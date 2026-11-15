# Zones to review (XP-04, P1)

Producer: `pipeline/review_zones.py`, configured by `pipeline/configs/review_zones_plaskett.toml`. Inputs: the XP-01 `highlight_meta.json` and `highlight_mask.tif`, the CH-01 index and HH/HV change, the DT-02 dB layers and common valid mask, the DT-03 perimeter (mask, 50 m edge band and `perimeter.geojson`) and the DT-05 `slope.tif` and `layover_shadow.tif`. Outputs in `data/interim/review_zones/`: `review_zones.geojson` (contract [review-zones schema](../../contracts/schemas/review-zones.schema.json)) and `review_zones_meta.json`.

**What it is.** A short, ranked list of connected regions that tells the analyst where to look first (EV-04):

| Kind | Id | Meaning |
| --- | --- | --- |
| `change_outside_perimeter` | `CO-nn` | Highlighted radar change outside the perimeter: a discrepancy to investigate |
| `no_change_inside_perimeter` | `NI-nn` | Little radar change inside the perimeter: a discrepancy to investigate (an unburned island? a radar limitation?) |
| `change_inside_perimeter` | `CI-nn` | Highlighted radar change inside the perimeter: an agreement example |

Kinds describe **observed radar change versus a dated reference perimeter**. They are not burned or unburned ground, and a discrepancy is not an error of the radar or of the perimeter.

## Method (decisions agreed 2026-11-15)

Every parameter was fixed before the real run and is not tuned on the data.

| Step | Rule | Why |
| --- | --- | --- |
| CO / CI pixels | `highlight_mask.tif == 1`, split by the DT-03 pixel-centre perimeter mask | The same threshold (2.0), 3 × 3 valid-only smoothing and 1 ha region filter as XP-01, by construction. The threshold, window and connectivity are read from `highlight_meta.json`. |
| NI pixels | valid, inside the perimeter, and the XP-01 smoothed index `<= 0.0` | The index is a robust z-score, so 0 means "no more change than is typical in the crop". It is fixed a priori and is symmetric with the 2.0 threshold. A data percentile (as in the mock) would adapt the threshold to the result. |
| Regions | 8-connected, as in XP-01; regions under **5 ha** (500 px) are dropped, for every kind | Large enough to see and fly to at demo zoom; one value for all kinds avoids per-kind tuning. |
| List length | at most **10 zones per kind** | Fits the EV-04 panel. `review_zones_meta.json` records how many candidates each kind had. |
| Ranking | area descending; then the index median (descending for CO/CI, ascending for NI); then the first pixel in raster order | "Review first" means the largest zone; ties are broken deterministically. |
| Empty kind | allowed | A kind without a zone of at least 5 ha has no feature; EV-04 shows it as empty. Thresholds are never lowered to fill it. |

The 50 m boundary band is included, as in XP-01 and CH-02. The `near_perimeter_edge` caveat shows how much of each zone lies in it.

## Zone properties

| Property | Rule |
| --- | --- |
| `area_ha` | pixel count × 100 m² / 10,000, rounded to 0.01 ha; never measured on the polygon |
| `geometry` | the exact pixel footprint, vectorised in EPSG:32610 (8-connected), simplified by 5 m (half a pixel, topology preserved, holes kept), reprojected to EPSG:4326 and snapped to 1e-6° (about 0.1 m). Pixels that touch only at a corner become separate parts of a `MultiPolygon`. |
| `centroid` | mean of the pixel centres in EPSG:32610, reprojected to `[lon, lat]` |
| `bbox` | bounds of the EPSG:4326 geometry (`fitBounds`) |
| `valid_fraction` | valid pixels / pixels of the zone with its enclosed holes filled, so invalid holes lower it |
| `hh_db`, `hv_db` | medians over the zone's valid pixels: DT-02 dB before (`t1`) and after (`t2`); `delta_median` is the median of the CH-01 per-pixel change, which need not equal `t2 − t1` of the medians |
| `change_index` | median and p90 (NumPy linear interpolation) of the **unsmoothed** CH-01 index, the value the inspector reports |
| `distance_to_perimeter_m` | EPSG:32610 distance from the unsimplified pixel footprint to the boundary of `perimeter.geojson` (exterior and holes), in whole metres; 0 when the footprint touches or crosses the line |
| `caveats` | share of the zone's pixels where each EV-02 rule fires, always listed (0 means checked and not fired): `steep_slope` slope > 30°, `radar_shadow_layover` code 1 or 2, `near_perimeter_edge` in the DT-03 50 m band. Unknown slope (NaN) or geometry (255) never fires. |

