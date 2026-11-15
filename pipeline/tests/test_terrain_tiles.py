from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from pipeline import terrain_tiles as tt

BOUNDS = [-121.45, 35.86, -121.35, 35.95]


def write_dem(path: Path, west: float, north: float, size: int = 200) -> None:
    """A synthetic EPSG:4326 DEM: a ramp rising 10 m per pixel to the east."""
    data = np.tile(np.arange(size, dtype=np.float32) * 10.0, (size, 1))
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=size,
        height=size,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=from_origin(west, north, 1 / size, 1 / size),
    ) as dst:
        dst.write(data, 1)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def case(tmp_path: Path):
    dem = tmp_path / "dem.tif"
    write_dem(dem, -122.0, 36.0)

    def write_config(**override: object) -> Path:
        values = {
            "bounds": BOUNDS,
            "minzoom": 9,
            "maxzoom": 10,
            "precision_m": 1.0,
            "sha256": sha(dem),
            "output_dir": str(tmp_path / "out" / "terrain_tiles"),
            **override,
        }
        config = tmp_path / "tiles.toml"
        config.write_text(
            f"""
case_id = "test-case"
output_dir = "{values["output_dir"]}"

[[dem]]
raw = "{dem}"
sha256 = "{values["sha256"]}"
product_id = "synthetic"
url = "https://example.org/dem.tif"

[source]
label = "Synthetic DEM"
url = "https://example.org"
vertical_datum = "EGM2008"

[tiles]
bounds = {json.dumps(values["bounds"])}
minzoom = {values["minzoom"]}
maxzoom = {values["maxzoom"]}
tile_size = 256
precision_m = {values["precision_m"]}
""",
            encoding="utf-8",
        )
        return config

    return tmp_path, write_config


def test_tile_maths_matches_known_values() -> None:
    assert tt.lonlat_to_tile(0.0, 0.0, 1) == (1.0, 1.0)
    x, y = tt.lonlat_to_tile(-121.4, 35.9, 12)
    # Independent slippy-map formula (OpenStreetMap wiki).
    lat = math.radians(35.9)
    osm_y = (1 - math.log(math.tan(lat) + 1 / math.cos(lat)) / math.pi) / 2 * 2**12
    assert y == pytest.approx(osm_y)
    assert (math.floor(x), math.floor(y)) == (666, 1609)
    left, bottom, right, top = tt.tile_bounds_mercator(0, 0, 0)
    assert left == pytest.approx(-tt.ORIGIN_SHIFT_M)
    assert top == pytest.approx(tt.ORIGIN_SHIFT_M)
    assert right - left == pytest.approx(top - bottom)
    assert tt.tiles_for_bounds((-1.0, -1.0, 1.0, 1.0), 1) == [(0, 0), (0, 1), (1, 0), (1, 1)]


def test_terrarium_round_trip_and_precision() -> None:
    heights = np.array([[-11.0, 0.0], [123.4567, 1551.6]], dtype=np.float32)
    exact = tt.terrarium_decode(tt.terrarium_encode(heights))
    assert np.abs(exact - heights).max() <= 1 / 512 + 1e-6
    metre = tt.terrarium_decode(tt.terrarium_encode(heights, precision_m=1.0))
    assert metre.tolist() == [[-11.0, 0.0], [123.0, 1552.0]]
    assert tt.terrarium_encode(heights)[..., 3].min() == 255
    with pytest.raises(tt.TerrainTilesError):
        tt.terrarium_encode(np.array([np.nan], dtype=np.float32))


def test_builds_a_verified_pyramid_with_manifest(case) -> None:
    root, write_config = case
    assert tt.main(["--config", str(write_config())]) == 0
    out = root / "out" / "terrain_tiles"
    manifest = json.loads((out / "tiles.json").read_text())
    expected = [
        f"{z}/{x}/{y}.png" for z in (9, 10) for x, y in tt.tiles_for_bounds(tuple(BOUNDS), z)
    ]
    assert sorted(manifest["firetrace"]["outputs"]) == sorted(expected)
    for name, digest in manifest["firetrace"]["outputs"].items():
        assert sha(out / name) == digest
    assert manifest["encoding"] == "terrarium"
    assert manifest["bounds"] == BOUNDS
    assert manifest["firetrace"]["dem"][0]["sha256"] == sha(root / "dem.tif")
    elevation = manifest["firetrace"]["elevation_m_at_maxzoom"]
    assert 0 <= elevation["min"] < elevation["max"] <= 1990
    # The decoded maximum-zoom tile still rises to the east, in whole metres.
    name = next(n for n in expected if n.startswith("10/"))
    with rasterio.open(out / name) as src:
        decoded = tt.terrarium_decode(np.moveaxis(src.read(), 0, -1))
    assert np.array_equal(decoded, np.round(decoded))
    row = decoded[128]
    assert row[-1] > row[0]


def test_reruns_are_byte_identical(case) -> None:
    root, write_config = case
    config = write_config()
    assert tt.main(["--config", str(config)]) == 0
    first = (root / "out" / "terrain_tiles" / "tiles.json").read_bytes()
    assert tt.main(["--config", str(config)]) == 0
    assert (root / "out" / "terrain_tiles" / "tiles.json").read_bytes() == first
    assert not (root / "out" / ".terrain_tiles.staging").exists()
    assert not (root / "out" / ".terrain_tiles.previous").exists()


def test_rejects_a_dem_with_the_wrong_checksum(case, capsys) -> None:
    _, write_config = case
    assert tt.main(["--config", str(write_config(sha256="0" * 64))]) == 2
    assert "does not match the pinned" in capsys.readouterr().err


def test_rejects_bounds_the_dem_does_not_cover(case, capsys) -> None:
    root, write_config = case
    config = write_config(bounds=[-121.2, 35.86, -120.8, 35.95])
    assert tt.main(["--config", str(config)]) == 2
    assert "not covered by the DEM" in capsys.readouterr().err
    assert not (root / "out" / "terrain_tiles").exists()


def test_refuses_to_replace_foreign_content(case, capsys) -> None:
    root, write_config = case
    out = root / "out" / "terrain_tiles"
    out.mkdir(parents=True)
    (out / "notes.txt").write_text("keep me")
    assert tt.main(["--config", str(write_config())]) == 2
    assert "foreign entries" in capsys.readouterr().err
    assert (out / "notes.txt").read_text() == "keep me"


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"bounds": [1, 2, 3]}, "tiles.bounds"),
        ({"minzoom": 11, "maxzoom": 10}, "minzoom"),
        ({"precision_m": 50}, "precision_m"),
        ({"sha256": "abc"}, "64 lowercase hex"),
    ],
)
def test_rejects_invalid_configuration(case, capsys, override, message) -> None:
    _, write_config = case
    assert tt.main(["--config", str(write_config(**override))]) == 2
    assert message in capsys.readouterr().err
