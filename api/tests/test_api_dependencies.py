"""The API's fixed-stack dependencies are installed and importable."""

import importlib

import pytest

API_MODULES = ["fastapi", "pydantic", "rasterio"]


@pytest.mark.parametrize("module", API_MODULES)
def test_api_dependency_imports(module: str) -> None:
    importlib.import_module(module)
