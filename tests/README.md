# Testing boundary

No application tests are implemented by this foundation. Existing contract examples are checked with `uv run contracts/tools/validate.py`; this is not radar-method validation or a running API/web test.

Scaffold tasks must add real ruff/pytest and eslint/prettier/vitest gates, wired through `quality.json`, with tests beside the behavior they verify. Use small synthetic inputs for deterministic dB/validity/grid rules and failure paths; do not download real GeoTIFFs in tests.

Collect separately traceable real-data sample checks and end-to-end demo evidence. See [QUALITY](../docs/QUALITY.md) and [CONTRACTS](../docs/CONTRACTS.md) for current commands and unresolved scientific semantics.
