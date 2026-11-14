# FireTrace architecture — precompute, serve, inspect

**Existing:** executable contracts, mock assets, board tooling, a Python 3.11/uv scaffold with NISAR ingest, and an initial web scaffold. **Planned, not implemented:** the remaining pipeline processing, API endpoints, the web data journey and real processed web artifacts. The [proposal](propuesta.md) governs scientific scope; its illustrative stack is superseded by the upstream choices below.

## Fixed stack and boundaries

| Component | Agreed technology | Handoff |
| --- | --- | --- |
| `pipeline/` | Python 3.11 + uv; rasterio, numpy, xarray, geopandas, shapely, scikit-image, rio-cogeo | Offline numerical COGs, web products, metrics and provenance |
| `api/` | FastAPI + rasterio + pydantic | Contract-defined point inspection over numerical products |
| `web/` | React 19 + strict TypeScript + Vite + MapLibre GL JS | Independent layers, comparison, metrics and Evidence Inspector |
| Web supporting choices | Tailwind CSS + shadcn/ui, TanStack Query, Zustand, Recharts | Styling, server/UI state and charts |
| Optional | deck.gl if needed; PyTorch for P1 | Not a P0 dependency |
| Quality | ruff + pytest; eslint + prettier + vitest | Real tests/lint/build once source exists |

The root `pyproject.toml` is a single uv project shared by `pipeline/` and `api/`; it declares their fixed-stack runtime dependencies and a `dev` group. The web scaffold has a dependency manifest and initial map; it does not yet consume scientific data. Stack changes require an ADR and human Kanvas approval. [TEAM](TEAM.md) records human responsibility; directory names are boundaries, not proof of working modules.

## Data flow and current implementation boundary

```text
Local NISAR HH/HV t1/t2 powers + dated reference perimeter
  -> planned offline pipeline: validity, dB, continuous HH/HV change
  -> planned numerical COGs + data/processed/web/ contract outputs
       -> planned static web consumption of metadata, stats and display PNGs
       -> planned FastAPI point lookup from numerical products

contracts/fixtures/ -> existing synthetic contract examples for parallel work
```

The real web directory mirrors `contracts/fixtures/web/`: `case.json`, `stats.json`, `layers.json`, `perimeter.geojson` and `layers/<id>.png`. It is not a tile-server architecture. Display PNGs use four geographic corners and contract-supplied legends; inspection never reconstructs values from colors.

Planned web configuration is `VITE_DATA_BASE_URL`, `VITE_API_BASE_URL` and `VITE_USE_MOCKS`. Mock mode uses MSW fixtures for `/api/*` and must show MOCK visibly. No web mock harness exists yet. Generated TypeScript types must come from [OpenAPI](../contracts/openapi.yaml), not manually maintained parallel interfaces.

## Geographic and numerical invariants

1. Check all four source rasters' CRS, origin, transform, resolution and dimensions. Preserve their **10 m EPSG:32610** common analysis grid. Fail explicitly on mismatch rather than silently resampling inputs.
2. Mask source no-data and non-finite/nonpositive powers before `10 * log10(x)`. Combined changes and metrics use the common valid set. Signed dB change is **t2 − t1**, as specified by the inspection schema.
3. Transform the WGS84 perimeter explicitly into analysis coordinates for raster/vector comparisons. Define AOI, rasterization and metric domains before publishing measurements; the input CRS alone does not define them.
4. Reproject/resample display PNGs to **EPSG:3857**, with alpha transparency for invalid pixels. The input no-resampling claim does not apply to web display. Choose/document resampling and verify that mask edges do not invent valid coverage.
5. Layer corners, bounding boxes, perimeter geometry and `lon`/`lat` queries are **EPSG:4326**. Resolve queries back to actual analysis-grid pixels and return their center/row/column. Never calculate scientific area from Web Mercator PNGs or longitude/latitude degrees.
6. Tie numerical values, styles, statistics and provenance to the same processing result. A successful schema check does not prove this identity or geographic correctness.

The proposed real continuous baseline combines absolute HH/HV log-ratio magnitudes. The mock fixture's median/MAD description is not a validated pipeline method: normalization domain/scaling, zero-MAD behavior and parameters still require scientific agreement. Physical confounds and the dated reference must remain visible.

## Service boundary

[Executable contracts](../contracts/README.md) define `/api/health`, `/api/case`, `/api/stats`, `/api/layers` and `/api/inspect/point`. A point outside the AOI returns 200 with `valid=false`, `pixel=null` and null values; invalid query parameters use 422. No region endpoint or authentication/deployment design is implemented.

COG names in current board proposals are implementation intentions, not a complete internal storage manifest. Record the numerical artifact layout, input integrity identifiers, crop/configuration and code/dependency versions during pipeline implementation. Extend shared metadata only through the contract process.

### Numerical artifact layout (implemented)

Internal, gitignored pipeline products on the 10 m EPSG:32610 crop grid. They are not web contracts; consumers (for example the EV-01 point-inspection API) should read them through their manifests and checksums.

| Stage | Path | Content |
| --- | --- | --- |
| DT-01 ingest | `data/interim/nisar/{t1,t2}_{hh,hv}.tif` | float32 GCOV linear power crops, source nodata (NaN) preserved, no resampling |
| DT-01 ingest | `data/interim/nisar/ingest.json` | epochs, acquisition, AOI (32610 and 4326), source/crop grid, input/output sha256 |
| DT-02 dB | `data/interim/sar/{t1,t2}_{hh,hv}_db.tif` | COG, float32 dB = `10*log10(x)` for finite x > 0 and not nodata; NaN nodata |
| DT-02 dB | `data/interim/sar/valid_mask.tif` | COG, uint8 (no nodata): 1 = valid in all four layers, 0 = invalid in at least one |
| DT-02 dB | `data/interim/sar/sar.json` | formula, mask rule, per-layer counts (valid / nodata / non_positive), valid pixels and coverage %, sha256 of ingest.json, sources and outputs |
| CH-01 change | `data/interim/change/change_{hh,hv}_db.tif` | COG, float32 signed dB difference (after − before), NaN where `valid_mask` = 0 |
| CH-01 change | `data/interim/change/change_index.tif` | COG, float32 continuous robust z-score of `abs(ΔHH) + abs(ΔHV)`; no threshold or clipping ([method](methods/change-index.md)) |
| CH-01 change | `data/interim/change/change.json` | `method` (copied to `case.json` by DT-04), median, MAD, percentiles, valid count, sha256 of `sar.json` and outputs |

COGs use 256 px deflate blocks and nearest-neighbour overviews for display only; scientific lookups read the full-resolution level. DT-02 and CH-01 build the whole set in a sibling staging directory and swaps it into place only when complete, so a failed run keeps the previous complete set; it refuses an output directory holding files it does not own.

## Reproducibility, diagnostics and deployment

- Precompute before the demo: no Earthdata login, catalogue dependence, gigabyte downloads or training on the presentation path.
- Use small synthetic rasters for numerical tests; verify real selected pixels separately. Test invalid values, all-invalid domains, grid mismatch, boundary queries and display/numeric consistency with agreed tolerances.
- Surface missing/incompatible artifacts and no-data; retain diagnostics sufficient to reproduce a mismatch without exposing private paths or credentials.
- Hosting, cost, CORS/security configuration, release/artifact identity and local fallback remain human decisions. No app or Cloud server deployment is claimed. [DEMO](DEMO.md) records rehearsal evidence when available.

See [CONTRACTS](CONTRACTS.md) for unresolved scientific semantics and [QUALITY](QUALITY.md) for runnable checks versus future stack commands.
