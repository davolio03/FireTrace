# Plaskett demo — target 90–120 seconds

**Not yet rehearsed:** no running app, real-processing acceptance or deployed endpoint is established by this foundation. Never present synthetic fixtures as real radar evidence.

## Planned sequence

1. Identify Plaskett, its location, fire start and NISAR observation dates/sources.
2. Compare the same geographic extent before/after in HH/HV.
3. Toggle **Observed radar changes** and explain the continuous calculation.
4. Independently overlay the dated **Official fire perimeter**; examine agreement and discrepancies.
5. Select a valid pixel and show actual HH/HV dB, signed deltas, method, reference relation, provenance and cautions. Show invalid/out-of-AOI behavior without invented numbers.
6. State that radar change is not confirmed fire or ecological severity. Threshold masks and DL are optional P1, not needed for this journey.

## Rehearsal record to complete

| Evidence | Required record |
| --- | --- |
| Candidate | App revision, matching real artifact identities, source/method/configuration |
| Start | Actual local commands and configuration names; no secrets |
| Checks | Exact commands, observed outputs and exit codes; relevant tests and known-value selections |
| Presentation | Measured duration on the presenting laptop/network; screenshot/recording location |
| No-data | Invalid and out-of-coverage query demonstrations; graceful missing-artifact behavior |
| Fallback | Rehearsed local precomputed artifacts/recording and exact restoration procedure |

Do not fill these fields with hypothetical URLs or success claims. No live Earthdata login, scene downloads, catalog queries or training belongs in the presentation path.

## IN-01 local integration evidence — 2026-11-15

**Reviewed:** the real bundle loads, selected values match its statistics, and the layers look aligned in a bounded visual check. Gabriel reviewed the interface and relayed David's approval of the integration evidence. This is not scientific validation.

- Application: `da208f9` on the IN-01 branch. Bundle: GitHub release `data-web-plaskett-f66c4d9`, extracted to `data/processed/web/`. The release reports pipeline commit `f66c4d9` and `SOURCE_DATE_EPOCH=1794700000`. Case `plaskett-2026`, status `real`, method `abs-logratio-hhhv-v1`. The release does not include raw inputs or analysis COGs.
- `cd data/processed && sha256sum -c SHA256SUMS.txt`: exit 0. `UV_OFFLINE=1 uv run --no-sync contracts/tools/validate.py data/processed/web`: exit 0. An additional local SHA-256 comparison matched all 19 output paths in `export.json`. These checks establish bundle consistency, not scientific accuracy.
- Served the bundle on `127.0.0.1:5190` with CORS restricted to the local web origin. Started the web on `127.0.0.1:5189` with `VITE_USE_MOCKS=false` and `VITE_DATA_BASE_URL=http://127.0.0.1:5190`. Chromium had external network access blocked; the basemap was unavailable and the map displayed a load error.
- In Chromium, real case metadata, layer controls and legends loaded. The perimeter toggle changed state; comparison controls switched between HH and HV with the expected before/after labels. This does not establish image alignment.
- The Results panel matched `stats.json` for total/valid pixels (`3,109,960`), valid coverage (`100%`), inside pixels and area (`1,213,498`; `12,134.98 ha`), outside pixels and area (`1,896,462`; `18,964.62 ha`), and each displayed mean and percentile in both regions. The documented [statistics method](methods/stats.md) includes open water in the outside group and includes the 50 m boundary band. These are descriptive values from the product, not burned area.
- Browser request interception simulated a missing `stats.json` and, separately, a `case.json` with an invalid `data_status`. Both displayed “Unable to load case data.” without switching to MOCK. The real files were not modified.
- With separately authorized anonymous OpenStreetMap requests, Chromium loaded the real imagery, official perimeter and basemap without map alerts. The before/after HH and HV views looked aligned at the initial view; after zooming and panning in HV, the views still appeared aligned. All 12 visible layer toggles changed and restored state without alerts. Local screenshots are in the gitignored `data/processed/in01-evidence/` directory. This qualitative screen check does not measure geolocation or validate pixels. It does not establish why radar changes occurred.
- A mock fallback was also started using `VITE_USE_MOCKS=true npm run dev -- --host 127.0.0.1 --port 5191 --strictPort` with no `VITE_DATA_BASE_URL`; Chromium displayed the fixture product and MOCK notice. Stop the real-data web and data servers, then use that command from `web/` to return to the checked fixture fallback. No previously verified real bundle has been selected for rollback.
- Gabriel reviewed the real-data interface and reported that the visual result looked correct. He relayed David's approval of the integration evidence and confirmation that the previous open-agreements list in `docs/CONTRACTS.md` was outdated; this branch reconciles it with the documented methods.
- No API inspector behavior or independent numerical recomputation was verified. The 2026-09-14 perimeter predates the after observation and is not pixel-level ground truth.
- The real release does not contain `terrain/tiles.json`; a request for the optional story terrain returned 404 during the human review session. The story's real-data integration is IN-03, outside IN-01; this check does not establish 3D terrain availability.

For the local real-data check, the bundle server was bound only to loopback:

