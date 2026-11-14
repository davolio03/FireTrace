# Reference perimeter (DT-03)

Producer: `pipeline/perimeter.py`, configured by `pipeline/configs/perimeter_plaskett.toml`. The WFIGS perimeter is the **official, dated reference** used to contrast the radar observation. It is not ground truth, not a final perimeter and not a pixel-level label.

## What is pinned

| Field | Value |
| --- | --- |
| Source | NIFC WFIGS Interagency Perimeters YearToDate |
| Feature | OBJECTID 58728 (Plaskett, Wildfire Daily Fire Perimeter, IR Image Interpretation) |
| PolygonDateTime | 2026-09-14 20:44 UTC, **before** the 2026-10-03 after scene |
| Raw file | `data/raw/wfigs_58728_raw.geojson` (gitignored), sha256 pinned in the config |

The pipeline never downloads. A missing or changed raw file, another OBJECTID or another PolygonDateTime stops the run. Refreshing the reference is a deliberate, reviewed change of the pin.

## Geometry repair

The raw MultiPolygon is invalid (`Nested shells`): a 51 ha polygon lies inside the main 12,185 ha polygon. `shapely.make_valid` turns the nested shell into a hole (an unburned island). This is the reading consistent with WFIGS: the repaired area is 12,134.3 ha against the declared GISAcres of 12,137.7 ha (0.03 %), whereas merging the shells would give 12,185.6 ha. `perimeter.json` records `repaired: true` and the original validity message.

## Rasterization (decision C)

`perimeter_mask.tif` is a uint8 COG on the DT-01 crop grid (10 m, EPSG:32610). A pixel is **inside** (1) when its **centre** lies inside the polygon (`all_touched=False`); otherwise it is 0. Holes are outside. This standard rule neither inflates nor shrinks the area systematically. On Plaskett it gives 1,213,498 pixels = 12,134.98 ha, matching the vector area within 0.01 %.

`perimeter_edge.tif` marks pixels whose centre lies within **50 m** of the boundary (including hole boundaries), on both sides. It supports the `near_perimeter_edge` caveat: near the line, the reference itself is imprecise.

## Outputs

`data/interim/perimeter/`:

- `perimeter.geojson`: EPSG:4326, full geometry (no simplification; the original coordinates when valid, the repaired geometry otherwise), properties `OBJECTID`, `IncidentName`, `FeatureCategory`, `MapMethod`, `GISAcres`, `PolygonDateTime`, `Source`. DT-04 copies it to `data/processed/web/`.
- `perimeter_mask.tif`, `perimeter_edge.tif`: uint8 COGs, no nodata.
- `perimeter.json`: `reference` (exactly the `case.json` reference fields, for DT-04), raw checksum, geometry summary, areas (vector, raster, WFIGS), rasterization rule, grid, pixel counts and output checksums.

Command: `uv run python -m pipeline.perimeter --config pipeline/configs/perimeter_plaskett.toml` (needs the DT-01 `ingest.json` for the crop grid).

## Limitations

- The perimeter predates the after scene by 19 days; the fire could still change.
- Daily IR perimeters can include unburned patches and miss spot fires.
- Inside/outside statistics (CH-02) inherit the rasterization rule and the reference date.
