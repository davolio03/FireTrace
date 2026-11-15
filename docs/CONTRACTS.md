# Shared interfaces — executable v1.2.0, real science still to verify

**Authoritative definitions:** [contracts/README.md](../contracts/README.md), [JSON Schemas](../contracts/schemas/) and [OpenAPI 3.1](../contracts/openapi.yaml). This guide explains their semantics; it does not redefine fields or change interfaces. The pipeline and web are implemented; integration of the real inspection API remains separate work.

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
| Coverage | Invalid pixels excluded; valid/total domain, area units and denominator must be documented, not assumed from a fixture. |
| P1 | `highlight=null` when disabled; inspection `highlighted=null`. Hide optional widgets. Flagged area/IoU are reference agreement, not validated burned area/severity. |

Retain before `G4284560161-ASF` (2026-08-16 02:56:39 UTC) and after `G4340499432-ASF` (2026-10-03 02:56:38 UTC), frequency A HH/HV, track 42/frame 70 descending, orbits 5504/6196. Reference WFIGS 58728 is dated 2026-09-14 20:44 UTC, before the after scene. See [PRODUCT](PRODUCT.md) and the [proposal](propuesta.md) for reported verification boundaries and sources.

## Documented processing choices and remaining verification

The implemented Plaskett methods document the following choices. They do not change the schemas or turn observations into scientific validation.

- **Continuous index:** signed HH/HV dB changes are combined as `|ΔHH| + |ΔHV|` and normalized over the common-valid crop using the median and `1.4826 × MAD`. The index is not clipped or thresholded; zero MAD or no valid pixels is an error. See [change-index](methods/change-index.md).
- **Statistics domain:** coverage is valid pixels divided by all crop pixels. Inside/outside use the perimeter pixel-centre mask; the 50 m boundary band is included and the outside group includes open water. Area uses the 10 m analysis grid, not display pixels. See [stats](methods/stats.md).
- **Display:** radar floats are reprojected to EPSG:3857 with nearest-neighbour resampling before colouring; radar stretches are shared for comparable layers. Terrain context has its own resampling rule. Never derive scientific values from colours. See [web export](methods/web-export.md).
- **P1:** documented highlight and review-zone rules are exploratory; their thresholds and overlap metrics do not establish burned area or accuracy. See [highlight](methods/highlight.md) and [review zones](methods/review-zones.md).
- **Remaining verification:** retain moisture, terrain, geometry, vegetation and reference-date cautions. The release's schema and hash checks do not independently prove numerical accuracy, geolocation or scientific interpretation. Real inspection API integration and display/lookup consistency remain separate work; agree any comparison tolerances needed for that work. Preserve input identities, configuration and environment/revision evidence. If additional shared provenance is required, agree a contract extension rather than adding undocumented fields.

## What validation proves

```sh
uv run contracts/tools/validate.py
uv run contracts/tools/validate.py data/processed/web
```

The existing validator checks web case/stats/layers JSON against schemas, referenced layer-file existence, case/layers status consistency, and (in fixture mode) the highlight stats and inspect-point examples. It does **not** validate the OpenAPI document, every mock-only file, scientific arithmetic, PNG reprojection, perimeter geometry, all cross-file identities or real data provenance. A pass is necessary interface evidence, not application/scientific acceptance.

Real producers/consumers must add known-value, invalid/zero/negative input, no-data/out-of-AOI, grid/CRS mismatch, coverage arithmetic and display/lookup consistency tests. Agree tolerances and collect real sample evidence separately.

## Contract change approval

Use a dedicated `docs/contract-<topic>` PR: update schemas/OpenAPI as applicable, fixtures, version and checks; review from each affected producer/consumer side. Patch clarifies; minor adds compatible optional fields; major renames/removes/changes meaning. Numerical-semantic changes count even without an HTTP signature change. Record the accepted decision and affected owners in Git and reusable Engram history. Kanvas alone holds task state; a proposed board item is not scientific approval.
