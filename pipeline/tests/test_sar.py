"""DT-02 dB conversion and common valid mask: known values, masking, COGs, determinism.

All rasters are tiny synthetic GeoTIFFs in ``tmp_path``; no real data is used.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import rasterio
from affine import Affine
from rasterio.crs import CRS
from rio_cogeo.cogeo import cog_validate

from pipeline.sar import NAMES, SarError, classify, common_valid_mask, main, run_sar, to_db

UTM10N = CRS.from_epsg(32610)
TRANSFORM = Affine(10.0, 0.0, 636_000.0, 0.0, -10.0, 3_983_990.0)
H, W = 40, 50


def base_power(seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.uniform(0.01, 1.0, size=(H, W)).astype(np.float32)


def write_ingest_dir(
    root: Path,
    arrays: dict[str, np.ndarray] | None = None,
    *,
    nodata: float | None = float("nan"),
    crs: CRS = UTM10N,
    transform: Affine = TRANSFORM,
) -> Path:
    """Mimic a DT-01 output directory: four float32 crops plus a matching ingest.json."""
    root.mkdir(parents=True, exist_ok=True)
    arrays = arrays or {}
    outputs: dict[str, Any] = {}
    for seed, name in enumerate(NAMES):
        data = arrays.get(name, base_power(seed))
        path = root / f"{name}.tif"
        with rasterio.open(
            path,
            "w",
            driver="GTiff",
            width=data.shape[1],
            height=data.shape[0],
            count=1,
            dtype="float32",
            crs=crs,
            transform=transform,
            nodata=nodata,
        ) as ds:
            ds.write(data, 1)
        outputs[name] = {
            "file": path.name,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "dtype": "float32",
            "nodata": None if nodata is None else ("nan" if math.isnan(nodata) else nodata),
        }
    ingest = {
        "ingest_format_version": 1,
        "case_id": "synthetic",
        "grid": {
            "crs": "EPSG:32610",
            "crop": {"transform": list(TRANSFORM)[:6], "width": W, "height": H},
        },
        "outputs": outputs,
    }
    (root / "ingest.json").write_text(json.dumps(ingest), encoding="utf-8")
    return root


# --------------------------------------------------------------------------- known values


def test_db_known_values() -> None:
    power = np.array([1.0, 0.1, 0.01, 10.0], dtype=np.float32)
    np.testing.assert_allclose(to_db(power, None), [0.0, -10.0, -20.0, 10.0], atol=1e-5)
    assert to_db(power, None).dtype == np.float32


@pytest.mark.parametrize(
    "value",
    [0.0, -0.5, float("nan"), float("inf"), -9999.0],
    ids=["zero", "neg", "nan", "inf", "nd"],
)
def test_invalid_power_becomes_nan(value: float) -> None:
    power = np.array([value, 1.0], dtype=np.float32)
    out = to_db(power, -9999.0)
    assert math.isnan(out[0]) and out[1] == 0.0


def test_classify_counts_are_disjoint() -> None:
    power = np.array([1.0, 0.0, -1.0, np.nan, -9999.0, 0.5], dtype=np.float32)
    c = classify(power, -9999.0)
    assert (c.valid, c.nodata, c.non_positive) == (2, 2, 2)
    assert c.valid + c.nodata + c.non_positive == power.size


def test_mask_is_and_of_the_four_layers() -> None:
    layers = {n: np.ones((1, 5), dtype=np.float32) for n in NAMES}
    layers["t1_hh"][0, 0] = 0.0
    layers["t1_hv"][0, 1] = np.nan
    layers["t2_hh"][0, 2] = -1.0
    layers["t2_hv"][0, 3] = np.inf
    mask = common_valid_mask(layers, {n: float("nan") for n in NAMES})
    assert mask.dtype == np.uint8
    assert mask.tolist() == [[0, 0, 0, 0, 1]]


# --------------------------------------------------------------------------- end to end


def test_run_writes_valid_cogs_and_manifest(tmp_path: Path) -> None:
    t2_hv = base_power(3)
    t2_hv[0, 0] = 0.0
    t2_hv[1, 1] = np.nan
    ingest = write_ingest_dir(tmp_path / "nisar", {"t2_hv": t2_hv})
    doc = run_sar(ingest, tmp_path / "sar")
    out = tmp_path / "sar"
    for name in NAMES:
        path = out / f"{name}_db.tif"
        assert cog_validate(str(path), quiet=True)[0]
        with rasterio.open(path) as ds:
            assert ds.dtypes[0] == "float32" and math.isnan(ds.nodata)
            assert ds.crs == UTM10N and ds.transform == TRANSFORM
    with rasterio.open(out / "t2_hv_db.tif") as ds:
        db = ds.read(1)
    assert math.isnan(db[0, 0]) and math.isnan(db[1, 1])
    np.testing.assert_array_equal(db, to_db(t2_hv, float("nan")))  # COG keeps exact values
    np.testing.assert_allclose(db[2, 2], 10 * np.log10(np.float64(t2_hv[2, 2])), atol=1e-5)
    with rasterio.open(out / "valid_mask.tif") as ds:
        mask = ds.read(1)
        assert ds.dtypes[0] == "uint8" and ds.nodata is None
        assert cog_validate(str(out / "valid_mask.tif"), quiet=True)[0]
    assert mask[0, 0] == 0 and mask[1, 1] == 0 and mask.sum() == H * W - 2
    m = doc["valid_mask"]
    assert (m["valid_pixels"], m["total_pixels"]) == (H * W - 2, H * W)
    assert m["valid_coverage_pct"] == round(100 * (H * W - 2) / (H * W), 6)
    counts = doc["db"]["layers"]["t2_hv"]["counts"]
    assert counts == {"valid": H * W - 2, "nodata": 1, "non_positive": 1}
    assert json.loads((out / "sar.json").read_text(encoding="utf-8")) == doc


def test_numeric_nodata_is_masked(tmp_path: Path) -> None:
    data = {n: base_power(i) for i, n in enumerate(NAMES)}
    data["t1_hh"][5, 5] = -9999.0
    doc = run_sar(write_ingest_dir(tmp_path / "nisar", data, nodata=-9999.0), tmp_path / "sar")
    assert doc["db"]["layers"]["t1_hh"]["counts"]["nodata"] == 1
    assert doc["valid_mask"]["valid_pixels"] == H * W - 1


def test_outputs_are_byte_identical_across_runs(tmp_path: Path) -> None:
    ingest = write_ingest_dir(tmp_path / "nisar")
    run_sar(ingest, tmp_path / "a")
    run_sar(ingest, tmp_path / "b")
    for f in sorted(p.name for p in (tmp_path / "a").iterdir()):
        assert (tmp_path / "a" / f).read_bytes() == (tmp_path / "b" / f).read_bytes(), f


# --------------------------------------------------------------------------- failures


def test_modified_input_is_rejected(tmp_path: Path) -> None:
    ingest = write_ingest_dir(tmp_path / "nisar")
    record = json.loads((ingest / "ingest.json").read_text(encoding="utf-8"))
    record["outputs"]["t2_hh"]["sha256"] = "0" * 64
    (ingest / "ingest.json").write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(SarError, match="t2_hh.tif: sha256"):
        run_sar(ingest, tmp_path / "sar")
    assert not (tmp_path / "sar").exists()


def test_grid_differing_from_ingest_is_rejected(tmp_path: Path) -> None:
    shifted = Affine(10.0, 0.0, 636_010.0, 0.0, -10.0, 3_983_990.0)
    ingest = write_ingest_dir(tmp_path / "nisar", transform=shifted)
    with pytest.raises(SarError, match="transform differs"):
        run_sar(ingest, tmp_path / "sar")


def test_output_dir_equal_to_ingest_dir_is_rejected(tmp_path: Path) -> None:
    ingest = write_ingest_dir(tmp_path / "nisar")
    with pytest.raises(SarError, match="must differ"):
        run_sar(ingest, ingest)


def test_cli_reports_errors_with_exit_code(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--ingest-dir", str(tmp_path / "missing"), "--output-dir", str(tmp_path)]) == 2
    assert "sar error" in capsys.readouterr().err
