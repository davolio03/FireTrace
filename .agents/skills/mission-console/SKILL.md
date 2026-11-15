# Mission console — FireTrace web visual system

Use this skill when changing the FireTrace web interface (`web/`). It records the
visual and interaction rules the team agreed for the mission-console look, so
new work stays coherent instead of adding isolated styles.

## Why this exists

No frontend, design or accessibility skill was installed in the environment when
AP-09 was implemented, so these rules were written from the approved task and
the MapLibre capabilities verified against the installed version. They are not
a substitute for reviewing the result in a browser.

## Visual language

| Element | Rule |
| --- | --- |
| Surfaces | Deep navy stack (`#050d18` background, `#0c1f33` panels, `#10263b` workspace). Panels never return to white cards. |
| Accents | Cyan `#7adcf1` for active state and instruments; amber `#ffbd6a` for focus rings; red `#ffe5df` on `#522c32` for errors. |
| Typography | Space Grotesk Variable for display, IBM Plex Mono (tabular numerals) for dates, readouts, labels and badges. Both OFL-1.1 and self-hosted through Fontsource. |
| Labels | Uppercase, letter-spaced, monospaced micro-labels; they identify state without relying on colour alone. |
| Texture | A single filmic grain and vignette overlay (`pointer-events: none`). It never carries data. |

## Layout: the map is the screen

The analysis view is a HUD, not a page of cards:

- The map fills the viewport edge to edge. No rounded container, no frame.
- A 46 px top bar holds the case, the observation window, the MOCK badge and
  the story actions.
- A vertical rail of glyph buttons floats over the map on the left. The active
  tool is filled cyan; the label appears on hover and focus.
- Exactly one floating glass panel is visible. The other tools stay mounted
  with `hidden`, so their form state survives switching.
- Inside the panel: hairline separators, no nested cards, mono labels and
  values, square cyan checkboxes and thin sliders.
- Edge instrumentation is real: MapLibre's metric scale bar, a cursor
  coordinate readout, the camera bearing, and the active tool and selection.
- The landing page is a full-bleed globe with the title over it and the case
  metadata in a column on the right edge.

## Motion

- The globe descends into the case when the reader enters the analysis, and
  the shared camera lands where the descent stopped.
- The instrument wakes with a short boot sweep when the analysis opens.
- A lit sweep crosses the map whenever the instrumentation changes.
- Measured values count to their new reading (`AnimatedValue`).
- Every custom animation is disabled under `prefers-reduced-motion`.

## Map rules

- The basemap is the same OpenStreetMap raster, colour graded dark in the style
  expression. Grading changes rendering only, never the data layers above it.
- Radar and context rasters use `raster-layer-blend: screen` so they read as
  luminous data; vector overlays keep their legend colour and get a pale casing
  for contrast.
- The analysis map stays Mercator. The overview globe uses the projection
  expression, so zooming morphs globe to map natively.
- Vector overlays, the graticule and the selection marker are references. They
  must never suggest live acquisition, scanning or confidence.

## Interaction rules

- Motion comes from Motion (`LazyMotion` + `domAnimation`), with
  `MotionConfig reducedMotion="user"`.
- Number keys (1–5) switch tools while the analysis is open.
- Visible focus is mandatory: keep the amber `:focus-visible` outline.
- Actions confirm with inline `role="status"` notices; the MOCK notice stays
  visible and persistent, never a transient toast.

## Checks after a change

```sh
cd web && npm run lint && npm test && npm run build
```

Then confirm in a browser: desktop and 390 px layouts, keyboard order, focus
visibility, reduced motion, contrast of new text on its surface, and the MOCK
banner.
