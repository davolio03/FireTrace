"""Ranked zones to review: where radar change and the reference perimeter agree or differ (XP-04).

Turns the XP-01 highlight mask and a "little change" mask into a short, ranked list of
connected regions (``review_zones.geojson``, contract ``review-zones.schema.json``), so the
analyst knows where to look first:

- ``CO`` change_outside_perimeter: highlighted radar change outside the perimeter;
- ``NI`` no_change_inside_perimeter: little radar change inside the perimeter;
- ``CI`` change_inside_perimeter: highlighted change inside (agreement examples).

``CO`` and ``NI`` are discrepancies **to investigate**, never radar or perimeter errors, and no
kind means burned or unburned. The rules were fixed a priori with David on 2026-11-15 and are
never tuned on the data (``docs/methods/review-zones.md``):

- CO/CI come straight from ``highlight_mask.tif == 1`` (same threshold, smoothing and 1 ha
  region filter as XP-01, by construction), split by the DT-03 pixel-centre perimeter mask.
- NI is ``smoothed index <= no_change_threshold`` (0.0) inside the perimeter, with the XP-01
  valid-only smoothing and the window recorded in ``highlight_meta.json``.
- Regions are connected with the XP-01 connectivity (8); regions under ``min_area_ha`` (5 ha)
  are dropped and at most ``max_zones_per_kind`` (10) are published per kind. An empty kind
  is a valid result.
- Ranking within a kind: area descending, then the index median (descending for CO/CI,
  ascending for NI), then the first pixel in raster order.
- Geometry: the exact pixel footprint in EPSG:32610, simplified by ``simplify_tolerance_m``
  (5 m, topology preserved, holes kept), then EPSG:4326 at 1e-6 degrees. Area is the pixel
  count times 100 m2, never measured on the polygon.
- Statistics over the zone's valid pixels: DT-02 dB before/after, CH-01 HH/HV change and the
  **unsmoothed** index (median and p90). ``valid_fraction`` is over the zone with its holes
  filled. ``distance_to_perimeter_m`` is the UTM distance from the pixel footprint to the
  perimeter boundary (0 when touching), in whole metres.
- Caveats, always listed: ``steep_slope`` (DT-05 slope > 30 deg), ``radar_shadow_layover``
  (DT-05 codes 1 or 2) and ``near_perimeter_edge`` (DT-03 50 m band). Unknown values never
  fire. The rules mirror ``api/caveats.py`` (EV-02) without importing it.

Outputs in ``output_dir``: ``review_zones.geojson`` and ``review_zones_meta.json`` (input
hashes, parameters, per-kind counts and output checksums). DT-04 merges the GeoJSON into the
web bundle only when this manifest exists and matches the bundle's inputs.

Run from the repository root::

    uv run python -m pipeline.review_zones --config pipeline/configs/review_zones_plaskett.toml
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import shapely
from affine import Affine
from rasterio.crs import CRS
from rasterio.features import shapes
from rasterio.warp import transform as warp_transform
from shapely.geometry import LineString, MultiLineString, MultiPolygon, Polygon, shape
from shapely.geometry.base import BaseGeometry
from shapely.validation import make_valid
from skimage.measure import label

from pipeline import highlight, publishing, stats
from pipeline.highlight import CONNECTIVITY, HighlightConfig, HighlightError, HighlightParams
from pipeline.publishing import PublishError, input_file, read_verified
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
)
from pipeline.stats import StatsError

REVIEW_ZONES_FORMAT_VERSION = 1
CONTRACT_VERSION = "1.2.0"
PIXEL_AREA_M2 = ANALYSIS_PIXEL_SIZE_M * ANALYSIS_PIXEL_SIZE_M
KINDS: tuple[tuple[str, str], ...] = (
    ("change_outside_perimeter", "CO"),
    ("no_change_inside_perimeter", "NI"),
    ("change_inside_perimeter", "CI"),
)
SLOPE_THRESHOLD_DEG = 30.0  # docs/methods/caveats.md (EV-02)
LAYOVER, SHADOW, GEOMETRY_UNKNOWN = 1, 2, 255
CAVEAT_LABELS: dict[str, str] = {  # same labels as api/caveats.py
    "steep_slope": "Steep slope",
    "radar_shadow_layover": "Radar layover or shadow",
    "near_perimeter_edge": "Near the reference perimeter edge",
}
LONLAT_DECIMALS = 6
WGS84 = CRS.from_epsg(4326)
CONFIG_KEYS = frozenset(
    {
        "no_change_threshold",
        "min_area_ha",
        "max_zones_per_kind",
        "simplify_tolerance_m",
        "change_dir",
        "sar_dir",
        "perimeter_dir",
        "terrain_dir",
        "highlight_dir",
        "output_dir",
    }
)
OUTPUT_FILES: frozenset[str] = frozenset({"review_zones.geojson", "review_zones_meta.json"})


class ReviewZonesError(Exception):
    """Raised for any input or numerical condition that prevents faithful zones."""


@dataclass(frozen=True)
class ZoneParams:
    no_change_threshold: float
    min_area_ha: float
    max_zones_per_kind: int
    simplify_tolerance_m: float

    @property
    def min_region_px(self) -> int:
        """Smallest whole number of 100 m2 pixels whose area reaches ``min_area_ha``."""
        return max(1, math.ceil(self.min_area_ha * 10_000 / PIXEL_AREA_M2 - 1e-9))


@dataclass(frozen=True)
class ReviewZonesConfig:
    params: ZoneParams
    change_dir: Path
    sar_dir: Path
    perimeter_dir: Path
    terrain_dir: Path
    highlight_dir: Path
    output_dir: Path


@dataclass(frozen=True)
class Region:
    """Pixels of one connected region, in raster order (row, then column)."""

    rows: np.ndarray
    cols: np.ndarray

    @property
    def size(self) -> int:
        return int(self.rows.size)

    @property
    def first(self) -> tuple[int, int]:
        return int(self.rows[0]), int(self.cols[0])


# --------------------------------------------------------------------------- core rules


def kind_masks(
    highlighted: np.ndarray,
    smoothed: np.ndarray,
    inside: np.ndarray,
    valid: np.ndarray,
    no_change_threshold: float,
) -> dict[str, np.ndarray]:
    """Candidate pixels of each kind; invalid pixels never belong to any kind."""
    valid = valid.astype(bool)
    inside = inside.astype(bool)
    change = highlighted.astype(bool) & valid
    with np.errstate(invalid="ignore"):
        little = valid & np.isfinite(smoothed) & (smoothed <= no_change_threshold)
    return {
        "change_outside_perimeter": change & ~inside,
        "no_change_inside_perimeter": little & inside,
        "change_inside_perimeter": change & inside,
    }


def find_regions(mask: np.ndarray, min_px: int, connectivity: int) -> list[Region]:
    """Connected regions of at least ``min_px`` pixels (raster order within each region)."""
    if connectivity not in CONNECTIVITY:
        raise ReviewZonesError(f"connectivity must be 4 or 8, got {connectivity}")
    labels = label(mask.astype(bool), connectivity=CONNECTIVITY[connectivity])
    sizes = np.bincount(labels.ravel())
    sizes[0] = 0
    keep = np.flatnonzero(sizes >= min_px)
    if keep.size == 0:
        return []
    rows, cols = np.nonzero(np.isin(labels, keep))  # raster order
    owners = labels[rows, cols]
    order = np.argsort(owners, kind="stable")  # stable: raster order kept per region
    rows, cols, owners = rows[order], cols[order], owners[order]
    bounds = np.flatnonzero(np.diff(owners)) + 1
    return [
        Region(r, c) for r, c in zip(np.split(rows, bounds), np.split(cols, bounds), strict=True)
    ]


def _index_median(region: Region, index: np.ndarray) -> float:
    return float(np.median(index[region.rows, region.cols].astype(np.float64)))


def rank_regions(regions: Sequence[Region], index: np.ndarray, kind: str) -> list[Region]:
    """Area descending; then index median (desc for change kinds, asc for NI); then position."""
    sign = 1.0 if kind == "no_change_inside_perimeter" else -1.0
    return sorted(
        regions,
        key=lambda r: (-r.size, sign * _index_median(r, index), r.first),
    )


def _window(region: Region) -> tuple[int, int, np.ndarray]:
    """Top-left offset and the region's boolean mask inside its bounding window."""
    r0, c0 = int(region.rows.min()), int(region.cols.min())
    sub = np.zeros((int(region.rows.max()) - r0 + 1, int(region.cols.max()) - c0 + 1), dtype=bool)
    sub[region.rows - r0, region.cols - c0] = True
    return r0, c0, sub


