# Publication privacy recovery

## Objective and authorization
Sanitize current publishable files while preserving local working configuration and leaving Git history untouched. Explicit direct user authorization was relayed by the parent on 2026-11-15; no matching approved Kanvas task is claimed. The live board is unchanged and is the only canonical task state. This document is recovery evidence, not another board.

## Scope and constraints
- Branch: `fix/publication-privacy`, based on local `main` at `92e95fb`.
- Ignore/untrack private board configuration and the stale board snapshot without changing their local bytes.
- Publish an example configuration; remove real infrastructure identifiers from tracked guidance.
- Fail closed if live-board configuration is missing; never silently use the stale snapshot.
- No remote access, installs, commit, push, PR, or history rewrite authorized. Preserve public attribution and AI disclosure.

## Route and test policy
Delegated direct: multiple configuration/documentation files and a discovered fail-closed CLI edge case. Full effective ODD TDD mode is unknown (parent found no authoritative configuration); do not claim strict mode. Project deterministic-rule test-first policy applies: observe RED/GREEN for ignore rules and missing-config behavior. Existing runners: `uv run pytest` and `python scripts/check.py`; offline only.

## Checklist
- [ ] PP-01: Implementation verified: current files sanitized, original ignored local bytes preserved, focused tests/scan pass. Work unit remains open pending an authorized commit.
- [ ] PP-02: Checks and readback performed; full gate is partial due to missing web dependencies. Pending environment resolution and authorized work-unit commit.

## Acceptance and verification
No private infrastructure identifiers or personal absolute paths in candidate tracked text; example endpoint is reserved/nonoperational; real configuration and board snapshot remain ignored with original bytes; missing config cannot reach a local board; existing remote behavior still passes synthetic tests. Foreground checks: `python scripts/check.py`, `UV_OFFLINE=1 uv run contracts/tools/validate.py`, `git diff --check`, `git diff --cached --check`.

## Progress and evidence
- Initial ignore RED: `git check-ignore --no-index .agents/skills/kanvas/remote.json kanvas.json` exited 1; neither file ignored.
- Parent approved a minimal fail-closed safeguard after confirming that removing tracked remote configuration otherwise exposes local-snapshot fallback. A neighboring example marker scopes this behavior to configured live-board projects; generic Kanvas and explicit server-local behavior remain available.
- Focused configuration RED: `python -m unittest discover -s tests -p test_kanvas_configuration.py` exited 1 (six tests, five failing cases for missing/empty config). Final GREEN: same command exited 0 (six tests).
- Ignore GREEN: the original ignore command exited 0; both files are now ignored and untracked, and their bytes match the original HEAD versions.
- Candidate rescan: 299 tracked/new paths; no private host/IP or personal absolute path matches. Public example uses a reserved nonoperational hostname.
- `UV_OFFLINE=1 uv run ruff check tests/test_kanvas_configuration.py`: exit 0. Unexpectedly synchronized two packages from local cache; no network used, but this was an unrequested environment mutation. Further uv commands use `UV_NO_SYNC=1`; no environment rollback attempted.
- Existing project interpreter: `.venv/Scripts/python.exe`, Python 3.11.9 (default `python` is 3.10.5).
- Offline contract validation exited 0: `OK: contract satisfied`. Inline script metadata ignores no-sync and uses isolation; no new installation was reported.
- `git diff --check` and `git diff --cached --check`: exit 0.
- Foreground `.venv/Scripts/python.exe scripts/check.py` with `UV_OFFLINE=1 UV_NO_SYNC=1`: exit 1. Python/web lint passed; Python tests: 795 passed, 9 skipped (three symlink-unavailable cases and six real-data cases without a verified bundle), 2848 warnings. Web tests: 173 passed, two failed, four failed files (three failed import suites plus worker-build tests); existing local dependencies lack `motion` and the Space Grotesk / IBM Plex Mono fonts declared by unchanged main. No web source/manifest edits were made. Standalone build was not reached because the gate stops on test failure. No install attempted to repair it.
- Focused tests also passed with project Python 3.11.9. These offline tool tests live outside the application's configured pytest testpaths and were run explicitly, not claimed as part of the 795 application tests.
- No commits, publication, live-board calls, or history rewrite performed.
- Independent read-only verification found no privacy blocker. Its CI coverage gap was corrected by adding the six offline configuration tests to the existing workflow; no new service or dependency is involved.
- Engram initial full mirror #3335 was read back; progress mirror maintained under the same topic.

## Delivery and rollback
Strategy: `ask-on-risk`; no PR or commit authorized. Forecast: about 150 authored changed lines plus removal from tracking of the existing board snapshot (content unchanged locally); snapshot deletion can exceed the 400-line heuristic without meaningful benefit from splitting. Running committed authored lines: 0. No slice selected.
Rollback boundary: this branch's privacy guidance/configuration, ignore rules, and CLI safeguard/tests only; restore tracking only with explicit approval because it reintroduces private metadata.

## Next step
Hand off the verified privacy implementation and failed full-gate evidence. Ask the human separately about restoring missing local web dependencies and any commit/publication. Git history, including prior metadata, remains unchanged.
