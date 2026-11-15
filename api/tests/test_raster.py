from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import rasterio
from fastapi import HTTPException
from jsonschema import Draft202012Validator
from rasterio.transform import from_origin
from rasterio.warp import transform as transform_coordinates

from api.raster import FireTraceRasterService

GRID = {
    "crs": "EPSG:32610",
    "transform": [10.0, 0.0, 600000.0, 0.0, -10.0, 3975000.0],
    "width": 2,
    "height": 2,
}
TRANSFORM = from_origin(600000.0, 3975000.0, 10.0, 10.0)


def _write_json(path: Path, document: dict[str, Any]) -> bytes:
    payload = json.dumps(document, sort_keys=True).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return payload


def _write_raster(path: Path, values: np.ndarray) -> dict[str, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = np.asarray(values)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=data.shape[1],
        height=data.shape[0],
        count=1,
        dtype=data.dtype,
        crs=GRID["crs"],
        transform=TRANSFORM,
        nodata=np.nan if data.dtype == np.float32 else None,
    ) as dataset:
        dataset.write(data, 1)
    return {"file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _case_data(tmp_path: Path) -> tuple[Path, float, float]:
    root = tmp_path / "data"
    sar_dir = root / "interim" / "sar"
    change_dir = root / "interim" / "change"
    perimeter_dir = root / "interim" / "perimeter"

    sar_values = {
        "t1_hh": np.array([[-10, -11], [-12, -13]], dtype=np.float32),
        "t1_hv": np.array([[-20, -21], [-22, -23]], dtype=np.float32),
        "t2_hh": np.array([[-9, -10], [-11, -12]], dtype=np.float32),
        "t2_hv": np.array([[-22, -23], [-24, -25]], dtype=np.float32),
    }
    sar_layers = {
        name: _write_raster(sar_dir / f"{name}_db.tif", values)
        for name, values in sar_values.items()
    }
    valid_mask = _write_raster(
        sar_dir / "valid_mask.tif",
        np.array([[1, 1], [1, 0]], dtype=np.uint8),
    )
    sar_doc = {
        "sar_format_version": 1,
        "grid": GRID,
        "db": {"layers": sar_layers},
        "valid_mask": valid_mask,
    }
    sar_bytes = _write_json(sar_dir / "sar.json", sar_doc)

    change_values = {
        "change_hh_db": np.ones((2, 2), dtype=np.float32),
        "change_hv_db": np.full((2, 2), -2.0, dtype=np.float32),
        "change_index": np.array([[0.5, 1.5], [2.5, 3.5]], dtype=np.float32),
    }
    change_outputs = {
        name: _write_raster(change_dir / f"{name}.tif", values)
        for name, values in change_values.items()
    }
    _write_json(
        change_dir / "change.json",
        {
            "change_format_version": 1,
            "source_sar": {"sha256": hashlib.sha256(sar_bytes).hexdigest()},
            "grid": GRID,
            "outputs": change_outputs,
        },
    )

    perimeter_outputs = {
        name: _write_raster(perimeter_dir / name, values)
        for name, values in {
            "perimeter_mask.tif": np.array([[1, 0], [1, 0]], dtype=np.uint8),
            "perimeter_edge.tif": np.zeros((2, 2), dtype=np.uint8),
        }.items()
    }
    _write_json(
        perimeter_dir / "perimeter.json",
        {"perimeter_format_version": 1, "grid": GRID, "outputs": perimeter_outputs},
    )

    web_dir = root / "processed" / "web"
    web_documents = {
        "case.json": {
            "contract_version": "1.2.0",
            "data_status": "real",
            "method": {"id": "abs-logratio-hhhv-v1"},
        },
        "stats.json": {"contract_version": "1.2.0", "data_status": "real"},
        "layers.json": {"contract_version": "1.2.0", "data_status": "real"},
    }
    output_hashes = {
        name: hashlib.sha256(_write_json(web_dir / name, document)).hexdigest()
        for name, document in web_documents.items()
    }
    _write_json(web_dir / "export.json", {"outputs": output_hashes})

    pixel_x, pixel_y = 600005.0, 3974995.0
    lon, lat = transform_coordinates("EPSG:32610", "EPSG:4326", [pixel_x], [pixel_y])
    return root, lon[0], lat[0]


def test_inspection_samples_valid_pixel_and_matches_contract(tmp_path: Path) -> None:
    root, lon, lat = _case_data(tmp_path)
    result = FireTraceRasterService(root).inspect_point(lon, lat)
    schema_path = (
        Path(__file__).resolve().parents[2] / "contracts" / "schemas" / "inspect-point.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(result)

    assert result["valid"] is True
    assert result["pixel"]["row"] == 0
    assert result["pixel"]["col"] == 0
    assert result["hh_db"] == {"t1": -10.0, "t2": -9.0, "delta": 1.0}
    assert result["hv_db"] == {"t1": -20.0, "t2": -22.0, "delta": -2.0}
    assert result["change_index"] == 0.5
    assert result["change_index_percentile"] == pytest.approx(100 / 3)
    assert result["perimeter_relation"] == "inside"


def test_inspection_returns_null_values_for_invalid_pixel(tmp_path: Path) -> None:
    root, _, _ = _case_data(tmp_path)
    lon, lat = transform_coordinates("EPSG:32610", "EPSG:4326", [600015.0], [3974985.0])

    result = FireTraceRasterService(root).inspect_point(lon[0], lat[0])

    assert result["valid"] is False
    assert result["pixel"]["row"] == 1
    assert result["pixel"]["col"] == 1
    assert result["hh_db"] == {"t1": None, "t2": None, "delta": None}
    assert result["change_index"] is None
    assert result["perimeter_relation"] == "outside"


def test_inspection_returns_no_pixel_outside_raster(tmp_path: Path) -> None:
    root, _, _ = _case_data(tmp_path)

    result = FireTraceRasterService(root).inspect_point(0.0, 0.0)

    assert result["valid"] is False
    assert result["pixel"] is None
    assert result["perimeter_relation"] == "unknown"


def test_inspection_returns_no_pixel_for_unprojectable_coordinate(tmp_path: Path) -> None:
    root, _, _ = _case_data(tmp_path)

    result = FireTraceRasterService(root).inspect_point(0.0, 90.0)

    assert result["valid"] is False
    assert result["pixel"] is None
    assert result["perimeter_relation"] == "unknown"


def test_inspection_rejects_raster_checksum_mismatch(tmp_path: Path) -> None:
    root, lon, lat = _case_data(tmp_path)
    raster_path = root / "interim" / "sar" / "t1_hh_db.tif"
    raster_path.write_bytes(raster_path.read_bytes() + b"corrupted")

    with pytest.raises(HTTPException) as error:
        FireTraceRasterService(root).inspect_point(lon, lat)

    assert error.value.status_code == 503


def test_inspection_rejects_malformed_source_sar_manifest(tmp_path: Path) -> None:
    root, lon, lat = _case_data(tmp_path)
    change_path = root / "interim" / "change" / "change.json"
    change_doc = json.loads(change_path.read_text(encoding="utf-8"))
    change_doc["source_sar"] = None
    _write_json(change_path, change_doc)

    with pytest.raises(HTTPException) as error:
        FireTraceRasterService(root).inspect_point(lon, lat)

    assert error.value.status_code == 503


def test_inspection_rejects_invalid_analysis_crs(tmp_path: Path) -> None:
    root, lon, lat = _case_data(tmp_path)
    sar_path = root / "interim" / "sar" / "sar.json"
    sar_doc = json.loads(sar_path.read_text(encoding="utf-8"))
    sar_doc["grid"]["crs"] = "not-a-crs"
    sar_bytes = _write_json(sar_path, sar_doc)
    change_path = root / "interim" / "change" / "change.json"
    change_doc = json.loads(change_path.read_text(encoding="utf-8"))
    change_doc["source_sar"]["sha256"] = hashlib.sha256(sar_bytes).hexdigest()
    change_doc["grid"]["crs"] = "not-a-crs"
    _write_json(change_path, change_doc)
    perimeter_path = root / "interim" / "perimeter" / "perimeter.json"
    perimeter_doc = json.loads(perimeter_path.read_text(encoding="utf-8"))
    perimeter_doc["grid"]["crs"] = "not-a-crs"
    _write_json(perimeter_path, perimeter_doc)

    with pytest.raises(HTTPException) as error:
        FireTraceRasterService(root).inspect_point(lon, lat)

    assert error.value.status_code == 503


@pytest.mark.parametrize("layer_name", ["perimeter_mask.tif", "perimeter_edge.tif"])
def test_inspection_rejects_non_binary_perimeter_layer(tmp_path: Path, layer_name: str) -> None:
    root, lon, lat = _case_data(tmp_path)
    perimeter_dir = root / "interim" / "perimeter"
    record = _write_raster(perimeter_dir / layer_name, np.array([[0, 2], [0, 0]], dtype=np.uint8))
    manifest_path = perimeter_dir / "perimeter.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["outputs"][layer_name] = record
    _write_json(manifest_path, manifest)

    with pytest.raises(HTTPException) as error:
        FireTraceRasterService(root).inspect_point(lon, lat)

    assert error.value.status_code == 503


def test_inspection_includes_verified_terrain_when_available(tmp_path: Path) -> None:
    root, lon, lat = _case_data(tmp_path)
    terrain_dir = root / "interim" / "terrain"
    outputs = {
        f"{name}.tif": _write_raster(terrain_dir / f"{name}.tif", values)
        for name, values in {
            "elevation": np.full((2, 2), 123.5, dtype=np.float32),
            "slope": np.full((2, 2), 12.0, dtype=np.float32),
            "aspect": np.full((2, 2), np.nan, dtype=np.float32),
        }.items()
    }
    _write_json(
        terrain_dir / "terrain.json",
        {"terrain_format_version": 1, "grid": GRID, "outputs": outputs},
    )

    result = FireTraceRasterService(root).inspect_point(lon, lat)

    assert result["terrain"] == {
        "elevation_m": 123.5,
        "slope_deg": 12.0,
        "aspect_deg": None,
    }
    schema_path = (
        Path(__file__).resolve().parents[2] / "contracts" / "schemas" / "inspect-point.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(result)


@pytest.mark.parametrize(
    "fixture_name",
    [
        "inspect-point-inside.json",
        "inspect-point-outside.json",
        "inspect-point-invalid.json",
    ],
)
def test_api_point_fixtures_match_inspection_schema(fixture_name: str) -> None:
    fixture_path = (
        Path(__file__).resolve().parents[2] / "contracts" / "fixtures" / "api" / fixture_name
    )
    schema_path = (
        Path(__file__).resolve().parents[2] / "contracts" / "schemas" / "inspect-point.schema.json"
    )

    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(fixture)


def test_metadata_methods_read_checksum_verified_web_documents(tmp_path: Path) -> None:
    root = tmp_path / "data"
    fixture_dir = Path(__file__).resolve().parents[2] / "contracts" / "fixtures" / "web"
    web_dir = root / "processed" / "web"
    fixture_names = ("case.json", "stats.json", "layers.json")
    output_hashes: dict[str, str] = {}
    for name in fixture_names:
        payload = (fixture_dir / name).read_bytes()
        web_path = web_dir / name
        web_path.parent.mkdir(parents=True, exist_ok=True)
        web_path.write_bytes(payload)
        output_hashes[name] = hashlib.sha256(payload).hexdigest()
    _write_json(web_dir / "export.json", {"outputs": output_hashes})
    service = FireTraceRasterService(root)

    assert service.health() == {"status": "ok", "data_status": "mock"}
    for name, method in (
        ("case.json", service.get_case),
        ("stats.json", service.get_stats),
        ("layers.json", service.get_layers),
    ):
        response = method()
        schema_path = (
            Path(__file__).resolve().parents[2]
            / "contracts"
            / "schemas"
            / name.replace(".json", ".schema.json")
        )
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        Draft202012Validator(schema).validate(response)
        assert response == json.loads((fixture_dir / name).read_text(encoding="utf-8"))
