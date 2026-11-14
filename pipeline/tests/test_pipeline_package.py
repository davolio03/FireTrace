"""Smoke test: the repository ``pipeline`` package is the one that gets imported."""

from pathlib import Path

import pipeline

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_pipeline_package_resolves_to_repository() -> None:
    assert pipeline.__file__ is not None
    assert Path(pipeline.__file__).resolve().parent == REPO_ROOT / "pipeline"
