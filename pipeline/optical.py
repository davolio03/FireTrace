"""Optical context: Sentinel-2 true colour during (smoke) and after the fire (DT-07).

Shows that optical imagery is blinded by smoke where L-band radar is not. Complementary
context only: NISAR stays the primary observation and these images validate nothing.

Two commands:

- ``fetch`` (one-off, public data, no credentials): reads each scene's STAC item from Earth
  Search, downloads the B04/B03/B02 and SCL COGs once over HTTPS, keeps only the exact
  window of the DT-01 crop grid (tile 10SFE shares EPSG:32610 and the 10 m lattice, so no
  resampling) and writes ``data/raw/sentinel2/optical_manifest.json`` with sha256.
- ``build`` (offline): verifies the crops, converts L2A digital numbers to reflectance
  (``DN * scale + offset``; 0 = nodata), renders one fixed common stretch for both scenes
  and writes EPSG:3857 PNGs, the ``optical_layers.json`` fragment merged by DT-04, the crop
  COGs and ``optical.json``.

Run from the repository root::

    uv run python -m pipeline.optical fetch --config pipeline/configs/optical_plaskett.toml
    uv run python -m pipeline.optical build --config pipeline/configs/optical_plaskett.toml
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import sys
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from affine import Affine
from rasterio.errors import RasterioError
from rasterio.windows import Window

from pipeline import publishing
from pipeline.publishing import PublishError
from pipeline.sar import (
    ANALYSIS_CRS,
    ANALYSIS_PIXEL_SIZE_M,
    SarError,
    _staging_dirs,
    clear_staging,
    discard_staging,
    overlapping_input,
    publish,
)
from pipeline.webexport import WebExportError, warp_to_web, write_png

OPTICAL_FORMAT_VERSION = 1
MANIFEST_VERSION = 1
CONTRACT_VERSION = "1.2.0"
LAYER_IDS: tuple[str, ...] = ("optical_during", "optical_after")
RGB_BANDS: tuple[str, ...] = ("red", "green", "blue")  # B04, B03, B02
SCL_RES_M = 20.0
OFFSET_POLICIES = ("stac", "none")
MAX_NEGATIVE_SHARE = 0.01  # more negative reflectance than this means a wrong DN offset
TITLES = {
    "optical_during": "Optical during the fire (Sentinel-2, {date})",
    "optical_after": "Optical after the fire (Sentinel-2, {date})",
}
NOTES = {
    "optical_during": "True colour B04/B03/B02, fixed reflectance stretch 0-{max}. Smoke hides "
    "the ground; L-band radar sees through it. Complementary context, not validation.",
    "optical_after": "True colour B04/B03/B02, fixed reflectance stretch 0-{max}, after the "
    "fire. Complementary context, not validation.",
}
OUTPUT_FILES: frozenset[str] = frozenset(
    {
        "optical_layers.json",
        "optical.json",
        *(f"{lid}.png" for lid in LAYER_IDS),
        *(f"{lid}.tif" for lid in LAYER_IDS),
    }
)

JsonGetter = Callable[[str], dict[str, Any]]
Downloader = Callable[[str, Path], None]


class OpticalError(Exception):
    """Raised for any condition that prevents faithful optical context layers."""


# --------------------------------------------------------------------------- config


@dataclass(frozen=True)
class OpticalConfig:
    stac_items_url: str
    source_label: str
    source_url: str
    reflectance_max: float
    gamma: float
    dn_offset_policy: str
    scenes: Mapping[str, str]
    ingest_dir: Path
    raw_dir: Path
    output_dir: Path


def load_config(path: Path, base_dir: Path | None = None) -> OpticalConfig:
    base = Path.cwd() if base_dir is None else base_dir
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise OpticalError(f"config: cannot read {path.name}: {exc}") from exc

    def need(key: str, kind: type) -> Any:
        value = raw.get(key)
        if kind is float and isinstance(value, int) and not isinstance(value, bool):
            value = float(value)
        if not isinstance(value, kind) or isinstance(value, bool):
            raise OpticalError(f"config: '{key}' must be {kind.__name__}")
        return value

    def resolve(key: str) -> Path:
        p = Path(need(key, str))
        return p if p.is_absolute() else base / p

    scenes_raw = raw.get("scenes")
    if not isinstance(scenes_raw, dict) or set(scenes_raw) != set(LAYER_IDS):
        raise OpticalError(f"config: [scenes] must define exactly {list(LAYER_IDS)}")
    scenes = {}
    for lid in LAYER_IDS:
        sid = scenes_raw[lid].get("id") if isinstance(scenes_raw[lid], dict) else None
        if not isinstance(sid, str) or not sid:
            raise OpticalError(f"config: scenes.{lid}.id must be a scene id")
        scenes[lid] = sid
    rmax, gamma = need("reflectance_max", float), need("gamma", float)
    if not (0 < rmax <= 1.0 and gamma > 0):
        raise OpticalError("config: reflectance_max must be in (0, 1] and gamma > 0")
    policy = need("dn_offset_policy", str)
    if policy not in OFFSET_POLICIES:
        raise OpticalError(f"config: dn_offset_policy must be one of {list(OFFSET_POLICIES)}")
    url = need("stac_items_url", str)
    if not url.startswith("https://"):
        raise OpticalError("config: stac_items_url must be HTTPS")
    return OpticalConfig(
        stac_items_url=url.rstrip("/"),
        source_label=need("source_label", str),
        source_url=need("source_url", str),
        reflectance_max=rmax,
        gamma=gamma,
        dn_offset_policy=policy,
        scenes=scenes,
        ingest_dir=resolve("ingest_dir"),
        raw_dir=resolve("raw_dir"),
        output_dir=resolve("output_dir"),
    )


# --------------------------------------------------------------------------- pure functions


def reflectance(dn: np.ndarray, *, scale: float, offset: float, nodata: int | None) -> np.ndarray:
    """Surface reflectance (float64) from L2A digital numbers; nodata becomes NaN."""
    out = dn.astype(np.float64) * scale + offset
    if nodata is not None:
        out[dn == nodata] = np.nan
    return out


def render_rgb(refl: np.ndarray, *, reflectance_max: float, gamma: float) -> np.ndarray:
    """Fixed stretch: clip(refl / max, 0, 1) ** (1 / gamma); NaN stays NaN."""
    with np.errstate(invalid="ignore"):
        return np.clip(refl / reflectance_max, 0.0, 1.0) ** (1.0 / gamma)


def _sha256(path: Path) -> str:
    with path.open("rb") as fh:
        return hashlib.file_digest(fh, "sha256").hexdigest()


def _write_json(path: Path, document: Mapping[str, Any]) -> None:
    text = json.dumps(document, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False)
    path.write_text(text + "\n", encoding="utf-8", newline="\n")


def _load_json(path: Path) -> dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OpticalError(f"cannot read {path.name}: {exc}") from exc
    if not isinstance(doc, dict):
        raise OpticalError(f"{path.name}: top level must be an object")
    return doc


def load_crop(ingest_dir: Path) -> tuple[Affine, int, int]:
    doc = _load_json(ingest_dir / "ingest.json")
    try:
        crop = doc["grid"]["crop"]
        transform = Affine(*[float(v) for v in crop["transform"]])
        width, height = int(crop["width"]), int(crop["height"])
        crs = doc["grid"]["crs"]
    except (KeyError, TypeError, ValueError) as exc:
        raise OpticalError(f"ingest.json: missing crop grid: {exc}") from exc
    size = ANALYSIS_PIXEL_SIZE_M
    if crs != "EPSG:32610" or (transform.a, transform.b, transform.d, transform.e) != (
        size,
        0.0,
        0.0,
        -size,
    ):
        raise OpticalError("ingest.json: crop is not the north-up 10 m EPSG:32610 grid")
    return transform, width, height


# --------------------------------------------------------------------------- fetch


class HttpsOnlyRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Refuses any redirect to a non-HTTPS URL before following it."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        if urllib.parse.urlsplit(newurl).scheme != "https":
            raise OpticalError("refusing a redirect to a non-HTTPS URL")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open(url: str, timeout: int):  # type: ignore[no-untyped-def]
    if not url.startswith("https://"):
        raise OpticalError("requests must use HTTPS")
    return urllib.request.build_opener(HttpsOnlyRedirectHandler).open(url, timeout=timeout)


def get_json(url: str) -> dict[str, Any]:
    if not url.startswith("https://"):
        raise OpticalError("STAC requests must use HTTPS")
    try:
        with _open(url, 60) as response:
            return json.load(response)
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        raise OpticalError(f"STAC request failed: {exc}") from exc


def download_file(url: str, dest: Path) -> None:
    """Stream a public HTTPS file to ``dest`` (no credentials are ever sent)."""
    if not url.startswith("https://"):
        raise OpticalError("downloads must use HTTPS")
    try:
        with _open(url, 300) as response, dest.open("wb") as out:
            shutil.copyfileobj(response, out, length=1 << 20)
    except urllib.error.URLError as exc:
        raise OpticalError(f"download failed: {exc}") from exc


def _exact_window(asset: Mapping[str, Any], crop: Affine, width: int, height: int) -> Window:
    tf = asset.get("proj:transform")
    shape = asset.get("proj:shape")
    if not (isinstance(tf, list) and len(tf) >= 6 and isinstance(shape, list)):
        raise OpticalError("STAC asset lacks proj:transform/proj:shape")
    a, _, c, _, e, f = (float(v) for v in tf[:6])
    if (a, e) != (ANALYSIS_PIXEL_SIZE_M, -ANALYSIS_PIXEL_SIZE_M):
        raise OpticalError(f"asset pixel size ({a}, {e}) is not 10 m")
    col, row = (crop.c - c) / a, (f - crop.f) / -e
    if not (float(col).is_integer() and float(row).is_integer()):
        raise OpticalError(
            f"the Sentinel-2 grid is not aligned with the crop grid (offset {col}, {row} px)"
        )
    col, row = int(col), int(row)
    if col < 0 or row < 0 or col + width > shape[1] or row + height > shape[0]:
        raise OpticalError("the crop window falls outside the Sentinel-2 tile")
    return Window(col, row, width, height)


def _scl_window(asset: Mapping[str, Any], crop: Affine, width: int, height: int) -> Window:
    """Smallest 20 m window covering the 10 m crop (diagnostics only)."""
    a, _, c, _, e, f = (float(v) for v in asset["proj:transform"][:6])
    if (a, e) != (SCL_RES_M, -SCL_RES_M):
        raise OpticalError("SCL asset is not 20 m")
    right = crop.c + width * crop.a
    bottom = crop.f + height * crop.e
    col0, col1 = math.floor((crop.c - c) / a), math.ceil((right - c) / a)
    row0, row1 = math.floor((f - crop.f) / -e), math.ceil((f - bottom) / -e)
    return Window(col0, row0, col1 - col0, row1 - row0)


def _write_crop(src: Path, window: Window, dest: Path) -> None:
    try:
        with rasterio.open(src) as ds:
            data = ds.read(1, window=window)
            profile = {
                "driver": "GTiff",
                "width": int(window.width),
                "height": int(window.height),
                "count": 1,
                "dtype": ds.dtypes[0],
                "crs": ds.crs,
                "transform": ds.window_transform(window),
                "nodata": ds.nodata,
                "compress": "deflate",
            }
            if ds.crs is None or ds.crs.to_epsg() != 32610:
                raise OpticalError(f"{src.name}: tile is not EPSG:32610")
        tmp = dest.with_name(dest.name + ".tmp")
        with rasterio.open(tmp, "w", **profile) as out:
            out.write(data, 1)
        os.replace(tmp, dest)
    except RasterioError as exc:
        raise OpticalError(f"{src.name}: cannot crop: {exc}") from exc


def _crop_matches(path: Path, asset: Mapping[str, Any], window: Window) -> bool:
    """True if an existing crop is exactly ``window`` of this asset's grid."""
    a, _, c, _, e, f = (float(v) for v in asset["proj:transform"][:6])
    expected = Affine(a, 0.0, c + int(window.col_off) * a, 0.0, e, f + int(window.row_off) * e)
    try:
        with rasterio.open(path) as ds:
            return (
                ds.crs is not None
                and ds.crs.to_epsg() == 32610
                and ds.transform == expected
                and (ds.width, ds.height) == (int(window.width), int(window.height))
            )
    except RasterioError:
        return False


