# Quality gates — honest bootstrap, real tests with application code

Run checks in the foreground from the repository root. Never claim success for an unexecuted command.

## Current executable checks

```sh
python3 scripts/check.py
uv run contracts/tools/validate.py
git diff --check
```

`scripts/check.py` checks required guidance, local inline link destination existence, the selected `firetrace` identity and configured quality commands. It executes argv lists without shell interpolation. Empty commands are allowed **only while no application source exists** under configured roots, including `pipeline/`, `api/` and `web/` as well as generic starter roots. Contracts/Kanvas tooling is not counted as an application.

The script checks file existence for links, not anchors/external URLs. Review new/untracked files directly for whitespace, secrets and correctness too: `git diff --check` alone omits them.

The contract validator uses its existing inline dependency declaration, **`jsonschema>=4.20`**. uv resolves that specification; CI does not invent a separate dependency list. With uv unavailable, `python3 contracts/tools/validate.py` can run against already-installed jsonschema, but Python does not enforce the inline metadata. Report the installed version and any mismatch rather than calling that a verified dependency environment. The check is JSON/path validation with the [limits described here](CONTRACTS.md), not a complete OpenAPI/geospatial/scientific audit.

## Python 3.11 CI, separate from local evidence

The `quality` workflow selects **Python 3.11** and **Node 24**, installs the web dependencies, runs the configured application checks and then the existing fixture validator through uv. It uses the starter's checkout/setup-python action versions and the immutable setup-uv reference documented by its publisher.

The integration environment provides Python **3.14.4** and jsonschema **4.19.2**, below the declared `>=4.20`; `python` and uv are absent. No packages were installed or contract requirements weakened. Running the two direct Python3 scripts here is **not Python 3.11/uv, declared-dependency or hosted CI verification**. CI configuration is not a CI execution result; record the actual remote outcome only when an authorized run occurs.

## Before adding application source

Configure real `lint` and `test` argv lists in [quality.json](../quality.json) in the same change as source; configure build for bundled web code. Add dependency manifests/lockfiles and CI runtime setup in the authorized scaffold work. The gate refuses source with unset lint/test, but cannot prove arbitrary configured commands are meaningful; reviewers must reject dummy success commands.

Canonical upstream commands **after the corresponding scaffold/dependencies exist**:

| Boundary | Commands to wire into real quality gates |
| --- | --- |
| Python pipeline/API | `uv sync`; `uv run ruff check .`; `uv run ruff format --check .`; `uv run pytest` |
| Web (run within `web/`) | `npm install`; `npm run lint`; `npm run test`; `npm run build`; add the selected prettier check to lint |
| Real pipeline output | `uv run contracts/tools/validate.py data/processed/web` |

`npm run dev` within `web/` starts the web scaffold. `uv run python -m pipeline.run --all` and `uv run uvicorn api.main:app --reload` remain planned processing/start targets, **not working commands in this checkout**.

Cover deterministic numerical rules and realistic failure paths with small synthetic rasters. Application integration must verify actual lookup/display alignment, no-data, coverage arithmetic, provenance and mock-to-real switching. Real science requires separate reproducible sample evidence and an agreed method/domain; schema-valid mocks are not that evidence.

Human review checks acceptance, contract compatibility, privacy, error handling, demo fallback and exact rollback boundaries. Preserve configured ODD/RDD behavior without changing native review state; neither a receipt nor a green bootstrap substitutes for tests or human review.
