# Optical context (DT-07)

Producer: `pipeline/optical.py`, configured by `pipeline/configs/optical_plaskett.toml`. Outputs: `data/interim/optical/` (`optical_{during,after}.png`, `optical_layers.json`, `optical_{during,after}.tif`, `optical.json`). DT-04 (`pipeline/export.py`) merges the two layers into the web `layers.json` when `optical.json` exists.

**Why it exists.** Optical satellites see sunlight reflected by the surface, so smoke and cloud hide the ground. The L-band radar wavelength (about 24 cm) is far larger than smoke particles, so it passes through them. Showing a smoky optical image next to the radar change map lets a viewer see that limitation directly. These layers are **complementary context**: NISAR stays the primary observation, and the optical images neither validate nor measure radar change.

## Scenes (decision K1)

| Layer | Scene | Acquired (UTC) | Why |
| --- | --- | --- | --- |
| `optical_during` | `S2A_10SFE_20260830_0_L2A` | 2026-08-30 18:54 | Large smoke plume over the Plaskett area, four days after ignition |
| `optical_after` | `S2B_10SFE_20261015_0_L2A` | 2026-10-15 19:04 | Clear sky, 12 days after the NISAR after scene |

The scenes were chosen by looking at the images. The catalogue cloud percentage (`eo:cloud_cover`) does not flag smoke: the during scene reports only 2.2 %. The fallback during scene is `S2B_10SFE_20260905_1_L2A` (lighter smoke). Neither date matches a NISAR acquisition.

## Data and grid (decision M1)

- `fetch` reads public STAC items from Earth Search (AWS Open Data; no credentials). It downloads the B04/B03/B02 (10 m) and SCL (20 m) COGs once over HTTPS and keeps only the needed window in `data/raw/sentinel2/`, with `optical_manifest.json` (scene metadata, asset URLs, windows, sha256). The full tiles are deleted after cropping.
- Tile 10SFE is EPSG:32610 on the same 10 m lattice as the DT-01 crop grid, so each band is an **exact pixel window** with no resampling. A misaligned grid stops the run.
- `build` verifies every crop against the manifest and never uses the network.

## Rendering (decision L1)

- Reflectance = `DN × 0.0001 − 0.1` (L2A processing baseline ≥ 04.00; scale and offset are read from the STAC metadata). `DN = 0` is nodata and becomes transparent, as does any pixel missing in one of the three bands.
- True colour (B04, B03, B02) uses **one fixed stretch for both scenes**: `clip(reflectance / 0.3, 0, 1) ^ (1 / 2.2)`. A per-scene automatic stretch would make the two images incomparable and could tone smoke down.
- Display PNGs are warped to EPSG:3857 with bilinear resampling per channel through the shared `pipeline/webexport.py`, and share their corners and size with the SAR layers.
- The crop COGs (`optical_*.tif`) keep the original L2A digital numbers (three bands, uint16).
- `optical.json` records valid coverage, median reflectance and the SCL class shares over the AOI window. Some SCL classes are diagnostic only: smoke is not a dedicated class and may appear as cloud or cirrus classes.

## Limitations

- Smoke and cloud are not masked; that is the point of the during layer.
- Dates differ from the NISAR epochs: the during scene falls between t1 and t2, and the after scene is 12 days after t2.
- Visual context only. No burn index (NBR/dNBR) is computed; that would be a separate, validated product.
