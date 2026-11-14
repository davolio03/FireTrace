"""DT-06 precipitation context: IMERG-like grids, area weights, date rules, offline build.

Synthetic NetCDF files mimic the IMERG daily layout (precipitation[time, lon, lat]); no
network access and no real data are used.
"""

from __future__ import annotations

import hashlib
import json
import math
import urllib.request
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import xarray as xr
from jsonschema import Draft202012Validator

from pipeline import weather
from pipeline.weather import (
    WeatherError,
    cell_weights,
    fetch,
    main,
    parse_cmr_granules,
    read_daily_grid,
    run_build,
)

ROOT = Path(__file__).resolve().parents[2]
LON = np.round(np.arange(-121.55, -121.14, 0.1), 2)  # 5 cell centres
LAT = np.round(np.arange(35.75, 36.06, 0.1), 2)  # 4 cell centres (non-square on purpose)
AOI = [-121.5, 35.8, -121.3, 36.0]  # exactly 2 x 2 cells: centres -121.45/-121.35, 35.85/35.95
T1 = "2026-08-16T02:56:39Z"
T2 = "2026-08-20T02:56:38Z"  # short synthetic period: 16..20 Aug
DAYS = ["2026-08-16", "2026-08-17", "2026-08-18", "2026-08-19", "2026-08-20"]


def write_day(path: Path, values: np.ndarray, lon_dtype: type = np.float64) -> Path:
    """IMERG-like daily file: precipitation(time, lon, lat) in mm/day, -9999.9 fill."""
    ds = xr.Dataset(
        {"precipitation": (("time", "lon", "lat"), values[np.newaxis].astype(np.float32))},
        coords={"lon": LON.astype(lon_dtype), "lat": LAT, "time": [0]},
    )
    ds["precipitation"].attrs.update({"units": "mm/day", "_FillValue": np.float32(-9999.9)})
    ds.to_netcdf(path, engine="h5netcdf")  # NetCDF4/HDF5, like the real granules
    return path


def grid(fill: float) -> np.ndarray:
    return np.full((LON.size, LAT.size), fill, dtype=np.float32)


