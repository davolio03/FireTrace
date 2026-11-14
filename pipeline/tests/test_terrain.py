"""DT-05 terrain context: DEM pinning, slope/aspect/hillshade, radar geometry and web layers.

Synthetic planes with hand-computable slopes on a synthetic 10 m grid; no real data is used.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pytest
import rasterio
from affine import Affine
from rasterio.crs import CRS
from rasterio.warp import transform as warp_transform

from pipeline import terrain
from pipeline.terrain import (
    LAYOVER,
    NONE,
    SHADOW,
    UNKNOWN,
    RadarGrid,
    TerrainError,
    aspect_deg,
    hillshade,
    horn_gradient,
    interpolate_cube,
    layover_shadow,
    load_config,
    local_incidence_deg,
    main,
    run_terrain,
    slope_deg,
)

UTM10N = CRS.from_epsg(32610)
X0, Y0 = 600_000.0, 3_970_000.0
W, H = 40, 30
TRANSFORM = Affine(10.0, 0.0, X0, 0.0, -10.0, Y0)
H5_NAME = "NISAR_L2_PR_GCOV_032_042_D_070_4005_DHDH_A_20261003T025638_20261003T025713_x.h5"


def plane(a: float, b: float, rows: int = 7, cols: int = 7, c: float = 100.0) -> np.ndarray:
    """z = c + a*x_east + b*y_north sampled at 10 m pixel centres (row 0 = north)."""
    x = (np.arange(cols) + 0.5) * 10.0
    y = -(np.arange(rows) + 0.5) * 10.0
    return c + a * x[None, :] + b * y[:, None]


# --------------------------------------------------------------------------- derivatives


def test_horn_gradient_is_exact_on_a_plane_and_nan_on_the_border():
    p, q = horn_gradient(plane(0.3, -0.2), 10.0)
    np.testing.assert_allclose(p[1:-1, 1:-1], 0.3, atol=1e-12)
    np.testing.assert_allclose(q[1:-1, 1:-1], -0.2, atol=1e-12)
    for arr in (p, q):
        assert np.isnan(arr[0]).all() and np.isnan(arr[-1]).all()
        assert np.isnan(arr[:, 0]).all() and np.isnan(arr[:, -1]).all()


def test_horn_gradient_propagates_nodata_to_neighbours():
    z = plane(0.3, 0.0)
    z[3, 3] = np.nan
    p, _ = horn_gradient(z, 10.0)
    assert np.isnan(p[2:5, 2:5]).all()
    assert np.isfinite(p[1, 1]) and np.isfinite(p[5, 5])


@pytest.mark.parametrize(
    ("a", "b", "aspect"),
    [
        (math.tan(math.radians(20)), 0.0, 270.0),  # rises east -> faces west
        (-math.tan(math.radians(20)), 0.0, 90.0),  # rises west -> faces east
        (0.0, -math.tan(math.radians(20)), 0.0),  # rises south -> faces north
        (0.0, math.tan(math.radians(20)), 180.0),  # rises north -> faces south
    ],
)
def test_slope_and_aspect_of_tilted_planes(a: float, b: float, aspect: float):
    p, q = horn_gradient(plane(a, b), 10.0)
    np.testing.assert_allclose(slope_deg(p, q)[1:-1, 1:-1], 20.0, atol=1e-9)
    np.testing.assert_allclose(aspect_deg(p, q)[1:-1, 1:-1], aspect, atol=1e-9)


def test_flat_terrain_has_zero_slope_and_undefined_aspect():
    p, q = horn_gradient(np.full((5, 5), 42.0), 10.0)
    assert (slope_deg(p, q)[1:-1, 1:-1] == 0.0).all()
    assert np.isnan(aspect_deg(p, q)[1:-1, 1:-1]).all()


def test_aspect_stays_in_0_360():
    a = math.tan(math.radians(10))
    p, q = horn_gradient(plane(-a * 1e-9, -a), 10.0)  # faces (almost exactly) north
    asp = aspect_deg(p, q)[1:-1, 1:-1]
    assert ((asp >= 0.0) & (asp < 360.0)).all()


def test_hillshade_matches_the_closed_form():
    s, asp = np.array([30.0, 0.0, np.nan]), np.array([270.0, np.nan, 0.0])
    hs = hillshade(s, asp, azimuth_deg=315.0, altitude_deg=45.0)
    zen = math.radians(45.0)
    expected = math.cos(zen) * math.cos(math.radians(30)) + math.sin(zen) * math.sin(
        math.radians(30)
    ) * math.cos(math.radians(45))
    assert hs[0] == pytest.approx(expected, abs=1e-12)
    assert hs[1] == pytest.approx(math.cos(zen), abs=1e-12)  # flat: aspect irrelevant
    assert np.isnan(hs[2])


def test_hillshade_clips_self_shadow_to_zero():
    hs = hillshade(np.array([80.0]), np.array([135.0]), azimuth_deg=315.0, altitude_deg=10.0)
    assert hs[0] == 0.0


# --------------------------------------------------------------------------- radar geometry

THETA = 40.0
LOS_E, LOS_N = math.sin(math.radians(THETA)), 0.0  # sensor to the east (target -> sensor)


def _geometry(a: float):
    p = np.full((1, 1), a)
    q = np.zeros((1, 1))
    inc = np.full((1, 1), THETA)
    e, n = np.full((1, 1), LOS_E), np.full((1, 1), LOS_N)
    return p, q, inc, e, n


@pytest.mark.parametrize(
    ("a", "flag", "local"),
    [
        (0.0, NONE, 40.0),  # flat: local incidence = ellipsoid incidence
        (-math.tan(math.radians(30)), NONE, 10.0),  # foreslope 30 deg < 40
        (-math.tan(math.radians(45)), LAYOVER, 5.0),  # foreslope 45 deg > 40 -> layover
        (math.tan(math.radians(30)), NONE, 70.0),  # backslope 30 deg: 70 < 90
        (math.tan(math.radians(55)), SHADOW, 95.0),  # backslope 55 deg: 95 > 90 -> shadow
    ],
)
def test_layover_shadow_and_local_incidence_on_range_slopes(a: float, flag: int, local: float):
    p, q, inc, e, n = _geometry(a)
    assert layover_shadow(p, q, inc, e, n)[0, 0] == flag
    assert local_incidence_deg(p, q, inc, e, n)[0, 0] == pytest.approx(local, abs=1e-9)


def test_azimuth_slopes_do_not_trigger_range_flags():
    p = np.zeros((1, 1))
    q = np.full((1, 1), math.tan(math.radians(60)))  # steep, but along azimuth
    inc, e, n = np.full((1, 1), THETA), np.full((1, 1), LOS_E), np.full((1, 1), LOS_N)
    assert layover_shadow(p, q, inc, e, n)[0, 0] == NONE


def test_unknown_geometry_is_flagged_unknown():
    p, q, inc, e, n = _geometry(np.nan)
    assert layover_shadow(p, q, inc, e, n)[0, 0] == UNKNOWN
    assert np.isnan(local_incidence_deg(p, q, inc, e, n)[0, 0])
    p, q, inc, e, n = _geometry(0.0)
    inc[:] = np.nan
    assert layover_shadow(p, q, inc, e, n)[0, 0] == UNKNOWN


def test_interpolate_cube_is_exact_for_trilinear_fields():
    xs = 599_000.0 + 500.0 * np.arange(6)
    ys = 3_971_000.0 - 500.0 * np.arange(5)
    hs = np.array([-1000.0, -500.0, 0.0, 500.0, 1000.0])
    cube = 2.0 * xs[None, None, :] / 1000 + 3.0 * ys[None, :, None] / 1000 + 0.5 * hs[:, None, None]
    px = X0 + 10.0 * (np.arange(W) + 0.5)
    py = Y0 - 10.0 * (np.arange(H) + 0.5)
    z = np.linspace(-200.0, 800.0, W * H).reshape(H, W)
    out = interpolate_cube(cube, xs, ys, hs, px, py, z)
    expected = 2.0 * px[None, :] / 1000 + 3.0 * py[:, None] / 1000 + 0.5 * z
    np.testing.assert_allclose(out, expected, rtol=0, atol=1e-6)


def test_interpolate_cube_refuses_points_outside_the_cube():
    xs = np.array([0.0, 500.0])
    ys = np.array([500.0, 0.0])
    hs = np.array([0.0, 500.0])
    cube = np.zeros((2, 2, 2))
    with pytest.raises(TerrainError, match="height"):
        interpolate_cube(
            cube, xs, ys, hs, np.array([100.0]), np.array([100.0]), np.full((1, 1), 900)
        )
    with pytest.raises(TerrainError, match="footprint"):
        interpolate_cube(cube, xs, ys, hs, np.array([700.0]), np.array([100.0]), np.zeros((1, 1)))


# --------------------------------------------------------------------------- end to end

A = math.tan(math.radians(20))  # rises east
B = math.tan(math.radians(10))  # rises north


def write_dem(path: Path, *, crs: CRS = UTM10N, extent_m: float = 400.0) -> Path:
    """30 m float32 DEM of the plane z = 200 + A*(x-X0) + B*(y-Y0) around the crop."""
    res = 30.0
    left, top = X0 - extent_m, Y0 + extent_m
    cols = int((W * 10 + 2 * extent_m) / res)
    rows = int((H * 10 + 2 * extent_m) / res)
    x = left + (np.arange(cols) + 0.5) * res
    y = top - (np.arange(rows) + 0.5) * res
    z = 200.0 + A * (x[None, :] - X0) + B * (y[:, None] - Y0)
    profile = {
        "driver": "GTiff",
        "width": cols,
        "height": rows,
        "count": 1,
        "dtype": "float32",
        "crs": crs,
        "transform": Affine(res, 0.0, left, 0.0, -res, top),
    }
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(z.astype(np.float32), 1)
    return path


def write_ingest(root: Path, transform: Affine = TRANSFORM) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    doc = {
        "ingest_format_version": 1,
        "case_id": "synthetic",
        "acquisition": {"track": 42, "frame": 70, "direction": "descending"},
        "epochs": {
            "t1": {"datetime": "2026-08-16T02:56:39Z"},
            "t2": {"datetime": "2026-10-03T02:56:38Z"},
        },
        "grid": {
            "crs": "EPSG:32610",
            "crop": {"transform": list(transform)[:6], "width": W, "height": H},
        },
    }
    (root / "ingest.json").write_text(json.dumps(doc), encoding="utf-8")
    return root


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def synthetic_radar_grid(path: Path, bounds: tuple[float, float, float, float]) -> RadarGrid:
    xs = X0 - 1000.0 + 500.0 * np.arange(6)
    ys = Y0 + 1000.0 - 500.0 * np.arange(6)
    hs = np.array([-1000.0, 0.0, 1000.0, 2000.0])
    shape = (hs.size, ys.size, xs.size)
    return RadarGrid(
        xs=xs,
        ys=ys,
        heights=hs,
        incidence_deg=np.full(shape, THETA),
        los_east=np.full(shape, LOS_E),
        los_north=np.full(shape, LOS_N),
    )


@pytest.fixture
def case(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(terrain, "read_radar_grid", synthetic_radar_grid)
    raw = tmp_path / "raw"
    raw.mkdir()
    dem = write_dem(raw / "dem.tif")
    h5 = raw / H5_NAME
    h5.write_bytes(b"synthetic radar grid placeholder")
    ingest = write_ingest(tmp_path / "nisar")
    out = tmp_path / "terrain"
    config = tmp_path / "terrain.toml"

    def write_config(**over: object) -> Path:
        values: dict[str, object] = {"dem": dem.as_posix(), "h5": h5.as_posix(), "margin_m": 100.0}
        values.update(over)
        values.setdefault("dem_sha", sha(Path(str(values["dem"]))))
        values.setdefault("h5_sha", sha(Path(str(values["h5"]))))
        config.write_text(
            f"""
