# Internal web contract — shared state (v1.2.0)

Used by the two frontend lanes (L4 "map" and L5 "experience") to work in parallel. **Every feature reads and writes the same store** (Zustand, in `web/src/state/`) and **nobody touches the MapLibre instance outside `features/map/`**.

```text
features/story ─┐                      ┌─► features/map        (L4) draws layers, swipe, selection, camera
features/zones ─┤                      ├─► features/inspector  (L4) reads selection → /api/inspect/*
features/annot ─┼─► store (actions) ───┼─► features/profile    (L4) reads selection.profile → chart
features/...   ─┘                      └─► features/metrics, weather, zones (L5)
```

## State shape

```ts
type LayerId = /* ids from contracts/schemas/layers.schema.json */;
type LonLat = [number, number];

interface Camera { center: LonLat; zoom: number; bearing?: number; pitch?: number }

type Selection =
  | { type: "none" }
  | { type: "point"; point: LonLat }
  | { type: "zone"; zoneId: string }
  | { type: "profile"; line: LonLat[] };

interface MapState {
  camera: Camera;                              // L4 keeps it in sync with the map both ways
  cameraDurationMs: number;                    // duration of the last flyTo; 0 = jump (additive, AP-07)
  visible: LayerId[];
  opacity: Partial<Record<LayerId, number>>;
  compare: { left: LayerId; right: LayerId; position: number } | null;   // null = no swipe
  selection: Selection;
  panel: "none" | "inspector" | "zones" | "metrics" | "weather" | "profile";
  tool: "pan" | "inspect" | "draw-profile";
  story: { active: boolean; stepIndex: number };
}
```

## Actions (the only way to change state)

| Action | Called by | Effect guaranteed by L4 |
|---|---|---|
| `flyTo(camera, durationMs?)` | story, zones, user | Animates the map to the camera over `durationMs` (default 0 = jump; skipped under `prefers-reduced-motion`). Finished user movements (drag, zoom, rotate) write the map camera back with `flyTo(camera, 0)`; programmatic moves never do. The map starts from the store camera and fits the data only while the camera is still the initial one |
| `setVisible(ids)` / `toggleLayer(id)` / `setOpacity(id, v)` | layer panel, story | Shows/hides layers, respecting their `group` |
| `setCompare(cfg \| null)` / `animateCompare(to, ms)` | story, comparator | Swipe between two layers |
| `select(selection)` | map click, zones, story, annotations | Highlights on the map and opens the matching panel |
| `setTool(tool)` | toolbar | Changes the interaction mode (e.g. draw a transect) |
| `applyStoryStep(step)` | story | Applies a `story.json` step (camera, layers, compare, focus, panel) **using the actions above** |

Rules:

1. `applyStoryStep` has no special code paths: a story step is exactly what a user could do. If the story works, the app works.
2. Remote data (case, stats, layers, zones, weather, inspect, profile) is fetched with **TanStack Query** using types generated from `contracts/openapi.yaml` and the schemas. It is never copied into the store.
3. Annotations live in their own persisted store (localStorage) shaped like `annotations.schema.json`. The export is that same document.
4. BS-07 creates the store with **minimal implementations** of every action so L4 and L5 can code against it from day one. L4 later replaces the map stubs with the real implementation without changing signatures.
5. Changing a signature here follows the same rule as the rest of the contract: a dedicated PR reviewed by both sides (L4 and L5).
