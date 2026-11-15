# Web bundle export (DT-04)

Producer: `pipeline/export.py`, configured by `pipeline/configs/case_plaskett.toml`; display PNGs use the shared `pipeline/webexport.py`. Output: `data/processed/web/`, the same layout as `contracts/fixtures/web/` ([contract](../../contracts/README.md)), so the web moves from mocks to real data by changing `VITE_DATA_BASE_URL` only. Done means `uv run contracts/tools/validate.py data/processed/web` passes.

The PNGs are **for viewing only**. Every number the product shows (inspector, metrics) comes from the analysis COGs on the 10 m EPSG:32610 grid or from `stats.json`, never from colours or Web Mercator pixels.

## Inputs and integrity

| Input | Stage | Check |
| --- | --- | --- |
| `ingest.json` | DT-01 | format version, analysis CRS, crop grid; AOI, epochs, acquisition and product for `case.json` |
| `sar.json`, `{t1,t2}_{hh,hv}_db.tif`, `valid_mask.tif` | DT-02 | built from this `ingest.json` (sha256); same grid; every COG sha256, CRS, north-up 10 m grid and dtype |
| `change.json`, `change_{hh,hv}_db.tif`, `change_index.tif` | CH-01 | built from this `sar.json`; same grid; COG checks; `method` for `case.json` |
| `perimeter.json`, `perimeter.geojson` | DT-03 | same grid; same raw WFIGS file (sha256, OBJECTID) that DT-01 used for the AOI; GeoJSON sha256 |
| `stats_meta.json`, `stats.json` | CH-02 | built from exactly these `change.json`, `sar.json` and `perimeter.json`; `stats.json` sha256; `data_status: real` |
| `terrain.json`, `terrain_layers.json`, `{hillshade,slope}.png` | DT-05, optional | only when `terrain_dir` exists; built from this `ingest.json`; same grid; sha256 of each file; `data_status: real`; corners and size identical to the radar layers |
| `weather_meta.json`, `weather.json` | DT-06, optional | only when `weather_dir` exists; built from this `ingest.json`; sha256; `data_status: real` |
| `highlight_meta.json`, `highlight.json`, `highlight_mask.tif` | XP-01, optional (P1) | only when `highlight_dir` has `highlight_meta.json`; built from exactly these `change.json`, `sar.json` and `perimeter.json`; same grid; sha256 of each file; contract `highlight` block (keys, finite non-negative numbers, IoU in [0, 1], inside + outside = area); mask values 0/1/255 with 255 exactly where the DT-02 mask is 0; `stats.json` must still have `highlight: null` |
| `review_zones_meta.json`, `review_zones.geojson` | XP-04, optional (P1) | only when `review_zones_dir` has `review_zones_meta.json`; requires the XP-01 highlight and DT-05 terrain in the same bundle; built from exactly these `change.json`, `sar.json`, `perimeter.json`, `highlight_meta.json` and `terrain.json`; same grid; GeoJSON sha256; a `FeatureCollection` with `contract_version` 1.2.0, `data_status: real` and `method.change_threshold` equal to the highlight threshold |
| `tiles.json`, `{z}/{x}/{y}.png` | AP-07 relief tiles, optional (DT-09) | only when `terrain_tiles_dir` has `tiles.json`; the directory holds exactly `tiles.json` and the tiles it lists (plain files at `<z>/<x>/<y>.png`, canonical decimal names, no links), all read once in a walk that re-checks every directory and file identity, so only those bytes are verified and published; the manifest satisfies `terrain-tiles.schema.json` (checked by the exporter itself) and: `encoding: terrarium`, `tiles: ["{z}/{x}/{y}.png"]`, `tileSize` 256 or 512, integer zooms 0-15 with min <= max, finite bounds that contain the `ingest.json` AOI, non-empty attribution; `firetrace.tiles_format_version` 1, `case_id` equal to the config, `data_status: real`, `tile_count` equal to the outputs; the listed tiles are exactly those the bounds give at each zoom (at most 2000); each tile's sha256 is checked and it must be a complete, decodable, non-interlaced 8-bit RGB(A) PNG of `tileSize` pixels (chunk CRCs, only known critical chunks in spec order, compression/filter methods 0, IDAT inflating to exactly the scanlines, every scanline filter type 0-4); when DT-05 terrain is merged too, its `dem.sha256` must be one of `firetrace.dem` |
| `case_plaskett.toml` | config | `name`, `location`, `fire_start` and `sources`, which no stage produces (from [PRODUCT](../PRODUCT.md) and the CAL FIRE incident page) |

Each raster is decoded from the same in-memory bytes whose sha256 was verified, so a file replaced after hashing cannot slip in. Each radar layer must be finite wherever the DT-02 common mask is 1.

Any failure before publication stops the run with exit code 2 and changes nothing: the bundle is built in the sibling `.web.staging` directory and swapped in only when complete. The previous bundle is moved to `.web.previous` and restored if the swap fails. The swap is the commit point: if only the removal of `.web.previous` fails afterwards, the new bundle stays published, the backup is kept and the CLI prints an `export warning`. Nothing is deleted recursively: owned files are unlinked one by one, emptied directories removed with `rmdir`, and a directory that changes identity mid-removal stops it; a missing bundle with a complete `.web.previous` is restored first. The threat model (single publisher, no concurrent editing) is in [ARCHITECTURE](../ARCHITECTURE.md). The stage refuses to run when the output directory or either sibling holds anything it does not own (unknown names, directories or symlinks/junctions under owned names; under `terrain/` only `tiles.json` and `<z>/<x>/<y>.png` at that depth are owned, by name pattern, so a previous pyramid with another tile set is still removed file by file), or when any input directory is, or lies inside, one of these three paths. These rules are the shared `pipeline/publishing.py` helpers used by every stage.

