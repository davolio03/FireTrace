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

## Human delivery checklist

- [ ] Independent toggles/legends and before/after alignment verified with real outputs
- [ ] Inspector/coverage checked against numerical products, not display colors
- [ ] Reference date, confounds, sources/licenses, limitations and AI-tool usage disclosed
- [ ] Complete journey succeeds twice and backup works without network access
- [ ] Freeze/release owner selects a verified revision plus matching artifacts for rollback

Use Kanvas for delivery task state; this checklist is evidence to collect, not task approval.
