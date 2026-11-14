"""The pipeline's fixed-stack dependencies are installed and importable."""

import importlib

import pytest

PIPELINE_MODULES = [
    "numpy",
    "rasterio",
    "xarray",
    "geopandas",
    "shapely",
    "skimage",
    "rio_cogeo",
]


@pytest.mark.parametrize("module", PIPELINE_MODULES)
def test_pipeline_dependency_imports(module: str) -> None:
    importlib.import_module(module)