## Display rules

| Topic | Rule | Why |
| --- | --- | --- |
| Projection | EPSG:3857 grid from `webexport.warp_to_web`: GDAL's suggested resolution, extent rounded outwards to cover the whole crop footprint | MapLibre `image` sources are drawn in Web Mercator |
| Corners | `[top-left, top-right, bottom-right, bottom-left]` `[lon, lat]` of that grid, 8 decimals; identical for every raster layer (the run fails otherwise) | A north-up Web Mercator rectangle is an exact lon/lat rectangle |
| Resampling | **Nearest neighbour** on the float values, then colour. Never resample colours | Each display pixel shows one real analysis pixel; no averaged values and no smeared mask edges (terrain context keeps DT-05's bilinear) |
| Transparency | Alpha 0 where the DT-02 common valid mask is 0 or outside the crop, in **every** radar layer | Combined results use the common valid set; the map matches the inspector's `valid=false` |
| Quality layer | `valid_mask.png` is grey `#7f7f7f` where invalid and transparent elsewhere | Shows where there is no measurement |

### Colour stretches

Percentiles use NumPy linear interpolation over the stored float32 values of common-valid pixels. Values outside a domain take the end colour (stated in each legend note). Legends publish the actual domains and stops; `export.json` repeats them.

| Layer | Palette | Domain |
| --- | --- | --- |
| `sar_t1_hh`, `sar_t2_hh` | black → white | p2–p98 of **both dates together**, rounded outward to whole dB; one domain for before and after |
| `sar_t1_hv`, `sar_t2_hv` | black → white | the same rule for HV |
| `change_hh`, `change_hv` | diverging RdBu (`#2166ac` … `#b2182b`), 0 = `#f7f7f7` | symmetric ±D, D = p98 of \|ΔdB\| over HH and HV together, rounded up to a whole dB (at least 1); one domain for both polarisations |
| `change_index` | viridis, 5 stops | p2–p98 of the index, rounded outward to 0.01 |

A per-date or per-polarisation stretch would show differences that are only stretch differences, so the stretches are shared wherever layers are compared. Blue means backscatter decreased and red that it increased. This is **observed radar change**, not burned area or severity.

## `case.json`

| Field | Source |
| --- | --- |
| `case_id` | config, equal to the `case_id` of `ingest.json`, `sar.json` and `change.json` |
| `name`, `location`, `fire_start`, `sources` | config |
| `aoi_bbox` | `ingest.json` `aoi.aoi_bbox_4326` (reference perimeter bbox + 2 km in EPSG:32610, as EPSG:4326) |
| `epochs`, `acquisition` | `ingest.json` |
| `product` | `ingest.json` as ingested (`NISAR_L2_PR_GCOV`). The fixture and PRODUCT use `NISAR_L2_GCOV_PROVISIONAL_V1`; the difference is reported to the team, not resolved here |
| `reference` | `perimeter.json` (DT-03) |
| `method` | `change.json` (CH-01) |
| `generated_at` | UTC time of the run, or `SOURCE_DATE_EPOCH` when set (reproducible builds) |
| `pipeline_version` | `<name> <version>` from `pyproject.toml` |

## Outputs

`data/processed/web/` (gitignored):

- `case.json`, `layers.json` (contract);
- `stats.json`, `perimeter.geojson` and, when present, `weather.json`, byte-for-byte copies;
- `layers/{sar_t1_hh,sar_t2_hh,sar_t1_hv,sar_t2_hv,change_hh,change_hv,change_index,valid_mask}.png` and, when present, `layers/{hillshade,slope}.png`;
- when present, `terrain/tiles.json` and `terrain/{z}/{x}/{y}.png`: byte-for-byte copies of the AP-07 relief tiles for the 3D story (display context, never measured; `validate.py` re-checks every tile);
- `export.json`: not a contract file (the validator and the web ignore it). It holds the sha256 of every input manifest and output file, which optional inputs were merged, the web grid, the resampling and the stretch rules and domains.

With the same inputs and the same `SOURCE_DATE_EPOCH`, two runs are byte-identical.

Command: `uv run python -m pipeline.export --config pipeline/configs/case_plaskett.toml`.

When the XP-01 result is merged, `stats.json` is re-serialized with only `highlight` filled, and `layers/highlight_mask.png` is warped with nearest neighbour from the mask (orange where highlighted, transparent elsewhere) as a hidden-by-default `p1` layer ([highlight](highlight.md)).

When the XP-04 result is merged, `review_zones.geojson` is copied byte for byte and the hidden-by-default `p1` vector layer `review_zones` (group `highlighted_change`) is listed after the perimeter with the contract legend ([review zones](review-zones.md)).

Out of scope: computing statistics, terrain, weather, the highlight mask or the review zones.
