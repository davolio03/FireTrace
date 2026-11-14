"""DT-03 reference perimeter: pinning, validation, web GeoJSON and analysis-grid masks.

Synthetic polygons with known areas on a synthetic 10 m grid; no real data is used.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import rasterio
from affine import Affine
from rasterio.crs import CRS
from rasterio.warp import transform as warp_transform
from shapely.geometry import Point, Polygon, box, shape

from pipeline import perimeter
from pipeline.perimeter import PerimeterError, load_config, main, run_perimeter
from pipeline.sar import SarError

UTM10N = CRS.from_epsg(32610)
WGS84 = CRS.from_epsg(4326)
X0, Y0 = 600_000.0, 3_970_000.0
W, H = 200, 160  # 2 km x 1.6 km crop
TRANSFORM = Affine(10.0, 0.0, X0, 0.0, -10.0, Y0)
DATETIME_MS = 1789418640000  # 2026-09-14T20:44:00Z


def _ring_to_lonlat(coords: list[tuple[float, float]]) -> list[list[float]]:
    xs, ys = zip(*coords, strict=True)
    lons, lats = warp_transform(UTM10N, WGS84, list(xs), list(ys))
    return [[lon, lat] for lon, lat in zip(lons, lats, strict=True)]


def utm_polygon_to_geojson(poly: Polygon) -> list[list[list[float]]]:
    rings = [list(poly.exterior.coords)] + [list(r.coords) for r in poly.interiors]
    return [_ring_to_lonlat(r) for r in rings]


def write_raw(path: Path, polygons: list[Polygon], **props: Any) -> Path:
    properties = {
        "OBJECTID": 58728,
        "poly_IncidentName": "Plaskett",
        "poly_FeatureCategory": "Wildfire Daily Fire Perimeter",
        "poly_MapMethod": "IR Image Interpretation",
        "poly_GISAcres": 10.0,
        "poly_PolygonDateTime": DATETIME_MS,
    }
    properties.update(props)
    geometry = {
        "type": "MultiPolygon",
        "coordinates": [utm_polygon_to_geojson(p) for p in polygons],
    }
    doc = {
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "properties": properties, "geometry": geometry}],
    }
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def write_ingest(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    doc = {
        "ingest_format_version": 1,
        "case_id": "synthetic",
        "grid": {
            "crs": "EPSG:32610",
            "crop": {"transform": list(TRANSFORM)[:6], "width": W, "height": H},
        },
    }
    (root / "ingest.json").write_text(json.dumps(doc), encoding="utf-8")
    return root


def write_case(
    tmp_path: Path,
    polygons: list[Polygon] | None = None,
    *,
    sha256: str | None = None,
    edge_distance_m: float = 50.0,
    datetime: str = "2026-09-14T20:44:00Z",
    **props: Any,
) -> Path:
    raw = tmp_path / "raw" / "perimeter.geojson"
    raw.parent.mkdir(parents=True, exist_ok=True)
    polygons = polygons or [box(X0 + 500, Y0 - 1100, X0 + 1100, Y0 - 700)]  # 600 x 400 m
    write_raw(raw, polygons, **props)
    digest = sha256 or hashlib.sha256(raw.read_bytes()).hexdigest()
    write_ingest(tmp_path / "nisar")
    config = tmp_path / "perimeter.toml"
    config.write_text(
        f"""
