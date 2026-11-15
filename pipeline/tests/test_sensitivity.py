"""XP-02 sensitivity sweep: hand-computed indices and baselines, XP-01 parity, safety.

Tiny synthetic rasters on the 10 m grid; no real data is used.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from affine import Affine
from rasterio.crs import CRS

from pipeline.highlight import HighlightConfig, HighlightParams, run_highlight
from pipeline.sar import write_cog
from pipeline.sensitivity import (
    CSV_COLUMNS,
    SensitivityConfig,
    SensitivityError,
    chance_iou,
    load_config,
    main,
    polarization_index,
    run_sensitivity,
    threshold_grid,
)

ROOT = Path(__file__).resolve().parents[2]
UTM10N = CRS.from_epsg(32610)
TRANSFORM = Affine(10.0, 0.0, 636_000.0, 0.0, -10.0, 3_983_990.0)
H, W = 6, 8
NAN = float("nan")

RNG = np.random.default_rng(7)
VALID = np.ones((H, W), dtype=np.uint8)
VALID[5, 7] = 0
INSIDE = np.zeros((H, W), dtype=np.uint8)
INSIDE[:, :4] = 1
EDGE = np.zeros((H, W), dtype=np.uint8)
EDGE[:, 3:5] = 1
HH = np.where(VALID == 1, RNG.normal(0.0, 1.0, (H, W)) - 3.0 * INSIDE, NAN).astype(np.float32)
HV = np.where(VALID == 1, RNG.normal(0.0, 1.0, (H, W)) - 4.0 * INSIDE, NAN).astype(np.float32)
INDEX = np.where(VALID == 1, np.abs(HH) + np.abs(HV) - 2.0, NAN).astype(np.float32)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _cog(path: Path, data: np.ndarray, nodata: float | None) -> dict[str, str]:
    write_cog(path, data, crs=UTM10N, transform=TRANSFORM, nodata=nodata)
    return {"file": path.name, "sha256": _sha(path)}


def write_inputs(
    root: Path,
    *,
    hh: np.ndarray = HH,
    inside: np.ndarray = INSIDE,
    method_id: str = "abs-logratio-hhhv-v1",
):
    """Mimic the CH-01, DT-02 and DT-03 output directories with minimal manifests."""
    grid = {"crs": "EPSG:32610", "transform": list(TRANSFORM)[:6], "width": W, "height": H}
    dirs = {name: root / name for name in ("change", "sar", "perimeter")}
    for d in dirs.values():
        d.mkdir(parents=True, exist_ok=True)
    sar_doc = {
        "sar_format_version": 1,
        "grid": grid,
        "valid_mask": _cog(dirs["sar"] / "valid_mask.tif", VALID, None),
    }
    (dirs["sar"] / "sar.json").write_text(json.dumps(sar_doc), encoding="utf-8")
    outputs = {
        name: _cog(dirs["change"] / f"{name}.tif", data, NAN)
        for name, data in (("change_index", INDEX), ("change_hh_db", hh), ("change_hv_db", HV))
    }
    change_doc = {
        "change_format_version": 1,
        "grid": grid,
        "method": {"id": method_id},
        "source_sar": {"file": "sar.json", "sha256": _sha(dirs["sar"] / "sar.json")},
        "outputs": outputs,
    }
    (dirs["change"] / "change.json").write_text(json.dumps(change_doc), encoding="utf-8")
    perim_doc = {
        "perimeter_format_version": 1,
        "grid": grid,
        "rasterization": {"rule": "pixel_centre", "all_touched": False, "edge_distance_m": 50.0},
        "outputs": {
            "perimeter_mask.tif": _cog(dirs["perimeter"] / "perimeter_mask.tif", inside, None),
            "perimeter_edge.tif": _cog(dirs["perimeter"] / "perimeter_edge.tif", EDGE, None),
        },
    }
    (dirs["perimeter"] / "perimeter.json").write_text(json.dumps(perim_doc), encoding="utf-8")
    return dirs


def config_for(root: Path, **kwargs: Any) -> SensitivityConfig:
    d = write_inputs(root, **kwargs)
    return SensitivityConfig(
        thresholds=threshold_grid(0.5, 5.0, 0.25),
        windows=(1, 3, 5),
        min_region_px=2,
        connectivity=8,
        change_dir=d["change"],
        sar_dir=d["sar"],
        perimeter_dir=d["perimeter"],
        output_dir=root / "sensitivity",
    )


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _files(directory: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted(directory.iterdir())}


# --------------------------------------------------------------------------- core


def test_threshold_grid_matches_decision_b() -> None:
    grid = threshold_grid(0.5, 5.0, 0.25)
    assert len(grid) == 19 and grid[0] == 0.5 and grid[-1] == 5.0
    assert 2.0 in grid and grid[6] == 2.0
    assert all(isinstance(t, float) for t in grid)


def test_threshold_grid_must_contain_the_xp01_threshold() -> None:
    with pytest.raises(SensitivityError, match="2.0"):
        threshold_grid(0.5, 5.0, 0.4)


def test_polarization_index_is_the_robust_z_of_the_magnitude() -> None:
    delta = np.array([[0.0, -1.0, 2.0, -3.0, 4.0, 99.0]], dtype=np.float32)
    valid = np.array([[1, 1, 1, 1, 1, 0]], dtype=bool)
    z, median, mad = polarization_index(delta, valid)
    # |delta| over valid = 0, 1, 2, 3, 4 -> median 2, MAD = median(2, 1, 0, 1, 2) = 1.
    assert (median, mad) == (2.0, 1.0)
    assert z[0, :5] == pytest.approx([(v - 2.0) / 1.4826 for v in (0, 1, 2, 3, 4)])
    assert np.isnan(z[0, 5]), "the invalid pixel stays invalid"


def test_polarization_index_with_zero_mad_is_an_error() -> None:
    with pytest.raises(SensitivityError, match="MAD"):
        polarization_index(np.ones((2, 2), dtype=np.float32), np.ones((2, 2), dtype=bool))


def test_chance_iou_by_hand() -> None:
    # 2 highlighted, 8 reference, 10 valid: expected intersection 2 * 8 / 10 = 1.6.
    assert chance_iou(2, 8, 10) == pytest.approx(1.6 / (2 + 8 - 1.6))
    assert chance_iou(0, 8, 10) == 0.0
    assert chance_iou(10, 8, 10) == pytest.approx(8 / 10)  # everything highlighted


# --------------------------------------------------------------------------- end to end


def test_sweep_has_every_point_once(tmp_path: Path) -> None:
    doc = run_sensitivity(config_for(tmp_path))
    points = doc["points"]
    assert len(points) == 3 * 3 * 19
    keys = {(p["index"], p["window"], p["threshold"]) for p in points}
    assert len(keys) == len(points)
    assert {p["index"] for p in points} == {"combined", "hh", "hv"}


def test_combined_window3_threshold2_matches_the_highlight_stage(tmp_path: Path) -> None:
    # Same rules as XP-01 with the same region settings -> identical numbers. (The tiny grid
    # needs a 2 px region filter, so this point is not marked as the XP-01 operating point.)
    config = config_for(tmp_path)
    doc = run_sensitivity(config)
    point = next(
        p
        for p in doc["points"]
        if (p["index"], p["window"], p["threshold"]) == ("combined", 3, 2.0)
    )
    block = run_highlight(
        HighlightConfig(
            params=HighlightParams(2.0, 3, config.min_region_px, config.connectivity),
            change_dir=config.change_dir,
            sar_dir=config.sar_dir,
            perimeter_dir=config.perimeter_dir,
            output_dir=tmp_path / "highlight",
        )
    )
    for key in ("area_ha", "inside_ha", "outside_ha"):
        assert point[key] == block[key], key
    assert point["iou"] == block["iou_vs_perimeter"]


def test_area_never_grows_with_the_threshold(tmp_path: Path) -> None:
    doc = run_sensitivity(config_for(tmp_path))
    for index in ("combined", "hh", "hv"):
        for window in (1, 3, 5):
            series = [
                p["area_ha"] for p in doc["points"] if p["index"] == index and p["window"] == window
            ]
            assert series == sorted(series, reverse=True), (index, window)


def test_iou_lies_between_zero_and_its_upper_bound(tmp_path: Path) -> None:
    doc = run_sensitivity(config_for(tmp_path))
    for p in doc["points"]:
        assert 0.0 <= p["iou"] <= p["iou_upper_bound"] + 1e-12
        assert 0.0 <= p["iou_chance"] <= p["iou_upper_bound"] + 1e-12


def test_polarization_normalization_is_recorded(tmp_path: Path) -> None:
    config = config_for(tmp_path)
    doc = run_sensitivity(config)
    valid = VALID == 1
    for name, delta in (("hh", HH), ("hv", HV)):
        magnitude = np.abs(delta[valid].astype(np.float64))
        median = float(np.median(magnitude))
        assert doc["indices"][name]["median"] == median
        assert doc["indices"][name]["mad"] == float(np.median(np.abs(magnitude - median)))
    assert doc["indices"]["combined"]["source"] == "CH-01 change_index.tif"


def test_csv_has_one_row_per_point_and_matches_the_json(tmp_path: Path) -> None:
    config = config_for(tmp_path)
    doc = run_sensitivity(config)
    text = (config.output_dir / "sensitivity.csv").read_text(encoding="utf-8")
    rows = list(csv.DictReader(io.StringIO(text)))
    assert list(rows[0]) == list(CSV_COLUMNS)
    assert len(rows) == len(doc["points"])
    first = doc["points"][0]
    assert float(rows[0]["iou"]) == first["iou"]
    assert rows[0]["index"] == first["index"]
    assert "\r" not in text


def test_reruns_are_byte_identical(tmp_path: Path) -> None:
    config = config_for(tmp_path)
    run_sensitivity(config)
    first = _files(config.output_dir)
    run_sensitivity(config)
    assert _files(config.output_dir) == first
    assert set(first) == {"sensitivity.json", "sensitivity.csv"}


def test_document_records_inputs_and_parameters(tmp_path: Path) -> None:
    config = config_for(tmp_path)
    doc = run_sensitivity(config)
    assert doc["sensitivity_format_version"] == 1
    assert doc["inputs"] == {
        "change.json": _sha(config.change_dir / "change.json"),
        "sar.json": _sha(config.sar_dir / "sar.json"),
        "perimeter.json": _sha(config.perimeter_dir / "perimeter.json"),
    }
    assert doc["parameters"]["windows"] == [1, 3, 5]
    assert doc["parameters"]["thresholds"] == threshold_grid(0.5, 5.0, 0.25)
    assert doc["parameters"]["min_region_px"] == 2


# --------------------------------------------------------------------------- failures


def _fails_without_writing(config: SensitivityConfig, match: str) -> None:
    with pytest.raises(SensitivityError, match=match):
        run_sensitivity(config)
    assert not config.output_dir.exists()


def test_tampered_polarization_layer_is_rejected(tmp_path: Path) -> None:
    config = config_for(tmp_path)
    path = config.change_dir / "change_hh_db.tif"
    path.write_bytes(path.read_bytes() + b"\0")
    _fails_without_writing(config, "sha256")


def test_other_method_is_rejected(tmp_path: Path) -> None:
    _fails_without_writing(config_for(tmp_path, method_id="other-v9"), "method")


def test_non_finite_polarization_value_on_a_valid_pixel_is_rejected(tmp_path: Path) -> None:
    hh = HH.copy()
    hh[0, 0] = NAN
    _fails_without_writing(config_for(tmp_path, hh=hh), "non-finite")


def test_failed_rerun_keeps_the_previous_outputs(tmp_path: Path) -> None:
    config = config_for(tmp_path)
    run_sensitivity(config)
    before = _files(config.output_dir)
    (config.change_dir / "change.json").write_text("[]", encoding="utf-8")
    with pytest.raises(SensitivityError):
        run_sensitivity(config)
    assert _files(config.output_dir) == before


def test_foreign_file_in_the_output_dir_is_refused(tmp_path: Path) -> None:
    config = config_for(tmp_path)
    config.output_dir.mkdir()
    (config.output_dir / "notes.txt").write_text("mine", encoding="utf-8")
    with pytest.raises(SensitivityError, match="notes.txt"):
        run_sensitivity(config)


def test_output_dir_may_not_be_an_input_dir(tmp_path: Path) -> None:
    config = config_for(tmp_path)
    from dataclasses import replace

    with pytest.raises(SensitivityError, match="differ from the input"):
        run_sensitivity(replace(config, output_dir=config.change_dir))


# --------------------------------------------------------------------------- config and CLI


def _write_config(path: Path, **overrides: Any) -> Path:
    values: dict[str, Any] = {
        "threshold_min": 0.5,
        "threshold_max": 5.0,
        "threshold_step": 0.25,
        "windows": [1, 3, 5],
        "min_region_px": 100,
        "connectivity": 8,
        "change_dir": "c",
        "sar_dir": "s",
        "perimeter_dir": "p",
        "output_dir": "o",
        **overrides,
    }
    lines = [f"{k} = {json.dumps(v)}" for k, v in values.items() if v is not None]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_repository_config_holds_the_agreed_grid(tmp_path: Path) -> None:
    config = load_config(ROOT / "pipeline/configs/sensitivity_plaskett.toml", base_dir=tmp_path)
    assert config.thresholds == threshold_grid(0.5, 5.0, 0.25)
    assert config.windows == (1, 3, 5)
    assert (config.min_region_px, config.connectivity) == (100, 8)
    assert config.output_dir == tmp_path / "data/interim/sensitivity"


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"windows": [1, 2]}, "odd"),
        ({"windows": []}, "windows"),
        ({"windows": [3, 3]}, "windows"),
        ({"threshold_step": 0}, "threshold_step"),
        ({"threshold_max": 0.25}, "threshold_max"),
        ({"min_region_px": 0}, "min_region_px"),
        ({"connectivity": 6}, "connectivity"),
        ({"surprise": 1}, "unknown"),
    ],
)
def test_load_config_rejects_bad_values(
    tmp_path: Path, override: dict[str, Any], message: str
) -> None:
    with pytest.raises(SensitivityError, match=message):
        load_config(_write_config(tmp_path / "s.toml", **override), base_dir=tmp_path)


def test_non_utf8_config_is_a_clean_error(tmp_path: Path) -> None:
    path = tmp_path / "s.toml"
    path.write_bytes(b'output_dir = "\xff"\n')
    with pytest.raises(SensitivityError, match="config"):
        load_config(path, base_dir=tmp_path)


def test_cli_exit_codes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    dirs = write_inputs(tmp_path)
    path = _write_config(
        tmp_path / "s.toml",
        min_region_px=2,
        change_dir=str(dirs["change"]),
        sar_dir=str(dirs["sar"]),
        perimeter_dir=str(dirs["perimeter"]),
        output_dir=str(tmp_path / "out"),
    )
    assert main(["--config", str(path)]) == 0
    assert "sensitivity ok" in capsys.readouterr().out
    (dirs["change"] / "change.json").write_bytes(b"\xff")
    assert main(["--config", str(path)]) == 2
    assert "sensitivity error" in capsys.readouterr().err


# --------------------------------------------------------------------------- review fixes


def test_marker_requires_the_xp01_region_settings(tmp_path: Path) -> None:
    config = config_for(tmp_path)  # min_region_px = 2: not the XP-01 1 ha filter
    doc = run_sensitivity(config)
    assert not any(p["xp01_operating_point"] for p in doc["points"])
    assert doc["parameters"]["xp01_operating_point"] is None
    from dataclasses import replace

    xp01 = replace(config, min_region_px=100, output_dir=tmp_path / "xp01")
    doc = run_sensitivity(xp01)
    marked = [p for p in doc["points"] if p["xp01_operating_point"]]
    assert [(p["index"], p["window"], p["threshold"]) for p in marked] == [("combined", 3, 2.0)]
    assert doc["parameters"]["xp01_operating_point"] == {
        "index": "combined",
        "window": 3,
        "threshold": 2.0,
        "min_region_px": 100,
        "connectivity": 8,
    }


def test_cli_without_the_xp01_point_still_succeeds(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dirs = write_inputs(tmp_path)
    path = _write_config(
        tmp_path / "s.toml",
        min_region_px=2,
        connectivity=4,
        change_dir=str(dirs["change"]),
        sar_dir=str(dirs["sar"]),
        perimeter_dir=str(dirs["perimeter"]),
        output_dir=str(tmp_path / "out"),
    )
    assert main(["--config", str(path)]) == 0
    assert "XP-01 point not in this sweep" in capsys.readouterr().out


@pytest.mark.parametrize("windows", ["[[3]]", '["3"]', "[3.0]", "[true, 3]"])
def test_malformed_windows_are_a_clean_cli_error(
    tmp_path: Path, windows: str, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write_config(tmp_path / "s.toml", windows=None)
    text = path.read_text(encoding="utf-8") + f"windows = {windows}" + chr(10)
    path.write_text(text, encoding="utf-8")
    assert main(["--config", str(path)]) == 2
    assert "windows" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("start", "stop", "step", "message"),
    [
        (0.5, 5.0, 1e-320, "too many"),
        (2.0, 2.00000000002, 1e-11, "distinct"),
        (0.5, 5.0, float("inf"), "threshold_step"),
    ],
    ids=["tiny_step", "collapsed", "infinite"],
)
def test_impractical_threshold_grids_are_rejected(
    start: float, stop: float, step: float, message: str
) -> None:
    with pytest.raises(SensitivityError, match=message):
        threshold_grid(start, stop, step)


def test_chance_baseline_is_a_ratio_of_expectations_not_the_expected_iou() -> None:
    # H = P = 1 of N = 2: the expected IoU is 1/2 (overlap 1 half the time, else 0), but the
    # agreed ratio-of-expectations baseline is I / (H + P - I) with I = 1/2 -> 1/3.
    assert chance_iou(1, 1, 2) == pytest.approx(1 / 3)


# --------------------------------------------------------------------------- second review


def _cli_config(tmp_path: Path, dirs: dict[str, Path], **overrides: Any) -> Path:
    return _write_config(
        tmp_path / "s.toml",
        min_region_px=2,
        change_dir=str(dirs["change"]),
        sar_dir=str(dirs["sar"]),
        perimeter_dir=str(dirs["perimeter"]),
        output_dir=str(tmp_path / "out"),
        **overrides,
    )


def test_no_reference_pixel_is_a_clean_cli_error_keeping_outputs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dirs = write_inputs(tmp_path)
    path = _cli_config(tmp_path, dirs)
    assert main(["--config", str(path)]) == 0
    before = _files(tmp_path / "out")
    write_inputs(tmp_path, inside=np.zeros((H, W), dtype=np.uint8))
    assert main(["--config", str(path)]) == 2
    assert "no valid pixel inside the perimeter" in capsys.readouterr().err
    assert _files(tmp_path / "out") == before


@pytest.mark.parametrize(
    ("start", "stop", "step", "expected_len", "expected_last"),
    [
        (2.0, 1001.9999999996, 1.0, 1000, 1001.0),
        (2.0, 2.9999999996, 1.0, 1, 2.0),
        (1.0, 1000.0, 1.0, 1000, 1000.0),
        (0.5, 5.0, 0.25, 19, 5.0),
    ],
    ids=["rounded_up_past_limit", "rounded_up_past_stop", "exactly_1000", "agreed"],
)
def test_threshold_grid_never_exceeds_the_stop_or_the_limit(
    start: float, stop: float, step: float, expected_len: int, expected_last: float
) -> None:
    grid = threshold_grid(start, stop, step)
    assert len(grid) == expected_len and grid[-1] == expected_last
    assert max(grid) <= stop


def test_threshold_grid_over_the_limit_is_rejected() -> None:
    with pytest.raises(SensitivityError, match="too many"):
        threshold_grid(1.0, 1001.0, 1.0)  # 1,001 values


@pytest.mark.parametrize("key", ["threshold_min", "threshold_max", "threshold_step"])
def test_huge_integer_threshold_value_is_a_clean_cli_error(
    tmp_path: Path, key: str, capsys: pytest.CaptureFixture[str]
) -> None:
    dirs = write_inputs(tmp_path)
    path = _cli_config(tmp_path, dirs, **{key: None})
    text = path.read_text(encoding="utf-8") + f"{key} = 1{'0' * 400}" + chr(10)
    path.write_text(text, encoding="utf-8")
    assert main(["--config", str(path)]) == 2
    assert key in capsys.readouterr().err


@pytest.mark.parametrize("window", [10**30 + 1, 101])
def test_oversized_window_is_a_clean_cli_error(
    tmp_path: Path, window: int, capsys: pytest.CaptureFixture[str]
) -> None:
    dirs = write_inputs(tmp_path)
    path = _cli_config(tmp_path, dirs, windows=[3, window])
    assert main(["--config", str(path)]) == 2
    assert "window" in capsys.readouterr().err