def _polygonal(geometry: BaseGeometry) -> BaseGeometry:
    if isinstance(geometry, Polygon | MultiPolygon):
        return geometry
    parts = [g for g in getattr(geometry, "geoms", []) if isinstance(g, Polygon | MultiPolygon)]
    return shapely.union_all(parts) if parts else Polygon()


def region_geometry(region: Region, transform: Affine) -> BaseGeometry:
    """Exact pixel footprint of the region in the raster CRS (valid, holes kept)."""
    r0, c0, sub = _window(region)
    window_transform = transform @ Affine.translation(c0, r0)
    polygons = [
        shape(geom)
        for geom, value in shapes(
            sub.astype(np.uint8), mask=sub, connectivity=8, transform=window_transform
        )
        if value == 1
    ]
    geometry = shapely.union_all(polygons)
    if not geometry.is_valid:
        geometry = make_valid(geometry)
    return _polygonal(geometry)


def filled_valid_fraction(region: Region, valid: np.ndarray) -> float:
    """Share of valid pixels over the region with its enclosed holes filled."""
    r0, c0, sub = _window(region)
    padded = np.pad(sub, 1)
    background = label(~padded, connectivity=1)
    outside = np.unique(
        np.concatenate([background[0], background[-1], background[:, 0], background[:, -1]])
    )
    filled = (padded | ~np.isin(background, outside))[1:-1, 1:-1]
    rows, cols = np.nonzero(filled)
    return float(valid[rows + r0, cols + c0].astype(bool).mean())


