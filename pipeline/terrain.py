"""Terrain context on the analysis grid: elevation, slope, aspect and radar geometry (DT-05).

Terrain is complementary (non-NISAR) context. It helps explain possible radar artefacts
(steep slopes, layover, shadow); it is never evidence of fire, burned area or severity.

This stage never downloads. It verifies the pinned Copernicus GLO-30 DEM tile and the t2
NISAR GCOV ``.h5`` (for its radar-geometry cubes) against their sha256, then writes on the
DT-01 crop grid (10 m EPSG:32610):

- ``elevation.tif``: float32 metres above the EGM2008 geoid, bilinear from the 30 m DEM;
- ``slope.tif``: float32 degrees, Horn 3x3 in metres on the 10 m grid;
- ``aspect.tif``: float32 degrees clockwise from north (downslope direction), NaN on flats;
- ``local_incidence.tif``: float32 degrees between the surface normal and the line of sight;
- ``layover_shadow.tif``: uint8 0 none, 1 layover, 2 shadow, 255 unknown (approximate,
  local range-plane criteria; see ``docs/methods/terrain.md``);
- ``hillshade.png`` and ``slope.png``: EPSG:3857 display PNGs, plus ``terrain_layers.json``
  (a ``layers.schema.json`` document with the two terrain layers that DT-04 merges);
- ``terrain.json``: provenance, method, grid, statistics and checksums.

Run from the repository root::

    uv run python -m pipeline.terrain --config pipeline/configs/terrain_plaskett.toml
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
import tomllib
import warnings
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from affine import Affine
from rasterio.crs import CRS
from rasterio.errors import NotGeoreferencedWarning, RasterioError
from rasterio.warp import Resampling, reproject
from rasterio.warp import transform as warp_transform
from rasterio.windows import Window

from pipeline.perimeter import PerimeterError, load_crop_grid
from pipeline.sar import (
    ANALYSIS_CRS,
    ANALYSIS_PIXEL_SIZE_M,
    SarError,
    _staging_dirs,
    publish,
    sha256_file,
    write_cog,
)
from pipeline.webexport import WebExportError, colorize, grayscale, warp_to_web, write_png

TERRAIN_FORMAT_VERSION = 1
CONTRACT_VERSION = "1.2.0"
NONE, LAYOVER, SHADOW, UNKNOWN = 0, 1, 2, 255
FLOAT_OUTPUTS = ("elevation.tif", "slope.tif", "aspect.tif", "local_incidence.tif")
OUTPUT_FILES: frozenset[str] = frozenset(
    {
        *FLOAT_OUTPUTS,
        "layover_shadow.tif",
        "hillshade.png",
        "slope.png",
        "terrain_layers.json",
        "terrain.json",
    }
)
# Sequential, colourblind-safe ramp; same stops as the contract fixture slope layer.
SLOPE_STOPS: tuple[tuple[float, str], ...] = (
    (0.0, "#ffffd4"),
    (11.25, "#fed98e"),
    (22.5, "#fe9929"),
    (33.75, "#d95f0e"),
    (45.0, "#993404"),
)
RADAR_GRID = "//science/LSAR/GCOV/metadata/radarGrid/"
CUBE_MARGIN_M = 1000.0
LONLAT = CRS.from_epsg(4326)
EPSG_TAG = "science_LSAR_GCOV_metadata_radarGrid_projection_epsg_code"


class TerrainError(Exception):
    """Raised for any condition that prevents faithful terrain products."""


# --------------------------------------------------------------------------- config


@dataclass(frozen=True)
class DemSource:
    raw: Path
    sha256: str
    product_id: str
    url: str
    source_label: str
    source_url: str
    vertical_datum: str


@dataclass(frozen=True)
class GeometrySource:
    h5: Path
    sha256: str
    epoch: str


@dataclass(frozen=True)
class TerrainConfig:
    dem: DemSource
    geometry: GeometrySource
    ingest_dir: Path
    output_dir: Path
    margin_m: float
    hillshade_azimuth_deg: float
    hillshade_altitude_deg: float


def _require(table: Mapping[str, Any], key: str, kind: type, where: str = "") -> Any:
    if key not in table:
        raise TerrainError(f"config: missing '{where}{key}'")
    value = table[key]
    if kind is float and isinstance(value, int) and not isinstance(value, bool):
        value = float(value)
    if not isinstance(value, kind) or (isinstance(value, bool) and kind is not bool):
        raise TerrainError(f"config: '{where}{key}' must be {kind.__name__}, got {value!r}")
    return value


def _sha(table: Mapping[str, Any], where: str) -> str:
    value = _require(table, "sha256", str, where)
    if len(value) != 64 or any(c not in "0123456789abcdefABCDEF" for c in value):
        raise TerrainError(f"config: '{where}sha256' must be a 64-character hex digest")
    return value.lower()


def load_config(path: Path, base_dir: Path | None = None) -> TerrainConfig:
    """Parse the TOML configuration; relative paths resolve against ``base_dir`` (cwd)."""
    base = Path.cwd() if base_dir is None else base_dir
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise TerrainError(f"config: cannot read {path.name}: {exc}") from exc

    def resolve(value: str) -> Path:
        p = Path(value)
        return p if p.is_absolute() else base / p

    dem = _require(raw, "dem", dict)
    geom = _require(raw, "geometry", dict)
    margin = _require(raw, "margin_m", float)
    if (
        not math.isfinite(margin)
        or margin < ANALYSIS_PIXEL_SIZE_M
        or (margin % ANALYSIS_PIXEL_SIZE_M)
    ):
        raise TerrainError(
            f"config: 'margin_m' must be a positive multiple of {ANALYSIS_PIXEL_SIZE_M} m "
            f"(at least one pixel for the Horn window), got {margin}"
        )
    azimuth = _require(raw, "hillshade_azimuth_deg", float)
    altitude = _require(raw, "hillshade_altitude_deg", float)
    if not (0.0 <= azimuth < 360.0 and 0.0 < altitude <= 90.0):
        raise TerrainError("config: hillshade azimuth must be in [0, 360) and altitude in (0, 90]")
    epoch = _require(geom, "epoch", str, "geometry.")
    if epoch not in ("t1", "t2"):
        raise TerrainError(f"config: 'geometry.epoch' must be t1 or t2, got {epoch!r}")
    return TerrainConfig(
        dem=DemSource(
            raw=resolve(_require(dem, "raw", str, "dem.")),
            sha256=_sha(dem, "dem."),
            product_id=_require(dem, "product_id", str, "dem."),
            url=_require(dem, "url", str, "dem."),
            source_label=_require(dem, "source_label", str, "dem."),
            source_url=_require(dem, "source_url", str, "dem."),
            vertical_datum=_require(dem, "vertical_datum", str, "dem."),
        ),
        geometry=GeometrySource(
            h5=resolve(_require(geom, "h5", str, "geometry.")),
            sha256=_sha(geom, "geometry."),
            epoch=epoch,
        ),
        ingest_dir=resolve(_require(raw, "ingest_dir", str)),
        output_dir=resolve(_require(raw, "output_dir", str)),
        margin_m=margin,
        hillshade_azimuth_deg=azimuth,
        hillshade_altitude_deg=altitude,
    )


# --------------------------------------------------------------------------- derivatives


def horn_gradient(z: np.ndarray, pixel_m: float) -> tuple[np.ndarray, np.ndarray]:
    """Horn (1981) 3x3 gradient: ``p`` = dz/dx (east), ``q`` = dz/dy (north), per metre.

    Row 0 is north. The one-pixel border, and any pixel whose 3x3 window (centre included)
    holds no-data, is NaN.
    """
    z = np.asarray(z, dtype=np.float64)
    p = np.full(z.shape, np.nan)
    q = np.full(z.shape, np.nan)
    if min(z.shape) < 3:
        return p, q
    a, b, c = z[:-2, :-2], z[:-2, 1:-1], z[:-2, 2:]
    d, e, f = z[1:-1, :-2], z[1:-1, 1:-1], z[1:-1, 2:]
    g, h, i = z[2:, :-2], z[2:, 1:-1], z[2:, 2:]
    inner_p = ((c + 2 * f + i) - (a + 2 * d + g)) / (8 * pixel_m)
    inner_q = ((a + 2 * b + c) - (g + 2 * h + i)) / (8 * pixel_m)
    # p ignores the north/south neighbours and q the east/west ones: invalidate both
    # whenever anything in the 3x3 window is missing.
    bad = ~np.isfinite(e) | ~np.isfinite(inner_p) | ~np.isfinite(inner_q)
    inner_p[bad] = np.nan
    inner_q[bad] = np.nan
    p[1:-1, 1:-1] = inner_p
    q[1:-1, 1:-1] = inner_q
    return p, q


WGS84_A = 6378137.0
WGS84_F = 1 / 298.257223563
NORTH_STEP_M = 10.0


def grid_north_rotation(
    transform: Affine, width: int, height: int
) -> tuple[np.ndarray, np.ndarray]:
    """Per-pixel true bearing of UTM grid north (deg, clockwise) and point scale factor.

    A step of ``NORTH_STEP_M`` grid metres toward grid north is projected to lon/lat; its
    true east/north lengths use the WGS84 meridional and prime-vertical radii. Returns
    ``beta`` (true bearing of grid north) and ``k`` (grid metres per true metre).
    """
    cols, rows = np.meshgrid(np.arange(width) + 0.5, np.arange(height) + 0.5)
    flat_x = (transform.c + cols * transform.a).ravel()
    flat_y = (transform.f + rows * transform.e).ravel()
    lon0, lat0 = warp_transform(ANALYSIS_CRS, LONLAT, flat_x, flat_y)
    lon1, lat1 = warp_transform(ANALYSIS_CRS, LONLAT, flat_x, flat_y + NORTH_STEP_M)
    lon0, lat0, lon1, lat1 = (np.asarray(v, dtype=np.float64) for v in (lon0, lat0, lon1, lat1))
    phi = np.radians(lat0)
    e2 = WGS84_F * (2 - WGS84_F)
    w = np.sqrt(1 - e2 * np.sin(phi) ** 2)
    meridional = WGS84_A * (1 - e2) / w**3
    prime_vertical = WGS84_A / w
    d_north = meridional * np.radians(lat1 - lat0)
    d_east = prime_vertical * np.cos(phi) * np.radians(lon1 - lon0)
    beta = np.degrees(np.arctan2(d_east, d_north)).reshape(height, width)
    k = (NORTH_STEP_M / np.hypot(d_east, d_north)).reshape(height, width)
    return beta, k


def to_true_gradient(
    p: np.ndarray, q: np.ndarray, beta_deg: np.ndarray, k: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Grid-axis gradients (per grid metre) to true east/north gradients (per true metre)."""
    b = np.radians(beta_deg)
    cos_b, sin_b = np.cos(b), np.sin(b)
    return k * (p * cos_b + q * sin_b), k * (-p * sin_b + q * cos_b)


