"""XP-04 review zones: hand-computed regions, ranking, geometry, statistics and safety.

Tiny synthetic rasters on the 10 m grid; no real data is used. The end-to-end tests build
the CH-01, DT-02, DT-03 and DT-05 directories, run the real XP-01 stage on them and then
this stage, so the manifest chain is the one the pipeline produces.
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
import shapely
from affine import Affine
from jsonschema import Draft202012Validator
from rasterio.crs import CRS
from shapely.geometry import LineString, Polygon, box, mapping

from pipeline import highlight, review_zones
from pipeline.highlight import HighlightConfig, HighlightParams, run_highlight
from pipeline.review_zones import (
    Region,
    ReviewZonesConfig,
    ReviewZonesError,
    ZoneParams,
    caveat_fractions,
    filled_valid_fraction,
    find_regions,
    kind_masks,
    load_config,
    main,
    perimeter_distance_m,
    rank_regions,
    region_geometry,
    run_review_zones,
)
from pipeline.sar import write_cog

ROOT = Path(__file__).resolve().parents[2]
UTM10N = CRS.from_epsg(32610)
X0, Y0 = 636_000.0, 3_984_000.0
TRANSFORM = Affine(10.0, 0.0, X0, 0.0, -10.0, Y0)
NAN = float("nan")


def _region(pixels: list[tuple[int, int]]) -> Region:
    rows, cols = zip(*sorted(pixels), strict=True)
    return Region(np.array(rows), np.array(cols))


# --------------------------------------------------------------------------- pure rules


def test_kind_masks_split_highlight_by_perimeter_and_threshold_little_change_inside():
    highlighted = np.array([[1, 1, 0, 0]], dtype=bool)
    smoothed = np.array([[3.0, 3.0, 0.0, -1.0]])
    inside = np.array([[1, 0, 1, 1]], dtype=bool)
    valid = np.array([[1, 1, 1, 1]], dtype=bool)
    masks = kind_masks(highlighted, smoothed, inside, valid, no_change_threshold=0.0)
    assert masks["change_inside_perimeter"].tolist() == [[True, False, False, False]]
    assert masks["change_outside_perimeter"].tolist() == [[False, True, False, False]]
    # <= is inclusive: exactly 0.0 counts as little change.
    assert masks["no_change_inside_perimeter"].tolist() == [[False, False, True, True]]


def test_kind_masks_never_use_invalid_pixels():
    highlighted = np.array([[1, 0]], dtype=bool)
    smoothed = np.array([[NAN, NAN]])
    inside = np.array([[1, 1]], dtype=bool)
    valid = np.array([[0, 0]], dtype=bool)
    masks = kind_masks(highlighted, smoothed, inside, valid, no_change_threshold=0.0)
    assert not any(m.any() for m in masks.values())


def test_diagonal_pixels_form_one_8_connected_region():
    mask = np.zeros((4, 4), dtype=bool)
    mask[0, 0] = mask[1, 1] = mask[2, 2] = True
    regions = find_regions(mask, min_px=3, connectivity=8)
    assert len(regions) == 1 and regions[0].size == 3
    assert find_regions(mask, min_px=1, connectivity=4)[0].size == 1


def test_regions_under_the_minimum_size_are_dropped():
    mask = np.zeros((3, 6), dtype=bool)
    mask[0, 0:3] = True  # 3 px
    mask[2, 5] = True  # 1 px
    sizes = [r.size for r in find_regions(mask, min_px=2, connectivity=8)]
    assert sizes == [3]
    assert find_regions(np.zeros((2, 2), dtype=bool), min_px=1, connectivity=8) == []


def test_rank_by_area_then_index_median_then_first_pixel():
    index = np.array(
        [
            [1.0, 1.0, 0.0, 5.0, 5.0, 0.0, 2.0, 2.0],
            [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            [9.0, 9.0, 9.0, 0.0, 3.0, 3.0, 0.0, 0.0],
        ]
    )
    big = _region([(2, 0), (2, 1), (2, 2)])
    low = _region([(0, 0), (0, 1)])
    high = _region([(0, 3), (0, 4)])
    tie_a = _region([(0, 6), (0, 7)])  # median 2.0, first pixel (0, 6)
    tie_b = _region([(2, 4), (2, 5)])  # median 3.0
    regions = [low, tie_a, high, big, tie_b]
    change = rank_regions(regions, index, "change_inside_perimeter")
    assert [r.first for r in change] == [(2, 0), (0, 3), (2, 4), (0, 6), (0, 0)]
    little = rank_regions(regions, index, "no_change_inside_perimeter")
    assert [r.first for r in little] == [(2, 0), (0, 0), (0, 6), (2, 4), (0, 3)]
    same = [_region([(1, 5), (1, 6)]), _region([(1, 0), (1, 1)])]
    zero = np.zeros((3, 8))
    assert [r.first for r in rank_regions(same, zero, "change_outside_perimeter")] == [
        (1, 0),
        (1, 5),
    ]


def test_region_geometry_is_the_exact_pixel_footprint_in_utm():
    region = _region([(0, 0), (0, 1), (1, 0), (1, 1), (2, 2)])  # 2x2 block + diagonal pixel
    geom = region_geometry(region, TRANSFORM)
    assert geom.is_valid and not geom.is_empty
    assert math.isclose(geom.area, 5 * 100.0)
    assert geom.bounds == (X0, Y0 - 30.0, X0 + 30.0, Y0)


def test_region_geometry_keeps_holes():
    pixels = [(r, c) for r in range(3) for c in range(3) if (r, c) != (1, 1)]
    geom = region_geometry(_region(pixels), TRANSFORM)
    assert math.isclose(geom.area, 800.0)
    assert isinstance(geom, Polygon) and len(geom.interiors) == 1


def test_valid_fraction_counts_invalid_holes_inside_the_zone():
    pixels = [(r, c) for r in range(3) for c in range(3) if (r, c) != (1, 1)]
    valid = np.ones((4, 4), dtype=bool)
    assert filled_valid_fraction(_region(pixels), valid) == 1.0
    valid[1, 1] = False  # an invalid hole: 8 of the 9 filled pixels are valid
    assert filled_valid_fraction(_region(pixels), valid) == pytest.approx(8 / 9)
    valid[3, 3] = False  # outside the zone: ignored
    assert filled_valid_fraction(_region(pixels), valid) == pytest.approx(8 / 9)


def test_caveat_fractions_follow_the_ev02_rules_and_are_always_listed():
    region = _region([(0, 0), (0, 1), (0, 2), (0, 3)])
    slope = np.array([[30.0, 30.01, NAN, 45.0]])
    flags = np.array([[0, 1, 2, 255]], dtype=np.uint8)
    edge = np.array([[0, 0, 0, 1]], dtype=bool)
    caveats = caveat_fractions(region, slope, flags, edge)
    assert [c["id"] for c in caveats] == [
        "steep_slope",
        "radar_shadow_layover",
        "near_perimeter_edge",
    ]
    fractions = {c["id"]: c["fraction"] for c in caveats}
    # > 30 strictly; NaN (unknown) never fires; 255 (unknown) never fires.
    assert fractions == {
        "steep_slope": 0.5,
        "radar_shadow_layover": 0.5,
        "near_perimeter_edge": 0.25,
    }
    assert (
        caveat_fractions(region, np.zeros((1, 4)), np.zeros((1, 4), np.uint8), ~edge | edge)[2][
            "fraction"
        ]
        == 1.0
    )
    quiet = caveat_fractions(region, np.zeros((1, 4)), np.zeros((1, 4), np.uint8), edge & False)
    assert [c["fraction"] for c in quiet] == [0.0, 0.0, 0.0]


def test_distance_is_zero_when_touching_and_metric_otherwise():
    line = LineString([(X0 + 50.0, Y0 - 100.0), (X0 + 50.0, Y0 + 100.0)])
    near = box(X0, Y0 - 10.0, X0 + 50.0, Y0)  # its right edge lies on the line
    far = box(X0, Y0 - 10.0, X0 + 20.0, Y0)
    assert perimeter_distance_m(near, line) == 0.0
    assert perimeter_distance_m(far, line) == 30.0
    assert perimeter_distance_m(box(X0, Y0 - 10.0, X0 + 20.4, Y0), line) == 30.0  # whole metres


# --------------------------------------------------------------------------- end to end

# 12 x 16 crop. The perimeter is the left half (columns 0-7), drawn as a polygon whose
# boundary runs along x = X0 + 80 m. Highlighted change (index 5) forms:
#   A: rows 0-2, cols 1-3 (9 px, inside)          -> CI
#   B: rows 0-1, cols 11-12 (4 px, outside)       -> CO
#   C: rows 5-6, cols 2-3 + (7, 4) (5 px, inside) -> CI, one diagonal pixel
# Little change (index -3) inside: rows 9-11, cols 0-2 (9 px) -> NI.
# Everything else is index 0.5 (neither highlighted nor little change).
H, W = 12, 16
INDEX = np.full((H, W), 0.5)
INDEX[0:3, 1:4] = 5.0
INDEX[0:2, 11:13] = 5.0
INDEX[5:7, 2:4] = 5.0
INDEX[7, 4] = 5.0
INDEX[9:12, 0:3] = -3.0
VALID = np.ones((H, W), dtype=np.uint8)
VALID[1, 2] = 0  # an invalid pixel inside zone A
INDEX[1, 2] = NAN
INSIDE = np.zeros((H, W), dtype=np.uint8)
INSIDE[:, 0:8] = 1
EDGE = np.zeros((H, W), dtype=np.uint8)
EDGE[:, 3:13] = 0
EDGE[:, 7:9] = 1  # pixel centres within 50 m... a 2-column band suffices for the test
SLOPE = np.full((H, W), 10.0, dtype=np.float32)
SLOPE[0, 1:4] = 40.0  # 3 of A's 8 valid pixels are steep
FLAGS = np.zeros((H, W), dtype=np.uint8)
FLAGS[0:2, 11] = 1  # 2 of B's 4 pixels are layover
PERIMETER_4326: dict[str, Any] = {}  # filled lazily from the UTM polygon below
PERIMETER_UTM = box(X0 - 100.0, Y0 - 200.0, X0 + 80.0, Y0 + 100.0)

# No smoothing and tiny minimum sizes keep the end-to-end values hand-computable.
HL_PARAMS = HighlightParams(threshold=2.0, window=1, min_region_px=2, connectivity=8)
PARAMS = ZoneParams(
    no_change_threshold=0.0, min_area_ha=0.04, max_zones_per_kind=10, simplify_tolerance_m=5.0
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path, doc: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=1), encoding="utf-8")


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _cog(path: Path, data: np.ndarray, nodata: float | None) -> dict[str, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_cog(path, data, crs=UTM10N, transform=TRANSFORM, nodata=nodata)
    return {"file": path.name, "sha256": _sha(path)}


GRID = {"crs": "EPSG:32610", "transform": list(TRANSFORM)[:6], "width": W, "height": H}


def _perimeter_geojson() -> dict[str, Any]:
    import geopandas as gpd

    geom = gpd.GeoSeries([PERIMETER_UTM], crs=UTM10N).to_crs("EPSG:4326").iloc[0]
    return {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "properties": {"OBJECTID": 58728}, "geometry": mapping(geom)}
        ],
    }


def write_upstream(
    root: Path,
    *,
    index: np.ndarray = INDEX,
    slope: np.ndarray = SLOPE,
    flags: np.ndarray = FLAGS,
    terrain_grid: dict[str, Any] | None = None,
) -> dict[str, Path]:
    """CH-01, DT-02, DT-03 and DT-05 directories with the manifest fields this stage reads."""
    d = {n: root / n for n in ("sar", "change", "perimeter", "terrain")}
    valid = VALID == 1
    t1_hh = np.where(valid, -10.0, NAN).astype(np.float32)
    t2_hh = np.where(valid, -10.0 - np.nan_to_num(index), NAN).astype(np.float32)
    t1_hv = np.where(valid, -18.0, NAN).astype(np.float32)
    t2_hv = np.where(valid, -18.0 - 0.5 * np.nan_to_num(index), NAN).astype(np.float32)
    ingest_sha = "c" * 64
    sar = {
        "sar_format_version": 1,
        "source_ingest": {"file": "ingest.json", "sha256": ingest_sha},
        "grid": GRID,
        "db": {
            "layers": {
                name: _cog(d["sar"] / f"{name}_db.tif", data, NAN)
                for name, data in (
                    ("t1_hh", t1_hh),
                    ("t2_hh", t2_hh),
                    ("t1_hv", t1_hv),
                    ("t2_hv", t2_hv),
                )
            }
        },
        "valid_mask": _cog(d["sar"] / "valid_mask.tif", VALID, None),
    }
    _json(d["sar"] / "sar.json", sar)
    change = {
        "change_format_version": 1,
        "grid": GRID,
        "method": {"id": "abs-logratio-hhhv-v1"},
        "source_sar": {"file": "sar.json", "sha256": _sha(d["sar"] / "sar.json")},
        "outputs": {
            "change_index": _cog(d["change"] / "change_index.tif", index.astype(np.float32), NAN),
            "change_hh_db": _cog(d["change"] / "change_hh_db.tif", t2_hh - t1_hh, NAN),
            "change_hv_db": _cog(d["change"] / "change_hv_db.tif", t2_hv - t1_hv, NAN),
        },
    }
    _json(d["change"] / "change.json", change)
    _json(d["perimeter"] / "perimeter.geojson", _perimeter_geojson())
    perimeter = {
        "perimeter_format_version": 1,
        "grid": GRID,
        "rasterization": {"rule": "pixel_centre", "all_touched": False, "edge_distance_m": 50.0},
        "outputs": {
            "perimeter.geojson": {
                "file": "perimeter.geojson",
                "sha256": _sha(d["perimeter"] / "perimeter.geojson"),
            },
            "perimeter_mask.tif": _cog(d["perimeter"] / "perimeter_mask.tif", INSIDE, None),
            "perimeter_edge.tif": _cog(d["perimeter"] / "perimeter_edge.tif", EDGE, None),
        },
    }
    _json(d["perimeter"] / "perimeter.json", perimeter)
    terrain = {
        "terrain_format_version": 1,
        "ingest": {"sha256": ingest_sha},
        "grid": terrain_grid or GRID,
        "outputs": {
            "slope.tif": _cog(d["terrain"] / "slope.tif", slope.astype(np.float32), NAN),
            "layover_shadow.tif": _cog(d["terrain"] / "layover_shadow.tif", flags, 255),
        },
    }
    _json(d["terrain"] / "terrain.json", terrain)
    return d


def config_for(root: Path, params: ZoneParams = PARAMS, **kwargs: Any) -> ReviewZonesConfig:
    d = write_upstream(root, **kwargs)
    run_highlight(
        HighlightConfig(
            params=HL_PARAMS,
            change_dir=d["change"],
            sar_dir=d["sar"],
            perimeter_dir=d["perimeter"],
            output_dir=root / "highlight",
        )
    )
    return ReviewZonesConfig(
        params=params,
        change_dir=d["change"],
        sar_dir=d["sar"],
        perimeter_dir=d["perimeter"],
        terrain_dir=d["terrain"],
        highlight_dir=root / "highlight",
        output_dir=root / "review_zones",
    )


def _zones(config: ReviewZonesConfig) -> dict[str, dict[str, Any]]:
    doc = _load(config.output_dir / "review_zones.geojson")
    return {f["id"]: f for f in doc["features"]}


def _validator() -> Draft202012Validator:
    schema = _load(ROOT / "contracts/schemas/review-zones.schema.json")
    return Draft202012Validator(schema)


def test_end_to_end_zones_validate_and_match_hand_values(tmp_path: Path):
    config = config_for(tmp_path)
    run_review_zones(config)
    doc = _load(config.output_dir / "review_zones.geojson")
    assert list(_validator().iter_errors(doc)) == []
    assert doc["data_status"] == "real" and doc["contract_version"] == "1.2.0"
    assert doc["method"] == {
        "change_threshold": 2.0,
        "no_change_threshold": 0.0,
        "smoothing": doc["method"]["smoothing"],
        "min_area_ha": 0.04,
        "max_zones_per_kind": 10,
    }
    assert "XP-01" in doc["method"]["smoothing"]
    zones = _zones(config)
    assert sorted(zones) == ["CI-01", "CI-02", "CO-01", "NI-01"]

    a = zones["CI-01"]["properties"]  # zone A: 8 valid pixels around one invalid hole
    assert a["kind"] == "change_inside_perimeter" and a["rank"] == 1
    assert a["area_ha"] == 0.08
    assert a["valid_fraction"] == pytest.approx(8 / 9, abs=1e-4)
    assert a["change_index"] == {"median": 5.0, "p90": 5.0}
    assert a["hh_db"] == {"t1_median": -10.0, "t2_median": -15.0, "delta_median": -5.0}
    assert a["hv_db"] == {"t1_median": -18.0, "t2_median": -20.5, "delta_median": -2.5}
    assert {c["id"]: c["fraction"] for c in a["caveats"]}["steep_slope"] == 0.375
    assert a["distance_to_perimeter_m"] == 40.0  # right edge x = X0 + 40 m, line at X0 + 80 m

    c = zones["CI-02"]["properties"]  # zone C: 4 + 1 diagonal pixel, 8-connected
    assert c["area_ha"] == 0.05
    assert c["distance_to_perimeter_m"] == 30.0

    b = zones["CO-01"]["properties"]
    assert b["kind"] == "change_outside_perimeter" and b["area_ha"] == 0.04
    assert b["distance_to_perimeter_m"] == 30.0  # left edge x = X0 + 110 m
    assert {c["id"]: c["fraction"] for c in b["caveats"]}["radar_shadow_layover"] == 0.5

    n = zones["NI-01"]["properties"]
    assert n["kind"] == "no_change_inside_perimeter" and n["area_ha"] == 0.09
    assert n["change_index"]["median"] == -3.0
    assert n["distance_to_perimeter_m"] == 50.0

    for feature in zones.values():
        props = feature["properties"]
        assert feature["id"] == props["zone_id"]
        geom = shapely.geometry.shape(feature["geometry"])
        assert geom.is_valid
        lon, lat = props["centroid"]
        x0, y0, x1, y1 = props["bbox"]
        assert x0 <= lon <= x1 and y0 <= lat <= y1
        assert geom.bounds == pytest.approx(props["bbox"], abs=1e-6)


def test_an_empty_kind_is_published_with_no_features(tmp_path: Path):
    index = INDEX.copy()
    index[0:2, 11:13] = 0.5  # remove the only change outside the perimeter
    config = config_for(tmp_path, index=index)
    run_review_zones(config)
    doc = _load(config.output_dir / "review_zones.geojson")
    assert list(_validator().iter_errors(doc)) == []
    assert not any(f["properties"]["kind"] == "change_outside_perimeter" for f in doc["features"])
    meta = _load(config.output_dir / "review_zones_meta.json")
    assert meta["kinds"]["change_outside_perimeter"]["published"] == 0
    assert meta["kinds"]["change_outside_perimeter"]["candidate_regions"] == 0


def test_max_zones_per_kind_keeps_the_top_ranked(tmp_path: Path):
    config = config_for(tmp_path, params=replace(PARAMS, max_zones_per_kind=1))
    run_review_zones(config)
    zones = _zones(config)
    assert sorted(zones) == ["CI-01", "CO-01", "NI-01"]
    assert zones["CI-01"]["properties"]["area_ha"] == 0.08
    meta = _load(config.output_dir / "review_zones_meta.json")
    assert meta["kinds"]["change_inside_perimeter"] == {
        **meta["kinds"]["change_inside_perimeter"],
        "candidate_regions": 2,
        "published": 1,
    }


def test_meta_records_inputs_parameters_and_outputs(tmp_path: Path):
    config = config_for(tmp_path)
    run_review_zones(config)
    meta = _load(config.output_dir / "review_zones_meta.json")
    assert meta["review_zones_format_version"] == 1
    assert meta["inputs"] == {
        "change.json": _sha(config.change_dir / "change.json"),
        "sar.json": _sha(config.sar_dir / "sar.json"),
        "perimeter.json": _sha(config.perimeter_dir / "perimeter.json"),
        "highlight_meta.json": _sha(config.highlight_dir / "highlight_meta.json"),
        "terrain.json": _sha(config.terrain_dir / "terrain.json"),
    }
    assert meta["parameters"]["min_region_px"] == 4
    assert meta["outputs"]["review_zones.geojson"]["sha256"] == _sha(
        config.output_dir / "review_zones.geojson"
    )
    ni = meta["kinds"]["no_change_inside_perimeter"]
    assert ni["largest_ha"] == 0.09


def test_reruns_are_byte_identical(tmp_path: Path):
    config = config_for(tmp_path)
    run_review_zones(config)
    first = {p.name: p.read_bytes() for p in config.output_dir.iterdir()}
    run_review_zones(config)
    assert {p.name: p.read_bytes() for p in config.output_dir.iterdir()} == first


# --------------------------------------------------------------------------- failure paths


def _fails_without_writing(config: ReviewZonesConfig, match: str) -> None:
    with pytest.raises(ReviewZonesError, match=match):
        run_review_zones(config)
    assert not config.output_dir.exists()


def test_highlight_from_another_generation_is_rejected(tmp_path: Path):
    config = config_for(tmp_path)
    meta_path = config.highlight_dir / "highlight_meta.json"
    meta = _load(meta_path)
    meta["inputs"]["sar.json"] = "0" * 64
    _json(meta_path, meta)
    _fails_without_writing(config, "highlight_meta.json was built from other inputs")


def test_tampered_highlight_mask_is_rejected(tmp_path: Path):
    config = config_for(tmp_path)
    mask = np.zeros((H, W), dtype=np.uint8)
    write_cog(
        config.highlight_dir / "highlight_mask.tif",
        mask,
        crs=UTM10N,
        transform=TRANSFORM,
        nodata=255,
    )
    _fails_without_writing(config, "sha256")


def test_terrain_on_another_grid_is_rejected(tmp_path: Path):
    other = {**GRID, "width": W + 1}
    _fails_without_writing(config_for(tmp_path, terrain_grid=other), "terrain.json: grid")


def test_terrain_from_another_ingest_is_rejected(tmp_path: Path):
    config = config_for(tmp_path)
    path = config.terrain_dir / "terrain.json"
    doc = _load(path)
    doc["ingest"]["sha256"] = "d" * 64
    _json(path, doc)
    _fails_without_writing(config, "terrain.json was built from another ingest")


def test_unknown_layover_code_is_rejected(tmp_path: Path):
    flags = FLAGS.copy()
    flags[3, 3] = 7
    _fails_without_writing(config_for(tmp_path, flags=flags), "layover_shadow")


def test_tampered_perimeter_geojson_is_rejected(tmp_path: Path):
    config = config_for(tmp_path)
    (config.perimeter_dir / "perimeter.geojson").write_text("{}", encoding="utf-8")
    _fails_without_writing(config, "perimeter.geojson")


def test_foreign_files_in_the_output_dir_are_refused(tmp_path: Path):
    config = config_for(tmp_path)
    config.output_dir.mkdir()
    (config.output_dir / "notes.txt").write_text("x", encoding="utf-8")
    with pytest.raises(ReviewZonesError):
        run_review_zones(config)
    assert (config.output_dir / "notes.txt").exists()


def test_failed_rerun_keeps_the_previous_outputs(tmp_path: Path):
    config = config_for(tmp_path)
    run_review_zones(config)
    before = (config.output_dir / "review_zones.geojson").read_bytes()
    path = config.terrain_dir / "terrain.json"
    doc = _load(path)
    doc["terrain_format_version"] = 99
    _json(path, doc)
    with pytest.raises(ReviewZonesError):
        run_review_zones(config)
    assert (config.output_dir / "review_zones.geojson").read_bytes() == before


def test_output_dir_may_not_be_an_input_dir(tmp_path: Path):
    config = config_for(tmp_path)
    with pytest.raises(ReviewZonesError, match="output_dir"):
        run_review_zones(replace(config, output_dir=config.highlight_dir))


# --------------------------------------------------------------------------- config / CLI


def test_repository_config_loads(tmp_path: Path):
    config = load_config(ROOT / "pipeline/configs/review_zones_plaskett.toml", base_dir=tmp_path)
    assert config.params == ZoneParams(
        no_change_threshold=0.0, min_area_ha=5.0, max_zones_per_kind=10, simplify_tolerance_m=5.0
    )
    assert config.output_dir == tmp_path / "data/interim/review_zones"
    assert config.highlight_dir == tmp_path / "data/interim/highlight"


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"min_area_ha": 0}, "min_area_ha"),
        ({"max_zones_per_kind": 0}, "max_zones_per_kind"),
        ({"no_change_threshold": "0"}, "no_change_threshold"),
        ({"simplify_tolerance_m": -1}, "simplify_tolerance_m"),
        ({"surprise": 1}, "unknown"),
    ],
)
def test_bad_config_is_rejected(tmp_path: Path, override: dict[str, Any], message: str):
    base: dict[str, Any] = {
        "no_change_threshold": 0.0,
        "min_area_ha": 5.0,
        "max_zones_per_kind": 10,
        "simplify_tolerance_m": 5.0,
        **{k: k for k in ("change_dir", "sar_dir", "perimeter_dir", "terrain_dir")},
        "highlight_dir": "h",
        "output_dir": "o",
    }
    base.update(override)
    lines = [f"{k} = {json.dumps(v)}" for k, v in base.items()]
    path = tmp_path / "c.toml"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(ReviewZonesError, match=message):
        load_config(path, base_dir=tmp_path)


def test_cli_exit_codes(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    config = config_for(tmp_path)
    lines = [
        f"no_change_threshold = {PARAMS.no_change_threshold}",
        f"min_area_ha = {PARAMS.min_area_ha}",
        f"max_zones_per_kind = {PARAMS.max_zones_per_kind}",
        f"simplify_tolerance_m = {PARAMS.simplify_tolerance_m}",
    ] + [
        f"{key} = {json.dumps(getattr(config, key).as_posix())}"
        for key in (
            "change_dir",
            "sar_dir",
            "perimeter_dir",
            "terrain_dir",
            "highlight_dir",
            "output_dir",
        )
    ]
    path = tmp_path / "rz.toml"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert main(["--config", str(path)]) == 0
    assert "review zones ok" in capsys.readouterr().out
    (config.terrain_dir / "terrain.json").write_text("{", encoding="utf-8")
    assert main(["--config", str(path)]) == 2
    assert "review zones error" in capsys.readouterr().err


def test_module_constants_match_the_caveat_method_doc():
    doc = (ROOT / "docs/methods/caveats.md").read_text(encoding="utf-8")
    assert "| `SLOPE_THRESHOLD_DEG` | 30° |" in doc
    assert review_zones.SLOPE_THRESHOLD_DEG == 30.0
    assert highlight.MASK_NODATA == 255


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("window", 1.9, "window must be an integer"),
        ("window", 2, "positive odd integer"),
        ("window", True, "window must be an integer"),
        ("connectivity", 8.9, "connectivity must be an integer"),
        ("connectivity", 6, "4 or 8"),
        ("threshold", "2.0", "finite number"),
        ("min_region_px", 0, "at least 1"),
    ],
)
def test_malformed_highlight_parameters_are_rejected_not_coerced(
    tmp_path: Path, key: str, value: Any, message: str
):
    config = config_for(tmp_path)
    meta_path = config.highlight_dir / "highlight_meta.json"
    meta = _load(meta_path)
    meta["parameters"][key] = value
    _json(meta_path, meta)
    _fails_without_writing(config, message)