`soil_moisture_change` is AOI-wide (DT-06), so it would be identical for every zone; the inspector already shows it. `vegetation_structure` has no per-pixel rule, and `low_backscatter` and `other_disturbance` have no agreed threshold, so they are not listed. The caveat rules mirror `api/caveats.py` without importing it, so the pipeline does not depend on the API; a test pins the 30° threshold to the [caveats](caveats.md) table.

Medians, the index and fractions are rounded to 0.001 (fractions to 0.0001) for display. The GeoJSON is written compact, with sorted keys, because the web downloads it.

## Inputs and provenance

The stage accepts exactly the inputs XP-01 accepts (same versions, `change.json` → `sar.json` linkage, method id, rasterization rule and grid), and also checks:

- `highlight_meta.json`: version 1, built from these `change.json`, `sar.json` and `perimeter.json` (sha256), same grid, mask sha256, values 0/1/255 with 255 exactly where the DT-02 mask is 0;
- `terrain.json`: version 1, same grid, built from the same `ingest.json` as `sar.json`, `slope.tif` (float32, 0–90° where finite) and `layover_shadow.tif` (codes 0/1/2/255) sha256;
- the dB and change rasters (sha256, grid, finite where valid) and `perimeter.geojson` (sha256).

`review_zones_meta.json` records the five input manifest hashes, the parameters, the rules, per-kind counts (`mask_px`, candidate regions and area, published zones and area, the largest region and its share of the perimeter) and the GeoJSON sha256. Outputs are staged and published atomically through `pipeline/publishing.py`.

DT-04 (`pipeline/export.py`) copies `review_zones.geojson` byte for byte into `data/processed/web/` only when `review_zones_meta.json` exists in `review_zones_dir` and was built from the bundle's `change.json`, `sar.json` and `perimeter.json` and from the very XP-01 and DT-05 manifests merged in the same bundle, and its `method.change_threshold` equals the highlight threshold. It adds the `review_zones` vector layer (group `highlighted_change`, `p1: true`, hidden by default) with the contract legend.

## Plaskett result (real data, 2026-11-15)

Run on the same upstream generation as XP-01 (1,049.66 ha highlighted, IoU 0.086).

| Kind | Pixels in the kind mask | Regions ≥ 5 ha | Published | Published area | Largest |
| --- | --- | --- | --- | --- | --- |
| CO (change outside) | 46 px (0.46 ha) | 0 | 0 | 0 ha | — |
| NI (little change inside) | 2,187.65 ha | 44 (706.25 ha) | 10 | 407.03 ha | 71.87 ha (0.59 % of the perimeter) |
| CI (change inside) | 1,049.20 ha | 56 (675.68 ha) | 10 | 295.44 ha | 62.89 ha |

- **CO is empty**, as expected from XP-01: only 0.46 ha of highlighted change lies outside the perimeter, in patches far below 5 ha.
- **NI is not one dominant region**: the largest is 71.87 ha, 0.59 % of the 12,134.98 ha perimeter, so the a priori 0.0 threshold gives separate patches and no discussion was needed. Their index medians are −0.32 to −0.50, and their HH and HV median changes are within ±0.17 dB. Eight of the ten touch the perimeter line (distance 0), and their edge-band shares reach 27 %: low change is concentrated along the margins of the reference outline.
- **CI zones** have index medians of 3.0–3.5, with HH median changes of −4.9 to −6.1 dB and HV of −6.9 to −7.4 dB. They lie 20 m to 2.9 km inside the line.
- `radar_shadow_layover` is 0 in every zone (layover is 0.09 % of the crop); `steep_slope` ranges from 1 % to 40 %.
- The GeoJSON is 589,356 bytes. Two identical runs give byte-identical `review_zones.geojson`, `review_zones_meta.json` and web bundle, and `contracts/tools/validate.py` accepts the bundle.

A quicklook over the index showed NI zones on dark (low-change) areas near the north-west, north-east and south margins, and CI zones on bright interior patches.

## Limitations

- Zones inherit every XP-01 limitation: one image pair, an exploratory, uncalibrated threshold, and a WFIGS perimeter dated 2026-09-14, before the after scene (2026-10-03), which is an operational outline, not pixel-level ground truth.
- NI zones can be unburned islands, low-severity burns, areas where L-band saw little structural change, or terrain and moisture effects; CI zones can include non-fire change. The list says where to look, not what happened.
- The 0.0, 5 ha and 10-zone choices are documented conventions, not calibrated values. A different minimum area changes how many zones appear, not the underlying measurements.
- Corner-touching pixels are one zone (8-connectivity) but separate polygon parts. Simplification changes only the drawn outline; area and statistics come from pixels.
