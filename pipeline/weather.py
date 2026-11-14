"""Daily precipitation over the case AOI between the two NISAR acquisitions (DT-06).

Context for the soil-moisture caveat: rain before the after scene can raise L-band
backscatter. This series is context only; it does not explain any individual pixel.

Two separate commands:

- ``fetch`` (one-off, needs the user's Earthdata token): lists NASA GPM IMERG Late daily
  V07 granules through the public CMR API and downloads them to ``data/raw/imerg/`` with a
  sha256 manifest. The token is read from a file or ``EARTHDATA_TOKEN`` and never written.
- ``build`` (offline, reproducible): verifies the local granules against the manifest and
  writes ``weather.json`` (web contract) and ``weather_meta.json``.

Rules (agreed with David): IMERG Late V07C because Final is not yet released for the period
(G1); area-weighted mean of the 0.1 degree cells overlapping the DT-01 AOI bbox (I1);
``daily`` lists every UTC day from the t1 date to the t2 date, while the summary (total,
rain days, last rain) only uses days before the t2 date, because t2 was acquired at
02:56 UTC (J1).

Run from the repository root::

    uv run python -m pipeline.weather fetch --token-file <file>
    uv run python -m pipeline.weather build
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr

from pipeline import publishing
from pipeline.publishing import PublishError
from pipeline.sar import SarError, _staging_dirs, publish

WEATHER_FORMAT_VERSION = 1
MANIFEST_VERSION = 1
CONTRACT_VERSION = "1.2.0"
SHORT_NAME = "GPM_3IMERGDL"
COLLECTION_VERSION = "07"
VERSION = "V07C"  # agreed granule version (decision G1)
# The bearer token is only ever sent over HTTPS to NASA Earthdata hosts.
TOKEN_HOST_SUFFIX = ".earthdata.nasa.gov"
OVERLAP_EPS_DEG = 1e-9  # overlaps below this are floating-point artefacts, not cells
CMR_GRANULES_URL = "https://cmr.earthdata.nasa.gov/search/granules.json"
SOURCE_URL = "https://disc.gsfc.nasa.gov/datasets/GPM_3IMERGDL_07/summary"
RAIN_DAY_THRESHOLD_MM = 1.0
DECIMALS = 4
COORD_DECIMALS = 4
AGGREGATION = "Area-weighted mean of IMERG 0.1 deg cells over the case AOI bbox (UTC days)"
OUTPUT_FILES: frozenset[str] = frozenset({"weather.json", "weather_meta.json"})

Downloader = Callable[[str, str], bytes]


class WeatherError(Exception):
    """Raised for any condition that prevents a faithful precipitation series."""


# --------------------------------------------------------------------------- reading + weights


def read_daily_grid(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (lon, lat, precipitation[lon, lat]) in mm/day; fill values become NaN."""
    try:
        with xr.open_dataset(path, engine="h5netcdf", mask_and_scale=True) as ds:
            precip = ds["precipitation"]
            if "time" in precip.dims:
                if precip.sizes["time"] != 1:
                    raise WeatherError(f"{path.name}: expected one time step")
                precip = precip.isel(time=0)
            precip = precip.transpose("lon", "lat")
            values = precip.values.astype(np.float64)
            # IMERG stores lon as float32 (about 1e-5 deg jitter); its cell centres are exact
            # multiples of 0.05 deg, so rounding restores the true regular grid.
            lon = np.round(ds["lon"].values.astype(np.float64), COORD_DECIMALS)
            lat = np.round(ds["lat"].values.astype(np.float64), COORD_DECIMALS)
    except WeatherError:
        raise
    except (OSError, KeyError, ValueError) as exc:
        raise WeatherError(f"{path.name}: cannot read IMERG precipitation: {exc}") from exc
    values[values < 0] = np.nan  # negative values are fill or invalid
    return lon, lat, values


def _half_step(centres: np.ndarray, axis: str) -> float:
    steps = np.diff(centres)
    if centres.size < 2 or not np.allclose(steps, steps[0], atol=1e-6) or steps[0] <= 0:
        raise WeatherError(f"IMERG {axis} centres are not a regular increasing grid")
    return float(steps[0]) / 2


