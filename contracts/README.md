# Contrato de datos y API — v1.1.0

El contrato permite que **pipeline, API y web avancen en paralelo**. Cada lado programa contra el contrato, no contra el código de los demás.

```text
              contracts/schemas/*.schema.json   ← fuente de verdad (JSON Schema 2020-12)
              contracts/openapi.yaml            ← endpoints de la API (referencia a los schemas)
                         │
   ┌─────────────────────┼──────────────────────────┐
   ▼                     ▼                          ▼
pipeline/            api/ (FastAPI)              web/ (React)
produce               sirve los productos;       lee data/web/* + API;
data/processed/web/   sus tests validan las      tipos TS generados del OpenAPI;
y lo valida con       respuestas contra los      en modo mock usa
validate.py           schemas                    contracts/fixtures/ + MSW
```

## La regla clave: misma forma, distinta fuente

`contracts/fixtures/web/` tiene **exactamente la misma estructura** que el pipeline real escribe en `data/processed/web/`:

```text
case.json          metadatos del caso                    → case.schema.json
stats.json         métricas sobre píxeles válidos        → stats.schema.json
layers.json        manifiesto de capas + leyendas        → layers.schema.json
perimeter.geojson  perímetro WFIGS 58728 (EPSG:4326)
layers/<id>.png    una PNG RGBA por capa ráster, ya en EPSG:3857 (transparente = nodata)
review_zones.geojson  (P1, opcional) zonas a revisar   → review-zones.schema.json
```

- **Web:** la ruta base de datos se elige con `VITE_DATA_BASE_URL` y la API con `VITE_API_BASE_URL`; con `VITE_USE_MOCKS=true`, MSW responde a `/api/*` usando `contracts/fixtures/api/`. Pasar de mock a real es cambiar variables de entorno, no código.
- **API:** los tests usan `contracts/fixtures/`; en producción lee `data/processed/`.
- **Pipeline:** hecho = `uv run contracts/tools/validate.py data/processed/web` pasa.

Todos los ficheros llevan `data_status: "mock" | "real"`. **La web debe mostrar un aviso visible de MOCK** cuando sea `mock`, para que nunca se enseñe un dato sintético como real.

## Capas ráster: PNG + coordenadas

Cada capa es una imagen que MapLibre pinta con una fuente `image` y sus 4 esquinas (`coordinates` en `layers.json`). No hay servidor de tiles. Al tamaño del AOI (~20 × 17 km a 10 m, unos 2000 × 1700 px) es sencillo y rápido. La paleta y el rango los fija el pipeline y se describen en `legend`, así que la web pinta la leyenda sin conocer los datos.

IDs de capa fijos: `sar_t1_hh`, `sar_t2_hh`, `sar_t1_hv`, `sar_t2_hv`, `change_hh`, `change_hv`, `change_index`, `highlight_mask` (P1), `valid_mask`, `perimeter`, `review_zones` (P1). El campo `group` (`sar`, `observed_change`, `highlighted_change`, `reference`, `quality`) mantiene en la UI la separación observación / interpretación / contraste.

Los valores numéricos de cada píxel no salen de las PNG, sino de `GET /api/inspect/point`.

## Zonas a revisar (P1 · EV-04)

`review_zones.geojson` lista regiones conectadas, precalculadas y ordenadas, para que el analista sepa **dónde mirar primero**:

| `kind` | Prefijo | Qué es |
|---|---|---|
| `change_outside_perimeter` | `CO` | Cambio radar destacado **fuera** del perímetro → discrepancia |
| `no_change_inside_perimeter` | `NI` | Poco cambio radar **dentro** del perímetro → discrepancia (¿isla sin quemar?, ¿límite del radar?) |
| `change_inside_perimeter` | `CI` | Cambio destacado dentro → ejemplos de **acuerdo** |

Cada zona trae la superficie, el centroide y la bbox (para que el mapa vuele a ella), las medianas de HH y HV antes, después y delta, el índice, la distancia al perímetro y la fracción de píxeles en los que se activa cada cautela. `method` documenta los umbrales usados. Todo sale del pipeline: la web no recalcula nada. Las discrepancias se presentan como **"para investigar"**, nunca como errores del radar ni del perímetro.

## Fixtures (todo sintético salvo la geometría del perímetro)

| Fichero | Uso |
|---|---|
| `fixtures/web/*` | Datos mock con la estructura de producción |
| `fixtures/api/inspect-point-{inside,outside,invalid}.json` | Respuestas de ejemplo del inspector (casos dentro del perímetro, fuera y píxel sin datos) |
| `fixtures/api/stats-with-highlight.json` | `stats` con la máscara P1 activada, para maquetar los widgets de F05 |
| `fixtures/api/inspect-grid.json` | **Solo para mocks**: rejilla compacta que MSW usa para responder a cualquier clic con valores coherentes |

Regenerar los mocks (deterministas, con semilla fija):

```bash
uv run contracts/tools/generate_mocks.py
uv run contracts/tools/generate_mocks.py --perimeter-source data/raw/wfigs_58728_raw.geojson   # re-simplificar el perímetro
uv run contracts/tools/validate.py          # valida fixtures; en CI
```

## Cómo cambiar el contrato

1. Rama `docs/contract-<tema>` y un PR solo con el cambio de contrato.
2. Actualiza schema(s) → `openapi.yaml` si aplica → regenera los fixtures → `validate.py` en verde.
3. Sube `contract_version`: **patch** = aclaración, **minor** = campo opcional nuevo (compatible), **major** = renombrar, quitar o cambiar el significado de un campo.
4. Revisa al menos una persona de cada lado afectado (datos y web/API).
5. Guarda la decisión en Engram: `[contract] <qué cambió y por qué>`.

Un cambio de contrato no se cuela dentro de un PR de feature.
