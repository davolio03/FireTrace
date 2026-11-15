"""Exploratory "Highlighted radar changes" mask and its perimeter agreement (XP-01, P1, F05).

Turns the CH-01 continuous change index into an optional binary mask with a documented
threshold, and measures how much it overlaps the DT-03 reference perimeter. The mask is an
exploratory view of *where the radar change is large*; it is not burned area, burn severity
or a validated classification, and the IoU is agreement with a dated reference perimeter,
not accuracy.

Rules (agreed with David, 2026-11-15):

- A1: fixed a-priori threshold on the smoothed robust z-score, ``smoothed >= threshold``
  (2.0 for Plaskett). It is never tuned on the IoU; the threshold sweep is XP-02.
- B2: before thresholding, a ``window x window`` mean over valid pixels only (3 x 3), with
  only in-bounds neighbours; an invalid pixel stays invalid. Afterwards, connected regions
  (8-connectivity) smaller than ``min_region_px`` (100 px = 1 ha) are removed.
- C1: agreement is measured over valid pixels only; unavailable pixels are never counted as
  measured negatives. The 50 m boundary band and open water are included, as in CH-02; a
  variant without the band is recorded in ``highlight_meta.json``.
- D1: this stage publishes its own outputs; DT-04 merges them into the web bundle only when
  ``highlight_meta.json`` exists.

Outputs in ``output_dir``: ``highlight_mask.tif`` (uint8 COG: 1 highlighted, 0 not,
255 invalid), ``highlight.json`` (exactly the ``stats.highlight`` contract block) and
``highlight_meta.json`` (parameters, input hashes, regions, pixel counts, sensitivity).

Run from the repository root::

    uv run python -m pipeline.highlight --config pipeline/configs/highlight_plaskett.toml
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np
from affine import Affine
from skimage.measure import label

from pipeline import publishing, stats
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
from pipeline.stats import StatsError

HIGHLIGHT_FORMAT_VERSION = 1
MASK_NODATA = 255
PIXEL_AREA_M2 = ANALYSIS_PIXEL_SIZE_M * ANALYSIS_PIXEL_SIZE_M
CONNECTIVITY = {4: 1, 8: 2}  # neighbourhood size -> skimage connectivity (2-D)
CONFIG_KEYS = frozenset(
    {
        "threshold",
        "smoothing_window",
        "min_region_px",
        "connectivity",
        "change_dir",
        "sar_dir",
        "perimeter_dir",
        "output_dir",
    }
)
OUTPUT_FILES: frozenset[str] = frozenset(
    {"highlight_mask.tif", "highlight.json", "highlight_meta.json"}
)


class HighlightError(Exception):
    """Raised for any input or numerical condition that prevents a faithful mask."""


@dataclass(frozen=True)
class HighlightParams:
    threshold: float
    window: int
    min_region_px: int
    connectivity: int


@dataclass(frozen=True)
class HighlightConfig:
    params: HighlightParams
    change_dir: Path
    sar_dir: Path
    perimeter_dir: Path
    output_dir: Path


# --------------------------------------------------------------------------- core


def smooth_valid(index: np.ndarray, valid: np.ndarray, window: int) -> np.ndarray:
    """Mean of the valid, in-bounds pixels in a ``window x window`` box (float64).

    Invalid pixels are NaN in the result and never contribute to a neighbour's mean, whatever
    value they hold. ``window = 1`` returns the valid values unchanged.
    """
    if window < 1 or window % 2 == 0:
        raise HighlightError(f"smoothing window must be a positive odd integer, got {window}")
    valid = valid.astype(bool)
    values = np.where(valid, index.astype(np.float64), 0.0)
    if window == 1:
        return np.where(valid, values, np.nan)
    r = window // 2
    box = (window, window)
    sums = np.lib.stride_tricks.sliding_window_view(np.pad(values, r), box).sum(axis=(-2, -1))
    counts = np.lib.stride_tricks.sliding_window_view(np.pad(valid.astype(np.float64), r), box).sum(
        axis=(-2, -1)
    )
    # A valid pixel always counts itself, so counts >= 1 wherever the result is used.
    return np.where(valid, sums / np.maximum(counts, 1.0), np.nan)


def threshold_mask(smoothed: np.ndarray, threshold: float) -> np.ndarray:
    """``smoothed >= threshold``; NaN (invalid) pixels are never highlighted."""
    with np.errstate(invalid="ignore"):
        return np.isfinite(smoothed) & (smoothed >= threshold)


def remove_small_regions(
    mask: np.ndarray, min_px: int, connectivity: int
) -> tuple[np.ndarray, list[int], int]:
    """Drop connected regions smaller than ``min_px``.

    Returns the kept mask, the kept region sizes (largest first) and the number of regions
    removed.
    """
    if connectivity not in CONNECTIVITY:
        raise HighlightError(f"connectivity must be 4 or 8, got {connectivity}")
    labels = label(mask.astype(bool), connectivity=CONNECTIVITY[connectivity])
    sizes = np.bincount(labels.ravel())
    sizes[0] = 0  # background
    keep = sizes >= min_px
    keep[0] = False
    kept = keep[labels]
    kept_sizes = sorted((int(s) for s in sizes[keep]), reverse=True)
    removed = int(((sizes > 0) & ~keep).sum())
    return kept, kept_sizes, removed


def agreement(highlighted: np.ndarray, inside: np.ndarray, domain: np.ndarray) -> dict[str, Any]:
    """Pixel counts and IoU of the highlight against the perimeter, within ``domain`` only.

    Also the two shares that IoU mixes, so a low IoU can be read correctly:

    - ``highlighted_inside_pct``: share of highlighted pixels inside the perimeter (None when
      nothing is highlighted: undefined, not 0 %);
    - ``reference_covered_pct``: share of perimeter pixels that are highlighted;
    - ``iou_upper_bound``: ``min(H, P) / max(H, P)``, the best IoU two areas of these sizes
      could reach with perfect overlap.
    """
    h = highlighted.astype(bool) & domain.astype(bool)
    p = inside.astype(bool) & domain.astype(bool)
    if not p.any():
        raise HighlightError("no valid pixel inside the perimeter; agreement is undefined")
    intersection = int((h & p).sum())
    union = int((h | p).sum())
    h_px, p_px = int(h.sum()), int(p.sum())
    return {
        "domain_px": int(domain.astype(bool).sum()),
        "highlighted_px": h_px,
        "inside_px": intersection,
        "outside_px": int((h & ~p).sum()),
        "reference_px": p_px,
        "intersection_px": intersection,
        "union_px": union,
        "iou": intersection / union,
        "highlighted_inside_pct": 100.0 * intersection / h_px if h_px else None,
        "reference_covered_pct": 100.0 * intersection / p_px,
        "iou_upper_bound": min(h_px, p_px) / max(h_px, p_px),
    }


def _ha(pixels: int) -> float:
    return pixels * PIXEL_AREA_M2 / 10_000


def smoothing_label(params: HighlightParams) -> str:
    smooth = (
        "none" if params.window == 1 else f"{params.window}x{params.window} mean over valid pixels"
    )
    return (
        f"{smooth}; {params.connectivity}-connected regions under {params.min_region_px} px "
        f"({_ha(params.min_region_px):g} ha) removed"
    )


# --------------------------------------------------------------------------- config


def load_config(path: Path, base_dir: Path | None = None) -> HighlightConfig:
    """Parse the TOML configuration; relative paths resolve against ``base_dir`` (cwd)."""
    base = Path.cwd() if base_dir is None else base_dir
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise HighlightError(f"config: cannot read {path.name}: {exc}") from exc
    unknown = sorted(set(raw) - CONFIG_KEYS)
    if unknown:
        raise HighlightError(f"config: unknown key(s) {unknown}")

    def integer(key: str) -> int:
        value = raw.get(key)
        if not isinstance(value, int) or isinstance(value, bool):
            raise HighlightError(f"config: '{key}' must be an integer, got {value!r}")
        return value

    threshold = raw.get("threshold")
    if (
        not isinstance(threshold, int | float)
        or isinstance(threshold, bool)
        or not math.isfinite(threshold)
    ):
        raise HighlightError(f"config: 'threshold' must be a finite number, got {threshold!r}")
    window = integer("smoothing_window")
    if window < 1 or window % 2 == 0:
        raise HighlightError(
            f"config: 'smoothing_window' must be a positive odd integer ({window})"
        )
    min_region = integer("min_region_px")
    if min_region < 1:
        raise HighlightError(f"config: 'min_region_px' must be at least 1, got {min_region}")
    connectivity = integer("connectivity")
    if connectivity not in CONNECTIVITY:
        raise HighlightError(f"config: 'connectivity' must be 4 or 8, got {connectivity}")

    def resolve(key: str) -> Path:
        value = raw.get(key)
        if not isinstance(value, str) or not value:
            raise HighlightError(f"config: '{key}' must be a non-empty string, got {value!r}")
        p = Path(value)
        return p if p.is_absolute() else base / p

    return HighlightConfig(
        params=HighlightParams(float(threshold), window, min_region, connectivity),
        change_dir=resolve("change_dir"),
        sar_dir=resolve("sar_dir"),
        perimeter_dir=resolve("perimeter_dir"),
        output_dir=resolve("output_dir"),
    )


# --------------------------------------------------------------------------- inputs


class InputDirs(Protocol):
    """The three upstream directories a highlight-style stage reads (also XP-02)."""

    @property
    def change_dir(self) -> Path: ...

    @property
    def sar_dir(self) -> Path: ...

    @property
    def perimeter_dir(self) -> Path: ...


@dataclass(frozen=True)
class Inputs:
    grid: dict[str, Any]
    index: np.ndarray
    valid: np.ndarray
    inside: np.ndarray
    edge: np.ndarray
    shas: dict[str, str]
    method_id: str


def _manifest(path: Path) -> tuple[dict[str, Any], str]:
    """Parse a JSON manifest and return it with the sha256 of the exact bytes parsed."""
    try:
        payload = path.read_bytes()
        doc = json.loads(payload.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HighlightError(f"cannot read {path.name}: {exc}") from exc
    if not isinstance(doc, dict):
        raise HighlightError(f"{path.name}: top level must be an object")
    return doc, hashlib.sha256(payload).hexdigest()


def load_inputs(config: InputDirs) -> Inputs:
    """Read CH-01, DT-02 and DT-03 products and check versions, linkage, grids and hashes.

    The checks are the CH-02 ones (``pipeline.stats``), so both stages accept exactly the
    same upstream generation. Each manifest is hashed from the same bytes that were parsed.
    """
    change, change_sha = _manifest(config.change_dir / "change.json")
    sar, sar_sha = _manifest(config.sar_dir / "sar.json")
    perimeter, perimeter_sha = _manifest(config.perimeter_dir / "perimeter.json")
    try:
        for doc, source in (
            (change, "change.json"),
            (sar, "sar.json"),
            (perimeter, "perimeter.json"),
        ):
            key, version = stats.SUPPORTED_INPUT_VERSIONS[source]
            if doc.get(key) != version:
                raise HighlightError(f"{source}: unsupported {key} {doc.get(key)!r}")
        if stats._get(change, ("source_sar", "sha256"), "change.json") != sar_sha:
            raise HighlightError(
                "change.json was computed from another sar.json (source_sar sha256 differs); "
                "re-run CH-01 on these DT-02 outputs"
            )
        method_id = stats._get(change, ("method", "id"), "change.json")
        if method_id != stats.EXPECTED_METHOD_ID:
            raise HighlightError(
                f"change.json: method {method_id!r} is not {stats.EXPECTED_METHOD_ID}"
            )
        rasterization = stats._get(perimeter, ("rasterization",), "perimeter.json")
        for key, expected in stats.EXPECTED_RASTERIZATION.items():
            value = rasterization.get(key) if isinstance(rasterization, Mapping) else None
            if value != expected:
                raise HighlightError(
                    f"perimeter.json: rasterization.{key} is {value!r}, expected {expected!r}"
                )
        grid = stats._grid(change, "change.json")
        for doc, source in ((sar, "sar.json"), (perimeter, "perimeter.json")):
            if stats._grid(doc, source) != grid:
                raise HighlightError(f"{source}: grid differs from change.json")

        def read(
            directory: Path,
            doc: Mapping[str, Any],
            path: tuple[str, ...],
            dtype: str,
            manifest: str,
        ) -> np.ndarray:
            return stats._read(directory, stats._record(doc, path, manifest), grid, dtype, manifest)

        index = read(
            config.change_dir, change, ("outputs", "change_index"), "float32", "change.json"
        )
        valid = read(config.sar_dir, sar, ("valid_mask",), "uint8", "sar.json")
        inside = read(
            config.perimeter_dir,
            perimeter,
            ("outputs", "perimeter_mask.tif"),
            "uint8",
            "perimeter.json",
        )
        edge = read(
            config.perimeter_dir,
            perimeter,
            ("outputs", "perimeter_edge.tif"),
            "uint8",
            "perimeter.json",
        )
        shas = {
            "change.json": change_sha,
            "sar.json": sar_sha,
            "perimeter.json": perimeter_sha,
        }
    except (StatsError, SarError) as exc:
        raise HighlightError(str(exc)) from exc
    except OSError as exc:
        raise HighlightError(f"cannot read inputs: {exc}") from exc

    for name, mask in (("valid_mask", valid), ("perimeter_mask", inside), ("perimeter_edge", edge)):
        if not np.isin(mask, (0, 1)).all():
            raise HighlightError(f"{name}: values must be 0 or 1")
    is_valid = valid.astype(bool)
    bad = int((~np.isfinite(index[is_valid])).sum())
    if bad:
        raise HighlightError(f"change_index: {bad} non-finite value(s) where valid_mask = 1")
    return Inputs(
        grid=grid,
        index=index,
        valid=is_valid,
        inside=inside.astype(bool),
        edge=edge.astype(bool),
        shas=shas,
        method_id=str(method_id),
    )


def check_output_dir(output_dir: Path) -> None:
    """Only missing or fully owned output, staging and backup directories may be replaced."""
    try:
        publishing.check_output_dir(output_dir, OUTPUT_FILES)
    except PublishError as exc:
        raise HighlightError(str(exc)) from exc


# --------------------------------------------------------------------------- run


def run_highlight(config: HighlightConfig) -> dict[str, Any]:
    """Build and publish the mask; return the ``highlight.json`` contract block written."""
    inputs_dirs = (config.change_dir, config.sar_dir, config.perimeter_dir)
    try:
        clash = overlapping_input(config.output_dir, inputs_dirs)
    except SarError as exc:
        raise HighlightError(str(exc)) from exc
    if clash is not None:
        raise HighlightError("output_dir must differ from the input directories")
    check_output_dir(config.output_dir)
    inputs = load_inputs(config)
    params = config.params

    smoothed = smooth_valid(inputs.index, inputs.valid, params.window)
    raw = threshold_mask(smoothed, params.threshold)
    highlighted, sizes, removed = remove_small_regions(
        raw, params.min_region_px, params.connectivity
    )
    main_agreement = agreement(highlighted, inputs.inside, inputs.valid)
    try:
        no_edge: dict[str, Any] | None = agreement(
            highlighted, inputs.inside, inputs.valid & ~inputs.edge
        )
    except HighlightError:
        no_edge = None

    block = {
        "threshold": params.threshold,
        "smoothing": smoothing_label(params),
        "area_ha": _ha(main_agreement["highlighted_px"]),
        "inside_ha": _ha(main_agreement["inside_px"]),
        "outside_ha": _ha(main_agreement["outside_px"]),
        "iou_vs_perimeter": main_agreement["iou"],
    }
    mask = np.where(inputs.valid, highlighted.astype(np.uint8), MASK_NODATA).astype(np.uint8)
    meta: dict[str, Any] = {
        "highlight_format_version": HIGHLIGHT_FORMAT_VERSION,
        "inputs": inputs.shas,
        "method_id": inputs.method_id,
        "grid": {"crs": ANALYSIS_CRS.to_string(), **inputs.grid},
        "parameters": {
            "threshold": params.threshold,
            "window": params.window,
            "min_region_px": params.min_region_px,
            "connectivity": params.connectivity,
        },
        "rule": (
            "valid-only window mean of the CH-01 index (in-bounds neighbours), then "
            "smoothed >= threshold, then connected regions under min_region_px removed; "
            "fixed a priori, never tuned on the IoU"
        ),
        "domain": {
            "valid": "DT-02 valid_mask == 1; invalid pixels are 255 in the mask and never "
            "counted as measured negatives",
            "reference": "DT-03 pixel-centre perimeter mask == 1 (edge band included)",
            "outside": "valid and perimeter mask == 0 (open water included)",
            "iou": "intersection / union of highlighted and reference pixels, valid pixels only",
        },
        "regions": {
            "count": len(sizes),
            "removed_count": removed,
            "removed_px": int(raw.sum() - highlighted.sum()),
            "sizes_px": sizes,
        },
        "before_region_filter_px": int(raw.sum()),
        "agreement": main_agreement,
        "sensitivity": {
            "without_edge_band": no_edge,
            "note": "DT-03 50 m boundary band removed from the domain; null when no reference "
            "pixel is left; not in highlight.json",
        },
        "interpretation": "Exploratory highlighted radar change, not burned area or severity. "
        "IoU is agreement with the WFIGS perimeter dated 2026-09-14 (before the after scene), "
        "not accuracy.",
    }

    staging, _ = _staging_dirs(config.output_dir)
    try:
        clear_staging(staging, OUTPUT_FILES)
        staging.mkdir(parents=True)
        write_cog(
            staging / "highlight_mask.tif",
            mask,
            crs=ANALYSIS_CRS,
            transform=Affine(*inputs.grid["transform"]),
            nodata=MASK_NODATA,
        )
        _write_json(staging / "highlight.json", block)
        meta["outputs"] = {
            name: {"file": name, "sha256": sha256_file(staging / name)}
            for name in ("highlight.json", "highlight_mask.tif")
        }
        _write_json(staging / "highlight_meta.json", meta)
        publish(staging, config.output_dir, OUTPUT_FILES, "highlight")
    except SarError as exc:
        raise HighlightError(str(exc)) from exc
    except OSError as exc:
        raise HighlightError(f"cannot write outputs: {exc}") from exc
    finally:
        discard_staging(staging, OUTPUT_FILES)
    return block


def _write_json(path: Path, document: Mapping[str, Any]) -> None:
    text = json.dumps(document, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False)
    path.write_text(text + "\n", encoding="utf-8", newline="\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m pipeline.highlight",
        description="Exploratory highlighted radar change mask and perimeter agreement (P1).",
    )
    parser.add_argument(
        "--config", type=Path, default=Path("pipeline/configs/highlight_plaskett.toml")
    )
    args = parser.parse_args(argv)
    try:
        block = run_highlight(load_config(args.config))
    except HighlightError as exc:
        print(f"highlight error: {exc}", file=sys.stderr)
        return 2
    print(
        f"highlight ok: {block['area_ha']:.2f} ha highlighted ({block['inside_ha']:.2f} inside, "
        f"{block['outside_ha']:.2f} outside the perimeter); IoU {block['iou_vs_perimeter']:.3f}; "
        f"{block['smoothing']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