def _iso_seconds(value: str) -> str:
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise OpticalError(f"invalid STAC datetime {value!r}") from exc
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch(
    config: OpticalConfig, get_json: JsonGetter = get_json, download: Downloader = download_file
) -> dict[str, Any]:
    """Download each scene once, keep the exact crop windows, write the manifest."""
    crop, width, height = load_crop(config.ingest_dir)
    raw = config.raw_dir
    raw.mkdir(parents=True, exist_ok=True)
    old = raw / "optical_manifest.json"
    previous: dict[str, str] = {}
    if old.is_file():
        try:
            for s in _load_json(old).get("scenes", {}).values():
                for b in (*s.get("bands", {}).values(), s.get("scl", {})):
                    previous[b["file"]] = b["sha256"]
        except (OpticalError, KeyError, TypeError, AttributeError):
            previous = {}
    scenes: dict[str, Any] = {}
    for lid, sid in config.scenes.items():
        item = get_json(f"{config.stac_items_url}/{urllib.parse.quote(sid)}")
        props = item.get("properties", {})
        epsg = props.get("proj:code") or (
            f"EPSG:{props['proj:epsg']}" if props.get("proj:epsg") else None
        )
        if epsg != "EPSG:32610":
            raise OpticalError(f"{sid}: scene is {epsg}, expected EPSG:32610")
        assets = item.get("assets", {})
        record: dict[str, Any] = {
            "scene_id": sid,
            "datetime": _iso_seconds(str(props.get("datetime", ""))),
            "platform": props.get("platform"),
            "cloud_cover_pct": props.get("eo:cloud_cover"),
            "processing_baseline": props.get("s2:processing_baseline"),
            "bands": {},
        }
        for band in (*RGB_BANDS, "scl"):
            asset = assets.get(band)
            if not isinstance(asset, dict) or not str(asset.get("href", "")).startswith("https://"):
                raise OpticalError(f"{sid}: missing HTTPS asset '{band}'")
            if band == "scl":
                window = _scl_window(asset, crop, width, height)
            else:
                window = _exact_window(asset, crop, width, height)
            name = f"{sid}_{band}.tif"
            dest = raw / name
            reusable = (
                dest.is_file()
                and previous.get(name) == _sha256(dest)
                and _crop_matches(dest, asset, window)
            )
            if not reusable:
                part = raw / (name + ".part")
                try:
                    download(asset["href"], part)
                    _write_crop(part, window, dest)
                finally:
                    if part.exists():
                        part.unlink()
            rb = (asset.get("raster:bands") or [{}])[0]
            entry = {
                "file": name,
                "href": asset["href"],
                "sha256": _sha256(dest),
                "window": {
                    "col_off": int(window.col_off),
                    "row_off": int(window.row_off),
                    "width": int(window.width),
                    "height": int(window.height),
                },
                "scale": rb.get("scale"),
                "offset": rb.get("offset"),
                "nodata": rb.get("nodata"),
            }
            if band == "scl":
                record["scl"] = entry
            else:
                record["bands"][band] = entry
        scenes[lid] = record
    manifest = {
        "optical_manifest_version": MANIFEST_VERSION,
        "stac_items_url": config.stac_items_url,
        "scenes": scenes,
    }
    tmp = old.with_name(old.name + ".tmp")
    try:
        _write_json(tmp, manifest)
        os.replace(tmp, old)
    finally:
        if tmp.exists():
            tmp.unlink()
    return manifest


