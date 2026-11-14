"""DT-04 web export: hand-computed stretches, warp/mask honesty, contract output, safety.

Tiny synthetic upstream sets (6 x 8 pixels of the 10 m EPSG:32610 grid); no real data.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import rasterio
from affine import Affine
from jsonschema import Draft202012Validator
from rasterio.crs import CRS
from rasterio.warp import transform as warp_transform

from pipeline import export
from pipeline.change import METHOD
from pipeline.export import (
    ExportConfig,
    ExportError,
    change_half_range,
    generated_at,
    index_domain,
    load_config,
    main,
    run_export,
    sar_domain,
)
from pipeline.sar import write_cog
from pipeline.webexport import colorize, warp_to_web, write_png

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "contracts" / "fixtures" / "web"
SCHEMAS = ROOT / "contracts" / "schemas"
UTM10N = CRS.from_epsg(32610)
WEB = CRS.from_epsg(3857)
TRANSFORM = Affine(10.0, 0.0, 636_000.0, 0.0, -10.0, 3_983_990.0)
H, W = 6, 8
GRID = {"crs": "EPSG:32610", "transform": list(TRANSFORM)[:6], "width": W, "height": H}
EPOCH = "1794268800"  # 2026-11-10T00:00:00Z
EPOCH_ISO = "2026-11-10T00:00:00Z"
RASTER_IDS = [
    "sar_t1_hh",
    "sar_t2_hh",
    "sar_t1_hv",
    "sar_t2_hv",
    "change_hh",
    "change_hv",
    "change_index",
    "valid_mask",
]

# Common valid mask: two invalid pixels. t1_hh stays finite there, so a correct export must
# use the common mask, not each layer's own validity.
MASK = np.ones((H, W), dtype=np.uint8)
MASK[2, 3] = MASK[2, 4] = 0
ROWS, COLS = np.mgrid[0:H, 0:W]
T1_HH = (-20.0 + ROWS + 0.5 * COLS).astype(np.float32)
T2_HH = (T1_HH - 2.0 * (COLS >= 4)).astype(np.float32)
T1_HV = (T1_HH - 8.0).astype(np.float32)
T2_HV = np.where(MASK == 1, T1_HV + 1.0, np.nan).astype(np.float32)


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


def _change_layers() -> dict[str, np.ndarray]:
    valid = MASK == 1
    hh = np.where(valid, T2_HH.astype(np.float64) - T1_HH, np.nan)
    hv = np.where(valid, T2_HV.astype(np.float64) - T1_HV, np.nan)
    index = np.where(valid, np.abs(hh) + np.abs(hv) - 1.0, np.nan)
    return {
        "change_hh_db": hh.astype(np.float32),
        "change_hv_db": hv.astype(np.float32),
        "change_index": index.astype(np.float32),
    }


def write_inputs(root: Path, *, terrain: bool = False, weather: bool = False) -> ExportConfig:
    """Mimic the DT-01, DT-02, CH-01, DT-03, CH-02 (+ DT-05, DT-06) output directories."""
    d = {n: root / n for n in ("nisar", "sar", "change", "perimeter", "stats")}
    raw_sha = "a" * 64
    ingest = {
        "ingest_format_version": 1,
        "case_id": "plaskett-2026",
        "product": "NISAR_L2_PR_GCOV",
        "acquisition": {
            "crs": "EPSG:32610",
            "direction": "descending",
            "frame": 70,
            "frequency": "A",
            "pixel_size_m": 10.0,
            "polarizations": ["HH", "HV"],
            "track": 42,
        },
        "aoi": {"aoi_bbox_4326": [-121.494, 35.9904, -121.4931, 35.9909]},
        "epochs": {
            "t1": {
                "absolute_orbit": 5504,
                "datetime": "2026-08-16T02:56:39Z",
                "granule_id": "G4284560161-ASF",
                "label": "Before",
            },
            "t2": {
                "absolute_orbit": 6196,
                "datetime": "2026-10-03T02:56:38Z",
                "granule_id": "G4340499432-ASF",
                "label": "After",
            },
        },
        "grid": {
            "crs": "EPSG:32610",
            "crop": {"transform": list(TRANSFORM)[:6], "width": W, "height": H},
        },
        "reference": {"file": "wfigs_58728_raw.geojson", "objectid": 58728, "sha256": raw_sha},
    }
    _json(d["nisar"] / "ingest.json", ingest)

    db = {
        name: _cog(d["sar"] / f"{name}_db.tif", data, np.nan)
        for name, data in (("t1_hh", T1_HH), ("t1_hv", T1_HV), ("t2_hh", T2_HH), ("t2_hv", T2_HV))
    }
    sar = {
        "sar_format_version": 1,
        "case_id": "plaskett-2026",
        "source_ingest": {"file": "ingest.json", "sha256": _sha(d["nisar"] / "ingest.json")},
        "grid": {**GRID, "resampling": "none"},
        "db": {"layers": db},
        "valid_mask": _cog(d["sar"] / "valid_mask.tif", MASK, None),
    }
    _json(d["sar"] / "sar.json", sar)

    outputs = {
        name: _cog(d["change"] / f"{name}.tif", data, np.nan)
        for name, data in _change_layers().items()
    }
    change = {
        "change_format_version": 1,
        "case_id": "plaskett-2026",
        "method": METHOD,
        "source_sar": {"file": "sar.json", "sha256": _sha(d["sar"] / "sar.json")},
        "grid": {**GRID, "resampling": "none"},
        "outputs": outputs,
    }
    _json(d["change"] / "change.json", change)

    geojson = d["perimeter"] / "perimeter.geojson"
    geojson.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(FIXTURES / "perimeter.geojson", geojson)
    perimeter = {
        "perimeter_format_version": 1,
        "reference": {
            "source": "NIFC WFIGS Interagency Perimeters YearToDate",
            "objectid": 58728,
            "datetime": "2026-09-14T20:44:00Z",
            "url": "https://services3.arcgis.com/example/FeatureServer/0",
            "note": "Dated reference for contrast, not pixel-level ground truth.",
        },
        "raw": {"file": "wfigs_58728_raw.geojson", "sha256": raw_sha},
        "grid": GRID,
        "outputs": {"perimeter.geojson": {"file": geojson.name, "sha256": _sha(geojson)}},
    }
    _json(d["perimeter"] / "perimeter.json", perimeter)

    stats_doc = _load(FIXTURES / "stats.json")
    stats_doc["data_status"] = "real"
    _json(d["stats"] / "stats.json", stats_doc)
    meta = {
        "stats_format_version": 1,
        "inputs": {
            "change.json": _sha(d["change"] / "change.json"),
            "sar.json": _sha(d["sar"] / "sar.json"),
            "perimeter.json": _sha(d["perimeter"] / "perimeter.json"),
        },
        "outputs": {"stats.json": _sha(d["stats"] / "stats.json")},
    }
    _json(d["stats"] / "stats_meta.json", meta)

    if terrain:
        write_terrain(root / "terrain", d["nisar"] / "ingest.json")
    if weather:
        write_weather(root / "weather", d["nisar"] / "ingest.json")

    return ExportConfig(
        case_id="plaskett-2026",
        name="Plaskett Fire",
        location="Big Sur, Monterey County, California, USA",
        fire_start="2026-08-26",
        sources=[{"label": "CAL FIRE incident page", "url": "https://www.fire.ca.gov/x"}],
        ingest_dir=d["nisar"],
        sar_dir=d["sar"],
        change_dir=d["change"],
        perimeter_dir=d["perimeter"],
        stats_dir=d["stats"],
        terrain_dir=root / "terrain",
        weather_dir=root / "weather",
        output_dir=root / "web",
    )


def write_terrain(directory: Path, ingest_path: Path, **layer_overrides: Any) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    shade = np.linspace(0.0, 1.0, H * W).reshape(H, W)
    warped = warp_to_web(shade, src_transform=TRANSFORM, src_crs=UTM10N, resampling="bilinear")
    write_png(directory / "hillshade.png", colorize(warped.data, [(0, "#000000"), (1, "#ffffff")]))
    write_png(directory / "slope.png", colorize(warped.data, [(0, "#ffffd4"), (1, "#993404")]))
    source = {"label": "Copernicus GLO-30", "url": "https://example.org/dem"}
    web = {"coordinates": warped.coordinates, "width_px": warped.width, "height_px": warped.height}
    layers = [
        {
            "id": lid,
            "title": title,
            "kind": "raster",
            "group": "terrain",
            "url": f"layers/{lid}.png",
            "default_visible": False,
            "default_opacity": 0.5,
            "source": source,
            **web,
            "legend": {"type": "rgb", "note": "Display only."},
            **layer_overrides,
        }
        for lid, title in (("hillshade", "Terrain relief (hillshade)"), ("slope", "Slope"))
    ]
    doc = {"contract_version": "1.2.0", "data_status": "real", "layers": layers}
    _json(directory / "terrain_layers.json", doc)
    terrain = {
        "terrain_format_version": 1,
        "ingest": {"sha256": _sha(ingest_path)},
        "grid": GRID,
        "outputs": {
            name: {"file": name, "sha256": _sha(directory / name)}
            for name in ("hillshade.png", "slope.png", "terrain_layers.json")
        },
    }
    _json(directory / "terrain.json", terrain)


def write_weather(directory: Path, ingest_path: Path, data_status: str = "real") -> None:
    doc = _load(FIXTURES / "weather.json")
    doc["data_status"] = data_status
    _json(directory / "weather.json", doc)
    meta = {
        "weather_format_version": 1,
        "inputs": {"ingest.json": _sha(ingest_path), "imerg_manifest.json": "b" * 64},
        "outputs": {"weather.json": _sha(directory / "weather.json")},
    }
    _json(directory / "weather_meta.json", meta)


def _rewrite_json(path: Path, edit: Callable[[dict[str, Any]], None]) -> None:
    doc = _load(path)
    edit(doc)
    _json(path, doc)


@pytest.fixture(autouse=True)
def _fixed_epoch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOURCE_DATE_EPOCH", EPOCH)


def _validator(name: str) -> Draft202012Validator:
    schema = _load(SCHEMAS / f"{name}.schema.json")
    return Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)


def _png(path: Path) -> np.ndarray:
    with rasterio.open(path) as src:
        return np.moveaxis(src.read(), 0, -1)


def _layers(web: Path) -> dict[str, dict[str, Any]]:
    return {layer["id"]: layer for layer in _load(web / "layers.json")["layers"]}


# --------------------------------------------------------------------------- stretches


def test_sar_domain_is_joint_p2_p98_rounded_outward_to_whole_db():
    # linspace(-30, 0, 101): p2 = -29.4, p98 = -0.6 -> [-30, 0]
    t1 = np.linspace(-30.0, 0.0, 101)
    assert sar_domain(t1[:50], t1[50:]) == (-30.0, 0.0)
    # Joint: one epoch alone would give another domain.
    assert sar_domain(np.full(10, -12.5), np.full(10, -3.5)) == (-13.0, -3.0)


def test_sar_domain_widens_a_constant_field():
    assert sar_domain(np.full(5, -10.0), np.full(5, -10.0)) == (-10.0, -9.0)


def test_change_half_range_is_p98_of_absolute_change_rounded_up_and_shared():
    # |delta| = linspace(0, 10, 101) split across HH (negative) and HV: p98 = 9.8 -> 10
    mags = np.linspace(0.0, 10.0, 101)
    assert change_half_range(-mags[:60], mags[60:]) == 10.0
    assert change_half_range(np.zeros(4), np.zeros(4)) == 1.0, "no change still needs a range"


def test_index_domain_is_p2_p98_rounded_outward_to_hundredths():
    # linspace(-1, 4, 101): p2 = -0.9, p98 = 3.9
    assert index_domain(np.linspace(-1.0, 4.0, 101)) == (-0.9, 3.9)
    assert index_domain(np.array([0.123, 0.123])) == (0.12, 0.13)


def test_stretches_reject_empty_input():
    with pytest.raises(ExportError):
        sar_domain(np.array([]), np.array([]))
    with pytest.raises(ExportError):
        index_domain(np.array([]))


def test_generated_at_uses_source_date_epoch_or_rejects_garbage():
    assert generated_at({"SOURCE_DATE_EPOCH": EPOCH}) == EPOCH_ISO
    with pytest.raises(ExportError):
        generated_at({"SOURCE_DATE_EPOCH": "yesterday"})
    now = generated_at({})
    assert now.endswith("Z") and len(now) == len(EPOCH_ISO)


# --------------------------------------------------------------------------- end to end


def test_bundle_layout_and_contract(tmp_path: Path):
    config = write_inputs(tmp_path)
    run_export(config)
    web = config.output_dir
    names = sorted(p.relative_to(web).as_posix() for p in web.rglob("*") if p.is_file())
    assert names == sorted(
        ["case.json", "layers.json", "stats.json", "perimeter.geojson", "export.json"]
        + [f"layers/{lid}.png" for lid in RASTER_IDS]
    )
    for name, schema in (("case.json", "case"), ("layers.json", "layers"), ("stats.json", "stats")):
        errors = list(_validator(schema).iter_errors(_load(web / name)))
        assert not errors, (name, [e.message for e in errors])
    # The repository validator agrees (it is what "done" means for the pipeline).
    spec = importlib.util.spec_from_file_location("validate", ROOT / "contracts/tools/validate.py")
    assert spec and spec.loader
    validate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validate)
    problems: list[str] = []
    validate.check_web_dir(web, problems)
    assert problems == []


def test_case_json_comes_from_upstream_manifests(tmp_path: Path):
    config = write_inputs(tmp_path)
    run_export(config)
    case = _load(config.output_dir / "case.json")
    assert case["data_status"] == "real" and case["contract_version"] == "1.2.0"
    assert case["product"] == "NISAR_L2_PR_GCOV", "product as ingested, not the fixture name"
    assert case["acquisition"]["track"] == 42 and case["acquisition"]["crs"] == "EPSG:32610"
    assert case["epochs"]["t2"]["granule_id"] == "G4340499432-ASF"
    assert case["aoi_bbox"] == [-121.494, 35.9904, -121.4931, 35.9909]
    assert case["reference"]["objectid"] == 58728
    assert case["reference"]["datetime"] == "2026-09-14T20:44:00Z"
    assert case["method"] == METHOD
    assert case["fire_start"] == "2026-08-26" and case["name"] == "Plaskett Fire"
    assert case["generated_at"] == EPOCH_ISO
    assert case["pipeline_version"].startswith("firetrace ")


def test_copies_are_byte_identical(tmp_path: Path):
    config = write_inputs(tmp_path, weather=True)
    run_export(config)
    web = config.output_dir
    assert (web / "stats.json").read_bytes() == (config.stats_dir / "stats.json").read_bytes()
    assert (web / "perimeter.geojson").read_bytes() == (
        config.perimeter_dir / "perimeter.geojson"
    ).read_bytes()
    assert (web / "weather.json").read_bytes() == (config.weather_dir / "weather.json").read_bytes()


def test_all_raster_layers_share_corners_and_size(tmp_path: Path):
    config = write_inputs(tmp_path, terrain=True)
    run_export(config)
    layers = _layers(config.output_dir)
    expected = warp_to_web(
        T1_HH.astype(np.float64), src_transform=TRANSFORM, src_crs=UTM10N, resampling="nearest"
    )
    for lid in [*RASTER_IDS, "hillshade", "slope"]:
        layer = layers[lid]
        assert layer["coordinates"] == expected.coordinates, lid
        assert (layer["width_px"], layer["height_px"]) == (expected.width, expected.height), lid
        rgba = _png(config.output_dir / layer["url"])
        assert rgba.shape == (expected.height, expected.width, 4), lid


def _source_pixels(layer: dict[str, Any]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Exact source (row, col) of every web pixel centre and whether it is unambiguous."""
    tl, tr, _br, bl = layer["coordinates"]
    (x0, x1), (y0, y1) = warp_transform(CRS.from_epsg(4326), WEB, [tl[0], tr[0]], [tl[1], bl[1]])
    w, h = layer["width_px"], layer["height_px"]
    cols, rows = np.meshgrid(np.arange(w) + 0.5, np.arange(h) + 0.5)
    xs = x0 + cols * (x1 - x0) / w
    ys = y0 + rows * (y1 - y0) / h
    ux, uy = warp_transform(WEB, UTM10N, xs.ravel().tolist(), ys.ravel().tolist())
    fc, fr = ~TRANSFORM * (np.array(ux), np.array(uy))
    fc, fr = fc.reshape(h, w), fr.reshape(h, w)
    # Pixels whose centre lands within 0.2 px of a source edge may legitimately go either way.
    clear = (np.abs(fc - np.round(fc)) > 0.2) & (np.abs(fr - np.round(fr)) > 0.2)
    return np.floor(fr).astype(int), np.floor(fc).astype(int), clear