def cell_weights(
    lon: np.ndarray, lat: np.ndarray, bbox: Sequence[float]
) -> dict[tuple[int, int], float]:
    """Normalised spherical-area weights of the cells overlapping ``bbox`` (W, S, E, N)."""
    west, south, east, north = (float(v) for v in bbox)
    hx, hy = _half_step(lon, "lon"), _half_step(lat, "lat")
    raw: dict[tuple[int, int], float] = {}
    for i, x in enumerate(lon):
        dx = min(x + hx, east) - max(x - hx, west)
        if dx <= OVERLAP_EPS_DEG:
            continue
        for j, y in enumerate(lat):
            lo, hi = max(y - hy, south), min(y + hy, north)
            if hi - lo <= OVERLAP_EPS_DEG:
                continue
            raw[(i, j)] = math.radians(dx) * (
                math.sin(math.radians(hi)) - math.sin(math.radians(lo))
            )
    total = sum(raw.values())
    if total <= 0:
        raise WeatherError(f"the AOI {list(bbox)} does not overlap the IMERG grid")
    return {k: v / total for k, v in sorted(raw.items())}


def aoi_mean(values: np.ndarray, weights: Mapping[tuple[int, int], float]) -> float | None:
    """Unrounded weighted mean, or None if any weighted cell is missing (conservative)."""
    cells = [values[i, j] for i, j in weights]
    if not all(np.isfinite(c) for c in cells):
        return None
    return float(sum(w * values[i, j] for (i, j), w in weights.items()))


# --------------------------------------------------------------------------- manifests


def _sha256(path: Path) -> str:
    with path.open("rb") as fh:
        return hashlib.file_digest(fh, "sha256").hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WeatherError(f"cannot read {path.name}: {exc}") from exc
    if not isinstance(doc, dict):
        raise WeatherError(f"{path.name}: top level must be an object")
    return doc


def _iso_date(value: Any, what: str) -> date:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError as exc:
        raise WeatherError(f"{what}: invalid date {value!r}") from exc


def load_case(ingest_dir: Path) -> tuple[date, date, list[float]]:
    """t1 and t2 UTC dates and the AOI bbox (EPSG:4326) recorded by DT-01."""
    doc = _load_json(ingest_dir / "ingest.json")
    try:
        t1 = _iso_date(doc["epochs"]["t1"]["datetime"], "ingest.json t1")
        t2 = _iso_date(doc["epochs"]["t2"]["datetime"], "ingest.json t2")
        bbox = [float(v) for v in doc["aoi"]["crop_bbox_4326"]]
    except (KeyError, TypeError, ValueError) as exc:
        raise WeatherError(f"ingest.json: missing epochs or AOI: {exc}") from exc
    if len(bbox) != 4 or not (bbox[0] < bbox[2] and bbox[1] < bbox[3]) or t2 <= t1:
        raise WeatherError("ingest.json: invalid AOI bbox or epochs")
    return t1, t2, bbox


def load_granules(raw_dir: Path) -> tuple[dict[str, Any], dict[date, Path]]:
    manifest = _load_json(raw_dir / "imerg_manifest.json")
    if manifest.get("imerg_manifest_version") != MANIFEST_VERSION:
        raise WeatherError("imerg_manifest.json: unsupported version")
    if manifest.get("short_name") != SHORT_NAME:
        raise WeatherError(f"imerg_manifest.json: expected {SHORT_NAME} granules")
    if manifest.get("version") != VERSION:
        raise WeatherError(
            f"imerg_manifest.json: version {manifest.get('version')!r}, expected {VERSION}"
        )
    files: dict[date, Path] = {}
    for g in manifest.get("granules", []):
        try:
            day, name, sha = _iso_date(g["date"], "granule"), g["file"], g["sha256"]
        except (KeyError, TypeError) as exc:
            raise WeatherError(f"imerg_manifest.json: malformed granule {g!r}") from exc
        path = raw_dir / Path(name).name
        if granule_version(path.name) != VERSION:
            raise WeatherError(f"{path.name}: not an IMERG {VERSION} granule")
        if not path.is_file():
            raise WeatherError(f"granule not found: {path.name}")
        if _sha256(path) != sha:
            raise WeatherError(f"{path.name}: sha256 differs from imerg_manifest.json")
        if day in files:
            raise WeatherError(f"imerg_manifest.json: two granules for {day}")
        files[day] = path
    return manifest, files


# --------------------------------------------------------------------------- build


