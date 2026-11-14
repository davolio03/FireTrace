"""DT-01 ingest: grid checks, AOI window snapping, crop fidelity and determinism.

All rasters are small synthetic GeoTIFFs written to ``tmp_path``; no real data is used.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import rasterio
from affine import Affine
from rasterio.crs import CRS
from rasterio.warp import transform as warp_transform

from pipeline.ingest import (
    IngestError,
    check_common_grid,
    load_config,
    main,
    read_grid,
    run_ingest,
    snap_window,
)

UTM10N = CRS.from_epsg(32610)
# 200 x 160 px synthetic grid at 10 m (2 km x 1.6 km), origin on a 10 m multiple.
ORIGIN_X, ORIGIN_Y = 600_000.0, 3_970_000.0
WIDTH, HEIGHT = 200, 160
TRANSFORM = Affine(10.0, 0.0, ORIGIN_X, 0.0, -10.0, ORIGIN_Y)
NAMES = ("t1_hh", "t1_hv", "t2_hh", "t2_hv")


def write_raster(
    path: Path,
    data: np.ndarray,
    *,
    crs: CRS = UTM10N,
    transform: Affine = TRANSFORM,
    nodata: float | None = float("nan"),
) -> Path:
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=data.shape[1],
        height=data.shape[0],
        count=1,
        dtype=data.dtype,
        crs=crs,
        transform=transform,
        nodata=nodata,
    ) as ds:
        ds.write(data, 1)
    return path


def synthetic_power(seed: int, shape: tuple[int, int] = (HEIGHT, WIDTH)) -> np.ndarray:
    rng = np.random.default_rng(seed)
    data = rng.gamma(1.0, 0.1, size=shape).astype(np.float32)
    data[0:5, :] = np.nan  # no-data stripe
    data[50, 60] = 0.0  # zero power must be copied unchanged (masking is DT-02)
    return data


def write_perimeter(path: Path, utm_box: tuple[float, float, float, float]) -> Path:
    """GeoJSON (EPSG:4326) square perimeter whose UTM footprint is ``utm_box``."""
    min_x, min_y, max_x, max_y = utm_box
    xs = [min_x, max_x, max_x, min_x, min_x]
    ys = [min_y, min_y, max_y, max_y, min_y]
    lons, lats = warp_transform(UTM10N, CRS.from_epsg(4326), xs, ys)
    feature = {
        "type": "Feature",
        "id": 58728,
        "properties": {"OBJECTID": 58728},
        "geometry": {
            "type": "Polygon",
            "coordinates": [list(map(list, zip(lons, lats, strict=True)))],
        },
    }
    path.write_text(
        json.dumps({"type": "FeatureCollection", "features": [feature]}), encoding="utf-8"
    )
    return path


def write_case(
    tmp_path: Path,
    *,
    utm_box: tuple[float, float, float, float] = (600_500.0, 3_968_900.0, 601_200.0, 3_969_500.0),
    margin_m: float = 200.0,
    overrides: dict[str, dict[str, Any]] | None = None,
    output_dir: str = "out",
    grid_crs: str = "EPSG:32610",
    pixel_size_m: float = 10.0,
) -> Path:
    raw = tmp_path / "raw"
    raw.mkdir(exist_ok=True)
    overrides = overrides or {}
    for seed, name in enumerate(NAMES):
        kwargs = overrides.get(name, {})
        data = kwargs.pop("data", synthetic_power(seed))
        write_raster(raw / f"{name}.tif", data, **kwargs)
    write_perimeter(raw / "perimeter.geojson", utm_box)
    config = tmp_path / "ingest.toml"
    config.write_text(
        f"""
case_id = "synthetic"
product = "SYNTHETIC_GCOV"
output_dir = "{output_dir}"

[aoi]
perimeter = "raw/perimeter.geojson"
objectid = 58728
margin_m = {margin_m}

[grid]
crs = "{grid_crs}"
pixel_size_m = {pixel_size_m}

[acquisition]
track = 42
frame = 70
direction = "descending"
frequency = "A"

[epochs.t1]
label = "Before"
datetime = "2026-08-16T02:56:39Z"
granule_id = "G-T1"
absolute_orbit = 1
hh = "raw/t1_hh.tif"
hv = "raw/t1_hv.tif"

