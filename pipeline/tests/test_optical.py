"""DT-07 optical context: exact grid window, fixed stretch, offline build, web fragment.

A fake STAC item and small synthetic Sentinel-2-like tiles stand in for Earth Search; no
network access and no real data are used.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import urllib.request
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import rasterio
from affine import Affine
from jsonschema import Draft202012Validator
from rasterio.crs import CRS

from pipeline import optical
from pipeline.optical import (
    OpticalError,
    fetch,
    load_config,
    main,
    reflectance,
    render_rgb,
    run_build,
)

ROOT = Path(__file__).resolve().parents[2]
UTM10N = CRS.from_epsg(32610)
TILE_ORIGIN = (600_000.0, 4_000_020.0)
TILE = 100  # 100 x 100 px synthetic tile at 10 m
CROP_T = Affine(10.0, 0.0, 600_100.0, 0.0, -10.0, 3_999_920.0)  # col 10, row 10 of the tile
CW, CH = 30, 20
SCENES = {"optical_during": "S2A_TEST_20260830_0_L2A", "optical_after": "S2B_TEST_20261015_0_L2A"}


def dn_for(refl: float) -> int:
    return round((refl + 0.1) / 1e-4)  # L2A baseline >= 04.00: refl = DN * 1e-4 - 0.1


def write_tile(path: Path, value: int, *, res: float = 10.0, origin=TILE_ORIGIN, zero_block=False):
    size = int(TILE * 10 / res)
    data = np.full((size, size), value, dtype=np.uint16)
    if zero_block:
        data[12:14, 15:20] = 0  # nodata inside the crop window (rows 12-13, cols 15-19)
    t = Affine(res, 0.0, origin[0], 0.0, -res, origin[1])
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=size,
        height=size,
        count=1,
        dtype="uint16",
        crs=UTM10N,
        transform=t,
        nodata=0,
    ) as ds:
        ds.write(data, 1)


def stac_item(scene: str, origin=TILE_ORIGIN) -> dict[str, Any]:
    def asset(band: str, res: float) -> dict[str, Any]:
        size = int(TILE * 10 / res)
        rb = {"nodata": 0, "data_type": "uint16" if band != "scl" else "uint8"}
        if band != "scl":
            rb.update({"scale": 0.0001, "offset": -0.1})
        return {
            "href": f"https://tiles.example/{scene}/{band}.tif",
            "proj:transform": [res, 0, origin[0], 0, -res, origin[1]],
            "proj:shape": [size, size],
            "raster:bands": [rb],
        }

    return {
        "id": scene,
        "properties": {
            "datetime": "2026-08-30T18:54:53.893000Z"
            if "0830" in scene
            else "2026-10-15T19:04:33Z",
            "proj:code": "EPSG:32610",
            "platform": "sentinel-2a",
            "eo:cloud_cover": 2.2,
            "s2:processing_baseline": "05.12",
        },
        "assets": {
            "red": asset("red", 10),
            "green": asset("green", 10),
            "blue": asset("blue", 10),
            "scl": asset("scl", 20),
        },
    }


class FakeRemote:
    """Serves STAC items and synthetic tiles from a local folder; counts downloads."""

    def __init__(self, root: Path, values: dict[str, int], origin=TILE_ORIGIN, zero_block=False):
        self.root, self.downloads, self.origin = root, 0, origin
        root.mkdir(parents=True, exist_ok=True)
        for scene in SCENES.values():
            for band, value in values.items():
                write_tile(
                    root / f"{scene}_{band}.tif", value, origin=origin, zero_block=zero_block
                )
            write_tile(root / f"{scene}_scl.tif", 4, res=20.0, origin=origin)

    def get_json(self, url: str) -> dict[str, Any]:
        return stac_item(url.rstrip("/").split("/")[-1], self.origin)

    def download(self, url: str, dest: Path) -> None:
        self.downloads += 1
        scene, band = url.split("/")[-2], url.split("/")[-1].removesuffix(".tif")
        shutil.copy(self.root / f"{scene}_{band}.tif", dest)


def write_ingest(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    doc = {
        "ingest_format_version": 1,
        "grid": {
            "crs": "EPSG:32610",
            "crop": {"transform": list(CROP_T)[:6], "width": CW, "height": CH},
        },
    }
    (root / "ingest.json").write_text(json.dumps(doc), encoding="utf-8")
    return root


def write_config(tmp_path: Path, policy: str = "stac") -> Path:
    write_ingest(tmp_path / "nisar")
    scenes = "\n".join(f'[scenes.{k}]\nid = "{v}"\n' for k, v in SCENES.items())
    path = tmp_path / "optical.toml"
    path.write_text(
        f"""