def check_output_dir(output_dir: Path) -> None:
    """Only missing or fully owned output, staging and backup directories may be replaced."""
    try:
        publishing.check_output_dir(output_dir, OUTPUT_FILES)
    except PublishError as exc:
        raise WeatherError(str(exc)) from exc


def _write_json(path: Path, document: Mapping[str, Any]) -> None:
    text = json.dumps(document, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False)
    path.write_text(text + "\n", encoding="utf-8", newline="\n")


def run_build(raw_dir: Path, ingest_dir: Path, output_dir: Path) -> dict[str, Any]:
    """Build ``weather.json`` from verified local granules; never uses the network."""
    if publishing.overlapping_input(output_dir, (raw_dir, ingest_dir)) is not None:
        raise WeatherError("output_dir must differ from the raw and ingest directories")
    check_output_dir(output_dir)
    t1, t2, bbox = load_case(ingest_dir)
    manifest, files = load_granules(raw_dir)

    days = [t1 + timedelta(days=n) for n in range((t2 - t1).days + 1)]
    weights: dict[tuple[int, int], float] | None = None
    grid_ref: tuple[np.ndarray, np.ndarray] | None = None
    daily: list[dict[str, Any]] = []
    means: list[tuple[date, float | None]] = []
    missing: list[str] = []
    for day in days:
        value: float | None = None
        if day in files:
            lon, lat, precip = read_daily_grid(files[day])
            if grid_ref is None:
                grid_ref, weights = (lon, lat), cell_weights(lon, lat, bbox)
            elif not (np.array_equal(lon, grid_ref[0]) and np.array_equal(lat, grid_ref[1])):
                raise WeatherError(f"{files[day].name}: grid differs from the other granules")
            assert weights is not None
            value = aoi_mean(precip, weights)
        if value is None:
            missing.append(day.isoformat())
        means.append((day, value))
        daily.append(
            {"date": day.isoformat(), "value": None if value is None else round(value, DECIMALS)}
        )
    if weights is None or grid_ref is None:
        raise WeatherError("no IMERG granule covers the period")

    # Thresholds and totals use the unrounded means; only serialized values are rounded.
    summary = [(d, v) for d, v in means if v is not None and d < t2]
    rainy = [d.isoformat() for d, v in summary if v > RAIN_DAY_THRESHOLD_MM]
    version = str(manifest.get("version", "unknown"))
    document: dict[str, Any] = {
        "contract_version": CONTRACT_VERSION,
        "data_status": "real",
        "variable": "precipitation",
        "units": "mm/day",
        "aggregation": AGGREGATION,
        "source": {
            "label": f"NASA GPM IMERG Late Run daily ({version})",
            "url": SOURCE_URL,
            "product": SHORT_NAME,
        },
        "period": {"start": t1.isoformat(), "end": t2.isoformat()},
        "daily": daily,
        "total": round(sum(v for _, v in summary), DECIMALS),
        "rain_days_over_1mm": len(rainy),
        "last_rain_before_t2": rainy[-1] if rainy else None,
        "notes": (
            f"IMERG Late ({version}) is used because IMERG Final was not yet released for this "
            f"period. total, rain_days_over_1mm and last_rain_before_t2 use UTC days before "
            f"{t2.isoformat()}: the after scene was acquired early that day (UTC), so that "
            "day's rain fell mostly after it. Missing days are null and excluded. Context for "
            "the soil-moisture caveat only; not a per-pixel measurement."
        ),
    }
    lon, lat = grid_ref
    meta: dict[str, Any] = {
        "weather_format_version": WEATHER_FORMAT_VERSION,
        "inputs": {
            "ingest.json": _sha256(ingest_dir / "ingest.json"),
            "imerg_manifest.json": _sha256(raw_dir / "imerg_manifest.json"),
        },
        "imerg": {"short_name": SHORT_NAME, "version": version, "granules": len(files)},
        "aoi_bbox_4326": bbox,
        "cells": [
            {"lon": float(lon[i]), "lat": float(lat[j]), "weight": round(w, 8)}
            for (i, j), w in weights.items()
        ],
        "rules": {
            "spatial": "area-weighted (spherical) overlap of 0.1 deg cells with the AOI bbox; "
            "a day is null if any weighted cell is missing",
            "summary_days": f"UTC days before {t2.isoformat()} (t2 acquisition day excluded)",
            "rain_day": f"value > {RAIN_DAY_THRESHOLD_MM} mm",
            "rounding": f"serialized values rounded to {DECIMALS} decimals; totals and the "
            "> 1 mm test use unrounded means",
        },
        "missing_days": missing,
    }

    staging, _ = _staging_dirs(output_dir)
    try:
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True)
        _write_json(staging / "weather.json", document)
        meta["outputs"] = {"weather.json": _sha256(staging / "weather.json")}
        _write_json(staging / "weather_meta.json", meta)
        publish(staging, output_dir)
    except SarError as exc:
        raise WeatherError(str(exc)) from exc
    except OSError as exc:
        raise WeatherError(f"cannot write outputs: {exc}") from exc
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
    return document