[epochs.t2]
label = "After"
datetime = "2026-10-03T02:56:38Z"
granule_id = "G-T2"
absolute_orbit = 2
hh = "raw/t2_hh.tif"
hv = "raw/t2_hv.tif"
""",
        encoding="utf-8",
    )
    return config


def ingest(tmp_path: Path, **kwargs: Any) -> dict[str, Any]:
    config = write_case(tmp_path, **kwargs)
    return run_ingest(load_config(config, base_dir=tmp_path))


# --------------------------------------------------------------------------- grid checks


def test_matching_grids_are_accepted(tmp_path: Path) -> None:
    doc = ingest(tmp_path)
    assert doc["grid"]["crs"] == "EPSG:32610"
    assert doc["grid"]["source"]["width"] == WIDTH
    assert doc["grid"]["source"]["height"] == HEIGHT
    assert sorted(doc["outputs"]) == sorted(NAMES)
    for name in NAMES:
        assert (tmp_path / "out" / f"{name}.tif").is_file()
    assert (tmp_path / "out" / "ingest.json").is_file()


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"crs": CRS.from_epsg(32611)}, "CRS"),
        ({"transform": Affine(10.0, 0.0, ORIGIN_X + 10.0, 0.0, -10.0, ORIGIN_Y)}, "transform"),
        ({"data": synthetic_power(9, shape=(HEIGHT, WIDTH + 1))}, "shape"),
    ],
    ids=["crs", "transform", "shape"],
)
def test_grid_mismatch_fails(tmp_path: Path, override: dict[str, Any], message: str) -> None:
    with pytest.raises(IngestError, match=f"grid mismatch: {message} of t2_hv"):
        ingest(tmp_path, overrides={"t2_hv": override})
    assert not (tmp_path / "out").exists(), "no output may be written on a failed check"


def test_wrong_analysis_crs_fails(tmp_path: Path) -> None:
    crs = CRS.from_epsg(32611)
    overrides = {name: {"crs": crs} for name in NAMES}
    with pytest.raises(IngestError, match="expected analysis CRS"):
        ingest(tmp_path, overrides=overrides)


def test_non_float32_input_fails(tmp_path: Path) -> None:
    data = synthetic_power(0).astype(np.float64)
    with pytest.raises(IngestError, match="float32"):
        ingest(tmp_path, overrides={"t1_hh": {"data": data}})


def test_rotated_or_wrong_pixel_size_grid_fails(tmp_path: Path) -> None:
    paths = []
    for i, name in enumerate(NAMES):
        t = Affine(20.0, 0.0, ORIGIN_X, 0.0, -20.0, ORIGIN_Y)
        paths.append(write_raster(tmp_path / f"{name}.tif", synthetic_power(i), transform=t))
    grids = {p.stem: read_grid(p) for p in paths}
    with pytest.raises(IngestError, match="pixel size"):
        check_common_grid(grids, UTM10N, 10.0)


# --------------------------------------------------------------------------- AOI and window


def test_aoi_outside_raster_fails(tmp_path: Path) -> None:
    far_box = (700_000.0, 3_900_000.0, 700_500.0, 3_900_500.0)
    with pytest.raises(IngestError, match="exceeds the raster extent"):
        ingest(tmp_path, utm_box=far_box)


def test_aoi_partially_outside_raster_fails(tmp_path: Path) -> None:
    # Perimeter inside, but the margin pushes the AOI past the left edge.
    with pytest.raises(IngestError, match="exceeds the raster extent"):
        ingest(tmp_path, utm_box=(600_100.0, 3_968_900.0, 600_600.0, 3_969_500.0), margin_m=500.0)


def test_snap_window_covers_aoi_with_integer_offsets() -> None:
    aoi = (600_123.4, 3_968_456.7, 600_987.6, 3_969_501.0)
    w = snap_window(aoi, TRANSFORM, WIDTH, HEIGHT)
    assert (w.col_off, w.row_off, w.width, w.height) == (12, 49, 87, 106)
    crop_t = TRANSFORM @ Affine.translation(w.col_off, w.row_off)
    left, top = crop_t.c, crop_t.f
    right, bottom = left + w.width * 10.0, top - w.height * 10.0
    assert left <= aoi[0] < left + 10 and right - 10 < aoi[2] <= right
    assert bottom <= aoi[1] < bottom + 10 and top - 10 < aoi[3] <= top


def test_snap_window_on_exact_grid_lines_adds_no_extra_pixel() -> None:
    aoi = (600_100.0, 3_968_500.0, 600_300.0, 3_969_000.0)
    w = snap_window(aoi, TRANSFORM, WIDTH, HEIGHT)
    assert (w.col_off, w.row_off, w.width, w.height) == (10, 100, 20, 50)


def test_crop_is_aligned_to_native_grid(tmp_path: Path) -> None:
    doc = ingest(tmp_path)
    window = doc["grid"]["crop"]["window"]
    with rasterio.open(tmp_path / "out" / "t1_hh.tif") as ds:
        t = ds.transform
        assert (t.a, t.b, t.d, t.e) == (10.0, 0.0, 0.0, -10.0)
        assert t.c == ORIGIN_X + 10.0 * window["col_off"]
        assert t.f == ORIGIN_Y - 10.0 * window["row_off"]
        assert (ds.width, ds.height) == (window["width"], window["height"])
        assert ds.crs == UTM10N
    aoi = doc["aoi"]["aoi_bounds_projected"]
    crop = doc["aoi"]["crop_bounds_projected"]
    assert crop[0] <= aoi[0] and crop[1] <= aoi[1] and crop[2] >= aoi[2] and crop[3] >= aoi[3]
    west, south, east, north = doc["aoi"]["crop_bbox_4326"]
    assert -180 <= west < east <= 180 and -90 <= south < north <= 90


# --------------------------------------------------------------------------- values and no-data


@pytest.mark.parametrize("nodata", [float("nan"), -9999.0], ids=["nan", "numeric"])
def test_values_and_nodata_are_preserved(tmp_path: Path, nodata: float) -> None:
    data = synthetic_power(3)
    if not math.isnan(nodata):
        data[np.isnan(data)] = nodata
    overrides = {name: {"data": data.copy(), "nodata": nodata} for name in NAMES}
    # Perimeter touching the no-data stripe (rows 0-4) so it falls inside the crop.
    doc = ingest(
        tmp_path, utm_box=(600_500.0, 3_969_000.0, 601_200.0, 3_969_780.0), overrides=overrides
    )
    w = doc["grid"]["crop"]["window"]
    expected = data[
        w["row_off"] : w["row_off"] + w["height"], w["col_off"] : w["col_off"] + w["width"]
    ]
    with rasterio.open(tmp_path / "out" / "t2_hv.tif") as ds:
        out = ds.read(1)
        assert ds.dtypes[0] == "float32"
        if math.isnan(nodata):
            assert ds.nodata is not None and math.isnan(ds.nodata)
        else:
            assert ds.nodata == nodata
    np.testing.assert_array_equal(out, expected)  # NaN positions compared as equal
    assert (np.isnan(expected) if math.isnan(nodata) else expected == nodata).any()
    assert (expected == 0.0).any(), "zero power must be copied, not masked"


# ---------------------------------------------------------------- metadata and determinism


def test_ingest_json_records_checksums_and_epochs(tmp_path: Path) -> None:
    doc = ingest(tmp_path)
    on_disk = json.loads((tmp_path / "out" / "ingest.json").read_text(encoding="utf-8"))
    assert on_disk == doc
    assert doc["epochs"]["t1"]["granule_id"] == "G-T1"
    assert doc["epochs"]["t2"]["granule_id"] == "G-T2"
    assert doc["acquisition"]["crs"] == "EPSG:32610"
    assert doc["acquisition"]["polarizations"] == ["HH", "HV"]
    for name in NAMES:
        assert len(doc["inputs"][name]["sha256"]) == 64
        assert doc["inputs"][name]["nodata"] == "nan"
        assert doc["outputs"][name]["file"] == f"{name}.tif"
    assert len(doc["reference"]["sha256"]) == 64
    text = (tmp_path / "out" / "ingest.json").read_text(encoding="utf-8")
    assert str(tmp_path) not in text, "ingest.json must not leak local absolute paths"


def test_outputs_are_byte_identical_across_runs(tmp_path: Path) -> None:
    config = write_case(tmp_path)
    first = run_ingest(load_config(config, base_dir=tmp_path))
    first_bytes = {p.name: p.read_bytes() for p in sorted((tmp_path / "out").iterdir())}
    second = run_ingest(load_config(config, base_dir=tmp_path))
    second_bytes = {p.name: p.read_bytes() for p in sorted((tmp_path / "out").iterdir())}
    assert first == second
    assert first_bytes == second_bytes


def test_cli_reports_errors_with_exit_code(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "missing.toml"
    assert main(["--config", str(missing)]) == 2
    assert "ingest error" in capsys.readouterr().err


def test_corrupt_input_is_reported_by_cli(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    config = write_case(tmp_path)
    monkeypatch.chdir(tmp_path)  # the CLI resolves relative config paths against the cwd
    (tmp_path / "raw" / "t2_hv.tif").write_bytes(b"II*" + bytes(1) + b"not a real tiff")
    assert main(["--config", str(config)]) == 2
    assert "ingest error: t2_hv.tif" in capsys.readouterr().err


# --------------------------------------------------------------- safety and fixed grid


def test_output_dir_aliasing_inputs_fails_and_leaves_inputs_untouched(tmp_path: Path) -> None:
    config = write_case(tmp_path, output_dir="raw")
    before = {p.name: p.read_bytes() for p in sorted((tmp_path / "raw").iterdir())}
    with pytest.raises(IngestError, match="would overwrite input"):
        run_ingest(load_config(config, base_dir=tmp_path))
    after = {p.name: p.read_bytes() for p in sorted((tmp_path / "raw").iterdir())}
    assert after == before


@pytest.mark.parametrize(
    ("grid", "message"),
    [
        ({"pixel_size_m": 20.0}, "grid.pixel_size_m must be the analysis grid"),
        ({"grid_crs": "EPSG:32611"}, "grid.crs must be the analysis CRS"),
    ],
    ids=["pixel_size", "crs"],
)
def test_config_cannot_change_the_analysis_grid(
    tmp_path: Path, grid: dict[str, Any], message: str
) -> None:
    config = write_case(tmp_path, **grid)
    with pytest.raises(IngestError, match=message):
        load_config(config, base_dir=tmp_path)
