from __future__ import annotations

import hashlib
import json
import os
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


GENERATION_MANIFESTS = ("sar.json", "change.json", "perimeter.json")


MANIFEST_DIRS = {"highlight_meta.json": "highlight"}


def _manifest_path(root: Path, name: str) -> Path:
    directory = MANIFEST_DIRS.get(name, name.removesuffix(".json"))
    return root / "interim" / directory / name


def _record_inputs(root: Path, names: tuple[str, ...] = GENERATION_MANIFESTS) -> None:
    """Record in export.json the manifests the bundle was built from, as DT-04 does."""
    export_path = root / "processed" / "web" / "export.json"
    export = json.loads(export_path.read_text(encoding="utf-8"))
    export["inputs"] = {
        name: hashlib.sha256(_manifest_path(root, name).read_bytes()).hexdigest() for name in names
    }
    _write_json(export_path, export)


def _write_terrain(
    root: Path,
    slope: np.ndarray | None = None,
    layover_shadow: np.ndarray | None = None,
) -> None:
    terrain_dir = root / "interim" / "terrain"
    outputs = {
        f"{name}.tif": _write_raster(terrain_dir / f"{name}.tif", values)
        for name, values in {
            "elevation": np.full((2, 2), 123.5, dtype=np.float32),
            "slope": np.full((2, 2), 12.0, dtype=np.float32) if slope is None else slope,
            "aspect": np.full((2, 2), np.nan, dtype=np.float32),
            "layover_shadow": (
                np.zeros((2, 2), dtype=np.uint8) if layover_shadow is None else layover_shadow
            ),
        }.items()
    }
    _write_json(
        terrain_dir / "terrain.json",
        {"terrain_format_version": 1, "grid": GRID, "outputs": outputs},
    )


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
            "data_status": "mock",
            "method": {"id": "abs-logratio-hhhv-v1"},
        },
        "stats.json": {"contract_version": "1.2.0", "data_status": "mock"},
        "layers.json": {"contract_version": "1.2.0", "data_status": "mock"},
    }
    output_hashes = {
        name: hashlib.sha256(_write_json(web_dir / name, document)).hexdigest()
        for name, document in web_documents.items()
    }
    _write_json(web_dir / "export.json", {"outputs": output_hashes})
    _record_inputs(root)

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
    _record_inputs(root)

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
    _record_inputs(root)

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
    _record_inputs(root)

    with pytest.raises(HTTPException) as error:
        FireTraceRasterService(root).inspect_point(lon, lat)

    assert error.value.status_code == 503


def test_inspection_includes_verified_terrain_when_available(tmp_path: Path) -> None:
    root, lon, lat = _case_data(tmp_path)
    _write_terrain(root)
    _record_inputs(root, (*GENERATION_MANIFESTS, "terrain.json"))

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


def _wgs84(x: float, y: float) -> tuple[float, float]:
    lon, lat = transform_coordinates("EPSG:32610", "EPSG:4326", [x], [y])
    return float(lon[0]), float(lat[0])


def _profile_schema() -> dict[str, Any]:
    path = Path(__file__).resolve().parents[2] / "contracts" / "schemas" / "profile.schema.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _assert_profile_contract(result: dict[str, Any]) -> None:
    Draft202012Validator(_profile_schema()).validate(result)


def test_profile_samples_the_transect_and_matches_contract(tmp_path: Path) -> None:
    root, _, _ = _case_data(tmp_path)
    line = [_wgs84(600000.0, 3974995.0), _wgs84(600020.0, 3974995.0)]

    result = FireTraceRasterService(root).inspect_profile(line, spacing_m=10.0)
    _assert_profile_contract(result)

    assert result["contract_version"] == "1.2.0"
    assert result["data_status"] == "mock"
    assert result["line"] == [list(point) for point in line]
    assert result["length_m"] == pytest.approx(20.0, abs=1e-6)
    assert result["spacing_m"] == 10.0
    assert result["truncated"] is False
    assert [sample["distance_m"] for sample in result["samples"]] == pytest.approx(
        [0.0, 10.0, 20.0]
    )
    first, second, outside = result["samples"]
    assert first["valid"] is True
    assert (first["hh_t1"], first["hh_t2"], first["hv_t1"], first["hv_t2"]) == (
        -10.0,
        -9.0,
        -20.0,
        -22.0,
    )
    assert first["change_index"] == 0.5
    assert first["inside_perimeter"] is True
    assert (first["lon"], first["lat"]) == pytest.approx(line[0], abs=1e-9)
    assert second["valid"] is True
    assert second["inside_perimeter"] is False
    assert (outside["valid"], outside["inside_perimeter"], outside["elevation_m"]) == (
        False,
        None,
        None,
    )
    assert result["perimeter_crossings_m"] == pytest.approx([10.0], abs=1.0)