def test_nearest_warp_never_makes_invalid_pixels_opaque(tmp_path: Path):
    config = write_inputs(tmp_path)
    run_export(config)
    layers = _layers(config.output_dir)
    rows, cols, clear = _source_pixels(layers["sar_t1_hh"])
    inside = (rows >= 0) & (rows < H) & (cols >= 0) & (cols < W)
    src_valid = np.zeros(rows.shape, dtype=bool)
    src_valid[inside] = MASK[rows[inside], cols[inside]] == 1
    # The check is not vacuous: both invalid pixels and outside-crop pixels are covered.
    assert (clear & inside & ~src_valid).sum() >= 2
    assert (clear & ~inside).sum() >= 1 and (clear & src_valid).sum() >= 30
    for lid in RASTER_IDS[:-1]:
        alpha = _png(config.output_dir / layers[lid]["url"])[..., 3]
        assert set(np.unique(alpha)) <= {0, 255}, lid
        # Outside the crop or on an invalid pixel -> transparent; t1_hh is finite there.
        assert (alpha[clear & ~src_valid] == 0).all(), lid
        assert (alpha[clear & src_valid] == 255).all(), lid
    # The quality layer is the complement: grey exactly where the source is invalid.
    mask_rgba = _png(config.output_dir / layers["valid_mask"]["url"])
    grey = mask_rgba[..., 3] == 255
    assert (grey[clear & inside] == ~src_valid[clear & inside]).all()
    assert not grey[clear & ~inside].any()
    assert (mask_rgba[grey][:, :3] == [0x7F, 0x7F, 0x7F]).all()