def slope_deg(p: np.ndarray, q: np.ndarray) -> np.ndarray:
    """Slope in degrees (0 flat, 90 vertical)."""
    return np.degrees(np.arctan(np.hypot(p, q)))


def aspect_deg(p: np.ndarray, q: np.ndarray) -> np.ndarray:
    """Downslope direction in degrees clockwise from north, in [0, 360); NaN where flat."""
    with np.errstate(invalid="ignore"):
        aspect = np.degrees(np.arctan2(-p, -q)) % 360.0
    aspect = np.where(aspect >= 360.0, 0.0, aspect)
    return np.where((p == 0) & (q == 0), np.nan, aspect)


def aspect_float32(aspect: np.ndarray) -> np.ndarray:
    """float32 aspect kept in [0, 360): values that round up to 360 wrap to 0."""
    out = np.asarray(aspect, dtype=np.float32).copy()
    out[out >= np.float32(360.0)] = np.float32(0.0)
    return out


def hillshade(
    slope: np.ndarray, aspect: np.ndarray, *, azimuth_deg: float, altitude_deg: float
) -> np.ndarray:
    """Lambertian shaded relief in [0, 1] for a sun at ``azimuth_deg``/``altitude_deg``."""
    zenith = math.radians(90.0 - altitude_deg)
    s = np.radians(slope)
    asp = np.where(np.isnan(aspect) & (slope == 0), 0.0, aspect)
    shade = math.cos(zenith) * np.cos(s) + math.sin(zenith) * np.sin(s) * np.cos(
        np.radians(azimuth_deg - asp)
    )
    with np.errstate(invalid="ignore"):
        return np.where(np.isnan(shade), np.nan, np.clip(shade, 0.0, 1.0))