def caveat_fractions(
    region: Region, slope: np.ndarray, flags: np.ndarray, edge: np.ndarray
) -> list[dict[str, Any]]:
    """Share of the region's pixels where each EV-02 rule fires (unknown never fires)."""
    r, c = region.rows, region.cols
    with np.errstate(invalid="ignore"):
        steep = np.isfinite(slope[r, c]) & (slope[r, c] > SLOPE_THRESHOLD_DEG)
    geometry = np.isin(flags[r, c], (LAYOVER, SHADOW))
    near = edge[r, c].astype(bool)
    return [
        {"id": cid, "label": CAVEAT_LABELS[cid], "fraction": round(float(fired.mean()), 4)}
        for cid, fired in (
            ("steep_slope", steep),
            ("radar_shadow_layover", geometry),
            ("near_perimeter_edge", near),
        )
    ]


def perimeter_distance_m(geometry: BaseGeometry, boundary: BaseGeometry) -> float:
    """Whole metres from the zone footprint to the perimeter boundary; 0 when touching."""
    if geometry.intersects(boundary):
        return 0.0
    return float(round(geometry.distance(boundary)))


def _round(value: float, decimals: int = 3) -> float:
    rounded = round(float(value), decimals)
    return 0.0 if rounded == 0 else rounded  # no "-0.0" in the output


def _to_lonlat(geometry: BaseGeometry) -> BaseGeometry:
    projected = reproject(geometry, ANALYSIS_CRS, WGS84)
    snapped = shapely.set_precision(projected, 10.0**-LONLAT_DECIMALS)
    snapped = _polygonal(snapped)
    if snapped.is_empty or not snapped.is_valid:
        raise ReviewZonesError("a zone geometry collapsed when snapped to 1e-6 degrees")
    return snapped


def _coords(geometry: BaseGeometry) -> dict[str, Any]:
    """GeoJSON geometry with coordinates rounded to the snapping precision."""

    def ring(coords: Any) -> list[list[float]]:
        return [[round(x, LONLAT_DECIMALS), round(y, LONLAT_DECIMALS)] for x, y in coords]

    def polygon(p: Polygon) -> list[list[list[float]]]:
        p = shapely.geometry.polygon.orient(p, sign=1.0)  # RFC 7946: exterior CCW
        return [ring(p.exterior.coords), *(ring(i.coords) for i in p.interiors)]

    if isinstance(geometry, Polygon):
        return {"type": "Polygon", "coordinates": polygon(geometry)}
    parts = sorted(geometry.geoms, key=lambda p: (p.bounds[0], p.bounds[1]))
    return {"type": "MultiPolygon", "coordinates": [polygon(p) for p in parts]}


