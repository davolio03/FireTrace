# Highlighted radar changes (XP-01, P1)

Producer: `pipeline/highlight.py`, configured by `pipeline/configs/highlight_plaskett.toml`. Inputs: the CH-01 `change_index.tif` (method `abs-logratio-hhhv-v1`), the DT-02 common valid mask and the DT-03 perimeter mask and 50 m edge band, checked with the same manifest, version, linkage and grid rules as CH-02. Outputs in `data/interim/highlight/`: `highlight_mask.tif`, `highlight.json`, `highlight_meta.json`.

**What it is.** An optional, exploratory view (F05) of where the observed L-band change is large: the continuous change index is smoothed, cut at a documented threshold and cleaned of tiny patches. It is shown as **"Highlighted radar changes"**. It is **not** burned area, burn severity or a fire detection, and it is not validated. The continuous index (P0) stays the primary product; this mask is P1 and off unless the stage is run.

## Method (decisions agreed 2026-11-15)

| Step | Rule | Why |
| --- | --- | --- |
| Smoothing (B2) | 3 × 3 mean of the index over **valid pixels only** (in-bounds neighbours; float64). An invalid pixel stays invalid and never contributes to a neighbour. | Reduces radar speckle so isolated noisy pixels do not dominate; the inspector still reports the unsmoothed pixel value. |
| Threshold (A1) | `smoothed >= 2.0` (robust z-score: about 2 standard deviations above the typical change in the crop). | Fixed **a priori**, never tuned on the IoU: choosing it to match the perimeter would make the agreement circular. The threshold sweep and HH vs HV are XP-02. |
| Regions (B2) | 8-connected regions smaller than 100 px (1 ha) are removed. | A minimum mapping unit: single pixels and slivers are not meaningful patches. |
| Agreement domain (C1) | Valid pixels only. Unavailable pixels are 255 in the mask and never count as measured negatives. The DT-03 50 m boundary band and open water are included, as in CH-02. | Consistent with the CH-02 statistics; a variant without the band is recorded as a sensitivity check. |

`highlight.json` is exactly the `stats.highlight` block of the contract:

```text
area_ha          = highlighted valid pixels × 100 m² / 10,000
inside_ha        = highlighted valid pixels inside the perimeter (pixel-centre mask)
outside_ha       = highlighted valid pixels outside it            (area = inside + outside)
iou_vs_perimeter = |H ∩ P| / |H ∪ P|   over valid pixels, H = highlighted, P = perimeter mask
```

`highlight_mask.tif` is a uint8 COG on the 10 m EPSG:32610 crop grid: 1 highlighted, 0 not highlighted, 255 invalid (no data). EV-01 can read it for the inspector's `highlighted` field. `highlight_meta.json` records the input manifest hashes, the parameters, the region count and sizes, the pixels removed by the region filter, the pixel counts behind the IoU and the no-edge-band variant.

DT-04 (`pipeline/export.py`) merges the result only when `highlight_meta.json` exists in `highlight_dir`, and only if it was built from the same `change.json`, `sar.json` and `perimeter.json` as the bundle. It then fills `stats.json` `highlight` (every other field unchanged) and adds the `highlight_mask` layer (group `highlighted_change`, `p1: true`, hidden by default, nearest-neighbour warp, orange where highlighted and transparent elsewhere). Without the stage, the bundle is unchanged and `stats.json` stays byte-identical to the CH-02 file, with `highlight: null`.

## Plaskett result (real data, 2026-11-15)

| Quantity | Value |
| --- | --- |
| Highlighted | 1,049.66 ha in 238 regions (largest 62.9 ha) |
| Inside / outside the perimeter | 1,049.20 ha / 0.46 ha |
| Perimeter (valid, pixel-centre) | 12,134.98 ha |
| IoU vs perimeter | 0.086 |
| Before the 1 ha region filter | 1,538 ha (5,184 small regions removed, 488 ha) |

Almost everything highlighted lies inside the perimeter, but it covers only about 9 % of it, so the IoU is low. This matches CH-02 (median index 0.50 inside versus −0.22 outside): the strong change is concentrated in patches, many aligned with slopes and drainages, rather than spread over the whole perimeter. The low IoU is a description of the data, not a defect to tune away. Two identical runs produce byte-identical outputs.

## Limitations

- The reference is the WFIGS perimeter dated 2026-09-14, **before** the after scene (2026-10-03), and it is an operational outline, not pixel-level ground truth. IoU measures agreement with it, not accuracy.
- One case and one image pair: nothing here establishes a general threshold.
- Moisture, terrain (slope, layover, shadow), viewing geometry and vegetation can raise or hide the index; see the EV-02 caveats. The patch pattern along slopes is a reason for caution, not a finding.
- The 2.0 threshold and the 3 × 3 / 1 ha cleaning are documented choices, not calibrated ones.