def test_colours_follow_the_published_legend(tmp_path: Path):
    config = write_inputs(tmp_path)
    run_export(config)
    layers = _layers(config.output_dir)
    rows, cols, clear = _source_pixels(layers["sar_t2_hh"])
    inside = (rows >= 0) & (rows < H) & (cols >= 0) & (cols < W)
    sources = {
        "sar_t2_hh": T2_HH,
        "change_hh": _change_layers()["change_hh_db"],
        "change_index": _change_layers()["change_index"],
    }
    for lid, src in sources.items():
        legend = layers[lid]["legend"]
        stops = [(s["value"], s["color"]) for s in legend["stops"]]
        assert legend["domain"] == [stops[0][0], stops[-1][0]]
        rgba = _png(config.output_dir / layers[lid]["url"])
        pick = clear & inside
        pick[pick] &= MASK[rows[pick], cols[pick]] == 1
        expected = colorize(src[rows[pick], cols[pick]].astype(np.float64)[None, :], stops)[0]
        np.testing.assert_array_equal(rgba[pick], expected, err_msg=lid)


def test_legends_record_the_computed_stretches(tmp_path: Path):
    config = write_inputs(tmp_path)
    run_export(config)
    layers = _layers(config.output_dir)
    valid = MASK == 1
    hh = sar_domain(T1_HH[valid], T2_HH[valid])
    hv = sar_domain(T1_HV[valid], T2_HV[valid])
    assert layers["sar_t1_hh"]["legend"]["domain"] == list(hh)
    assert layers["sar_t2_hh"]["legend"]["domain"] == list(hh), "before/after share a stretch"
    assert layers["sar_t1_hv"]["legend"]["domain"] == list(hv)
    ch = _change_layers()
    d = change_half_range(ch["change_hh_db"][valid], ch["change_hv_db"][valid])
    assert layers["change_hh"]["legend"]["domain"] == [-d, d]
    assert layers["change_hv"]["legend"]["domain"] == [-d, d], "HH and HV share a stretch"
    assert layers["change_index"]["legend"]["domain"] == list(
        index_domain(ch["change_index"][valid])
    )
    manifest = _load(config.output_dir / "export.json")
    assert manifest["display"]["resampling"] == "nearest"
    assert manifest["display"]["domains"]["sar_hh"] == list(hh)


