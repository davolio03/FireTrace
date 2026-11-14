# Continuous radar change index (CH-01)

Method id: **`abs-logratio-hhhv-v1`**. Producer: `pipeline/change.py`. Inputs: the DT-02 dB layers and common valid mask. This is an **observation** product: it shows where and how much the L-band backscatter changed between the two dates, relative to the typical change in the crop. It is **not** burned area, burn severity or a fire detection, and it has no threshold.

## Computation

For every pixel where `valid_mask == 1` (all four GCOV inputs finite, positive and not no-data):

```text
change_hh_db = t2_hh_db - t1_hh_db          signed dB difference (after - before)
change_hv_db = t2_hv_db - t1_hv_db
S            = |change_hh_db| + |change_hv_db|
change_index = (S - median(S)) / (1.4826 * MAD(S))
MAD(S)       = median(|S - median(S)|)
```

Pixels with `valid_mask == 0` are NaN in all three outputs and never enter the median or MAD. Differences, the median, the MAD and the index are computed in float64 and cast to float32 only for storage, on the unchanged 10 m EPSG:32610 crop grid. Input dB values must be finite wherever `valid_mask == 1`; otherwise the run fails, so all three outputs and the statistics share one valid domain.

## Decisions (agreed 2026-11-14)

| Decision | Choice | Why |
| --- | --- | --- |
| Normalization domain (A) | All valid pixels of the crop | Independent of the reference perimeter. Normalising only outside the perimeter would use the perimeter to build the index that is later compared against it (circular). Cost: the changed area itself enters the median/MAD; robust statistics limit that bias. |
| Speckle filter (B) | None in v1 | Each pixel is exactly what NISAR measured, so the Evidence Inspector can explain it from its own values. Speckle is documented below instead of hidden. |
| Signed changes | Kept in `change_{hh,hv}_db` | A decrease (typical when foliage and branches burn, especially in HV) and an increase (for example wetter soil) tell different stories. Only the index uses magnitudes. |
| Robust z-score | Median and 1.4826 × MAD | The median/MAD are not dragged by the large changes that matter; 1.4826 makes the MAD comparable to a standard deviation for normally distributed data. |
| Clipping / threshold | None | The scientific value is stored in full. Colour stretch is a display choice (DT-04); thresholds are P1 (XP-01). |
| MAD = 0 or no valid pixels | Error | A robust z-score is undefined when at least half of the valid pixels share the median change (or none are valid). On real radar pairs this is unexpected and worth investigating before any reporting. |

The combination of absolute HH/HV log-ratio changes follows the methodological reference cited in the [proposal](../propuesta.md) (Timber/Plaskett preprint). It is a simplified single-pair version, not a reproduction of that work, and the preprint's reported performance is not FireTrace performance.

## Worked example

Suppose five valid pixels have magnitudes `S = 1, 2, 3, 4, 100` dB. The median is 3. The absolute deviations are 2, 1, 0, 1, 97, so the MAD is 1. The index is `(S - 3) / 1.4826`:

| S (dB) | 1 | 2 | 3 | 4 | 100 |
| --- | --- | --- | --- | --- | --- |
| index | -1.35 | -0.67 | 0.00 | 0.67 | 65.4 |

The extreme pixel does not move the reference: with a mean and standard deviation instead, the "typical" level would jump to 22 dB. A pixel with `change_hh_db = +3` and `change_hv_db = -4` has `S = 7` dB.

## Reading the values

- `change_index = 0`: the pixel changed as much as the typical pixel of the crop.
- `change_index = 3`: its change magnitude is about three robust standard deviations above typical.
- Negative values: less change than typical. They are kept, not clipped.
- The index is relative to this crop and this date pair; values are not comparable across cases without recomputing the reference.

## Confounders and limitations

Large index values mean large radar change, which can have causes other than fire:

- **Speckle:** without spatial filtering, single-pixel differences are noisy. On the Plaskett crop the typical magnitude is about 4 dB (median S), so isolated high pixels deserve less trust than coherent patches.
- **Open water:** wind changes the sea-surface roughness between passes, producing large, random changes unrelated to land cover.
- **Soil and vegetation moisture:** rain between the dates raises backscatter, especially HH.
- **Terrain:** steep slopes, radar shadow and layover distort backscatter; slope-aligned patterns can appear.
- **Vegetation structure and phenology:** seasonal change, harvest or other disturbance also change HV.
- **Reference timing:** the WFIGS perimeter (2026-09-14) predates the after scene and is not pixel-level ground truth.

## Outputs

`data/interim/change/`: `change_hh_db.tif`, `change_hv_db.tif`, `change_index.tif` (COG float32, NaN no-data) and `change.json` (method, median, MAD, percentiles, valid count, checksums). Percentiles describe the stored float32 values over valid pixels, using NumPy's default linear interpolation. DT-04 copies `change.json` → `method` into `case.json`; CH-02 builds `stats.json`. Layout: [ARCHITECTURE](../ARCHITECTURE.md).

Command: `uv run python -m pipeline.change --sar-dir data/interim/sar --output-dir data/interim/change [--quicklook <png>]`. The optional quicklook is an ungeoreferenced viridis p2–p98 PNG for review evidence, not the web product; it must be written outside the input and output directories and is rendered before the outputs are published.