# --------------------------------------------------------------------------- config


def load_config(path: Path, base_dir: Path | None = None) -> ReviewZonesConfig:
    """Parse the TOML configuration; relative paths resolve against ``base_dir`` (cwd)."""
    base = Path.cwd() if base_dir is None else base_dir
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ReviewZonesError(f"config: cannot read {path.name}: {exc}") from exc
    unknown = sorted(set(raw) - CONFIG_KEYS)
    if unknown:
        raise ReviewZonesError(f"config: unknown key(s) {unknown}")

    def number(key: str, *, positive: bool = False, non_negative: bool = False) -> float:
        value = raw.get(key)
        if (
            not isinstance(value, int | float)
            or isinstance(value, bool)
            or not math.isfinite(value)
        ):
            raise ReviewZonesError(f"config: '{key}' must be a finite number, got {value!r}")
        if positive and value <= 0:
            raise ReviewZonesError(f"config: '{key}' must be positive, got {value!r}")
        if non_negative and value < 0:
            raise ReviewZonesError(f"config: '{key}' must not be negative, got {value!r}")
        return float(value)

    max_zones = raw.get("max_zones_per_kind")
    if not isinstance(max_zones, int) or isinstance(max_zones, bool) or max_zones < 1:
        raise ReviewZonesError(
            f"config: 'max_zones_per_kind' must be an integer >= 1, got {max_zones!r}"
        )

    def resolve(key: str) -> Path:
        value = raw.get(key)
        if not isinstance(value, str) or not value:
            raise ReviewZonesError(f"config: '{key}' must be a non-empty string, got {value!r}")
        p = Path(value)
        return p if p.is_absolute() else base / p

    return ReviewZonesConfig(
        params=ZoneParams(
            no_change_threshold=number("no_change_threshold"),
            min_area_ha=number("min_area_ha", positive=True),
            max_zones_per_kind=max_zones,
            simplify_tolerance_m=number("simplify_tolerance_m", non_negative=True),
        ),
        change_dir=resolve("change_dir"),
        sar_dir=resolve("sar_dir"),
        perimeter_dir=resolve("perimeter_dir"),
        terrain_dir=resolve("terrain_dir"),
        highlight_dir=resolve("highlight_dir"),
        output_dir=resolve("output_dir"),
    )


# --------------------------------------------------------------------------- inputs


@dataclass(frozen=True)
class Inputs:
    base: highlight.Inputs
    highlighted: np.ndarray
    highlight_params: dict[str, Any]
    db: dict[str, np.ndarray]
    change: dict[str, np.ndarray]
    slope: np.ndarray
    flags: np.ndarray
    boundary: BaseGeometry
    shas: dict[str, str]


def _manifest(path: Path) -> tuple[dict[str, Any], str]:
    try:
        return highlight._manifest(path)
    except HighlightError as exc:
        raise ReviewZonesError(str(exc)) from exc


def _verified_bytes(directory: Path, record: tuple[str, str], manifest: str) -> bytes:
    try:
        return read_verified(input_file(directory, record[0], manifest), record[1], manifest)
    except PublishError as exc:
        raise ReviewZonesError(str(exc)) from exc


def reproject(geometry: BaseGeometry, src: CRS, dst: CRS) -> BaseGeometry:
    """Vertex-wise reprojection (rasterio/PROJ, x-y axis order)."""

    def move(xy: np.ndarray) -> np.ndarray:
        xs, ys = warp_transform(src, dst, xy[:, 0].tolist(), xy[:, 1].tolist())
        return np.column_stack([xs, ys])

    return shapely.transform(geometry, move)


def _boundary_utm(payload: bytes) -> BaseGeometry:
    """Boundary of the DT-03 perimeter (EPSG:4326 GeoJSON) in the analysis CRS."""
    try:
        doc = json.loads(payload.decode("utf-8"))
        geoms = [shape(f["geometry"]) for f in doc["features"]]
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise ReviewZonesError(f"perimeter.geojson: malformed ({exc})") from exc
    if not geoms:
        raise ReviewZonesError("perimeter.geojson: no feature")
    projected = reproject(shapely.union_all(geoms), WGS84, ANALYSIS_CRS)
    boundary = projected.boundary
    if boundary.is_empty or not isinstance(boundary, LineString | MultiLineString):
        raise ReviewZonesError("perimeter.geojson: polygon boundary is empty")
    return boundary