def test_profile_includes_the_final_endpoint_once(tmp_path: Path) -> None:
    root, _, _ = _case_data(tmp_path)
    line = [_wgs84(600000.0, 3974995.0), _wgs84(600025.0, 3974995.0)]

    result = FireTraceRasterService(root).inspect_profile(line, spacing_m=10.0)

    assert result["length_m"] == pytest.approx(25.0, abs=1e-6)
    assert [sample["distance_m"] for sample in result["samples"]] == pytest.approx(
        [0.0, 10.0, 20.0, 25.0]
    )
    assert result["truncated"] is False


def test_profile_walks_polyline_vertices_by_arc_length(tmp_path: Path) -> None:
    root, _, _ = _case_data(tmp_path)
    corner = _wgs84(600010.0, 3974995.0)
    end = _wgs84(600010.0, 3974985.0)
    line = [_wgs84(600000.0, 3974995.0), corner, end]

    result = FireTraceRasterService(root).inspect_profile(line, spacing_m=10.0)

    assert result["length_m"] == pytest.approx(20.0, abs=1e-6)
    assert [sample["distance_m"] for sample in result["samples"]] == pytest.approx(
        [0.0, 10.0, 20.0]
    )
    last = result["samples"][-1]
    assert (last["lon"], last["lat"]) == pytest.approx(end, abs=1e-9)


def test_profile_keeps_masked_samples_with_null_values(tmp_path: Path) -> None:
    root, _, _ = _case_data(tmp_path)
    line = [_wgs84(600010.0, 3974985.0), _wgs84(600020.0, 3974985.0)]

    result = FireTraceRasterService(root).inspect_profile(line, spacing_m=10.0)
    masked = result["samples"][0]

    assert masked["valid"] is False
    assert masked["inside_perimeter"] is False
    assert masked["elevation_m"] is None
    assert (
        masked["hh_t1"],
        masked["hh_t2"],
        masked["hv_t1"],
        masked["hv_t2"],
        masked["change_index"],
    ) == (None,) * 5
    assert result["perimeter_crossings_m"] == []


def test_profile_keeps_positions_outside_the_analysis_grid(tmp_path: Path) -> None:
    root, _, _ = _case_data(tmp_path)
    line = [[0.0, 35.9], [0.001, 35.9]]

    result = FireTraceRasterService(root).inspect_profile(line, spacing_m=10.0)

    assert result["length_m"] > 0
    assert result["samples"]
    assert all(sample["valid"] is False for sample in result["samples"])
    assert all(sample["inside_perimeter"] is None for sample in result["samples"])
    assert result["perimeter_crossings_m"] == []
    _assert_profile_contract(result)


def test_profile_includes_verified_terrain_elevation(tmp_path: Path) -> None:
    root, _, _ = _case_data(tmp_path)
    _write_terrain(root)
    _record_inputs(root, (*GENERATION_MANIFESTS, "terrain.json"))
    line = [_wgs84(600000.0, 3974995.0), _wgs84(600020.0, 3974995.0)]

    result = FireTraceRasterService(root).inspect_profile(line, spacing_m=10.0)

    assert [sample["elevation_m"] for sample in result["samples"]] == [123.5, 123.5, None]
    _assert_profile_contract(result)


def test_profile_truncates_at_the_contract_sample_limit(tmp_path: Path) -> None:
    root, _, _ = _case_data(tmp_path)
    line = [_wgs84(600000.0, 3974995.0), _wgs84(600020.0, 3974995.0)]

    result = FireTraceRasterService(root).inspect_profile(line, spacing_m=0.01)

    assert result["truncated"] is True
    assert len(result["samples"]) == 2000
    assert result["length_m"] == pytest.approx(20.0, abs=1e-6)
    assert result["samples"][-1]["distance_m"] == pytest.approx(19.99, abs=1e-6)
    assert result["samples"][0]["hh_t1"] == result["samples"][1]["hh_t1"]
    _assert_profile_contract(result)


def test_profile_rejects_a_zero_length_line(tmp_path: Path) -> None:
    root, _, _ = _case_data(tmp_path)
    point = _wgs84(600000.0, 3974995.0)

    with pytest.raises(HTTPException) as error:
        FireTraceRasterService(root).inspect_profile([point, point], spacing_m=10.0)

    assert error.value.status_code == 422


def test_profile_rejects_corrupt_products(tmp_path: Path) -> None:
    root, _, _ = _case_data(tmp_path)
    raster_path = root / "interim" / "change" / "change_index.tif"
    raster_path.write_bytes(raster_path.read_bytes() + b"corrupted")
    line = [_wgs84(600000.0, 3974995.0), _wgs84(600010.0, 3974995.0)]

    with pytest.raises(HTTPException) as error:
        FireTraceRasterService(root).inspect_profile(line, spacing_m=10.0)

    assert error.value.status_code == 503


