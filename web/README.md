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
details are unavailable. The viewer displays fixture SAR and observed-change
layers and the reference perimeter with independent visibility and opacity
controls. Its legends come from the layer manifest. The Evidence Inspector and
before/after comparison belong to later tasks. Fixture display is not evidence
of real-data alignment or scientific validation.

## Shared map state

Frontend features use `useMapStore` from `src/state/mapStore.ts` and its actions.
The store holds UI state only; remote data stays outside it. `flyTo` and
`animateCompare` update their target state immediately as placeholders: the map
lane will connect real animations later. Applying a story step uses the same
actions as manual interaction. With no comparison or focus in a step, the
corresponding prior state is cleared.
TypeScript widens arrays and strings in directly imported JSON; consumers of
story files must validate their data against the story schema and provide a
`StoryStep`-typed value before calling `applyStoryStep`.
