"""XP-01 exploratory highlight mask: hand-computed smoothing, regions, IoU and safety.

Tiny synthetic rasters on the 10 m grid; no real data is used.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import rasterio
from affine import Affine
from jsonschema import Draft202012Validator
from rasterio.crs import CRS

from pipeline import highlight
from pipeline.highlight import (
    HighlightConfig,
    HighlightError,
    HighlightParams,
    agreement,
    load_config,
    main,
    remove_small_regions,
    run_highlight,
    smooth_valid,
    threshold_mask,
)
from pipeline.sar import write_cog

ROOT = Path(__file__).resolve().parents[2]
UTM10N = CRS.from_epsg(32610)
TRANSFORM = Affine(10.0, 0.0, 636_000.0, 0.0, -10.0, 3_983_990.0)
NAN = float("nan")

# 4 x 6 crop. Pixel (3, 5) is invalid (NaN index) but lies inside the perimeter.
INDEX = [
    [5.0, 5.0, 0.0, 0.0, 0.0, 0.0],
    [5.0, 5.0, 0.0, 0.0, 0.0, 5.0],
    [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    [0.0, 0.0, 5.0, 5.0, 0.0, NAN],
]
VALID = [[1] * 6, [1] * 6, [1] * 6, [1, 1, 1, 1, 1, 0]]
INSIDE = [[1, 1, 1, 0, 0, 0]] * 3 + [[1, 1, 1, 0, 0, 1]]
EDGE = [[0, 0, 1, 1, 0, 0]] * 4  # columns 2 and 3 form the boundary band

# Window 1 (no smoothing) and a 2-pixel minimum keep the end-to-end values hand-computable:
# region A = 2x2 block top-left (4 px, inside), B = (1, 5) alone (1 px, removed),
# C = (3, 2)-(3, 3) (2 px: one inside, one outside).
SIMPLE = HighlightParams(threshold=2.0, window=1, min_region_px=2, connectivity=8)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _grid(transform: Affine, shape: tuple[int, int]) -> dict[str, Any]:
    return {
        "crs": "EPSG:32610",
        "transform": list(transform)[:6],
        "width": shape[1],
        "height": shape[0],
    }


def write_inputs(
    root: Path,
    *,
    index: list[list[float]] = INDEX,
    valid: list[list[int]] = VALID,
    inside: list[list[int]] = INSIDE,
    edge: list[list[int]] = EDGE,
    perimeter_transform: Affine = TRANSFORM,
    method_id: str = "abs-logratio-hhhv-v1",
) -> dict[str, Path]:
    """Mimic the CH-01, DT-02 and DT-03 output directories with minimal manifests."""
    shape = (len(index), len(index[0]))
    grid = _grid(TRANSFORM, shape)
    dirs = {name: root / name for name in ("change", "sar", "perimeter")}
    for d in dirs.values():
        d.mkdir(parents=True, exist_ok=True)

    mask_path = dirs["sar"] / "valid_mask.tif"
    write_cog(
        mask_path, np.array(valid, dtype="uint8"), crs=UTM10N, transform=TRANSFORM, nodata=None
    )
    sar_doc = {
        "sar_format_version": 1,
        "grid": grid,
        "valid_mask": {"file": mask_path.name, "sha256": _sha(mask_path)},
    }
    (dirs["sar"] / "sar.json").write_text(json.dumps(sar_doc), encoding="utf-8")

    idx_path = dirs["change"] / "change_index.tif"
    write_cog(
        idx_path, np.array(index, dtype="float32"), crs=UTM10N, transform=TRANSFORM, nodata=NAN
    )
    change_doc = {
        "change_format_version": 1,
        "grid": grid,
        "method": {"id": method_id},
        "source_sar": {"file": "sar.json", "sha256": _sha(dirs["sar"] / "sar.json")},
        "outputs": {"change_index": {"file": idx_path.name, "sha256": _sha(idx_path)}},
    }
    (dirs["change"] / "change.json").write_text(json.dumps(change_doc), encoding="utf-8")

    outputs = {}
    for name, values in (("perimeter_mask.tif", inside), ("perimeter_edge.tif", edge)):
        path = dirs["perimeter"] / name
        data = np.array(values, dtype="uint8")
        write_cog(path, data, crs=UTM10N, transform=perimeter_transform, nodata=None)
        outputs[name] = {"file": name, "sha256": _sha(path)}
    perim_doc = {
        "perimeter_format_version": 1,
        "grid": _grid(perimeter_transform, shape),
        "rasterization": {"rule": "pixel_centre", "all_touched": False, "edge_distance_m": 50.0},
        "outputs": outputs,
    }
    (dirs["perimeter"] / "perimeter.json").write_text(json.dumps(perim_doc), encoding="utf-8")
    return dirs


def config_for(root: Path, params: HighlightParams = SIMPLE, **kwargs: Any) -> HighlightConfig:
    d = write_inputs(root, **kwargs)
    return HighlightConfig(
        params=params,
        change_dir=d["change"],
        sar_dir=d["sar"],
        perimeter_dir=d["perimeter"],
        output_dir=root / "highlight",
    )


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _files(directory: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted(directory.iterdir())}


# --------------------------------------------------------------------------- core functions


def test_smoothing_averages_only_valid_in_bounds_neighbours() -> None:
    index = np.array([[1, 2, 3], [4, 1000, 6], [7, 8, 9]], dtype=np.float32)
    valid = np.array([[1, 1, 1], [1, 0, 1], [1, 1, 1]], dtype=bool)
    out = smooth_valid(index, valid, 3)
    assert out.dtype == np.float64
    assert math.isnan(out[1, 1]), "an invalid pixel stays invalid"
    assert out[0, 0] == pytest.approx(7 / 3)  # 1, 2, 4: the invalid 1000 never leaks in
    assert out[0, 1] == pytest.approx(16 / 5)  # 1, 2, 3, 4, 6
    assert out[1, 0] == pytest.approx(22 / 5)  # 1, 2, 4, 7, 8
    assert out[2, 2] == pytest.approx(23 / 3)  # 6, 8, 9


def test_window_one_is_the_identity_on_valid_pixels() -> None:
    index = np.array([[1.5, NAN], [3.0, 4.0]], dtype=np.float32)
    valid = np.array([[1, 0], [1, 1]], dtype=bool)
    out = smooth_valid(index, valid, 1)
    assert out[0, 0] == 1.5 and out[1, 0] == 3.0 and out[1, 1] == 4.0
    assert math.isnan(out[0, 1])


def test_threshold_is_inclusive_and_never_flags_invalid_pixels() -> None:
    smoothed = np.array([[1.999, 2.0, 2.5, NAN]])
    assert threshold_mask(smoothed, 2.0).tolist() == [[False, True, True, False]]


def test_connectivity_decides_whether_diagonal_pixels_form_one_region() -> None:
    mask = np.array([[1, 0, 0], [0, 1, 0], [0, 0, 0]], dtype=bool)
    kept8, sizes8, removed8 = remove_small_regions(mask, 2, 8)
    assert kept8.tolist() == mask.tolist() and sizes8 == [2] and removed8 == 0
    kept4, sizes4, removed4 = remove_small_regions(mask, 2, 4)
    assert not kept4.any() and sizes4 == [] and removed4 == 2


def test_regions_below_the_minimum_are_removed_and_sizes_sorted() -> None:
    mask = np.zeros((4, 6), dtype=bool)
    mask[0:2, 0:2] = True  # 4 px
    mask[3, 4:6] = True  # 2 px
    mask[1, 5] = True  # 1 px, not touching the 2-px region (row 3 vs row 1)
    kept, sizes, removed = remove_small_regions(mask, 2, 8)
    assert sizes == [4, 2] and removed == 1
    assert kept.sum() == 6 and not kept[1, 5]


def test_agreement_excludes_unavailable_pixels_from_the_union() -> None:
    highlighted = np.array([[1, 1, 0, 0]], dtype=bool)
    inside = np.array([[1, 0, 1, 1]], dtype=bool)
    domain = np.array([[1, 1, 1, 0]], dtype=bool)  # the last inside pixel is unavailable
    result = agreement(highlighted, inside, domain)
    assert result["intersection_px"] == 1 and result["union_px"] == 3
    assert result["iou"] == pytest.approx(1 / 3)
    assert (result["highlighted_px"], result["inside_px"], result["outside_px"]) == (2, 1, 1)
    # 1 of 2 highlighted pixels is inside; 1 of 2 reference pixels is highlighted.
    assert result["highlighted_inside_pct"] == 50.0
    assert result["reference_covered_pct"] == 50.0
    # With 2 highlighted and 2 reference pixels, perfect overlap would give IoU 1.
    assert result["iou_upper_bound"] == 1.0


def test_iou_upper_bound_is_the_area_ratio() -> None:
    domain = np.ones((1, 10), dtype=bool)
    inside = np.array([[1] * 8 + [0, 0]], dtype=bool)  # 8 reference pixels
    highlighted = np.array([[1, 1] + [0] * 8], dtype=bool)  # 2 highlighted, both inside
    result = agreement(highlighted, inside, domain)
    assert result["iou"] == result["iou_upper_bound"] == pytest.approx(2 / 8)
    assert result["highlighted_inside_pct"] == 100.0
    assert result["reference_covered_pct"] == 25.0


def test_shares_with_nothing_highlighted() -> None:
    result = agreement(
        np.zeros((1, 3), dtype=bool), np.ones((1, 3), dtype=bool), np.ones((1, 3), dtype=bool)
    )
    assert result["iou"] == 0.0 and result["iou_upper_bound"] == 0.0
    assert result["highlighted_inside_pct"] is None, "undefined, not 0 %"
    assert result["reference_covered_pct"] == 0.0


def test_agreement_needs_reference_pixels_in_the_domain() -> None:
    zeros = np.zeros((1, 3), dtype=bool)
    with pytest.raises(HighlightError, match="no valid pixel inside"):
        agreement(zeros, np.array([[1, 0, 0]], dtype=bool), np.array([[0, 1, 1]], dtype=bool))


# --------------------------------------------------------------------------- end to end


def test_end_to_end_values_by_hand(tmp_path: Path) -> None:
    block = run_highlight(config_for(tmp_path))
    # Highlighted: region A (4 px inside) + region C (1 inside, 1 outside); B removed.
    assert block["threshold"] == 2.0
    assert block["area_ha"] == pytest.approx(0.06)
    assert block["inside_ha"] == pytest.approx(0.05)
    assert block["outside_ha"] == pytest.approx(0.01)
    # Inside valid = 12 px (columns 0-2); the invalid inside pixel is not a negative.
    assert block["iou_vs_perimeter"] == pytest.approx(5 / 13)
    out = tmp_path / "highlight"
    assert _read_json(out / "highlight.json") == block
    meta = _read_json(out / "highlight_meta.json")
    assert meta["agreement"]["intersection_px"] == 5 and meta["agreement"]["union_px"] == 13
    assert meta["agreement"]["highlighted_inside_pct"] == pytest.approx(100 * 5 / 6)
    assert meta["agreement"]["reference_covered_pct"] == pytest.approx(100 * 5 / 12)
    assert meta["agreement"]["iou_upper_bound"] == pytest.approx(6 / 12)
    assert meta["regions"] == {
        "count": 2,
        "removed_count": 1,
        "removed_px": 1,
        "sizes_px": [4, 2],
    }


def test_mask_cog_values_dtype_and_grid(tmp_path: Path) -> None:
    run_highlight(config_for(tmp_path))
    with rasterio.open(tmp_path / "highlight" / "highlight_mask.tif") as ds:
        data = ds.read(1)
        assert ds.dtypes == ("uint8",) and ds.nodata == 255
        assert ds.crs.to_epsg() == 32610 and ds.transform == TRANSFORM
    expected = np.zeros((4, 6), dtype=np.uint8)
    expected[0:2, 0:2] = 1
    expected[3, 2:4] = 1
    expected[3, 5] = 255
    assert data.tolist() == expected.tolist()


def test_without_edge_band_variant_by_hand(tmp_path: Path) -> None:
    run_highlight(config_for(tmp_path))
    variant = _read_json(tmp_path / "highlight" / "highlight_meta.json")["sensitivity"][
        "without_edge_band"
    ]
    # Columns 2-3 removed: highlighted = A (4 px), inside = columns 0-1 (8 px).
    assert variant["intersection_px"] == 4 and variant["union_px"] == 8
    assert variant["iou"] == pytest.approx(0.5)


def test_default_parameters_smooth_before_thresholding(tmp_path: Path) -> None:
    index = [[3.0] * 6 for _ in range(4)]
    index[0][0] = 0.0  # one low pixel is lifted by its neighbours: mean of 0, 3, 3, 3 = 2.25
    params = HighlightParams(threshold=2.0, window=3, min_region_px=1, connectivity=8)
    block = run_highlight(config_for(tmp_path, params, index=index, valid=[[1] * 6] * 4))
    assert block["area_ha"] == pytest.approx(0.24)
    assert "3x3" in block["smoothing"]


def test_highlight_json_matches_the_stats_schema_block(tmp_path: Path) -> None:
    block = run_highlight(config_for(tmp_path))
    schema = _read_json(ROOT / "contracts/schemas/stats.schema.json")
    sub = {"$schema": schema.get("$schema"), **schema["properties"]["highlight"]}
    Draft202012Validator(sub).validate(block)
    assert block["smoothing"] == "none; 8-connected regions under 2 px (0.02 ha) removed"


def test_reruns_are_byte_identical(tmp_path: Path) -> None:
    config = config_for(tmp_path)
    run_highlight(config)
    first = _files(config.output_dir)
    run_highlight(config)
    assert _files(config.output_dir) == first
    assert set(first) == {"highlight.json", "highlight_meta.json", "highlight_mask.tif"}


def test_meta_records_inputs_parameters_and_outputs(tmp_path: Path) -> None:
    config = config_for(tmp_path)
    run_highlight(config)
    meta = _read_json(config.output_dir / "highlight_meta.json")
    assert meta["highlight_format_version"] == 1
    assert meta["inputs"] == {
        "change.json": _sha(config.change_dir / "change.json"),
        "sar.json": _sha(config.sar_dir / "sar.json"),
        "perimeter.json": _sha(config.perimeter_dir / "perimeter.json"),
    }
    assert meta["parameters"] == {
        "threshold": 2.0,
        "window": 1,
        "min_region_px": 2,
        "connectivity": 8,
    }
    for name in ("highlight.json", "highlight_mask.tif"):
        assert meta["outputs"][name] == {
            "file": name,
            "sha256": _sha(config.output_dir / name),
        }
    assert meta["method_id"] == "abs-logratio-hhhv-v1"
    assert meta["grid"]["width"] == 6 and meta["grid"]["height"] == 4


# --------------------------------------------------------------------------- failures


def _fails_without_writing(config: HighlightConfig, match: str) -> None:
    with pytest.raises(HighlightError, match=match):
        run_highlight(config)
    assert not config.output_dir.exists()


def test_tampered_input_is_rejected(tmp_path: Path) -> None:
    config = config_for(tmp_path)
    path = config.change_dir / "change_index.tif"
    path.write_bytes(path.read_bytes() + b"\0")
    _fails_without_writing(config, "sha256")


def test_grid_mismatch_is_rejected(tmp_path: Path) -> None:
    moved = Affine(10.0, 0.0, 636_010.0, 0.0, -10.0, 3_983_990.0)
    _fails_without_writing(config_for(tmp_path, perimeter_transform=moved), "grid")


def test_other_method_is_rejected(tmp_path: Path) -> None:
    _fails_without_writing(config_for(tmp_path, method_id="other-v9"), "method")


def test_change_from_another_sar_generation_is_rejected(tmp_path: Path) -> None:
    config = config_for(tmp_path)
    doc = _read_json(config.change_dir / "change.json")
    doc["source_sar"]["sha256"] = "0" * 64
    (config.change_dir / "change.json").write_text(json.dumps(doc), encoding="utf-8")
    _fails_without_writing(config, "another sar.json")


def test_malformed_manifest_is_rejected(tmp_path: Path) -> None:
    config = config_for(tmp_path)
    (config.perimeter_dir / "perimeter.json").write_text("{not json", encoding="utf-8")
    _fails_without_writing(config, "perimeter.json")


def test_perimeter_mask_outside_zero_one_is_rejected(tmp_path: Path) -> None:
    bad = [row[:] for row in INSIDE]
    bad[0][0] = 2
    _fails_without_writing(config_for(tmp_path, inside=bad), "0 or 1")


def test_non_finite_index_on_a_valid_pixel_is_rejected(tmp_path: Path) -> None:
    index = [row[:] for row in INDEX]
    index[0][0] = NAN
    _fails_without_writing(config_for(tmp_path, index=index), "non-finite")


def test_no_valid_pixel_inside_the_perimeter_is_rejected(tmp_path: Path) -> None:
    _fails_without_writing(config_for(tmp_path, inside=[[0] * 6] * 4), "no valid pixel inside")


def test_failed_rerun_keeps_the_previous_outputs(tmp_path: Path) -> None:
    config = config_for(tmp_path)
    run_highlight(config)
    before = _files(config.output_dir)
    path = config.change_dir / "change_index.tif"
    path.write_bytes(path.read_bytes() + b"\0")
    with pytest.raises(HighlightError):
        run_highlight(config)
    assert _files(config.output_dir) == before


def test_foreign_file_in_the_output_dir_is_refused(tmp_path: Path) -> None:
    config = config_for(tmp_path)
    config.output_dir.mkdir()
    (config.output_dir / "notes.txt").write_text("mine", encoding="utf-8")
    with pytest.raises(HighlightError, match="notes.txt"):
        run_highlight(config)
    assert (config.output_dir / "notes.txt").read_text(encoding="utf-8") == "mine"


def test_output_dir_may_not_be_an_input_dir(tmp_path: Path) -> None:
    config = config_for(tmp_path)
    with pytest.raises(HighlightError, match="differ from the input"):
        run_highlight(replace(config, output_dir=config.change_dir))


def test_failure_while_writing_publishes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = config_for(tmp_path)

    def boom(*_args: Any, **_kwargs: Any) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(highlight, "write_cog", boom)
    _fails_without_writing(config, "disk full")


# --------------------------------------------------------------------------- config and CLI


def _write_config(path: Path, **overrides: Any) -> Path:
    values: dict[str, Any] = {
        "threshold": 2.0,
        "smoothing_window": 3,
        "min_region_px": 100,
        "connectivity": 8,
        "change_dir": "c",
        "sar_dir": "s",
        "perimeter_dir": "p",
        "output_dir": "o",
        **overrides,
    }
    lines = []
    for key, value in values.items():
        if value is None:
            continue
        lines.append(f"{key} = {json.dumps(value)}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_load_config_resolves_relative_paths(tmp_path: Path) -> None:
    config = load_config(_write_config(tmp_path / "h.toml"), base_dir=tmp_path)
    assert config.params == HighlightParams(2.0, 3, 100, 8)
    assert config.change_dir == tmp_path / "c" and config.output_dir == tmp_path / "o"


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"smoothing_window": 2}, "odd"),
        ({"smoothing_window": 0}, "odd"),
        ({"smoothing_window": True}, "smoothing_window"),
        ({"min_region_px": 0}, "min_region_px"),
        ({"connectivity": 6}, "connectivity"),
        ({"threshold": "2"}, "threshold"),
        ({"threshold": None}, "threshold"),
        ({"output_dir": ""}, "output_dir"),
        ({"surprise": 1}, "unknown"),
    ],
)
def test_load_config_rejects_bad_values(
    tmp_path: Path, override: dict[str, Any], message: str
) -> None:
    with pytest.raises(HighlightError, match=message):
        load_config(_write_config(tmp_path / "h.toml", **override), base_dir=tmp_path)


def test_load_config_rejects_a_non_finite_threshold(tmp_path: Path) -> None:
    path = _write_config(tmp_path / "h.toml", threshold=None)
    path.write_text(path.read_text(encoding="utf-8") + "threshold = nan\n", encoding="utf-8")
    with pytest.raises(HighlightError, match="threshold"):
        load_config(path, base_dir=tmp_path)


def test_repository_config_holds_the_agreed_parameters(tmp_path: Path) -> None:
    config = load_config(ROOT / "pipeline/configs/highlight_plaskett.toml", base_dir=tmp_path)
    assert config.params == HighlightParams(
        threshold=2.0, window=3, min_region_px=100, connectivity=8
    )
    assert config.output_dir == tmp_path / "data/interim/highlight"


def test_cli_exit_codes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    dirs = write_inputs(tmp_path)
    path = _write_config(
        tmp_path / "h.toml",
        smoothing_window=1,
        min_region_px=2,
        change_dir=str(dirs["change"]),
        sar_dir=str(dirs["sar"]),
        perimeter_dir=str(dirs["perimeter"]),
        output_dir=str(tmp_path / "out"),
    )
    assert main(["--config", str(path)]) == 0
    assert "highlight ok" in capsys.readouterr().out
    (dirs["change"] / "change.json").write_text("[]", encoding="utf-8")
    assert main(["--config", str(path)]) == 2
    assert "highlight error" in capsys.readouterr().err


# --------------------------------------------------------------------------- review fixes


def test_manifest_with_invalid_utf8_is_a_clean_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dirs = write_inputs(tmp_path)
    (dirs["sar"] / "sar.json").write_bytes(b'{"sar_format_version": 1, "x": "\xff"}')
    path = _write_config(
        tmp_path / "h.toml",
        change_dir=str(dirs["change"]),
        sar_dir=str(dirs["sar"]),
        perimeter_dir=str(dirs["perimeter"]),
        output_dir=str(tmp_path / "out"),
    )
    assert main(["--config", str(path)]) == 2
    assert "sar.json" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()


def test_config_with_invalid_utf8_is_a_clean_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "h.toml"
    path.write_bytes(b'output_dir = "\xff"\n')
    assert main(["--config", str(path)]) == 2
    assert "config" in capsys.readouterr().err


def test_recorded_input_hash_is_of_the_bytes_that_were_parsed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = config_for(tmp_path)
    manifest = config.perimeter_dir / "perimeter.json"
    parsed = manifest.read_bytes()
    read_bytes, read_text = Path.read_bytes, Path.read_text
    swapped: list[bool] = []

    def swap(self: Path) -> None:
        if self == manifest and not swapped:  # replaced right after the first read
            swapped.append(True)
            with manifest.open("ab") as fh:
                fh.write(b" ")

    def fake_bytes(self: Path) -> bytes:
        payload = read_bytes(self)
        swap(self)
        return payload

    def fake_text(self: Path, *args: Any, **kwargs: Any) -> str:
        payload = read_text(self, *args, **kwargs)
        swap(self)
        return payload

    monkeypatch.setattr(Path, "read_bytes", fake_bytes)
    monkeypatch.setattr(Path, "read_text", fake_text)
    run_highlight(config)
    assert swapped
    monkeypatch.undo()
    meta = _read_json(config.output_dir / "highlight_meta.json")
    assert meta["inputs"]["perimeter.json"] == hashlib.sha256(parsed).hexdigest()