raw = "raw/perimeter.geojson"
sha256 = "{digest}"
objectid = 58728
polygon_datetime = "{datetime}"
url = "https://example.invalid/wfigs?where=OBJECTID%3D58728"
source = "NIFC WFIGS Interagency Perimeters YearToDate"
note = "Synthetic test perimeter."
ingest_dir = "nisar"
output_dir = "out"
edge_distance_m = {edge_distance_m}
""",
        encoding="utf-8",
    )
    return config


def run(tmp_path: Path, *args: Any, **kwargs: Any) -> dict[str, Any]:
    return run_perimeter(load_config(write_case(tmp_path, *args, **kwargs), base_dir=tmp_path))


def read_mask(path: Path) -> np.ndarray:
    with rasterio.open(path) as ds:
        assert ds.dtypes[0] == "uint8" and ds.crs == UTM10N and ds.transform == TRANSFORM
        assert (ds.height, ds.width) == (H, W)
        return ds.read(1)


# --------------------------------------------------------------------------- areas


def test_grid_aligned_square_gives_exact_pixel_count(tmp_path: Path) -> None:
    doc = run(tmp_path)
    mask = read_mask(tmp_path / "out" / "perimeter_mask.tif")
    assert int(mask.sum()) == 60 * 40 == doc["inside_pixels"]
    assert set(np.unique(mask)) == {0, 1}
    assert doc["area"]["vector_ha"] == pytest.approx(24.0, abs=1e-3)
    assert doc["area"]["raster_inside_ha"] == 24.0
    assert doc["rasterization"]["rule"] == "pixel_centre"


def test_pixel_centre_rule_differs_from_touched(tmp_path: Path) -> None:
    # Edges 3 m off the grid lines: a touched rule would add the partial pixels.
    poly = box(X0 + 503, Y0 - 1097, X0 + 1103, Y0 - 697)
    doc = run(tmp_path, [poly])
    # Pixel centres sit at 5, 15, ... m; a centre is inside if 503 < x < 1103 etc.
    assert doc["inside_pixels"] == 60 * 40
    assert doc["inside_pixels"] < 61 * 41  # what all_touched=True would give


def test_multipolygon_with_hole(tmp_path: Path) -> None:
    outer = Polygon(
        box(X0 + 200, Y0 - 600, X0 + 600, Y0 - 200).exterior.coords,
        [box(X0 + 300, Y0 - 500, X0 + 500, Y0 - 300).exterior.coords],
    )
    island = box(X0 + 1000, Y0 - 1000, X0 + 1100, Y0 - 900)
    doc = run(tmp_path, [outer, island])
    assert doc["inside_pixels"] == 40 * 40 - 20 * 20 + 10 * 10
    assert doc["geometry"]["polygon_count"] == 2
    assert doc["geometry"]["hole_count"] == 1
    mask = read_mask(tmp_path / "out" / "perimeter_mask.tif")
    assert mask[40, 40] == 0, "pixel in the hole is outside"
    assert mask[25, 25] == 1


def test_edge_band_covers_centres_near_the_boundary(tmp_path: Path) -> None:
    doc = run(tmp_path, edge_distance_m=50.0)
    band = read_mask(tmp_path / "out" / "perimeter_edge.tif")
    boundary = box(X0 + 500, Y0 - 1100, X0 + 1100, Y0 - 700).boundary
    rows, cols = np.indices((H, W))
    xs, ys = TRANSFORM * (cols + 0.5, rows + 0.5)
    for r, c in [(r, c) for r in range(0, H, 3) for c in range(0, W, 3)]:
        d = boundary.distance(Point(xs[r, c], ys[r, c]))
        if d < 49.0:
            assert band[r, c] == 1, (r, c, d)
        elif d > 51.0:
            assert band[r, c] == 0, (r, c, d)
    assert doc["edge_pixels"] == int(band.sum()) > 0
    assert doc["rasterization"]["edge_distance_m"] == 50.0


# --------------------------------------------------------------------------- web + manifest


def test_web_geojson_is_4326_full_geometry_with_contract_properties(tmp_path: Path) -> None:
    doc = run(tmp_path)
    web = json.loads((tmp_path / "out" / "perimeter.geojson").read_text(encoding="utf-8"))
    assert web["type"] == "FeatureCollection" and len(web["features"]) == 1
    feature = web["features"][0]
    props = feature["properties"]
    assert props["OBJECTID"] == 58728
    assert props["IncidentName"] == "Plaskett"
    assert props["PolygonDateTime"] == "2026-09-14T20:44:00Z"
    assert props["Source"] == "NIFC WFIGS Interagency Perimeters YearToDate"
    assert {"FeatureCategory", "MapMethod", "GISAcres"} <= set(props)
    geom = shape(feature["geometry"])
    lon, lat = geom.centroid.x, geom.centroid.y
    assert -180 <= lon <= 180 and -90 <= lat <= 90, "web geometry is lon/lat"
    raw = json.loads((tmp_path / "raw" / "perimeter.geojson").read_text(encoding="utf-8"))
    assert feature["geometry"]["coordinates"] == raw["features"][0]["geometry"]["coordinates"]
    assert doc["reference"] == {
        "source": "NIFC WFIGS Interagency Perimeters YearToDate",
        "objectid": 58728,
        "datetime": "2026-09-14T20:44:00Z",
        "url": "https://example.invalid/wfigs?where=OBJECTID%3D58728",
        "note": "Synthetic test perimeter.",
    }


def test_outputs_are_byte_identical_across_runs(tmp_path: Path) -> None:
    config = load_config(write_case(tmp_path), base_dir=tmp_path)
    run_perimeter(config)
    first = {p.name: p.read_bytes() for p in sorted((tmp_path / "out").iterdir())}
    run_perimeter(config)
    second = {p.name: p.read_bytes() for p in sorted((tmp_path / "out").iterdir())}
    assert first == second


def test_invalid_geometry_is_repaired_and_reported(tmp_path: Path) -> None:
    bowtie = Polygon(
        [
            (X0 + 500, Y0 - 700),
            (X0 + 1100, Y0 - 1100),
            (X0 + 1100, Y0 - 700),
            (X0 + 500, Y0 - 1100),
            (X0 + 500, Y0 - 700),
        ]
    )
    assert not bowtie.is_valid
    doc = run(tmp_path, [bowtie])
    assert doc["geometry"]["repaired"] is True
    assert doc["inside_pixels"] > 0


# --------------------------------------------------------------------------- failures


def test_checksum_mismatch_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(PerimeterError, match="sha256"):
        run(tmp_path, sha256="0" * 64)
    assert not (tmp_path / "out").exists()


def test_wrong_polygon_datetime_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(PerimeterError, match="PolygonDateTime"):
        run(tmp_path, datetime="2026-09-20T00:00:00Z")


def test_wrong_objectid_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(PerimeterError, match="OBJECTID"):
        run(tmp_path, OBJECTID=1)


def test_perimeter_outside_the_crop_is_an_error(tmp_path: Path) -> None:
    far = box(X0 + 50_000, Y0 - 50_400, X0 + 50_600, Y0 - 50_000)
    with pytest.raises(PerimeterError, match="no pixel"):
        run(tmp_path, [far])


def test_cli_reports_errors_with_exit_code(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--config", str(tmp_path / "missing.toml")]) == 2
    assert "perimeter error" in capsys.readouterr().err


# --------------------------------------------------------------- review regressions


@pytest.mark.parametrize(
    ("edge_x", "inside_band"), [(504.99, 1), (505.01, 0)], ids=["49.99m", "50.01m"]
)
def test_edge_band_threshold_is_exact(tmp_path: Path, edge_x: float, inside_band: int) -> None:
    # Left edge at X0 + edge_x; the centre of column 45 is at X0 + 455 (distance edge_x - 455).
    run(tmp_path, [box(X0 + edge_x, Y0 - 1100, X0 + 1100, Y0 - 700)], edge_distance_m=50.0)
    band = read_mask(tmp_path / "out" / "perimeter_edge.tif")
    assert band[90, 45] == inside_band  # row 90: centre y = Y0 - 905, mid-edge


def test_edge_band_includes_hole_boundaries(tmp_path: Path) -> None:
    outer = Polygon(
        box(X0 + 100, Y0 - 1500, X0 + 1900, Y0 - 100).exterior.coords,
        [box(X0 + 700, Y0 - 1000, X0 + 1300, Y0 - 600).exterior.coords],
    )
    run(tmp_path, [outer], edge_distance_m=50.0)
    band = read_mask(tmp_path / "out" / "perimeter_edge.tif")
    assert band[80, 72] == 1, "centre 25 m inside the hole edge"
    assert band[80, 100] == 0, "centre of the hole, 200 m from any boundary"
    assert band[80, 66] == 1, "centre 35 m outside the hole, inside the polygon"


@pytest.mark.parametrize("value", [DATETIME_MS + 999, DATETIME_MS + 0.5], ids=["ms", "fraction"])
def test_non_whole_second_datetime_is_rejected(tmp_path: Path, value: float) -> None:
    with pytest.raises(PerimeterError, match="PolygonDateTime"):
        run(tmp_path, poly_PolygonDateTime=value)


def test_failed_publication_keeps_the_previous_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = load_config(write_case(tmp_path), base_dir=tmp_path)
    run_perimeter(config)
    before = {p.name: p.read_bytes() for p in sorted((tmp_path / "out").iterdir())}

    def boom(*_args: Any) -> None:
        raise SarError("injected publish failure")

    monkeypatch.setattr(perimeter, "publish", boom)
    with pytest.raises(PerimeterError, match="injected"):
        run_perimeter(config)
    assert {p.name: p.read_bytes() for p in sorted((tmp_path / "out").iterdir())} == before
    assert sorted(p.name for p in tmp_path.iterdir() if p.name.startswith(".")) == []