def check_highlight_params(params: Any) -> dict[str, Any]:
    """The XP-01 parameters this stage reuses, rejected (never coerced) when malformed."""
    source = "highlight_meta.json: parameters"
    if not isinstance(params, Mapping):
        raise ReviewZonesError(f"{source} must be an object")

    def integer(key: str) -> int:
        value = params.get(key)
        if not isinstance(value, int) or isinstance(value, bool):
            raise ReviewZonesError(f"{source}.{key} must be an integer, got {value!r}")
        return value

    threshold = params.get("threshold")
    if (
        not isinstance(threshold, int | float)
        or isinstance(threshold, bool)
        or not math.isfinite(threshold)
    ):
        raise ReviewZonesError(f"{source}.threshold must be a finite number, got {threshold!r}")
    window = integer("window")
    if window < 1 or window % 2 == 0:
        raise ReviewZonesError(f"{source}.window must be a positive odd integer, got {window}")
    connectivity = integer("connectivity")
    if connectivity not in CONNECTIVITY:
        raise ReviewZonesError(f"{source}.connectivity must be 4 or 8, got {connectivity}")
    min_region = integer("min_region_px")
    if min_region < 1:
        raise ReviewZonesError(f"{source}.min_region_px must be at least 1, got {min_region}")
    return {
        "threshold": float(threshold),
        "window": window,
        "connectivity": connectivity,
        "min_region_px": min_region,
    }


