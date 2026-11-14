"""Continuous HH/HV radar change index from the DT-02 dB layers (CH-01).

Observation only: the index says where and how much the radar signal changed relative to
the typical change in the crop. It has no threshold and is not burned area or severity.

For each valid pixel (``valid_mask == 1``)::

    change_hh_db = t2_hh_db - t1_hh_db            (signed dB difference)
    change_hv_db = t2_hv_db - t1_hv_db
    S            = |change_hh_db| + |change_hv_db|
    change_index = (S - median(S)) / (1.4826 * MAD(S))

``median`` and ``MAD`` are taken over all valid pixels of the crop (no perimeter input), no
speckle filter is applied and values are not clipped. Invalid pixels are NaN. See
``docs/methods/change-index.md``.

Run from the repository root::

    uv run python -m pipeline.change --sar-dir data/interim/sar --output-dir data/interim/change
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
import warnings
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from affine import Affine
from rasterio.errors import NotGeoreferencedWarning

from pipeline import publishing
from pipeline.publishing import PublishError, read_verified_raster
from pipeline.sar import (
    _RASTER_IO_ERRORS,
    ANALYSIS_CRS,
    ANALYSIS_PIXEL_SIZE_M,
    SarError,
    _staging_dirs,
    publish,
    sha256_file,
    write_cog,
)

CHANGE_FORMAT_VERSION = 1
SUPPORTED_SAR_FORMAT_VERSION = 1
METHOD_ID = "abs-logratio-hhhv-v1"
MAD_SCALE = 1.4826  # makes the MAD comparable to a standard deviation for normal data
PERCENTILES: tuple[int, ...] = (1, 5, 25, 50, 75, 95, 99)
INPUT_NAMES: tuple[str, ...] = ("t1_hh", "t1_hv", "t2_hh", "t2_hv")
OUTPUT_FILES: frozenset[str] = frozenset(
    {"change_hh_db.tif", "change_hv_db.tif", "change_index.tif", "change.json"}
)
METHOD: dict[str, Any] = {
    "id": METHOD_ID,
    "name": "Absolute log-ratio change, HH + HV",
    "description": (
        "Per-pixel dB differences (after - before) for HH and HV; their absolute values are "
        "summed and normalised with a robust z-score (median and 1.4826 * MAD over all valid "
        "pixels of the crop). Continuous, unthresholded observation of radar change; not "
        "burned area or severity."
    ),
    "params": {
        "change": "t2_db - t1_db (signed)",
        "combination": "abs(change_hh_db) + abs(change_hv_db)",
        "normalization": "median_mad",
        "mad_scale": MAD_SCALE,
        "domain": "all_valid_crop",
        "speckle_filter": "none",
        "clipping": "none",
        "threshold": None,
    },
    "doc_url": "docs/methods/change-index.md",
}

# Quicklook palette: viridis stops, as in the contract fixture legend for change_index.
QUICKLOOK_STOPS: tuple[tuple[int, int, int], ...] = (
    (0x44, 0x01, 0x54),
    (0x3B, 0x52, 0x8B),
    (0x21, 0x91, 0x8C),
    (0x5E, 0xC9, 0x62),
    (0xFD, 0xE7, 0x25),
)


class ChangeError(Exception):
    """Raised for any input or numerical condition that prevents a faithful index."""


# --------------------------------------------------------------------------- core


def change_db(t1_db: np.ndarray, t2_db: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Signed float64 dB difference ``t2 - t1``; NaN where mask == 0.

    Kept in float64 through normalization; outputs are cast to float32 only for storage.
    """
    out = np.full(t1_db.shape, np.nan, dtype=np.float64)
    valid = mask.astype(bool)
    out[valid] = t2_db[valid].astype(np.float64) - t1_db[valid].astype(np.float64)
    return out


def combine(change_hh: np.ndarray, change_hv: np.ndarray) -> np.ndarray:
    """Absolute HH/HV change magnitude ``|dHH| + |dHV|`` in float64 (NaN propagates)."""
    return np.abs(change_hh.astype(np.float64)) + np.abs(change_hv.astype(np.float64))


