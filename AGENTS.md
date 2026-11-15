# FireTrace Explorer — team agent contract

Build one integrated, demonstrable Plaskett Fire case. Preserve the team's architecture and distinguish implemented contracts/mocks from the pipeline, API and web that still need implementation.

## Authority and first read

1. Explicit user instructions and human approvals define authorization and scope.
2. Current repository truth: [proposal](docs/propuesta.md) for scientific/product scope; [executable contracts](contracts/README.md), schemas and OpenAPI for interfaces; accepted decisions and current code for implementation.
3. [Product](docs/PRODUCT.md), [architecture](docs/ARCHITECTURE.md), [contract semantics](docs/CONTRACTS.md) and [team agreement](docs/TEAM.md) explain those boundaries.
4. Engram is historical supporting evidence, never authority over the repository. Label inferences and surface contradictions to the human owner before relying on them.

The proposal's illustrative stack has been superseded by the stack below. Its scientific cautions remain applicable. Do not silently resolve any other scope/interface conflict.

Before editing, read the relevant documents, the task and every note, affected code/tests and any linked issue's acceptance criteria. Search relevant Engram history unless explicitly instructed not to. Describe the smallest change, touched interfaces and verification. Use a short [task brief](docs/tasks/TEMPLATE.md) only when the diff/task is insufficient to resume work.

## Scientific invariants

- **Observation is not interpretation or validation.** Use *Observed radar changes*, optional *Highlighted radar changes*, and *Official fire perimeter*. Never equate radar change with confirmed fire, burned area or ecological severity.
- NISAR is primary; Sentinel, RAVG and other references are complementary. The external preprint's AUC 0.984 is not FireTrace performance.
- For finite positive GCOV power, use `10 * log10(x)`. Mask source no-data, non-finite, zero and negative inputs before logs; combined results use the common valid set across all four inputs. Exclude invalid values from metrics.
- Preserve the common **10 m EPSG:32610 analysis grid**. Display PNGs are reprojected/resampled to **EPSG:3857**; WGS84 selections/corners and the reference geometry use **EPSG:4326**. Never measure from colors or Web Mercator display pixels.
- The WFIGS perimeter dated 2026-09-14 predates the after observation; it is not final or pixel-level ground truth. Moisture, terrain, geometry and vegetation can confound the signal.
- The Evidence Inspector must show computed values and the real method, not LLM-generated evidence or uncalibrated confidence. Mocks must carry a visible MOCK notice and never count as real scientific validation.
- P0 is the continuous HH/HV change journey. Threshold masks, overlap metrics and DL are P1, only after an integrated P0. Resolve the scientific choices in [CONTRACTS](docs/CONTRACTS.md) before claiming real measurements.

## Architecture and fixed stack

Heavy processing is offline. The demo must not download scenes, authenticate to Earthdata or train a model live.

| Boundary | Stack / responsibility |
| --- | --- |
| Planned `pipeline/` | Python 3.11 + uv; rasterio, numpy, xarray, geopandas, shapely, scikit-image, rio-cogeo; reproducible products |
| Planned `api/` | FastAPI, rasterio COG lookup, pydantic; contract-defined inspection |
| Planned `web/` | React 19, strict TypeScript, Vite, MapLibre GL JS; Tailwind CSS + shadcn/ui, TanStack Query, Zustand, Recharts |
| Optional | deck.gl if needed; PyTorch for P1 experiments |
| Quality | ruff + pytest; eslint + prettier + vitest |
| Existing `contracts/` | JSON Schema 2020-12, OpenAPI, synthetic fixtures and tooling; authoritative shared interfaces |

These choices do not imply packages are installed or application scaffolds exist. Stack changes need a short ADR in `docs/decisions/` and human approval recorded through Kanvas. See [QUALITY](docs/QUALITY.md) for current versus future commands.

## One task, one worktree, one writer

