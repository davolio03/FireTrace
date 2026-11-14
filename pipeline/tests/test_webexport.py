"""Shared web display export: EPSG:3857 warp, corners, colour ramps and PNG writing.

Small synthetic rasters only; display products are never used for measurement.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import rasterio
from affine import Affine
from rasterio.crs import CRS
from rasterio.warp import transform as warp_transform

from pipeline import webexport
from pipeline.webexport import WebExportError, colorize, grayscale, warp_to_web, write_png

UTM10N = CRS.from_epsg(32610)
TRANSFORM = Affine(10.0, 0.0, 600_000.0, 0.0, -10.0, 3_970_000.0)
STOPS = [(0.0, "#000000"), (10.0, "#ff0000"), (20.0, "#ffffff")]


def test_colorize_hits_stops_interpolates_and_clamps():
    data = np.array([[0.0, 10.0, 20.0, 5.0, -3.0, 99.0, np.nan]])
    rgba = colorize(data, STOPS)
    assert rgba.dtype == np.uint8 and rgba.shape == (1, 7, 4)
    assert rgba[0, 0].tolist() == [0, 0, 0, 255]
    assert rgba[0, 1].tolist() == [255, 0, 0, 255]
    assert rgba[0, 2].tolist() == [255, 255, 255, 255]
    assert rgba[0, 3].tolist() == [128, 0, 0, 255]  # halfway 0 -> 255 rounds to 128
    assert rgba[0, 4].tolist() == [0, 0, 0, 255]  # below the domain clamps to the first stop
    assert rgba[0, 5].tolist() == [255, 255, 255, 255]  # above clamps to the last stop
    assert rgba[0, 6].tolist() == [0, 0, 0, 0]  # invalid -> transparent


def test_colorize_rejects_unsorted_or_bad_stops():
    with pytest.raises(WebExportError):
        colorize(np.zeros((1, 1)), [(10.0, "#000000"), (0.0, "#ffffff")])
    with pytest.raises(WebExportError):
        colorize(np.zeros((1, 1)), [(0.0, "#000000"), (1.0, "red")])
    with pytest.raises(WebExportError):
        colorize(np.zeros((1, 1)), [(0.0, "#000000")])


def test_grayscale_scales_and_masks():
    rgba = grayscale(np.array([[0.0, 0.5, 1.0, np.nan, 2.0]]))
    assert rgba[0, :, 0].tolist() == [0, 128, 255, 0, 255]
    assert (rgba[0, :3, 0] == rgba[0, :3, 1]).all() and (rgba[0, :3, 1] == rgba[0, :3, 2]).all()
    assert rgba[0, :, 3].tolist() == [255, 255, 255, 0, 255]


def test_warp_to_web_covers_the_source_footprint():
    data = np.arange(50 * 60, dtype=np.float64).reshape(50, 60)
    data[0, 0] = np.nan
    web = warp_to_web(data, src_transform=TRANSFORM, src_crs=UTM10N, resampling="bilinear")
    assert web.data.shape == (web.height, web.width)
    tl, tr, br, bl = web.coordinates
    assert tl[1] == tr[1] and bl[1] == br[1] and tl[0] == bl[0] and tr[0] == br[0]
    assert tl[0] < tr[0] and bl[1] < tl[1]
    # Every source corner lies inside the published geographic rectangle.
    xs = [600_000.0, 600_600.0, 600_600.0, 600_000.0]
    ys = [3_970_000.0, 3_970_000.0, 3_969_500.0, 3_969_500.0]
    lons, lats = warp_transform(UTM10N, CRS.from_epsg(4326), xs, ys)
    eps = 1e-9
    assert all(tl[0] - eps <= lon <= tr[0] + eps for lon in lons)
    assert all(bl[1] - eps <= lat <= tl[1] + eps for lat in lats)
    # Values stay within the source range; outside the footprint is NaN.
    assert np.nanmin(web.data) >= 0.0 and np.nanmax(web.data) <= data[~np.isnan(data)].max()
    assert np.isnan(web.data).any()


def test_warp_to_web_rejects_unknown_resampling():
    with pytest.raises(WebExportError):
        warp_to_web(np.zeros((4, 4)), src_transform=TRANSFORM, src_crs=UTM10N, resampling="cubic")


def test_write_png_round_trips_and_is_deterministic(tmp_path: Path):
    rgba = colorize(np.linspace(0, 20, 12).reshape(3, 4), STOPS)
    a, b = tmp_path / "a.png", tmp_path / "b.png"
    write_png(a, rgba)
    write_png(b, rgba)
    assert a.read_bytes() == b.read_bytes()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.png", "b.png"]  # no sidecars
    with rasterio.open(a) as src:
        assert src.count == 4
        np.testing.assert_array_equal(np.moveaxis(src.read(), 0, -1), rgba)


def test_write_png_rejects_non_rgba(tmp_path: Path):
    with pytest.raises(WebExportError):
        write_png(tmp_path / "x.png", np.zeros((3, 4, 3), dtype=np.uint8))
    with pytest.raises(WebExportError):
        write_png(tmp_path / "x.png", np.zeros((3, 4, 4), dtype=np.float32))


def test_module_exposes_web_crs():
    assert webexport.WEB_CRS == CRS.from_epsg(3857)
