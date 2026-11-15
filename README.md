# FireTrace Explorer

Explore what changed in NISAR HH/HV radar observations before and after the **Plaskett Fire (Big Sur, California, 2026)**. Inspect the radar values behind every pixel and compare them with a dated official fire perimeter. Built for the NASA Space Apps Challenge 2026, *Dancing with the SARs*.

FireTrace shows **observed radar change**. Radar change is not confirmed fire, burned area or ecological severity: moisture, terrain, viewing geometry and vegetation can explain it too ([limitations](docs/LIMITATIONS.md)).

## Current state (2026-11-15)

- **Pipeline (`pipeline/`):** implemented and run on real data. It goes from the four NISAR GCOV inputs to the web bundle, with optional P1 stages (highlight mask, sensitivity sweep, zones to review, terrain tiles). Every stage verifies its inputs by sha256 and publishes atomically, and reruns are byte-identical.
- **API (`api/`):** a FastAPI service implements the contract endpoints: health, case, stats, layers, point inspection and transect profile. It reads the 10 m analysis rasters and verifies their manifests, and it is tested against the contract schemas. Serving it to the web with real data is integration task IN-02; deployment is DL-01.
- **Web (`web/`):** a React + MapLibre application with these parts:
  - before/after comparison;
  - independent layers with legends;
  - the change map and the reference perimeter;
  - results;
  - the Evidence Inspector and transect;
  - the guided story;
  - annotations.

  It loads the real bundle (IN-01) or the contract fixtures with a visible MOCK notice.
- **Not done:** a deployed demo, independent validation and any deep-learning model.

Task state lives only in Kanvas (`python3 .agents/skills/kanvas/kanvas.py status`); [STATUS](docs/STATUS.md) records the evidence.

## Data sources and attribution

