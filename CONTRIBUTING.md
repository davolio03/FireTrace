# Contributing to FireTrace

Read [AGENTS.md](AGENTS.md) and [onboarding](docs/ONBOARDING.md). Kanvas is the **only task state**; GitHub Issues support discussion, references and acceptance criteria. Proposals require human approval, and each task needs an accountable owner.

Use one feature/task per branch and worktree, one writer per worktree. Start from updated `main` when authorized; branch names use `feat/<ID>-topic`, `fix/<ID>-topic`, `docs/<ID>-topic` or another agreed Conventional Commit type. No direct `main` push, force push, hook bypass or destructive cleanup. Commit/publish only when explicitly requested.

Respect existing executable interfaces. Shared schema, numerical-semantic or dependency changes need affected owners' agreement; contract changes get a separate versioned PR and fixtures/tests. Keep unrelated work separate. The baseline continuous P0 must work before threshold/DL P1.

Before handoff, run `python3 scripts/check.py`, `uv run contracts/tools/validate.py` and `git diff --check`; inspect untracked files and relevant real application lint/tests/build. Report exact observed results/exit codes and environment limitations. The repository gate refuses application source without configured real lint/tests; a bootstrap pass is not app/science evidence.

Use the [PR template](.github/pull_request_template.md) to prepare review evidence, including Kanvas reference or explicit direct authorization, touched contracts, scientific/mock status, security, demo limitations and rollback. A human owns publication/review/merge; cross-boundary changes need a second teammate.

Save reusable approved decisions and verified findings to the `firetrace` Engram project in English. Label implementation status honestly; do not commit memory exports or save private information. Keep Kanvas state and demo evidence current through their authorized workflows rather than duplicating a backlog in docs.