@pytest.mark.parametrize("failure", ["unsupported-version", "wrong-crs", "wrong-pixel-size"])
def test_profile_rejects_incompatible_products(tmp_path: Path, failure: str) -> None:
    root, _, _ = _case_data(tmp_path)
    interim = root / "interim"
    manifests = (
        (interim / "sar" / "sar.json", "sar_format_version"),
        (interim / "change" / "change.json", "change_format_version"),
        (interim / "perimeter" / "perimeter.json", "perimeter_format_version"),
    )
    if failure == "unsupported-version":
        path, version_key = manifests[0]
        document = json.loads(path.read_text(encoding="utf-8"))
        document[version_key] = 2
        _write_json(path, document)
    else:
        for path, _ in manifests:
            document = json.loads(path.read_text(encoding="utf-8"))
            if failure == "wrong-crs":
                document["grid"]["crs"] = "EPSG:3857"
            else:
                document["grid"]["transform"][0] = 5.0
            _write_json(path, document)
        change_path = interim / "change" / "change.json"
        change_doc = json.loads(change_path.read_text(encoding="utf-8"))
        change_doc["source_sar"]["sha256"] = hashlib.sha256(
            (interim / "sar" / "sar.json").read_bytes()
        ).hexdigest()
        _write_json(change_path, change_doc)
    _record_inputs(root)
    line = [_wgs84(600000.0, 3974995.0), _wgs84(600010.0, 3974995.0)]

    with pytest.raises(HTTPException) as error:
        FireTraceRasterService(root).inspect_profile(line, spacing_m=10.0)

    assert error.value.status_code == 503


def test_profile_fixture_matches_profile_schema() -> None:
    fixture_path = (
        Path(__file__).resolve().parents[2]
        / "contracts"
        / "fixtures"
        / "api"
        / "profile-example.json"
    )

    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    Draft202012Validator(_profile_schema()).validate(fixture)


@pytest.mark.parametrize("spacing_m", [0.0, -1.0, float("inf"), float("nan")])
def test_profile_rejects_invalid_spacing(spacing_m: float, tmp_path: Path) -> None:
    root, _, _ = _case_data(tmp_path)
    line = [_wgs84(600000.0, 3974995.0), _wgs84(600010.0, 3974995.0)]

    with pytest.raises(HTTPException) as error:
        FireTraceRasterService(root).inspect_profile(line, spacing_m=spacing_m)

    assert error.value.status_code == 422


# --------------------------------------------------------------------------- EV-01 hardening

NON_UTF8_JSON = b'{"name": "\xff\xfe"}'


def _assert_503(call: Any, *args: Any, match: str | None = None) -> None:
    with pytest.raises(HTTPException) as error:
        call(*args)
    assert error.value.status_code == 503
    if match is not None:
        assert match in str(error.value.detail)


def test_non_utf8_export_json_is_unavailable(tmp_path: Path) -> None:
    root, lon, lat = _case_data(tmp_path)
    (root / "processed" / "web" / "export.json").write_bytes(NON_UTF8_JSON)
    service = FireTraceRasterService(root)

    _assert_503(service.get_case)
    _assert_503(service.inspect_point, lon, lat)


def test_non_utf8_case_json_is_unavailable(tmp_path: Path) -> None:
    root, lon, lat = _case_data(tmp_path)
    web_dir = root / "processed" / "web"
    (web_dir / "case.json").write_bytes(NON_UTF8_JSON)
    export_path = web_dir / "export.json"
    export = json.loads(export_path.read_text(encoding="utf-8"))
    export["outputs"]["case.json"] = hashlib.sha256(NON_UTF8_JSON).hexdigest()
    _write_json(export_path, export)
    service = FireTraceRasterService(root)

    _assert_503(service.get_case)
    _assert_503(service.inspect_point, lon, lat)


@pytest.mark.parametrize("name", GENERATION_MANIFESTS)
def test_non_utf8_interim_manifest_is_unavailable(tmp_path: Path, name: str) -> None:
    root, lon, lat = _case_data(tmp_path)
    _manifest_path(root, name).write_bytes(NON_UTF8_JSON)
    _record_inputs(root)

    _assert_503(FireTraceRasterService(root).inspect_point, lon, lat)


def test_non_utf8_recorded_terrain_manifest_is_unavailable(tmp_path: Path) -> None:
    root, lon, lat = _case_data(tmp_path)
    _write_terrain(root)
    _manifest_path(root, "terrain.json").write_bytes(NON_UTF8_JSON)
    _record_inputs(root, (*GENERATION_MANIFESTS, "terrain.json"))

    _assert_503(FireTraceRasterService(root).inspect_point, lon, lat)