def robust_stats(values: np.ndarray) -> tuple[float, float]:
    """Median and unscaled MAD of the finite ``values``; errors if undefined or zero."""
    finite = values[np.isfinite(values)].astype(np.float64)
    if finite.size == 0:
        raise ChangeError("no valid pixels to normalise the change index")
    median = float(np.median(finite))
    mad = float(np.median(np.abs(finite - median)))
    if not mad > 0:
        raise ChangeError(
            f"MAD of the change magnitude is {mad}: at least half of the valid pixels share "
            "the median change, so a robust z-score is undefined for this input"
        )
    return median, mad


def robust_z(values: np.ndarray, median: float, mad: float) -> np.ndarray:
    """``(values - median) / (1.4826 * mad)`` in float64; NaN stays NaN, no clipping."""
    return (values.astype(np.float64) - median) / (MAD_SCALE * mad)


def percentiles(values: np.ndarray) -> dict[str, float]:
    """Percentiles (NumPy default linear interpolation) and mean of the finite values."""
    finite = values[np.isfinite(values)].astype(np.float64)
    result = {f"p{p}": float(np.percentile(finite, p)) for p in PERCENTILES}
    result["mean"] = float(finite.mean())
    return result


# --------------------------------------------------------------------------- inputs


def _expect(cond: bool, what: str) -> None:
    if not cond:
        raise ChangeError(f"sar.json: {what}")