def test_layer_metadata_follows_the_contract_conventions(tmp_path: Path):
    config = write_inputs(tmp_path)
    run_export(config)
    layers = _layers(config.output_dir)
    assert layers["change_index"]["group"] == "observed_change"
    assert layers["change_index"]["title"].startswith("Observed radar changes")
    assert layers["sar_t1_hv"]["epoch"] == "t1" and layers["sar_t1_hv"]["polarization"] == "HV"
    assert layers["perimeter"]["kind"] == "vector"
    assert layers["perimeter"]["url"] == "perimeter.geojson"
    assert layers["perimeter"]["title"] == "Official fire perimeter"
    assert layers["perimeter"]["legend"]["items"][0]["label"] == (
        "WFIGS perimeter, 2026-09-14 20:44 UTC"
    )
    text = (config.output_dir / "layers.json").read_text(encoding="utf-8").lower()
    assert "burn" not in text and "mock" not in text


def test_optional_inputs_are_merged_only_when_present(tmp_path: Path):
    bare = write_inputs(tmp_path / "bare")
    run_export(bare)
    assert "hillshade" not in _layers(bare.output_dir)
    assert not (bare.output_dir / "weather.json").exists()
    manifest = _load(bare.output_dir / "export.json")
    assert manifest["optional"] == {"terrain": False, "weather": False}

    full = write_inputs(tmp_path / "full", terrain=True, weather=True)
    run_export(full)
    layers = _layers(full.output_dir)
    assert layers["hillshade"]["source"]["label"] == "Copernicus GLO-30"
    assert (full.output_dir / "layers/slope.png").read_bytes() == (
        full.terrain_dir / "slope.png"
    ).read_bytes()
    assert _load(full.output_dir / "export.json")["optional"] == {"terrain": True, "weather": True}