def test_matching_generation_serves_inspection_and_caches_products(tmp_path: Path) -> None:
    root, lon, lat = _case_data(tmp_path)
    service = FireTraceRasterService(root)

    result = service.inspect_point(lon, lat)

    assert result["valid"] is True
    assert "terrain" not in result
    assert service._load_products() is service._load_products()


@pytest.mark.parametrize("name", GENERATION_MANIFESTS)
def test_bundle_from_a_different_run_is_unavailable(tmp_path: Path, name: str) -> None:
    root, lon, lat = _case_data(tmp_path)
    export_path = root / "processed" / "web" / "export.json"
    export = json.loads(export_path.read_text(encoding="utf-8"))
    export["inputs"][name] = "0" * 64
    _write_json(export_path, export)
    service = FireTraceRasterService(root)

    _assert_503(service.inspect_point, lon, lat, match="different pipeline runs")
    line = [_wgs84(600000.0, 3974995.0), _wgs84(600010.0, 3974995.0)]
    with pytest.raises(HTTPException) as error:
        service.inspect_profile(line, spacing_m=10.0)
    assert error.value.status_code == 503


@pytest.mark.parametrize("name", GENERATION_MANIFESTS)
def test_bundle_without_input_record_is_unavailable(tmp_path: Path, name: str) -> None:
    root, lon, lat = _case_data(tmp_path)
    _record_inputs(root, tuple(other for other in GENERATION_MANIFESTS if other != name))

    _assert_503(FireTraceRasterService(root).inspect_point, lon, lat, match=name)


def test_bundle_without_inputs_object_is_unavailable(tmp_path: Path) -> None:
    root, lon, lat = _case_data(tmp_path)
    export_path = root / "processed" / "web" / "export.json"
    export = json.loads(export_path.read_text(encoding="utf-8"))
    del export["inputs"]
    _write_json(export_path, export)

    _assert_503(FireTraceRasterService(root).inspect_point, lon, lat)


def test_recorded_terrain_must_match_the_interim_manifest(tmp_path: Path) -> None:
    root, lon, lat = _case_data(tmp_path)
    _write_terrain(root)
    _record_inputs(root, (*GENERATION_MANIFESTS, "terrain.json"))
    terrain_path = _manifest_path(root, "terrain.json")
    terrain = json.loads(terrain_path.read_text(encoding="utf-8"))
    terrain["note"] = "re-run after the export"
    _write_json(terrain_path, terrain)

    _assert_503(
        FireTraceRasterService(root).inspect_point, lon, lat, match="different pipeline runs"
    )


def test_recorded_terrain_must_exist(tmp_path: Path) -> None:
    root, lon, lat = _case_data(tmp_path)
    _write_terrain(root)
    _record_inputs(root, (*GENERATION_MANIFESTS, "terrain.json"))
    _manifest_path(root, "terrain.json").unlink()
    service = FireTraceRasterService(root)
    line = [_wgs84(600000.0, 3974995.0), _wgs84(600010.0, 3974995.0)]

    for call, args in (
        (service.inspect_point, (lon, lat)),
        (service.inspect_profile, (line, 10.0)),
    ):
        _assert_503(call, *args, match="export.json records it but the interim file is missing")


@pytest.mark.parametrize(
    "methods", [("stat", "read_bytes"), ("is_file", "read_bytes"), ("read_bytes",)]
)
def test_unreadable_recorded_terrain_is_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, methods: tuple[str, ...]
) -> None:
    """A recorded terrain.json that becomes inaccessible is a 503, not an unhandled 500."""
    root, lon, lat = _case_data(tmp_path)
    _write_terrain(root)
    _record_inputs(root, (*GENERATION_MANIFESTS, "terrain.json"))
    terrain_path = _manifest_path(root, "terrain.json")

    def denied(method: str) -> Any:
        original = getattr(Path, method)

        def deny_terrain(self: Path, *args: Any, **kwargs: Any) -> Any:
            if self == terrain_path:
                raise PermissionError(13, "Permission denied", str(self))
            return original(self, *args, **kwargs)

        return deny_terrain

    for method in methods:
        monkeypatch.setattr(Path, method, denied(method))
    service = FireTraceRasterService(root)
    line = [_wgs84(600000.0, 3974995.0), _wgs84(600010.0, 3974995.0)]

    _assert_503(service.inspect_point, lon, lat, match="terrain.json")
    _assert_503(service.inspect_profile, line, 10.0, match="terrain.json")


def test_unrecorded_terrain_is_not_served(tmp_path: Path) -> None:
    root, lon, lat = _case_data(tmp_path)
    _write_terrain(root)
    service = FireTraceRasterService(root)

    result = service.inspect_point(lon, lat)
    line = [_wgs84(600000.0, 3974995.0), _wgs84(600020.0, 3974995.0)]
    profile = service.inspect_profile(line, spacing_m=10.0)

    assert result["valid"] is True
    assert "terrain" not in result
    assert [sample["elevation_m"] for sample in profile["samples"]] == [None, None, None]