| Source | Role | Identity | Provider and attribution |
| --- | --- | --- | --- |
| **NASA/ASF NISAR L2 GCOV (provisional)** | Primary observation | Before: `G4284560161-ASF`, 2026-08-16 02:56:39 UTC, orbit 5504. After: `G4340499432-ASF`, 2026-10-03 02:56:38 UTC, orbit 6196. Frequency A, HHHH and HVHV, track 42, frame 70, descending ([CMR before](https://cmr.earthdata.nasa.gov/search/granules.umm_json?concept_id=G4284560161-ASF), [CMR after](https://cmr.earthdata.nasa.gov/search/granules.umm_json?concept_id=G4340499432-ASF)) | NASA Earth science data, distributed by the Alaska Satellite Facility DAAC |
| **NASA GPM IMERG Late Run daily V07C** (`GPM_3IMERGDL`) | Precipitation context for the moisture caveat | 49 daily granules, 2026-08-16 to 2026-10-03 ([GES DISC](https://disc.gsfc.nasa.gov/datasets/GPM_3IMERGDL_07/summary)) | NASA Earth science data, distributed by NASA GES DISC |
| **NIFC WFIGS Interagency Perimeters** | Dated reference for contrast | OBJECTID 58728, dated 2026-09-14 20:44 UTC ([query](https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/WFIGS_Interagency_Perimeters_YearToDate/FeatureServer/0/query?where=OBJECTID%3D58728&outFields=*&returnGeometry=true&outSR=4326&f=geojson)) | NIFC open data |
| **CAL FIRE** | Incident facts (start date 2026-08-26) | [Incident page](https://www.fire.ca.gov/incidents/2026/8/26/plaskett-fire) | CAL FIRE |
| **Copernicus DEM GLO-30** | Terrain context (slope, hillshade, layover/shadow) | Tile `Copernicus_DSM_COG_10_N35_00_W122_00_DEM` ([DOI](https://doi.org/10.5270/ESA-c5d3d65)) | "Produced using Copernicus WorldDEM-30 © DLR e.V. 2010-2014 and © Airbus Defence and Space GmbH 2014-2018 provided under COPERNICUS by the European Union and ESA; all rights reserved" |
| **Copernicus Sentinel-2 L2A** | Optical context (smoke during, clear after) | `S2A_10SFE_20260830_0_L2A`, `S2B_10SFE_20261015_0_L2A`, via Earth Search ([AWS Open Data](https://registry.opendata.aws/sentinel-2-l2a-cogs/)) | Contains modified Copernicus Sentinel data 2026 (ESA) |

NISAR is the primary source. The other sources are context and never replace or validate the radar result. The web shows each layer's source with it. Every data set, service, software package and reference, with its licence, is listed in [REFERENCES](docs/REFERENCES.md), as the NASA Space Apps rules require. The scientific background is the Döweler, Leuzinger and Bader preprint on Plaskett and Timber ([SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=7553393)). Its AUC-ROC of 0.984 is their result, not FireTrace's.

## Methodology

All analysis runs offline on the common **10 m EPSG:32610** grid of the NISAR scenes.

1. **Ingest (DT-01):** crop the four GCOV power rasters around the perimeter (2 km margin) without resampling.
2. **dB and validity (DT-02):** `10 × log10(x)` for finite positive powers; one common valid mask over the four inputs.
3. **Continuous change (CH-01, P0):** signed HH and HV differences (after − before); the index is the robust z-score of `|ΔHH| + |ΔHV|` over the crop, with no threshold ([change index](docs/methods/change-index.md)).
4. **Reference perimeter (DT-03):** the pinned WFIGS geometry, repaired, rasterized by pixel centre with a 50 m edge band ([reference perimeter](docs/methods/reference-perimeter.md)).
5. **Statistics (CH-02):** index distributions inside and outside the perimeter ([stats](docs/methods/stats.md)).
6. **Context (DT-05, DT-06, DT-07):** [terrain](docs/methods/terrain.md), [precipitation](docs/methods/weather.md) and [optical](docs/methods/optical.md) layers.
7. **Exploratory, P1:**
   - the [highlight mask](docs/methods/highlight.md) with its IoU;
   - the [sensitivity sweep](docs/methods/sensitivity.md);
   - the [zones to review](docs/methods/review-zones.md);
   - [3D terrain tiles](docs/methods/terrain-tiles.md).
8. **Web export (DT-04):** contract bundle with EPSG:3857 display PNGs ([web export](docs/methods/web-export.md)).
9. **Inspection (EV-01, EV-05):** the API reads the numerical rasters, never the PNG colours. The deterministic [caveat rules](docs/methods/caveats.md) (EV-02) are implemented but not yet wired into the real point inspection, which returns only generic cautions.

## Results on Plaskett

From the releases of commit `f66c4d9`:

- **Coverage:** 100 % valid.
- **Change index:** median 0.50 inside the perimeter versus −0.22 outside.
- **Highlighted radar changes (P1):** 1,049.66 ha, of which 0.46 ha lie outside. The highlight covers 8.6 % of the perimeter, and its IoU of 0.086 is limited by its size.
- **Zones to review:** none with change outside; 10 with little change inside, mostly along the perimeter line; 10 with change inside.

The discrepancies, their possible causes and the limitations are in [LIMITATIONS](docs/LIMITATIONS.md).

## Run it locally

Requirements: Python 3.11 with [uv](https://docs.astral.sh/uv/), Node 24 and the GitHub CLI.

```sh
uv sync
npm ci --prefix web
```

Real data comes from GitHub releases, never from Git. Download and verify both from the repository root:

```sh
gh release download data-web-plaskett-f66c4d9 -D data/processed
gh release download data-interim-plaskett-f66c4d9 -D data
cd data/processed && sha256sum -c SHA256SUMS.txt && unzip -o firetrace-web-plaskett.zip && cd ../..
cd data && sha256sum -c SHA256SUMS.txt && unzip -o firetrace-interim-plaskett.zip && cd ..
uv run contracts/tools/validate.py data/processed/web
```

- **Web with the real bundle:** serve `data/processed/web/` locally and start the web with `VITE_USE_MOCKS=false` and `VITE_DATA_BASE_URL`, as recorded in [DEMO](docs/DEMO.md).
- **Web with the contract fixtures:** run `npm run dev` in `web/`; it shows a MOCK notice.
- **API:** the service reads `data/` by default; `FIRETRACE_DATA_ROOT` selects another directory. It is exercised by `uv run pytest api`.
- **Rebuilding the data:** this needs the raw inputs (GCOV GeoTIFFs and `.h5`, DEM tile, WFIGS GeoJSON, IMERG and Sentinel-2 windows), which are not distributed. The stage commands are in [QUALITY](docs/QUALITY.md).

The demo needs no Earthdata login, scene download or model training.

## Quality checks

```sh
python3 scripts/check.py
uv run contracts/tools/validate.py
git diff --check
```

`scripts/check.py` runs the Python and web lint, tests and build ([QUALITY](docs/QUALITY.md)). These checks test the software, not the science.

## Use of AI

AI coding agents (Claude Code and Codex through T3 Code, and OpenCode with Claude models) helped write and review code and documentation. People made the scientific decisions, approved every task and reviewed and merged every change. The product runs no AI and shows no AI-generated evidence. See [AI_USE](docs/AI_USE.md).

## Team navigation

| Resource | Purpose |
| --- | --- |
| [AGENTS](AGENTS.md) | Team contract for people and agents |
| [Proposal](docs/propuesta.md) / [PRODUCT](docs/PRODUCT.md) | Scientific and product scope, P0/P1 and acceptance criteria |
| [ARCHITECTURE](docs/ARCHITECTURE.md) | Stack, data flow, artifact layout and geographic invariants |
| [CONTRACTS](docs/CONTRACTS.md) / [contracts](contracts/README.md) | Executable schemas, OpenAPI and fixtures |
| [Methods](docs/methods/) | How each product is computed, with its real-data result |
| [LIMITATIONS](docs/LIMITATIONS.md) / [AI_USE](docs/AI_USE.md) | Discrepancies, limitations and the AI-use declaration |
| [REFERENCES](docs/REFERENCES.md) | Data, software and references with their licences |
| [TEAM](docs/TEAM.md) / [CONTRIBUTING](CONTRIBUTING.md) | Owners, Kanvas, worktrees and human review |
| [STATUS](docs/STATUS.md) / [DEMO](docs/DEMO.md) | Evidence snapshot and rehearsal runbook |
| [QUALITY](docs/QUALITY.md) / [quality.json](quality.json) | Quality gate and pipeline commands |
| [ENGRAM_CLOUD](docs/ENGRAM_CLOUD.md) | Shared team memory |

## Licence

FireTrace's code and documentation are licensed under the [Apache License 2.0](LICENSE); see [NOTICE](NOTICE). Data are not in the repository and keep the licences listed in [REFERENCES](docs/REFERENCES.md).

## Safety and delivery

One writer per worktree. Contract changes need approval from the affected side and their own versioned PR. People own publication, review and merge. No direct or force pushes to `main`, and no secrets, raw data, model weights or memory exports in Git.