# --------------------------------------------------------------------------- build


def check_output_dir(output_dir: Path) -> None:
    """Only missing or fully owned output, staging and backup directories may be replaced."""
    try:
        publishing.check_output_dir(output_dir, OUTPUT_FILES)
    except PublishError as exc:
        raise OpticalError(str(exc)) from exc


def _read_crop(path: Path, sha: str, crop: Affine, width: int, height: int) -> np.ndarray:
    if not path.is_file():
        raise OpticalError(f"crop not found: {path.name}")
    if _sha256(path) != sha:
        raise OpticalError(f"{path.name}: sha256 differs from optical_manifest.json")
    try:
        with rasterio.open(path) as ds:
            if ds.crs is None or ds.crs.to_epsg() != 32610 or ds.transform != crop:
                raise OpticalError(f"{path.name}: not on the DT-01 crop grid")
            if (ds.width, ds.height) != (width, height):
                raise OpticalError(f"{path.name}: size differs from the crop")
            return ds.read(1)
    except RasterioError as exc:
        raise OpticalError(f"{path.name}: cannot read: {exc}") from exc


def _write_rgb_tif(path: Path, dn: np.ndarray, transform: Affine, nodata: int | None) -> None:
    with rasterio.open(
        path,
        "w",
        driver="COG",
        width=dn.shape[2],
        height=dn.shape[1],
        count=3,
        dtype=dn.dtype.name,
        crs=ANALYSIS_CRS,
        transform=transform,
        nodata=nodata,
        compress="deflate",
        blocksize=256,
        overviews="NONE",
    ) as out:
        out.write(dn)
        out.set_band_description(1, "B04 red (L2A DN)")
        out.set_band_description(2, "B03 green (L2A DN)")
        out.set_band_description(3, "B02 blue (L2A DN)")


