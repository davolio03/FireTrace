# Shared interfaces — executable v1.2.0, real science still to verify

**Authoritative definitions:** [contracts/README.md](../contracts/README.md), [JSON Schemas](../contracts/schemas/) and [OpenAPI 3.1](../contracts/openapi.yaml). This guide explains their semantics; it does not redefine fields or change interfaces. Schemas, fixtures and tooling already exist. The real pipeline/API/web do not.

## Interface registry

| Producer → consumer | Defined artifact/interface | Source |
| --- | --- | --- |
| Pipeline → web/API | `case.json`: identity, epochs/acquisition, reference, method, generation/version metadata | [case schema](../contracts/schemas/case.schema.json) |
| Pipeline → web/API | `stats.json`: valid/total pixels, coverage, distributions inside/outside reference, nullable P1 highlight | [stats schema](../contracts/schemas/stats.schema.json) |
| Pipeline → web | `layers.json`: fixed IDs/groups, URLs, legends and four raster corners | [layers schema](../contracts/schemas/layers.schema.json) |
| Pipeline → web | RGBA PNG layers + WGS84 `perimeter.geojson` | [artifact layout](../contracts/README.md) |
| API → web | Health, case, stats, layers and point inspection (optional `terrain`) | [OpenAPI](../contracts/openapi.yaml) / [inspection schema](../contracts/schemas/inspect-point.schema.json) |
| API → web | Transect: `POST /api/inspect/profile` | [profile schema](../contracts/schemas/profile.schema.json) |
| Pipeline → web (P1) | `review_zones.geojson`: ranked change-outside / little-change-inside / agreement zones | [review-zones schema](../contracts/schemas/review-zones.schema.json) |
| Context data → web | `weather.json` (precipitation between acquisitions); `optical_*`, `hillshade`, `slope` layers with mandatory `source` | [weather schema](../contracts/schemas/weather.schema.json) / [layers schema](../contracts/schemas/layers.schema.json) |
| Storytelling → web | Guided story steps (`web/src/story/story.json`) | [story schema](../contracts/schemas/story.schema.json) |
| Context data → web (optional) | `terrain/tiles.json` + Terrarium `terrain/{z}/{x}/{y}.png` 3D relief for the story | [terrain-tiles schema](../contracts/schemas/terrain-tiles.schema.json) |
| Web → analyst | Annotation export (GeoJSON) for the report | [annotations schema](../contracts/schemas/annotations.schema.json) |
| Web L4 ↔ L5 | Shared store shape and actions | [web-state](../contracts/web-state.md) |

`contract_version` is `1.2.0`; the versioned JSON envelopes identify `data_status: mock | real`. Do not infer that every PNG/GeoJSON has that property. Mocks require a visible MOCK notice; changing a label to `real` is not evidence of processing.

The real web output mirrors `contracts/fixtures/web/` under `data/processed/web/`. The mock API examples cover inside/outside perimeter and invalid pixels. `inspect-grid.json` is a compact **mock-only** lookup aid; it is not the real scientific raster representation. Region inspection is covered by precomputed `review_zones.geojson` properties (v1.1); an on-demand region endpoint is still undefined: discuss an extension before implementing it. Zone kinds describe radar change versus the reference perimeter, never burned/unburned.

## Defined numerical and geographic meaning

