# FireTrace Explorer

Explore what changed in NISAR HH/HV observations before and after **Plaskett Fire, Big Sur, 2026**, inspect the radar values and compare them with a dated official perimeter. Radar change is not confirmed fire, burned area or ecological severity.

**Current state:** executable v1.0.0 contracts, synthetic fixtures and Kanvas tooling exist. The pipeline, FastAPI service and React application are not implemented here. Neither real processing nor a running demo is claimed. See the [in-repo proposal](docs/propuesta.md) and [product acceptance criteria](docs/PRODUCT.md).

## Start here

1. Read [AGENTS.md](AGENTS.md), [architecture](docs/ARCHITECTURE.md) and [executable contracts](contracts/README.md).
2. Read Kanvas using `python3 .agents/skills/kanvas/kanvas.py status`. It is the **only canonical task state**; issues are supporting discussion/references.
3. Use Python **3.11** and uv for the agreed Python stack. Current repository checks are:

   ```sh
   python3 scripts/check.py
   uv run contracts/tools/validate.py
   git diff --check
   ```

   Without uv, `python3 contracts/tools/validate.py` can run against already-installed jsonschema; report its version and any mismatch with the inline declaration. This does not resolve dependencies. Bootstrap/fixture checks do not test an application or validate science. See [QUALITY](docs/QUALITY.md).
4. Follow [onboarding](docs/ONBOARDING.md) for worktree ownership, planned application commands and shared memory. Configure application lint/tests before adding source; empty `quality.json` commands are not an app test suite.

## What we will demonstrate

A 90–120 second journey: case context → aligned before/after map → continuous **Observed radar changes** → independent **Official fire perimeter** → computed pixel evidence, valid coverage, provenance and limitations. Thresholded **Highlighted radar changes**, IoU and DL are P1, not MVP dependencies.

Analysis stays on the common **10 m EPSG:32610** grid. Precomputed RGBA display PNGs are resampled/reprojected to **EPSG:3857**; corners, reference geometry and inspector queries use WGS84. Scientific values come from numerical products, never PNG colors. Mocks require a visible MOCK banner.

## Team navigation

| Resource | Purpose |
| --- | --- |
| [PRODUCT](docs/PRODUCT.md) | P0/P1, evidence boundaries and observable acceptance |
| [ARCHITECTURE](docs/ARCHITECTURE.md) | Fixed stack, planned modules and geographic invariants |
| [CONTRACTS](docs/CONTRACTS.md) | Guide to authoritative schemas/OpenAPI and unresolved science |
| [TEAM](docs/TEAM.md) / [CONTRIBUTING](CONTRIBUTING.md) | Owners, Kanvas, worktrees and human review |
| [STATUS](docs/STATUS.md) / [DEMO](docs/DEMO.md) | Evidence snapshot and rehearsal runbook, not a second task board |
| [ENGRAM_CLOUD](docs/ENGRAM_CLOUD.md) | Chosen `firetrace` identity, authenticated Cloud recipe and privacy |
| [QUALITY](docs/QUALITY.md) / [quality.json](quality.json) | Real quality command gate and current limitations |

## Safety and delivery

One writer per worktree; contract changes need affected-side approval and their own versioned PR. Humans own publication, review and merge. No direct/force pushes to `main`, secrets, raw data, model weights or memory exports in Git.

Engram Cloud is the chosen shared-memory transport, not a deployed service. `.engram/config.json` selects `firetrace`; it does not enroll a client or authorize remote access. Old memory projects remain untouched. Private notes are unsafe even with `scope: personal` in an enrolled project.

Maintainers should protect `main` with PRs, the `quality` check and a teammate review for meaningful changes, especially cross-boundary work. This document does not change GitHub settings or native review state. Hosting, source usage/attribution and challenge submission rules still need human confirmation.