```sh
python3 -c 'from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer; from functools import partial
class Handler(SimpleHTTPRequestHandler):
 def end_headers(self):
  self.send_header("Access-Control-Allow-Origin", "http://127.0.0.1:5189"); super().end_headers()
ThreadingHTTPServer(("127.0.0.1",5190),partial(Handler,directory="data/processed/web")).serve_forever()'
```

In a second terminal, from `web/`:

```sh
VITE_USE_MOCKS=false VITE_DATA_BASE_URL=http://127.0.0.1:5190 npm run dev -- --host 127.0.0.1 --port 5189 --strictPort
```

## IN-03 guided story on real data — 2026-11-15

**Checked:** the 7-step guided story and the context layers play on the real bundle without mock data, and every figure in `web/src/story/story.json` traces to a real product field or a cited source. This is a display and wording check, not scientific validation.

- Bundle: release `data-web-plaskett-f66c4d9` (`sha256sum -c SHA256SUMS.txt`: OK). It has no `terrain/tiles.json`, so the story stays 2D on the published bundle. For this check, a scratch copy outside the repository added the real Copernicus GLO-30 tiles from `contracts/fixtures/web/terrain/` (46 tiles, `data_status: real`); `uv run contracts/tools/validate.py <copy>`: OK. Publishing the tiles in the bundle is proposed as DT-09.
- Served on loopback as in the IN-01 procedure (`127.0.0.1:5190`, CORS limited to `http://127.0.0.1:5189`); web on `127.0.0.1:5189` with `VITE_USE_MOCKS=false`, Node v26.13.1, vite 8.3.8. The page must be opened at `127.0.0.1`, not `localhost`, or the CORS rule blocks the data.
- All 7 steps played in order with autoplay paused: no MOCK text on any step; relief shown on every step ("Relief ×1.6 · Copernicus DEM GLO-30"); step 3 crossfaded the Sentinel-2 smoke scene (2026-08-30) into the real HV after layer; steps 5–7 showed the real index legend (−1.28 to 3.81); step 6 showed the real highlight mask inside the perimeter.
- Requests to the data server: 19 from the page (4 JSON manifests, 12 layer PNGs), all 200; the server log recorded 92 terrain-tile requests, all 200, and no 4xx/5xx. Basemap tiles came from OpenStreetMap.
- The analysis view's rainfall panel showed the real NASA GPM IMERG Late V07C daily series with no MOCK notice.
- Screenshots of steps 1–3 and 5–7 are in the gitignored `data/processed/in03-evidence/`.
- Not checked: the inspector API behind "Explore the evidence" (IN-02) and deployment (DL-01).

### Story figure trace

| Step | Statement | Source → value |
| --- | --- | --- |
| orbit | NASA–ISRO mission, about 747 km up | [NASA NISAR mission overview](https://science.nasa.gov/mission/nisar/mission-overview/): "Orbit Altitude 747 km", partnership NASA and ISRO |
| orbit | 16 August and 3 October 2026, same descending track | `case.json` `epochs.t1/t2.datetime` 2026-08-16 / 2026-10-03, `acquisition.direction` descending, track 42 |
| context | Started on 26 August, Big Sur | `case.json` `fire_start` 2026-08-26 (CAL FIRE source), `location` Big Sur, Monterey County |
| context | Perimeter mapped from infrared imagery on 14 September | `perimeter.geojson` `MapMethod` "IR Image Interpretation", `PolygonDateTime` 2026-09-14T20:44Z |
| context | About 12,100 ha | `stats.json` `inside_perimeter.area_ha` 12,134.98 (WFIGS 29,992.9 acres = 12,137.7 ha) |
| context | Steep terrain | DT-05 [terrain](methods/terrain.md): median slope 20.4°, 14.4 % of the crop > 30° |
| smoke | Sentinel-2 smoke plume during the fire | [optical](methods/optical.md): `S2A_10SFE_20260830_0_L2A`, large smoke plume over the Plaskett area |
| smoke | L-band wavelength about 24 cm | NASA NISAR mission overview: "L-band: 24 cm" |
| change-index | Higher inside, distributions overlap | `stats.json` median 0.50 inside vs −0.22 outside; inside p25 −0.29 < outside p95 1.60 |
| highlight | About 1,050 ha, almost all inside, 9 % of the perimeter | `stats.json` `highlight.area_ha` 1,049.66, `inside_ha` 1,049.2; 1,049.2 / 12,134.98 = 8.6 % |

Removed: "many patches follow slopes and drainages". Across the ten `change_inside_perimeter` zones in `review_zones.geojson`, the share of pixels above 30° (`steep_slope` fraction) ranges from 1 % to 25 % and averages 7.8 % by area, below the 14.4 % crop share; drainages are not measured. `docs/methods/highlight.md` (XP-01) still contains the same sentence; its owner should review it. A rain sentence was not added: the story test deliberately excludes rain and soil-moisture claims, and the rainfall series is shown in its own panel.

## Human delivery checklist

- [ ] Independent toggles/legends and before/after alignment verified with real outputs
- [ ] Inspector/coverage checked against numerical products, not display colors
- [ ] Reference date, confounds, sources/licenses, limitations and AI-tool usage disclosed
- [ ] Complete journey succeeds twice and backup works without network access
- [ ] Freeze/release owner selects a verified revision plus matching artifacts for rollback

Use Kanvas for delivery task state; this checklist is evidence to collect, not task approval.