# --------------------------------------------------------------------------- radar geometry


@dataclass(frozen=True)
class RadarGrid:
    """NISAR GCOV radarGrid cubes (heights, rows, cols) on a coarse EPSG:32610 grid."""

    xs: np.ndarray
    ys: np.ndarray
    heights: np.ndarray
    incidence_deg: np.ndarray
    los_east: np.ndarray
    los_north: np.ndarray


def _bracket(coords: np.ndarray, values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Lower index and fraction of ``values`` on increasing ``coords``."""
    idx = np.clip(np.searchsorted(coords, values, side="right") - 1, 0, coords.size - 2)
    frac = (values - coords[idx]) / (coords[idx + 1] - coords[idx])
    return idx, frac


def interpolate_cube(
    cube: np.ndarray,
    xs: np.ndarray,
    ys: np.ndarray,
    heights: np.ndarray,
    px: np.ndarray,
    py: np.ndarray,
    z: np.ndarray,
) -> np.ndarray:
    """Bilinear in x/y and linear in height, at pixel centres ``px`` (cols), ``py`` (rows).

    ``z`` (rows, cols) gives the height of each pixel; NaN heights give NaN.
    """
    xs, ys, heights = (np.asarray(v, dtype=np.float64) for v in (xs, ys, heights))
    cube = np.asarray(cube, dtype=np.float64)
    if ys.size > 1 and ys[0] > ys[-1]:
        ys, cube = ys[::-1], cube[:, ::-1, :]
    for name, coords in (("x", xs), ("y", ys), ("height", heights)):
        if coords.size < 2 or not (np.diff(coords) > 0).all():
            raise TerrainError(f"radar grid {name} coordinates must be strictly monotonic")
    if cube.shape != (heights.size, ys.size, xs.size):
        raise TerrainError("radar grid cube shape does not match its coordinates")
    if px.min() < xs[0] or px.max() > xs[-1] or py.min() < ys[0] or py.max() > ys[-1]:
        raise TerrainError("the crop extends beyond the radar grid footprint")
    finite = np.isfinite(z)
    if finite.any() and (z[finite].min() < heights[0] or z[finite].max() > heights[-1]):
        raise TerrainError(
            f"terrain height range [{z[finite].min():.1f}, {z[finite].max():.1f}] m is outside "
            f"the radar grid heights [{heights[0]}, {heights[-1]}] m"
        )
    ix, fx = _bracket(xs, px)
    iy, fy = _bracket(ys, py)
    zz = np.where(finite, z, heights[0])
    iz, fz = _bracket(heights, zz)
    fx2, fy2 = fx[None, :], fy[:, None]
    r0, c0 = iy[:, None], ix[None, :]
    out = np.zeros(z.shape, dtype=np.float64)
    for k in range(int(iz.min()), int(iz.max()) + 2):
        level = cube[k]
        v = _weighted_sum(
            [
                ((1 - fy2) * (1 - fx2), level[r0, c0]),
                ((1 - fy2) * fx2, level[r0, c0 + 1]),
                (fy2 * (1 - fx2), level[r0 + 1, c0]),
                (fy2 * fx2, level[r0 + 1, c0 + 1]),
            ]
        )
        weight = np.where(iz == k, 1 - fz, 0.0) + np.where(iz + 1 == k, fz, 0.0)
        out = out + _weighted_sum([(weight, v)])
    return np.where(finite, out, np.nan)


def _weighted_sum(terms: Sequence[tuple[np.ndarray, np.ndarray]]) -> np.ndarray:
    """Sum of ``weight * value`` skipping zero-weight terms, so a missing sample only
    yields NaN when it actually contributes."""
    total: np.ndarray | float = 0.0
    for weight, value in terms:
        with np.errstate(invalid="ignore"):
            total = total + np.where(weight > 0, weight * value, 0.0)
    return np.asarray(total, dtype=np.float64)


def _look_vector(
    incidence: np.ndarray, los_east: np.ndarray, los_north: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Unit horizontal direction to the sensor and the target-to-sensor unit vector."""
    with np.errstate(invalid="ignore", divide="ignore"):
        norm = np.hypot(los_east, los_north)
        he, hn = los_east / norm, los_north / norm
    theta = np.radians(incidence)
    return he, hn, np.sin(theta) * he, np.sin(theta) * hn, np.cos(theta)


def local_incidence_deg(
    p: np.ndarray,
    q: np.ndarray,
    incidence: np.ndarray,
    los_east: np.ndarray,
    los_north: np.ndarray,
) -> np.ndarray:
    """Angle between the terrain normal and the target-to-sensor line of sight (0-180 deg)."""
    _, _, sx, sy, sz = _look_vector(incidence, los_east, los_north)
    with np.errstate(invalid="ignore"):
        cos_local = (-p * sx - q * sy + sz) / np.sqrt(1.0 + p * p + q * q)
        return np.degrees(np.arccos(np.clip(cos_local, -1.0, 1.0)))


def layover_shadow(
    p: np.ndarray,
    q: np.ndarray,
    incidence: np.ndarray,
    los_east: np.ndarray,
    los_north: np.ndarray,
) -> np.ndarray:
    """Approximate local flags from the range-plane local incidence ``theta + atan(g)``.

    ``g`` is the terrain rise per metre toward the sensor. Layover where the range-plane
    local incidence is < 0 (foreslope steeper than the incidence angle); shadow where it is
    > 90 deg (backslope steeper than 90 - incidence). Distant ridges are not modelled.
    """
    he, hn, _, _, _ = _look_vector(incidence, los_east, los_north)
    with np.errstate(invalid="ignore"):
        g = p * he + q * hn
        local_range = incidence + np.degrees(np.arctan(g))
        flags = np.full(p.shape, NONE, dtype=np.uint8)
        flags[local_range < 0.0] = LAYOVER
        flags[local_range > 90.0] = SHADOW
    flags[~np.isfinite(local_range)] = UNKNOWN
    return flags


def _read_hdf(h5: Path, name: str, window: Window | None = None) -> np.ndarray:
    """One radarGrid dataset as (bands, rows, cols) float64 via the GDAL HDF5 driver."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", NotGeoreferencedWarning)
            with rasterio.open(f'HDF5:"{h5.as_posix()}":{RADAR_GRID}{name}') as src:
                return src.read(window=window).astype(np.float64)
    except (RasterioError, OSError) as exc:
        raise TerrainError(f"{h5.name}: cannot read radarGrid/{name}: {exc}") from exc


def _hdf_epsg(h5: Path) -> str | None:
    """EPSG code of the radarGrid cubes, from the file-level attributes."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", NotGeoreferencedWarning)
            with rasterio.open(h5) as src:
                return src.tags().get(EPSG_TAG)
    except (RasterioError, OSError) as exc:
        raise TerrainError(f"{h5.name}: cannot read the file attributes: {exc}") from exc