def write_raw(root: Path, daily: dict[str, np.ndarray]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    granules = []
    for day, values in daily.items():
        name = f"3B-DAY-L.MS.MRG.3IMERG.{day.replace('-', '')}-S000000-E235959.V07C.nc4"
        path = write_day(root / name, values)
        granules.append(
            {
                "date": day,
                "file": name,
                "url": f"https://example.invalid/{name}",
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    manifest = {
        "imerg_manifest_version": 1,
        "short_name": "GPM_3IMERGDL",
        "version": "V07C",
        "granules": granules,
    }
    (root / "imerg_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return root


def write_ingest(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    doc = {
        "ingest_format_version": 1,
        "epochs": {"t1": {"datetime": T1}, "t2": {"datetime": T2}},
        "aoi": {"crop_bbox_4326": AOI},
    }
    (root / "ingest.json").write_text(json.dumps(doc), encoding="utf-8")
    return root


def build(tmp_path: Path, daily: dict[str, np.ndarray] | None = None) -> dict[str, Any]:
    daily = daily if daily is not None else {d: grid(0.0) for d in DAYS}
    raw = write_raw(tmp_path / "raw", daily)
    ingest = write_ingest(tmp_path / "nisar")
    return run_build(raw, ingest, tmp_path / "out")


# --------------------------------------------------------------------------- reading + weights


def test_reader_keeps_lon_lat_orientation(tmp_path: Path) -> None:
    values = ((LON[:, None] + 180) * 100 + LAT[None, :]).astype(np.float32)  # position code
    lon, lat, precip = read_daily_grid(write_day(tmp_path / "d.nc4", values))
    assert np.allclose(lon, LON) and np.allclose(lat, LAT)
    assert precip.shape == (LON.size, LAT.size)
    i, j = 2, 3
    assert precip[i, j] == pytest.approx((LON[i] + 180) * 100 + LAT[j], abs=1e-2)


def test_cell_weights_cover_the_aoi_by_area() -> None:
    weights = cell_weights(LON, LAT, AOI)
    assert sorted(weights) == [(1, 1), (1, 2), (2, 1), (2, 2)]
    # Area on the sphere scales with sin(lat2) - sin(lat1): northern cells are smaller.
    south = math.sin(math.radians(35.9)) - math.sin(math.radians(35.8))
    north = math.sin(math.radians(36.0)) - math.sin(math.radians(35.9))
    assert weights[(1, 2)] / weights[(1, 1)] == pytest.approx(north / south)
    assert sum(weights.values()) == pytest.approx(1.0)


def test_partial_overlap_gets_proportional_weight() -> None:
    aoi = [-121.45, 35.8, -121.3, 35.9]  # half of cell lon -121.45, all of -121.35
    weights = cell_weights(LON, LAT, aoi)
    assert weights[(1, 1)] / weights[(2, 1)] == pytest.approx(0.5)


# --------------------------------------------------------------------------- series + rules


def test_area_weighted_daily_means_and_summary(tmp_path: Path) -> None:
    daily = {d: grid(0.0) for d in DAYS}
    daily["2026-08-17"] = grid(4.0)  # uniform 4 mm/day -> mean 4
    rainy = grid(0.0)
    rainy[1, :] = 2.0  # western AOI column 2 mm/day, eastern 0 -> mean ~1 (equal widths)
    daily["2026-08-18"] = rainy
    daily["2026-08-20"] = grid(9.0)  # the t2 day: listed, but excluded from the summary
    doc = build(tmp_path, daily)
    values = {d["date"]: d["value"] for d in doc["daily"]}
    assert list(values) == DAYS
    assert values["2026-08-17"] == pytest.approx(4.0)
    assert values["2026-08-18"] == pytest.approx(1.0, abs=1e-6)
    assert values["2026-08-20"] == pytest.approx(9.0)
    assert doc["total"] == pytest.approx(5.0, abs=1e-6), "days up to 2026-08-19 only"
    assert doc["rain_days_over_1mm"] == 1, "1.0 mm is not > 1 mm"
    assert doc["last_rain_before_t2"] == "2026-08-17"
    assert doc["period"] == {"start": "2026-08-16", "end": "2026-08-20"}
    assert doc["data_status"] == "real" and doc["units"] == "mm/day"


def test_no_rain_before_t2_gives_null_last_rain(tmp_path: Path) -> None:
    doc = build(tmp_path)
    assert doc["total"] == 0.0 and doc["last_rain_before_t2"] is None


def test_missing_day_and_fill_values_become_null(tmp_path: Path) -> None:
    daily = {d: grid(1.5) for d in DAYS}
    del daily["2026-08-18"]  # no granule
    filled = grid(1.5)
    filled[2, 2] = -9999.9  # a fill value inside the AOI
    daily["2026-08-19"] = filled
    doc = build(tmp_path, daily)
    values = {d["date"]: d["value"] for d in doc["daily"]}
    assert values["2026-08-18"] is None and values["2026-08-19"] is None
    assert doc["total"] == pytest.approx(3.0)  # 16 + 17 only
    meta = json.loads((tmp_path / "out" / "weather_meta.json").read_text(encoding="utf-8"))
    assert meta["missing_days"] == ["2026-08-18", "2026-08-19"]


def test_weather_json_validates_against_the_contract(tmp_path: Path) -> None:
    build(tmp_path)
    schema = json.loads(
        (ROOT / "contracts" / "schemas" / "weather.schema.json").read_text(encoding="utf-8")
    )
    doc = json.loads((tmp_path / "out" / "weather.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)
    assert list(validator.iter_errors(doc)) == []


def test_outputs_are_byte_identical_across_runs(tmp_path: Path) -> None:
    raw = write_raw(tmp_path / "raw", {d: grid(0.5) for d in DAYS})
    ingest = write_ingest(tmp_path / "nisar")
    run_build(raw, ingest, tmp_path / "a")
    run_build(raw, ingest, tmp_path / "b")
    for f in sorted(p.name for p in (tmp_path / "a").iterdir()):
        assert (tmp_path / "a" / f).read_bytes() == (tmp_path / "b" / f).read_bytes(), f


def test_build_never_uses_the_network(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("build must not open network connections")

    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", forbidden)
    build(tmp_path)


# --------------------------------------------------------------------------- failures


def test_checksum_mismatch_is_rejected(tmp_path: Path) -> None:
    raw = write_raw(tmp_path / "raw", {d: grid(0.0) for d in DAYS})
    manifest = json.loads((raw / "imerg_manifest.json").read_text(encoding="utf-8"))
    manifest["granules"][1]["sha256"] = "0" * 64
    (raw / "imerg_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(WeatherError, match="sha256"):
        run_build(raw, write_ingest(tmp_path / "nisar"), tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_aoi_outside_the_grid_is_rejected(tmp_path: Path) -> None:
    raw = write_raw(tmp_path / "raw", {d: grid(0.0) for d in DAYS})
    ingest = write_ingest(tmp_path / "nisar")
    doc = json.loads((ingest / "ingest.json").read_text(encoding="utf-8"))
    doc["aoi"]["crop_bbox_4326"] = [10.0, 10.0, 10.1, 10.1]
    (ingest / "ingest.json").write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(WeatherError, match="AOI"):
        run_build(raw, ingest, tmp_path / "out")


def test_cli_reports_errors_with_exit_code(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = ["build", "--raw-dir", str(tmp_path / "missing"), "--ingest-dir", str(tmp_path)]
    assert main([*args, "--output-dir", str(tmp_path / "out")]) == 2
    assert "weather error" in capsys.readouterr().err


# --------------------------------------------------------------------------- fetch (offline)

CMR_SAMPLE = {
    "feed": {
        "entry": [
            {
                "title": "GPM_3IMERGDL.07:3B-DAY-L.MS.MRG.3IMERG.20260817-S000000-E235959.V07C.nc4",
                "time_start": "2026-08-17T00:00:00.000Z",
                "links": [
                    {"href": "s3://bucket/x.nc4"},
                    {
                        "href": "https://data.example/a/3B-DAY-L.MS.MRG.3IMERG.20260817-S000000-E235959.V07C.nc4"
                    },
                    {
                        "href": "https://data.example/a/3B-DAY-L.MS.MRG.3IMERG.20260817-S000000-E235959.V07C.nc4.xml"
                    },
                ],
            },
            {
                "title": "GPM_3IMERGDL.07:3B-DAY-L.MS.MRG.3IMERG.20260816-S000000-E235959.V07C.nc4",
                "time_start": "2026-08-16T00:00:00.000Z",
                "links": [
                    {
                        "href": "https://data.example/a/3B-DAY-L.MS.MRG.3IMERG.20260816-S000000-E235959.V07C.nc4"
                    }
                ],
            },
        ]
    }
}


def test_parse_cmr_keeps_https_nc4_sorted_by_date() -> None:
    granules = parse_cmr_granules(CMR_SAMPLE)
    assert [g["date"] for g in granules] == ["2026-08-16", "2026-08-17"]
    assert all(g["url"].startswith("https://") and g["url"].endswith(".nc4") for g in granules)


def test_fetch_writes_manifest_without_the_token(tmp_path: Path) -> None:
    token = "SECRET-TOKEN-VALUE"
    seen: list[str] = []

    def fake_download(url: str, bearer: str) -> bytes:
        assert bearer == token
        seen.append(url)
        return b"payload-" + url[-30:].encode()

    manifest = fetch(
        parse_cmr_granules(CMR_SAMPLE), tmp_path / "raw", token, download=fake_download
    )
    assert len(seen) == 2 and len(manifest["granules"]) == 2
    text = (tmp_path / "raw" / "imerg_manifest.json").read_text(encoding="utf-8")
    assert token not in text
    for g in manifest["granules"]:
        data = (tmp_path / "raw" / g["file"]).read_bytes()
        assert g["sha256"] == hashlib.sha256(data).hexdigest()
    # A second fetch reuses verified files instead of downloading again.
    fetch(parse_cmr_granules(CMR_SAMPLE), tmp_path / "raw", token, download=fake_download)
    assert len(seen) == 2


def test_fetch_requires_a_token(tmp_path: Path) -> None:
    with pytest.raises(WeatherError, match="token"):
        fetch(parse_cmr_granules(CMR_SAMPLE), tmp_path / "raw", "", download=lambda *_: b"")


def test_module_exposes_imerg_identity() -> None:
    assert weather.SHORT_NAME == "GPM_3IMERGDL"


def test_float32_longitudes_like_real_imerg_are_accepted(tmp_path: Path) -> None:
    # Real IMERG lon is float32: spacing jitters by about 1e-5 deg around 0.1 deg.
    values = grid(3.0)
    lon, lat, precip = read_daily_grid(write_day(tmp_path / "d.nc4", values, np.float32))
    assert np.array_equal(lon, LON)
    assert sum(cell_weights(lon, lat, AOI).values()) == pytest.approx(1.0)