def _is_sha(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64


def load_sar(sar_dir: Path) -> dict[str, Any]:
    """Read and structurally validate the DT-02 manifest before anything is written."""
    path = sar_dir / "sar.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ChangeError(f"cannot read {path.name}: {exc}") from exc
    _expect(isinstance(doc, dict), "top level must be an object")
    version = doc.get("sar_format_version")
    _expect(version == SUPPORTED_SAR_FORMAT_VERSION, f"unsupported sar_format_version {version!r}")
    _expect(isinstance(doc.get("case_id"), str), "'case_id' must be a string")
    grid = doc.get("grid")
    _expect(isinstance(grid, dict), "'grid' must be an object")
    transform = grid.get("transform")
    _expect(
        isinstance(transform, list)
        and len(transform) == 6
        and all(isinstance(v, int | float) and not isinstance(v, bool) for v in transform),
        "'grid.transform' must be 6 numbers",
    )
    for key in ("width", "height"):
        value = grid.get(key)
        _expect(
            isinstance(value, int) and not isinstance(value, bool) and value > 0,
            f"'grid.{key}' must be a positive integer",
        )
    db = doc.get("db")
    layers = db.get("layers") if isinstance(db, dict) else None
    _expect(isinstance(layers, dict), "'db.layers' must be an object")
    for name in INPUT_NAMES:
        record = layers.get(name)
        _expect(isinstance(record, dict), f"'db.layers.{name}' is missing")
        _expect(isinstance(record.get("file"), str), f"'db.layers.{name}.file' must be a string")
        _expect(_is_sha(record.get("sha256")), f"'db.layers.{name}.sha256' must be a sha256")
    mask = doc.get("valid_mask")
    _expect(isinstance(mask, dict), "'valid_mask' must be an object")
    _expect(isinstance(mask.get("file"), str), "'valid_mask.file' must be a string")
    _expect(_is_sha(mask.get("sha256")), "'valid_mask.sha256' must be a sha256")
    return doc


def read_checked(
    path: Path,
    sha256: str,
    grid: Mapping[str, Any],
    dtype: str,
    manifest: str = "sar.json",
) -> np.ndarray:
    """Read a single-band raster after checking checksum, dtype, CRS and grid.

    The raster is decoded from the same bytes whose sha256 was checked, so a file replaced
    after hashing is never read unverified.
    """
    try:
        raster = read_verified_raster(
            path, sha256, manifest, f"re-run the stage that wrote {manifest}"
        )
    except PublishError as exc:
        raise ChangeError(str(exc)) from exc
    data = raster.data
    count, actual_dtype, crs = raster.count, raster.dtype, raster.crs
    transform, height, width = raster.transform, raster.height, raster.width
    if count != 1 or actual_dtype != dtype:
        raise ChangeError(f"{path.name}: expected 1 {dtype} band, got {count} {actual_dtype}")
    if crs != ANALYSIS_CRS:
        raise ChangeError(f"{path.name}: CRS {crs} is not the analysis CRS EPSG:32610")
    coeffs = tuple(float(v) for v in tuple(transform)[:6])
    north_up_10m = (ANALYSIS_PIXEL_SIZE_M, 0.0, 0.0, -ANALYSIS_PIXEL_SIZE_M)
    if (
        not all(math.isfinite(v) for v in coeffs)
        or (
            coeffs[0],
            coeffs[1],
            coeffs[3],
            coeffs[4],
        )
        != north_up_10m
    ):
        raise ChangeError(f"{path.name}: not the north-up 10 m analysis grid: {coeffs}")
    if [float(v) for v in tuple(transform)[:6]] != [float(v) for v in grid["transform"]]:
        raise ChangeError(f"{path.name}: transform differs from {manifest}")
    if (height, width) != (grid["height"], grid["width"]):
        raise ChangeError(f"{path.name}: shape {(height, width)} differs from {manifest}")
    return data


def check_output_dir(output_dir: Path) -> None:
    """Only missing or fully owned output, staging and backup directories may be replaced."""
    try:
        publishing.check_output_dir(output_dir, OUTPUT_FILES)
    except PublishError as exc:
        raise ChangeError(str(exc)) from exc


# --------------------------------------------------------------------------- quicklook


def write_quicklook(path: Path, index: np.ndarray) -> None:
    """RGBA PNG of the index (p2-p98 stretch, viridis, transparent NaN) for PR evidence only.

    It is not the web product (DT-04 renders EPSG:3857 PNGs with the agreed legend).
    """
    finite = index[np.isfinite(index)]
    lo, hi = (float(v) for v in np.percentile(finite, (2, 98)))
    span = hi - lo if hi > lo else 1.0
    t = np.clip((np.nan_to_num(index, nan=lo) - lo) / span, 0.0, 1.0)
    stops = np.array(QUICKLOOK_STOPS, dtype=np.float64)
    pos = t * (len(stops) - 1)
    i0 = np.minimum(pos.astype(int), len(stops) - 2)
    frac = (pos - i0)[..., None]
    rgb = stops[i0] * (1 - frac) + stops[i0 + 1] * frac
    rgba = np.empty((4, *index.shape), dtype=np.uint8)
    rgba[:3] = np.moveaxis(np.rint(rgb), -1, 0).astype(np.uint8)
    rgba[3] = np.where(np.isfinite(index), 255, 0).astype(np.uint8)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Deliberately ungeoreferenced: a plain picture, so GDAL writes no .aux.xml sidecar.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", NotGeoreferencedWarning)
            with rasterio.open(
                path,
                "w",
                driver="PNG",
                width=index.shape[1],
                height=index.shape[0],
                count=4,
                dtype="uint8",
            ) as out:
                out.write(rgba)
    except _RASTER_IO_ERRORS as exc:
        raise ChangeError(f"{path.name}: cannot write quicklook: {exc}") from exc


def check_quicklook_path(quicklook: Path, sar_dir: Path, output_dir: Path) -> None:
    """The preview must be a .png outside the input and product directories."""
    target = quicklook.resolve()
    if target.suffix.lower() != ".png":
        raise ChangeError(f"quicklook must be a .png file, got {quicklook.name}")
    staging, previous = _staging_dirs(output_dir)
    for protected in (sar_dir, output_dir, staging, previous):
        if target.is_relative_to(protected.resolve()):
            raise ChangeError(
                f"quicklook {quicklook.name} must be outside {protected.name}: it is review "
                "evidence and must never overwrite inputs or products"
            )


# --------------------------------------------------------------------------- run


def run_change(sar_dir: Path, output_dir: Path, quicklook: Path | None = None) -> dict[str, Any]:
    """Compute the change products from ``sar_dir`` and return the ``change.json`` written."""
    if publishing.overlapping_input(output_dir, [sar_dir]) is not None:
        raise ChangeError("output_dir must differ from sar_dir")
    if quicklook is not None:
        check_quicklook_path(quicklook, sar_dir, output_dir)
    check_output_dir(output_dir)
    sar = load_sar(sar_dir)
    grid = sar["grid"]
    layers = sar["db"]["layers"]
    db = {
        name: read_checked(sar_dir / layers[name]["file"], layers[name]["sha256"], grid, "float32")
        for name in INPUT_NAMES
    }
    mask = read_checked(
        sar_dir / sar["valid_mask"]["file"], sar["valid_mask"]["sha256"], grid, "uint8"
    )
    if not np.isin(mask, (0, 1)).all():
        raise ChangeError(f"{sar['valid_mask']['file']}: values must be 0 or 1")

    valid = mask.astype(bool)
    for name, data in db.items():
        bad = int((~np.isfinite(data[valid])).sum())
        if bad:
            raise ChangeError(
                f"{layers[name]['file']}: {bad} non-finite value(s) where valid_mask = 1; "
                "the DT-02 outputs are inconsistent"
            )
    change_hh = change_db(db["t1_hh"], db["t2_hh"], mask)
    change_hv = change_db(db["t1_hv"], db["t2_hv"], mask)
    magnitude = combine(change_hh, change_hv)
    median, mad = robust_stats(magnitude)
    # Normalise in float64; cast to float32 only for storage. Percentiles describe the stored
    # values that consumers (API, web export) will read.
    products = {
        "change_hh_db.tif": change_hh.astype(np.float32),
        "change_hv_db.tif": change_hv.astype(np.float32),
        "change_index.tif": robust_z(magnitude, median, mad).astype(np.float32),
    }
    transform = Affine(*grid["transform"])

    staging, _ = _staging_dirs(output_dir)
    try:
        if staging.exists():
            shutil.rmtree(staging)
        for name, data in products.items():
            write_cog(staging / name, data, crs=ANALYSIS_CRS, transform=transform, nodata=np.nan)
        document = {
            "change_format_version": CHANGE_FORMAT_VERSION,
            "case_id": sar["case_id"],
            "method": METHOD,
            "source_sar": {"file": "sar.json", "sha256": sha256_file(sar_dir / "sar.json")},
            "grid": {
                "crs": ANALYSIS_CRS.to_string(),
                "transform": [float(v) for v in grid["transform"]],
                "width": grid["width"],
                "height": grid["height"],
                "resampling": "none",
            },
            "normalization": {"median": median, "mad": mad, "mad_scale": MAD_SCALE},
            "valid_pixels": int(mask.sum()),
            "total_pixels": int(mask.size),
            "percentiles": {
                name.removesuffix(".tif"): percentiles(data) for name, data in products.items()
            },
            "outputs": {
                name.removesuffix(".tif"): {
                    "file": name,
                    "sha256": sha256_file(staging / name),
                    "dtype": "float32",
                    "nodata": "nan",
                    "units": "index (unitless, robust z-score)"
                    if name == "change_index.tif"
                    else "dB difference (after - before)",
                }
                for name in products
            },
        }
        text = json.dumps(document, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False)
        (staging / "change.json").write_text(text + "\n", encoding="utf-8", newline="\n")
        if quicklook is not None:
            # Rendered before publication: a failing preview never replaces the previous set.
            write_quicklook(quicklook, products["change_index.tif"])
        publish(staging, output_dir)
    except SarError as exc:
        raise ChangeError(str(exc)) from exc
    except OSError as exc:
        raise ChangeError(f"cannot write outputs: {exc}") from exc
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
    return document


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m pipeline.change",
        description="Compute the continuous HH/HV change index from the DT-02 dB layers.",
    )
    parser.add_argument("--sar-dir", type=Path, default=Path("data/interim/sar"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/interim/change"))
    parser.add_argument(
        "--quicklook", type=Path, default=None, help="optional PNG preview for PR evidence"
    )
    args = parser.parse_args(argv)
    try:
        doc = run_change(args.sar_dir, args.output_dir, args.quicklook)
    except ChangeError as exc:
        print(f"change error: {exc}", file=sys.stderr)
        return 2
    p = doc["percentiles"]["change_index"]
    print(
        f"change ok: {doc['valid_pixels']}/{doc['total_pixels']} valid, median S "
        f"{doc['normalization']['median']:.3f} dB, MAD {doc['normalization']['mad']:.3f} dB, "
        f"index p5/p50/p95 {p['p5']:.2f}/{p['p50']:.2f}/{p['p95']:.2f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
