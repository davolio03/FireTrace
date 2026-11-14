# FireTrace team operating agreement

**Known assignment:** David is the upstream NISAR data/models orchestrator. Other roles and all backups remain unassigned; this document does not invent owners or approve board proposals.

## Ownership boundaries

| Role | Handoff | Owner / backup | Kanvas groups |
| --- | --- | --- | --- |
| NISAR data + models | Input identity, crop metadata, reproducible products and orchestration | David / unassigned | DT, CH, XP |
| Geospatial processing | Grid/CRS, validity, reprojection and reference alignment | Unassigned / unassigned | DT, EV |
| CV / ML | Continuous baseline first; optional CV/DL with evaluation later | Unassigned / unassigned | CH, XP |
| Scientific evaluation | Metric domains, sensitivity and attribution limits | Unassigned / unassigned | EV |
| Application / frontend | Independent layers, comparison, coverage and point inspector | Unassigned / unassigned | AP |
| Integration / storytelling | Boundary coordination, documentation, release and demo fallback | Unassigned / unassigned | BS, IN, DL |

Roles may overlap, but every task and shared boundary needs one accountable human. DL cannot block P0. Maintainers must select actual GitHub reviewers/handles before enabling CODEOWNERS; no placeholder assignment grants review authority.

## Parallel work lanes (4–5 people)

Each lane builds against the [contracts](../contracts/README.md) and fixtures, without waiting for the others. Lanes only meet in the `IN-*` integration tasks (mock → real), done jointly by producer and consumer. With four people, one person owns L2 and L3.

| Lane | Owner | Produces | Main tasks |
| --- | --- | --- | --- |
| L1 Radar data + models | David | dB, change index, stats, review zones, SAR layers, analysis COGs | DT-01/02/04, CH, XP |
| L2 Context data | David | Perimeter, DEM → hillshade/slope + terrain COG, `weather.json`, optical layers | DT-03, DT-05, DT-06, DT-07 |
| L3 API | Unassigned | Point inspection (+ terrain), transect endpoint, deterministic caveat rules | BS-03, EV-01, EV-02, EV-05 |
| L4 Web: map | Unassigned | Map, layers, swipe, inspector, transect tool, context layers | BS-04, BS-05, BS-07, AP-02/03/05/06, EV-03 |
| L5 Web: experience | Unassigned | Overview, metrics, review zones, guided story, annotations + report, demo | AP-01/04/07/08, EV-04, DL |

L4 and L5 coordinate through the shared store in [web-state](../contracts/web-state.md): nobody touches MapLibre outside `features/map/`. The role table above stays the accountability view; lanes are how the work is split in time.

## One board, isolated writers, human decisions

- **Kanvas is the only canonical task state.** Use the live board at `http://andriudevserver.tail8ddc4a.ts.net:8765/FireTrace/` through the [Kanvas CLI/skill](../.agents/skills/kanvas/SKILL.md); the CLI reads `.agents/skills/kanvas/remote.json` and `git pull` brings the config. Never pass `-b`, set `KANVAS_BOARD`, or edit a local `kanvas.json`.
- Humans approve proposed work and mark done. Agents operate only within the skill and explicit authorization; one writer per worktree, no taking another writer's work. Issues may carry acceptance/discussion, not parallel status columns.
- Scope and tradeoffs stay human-owned. Report direct authorization without a matching task honestly; do not invent an approved Kanvas ID.
- Current [schemas/OpenAPI](../contracts/README.md) define interfaces. Producers/consumers agree changes before implementation and review a dedicated contract PR. Existing fixtures allow parallel work without declaring every scientific detail settled.
- Git and accepted docs outrank memory. A second teammate reviews cross-boundary data semantics, shared dependencies, auth/deployment and critical demo behavior. Agents do not publish or merge without authority.

## Integration checkpoints, not another task board

1. Confirm P0, owners, input inventory and open scientific decisions in [CONTRACTS](CONTRACTS.md).
2. Develop against the existing contract fixtures with visible MOCK labeling; integrate one real SAR layer and continuous result early.
3. Demonstrate independent layers, coverage, point inspection and provenance; check discrepancies and physical confounds.
4. Only then consider P1. Freeze nonessential features, rehearse the 90–120 second journey and test the fallback in [DEMO](DEMO.md).

Exact checkpoint times remain to be agreed. Urgent blockers go to the orchestrator and affected human owners; copy the resolution to the canonical task and accepted technical decisions to Git. [STATUS](STATUS.md) records evidence/readiness, not a replacement backlog.

## Required handoff proof

Provide artifact/revision and source identities, method/configuration, grid/CRS, contract compatibility, exact commands/results/exit codes, known-value and failure evidence, limitations and rollback boundary. Run `python3 scripts/check.py`, contract validation and relevant real lint/tests/build. A successful bootstrap/fixture check is not proof of app behavior or radar interpretation.

Keep a last verified demo revision and matching artifact set. No existing run or Cloud deployment is claimed by this agreement.

## Shared memory and privacy

The explicit user decision is **firetrace + Engram Cloud**. No migration/deletion of older projects is needed; do not commit Git memory exports or private local stores. [ENGRAM_CLOUD](ENGRAM_CLOUD.md) documents enrollment and operational safeguards, not authorization to use a remote session.

Save reusable grounded findings in English, `scope: project`, with evidence and status. Do not save secrets, personal notes, sensitive payloads, transcripts or speculation: even personal-scoped observations may sync from an enrolled project. Configuration alone neither deploys nor enrolls anything.