ingest_dir = "{ingest.as_posix()}"
output_dir = "{out.as_posix()}"
margin_m = {values["margin_m"]}
hillshade_azimuth_deg = 315.0
hillshade_altitude_deg = 45.0

[dem]
raw = "{values["dem"]}"
sha256 = "{values["dem_sha"]}"
product_id = "SYNTHETIC_DEM"
url = "https://example.org/dem.tif"
source_label = "Synthetic DEM"
source_url = "https://example.org/dem"
vertical_datum = "EGM2008"

[geometry]
h5 = "{values["h5"]}"
sha256 = "{values["h5_sha"]}"
epoch = "t2"
""",
            encoding="utf-8",
        )
        return config

    write_config()
    return {
        "dem": dem,
        "h5": h5,
        "ingest": ingest,
        "out": out,
        "config": config,
        "write_config": write_config,
        "raw": raw,
    }


def read(path: Path) -> tuple[np.ndarray, rasterio.profiles.Profile]:
    with rasterio.open(path) as src:
        return src.read(1), src.profile


def test_run_builds_grid_aligned_terrain_products(case):
    doc = run_terrain(load_config(case["config"]))
    out = case["out"]
    assert sorted(p.name for p in out.iterdir()) == sorted(terrain.OUTPUT_FILES)
    for name in ("elevation.tif", "slope.tif", "aspect.tif", "local_incidence.tif"):
        data, prof = read(out / name)
        assert prof["crs"] == UTM10N and prof["transform"] == TRANSFORM
        assert (prof["width"], prof["height"]) == (W, H) and data.dtype == np.float32
    elev, _ = read(out / "elevation.tif")
    # Pixel (row 10, col 20) centre: x = X0 + 205, y = Y0 - 105.
    assert elev[10, 20] == pytest.approx(200.0 + A * 205.0 - B * 105.0, abs=1e-3)
    slope, _ = read(out / "slope.tif")
    expected_slope = math.degrees(math.atan(math.hypot(A, B)))
    np.testing.assert_allclose(slope, expected_slope, atol=1e-3)
    aspect, _ = read(out / "aspect.tif")
    expected_aspect = math.degrees(math.atan2(-A, -B)) % 360.0
    np.testing.assert_allclose(aspect, expected_aspect, atol=1e-3)
    flags, prof = read(out / "layover_shadow.tif")
    assert prof["nodata"] == UNKNOWN and flags.dtype == np.uint8
    assert (flags == NONE).all()  # 20 deg backslope with a 40 deg look: no flag
    assert doc["layover_shadow"]["none"] == W * H
    assert doc["dem"]["sha256"] == sha(case["dem"])
    assert doc["geometry"]["sha256"] == sha(case["h5"])
    assert doc["grid"]["transform"] == list(TRANSFORM)[:6]
    assert doc["layers"]["slope"]["valid"] == W * H


def test_run_writes_web_layers_fragment(case):
    run_terrain(load_config(case["config"]))
    out = case["out"]
    fragment = json.loads((out / "terrain_layers.json").read_text(encoding="utf-8"))
    assert fragment["contract_version"] == "1.2.0" and fragment["data_status"] == "real"
    layers = {layer["id"]: layer for layer in fragment["layers"]}
    assert set(layers) == {"hillshade", "slope"}
    for lid, layer in layers.items():
        assert layer["group"] == "terrain" and layer["kind"] == "raster"
        assert layer["url"] == f"layers/{lid}.png"
        assert layer["source"]["label"] == "Synthetic DEM"
        assert layer["source"]["product_id"] == "SYNTHETIC_DEM"
        with rasterio.open(out / f"{lid}.png") as png:
            assert (png.width, png.height) == (layer["width_px"], layer["height_px"])
            assert png.count == 4
        assert len(layer["coordinates"]) == 4
    assert layers["slope"]["legend"]["type"] == "continuous"
    assert layers["slope"]["legend"]["units"] == "degrees"
    assert layers["hillshade"]["legend"]["type"] == "rgb"


def test_reruns_are_byte_identical(case):
    run_terrain(load_config(case["config"]))
    first = {p.name: p.read_bytes() for p in case["out"].iterdir()}
    run_terrain(load_config(case["config"]))
    second = {p.name: p.read_bytes() for p in case["out"].iterdir()}
    assert first == second


def test_dem_in_geographic_crs_is_warped_to_the_crop_grid(case, tmp_path: Path):
    flat = tmp_path / "flat4326.tif"
    (lon,), (lat,) = warp_transform(UTM10N, CRS.from_epsg(4326), [X0 - 300.0], [Y0 + 300.0])
    profile = {
        "driver": "GTiff",
        "width": 60,
        "height": 60,
        "count": 1,
        "dtype": "float32",
        "crs": CRS.from_epsg(4326),
        "transform": Affine(1 / 3600, 0, lon, 0, -1 / 3600, lat),
    }
    with rasterio.open(flat, "w", **profile) as dst:
        dst.write(np.full((60, 60), 321.0, dtype=np.float32), 1)
    case["write_config"](dem=flat.as_posix(), dem_sha=sha(flat))
    run_terrain(load_config(case["config"]))
    elev, _ = read(case["out"] / "elevation.tif")
    slope, _ = read(case["out"] / "slope.tif")
    np.testing.assert_allclose(elev, 321.0, atol=1e-4)
    np.testing.assert_allclose(slope, 0.0, atol=1e-6)


def test_dem_checksum_mismatch_exits_2_and_writes_nothing(case, capsys):
    case["write_config"](dem_sha="0" * 64)
    assert main(["--config", str(case["config"])]) == 2
    assert "sha256" in capsys.readouterr().err
    assert not case["out"].exists()


def test_geometry_checksum_mismatch_is_an_error(case):
    case["write_config"](h5_sha="f" * 64)
    with pytest.raises(TerrainError, match="sha256"):
        run_terrain(load_config(case["config"]))


def test_failed_rerun_keeps_previous_outputs(case):
    run_terrain(load_config(case["config"]))
    before = {p.name: p.read_bytes() for p in case["out"].iterdir()}
    case["write_config"](dem_sha="0" * 64)
    with pytest.raises(TerrainError):
        run_terrain(load_config(case["config"]))
    assert {p.name: p.read_bytes() for p in case["out"].iterdir()} == before


def test_dem_that_does_not_cover_the_crop_is_an_error(case, tmp_path: Path):
    small = write_dem(tmp_path / "small.tif", extent_m=-60.0)  # stops short of the margin
    case["write_config"](dem=small.as_posix(), dem_sha=sha(small))
    with pytest.raises(TerrainError, match="cover"):
        run_terrain(load_config(case["config"]))


def test_foreign_files_in_output_dir_are_refused(case):
    case["out"].mkdir()
    (case["out"] / "notes.txt").write_text("mine", encoding="utf-8")
    with pytest.raises(TerrainError, match="does not own"):
        run_terrain(load_config(case["config"]))


def test_non_10m_ingest_grid_is_refused(case):
    write_ingest(case["ingest"], Affine(20.0, 0.0, X0, 0.0, -20.0, Y0))
    with pytest.raises(TerrainError, match="10 m"):
        run_terrain(load_config(case["config"]))


def test_geometry_granule_must_match_the_ingest_acquisition(case):
    other = case["raw"] / H5_NAME.replace("_042_D_070_", "_043_D_070_")
    case["h5"].rename(other)
    case["write_config"](h5=other.as_posix(), h5_sha=sha(other))
    with pytest.raises(TerrainError, match="track"):
        run_terrain(load_config(case["config"]))


def test_missing_config_key_is_an_error(case):
    case["config"].write_text('ingest_dir = "x"\n', encoding="utf-8")
    with pytest.raises(TerrainError, match="missing"):
        load_config(case["config"])


def test_margin_must_cover_the_horn_window(case):
    case["write_config"](margin_m=5.0)
    with pytest.raises(TerrainError, match="margin_m"):
        load_config(case["config"])
