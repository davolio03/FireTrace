"""Manifests and configs that are not valid UTF-8 are input errors of their stage.

``UnicodeDecodeError`` is raised before JSON/TOML parsing, so a corrupted file used to end in
a traceback and exit code 1 instead of the stage error and exit code 2. Every CLI turns its
stage error into exit code 2, so raising that error is the behaviour under test.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from pipeline import change, export, ingest, optical, perimeter, sar, terrain, weather

BAD_UTF8 = b'{"key": "\xff"}\n'
BAD_TOML = b'key = "\xff"\n'


def _file(tmp_path: Path, name: str, payload: bytes) -> Path:
    path = tmp_path / name
    path.write_bytes(payload)
    return path


CONFIG_LOADERS: list[tuple[str, Callable[..., Any], type[Exception]]] = [
    ("export", export.load_config, export.ExportError),
    ("ingest", ingest.load_config, ingest.IngestError),
    ("optical", optical.load_config, optical.OpticalError),
    ("perimeter", perimeter.load_config, perimeter.PerimeterError),
    ("terrain", terrain.load_config, terrain.TerrainError),
]


@pytest.mark.parametrize(
    ("loader", "error"),
    [(load, err) for _, load, err in CONFIG_LOADERS],
    ids=[name for name, _, _ in CONFIG_LOADERS],
)
def test_non_utf8_config_is_a_stage_error(
    tmp_path: Path, loader: Callable[..., Any], error: type[Exception]
) -> None:
    path = _file(tmp_path, "case.toml", BAD_TOML)
    with pytest.raises(error, match="config: cannot read case.toml"):
        loader(path, base_dir=tmp_path)


def test_non_utf8_sar_manifest_is_a_change_error(tmp_path: Path) -> None:
    _file(tmp_path, "sar.json", BAD_UTF8)
    with pytest.raises(change.ChangeError, match="cannot read sar.json"):
        change.load_sar(tmp_path)


def test_non_utf8_ingest_manifest_is_a_sar_error(tmp_path: Path) -> None:
    _file(tmp_path, "ingest.json", BAD_UTF8)
    with pytest.raises(sar.SarError, match="cannot read ingest.json"):
        sar.load_ingest(tmp_path)


@pytest.mark.parametrize(
    ("load_json", "error"),
    [(optical._load_json, optical.OpticalError), (weather._load_json, weather.WeatherError)],
    ids=["optical", "weather"],
)
def test_non_utf8_json_is_a_stage_error(
    tmp_path: Path, load_json: Callable[[Path], Any], error: type[Exception]
) -> None:
    path = _file(tmp_path, "manifest.json", BAD_UTF8)
    with pytest.raises(error, match="cannot read manifest.json"):
        load_json(path)


def test_non_utf8_pyproject_is_an_export_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(export, "PYPROJECT", _file(tmp_path, "pyproject.toml", BAD_TOML))
    with pytest.raises(export.ExportError, match="pyproject.toml"):
        export.pipeline_version()


def test_terrain_ingest_reread_is_a_terrain_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The crop grid was already read; the manifest is then unreadable on the second read
    # (for example replaced in between). That must still be a TerrainError, not a traceback.
    monkeypatch.setattr(terrain, "load_crop_grid", lambda _dir: (None, 1, 1))
    _file(tmp_path, "ingest.json", BAD_UTF8)
    with pytest.raises(terrain.TerrainError, match="cannot read ingest.json"):
        terrain.load_ingest(tmp_path)


def test_perimeter_crop_grid_already_reports_non_utf8(tmp_path: Path) -> None:
    _file(tmp_path, "ingest.json", BAD_UTF8)
    with pytest.raises(perimeter.PerimeterError, match="cannot read the crop grid"):
        perimeter.load_crop_grid(tmp_path)
