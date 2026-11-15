# FireTrace Explorer

Explore the **Plaskett Fire, Big Sur, California (2026)** through NISAR radar observations: compare before and after, inspect the numerical evidence, and investigate where radar changes agree with a dated official perimeter. Built for NASA Space Apps Challenge 2026, *Dancing with the SARs*.

**Observed radar change is not confirmed fire, burned area or ecological severity.** Moisture, terrain, viewing geometry and vegetation can also change the signal. The WFIGS perimeter is dated **14 September 2026**, before the 3 October after observation; it is neither a final outline nor pixel-level ground truth.

## Explore the case

- Follow the guided story from the globe to the Plaskett observations, then enter the analysis map.
- Compare aligned HH/HV before and after views; independently toggle **Observed radar changes**, the **Official fire perimeter**, legends and contextual layers.
- Select a point in the **Evidence Inspector** to read HH/HV dB, signed differences, change index, terrain and deterministic caveats from the analysis products. Draw a transect to explore sampled values along a line.
- Inspect descriptive statistics, precipitation and optional highlighted changes/review zones. Add analyst annotations and export GeoJSON or a Markdown report; analyst judgements are not validated classifications.
- Switch between the real artifact bundle/API and synthetic fixtures with a visible **MOCK** notice. Mocks are a software demonstration, not scientific evidence.

The pipeline precomputes products offline; FastAPI samples the analysis rasters; the React application displays the bundle and queries the API. No scene downloads, Earthdata authentication or model training belongs in the presentation. This repository provides a local demo; no hosted endpoint or independent scientific validation is claimed here.

## Data and attribution

**NISAR is the primary observation.** Other sources provide context or a dated reference, not independent validation.