def test_reruns_are_byte_identical(tmp_path: Path):
    config = write_inputs(tmp_path, terrain=True, weather=True)
    run_export(config)
    first = {
        p.relative_to(config.output_dir): p.read_bytes()
        for p in config.output_dir.rglob("*")
        if p.is_file()
    }
    run_export(config)
    second = {
        p.relative_to(config.output_dir): p.read_bytes()
        for p in config.output_dir.rglob("*")
        if p.is_file()
    }
    assert first == second


def test_export_manifest_checksums_every_output(tmp_path: Path):
    config = write_inputs(tmp_path, weather=True)
    run_export(config)
    manifest = _load(config.output_dir / "export.json")
    files = {
        p.relative_to(config.output_dir).as_posix(): _sha(p)
        for p in config.output_dir.rglob("*")
        if p.is_file() and p.name != "export.json"
    }
    assert manifest["outputs"] == files
    assert manifest["inputs"]["sar.json"] == _sha(config.sar_dir / "sar.json")


# --------------------------------------------------------------------------- failures


def _fails_without_writing(config: ExportConfig, match: str) -> None:
    with pytest.raises(ExportError, match=match):
        run_export(config)
    assert not config.output_dir.exists()
    leftovers = [p.name for p in config.output_dir.parent.iterdir() if p.name.startswith(".web")]
    assert leftovers == []


