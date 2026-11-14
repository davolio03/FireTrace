# Data and API contract — v1.2.0

The contract lets **pipeline, API and web move in parallel**. Each side codes against the contract, not against the others' code.

```text
              contracts/schemas/*.schema.json   ← source of truth (JSON Schema 2020-12)
              contracts/openapi.yaml            ← API endpoints (reference the schemas)
                         │
   ┌─────────────────────┼──────────────────────────┐
   ▼                     ▼                          ▼
pipeline/            api/ (FastAPI)              web/ (React)
writes                serves the products;       reads data/web/* + API;
data/processed/web/   its tests validate         TS types generated from OpenAPI;
and checks it with    responses against          in mock mode uses
validate.py           the schemas                contracts/fixtures/ + MSW
```

## The key rule: same shape, different source

`contracts/fixtures/web/` has **exactly the same layout** the real pipeline writes to `data/processed/web/`:

```text
case.json             case metadata                          → case.schema.json
stats.json            metrics over valid pixels              → stats.schema.json
layers.json           layer manifest + legends               → layers.schema.json
perimeter.geojson     WFIGS 58728 perimeter (EPSG:4326)
layers/<id>.png       one RGBA PNG per raster layer, already in EPSG:3857 (transparent = no-data)
review_zones.geojson  (P1, optional) zones to review         → review-zones.schema.json
weather.json          daily rain between acquisitions        → weather.schema.json
story.json            FIXTURES ONLY: example guided story    → story.schema.json
```

| Other contracts | Where |
|---|---|
| Transect `POST /api/inspect/profile` | `schemas/profile.schema.json` + `openapi.yaml` |
| Terrain in the inspector (`terrain`: elevation, slope, aspect) | optional field of `inspect-point.schema.json` |
| Analyst annotation export (GeoJSON) | `schemas/annotations.schema.json` |
| Guided story (production file: `web/src/story/story.json`) | `schemas/story.schema.json` |
| Shared web state (store and actions) | [`web-state.md`](web-state.md) |

- **Web:** the data base path comes from `VITE_DATA_BASE_URL` and the API from `VITE_API_BASE_URL`; with `VITE_USE_MOCKS=true`, MSW answers `/api/*` from `contracts/fixtures/api/`. Switching from mock to real is an environment change, not a code change.
- **API:** tests use `contracts/fixtures/`; in production it reads `data/processed/`.
- **Pipeline:** done = `uv run contracts/tools/validate.py data/processed/web` passes.

Every versioned JSON file carries `data_status: "mock" | "real"`. **The web must show a visible MOCK notice** when it is `mock`, so synthetic data is never presented as real.

## Raster layers: PNG + corners

Each layer is an image drawn by MapLibre through an `image` source and its 4 corners (`coordinates` in `layers.json`). There is no tile server. At the AOI size (~20 × 17 km at 10 m, about 2000 × 1700 px) this is simple and fast. The pipeline fixes palette and range and describes them in `legend`, so the web draws legends without knowing the data.

Fixed layer IDs: `sar_t1_hh`, `sar_t2_hh`, `sar_t1_hv`, `sar_t2_hv`, `change_hh`, `change_hv`, `change_index`, `highlight_mask` (P1), `valid_mask`, `perimeter`, `review_zones` (P1), `optical_during`, `optical_after`, `hillshade`, `slope`. The `group` field (`sar`, `observed_change`, `highlighted_change`, `reference`, `quality`, `optical_context`, `terrain`) keeps the observation / interpretation / contrast separation in the UI. Non-NISAR layers (`optical_context`, `terrain`) **must** carry `source`, and the UI shows it.

Per-pixel numbers never come from the PNGs; they come from `GET /api/inspect/point`.

## Zones to review (P1 · EV-04)

`review_zones.geojson` lists precomputed, ranked connected regions so the analyst knows **where to look first**:

| `kind` | Prefix | Meaning |
|---|---|---|
| `change_outside_perimeter` | `CO` | Highlighted radar change **outside** the perimeter → discrepancy |
| `no_change_inside_perimeter` | `NI` | Little radar change **inside** the perimeter → discrepancy (unburned island? radar limitation?) |
| `change_inside_perimeter` | `CI` | Highlighted change inside → **agreement** examples |

Each zone carries area, centroid and bbox (so the map can fly to it), HH and HV medians before/after/delta, the index, the distance to the perimeter and the share of pixels where each caveat fires. `method` documents the thresholds used. Everything comes from the pipeline: the web recomputes nothing. Discrepancies are presented as **"to investigate"**, never as radar or perimeter errors.

## Work lanes and the contract that separates them

Designed for 4–5 people. Each lane delivers against the contract and tests with fixtures; only the `IN-*` tasks bring lanes together. Owners and tasks: [docs/TEAM.md](../docs/TEAM.md).

| Lane | Produces | Consumes (mock until IN-*) |
|---|---|---|
| **L1 Radar data** | dB, index, stats, zones, SAR layers (`data/processed/web`, analysis COGs) | — |
| **L2 Context data** | perimeter, DEM → `hillshade`/`slope` + terrain COG, `weather.json`, optical layers | AOI from `case.json`; NISAR grid from DT-01 to align the terrain COG |
| **L3 API** | `/api/inspect/point` (+ `terrain`), `/api/inspect/profile`, caveat rules | COGs from L1 and L2 (fixtures in tests) |
| **L4 Web: map** | map, layers, swipe, inspector, transect, context layers | fixtures + MSW, store from `web-state.md` |
| **L5 Web: experience** | overview, metrics, zones, guided story, annotations and report, demo | fixtures + MSW, store from `web-state.md` |

With four people, one person owns L2 and L3.

## Fixtures (all synthetic except the perimeter geometry)

| File | Use |
|---|---|
| `fixtures/web/*` | Mock data with the production layout |
| `fixtures/api/inspect-point-{inside,outside,invalid}.json` | Example inspector responses (inside the perimeter, outside, no-data pixel) |
| `fixtures/api/stats-with-highlight.json` | `stats` with the P1 mask enabled, to build the F05 widgets |
| `fixtures/api/inspect-grid.json` | **Mock only**: compact grid MSW uses to answer any click or transect with consistent values (includes elevation and slope) |
| `fixtures/api/profile-example.json` | Transect crossing the perimeter: HV drops when entering |
| `fixtures/web/story.json` | Starting 5-step story (draft copy) |
| `fixtures/web/weather.json` | Mock rain with an event on 24–26 September |
| `fixtures/exports/annotations.geojson` | Example annotation export |

Regenerate the mocks (deterministic, fixed seed):

```bash
uv run contracts/tools/generate_mocks.py
uv run contracts/tools/generate_mocks.py --perimeter-source data/raw/wfigs_58728_raw.geojson   # re-simplify the perimeter
uv run contracts/tools/validate.py          # validate fixtures; runs in CI
```

## Changing the contract

1. Branch `docs/contract-<topic>` and a PR containing only the contract change.
2. Update schema(s) → `openapi.yaml` if relevant → regenerate fixtures → `validate.py` green.
3. Bump `contract_version`: **patch** = clarification, **minor** = new optional field (compatible), **major** = rename, remove or change the meaning of a field.
4. At least one reviewer from each affected side (data and web/API).
5. Record the decision in Engram (project `firetrace`, see [docs/ENGRAM_CLOUD.md](../docs/ENGRAM_CLOUD.md)).

A contract change never hides inside a feature PR.