def load_inputs(config: ReviewZonesConfig) -> Inputs:
    """Read every product and check versions, the manifest chain, grids and checksums."""
    try:
        base = highlight.load_inputs(
            HighlightConfig(
                params=HighlightParams(0.0, 1, 1, 8),  # unused: only the directories are read
                change_dir=config.change_dir,
                sar_dir=config.sar_dir,
                perimeter_dir=config.perimeter_dir,
                output_dir=config.output_dir,
            )
        )
    except HighlightError as exc:
        raise ReviewZonesError(str(exc)) from exc
    grid = base.grid

    docs: dict[str, dict[str, Any]] = {}
    for directory, name in (
        (config.change_dir, "change.json"),
        (config.sar_dir, "sar.json"),
        (config.perimeter_dir, "perimeter.json"),
    ):
        doc, sha = _manifest(directory / name)
        if sha != base.shas[name]:
            raise ReviewZonesError(f"{name} changed while the inputs were read; re-run")
        docs[name] = doc

    hl_meta, hl_sha = _manifest(config.highlight_dir / "highlight_meta.json")
    terrain, terrain_sha = _manifest(config.terrain_dir / "terrain.json")
    try:
        if hl_meta.get("highlight_format_version") != highlight.HIGHLIGHT_FORMAT_VERSION:
            raise ReviewZonesError(
                "highlight_meta.json: unsupported highlight_format_version "
                f"{hl_meta.get('highlight_format_version')!r}"
            )
        if hl_meta.get("inputs") != base.shas:
            raise ReviewZonesError(
                "highlight_meta.json was built from other inputs (change/sar/perimeter "
                "sha256 differ); re-run XP-01 on these products"
            )
        hl_grid = stats._grid(hl_meta, "highlight_meta.json")
        if hl_grid != grid:
            raise ReviewZonesError("highlight_meta.json: grid differs from change.json")
        hl_params = check_highlight_params(stats._get(hl_meta, "parameters", "highlight_meta.json"))
        mask = stats._read(
            config.highlight_dir,
            stats._record(hl_meta, ("outputs", "highlight_mask.tif"), "highlight_meta.json"),
            grid,
            "uint8",
            "highlight_meta.json",
        )

        if terrain.get("terrain_format_version") != 1:
            raise ReviewZonesError(
                "terrain.json: unsupported terrain_format_version "
                f"{terrain.get('terrain_format_version')!r}"
            )
        if stats._grid(terrain, "terrain.json") != grid:
            raise ReviewZonesError("terrain.json: grid differs from change.json")
        sar_ingest = stats._get(docs["sar.json"], ("source_ingest", "sha256"), "sar.json")
        if stats._get(terrain, ("ingest", "sha256"), "terrain.json") != sar_ingest:
            raise ReviewZonesError(
                "terrain.json was built from another ingest.json than sar.json; re-run DT-05"
            )
        slope = stats._read(
            config.terrain_dir,
            stats._record(terrain, ("outputs", "slope.tif"), "terrain.json"),
            grid,
            "float32",
            "terrain.json",
        )
        flags = stats._read(
            config.terrain_dir,
            stats._record(terrain, ("outputs", "layover_shadow.tif"), "terrain.json"),
            grid,
            "uint8",
            "terrain.json",
        )

        db = {
            name: stats._read(
                config.sar_dir,
                stats._record(docs["sar.json"], ("db", "layers", name), "sar.json"),
                grid,
                "float32",
                "sar.json",
            )
            for name in ("t1_hh", "t2_hh", "t1_hv", "t2_hv")
        }
        change = {
            name: stats._read(
                config.change_dir,
                stats._record(docs["change.json"], ("outputs", name), "change.json"),
                grid,
                "float32",
                "change.json",
            )
            for name in ("change_hh_db", "change_hv_db")
        }
        geojson = _verified_bytes(
            config.perimeter_dir,
            stats._record(
                docs["perimeter.json"], ("outputs", "perimeter.geojson"), "perimeter.json"
            ),
            "perimeter.json",
        )
    except StatsError as exc:
        raise ReviewZonesError(str(exc)) from exc

    if not np.isin(mask, (0, 1, highlight.MASK_NODATA)).all():
        raise ReviewZonesError("highlight_mask.tif: values must be 0, 1 or 255")
    if not ((mask == highlight.MASK_NODATA) == ~base.valid).all():
        raise ReviewZonesError("highlight_mask.tif: must be 255 exactly where valid_mask is 0")
    if not np.isin(flags, (0, LAYOVER, SHADOW, GEOMETRY_UNKNOWN)).all():
        raise ReviewZonesError("layover_shadow.tif: codes must be 0, 1, 2 or 255")
    with np.errstate(invalid="ignore"):
        bad_slope = np.isfinite(slope) & ((slope < 0) | (slope > 90))
    if bad_slope.any():
        raise ReviewZonesError("slope.tif: values must lie in 0-90 degrees")
    for name, data in (*db.items(), *change.items()):
        if not np.isfinite(data[base.valid]).all():
            raise ReviewZonesError(f"{name}: non-finite values where valid_mask = 1")

    return Inputs(
        base=base,
        highlighted=mask == 1,
        highlight_params=dict(hl_params),
        db=db,
        change=change,
        slope=slope,
        flags=flags,
        boundary=_boundary_utm(geojson),
        shas={**base.shas, "highlight_meta.json": hl_sha, "terrain.json": terrain_sha},
    )


# --------------------------------------------------------------------------- run


def _median(values: np.ndarray) -> float:
    return _round(float(np.median(values.astype(np.float64))))


def _feature(
    kind: str,
    prefix: str,
    rank: int,
    region: Region,
    inputs: Inputs,
    params: ZoneParams,
    transform: Affine,
) -> dict[str, Any]:
    r, c = region.rows, region.cols
    footprint = region_geometry(region, transform)
    simplified = footprint
    if params.simplify_tolerance_m > 0:
        candidate = footprint.simplify(params.simplify_tolerance_m, preserve_topology=True)
        if not candidate.is_empty and candidate.is_valid:
            simplified = _polygonal(candidate)
    lonlat = _to_lonlat(simplified)
    # North-up grid (enforced upstream): pixel centres from the affine coefficients.
    xs = transform.c + (c + 0.5) * transform.a
    ys = transform.f + (r + 0.5) * transform.e
    (lon,), (lat,) = warp_transform(ANALYSIS_CRS, WGS84, [float(np.mean(xs))], [float(np.mean(ys))])
    index = inputs.base.index[r, c]
    db, ch = inputs.db, inputs.change
    zone_id = f"{prefix}-{rank:02d}"
    return {
        "type": "Feature",
        "id": zone_id,
        "geometry": _coords(lonlat),
        "properties": {
            "zone_id": zone_id,
            "kind": kind,
            "rank": rank,
            "area_ha": round(region.size * PIXEL_AREA_M2 / 10_000, 2),
            "centroid": [round(lon, LONLAT_DECIMALS), round(lat, LONLAT_DECIMALS)],
            "bbox": [round(v, LONLAT_DECIMALS) for v in lonlat.bounds],
            "valid_fraction": round(filled_valid_fraction(region, inputs.base.valid), 4),
            "hh_db": {
                "t1_median": _median(db["t1_hh"][r, c]),
                "t2_median": _median(db["t2_hh"][r, c]),
                "delta_median": _median(ch["change_hh_db"][r, c]),
            },
            "hv_db": {
                "t1_median": _median(db["t1_hv"][r, c]),
                "t2_median": _median(db["t2_hv"][r, c]),
                "delta_median": _median(ch["change_hv_db"][r, c]),
            },
            "change_index": {
                "median": _median(index),
                "p90": _round(float(np.percentile(index.astype(np.float64), 90))),
            },
            "distance_to_perimeter_m": perimeter_distance_m(footprint, inputs.boundary),
            "caveats": caveat_fractions(region, inputs.slope, inputs.flags, inputs.base.edge),
        },
    }