def test_tampered_raster_is_rejected(tmp_path: Path):
    config = write_inputs(tmp_path)
    path = config.change_dir / "change_index.tif"
    write_cog(path, np.zeros((H, W), np.float32), crs=UTM10N, transform=TRANSFORM, nodata=np.nan)
    _fails_without_writing(config, "sha256")


def test_broken_manifest_chain_is_rejected(tmp_path: Path):
    config = write_inputs(tmp_path)
    _rewrite_json(config.sar_dir / "sar.json", lambda d: d.update(note="edited"))
    # sar.json changed after change.json recorded it -> mixed generations.
    _fails_without_writing(config, "sar.json")


def test_stats_from_another_generation_is_rejected(tmp_path: Path):
    config = write_inputs(tmp_path)
    _rewrite_json(
        config.stats_dir / "stats_meta.json",
        lambda d: d["inputs"].update({"perimeter.json": "c" * 64}),
    )
    _fails_without_writing(config, "stats_meta.json")


def test_stats_json_must_match_its_manifest(tmp_path: Path):
    config = write_inputs(tmp_path)
    _rewrite_json(config.stats_dir / "stats.json", lambda d: d.update(valid_pixels=1))
    _fails_without_writing(config, "stats.json")


def test_perimeter_from_another_raw_file_is_rejected(tmp_path: Path):
    config = write_inputs(tmp_path)
    _rewrite_json(
        config.perimeter_dir / "perimeter.json", lambda d: d["raw"].update(sha256="d" * 64)
    )
    # The stats manifest now also disagrees; the reference check must still be the reason.
    _rewrite_json(
        config.stats_dir / "stats_meta.json",
        lambda d: d["inputs"].update(
            {"perimeter.json": _sha(config.perimeter_dir / "perimeter.json")}
        ),
    )
    _fails_without_writing(config, "raw perimeter")


def test_grid_mismatch_is_rejected(tmp_path: Path):
    config = write_inputs(tmp_path)
    _rewrite_json(config.perimeter_dir / "perimeter.json", lambda d: d["grid"].update(width=W + 1))
    perimeter_sha = _sha(config.perimeter_dir / "perimeter.json")
    _rewrite_json(
        config.stats_dir / "stats_meta.json",
        lambda d: d["inputs"].update({"perimeter.json": perimeter_sha}),
    )
    _fails_without_writing(config, "perimeter.json: grid")


def test_value_outside_the_mask_contract_is_rejected(tmp_path: Path):
    config = write_inputs(tmp_path)
    bad = T1_HH.copy()
    bad[0, 0] = np.nan  # mask says valid
    record = _cog(config.sar_dir / "t1_hh_db.tif", bad, np.nan)
    _rewrite_json(config.sar_dir / "sar.json", lambda d: d["db"]["layers"].update(t1_hh=record))
    sar_sha = _sha(config.sar_dir / "sar.json")
    _rewrite_json(
        config.change_dir / "change.json", lambda d: d["source_sar"].update(sha256=sar_sha)
    )
    _rewrite_json(
        config.stats_dir / "stats_meta.json",
        lambda d: d["inputs"].update(
            {"sar.json": sar_sha, "change.json": _sha(config.change_dir / "change.json")}
        ),
    )
    _fails_without_writing(config, "valid mask")


def test_terrain_with_other_corners_is_rejected(tmp_path: Path):
    config = write_inputs(tmp_path)
    write_terrain(
        config.terrain_dir,
        config.ingest_dir / "ingest.json",
        coordinates=[[-121.0, 36.0], [-120.9, 36.0], [-120.9, 35.9], [-121.0, 35.9]],
    )
    _fails_without_writing(config, "corners")


def test_terrain_png_must_match_its_manifest(tmp_path: Path):
    config = write_inputs(tmp_path, terrain=True)
    (config.terrain_dir / "slope.png").write_bytes(b"not the png")
    _fails_without_writing(config, "slope.png")


def test_mock_weather_is_rejected(tmp_path: Path):
    config = write_inputs(tmp_path)
    write_weather(config.weather_dir, config.ingest_dir / "ingest.json", data_status="mock")
    _fails_without_writing(config, "data_status")


