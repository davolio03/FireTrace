"""Shared display export for web layers: EPSG:3857 warp, corners, colour ramps, PNG.

Display PNGs are for viewing only. They are warped from the 10 m EPSG:32610 analysis grid
to EPSG:3857 and placed with four EPSG:4326 corners (MapLibre ``image`` source, as in
``contracts/schemas/layers.schema.json``). Nothing is ever measured from these pixels.

DT-05 introduced this module for the terrain layers; DT-04 reuses it for the SAR layers so
all PNGs share one warp and corner convention.
"""

from __future__ import annotations

import math
import re
import warnings
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from affine import Affine
from rasterio.crs import CRS
from rasterio.errors import NotGeoreferencedWarning, RasterioError
from rasterio.io import MemoryFile
from rasterio.warp import Resampling, calculate_default_transform, reproject, transform_bounds
from rasterio.warp import transform as warp_transform

WEB_CRS = CRS.from_epsg(3857)
LONLAT_CRS = CRS.from_epsg(4326)
CORNER_DECIMALS = 8
_RESAMPLING = {"bilinear": Resampling.bilinear, "nearest": Resampling.nearest}
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


class WebExportError(Exception):
    """Raised when a display product cannot be built faithfully."""


@dataclass(frozen=True)
class WebRaster:
    """Float raster on an EPSG:3857 grid; NaN = outside the source or invalid."""

    data: np.ndarray
    transform: Affine
    width: int
    height: int
    coordinates: list[list[float]]  # [top-left, top-right, bottom-right, bottom-left] lon/lat


def corners_lonlat(transform: Affine, width: int, height: int) -> list[list[float]]:
    """Four EPSG:4326 corners of a north-up EPSG:3857 grid, in the contract order."""
    xs = [transform.c, transform.c + width * transform.a]
    ys = [transform.f, transform.f + height * transform.e]
    corners = [(xs[0], ys[0]), (xs[1], ys[0]), (xs[1], ys[1]), (xs[0], ys[1])]
    lons, lats = warp_transform(
        WEB_CRS, LONLAT_CRS, [c[0] for c in corners], [c[1] for c in corners]
    )
    return [
        [round(float(lon), CORNER_DECIMALS), round(float(lat), CORNER_DECIMALS)]
        for lon, lat in zip(lons, lats, strict=True)
    ]


def warp_to_web(
    data: np.ndarray, *, src_transform: Affine, src_crs: CRS, resampling: str
) -> WebRaster:
    """Warp a float raster (NaN = invalid) to EPSG:3857 at the default matching resolution.

    ``bilinear`` suits continuous fields; ``nearest`` suits categorical rasters.
    """
    if resampling not in _RESAMPLING:
        raise WebExportError(f"unsupported resampling {resampling!r}; use {sorted(_RESAMPLING)}")
    if data.ndim != 2:
        raise WebExportError("warp_to_web expects a single 2-D band")
    height, width = data.shape
    left, top = src_transform.c, src_transform.f
    right, bottom = src_transform @ (width, height)
    try:
        # GDAL's suggested resolution, but an extent rounded outwards so the whole source
        # footprint (densified edges) is covered; the default extent can clip an edge.
        suggested, _, _ = calculate_default_transform(
            src_crs, WEB_CRS, width, height, left=left, bottom=bottom, right=right, top=top
        )
        res = abs(suggested.a)
        w_left, w_bottom, w_right, w_top = transform_bounds(
            src_crs, WEB_CRS, left, bottom, right, top, densify_pts=101
        )
        dst_width = math.ceil((w_right - w_left) / res)
        dst_height = math.ceil((w_top - w_bottom) / res)
        dst_transform = Affine(res, 0.0, w_left, 0.0, -res, w_top)
        out = np.full((dst_height, dst_width), np.nan, dtype=np.float64)
        reproject(
            source=np.asarray(data, dtype=np.float64),
            destination=out,
            src_transform=src_transform,
            src_crs=src_crs,
            src_nodata=np.nan,
            dst_transform=dst_transform,
            dst_crs=WEB_CRS,
            dst_nodata=np.nan,
            resampling=_RESAMPLING[resampling],
        )
    except RasterioError as exc:
        raise WebExportError(f"cannot warp to EPSG:3857: {exc}") from exc
    return WebRaster(
        data=out,
        transform=dst_transform,
        width=dst_width,
        height=dst_height,
        coordinates=corners_lonlat(dst_transform, dst_width, dst_height),
    )


def _rgb(color: str) -> tuple[int, int, int]:
    if not isinstance(color, str) or not _HEX.match(color):
        raise WebExportError(f"colour must be #rrggbb, got {color!r}")
    return int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)


def colorize(data: np.ndarray, stops: Sequence[tuple[float, str]]) -> np.ndarray:
    """RGBA uint8 by linear interpolation between ``(value, '#rrggbb')`` stops.

    Values outside the stop range clamp to the end colours; NaN is fully transparent.
    """
    if len(stops) < 2:
        raise WebExportError("a colour ramp needs at least two stops")
    values = np.array([float(v) for v, _ in stops])
    if not (np.diff(values) > 0).all():
        raise WebExportError("colour stops must be strictly increasing")
    colors = np.array([_rgb(c) for _, c in stops], dtype=np.float64)
    valid = np.isfinite(data)
    filled = np.where(valid, data, values[0])
    rgba = np.zeros((*data.shape, 4), dtype=np.uint8)
    for channel in range(3):
        level = np.interp(filled, values, colors[:, channel])
        rgba[..., channel] = np.floor(level + 0.5).astype(np.uint8)
    rgba[..., 3] = np.where(valid, 255, 0).astype(np.uint8)
    rgba[~valid, :3] = 0
    return rgba


def grayscale(data: np.ndarray, lo: float = 0.0, hi: float = 1.0) -> np.ndarray:
    """RGBA uint8 grey ramp from ``lo`` (black) to ``hi`` (white); NaN transparent."""
    return colorize(data, [(lo, "#000000"), (hi, "#ffffff")])


def write_png(path: Path, rgba: np.ndarray) -> None:
    """Write an RGBA uint8 PNG deterministically, with no georeferencing sidecars."""
    if rgba.ndim != 3 or rgba.shape[2] != 4 or rgba.dtype != np.uint8:
        raise WebExportError("write_png expects an (H, W, 4) uint8 RGBA array")
    height, width, _ = rgba.shape
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", NotGeoreferencedWarning)
            with MemoryFile() as mem:
                with mem.open(
                    driver="PNG", width=width, height=height, count=4, dtype="uint8"
                ) as dst:
                    dst.write(np.moveaxis(rgba, -1, 0))
                payload = mem.read()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    except (RasterioError, OSError) as exc:
        raise WebExportError(f"{path.name}: cannot write PNG: {exc}") from exc