# --------------------------------------------------------------------------- fetch


def granule_version(filename: str) -> str | None:
    """IMERG granule version from its file name, e.g. 'V07C'."""
    match = re.search(r"\.(V\d+[A-Z]?)\.nc4$", filename)
    return match.group(1) if match else None


def parse_cmr_granules(cmr: Mapping[str, Any]) -> list[dict[str, str]]:
    """One HTTPS .nc4 granule of the agreed version per day, sorted by date.

    Fails on two granules of that version for one day, or on a day that only has other
    versions, instead of silently picking one.
    """
    granules: dict[str, dict[str, str]] = {}
    other_versions: dict[str, set[str]] = {}
    for entry in cmr.get("feed", {}).get("entry", []):
        links = [
            link.get("href", "")
            for link in entry.get("links", [])
            if link.get("href", "").startswith("https://") and link["href"].endswith(".nc4")
        ]
        if not links:
            continue
        day = str(entry.get("time_start", ""))[:10]
        url = links[0]
        name = urllib.parse.urlparse(url).path.split("/")[-1]
        version = granule_version(name)
        if version != VERSION:
            other_versions.setdefault(day, set()).add(str(version))
            continue
        if day in granules:
            raise WeatherError(f"CMR lists two {VERSION} granules for {day}; refusing to guess")
        granules[day] = {"date": day, "url": url, "file": name}
    only_other = sorted(set(other_versions) - set(granules))
    if only_other:
        raise WeatherError(
            f"no {VERSION} granule for {only_other} (found {sorted(other_versions[only_other[0]])})"
        )
    return [granules[d] for d in sorted(granules)]


def query_cmr(start: date, end: date) -> list[dict[str, str]]:
    """Public CMR search (no credentials) for IMERG Late daily granules in [start, end]."""
    params = urllib.parse.urlencode(
        {
            "short_name": SHORT_NAME,
            "version": COLLECTION_VERSION,
            "temporal": f"{start.isoformat()}T00:00:00Z,{end.isoformat()}T23:59:59Z",
            "page_size": 200,
            "sort_key": "start_date",
        }
    )
    try:
        with urllib.request.urlopen(f"{CMR_GRANULES_URL}?{params}", timeout=60) as response:
            return parse_cmr_granules(json.load(response))
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        raise WeatherError(f"CMR search failed: {exc}") from exc


def token_allowed(url: str) -> bool:
    """True only for HTTPS URLs on NASA Earthdata hosts."""
    parts = urllib.parse.urlsplit(url)
    host = (parts.hostname or "").lower()
    return parts.scheme == "https" and host.endswith(TOKEN_HOST_SUFFIX)


class TokenRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Follows HTTPS redirects, sending the bearer token only to Earthdata hosts.

    The token is attached as an unredirected header, so urllib never copies it; each hop
    re-adds it only when ``token_allowed``. Any redirect to a non-HTTPS URL is refused.
    """

    def __init__(self, token: str) -> None:
        super().__init__()
        self._token = token

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        if urllib.parse.urlsplit(newurl).scheme != "https":
            raise WeatherError("refusing a redirect to a non-HTTPS URL during download")
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None:
            new.remove_header("Authorization")
            if token_allowed(newurl):
                new.add_unredirected_header("Authorization", f"Bearer {self._token}")
        return new


def download_with_token(url: str, token: str) -> bytes:
    """GET ``url`` with an Earthdata bearer token across the Earthdata login redirects."""
    if not token_allowed(url):
        raise WeatherError("downloads must start from an HTTPS NASA Earthdata URL")
    opener = urllib.request.build_opener(
        TokenRedirectHandler(token), urllib.request.HTTPCookieProcessor()
    )
    request = urllib.request.Request(url)
    request.add_unredirected_header("Authorization", f"Bearer {token}")
    try:
        with opener.open(request, timeout=300) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        hint = ""
        if exc.code == 403:
            hint = " (approve the 'NASA GESDISC DATA ARCHIVE' application / EULA in Earthdata)"
        elif exc.code == 401:
            hint = " (token missing, expired or invalid)"
        raise WeatherError(f"download failed with HTTP {exc.code}{hint}") from None
    except urllib.error.URLError as exc:
        raise WeatherError(f"download failed: {exc.reason}") from None


def fetch(
    granules: Sequence[Mapping[str, str]],
    raw_dir: Path,
    token: str,
    download: Downloader = download_with_token,
) -> dict[str, Any]:
    """Download missing granules into ``raw_dir`` and write ``imerg_manifest.json``."""
    if not token:
        raise WeatherError("an Earthdata token is required for fetch (never stored)")
    raw_dir.mkdir(parents=True, exist_ok=True)
    previous: dict[str, str] = {}
    old = raw_dir / "imerg_manifest.json"
    if old.is_file():
        try:
            previous = {g["file"]: g["sha256"] for g in _load_json(old).get("granules", [])}
        except (WeatherError, KeyError, TypeError):
            previous = {}
    records = []
    for g in granules:
        path = raw_dir / Path(g["file"]).name
        if path.is_file() and previous.get(path.name) == _sha256(path):
            sha = previous[path.name]
        else:
            data = download(g["url"], token)
            tmp = path.with_name(path.name + ".part")
            tmp.write_bytes(data)
            tmp.replace(path)
            sha = _sha256(path)
        records.append({"date": g["date"], "file": path.name, "url": g["url"], "sha256": sha})
    bad = sorted(r["file"] for r in records if granule_version(r["file"]) != VERSION)
    if bad:
        raise WeatherError(f"granules not in the agreed version {VERSION}: {bad}")
    manifest = {
        "imerg_manifest_version": MANIFEST_VERSION,
        "short_name": SHORT_NAME,
        "version": VERSION,
        "granules": records,
    }
    # Atomic replacement: an interrupted write never truncates the previous manifest.
    tmp = old.with_name(old.name + ".tmp")
    try:
        _write_json(tmp, manifest)
        os.replace(tmp, old)
    except OSError as exc:
        raise WeatherError(f"cannot write imerg_manifest.json: {exc.strerror}") from None
    finally:
        if tmp.exists():
            tmp.unlink()
    return manifest


def _read_token(token_file: Path | None) -> str:
    if token_file is not None:
        try:
            return token_file.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise WeatherError(f"cannot read the token file: {exc.strerror}") from None
    return os.environ.get("EARTHDATA_TOKEN", "").strip()


# --------------------------------------------------------------------------- CLI


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m pipeline.weather",
        description="IMERG precipitation context between the NISAR acquisitions.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    f = sub.add_parser("fetch", help="one-off download with the user's Earthdata token")
    f.add_argument("--ingest-dir", type=Path, default=Path("data/interim/nisar"))
    f.add_argument("--raw-dir", type=Path, default=Path("data/raw/imerg"))
    f.add_argument("--token-file", type=Path, default=None, help="else EARTHDATA_TOKEN")
    b = sub.add_parser("build", help="offline weather.json from local granules")
    b.add_argument("--raw-dir", type=Path, default=Path("data/raw/imerg"))
    b.add_argument("--ingest-dir", type=Path, default=Path("data/interim/nisar"))
    b.add_argument("--output-dir", type=Path, default=Path("data/interim/weather"))
    args = parser.parse_args(argv)
    try:
        if args.command == "fetch":
            t1, t2, _ = load_case(args.ingest_dir)
            granules = query_cmr(t1, t2)
            manifest = fetch(granules, args.raw_dir, _read_token(args.token_file))
            print(f"fetch ok: {len(manifest['granules'])} granules ({manifest['version']})")
        else:
            doc = run_build(args.raw_dir, args.ingest_dir, args.output_dir)
            print(
                f"weather ok: {doc['period']['start']}..{doc['period']['end']}, total "
                f"{doc['total']} mm before t2, {doc['rain_days_over_1mm']} day(s) > 1 mm, "
                f"last rain {doc['last_rain_before_t2']}"
            )
    except WeatherError as exc:
        print(f"weather error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
