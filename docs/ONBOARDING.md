# Join FireTrace without inventing a running app

The case, stack and executable v1 contracts are selected. Pipeline/API/web implementation and real-data acceptance are still pending. Start with [PRODUCT](PRODUCT.md), [ARCHITECTURE](ARCHITECTURE.md), [CONTRACTS](CONTRACTS.md) and [AGENTS](../AGENTS.md).

## First local session

1. Use the agreed Python **3.11** and uv environment; install tools only with local permission. [QUALITY](QUALITY.md) distinguishes current checks from future stack commands.
2. Run `python3 scripts/check.py` and `uv run contracts/tools/validate.py`. If uv is absent but jsonschema is already installed, `python3 contracts/tools/validate.py` provides limited direct-run evidence: record interpreter/dependency versions and any mismatch with the declaration. Do not treat bootstrap checks as app tests or an out-of-spec environment as canonical verification.
3. Read [.agents/skills/kanvas/SKILL.md](../.agents/skills/kanvas/SKILL.md), then run:

   ```sh
   python3 .agents/skills/kanvas/kanvas.py status
   python3 .agents/skills/kanvas/kanvas.py ready
   ```

   Use the authoritative board in the main checkout; from a feature worktree add `-b <main-checkout>/kanvas.json`. No feature-branch board writes. If nothing is approved, report it to the human rather than approving a proposal yourself.
4. Agree the task owner and isolated worktree. With explicit Git authorization, branch from current `origin/main` into a separate worktree; one writer owns it. No fetch, staging, commit or publication is implied by this guide.
5. For Python work in `pipeline/` or `api/`, run `uv sync` once, then `python3 scripts/check.py` (ruff check + pytest from `quality.json`) and `uv run ruff format --check .`. No processing or API start command exists yet.
6. Read only relevant fixtures and affected code; agree open science/interfaces with the producer and consumer. Configure real lint/tests before the first application source file.

## Configuration boundaries

There is no application environment file in this foundation. The source starter's `.env.example` could not be inspected under the active access rules and was not copied. Safe names selected by the executable contract are listed here; these are **planned web configuration**, not working app setup:

| Name | Intended use |
| --- | --- |
| `VITE_DATA_BASE_URL` | Static base for contract-shaped web artifacts |
| `VITE_API_BASE_URL` | API base for numerical inspection |
| `VITE_USE_MOCKS` | `true` for the future MSW fixture harness with a visible MOCK banner |

Vite client configuration is public: never put Earthdata, Engram or other secrets in `VITE_*`. Raw data and real processed outputs remain outside Git. Future scaffold tasks must document actual start commands and safe examples when access allows.

## Shared memory, separately authorized

The committed identity is **firetrace** and transport is **Engram Cloud**. Follow [ENGRAM_CLOUD](ENGRAM_CLOUD.md) only after an operator supplies an authorized HTTPS endpoint and your individual project token. `engram setup opencode` connects the agent integration, not Cloud; restart the actual MCP/serve process after changing its environment.

No migration of `hackathon-team` or deletion of local memory is necessary. Do not export memory to Git or store personal notes in an enrolled project. Server provisioning/client sync are not authorized merely because this documentation/config exists.

## Handoff

Use [CONTRIBUTING](../CONTRIBUTING.md) and the [PR template](../.github/pull_request_template.md): exact commands/results, mock/real boundary, contracts, limitations and rollback. Humans review and accept; no automatic PR creation, board approval, deployment or merge.