def smoothing_label(hl: Mapping[str, Any]) -> str:
    window = int(hl["window"])
    smooth = "none" if window == 1 else f"{window}x{window} mean over valid pixels"
    return (
        f"XP-01: {smooth}; {int(hl['connectivity'])}-connected highlight regions under "
        f"{int(hl['min_region_px'])} px removed. Zones: same smoothing for little change, "
        f"{int(hl['connectivity'])}-connected regions"
    )


def check_output_dir(output_dir: Path) -> None:
    try:
        publishing.check_output_dir(output_dir, OUTPUT_FILES)
    except PublishError as exc:
        raise ReviewZonesError(str(exc)) from exc


def build(config: ReviewZonesConfig, inputs: Inputs) -> tuple[dict[str, Any], dict[str, Any]]:
    """The GeoJSON document and the per-kind summary (no file is written)."""
    params, hl = config.params, inputs.highlight_params
    connectivity = int(hl["connectivity"])
    base = inputs.base
    smoothed = highlight.smooth_valid(base.index, base.valid, int(hl["window"]))
    masks = kind_masks(
        inputs.highlighted, smoothed, base.inside, base.valid, params.no_change_threshold
    )
    transform = Affine(*base.grid["transform"])
    reference_px = int((base.inside & base.valid).sum())
    features: list[dict[str, Any]] = []
    summary: dict[str, Any] = {}
    for kind, prefix in KINDS:
        regions = find_regions(masks[kind], params.min_region_px, connectivity)
        ranked = rank_regions(regions, base.index, kind)
        chosen = ranked[: params.max_zones_per_kind]
        for rank, region in enumerate(chosen, start=1):
            features.append(_feature(kind, prefix, rank, region, inputs, params, transform))
        largest = ranked[0].size if ranked else 0
        summary[kind] = {
            "mask_px": int(masks[kind].sum()),
            "mask_ha": _ha(int(masks[kind].sum())),
            "candidate_regions": len(ranked),
            "candidate_ha": _ha(sum(r.size for r in ranked)),
            "published": len(chosen),
            "published_ha": _ha(sum(r.size for r in chosen)),
            "largest_ha": _ha(largest),
            "largest_share_of_reference_pct": (
                round(100.0 * largest / reference_px, 3) if reference_px else None
            ),
        }
    document = {
        "type": "FeatureCollection",
        "contract_version": CONTRACT_VERSION,
        "data_status": "real",
        "method": {
            "change_threshold": float(hl["threshold"]),
            "no_change_threshold": params.no_change_threshold,
            "smoothing": smoothing_label(hl),
            "min_area_ha": params.min_area_ha,
            "max_zones_per_kind": params.max_zones_per_kind,
        },
        "features": features,
    }
    return document, summary


def _ha(pixels: int) -> float:
    return round(pixels * PIXEL_AREA_M2 / 10_000, 2)


