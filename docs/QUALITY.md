# Quality gates — honest bootstrap, real tests with application code

Run checks in the foreground from the repository root. Never claim success for an unexecuted command.

## Current executable checks

```sh
uv sync
python3 scripts/check.py
uv run ruff format --check .
uv run contracts/tools/validate.py
git diff --check
```

The root [pyproject.toml](../pyproject.toml) is a virtual uv project (`package = false`) for Python 3.11 with empty `pipeline/` and `api/` packages and a `dev` dependency group (ruff, pytest). [quality.json](../quality.json) sets `lint` to `uv run ruff check .` and `test` to `uv run pytest`; pytest collects the smoke tests under `pipeline/tests/` and `api/tests/` with the repository root on `sys.path`. Runtime dependencies follow the fixed stack: rasterio, numpy, xarray, geopandas, shapely, scikit-image and rio-cogeo for `pipeline/`; FastAPI and pydantic for `api/`. Smoke tests import them so `uv sync` problems fail fast. Ruff currently excludes pre-existing tooling (`.agents/`, `contracts/tools/`, `scripts/`).

`scripts/check.py` checks required guidance, local inline link destination existence, the selected `firetrace` identity and configured quality commands. It executes argv lists without shell interpolation. Empty commands are allowed **only while no application source exists** under configured roots, including `pipeline/`, `api/` and `web/` as well as generic starter roots. Contracts/Kanvas tooling is not counted as an application.

The script checks file existence for links, not anchors/external URLs. Review new/untracked files directly for whitespace, secrets and correctness too: `git diff --check` alone omits them.

The contract validator uses its existing inline dependency declaration, **`jsonschema>=4.20`**. uv resolves that specification; CI does not invent a separate dependency list. With uv unavailable, `python3 contracts/tools/validate.py` can run against already-installed jsonschema, but Python does not enforce the inline metadata. Report the installed version and any mismatch rather than calling that a verified dependency environment. The check is JSON/path validation with the [limits described here](CONTRACTS.md), not a complete OpenAPI/geospatial/scientific audit.

## Python 3.11 CI, separate from local evidence

The `quality` workflow selects **Python 3.11**, runs `uv sync --locked`, the repository gate (which executes the `quality.json` lint and test commands), `uv run ruff format --check .` and then the existing fixture validator through uv, on pull requests and pushes to `main`. It uses the starter's checkout/setup-python action versions and the immutable setup-uv reference documented by its publisher. Dependency versions are pinned by the committed `uv.lock`; CI fails if `pyproject.toml` and the lockfile disagree.

The integration environment provides Python **3.14.4** and jsonschema **4.19.2**, below the declared `>=4.20`; `python` and uv are absent. No packages were installed or contract requirements weakened. Running the two direct Python3 scripts here is **not Python 3.11/uv, declared-dependency or hosted CI verification**. CI configuration is not a CI execution result; record the actual remote outcome only when an authorized run occurs.

## Before adding application source

Configure real `lint` and `test` argv lists in [quality.json](../quality.json) in the same change as source; configure build for bundled web code. Add dependency manifests/lockfiles and CI runtime setup in the authorized scaffold work. The gate refuses source with unset lint/test, but cannot prove arbitrary configured commands are meaningful; reviewers must reject dummy success commands.

Canonical upstream commands (Python is wired; the others need their scaffold/dependencies first):

| Boundary | Commands to wire into real quality gates |
| --- | --- |
| Python pipeline/API (wired) | `uv sync`; `uv run ruff check .`; `uv run ruff format --check .`; `uv run pytest` |
| Web (run within `web/`) | `npm install`; `npm run lint`; `npm run test`; `npm run build`; add the selected prettier check to lint |
| Real pipeline output | `uv run contracts/tools/validate.py data/processed/web` |

The first implemented pipeline stage is the DT-01 NISAR ingest/crop: `uv run python -m pipeline.ingest --config pipeline/configs/ingest_plaskett.toml`. It reads the four local GCOV GeoTIFFs from `data/raw/nisar/` (relative paths resolve against the working directory) and writes float32 crops plus `ingest.json` to `data/interim/nisar/`. It needs the gitignored raw inputs and is not run in CI; its tests use synthetic rasters only.

`uv run python -m pipeline.run --all`, `uv run uvicorn api.main:app --reload` and `npm run dev` within `web/` are planned upstream processing/start targets, **not working commands in this checkout**. Do not run or document them as implemented until their scaffold task supplies evidence.

Cover deterministic numerical rules and realistic failure paths with small synthetic rasters. Application integration must verify actual lookup/display alignment, no-data, coverage arithmetic, provenance and mock-to-real switching. Real science requires separate reproducible sample evidence and an agreed method/domain; schema-valid mocks are not that evidence.

Human review checks acceptance, contract compatibility, privacy, error handling, demo fallback and exact rollback boundaries. Preserve configured ODD/RDD behavior without changing native review state; neither a receipt nor a green bootstrap substitutes for tests or human review.
