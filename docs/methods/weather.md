# Precipitation context (DT-06)

Producer: `pipeline/weather.py`. Output: `data/interim/weather/weather.json` (web contract, [weather schema](../../contracts/schemas/weather.schema.json), copied to `data/processed/web/` by DT-04) and `weather_meta.json` (granules, checksums, cells, weights, rules).

**Why it exists.** L-band backscatter rises with soil and vegetation moisture. Rain shortly before the after scene can raise HH/HV and either mask or mimic change. This series backs the Evidence Inspector's soil-moisture caveat with data. It is **context for the whole AOI**: it does not explain any individual pixel and does not measure soil moisture.

## Source (decision G1)

NASA GPM IMERG **Late Run** daily, version V07 (`GPM_3IMERGDL`), from NASA GES DISC. On 2026-11-14 the public CMR catalogue listed 49 Late granules (V07C) for 2026-08-16..2026-10-03 and **no Final granules** (`GPM_3IMERGDF`): Final, which is gauge-adjusted, is published about 3.5 months later. Late is a satellite-only estimate. The output records the version; recompute with Final when it is released.

## Acquisition (decision H1)

- `uv run python -m pipeline.weather fetch --token-file <file>` (or `EARTHDATA_TOKEN`) queries the public CMR API, downloads each daily granule once with the user's own Earthdata token, and writes `data/raw/imerg/imerg_manifest.json` (date, file, URL, sha256). The token is never written anywhere. The Earthdata account must have approved the "NASA GESDISC DATA ARCHIVE" application (EULA); otherwise downloads return HTTP 403.
- `uv run python -m pipeline.weather build` verifies every granule against the manifest and makes **no network call**. The demo never downloads or authenticates.

Granules are global daily files (~30 MB each, ~1.5 GB in total) in `data/raw/`, which is gitignored.

## Spatial mean (decision I1)

The AOI is the DT-01 crop bbox in EPSG:4326. Each 0.1° IMERG cell that overlaps it gets a weight equal to its overlapping area on the sphere: Δλ × (sin φ₂ − sin φ₁). Weights are normalised to sum to 1. The AOI spans only about six cells, so the series is a coarse regional estimate. A day is `null` if any weighted cell is missing or negative (fill), which is conservative. `weather_meta.json` lists the cells and weights.

## Dates (decision J1)

IMERG days are UTC days. The before scene was acquired on 2026-08-16 at 02:56 UTC and the after scene on 2026-10-03 at 02:56 UTC.

- `daily` lists every UTC day from the t1 date to the t2 date (49 days). The first day's rain fell almost entirely after t1.
- `total`, `rain_days_over_1mm` (> 1 mm) and `last_rain_before_t2` use only days **before** the t2 date, because the t2 day's rain fell almost entirely after the after scene.
- `null` days are excluded from the summary and listed in `weather_meta.json`. Daily values are rounded to 0.0001 mm before summarising.

## Limitations

- Satellite-only Late estimates can miss or misplace light coastal rain; Final may differ.
- 0.1° cells (about 10 km) mix land and ocean along the Big Sur coast.
- Daily totals cannot resolve rain within a few hours of an acquisition.
- Rain is a proxy; soil and canopy moisture also depend on fog, dew, evaporation and terrain.