def test_replacing_export_json_invalidates_cached_products(tmp_path: Path) -> None:
    root, lon, lat = _case_data(tmp_path)
    service = FireTraceRasterService(root)
    assert service.inspect_point(lon, lat)["valid"] is True

    export_path = root / "processed" / "web" / "export.json"
    export = json.loads(export_path.read_text(encoding="utf-8"))
    export["inputs"]["sar.json"] = "0" * 64
    export["generated_at"] = "2026-11-15T00:00:00Z"
    _write_json(export_path, export)

    _assert_503(service.inspect_point, lon, lat, match="different pipeline runs")


# ------------------------------------------------------- EV-01 one export snapshot per request


def _publish_generation_b(root: Path) -> None:
    """Republish the bundle as a later run: real case metadata and recorded terrain.

    The SAR, change and perimeter manifests keep their bytes, so a response built from
    generation A's export is still fully consistent with generation A.
    """
    web_dir = root / "processed" / "web"
    case_bytes = _write_json(
        web_dir / "case.json",
        {
            "contract_version": "1.2.0",
            "data_status": "real",
            "method": {"id": "generation-b-method"},
        },
    )
    export_path = web_dir / "export.json"
    export = json.loads(export_path.read_text(encoding="utf-8"))
    export["outputs"]["case.json"] = hashlib.sha256(case_bytes).hexdigest()
    _write_json(export_path, export)
    _write_terrain(root)
    _record_inputs(root, (*GENERATION_MANIFESTS, "terrain.json"))


