# FireTrace web scaffold

Install dependencies with `npm ci`, then run `npm run dev` from this directory.
Use `npm run lint`, `npm run test`, and `npm run build` for local checks.

The default development mode serves synthetic fixtures from
`contracts/fixtures/web` and starts the mock API without a backend. The visible
MOCK notice identifies synthetic data, which is not scientific validation.
Point inspection uses the nearest lower sampled grid cell; the mock generator's
projected pixel coordinates are synthetic and do not describe a real UTM
transformation. Mock profiles sample that grid along an approximate geographic
path; their distances and perimeter crossings are illustrative, not measurements.
Unimplemented mock API endpoints return 501.

Set `VITE_USE_MOCKS=false` and `VITE_DATA_BASE_URL` to a real artifact base URL
to disable the mock service worker and load other case data. An API consumer can
use `VITE_API_BASE_URL` to select its server. Regenerate API types from the
contract with `npm run generate:types`.

The map loads OpenStreetMap tiles in the browser; this requires a connection and
shares the visitor's IP address with the tile service. When offline, geographic
details are unavailable. Scientific layers and the Evidence Inspector interface
belong to later tasks.