| Topic | Current contract / required interpretation |
| --- | --- |
| Power/dB | GCOV power: `10 * log10(x)` only for finite positive unmasked values; never amplitude `20 * log10`. |
| Signed change | Per-polarization `delta = t2 - t1` in dB. Continuous combined change must identify its actual method/params. |
| Invalid samples | Common valid set across all four inputs. `valid=false` means numerical values are null; no fabricated zero/confidence. Schema structure alone does not enforce every cross-field condition. |
| Analysis | Point sampling on the 10 m EPSG:32610 grid; return sampled row/column, projected position and WGS84 center. |
| Display | PNGs warped/resampled to EPSG:3857; transparency means invalid/no-data. Corners are WGS84 `[lon, lat]` in top-left, top-right, bottom-right, bottom-left order. |
| Point query | `/api/inspect/point?lon=...&lat=...` uses WGS84. Out-of-AOI remains 200 with `valid=false`, `pixel=null`; malformed/out-of-range parameters use 422. |
| Transect query | `POST /api/inspect/profile` samples the 10 m analysis grid at `spacing_m` (default 10 m) along a WGS84 `[lon, lat]` polyline, includes the final endpoint once and caps the response at 2,000 samples (`truncated`). Masked or out-of-grid positions stay in `samples` with null values; `perimeter_crossings_m` marks inside/outside changes on the operational perimeter. Invalid bodies use 422; unavailable or incompatible products use 503. |
| Coverage | Invalid pixels excluded; valid/total domain, area units and denominator must be documented, not assumed from a fixture. |
| P1 | `highlight=null` when disabled; inspection `highlighted=null`. Hide optional widgets. Flagged area/IoU are reference agreement, not validated burned area/severity. |

Retain before `G4284560161-ASF` (2026-08-16 02:56:39 UTC) and after `G4340499432-ASF` (2026-10-03 02:56:38 UTC), frequency A HH/HV, track 42/frame 70 descending, orbits 5504/6196. Reference WFIGS 58728 is dated 2026-09-14 20:44 UTC, before the after scene. See [PRODUCT](PRODUCT.md) and the [proposal](propuesta.md) for reported verification boundaries and sources.

## Real-processing agreements still open

These are not permission to silently alter fields or use fixture numbers as science:

- **Domain:** exact AOI/crop margin, rasterization/pixel inclusion rule, inside/outside boundary policy, coverage denominator and empty/all-invalid behavior. The reported 1,948,374 positive crop pixels do not define all product metrics.
- **Continuous index:** exact absolute HH/HV combination, robust normalization domain/scaling, zero-MAD handling, clipping and comparison tolerances. `method.params` can carry agreed parameters; the mock median/MAD formula is not validated real processing.
- **Display/lookup:** chosen resampling, color scale/stretch, coordinate rounding/pixel selection and numerical/display result identity. Do not interpolate scientific values from a rendered PNG.
- **Physical interpretation:** moisture, slopes/shadow/layover, geometry and vegetation cautions; deterministic rule thresholds versus generic limitations. No invented trigger or confidence.
- **P1 only:** threshold/smoothing, connected regions, valid IoU intersection/union domain, reference rasterization and sensitivity. IoU must not count unavailable pixels as measured negatives.
- **Reproducibility:** input integrity identities, exact numerical artifact layout, configuration and environment/revision. Where the existing schema cannot express required shared provenance, propose a contract extension rather than extra undocumented fields.

## What validation proves

```sh
uv run contracts/tools/validate.py
uv run contracts/tools/validate.py data/processed/web
```

The existing validator checks web case/stats/layers JSON against schemas, referenced layer-file existence, case/layers status consistency, and (in fixture mode) the highlight stats and inspect-point examples. It does **not** validate the OpenAPI document, every mock-only file, scientific arithmetic, PNG reprojection, perimeter geometry, all cross-file identities or real data provenance. A pass is necessary interface evidence, not application/scientific acceptance.

Real producers/consumers must add known-value, invalid/zero/negative input, no-data/out-of-AOI, grid/CRS mismatch, coverage arithmetic and display/lookup consistency tests. Agree tolerances and collect real sample evidence separately.

## Contract change approval

Use a dedicated `docs/contract-<topic>` PR: update schemas/OpenAPI as applicable, fixtures, version and checks; review from each affected producer/consumer side. Patch clarifies; minor adds compatible optional fields; major renames/removes/changes meaning. Numerical-semantic changes count even without an HTTP signature change. Record the accepted decision and affected owners in Git and reusable Engram history. Kanvas alone holds task state; a proposed board item is not scientific approval.
