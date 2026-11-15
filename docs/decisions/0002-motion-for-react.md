# ADR 0002: Motion for React in the analysis experience

- Status: accepted for AP-09, pending code review
- Date: 2026-11-15
- Human owner / affected reviewers: Gabriel; web maintainers
- Kanvas task: AP-09

## Context

The web experience needs coordinated, interruptible interface transitions while
preserving keyboard access, reduced-motion preferences and the existing map state.
The application already uses React, MapLibre and CSS; the current production
bundle also has a large-chunk warning.

A second research round compared animation, 3D and interaction libraries against
this repository, with measured bundle cost rather than estimates: Motion 14.14
(added, about 31 kB gzip on the main chunk), GSAP with ScrollTrigger (45 kB
gzip), anime.js (14 kB), Lenis (5 kB), auto-animate (4 kB), Radix slider
(11 kB), Sonner (10 kB), lottie-react (83 kB), deck.gl (199 kB), Three.js
(190 kB), React Three Fiber (250 kB), drei (212 kB) and postprocessing (148 kB).
MapLibre 6.18 itself already provides globe projection, sky and fog, native
paint transitions, `raster-layer-blend` and projection expressions.

## Decision

Use the open-source Motion for React library for purposeful interface transitions.
Gabriel approved the dependency and its anonymous download; that approval is
recorded in AP-09. Respect the user's reduced-motion preference and avoid
animation that implies live telemetry or scientific measurements.

Take the visual weight from MapLibre and CSS first: globe projection with
atmosphere, colour-graded dark basemap, additive raster blending, a graticule,
a filmic grain overlay and self-hosted OFL fonts. Add no second rendering
engine: Three.js with React Three Fiber would add roughly 850 kB gzip, its
React peer range excludes React 19.4, and the project keeps MapLibre as the
only map engine.

## Alternatives and tradeoffs

- CSS is appropriate for simple effects and remains in use; coordinated layout
  and interruptible transitions are more difficult to maintain there.
- GSAP provides timeline control but adds about 45 kB gzip of imperative
  machinery next to Motion, and its standard licence is not an MIT licence.
- A separate 3D renderer or deck.gl adds another rendering stack without an
  identified data-visualization need; the existing MapLibre map remains primary.
- Lenis, auto-animate, Radix primitives and Sonner remain candidates for
  specific needs (smooth scrolling, list reordering, a custom slider, transient
  notices) and were not added without such a need.

## Consequences and verification

The web dependency and lockfile change; no API, scientific method or data
contract changes. Verify the bundle size, keyboard access, reduced-motion mode,
existing workflows and responsive layouts. Web maintainers review the change.
Rollback removes Motion and replaces its uses with static or CSS presentation.
The visual rules are recorded in the project skill
`.agents/skills/mission-console/SKILL.md`.
