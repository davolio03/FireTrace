"""Export the web bundle ``data/processed/web/`` from the verified pipeline products (DT-04).

The bundle has the contract layout (``contracts/README.md``), so the web switches from mocks
to real data by changing ``VITE_DATA_BASE_URL`` only:

- ``layers/<id>.png``: one RGBA PNG per raster layer (``sar_t{1,2}_{hh,hv}``,
  ``change_hh``, ``change_hv``, ``change_index``, ``valid_mask``), warped from the 10 m
  EPSG:32610 analysis grid to EPSG:3857 with the shared ``pipeline.webexport`` helper.
  Float values are resampled with **nearest** neighbour, then coloured, so every display
  pixel shows one real analysis pixel and no invalid pixel becomes opaque. Every layer is
  transparent where the DT-02 common valid mask is 0.
- ``layers.json``: ids, titles, groups, corners and legends with the computed stretches,
  plus the DT-05 terrain layers when ``terrain.json`` exists.
- ``case.json``: identity from ``case_plaskett.toml``, acquisition/epochs/AOI/product from
  ``ingest.json``, reference from ``perimeter.json``, method from ``change.json``.
- ``perimeter.geojson``, ``stats.json`` and (when present) ``weather.json`` byte for byte.
- ``export.json``: input/output checksums, resampling and stretch rules (not a contract file).

The PNGs are for viewing only; nothing is ever measured from them. Every input is checked
against the manifest of the stage that produced it, and the whole manifest chain must come
from one generation. The bundle is built in a staging directory and swapped into place.

Run from the repository root::

    uv run python -m pipeline.export --config pipeline/configs/case_plaskett.toml
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import numpy as np
from affine import Affine

from pipeline import publishing
from pipeline.publishing import PublishError, decode_raster, staging_dirs
from pipeline.sar import ANALYSIS_CRS, ANALYSIS_PIXEL_SIZE_M, SarError
from pipeline.webexport import WebExportError, WebRaster, colorize, warp_to_web, write_png

EXPORT_FORMAT_VERSION = 1
CONTRACT_VERSION = "1.2.0"
PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"
RESAMPLING = "nearest"
SAR_NAMES: tuple[str, ...] = ("t1_hh", "t2_hh", "t1_hv", "t2_hv")
CHANGE_NAMES: tuple[str, ...] = ("change_hh_db", "change_hv_db", "change_index")
TERRAIN_IDS: tuple[str, ...] = ("hillshade", "slope")
RASTER_IDS: tuple[str, ...] = (
    "sar_t1_hh",
    "sar_t2_hh",
    "sar_t1_hv",
    "sar_t2_hv",
    "change_hh",
    "change_hv",
    "change_index",
    "valid_mask",
)
TOP_FILES: frozenset[str] = frozenset(
    {"case.json", "layers.json", "stats.json", "perimeter.geojson", "weather.json", "export.json"}
)
LAYER_FILES: frozenset[str] = frozenset(f"{lid}.png" for lid in (*RASTER_IDS, *TERRAIN_IDS))
LAYER_SUBDIRS: dict[str, frozenset[str]] = {"layers": LAYER_FILES}

GREY = ("#000000", "#ffffff")
RDBU = ("#2166ac", "#92c5de", "#f7f7f7", "#f4a582", "#b2182b")  # contract fixture stops
VIRIDIS = ("#440154", "#3b528b", "#21918c", "#5ec962", "#fde725")
INVALID_GREY = "#7f7f7f"
CHANGE_UNITS = "dB difference (after - before)"
INDEX_UNITS = "index (unitless, robust z-score)"
SAR_NOTE = (
    "Grey stretch shared by before and after: p2-p98 of both dates over common-valid pixels, "
    "rounded outward to whole dB; values outside clamp to black or white. Display only: "
    "numbers come from the inspector, not from this image."
)
CHANGE_NOTE = (
    "Diverging stretch symmetric around 0 and shared by HH and HV: +/- the p98 of |change| "
    "over common-valid pixels, rounded up to a whole dB. Blue = backscatter decrease, red = "
    "increase; values outside clamp to the end colours. Observation, not interpretation."
)
INDEX_NOTE = (
    "Viridis stretch from p2 to p98 of the index over common-valid pixels, rounded outward to "
    "0.01; values outside clamp to the end colours. Continuous observation with no threshold."
)
MASK_NOTE = (
    "Grey where at least one of the four HH/HV inputs is invalid (DT-02 common mask); these "
    "pixels are transparent in every other radar layer."
)
PERIMETER_NOTE = "Reference only, not pixel-level truth."
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_CASE_ID = re.compile(r"^[a-z0-9-]+$")


class ExportError(Exception):
    """Raised for any input condition that prevents a faithful web bundle."""


# --------------------------------------------------------------------------- config


@dataclass(frozen=True)
class ExportConfig:
    case_id: str
    name: str
    location: str
    fire_start: str
    sources: list[dict[str, str]]
    ingest_dir: Path
    sar_dir: Path
    change_dir: Path
    perimeter_dir: Path
    stats_dir: Path
    terrain_dir: Path
    weather_dir: Path
    output_dir: Path

    def input_dirs(self) -> list[Path]:
        return [
            self.ingest_dir,
            self.sar_dir,
            self.change_dir,
            self.perimeter_dir,
            self.stats_dir,
            self.terrain_dir,
            self.weather_dir,
        ]


def _require_str(table: Mapping[str, Any], key: str) -> str:
    value = table.get(key)
    if not isinstance(value, str) or not value:
        raise ExportError(f"config: '{key}' must be a non-empty string, got {value!r}")
    return value


def load_config(path: Path, base_dir: Path | None = None) -> ExportConfig:
    """Parse the TOML configuration; relative paths resolve against ``base_dir`` (cwd)."""
    base = Path.cwd() if base_dir is None else base_dir
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ExportError(f"config: cannot read {path.name}: {exc}") from exc

    def resolve(key: str) -> Path:
        p = Path(_require_str(raw, key))
        return p if p.is_absolute() else base / p

    case_id = _require_str(raw, "case_id")
    if not _CASE_ID.match(case_id):
        raise ExportError(f"config: 'case_id' must match {_CASE_ID.pattern}, got {case_id!r}")
    fire_start = _require_str(raw, "fire_start")
    try:
        if not _DATE.match(fire_start):
            raise ValueError
        date.fromisoformat(fire_start)
    except ValueError as exc:
        raise ExportError(f"config: 'fire_start' must be YYYY-MM-DD, got {fire_start!r}") from exc
    sources = raw.get("sources", [])
    if not isinstance(sources, list):
        raise ExportError("config: 'sources' must be an array of tables")
    clean: list[dict[str, str]] = []
    for i, item in enumerate(sources):
        if not isinstance(item, dict) or set(item) != {"label", "url"}:
            raise ExportError(f"config: sources[{i}] must have exactly 'label' and 'url'")
        label, url = _require_str(item, "label"), _require_str(item, "url")
        if not url.startswith(("https://", "http://")):
            raise ExportError(f"config: sources[{i}].url must be an http(s) URL")
        clean.append({"label": label, "url": url})
    return ExportConfig(
        case_id=case_id,
        name=_require_str(raw, "name"),
        location=_require_str(raw, "location"),
        fire_start=fire_start,
        sources=clean,
        ingest_dir=resolve("ingest_dir"),
        sar_dir=resolve("sar_dir"),
        change_dir=resolve("change_dir"),
        perimeter_dir=resolve("perimeter_dir"),
        stats_dir=resolve("stats_dir"),
        terrain_dir=resolve("terrain_dir"),
        weather_dir=resolve("weather_dir"),
        output_dir=resolve("output_dir"),
    )


def generated_at(environ: Mapping[str, str]) -> str:
    """UTC timestamp; ``SOURCE_DATE_EPOCH`` (reproducible builds) pins it when set."""
    value = environ.get("SOURCE_DATE_EPOCH")
    if value is None:
        moment = datetime.now(UTC)
    else:
        if not value.isdigit():
            raise ExportError(f"SOURCE_DATE_EPOCH must be whole seconds, got {value!r}")
        try:
            moment = datetime.fromtimestamp(int(value), UTC)
        except (OverflowError, OSError, ValueError) as exc:
            raise ExportError(f"SOURCE_DATE_EPOCH out of range: {value!r}") from exc
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def pipeline_version() -> str:
    try:
        project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]
        return f"{project['name']} {project['version']}"
    except (OSError, tomllib.TOMLDecodeError, KeyError, TypeError) as exc:
        raise ExportError(f"cannot read the pipeline version from pyproject.toml: {exc}") from exc


# --------------------------------------------------------------------------- stretches


def _percentiles(values: np.ndarray, qs: Sequence[float]) -> list[float]:
    finite = np.ravel(values)[np.isfinite(np.ravel(values))].astype(np.float64)
    if finite.size == 0:
        raise ExportError("no valid pixels to compute a display stretch")
    return [float(v) for v in np.percentile(finite, qs)]


def _round_out(lo: float, hi: float, step: float) -> tuple[float, float]:
    """Round ``lo`` down and ``hi`` up to multiples of ``step``; never an empty domain."""
    # Rounding the quotient first keeps float noise (e.g. -0.9000000001) from moving a step.
    lo_r = math.floor(round(lo / step, 6)) * step
    hi_r = math.ceil(round(hi / step, 6)) * step
    if hi_r <= lo_r:
        hi_r = lo_r + step
    return round(lo_r, 6) + 0.0, round(hi_r, 6) + 0.0


def sar_domain(t1: np.ndarray, t2: np.ndarray) -> tuple[float, float]:
    """Joint before+after p2-p98 in dB, rounded outward to whole dB."""
    p2, p98 = _percentiles(np.concatenate([np.ravel(t1), np.ravel(t2)]), (2, 98))
    return _round_out(p2, p98, 1.0)


def change_half_range(hh: np.ndarray, hv: np.ndarray) -> float:
    """p98 of |change| over HH and HV together, rounded up to a whole dB (at least 1)."""
    (p98,) = _percentiles(np.abs(np.concatenate([np.ravel(hh), np.ravel(hv)])), (98,))
    return float(max(math.ceil(round(p98, 6)), 1))


def index_domain(index: np.ndarray) -> tuple[float, float]:
    """p2-p98 of the change index, rounded outward to hundredths."""
    p2, p98 = _percentiles(index, (2, 98))
    return _round_out(p2, p98, 0.01)


def _even_stops(lo: float, hi: float, colors: Sequence[str]) -> list[tuple[float, str]]:
    n = len(colors) - 1
    values = [lo] + [round(lo + k * (hi - lo) / n, 6) for k in range(1, n)] + [hi]
    return list(zip(values, colors, strict=True))


def _continuous(units: str, stops: list[tuple[float, str]], note: str) -> dict[str, Any]:
    return {
        "type": "continuous",
        "units": units,
        "domain": [stops[0][0], stops[-1][0]],
        "stops": [{"value": v, "color": c} for v, c in stops],
        "note": note,
    }


# --------------------------------------------------------------------------- inputs


def _sha_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _read_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise ExportError(f"cannot read {path.name}: {exc}") from exc


def _manifest(path: Path) -> tuple[dict[str, Any], str]:
    """Parse a JSON manifest and return it with the sha256 of the exact bytes parsed."""
    payload = _read_bytes(path)
    doc = _parse(payload, path.name)
    if not isinstance(doc, dict):
        raise ExportError(f"{path.name}: top level must be an object")
    return doc, _sha_bytes(payload)


def _parse(payload: bytes, source: str) -> Any:
    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExportError(f"{source}: not valid JSON: {exc}") from exc


def _verified(path: Path, sha256: Any, manifest: str) -> bytes:
    payload = _read_bytes(path)
    if _sha_bytes(payload) != sha256:
        raise ExportError(f"{path.name}: sha256 differs from {manifest}; re-run that stage")
    return payload


def _get(doc: Mapping[str, Any], keys: Sequence[str], source: str) -> Any:
    node: Any = doc
    for key in keys:
        if not isinstance(node, Mapping) or key not in node:
            raise ExportError(f"{source}: missing '{'.'.join(keys)}'")
        node = node[key]
    return node


def _version(doc: Mapping[str, Any], key: str, source: str) -> None:
    if doc.get(key) != 1:
        raise ExportError(f"{source}: unsupported {key} {doc.get(key)!r}")


def _record(doc: Mapping[str, Any], keys: Sequence[str], source: str) -> tuple[str, str]:
    record = _get(doc, keys, source)
    file = record.get("file") if isinstance(record, Mapping) else None
    sha = record.get("sha256") if isinstance(record, Mapping) else None
    if not isinstance(file, str) or not (isinstance(sha, str) and len(sha) == 64):
        raise ExportError(f"{source}: '{'.'.join(keys)}' needs 'file' and a sha256")
    if Path(file).name != file:
        raise ExportError(f"{source}: '{'.'.join(keys)}.file' must be a bare file name")
    return file, sha


def _grid(node: Any, source: str) -> dict[str, Any]:
    if not isinstance(node, Mapping):
        raise ExportError(f"{source}: malformed grid")
    transform, width, height = node.get("transform"), node.get("width"), node.get("height")
    if not (
        isinstance(transform, list)
        and len(transform) == 6
        and all(isinstance(v, int | float) and not isinstance(v, bool) for v in transform)
        and isinstance(width, int)
        and isinstance(height, int)
        and not isinstance(width, bool)
        and not isinstance(height, bool)
        and width > 0
        and height > 0
    ):
        raise ExportError(f"{source}: malformed grid")
    return {"transform": [float(v) for v in transform], "width": width, "height": height}


def _same_grid(node: Any, crop: Mapping[str, Any], source: str) -> None:
    if _grid(node, source) != crop:
        raise ExportError(f"{source}: grid differs from the ingest.json crop grid")


def _chain(recorded: Any, actual: str, source: str, upstream: str) -> None:
    if recorded != actual:
        raise ExportError(f"{source} was built from another {upstream}; re-run the pipeline")


@dataclass(frozen=True)
class Inputs:
    ingest: dict[str, Any]
    change: dict[str, Any]
    perimeter: dict[str, Any]
    crop: dict[str, Any]
    shas: dict[str, str]
    valid: np.ndarray
    sar: dict[str, np.ndarray]
    changes: dict[str, np.ndarray]
    perimeter_geojson: bytes
    stats_json: bytes


def _raster(
    directory: Path, record: tuple[str, str], crop: Mapping[str, Any], dtype: str, manifest: str
) -> np.ndarray:
    """Decode the exact bytes whose sha256 was verified (the path is never re-opened)."""
    name = record[0]
    payload = _verified(directory / name, record[1], manifest)
    try:
        raster = decode_raster(payload, name)
    except PublishError as exc:
        raise ExportError(str(exc)) from exc
    data = raster.data
    count, actual_dtype, crs = raster.count, raster.dtype, raster.crs
    transform, height, width = raster.transform, raster.height, raster.width
    if count != 1 or actual_dtype != dtype:
        raise ExportError(f"{name}: expected 1 {dtype} band, got {count} {actual_dtype}")
    if crs != ANALYSIS_CRS:
        raise ExportError(f"{name}: CRS {crs} is not the analysis CRS EPSG:32610")
    if [float(v) for v in tuple(transform)[:6]] != crop["transform"]:
        raise ExportError(f"{name}: transform differs from the ingest.json crop grid")
    if (height, width) != (crop["height"], crop["width"]):
        raise ExportError(f"{name}: shape {(height, width)} differs from the ingest.json crop")
    return data


def load_inputs(config: ExportConfig) -> Inputs:
    """Read every required product and check the manifest chain, grids and checksums."""
    ingest, ingest_sha = _manifest(config.ingest_dir / "ingest.json")
    _version(ingest, "ingest_format_version", "ingest.json")
    if _get(ingest, ("grid", "crs"), "ingest.json") != ANALYSIS_CRS.to_string():
        raise ExportError("ingest.json: grid CRS is not the analysis CRS EPSG:32610")
    crop = _grid(_get(ingest, ("grid", "crop"), "ingest.json"), "ingest.json")
    a, b, _c, d, e, _f = crop["transform"]
    if (a, b, d, e) != (ANALYSIS_PIXEL_SIZE_M, 0.0, 0.0, -ANALYSIS_PIXEL_SIZE_M):
        raise ExportError("ingest.json: crop grid is not the north-up 10 m analysis grid")

    sar, sar_sha = _manifest(config.sar_dir / "sar.json")
    _version(sar, "sar_format_version", "sar.json")
    _chain(
        _get(sar, ("source_ingest", "sha256"), "sar.json"), ingest_sha, "sar.json", "ingest.json"
    )
    _same_grid(sar.get("grid"), crop, "sar.json")

    change, change_sha = _manifest(config.change_dir / "change.json")
    _version(change, "change_format_version", "change.json")
    _chain(
        _get(change, ("source_sar", "sha256"), "change.json"), sar_sha, "change.json", "sar.json"
    )
    _same_grid(change.get("grid"), crop, "change.json")
    if not isinstance(change.get("method"), dict):
        raise ExportError("change.json: 'method' must be an object")

    perimeter, perimeter_sha = _manifest(config.perimeter_dir / "perimeter.json")
    _version(perimeter, "perimeter_format_version", "perimeter.json")
    _same_grid(perimeter.get("grid"), crop, "perimeter.json")
    raw = _get(perimeter, ("raw",), "perimeter.json")
    used = _get(ingest, ("reference",), "ingest.json")
    if not (
        isinstance(raw, Mapping)
        and isinstance(used, Mapping)
        and raw.get("sha256") == used.get("sha256")
        and _get(perimeter, ("reference", "objectid"), "perimeter.json") == used.get("objectid")
    ):
        raise ExportError(
            "perimeter.json: raw perimeter differs from the one ingest.json used for the AOI"
        )
    geo_file, geo_sha = _record(perimeter, ("outputs", "perimeter.geojson"), "perimeter.json")
    geojson = _verified(config.perimeter_dir / geo_file, geo_sha, "perimeter.json")

    meta, meta_sha = _manifest(config.stats_dir / "stats_meta.json")
    _version(meta, "stats_format_version", "stats_meta.json")
    expected = {"change.json": change_sha, "sar.json": sar_sha, "perimeter.json": perimeter_sha}
    _chain(_get(meta, ("inputs",), "stats_meta.json"), expected, "stats_meta.json", "upstream set")
    stats_json = _verified(
        config.stats_dir / "stats.json",
        _get(meta, ("outputs", "stats.json"), "stats_meta.json"),
        "stats_meta.json",
    )
    _real(_parse(stats_json, "stats.json"), "stats.json")

    for doc, source in ((ingest, "ingest.json"), (sar, "sar.json"), (change, "change.json")):
        if doc.get("case_id") != config.case_id:
            raise ExportError(f"{source}: case_id {doc.get('case_id')!r} is not {config.case_id!r}")

    mask_record = _record(sar, ("valid_mask",), "sar.json")
    mask = _raster(config.sar_dir, mask_record, crop, "uint8", "sar.json")
    if not np.isin(mask, (0, 1)).all():
        raise ExportError("valid_mask.tif: values other than 0 and 1")
    valid = mask == 1
    if not valid.any():
        raise ExportError("valid_mask.tif: no valid pixel")
    arrays: dict[str, np.ndarray] = {}
    for name in SAR_NAMES:
        record = _record(sar, ("db", "layers", name), "sar.json")
        arrays[name] = _raster(config.sar_dir, record, crop, "float32", "sar.json")
    for name in CHANGE_NAMES:
        record = _record(change, ("outputs", name), "change.json")
        arrays[name] = _raster(config.change_dir, record, crop, "float32", "change.json")
    for name, data in arrays.items():
        if not np.isfinite(data[valid]).all():
            raise ExportError(f"{name}: non-finite values where the DT-02 valid mask is 1")
    return Inputs(
        ingest=ingest,
        change=change,
        perimeter=perimeter,
        crop=crop,
        shas={
            "ingest.json": ingest_sha,
            "sar.json": sar_sha,
            "change.json": change_sha,
            "perimeter.json": perimeter_sha,
            "stats_meta.json": meta_sha,
            "stats.json": _sha_bytes(stats_json),
        },
        valid=valid,
        sar={n: arrays[n] for n in SAR_NAMES},
        changes={n: arrays[n] for n in CHANGE_NAMES},
        perimeter_geojson=geojson,
        stats_json=stats_json,
    )


def _real(doc: Any, source: str) -> None:
    if not isinstance(doc, dict) or doc.get("contract_version") != CONTRACT_VERSION:
        raise ExportError(f"{source}: contract_version must be {CONTRACT_VERSION}")
    if doc.get("data_status") != "real":
        raise ExportError(f"{source}: data_status must be 'real', got {doc.get('data_status')!r}")


@dataclass(frozen=True)
class Terrain:
    layers: list[dict[str, Any]]
    pngs: dict[str, bytes]
    sha: str


def load_terrain(config: ExportConfig, ingest_sha: str, crop: Mapping[str, Any]) -> Terrain | None:
    """DT-05 display layers, or None when the terrain stage has not been run."""
    if not config.terrain_dir.exists():
        return None
    doc, sha = _manifest(config.terrain_dir / "terrain.json")
    _version(doc, "terrain_format_version", "terrain.json")
    _chain(
        _get(doc, ("ingest", "sha256"), "terrain.json"), ingest_sha, "terrain.json", "ingest.json"
    )
    _same_grid(doc.get("grid"), crop, "terrain.json")
    payloads: dict[str, bytes] = {}
    for name in ("terrain_layers.json", *(f"{lid}.png" for lid in TERRAIN_IDS)):
        file, file_sha = _record(doc, ("outputs", name), "terrain.json")
        payloads[name] = _verified(config.terrain_dir / file, file_sha, "terrain.json")
    fragment = _parse(payloads.pop("terrain_layers.json"), "terrain_layers.json")
    _real(fragment, "terrain_layers.json")
    layers = fragment.get("layers")
    if not isinstance(layers, list) or [lyr.get("id") for lyr in layers] != list(TERRAIN_IDS):
        raise ExportError(f"terrain_layers.json: layers must be exactly {list(TERRAIN_IDS)}")
    for layer in layers:
        lid = layer["id"]
        if layer.get("group") != "terrain" or not isinstance(layer.get("source"), dict):
            raise ExportError(f"terrain_layers.json: {lid} needs group 'terrain' and a source")
        if layer.get("url") != f"layers/{lid}.png":
            raise ExportError(f"terrain_layers.json: {lid} url must be layers/{lid}.png")
    return Terrain(
        layers=layers, pngs={lid: payloads[f"{lid}.png"] for lid in TERRAIN_IDS}, sha=sha
    )


def load_weather(config: ExportConfig, ingest_sha: str) -> tuple[bytes, str] | None:
    """DT-06 ``weather.json`` bytes and manifest sha, or None when not built."""
    if not config.weather_dir.exists():
        return None
    meta, sha = _manifest(config.weather_dir / "weather_meta.json")
    _version(meta, "weather_format_version", "weather_meta.json")
    recorded = _get(meta, ("inputs", "ingest.json"), "weather_meta.json")
    _chain(recorded, ingest_sha, "weather_meta.json", "ingest.json")
    payload = _verified(
        config.weather_dir / "weather.json",
        _get(meta, ("outputs", "weather.json"), "weather_meta.json"),
        "weather_meta.json",
    )
    _real(_parse(payload, "weather.json"), "weather.json")
    return payload, sha


# --------------------------------------------------------------------------- build


def _layer(
    lid: str,
    title: str,
    group: str,
    web: WebRaster,
    legend: dict[str, Any],
    *,
    visible: bool,
    opacity: float,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "id": lid,
        "title": title,
        "kind": "raster",
        "group": group,
        "url": f"layers/{lid}.png",
        "coordinates": web.coordinates,
        "width_px": web.width,
        "height_px": web.height,
        "default_visible": visible,
        "default_opacity": opacity,
        "legend": legend,
        **extra,
    }


def _same_web_grid(a: WebRaster, b: WebRaster, what: str) -> None:
    if (a.transform, a.width, a.height, a.coordinates) != (
        b.transform,
        b.width,
        b.height,
        b.coordinates,
    ):
        raise ExportError(f"{what}: EPSG:3857 grid differs from the other layers")


def _render(staging: Path, inputs: Inputs) -> tuple[list[dict[str, Any]], WebRaster, dict]:
    """Write the eight radar PNGs; return their layer entries, the web grid and domains."""
    valid = inputs.valid
    transform = Affine(*inputs.crop["transform"])
    sar, ch = inputs.sar, inputs.changes
    hh = sar_domain(sar["t1_hh"][valid], sar["t2_hh"][valid])
    hv = sar_domain(sar["t1_hv"][valid], sar["t2_hv"][valid])
    half = change_half_range(ch["change_hh_db"][valid], ch["change_hv_db"][valid])
    idx = index_domain(ch["change_index"][valid])
    stops = {
        "hh": list(zip(hh, GREY, strict=True)),
        "hv": list(zip(hv, GREY, strict=True)),
        "change": _even_stops(-half, half, RDBU),
        "index": _even_stops(*idx, VIRIDIS),
    }

    def warp(data: np.ndarray) -> WebRaster:
        return warp_to_web(
            np.where(valid, data.astype(np.float64), np.nan),
            src_transform=transform,
            src_crs=ANALYSIS_CRS,
            resampling=RESAMPLING,
        )

    titles = {"t1": "before", "t2": "after"}
    plan: list[tuple[str, np.ndarray, list[tuple[float, str]], dict[str, Any]]] = []
    for name in SAR_NAMES:
        epoch, pol = name.split("_")
        pol_key = pol.lower()
        legend = _continuous("dB", stops[pol_key], SAR_NOTE)
        meta = {
            "title": f"SAR backscatter {pol.upper()} — {titles[epoch]}",
            "group": "sar",
            "legend": legend,
            "visible": name == "t1_hh",
            "opacity": 1.0,
            "extra": {"epoch": epoch, "polarization": pol.upper()},
        }
        plan.append((f"sar_{name}", sar[name], stops[pol_key], meta))
    for pol in ("hh", "hv"):
        meta = {
            "title": f"Observed radar changes — {pol.upper()}",
            "group": "observed_change",
            "legend": _continuous(CHANGE_UNITS, stops["change"], CHANGE_NOTE),
            "visible": False,
            "opacity": 0.85,
            "extra": {"polarization": pol.upper()},
        }
        plan.append((f"change_{pol}", ch[f"change_{pol}_db"], stops["change"], meta))
    plan.append(
        (
            "change_index",
            ch["change_index"],
            stops["index"],
            {
                "title": "Observed radar changes — combined index",
                "group": "observed_change",
                "legend": _continuous(INDEX_UNITS, stops["index"], INDEX_NOTE),
                "visible": True,
                "opacity": 0.85,
                "extra": {},
            },
        )
    )

    layers: list[dict[str, Any]] = []
    grid: WebRaster | None = None
    for lid, data, ramp, meta in plan:
        web = warp(data)
        grid = web if grid is None else grid
        _same_web_grid(web, grid, lid)
        write_png(staging / "layers" / f"{lid}.png", colorize(web.data, ramp))
        layers.append(
            _layer(
                lid,
                meta["title"],
                meta["group"],
                web,
                meta["legend"],
                visible=meta["visible"],
                opacity=meta["opacity"],
                **meta["extra"],
            )
        )
    assert grid is not None
    # Quality layer: grey where invalid, transparent where valid and outside the crop.
    mask_web = warp_to_web(
        np.where(valid, np.nan, 0.0),
        src_transform=transform,
        src_crs=ANALYSIS_CRS,
        resampling=RESAMPLING,
    )
    _same_web_grid(mask_web, grid, "valid_mask")
    write_png(
        staging / "layers" / "valid_mask.png",
        colorize(mask_web.data, [(0.0, INVALID_GREY), (1.0, INVALID_GREY)]),
    )
    mask_legend = {
        "type": "categorical",
        "items": [{"value": 0, "label": "Invalid in at least one layer", "color": INVALID_GREY}],
        "note": MASK_NOTE,
    }
    layers.append(
        _layer(
            "valid_mask",
            "No-data / invalid pixels",
            "quality",
            mask_web,
            mask_legend,
            visible=False,
            opacity=1.0,
        )
    )
    domains = {"sar_hh": list(hh), "sar_hv": list(hv), "change_db": [-half, half]}
    domains["change_index"] = list(idx)
    return layers, grid, domains


def _perimeter_layer(reference: Mapping[str, Any]) -> dict[str, Any]:
    try:
        stamp = datetime.strptime(str(reference["datetime"]), "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise ExportError(f"perimeter.json: reference datetime is not UTC ISO: {exc}") from exc
    return {
        "id": "perimeter",
        "title": "Official fire perimeter",
        "kind": "vector",
        "group": "reference",
        "url": "perimeter.geojson",
        "default_visible": True,
        "default_opacity": 1.0,
        "legend": {
            "type": "categorical",
            "items": [
                {
                    "value": f"WFIGS {reference['objectid']}",
                    "label": f"WFIGS perimeter, {stamp:%Y-%m-%d %H:%M} UTC",
                    "color": "#000000",
                }
            ],
            "note": PERIMETER_NOTE,
        },
    }


def build_case(config: ExportConfig, inputs: Inputs, stamp: str, version: str) -> dict[str, Any]:
    ingest = inputs.ingest
    acquisition = _get(ingest, ("acquisition",), "ingest.json")
    keys = ("track", "frame", "direction", "frequency", "polarizations", "pixel_size_m", "crs")
    epochs = {}
    for epoch in ("t1", "t2"):
        record = _get(ingest, ("epochs", epoch), "ingest.json")
        epochs[epoch] = {
            k: _get(record, (k,), f"ingest.json epochs.{epoch}")
            for k in ("label", "datetime", "granule_id", "absolute_orbit")
        }
    reference = _get(inputs.perimeter, ("reference",), "perimeter.json")
    return {
        "contract_version": CONTRACT_VERSION,
        "data_status": "real",
        "case_id": config.case_id,
        "name": config.name,
        "location": config.location,
        "fire_start": config.fire_start,
        "aoi_bbox": _get(ingest, ("aoi", "aoi_bbox_4326"), "ingest.json"),
        "epochs": epochs,
        "acquisition": {k: _get(acquisition, (k,), "ingest.json acquisition") for k in keys},
        "product": _get(ingest, ("product",), "ingest.json"),
        "reference": {
            k: _get(reference, (k,), "perimeter.json reference")
            for k in ("source", "objectid", "datetime", "url", "note")
        },
        "method": inputs.change["method"],
        "sources": config.sources,
        "generated_at": stamp,
        "pipeline_version": version,
    }


def _write_json(path: Path, document: Mapping[str, Any]) -> None:
    text = json.dumps(document, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False)
    path.write_text(text + "\n", encoding="utf-8", newline="\n")


def check_output_dir(output_dir: Path) -> None:
    """The output directory and its staging/backup siblings must hold only our files.

    Owned names must be regular files and ``layers`` a plain directory of owned PNGs; any
    other directory, symlink or junction is foreign (``pipeline.publishing``).
    """
    try:
        publishing.check_output_dir(output_dir, TOP_FILES, LAYER_SUBDIRS)
    except PublishError as exc:
        raise ExportError(str(exc)) from exc


def _check_separate(config: ExportConfig) -> None:
    """No input directory may be, or lie inside, the output or its staging/backup siblings."""
    try:
        clash = publishing.overlapping_input(config.output_dir, config.input_dirs())
    except PublishError as exc:
        raise ExportError(str(exc)) from exc
    if clash is not None:
        raise ExportError(
            "output_dir and its staging/backup siblings must be separate from every "
            f"input directory ({clash.name})"
        )


def run_export(config: ExportConfig, environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Build and publish the web bundle; return the ``export.json`` document written."""
    stamp = generated_at(os.environ if environ is None else environ)
    version = pipeline_version()
    _check_separate(config)
    check_output_dir(config.output_dir)
    inputs = load_inputs(config)
    terrain = load_terrain(config, inputs.shas["ingest.json"], inputs.crop)
    weather = load_weather(config, inputs.shas["ingest.json"])

    staging, _ = staging_dirs(config.output_dir)
    try:
        publishing.remove_owned(staging, TOP_FILES, LAYER_SUBDIRS)
        (staging / "layers").mkdir(parents=True)
        layers, grid, domains = _render(staging, inputs)
        if terrain is not None:
            for layer in terrain.layers:
                lid = layer["id"]
                if layer.get("coordinates") != grid.coordinates:
                    raise ExportError(
                        f"terrain_layers.json: {lid} corners differ from the SAR layers"
                    )
                if (layer.get("width_px"), layer.get("height_px")) != (grid.width, grid.height):
                    raise ExportError(
                        f"terrain_layers.json: {lid} size differs from the SAR layers"
                    )
                (staging / "layers" / f"{lid}.png").write_bytes(terrain.pngs[lid])
            layers += terrain.layers
        layers.append(_perimeter_layer(_get(inputs.perimeter, ("reference",), "perimeter.json")))
        _write_json(
            staging / "layers.json",
            {"contract_version": CONTRACT_VERSION, "data_status": "real", "layers": layers},
        )
        _write_json(staging / "case.json", build_case(config, inputs, stamp, version))
        (staging / "perimeter.geojson").write_bytes(inputs.perimeter_geojson)
        (staging / "stats.json").write_bytes(inputs.stats_json)
        input_shas = dict(inputs.shas)
        if terrain is not None:
            input_shas["terrain.json"] = terrain.sha
        if weather is not None:
            (staging / "weather.json").write_bytes(weather[0])
            input_shas["weather_meta.json"] = weather[1]
        outputs = {
            p.relative_to(staging).as_posix(): _sha_bytes(p.read_bytes())
            for p in sorted(staging.rglob("*"))
            if p.is_file()
        }
        document = {
            "export_format_version": EXPORT_FORMAT_VERSION,
            "case_id": config.case_id,
            "generated_at": stamp,
            "pipeline_version": version,
            "inputs": input_shas,
            "optional": {"terrain": terrain is not None, "weather": weather is not None},
            "display": {
                "crs": "EPSG:3857",
                "resampling": RESAMPLING,
                "rule": "float values warped with nearest neighbour, then coloured; "
                "transparent where the DT-02 common valid mask is 0 or outside the crop",
                "web_grid": {
                    "transform": [float(v) for v in tuple(grid.transform)[:6]],
                    "width": grid.width,
                    "height": grid.height,
                    "coordinates": grid.coordinates,
                },
                "domains": domains,
                "stretch": {
                    "sar": "joint t1+t2 p2-p98 per polarisation, rounded outward to whole dB",
                    "change_db": "symmetric +/- ceil(p98(|change|)) over HH and HV, at least 1",
                    "change_index": "p2-p98 rounded outward to 0.01",
                    "percentiles": "NumPy linear interpolation over float32 values, "
                    "common-valid pixels only",
                    "out_of_range": "clamped to the end colours",
                },
            },
            "outputs": outputs,
        }
        _write_json(staging / "export.json", document)
        warning = publishing.publish(staging, config.output_dir, TOP_FILES, LAYER_SUBDIRS)
    except (SarError, WebExportError, PublishError) as exc:
        raise ExportError(str(exc)) from exc
    except OSError as exc:
        raise ExportError(f"cannot write outputs: {exc}") from exc
    finally:
        publishing.discard_staging(staging, TOP_FILES, LAYER_SUBDIRS)
    publishing.report(warning, "export")
    return document


# --------------------------------------------------------------------------- CLI


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m pipeline.export",
        description="Export the verified pipeline products as the web bundle (contract layout).",
    )
    parser.add_argument("--config", type=Path, default=Path("pipeline/configs/case_plaskett.toml"))
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        doc = run_export(config)
    except ExportError as exc:
        print(f"export error: {exc}", file=sys.stderr)
        return 2
    extras = [name for name, present in doc["optional"].items() if present]
    d = doc["display"]["domains"]
    print(
        f"export ok: {len(RASTER_IDS)} radar layers"
        f"{' + ' + ' + '.join(extras) if extras else ''} -> {config.output_dir}; "
        f"HH {d['sar_hh']} dB, HV {d['sar_hv']} dB, change {d['change_db']} dB, "
        f"index {d['change_index']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