def _publish_b_after_case_is_read(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    """Republish generation B right after the request has read case.json once."""
    import api.raster as raster_module

    original = raster_module.read_verified
    published: list[bool] = []

    def read_then_publish(path: Path, *args: Any, **kwargs: Any) -> bytes:
        payload = original(path, *args, **kwargs)
        if path.name == "case.json" and not published:
            published.append(True)
            _publish_generation_b(root)
        return payload

    monkeypatch.setattr(raster_module, "read_verified", read_then_publish)


def _assert_one_generation(data_status: str, method_id: str | None, has_terrain: bool) -> None:
    if data_status == "mock":
        assert (method_id, has_terrain) in {("abs-logratio-hhhv-v1", False), (None, False)}
    else:
        assert (data_status, has_terrain) == ("real", True)
        assert method_id in {"generation-b-method", None}


def test_point_inspection_uses_one_export_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, lon, lat = _case_data(tmp_path)
    _publish_b_after_case_is_read(monkeypatch, root)

    try:
        result = FireTraceRasterService(root).inspect_point(lon, lat)
    except HTTPException as error:
        assert error.status_code == 503
        return
    _assert_one_generation(result["data_status"], result["method_id"], "terrain" in result)


def test_profile_inspection_uses_one_export_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _, _ = _case_data(tmp_path)
    _publish_b_after_case_is_read(monkeypatch, root)
    line = [_wgs84(600000.0, 3974995.0), _wgs84(600010.0, 3974995.0)]

    try:
        result = FireTraceRasterService(root).inspect_profile(line, spacing_m=10.0)
    except HTTPException as error:
        assert error.status_code == 503
        return
    elevations = {sample["elevation_m"] for sample in result["samples"]}
    _assert_one_generation(result["data_status"], None, elevations != {None})


def test_restored_generation_never_serves_products_cached_from_another(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Generation B lands while a request is checking A; A is then restored byte-for-byte.

    A stat-sampled cache key would still describe A while the products were parsed from
    B, so the restored A would serve B's terrain.
    """
    root, lon, lat = _case_data(tmp_path)
    _write_terrain(root)  # on disk but not recorded by generation A
    web_dir = root / "processed" / "web"
    terrain_manifest = _manifest_path(root, "terrain.json")
    restore = {
        path: (path.read_bytes(), path.stat())
        for path in (web_dir / "export.json", web_dir / "case.json", terrain_manifest)
    }
    original_stat = Path.stat
    original_read_json = FireTraceRasterService._read_json
    published: list[bool] = []

    def publish_once() -> None:
        if not published:
            published.append(True)
            _publish_generation_b(root)

    def stat_then_publish(self: Path, *args: Any, **kwargs: Any) -> Any:
        try:
            return original_stat(self, *args, **kwargs)
        finally:
            if self.name == "terrain.json":
                publish_once()

    def publish_then_read(path: Path, source: str) -> tuple[dict[str, Any], str]:
        if path.name == "sar.json":
            publish_once()
        return original_read_json(path, source)

    monkeypatch.setattr(Path, "stat", stat_then_publish)
    monkeypatch.setattr(FireTraceRasterService, "_read_json", staticmethod(publish_then_read))
    service = FireTraceRasterService(root)
    try:
        service.inspect_point(lon, lat)
    except HTTPException as error:
        assert error.status_code == 503
    assert published
    monkeypatch.undo()

    for path, (payload, stat) in restore.items():
        path.write_bytes(payload)
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))

    result = service.inspect_point(lon, lat)

    assert result["data_status"] == "mock"
    assert result["valid"] is True
    assert "terrain" not in result


# ------------------------------------------- EV-01/EV-02 caveats and the XP-01 highlight


def _inspect_schema() -> dict[str, Any]:
    path = (
        Path(__file__).resolve().parents[2] / "contracts" / "schemas" / "inspect-point.schema.json"
    )
    return json.loads(path.read_text(encoding="utf-8"))


def _fixture(name: str) -> dict[str, Any]:
    path = Path(__file__).resolve().parents[2] / "contracts" / "fixtures" / "api" / name
    return json.loads(path.read_text(encoding="utf-8"))


def _inspect(root: Path, row: int, col: int) -> dict[str, Any]:
    """Inspect the centre of analysis pixel (row, col) and check the response contract."""
    lon, lat = _wgs84(600005.0 + 10.0 * col, 3974995.0 - 10.0 * row)
    result = FireTraceRasterService(root).inspect_point(lon, lat)
    Draft202012Validator(_inspect_schema()).validate(result)
    assert result["pixel"]["row"] == row
    assert result["pixel"]["col"] == col
    return result


def _caveats_by_id(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["id"]: item for item in result["caveats"]}


def _with_terrain(
    root: Path,
    slope: np.ndarray | None = None,
    layover_shadow: np.ndarray | None = None,
    extra: tuple[str, ...] = (),
) -> None:
    _write_terrain(root, slope, layover_shadow)
    _record_inputs(root, (*GENERATION_MANIFESTS, "terrain.json", *extra))


def _set_perimeter_edge(root: Path, edge: np.ndarray) -> None:
    perimeter_dir = root / "interim" / "perimeter"
    record = _write_raster(perimeter_dir / "perimeter_edge.tif", edge)
    manifest_path = perimeter_dir / "perimeter.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["outputs"]["perimeter_edge.tif"] = record
    _write_json(manifest_path, manifest)


def _weather_document(**overrides: Any) -> dict[str, Any]:
    document: dict[str, Any] = {
        "contract_version": "1.2.0",
        "data_status": "mock",
        "period": {"start": "2026-08-16", "end": "2026-10-03"},
        "last_rain_before_t2": "2026-09-30",
    }
    document.update(overrides)
    return document


def _publish_weather(root: Path, document: dict[str, Any]) -> Path:
    """Publish weather.json and record its exact bytes in export.json outputs."""
    web_dir = root / "processed" / "web"
    payload = _write_json(web_dir / "weather.json", document)
    export_path = web_dir / "export.json"
    export = json.loads(export_path.read_text(encoding="utf-8"))
    export["outputs"]["weather.json"] = hashlib.sha256(payload).hexdigest()
    _write_json(export_path, export)
    return web_dir / "weather.json"


HIGHLIGHT_MASK = np.array([[1, 0], [1, 255]], dtype=np.uint8)


def _write_highlight(root: Path, mask: np.ndarray = HIGHLIGHT_MASK) -> None:
    highlight_dir = root / "interim" / "highlight"
    record = _write_raster(highlight_dir / "highlight_mask.tif", mask)
    _write_json(
        highlight_dir / "highlight_meta.json",
        {
            "highlight_format_version": 1,
            "grid": GRID,
            "outputs": {"highlight_mask.tif": record},
        },
    )


def _with_highlight(root: Path, mask: np.ndarray = HIGHLIGHT_MASK) -> None:
    _write_highlight(root, mask)
    _record_inputs(root, (*GENERATION_MANIFESTS, "highlight_meta.json"))


def test_benign_pixel_returns_the_contract_fixture_caveats(tmp_path: Path) -> None:
    """Slope <= 30, no layover, no edge, no weather: exactly the fixture's generic caveats."""
    root, _, _ = _case_data(tmp_path)
    _with_terrain(root)

    result = _inspect(root, 0, 0)

    assert result["caveats"] == _fixture("inspect-point-inside.json")["caveats"]
    assert result["highlighted"] is None


def test_steep_slope_pixel_lists_the_slope_value(tmp_path: Path) -> None:
    root, _, _ = _case_data(tmp_path)
    _with_terrain(root, slope=np.array([[34.25, 30.0], [12.0, 12.0]], dtype=np.float32))

    steep = _caveats_by_id(_inspect(root, 0, 0))
    at_threshold = _caveats_by_id(_inspect(root, 0, 1))

    assert steep["steep_slope"]["triggered"] is True
    assert "34.2° > 30°" in steep["steep_slope"]["reason"]
    assert "steep_slope" not in at_threshold


def test_nan_slope_is_unknown_and_not_listed(tmp_path: Path) -> None:
    root, _, _ = _case_data(tmp_path)
    _with_terrain(root, slope=np.full((2, 2), np.nan, dtype=np.float32))

    assert "steep_slope" not in _caveats_by_id(_inspect(root, 0, 0))


def test_layover_and_unknown_geometry_caveats(tmp_path: Path) -> None:
    root, _, _ = _case_data(tmp_path)
    _with_terrain(root, layover_shadow=np.array([[1, 255], [2, 0]], dtype=np.uint8))

    layover = _caveats_by_id(_inspect(root, 0, 0))["radar_shadow_layover"]
    unknown = _caveats_by_id(_inspect(root, 0, 1))["radar_shadow_layover"]
    shadow = _caveats_by_id(_inspect(root, 1, 0))["radar_shadow_layover"]

    assert layover["triggered"] is True
    assert "layover" in layover["reason"]
    assert shadow["triggered"] is True
    assert "shadow" in shadow["reason"]
    assert unknown["triggered"] is False
    assert "unknown" in unknown["reason"]


def test_layover_shadow_with_an_unknown_code_is_unavailable(tmp_path: Path) -> None:
    root, lon, lat = _case_data(tmp_path)
    _with_terrain(root, layover_shadow=np.array([[3, 0], [0, 0]], dtype=np.uint8))

    _assert_503(FireTraceRasterService(root).inspect_point, lon, lat, match="layover_shadow")


def test_edge_band_pixel_lists_near_perimeter_edge(tmp_path: Path) -> None:
    root, _, _ = _case_data(tmp_path)
    _set_perimeter_edge(root, np.array([[1, 0], [0, 0]], dtype=np.uint8))
    _record_inputs(root)

    edge = _caveats_by_id(_inspect(root, 0, 0))
    away = _caveats_by_id(_inspect(root, 0, 1))

    assert edge["near_perimeter_edge"]["triggered"] is True
    assert "near_perimeter_edge" not in away


def test_without_terrain_slope_is_absent_and_geometry_unknown(tmp_path: Path) -> None:
    root, _, _ = _case_data(tmp_path)

    caveats = _caveats_by_id(_inspect(root, 0, 0))

    assert "steep_slope" not in caveats
    assert caveats["radar_shadow_layover"]["triggered"] is False
    assert "unknown" in caveats["radar_shadow_layover"]["reason"]


def test_recent_rain_before_t2_triggers_soil_moisture(tmp_path: Path) -> None:
    root, _, _ = _case_data(tmp_path)
    _with_terrain(root)
    _publish_weather(root, _weather_document())

    soil = _caveats_by_id(_inspect(root, 0, 0))["soil_moisture_change"]

    assert soil["triggered"] is True
    assert "2026-09-30" in soil["reason"]
    assert "3 day(s)" in soil["reason"]
    assert "MOCK weather data." in soil["reason"]


def test_unpublished_weather_keeps_the_generic_soil_moisture_caution(tmp_path: Path) -> None:
    root, _, _ = _case_data(tmp_path)
    _with_terrain(root)
    # On disk but not listed in export.json outputs: not part of this bundle.
    (root / "processed" / "web" / "weather.json").write_bytes(
        json.dumps(_weather_document()).encode("utf-8")
    )

    result = _inspect(root, 0, 0)

    assert result["caveats"] == _fixture("inspect-point-inside.json")["caveats"]


def test_tampered_weather_is_unavailable(tmp_path: Path) -> None:
    root, lon, lat = _case_data(tmp_path)
    path = _publish_weather(root, _weather_document())
    path.write_bytes(path.read_bytes() + b" ")

    _assert_503(FireTraceRasterService(root).inspect_point, lon, lat, match="weather.json")


@pytest.mark.parametrize(
    "overrides",
    [
        {"period": {"start": "2026-08-16"}},
        {"period": {"start": "2026-08-16", "end": "not-a-date"}},
        {"last_rain_before_t2": "yesterday"},
        {"last_rain_before_t2": 5},
        {"data_status": "synthetic"},
        {"period": None},
        {"last_rain_before_t2": "2026-10-03"},  # rain on t2 breaks the rule's precondition
    ],
)
def test_malformed_weather_is_unavailable(tmp_path: Path, overrides: dict[str, Any]) -> None:
    root, lon, lat = _case_data(tmp_path)
    _publish_weather(root, _weather_document(**overrides))

    _assert_503(FireTraceRasterService(root).inspect_point, lon, lat, match="weather.json")


def test_out_of_range_slope_is_unavailable(tmp_path: Path) -> None:
    root, lon, lat = _case_data(tmp_path)
    _with_terrain(root, slope=np.full((2, 2), 95.0, dtype=np.float32))

    _assert_503(FireTraceRasterService(root).inspect_point, lon, lat)


def test_invalid_pixel_has_no_caveats_even_with_triggers(tmp_path: Path) -> None:
    root, _, _ = _case_data(tmp_path)
    _set_perimeter_edge(root, np.ones((2, 2), dtype=np.uint8))
    _with_terrain(
        root,
        slope=np.full((2, 2), 45.0, dtype=np.float32),
        layover_shadow=np.ones((2, 2), dtype=np.uint8),
    )
    _publish_weather(root, _weather_document())

    result = _inspect(root, 1, 1)

    assert result["valid"] is False
    assert result["caveats"] == []
    assert result["highlighted"] is None


def test_recorded_highlight_is_sampled_for_valid_pixels(tmp_path: Path) -> None:
    root, _, _ = _case_data(tmp_path)
    _with_highlight(root)

    assert _inspect(root, 0, 0)["highlighted"] is True
    assert _inspect(root, 0, 1)["highlighted"] is False
    assert _inspect(root, 1, 0)["highlighted"] is True
    assert _inspect(root, 1, 1)["highlighted"] is None


def test_highlight_outside_the_grid_is_null(tmp_path: Path) -> None:
    root, _, _ = _case_data(tmp_path)
    _with_highlight(root)

    result = FireTraceRasterService(root).inspect_point(0.0, 0.0)

    assert result["pixel"] is None
    assert result["highlighted"] is None


def test_unrecorded_highlight_is_null(tmp_path: Path) -> None:
    root, _, _ = _case_data(tmp_path)
    _write_highlight(root)  # on disk but not recorded by this bundle

    assert _inspect(root, 0, 0)["highlighted"] is None


def test_highlight_meta_from_another_run_is_unavailable(tmp_path: Path) -> None:
    root, lon, lat = _case_data(tmp_path)
    _with_highlight(root)
    meta_path = _manifest_path(root, "highlight_meta.json")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["note"] = "re-run after the export"
    _write_json(meta_path, meta)

    _assert_503(
        FireTraceRasterService(root).inspect_point, lon, lat, match="different pipeline runs"
    )


def test_missing_recorded_highlight_meta_is_unavailable(tmp_path: Path) -> None:
    root, lon, lat = _case_data(tmp_path)
    _with_highlight(root)
    _manifest_path(root, "highlight_meta.json").unlink()

    _assert_503(FireTraceRasterService(root).inspect_point, lon, lat, match="highlight_meta.json")


@pytest.mark.parametrize(
    "mask",
    [
        np.array([[1, 255], [1, 255]], dtype=np.uint8),  # 255 on a valid pixel
        np.array([[1, 0], [1, 0]], dtype=np.uint8),  # not 255 on the invalid pixel
        np.array([[2, 0], [1, 255]], dtype=np.uint8),  # value outside 0/1/255
    ],
)
def test_highlight_mask_must_follow_the_valid_mask(tmp_path: Path, mask: np.ndarray) -> None:
    root, lon, lat = _case_data(tmp_path)
    _with_highlight(root, mask)

    _assert_503(FireTraceRasterService(root).inspect_point, lon, lat, match="highlight_mask.tif")


def test_corrupt_highlight_mask_is_unavailable(tmp_path: Path) -> None:
    root, lon, lat = _case_data(tmp_path)
    _with_highlight(root)
    path = root / "interim" / "highlight" / "highlight_mask.tif"
    path.write_bytes(path.read_bytes() + b"corrupted")

    _assert_503(FireTraceRasterService(root).inspect_point, lon, lat)


def test_highlight_is_cached_with_the_products_by_content(tmp_path: Path) -> None:
    root, _, _ = _case_data(tmp_path)
    _with_highlight(root)
    service = FireTraceRasterService(root)
    lon, lat = _wgs84(600015.0, 3974995.0)
    assert service.inspect_point(lon, lat)["highlighted"] is False
    assert service._load_products() is service._load_products()

    _with_highlight(root, np.array([[1, 1], [1, 255]], dtype=np.uint8))

    assert service.inspect_point(lon, lat)["highlighted"] is True


def test_profile_output_is_unchanged_by_caveat_inputs(tmp_path: Path) -> None:
    root, _, _ = _case_data(tmp_path)
    _write_highlight(root)
    _write_terrain(root, layover_shadow=np.ones((2, 2), dtype=np.uint8))
    _record_inputs(root, (*GENERATION_MANIFESTS, "terrain.json", "highlight_meta.json"))
    _publish_weather(root, _weather_document())
    line = [_wgs84(600000.0, 3974995.0), _wgs84(600020.0, 3974995.0)]

    result = FireTraceRasterService(root).inspect_profile(line, spacing_m=10.0)

    _assert_profile_contract(result)
    assert all(
        "caveats" not in sample and "highlighted" not in sample for sample in result["samples"]
    )
