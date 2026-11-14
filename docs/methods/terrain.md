# Terrain context (DT-05)

Producer: `pipeline/terrain.py`, configured by `pipeline/configs/terrain_plaskett.toml`; display PNGs use the shared `pipeline/webexport.py`. Terrain is **complementary, non-NISAR context**. It helps explain where the radar signal may be distorted (steep slopes, layover, shadow). It is never evidence of fire, burned area or severity, and it does not validate any radar change.

## Inputs (pinned, never downloaded)

| Input | Value |
| --- | --- |
| DEM | Copernicus DEM GLO-30 tile `Copernicus_DSM_COG_10_N35_00_W122_00_DEM` (1 arc-second, about 30 m; EPSG:4326; pixel-is-point), sha256 pinned |
| Heights | metres above the **EGM2008 geoid** |
| Surface | a **surface model (DSM)** from TanDEM-X data (2011-2015): it includes canopy and structures from that time, before the fire |
| Radar geometry | `radarGrid` cubes of the **t2** NISAR GCOV `.h5` (G4340499432-ASF): `incidenceAngle`, `losUnitVectorX/Y` on a 500 m EPSG:32610 grid with 21 ellipsoidal height levels, sha256 pinned |
| Grid | the DT-01 crop grid from `data/interim/nisar/ingest.json` (10 m EPSG:32610); its sha256 is recorded |

The licence attribution travels in the layer `source.label` (shown by the web), with the dataset DOI as `source.url`. A missing or changed file stops the run. Refreshing a pin is a deliberate, reviewed change (the config shows the manual fetch commands).

The geometry granule name must carry the ingest track, direction and frame (`_042_D_070_`) and the t2 start time. t1 has no `.h5`. Both scenes share track 42 descending frame 70, so the t2 geometry is used for both epochs. This is a documented **assumption**: a repeat pass on the same track has nearly the same geometry, but it has not been verified against a t1 `.h5`.

## Elevation, slope and aspect (decision C1)

1. The DEM is warped with **bilinear** resampling onto the crop grid **extended by a 100 m margin**. The DEM must cover this extended grid entirely; otherwise the run stops.
2. The **Horn (1981) 3x3** gradient is computed in metres on the 10 m grid. Then the margin is trimmed, so crop-edge pixels still have full neighbourhoods. A pixel whose 3x3 window holds no-data gets no slope.
3. `slope = atan(|∇z|)` in degrees (0-90).
4. `aspect` is the downslope direction in degrees clockwise from north, in [0, 360). It is NaN where the slope is exactly 0 (flat, aspect undefined).

The **effective resolution stays about 30 m**: interpolating to 10 m adds no terrain detail, it only aligns the values pixel-for-pixel with the radar products. Slopes are therefore smoothed compared with the real hillsides.

GLO-30 stores the open sea at 0 m. On Plaskett, about 418,000 crop pixels (13 %) are sea with slope 0 and undefined aspect. No water mask is applied here; terrain values over water carry no meaning.

## Radar geometry and layover/shadow (decision D1)

The cubes are interpolated to every pixel centre: bilinear in x/y, then linear in height using the pixel's DEM elevation. Cube heights are **ellipsoidal**, while DEM heights are geoid heights. The offset of a few tens of metres is neglected. On Plaskett the incidence angle changes by at most 0.02° per 500 m of height, so the effect is below about 0.002°.

NISAR looks **left**. On this descending pass the target-to-sensor vector points west-north-west (east component about −0.62, north about +0.21), and the ellipsoid incidence is 40.4-41.6° over the crop. The code takes the direction from the cubes and assumes nothing about it.

- `local_incidence.tif` is the 3D angle between the terrain normal `(-p, -q, 1)` and the target-to-sensor unit vector.
- `layover_shadow.tif` uses the classic **range-plane** criteria, where `g` is the terrain rise per metre toward the sensor. With the range-plane local incidence `θ + atan(g)`:
  - **< 0°** is layover (`1`): the slope facing the sensor is steeper than the incidence angle;
  - **> 90°** is shadow (`2`): the slope facing away is steeper than `90° − θ`;
  - otherwise none (`0`); `255` means unknown.

These are **local, approximate** flags. They do not trace rays, so they miss shadow cast by a distant ridge and the passive layover zone around an active one, and they are computed from 30 m terrain. NISAR GCOV applies area-based radiometric terrain correction (gamma0) but reports `shadowMaskingApplied=False`, so these flags are context for EV-02 caveats, not a product mask. Thresholds and caveat wording belong to EV-02.

## Display layers (decision B1)

`hillshade.png` (sun at 315° / 45°, display only) and `slope.png` (sequential ramp 0-45°, the contract fixture stops; steeper slopes share the last colour) are warped bilinearly to EPSG:3857. The 3857 extent is rounded outwards so the whole crop footprint is covered. Their four EPSG:4326 corners come from that grid. `terrain_layers.json` is a complete `layers.schema.json` document (`contract_version` 1.2.0, `data_status` real) holding only the `hillshade` and `slope` layers with `group: terrain` and the mandatory `source`. DT-04 merges these entries into `layers.json` and copies the PNGs to `layers/`. The layer `url`s are already the web paths. Nothing is measured from the PNGs.

## Outputs

`data/interim/terrain/` (gitignored): `elevation.tif`, `slope.tif`, `aspect.tif`, `local_incidence.tif` (float32 COG, NaN nodata), `layover_shadow.tif` (uint8 COG, nodata 255), `hillshade.png`, `slope.png`, `terrain_layers.json` and `terrain.json`.

`terrain.json` records:
- source and geometry provenance with checksums;
- the native DEM grid and the ingest checksum;
- the method;
- min/median/max and valid counts per layer;
- the incidence range;
- layover/shadow counts and percentages;
- the web corners and sizes;
- the output checksums.

The set is built in a staging directory and swapped in only when complete. The stage refuses an output directory holding files it does not own. Reruns are byte-identical.

## Plaskett run (real data)

| Quantity | Value |
| --- | --- |
| Elevation | 0.0-1,142.2 m (median 594.6 m) |
| Slope | median 20.4°, max 63.0°; 14.4 % of pixels > 30°, 0.7 % > 40° |
| Local incidence | 0.04-89.1° (median 40.9°) |
| Layover / shadow | 2,819 px (0.09 %) / 0 px |
| Web PNGs | 1,938 x 1,660 px |

Layover concentrates on steep west-facing coastal and canyon slopes, which face the west-looking sensor. No pixel reaches the local shadow criterion: the facing-away slope would have to exceed about 49°, which 30 m terrain rarely shows.
