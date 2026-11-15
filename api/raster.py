"""Verified access to FireTrace web metadata and numerical raster products."""

from __future__ import annotations

import hashlib
import json
import math
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import HTTPException
from rasterio.crs import CRS
from rasterio.errors import CRSError, TransformError
from rasterio.transform import rowcol, xy
from rasterio.warp import transform as transform_coordinates

from pipeline.publishing import PublishError, input_file, read_verified, read_verified_raster

CONTRACT_VERSION = "1.2.0"
FORMAT_VERSIONS = {
    "sar_format_version": 1,
    "change_format_version": 1,
    "perimeter_format_version": 1,
}
ANALYSIS_CRS = CRS.from_epsg(32610)
ANALYSIS_PIXEL_SIZE_M = 10.0


@dataclass(frozen=True)
class RasterLayer:
    """One manifest-verified single-band analysis raster."""

    data: np.ndarray
    crs: CRS
    transform: Any
    width: int
    height: int
    dtype: str


@dataclass(frozen=True)
class InspectionProducts:
    """Numerical arrays from one consistent SAR/change/perimeter generation."""

    grid: dict[str, Any]
    sar: dict[str, Any]
    change: dict[str, Any]
    perimeter: dict[str, Any]
    layers: dict[str, RasterLayer]


class FireTraceRasterService:
    """Serve contract JSON and inspect pixels from checksummed pipeline COGs.

    ``data_root`` contains ``interim/`` and ``processed/web/``. The default is the
    repository's ``data/`` directory; ``FIRETRACE_DATA_ROOT`` can select another local
    artifact directory without putting a private path in the source code.
    """

    def __init__(self, data_root: Path | str | None = None) -> None:
        configured = data_root or os.environ.get("FIRETRACE_DATA_ROOT")
        self.data_root = (
            Path(configured) if configured else Path(__file__).resolve().parents[1] / "data"
        )
        self.web_dir = self.data_root / "processed" / "web"
        self.sar_dir = self.data_root / "interim" / "sar"
        self.change_dir = self.data_root / "interim" / "change"
        self.perimeter_dir = self.data_root / "interim" / "perimeter"
        self.terrain_dir = self.data_root / "interim" / "terrain"
        self._products: InspectionProducts | None = None
        self._products_manifest_key: tuple[tuple[int, int], ...] | None = None

    @staticmethod
    def _json_bytes(path: Path, source: str) -> dict[str, Any]:
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=503, detail=f"Cannot read {source}: {exc}") from exc
        if not isinstance(document, dict):
            raise HTTPException(status_code=503, detail=f"{source} must contain a JSON object")
        return document

    def _web_json(self, name: str) -> dict[str, Any]:
        """Read a published web document only when export.json records its exact bytes."""
        export_path = self.web_dir / "export.json"
        export = self._json_bytes(export_path, "export.json")
        outputs = export.get("outputs")
        expected = outputs.get(name) if isinstance(outputs, dict) else None
        if not isinstance(expected, str) or len(expected) != 64:
            raise HTTPException(status_code=503, detail=f"export.json has no checksum for {name}")
        path = self.web_dir / name
        try:
            payload = read_verified(path, expected, "export.json", "re-run the DT-04 export")
            document = json.loads(payload.decode("utf-8"))
        except (PublishError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HTTPException(
                status_code=503, detail=f"Published {name} is unavailable: {exc}"
            ) from exc
        if not isinstance(document, dict):
            raise HTTPException(status_code=503, detail=f"Published {name} must be a JSON object")
        if document.get("contract_version") != CONTRACT_VERSION:
            raise HTTPException(
                status_code=503, detail=f"{name} has an unsupported contract version"
            )
        return document

    def get_case(self) -> dict[str, Any]:
        return self._web_json("case.json")

    def get_stats(self) -> dict[str, Any]:
        return self._web_json("stats.json")

    def get_layers(self) -> dict[str, Any]:
        return self._web_json("layers.json")

    def health(self) -> dict[str, str]:
        case = self.get_case()
        data_status = case.get("data_status")
        if data_status not in {"mock", "real"}:
            raise HTTPException(status_code=503, detail="case.json has an invalid data_status")
        return {"status": "ok", "data_status": data_status}

    @staticmethod
    def _manifest(path: Path) -> dict[str, Any]:
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=503, detail=f"Cannot read {path.name}: {exc}") from exc
        if not isinstance(document, dict):
            raise HTTPException(status_code=503, detail=f"{path.name} must contain a JSON object")
        return document

    @staticmethod
    def _grid(document: Mapping[str, Any], manifest: str) -> dict[str, Any]:
        grid = document.get("grid")
        if not isinstance(grid, Mapping):
            raise HTTPException(status_code=503, detail=f"{manifest} has no grid")
        transform = grid.get("transform")
        width, height, crs = grid.get("width"), grid.get("height"), grid.get("crs")
        if not (
            isinstance(transform, list)
            and len(transform) == 6
            and all(
                isinstance(value, int | float) and not isinstance(value, bool)
                for value in transform
            )
            and isinstance(width, int)
            and isinstance(height, int)
            and width > 0
            and height > 0
            and isinstance(crs, str)
        ):
            raise HTTPException(status_code=503, detail=f"{manifest} has a malformed grid")
        return {
            "transform": [float(value) for value in transform],
            "width": width,
            "height": height,
            "crs": crs,
        }

    @staticmethod
    def _record(
        document: Mapping[str, Any], path: tuple[str, ...], manifest: str
    ) -> Mapping[str, Any]:
        value: Any = document
        for key in path:
            if not isinstance(value, Mapping) or key not in value:
                raise HTTPException(
                    status_code=503, detail=f"{manifest} is missing {'.'.join(path)}"
                )
            value = value[key]
        if not isinstance(value, Mapping):
            raise HTTPException(
                status_code=503, detail=f"{manifest} record {'.'.join(path)} is malformed"
            )
        filename, checksum = value.get("file"), value.get("sha256")
        if not isinstance(filename, str) or not isinstance(checksum, str) or len(checksum) != 64:
            raise HTTPException(
                status_code=503, detail=f"{manifest} record {'.'.join(path)} lacks file/checksum"
            )
        return value

    @staticmethod
    def _read_layer(
        directory: Path,
        record: Mapping[str, Any],
        manifest: str,
        grid: Mapping[str, Any],
        expected_dtype: str,
    ) -> RasterLayer:
        try:
            path = input_file(directory, record.get("file"), manifest)
            decoded = read_verified_raster(
                path,
                str(record["sha256"]),
                manifest,
                "re-run the pipeline stage that produced this raster",
            )
        except (PublishError, OSError, KeyError) as exc:
            raise HTTPException(
                status_code=503, detail=f"Cannot read verified raster from {manifest}: {exc}"
            ) from exc
        expected_transform = [float(value) for value in grid["transform"]]
        actual_transform = [float(value) for value in tuple(decoded.transform)[:6]]
        if (
            decoded.count != 1
            or decoded.dtype != expected_dtype
            or decoded.crs is None
            or decoded.crs != CRS.from_user_input(grid["crs"])
            or decoded.width != grid["width"]
            or decoded.height != grid["height"]
            or actual_transform != expected_transform
        ):
            raise HTTPException(
                status_code=503,
                detail=f"{Path(str(record['file'])).name} does not match {manifest} grid/dtype",
            )
        if decoded.data.shape != (grid["height"], grid["width"]):
            raise HTTPException(
                status_code=503, detail=f"{manifest} raster has an inconsistent array shape"
            )
        return RasterLayer(
            data=decoded.data,
            crs=decoded.crs,
            transform=decoded.transform,
            width=decoded.width,
            height=decoded.height,
            dtype=decoded.dtype,
        )

    def _load_products(self) -> InspectionProducts:
        manifest_paths = (
            self.sar_dir / "sar.json",
            self.change_dir / "change.json",
            self.perimeter_dir / "perimeter.json",
        )
        try:
            key = tuple((path.stat().st_mtime_ns, path.stat().st_size) for path in manifest_paths)
        except OSError as exc:
            raise HTTPException(
                status_code=503, detail=f"Pipeline manifests are unavailable: {exc}"
            ) from exc
        terrain_manifest = self.terrain_dir / "terrain.json"
        try:
            terrain_key = (terrain_manifest.stat().st_mtime_ns, terrain_manifest.stat().st_size)
        except FileNotFoundError:
            terrain_key = (-1, -1)
        except OSError as exc:
            raise HTTPException(
                status_code=503, detail=f"Terrain manifest is unavailable: {exc}"
            ) from exc
        key += (terrain_key,)
        if self._products is not None and self._products_manifest_key == key:
            return self._products

        sar, change, perimeter = (self._manifest(path) for path in manifest_paths)
        expected_versions = (
            "sar_format_version",
            "change_format_version",
            "perimeter_format_version",
        )
        for document, key_name in zip((sar, change, perimeter), expected_versions, strict=True):
            if document.get(key_name) != FORMAT_VERSIONS[key_name]:
                raise HTTPException(
                    status_code=503, detail=f"Unsupported {key_name} in pipeline manifest"
                )

        sar_bytes = manifest_paths[0].read_bytes()
        source_sar = change.get("source_sar")
        if (
            not isinstance(source_sar, Mapping)
            or source_sar.get("sha256") != hashlib.sha256(sar_bytes).hexdigest()
        ):
            raise HTTPException(
                status_code=503, detail="change.json was built from a different sar.json"
            )

        grid = self._grid(sar, "sar.json")
        for document, name in ((change, "change.json"), (perimeter, "perimeter.json")):
            if self._grid(document, name) != grid:
                raise HTTPException(status_code=503, detail=f"{name} grid differs from sar.json")
        try:
            grid_crs = CRS.from_user_input(grid["crs"])
        except CRSError as exc:
            raise HTTPException(status_code=503, detail="Analysis grid has an invalid CRS") from exc
        if grid_crs != ANALYSIS_CRS:
            raise HTTPException(status_code=503, detail="Analysis products must use EPSG:32610")
        transform = grid["transform"]
        if (
            transform[0] != ANALYSIS_PIXEL_SIZE_M
            or transform[1] != 0
            or transform[3] != 0
            or transform[4] != -ANALYSIS_PIXEL_SIZE_M
        ):
            raise HTTPException(
                status_code=503, detail="Analysis products must use the north-up 10 m grid"
            )

        layers: dict[str, RasterLayer] = {}
        sar_names = {"t1_hh", "t1_hv", "t2_hh", "t2_hv"}
        for name in sar_names:
            record = self._record(sar, ("db", "layers", name), "sar.json")
            layers[name] = self._read_layer(self.sar_dir, record, "sar.json", grid, "float32")
        mask_record = self._record(sar, ("valid_mask",), "sar.json")
        layers["valid_mask"] = self._read_layer(
            self.sar_dir, mask_record, "sar.json", grid, "uint8"
        )
        if not np.isin(layers["valid_mask"].data, (0, 1)).all():
            raise HTTPException(
                status_code=503, detail="valid_mask.tif contains values other than 0 or 1"
            )

        for name in ("change_hh_db", "change_hv_db", "change_index"):
            record = self._record(change, ("outputs", name), "change.json")
            layers[name] = self._read_layer(self.change_dir, record, "change.json", grid, "float32")
        for name in ("perimeter_mask.tif", "perimeter_edge.tif"):
            record = self._record(perimeter, ("outputs", name), "perimeter.json")
            layers[name] = self._read_layer(
                self.perimeter_dir, record, "perimeter.json", grid, "uint8"
            )
            if not np.isin(layers[name].data, (0, 1)).all():
                raise HTTPException(
                    status_code=503, detail=f"{name} contains values other than 0 or 1"
                )

        if terrain_key != (-1, -1):
            terrain = self._manifest(terrain_manifest)
            if terrain.get("terrain_format_version") != 1:
                raise HTTPException(status_code=503, detail="Unsupported terrain_format_version")
            terrain_grid = self._grid(terrain, "terrain.json")
            if terrain_grid != grid:
                raise HTTPException(
                    status_code=503, detail="terrain.json grid differs from sar.json"
                )
            for name in ("elevation", "slope", "aspect"):
                record = self._record(terrain, ("outputs", f"{name}.tif"), "terrain.json")
                layers[name] = self._read_layer(
                    self.terrain_dir, record, "terrain.json", grid, "float32"
                )

        products = InspectionProducts(grid, sar, change, perimeter, layers)
        self._products = products
        self._products_manifest_key = key
        return products

    @staticmethod
    def _empty_values() -> dict[str, dict[str, float | None]]:
        return {"t1": None, "t2": None, "delta": None}

    @staticmethod
    def _generic_caveats() -> list[dict[str, Any]]:
        return [
            {
                "id": "soil_moisture_change",
                "label": "Soil moisture change",
                "triggered": False,
                "reason": (
                    "Generic caution: soil moisture can change L-band backscatter "
                    "independently of fire."
                ),
            },
            {
                "id": "vegetation_structure",
                "label": "Vegetation structure",
                "triggered": False,
                "reason": (
                    "Generic caution: changes in vegetation structure can alter HH/HV backscatter."
                ),
            },
        ]

    def inspect_point(self, lon: float, lat: float) -> dict[str, Any]:
        """Sample verified numerical products at the analysis-grid pixel under WGS84."""
        case = self.get_case()
        products = self._load_products()
        reference = products.layers["t1_hh"]
        response: dict[str, Any] = {
            "contract_version": CONTRACT_VERSION,
            "data_status": case["data_status"],
            "query": {"lon": lon, "lat": lat},
            "pixel": None,
            "valid": False,
            "hh_db": self._empty_values(),
            "hv_db": self._empty_values(),
            "change_index": None,
            "change_index_percentile": None,
            "highlighted": None,
            "perimeter_relation": "unknown",
            "method_id": case["method"]["id"],
            "caveats": [],
        }
        try:
            x, y = transform_coordinates("EPSG:4326", reference.crs, [lon], [lat])
            if not math.isfinite(x[0]) or not math.isfinite(y[0]):
                return response
            row_values, col_values = rowcol(reference.transform, x[0], y[0])
            row, col = int(row_values), int(col_values)
        except (CRSError, TransformError, OverflowError, TypeError, ValueError):
            return response
        if row < 0 or col < 0 or row >= reference.height or col >= reference.width:
            return response

        center_x, center_y = xy(reference.transform, row, col, offset="center")
        center_lon, center_lat = transform_coordinates(
            reference.crs, "EPSG:4326", [center_x], [center_y]
        )
        perimeter = int(products.layers["perimeter_mask.tif"].data[row, col])
        response["perimeter_relation"] = "inside" if perimeter == 1 else "outside"
        response["pixel"] = {
            "row": row,
            "col": col,
            "x": float(center_x),
            "y": float(center_y),
            "crs": products.grid["crs"],
            "center_lon": float(center_lon[0]),
            "center_lat": float(center_lat[0]),
        }
        if "elevation" in products.layers:

            def terrain_value(name: str) -> float | None:
                value = float(products.layers[name].data[row, col])
                return value if math.isfinite(value) else None

            response["terrain"] = {
                "elevation_m": terrain_value("elevation"),
                "slope_deg": terrain_value("slope"),
                "aspect_deg": terrain_value("aspect"),
            }

        if int(products.layers["valid_mask"].data[row, col]) != 1:
            return response

        sample_names = (
            "t1_hh",
            "t2_hh",
            "t1_hv",
            "t2_hv",
            "change_hh_db",
            "change_hv_db",
            "change_index",
        )
        values = {name: float(products.layers[name].data[row, col]) for name in sample_names}
        if not all(math.isfinite(value) for value in values.values()):
            return response

        valid_index = products.layers["change_index"].data[
            (products.layers["valid_mask"].data == 1)
            & np.isfinite(products.layers["change_index"].data)
        ]
        if valid_index.size == 0:
            raise HTTPException(
                status_code=503, detail="No finite change-index pixels are available"
            )
        percentile = (
            100.0
            * float(np.count_nonzero(valid_index <= values["change_index"]))
            / valid_index.size
        )
        response.update(
            {
                "valid": True,
                "hh_db": {
                    "t1": values["t1_hh"],
                    "t2": values["t2_hh"],
                    "delta": values["change_hh_db"],
                },
                "hv_db": {
                    "t1": values["t1_hv"],
                    "t2": values["t2_hv"],
                    "delta": values["change_hv_db"],
                },
                "change_index": values["change_index"],
                "change_index_percentile": percentile,
                "caveats": self._generic_caveats(),
            }
        )
        return response
