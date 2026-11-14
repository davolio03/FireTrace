"""Observed radar change statistics inside and outside the reference perimeter (CH-02).

Summarises the CH-01 continuous change index over the DT-02 common valid pixels, split by
the DT-03 pixel-centre perimeter mask. These are statistics of *observed radar change*;
they are not burned area, severity or a validation of the perimeter.

Rules (agreed with David):

- D1: one set of 30 histogram bins shared by the all-valid, inside and outside
  distributions, spanning the global p0.5 to p99.5 of valid pixels. Values outside that
  range are counted in the first or last bin, so counts sum to the group's valid pixels;
  the number of such values is recorded in ``stats_meta.json``.
- E1: the 50 m boundary band is included; a variant without it is reported in
  ``stats_meta.json`` as a sensitivity check only.
- F1: open water stays in "outside" (no land mask yet).

Outputs: ``stats.json`` (the web contract, copied unchanged by DT-04) and
``stats_meta.json`` (provenance, histogram rule and sensitivity variant).

Run from the repository root::

    uv run python -m pipeline.stats --change-dir data/interim/change \\
        --sar-dir data/interim/sar --perimeter-dir data/interim/perimeter \\
        --output-dir data/interim/stats
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from pipeline.change import ChangeError, read_checked
from pipeline.sar import ANALYSIS_PIXEL_SIZE_M, SarError, _staging_dirs, publish, sha256_file

STATS_FORMAT_VERSION = 1
SUPPORTED_INPUT_VERSIONS = {
    "change.json": ("change_format_version", 1),
    "sar.json": ("sar_format_version", 1),
    "perimeter.json": ("perimeter_format_version", 1),
}
EXPECTED_METHOD_ID = "abs-logratio-hhhv-v1"
EXPECTED_RASTERIZATION = {"rule": "pixel_centre", "all_touched": False, "edge_distance_m": 50.0}
CONTRACT_VERSION = "1.2.0"
N_BINS = 30
RANGE_PERCENTILES = (0.5, 99.5)
DISTRIBUTION_PERCENTILES = (5, 25, 50, 75, 95)
PIXEL_AREA_M2 = ANALYSIS_PIXEL_SIZE_M * ANALYSIS_PIXEL_SIZE_M
OUTPUT_FILES: frozenset[str] = frozenset({"stats.json", "stats_meta.json"})


class StatsError(Exception):
    """Raised for any input or numerical condition that prevents faithful statistics."""


# --------------------------------------------------------------------------- core


def histogram_range(values: np.ndarray) -> tuple[float, float]:
    """Global p0.5-p99.5 range (NumPy linear interpolation) shared by every group."""
    lo, hi = (float(v) for v in np.percentile(values, RANGE_PERCENTILES))
    if not hi > lo:
        raise StatsError(f"degenerate histogram range [{lo}, {hi}]: the index is (almost) constant")
    return lo, hi


def distribution(values: np.ndarray, edges: np.ndarray) -> dict[str, Any]:
    """Percentiles, mean and clamped histogram of ``values`` (float64 arithmetic)."""
    v = values.astype(np.float64)
    result: dict[str, Any] = {
        f"p{p}": float(x)
        for p, x in zip(
            DISTRIBUTION_PERCENTILES, np.percentile(v, DISTRIBUTION_PERCENTILES), strict=True
        )
    }
    result["mean"] = float(v.mean())
    counts, _ = np.histogram(np.clip(v, edges[0], edges[-1]), bins=edges)
    result["histogram"] = {
        "bin_edges": [float(e) for e in edges],
        "counts": [int(c) for c in counts],
    }
    return result


def out_of_range(values: np.ndarray, lo: float, hi: float) -> tuple[int, int]:
    """Counts below ``lo`` and above ``hi`` in float64, the precision used for clamping."""
    v = values.astype(np.float64)
    return int((v < lo).sum()), int((v > hi).sum())


def optional_zone(values: np.ndarray, edges: np.ndarray) -> dict[str, Any] | None:
    """Like ``zone`` but ``None`` when the group is empty (sensitivity variants only)."""
    return zone(values, edges) if values.size else None


def zone(values: np.ndarray, edges: np.ndarray) -> dict[str, Any]:
    return {
        "valid_pixels": int(values.size),
        "area_ha": values.size * PIXEL_AREA_M2 / 10_000,
        "change_index": distribution(values, edges),
    }


# --------------------------------------------------------------------------- inputs


def _load(path: Path) -> dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StatsError(f"cannot read {path.name}: {exc}") from exc
    if not isinstance(doc, dict):
        raise StatsError(f"{path.name}: top level must be an object")
    return doc


def _get(doc: Mapping[str, Any], path: str | tuple[str, ...], source: str) -> Any:
    keys = (path,) if isinstance(path, str) else path
    node: Any = doc
    for key in keys:
        if not isinstance(node, Mapping) or key not in node:
            raise StatsError(f"{source}: missing '{'.'.join(keys)}'")
        node = node[key]
    return node


def _grid(doc: Mapping[str, Any], source: str) -> dict[str, Any]:
    grid = _get(doc, "grid", source)
    transform = _get(grid, "transform", source)
    width, height = _get(grid, "width", source), _get(grid, "height", source)
    if not (
        isinstance(transform, list)
        and len(transform) == 6
        and all(isinstance(v, int | float) and not isinstance(v, bool) for v in transform)
        and isinstance(width, int)
        and isinstance(height, int)
        and width > 0
        and height > 0
    ):
        raise StatsError(f"{source}: malformed grid")
    return {"transform": [float(v) for v in transform], "width": width, "height": height}


def _record(doc: Mapping[str, Any], path: tuple[str, ...], source: str) -> tuple[str, str]:
    record = _get(doc, path, source)
    if not isinstance(record, Mapping):
        raise StatsError(f"{source}: '{'.'.join(path)}' must be an object")
    file, sha = record.get("file"), record.get("sha256")
    if not isinstance(file, str) or not (isinstance(sha, str) and len(sha) == 64):
        raise StatsError(f"{source}: '{'.'.join(path)}' needs 'file' and a sha256")
    return file, sha


def _read(directory: Path, record: tuple[str, str], grid: Mapping[str, Any], dtype: str):
    try:
        return read_checked(directory / record[0], record[1], grid, dtype)
    except ChangeError as exc:
        raise StatsError(str(exc)) from exc


def check_output_dir(output_dir: Path) -> None:
    if output_dir.exists():
        if not output_dir.is_dir():
            raise StatsError(f"output_dir {output_dir.name} is not a directory")
        foreign = sorted(p.name for p in output_dir.iterdir() if p.name not in OUTPUT_FILES)
        if foreign:
            raise StatsError(
                f"output_dir {output_dir.name} holds files this stage does not own: {foreign}"
            )


# --------------------------------------------------------------------------- run


def run_stats(
    change_dir: Path, sar_dir: Path, perimeter_dir: Path, output_dir: Path
) -> dict[str, Any]:
    """Compute the statistics and return the ``stats.json`` document written."""
    inputs = (change_dir, sar_dir, perimeter_dir)
    if any(output_dir.resolve() == d.resolve() for d in inputs):
        raise StatsError("output_dir must differ from the input directories")
    check_output_dir(output_dir)
    change = _load(change_dir / "change.json")
    sar = _load(sar_dir / "sar.json")
    perimeter = _load(perimeter_dir / "perimeter.json")

    for doc, source in ((change, "change.json"), (sar, "sar.json"), (perimeter, "perimeter.json")):
        key, version = SUPPORTED_INPUT_VERSIONS[source]
        if doc.get(key) != version:
            raise StatsError(f"{source}: unsupported {key} {doc.get(key)!r}")
    # Same generation: the change index must have been computed from this sar.json.
    linked = _get(change, ("source_sar", "sha256"), "change.json")
    actual_sar = sha256_file(sar_dir / "sar.json")
    if linked != actual_sar:
        raise StatsError(
            "change.json was computed from another sar.json (source_sar sha256 differs); "
            "re-run CH-01 on these DT-02 outputs"
        )
    method_id = _get(change, ("method", "id"), "change.json")
    if method_id != EXPECTED_METHOD_ID:
        raise StatsError(f"change.json: method {method_id!r} is not {EXPECTED_METHOD_ID}")
    rasterization = _get(perimeter, ("rasterization",), "perimeter.json")
    for key, expected in EXPECTED_RASTERIZATION.items():
        value = rasterization.get(key) if isinstance(rasterization, Mapping) else None
        if value != expected:
            raise StatsError(
                f"perimeter.json: rasterization.{key} is {value!r}, expected {expected!r} "
                "(decisions C/E1)"
            )

    grid = _grid(change, "change.json")
    for doc, source in ((sar, "sar.json"), (perimeter, "perimeter.json")):
        if _grid(doc, source) != grid:
            raise StatsError(f"{source}: grid differs from change.json")

    index = _read(
        change_dir, _record(change, ("outputs", "change_index"), "change.json"), grid, "float32"
    )
    valid = _read(sar_dir, _record(sar, ("valid_mask",), "sar.json"), grid, "uint8")
    inside = _read(
        perimeter_dir,
        _record(perimeter, ("outputs", "perimeter_mask.tif"), "perimeter.json"),
        grid,
        "uint8",
    )
    edge = _read(
        perimeter_dir,
        _record(perimeter, ("outputs", "perimeter_edge.tif"), "perimeter.json"),
        grid,
        "uint8",
    )
    for name, mask in (("valid_mask", valid), ("perimeter_mask", inside), ("perimeter_edge", edge)):
        if not np.isin(mask, (0, 1)).all():
            raise StatsError(f"{name}: values must be 0 or 1")

    is_valid = valid.astype(bool)
    bad = int((~np.isfinite(index[is_valid])).sum())
    if bad:
        raise StatsError(f"change_index: {bad} non-finite value(s) where valid_mask = 1")
    is_inside = is_valid & inside.astype(bool)
    is_outside = is_valid & ~inside.astype(bool)
    for label, sel in (("inside", is_inside), ("outside", is_outside)):
        if not sel.any():
            raise StatsError(f"no valid pixels {label} the perimeter; statistics are undefined")

    all_values = index[is_valid].astype(np.float64)
    lo, hi = histogram_range(all_values)
    edges = np.linspace(lo, hi, N_BINS + 1)
    total = int(index.size)
    groups = {"all": is_valid, "inside": is_inside, "outside": is_outside}

    document: dict[str, Any] = {
        "contract_version": CONTRACT_VERSION,
        "data_status": "real",
        "valid_pixels": int(is_valid.sum()),
        "total_pixels": total,
        "valid_coverage_pct": 100.0 * int(is_valid.sum()) / total,
        "pixel_area_m2": PIXEL_AREA_M2,
        "change_index": distribution(all_values, edges),
        "inside_perimeter": zone(index[is_inside], edges),
        "outside_perimeter": zone(index[is_outside], edges),
        "highlight": None,
    }
    not_edge = ~edge.astype(bool)
    meta: dict[str, Any] = {
        "stats_format_version": STATS_FORMAT_VERSION,
        "inputs": {
            "change.json": sha256_file(change_dir / "change.json"),
            "sar.json": actual_sar,
            "perimeter.json": sha256_file(perimeter_dir / "perimeter.json"),
        },
        "method_id": change.get("method", {}).get("id")
        if isinstance(change.get("method"), dict)
        else None,
        "domain": {
            "valid": "DT-02 valid_mask == 1 (all four inputs finite, > 0, not nodata)",
            "coverage_denominator": "all pixels of the DT-01 crop",
            "inside": "valid and DT-03 pixel-centre perimeter mask == 1 (edge band included)",
            "outside": "valid and perimeter mask == 0 (open water included)",
        },
        "percentiles": "NumPy linear interpolation over float32 index values, float64 arithmetic",
        "histogram": {
            "bins": N_BINS,
            "range_percentiles": list(RANGE_PERCENTILES),
            "range": [lo, hi],
            "rule": "shared edges; values outside the range are counted in the first/last bin",
            "below_range": {k: out_of_range(index[s], lo, hi)[0] for k, s in groups.items()},
            "above_range": {k: out_of_range(index[s], lo, hi)[1] for k, s in groups.items()},
        },
        "sensitivity": {
            "without_edge_band": {
                "note": "pixels in the DT-03 50 m boundary band removed; not in stats.json",
                "empty_group": "null when no valid pixel of the group lies outside the band",
                "inside_perimeter": optional_zone(index[is_inside & not_edge], edges),
                "outside_perimeter": optional_zone(index[is_outside & not_edge], edges),
            }
        },
    }

    staging, _ = _staging_dirs(output_dir)
    try:
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True)
        _write_json(staging / "stats.json", document)
        meta["outputs"] = {"stats.json": sha256_file(staging / "stats.json")}
        _write_json(staging / "stats_meta.json", meta)
        publish(staging, output_dir)
    except SarError as exc:
        raise StatsError(str(exc)) from exc
    except OSError as exc:
        raise StatsError(f"cannot write outputs: {exc}") from exc
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
    return document


def _write_json(path: Path, document: Mapping[str, Any]) -> None:
    text = json.dumps(document, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False)
    path.write_text(text + "\n", encoding="utf-8", newline="\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m pipeline.stats",
        description="Observed change statistics inside/outside the reference perimeter.",
    )
    parser.add_argument("--change-dir", type=Path, default=Path("data/interim/change"))
    parser.add_argument("--sar-dir", type=Path, default=Path("data/interim/sar"))
    parser.add_argument("--perimeter-dir", type=Path, default=Path("data/interim/perimeter"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/interim/stats"))
    args = parser.parse_args(argv)
    try:
        doc = run_stats(args.change_dir, args.sar_dir, args.perimeter_dir, args.output_dir)
    except StatsError as exc:
        print(f"stats error: {exc}", file=sys.stderr)
        return 2
    i, o = doc["inside_perimeter"], doc["outside_perimeter"]
    print(
        f"stats ok: {doc['valid_pixels']}/{doc['total_pixels']} valid; inside {i['area_ha']} ha "
        f"median {i['change_index']['p50']:.2f}; outside {o['area_ha']} ha "
        f"median {o['change_index']['p50']:.2f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
