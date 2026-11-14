"""Smoke test: the repository ``api`` package is the one that gets imported."""

from pathlib import Path

import api

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_api_package_resolves_to_repository() -> None:
    assert api.__file__ is not None
    assert Path(api.__file__).resolve().parent == REPO_ROOT / "api"