- **Kanvas is the only canonical task state.** Read [.agents/skills/kanvas/SKILL.md](.agents/skills/kanvas/SKILL.md). GitHub Issues hold references, acceptance criteria and discussion, not a second board.
- Before session `status` and `ready`, configure ignored `.agents/skills/kanvas/remote.json` from the tracked `remote.example.json` using the endpoint supplied privately by the maintainer; preserve an existing configured file. Then use `python3 .agents/skills/kanvas/kanvas.py status` and `ready` only with authorized remote access. `git pull` brings the example, not the private endpoint. Missing configuration blocks board work; never fall back to a local snapshot. Do not pass `-b`, set `KANVAS_BOARD`, or edit a local `kanvas.json`. `--local` is only for the computer running `kanvas serve`.
- Board writes use only the CLI, signed with `--as <tool>-<role>`. Humans approve proposals and mark done. Agents start approved ready work, add notes and submit with `finish` for human review, within the skill's rules. Never invent approvals or take another writer's task.
- Explicitly authorized direct work without a matching approved task must be reported as such; do not manufacture a task ID or silently approve a proposal.
- A human owns each task/PR. Work in a dedicated branch/worktree from current `main`, with disjoint ownership for parallel work. Never overwrite another worktree or agent's changes.
- Use small Conventional Commits with the task ID when one exists. No AI attribution trailers. Commit, publish, open PRs or remove worktrees only when authorized; agents never merge autonomously.
- No direct push to `main`, force push, hook bypass, destructive cleanup or data/secret commits. Do not discover or reuse ambient remote credentials/sessions: remote work requires explicit destination, operation and credential/session authorization.

## Shared interfaces and implementation discipline

- Develop against [contracts/](contracts/README.md). Web types come from OpenAPI; API tests validate responses against schemas; pipeline output must pass `uv run contracts/tools/validate.py data/processed/web`.
- Mock-to-real integration changes the data source, not feature interfaces. `VITE_USE_MOCKS=true` is the planned web mock mode, not an implemented app command.
- Shared interfaces, numerical semantics or dependencies require producer/consumer agreement first. Contract changes get their own PR, version update, fixtures/checks and review from each affected side. Do not hide them in a feature.
- Keep changes bounded and readable, with explicit types and CRS. Use test-first behavior for deterministic rules, small synthetic rasters, meaningful failure paths and no real-data downloads in tests.
- Python uses pathlib and pure processing functions where practical. Web uses functional components, strict types without `any`, accessible contrast/legends and colorblind-safe palettes.
- New code, comments, UI copy, docs, commits and reusable memory are English by default. Preserve existing source documents; explicitly requested Spanish artifacts use neutral/professional Spanish.
- No secrets, private paths, personal data, hidden telemetry or uncontrolled external calls. Use current official library docs; never fabricate APIs, package versions or test results.

## Verification and handoff

Run these checks in the foreground from the repository root:

```sh
python3 scripts/check.py
uv run contracts/tools/validate.py
git diff --check
```

When uv is unavailable, `python3 contracts/tools/validate.py` can report behavior with already-installed jsonschema, but direct Python does not resolve/enforce the inline dependency declaration. Report the actual interpreter, dependency version and any mismatch; do not present an out-of-spec run as canonical environment verification. Never install tooling or change review settings to bypass an explicit restriction.

Application source requires real lint/test commands in `quality.json` in the same change; bundled web code also needs a build. Bootstrap and fixture checks are not application tests or scientific validation. Inspect new/untracked files as well as the tracked diff. Report commands, observed results, exit codes, limitations and rollback boundary. Preserve configured ODD/RDD gates; they do not replace tests or human review.

Use the [PR template](.github/pull_request_template.md) for handoff evidence; opening a PR is a separate authorized action. A second teammate reviews cross-boundary changes. Keep demo readiness evidence in [DEMO](docs/DEMO.md), not a competing task board.

## Shared memory: firetrace + Engram Cloud

`.engram/config.json` selects **firetrace**. The user chose **Cloud**, not Git memory exports. Follow [ENGRAM_CLOUD](docs/ENGRAM_CLOUD.md); do not auto-export, import legacy projects, commit memory chunks or delete local databases to rename a project. Configuration is not enrollment, deployment or permission to contact a server.

Save only reusable, grounded team decisions/findings in English, `scope: project`, using **What / Why / Where / Learned**, a stable topic key and related task/PR evidence when available. Save explicit human decisions promptly; do not describe provisional implementation as merged/accepted. Current Git truth prevails over memory.

Cloud can synchronize even `scope: personal` observations in an enrolled project. Never save private information, credentials, sensitive payloads, full transcripts or speculative findings here. Keep old projects untouched; no migration is required. Use individual project-scoped tokens, never a shared/admin client token.
