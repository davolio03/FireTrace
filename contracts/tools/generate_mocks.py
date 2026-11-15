# /// script
# requires-python = ">=3.10"
# dependencies = ["numpy>=1.24", "pillow>=10"]
# ///
"""Generate SYNTHETIC fixtures that follow the FireTrace data contract v1.

Everything produced here is fake (data_status = "mock") except the perimeter
geometry, which is the real WFIGS 58728 polygon, simplified. The goal is that the
web and the API can be built before the real pipeline exists.

Usage (from the repo root):
    uv run contracts/tools/generate_mocks.py
    uv run contracts/tools/generate_mocks.py --perimeter-source data/raw/wfigs_58728_raw.geojson

Outputs (all under contracts/fixtures/):
    web/case.json, web/stats.json, web/layers.json, web/perimeter.geojson, web/layers/*.png
    api/stats-with-highlight.json, api/inspect-point-{inside,outside,invalid}.json,
    api/inspect-grid.json   (compact grid used by the web MSW mock to answer any click)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "contracts" / "fixtures"
WEB = FIX / "web"
API = FIX / "api"

CONTRACT_VERSION = "1.2.0"
# AOI = perimeter bbox + ~2 km margin (the real pipeline recomputes it).
AOI = (-121.495, 35.840, -121.278, 35.992)
WIDTH = 480  # mock resolution; real layers are ~10 m/px
METHOD_ID = "abs-logratio-hhhv-v1"
RNG = np.random.default_rng(58728)


# ---------------------------------------------------------------- geometry utils
def merc_y(lat: float) -> float:
    return math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


def inv_merc_y(y: float) -> float:
    return math.degrees(2 * math.atan(math.exp(y)) - math.pi / 2)


def grid_shape() -> tuple[int, int]:
    x_span = math.radians(AOI[2] - AOI[0])
    y_span = merc_y(AOI[3]) - merc_y(AOI[1])
    return round(WIDTH * y_span / x_span), WIDTH


def lonlat_to_px(lon: float, lat: float, h: int, w: int) -> tuple[float, float]:
    col = (lon - AOI[0]) / (AOI[2] - AOI[0]) * w
    row = (merc_y(AOI[3]) - merc_y(lat)) / (merc_y(AOI[3]) - merc_y(AOI[1])) * h
    return col, row


def px_to_lonlat(col: float, row: float, h: int, w: int) -> tuple[float, float]:
    lon = AOI[0] + col / w * (AOI[2] - AOI[0])
    y = merc_y(AOI[3]) - row / h * (merc_y(AOI[3]) - merc_y(AOI[1]))
    return lon, inv_merc_y(y)


def douglas_peucker(pts: list[list[float]], tol: float) -> list[list[float]]:
    if len(pts) < 3:
        return pts
    (x1, y1), (x2, y2) = pts[0][:2], pts[-1][:2]
    dx, dy = x2 - x1, y2 - y1
    norm = math.hypot(dx, dy) or 1e-12
    dmax, idx = 0.0, 0
    for i in range(1, len(pts) - 1):
        d = abs(dy * pts[i][0] - dx * pts[i][1] + x2 * y1 - y2 * x1) / norm
        if d > dmax:
            dmax, idx = d, i
    if dmax <= tol:
        return [pts[0], pts[-1]]
    return douglas_peucker(pts[: idx + 1], tol)[:-1] + douglas_peucker(pts[idx:], tol)


def simplify_perimeter(src: Path, dst: Path, tol: float = 0.0004) -> None:
    raw = json.loads(src.read_text(encoding="utf-8"))
    feat = raw["features"][0]
    polys = []
    for poly in feat["geometry"]["coordinates"]:
        rings = []
        for ring in poly:
            # Closed ring: split at the vertex farthest from the start so DP has a real baseline.
            far = max(range(len(ring)), key=lambda i: (ring[i][0] - ring[0][0]) ** 2 + (ring[i][1] - ring[0][1]) ** 2)
            s = douglas_peucker(ring[: far + 1], tol)[:-1] + douglas_peucker(ring[far:], tol)
            if len(s) >= 4:
                rings.append([[round(x, 6), round(y, 6)] for x, y in s])
        if rings:
            polys.append(rings)
    p = feat["properties"]
    keep = {
        "OBJECTID": p.get("OBJECTID"),
        "IncidentName": p.get("poly_IncidentName"),
        "FeatureCategory": p.get("poly_FeatureCategory"),
        "MapMethod": p.get("poly_MapMethod"),
        "GISAcres": p.get("poly_GISAcres"),
        "PolygonDateTime": datetime.fromtimestamp(p["poly_PolygonDateTime"] / 1000, timezone.utc).isoformat().replace("+00:00", "Z"),
        "Source": "NIFC WFIGS Interagency Perimeters YearToDate",
        "fixture_note": f"Real geometry simplified with Douglas-Peucker tol={tol} deg for fixtures. The pipeline publishes the full geometry.",
    }
    out = {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": keep, "geometry": {"type": "MultiPolygon", "coordinates": polys}}]}
    dst.write_text(json.dumps(out), encoding="utf-8")


# ---------------------------------------------------------------- synthetic fields
def smooth_noise(h: int, w: int, scale: float, amp: float) -> np.ndarray:
    small = RNG.normal(0, 1, (max(2, int(h / scale)), max(2, int(w / scale)))).astype(np.float32)
    img = Image.fromarray(small).resize((w, h), Image.BICUBIC)
    a = np.asarray(img, dtype=np.float32)
    return a / (a.std() + 1e-6) * amp


def perimeter_mask(h: int, w: int) -> np.ndarray:
    gj = json.loads((WEB / "perimeter.geojson").read_text(encoding="utf-8"))
    img = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(img)
    for poly in gj["features"][0]["geometry"]["coordinates"]:
        for i, ring in enumerate(poly):
            draw.polygon([lonlat_to_px(x, y, h, w) for x, y in ring], fill=255 if i == 0 else 0)
    return np.asarray(img) > 0


def build_fields(h: int, w: int) -> dict[str, np.ndarray]:
    inside = perimeter_mask(h, w)
    terrain = smooth_noise(h, w, 40, 2.5)
    # Fire-like effect: patchy, fading toward the edges, a bit outside too.
    effect = np.asarray(Image.fromarray((inside * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(6)), dtype=np.float32) / 255
    effect *= np.clip(0.6 + smooth_noise(h, w, 25, 0.5), 0, 1.3)
    # A non-fire change outside the perimeter (e.g. soil moisture) to show discrepancies.
    yy, xx = np.mgrid[0:h, 0:w]
    moisture = np.exp(-(((xx - 0.85 * w) / (0.07 * w)) ** 2 + ((yy - 0.2 * h) / (0.08 * h)) ** 2)).astype(np.float32)
    # A small non-fire structural change (e.g. a landslide on the coast side), also outside the perimeter.
    moisture += 1.3 * np.exp(-(((xx - 0.12 * w) / (0.025 * w)) ** 2 + ((yy - 0.85 * h) / (0.04 * h)) ** 2)).astype(np.float32)

    def speckle(sd: float) -> np.ndarray:
        return RNG.normal(0, sd, (h, w)).astype(np.float32)

    hh_t1 = -11.0 + terrain + speckle(1.2)
    hv_t1 = -18.0 + 0.8 * terrain + speckle(1.2)
    hh_t2 = hh_t1 - 2.5 * effect + 3.5 * moisture + speckle(1.0)
    hv_t2 = hv_t1 - 4.0 * effect + 2.5 * moisture + speckle(1.0)

    valid = np.ones((h, w), dtype=bool)
    # Fake radar shadow strip + scattered invalid pixels.
    valid[int(0.62 * h) : int(0.66 * h), int(0.05 * w) : int(0.35 * w)] = False
    valid &= RNG.random((h, w)) > 0.002

    # Mock DEM: coast to the west, ridges inland (Big Sur is steep). Slope/aspect/hillshade derived from it.
    elev = np.clip(80 + 1100 * (xx / w) ** 0.8 + smooth_noise(h, w, 18, 140), 0, None).astype(np.float32)
    px_m = pixel_size_m(h, w)
    gy, gx = np.gradient(elev, px_m)
    slope = np.degrees(np.arctan(np.hypot(gx, gy))).astype(np.float32)
    aspect = ((np.degrees(np.arctan2(-gx, gy)) + 360) % 360).astype(np.float32)
    az, alt = math.radians(315), math.radians(45)
    sl, asp = np.radians(slope), np.arctan2(-gx, gy)
    hillshade = np.clip(np.sin(alt) * np.cos(sl) + np.cos(alt) * np.sin(sl) * np.cos(az - asp), 0, 1).astype(np.float32)

    d_hh, d_hv = hh_t2 - hh_t1, hv_t2 - hv_t1
    raw_idx = np.abs(d_hh) + np.abs(d_hv)
    med = np.median(raw_idx[valid])
    mad = np.median(np.abs(raw_idx[valid] - med)) * 1.4826
    idx = (raw_idx - med) / (mad + 1e-6)

    for a in (hh_t1, hv_t1, hh_t2, hv_t2, d_hh, d_hv, idx):
        a[~valid] = np.nan
    thr = float(np.nanpercentile(idx, 90))
    highlight = np.where(valid, idx > thr, False)
    return {
        "sar_t1_hh": hh_t1, "sar_t2_hh": hh_t2, "sar_t1_hv": hv_t1, "sar_t2_hv": hv_t2,
        "change_hh": d_hh, "change_hv": d_hv, "change_index": idx,
        "highlight_mask": highlight, "valid": valid, "inside": inside, "_thr": np.float32(thr),
        "elevation": elev, "slope": slope, "aspect": aspect, "hillshade": hillshade, "effect": effect,
    }


def pixel_size_m(h: int, w: int) -> float:
    lat0 = math.radians((AOI[1] + AOI[3]) / 2)
    return math.sqrt(((AOI[2] - AOI[0]) * 111320 * math.cos(lat0) / w) * ((AOI[3] - AOI[1]) * 110540 / h))


def optical_images(f: dict, h: int, w: int) -> tuple[Image.Image, Image.Image]:
    """MOCK Sentinel-2-like true colour: during the fire (smoke plume) and after (burn scar)."""
    shade = 0.55 + 0.45 * f["hillshade"]
    veg = np.stack([70 + 40 * shade, 95 + 50 * shade, 55 + 25 * shade], -1)
    yy, xx = np.mgrid[0:h, 0:w]
    plume = np.exp(-(((xx - 0.55 * w) / (0.45 * w)) ** 2 + ((yy - 0.35 * h) / (0.5 * h)) ** 2))
    plume = np.clip(plume * (0.85 + 0.25 * smooth_noise(h, w, 30, 1)), 0, 0.97)[..., None]
    during = veg * (1 - plume) + np.array([205, 200, 192]) * plume
    scar = np.clip(f["effect"], 0, 1)[..., None]
    after = veg * (1 - 0.75 * scar) + np.array([45, 35, 30]) * 0.75 * scar
    return (Image.fromarray(np.clip(during, 0, 255).astype(np.uint8), "RGB"),
            Image.fromarray(np.clip(after, 0, 255).astype(np.uint8), "RGB"))


# ---------------------------------------------------------------- rendering
GRAY = [(0, "#000000"), (1, "#ffffff")]
DIVERGING = [(0, "#2166ac"), (0.25, "#92c5de"), (0.5, "#f7f7f7"), (0.75, "#f4a582"), (1, "#b2182b")]
VIRIDIS = [(0, "#440154"), (0.25, "#3b528b"), (0.5, "#21918c"), (0.75, "#5ec962"), (1, "#fde725")]


def hex_rgb(c: str) -> tuple[int, int, int]:
    return tuple(int(c[i : i + 2], 16) for i in (1, 3, 5))  # type: ignore[return-value]


def colorize(a: np.ndarray, domain: tuple[float, float], ramp) -> Image.Image:
    t = np.clip((a - domain[0]) / (domain[1] - domain[0]), 0, 1)
    xs = [s for s, _ in ramp]
    rgb = np.zeros(a.shape + (4,), dtype=np.uint8)
    for ch in range(3):
        ys = [hex_rgb(c)[ch] for _, c in ramp]
        rgb[..., ch] = np.interp(np.nan_to_num(t), xs, ys).astype(np.uint8)
    rgb[..., 3] = np.where(np.isnan(a), 0, 255)
    return Image.fromarray(rgb, "RGBA")


def stops(domain, ramp):
    return [{"value": round(domain[0] + s * (domain[1] - domain[0]), 3), "color": c} for s, c in ramp]


# ---------------------------------------------------------------- JSON products
def iso(dt: str) -> str:
    return dt


def distribution(a: np.ndarray) -> dict:
    v = a[~np.isnan(a)]
    q = np.percentile(v, [5, 25, 50, 75, 95])
    counts, edges = np.histogram(v, bins=30)
    return {
        "p5": round(float(q[0]), 3), "p25": round(float(q[1]), 3), "p50": round(float(q[2]), 3),
        "p75": round(float(q[3]), 3), "p95": round(float(q[4]), 3), "mean": round(float(v.mean()), 3),
        "histogram": {"bin_edges": [round(float(e), 3) for e in edges], "counts": [int(c) for c in counts]},
    }


def box_mean(a: np.ndarray, r: int) -> np.ndarray:
    """Mean filter of radius r (NaN filled with the median first)."""
    a = np.where(np.isnan(a), np.nanmedian(a), a)
    p = np.pad(a, r, mode="edge")
    c = p.cumsum(0).cumsum(1)
    c = np.pad(c, ((1, 0), (1, 0)))
    k = 2 * r + 1
    s = c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]
    return s / (k * k)


def label_components(mask: np.ndarray) -> list[np.ndarray]:
    """4-connected components; returns a list of (N, 2) arrays of (row, col)."""
    h, w = mask.shape
    seen = np.zeros_like(mask, dtype=bool)
    comps = []
    for r0, c0 in np.argwhere(mask):
        if seen[r0, c0]:
            continue
        stack, pix = [(r0, c0)], []
        seen[r0, c0] = True
        while stack:
            r, c = stack.pop()
            pix.append((r, c))
            for rr, cc in ((r + 1, c), (r - 1, c), (r, c + 1), (r, c - 1)):
                if 0 <= rr < h and 0 <= cc < w and mask[rr, cc] and not seen[rr, cc]:
                    seen[rr, cc] = True
                    stack.append((rr, cc))
        comps.append(np.array(pix))
    return comps


def convex_hull(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    pts = sorted(set(points))
    if len(pts) < 3:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def build_review_zones(f: dict, h: int, w: int, px_area: float, thr: float) -> dict:
    """MOCK zones. Geometry = convex hull of the region's pixels (the real pipeline vectorises the mask)."""
    valid, inside, idx = f["valid"], f["inside"], f["change_index"]
    sm = box_mean(idx, 3)
    no_change_thr = float(np.nanpercentile(idx[inside & valid], 25))
    min_area_ha, max_per_kind = 15.0, 6
    px_m = math.sqrt(px_area)
    # Perimeter boundary pixels, for distances and the near-edge caveat.
    edge = inside & ~(np.roll(inside, 1, 0) & np.roll(inside, -1, 0) & np.roll(inside, 1, 1) & np.roll(inside, -1, 1))
    edge_pts = np.argwhere(edge).astype(np.float32)
    kinds = [
        ("change_outside_perimeter", "CO", (sm > thr) & ~inside & valid),
        ("no_change_inside_perimeter", "NI", (sm < no_change_thr) & inside & valid),
        ("change_inside_perimeter", "CI", (sm > thr) & inside & valid),
    ]
    features = []
    for kind, prefix, mask in kinds:
        comps = [c for c in label_components(mask) if len(c) * px_area / 1e4 >= min_area_ha]
        comps.sort(key=len, reverse=True)
        for rank, pix in enumerate(comps[:max_per_kind], start=1):
            rows, cols = pix[:, 0], pix[:, 1]
            corners = [(c + dc, r + dr) for r, c in pix for dr in (0, 1) for dc in (0, 1)]
            hull = [px_to_lonlat(c, r, h, w) for c, r in convex_hull(corners)]
            ring = [[round(x, 6), round(y, 6)] for x, y in hull] + [[round(hull[0][0], 6), round(hull[0][1], 6)]]
            lons, lats = [p[0] for p in ring], [p[1] for p in ring]
            cen = px_to_lonlat(cols.mean() + 0.5, rows.mean() + 0.5, h, w)
            sample = pix[:: max(1, len(pix) // 400)].astype(np.float32)
            d = np.sqrt(((sample[:, None, :] - edge_pts[None, :, :]) ** 2).sum(-1)).min(1)
            dist_m = 0.0 if d.min() <= 1.5 else round(float(d.min() * px_m), 0)

            def med(k: str) -> float:
                return round(float(np.nanmedian(f[k][rows, cols])), 2)

            cav = [{"id": "near_perimeter_edge", "label": "Near the perimeter edge", "fraction": round(float((d * px_m < 200).mean()), 2)}]
            steep = float((f["slope"][rows, cols] > 30).mean())
            if steep > 0:
                cav.append({"id": "steep_slope", "label": "Steep slope", "fraction": round(steep, 2)})
            features.append({
                "type": "Feature", "id": f"{prefix}-{rank:02d}",
                "geometry": {"type": "Polygon", "coordinates": [ring]},
                "properties": {
                    "zone_id": f"{prefix}-{rank:02d}", "kind": kind, "rank": rank,
                    "area_ha": round(len(pix) * px_area / 1e4, 1),
                    "centroid": [round(cen[0], 6), round(cen[1], 6)],
                    "bbox": [min(lons), min(lats), max(lons), max(lats)],
                    "valid_fraction": round(float(valid[rows, cols].mean()), 3),
                    "hh_db": {"t1_median": med("sar_t1_hh"), "t2_median": med("sar_t2_hh"), "delta_median": med("change_hh")},
                    "hv_db": {"t1_median": med("sar_t1_hv"), "t2_median": med("sar_t2_hv"), "delta_median": med("change_hv")},
                    "change_index": {"median": med("change_index"), "p90": round(float(np.nanpercentile(idx[rows, cols], 90)), 2)},
                    "distance_to_perimeter_m": dist_m,
                    "caveats": cav,
                },
            })
    return {
        "type": "FeatureCollection", "contract_version": CONTRACT_VERSION, "data_status": "mock",
        "method": {"change_threshold": round(thr, 3), "no_change_threshold": round(no_change_thr, 3),
                   "smoothing": "7x7 mean of change_index (mock)", "min_area_ha": min_area_ha, "max_zones_per_kind": max_per_kind},
        "features": features,
    }


def write_context_fixtures(f: dict, h: int, w: int, zones_fc: dict) -> None:
    """weather.json, story.json (example), profile and annotations examples. All MOCK."""
    from datetime import date, timedelta

    # Weather: dry season with one rain event before t2 (MOCK values).
    start, end = date(2026, 8, 16), date(2026, 10, 3)
    days = [start + timedelta(d) for d in range((end - start).days + 1)]
    rain = {date(2026, 9, 24): 6.2, date(2026, 9, 25): 14.8, date(2026, 9, 26): 3.1}
    weather = {
        "contract_version": CONTRACT_VERSION, "data_status": "mock", "variable": "precipitation", "units": "mm/day",
        "aggregation": "AOI mean (mock)",
        "source": {"label": "MOCK (real: NASA GPM IMERG Final daily)", "url": "https://gpm.nasa.gov/data/imerg", "product": "GPM_3IMERGDF"},
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "daily": [{"date": d.isoformat(), "value": rain.get(d, 0.0)} for d in days],
        "total": round(sum(rain.values()), 1), "rain_days_over_1mm": sum(v > 1 for v in rain.values()),
        "last_rain_before_t2": max(d for d, v in rain.items() if v > 1).isoformat(),
        "notes": "MOCK values for UI development.",
    }
    (WEB / "weather.json").write_text(json.dumps(weather, indent=2) + "\n", encoding="utf-8")

    # Profile: a line crossing the perimeter edge near the largest agreement zone.
    zones = {z["id"]: z["properties"] for z in zones_fc["features"]}
    ci = zones.get("CI-01") or next(iter(zones.values()))
    px_m = pixel_size_m(h, w)
    # Cross the perimeter edge closest to CI-01: ~2.5 km outside -> ~2.5 km inside.
    ins_m = f["inside"]
    edge = ins_m & ~(np.roll(ins_m, 1, 0) & np.roll(ins_m, -1, 0) & np.roll(ins_m, 1, 1) & np.roll(ins_m, -1, 1))
    cc, cr = lonlat_to_px(*ci["centroid"], h, w)
    er, ec = min(np.argwhere(edge), key=lambda p: (p[0] - cr) ** 2 + (p[1] - cc) ** 2)
    dr, dc = cr - er, cc - ec
    norm = math.hypot(dr, dc) or 1.0
    half = 2500 / px_m
    p0 = (ec - dc / norm * half, er - dr / norm * half)
    p1 = (ec + dc / norm * half, er + dr / norm * half)
    line = [[round(v, 6) for v in px_to_lonlat(*p0, h, w)], [round(v, 6) for v in px_to_lonlat(*p1, h, w)]]
    (x0, y0), (x1, y1) = lonlat_to_px(*line[0], h, w), lonlat_to_px(*line[1], h, w)
    n = int(math.hypot(x1 - x0, y1 - y0)) + 1
    samples, crossings, prev = [], [], None

    def val(k: str, r: int, c: int, ok: bool):
        return round(float(f[k][r, c]), 2) if ok else None

    for i in range(n):
        t = i / max(1, n - 1)
        col, row = x0 + t * (x1 - x0), y0 + t * (y1 - y0)
        r, c = min(h - 1, max(0, int(row))), min(w - 1, max(0, int(col)))
        ok = bool(f["valid"][r, c])
        lon, lat = px_to_lonlat(col, row, h, w)
        ins = bool(f["inside"][r, c])
        dist = round(t * (n - 1) * px_m, 1)
        if prev is not None and ins != prev:
            crossings.append(dist)
        prev = ins
        samples.append({"distance_m": dist, "lon": round(lon, 6), "lat": round(lat, 6), "valid": ok,
                        "hh_t1": val("sar_t1_hh", r, c, ok), "hh_t2": val("sar_t2_hh", r, c, ok),
                        "hv_t1": val("sar_t1_hv", r, c, ok), "hv_t2": val("sar_t2_hv", r, c, ok),
                        "change_index": val("change_index", r, c, ok), "inside_perimeter": ins,
                        "elevation_m": round(float(f["elevation"][r, c]), 1)})
    profile = {"contract_version": CONTRACT_VERSION, "data_status": "mock", "line": line,
               "length_m": samples[-1]["distance_m"], "spacing_m": round(px_m, 1), "truncated": False,
               "samples": samples, "perimeter_crossings_m": crossings}
    (API / "profile-example.json").write_text(json.dumps(profile) + "\n", encoding="utf-8")

    # Story: 5-step example the storytelling lane starts from (texts are drafts to finalise with real data).
    case_c = [round((AOI[0] + AOI[2]) / 2, 5), round((AOI[1] + AOI[3]) / 2, 5)]
    co = zones.get("CO-01")
    steps = [
        {"id": "context", "title": "A wildfire in Big Sur", "panel": "none",
         "body_md": "The **Plaskett Fire** started on 26 August 2026 in the Santa Lucia Mountains. NISAR observed the area before and after it.",
         "camera": {"center": case_c, "zoom": 10, "duration_ms": 2500}, "layers": {"visible": ["perimeter"]}},
        {"id": "smoke", "title": "Smoke hides the ground, radar does not", "panel": "none",
         "body_md": "During the fire, smoke covers optical imagery. NISAR L-band microwaves (about 24 cm) pass through smoke and clouds.",
         "camera": {"center": case_c, "zoom": 11.5, "duration_ms": 2000},
         "layers": {"visible": ["optical_during", "sar_t2_hv"]},
         "compare": {"left": "optical_during", "right": "sar_t2_hv", "position": 0.9, "animate_to": 0.3}},
        {"id": "before-after", "title": "What changed in the radar signal", "panel": "none",
         "body_md": "Before (16 Aug) vs after (3 Oct), same orbit and geometry. HV drops where vegetation volume was lost.",
         "camera": {"center": case_c, "zoom": 12, "duration_ms": 2000},
         "layers": {"visible": ["sar_t1_hv", "sar_t2_hv", "perimeter"]},
         "compare": {"left": "sar_t1_hv", "right": "sar_t2_hv", "position": 0.5, "animate_to": 0.15}},
        {"id": "agreement", "title": "Where radar and perimeter agree", "panel": "profile",
         "body_md": "The change index is high inside the official perimeter. Along this transect, HV falls as it crosses the perimeter edge.",
         "camera": {"center": ci["centroid"], "zoom": 12.5, "duration_ms": 2000},
         "layers": {"visible": ["change_index", "perimeter"], "opacity": {"change_index": 0.8}},
         "focus": {"type": "profile", "line": line}},
    ]
    if co:
        steps.append({"id": "discrepancy", "title": "Where they disagree, and why", "panel": "inspector",
                      "body_md": "Outside the perimeter, backscatter **increased**: closer to wetter soil than to fire. The inspector lists the caveats.",
                      "camera": {"center": co["centroid"], "zoom": 13, "duration_ms": 2500},
                      "layers": {"visible": ["change_index", "perimeter", "review_zones"]},
                      "focus": {"type": "zone", "zone_id": "CO-01"}})
    story = {"contract_version": CONTRACT_VERSION, "case_id": "plaskett-2026", "title": "Plaskett Fire through the eyes of NISAR", "steps": steps}
    (WEB / "story.json").write_text(json.dumps(story, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # Annotations export example.
    def ann(zid: str, verdict: str, note: str) -> dict:
        z = zones[zid]
        return {"type": "Feature", "id": f"ann-{zid.lower()}", "geometry": {"type": "Point", "coordinates": z["centroid"]},
                "properties": {"target": {"type": "zone", "zone_id": zid}, "verdict": verdict, "note": note, "author": "analyst-demo",
                               "created_at": "2026-11-15T10:00:00Z",
                               "evidence": {"change_index": z["change_index"]["median"], "hh_delta_db": z["hh_db"]["delta_median"],
                                            "hv_delta_db": z["hv_db"]["delta_median"],
                                            "perimeter_relation": "outside" if zid.startswith("CO") else "inside",
                                            "caveat_ids": [c["id"] for c in z["caveats"] if c["fraction"] > 0.2]}}}

    feats = [ann("CI-01", "consistent_with_fire", "Strong HV decrease, inside the perimeter.")]
    if co:
        feats.append(ann("CO-01", "not_fire_related", "Backscatter increase in both polarizations; rain on 24-26 Sep. Check moisture."))
    annotations = {"type": "FeatureCollection", "contract_version": CONTRACT_VERSION, "case_id": "plaskett-2026",
                   "exported_at": "2026-11-15T10:05:00Z", "data_status": "mock", "method_id": METHOD_ID, "features": feats}
    (FIX / "exports").mkdir(exist_ok=True)
    (FIX / "exports" / "annotations.geojson").write_text(json.dumps(annotations, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--perimeter-source", type=Path, help="Raw WFIGS GeoJSON to (re)simplify into the fixtures")
    args = ap.parse_args()

    (WEB / "layers").mkdir(parents=True, exist_ok=True)
    API.mkdir(parents=True, exist_ok=True)
    if args.perimeter_source:
        simplify_perimeter(args.perimeter_source, WEB / "perimeter.geojson")

    h, w = grid_shape()
    f = build_fields(h, w)
    tl, tr = px_to_lonlat(0, 0, h, w), px_to_lonlat(w, 0, h, w)
    br, bl = px_to_lonlat(w, h, h, w), px_to_lonlat(0, h, h, w)
    coords = [[round(x, 6), round(y, 6)] for x, y in (tl, tr, br, bl)]
    p99 = float(np.nanpercentile(f["change_index"], 99))

    specs = [
        ("sar_t1_hh", "SAR backscatter HH — before", "sar", "t1", "HH", (-25.0, 0.0), GRAY, "dB", False),
        ("sar_t2_hh", "SAR backscatter HH — after", "sar", "t2", "HH", (-25.0, 0.0), GRAY, "dB", False),
        ("sar_t1_hv", "SAR backscatter HV — before", "sar", "t1", "HV", (-30.0, -5.0), GRAY, "dB", False),
        ("sar_t2_hv", "SAR backscatter HV — after", "sar", "t2", "HV", (-30.0, -5.0), GRAY, "dB", False),
        ("change_hh", "Observed radar changes — HH", "observed_change", None, "HH", (-6.0, 6.0), DIVERGING, "dB difference (after − before)", False),
        ("change_hv", "Observed radar changes — HV", "observed_change", None, "HV", (-6.0, 6.0), DIVERGING, "dB difference (after − before)", False),
        ("change_index", "Observed radar changes — combined index", "observed_change", None, None, (0.0, round(p99, 2)), VIRIDIS, "index (unitless, robust z-score)", False),
    ]
    layers = []
    for lid, title, group, epoch, pol, dom, ramp, units, visible in specs:
        colorize(f[lid], dom, ramp).save(WEB / "layers" / f"{lid}.png", optimize=True)
        layer = {
            "id": lid, "title": title, "kind": "raster", "group": group, "url": f"layers/{lid}.png",
            "coordinates": coords, "width_px": w, "height_px": h,
            "default_visible": lid in ("sar_t1_hh", "change_index"), "default_opacity": 0.85 if group != "sar" else 1.0,
            "legend": {"type": "continuous", "units": units, "domain": list(dom), "stops": stops(dom, ramp)},
        }
        if epoch:
            layer["epoch"] = epoch
        if pol:
            layer["polarization"] = pol
        layers.append(layer)

    hl = np.zeros((h, w, 4), dtype=np.uint8)
    hl[f["highlight_mask"]] = (*hex_rgb("#e66101"), 255)
    Image.fromarray(hl, "RGBA").save(WEB / "layers" / "highlight_mask.png", optimize=True)
    layers.append({
        "id": "highlight_mask", "title": "Highlighted radar changes", "kind": "raster", "group": "highlighted_change",
        "url": "layers/highlight_mask.png", "coordinates": coords, "width_px": w, "height_px": h,
        "default_visible": False, "default_opacity": 0.8, "p1": True,
        "legend": {"type": "categorical", "items": [{"value": 1, "label": "Change above exploratory threshold", "color": "#e66101"}],
                   "note": "Exploratory threshold, not a validated burned-area mask."},
    })
    vm = np.zeros((h, w, 4), dtype=np.uint8)
    vm[~f["valid"]] = (*hex_rgb("#7f7f7f"), 200)
    Image.fromarray(vm, "RGBA").save(WEB / "layers" / "valid_mask.png", optimize=True)
    layers.append({
        "id": "valid_mask", "title": "No-data / invalid pixels", "kind": "raster", "group": "quality",
        "url": "layers/valid_mask.png", "coordinates": coords, "width_px": w, "height_px": h,
        "default_visible": False, "default_opacity": 1.0,
        "legend": {"type": "categorical", "items": [{"value": 0, "label": "Invalid in at least one layer", "color": "#7f7f7f"}]},
    })
    # Complementary context layers (non-NISAR): terrain and optical. MOCK images.
    hs = (np.clip(f["hillshade"], 0, 1) * 255).astype(np.uint8)
    Image.fromarray(np.stack([hs, hs, hs], -1), "RGB").save(WEB / "layers" / "hillshade.png", optimize=True)
    slope_dom, slope_ramp = (0.0, 45.0), [(0, "#ffffd4"), (0.25, "#fed98e"), (0.5, "#fe9929"), (0.75, "#d95f0e"), (1, "#993404")]
    colorize(f["slope"], slope_dom, slope_ramp).save(WEB / "layers" / "slope.png", optimize=True)
    dem_src = {"label": "MOCK DEM (real: NASADEM / Copernicus GLO-30)", "url": "https://lpdaac.usgs.gov/products/nasadem_hgtv001/"}
    s2_src = {"label": "MOCK optical (real: Sentinel-2 L2A, Copernicus)", "url": "https://dataspace.copernicus.eu/"}
    opt_during, opt_after = optical_images(f, h, w)
    opt_during.save(WEB / "layers" / "optical_during.png", optimize=True)
    opt_after.save(WEB / "layers" / "optical_after.png", optimize=True)
    base = {"kind": "raster", "coordinates": coords, "width_px": w, "height_px": h, "default_visible": False}
    layers += [
        {**base, "id": "hillshade", "title": "Terrain relief (hillshade)", "group": "terrain", "url": "layers/hillshade.png",
         "default_opacity": 0.5, "source": dem_src, "legend": {"type": "rgb", "note": "Shaded relief from the DEM, sun at 315°/45°."}},
        {**base, "id": "slope", "title": "Terrain slope", "group": "terrain", "url": "layers/slope.png", "default_opacity": 0.8,
         "source": dem_src, "legend": {"type": "continuous", "units": "degrees", "domain": list(slope_dom), "stops": stops(slope_dom, slope_ramp),
                                       "note": "Slopes above 30° trigger the steep-slope caveat."}},
        {**base, "id": "optical_during", "title": "Optical image during the fire", "group": "optical_context", "url": "layers/optical_during.png",
         "default_opacity": 1.0, "acquired": "2026-09-05T18:59:00Z", "source": s2_src,
         "legend": {"type": "rgb", "note": "True colour. Smoke hides the ground; compare with the radar."}},
        {**base, "id": "optical_after", "title": "Optical image after the fire", "group": "optical_context", "url": "layers/optical_after.png",
         "default_opacity": 1.0, "acquired": "2026-10-05T18:59:00Z", "source": s2_src,
         "legend": {"type": "rgb", "note": "True colour, after the fire."}},
    ]
    layers.append({
        "id": "perimeter", "title": "Official fire perimeter", "kind": "vector", "group": "reference", "url": "perimeter.geojson",
        "default_visible": True, "default_opacity": 1.0,
        "legend": {"type": "categorical", "items": [{"value": "WFIGS 58728", "label": "WFIGS perimeter, 2026-09-14 20:44 UTC", "color": "#000000"}],
                   "note": "Reference only, not pixel-level truth."},
    })

    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    case = {
        "contract_version": CONTRACT_VERSION, "data_status": "mock",
        "case_id": "plaskett-2026", "name": "Plaskett Fire", "location": "Big Sur, Monterey County, California, USA",
        "fire_start": "2026-08-26", "aoi_bbox": list(AOI),
        "epochs": {
            "t1": {"label": "Before", "datetime": "2026-08-16T02:56:39Z", "granule_id": "G4284560161-ASF", "absolute_orbit": 5504},
            "t2": {"label": "After", "datetime": "2026-10-03T02:56:38Z", "granule_id": "G4340499432-ASF", "absolute_orbit": 6196},
        },
        "acquisition": {"track": 42, "frame": 70, "direction": "descending", "frequency": "A", "polarizations": ["HH", "HV"], "pixel_size_m": 10, "crs": "EPSG:32610"},
        "product": "NISAR_L2_GCOV_PROVISIONAL_V1",
        "reference": {
            "source": "NIFC WFIGS Interagency Perimeters", "objectid": 58728, "datetime": "2026-09-14T20:44:00Z",
            "url": "https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/WFIGS_Interagency_Perimeters_YearToDate/FeatureServer/0",
            "note": "Operational perimeter dated before the 'after' acquisition. Reference for contrast, not pixel-level truth.",
        },
        "method": {
            "id": METHOD_ID, "name": "Absolute log-ratio change, HH + HV",
            "description": "MOCK: |ΔdB HH| + |ΔdB HV| normalised with a robust z-score (median/MAD) over valid pixels.",
            "params": {"normalisation": "median_mad"},
        },
        "sources": [
            {"label": "CAL FIRE incident page", "url": "https://www.fire.ca.gov/incidents/2026/8/26/plaskett-fire"},
            {"label": "NISAR GCOV before (CMR)", "url": "https://cmr.earthdata.nasa.gov/search/granules.umm_json?concept_id=G4284560161-ASF"},
            {"label": "NISAR GCOV after (CMR)", "url": "https://cmr.earthdata.nasa.gov/search/granules.umm_json?concept_id=G4340499432-ASF"},
        ],
        "generated_at": now, "pipeline_version": "mock-generator",
    }

    valid, inside = f["valid"], f["inside"]
    # Mock pixels are much coarser than the real 10 m grid: use their true ground size.
    lat0 = math.radians((AOI[1] + AOI[3]) / 2)
    px_area = round(((AOI[2] - AOI[0]) * 111320 * math.cos(lat0) / w) * ((AOI[3] - AOI[1]) * 110540 / h), 1)
    idx = f["change_index"]

    def zone(m: np.ndarray) -> dict:
        sel = m & valid
        return {"valid_pixels": int(sel.sum()), "area_ha": round(sel.sum() * px_area / 1e4, 1), "change_index": distribution(np.where(sel, idx, np.nan))}

    stats = {
        "contract_version": CONTRACT_VERSION, "data_status": "mock",
        "valid_pixels": int(valid.sum()), "total_pixels": int(valid.size),
        "valid_coverage_pct": round(100 * valid.sum() / valid.size, 2), "pixel_area_m2": px_area,
        "change_index": distribution(idx), "inside_perimeter": zone(inside), "outside_perimeter": zone(~inside),
        "highlight": None,
    }
    hl_m = f["highlight_mask"]
    inter, union = (hl_m & inside & valid).sum(), ((hl_m | inside) & valid).sum()
    stats_hl = {**stats, "highlight": {
        "threshold": round(float(f["_thr"]), 3), "smoothing": "none (mock)",
        "area_ha": round(hl_m.sum() * px_area / 1e4, 1), "inside_ha": round((hl_m & inside).sum() * px_area / 1e4, 1),
        "outside_ha": round((hl_m & ~inside).sum() * px_area / 1e4, 1), "iou_vs_perimeter": round(float(inter / union), 3),
    }}

    def caveats(r: int, c: int) -> list[dict]:
        out = [{"id": "soil_moisture_change", "label": "Soil moisture change between dates", "triggered": False,
                "reason": "Generic caution: moisture changes alter L-band backscatter regardless of fire."},
               {"id": "vegetation_structure", "label": "Vegetation structure", "triggered": False,
                "reason": "Generic caution: HV responds to canopy volume; unburned stand changes also affect it."}]
        sl = float(f["slope"][r, c])
        if sl > 30:
            out.insert(0, {"id": "steep_slope", "label": "Steep slope", "triggered": True, "reason": f"slope {sl:.1f}° > 30° (mock DEM)"})
        return out

    def inspect(lon: float, lat: float) -> dict:
        col, row = lonlat_to_px(lon, lat, h, w)
        r, c = int(row), int(col)
        base = {"contract_version": CONTRACT_VERSION, "data_status": "mock", "query": {"lon": lon, "lat": lat}, "method_id": METHOD_ID}
        if not (0 <= r < h and 0 <= c < w):
            nulls = {"t1": None, "t2": None, "delta": None}
            return {**base, "pixel": None, "valid": False, "hh_db": nulls, "hv_db": dict(nulls), "change_index": None,
                    "change_index_percentile": None, "highlighted": None, "perimeter_relation": "unknown", "caveats": []}
        clon, clat = px_to_lonlat(c + 0.5, r + 0.5, h, w)
        pixel = {"row": r, "col": c, "x": round(600000 + c * 10.0, 1), "y": round(3975000 - r * 10.0, 1), "crs": "EPSG:32610",
                 "center_lon": round(clon, 6), "center_lat": round(clat, 6)}
        ok = bool(valid[r, c])

        def g(k: str):
            return None if not ok else round(float(f[k][r, c]), 2)

        v = g("change_index")
        pct = None if v is None else round(float((idx[valid] < v).mean() * 100), 1)
        return {**base, "pixel": pixel, "valid": ok,
                "hh_db": {"t1": g("sar_t1_hh"), "t2": g("sar_t2_hh"), "delta": g("change_hh")},
                "hv_db": {"t1": g("sar_t1_hv"), "t2": g("sar_t2_hv"), "delta": g("change_hv")},
                "change_index": v, "change_index_percentile": pct, "highlighted": None,
                "perimeter_relation": "inside" if inside[r, c] else "outside", "caveats": caveats(r, c) if ok else [],
                "terrain": {"elevation_m": round(float(f["elevation"][r, c]), 1), "slope_deg": round(float(f["slope"][r, c]), 1),
                            "aspect_deg": round(float(f["aspect"][r, c]), 1)}}

    # Representative points: one inside, one outside (moisture blob), one invalid (shadow strip).
    ins_r, ins_c = np.argwhere(inside & valid & (idx > np.nanpercentile(idx, 95)))[0]
    pts = {
        "inside": px_to_lonlat(ins_c + 0.5, ins_r + 0.5, h, w),
        "outside": px_to_lonlat(0.85 * w, 0.2 * h, h, w),
        "invalid": px_to_lonlat(0.2 * w, 0.64 * h, h, w),
    }
    for name, (lon, lat) in pts.items():
        (API / f"inspect-point-{name}.json").write_text(json.dumps(inspect(round(lon, 6), round(lat, 6)), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # Compact grid for the MSW mock: values every `step` pixels.
    step = 6
    rows, cols = range(0, h, step), range(0, w, step)

    def sample(k: str) -> list:
        return [[None if not valid[r, c] else round(float(f[k][r, c]), 2) for c in cols] for r in rows]

    grid = {
        "_note": "MOCK-ONLY compact grid for web/src/mocks. Not part of the production contract.",
        "aoi_bbox": list(AOI), "image_height": h, "image_width": w, "step_px": step,
        "fields": {k: sample(k) for k in ("sar_t1_hh", "sar_t2_hh", "sar_t1_hv", "sar_t2_hv", "change_index")},
        "terrain": {"elevation_m": [[round(float(f["elevation"][r, c]), 1) for c in cols] for r in rows],
                    "slope_deg": [[round(float(f["slope"][r, c]), 1) for c in cols] for r in rows]},
        "inside": [[bool(inside[r, c]) for c in cols] for r in rows],
    }
    (API / "inspect-grid.json").write_text(json.dumps(grid, separators=(",", ":")), encoding="utf-8")

    # Review zones (P1, EV-04): discrepancies and agreement examples between radar change and perimeter.
    zones_fc = build_review_zones(f, h, w, px_area, float(f["_thr"]))
    (WEB / "review_zones.geojson").write_text(json.dumps(zones_fc, ensure_ascii=False) + "\n", encoding="utf-8")
    layers.append({
        "id": "review_zones", "title": "Zones to review", "kind": "vector", "group": "highlighted_change", "url": "review_zones.geojson",
        "default_visible": False, "default_opacity": 1.0, "p1": True,
        "legend": {"type": "categorical", "items": [
            {"value": "change_outside_perimeter", "label": "Radar change outside the perimeter", "color": "#e66101"},
            {"value": "no_change_inside_perimeter", "label": "Little radar change inside the perimeter", "color": "#5e3c99"},
            {"value": "change_inside_perimeter", "label": "Radar change inside the perimeter (agreement)", "color": "#1b7837"},
        ], "note": "Derived from an exploratory threshold. Discrepancies are prompts to investigate, not errors."},
    })

    for name, obj in (("case", case), ("stats", stats), ("layers", {"contract_version": CONTRACT_VERSION, "data_status": "mock", "layers": layers})):
        (WEB / f"{name}.json").write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    export = {
        "export_format_version": 1,
        "case_id": case["case_id"],
        "outputs": {
            name: hashlib.sha256((WEB / name).read_bytes()).hexdigest()
            for name in ("case.json", "review_zones.geojson")
        },
    }
    (WEB / "export.json").write_text(json.dumps(export, indent=2) + "\n", encoding="utf-8")
    (API / "stats-with-highlight.json").write_text(json.dumps(stats_hl, indent=2) + "\n", encoding="utf-8")
    write_context_fixtures(f, h, w, zones_fc)
    print(f"Mock fixtures written to {FIX.relative_to(ROOT)} ({w}x{h} px)")


if __name__ == "__main__":
    main()