def cube_window(
    xs: np.ndarray, ys: np.ndarray, bounds: tuple[float, float, float, float], margin_m: float
) -> Window:
    """Smallest window of cube nodes covering ``bounds`` expanded by ``margin_m``."""
    left, bottom, right, top = bounds
    cols = np.nonzero((xs >= left - margin_m) & (xs <= right + margin_m))[0]
    rows = np.nonzero((ys >= bottom - margin_m) & (ys <= top + margin_m))[0]
    if cols.size < 2 or rows.size < 2:
        raise TerrainError("the radar grid does not cover the crop")
    return Window(
        int(cols[0]), int(rows[0]), int(cols[-1] - cols[0] + 1), int(rows[-1] - rows[0] + 1)
    )


def read_radar_grid(h5: Path, bounds: tuple[float, float, float, float]) -> RadarGrid:
    """Read the radarGrid cubes around ``bounds`` (EPSG:32610) from a NISAR GCOV .h5."""
    epsg = _hdf_epsg(h5)
    if epsg is None or int(float(epsg)) != ANALYSIS_CRS.to_epsg():
        raise TerrainError(f"{h5.name}: radar grid EPSG {epsg} is not {ANALYSIS_CRS.to_epsg()}")
    xs = _read_hdf(h5, "xCoordinates").ravel()
    ys = _read_hdf(h5, "yCoordinates").ravel()
    heights = _read_hdf(h5, "heightAboveEllipsoid").ravel()
    window = cube_window(xs, ys, bounds, CUBE_MARGIN_M)
    cubes = {}
    for name in ("incidenceAngle", "losUnitVectorX", "losUnitVectorY"):
        cube = _read_hdf(h5, name, window)
        expected = (heights.size, int(window.height), int(window.width))
        if cube.shape != expected:
            raise TerrainError(f"{h5.name}: {name} has shape {cube.shape}, expected {expected}")
        cubes[name] = cube
    c0, r0 = int(window.col_off), int(window.row_off)
    return RadarGrid(
        xs=xs[c0 : c0 + int(window.width)],
        ys=ys[r0 : r0 + int(window.height)],
        heights=heights,
        incidence_deg=cubes["incidenceAngle"],
        los_east=cubes["losUnitVectorX"],
        los_north=cubes["losUnitVectorY"],
    )


