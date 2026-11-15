# Terrain tiles for the 3D story view (AP-07)

Producer: `pipeline/terrain_tiles.py`, configured by `pipeline/configs/terrain_tiles_plaskett.toml`. Output: `data/interim/terrain_tiles/` (gitignored) with `{z}/{x}/{y}.png` and `tiles.json`.

**Why it exists.** The guided story flies over Big Sur in 3D. MapLibre draws relief from a `raster-dem` tile source, and drapes the radar layers and the reference perimeter over it. This stage turns the project's pinned DEM into that tile format. Terrain is **display context only**: it never measures, validates or explains radar change, and it is not used by any statistic.

## Input

The same Copernicus DEM GLO-30 product as DT-05 (`docs/methods/terrain.md`): 1 arc-second (about 30 m), EPSG:4326, heights in metres above the **EGM2008** geoid. It is a **surface model (DSM)**, so it includes canopy and buildings; the sea is stored as 0 m.

| Tile | sha256 | Why |
| --- | --- | --- |
| `Copernicus_DSM_COG_10_N35_00_W122_00_DEM` | `197d09cd…f197` (same as DT-05) | Covers the fire |
| `Copernicus_DSM_COG_10_N36_00_W122_00_DEM` | `cd834ec6…4ce9` | The case AOI reaches 35.992 N, so the tile bounds cross 36 N |

The stage never downloads: each tile is verified against its pinned sha256 (the config header shows the manual `curl` command), and a mismatch stops the run with exit code 2.

## Method

| Choice | Value | Reason |
| --- | --- | --- |
| Bounds | Case AOI bbox plus about 8 km: `[-121.585, 35.77, -121.19, 36.06]` | Relief around the fire for oblique views, without tiling the whole DEM |
| Zooms | 8–12, 256 px tiles (46 tiles) | Zoom 12 is about 31 m per pixel at this latitude, matching the 30 m DEM; MapLibre overzooms above it |
| Warp | Bilinear, each tile reprojected from the DEM mosaic to its EPSG:3857 extent | Smooth relief; nearest would create terraces |
| Encoding | Terrarium: `h = R*256 + G + B/256 - 32768` | Native MapLibre `raster-dem` encoding |
| Precision | Rounded to **1 m** | Far below the DEM's vertical error; halves the PNG size (2.1 MB instead of 4.7 MB) |
| Outside the bounds | 0 m | MapLibre is given the bounds and does not request other tiles |

Every pixel centre inside the bounds must be covered by a DEM tile; otherwise the run stops instead of inventing flat ground. Output is staged and swapped into place; a directory with foreign content is never replaced. Reruns are byte-identical.

`tiles.json` is a TileJSON 3.0 document (`tiles`, `encoding`, `tileSize`, `minzoom`, `maxzoom`, `bounds`, `attribution`) plus a `firetrace` block with the case id, the DEM tiles and checksums, datum, surface model, precision, the elevation range at the maximum zoom and a sha256 for every tile.

## Plaskett result (2026-11-15)

46 tiles, 2.1 MB, elevation 0.0 to 1551.6 m at zoom 12 inside the tile footprints. That range is wider than DT-05's 0–1142 m because the tile bounds extend about 8 km beyond the analysis crop, reaching the highest Santa Lucia summits east of the fire.

## Limitations

- The story view exaggerates the relief (×1.6) for readability and says so on screen.
- A DSM shows canopy height: forest edges can look like small steps. Burned canopy loss after the DEM epoch is not reflected.
- The tiles are not in the web bundle yet: copying them into `data/processed/web/terrain/` belongs to the export stage (follow-up task).
