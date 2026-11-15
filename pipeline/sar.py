"""Convert the DT-01 GCOV crops to dB and build the common valid mask (DT-02).

Inputs are the four float32 linear-power crops and ``ingest.json`` written by
``pipeline.ingest``. For each layer, ``10 * log10(x)`` is computed only where ``x`` is
finite, strictly positive and not the source no-data value; every other pixel becomes NaN.
``valid_mask.tif`` is 1 where all four inputs are valid and 0 otherwise, so combined
products and metrics use one common valid set (AGENTS.md scientific invariants).

The grid is copied unchanged (10 m EPSG:32610, no resampling). Outputs are COGs plus a
deterministic ``sar.json`` manifest with per-layer counts and checksums. ``stats.json``
(CH-02/DT-04) and the change index (CH-01) are out of scope.

Run from the repository root::

    uv run python -m pipeline.sar --ingest-dir data/interim/nisar --output-dir data/interim/sar
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from affine import Affine
from rasterio.crs import CRS
from rasterio.errors import RasterioError
from rasterio.io import MemoryFile
from rio_cogeo.cogeo import cog_translate, cog_validate
from rio_cogeo.profiles import cog_profiles

from pipeline import publishing
from pipeline.publishing import PublishError, read_verified_raster

SAR_FORMAT_VERSION = 1
SUPPORTED_INGEST_FORMAT_VERSION = 1
NAMES: tuple[str, ...] = ("t1_hh", "t1_hv", "t2_hh", "t2_hv")
ANALYSIS_CRS = CRS.from_epsg(32610)
ANALYSIS_PIXEL_SIZE_M = 10.0
DB_FORMULA = "10*log10(x) for finite x > 0 and x != source nodata; NaN otherwise"
MASK_RULE = "1 where all four inputs are finite, > 0 and not source nodata; 0 otherwise"
# Deterministic COG encoding: lossless, 256 px blocks, nearest overviews, no timestamps.
COG_BLOCKSIZE = 256
OVERVIEW_RESAMPLING = "nearest"

_RASTER_IO_ERRORS = (RasterioError, OSError)
OUTPUT_FILES: frozenset[str] = frozenset(
    {*(f"{n}_db.tif" for n in NAMES), "valid_mask.tif", "sar.json"}
)


class SarError(Exception):
    """Raised for any input condition that prevents a faithful dB conversion."""


# --------------------------------------------------------------------------- core


@dataclass(frozen=True)
class LayerCounts:
    """Pixel classification of one linear-power layer (classes are disjoint)."""

    valid: int
    nodata: int  # non-finite or equal to the source no-data value
    non_positive: int  # finite, not no-data, and <= 0

    def as_dict(self) -> dict[str, int]:
        return {"valid": self.valid, "nodata": self.nodata, "non_positive": self.non_positive}


def valid_power(power: np.ndarray, nodata: float | None) -> np.ndarray:
    """Boolean mask of pixels whose linear power can enter a logarithm."""
    valid = np.isfinite(power) & (power > 0)
    if nodata is not None and not math.isnan(nodata):
        valid &= power != nodata
    return valid


def classify(power: np.ndarray, nodata: float | None) -> LayerCounts:
    is_nodata = ~np.isfinite(power)
    if nodata is not None and not math.isnan(nodata):
        is_nodata |= power == nodata
    non_positive = ~is_nodata & (power <= 0)
    valid = ~is_nodata & ~non_positive
    return LayerCounts(
        valid=int(valid.sum()), nodata=int(is_nodata.sum()), non_positive=int(non_positive.sum())
    )


def to_db(power: np.ndarray, nodata: float | None) -> np.ndarray:
    """float32 dB of valid pixels; NaN elsewhere. Computed in float64, then rounded once."""
    valid = valid_power(power, nodata)
    out = np.full(power.shape, np.nan, dtype=np.float64)
    out[valid] = 10.0 * np.log10(power[valid].astype(np.float64))
    return out.astype(np.float32)


def common_valid_mask(layers: Mapping[str, np.ndarray], nodata: Mapping[str, float | None]):
    """uint8 mask: 1 where every layer is valid, 0 otherwise."""
    names = sorted(layers)
    mask = valid_power(layers[names[0]], nodata[names[0]])
    for name in names[1:]:
        mask &= valid_power(layers[name], nodata[name])
    return mask.astype(np.uint8)


# --------------------------------------------------------------------------- I/O


def sha256_file(path: Path) -> str:
    try:
        with path.open("rb") as fh:
            return hashlib.file_digest(fh, "sha256").hexdigest()
    except OSError as exc:
        raise SarError(f"{path.name}: cannot hash file: {exc}") from exc


def _nodata_from_record(value: Any) -> float | None:
    if value is None:
        return None
    if value == "nan":
        return float("nan")
    return float(value)


def load_ingest(ingest_dir: Path) -> dict[str, Any]:
    path = ingest_dir / "ingest.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SarError(f"cannot read {path.name}: {exc}") from exc
    validate_ingest(doc)
    return doc


def _expect(cond: bool, what: str) -> None:
    if not cond:
        raise SarError(f"ingest.json: {what}")


def _is_number(v: Any) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool)


def validate_ingest(doc: Any) -> None:
    """Check every ingest.json field DT-02 relies on, before anything is written."""
    _expect(isinstance(doc, dict), "top level must be an object")
    version = doc.get("ingest_format_version")
    _expect(
        version == SUPPORTED_INGEST_FORMAT_VERSION,
        f"unsupported ingest_format_version {version!r}",
    )
    _expect(isinstance(doc.get("case_id"), str), "'case_id' must be a string")
    grid = doc.get("grid")
    crop = grid.get("crop") if isinstance(grid, dict) else None
    _expect(isinstance(crop, dict), "'grid.crop' must be an object")
    transform = crop.get("transform")
    _expect(
        isinstance(transform, list) and len(transform) == 6 and all(map(_is_number, transform)),
        "'grid.crop.transform' must be 6 numbers",
    )
    for key in ("width", "height"):
        value = crop.get(key)
        _expect(
            isinstance(value, int) and not isinstance(value, bool) and value > 0,
            f"'grid.crop.{key}' must be a positive integer",
        )
    outputs = doc.get("outputs")
    _expect(isinstance(outputs, dict), "'outputs' must be an object")
    for name in NAMES:
        record = outputs.get(name)
        _expect(isinstance(record, dict), f"'outputs.{name}' is missing")
        _expect(isinstance(record.get("file"), str), f"'outputs.{name}.file' must be a string")
        sha = record.get("sha256")
        _expect(
            isinstance(sha, str) and len(sha) == 64, f"'outputs.{name}.sha256' must be a sha256"
        )
        nodata = record.get("nodata")
        _expect(
            nodata is None or nodata == "nan" or _is_number(nodata),
            f"'outputs.{name}.nodata' must be null, 'nan' or a number",
        )


@dataclass(frozen=True)
class Layer:
    data: np.ndarray
    nodata: float | None
    crs: CRS
    transform: Affine


def read_layer(path: Path, record: Mapping[str, Any], crop: Mapping[str, Any]) -> Layer:
    """Read one crop after checking it is the exact file and grid DT-01 recorded."""
    try:
        raster = read_verified_raster(
            path, record["sha256"], "ingest.json", "re-run the DT-01 ingest"
        )
    except PublishError as exc:
        raise SarError(str(exc)) from exc
    if raster.count != 1 or raster.dtype != "float32":
        raise SarError(f"{path.name}: expected 1 float32 band")
    layer = Layer(raster.data, raster.nodata, raster.crs, raster.transform)
    shape = (raster.height, raster.width)
    if layer.crs != ANALYSIS_CRS:
        raise SarError(f"{path.name}: CRS {layer.crs} is not the analysis CRS EPSG:32610")
    t = layer.transform
    if (t.a, t.b, t.d, t.e) != (ANALYSIS_PIXEL_SIZE_M, 0.0, 0.0, -ANALYSIS_PIXEL_SIZE_M):
        raise SarError(f"{path.name}: not a north-up 10 m grid: {tuple(t)[:6]}")
    if [float(v) for v in tuple(t)[:6]] != crop["transform"]:
        raise SarError(f"{path.name}: transform differs from the ingest.json crop")
    if shape != (crop["height"], crop["width"]):
        raise SarError(f"{path.name}: shape {shape} differs from the ingest.json crop")
    recorded = _nodata_from_record(record.get("nodata"))
    same_nodata = (recorded is None and layer.nodata is None) or (
        recorded is not None
        and layer.nodata is not None
        and (recorded == layer.nodata or (math.isnan(recorded) and math.isnan(layer.nodata)))
    )
    if not same_nodata:
        raise SarError(f"{path.name}: nodata {layer.nodata} differs from ingest.json {recorded}")
    return layer


def write_cog(dst: Path, data: np.ndarray, *, crs: CRS, transform: Affine, nodata: float | None):
    """Write a single-band COG deterministically (in-memory source, no temp files)."""
    profile = {
        "driver": "GTiff",
        "width": data.shape[1],
        "height": data.shape[0],
        "count": 1,
        "dtype": data.dtype.name,
        "crs": crs,
        "transform": transform,
        "nodata": nodata,
    }
    dst_profile = cog_profiles.get("deflate")
    dst_profile.update(
        {
            "blockxsize": COG_BLOCKSIZE,
            "blockysize": COG_BLOCKSIZE,
            "predictor": 3 if data.dtype.kind == "f" else 2,
        }
    )
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        with MemoryFile() as mem:
            with mem.open(**profile) as tmp:
                tmp.write(data, 1)
            with mem.open() as src:
                cog_translate(
                    src,
                    str(dst),
                    dst_profile,
                    nodata=nodata,
                    overview_resampling=OVERVIEW_RESAMPLING,
                    in_memory=True,
                    quiet=True,
                    use_cog_driver=False,
                )
    except _RASTER_IO_ERRORS as exc:
        raise SarError(f"{dst.name}: cannot write COG: {exc}") from exc
    is_valid, errors, _warnings = cog_validate(str(dst), quiet=True)
    if not is_valid:
        raise SarError(f"{dst.name}: not a valid COG: {errors}")


def write_json(path: Path, document: Mapping[str, Any]) -> None:
    text = json.dumps(document, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8", newline="\n")
    except OSError as exc:
        raise SarError(f"{path.name}: cannot write: {exc}") from exc


def _staging_dirs(output_dir: Path) -> tuple[Path, Path]:
    return publishing.staging_dirs(output_dir)


def check_output_dir(output_dir: Path) -> None:
    """Only missing or fully owned output, staging and backup directories may be replaced."""
    try:
        publishing.check_output_dir(output_dir, OUTPUT_FILES)
    except PublishError as exc:
        raise SarError(str(exc)) from exc


def publish(staging: Path, output_dir: Path, owned: Iterable[str], stage: str = "pipeline") -> None:
    """Swap a complete staging set into place (see :func:`pipeline.publishing.publish`).

    The rename is the commit point: an earlier failure restores the previous set and raises
    ``SarError``; a later backup-cleanup failure is only printed as ``<stage> warning``.
    """
    try:
        message = publishing.publish(staging, output_dir, owned)
    except PublishError as exc:
        raise SarError(str(exc)) from exc
    publishing.report(message, stage)


def clear_staging(staging: Path, owned: Iterable[str]) -> None:
    """Remove a stale owned staging set without recursion (``SarError`` on foreign entries)."""
    try:
        publishing.remove_owned(staging, owned)
    except PublishError as exc:
        raise SarError(str(exc)) from exc


def discard_staging(staging: Path, owned: Iterable[str]) -> None:
    """Best-effort, non-recursive cleanup of an unpublished staging set; never raises."""
    publishing.discard_staging(staging, owned)


def input_file(directory: Path, name: object, manifest: str) -> Path:
    """A bare manifest-recorded file name inside ``directory`` (``SarError`` otherwise)."""
    try:
        return publishing.input_file(directory, name, manifest)
    except PublishError as exc:
        raise SarError(str(exc)) from exc


def overlapping_input(output_dir: Path, inputs: Iterable[Path]) -> Path | None:
    """:func:`pipeline.publishing.overlapping_input` raising ``SarError`` on I/O failure."""
    try:
        return publishing.overlapping_input(output_dir, inputs)
    except PublishError as exc:
        raise SarError(str(exc)) from exc


# --------------------------------------------------------------------------- run


def run_sar(ingest_dir: Path, output_dir: Path) -> dict[str, Any]:
    """Convert the crops in ``ingest_dir`` and return the ``sar.json`` document written."""
    if overlapping_input(output_dir, [ingest_dir]) is not None:
        raise SarError("output_dir must differ from ingest_dir")
    check_output_dir(output_dir)
    ingest = load_ingest(ingest_dir)
    crop = ingest["grid"]["crop"]
    layers = {
        name: read_layer(
            input_file(ingest_dir, ingest["outputs"][name]["file"], "ingest.json"),
            ingest["outputs"][name],
            crop,
        )
        for name in NAMES
    }
    nodata = {name: layer.nodata for name, layer in layers.items()}
    mask = common_valid_mask({n: lyr.data for n, lyr in layers.items()}, nodata)

    # Build the complete set in a staging directory, then publish it in one swap, so a
    # failed run never leaves mixed-generation files or a stale sar.json behind.
    staging, _ = _staging_dirs(output_dir)
    clear_staging(staging, OUTPUT_FILES)
    try:
        document = _build(staging, ingest_dir, ingest, crop, layers, mask)
        publish(staging, output_dir, OUTPUT_FILES, "sar")
    finally:
        discard_staging(staging, OUTPUT_FILES)
    return document


def _build(
    output_dir: Path,
    ingest_dir: Path,
    ingest: Mapping[str, Any],
    crop: Mapping[str, Any],
    layers: Mapping[str, Layer],
    mask: np.ndarray,
) -> dict[str, Any]:
    ref = layers[NAMES[0]]
    total = int(mask.size)
    valid_total = int(mask.sum())
    layer_records: dict[str, Any] = {}
    for name, layer in layers.items():
        out = output_dir / f"{name}_db.tif"
        write_cog(
            out,
            to_db(layer.data, layer.nodata),
            crs=ref.crs,
            transform=ref.transform,
            nodata=float("nan"),
        )
        layer_records[name] = {
            "file": out.name,
            "sha256": sha256_file(out),
            "source_file": ingest["outputs"][name]["file"],
            "source_sha256": ingest["outputs"][name]["sha256"],
            "dtype": "float32",
            "units": "dB",
            "nodata": "nan",
            "counts": classify(layer.data, layer.nodata).as_dict(),
        }
    mask_path = output_dir / "valid_mask.tif"
    write_cog(mask_path, mask, crs=ref.crs, transform=ref.transform, nodata=None)

    document: dict[str, Any] = {
        "sar_format_version": SAR_FORMAT_VERSION,
        "case_id": ingest["case_id"],
        "source_ingest": {
            "file": "ingest.json",
            "sha256": sha256_file(ingest_dir / "ingest.json"),
        },
        "grid": {
            "crs": ref.crs.to_string(),
            "transform": [float(v) for v in tuple(ref.transform)[:6]],
            "width": int(crop["width"]),
            "height": int(crop["height"]),
            "resampling": "none",
        },
        "db": {"formula": DB_FORMULA, "layers": layer_records},
        "valid_mask": {
            "file": mask_path.name,
            "sha256": sha256_file(mask_path),
            "dtype": "uint8",
            "rule": MASK_RULE,
            "values": {"0": "invalid in at least one layer", "1": "valid in all four layers"},
            "valid_pixels": valid_total,
            "total_pixels": total,
            "valid_coverage_pct": round(100.0 * valid_total / total, 6) if total else 0.0,
        },
    }
    write_json(output_dir / "sar.json", document)
    return document


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m pipeline.sar",
        description="Convert the DT-01 GCOV crops to dB COGs and build the common valid mask.",
    )
    parser.add_argument("--ingest-dir", type=Path, default=Path("data/interim/nisar"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/interim/sar"))
    args = parser.parse_args(argv)
    try:
        doc = run_sar(args.ingest_dir, args.output_dir)
    except SarError as exc:
        print(f"sar error: {exc}", file=sys.stderr)
        return 2
    m = doc["valid_mask"]
    print(
        f"sar ok: 4 dB layers + valid mask, {m['valid_pixels']}/{m['total_pixels']} valid "
        f"({m['valid_coverage_pct']}%)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