def test_weather_from_another_ingest_is_rejected(tmp_path: Path):
    config = write_inputs(tmp_path, weather=True)
    _rewrite_json(
        config.weather_dir / "weather_meta.json",
        lambda d: d["inputs"].update({"ingest.json": "e" * 64}),
    )
    _fails_without_writing(config, "weather_meta.json")


def test_foreign_files_in_the_output_dir_are_refused(tmp_path: Path):
    config = write_inputs(tmp_path)
    config.output_dir.mkdir()
    (config.output_dir / "notes.txt").write_text("mine", encoding="utf-8")
    with pytest.raises(ExportError, match="does not own"):
        run_export(config)
    assert (config.output_dir / "notes.txt").read_text(encoding="utf-8") == "mine"
    (config.output_dir / "notes.txt").unlink()
    (config.output_dir / "layers").mkdir()
    (config.output_dir / "layers" / "optical_after.png").write_bytes(b"x")
    with pytest.raises(ExportError, match="does not own"):
        run_export(config)


def test_output_dir_may_not_be_an_input_dir(tmp_path: Path):
    config = write_inputs(tmp_path)
    clash = ExportConfig(**{**config.__dict__, "output_dir": config.stats_dir})
    with pytest.raises(ExportError, match="output_dir"):
        run_export(clash)