def run_review_zones(config: ReviewZonesConfig) -> dict[str, Any]:
    """Build and publish the zones; return the ``review_zones_meta.json`` document."""
    input_dirs = (
        config.change_dir,
        config.sar_dir,
        config.perimeter_dir,
        config.terrain_dir,
        config.highlight_dir,
    )
    try:
        clash = overlapping_input(config.output_dir, input_dirs)
    except SarError as exc:
        raise ReviewZonesError(str(exc)) from exc
    if clash is not None:
        raise ReviewZonesError("output_dir must differ from the input directories")
    check_output_dir(config.output_dir)
    inputs = load_inputs(config)
    document, summary = build(config, inputs)
    params = config.params
    meta: dict[str, Any] = {
        "review_zones_format_version": REVIEW_ZONES_FORMAT_VERSION,
        "inputs": inputs.shas,
        "grid": {"crs": ANALYSIS_CRS.to_string(), **inputs.base.grid},
        "parameters": {
            "change_threshold": float(inputs.highlight_params["threshold"]),
            "smoothing_window": int(inputs.highlight_params["window"]),
            "connectivity": int(inputs.highlight_params["connectivity"]),
            "no_change_threshold": params.no_change_threshold,
            "min_area_ha": params.min_area_ha,
            "min_region_px": params.min_region_px,
            "max_zones_per_kind": params.max_zones_per_kind,
            "simplify_tolerance_m": params.simplify_tolerance_m,
            "slope_threshold_deg": SLOPE_THRESHOLD_DEG,
            "edge_band_m": 50.0,
        },
        "rules": {
            "CO": "highlight_mask == 1 and pixel centre outside the DT-03 perimeter mask",
            "NI": "valid, inside the perimeter mask and smoothed index <= no_change_threshold",
            "CI": "highlight_mask == 1 and pixel centre inside the perimeter mask",
            "ranking": "area desc; index median desc (CO, CI) or asc (NI); first pixel",
            "statistics": "medians over the zone's valid pixels; index unsmoothed",
            "area": "pixel count x 100 m2, not the simplified polygon",
            "distance": "UTM distance from the pixel footprint to the perimeter boundary, "
            "0 when touching, whole metres",
            "caveats": "share of the zone's pixels where the EV-02 rule fires; unknown never fires",
        },
        "kinds": summary,
        "interpretation": "Zones describe observed radar change versus the WFIGS perimeter "
        "dated 2026-09-14, not burned or unburned ground. Discrepancies are prompts to "
        "investigate, not errors of the radar or the perimeter.",
    }

    staging, _ = _staging_dirs(config.output_dir)
    try:
        clear_staging(staging, OUTPUT_FILES)
        staging.mkdir(parents=True)
        _write_json(staging / "review_zones.geojson", document, compact=True)
        meta["outputs"] = {
            "review_zones.geojson": {
                "file": "review_zones.geojson",
                "sha256": sha256_file(staging / "review_zones.geojson"),
            }
        }
        _write_json(staging / "review_zones_meta.json", meta)
        publish(staging, config.output_dir, OUTPUT_FILES, "review zones")
    except SarError as exc:
        raise ReviewZonesError(str(exc)) from exc
    except OSError as exc:
        raise ReviewZonesError(f"cannot write outputs: {exc}") from exc
    finally:
        discard_staging(staging, OUTPUT_FILES)
    return meta


def _write_json(path: Path, document: Mapping[str, Any], *, compact: bool = False) -> None:
    """Deterministic JSON; the GeoJSON is compact because the web downloads it."""
    layout: dict[str, Any] = {"separators": (",", ":")} if compact else {"indent": 2}
    text = json.dumps(document, sort_keys=True, ensure_ascii=True, allow_nan=False, **layout)
    path.write_text(text + "\n", encoding="utf-8", newline="\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m pipeline.review_zones",
        description="Ranked zones where radar change and the reference perimeter agree or differ.",
    )
    parser.add_argument(
        "--config", type=Path, default=Path("pipeline/configs/review_zones_plaskett.toml")
    )
    args = parser.parse_args(argv)
    try:
        meta = run_review_zones(load_config(args.config))
    except ReviewZonesError as exc:
        print(f"review zones error: {exc}", file=sys.stderr)
        return 2
    counts = ", ".join(
        f"{prefix} {meta['kinds'][kind]['published']}/{meta['kinds'][kind]['candidate_regions']}"
        for kind, prefix in KINDS
    )
    print(f"review zones ok (published/candidates): {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