# --------------------------------------------------------------------------- inputs


def _verify(path: Path, expected: str, what: str) -> None:
    if not path.is_file():
        raise TerrainError(f"{what} not found: {path.name}")
    try:
        actual = sha256_file(path)
    except SarError as exc:
        raise TerrainError(str(exc)) from exc
    if actual != expected:
        raise TerrainError(
            f"{path.name}: sha256 {actual[:12]}... differs from the pinned {expected[:12]}...; "
            "review the file before updating the pin"
        )


def load_ingest(ingest_dir: Path) -> tuple[dict[str, Any], Affine, int, int]:
    try:
        transform, width, height = load_crop_grid(ingest_dir)
    except PerimeterError as exc:
        raise TerrainError(str(exc)) from exc
    doc = json.loads((ingest_dir / "ingest.json").read_text(encoding="utf-8"))
    return doc, transform, width, height


def check_granule(h5: Path, ingest: Mapping[str, Any], epoch: str) -> None:
    """The geometry granule name must carry the ingest track/direction/frame and epoch time."""
    try:
        acq = ingest["acquisition"]
        direction = str(acq["direction"])[0].upper()
        token = f"_{int(acq['track']):03d}_{direction}_{int(acq['frame']):03d}_"
        when = str(ingest["epochs"][epoch]["datetime"]).replace("-", "").replace(":", "")
        when = when.rstrip("Z")
    except (KeyError, TypeError, ValueError) as exc:
        raise TerrainError(f"ingest.json lacks acquisition/epoch metadata: {exc}") from exc
    if token not in h5.name:
        raise TerrainError(f"{h5.name}: track/direction/frame do not match the ingest ({token})")
    if when not in h5.name:
        raise TerrainError(f"{h5.name}: start time does not match the ingest {epoch} ({when})")


