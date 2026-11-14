"""CH-01 continuous change index: hand-computed values, masking, robustness, determinism.

All rasters are tiny synthetic COGs written through the DT-02 helpers; no real data is used.
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import rasterio
from affine import Affine
from rasterio.crs import CRS

from pipeline import change
from pipeline.change import (
    MAD_SCALE,
    METHOD_ID,
    ChangeError,
    change_db,
    combine,
    main,
    robust_stats,
    robust_z,
    run_change,
)
from pipeline.sar import write_cog

UTM10N = CRS.from_epsg(32610)
TRANSFORM = Affine(10.0, 0.0, 636_000.0, 0.0, -10.0, 3_983_990.0)
H, W = 30, 40
NAMES = ("t1_hh", "t1_hv", "t2_hh", "t2_hv")


# --------------------------------------------------------------------------- hand-computed


def test_combination_of_absolute_changes() -> None:
    s = combine(np.array([3.0]), np.array([-4.0]))
    assert s.tolist() == [7.0]


def test_change_keeps_sign_and_masks_invalid_pixels() -> None:
    t1 = np.array([[-13.0, -13.0, -10.0]], dtype=np.float32)
    t2 = np.array([[-19.0, -10.0, -10.0]], dtype=np.float32)
    mask = np.array([[1, 1, 0]], dtype=np.uint8)
    d = change_db(t1, t2, mask)
    assert d.dtype == np.float64, "kept in float64 until storage"
    assert d[0, 0] == -6.0, "a decrease must stay negative"
    assert d[0, 1] == 3.0
    assert math.isnan(d[0, 2]), "mask = 0 must give NaN"


def test_robust_z_by_hand() -> None:
    s = np.array([1.0, 2.0, 3.0, 4.0, 100.0])
    median, mad = robust_stats(s)
    assert (median, mad) == (3.0, 1.0)  # |s - 3| = 2, 1, 0, 1, 97 -> median 1
    z = robust_z(s, median, mad)
    assert z[2] == 0.0, "the median pixel is 'normal'"
    assert z[4] == pytest.approx(97 / MAD_SCALE)  # ~65.4; the extreme does not move the median
    assert z[0] == pytest.approx(-2 / MAD_SCALE), "below-typical change stays negative (no clip)"


def test_robust_stats_ignore_nan() -> None:
    s = np.array([np.nan, 1.0, 2.0, 3.0, 4.0, 100.0, np.nan])
    assert robust_stats(s) == (3.0, 1.0)


def test_zero_mad_is_an_error() -> None:
    with pytest.raises(ChangeError, match="MAD"):
        robust_stats(np.array([2.0, 2.0, 2.0, 2.0, 9.0]))


def test_no_valid_pixels_is_an_error() -> None:
    with pytest.raises(ChangeError, match="no valid pixels"):
        robust_stats(np.array([np.nan, np.nan]))


# --------------------------------------------------------------------------- end to end


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_sar_dir(
    root: Path,
    db: dict[str, np.ndarray] | None = None,
    mask: np.ndarray | None = None,
) -> Path:
    """Mimic a DT-02 output directory: four dB COGs, valid_mask.tif and sar.json."""
    root.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(7)
    db = db or {}
    layers: dict[str, Any] = {}
    for name in NAMES:
        data = db.get(name)
        if data is None:
            data = rng.normal(-12.0, 2.0, size=(H, W)).astype(np.float32)
        path = root / f"{name}_db.tif"
        write_cog(path, data, crs=UTM10N, transform=TRANSFORM, nodata=float("nan"))
        layers[name] = {"file": path.name, "sha256": _sha(path)}
    mask = np.ones((H, W), dtype=np.uint8) if mask is None else mask
    write_cog(root / "valid_mask.tif", mask, crs=UTM10N, transform=TRANSFORM, nodata=None)
    doc = {
        "sar_format_version": 1,
        "case_id": "synthetic",
        "grid": {
            "crs": "EPSG:32610",
            "transform": list(TRANSFORM)[:6],
            "width": W,
            "height": H,
            "resampling": "none",
        },
        "db": {"layers": layers},
        "valid_mask": {"file": "valid_mask.tif", "sha256": _sha(root / "valid_mask.tif")},
    }
    (root / "sar.json").write_text(json.dumps(doc), encoding="utf-8")
    return root


def known_case() -> tuple[dict[str, np.ndarray], np.ndarray]:
    t1 = np.full((H, W), -12.0, dtype=np.float32)
    db = {"t1_hh": t1.copy(), "t1_hv": t1.copy(), "t2_hh": t1.copy(), "t2_hv": t1.copy()}
    # Background: small varied changes so the MAD is not zero.
    rng = np.random.default_rng(3)
    db["t2_hh"] += rng.uniform(-0.5, 0.5, (H, W)).astype(np.float32)
    db["t2_hv"] += rng.uniform(-0.5, 0.5, (H, W)).astype(np.float32)
    db["t2_hh"][4, 5] = -9.0  # dHH = +3
    db["t2_hv"][4, 5] = -16.0  # dHV = -4 -> S = 7
    mask = np.ones((H, W), dtype=np.uint8)
    mask[0, 0] = 0
    return db, mask


def test_run_writes_signed_changes_index_and_manifest(tmp_path: Path) -> None:
    db, mask = known_case()
    doc = run_change(write_sar_dir(tmp_path / "sar", db, mask), tmp_path / "change")
    out = tmp_path / "change"
    with rasterio.open(out / "change_hh_db.tif") as ds:
        dhh = ds.read(1)
        assert ds.crs == UTM10N and ds.transform == TRANSFORM and ds.dtypes[0] == "float32"
    with rasterio.open(out / "change_hv_db.tif") as ds:
        dhv = ds.read(1)
    with rasterio.open(out / "change_index.tif") as ds:
        idx = ds.read(1)
    assert dhh[4, 5] == pytest.approx(3.0) and dhv[4, 5] == pytest.approx(-4.0)
    assert all(math.isnan(a[0, 0]) for a in (dhh, dhv, idx)), "mask = 0 -> NaN everywhere"

    s = np.abs(dhh.astype(np.float64)) + np.abs(dhv.astype(np.float64))
    valid = mask.astype(bool)
    med = float(np.median(s[valid]))
    mad = float(np.median(np.abs(s[valid] - med)))
    assert doc["normalization"]["median"] == pytest.approx(med)
    assert doc["normalization"]["mad"] == pytest.approx(mad)
    assert idx[4, 5] == pytest.approx((7.0 - med) / (MAD_SCALE * mad), rel=1e-5)

    method = doc["method"]
    assert method["id"] == METHOD_ID
    assert method["params"]["domain"] == "all_valid_crop"
    assert method["params"]["speckle_filter"] == "none"
    assert method["params"]["threshold"] is None
    assert doc["valid_pixels"] == H * W - 1
    assert set(doc["percentiles"]) == {"change_hh_db", "change_hv_db", "change_index"}
    assert json.loads((out / "change.json").read_text(encoding="utf-8")) == doc


def test_index_is_not_clipped(tmp_path: Path) -> None:
    db, mask = known_case()
    db["t2_hv"][10, 10] = 20.0  # absurd +32 dB jump must be stored as is
    run_change(write_sar_dir(tmp_path / "sar", db, mask), tmp_path / "change")
    with rasterio.open(tmp_path / "change" / "change_index.tif") as ds:
        idx = ds.read(1)
    assert np.nanmax(idx) == idx[10, 10] and idx[10, 10] > 50
    assert np.nanmin(idx) < 0


def test_outputs_are_byte_identical_across_runs(tmp_path: Path) -> None:
    sar = write_sar_dir(tmp_path / "sar", *known_case())
    run_change(sar, tmp_path / "a")
    run_change(sar, tmp_path / "b")
    for f in sorted(p.name for p in (tmp_path / "a").iterdir()):
        assert (tmp_path / "a" / f).read_bytes() == (tmp_path / "b" / f).read_bytes(), f


def test_quicklook_png_is_written(tmp_path: Path) -> None:
    sar = write_sar_dir(tmp_path / "sar", *known_case())
    png = tmp_path / "evidence" / "change_index.png"
    run_change(sar, tmp_path / "change", quicklook=png)
    with rasterio.open(png) as ds:
        assert ds.driver == "PNG" and ds.count == 4 and (ds.height, ds.width) == (H, W)
        alpha = ds.read(4)
    assert alpha[0, 0] == 0 and alpha[1, 1] == 255, "invalid pixels are transparent"
    assert not (tmp_path / "change" / "change_index.png").exists()


# --------------------------------------------------------------------------- failures


def test_modified_input_is_rejected_and_nothing_is_written(tmp_path: Path) -> None:
    sar = write_sar_dir(tmp_path / "sar", *known_case())
    doc = json.loads((sar / "sar.json").read_text(encoding="utf-8"))
    doc["db"]["layers"]["t2_hv"]["sha256"] = "0" * 64
    (sar / "sar.json").write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(ChangeError, match="t2_hv_db.tif: sha256"):
        run_change(sar, tmp_path / "change")
    assert not (tmp_path / "change").exists()


def test_constant_change_fails_with_zero_mad(tmp_path: Path) -> None:
    t = np.full((H, W), -12.0, dtype=np.float32)
    db = {"t1_hh": t, "t1_hv": t, "t2_hh": t - 1, "t2_hv": t - 1}
    with pytest.raises(ChangeError, match="MAD"):
        run_change(write_sar_dir(tmp_path / "sar", db), tmp_path / "change")
    assert not (tmp_path / "change").exists()


def test_failed_rerun_keeps_the_previous_complete_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sar = write_sar_dir(tmp_path / "sar", *known_case())
    run_change(sar, tmp_path / "change")
    before = {p.name: p.read_bytes() for p in sorted((tmp_path / "change").iterdir())}
    real = change.write_cog
    calls = {"n": 0}

    def flaky(*args: Any, **kwargs: Any) -> None:
        calls["n"] += 1
        if calls["n"] == 2:
            raise ChangeError("injected write failure")
        real(*args, **kwargs)

    monkeypatch.setattr(change, "write_cog", flaky)
    with pytest.raises(ChangeError, match="injected"):
        run_change(sar, tmp_path / "change")
    after = {p.name: p.read_bytes() for p in sorted((tmp_path / "change").iterdir())}
    assert after == before


def test_malformed_manifest_reported_by_cli(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sar = write_sar_dir(tmp_path / "sar", *known_case())
    (sar / "sar.json").write_text("[]", encoding="utf-8")
    out = tmp_path / "change"
    assert main(["--sar-dir", str(sar), "--output-dir", str(out)]) == 2
    assert "change error" in capsys.readouterr().err
    assert not out.exists()


# --------------------------------------------------------------- review regressions


def test_float32_rounding_does_not_create_a_false_zero_mad() -> None:
    t1 = np.full(5, -100.0, dtype=np.float32)
    t2 = (np.array([1, 2, 3, 4, 5]) * 1e-6).astype(np.float32)  # distinct in float32
    # In float32, 100.000001 ... 100.000005 collapse to tied values and the MAD would be 0.
    assert np.unique((t2 - t1).astype(np.float32)).size < 5
    mask = np.ones(5, dtype=np.uint8)
    d = change_db(t1, t2, mask)
    s = combine(d, np.zeros(5))
    assert robust_stats(s)[1] > 0


def test_percentiles_use_linear_interpolation() -> None:
    p = change.percentiles(np.array([np.nan, 0.0, 10.0, 20.0, 30.0, 40.0]))
    assert (p["p25"], p["p50"], p["p5"], p["mean"]) == (10.0, 20.0, 2.0, 20.0)


@pytest.mark.parametrize("bad", [np.nan, np.inf], ids=["nan", "inf"])
def test_non_finite_input_under_mask_is_rejected(tmp_path: Path, bad: float) -> None:
    db, mask = known_case()
    db["t2_hv"][7, 7] = bad
    with pytest.raises(ChangeError, match="non-finite"):
        run_change(write_sar_dir(tmp_path / "sar", db, mask), tmp_path / "change")
    assert not (tmp_path / "change").exists()


def test_non_10m_grid_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    coarse = Affine(20.0, 0.0, 636_000.0, 0.0, -20.0, 3_983_990.0)
    monkeypatch.setattr(sys.modules[__name__], "TRANSFORM", coarse)
    with pytest.raises(ChangeError, match="north-up 10 m"):
        run_change(write_sar_dir(tmp_path / "sar", *known_case()), tmp_path / "change")
    assert not (tmp_path / "change").exists()


@pytest.mark.parametrize(
    "target",
    ["sar/t1_hh_db.tif", "sar/preview.png", "change/preview.png", "change/sub/preview.png"],
    ids=["input_alias", "in_input_dir", "in_output_dir", "nested_in_output_dir"],
)
def test_quicklook_inside_protected_dirs_is_rejected(tmp_path: Path, target: str) -> None:
    sar = write_sar_dir(tmp_path / "sar", *known_case())
    before = {p.name: p.read_bytes() for p in sorted(sar.iterdir())}
    with pytest.raises(ChangeError, match="quicklook"):
        run_change(sar, tmp_path / "change", quicklook=tmp_path / target)
    assert {p.name: p.read_bytes() for p in sorted(sar.iterdir())} == before
    assert not (tmp_path / "change").exists()


def test_quicklook_failure_keeps_the_previous_set(tmp_path: Path) -> None:
    sar = write_sar_dir(tmp_path / "sar", *known_case())
    run_change(sar, tmp_path / "change")
    before = {p.name: p.read_bytes() for p in sorted((tmp_path / "change").iterdir())}
    blocker = tmp_path / "evidence"
    blocker.write_text("a file where a directory is expected", encoding="utf-8")
    with pytest.raises(ChangeError, match="quicklook"):
        run_change(sar, tmp_path / "change", quicklook=blocker / "q.png")
    after = {p.name: p.read_bytes() for p in sorted((tmp_path / "change").iterdir())}
    assert after == before


def test_quicklook_is_deterministic_without_sidecar(tmp_path: Path) -> None:
    sar = write_sar_dir(tmp_path / "sar", *known_case())
    run_change(sar, tmp_path / "a", quicklook=tmp_path / "ev" / "a.png")
    run_change(sar, tmp_path / "b", quicklook=tmp_path / "ev" / "b.png")
    assert (tmp_path / "ev" / "a.png").read_bytes() == (tmp_path / "ev" / "b.png").read_bytes()
    assert sorted(p.name for p in (tmp_path / "ev").iterdir()) == ["a.png", "b.png"]


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
    sar = write_sar_dir(tmp_path / ".change.staging", *known_case())
    with pytest.raises(ChangeError, match="must differ"):
        run_change(sar, tmp_path / "change")
    assert (sar / "sar.json").is_file(), "the input must never be deleted"


def test_directory_under_an_owned_name_is_refused(tmp_path: Path) -> None:
    sar = write_sar_dir(tmp_path / "sar", *known_case())
    trap = tmp_path / "change" / "change.json"
    trap.mkdir(parents=True)
    (trap / "keep.txt").write_text("mine", encoding="utf-8")
    with pytest.raises(ChangeError, match="does not own"):
        run_change(sar, tmp_path / "change")
    assert (trap / "keep.txt").is_file()


def test_rasters_are_decoded_from_the_hashed_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sar = write_sar_dir(tmp_path / "sar", *known_case())
    run_change(sar, tmp_path / "clean")
    hits = _tamper_after_read(monkeypatch, sar / "t2_hv_db.tif")
    run_change(sar, tmp_path / "raced")
    assert hits, "the raster was read through the verified bytes"
    clean = (tmp_path / "clean" / "change_index.tif").read_bytes()
    assert (tmp_path / "raced" / "change_index.tif").read_bytes() == clean