stac_items_url = "https://stac.example/collections/sentinel-2-l2a/items"
source_label = "Copernicus Sentinel-2 L2A (ESA), via Earth Search on AWS Open Data"
source_url = "https://registry.opendata.aws/sentinel-2-l2a-cogs/"
reflectance_max = 0.3
gamma = 2.2
dn_offset_policy = "{policy}"
ingest_dir = "nisar"
raw_dir = "raw"
output_dir = "out"
{scenes}
""",
        encoding="utf-8",
    )
    return path


def fetched(
    tmp_path: Path, values: dict[str, int] | None = None, policy: str = "stac", **remote_kw: Any
):
    values = values or {"red": dn_for(0.15), "green": dn_for(0.1), "blue": dn_for(0.05)}
    remote = FakeRemote(tmp_path / "remote", values, **remote_kw)
    config = load_config(write_config(tmp_path, policy), base_dir=tmp_path)
    fetch(config, get_json=remote.get_json, download=remote.download)
    return config, remote


# --------------------------------------------------------------------------- pure functions


def test_reflectance_applies_l2a_scale_offset_and_nodata() -> None:
    dn = np.array([0, 1000, 2500, 11000], dtype=np.uint16)
    refl = reflectance(dn, scale=1e-4, offset=-0.1, nodata=0)
    assert np.isnan(refl[0])
    assert refl[1:].tolist() == pytest.approx([0.0, 0.15, 1.0])


def test_render_rgb_uses_the_fixed_common_stretch() -> None:
    refl = np.array([[[0.15, -0.02, 0.6, np.nan]]] * 3)  # same value in R, G, B
    rgb = render_rgb(refl, reflectance_max=0.3, gamma=2.2)
    expected = round(255 * 0.5 ** (1 / 2.2))
    assert rgb[0, 0, 0] == pytest.approx(0.5 ** (1 / 2.2))
    assert round(255 * rgb[0, 0, 0]) == expected
    assert rgb[0, 0, 1] == 0.0 and rgb[0, 0, 2] == 1.0, "clipped below 0 and above max"
    assert np.isnan(rgb[0, 0, 3])


# --------------------------------------------------------------------------- fetch


def test_fetch_stores_exact_crop_windows_and_manifest(tmp_path: Path) -> None:
    config, remote = fetched(tmp_path)
    manifest = json.loads((tmp_path / "raw" / "optical_manifest.json").read_text(encoding="utf-8"))
    assert set(manifest["scenes"]) == set(SCENES)
    for lid, scene in SCENES.items():
        record = manifest["scenes"][lid]
        assert record["scene_id"] == scene
        for band in ("red", "green", "blue"):
            b = record["bands"][band]
            path = tmp_path / "raw" / b["file"]
            assert b["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
            with rasterio.open(path) as ds:
                assert ds.transform == CROP_T and (ds.width, ds.height) == (CW, CH)
                assert b["window"] == {"col_off": 10, "row_off": 10, "width": CW, "height": CH}
        with rasterio.open(tmp_path / "raw" / record["scl"]["file"]) as ds:
            left, top = ds.transform.c, ds.transform.f
            assert left <= CROP_T.c and top >= CROP_T.f, "the 20 m SCL window covers the crop"
    assert remote.downloads == 8
    assert not list((tmp_path / "raw").glob("*.part")), "temporary full tiles are removed"
    fetch(config, get_json=remote.get_json, download=remote.download)
    assert remote.downloads == 8, "verified crops are reused, not downloaded again"


def test_misaligned_tile_grid_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(OpticalError, match="aligned"):
        fetched(tmp_path, origin=(600_005.0, 4_000_020.0))


# --------------------------------------------------------------------------- build


def _build(tmp_path: Path, **kw: Any) -> dict[str, Any]:
    config, _ = fetched(tmp_path, **kw)
    return run_build(config)


def test_build_writes_fragment_valid_against_the_layers_contract(tmp_path: Path) -> None:
    doc = _build(tmp_path)
    fragment = json.loads((tmp_path / "out" / "optical_layers.json").read_text(encoding="utf-8"))
    assert [lyr["id"] for lyr in fragment["layers"]] == list(SCENES)
    schema = json.loads(
        (ROOT / "contracts" / "schemas" / "layers.schema.json").read_text(encoding="utf-8")
    )
    validator = Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)
    assert list(validator.iter_errors(fragment)) == []
    during = fragment["layers"][0]
    assert during["group"] == "optical_context" and during["legend"]["type"] == "rgb"
    assert during["source"]["product_id"] == SCENES["optical_during"]
    assert during["acquired"] == "2026-08-30T18:54:53Z"
    assert during["url"] == "layers/optical_during.png"
    assert doc["stretch"] == {"reflectance_min": 0.0, "reflectance_max": 0.3, "gamma": 2.2}


def test_png_is_rgba_with_transparent_nodata(tmp_path: Path) -> None:
    _build(tmp_path, zero_block=True)
    with rasterio.open(tmp_path / "out" / "optical_during.png") as ds:
        rgba = ds.read()
    assert rgba.shape[0] == 4
    alpha = rgba[3]
    assert (alpha == 0).any() and (alpha == 255).any()


def test_stats_and_crop_cog(tmp_path: Path) -> None:
    doc = _build(tmp_path, zero_block=True)
    layer = doc["layers"]["optical_during"]
    assert layer["valid_pct"] == pytest.approx(100 * (CW * CH - 10) / (CW * CH))
    assert layer["median_reflectance_rgb"] == pytest.approx([0.15, 0.1, 0.05], abs=1e-6)
    assert layer["scl_class_share_pct"] == {"4": 100.0}
    with rasterio.open(tmp_path / "out" / "optical_during.tif") as ds:
        assert ds.count == 3 and ds.dtypes[0] == "uint16" and ds.transform == CROP_T


def test_outputs_are_byte_identical_across_runs(tmp_path: Path) -> None:
    config, _ = fetched(tmp_path)
    run_build(config)
    first = {p.name: p.read_bytes() for p in sorted((tmp_path / "out").iterdir())}
    run_build(config)
    second = {p.name: p.read_bytes() for p in sorted((tmp_path / "out").iterdir())}
    assert first == second


def test_build_never_uses_the_network(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config, _ = fetched(tmp_path)

    def forbidden(*_a: Any, **_k: Any) -> None:
        raise AssertionError("build must not open network connections")

    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    run_build(config)


def test_checksum_mismatch_is_rejected(tmp_path: Path) -> None:
    config, _ = fetched(tmp_path)
    manifest_path = tmp_path / "raw" / "optical_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["scenes"]["optical_after"]["bands"]["green"]["sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(OpticalError, match="sha256"):
        run_build(config)
    assert not (tmp_path / "out").exists()


def test_cli_reports_errors_with_exit_code(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["build", "--config", str(tmp_path / "missing.toml")]) == 2
    assert "optical error" in capsys.readouterr().err


def test_default_downloader_requires_https() -> None:
    with pytest.raises(OpticalError, match="HTTPS"):
        optical.download_file("http://example.invalid/x.tif", Path("unused"))


# --------------------------------------------------------------- DN offset policy


def test_wrong_offset_is_caught_by_the_negative_reflectance_check(tmp_path: Path) -> None:
    # Real Earth Search crops: DN ~ 440 over land, i.e. no +1000 offset despite STAC "-0.1".
    config, _ = fetched(tmp_path, {"red": 441, "green": 400, "blue": 252}, policy="stac")
    with pytest.raises(OpticalError, match="negative reflectance"):
        run_build(config)
    assert not (tmp_path / "out").exists()


def test_policy_none_reads_dn_as_reflectance_times_10000(tmp_path: Path) -> None:
    config, _ = fetched(tmp_path, {"red": 441, "green": 400, "blue": 252}, policy="none")
    doc = run_build(config)
    layer = doc["layers"]["optical_after"]
    assert layer["median_reflectance_rgb"] == pytest.approx([0.0441, 0.04, 0.0252])
    assert layer["offset_applied"] == 0.0 and layer["stac_offset"] == -0.1
    assert doc["reflectance"]["dn_offset_policy"] == "none"


def test_unknown_offset_policy_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(OpticalError, match="dn_offset_policy"):
        load_config(write_config(tmp_path, "guess"), base_dir=tmp_path)
