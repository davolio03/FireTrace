# FireTrace web scaffold

Install dependencies with `npm ci`, then run `npm run dev` from this directory.
Use `npm run lint`, `npm run test`, and `npm run build` for local checks.

This initial scaffold does not load scientific data. It centers on Big Sur and
loads OpenStreetMap tiles in the browser; this requires a connection and shares
the visitor's IP address with the tile service. When offline, the map background
remains visible but geographic details are unavailable. Mock data and the
Evidence Inspector belong to later tasks.
