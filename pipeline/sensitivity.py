"""Sensitivity of the exploratory highlight to threshold, smoothing and polarization (XP-02).

Repeats the XP-01 rules (``pipeline.highlight``: valid-only window mean, ``>= threshold``,
connected regions under ``min_region_px`` removed, agreement over valid pixels only) over a
grid of thresholds, smoothing windows and three change indices, and records how the area,
the inside/outside split and the IoU against the reference perimeter move.

It describes; it never picks a "best" threshold, and nothing here feeds back into the
XP-01 operating point (combined index, window 3, threshold 2.0), which stays fixed a priori.
IoU is agreement with the dated WFIGS perimeter, not accuracy; nothing is burned area.

Decisions (agreed with David, 2026-11-15):

- A: indices on one scale. ``combined`` is the CH-01 index; ``hh`` and ``hv`` are the
  robust z-score of ``|change|`` per polarization (median and 1.4826 x MAD over all valid
  crop pixels, the CH-01 rule applied to each polarization on its own).
- B: thresholds 0.50 to 5.00 in steps of 0.25, always including 2.0.
- C: windows 1, 3 and 5, each followed by the region filter.
- D: each point also reports the IoU upper bound ``min(H, P) / max(H, P)`` and a chance
  baseline for a same-area mask placed uniformly at random over the valid domain. The
  baseline is a ratio of expectations, ``I / (H + P - I)`` with ``I = H * P / N``: a
  reference value for comparison, neither a lower bound nor the exact expected IoU.
- E: no plotting dependency; outputs are JSON and CSV for DL-02.

Run from the repository root::

    uv run python -m pipeline.sensitivity --config pipeline/configs/sensitivity_plaskett.toml
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import sys
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from pipeline import highlight, publishing, stats
from pipeline.change import MAD_SCALE, ChangeError, robust_stats, robust_z
from pipeline.highlight import (
    CONNECTIVITY,
    HighlightError,
    agreement,
    remove_small_regions,
    smooth_valid,
    threshold_mask,
)
from pipeline.publishing import PublishError
from pipeline.sar import (
    ANALYSIS_PIXEL_SIZE_M,
    SarError,
    _staging_dirs,
    clear_staging,
    discard_staging,
    overlapping_input,
    publish,
)
from pipeline.stats import StatsError

SENSITIVITY_FORMAT_VERSION = 1
XP01_THRESHOLD = 2.0
XP01_WINDOW = 3
XP01_MIN_REGION_PX = 100
XP01_CONNECTIVITY = 8
MAX_THRESHOLDS = 1000
INDEX_NAMES: tuple[str, ...] = ("combined", "hh", "hv")
PIXEL_AREA_M2 = ANALYSIS_PIXEL_SIZE_M * ANALYSIS_PIXEL_SIZE_M
OUTPUT_FILES: frozenset[str] = frozenset({"sensitivity.json", "sensitivity.csv"})
CSV_COLUMNS: tuple[str, ...] = (
    "index",
    "window",
    "threshold",
    "area_ha",
    "inside_ha",
    "outside_ha",
    "iou",
    "iou_upper_bound",
    "iou_chance",
    "highlighted_inside_pct",
    "reference_covered_pct",
    "regions",
    "iou_without_edge_band",
    "xp01_operating_point",
)
CONFIG_KEYS = frozenset(
    {
        "threshold_min",
        "threshold_max",
        "threshold_step",
        "windows",
        "min_region_px",
        "connectivity",
        "change_dir",
        "sar_dir",
        "perimeter_dir",
        "output_dir",
    }
)


class SensitivityError(Exception):
    """Raised for any input or configuration condition that prevents a faithful sweep."""


@dataclass(frozen=True)
class SensitivityConfig:
    thresholds: list[float]
    windows: tuple[int, ...]
    min_region_px: int
    connectivity: int
    change_dir: Path
    sar_dir: Path
    perimeter_dir: Path
    output_dir: Path


# --------------------------------------------------------------------------- core


def threshold_grid(start: float, stop: float, step: float) -> list[float]:
    """``start, start + step, ... <= stop``, rounded to 10 decimals; must contain 2.0.

    At most ``MAX_THRESHOLDS`` values, all distinct after rounding.
    """
    if not all(math.isfinite(v) for v in (start, stop, step)):
        raise SensitivityError("threshold_min, threshold_max and threshold_step must be finite")
    if not step > 0:
        raise SensitivityError(f"threshold_step must be positive, got {step}")
    if not stop >= start:
        raise SensitivityError(f"threshold_max {stop} is below threshold_min {start}")
    ratio = (stop - start) / step
    if not math.isfinite(ratio) or ratio >= MAX_THRESHOLDS:
        raise SensitivityError(f"threshold grid has too many values (limit {MAX_THRESHOLDS})")
    count = math.floor(round(ratio, 9)) + 1
    grid = [round(start + k * step, 10) + 0.0 for k in range(count)]
    if len(set(grid)) != len(grid):
        raise SensitivityError("threshold grid values are not distinct after rounding")
    if XP01_THRESHOLD not in grid:
        raise SensitivityError(
            f"the threshold grid must include the XP-01 threshold {XP01_THRESHOLD}"
        )
    return grid


def polarization_index(delta: np.ndarray, valid: np.ndarray) -> tuple[np.ndarray, float, float]:
    """Robust z-score of ``|delta|`` over valid pixels (CH-01 rule, one polarization).

    Returns the float64 index (NaN where invalid), the median and the unscaled MAD.
    """
    magnitude = np.where(valid, np.abs(delta.astype(np.float64)), np.nan)
    try:
        median, mad = robust_stats(magnitude)
    except ChangeError as exc:
        raise SensitivityError(str(exc)) from exc
    return robust_z(magnitude, median, mad), median, mad


def chance_iou(highlighted_px: int, reference_px: int, domain_px: int) -> float:
    """Chance baseline for ``highlighted_px`` pixels placed uniformly over ``domain_px``.

    The expected intersection with ``reference_px`` reference pixels is ``I = H * P / N``,
    and the baseline is the ratio of expectations ``I / (H + P - I)`` (decision D). It is a
    reference value for comparison: a random placement can score lower (even 0), and it is
    not the exact expected IoU (for H = P = 1, N = 2 it gives 1/3; the expected IoU is 1/2).
    """
    if highlighted_px == 0:
        return 0.0
    intersection = highlighted_px * reference_px / domain_px
    return intersection / (highlighted_px + reference_px - intersection)


def _ha(pixels: int) -> float:
    return pixels * PIXEL_AREA_M2 / 10_000


def sweep_point(
    smoothed: np.ndarray,
    threshold: float,
    inputs: highlight.Inputs,
    min_region_px: int,
    connectivity: int,
) -> dict[str, Any]:
    """One (index, window, threshold) point with the XP-01 rules."""
    raw = threshold_mask(smoothed, threshold)
    kept, sizes, _ = remove_small_regions(raw, min_region_px, connectivity)
    result = agreement(kept, inputs.inside, inputs.valid)
    try:
        no_edge: float | None = agreement(kept, inputs.inside, inputs.valid & ~inputs.edge)["iou"]
    except HighlightError:
        no_edge = None
    return {
        "area_ha": _ha(result["highlighted_px"]),
        "inside_ha": _ha(result["inside_px"]),
        "outside_ha": _ha(result["outside_px"]),
        "iou": result["iou"],
        "iou_upper_bound": result["iou_upper_bound"],
        "iou_chance": chance_iou(
            result["highlighted_px"], result["reference_px"], result["domain_px"]
        ),
        "highlighted_inside_pct": result["highlighted_inside_pct"],
        "reference_covered_pct": result["reference_covered_pct"],
        "regions": len(sizes),
        "iou_without_edge_band": no_edge,
    }


# --------------------------------------------------------------------------- config


def load_config(path: Path, base_dir: Path | None = None) -> SensitivityConfig:
    """Parse the TOML configuration; relative paths resolve against ``base_dir`` (cwd)."""
    base = Path.cwd() if base_dir is None else base_dir
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise SensitivityError(f"config: cannot read {path.name}: {exc}") from exc
    unknown = sorted(set(raw) - CONFIG_KEYS)
    if unknown:
        raise SensitivityError(f"config: unknown key(s) {unknown}")

    def number(key: str) -> float:
        value = raw.get(key)
        if (
            not isinstance(value, int | float)
            or isinstance(value, bool)
            or not math.isfinite(value)
        ):
            raise SensitivityError(f"config: '{key}' must be a finite number, got {value!r}")
        return float(value)

    def integer(key: str) -> int:
        value = raw.get(key)
        if not isinstance(value, int) or isinstance(value, bool):
            raise SensitivityError(f"config: '{key}' must be an integer, got {value!r}")
        return value

    thresholds = threshold_grid(
        number("threshold_min"), number("threshold_max"), number("threshold_step")
    )
    windows = raw.get("windows")
    if (
        not isinstance(windows, list)
        or not windows
        or not all(isinstance(w, int) and not isinstance(w, bool) for w in windows)
        or len(set(windows)) != len(windows)
    ):
        raise SensitivityError(f"config: 'windows' must be distinct integers, got {windows!r}")
    if any(w < 1 or w % 2 == 0 for w in windows):
        raise SensitivityError(f"config: every window must be a positive odd integer {windows}")
    if XP01_WINDOW not in windows:
        raise SensitivityError(f"config: 'windows' must include the XP-01 window {XP01_WINDOW}")
    min_region = integer("min_region_px")
    if min_region < 1:
        raise SensitivityError(f"config: 'min_region_px' must be at least 1, got {min_region}")
    connectivity = integer("connectivity")
    if connectivity not in CONNECTIVITY:
        raise SensitivityError(f"config: 'connectivity' must be 4 or 8, got {connectivity}")

    def resolve(key: str) -> Path:
        value = raw.get(key)
        if not isinstance(value, str) or not value:
            raise SensitivityError(f"config: '{key}' must be a non-empty string, got {value!r}")
        p = Path(value)
        return p if p.is_absolute() else base / p

    return SensitivityConfig(
        thresholds=thresholds,
        windows=tuple(windows),
        min_region_px=min_region,
        connectivity=connectivity,
        change_dir=resolve("change_dir"),
        sar_dir=resolve("sar_dir"),
        perimeter_dir=resolve("perimeter_dir"),
        output_dir=resolve("output_dir"),
    )


# --------------------------------------------------------------------------- inputs


def load_polarizations(
    config: SensitivityConfig, inputs: highlight.Inputs
) -> dict[str, np.ndarray]:
    """``change_hh_db`` and ``change_hv_db`` from the same ``change.json`` XP-01 checks used."""
    try:
        change, sha = highlight._manifest(config.change_dir / "change.json")
    except HighlightError as exc:
        raise SensitivityError(str(exc)) from exc
    if sha != inputs.shas["change.json"]:
        raise SensitivityError("change.json changed while it was being read; run again")
    layers: dict[str, np.ndarray] = {}
    try:
        for name in ("change_hh_db", "change_hv_db"):
            record = stats._record(change, ("outputs", name), "change.json")
            data = stats._read(config.change_dir, record, inputs.grid, "float32", "change.json")
            bad = int((~np.isfinite(data[inputs.valid])).sum())
            if bad:
                raise SensitivityError(f"{name}: {bad} non-finite value(s) where valid_mask = 1")
            layers[name] = data
    except (StatsError, SarError) as exc:
        raise SensitivityError(str(exc)) from exc
    return layers


# --------------------------------------------------------------------------- run


def run_sensitivity(config: SensitivityConfig) -> dict[str, Any]:
    """Run the sweep, publish ``sensitivity.json`` and ``.csv``; return the JSON document."""
    try:
        clash = overlapping_input(
            config.output_dir, (config.change_dir, config.sar_dir, config.perimeter_dir)
        )
    except SarError as exc:
        raise SensitivityError(str(exc)) from exc
    if clash is not None:
        raise SensitivityError("output_dir must differ from the input directories")
    try:
        publishing.check_output_dir(config.output_dir, OUTPUT_FILES)
        inputs = highlight.load_inputs(config)
    except (PublishError, HighlightError) as exc:
        raise SensitivityError(str(exc)) from exc
    pols = load_polarizations(config, inputs)

    indices: dict[str, np.ndarray] = {"combined": inputs.index}
    normalization: dict[str, Any] = {
        "combined": {"source": "CH-01 change_index.tif", "method_id": inputs.method_id}
    }
    for name, layer in (("hh", "change_hh_db"), ("hv", "change_hv_db")):
        z, median, mad = polarization_index(pols[layer], inputs.valid)
        indices[name] = z
        normalization[name] = {
            "source": f"robust z of |{layer}| over valid crop pixels",
            "median": median,
            "mad": mad,
            "mad_scale": MAD_SCALE,
        }

    # The XP-01 point exists only with the XP-01 region settings (1 ha, 8-connected).
    has_xp01 = (config.min_region_px, config.connectivity) == (
        XP01_MIN_REGION_PX,
        XP01_CONNECTIVITY,
    )
    points: list[dict[str, Any]] = []
    for name in INDEX_NAMES:
        for window in config.windows:
            smoothed = smooth_valid(indices[name], inputs.valid, window)
            for threshold in config.thresholds:
                point = {"index": name, "window": window, "threshold": threshold}
                point.update(
                    sweep_point(
                        smoothed, threshold, inputs, config.min_region_px, config.connectivity
                    )
                )
                point["xp01_operating_point"] = has_xp01 and (name, window, threshold) == (
                    "combined",
                    XP01_WINDOW,
                    XP01_THRESHOLD,
                )
                points.append(point)

    document: dict[str, Any] = {
        "sensitivity_format_version": SENSITIVITY_FORMAT_VERSION,
        "inputs": inputs.shas,
        "parameters": {
            "thresholds": config.thresholds,
            "windows": list(config.windows),
            "min_region_px": config.min_region_px,
            "connectivity": config.connectivity,
            "xp01_operating_point": {
                "index": "combined",
                "window": XP01_WINDOW,
                "threshold": XP01_THRESHOLD,
                "min_region_px": XP01_MIN_REGION_PX,
                "connectivity": XP01_CONNECTIVITY,
            }
            if has_xp01
            else None,
        },
        "indices": normalization,
        "rules": {
            "highlight": "pipeline.highlight rules: valid-only window mean, smoothed >= "
            "threshold, connected regions under min_region_px removed",
            "domain": "valid pixels only; unavailable pixels never count as negatives; DT-03 "
            "50 m edge band and open water included (iou_without_edge_band removes the band)",
            "iou_upper_bound": "min(H, P) / max(H, P): best IoU two areas of these sizes reach",
            "iou_chance": "I / (H + P - I) with I = H * P / N: ratio-of-expectations baseline "
            "for a same-area mask placed uniformly at random over the N valid pixels; a "
            "reference value, neither a lower bound nor the exact expected IoU",
            "interpretation": "Describes sensitivity; does not choose a threshold. IoU is "
            "agreement with the WFIGS perimeter dated 2026-09-14 (before the after scene), "
            "not accuracy; highlighted change is not burned area.",
        },
        "points": points,
    }

    staging, _ = _staging_dirs(config.output_dir)
    try:
        clear_staging(staging, OUTPUT_FILES)
        staging.mkdir(parents=True)
        text = json.dumps(document, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False)
        (staging / "sensitivity.json").write_text(text + "\n", encoding="utf-8", newline="\n")
        (staging / "sensitivity.csv").write_text(_csv(points), encoding="utf-8", newline="\n")
        publish(staging, config.output_dir, OUTPUT_FILES, "sensitivity")
    except SarError as exc:
        raise SensitivityError(str(exc)) from exc
    except OSError as exc:
        raise SensitivityError(f"cannot write outputs: {exc}") from exc
    finally:
        discard_staging(staging, OUTPUT_FILES)
    return document


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return repr(value)
    return str(value)


def _csv(points: Sequence[Mapping[str, Any]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(CSV_COLUMNS)
    for point in points:
        writer.writerow([_cell(point[c]) for c in CSV_COLUMNS])
    return buffer.getvalue()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m pipeline.sensitivity",
        description="Threshold, smoothing and polarization sensitivity of the highlight (P1).",
    )
    parser.add_argument(
        "--config", type=Path, default=Path("pipeline/configs/sensitivity_plaskett.toml")
    )
    args = parser.parse_args(argv)
    try:
        doc = run_sensitivity(load_config(args.config))
    except SensitivityError as exc:
        print(f"sensitivity error: {exc}", file=sys.stderr)
        return 2
    op = next((p for p in doc["points"] if p["xp01_operating_point"]), None)
    if op is None:
        summary = "XP-01 point not in this sweep (different region settings)"
    else:
        summary = (
            f"XP-01 point area {op['area_ha']:.2f} ha, IoU {op['iou']:.3f} "
            f"(chance {op['iou_chance']:.3f}, bound {op['iou_upper_bound']:.3f})"
        )
    print(f"sensitivity ok: {len(doc['points'])} points; {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
