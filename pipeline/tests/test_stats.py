"""CH-02 inside/outside statistics: hand-computed values, histogram rule, schema, safety.

Tiny synthetic rasters on a 1 x 9 strip of the 10 m grid; no real data is used.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from affine import Affine
from jsonschema import Draft202012Validator
from rasterio.crs import CRS

from pipeline import stats
from pipeline.sar import SarError, write_cog
from pipeline.stats import N_BINS, StatsError, main, out_of_range, run_stats

ROOT = Path(__file__).resolve().parents[2]
UTM10N = CRS.from_epsg(32610)
TRANSFORM = Affine(10.0, 0.0, 636_000.0, 0.0, -10.0, 3_983_990.0)
GRID = {"crs": "EPSG:32610", "transform": list(TRANSFORM)[:6], "width": 9, "height": 1}

# Pixels 0-4 inside the perimeter, 5-7 outside, 8 invalid (mask 0, NaN index).
INDEX = [1.0, 2.0, 3.0, 4.0, 5.0, 10.0, 20.0, 30.0, np.nan]
VALID = [1, 1, 1, 1, 1, 1, 1, 1, 0]
INSIDE = [1, 1, 1, 1, 1, 0, 0, 0, 1]  # the invalid pixel is "inside" but must not count
EDGE = [0, 0, 0, 0, 1, 1, 0, 0, 0]  # pixels 4 and 5 lie in the 50 m boundary band


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _row(values: list[float], dtype: str) -> np.ndarray:
    return np.array([values], dtype=dtype)


def write_inputs(
    root: Path,
    *,
    index: list[float] = INDEX,
    valid: list[int] = VALID,
    inside: list[int] = INSIDE,
    edge: list[int] = EDGE,
    perimeter_transform: Affine = TRANSFORM,
    rasterization: dict[str, Any] | None = None,
) -> dict[str, Path]:
    """Mimic the CH-01, DT-02 and DT-03 output directories with minimal manifests."""
    rasterization = {"edge_distance_m": 50.0, **(rasterization or {})}
    dirs = {name: root / name for name in ("change", "sar", "perimeter")}
    for d in dirs.values():
        d.mkdir(parents=True, exist_ok=True)

    mask_path = dirs["sar"] / "valid_mask.tif"
    write_cog(mask_path, _row(valid, "uint8"), crs=UTM10N, transform=TRANSFORM, nodata=None)
    sar_doc = {
        "sar_format_version": 1,
        "grid": GRID,
        "valid_mask": {"file": mask_path.name, "sha256": _sha(mask_path)},
    }
    (dirs["sar"] / "sar.json").write_text(json.dumps(sar_doc), encoding="utf-8")

    idx_path = dirs["change"] / "change_index.tif"
    write_cog(idx_path, _row(index, "float32"), crs=UTM10N, transform=TRANSFORM, nodata=np.nan)
    change_doc = {
        "change_format_version": 1,
        "grid": GRID,
        "method": {"id": "abs-logratio-hhhv-v1"},
        "source_sar": {"file": "sar.json", "sha256": _sha(dirs["sar"] / "sar.json")},
        "outputs": {"change_index": {"file": idx_path.name, "sha256": _sha(idx_path)}},
    }
    (dirs["change"] / "change.json").write_text(json.dumps(change_doc), encoding="utf-8")

    outputs = {}
    for name, values in (("perimeter_mask.tif", inside), ("perimeter_edge.tif", edge)):
        path = dirs["perimeter"] / name
        write_cog(
            path, _row(values, "uint8"), crs=UTM10N, transform=perimeter_transform, nodata=None
        )
        outputs[name] = {"file": name, "sha256": _sha(path)}
    perim_doc = {
        "perimeter_format_version": 1,
        "grid": {**GRID, "transform": list(perimeter_transform)[:6]},
        "rasterization": {**{"rule": "pixel_centre", "all_touched": False}, **rasterization},
        "outputs": outputs,
    }
    (dirs["perimeter"] / "perimeter.json").write_text(json.dumps(perim_doc), encoding="utf-8")
    return dirs


def run(root: Path, **kwargs: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    d = write_inputs(root, **kwargs)
    stats_doc = run_stats(d["change"], d["sar"], d["perimeter"], root / "stats")
    meta = json.loads((root / "stats" / "stats_meta.json").read_text(encoding="utf-8"))
    return stats_doc, meta


# --------------------------------------------------------------------------- hand-computed


def test_counts_areas_and_coverage(tmp_path: Path) -> None:
    doc, _ = run(tmp_path)
    assert (doc["valid_pixels"], doc["total_pixels"]) == (8, 9)
    assert doc["valid_coverage_pct"] == pytest.approx(100 * 8 / 9)
    assert doc["pixel_area_m2"] == 100.0
    assert doc["inside_perimeter"]["valid_pixels"] == 5, "the invalid inside pixel is excluded"
    assert doc["outside_perimeter"]["valid_pixels"] == 3
    assert doc["inside_perimeter"]["area_ha"] == 0.05  # 5 px x 100 m2
    assert doc["outside_perimeter"]["area_ha"] == 0.03
    assert doc["data_status"] == "real" and doc["contract_version"] == "1.2.0"
    assert doc["highlight"] is None


def test_percentiles_by_hand(tmp_path: Path) -> None:
    doc, _ = run(tmp_path)
    inside = doc["inside_perimeter"]["change_index"]  # 1, 2, 3, 4, 5
    assert (inside["p25"], inside["p50"], inside["p75"], inside["mean"]) == (2.0, 3.0, 4.0, 3.0)
    outside = doc["outside_perimeter"]["change_index"]  # 10, 20, 30
    assert (outside["p25"], outside["p50"], outside["mean"]) == (15.0, 20.0, 20.0)
    everything = doc["change_index"]  # 1, 2, 3, 4, 5, 10, 20, 30
    assert everything["p50"] == 4.5
    assert everything["p5"] == pytest.approx(1.35)  # 1 + 0.35 * (2 - 1)


def test_histogram_bins_are_shared_and_counts_sum_to_valid(tmp_path: Path) -> None:
    doc, meta = run(tmp_path)
    groups = [doc["change_index"], doc["inside_perimeter"]["change_index"]]
    groups.append(doc["outside_perimeter"]["change_index"])
    edges = [g["histogram"]["bin_edges"] for g in groups]
    assert edges[0] == edges[1] == edges[2]
    assert len(edges[0]) == N_BINS + 1
    # Global p0.5 = 1 + 0.035 * 1 = 1.035; p99.5 = 20 + 0.965 * 10 = 29.65.
    assert edges[0][0] == pytest.approx(1.035)
    assert edges[0][-1] == pytest.approx(29.65)
    assert [sum(g["histogram"]["counts"]) for g in groups] == [8, 5, 3]
    first, last = groups[0]["histogram"]["counts"][0], groups[0]["histogram"]["counts"][-1]
    assert first >= 1 and last >= 1, "1 and 30 are clamped into the edge bins"
    rule = meta["histogram"]
    assert rule["below_range"] == {"all": 1, "inside": 1, "outside": 0}
    assert rule["above_range"] == {"all": 1, "inside": 0, "outside": 1}


def test_edge_band_sensitivity_variant(tmp_path: Path) -> None:
    _, meta = run(tmp_path)
    variant = meta["sensitivity"]["without_edge_band"]
    assert variant["inside_perimeter"]["valid_pixels"] == 4  # pixel 4 removed
    assert variant["inside_perimeter"]["change_index"]["p50"] == 2.5
    assert variant["outside_perimeter"]["valid_pixels"] == 2  # pixel 5 removed
    assert variant["outside_perimeter"]["change_index"]["p50"] == 25.0


# --------------------------------------------------------------------------- contract


def test_stats_json_validates_against_the_contract(tmp_path: Path) -> None:
    run(tmp_path)
    schema = json.loads(
        (ROOT / "contracts" / "schemas" / "stats.schema.json").read_text(encoding="utf-8")
    )
    doc = json.loads((tmp_path / "stats" / "stats.json").read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema).iter_errors(doc))
    assert errors == []


def test_validator_accepts_a_web_folder_with_real_stats(tmp_path: Path) -> None:
    run(tmp_path)
    web = tmp_path / "web"
    shutil.copytree(ROOT / "contracts" / "fixtures" / "web", web)
    shutil.copy(tmp_path / "stats" / "stats.json", web / "stats.json")
    spec = importlib.util.spec_from_file_location(
        "contract_validate", ROOT / "contracts" / "tools" / "validate.py"
    )
    assert spec and spec.loader
    validate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validate)
    errors: list[str] = []
    validate.check_web_dir(web, errors)
    assert errors == []


def test_outputs_are_byte_identical_across_runs(tmp_path: Path) -> None:
    d = write_inputs(tmp_path)
    run_stats(d["change"], d["sar"], d["perimeter"], tmp_path / "a")
    run_stats(d["change"], d["sar"], d["perimeter"], tmp_path / "b")
    for f in sorted(p.name for p in (tmp_path / "a").iterdir()):
        assert (tmp_path / "a" / f).read_bytes() == (tmp_path / "b" / f).read_bytes(), f


# --------------------------------------------------------------------------- failures


def test_checksum_mismatch_is_rejected(tmp_path: Path) -> None:
    d = write_inputs(tmp_path)
    doc = json.loads((d["perimeter"] / "perimeter.json").read_text(encoding="utf-8"))
    doc["outputs"]["perimeter_mask.tif"]["sha256"] = "0" * 64
    (d["perimeter"] / "perimeter.json").write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(StatsError, match="perimeter_mask.tif: sha256"):
        run_stats(d["change"], d["sar"], d["perimeter"], tmp_path / "stats")
    assert not (tmp_path / "stats").exists()


def test_grid_mismatch_is_rejected(tmp_path: Path) -> None:
    shifted = Affine(10.0, 0.0, 636_010.0, 0.0, -10.0, 3_983_990.0)
    with pytest.raises(StatsError, match="grid"):
        run(tmp_path, perimeter_transform=shifted)
    assert not (tmp_path / "stats").exists()


def test_non_finite_index_under_valid_mask_is_rejected(tmp_path: Path) -> None:
    index = [*INDEX[:3], np.nan, *INDEX[4:]]
    with pytest.raises(StatsError, match="non-finite"):
        run(tmp_path, index=index)


def test_empty_group_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(StatsError, match="inside"):
        run(tmp_path, inside=[0] * 9)


def test_failed_publication_keeps_the_previous_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    d = write_inputs(tmp_path)
    run_stats(d["change"], d["sar"], d["perimeter"], tmp_path / "stats")
    before = {p.name: p.read_bytes() for p in sorted((tmp_path / "stats").iterdir())}

    def boom(*_args: Any) -> None:
        raise SarError("injected publish failure")

    monkeypatch.setattr(stats, "publish", boom)
    with pytest.raises(StatsError, match="injected"):
        run_stats(d["change"], d["sar"], d["perimeter"], tmp_path / "stats")
    assert {p.name: p.read_bytes() for p in sorted((tmp_path / "stats").iterdir())} == before


def test_malformed_manifest_reported_by_cli(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    d = write_inputs(tmp_path)
    (d["change"] / "change.json").write_text("[]", encoding="utf-8")
    args = ["--change-dir", str(d["change"]), "--sar-dir", str(d["sar"])]
    args += ["--perimeter-dir", str(d["perimeter"]), "--output-dir", str(tmp_path / "stats")]
    assert main(args) == 2
    assert "stats error" in capsys.readouterr().err
    assert not (tmp_path / "stats").exists()


# --------------------------------------------------------------- review regressions


def _edit_json(path: Path, **changes: Any) -> None:
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc.update(changes)
    path.write_text(json.dumps(doc), encoding="utf-8")


def test_mixed_generation_inputs_are_rejected(tmp_path: Path) -> None:
    d = write_inputs(tmp_path)
    # A newer, narrower but internally consistent DT-02 output on the same grid.
    narrower = [*VALID[:2], 0, *VALID[3:]]
    newer = write_inputs(tmp_path / "newer", valid=narrower)
    with pytest.raises(StatsError, match="another sar.json"):
        run_stats(d["change"], newer["sar"], d["perimeter"], tmp_path / "stats")
    assert not (tmp_path / "stats").exists()


def test_out_of_range_counts_use_float64_boundaries() -> None:
    values = np.array([1.0, 2.0], dtype=np.float32)
    lo = 1.0000000041723252  # rounds to 1.0 in float32, so a float32 comparison misses it
    assert float(np.float32(lo)) == 1.0
    assert out_of_range(values, lo, 1.5) == (1, 1)


def test_empty_sensitivity_group_is_null(tmp_path: Path) -> None:
    edge = [1, 1, 1, 1, 1, 0, 0, 0, 0]  # every inside pixel lies in the edge band
    doc, meta = run(tmp_path, edge=edge)
    variant = meta["sensitivity"]["without_edge_band"]
    assert variant["inside_perimeter"] is None
    assert variant["outside_perimeter"]["valid_pixels"] == 3
    assert doc["inside_perimeter"]["valid_pixels"] == 5


@pytest.mark.parametrize(
    ("rasterization", "message"),
    [
        ({"edge_distance_m": 100.0}, "edge_distance_m"),
        ({"all_touched": True}, "all_touched"),
        ({"rule": "touched"}, "rule"),
    ],
    ids=["band_100m", "all_touched", "rule"],
)
def test_unexpected_perimeter_semantics_are_rejected(
    tmp_path: Path, rasterization: dict[str, Any], message: str
) -> None:
    with pytest.raises(StatsError, match=message):
        run(tmp_path, rasterization=rasterization)
    assert not (tmp_path / "stats").exists()


@pytest.mark.parametrize(
    ("manifest", "changes", "message"),
    [
        ("change", {"change_format_version": 2}, "change_format_version"),
        ("sar", {"sar_format_version": 2}, "sar_format_version"),
        ("perimeter", {"perimeter_format_version": 2}, "perimeter_format_version"),
        ("change", {"method": {"id": "other-v1"}}, "method"),
    ],
    ids=["change_version", "sar_version", "perimeter_version", "method_id"],
)
def test_unsupported_manifest_versions_and_method_are_rejected(
    tmp_path: Path, manifest: str, changes: dict[str, Any], message: str
) -> None:
    d = write_inputs(tmp_path)
    _edit_json(d[manifest] / f"{manifest}.json", **changes)
    if manifest == "sar":  # keep the change -> sar link valid to reach the version check
        _edit_json(
            d["change"] / "change.json",
            source_sar={"file": "sar.json", "sha256": _sha(d["sar"] / "sar.json")},
        )
    with pytest.raises(StatsError, match=message):
        run_stats(d["change"], d["sar"], d["perimeter"], tmp_path / "stats")


# --------------------------------------------------------------------------- DT-08


def _tamper_after_read(monkeypatch: pytest.MonkeyPatch, target: Path) -> list[Path]:
    """Replace ``target`` with garbage right after its bytes are read (hash/decode race)."""
    real = Path.read_bytes
    hits: list[Path] = []

    def racing(self: Path) -> bytes:
        payload = real(self)
        if self == target and not hits:
            hits.append(self)
            target.write_bytes(b"tampered after hashing")
        return payload

    monkeypatch.setattr(Path, "read_bytes", racing)
    return hits


def test_input_on_the_staging_sibling_is_rejected(tmp_path: Path) -> None:
    d = write_inputs(tmp_path)
    moved = d["perimeter"].rename(tmp_path / ".stats.staging")
    with pytest.raises(StatsError, match="must differ"):
        run_stats(d["change"], d["sar"], moved, tmp_path / "stats")
    assert (moved / "perimeter.json").is_file(), "the input must never be deleted"


def test_directory_under_an_owned_name_is_refused(tmp_path: Path) -> None:
    d = write_inputs(tmp_path)
    trap = tmp_path / "stats" / "stats.json"
    trap.mkdir(parents=True)
    (trap / "keep.txt").write_text("mine", encoding="utf-8")
    with pytest.raises(StatsError, match="does not own"):
        run_stats(d["change"], d["sar"], d["perimeter"], tmp_path / "stats")
    assert (trap / "keep.txt").is_file()


def test_rasters_are_decoded_from_the_hashed_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clean, _ = run(tmp_path / "clean")
    d = write_inputs(tmp_path / "raced")
    hits = _tamper_after_read(monkeypatch, d["perimeter"] / "perimeter_mask.tif")
    raced = run_stats(d["change"], d["sar"], d["perimeter"], tmp_path / "raced" / "stats")
    assert hits, "the mask was read through the verified bytes"
    assert raced == clean


def test_sha_mismatch_names_the_manifest_that_recorded_it(tmp_path: Path) -> None:
    d = write_inputs(tmp_path)
    (d["perimeter"] / "perimeter_mask.tif").write_bytes(b"changed")
    with pytest.raises(StatsError, match="perimeter_mask.tif: sha256 .* perimeter.json"):
        run_stats(d["change"], d["sar"], d["perimeter"], tmp_path / "stats")


def test_manifest_with_invalid_utf8_is_a_clean_cli_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    d = write_inputs(tmp_path)
    (d["sar"] / "sar.json").write_bytes(b'{"sar_format_version": 1, "x": "\xff"}')
    args = ["--change-dir", str(d["change"]), "--sar-dir", str(d["sar"])]
    args += ["--perimeter-dir", str(d["perimeter"]), "--output-dir", str(tmp_path / "stats")]
    assert main(args) == 2
    assert "cannot read sar.json" in capsys.readouterr().err
    assert not (tmp_path / "stats").exists()
