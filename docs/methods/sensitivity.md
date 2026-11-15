# Highlight sensitivity: threshold, smoothing and polarization (XP-02, P1)

Producer: `pipeline/sensitivity.py`, configured by `pipeline/configs/sensitivity_plaskett.toml`. Inputs: the CH-01 `change_index.tif`, `change_hh_db.tif` and `change_hv_db.tif`, the DT-02 common valid mask and the DT-03 perimeter mask and 50 m edge band, checked exactly as in [XP-01](highlight.md). Outputs in `data/interim/sensitivity/`: `sensitivity.json` (inputs, normalization, parameters, every point) and `sensitivity.csv` (one row per point; the figure below is drawn from it).

**What it is.** XP-01 reports one operating point of the exploratory "Highlighted radar changes" mask. XP-02 repeats the same rules over a grid of settings to show whether that picture is robust. It **describes** sensitivity: it never chooses a "best" threshold and never changes the XP-01 operating point (combined index, 3 × 3, threshold 2.0, fixed a priori). IoU is agreement with the WFIGS perimeter dated 2026-09-14, not accuracy, and highlighted change is not burned area.

## Grid (decisions agreed 2026-11-15)

| Decision | Choice |
| --- | --- |
| A. Indices | `combined` = the CH-01 index. `hh`, `hv` = robust z-score of `|change|` per polarization: `(|Δ| − median) / (1.4826 × MAD)` over all valid crop pixels, the CH-01 rule applied to one polarization, so the three share a scale. Signed (decrease-only) variants are out of scope. |
| B. Thresholds | 0.50 to 5.00 in steps of 0.25 (19 values), always including 2.0 |
| C. Smoothing | Valid-only window mean of 1 (none), 3 and 5, each followed by the 1 ha (100 px, 8-connected) region filter |
| D. Baselines | Per point, `iou_upper_bound = min(H, P) / max(H, P)` (perfect overlap for these two areas) and `iou_chance = I / (H + P − I)` with `I = H × P / N` (a ratio-of-expectations baseline for a same-area mask placed uniformly at random over the N valid pixels; a reference value, neither a lower bound nor the exact expected IoU) |
| E. Outputs | JSON and CSV only; no plotting dependency. The curves are drawn from the CSV by a standard-library script (DL-02, below). |

That gives 3 indices × 3 windows × 19 thresholds = 171 points. Each point reports area, inside/outside area, IoU, the two baselines, the share of the highlight inside the perimeter, the share of the perimeter covered, the region count and the IoU without the edge band. Every point uses `pipeline.highlight` functions, and the XP-01 point is checked to reproduce `highlight.json` exactly.

## Plaskett result (real data, 2026-11-15)

Per-polarization normalization: HH median |Δ| 1.80 dB, MAD 1.12 dB; HV median 1.87 dB, MAD 1.17 dB.

Window 3 (the XP-01 smoothing):

| Index | Threshold | Highlighted (ha) | Outside (ha) | Inside share | Perimeter covered | IoU | Chance | Bound |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| combined | 0.5 | 6,213 | 511.1 | 91.8 % | 47.0 % | 0.451 | 0.152 | 0.512 |
| combined | 1.0 | 3,234 | 13.7 | 99.6 % | 26.5 % | 0.265 | 0.089 | 0.266 |
| combined | **2.0** (XP-01) | **1,050** | **0.5** | **100.0 %** | **8.6 %** | **0.086** | **0.032** | **0.086** |
| combined | 3.0 | 232 | 0.0 | 100.0 % | 1.9 % | 0.019 | 0.007 | 0.019 |
| hh | 1.0 | 2,078 | 96.8 | 95.3 % | 16.3 % | 0.162 | 0.060 | 0.171 |
| hh | 2.0 | 293 | 0.0 | 100.0 % | 2.4 % | 0.024 | 0.009 | 0.024 |
| hv | 1.0 | 3,123 | 6.4 | 99.8 % | 25.7 % | 0.257 | 0.087 | 0.257 |
| hv | 2.0 | 990 | 0.4 | 100.0 % | 8.2 % | 0.082 | 0.030 | 0.082 |

How to read it:

- **IoU is limited by the size of the highlight, not by misplaced pixels.** From threshold 1.0 upward the IoU of the combined and HV indices is within 0.004 of its upper bound (HH within 0.017), and across the grid the IoU is 2.2 to 3.2 times the chance baseline. Lowering the threshold raises the IoU only by highlighting more area, and below about 1.0 the area outside the perimeter grows quickly (511 ha at 0.5). The largest IoU in the grid (0.49, combined, window 5, threshold 0.5) comes with 503 ha outside the perimeter. That is why the XP-01 threshold was fixed a priori and not chosen from this table.
- **The HV-only mask resembles the combined one; the HH-only mask does not.** Each polarization is normalized on its own, so these are separate masks, not a decomposition of the combined index. At the same threshold, the HV-only mask has an area and agreement close to the combined mask, with the same near-perfect inside share. The HH-only mask is much smaller at moderate thresholds, and at low thresholds much more of it falls outside (1,337 ha at 0.5). This sweep does not identify a scattering mechanism; a possible explanation to check against the literature is the sensitivity of L-band cross-polarization to vegetation volume. It is an observation for this pair, not a general rule.
- **Smoothing changes little.** Windows 1, 3 and 5 give similar areas and IoU at each threshold. Smoothing mainly removes isolated pixels outside the perimeter (32.9 ha with no smoothing versus 13.7 ha at window 3, threshold 1.0).
- **Edge band.** Removing the 50 m band never lowers the IoU and raises it by at most 0.011, so the result does not hinge on the perimeter edge.

Two identical runs produce byte-identical outputs.

## Figure

![IoU with the perimeter and highlighted area outside it against the threshold, window 3, for the combined, HH-only and HV-only indices, with the chance baseline of the combined index](figures/sensitivity.svg)

`figures/sensitivity.svg` shows every window-3 point of the sweep (the table above lists a subset): IoU with the perimeter (with the chance baseline of the combined index, dashed) and the highlighted area outside it. It was drawn by `python scripts/plot_sensitivity.py data/interim/sensitivity/sensitivity.csv docs/methods/figures/sensitivity.svg` (standard library only, deterministic) from the `sensitivity.csv` of the `f66c4d9` generation (sha256 `698bef3cf538ed3be38f29cd74b485a07fbe9b36b94d546a5fed29bdfbead9ba`), whose `sensitivity.json` records the same `change.json`, `sar.json` and `perimeter.json` hashes as the web bundle of the `data-web-plaskett-f66c4d9` release. The CSV itself is not in a release; regenerate it with the XP-02 command. The exact values are in that CSV and, for the listed thresholds, in the table above.

## Limitations

- One case and one image pair; nothing here sets a general threshold.
- The reference perimeter predates the after scene and is an operational outline, not pixel-level ground truth. The chance baseline assumes a uniformly random placement, which ignores the spatial clustering of real change, and is a ratio of expectations: a random placement can score lower (even 0), so it is a reference value for orientation, not a lower bound or a significance test.
- Moisture was not varied: the AOI was essentially dry between the acquisitions (DT-06). Terrain, geometry and vegetation can still raise or hide the index; see the EV-02 caveats.
