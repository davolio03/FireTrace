# Contrato interno de la web — estado compartido (v1.2.0)

Lo usan las dos personas de frontend (L4 "mapa" y L5 "experiencia") para trabajar en paralelo. **Todas las features leen y escriben el mismo store** (Zustand, en `web/src/state/`) y **nadie toca la instancia de MapLibre directamente fuera de `features/map/`**.

```text
features/story ─┐                    ┌─► features/map        (L4) pinta capas, swipe, selección, cámara
features/zones ─┤                    ├─► features/inspector  (L4) lee selection → /api/inspect/*
features/annot ─┼─► store (acciones) ┼─► features/profile    (L4) lee selection.profile → gráfico
features/...   ─┘                    └─► features/metrics, weather, zones (L5)
```

## Forma del estado

```ts
type LayerId = /* ids de contracts/schemas/layers.schema.json */;
type LonLat = [number, number];

interface Camera { center: LonLat; zoom: number; bearing?: number; pitch?: number }

type Selection =
  | { type: "none" }
  | { type: "point"; point: LonLat }
  | { type: "zone"; zoneId: string }
  | { type: "profile"; line: LonLat[] };

interface MapState {
  camera: Camera;                              // L4 la sincroniza con el mapa en ambos sentidos
  visible: LayerId[];
  opacity: Partial<Record<LayerId, number>>;
  compare: { left: LayerId; right: LayerId; position: number } | null;   // null = sin swipe
  selection: Selection;
  panel: "none" | "inspector" | "zones" | "metrics" | "weather" | "profile";
  tool: "pan" | "inspect" | "draw-profile";
  story: { active: boolean; stepIndex: number };
}
```

## Acciones (la única forma de cambiar el estado)

| Acción | Quién la llama | Efecto que garantiza L4 |
|---|---|---|
| `flyTo(camera, durationMs?)` | story, zones, usuario | Anima el mapa a la cámara |
| `setVisible(ids)` / `toggleLayer(id)` / `setOpacity(id, v)` | panel de capas, story | Muestra u oculta capas respetando el `group` |
| `setCompare(cfg \| null)` / `animateCompare(to, ms)` | story, comparador | Swipe entre dos capas |
| `select(selection)` | clic en el mapa, zones, story, annotations | Resalta en el mapa y abre el panel adecuado |
| `setTool(tool)` | barra de herramientas | Cambia el modo de interacción (p. ej., dibujar el transecto) |
| `applyStoryStep(step)` | story | Aplica un paso de `story.json`: cámara, capas, comparador, foco y panel, **usando las acciones anteriores** |

Reglas:

1. `applyStoryStep` no tiene caminos especiales: un paso de la historia equivale exactamente a lo que haría un usuario. Si la historia funciona, la app funciona.
2. Los datos remotos (case, stats, layers, zones, weather, inspect, profile) se piden con **TanStack Query** usando los tipos generados de `contracts/openapi.yaml` y los schemas. Nunca se guardan en el store.
3. Las anotaciones viven en su propio store persistido (localStorage) con la forma de `annotations.schema.json`. La exportación es ese mismo documento.
4. El store se crea en BS-06 con **implementaciones mínimas** de cada acción, para que L4 y L5 programen contra él desde el primer día. L4 sustituye después los stubs del mapa por la implementación real, sin cambiar las firmas.
5. Cambiar una firma de este fichero sigue la misma regla que el resto del contrato: PR propio y revisión por ambos lados (L4 y L5).