def run_build(config: OpticalConfig) -> dict[str, Any]:
    """Offline build of the optical context products; never uses the network."""
    try:
        clash = overlapping_input(config.output_dir, (config.raw_dir, config.ingest_dir))
    except SarError as exc:
        raise OpticalError(str(exc)) from exc
    if clash is not None:
        raise OpticalError("output_dir must differ from the raw and ingest directories")
    check_output_dir(config.output_dir)
    crop, width, height = load_crop(config.ingest_dir)
    manifest = _load_json(config.raw_dir / "optical_manifest.json")
    if manifest.get("optical_manifest_version") != MANIFEST_VERSION:
        raise OpticalError("optical_manifest.json: unsupported version")
    scenes = manifest.get("scenes", {})
    renders: dict[str, Any] = {}
    stats: dict[str, Any] = {}
    for lid in LAYER_IDS:
        record = scenes.get(lid)
        if not isinstance(record, dict) or record.get("scene_id") != config.scenes[lid]:
            raise OpticalError(f"optical_manifest.json: {lid} is not {config.scenes[lid]}")
        dns, refls = [], []
        below: list[float] = []
        nodata = None
        for band in RGB_BANDS:
            b = record["bands"][band]
            dn = _read_crop(config.raw_dir / b["file"], b["sha256"], crop, width, height)
            scale, offset = b.get("scale"), b.get("offset")
            if not isinstance(scale, int | float) or not isinstance(offset, int | float):
                raise OpticalError(f"{lid} {band}: missing reflectance scale/offset")
            nodata = b.get("nodata")
            applied = float(offset) if config.dn_offset_policy == "stac" else 0.0
            dns.append(dn)
            band_refl = reflectance(dn, scale=float(scale), offset=applied, nodata=nodata)
            finite = band_refl[np.isfinite(band_refl)]
            negative = float((finite < 0).mean()) if finite.size else 0.0
            if negative > MAX_NEGATIVE_SHARE:
                raise OpticalError(
                    f"{lid} {band}: {negative:.1%} of valid pixels have negative reflectance with "
                    f"offset {applied}; the DN offset does not match the data (dn_offset_policy="
                    f"{config.dn_offset_policy!r})"
                )
            refls.append(band_refl)
            if config.dn_offset_policy == "none" and float(offset) < 0:
                # Evidence that the declared offset is absent: with a real +offset/scale DN
                # offset, (almost) no valid pixel could fall below that DN.
                floor_dn = -float(offset) / float(scale)
                valid_dn = dn[dn != nodata] if nodata is not None else dn.ravel()
                below.append(float((valid_dn < floor_dn).mean()) if valid_dn.size else 0.0)
        if config.dn_offset_policy == "none" and below and max(below) <= MAX_NEGATIVE_SHARE:
            raise OpticalError(
                f"{lid}: dn_offset_policy 'none' but only {max(below):.2%} of valid DNs lie below "
                "the declared offset; the data look offset, so ignoring it would brighten them"
            )
        refl = np.stack(refls)
        valid = np.isfinite(refl).all(axis=0)
        refl[:, ~valid] = np.nan
        scl_path = config.raw_dir / record["scl"]["file"]
        if _sha256(scl_path) != record["scl"]["sha256"]:
            raise OpticalError(f"{scl_path.name}: sha256 differs from optical_manifest.json")
        with rasterio.open(scl_path) as ds:
            scl = ds.read(1)
        classes, counts = np.unique(scl[scl != 0], return_counts=True)
        total = int(counts.sum()) or 1
        stats[lid] = {
            "stac_offset": record["bands"]["red"].get("offset"),
            "offset_applied": record["bands"]["red"].get("offset")
            if config.dn_offset_policy == "stac"
            else 0.0,
            "scene_id": record["scene_id"],
            "acquired": record["datetime"],
            "valid_pct": round(100.0 * float(valid.mean()), 4),
            "median_reflectance_rgb": [
                round(float(np.median(refl[i][valid])), 6) if valid.any() else None
                for i in range(3)
            ],
            "scl_class_share_pct": {
                str(int(k)): round(100.0 * int(n) / total, 3)
                for k, n in zip(classes, counts, strict=True)
            },
        }
        renders[lid] = (
            np.stack(dns),
            render_rgb(refl, reflectance_max=config.reflectance_max, gamma=config.gamma),
            nodata,
        )

    staging, _ = _staging_dirs(config.output_dir)
    layers = []
    try:
        clear_staging(staging, OUTPUT_FILES)
        staging.mkdir(parents=True)
        for lid in LAYER_IDS:
            dn, rgb, nodata = renders[lid]
            _write_rgb_tif(staging / f"{lid}.tif", dn, crop, nodata)
            warped = [
                warp_to_web(rgb[i], src_transform=crop, src_crs=ANALYSIS_CRS, resampling="bilinear")
                for i in range(3)
            ]
            channels = np.stack([w.data for w in warped], axis=-1)
            alpha = np.isfinite(channels).all(axis=-1)
            rgba = np.zeros((*alpha.shape, 4), dtype=np.uint8)
            rgba[..., :3] = np.where(
                alpha[..., None], np.rint(np.nan_to_num(channels) * 255), 0
            ).astype(np.uint8)
            rgba[..., 3] = np.where(alpha, 255, 0).astype(np.uint8)
            write_png(staging / f"{lid}.png", rgba)
            acquired = stats[lid]["acquired"]
            layers.append(
                {
                    "id": lid,
                    "title": TITLES[lid].format(date=acquired[:10]),
                    "kind": "raster",
                    "group": "optical_context",
                    "url": f"layers/{lid}.png",
                    "coordinates": warped[0].coordinates,
                    "width_px": warped[0].width,
                    "height_px": warped[0].height,
                    "default_visible": False,
                    "default_opacity": 1.0,
                    "legend": {
                        "type": "rgb",
                        "note": NOTES[lid].format(max=f"{config.reflectance_max:g}"),
                    },
                    "acquired": acquired,
                    "source": {
                        "label": config.source_label,
                        "url": config.source_url,
                        "product_id": stats[lid]["scene_id"],
                    },
                }
            )
        fragment = {"contract_version": CONTRACT_VERSION, "data_status": "real", "layers": layers}
        _write_json(staging / "optical_layers.json", fragment)
        document: dict[str, Any] = {
            "optical_format_version": OPTICAL_FORMAT_VERSION,
            "ingest": {"sha256": _sha256(config.ingest_dir / "ingest.json")},
            "manifest": {"sha256": _sha256(config.raw_dir / "optical_manifest.json")},
            "grid": {
                "crs": ANALYSIS_CRS.to_string(),
                "transform": [float(v) for v in tuple(crop)[:6]],
                "width": width,
                "height": height,
                "resampling": "none (exact 10 m window of the Sentinel-2 tile)",
            },
            "stretch": {
                "reflectance_min": 0.0,
                "reflectance_max": config.reflectance_max,
                "gamma": config.gamma,
            },
            "reflectance": {
                "formula": "DN * scale + offset_applied (scale and offset from STAC raster:bands)",
                "dn_offset_policy": config.dn_offset_policy,
                "max_negative_share": MAX_NEGATIVE_SHARE,
            },
            "display": {"crs": "EPSG:3857", "resampling": "bilinear per channel"},
            "layers": stats,
            "outputs": {
                name: {"file": name, "sha256": _sha256(staging / name)}
                for name in sorted(p.name for p in staging.iterdir())
            },
        }
        _write_json(staging / "optical.json", document)
        publish(staging, config.output_dir, OUTPUT_FILES, "optical")
    except (SarError, WebExportError) as exc:
        raise OpticalError(str(exc)) from exc
    except (OSError, RasterioError) as exc:
        raise OpticalError(f"cannot write outputs: {exc}") from exc
    finally:
        discard_staging(staging, OUTPUT_FILES)
    return document


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m pipeline.optical",
        description="Sentinel-2 optical context during and after the fire.",
    )
    parser.add_argument("command", choices=("fetch", "build"))
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        if args.command == "fetch":
            manifest = fetch(config)
            print(f"fetch ok: {len(manifest['scenes'])} scenes cropped")
        else:
            doc = run_build(config)
            summary = ", ".join(
                f"{lid} {s['acquired'][:10]} valid {s['valid_pct']}%"
                for lid, s in doc["layers"].items()
            )
            print(f"optical ok: {summary}")
    except OpticalError as exc:
        print(f"optical error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
