"""Ingest and crop the four NISAR GCOV power rasters (HH/HV x t1/t2) to the case AOI.

Scope (DT-01): read the four local GCOV covariance-term GeoTIFFs, verify that they share
one grid, derive the AOI from the reference perimeter bounding box plus a metric margin in
the analysis CRS, and write integer-pixel crops of the native grid without resampling.
Values and the source no-data value are copied unchanged: no dB conversion, no validity
mask (DT-02). ``case.json`` is not produced here (DT-04 assembles it).

Run from the repository root::

    uv run python -m pipeline.ingest --config pipeline/configs/ingest_plaskett.toml

Relative paths in the configuration resolve against the current working directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import geopandas as gpd
import rasterio
from affine import Affine
from pyogrio.errors import DataLayerError, DataSourceError
from rasterio.crs import CRS
from rasterio.errors import CRSError, RasterioError
from rasterio.warp import transform_bounds
from rasterio.windows import Window

INGEST_FORMAT_VERSION = 1
EPOCHS: tuple[str, ...] = ("t1", "t2")
POLARIZATIONS: tuple[str, ...] = ("HH", "HV")
WGS84 = CRS.from_epsg(4326)
# Fixed scientific analysis grid (AGENTS.md): configuration may restate it, never change it.
ANALYSIS_CRS = CRS.from_epsg(32610)
ANALYSIS_PIXEL_SIZE_M = 10.0
# Expected I/O failures from corrupt or unreadable raster/vector files.
_RASTER_IO_ERRORS = (RasterioError, OSError)
_VECTOR_IO_ERRORS = (DataSourceError, DataLayerError, OSError, ValueError)
# Deterministic output encoding: lossless, tiled, no timestamps.
OUTPUT_CREATION_OPTIONS: dict[str, Any] = {
    "driver": "GTiff",
    "tiled": True,
    "blockxsize": 256,
    "blockysize": 256,
    "compress": "deflate",
    "predictor": 3,
}
BOUNDS_DENSIFY_POINTS = 21
WGS84_DECIMALS = 8

Bounds = tuple[float, float, float, float]  # (min_x, min_y, max_x, max_y)


class IngestError(Exception):
    """Raised for any input, grid or AOI condition that prevents a faithful crop."""


# --------------------------------------------------------------------------- config


@dataclass(frozen=True)
class EpochConfig:
    label: str
    datetime: str
    granule_id: str
    absolute_orbit: int
    hh: Path
    hv: Path

    def path(self, polarization: str) -> Path:
        return {"HH": self.hh, "HV": self.hv}[polarization]


@dataclass(frozen=True)
class IngestConfig:
    case_id: str
    product: str
    output_dir: Path
    perimeter: Path
    perimeter_objectid: int
    margin_m: float
    crs: CRS
    pixel_size_m: float
    track: int
    frame: int
    direction: str
    frequency: str
    epochs: Mapping[str, EpochConfig]


def _require(table: Mapping[str, Any], key: str, kind: type, where: str) -> Any:
    if key not in table:
        raise IngestError(f"config: missing '{where}{key}'")
    value = table[key]
    if kind is float and isinstance(value, int) and not isinstance(value, bool):
        value = float(value)
    if not isinstance(value, kind) or (isinstance(value, bool) and kind is not bool):
        raise IngestError(f"config: '{where}{key}' must be {kind.__name__}, got {value!r}")
    return value


def load_config(path: Path, base_dir: Path | None = None) -> IngestConfig:
    """Parse a TOML ingest configuration; relative paths resolve against ``base_dir``."""
    base = Path.cwd() if base_dir is None else base_dir
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise IngestError(f"config: cannot read {path.name}: {exc}") from exc

    def resolve(value: str) -> Path:
        p = Path(value)
        return p if p.is_absolute() else base / p

    aoi = _require(raw, "aoi", dict, "")
    grid = _require(raw, "grid", dict, "")
    acq = _require(raw, "acquisition", dict, "")
    epochs_raw = _require(raw, "epochs", dict, "")
    epochs: dict[str, EpochConfig] = {}
    for name in EPOCHS:
        e = _require(epochs_raw, name, dict, "epochs.")
        w = f"epochs.{name}."
        epochs[name] = EpochConfig(
            label=_require(e, "label", str, w),
            datetime=_require(e, "datetime", str, w),
            granule_id=_require(e, "granule_id", str, w),
            absolute_orbit=_require(e, "absolute_orbit", int, w),
            hh=resolve(_require(e, "hh", str, w)),
            hv=resolve(_require(e, "hv", str, w)),
        )
    margin_m = _require(aoi, "margin_m", float, "aoi.")
    if not math.isfinite(margin_m) or margin_m < 0:
        raise IngestError(f"config: 'aoi.margin_m' must be a finite value >= 0, got {margin_m}")
    crs_text = _require(grid, "crs", str, "grid.")
    try:
        crs = CRS.from_user_input(crs_text)
    except CRSError as exc:
        raise IngestError(f"config: invalid grid.crs {crs_text!r}: {exc}") from exc
    if crs != ANALYSIS_CRS:
        raise IngestError(f"config: grid.crs must be the analysis CRS EPSG:32610, got {crs_text!r}")
    pixel_size_m = _require(grid, "pixel_size_m", float, "grid.")
    if pixel_size_m != ANALYSIS_PIXEL_SIZE_M:
        raise IngestError(
            f"config: grid.pixel_size_m must be the analysis grid {ANALYSIS_PIXEL_SIZE_M} m, "
            f"got {pixel_size_m}"
        )
    direction = _require(acq, "direction", str, "acquisition.")
    if direction not in ("ascending", "descending"):
        raise IngestError(f"config: unknown acquisition.direction {direction!r}")
    return IngestConfig(
        case_id=_require(raw, "case_id", str, ""),
        product=_require(raw, "product", str, ""),
        output_dir=resolve(_require(raw, "output_dir", str, "")),
        perimeter=resolve(_require(aoi, "perimeter", str, "aoi.")),
        perimeter_objectid=_require(aoi, "objectid", int, "aoi."),
        margin_m=margin_m,
        crs=crs,
        pixel_size_m=pixel_size_m,
        track=_require(acq, "track", int, "acquisition."),
        frame=_require(acq, "frame", int, "acquisition."),
        direction=direction,
        frequency=_require(acq, "frequency", str, "acquisition."),
        epochs=epochs,
    )


# --------------------------------------------------------------------------- grid


@dataclass(frozen=True)
class GridInfo:
    """Georeferencing, shape and encoding of one single-band source raster."""

    crs: CRS
    transform: Affine
    width: int
    height: int
    dtype: str
    nodata: float | None
    count: int


def read_grid(path: Path) -> GridInfo:
    if not path.is_file():
        raise IngestError(f"input not found: {path.name}")
    try:
        with rasterio.open(path) as ds:
            info = GridInfo(
                crs=ds.crs,
                transform=ds.transform,
                width=ds.width,
                height=ds.height,
                dtype=ds.dtypes[0],
                nodata=ds.nodata,
                count=ds.count,
            )
    except _RASTER_IO_ERRORS as exc:
        raise IngestError(f"{path.name}: cannot read raster: {exc}") from exc
    if info.crs is None:
        raise IngestError(f"{path.name}: raster has no CRS")
    return info


def check_common_grid(
    grids: Mapping[str, GridInfo], expected_crs: CRS, pixel_size_m: float
) -> GridInfo:
    """Return the shared grid or raise if any input differs in CRS, transform or shape.

    Also requires single-band float32 inputs, the configured analysis CRS and an
    axis-aligned, north-up transform with the configured square pixel size.
    """
    if not grids:
        raise IngestError("no inputs to check")
    names = sorted(grids)
    ref_name = names[0]
    ref = grids[ref_name]
    for name in names:
        g = grids[name]
        if g.count != 1:
            raise IngestError(f"{name}: expected 1 band, found {g.count}")
        if g.dtype != "float32":
            raise IngestError(f"{name}: expected float32 GCOV power, found {g.dtype}")
    for name in names[1:]:
        g = grids[name]
        if g.crs != ref.crs:
            raise IngestError(f"grid mismatch: CRS of {name} ({g.crs}) != {ref_name} ({ref.crs})")
        if tuple(g.transform) != tuple(ref.transform):
            raise IngestError(
                f"grid mismatch: transform of {name} {tuple(g.transform)[:6]} != "
                f"{ref_name} {tuple(ref.transform)[:6]}"
            )
        if (g.height, g.width) != (ref.height, ref.width):
            raise IngestError(
                f"grid mismatch: shape of {name} {(g.height, g.width)} != "
                f"{ref_name} {(ref.height, ref.width)}"
            )
    if ref.crs != expected_crs:
        raise IngestError(f"inputs use {ref.crs}, expected analysis CRS {expected_crs}")
    t = ref.transform
    if t.b != 0 or t.d != 0 or t.a <= 0 or t.e >= 0:
        raise IngestError(f"source transform is not axis-aligned north-up: {tuple(t)[:6]}")
    if t.a != pixel_size_m or -t.e != pixel_size_m:
        raise IngestError(f"pixel size ({t.a}, {-t.e}) != configured {pixel_size_m} m")
    return ref


# --------------------------------------------------------------------------- AOI


def perimeter_bounds(path: Path, objectid: int, crs: CRS) -> Bounds:
    """Bounds of the selected perimeter feature after reprojection to ``crs``."""
    if not path.is_file():
        raise IngestError(f"perimeter not found: {path.name}")
    try:
        gdf = gpd.read_file(path)
    except _VECTOR_IO_ERRORS as exc:
        raise IngestError(f"{path.name}: cannot read perimeter: {exc}") from exc
    if gdf.crs is None:
        raise IngestError(f"{path.name}: perimeter has no CRS")
    if "OBJECTID" not in gdf.columns:
        raise IngestError(f"{path.name}: no OBJECTID property")
    selected = gdf[gdf["OBJECTID"] == objectid]
    if len(selected) != 1:
        raise IngestError(
            f"{path.name}: expected 1 feature OBJECTID={objectid}, found {len(selected)}"
        )
    projected = selected.to_crs(crs)
    if projected.geometry.is_empty.any():
        raise IngestError(f"{path.name}: perimeter geometry is empty")
    min_x, min_y, max_x, max_y = (float(v) for v in projected.total_bounds)
    return (min_x, min_y, max_x, max_y)


def expand_bounds(bounds: Bounds, margin: float) -> Bounds:
    min_x, min_y, max_x, max_y = bounds
    return (min_x - margin, min_y - margin, max_x + margin, max_y + margin)


def snap_window(aoi: Bounds, transform: Affine, width: int, height: int) -> Window:
    """Smallest integer pixel window of the native grid that fully covers ``aoi``.

    Fails if the AOI is not fully inside the raster extent; never clips silently.
    """
    min_x, min_y, max_x, max_y = aoi
    if not (min_x < max_x and min_y < max_y):
        raise IngestError(f"degenerate AOI bounds {aoi}")
    col_start = math.floor((min_x - transform.c) / transform.a)
    col_stop = math.ceil((max_x - transform.c) / transform.a)
    row_start = math.floor((transform.f - max_y) / -transform.e)
    row_stop = math.ceil((transform.f - min_y) / -transform.e)
    if col_start < 0 or row_start < 0 or col_stop > width or row_stop > height:
        raise IngestError(
            f"AOI {aoi} exceeds the raster extent {raster_bounds(transform, width, height)} "
            f"(pixel window cols {col_start}:{col_stop}, rows {row_start}:{row_stop}, "
            f"raster {width}x{height})"
        )
    return Window(col_start, row_start, col_stop - col_start, row_stop - row_start)


def crop_transform_of(transform: Affine, window: Window) -> Affine:
    """Transform of an integer window: an exact pixel offset of the source grid."""
    return transform @ Affine.translation(int(window.col_off), int(window.row_off))


def raster_bounds(transform: Affine, width: int, height: int) -> Bounds:
    left, top = transform.c, transform.f
    right = left + width * transform.a
    bottom = top + height * transform.e
    return (left, bottom, right, top)


def to_wgs84(bounds: Bounds, crs: CRS) -> list[float]:
    """Densified reprojection of projected bounds to an EPSG:4326 lon/lat bbox."""
    west, south, east, north = transform_bounds(
        crs, WGS84, *bounds, densify_pts=BOUNDS_DENSIFY_POINTS
    )
    return [round(float(v), WGS84_DECIMALS) for v in (west, south, east, north)]


# --------------------------------------------------------------------------- I/O


def sha256_file(path: Path) -> str:
    try:
        with path.open("rb") as fh:
            return hashlib.file_digest(fh, "sha256").hexdigest()
    except OSError as exc:
        raise IngestError(f"{path.name}: cannot hash file: {exc}") from exc


def covariance_term(polarization: str) -> str:
    return polarization * 2


def check_polarization_tags(path: Path, polarization: str) -> None:
    """Guard against swapped files when the NISAR band metadata names the term."""
    try:
        with rasterio.open(path) as ds:
            long_name = ds.tags(1).get("long_name", "")
    except _RASTER_IO_ERRORS as exc:
        raise IngestError(f"{path.name}: cannot read raster tags: {exc}") from exc
    term = covariance_term(polarization)
    if "covariance term" in long_name and not long_name.endswith(term):
        raise IngestError(f"{path.name}: band is '{long_name}', expected term {term}")


def crop_raster(src: Path, dst: Path, window: Window, tags: Mapping[str, str]) -> None:
    """Copy ``window`` of ``src`` to ``dst`` unchanged (windowed read, no resampling)."""
    try:
        with rasterio.open(src) as ds:
            data = ds.read(1, window=window)
            transform = crop_transform_of(ds.transform, window)
            profile = {
                **OUTPUT_CREATION_OPTIONS,
                "width": int(window.width),
                "height": int(window.height),
                "count": 1,
                "dtype": ds.dtypes[0],
                "crs": ds.crs,
                "transform": transform,
                "nodata": ds.nodata,
            }
    except _RASTER_IO_ERRORS as exc:
        raise IngestError(f"{src.name}: cannot read crop window: {exc}") from exc
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(dst, "w", **profile) as out:
            out.write(data, 1)
            out.update_tags(**tags)
            out.set_band_description(1, tags["COVARIANCE_TERM"])
    except _RASTER_IO_ERRORS as exc:
        raise IngestError(f"{dst.name}: cannot write crop: {exc}") from exc


def _nodata_repr(value: float | None) -> float | str | None:
    if value is None:
        return None
    if math.isnan(value):
        return "nan"
    return float(value)


def _transform_list(t: Affine) -> list[float]:
    return [float(v) for v in tuple(t)[:6]]


def _bounds_list(b: Bounds) -> list[float]:
    return [float(v) for v in b]


def _same_file(a: Path, b: Path) -> bool:
    """True if two paths name the same file, including links to an existing file."""
    if a.resolve() == b.resolve():
        return True
    try:
        return a.exists() and b.exists() and os.path.samefile(a, b)
    except OSError:
        return False


def check_outputs_do_not_alias_inputs(outputs: Sequence[Path], sources: Sequence[Path]) -> None:
    """Refuse any output that would overwrite an input raster or the perimeter."""
    for out in outputs:
        for src in sources:
            if _same_file(out, src):
                raise IngestError(
                    f"output {out.name} would overwrite input {src.name}; "
                    "choose an output_dir separate from the inputs"
                )


# --------------------------------------------------------------------------- run


def run_ingest(config: IngestConfig) -> dict[str, Any]:
    """Run the ingest and return the ``ingest.json`` document that was written."""
    inputs = {
        f"{epoch}_{pol.lower()}": config.epochs[epoch].path(pol)
        for epoch in EPOCHS
        for pol in POLARIZATIONS
    }
    grids = {name: read_grid(path) for name, path in inputs.items()}
    grid = check_common_grid(grids, config.crs, config.pixel_size_m)
    for name, path in inputs.items():
        check_polarization_tags(path, name.split("_")[1].upper())

    out_paths = {name: config.output_dir / f"{name}.tif" for name in inputs}
    manifest_path = config.output_dir / "ingest.json"
    check_outputs_do_not_alias_inputs(
        [*out_paths.values(), manifest_path], [*inputs.values(), config.perimeter]
    )
    # Hash sources before any write, so provenance always describes the untouched inputs.
    input_sha256 = {name: sha256_file(path) for name, path in inputs.items()}
    perimeter_sha256 = sha256_file(config.perimeter)

    perim = perimeter_bounds(config.perimeter, config.perimeter_objectid, grid.crs)
    aoi = expand_bounds(perim, config.margin_m)
    window = snap_window(aoi, grid.transform, grid.width, grid.height)
    crop_transform = crop_transform_of(grid.transform, window)
    crop_bounds = raster_bounds(crop_transform, int(window.width), int(window.height))

    input_records: dict[str, Any] = {}
    output_records: dict[str, Any] = {}
    for name, path in inputs.items():
        epoch_name, pol_lower = name.split("_")
        epoch = config.epochs[epoch_name]
        pol = pol_lower.upper()
        term = covariance_term(pol)
        out_path = out_paths[name]
        crop_raster(
            path,
            out_path,
            window,
            {
                "FIRETRACE_STAGE": "ingest",
                "COVARIANCE_TERM": term,
                "POLARIZATION": pol,
                "EPOCH": epoch_name,
                "SOURCE_GRANULE_ID": epoch.granule_id,
                "SOURCE_FILE": path.name,
                "UNITS": "linear power (GCOV covariance term)",
            },
        )
        input_records[name] = {
            "file": path.name,
            "sha256": input_sha256[name],
            "granule_id": epoch.granule_id,
            "polarization": pol,
            "covariance_term": term,
            "nodata": _nodata_repr(grids[name].nodata),
        }
        output_records[name] = {
            "file": out_path.name,
            "sha256": sha256_file(out_path),
            "dtype": grids[name].dtype,
            "nodata": _nodata_repr(grids[name].nodata),
        }

    crs_string = grid.crs.to_string()
    document: dict[str, Any] = {
        "ingest_format_version": INGEST_FORMAT_VERSION,
        "case_id": config.case_id,
        "product": config.product,
        "epochs": {
            name: {
                "label": e.label,
                "datetime": e.datetime,
                "granule_id": e.granule_id,
                "absolute_orbit": e.absolute_orbit,
            }
            for name, e in config.epochs.items()
        },
        "acquisition": {
            "track": config.track,
            "frame": config.frame,
            "direction": config.direction,
            "frequency": config.frequency,
            "polarizations": list(POLARIZATIONS),
            "pixel_size_m": float(config.pixel_size_m),
            "crs": crs_string,
        },
        "reference": {
            "file": config.perimeter.name,
            "sha256": perimeter_sha256,
            "objectid": config.perimeter_objectid,
        },
        "aoi": {
            "rule": "reference perimeter bbox in analysis CRS expanded by margin_m on each side",
            "margin_m": float(config.margin_m),
            "perimeter_bounds_projected": _bounds_list(perim),
            "aoi_bounds_projected": _bounds_list(aoi),
            "crop_bounds_projected": _bounds_list(crop_bounds),
            "aoi_bbox_4326": to_wgs84(aoi, grid.crs),
            "crop_bbox_4326": to_wgs84(crop_bounds, grid.crs),
            "bounds_crs": crs_string,
        },
        "grid": {
            "crs": crs_string,
            "source": {
                "transform": _transform_list(grid.transform),
                "width": grid.width,
                "height": grid.height,
                "bounds": _bounds_list(raster_bounds(grid.transform, grid.width, grid.height)),
            },
            "crop": {
                "window": {
                    "col_off": int(window.col_off),
                    "row_off": int(window.row_off),
                    "width": int(window.width),
                    "height": int(window.height),
                },
                "transform": _transform_list(crop_transform),
                "width": int(window.width),
                "height": int(window.height),
                "bounds": _bounds_list(crop_bounds),
            },
            "resampling": "none",
        },
        "inputs": input_records,
        "outputs": output_records,
    }
    write_json(manifest_path, document)
    return document


def write_json(path: Path, document: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(document, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False)
    path.write_text(text + "\n", encoding="utf-8", newline="\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m pipeline.ingest",
        description="Crop the four NISAR GCOV HH/HV t1/t2 rasters to the case AOI.",
    )
    parser.add_argument("--config", type=Path, required=True, help="TOML ingest configuration")
    args = parser.parse_args(argv)
    try:
        document = run_ingest(load_config(args.config))
    except IngestError as exc:
        print(f"ingest error: {exc}", file=sys.stderr)
        return 2
    crop = document["grid"]["crop"]
    print(
        f"ingest ok: {len(document['outputs'])} rasters, crop {crop['width']}x{crop['height']} px, "
        f"bbox_4326 {document['aoi']['crop_bbox_4326']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