def test_failed_rerun_keeps_the_previous_bundle(tmp_path: Path):
    config = write_inputs(tmp_path)
    run_export(config)
    before = (config.output_dir / "layers.json").read_bytes()
    (config.stats_dir / "stats.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ExportError):
        run_export(config)
    assert (config.output_dir / "layers.json").read_bytes() == before
    assert (config.output_dir / "stats.json").exists()


def test_failure_after_staging_publishes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    config = write_inputs(tmp_path)

    def boom(*_args: Any, **_kwargs: Any) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(export, "write_png", boom)
    _fails_without_writing(config, "disk full")


# --------------------------------------------------------------------------- config + CLI


def test_load_config_resolves_relative_paths(tmp_path: Path):
    cfg = tmp_path / "case.toml"
    cfg.write_text(
        "\n".join(
            [
                'case_id = "plaskett-2026"',
                'name = "Plaskett Fire"',
                'location = "Big Sur"',
                'fire_start = "2026-08-26"',
                'ingest_dir = "i"',
                'sar_dir = "s"',
                'change_dir = "c"',
                'perimeter_dir = "p"',
                'stats_dir = "st"',
                'terrain_dir = "t"',
                'weather_dir = "w"',
                'output_dir = "out"',
                "[[sources]]",
                'label = "CAL FIRE"',
                'url = "https://www.fire.ca.gov/"',
            ]
        ),
        encoding="utf-8",
    )
    config = load_config(cfg, base_dir=tmp_path)
    assert config.output_dir == tmp_path / "out"
    assert config.sources == [{"label": "CAL FIRE", "url": "https://www.fire.ca.gov/"}]


def test_load_config_rejects_a_bad_date(tmp_path: Path):
    cfg = tmp_path / "case.toml"
    text = (ROOT / "pipeline/configs/case_plaskett.toml").read_text(encoding="utf-8")
    cfg.write_text(text.replace('"2026-08-26"', '"26/08/2026"'), encoding="utf-8")
    with pytest.raises(ExportError, match="fire_start"):
        load_config(cfg, base_dir=tmp_path)


def test_repository_config_loads(tmp_path: Path):
    config = load_config(ROOT / "pipeline/configs/case_plaskett.toml", base_dir=tmp_path)
    assert config.case_id == "plaskett-2026"
    assert config.output_dir == tmp_path / "data/processed/web"


def test_cli_exit_codes(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    config = write_inputs(tmp_path)
    cfg = tmp_path / "case.toml"
    lines = [
        f'case_id = "{config.case_id}"',
        f'name = "{config.name}"',
        f'location = "{config.location}"',
        f'fire_start = "{config.fire_start}"',
        *(
            f"{key} = '{getattr(config, key).as_posix()}'"
            for key in (
                "ingest_dir",
                "sar_dir",
                "change_dir",
                "perimeter_dir",
                "stats_dir",
                "terrain_dir",
                "weather_dir",
                "output_dir",
            )
        ),
        "[[sources]]",
        'label = "CAL FIRE"',
        'url = "https://www.fire.ca.gov/"',
    ]
    cfg.write_text("\n".join(lines), encoding="utf-8")
    assert main(["--config", str(cfg)]) == 0
    assert "export ok" in capsys.readouterr().out
    (config.stats_dir / "stats.json").write_text("{}", encoding="utf-8")
    assert main(["--config", str(cfg)]) == 2
    assert "export error" in capsys.readouterr().err


# --------------------------------------------------------------------------- review fixes


@pytest.mark.parametrize("sibling", [".web.staging", ".web.previous"])
def test_input_on_a_staging_or_backup_path_is_rejected(tmp_path: Path, sibling: str):
    config = write_inputs(tmp_path)
    moved = config.output_dir.with_name(sibling)
    config.ingest_dir.rename(moved)
    clash = ExportConfig(**{**config.__dict__, "ingest_dir": moved})
    with pytest.raises(ExportError, match="staging/backup"):
        run_export(clash)
    assert (moved / "ingest.json").is_file(), "the input must never be deleted"


@pytest.mark.parametrize("sibling", [".web.staging", ".web.previous"])
def test_foreign_files_in_staging_or_backup_are_refused(tmp_path: Path, sibling: str):
    config = write_inputs(tmp_path)
    foreign = config.output_dir.with_name(sibling)
    foreign.mkdir()
    (foreign / "notes.txt").write_text("mine", encoding="utf-8")
    with pytest.raises(ExportError, match="does not own"):
        run_export(config)
    assert (foreign / "notes.txt").read_text(encoding="utf-8") == "mine"


def test_directory_under_an_allowed_png_name_is_refused(tmp_path: Path):
    config = write_inputs(tmp_path)
    run_export(config)
    (config.output_dir / "layers" / "slope.png").mkdir()
    (config.output_dir / "layers" / "slope.png" / "notes.txt").write_text("x", encoding="utf-8")
    (config.output_dir / "weather.json").mkdir()
    with pytest.raises(ExportError, match="does not own") as info:
        run_export(config)
    assert "layers/slope.png" in str(info.value) and "weather.json" in str(info.value)
    assert (config.output_dir / "layers" / "slope.png" / "notes.txt").is_file()


def test_symlink_in_the_output_is_refused(tmp_path: Path):
    config = write_inputs(tmp_path)
    run_export(config)
    link = config.output_dir / "weather.json"
    try:
        os.symlink(config.stats_dir / "stats.json", link)
    except OSError:
        pytest.skip("symlinks are not available on this system")
    with pytest.raises(ExportError, match="does not own"):
        run_export(config)
    assert (config.stats_dir / "stats.json").is_file()


def test_raster_is_decoded_from_the_verified_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    config = write_inputs(tmp_path)
    target = config.sar_dir / "t1_hh_db.tif"
    real = export._read_bytes
    hits: list[Path] = []

    def racing(path: Path) -> bytes:
        payload = real(path)
        if path == target:
            hits.append(path)  # replaced right after hashing: same grid, other values
            _cog(target, (T1_HH + 100.0).astype(np.float32), np.nan)
        return payload

    monkeypatch.setattr(export, "_read_bytes", racing)
    run_export(config)
    assert hits == [target], "the raster is read exactly once, through the verified bytes"
    valid = MASK == 1
    hh = _layers(config.output_dir)["sar_t1_hh"]["legend"]["domain"]
    assert hh == list(sar_domain(T1_HH[valid], T2_HH[valid]))


def test_backup_cleanup_failure_still_reports_the_published_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    config = write_inputs(tmp_path)
    run_export(config)
    real_rmtree = shutil.rmtree

    def flaky(path: Any, *args: Any, **kwargs: Any) -> None:
        if Path(path).name == ".web.previous":
            raise PermissionError("backup locked")
        real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(shutil, "rmtree", flaky)
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1794355200")  # 2026-11-11T00:00:00Z
    run_export(config)
    assert _load(config.output_dir / "case.json")["generated_at"] == "2026-11-11T00:00:00Z"
    assert config.output_dir.with_name(".web.previous").is_dir(), "backup kept, not lost"
    assert "export warning" in capsys.readouterr().err


def test_failed_swap_restores_the_previous_bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    config = write_inputs(tmp_path)
    run_export(config)
    before = (config.output_dir / "case.json").read_bytes()
    real_rename = Path.rename

    def blocked(self: Path, target: Any) -> Any:
        if self.name == ".web.staging":
            raise OSError("rename blocked")
        return real_rename(self, target)

    monkeypatch.setattr(Path, "rename", blocked)
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1794355200")
    with pytest.raises(ExportError, match="rename blocked"):
        run_export(config)
    assert (config.output_dir / "case.json").read_bytes() == before
    assert not config.output_dir.with_name(".web.previous").exists()
    assert not config.output_dir.with_name(".web.staging").exists()


def test_junction_in_the_output_is_refused(tmp_path: Path):
    winapi = pytest.importorskip("_winapi")
    config = write_inputs(tmp_path)
    run_export(config)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "slope.png").write_bytes(b"precious")
    shutil.rmtree(config.output_dir / "layers")
    winapi.CreateJunction(str(elsewhere), str(config.output_dir / "layers"))
    with pytest.raises(ExportError, match="does not own"):
        run_export(config)
    assert (elsewhere / "slope.png").read_bytes() == b"precious"