| Source | Use and identity |
| --- | --- |
| NASA/ISRO NISAR L2 GCOV (provisional), distributed by ASF DAAC | Frequency A HHHH/HVHV; before `G4284560161-ASF` (2026-08-16), after `G4340499432-ASF` (2026-10-03); descending track 42, frame 70 |
| NIFC WFIGS / CAL FIRE | WFIGS OBJECTID 58728, 2026-09-14 20:44 UTC; CAL FIRE incident start 2026-08-26 |
| NASA GPM IMERG Late daily V07C, distributed by GES DISC | Precipitation context between the radar observations; not a soil-moisture measurement |
| Copernicus DEM GLO-30 (European Union / ESA) | Terrain context and optional 3D relief; produced using Copernicus WorldDEM-30 © DLR e.V. 2010-2014 and © Airbus Defence and Space GmbH 2014-2018 provided under COPERNICUS by the European Union and ESA; all rights reserved |
| Copernicus Sentinel-2 L2A, via Earth Search | Smoke context on 2026-08-30 and clear optical context on 2026-10-15; contains modified Copernicus Sentinel data 2026 |
| OpenStreetMap contributors | Basemap, with attribution in the map; [ODbL and copyright](https://www.openstreetmap.org/copyright) |

Full citations, source links, software licences and redistribution terms are in [References and licences](docs/REFERENCES.md). The external preprint's AUC-ROC of **0.984 is the authors' result, not FireTrace performance**.

## Method and example results

1. Crop the four GCOV power inputs to the common **10 m EPSG:32610 analysis grid**. Mask source no-data, non-finite, zero and negative powers; use the common valid set across all four inputs.
2. Convert valid power with `10 * log10(x)`. Compute signed HH/HV differences (after minus before) and a continuous robust z-score of `abs(delta_HH) + abs(delta_HV)` relative to this crop.
3. Compare distributions with the dated perimeter. Optional P1 products add a documented highlight threshold, sensitivity sweep and zones to review; they do not classify confirmed fire.
4. Export display PNGs in **EPSG:3857**. The API reads numerical analysis rasters, never PNG colours or Web Mercator screen pixels; selections and reference geometry use WGS84/EPSG:4326.

The documented `f66c4d9` artifact generation reports **100% valid coverage**, a median index of **0.50 inside versus -0.22 outside** the reference perimeter, and a P1 highlighted area of **1,049.66 ha** with perimeter IoU **0.086**. These describe one image pair and its chosen analysis domain, not burned area, classification accuracy or generalization. See [results, discrepancies and limitations](docs/LIMITATIONS.md) for source hashes, denominators and confounds, and [methods](docs/methods/) for the calculation and conventions.

## Run it locally

Requirements: **Python 3.11**, [uv](https://docs.astral.sh/uv/) and **Node 24**. Real-data setup additionally uses the GitHub CLI, `sha256sum` and `unzip` (commands below use a POSIX shell).

From the repository root, install the locked dependencies:

```sh
uv sync --locked
npm ci --prefix web
```

### Quick demo: visible MOCK mode

Create or update the ignored `web/.env.local`:

```dotenv
VITE_USE_MOCKS=true
VITE_DATA_BASE_URL=/
VITE_API_BASE_URL=
```

```sh
npm --prefix web run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

Open `http://127.0.0.1:5173`. This mode uses contract fixtures and a mock API, so no data download or backend is required. Keep the MOCK notice visible.

### Real observations and numerical inspection

Use the matching web and interim artifact releases recorded in the [integration runbook](docs/DEMO.md). Raw scenes are not distributed in Git. From the repository root:

```sh
gh release download data-web-plaskett-f66c4d9 -D data/processed
gh release download data-interim-plaskett-f66c4d9 -D data
(cd data/processed && sha256sum -c SHA256SUMS.txt && unzip firetrace-web-plaskett.zip)
(cd data && sha256sum -c SHA256SUMS.txt && unzip firetrace-interim-plaskett.zip)
(cd data && sha256sum -c SHA256SUMS-highlight.txt && unzip firetrace-highlight-plaskett-f66c4d9.zip)
uv run contracts/tools/validate.py data/processed/web
```

Use a fresh extraction directory; verify checksums before unpacking. The interim release includes a required highlight supplement alongside the original archive; extract both under `data/`. The resulting layout must include `data/processed/web/` and `data/interim/{sar,change,perimeter,terrain,highlight}/`. The API needs the interim rasters as well as the display bundle; missing or mismatched products must not be replaced with mock evidence.

Change `web/.env.local` to:

```dotenv
VITE_USE_MOCKS=false
VITE_DATA_BASE_URL=/data/
VITE_API_BASE_URL=
```

Start these in **three separate terminals**, each from the repository root:

```sh
# Terminal 1: numerical API; FIRETRACE_DATA_ROOT defaults to ./data
uv run uvicorn api.main:app --host 127.0.0.1 --port 8000
```

```sh
# Terminal 2: static artifact bundle
uv run python -m http.server 8001 --bind 127.0.0.1 --directory data/processed/web
```

```sh
# Terminal 3: browser application
npm --prefix web run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

Restart Vite after changing environment files. Its configured `/data` and `/api` proxies keep browser requests on one origin; `VITE_API_BASE_URL` stays empty. Check `/api/health` through the web origin for `data_status: real`, then inspect a point. Never put secrets in `VITE_*`: those values are public client configuration. See [web configuration](web/README.md) for proxy overrides and [DEMO](docs/DEMO.md) for recorded integration checks and their limits.

The basemap requests OpenStreetMap tiles over the internet and shares the visitor's IP with that provider. Precomputed radar layers remain local. 3D relief is optional: the documented `f66c4d9` web release lacks terrain tiles, so its story uses the 2D fallback. Rebuilding products requires separately obtained raw inputs; stage commands are in [QUALITY](docs/QUALITY.md).

## Stack and checks

- **Offline pipeline:** Python, NumPy, rasterio, xarray, GeoPandas, Shapely and rio-cogeo.
- **API:** FastAPI, Pydantic and rasterio; contract-defined point and transect inspection, with deterministic caveat rules.
- **Web:** React 19, strict TypeScript, Vite, MapLibre GL JS, Tailwind CSS, Motion, TanStack Query, Zustand and Recharts.
- **Interfaces:** JSON Schema 2020-12 and OpenAPI [v1.2.0 contracts](contracts/README.md); synthetic fixtures share the real bundle's shape.

```sh
uv run python scripts/check.py
uv run contracts/tools/validate.py
git diff --check
```

The repository gate runs Python/web lint, tests and the web build. Fixture/schema checks establish interface consistency, not scientific validation. [QUALITY](docs/QUALITY.md) details the checks; [DEMO](docs/DEMO.md) records bounded real-data integration evidence. Neither substitutes for independent validation or a timed end-to-end rehearsal.

## Documentation and licence

Start with [limitations](docs/LIMITATIONS.md), [methods](docs/methods/) and the [demo runbook](docs/DEMO.md). For development, see [architecture](docs/ARCHITECTURE.md), [contract semantics](docs/CONTRACTS.md), [contributing](CONTRIBUTING.md) and the [team agreement](docs/TEAM.md).

AI coding tools assisted development; the product runs no language model, produces no LLM-generated evidence, and uses no trained deep-learning model. The disclosure is in [AI_USE](docs/AI_USE.md) and [NOTICE](NOTICE).

Code and documentation are licensed under [Apache 2.0](LICENSE). Third-party data and software retain their own licences and required attribution: see [REFERENCES](docs/REFERENCES.md). Do not commit secrets, raw inputs, private infrastructure settings or memory exports.
