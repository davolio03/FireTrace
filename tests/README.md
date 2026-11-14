# Testing boundary

Python tests live beside the code they verify (`pipeline/tests/`, `api/tests/`) and run with `uv run pytest`, configured in the root `pyproject.toml`. Today they are package smoke tests only. Existing contract examples are checked with `uv run contracts/tools/validate.py`; this is not radar-method validation or a running API/web test.

The web scaffold must add real eslint/prettier/vitest gates, wired through `quality.json`, with tests beside the behavior they verify. Use small synthetic inputs for deterministic dB/validity/grid rules and failure paths; do not download real GeoTIFFs in tests.

Collect separately traceable real-data sample checks and end-to-end demo evidence. See [QUALITY](../docs/QUALITY.md) and [CONTRACTS](../docs/CONTRACTS.md) for current commands and unresolved scientific semantics.
