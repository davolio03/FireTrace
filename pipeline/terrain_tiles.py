"""Terrarium elevation tiles for the 3D story view (AP-07).

Terrain is complementary (non-NISAR) context: the web drapes the radar layers and the
reference perimeter over it for the guided story. It is never evidence of fire.

This stage never downloads. It verifies the pinned Copernicus GLO-30 DEM tiles against
their sha256, mosaics them and writes a small Web Mercator tile pyramid that MapLibre
reads as a ``raster-dem`` source with ``encoding: "terrarium"``:

- ``{z}/{x}/{y}.png``: 256 px RGBA tiles, elevation = R*256 + G + B/256 - 32768 metres
  above the EGM2008 geoid (bilinear from the 30 m DSM, rounded to ``precision_m``; 1 m
  halves the PNG size and is far below the DEM's own vertical error);
- ``tiles.json``: TileJSON 3.0 manifest plus provenance, statistics and checksums.

Pixels outside the configured bounds are set to 0 m (MapLibre is told not to request
tiles outside them); inside the bounds every pixel must be covered by a DEM tile.

Run from the repository root::

    uv run python -m pipeline.terrain_tiles --config pipeline/configs/terrain_tiles_plaskett.toml
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.errors import RasterioError
from rasterio.transform import from_bounds
from rasterio.warp import Resampling, reproject

from pipeline import publishing
from pipeline.publishing import PublishError
from pipeline.sar import SarError, sha256_file
from pipeline.webexport import WebExportError, write_png

TILES_FORMAT_VERSION = 1
MANIFEST = "tiles.json"
WEB_MERCATOR = CRS.from_epsg(3857)
LONLAT = CRS.from_epsg(4326)
EARTH_RADIUS_M = 6378137.0
ORIGIN_SHIFT_M = math.pi * EARTH_RADIUS_M
MAX_LAT = 85.0511287798066
TERRARIUM_OFFSET_M = 32768.0
MAX_TILES = 2000
_NUM = r"(?:0|[1-9][0-9]*)"
# What this stage (and the terrain/ directory of the web bundle) owns: the manifest plus
# {z}/{x}/{y}.png at exactly that depth, canonical decimal names only (DT-09).
TILE_TREE = publishing.Tree(
    files=frozenset({MANIFEST}),
    dir_pattern=_NUM,
    pattern_child=publishing.Tree(
        dir_pattern=_NUM, pattern_child=publishing.Tree(file_pattern=rf"{_NUM}\.png")
    ),
)
TILE_NAME = re.compile(rf"({_NUM})/({_NUM})/({_NUM})\.png", re.ASCII)


class TerrainTilesError(Exception):
    """Raised for any condition that prevents faithful elevation tiles."""


# --------------------------------------------------------------------------- config


@dataclass(frozen=True)
class DemTile:
    raw: Path
    sha256: str
    product_id: str
    url: str


@dataclass(frozen=True)
class TilesConfig:
    case_id: str
    output_dir: Path
    dems: tuple[DemTile, ...]
    source_label: str
    source_url: str
    vertical_datum: str
    bounds: tuple[float, float, float, float]
    minzoom: int
    maxzoom: int
    tile_size: int
    precision_m: float


def _require(table: Mapping[str, Any], key: str, kind: type, where: str) -> Any:
    value = table.get(key)
    if not isinstance(value, kind) or isinstance(value, bool) and kind is not bool:
        raise TerrainTilesError(f"config: {where}.{key} must be a {kind.__name__}")
    return value


def _sha(value: Any, where: str) -> str:
    if not (
        isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)
    ):
        raise TerrainTilesError(f"config: {where} must be 64 lowercase hex characters")
    return value


def load_config(path: Path) -> TilesConfig:
    try:
        doc = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise TerrainTilesError(f"config: cannot read {path}: {exc}") from exc
    dem_tables = doc.get("dem")
    if not isinstance(dem_tables, list) or not dem_tables:
        raise TerrainTilesError("config: at least one [[dem]] table is required")
    dems = tuple(
        DemTile(
            raw=Path(_require(t, "raw", str, f"dem[{i}]")),
            sha256=_sha(t.get("sha256"), f"dem[{i}].sha256"),
            product_id=_require(t, "product_id", str, f"dem[{i}]"),
            url=_require(t, "url", str, f"dem[{i}]"),
        )
        for i, t in enumerate(dem_tables)
    )
    source = _require(doc, "source", dict, "root")
    tiles = _require(doc, "tiles", dict, "root")
    bounds = tiles.get("bounds")
    if (
        not isinstance(bounds, list)
        or len(bounds) != 4
        or not all(isinstance(v, int | float) and math.isfinite(v) for v in bounds)
    ):
        raise TerrainTilesError("config: tiles.bounds must be [west, south, east, north]")
    west, south, east, north = (float(v) for v in bounds)
    if not (-180 <= west < east <= 180 and -MAX_LAT <= south < north <= MAX_LAT):
        raise TerrainTilesError("config: tiles.bounds is empty or out of range")
    minzoom = _require(tiles, "minzoom", int, "tiles")
    maxzoom = _require(tiles, "maxzoom", int, "tiles")
    tile_size = _require(tiles, "tile_size", int, "tiles")
    if not 0 <= minzoom <= maxzoom <= 15:
        raise TerrainTilesError("config: need 0 <= minzoom <= maxzoom <= 15")
    if tile_size not in (256, 512):
        raise TerrainTilesError("config: tiles.tile_size must be 256 or 512")
    precision = tiles.get("precision_m", 1 / 256)
    if (
        not isinstance(precision, int | float)
        or isinstance(precision, bool)
        or not (1 / 256 <= precision <= 10)
    ):
        raise TerrainTilesError("config: tiles.precision_m must be between 1/256 and 10")
    return TilesConfig(
        case_id=_require(doc, "case_id", str, "root"),
        output_dir=Path(_require(doc, "output_dir", str, "root")),
        dems=dems,
        source_label=_require(source, "label", str, "source"),
        source_url=_require(source, "url", str, "source"),
        vertical_datum=_require(source, "vertical_datum", str, "source"),
        bounds=(west, south, east, north),
        minzoom=minzoom,
        maxzoom=maxzoom,
        tile_size=tile_size,
        precision_m=float(precision),
    )


# --------------------------------------------------------------------- tile maths


def lonlat_to_tile(lon: float, lat: float, zoom: int) -> tuple[float, float]:
    """Fractional XYZ (slippy map) tile coordinates of a WGS84 point."""
    lat = min(MAX_LAT, max(-MAX_LAT, lat))
    n = 2.0**zoom
    x = (lon + 180.0) / 360.0 * n
    rad = math.radians(lat)
    y = (1.0 - math.asinh(math.tan(rad)) / math.pi) / 2.0 * n
    return x, y


def tiles_for_bounds(bounds: tuple[float, float, float, float], zoom: int) -> list[tuple[int, int]]:
    """All (x, y) tiles at ``zoom`` that intersect the WGS84 bounds."""
    xs, ys = _tile_ranges(bounds, zoom)
    return [(x, y) for x in xs for y in ys]


def tile_count(bounds: tuple[float, float, float, float], zoom: int) -> int:
    """How many tiles :func:`tiles_for_bounds` gives, without listing them."""
    xs, ys = _tile_ranges(bounds, zoom)
    return len(xs) * len(ys)


def _tile_ranges(bounds: tuple[float, float, float, float], zoom: int) -> tuple[range, range]:
    west, south, east, north = bounds
    x0, y0 = lonlat_to_tile(west, north, zoom)
    x1, y1 = lonlat_to_tile(east, south, zoom)
    last = 2**zoom - 1
    xs = range(max(0, math.floor(x0)), min(last, math.ceil(x1) - 1) + 1)
    ys = range(max(0, math.floor(y0)), min(last, math.ceil(y1) - 1) + 1)
    return xs, ys


def tile_bounds_mercator(zoom: int, x: int, y: int) -> tuple[float, float, float, float]:
    """(left, bottom, right, top) of a tile in EPSG:3857 metres."""
    size = 2 * ORIGIN_SHIFT_M / 2**zoom
    left = -ORIGIN_SHIFT_M + x * size
    top = ORIGIN_SHIFT_M - y * size
    return left, top - size, left + size, top


def mercator_to_lonlat(mx: np.ndarray, my: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    lon = np.degrees(mx / EARTH_RADIUS_M)
    lat = np.degrees(np.arctan(np.sinh(my / EARTH_RADIUS_M)))
    return lon, lat


# ------------------------------------------------------------------- terrarium


def terrarium_encode(elevation_m: np.ndarray, precision_m: float = 1 / 256) -> np.ndarray:
    """Encode finite elevations (metres) as Terrarium RGBA, rounded to ``precision_m``."""
    if not np.all(np.isfinite(elevation_m)):
        raise TerrainTilesError("cannot encode non-finite elevations")
    rounded = np.rint(elevation_m.astype(np.float64) / precision_m) * precision_m
    scaled = np.rint((rounded + TERRARIUM_OFFSET_M) * 256.0)
    scaled = np.clip(scaled, 0, 256**3 - 1).astype(np.int64)
    rgba = np.empty((*elevation_m.shape, 4), dtype=np.uint8)
    rgba[..., 0] = scaled // 65536
    rgba[..., 1] = (scaled // 256) % 256
    rgba[..., 2] = scaled % 256
    rgba[..., 3] = 255
    return rgba


def terrarium_decode(rgba: np.ndarray) -> np.ndarray:
    r, g, b = (rgba[..., i].astype(np.float64) for i in range(3))
    return r * 256.0 + g + b / 256.0 - TERRARIUM_OFFSET_M


# ------------------------------------------------------------------------ build


def _verify(dem: DemTile) -> None:
    if not dem.raw.is_file():
        raise TerrainTilesError(
            f"{dem.raw}: DEM tile missing; fetch it on purpose with curl -fL -o {dem.raw} {dem.url}"
        )
    try:
        actual = sha256_file(dem.raw)
    except SarError as exc:
        raise TerrainTilesError(str(exc)) from exc
    if actual != dem.sha256:
        raise TerrainTilesError(
            f"{dem.raw.name}: sha256 {actual} does not match the pinned {dem.sha256}"
        )


def _render_tile(
    sources: Sequence[rasterio.io.DatasetReader],
    config: TilesConfig,
    zoom: int,
    x: int,
    y: int,
) -> np.ndarray:
    size = config.tile_size
    left, bottom, right, top = tile_bounds_mercator(zoom, x, y)
    transform = from_bounds(left, bottom, right, top, size, size)
    elevation = np.full((size, size), np.nan, dtype=np.float32)
    for src in sources:
        part = np.full((size, size), np.nan, dtype=np.float32)
        reproject(
            source=rasterio.band(src, 1),
            destination=part,
            src_nodata=src.nodata,
            dst_transform=transform,
            dst_crs=WEB_MERCATOR,
            dst_nodata=np.nan,
            resampling=Resampling.bilinear,
        )
        elevation = np.where(np.isnan(elevation), part, elevation)

    # Pixel centres inside the configured bounds must be covered by the DEM.
    cols = left + (np.arange(size) + 0.5) * (right - left) / size
    rows = top - (np.arange(size) + 0.5) * (top - bottom) / size
    lon, lat = mercator_to_lonlat(*np.meshgrid(cols, rows))
    west, south, east, north = config.bounds
    inside = (lon >= west) & (lon <= east) & (lat >= south) & (lat <= north)
    missing = inside & np.isnan(elevation)
    if missing.any():
        raise TerrainTilesError(
            f"tile {zoom}/{x}/{y}: {int(missing.sum())} pixels inside the bounds are not "
            "covered by the DEM tiles; add the neighbouring DEM tile or shrink the bounds"
        )
    return np.where(np.isnan(elevation), 0.0, elevation).astype(np.float32)


def run_tiles(config: TilesConfig) -> dict[str, Any]:
    for dem in config.dems:
        _verify(dem)
    plan = [
        (zoom, x, y)
        for zoom in range(config.minzoom, config.maxzoom + 1)
        for x, y in tiles_for_bounds(config.bounds, zoom)
    ]
    if len(plan) > MAX_TILES:
        raise TerrainTilesError(f"{len(plan)} tiles exceed the {MAX_TILES} tile limit")

    output_dir = config.output_dir
    try:
        clash = publishing.overlapping_input(output_dir, [dem.raw for dem in config.dems])
        if clash is not None:
            raise TerrainTilesError(
                "output_dir and its staging/backup siblings must be separate from every "
                f"input ({clash.name})"
            )
        publishing.check_output_dir(output_dir, TILE_TREE)
        staging = publishing.clear_staging(output_dir, TILE_TREE)
        staging.mkdir(parents=True)
    except (PublishError, OSError) as exc:
        raise TerrainTilesError(str(exc)) from exc
    outputs: dict[str, str] = {}
    low, high = math.inf, -math.inf
    try:
        sources = [rasterio.open(dem.raw) for dem in config.dems]
        try:
            for zoom, x, y in plan:
                elevation = _render_tile(sources, config, zoom, x, y)
                if zoom == config.maxzoom:
                    low = min(low, float(elevation.min()))
                    high = max(high, float(elevation.max()))
                name = f"{zoom}/{x}/{y}.png"
                write_png(staging / name, terrarium_encode(elevation, config.precision_m))
                outputs[name] = sha256_file(staging / name)
        finally:
            for src in sources:
                src.close()
        document = {
            "tilejson": "3.0.0",
            "name": "FireTrace terrain (Copernicus GLO-30)",
            "tiles": ["{z}/{x}/{y}.png"],
            "encoding": "terrarium",
            "tileSize": config.tile_size,
            "minzoom": config.minzoom,
            "maxzoom": config.maxzoom,
            "bounds": list(config.bounds),
            "attribution": config.source_label,
            "firetrace": {
                "tiles_format_version": TILES_FORMAT_VERSION,
                "case_id": config.case_id,
                "data_status": "real",
                "note": (
                    "Display context only: a 30 m digital surface model (includes canopy), "
                    "sea at 0 m. Never evidence of fire, burned area or severity."
                ),
                "source_url": config.source_url,
                "vertical_datum": config.vertical_datum,
                "surface_model": "DSM",
                "resampling": "bilinear",
                "precision_m": config.precision_m,
                "dem": [
                    {
                        "file": dem.raw.name,
                        "product_id": dem.product_id,
                        "url": dem.url,
                        "sha256": dem.sha256,
                    }
                    for dem in config.dems
                ],
                "elevation_m_at_maxzoom": {"min": round(low, 2), "max": round(high, 2)},
                "tile_count": len(outputs),
                "outputs": outputs,
            },
        }
        (staging / MANIFEST).write_text(
            json.dumps(document, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
        warning = publishing.publish(staging, output_dir, TILE_TREE)
    except (RasterioError, WebExportError, SarError, PublishError, OSError) as exc:
        raise TerrainTilesError(str(exc)) from exc
    finally:
        publishing.discard_staging(staging, TILE_TREE)
    publishing.report(warning, "terrain_tiles")
    return document


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m pipeline.terrain_tiles",
        description="Build Terrarium elevation tiles for the 3D story view.",
    )
    parser.add_argument("--config", type=Path, required=True, help="TOML tiles config")
    args = parser.parse_args(argv)
    try:
        doc = run_tiles(load_config(args.config))
    except TerrainTilesError as exc:
        print(f"terrain tiles error: {exc}", file=sys.stderr)
        return 2
    info = doc["firetrace"]
    elevation = info["elevation_m_at_maxzoom"]
    print(
        f"terrain tiles ok: {info['tile_count']} tiles, zoom {doc['minzoom']}-"
        f"{doc['maxzoom']}, elevation {elevation['min']:.1f}..{elevation['max']:.1f} m"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
