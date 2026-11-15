"""Pin the WFIGS reference perimeter and derive its web and analysis-grid versions (DT-03).

The perimeter is the dated official reference used for contrast (WFIGS OBJECTID 58728,
2026-09-14 20:44 UTC). It predates the after scene and is not pixel-level ground truth.

This stage never downloads. It verifies the pinned raw GeoJSON against its sha256, checks
the feature identity and date, repairs invalid geometry only with ``make_valid`` (and says
so), and writes:

- ``perimeter.geojson``: EPSG:4326 full geometry with contract properties, for the web;
- ``perimeter_mask.tif``: uint8 COG on the DT-01 crop grid, 1 where the pixel centre is
  inside the polygon (``all_touched=False``), 0 otherwise;
- ``perimeter_edge.tif``: uint8 COG, 1 where the pixel centre lies within
  ``edge_distance_m`` of the boundary (for the ``near_perimeter_edge`` caveat);
- ``perimeter.json``: the ``reference`` block for ``case.json``, areas and checksums.

Run from the repository root::

    uv run python -m pipeline.perimeter --config pipeline/configs/perimeter_plaskett.toml
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import shapely
from affine import Affine
from pyogrio.errors import DataLayerError, DataSourceError
from rasterio.features import rasterize
from shapely.geometry import LineString, MultiPolygon, Polygon, mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.validation import explain_validity, make_valid

from pipeline import publishing
from pipeline.publishing import PublishError
from pipeline.sar import (
    ANALYSIS_CRS,
    ANALYSIS_PIXEL_SIZE_M,
    SarError,
    _staging_dirs,
    clear_staging,
    discard_staging,
    overlapping_input,
    publish,
    sha256_file,
    write_cog,
)

PERIMETER_FORMAT_VERSION = 1
SUPPORTED_INGEST_FORMAT_VERSION = 1
ACRE_M2 = 4046.8564224
PIXEL_AREA_M2 = ANALYSIS_PIXEL_SIZE_M * ANALYSIS_PIXEL_SIZE_M
OUTPUT_FILES: frozenset[str] = frozenset(
    {"perimeter.geojson", "perimeter_mask.tif", "perimeter_edge.tif", "perimeter.json"}
)
# Contract fixture property names -> raw WFIGS attribute names.
WEB_PROPERTIES: dict[str, str] = {
    "IncidentName": "poly_IncidentName",
    "FeatureCategory": "poly_FeatureCategory",
    "MapMethod": "poly_MapMethod",
    "GISAcres": "poly_GISAcres",
}
_VECTOR_IO_ERRORS = (DataSourceError, DataLayerError, OSError, ValueError)


class PerimeterError(Exception):
    """Raised for any condition that prevents a faithful reference perimeter."""


# --------------------------------------------------------------------------- config


@dataclass(frozen=True)
class PerimeterConfig:
    raw: Path
    sha256: str
    objectid: int
    polygon_datetime: str
    url: str
    source: str
    note: str
    ingest_dir: Path
    output_dir: Path
    edge_distance_m: float


def _require(table: Mapping[str, Any], key: str, kind: type) -> Any:
    if key not in table:
        raise PerimeterError(f"config: missing '{key}'")
    value = table[key]
    if kind is float and isinstance(value, int) and not isinstance(value, bool):
        value = float(value)
    if not isinstance(value, kind) or (isinstance(value, bool) and kind is not bool):
        raise PerimeterError(f"config: '{key}' must be {kind.__name__}, got {value!r}")
    return value


def load_config(path: Path, base_dir: Path | None = None) -> PerimeterConfig:
    """Parse the TOML configuration; relative paths resolve against ``base_dir`` (cwd)."""
    base = Path.cwd() if base_dir is None else base_dir
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise PerimeterError(f"config: cannot read {path.name}: {exc}") from exc

    def resolve(value: str) -> Path:
        p = Path(value)
        return p if p.is_absolute() else base / p

    sha = _require(raw, "sha256", str)
    if len(sha) != 64:
        raise PerimeterError("config: 'sha256' must be a 64-character hex digest")
    edge = _require(raw, "edge_distance_m", float)
    if not math.isfinite(edge) or edge <= 0:
        raise PerimeterError(f"config: 'edge_distance_m' must be > 0, got {edge}")
    return PerimeterConfig(
        raw=resolve(_require(raw, "raw", str)),
        sha256=sha.lower(),
        objectid=_require(raw, "objectid", int),
        polygon_datetime=_require(raw, "polygon_datetime", str),
        url=_require(raw, "url", str),
        source=_require(raw, "source", str),
        note=_require(raw, "note", str),
        ingest_dir=resolve(_require(raw, "ingest_dir", str)),
        output_dir=resolve(_require(raw, "output_dir", str)),
        edge_distance_m=edge,
    )


# --------------------------------------------------------------------------- inputs


def epoch_ms_to_iso(value: Any) -> str:
    """Whole-second UTC ISO string; fractional seconds are rejected, never truncated."""
    if (
        not isinstance(value, int | float)
        or isinstance(value, bool)
        or not math.isfinite(value)
        or value != int(value)
    ):
        raise PerimeterError(f"PolygonDateTime must be integer epoch milliseconds, got {value!r}")
    if int(value) % 1000:
        raise PerimeterError(
            f"PolygonDateTime {int(value)} ms has fractional seconds; pin the exact instant"
        )
    moment = datetime.fromtimestamp(int(value) // 1000, tz=UTC)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class Reference:
    properties: dict[str, Any]
    geometry_4326: BaseGeometry
    raw_geometry: dict[str, Any]
    repaired: bool
    validity: str


def read_reference(config: PerimeterConfig) -> Reference:
    """Verify the pinned raw file and return the single selected feature."""
    if not config.raw.is_file():
        raise PerimeterError(f"raw perimeter not found: {config.raw.name}")
    try:
        actual = sha256_file(config.raw)
    except SarError as exc:
        raise PerimeterError(str(exc)) from exc
    if actual != config.sha256:
        raise PerimeterError(
            f"{config.raw.name}: sha256 {actual[:12]}... differs from the pinned "
            f"{config.sha256[:12]}...; the reference changed, review it before updating the pin"
        )
    try:
        doc = json.loads(config.raw.read_text(encoding="utf-8"))
        gdf = gpd.read_file(config.raw)
    except (json.JSONDecodeError, *_VECTOR_IO_ERRORS) as exc:
        raise PerimeterError(f"{config.raw.name}: cannot read perimeter: {exc}") from exc
    if gdf.crs is None or gdf.crs.to_epsg() != 4326:
        raise PerimeterError(f"{config.raw.name}: expected EPSG:4326, got {gdf.crs}")
    features = [
        f
        for f in doc.get("features", [])
        if (f.get("properties") or {}).get("OBJECTID") == config.objectid
    ]
    if len(features) != 1 or len(doc.get("features", [])) != 1:
        raise PerimeterError(
            f"{config.raw.name}: expected exactly one feature with OBJECTID={config.objectid}, "
            f"found {len(features)} of {len(doc.get('features', []))}"
        )
    feature = features[0]
    props = feature["properties"]
    when = epoch_ms_to_iso(props.get("poly_PolygonDateTime"))
    if when != config.polygon_datetime:
        raise PerimeterError(
            f"{config.raw.name}: PolygonDateTime {when} differs from the pinned "
            f"{config.polygon_datetime}"
        )
    raw_geometry = feature.get("geometry") or {}
    if raw_geometry.get("type") not in ("Polygon", "MultiPolygon"):
        raise PerimeterError(f"{config.raw.name}: geometry must be (Multi)Polygon")
    geometry = shape(raw_geometry)
    repaired = not geometry.is_valid
    validity = explain_validity(geometry)
    if repaired:
        geometry = _polygonal(make_valid(geometry))
    if geometry.is_empty:
        raise PerimeterError(f"{config.raw.name}: perimeter geometry is empty")
    return Reference(props, geometry, raw_geometry, repaired, validity)


def _polygonal(geometry: BaseGeometry) -> BaseGeometry:
    """Keep only the polygonal parts that make_valid may return in a collection."""
    if isinstance(geometry, Polygon | MultiPolygon):
        return geometry
    parts = [g for g in getattr(geometry, "geoms", []) if isinstance(g, Polygon | MultiPolygon)]
    polygons = [p for g in parts for p in (g.geoms if isinstance(g, MultiPolygon) else [g])]
    return MultiPolygon(polygons)


def load_crop_grid(ingest_dir: Path) -> tuple[Affine, int, int]:
    """Crop grid recorded by DT-01, checked to be the north-up 10 m analysis grid."""
    path = ingest_dir / "ingest.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        if doc["ingest_format_version"] != SUPPORTED_INGEST_FORMAT_VERSION:
            raise PerimeterError(f"unsupported ingest_format_version in {path.name}")
        crop = doc["grid"]["crop"]
        transform = Affine(*[float(v) for v in crop["transform"]])
        width, height = int(crop["width"]), int(crop["height"])
        crs = doc["grid"]["crs"]
    except PerimeterError:
        raise
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise PerimeterError(f"cannot read the crop grid from {path.name}: {exc}") from exc
    if crs != "EPSG:32610":
        raise PerimeterError(f"{path.name}: grid CRS {crs} is not EPSG:32610")
    if (transform.a, transform.b, transform.d, transform.e) != (
        ANALYSIS_PIXEL_SIZE_M,
        0.0,
        0.0,
        -ANALYSIS_PIXEL_SIZE_M,
    ) or min(width, height) <= 0:
        raise PerimeterError(f"{path.name}: crop is not a north-up 10 m grid")
    return transform, width, height


# --------------------------------------------------------------------------- products


def web_feature_collection(ref: Reference, config: PerimeterConfig) -> dict[str, Any]:
    props = {name: ref.properties.get(raw_name) for name, raw_name in WEB_PROPERTIES.items()}
    props.update(
        {
            "OBJECTID": config.objectid,
            "PolygonDateTime": config.polygon_datetime,
            "Source": config.source,
        }
    )
    geometry = mapping(ref.geometry_4326) if ref.repaired else ref.raw_geometry
    return {
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "properties": props, "geometry": geometry}],
    }


def rasterize_centres(geometry: BaseGeometry, transform: Affine, width: int, height: int):
    """uint8 mask, 1 where the pixel centre is inside ``geometry`` (all_touched=False)."""
    if geometry.is_empty:
        return np.zeros((height, width), dtype=np.uint8)
    return rasterize(
        [(geometry, 1)],
        out_shape=(height, width),
        transform=transform,
        fill=0,
        all_touched=False,
        dtype="uint8",
    )


def boundary_segments(geometry: BaseGeometry) -> list[LineString]:
    """Every exterior and hole segment of a (Multi)Polygon."""
    polygons = list(geometry.geoms) if isinstance(geometry, MultiPolygon) else [geometry]
    rings = [r for p in polygons for r in (p.exterior, *p.interiors)]
    return [
        LineString([a, b])
        for ring in rings
        for a, b in zip(ring.coords[:-1], ring.coords[1:], strict=True)
        if a != b
    ]


def edge_band(
    geometry: BaseGeometry, distance_m: float, transform: Affine, width: int, height: int
) -> np.ndarray:
    """uint8 mask, 1 where the exact centre-to-boundary distance is <= ``distance_m``.

    A slightly wider buffer only selects candidates; the decision uses the exact Euclidean
    distance from each pixel centre to the nearest exterior or hole segment.
    """
    candidates = rasterize_centres(
        geometry.boundary.buffer(distance_m + ANALYSIS_PIXEL_SIZE_M), transform, width, height
    )
    rows, cols = np.nonzero(candidates)
    band = np.zeros((height, width), dtype=np.uint8)
    if rows.size == 0:
        return band
    xs, ys = transform * (cols + 0.5, rows + 0.5)
    tree = shapely.STRtree(boundary_segments(geometry))
    _, distances = tree.query_nearest(
        shapely.points(np.asarray(xs), np.asarray(ys)), return_distance=True, all_matches=False
    )
    band[rows, cols] = (distances <= distance_m).astype(np.uint8)
    return band


def _count_rings(geometry: BaseGeometry) -> tuple[int, int, int]:
    polygons = list(geometry.geoms) if isinstance(geometry, MultiPolygon) else [geometry]
    holes = sum(len(p.interiors) for p in polygons)
    vertices = sum(
        len(p.exterior.coords) + sum(len(r.coords) for r in p.interiors) for p in polygons
    )
    return len(polygons), holes, vertices


def _write_json(path: Path, document: Mapping[str, Any]) -> None:
    text = json.dumps(document, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False)
    path.write_text(text + "\n", encoding="utf-8", newline="\n")


def _overlaps(output_dir: Path, inputs: Sequence[Path]) -> bool:
    """True if publishing to ``output_dir`` could move or delete one of ``inputs``."""
    try:
        return overlapping_input(output_dir, inputs) is not None
    except SarError as exc:
        raise PerimeterError(str(exc)) from exc


def check_output_dir(output_dir: Path) -> None:
    """Only missing or fully owned output, staging and backup directories may be replaced."""
    try:
        publishing.check_output_dir(output_dir, OUTPUT_FILES)
    except PublishError as exc:
        raise PerimeterError(str(exc)) from exc


# --------------------------------------------------------------------------- run


def run_perimeter(config: PerimeterConfig) -> dict[str, Any]:
    """Build the perimeter products and return the ``perimeter.json`` document written."""
    if _overlaps(config.output_dir, (config.ingest_dir, config.raw)):
        raise PerimeterError("output_dir must differ from the raw and ingest directories")
    check_output_dir(config.output_dir)
    ref = read_reference(config)
    transform, width, height = load_crop_grid(config.ingest_dir)

    projected = gpd.GeoSeries([ref.geometry_4326], crs="EPSG:4326").to_crs(ANALYSIS_CRS)
    geom_utm = projected.iloc[0]
    mask = rasterize_centres(geom_utm, transform, width, height)
    inside = int(mask.sum())
    if inside == 0:
        raise PerimeterError("the perimeter covers no pixel centre of the DT-01 crop")
    edge = edge_band(geom_utm, config.edge_distance_m, transform, width, height)
    polygons, holes, vertices = _count_rings(ref.geometry_4326)
    gis_acres = ref.properties.get("poly_GISAcres")

    staging, _ = _staging_dirs(config.output_dir)
    try:
        clear_staging(staging, OUTPUT_FILES)
        staging.mkdir(parents=True)
        _write_json(staging / "perimeter.geojson", web_feature_collection(ref, config))
        write_cog(
            staging / "perimeter_mask.tif",
            mask,
            crs=ANALYSIS_CRS,
            transform=transform,
            nodata=None,
        )
        write_cog(
            staging / "perimeter_edge.tif",
            edge,
            crs=ANALYSIS_CRS,
            transform=transform,
            nodata=None,
        )
        document: dict[str, Any] = {
            "perimeter_format_version": PERIMETER_FORMAT_VERSION,
            "reference": {
                "source": config.source,
                "objectid": config.objectid,
                "datetime": config.polygon_datetime,
                "url": config.url,
                "note": config.note,
            },
            "raw": {"file": config.raw.name, "sha256": config.sha256},
            "geometry": {
                "type": ref.geometry_4326.geom_type,
                "polygon_count": polygons,
                "hole_count": holes,
                "vertex_count": vertices,
                "repaired": ref.repaired,
                "validity": ref.validity,
            },
            "area": {
                "vector_ha": round(float(geom_utm.area) / 10_000, 4),
                "raster_inside_ha": inside * PIXEL_AREA_M2 / 10_000,
                "wfigs_gisacres": gis_acres,
                "wfigs_ha": round(gis_acres * ACRE_M2 / 10_000, 4)
                if isinstance(gis_acres, int | float)
                else None,
            },
            "rasterization": {
                "rule": "pixel_centre",
                "all_touched": False,
                "edge_distance_m": config.edge_distance_m,
                "edge_rule": (
                    "exact distance from pixel centre to nearest exterior or hole segment "
                    "<= edge_distance_m"
                ),
            },
            "grid": {
                "crs": ANALYSIS_CRS.to_string(),
                "transform": [float(v) for v in tuple(transform)[:6]],
                "width": width,
                "height": height,
            },
            "inside_pixels": inside,
            "edge_pixels": int(edge.sum()),
            "outputs": {
                name: {"file": name, "sha256": sha256_file(staging / name)}
                for name in ("perimeter.geojson", "perimeter_mask.tif", "perimeter_edge.tif")
            },
        }
        _write_json(staging / "perimeter.json", document)
        publish(staging, config.output_dir, OUTPUT_FILES, "perimeter")
    except SarError as exc:
        raise PerimeterError(str(exc)) from exc
    except OSError as exc:
        raise PerimeterError(f"cannot write outputs: {exc}") from exc
    finally:
        discard_staging(staging, OUTPUT_FILES)
    return document


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m pipeline.perimeter",
        description="Pin the WFIGS reference perimeter and build its web and grid versions.",
    )
    parser.add_argument("--config", type=Path, required=True, help="TOML perimeter config")
    args = parser.parse_args(argv)
    try:
        doc = run_perimeter(load_config(args.config))
    except PerimeterError as exc:
        print(f"perimeter error: {exc}", file=sys.stderr)
        return 2
    a = doc["area"]
    print(
        f"perimeter ok: {doc['geometry']['polygon_count']} polygon(s), "
        f"{doc['inside_pixels']} inside pixels ({a['raster_inside_ha']} ha raster, "
        f"{a['vector_ha']} ha vector, {a['wfigs_ha']} ha WFIGS), "
        f"{doc['edge_pixels']} edge pixels"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
