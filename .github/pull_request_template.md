## Kanvas task and goal

<!-- Task ID/title and board reference; explain explicit direct authorization if no approved matching task exists. Optional linked issue for acceptance/discussion, not task state. -->

## What changed and why

<!-- User/module outcome, smallest approach, review order and excluded work. -->

## Contracts and scientific evidence

- Contracts changed: <!-- None, or separate contract PR/version and affected-side approvals. -->
- Data/method evidence: <!-- Mock or real; provenance, validity/CRS checks and reproducible numerical evidence, or N/A. No unearned fire/severity/confidence claims. -->

## Actual verification

- [ ] `python3 scripts/check.py` run; actual result recorded
- [ ] `uv run contracts/tools/validate.py` run, or interpreter/dependency limitation explained
- [ ] Meaningful lint/tests/build and failure paths for changed application behavior, or explicit N/A
- [ ] `git diff --check` plus direct inspection of new/untracked files
- [ ] Cross-module consistency checked where relevant
- [ ] No secrets, private data or committed memory exports

Commands, environment, observed results and exit codes:

```text
<actual evidence; distinguish bootstrap/fixture checks from application/science tests>
```

## Demo, risks and rollback

<!-- Reproducible steps/screenshots, visible MOCK labeling where applicable, limitations and exact rollback boundary. Never present mocks as real evidence. -->

## Human review and follow-up

<!-- Affected owners/reviewer, pending decisions and reusable Engram/docs follow-up. Kanvas review/done remains human-owned; no automatic PR creation or merge. -->
