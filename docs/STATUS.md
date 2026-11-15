# Evidence and readiness snapshot

**Documentation baseline: 2026-11-15.** Kanvas remains the only canonical task state. This page describes what is established by evidence, not task progress or new approvals.

| Boundary | What exists, with evidence | What is not established |
| --- | --- | --- |
| Shared interfaces | v1.2.0 schemas, OpenAPI, fixtures and validator | Scientific correctness of any value |
| Pipeline | Every stage from ingest to web export runs on the real Plaskett inputs; manifests chain sha256 from the raw inputs to the bundle; reruns are byte-identical ([methods](methods/)) | Validation against an independent reference |
| Real data | GitHub releases `data-web-plaskett-f66c4d9` (web bundle, passes `contracts/tools/validate.py`) and `data-interim-plaskett-f66c4d9` (analysis rasters whose manifests match the bundle's `export.json`) | Raw inputs are not distributed |
| API | Contract endpoints implemented and tested with synthetic rasters; `FireTraceRasterService` answered health, point and transect queries on the real releases with `data_status: real` | Web integration with the real API (IN-02); the EV-02 caveat rules wired into real point inspection (it returns only generic cautions); a served, deployed instance (DL-01) |
| Web | Real-bundle integration reviewed by people ([DEMO](DEMO.md), IN-01); MOCK fallback works | Real-data story and context (IN-03); a timed rehearsal |
| Delivery docs | [README](../README.md), [LIMITATIONS](LIMITATIONS.md) and [AI_USE](AI_USE.md) cover proposal criteria 9 and 10 | Each member's AI-tool row; the official submission rules |
| Shared memory | `firetrace` identity; Cloud selected | Team-wide enrollment |

Open decisions: hosting and deployment (DL-01), the official challenge and source-usage rules, and named reviewers and backups ([TEAM](TEAM.md)).

Record actual application and real-data rehearsal evidence in [DEMO](DEMO.md), with revision and artifact identities, commands, exit codes, limitations and fallback. Contract and bootstrap checks alone never make the product scientifically validated or demo-ready.
