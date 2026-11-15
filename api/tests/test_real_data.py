"""Opt-in checks of the inspection API against a verified real-data bundle (IN-02).

Run from the repository root against a bundle that contains ``processed/web`` and
``interim/{sar,change,perimeter[,terrain]}``::

    FIRETRACE_DATA_ROOT=/path/to/data uv run pytest api/tests/test_real_data.py -q

The module skips without ``FIRETRACE_DATA_ROOT`` so offline checkouts and CI never
read real products. Expected values are recomputed from the same verified files
with independent rasterio/NumPy reads. A pass is integration evidence, not
scientific validation, and this is not a licence to download scenes.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import rasterio
from affine import Affine
from jsonschema import Draft202012Validator
from rasterio.transform import rowcol, xy
from rasterio.warp import transform as transform_coordinates

from api.raster import FireTraceRasterService

DATA_ROOT = os.environ.get("FIRETRACE_DATA_ROOT")
pytestmark = pytest.mark.skipif(
    not DATA_ROOT, reason="set FIRETRACE_DATA_ROOT to a verified real-data bundle"
)

ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = ROOT / "contracts" / "schemas"
PIXEL_SIZE_M = 10.0
ANALYSIS_CRS = "EPSG:32610"
WGS84 = "EPSG:4326"
MANIFEST_DIRS = {
    "sar.json": ("interim", "sar"),
    "change.json": ("interim", "change"),
    "perimeter.json": ("interim", "perimeter"),
}


@dataclass(frozen=True)
class Bundle:
    """Verified manifests and arrays from one real pipeline generation."""

    root: Path
    web: Path
    case: dict[str, Any]
    export: dict[str, Any]
    manifests: dict[str, dict[str, Any]]
    layers: dict[str, np.ndarray]
    transform: Affine
    width: int
    height: int
    service: FireTraceRasterService


def _doc(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(document, dict), f"{path} is not a JSON object"
    return document


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read(directory: Path, record: dict[str, Any]) -> np.ndarray:
    path = directory / record["file"]
    assert _sha(path) == record["sha256"], f"{path} does not match its manifest checksum"
    with rasterio.open(path) as dataset:
        return dataset.read(1)


def _validator(name: str) -> Draft202012Validator:
    return Draft202012Validator(json.loads((SCHEMAS / name).read_text(encoding="utf-8")))


def _wgs84(x: float, y: float) -> tuple[float, float]:
    lon, lat = transform_coordinates(ANALYSIS_CRS, WGS84, [x], [y])
    return float(lon[0]), float(lat[0])


def _finite(value: float) -> float | None:
    number = float(value)
    return number if math.isfinite(number) else None


@pytest.fixture(scope="module")
def bundle() -> Bundle:
    root = Path(DATA_ROOT or "")
    web = root / "processed" / "web"
    export = _doc(web / "export.json")
    case = _doc(web / "case.json")
    manifests: dict[str, dict[str, Any]] = {}
    for name, parts in MANIFEST_DIRS.items():
        directory = root.joinpath(*parts)
        path = directory / name
        assert path.is_file(), f"missing {path}; IN-02 needs the verified bundle"
        assert export["inputs"].get(name) == _sha(path), (
            f"{name} is not the generation recorded in export.json"
        )
        manifests[name] = _doc(path)

    sar_dir = root.joinpath(*MANIFEST_DIRS["sar.json"])
    change_dir = root.joinpath(*MANIFEST_DIRS["change.json"])
    perimeter_dir = root.joinpath(*MANIFEST_DIRS["perimeter.json"])
    sar = manifests["sar.json"]
    layers = {
        name: _read(sar_dir, sar["db"]["layers"][name])
        for name in ("t1_hh", "t1_hv", "t2_hh", "t2_hv")
    }
    layers["valid_mask"] = _read(sar_dir, sar["valid_mask"])
    for name in ("change_hh_db", "change_hv_db", "change_index"):
        layers[name] = _read(change_dir, manifests["change.json"]["outputs"][name])
    for name in ("perimeter_mask.tif", "perimeter_edge.tif"):
        layers[name] = _read(perimeter_dir, manifests["perimeter.json"]["outputs"][name])

    terrain_path = root / "interim" / "terrain" / "terrain.json"
    if terrain_path.is_file():
        assert export["inputs"].get("terrain.json") == _sha(terrain_path), (
            "terrain.json is not the generation recorded in export.json"
        )
        terrain = _doc(terrain_path)
        terrain_dir = terrain_path.parent
        for name in ("elevation", "slope", "aspect"):
            layers[name] = _read(terrain_dir, terrain["outputs"][f"{name}.tif"])

    grid = sar["grid"]
    transform = Affine(*grid["transform"])
    return Bundle(
        root=root,
        web=web,
        case=case,
        export=export,
        manifests=manifests,
        layers=layers,
        transform=transform,
        width=int(grid["width"]),
        height=int(grid["height"]),
        service=FireTraceRasterService(root),
    )


def _valid_pixels(bundle: Bundle) -> np.ndarray:
    finite = np.ones((bundle.height, bundle.width), dtype=bool)
    for name in (
        "t1_hh",
        "t1_hv",
        "t2_hh",
        "t2_hv",
        "change_hh_db",
        "change_hv_db",
        "change_index",
    ):
        finite &= np.isfinite(bundle.layers[name])
    return (bundle.layers["valid_mask"] == 1) & finite


def _first(mask: np.ndarray) -> tuple[int, int]:
    rows, cols = np.nonzero(mask)
    assert rows.size, "the bundle has no pixel of this class"
    return int(rows[0]), int(cols[0])


def _point(bundle: Bundle, row: int, col: int) -> dict[str, Any]:
    lon, lat = _wgs84(*xy(bundle.transform, row, col, offset="center"))
    result = bundle.service.inspect_point(lon, lat)
    _validator("inspect-point.schema.json").validate(result)
    pixel = result["pixel"]
    assert pixel is not None, "an in-grid pixel must be returned"
    assert (pixel["row"], pixel["col"]) == (row, col)
    x, y = xy(bundle.transform, row, col, offset="center")
    assert pixel["x"] == pytest.approx(float(x), abs=1e-6)
    assert pixel["y"] == pytest.approx(float(y), abs=1e-6)
    assert pixel["crs"] == ANALYSIS_CRS
    assert pixel["center_lon"] == pytest.approx(lon, abs=1e-9)
    assert pixel["center_lat"] == pytest.approx(lat, abs=1e-9)
    assert result["contract_version"] == bundle.case["contract_version"]
    assert result["data_status"] == "real"
    assert result["method_id"] == bundle.case["method"]["id"]
    return result


def _assert_values(bundle: Bundle, result: dict[str, Any], row: int, col: int) -> None:
    valid = bool(_valid_pixels(bundle)[row, col])
    relation = "inside" if bundle.layers["perimeter_mask.tif"][row, col] == 1 else "outside"
    assert result["valid"] is valid
    assert result["perimeter_relation"] == relation
    if not valid:
        for name in ("hh_db", "hv_db"):
            assert result[name] == {"t1": None, "t2": None, "delta": None}
        assert result["change_index"] is None
        assert result["change_index_percentile"] is None
        assert result["caveats"] == []
        return
    layers = bundle.layers
    pairs = (
        ("hh_db", "t1_hh", "t2_hh", "change_hh_db"),
        ("hv_db", "t1_hv", "t2_hv", "change_hv_db"),
    )
    for name, first, second, delta in pairs:
        assert result[name]["t1"] == pytest.approx(float(layers[first][row, col]), abs=1e-6)
        assert result[name]["t2"] == pytest.approx(float(layers[second][row, col]), abs=1e-6)
        assert result[name]["delta"] == pytest.approx(float(layers[delta][row, col]), abs=1e-6)
    index = layers["change_index"]
    assert result["change_index"] == pytest.approx(float(index[row, col]), abs=1e-6)
    finite_index = index[(layers["valid_mask"] == 1) & np.isfinite(index)]
    assert np.isfinite(index[row, col])
    percentile = 100.0 * np.count_nonzero(finite_index <= index[row, col]) / finite_index.size
    assert result["change_index_percentile"] == pytest.approx(float(percentile), abs=1e-9)
    if "elevation" in layers:
        assert result["terrain"]["elevation_m"] == _finite(layers["elevation"][row, col])
        assert result["terrain"]["slope_deg"] == _finite(layers["slope"][row, col])
        assert result["terrain"]["aspect_deg"] == _finite(layers["aspect"][row, col])


def test_bundle_is_real_and_matches_export_identity(bundle: Bundle) -> None:
    assert bundle.case["data_status"] == "real"
    assert bundle.case["contract_version"] == "1.2.0"
    assert bundle.service.health() == {"status": "ok", "data_status": "real"}
    for name, checksum in bundle.export["outputs"].items():
        assert _sha(bundle.web / name) == checksum, f"{name} does not match export.json"

    def analysis_grid(manifest: dict[str, Any]) -> tuple[Any, ...]:
        grid = manifest["grid"]
        return (
            grid["crs"],
            tuple(float(value) for value in grid["transform"]),
            int(grid["width"]),
            int(grid["height"]),
        )

    for manifest in bundle.manifests.values():
        assert analysis_grid(manifest) == analysis_grid(bundle.manifests["sar.json"]), (
            "the interim manifests do not share one analysis grid"
        )


def test_point_inside_the_perimeter_matches_the_rasters(bundle: Bundle) -> None:
    row, col = _first(_valid_pixels(bundle) & (bundle.layers["perimeter_mask.tif"] == 1))
    _assert_values(bundle, _point(bundle, row, col), row, col)


def test_point_outside_the_perimeter_matches_the_rasters(bundle: Bundle) -> None:
    row, col = _first(_valid_pixels(bundle) & (bundle.layers["perimeter_mask.tif"] == 0))
    _assert_values(bundle, _point(bundle, row, col), row, col)


def test_point_outside_the_aoi_has_null_values(bundle: Bundle) -> None:
    west, south = bundle.case["aoi_bbox"][:2]
    result = bundle.service.inspect_point(west - 1.0, south)
    _validator("inspect-point.schema.json").validate(result)
    assert result["pixel"] is None
    assert result["valid"] is False
    assert result["perimeter_relation"] == "unknown"
    assert result["change_index"] is None
    assert result["caveats"] == []
    assert result["data_status"] == "real"


def test_masked_point_has_null_values_when_the_bundle_has_one(bundle: Bundle) -> None:
    masked = ~_valid_pixels(bundle)
    if not masked.any():
        pytest.skip("this bundle has no masked pixel; the synthetic API test covers it")
    row, col = _first(masked)
    _assert_values(bundle, _point(bundle, row, col), row, col)


def test_profile_matches_the_rasters_and_reports_crossings(bundle: Bundle) -> None:
    mask = bundle.layers["perimeter_mask.tif"]
    valid = _valid_pixels(bundle)
    row = next(
        (
            index
            for index in range(bundle.height)
            if mask[index].min() == 0 and mask[index].max() == 1 and valid[index].any()
        ),
        None,
    )
    assert row is not None, "no analysis row crosses the reference perimeter"
    x0, y = xy(bundle.transform, row, 0, offset="center")
    x1, _ = xy(bundle.transform, row, bundle.width - 1, offset="center")
    line = [list(_wgs84(x0, y)), list(_wgs84(x1, y))]
    spacing_m = 100.0

    result = bundle.service.inspect_profile(line, spacing_m)
    _validator("profile.schema.json").validate(result)

    assert result["data_status"] == "real"
    assert result["spacing_m"] == spacing_m
    assert result["truncated"] is False
    assert result["length_m"] == pytest.approx((bundle.width - 1) * PIXEL_SIZE_M, abs=0.01)
    samples = result["samples"]
    assert samples
    assert samples[0]["distance_m"] == 0.0
    assert samples[-1]["distance_m"] == pytest.approx(result["length_m"], abs=1e-6)

    xs, ys = transform_coordinates(
        WGS84,
        ANALYSIS_CRS,
        [sample["lon"] for sample in samples],
        [sample["lat"] for sample in samples],
    )
    for sample, x, y_sample in zip(samples, xs, ys, strict=True):
        sample_row, sample_col = rowcol(bundle.transform, x, y_sample)
        sample_row, sample_col = int(sample_row), int(sample_col)
        inside_grid = 0 <= sample_row < bundle.height and 0 <= sample_col < bundle.width
        if not inside_grid:
            assert sample["valid"] is False
            assert sample["inside_perimeter"] is None
            continue
        assert sample["inside_perimeter"] is bool(mask[sample_row, sample_col] == 1)
        assert sample["valid"] is bool(valid[sample_row, sample_col])
        if sample["valid"]:
            assert sample["hh_t1"] == pytest.approx(
                float(bundle.layers["t1_hh"][sample_row, sample_col]), abs=1e-6
            )
            assert sample["hv_t2"] == pytest.approx(
                float(bundle.layers["t2_hv"][sample_row, sample_col]), abs=1e-6
            )
            assert sample["change_index"] == pytest.approx(
                float(bundle.layers["change_index"][sample_row, sample_col]), abs=1e-6
            )

    flips = [
        (samples[index - 1]["distance_m"], samples[index]["distance_m"])
        for index in range(1, len(samples))
        if samples[index - 1]["inside_perimeter"] is not None
        and samples[index]["inside_perimeter"] is not None
        and samples[index - 1]["inside_perimeter"] != samples[index]["inside_perimeter"]
    ]
    assert len(result["perimeter_crossings_m"]) == len(flips)
    for crossing, (low, high) in zip(result["perimeter_crossings_m"], flips, strict=True):
        assert low <= crossing <= high
        assert _mask_at(bundle, x0, y, crossing - 2.0) is not _mask_at(
            bundle, x0, y, crossing + 2.0
        ), "a reported crossing must separate inside from outside"


def _mask_at(bundle: Bundle, x0: float, y: float, distance: float) -> bool | None:
    row, col = rowcol(bundle.transform, x0 + distance, y)
    row, col = int(row), int(col)
    if not (0 <= row < bundle.height and 0 <= col < bundle.width):
        return None
    return bool(bundle.layers["perimeter_mask.tif"][row, col] == 1)
