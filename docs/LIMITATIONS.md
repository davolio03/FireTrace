# Discrepancies and limitations

This page answers proposal §11, criterion 9: it documents the discrepancies between the radar observation and the reference perimeter, the limitations of the method and data, and the cases where a radar change **cannot be attributed to fire**. The [methods](methods/) give the detail for each product.

FireTrace shows **observed radar change**. It does not detect fire, map burned area or estimate burn severity, and nothing on this page validates either the radar or the perimeter.

## Data generation

Every number below comes from one pipeline generation: main commit `f66c4d9`, `SOURCE_DATE_EPOCH=1794700000`, published as the GitHub releases `data-web-plaskett-f66c4d9` (web bundle) and `data-interim-plaskett-f66c4d9` (analysis rasters). The bundle files cited are:

| File | sha256 |
| --- | --- |
| `case.json` | `faeb6a187d5829e90996257536f6a1734b85b265964d8168c6cc892502861a69` |
| `stats.json` | `c7d0e9067efc22d4f2cefefb874db22711294a94d1ec9bc2c25a5ad4a0de1a62` |
| `review_zones.geojson` | `de4ed6f039d9c7e2a270582672856a069e34809d404cefda5a705518e5e9923f` |

Numbers taken from the methods' real runs, rather than from the bundle, name their source. Those runs used the same upstream inputs.

## What the observation shows

| Quantity | Value | Source |
| --- | --- | --- |
| Valid coverage of the crop | 100 % (3,109,960 px, 31,099.6 ha) | `stats.json` |
| Change index median inside the perimeter | 0.50 (12,134.98 ha) | `stats.json` `inside_perimeter` |
| Change index median outside | −0.22 (18,964.62 ha) | `stats.json` `outside_perimeter` |
| Inside pixels that changed less than the typical crop pixel | about a quarter (inside p25 = −0.29 < 0) | `stats.json` |

The strongest changes concentrate inside the reference perimeter, but the two distributions overlap. More change inside than outside is consistent with the fire footprint. It does not show that any given pixel burned, or that an outside pixel did not.

## Discrepancies with the reference perimeter

The exploratory P1 mask "Highlighted radar changes" (threshold 2.0 on the 3 × 3 smoothed index, 1 ha minimum, fixed before the comparison) gives:

| Quantity | Value | Source |
| --- | --- | --- |
| Highlighted area | 1,049.66 ha | `stats.json` `highlight` |
| Inside / outside the perimeter | 1,049.20 ha / 0.46 ha | `stats.json` `highlight` |
| Perimeter covered by the highlight | 8.6 % | [highlight](methods/highlight.md) |
| IoU with the perimeter | 0.086, equal to the upper bound for areas of these sizes | `stats.json`, [highlight](methods/highlight.md) |

Reading: almost nothing highlighted lies outside the perimeter, but the highlight covers only about 9 % of it. The IoU is limited by the size of the highlight, not by misplaced pixels. The [sensitivity sweep](methods/sensitivity.md) shows the same pattern from threshold 1.0 upward for the combined and HV indices. Lowering the threshold raises the IoU only by highlighting more area, and below about 1.0 the area outside grows fast (511 ha at 0.5). The threshold was not tuned on this table.

The zones to review (`review_zones.geojson`, regions of at least 5 ha, at most 10 per kind) make the discrepancies concrete:

| Kind | Published | Area | What they show |
| --- | --- | --- | --- |
| Change outside the perimeter (CO) | 0 | — | Only 0.46 ha of highlighted change lies outside, in patches far below 5 ha. |
| Little change inside the perimeter (NI) | 10 | 407.03 ha, largest 71.87 ha | Index medians −0.50 to −0.32; median HH and HV change between −0.07 and +0.16 dB. Eight of the ten touch the perimeter line. |
| Change inside the perimeter (CI) | 10 | 295.44 ha, largest 62.89 ha | Index medians 3.01 to 3.54; median change −6.1 to −4.9 dB in HH and −7.4 to −6.9 dB in HV, 20 m to 2.9 km inside the line. |

