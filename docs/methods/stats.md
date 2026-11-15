# Observed change statistics (CH-02)

Producer: `pipeline/stats.py`. Output: `data/interim/stats/stats.json` (the web contract, [stats schema](../../contracts/schemas/stats.schema.json), copied unchanged to `data/processed/web/` by DT-04) and `stats_meta.json` (provenance, histogram rule, sensitivity variant).

These numbers summarise **observed radar change** ([change index](change-index.md)) inside and outside the dated [reference perimeter](reference-perimeter.md). They are **not** burned area, burn severity, detection accuracy or a validation of the perimeter. More change inside than outside is consistent with the fire footprint, but it does not show that any given pixel burned, nor that outside pixels did not.

## Domain

| Term | Definition |
| --- | --- |
| Valid | DT-02 `valid_mask == 1`: all four GCOV inputs finite, positive and not no-data. Invalid pixels never enter any statistic. |
| Coverage | `valid_coverage_pct = valid pixels / all pixels of the DT-01 crop × 100`. |
| Inside | Valid and DT-03 pixel-centre perimeter mask = 1. The 50 m boundary band is **included** (decision E1), so the inside area equals the DT-03 mask area whenever every inside pixel is valid (as on Plaskett, 100 % coverage); invalid inside pixels are excluded. |
| Outside | Valid and perimeter mask = 0. **Open water is included** (decision F1): there is no land mask yet; revisit with DT-05 terrain data. |
| Area | `area_ha = valid pixels × 100 m² / 10,000` (`pixel_area_m2 = 100`, the 10 m analysis grid; never Web Mercator pixels). |

`highlight` is `null` here: thresholds, highlighted areas and IoU are P1. The optional XP-01 stage computes them ([highlight](highlight.md)) and DT-04 fills this block in the web copy only when that stage was run.

## Distributions

For all valid pixels, inside and outside: p5, p25, p50, p75, p95 (NumPy linear interpolation) and the mean, computed in float64 over the stored float32 index values, as in CH-01.

**Histogram (decision D1).** One set of 30 equal-width bins is shared by the three distributions, so the web can overlay them. Its range is the global p0.5 to p99.5 of all valid pixels. Values outside that range are counted in the first or last bin, so every histogram's counts sum to its group's valid pixels. The first bin therefore covers `(-∞, edges[1])` and the last bin `[edges[-2], +∞)`: each holds its ordinary interval plus the clamped tail. `stats_meta.json` records the range and how many values were below or above it per group, compared in float64 like the clamping.

## Sensitivity variant

`stats_meta.json` → `sensitivity.without_edge_band` repeats the inside/outside zones without the pixels in the DT-03 50 m boundary band, where the reference itself is least precise. It is a check on how much the boundary matters, not part of the contract. A group with no valid pixel outside the band is reported as `null`.

## Input checks

Besides checksums and the shared 10 m grid, CH-02 refuses mixed generations and unexpected semantics: `change.json` must name this `sar.json` (`source_sar.sha256`), the method must be `abs-logratio-hhhv-v1`, the DT-03 rasterization must be the agreed pixel-centre rule (`all_touched: false`) with a 50 m band, and every manifest must have a supported format version.

## Plaskett results (real run, 2026-11-14)

| Group | Valid pixels | Area (ha) | p5 | p25 | p50 | p75 | p95 | mean |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| All valid | 3,109,960 | 31,099.6 | -1.14 | -0.59 | 0.00 | 0.83 | 2.71 | 0.28 |
| Inside | 1,213,498 | 12,134.98 | -1.01 | -0.29 | 0.50 | 1.58 | 3.78 | 0.82 |
| Outside | 1,896,462 | 18,964.62 | -1.18 | -0.71 | -0.22 | 0.41 | 1.60 | -0.06 |

Histogram range [-1.398, 5.286]. Above the range: 15,130 pixels inside vs 420 outside. Without the edge band the medians barely move (inside 0.52, outside -0.22). Coverage is 100 %.

The inside/outside contrast is clear, and the strongest changes concentrate inside the reference. Even so, the distributions overlap: about a quarter of the inside pixels changed less than the crop's typical pixel. Confounders (speckle, open water, moisture, terrain, phenology) are described in the change index method.