def warp_dem(dem: Path, transform: Affine, width: int, height: int) -> tuple[np.ndarray, dict]:
    """DEM resampled bilinearly onto the given EPSG:32610 grid; it must cover it fully."""
    out = np.full((height, width), np.nan, dtype=np.float64)
    try:
        with rasterio.open(dem) as src:
            if src.crs is None or src.count != 1:
                raise TerrainError(f"{dem.name}: expected a single-band georeferenced DEM")
            info = {
                "crs": src.crs.to_string(),
                "width": src.width,
                "height": src.height,
                "transform": [float(v) for v in tuple(src.transform)[:6]],
                "nodata": src.nodata,
                "area_or_point": src.tags().get("AREA_OR_POINT"),
            }
            reproject(
                source=rasterio.band(src, 1),
                destination=out,
                src_nodata=src.nodata,
                dst_transform=transform,
                dst_crs=ANALYSIS_CRS,
                dst_nodata=np.nan,
                resampling=Resampling.bilinear,
            )
    except (RasterioError, OSError) as exc:
        raise TerrainError(f"{dem.name}: cannot read or warp the DEM: {exc}") from exc
    missing = int((~np.isfinite(out)).sum())
    if missing:
        raise TerrainError(
            f"{dem.name}: the DEM does not cover the crop plus margin ({missing} pixels missing)"
        )
    return out, info


# --------------------------------------------------------------------------- products


def _summary(data: np.ndarray) -> dict[str, Any]:
    values = data[np.isfinite(data)]
    if values.size == 0:
        return {"valid": 0, "min": None, "median": None, "max": None}
    return {
        "valid": int(values.size),
        "min": float(values.min()),
        "median": float(np.median(values)),
        "max": float(values.max()),
    }


def _write_json(path: Path, document: Mapping[str, Any]) -> None:
    text = json.dumps(document, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False)
    path.write_text(text + "\n", encoding="utf-8", newline="\n")


def check_output_dir(output_dir: Path) -> None:
    if output_dir.exists():
        if not output_dir.is_dir():
            raise TerrainError(f"output_dir {output_dir.name} is not a directory")
        foreign = sorted(p.name for p in output_dir.iterdir() if p.name not in OUTPUT_FILES)
        if foreign:
            raise TerrainError(
                f"output_dir {output_dir.name} holds files this stage does not own: {foreign}"
            )


def layer_entries(config: TerrainConfig, web: Mapping[str, Any]) -> list[dict[str, Any]]:
    source = {
        "label": config.dem.source_label,
        "url": config.dem.source_url,
        "product_id": config.dem.product_id,
    }
    az, alt = config.hillshade_azimuth_deg, config.hillshade_altitude_deg
    common = {"kind": "raster", "group": "terrain", "default_visible": False, "source": source}
    return [
        {
            **common,
            "id": "hillshade",
            "title": "Terrain relief (hillshade)",
            "url": "layers/hillshade.png",
            "default_opacity": 0.5,
            **web["hillshade"],
            "legend": {
                "type": "rgb",
                "note": (
                    f"Shaded relief from the DEM, sun at {az:g}° azimuth / {alt:g}° "
                    "altitude. Display only."
                ),
            },
        },
        {
            **common,
            "id": "slope",
            "title": "Terrain slope",
            "url": "layers/slope.png",
            "default_opacity": 0.8,
            **web["slope"],
            "legend": {
                "type": "continuous",
                "units": "degrees",
                "domain": [SLOPE_STOPS[0][0], SLOPE_STOPS[-1][0]],
                "stops": [{"value": v, "color": c} for v, c in SLOPE_STOPS],
                "note": (
                    "Slope from a 30 m DEM resampled to the 10 m analysis grid; values above "
                    f"{SLOPE_STOPS[-1][0]:g}° share the last colour."
                ),
            },
        },
    ]