NI zones are not one dominant block. The largest is 0.59 % of the perimeter, and low change gathers along the margins of the reference outline. Up to 27 % of an NI zone lies in the 50 m edge band. An NI zone can be an unburned island, a low-severity burn, an area where L-band saw little structural change, a terrain or moisture effect, or an imprecision of the reference outline. The data do not tell these apart.

## When a change cannot be attributed to fire

| Cause | Effect on the radar | What FireTrace shows on Plaskett |
| --- | --- | --- |
| Soil and vegetation moisture | Rain before the after scene raises backscatter, especially HH | IMERG Late shows 0.95 mm in total before 2026-10-03 and no day above 1 mm (`weather.json`), so the AOI was essentially dry. The caveat is always listed, but it is AOI-wide and not a per-pixel measurement. |
| Steep terrain | Slopes distort backscatter; patterns can follow slopes and drainages | 14.4 % of crop pixels have a slope above 30° ([terrain](methods/terrain.md)); review zones have 1 % to 40 % steep pixels. Slopes come from ~30 m DEM data and are smoothed. |
| Layover and shadow | Geometry folds or hides the signal | 0.09 % of pixels are layover and none is shadow. These are local, approximate flags that miss shadow cast by distant ridges. |
| Open water | Wind changes sea-surface roughness between passes | About 13 % of the crop is sea and is included in the "outside" statistics; there is no water mask. |
| Vegetation structure and phenology | Seasonal change, harvest or other disturbance also change HV | No per-pixel rule; the inspector always shows the generic caution. |
| Speckle | Single-pixel differences are noisy | No speckle filter, so each pixel is exactly what NISAR measured; isolated high pixels deserve less trust than coherent patches. |
| Reference timing and quality | The perimeter predates the after scene | WFIGS 58728 is dated 2026-09-14 20:44 UTC, 19 days before the after scene. It is an operational IR perimeter, not a final outline or pixel-level ground truth. Its 51 ha hole comes from topology repair and its meaning on the ground is unresolved. |

The Evidence Inspector reports these as deterministic caveats computed from existing products ([caveats](methods/caveats.md)). A caveat that fires does not make the change false, and the absence of caveats does not confirm fire.

## Limitations

- **One case, one image pair.** One descending pair (track 42, frame 70) from 2026-08-16 and 2026-10-03. Nothing here establishes a general threshold or transfers to other fires, vegetation types or seasons.
- **Provisional data.** NISAR GCOV provisional products. The terrain geometry uses the after scene's radar-geometry cubes for both dates, an assumption that has not been verified against a before-scene `.h5`.
- **Relative index.** The change index is a robust z-score relative to this crop and this pair. Values are not comparable across cases without recomputing the reference.
- **Uncalibrated choices.** The 2.0 threshold, the 3 × 3 smoothing, the 1 ha and 5 ha minimum areas, the 30° slope and the 7-day rain window are documented conventions, not calibrated values.
- **No independent validation.** The only reference is the dated WFIGS perimeter. IoU measures agreement with it, not accuracy. No RAVG severity product or field data were used. No confidence percentage is shown, because none is calibrated.
- **External results are not ours.** The AUC-ROC of 0.984 reported by Döweler, Leuzinger and Bader for Plaskett and Timber is their own evaluation of their own method. FireTrace uses a simplified single-pair version of the absolute HH/HV log-ratio idea and does not reproduce that result.
- **Complementary sources are context.** Sentinel-2 optical images (2026-08-30 with smoke, 2026-10-15 clear) are on dates different from the NISAR scenes and only show what optical sensors see. No burn index (NBR/dNBR) is computed. IMERG Late is a satellite-only estimate on ~10 km cells.
- **No deep learning.** No model was trained or used. The Siamese U-Net experiment (XP-03) was proposed but not carried out.
- **Display is not measurement.** Map PNGs are reprojected to EPSG:3857 for display. Every number comes from the 10 m EPSG:32610 rasters, never from colours or screen pixels.
