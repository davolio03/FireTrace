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

The root [pyproject.toml](../pyproject.toml) is a virtual uv project (`package = false`) for Python 3.11 with `pipeline/` and `api/` packages and a `dev` dependency group (ruff, pytest, and jsonschema `>=4.20`, matching the contract validator, so pipeline tests can validate outputs against the contract schemas). [quality.json](../quality.json) runs Python and web lint and tests through `scripts/quality_commands.py`, then the web build. Pytest collects tests under `pipeline/tests/` and `api/tests/` with the repository root on `sys.path`. Runtime dependencies follow the fixed stack. Ruff currently excludes pre-existing tooling (`.agents/`, `contracts/tools/`, `scripts/`).

`scripts/check.py` checks required guidance, local inline link destination existence, the selected `firetrace` identity and configured quality commands. It executes argv lists without shell interpolation. Empty commands are allowed **only while no application source exists** under configured roots, including `pipeline/`, `api/` and `web/` as well as generic starter roots. Contracts/Kanvas tooling is not counted as an application.

The script checks file existence for links, not anchors/external URLs. Review new/untracked files directly for whitespace, secrets and correctness too: `git diff --check` alone omits them.

The contract validator uses its existing inline dependency declaration, **`jsonschema>=4.20`**. uv resolves that specification; CI does not invent a separate dependency list. With uv unavailable, `python3 contracts/tools/validate.py` can run against already-installed jsonschema, but Python does not enforce the inline metadata. Report the installed version and any mismatch rather than calling that a verified dependency environment. The check is JSON/path validation with the [limits described here](CONTRACTS.md), not a complete OpenAPI/geospatial/scientific audit.

## Python 3.11 CI, separate from local evidence

The `quality` workflow runs on pull requests and pushes to `main`, selects **Python 3.11** and **Node 24**, and installs dependencies with `uv sync --locked` and `npm ci`. It runs the repository gate, Python formatting, orchestration tests and fixture validation. The pinned `uv.lock` must match `pyproject.toml`; setup-uv uses the documented immutable reference. CI configuration is not evidence of a hosted run.

Locally, run `uv sync` and `npm ci --prefix web` once, then `python scripts/check.py` (or `python3` where available). The runners launch `python3`/`python` commands with the current interpreter and resolve other programs through `PATH`, so the same `quality.json` works on Windows, where `python3` is usually absent and npm is `npm.cmd`.

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

The DT-02 stage converts those crops to dB and builds the common valid mask: `uv run python -m pipeline.sar --ingest-dir data/interim/nisar --output-dir data/interim/sar`. It verifies the crops against the sha256 values in `ingest.json` and writes dB COGs, `valid_mask.tif` and `sar.json` (layout in [ARCHITECTURE](ARCHITECTURE.md)). Like DT-01 it needs local data, is not run in CI and is tested with synthetic rasters.

The CH-01 stage computes the continuous change index: `uv run python -m pipeline.change --sar-dir data/interim/sar --output-dir data/interim/change` (add `--quicklook <png>` outside the output directory for a review preview). The method is documented in [change-index](methods/change-index.md).

The DT-03 stage pins the WFIGS reference perimeter and rasterizes it on the crop grid: `uv run python -m pipeline.perimeter --config pipeline/configs/perimeter_plaskett.toml`. It verifies the raw GeoJSON sha256, never downloads, and is documented in [reference-perimeter](methods/reference-perimeter.md).

The DT-05 stage builds terrain context on the crop grid: `uv run python -m pipeline.terrain --config pipeline/configs/terrain_plaskett.toml`. It needs the pinned Copernicus GLO-30 tile in `data/raw/dem/` and the t2 GCOV `.h5` in `data/raw/nisar/` (both sha256-verified, never downloaded), writes elevation/slope/aspect/local-incidence COGs, approximate layover/shadow flags and the `hillshade`/`slope` display PNGs with their `terrain_layers.json` entries, and is documented in [terrain](methods/terrain.md). Display PNGs use the shared `pipeline/webexport.py` (EPSG:3857 warp, corners, colour ramps).

`npm run dev` within `web/` starts the web scaffold. `uv run python -m pipeline.run --all` and `uv run uvicorn api.main:app --reload` remain planned processing/start targets, **not working commands in this checkout**.

Cover deterministic numerical rules and realistic failure paths with small synthetic rasters. Application integration must verify actual lookup/display alignment, no-data, coverage arithmetic, provenance and mock-to-real switching. Real science requires separate reproducible sample evidence and an agreed method/domain; schema-valid mocks are not that evidence.

Human review checks acceptance, contract compatibility, privacy, error handling, demo fallback and exact rollback boundaries. Preserve configured ODD/RDD behavior without changing native review state; neither a receipt nor a green bootstrap substitutes for tests or human review.