# --------------------------------------------------------------------------- run


def run_terrain(config: TerrainConfig) -> dict[str, Any]:
    """Build the terrain products and return the ``terrain.json`` document written."""
    protected = {
        config.ingest_dir.resolve(),
        config.dem.raw.parent.resolve(),
        config.geometry.h5.parent.resolve(),
    }
    if config.output_dir.resolve() in protected:
        raise TerrainError("output_dir must differ from the ingest and raw input directories")
    check_output_dir(config.output_dir)
    ingest, transform, width, height = load_ingest(config.ingest_dir)
    _verify(config.dem.raw, config.dem.sha256, "DEM")
    _verify(config.geometry.h5, config.geometry.sha256, "radar geometry granule")
    check_granule(config.geometry.h5, ingest, config.geometry.epoch)

    m = int(round(config.margin_m / ANALYSIS_PIXEL_SIZE_M))
    margin_transform = transform * Affine.translation(-m, -m)
    dem_m, dem_info = warp_dem(config.dem.raw, margin_transform, width + 2 * m, height + 2 * m)
    p_m, q_m = horn_gradient(dem_m, ANALYSIS_PIXEL_SIZE_M)
    crop = (slice(m, m + height), slice(m, m + width))
    elevation = dem_m[crop]
    beta, scale = grid_north_rotation(transform, width, height)
    p, q = to_true_gradient(p_m[crop], q_m[crop], beta, scale)
    slope = slope_deg(p, q)
    aspect = aspect_deg(p, q)
    shade = hillshade(
        slope,
        aspect,
        azimuth_deg=config.hillshade_azimuth_deg,
        altitude_deg=config.hillshade_altitude_deg,
    )

    left, top = transform.c, transform.f
    bounds = (left, top - height * ANALYSIS_PIXEL_SIZE_M, left + width * ANALYSIS_PIXEL_SIZE_M, top)
    grid = read_radar_grid(config.geometry.h5, bounds)
    px = left + (np.arange(width) + 0.5) * ANALYSIS_PIXEL_SIZE_M
    py = top - (np.arange(height) + 0.5) * ANALYSIS_PIXEL_SIZE_M
    cube = {
        name: interpolate_cube(values, grid.xs, grid.ys, grid.heights, px, py, elevation)
        for name, values in (
            ("incidence", grid.incidence_deg),
            ("east", grid.los_east),
            ("north", grid.los_north),
        )
    }
    local = local_incidence_deg(p, q, cube["incidence"], cube["east"], cube["north"])
    flags = layover_shadow(p, q, cube["incidence"], cube["east"], cube["north"])

    floats = {
        "elevation.tif": elevation.astype(np.float32),
        "slope.tif": slope.astype(np.float32),
        "aspect.tif": aspect_float32(aspect),
        "local_incidence.tif": local.astype(np.float32),
    }
    staging, _ = _staging_dirs(config.output_dir)
    try:
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True)
        for name, data in floats.items():
            write_cog(staging / name, data, crs=ANALYSIS_CRS, transform=transform, nodata=np.nan)
        write_cog(
            staging / "layover_shadow.tif",
            flags,
            crs=ANALYSIS_CRS,
            transform=transform,
            nodata=UNKNOWN,
        )
        web: dict[str, Any] = {}
        for lid, data, render in (
            ("hillshade", shade, grayscale),
            ("slope", slope, lambda d: colorize(d, SLOPE_STOPS)),
        ):
            warped = warp_to_web(
                data, src_transform=transform, src_crs=ANALYSIS_CRS, resampling="bilinear"
            )
            write_png(staging / f"{lid}.png", render(warped.data))
            web[lid] = {
                "coordinates": warped.coordinates,
                "width_px": warped.width,
                "height_px": warped.height,
            }
        _write_json(
            staging / "terrain_layers.json",
            {
                "contract_version": CONTRACT_VERSION,
                "data_status": "real",
                "layers": layer_entries(config, web),
            },
        )
        counts = {
            "none": int((flags == NONE).sum()),
            "layover": int((flags == LAYOVER).sum()),
            "shadow": int((flags == SHADOW).sum()),
            "unknown": int((flags == UNKNOWN).sum()),
        }
        total = int(flags.size)
        document: dict[str, Any] = {
            "terrain_format_version": TERRAIN_FORMAT_VERSION,
            "note": (
                "Complementary terrain context, not NISAR and not evidence of fire. "
                "Layover/shadow flags are approximate local criteria."
            ),
            "dem": {
                "file": config.dem.raw.name,
                "sha256": config.dem.sha256,
                "product_id": config.dem.product_id,
                "url": config.dem.url,
                "source_label": config.dem.source_label,
                "source_url": config.dem.source_url,
                "vertical_datum": config.dem.vertical_datum,
                "surface_model": "DSM (includes canopy and structures at DEM acquisition time)",
                "native": dem_info,
            },
            "geometry": {
                "file": config.geometry.h5.name,
                "sha256": config.geometry.sha256,
                "epoch": config.geometry.epoch,
                "cubes": ["incidenceAngle", "losUnitVectorX", "losUnitVectorY"],
                "cube_spacing_m": [
                    float(abs(grid.xs[1] - grid.xs[0])),
                    float(abs(grid.ys[1] - grid.ys[0])),
                ],
                "assumption": (
                    "Both epochs share track/frame/direction; the geometry of this epoch is "
                    "used for both. Cube heights are ellipsoidal and are sampled with the "
                    "DEM's geoid heights (the geoid-ellipsoid offset is neglected)."
                ),
            },
            "ingest": {"sha256": sha256_file(config.ingest_dir / "ingest.json")},
            "grid": {
                "crs": ANALYSIS_CRS.to_string(),
                "transform": [float(v) for v in tuple(transform)[:6]],
                "width": width,
                "height": height,
            },
            "method": {
                "resampling": "bilinear (DEM to the 10 m crop grid)",
                "margin_m": config.margin_m,
                "effective_resolution_m": 30.0,
                "slope": (
                    "Horn 3x3 on the 10 m grid; gradients rotated from UTM grid axes to true "
                    "east/north and scaled to true metres; degrees 0-90"
                ),
                "aspect": "downslope direction, degrees clockwise from true north; NaN where flat",
                "grid_convergence_deg": _summary(beta),
                "point_scale_factor": _summary(scale),
                "hillshade": {
                    "azimuth_deg": config.hillshade_azimuth_deg,
                    "altitude_deg": config.hillshade_altitude_deg,
                    "use": "display only",
                },
                "local_incidence": (
                    "angle between the terrain normal and the target-to-sensor line of sight"
                ),
                "layover_shadow": {
                    "values": {"0": "none", "1": "layover", "2": "shadow", "255": "unknown"},
                    "rule": (
                        "range-plane local incidence = incidence + atan(rise toward sensor); "
                        "< 0 deg layover, > 90 deg shadow; local only (distant ridges are not "
                        "modelled)"
                    ),
                },
            },
            "layers": {name.removesuffix(".tif"): _summary(data) for name, data in floats.items()},
            "incidence_deg": _summary(cube["incidence"]),
            "layover_shadow": {
                **counts,
                "layover_pct": round(100.0 * counts["layover"] / total, 4),
                "shadow_pct": round(100.0 * counts["shadow"] / total, 4),
            },
            "web": web,
            "outputs": {
                name: {"file": name, "sha256": sha256_file(staging / name)}
                for name in sorted(OUTPUT_FILES - {"terrain.json"})
            },
        }
        _write_json(staging / "terrain.json", document)
        publish(staging, config.output_dir)
    except (SarError, WebExportError) as exc:
        raise TerrainError(str(exc)) from exc
    except OSError as exc:
        raise TerrainError(f"cannot write outputs: {exc}") from exc
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
    return document


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m pipeline.terrain",
        description="Build terrain context (elevation, slope, aspect, radar geometry) layers.",
    )
    parser.add_argument("--config", type=Path, required=True, help="TOML terrain config")
    args = parser.parse_args(argv)
    try:
        doc = run_terrain(load_config(args.config))
    except TerrainError as exc:
        print(f"terrain error: {exc}", file=sys.stderr)
        return 2
    s, e, ls = doc["layers"]["slope"], doc["layers"]["elevation"], doc["layover_shadow"]
    print(
        f"terrain ok: elevation {e['min']:.1f}..{e['max']:.1f} m, slope median "
        f"{s['median']:.1f} deg (max {s['max']:.1f}), layover {ls['layover_pct']}%, "
        f"shadow {ls['shadow_pct']}%"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
