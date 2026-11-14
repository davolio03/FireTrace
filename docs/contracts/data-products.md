# Contrato v0 — Productos de datos (pipeline → API / web)

**Estado:** borrador v0. La propone el orquestador y la aprueban Datos, Frontend y API en la tarea `BS-02`. Cualquier cambio posterior se hace en un PR propio y sube la versión.

## Convenciones generales

| Aspecto | Valor |
|---|---|
| CRS de análisis | EPSG:32610, rejilla NISAR de 10 m sin remuestrear |
| CRS web | EPSG:3857 para los tiles; EPSG:4326 para GeoJSON |
| Unidades radar | dB = `10·log10(potencia)` de GCOV `HHHH`/`HVHV` (γ⁰, convención del producto) |
| Nodata | `NaN` en float32; máscara explícita en `valid_mask.tif` |
| Fechas | ISO 8601 UTC (`2026-08-16T02:56:39Z`) |
| IDs de época | `t1` = 2026-08-16 (antes), `t2` = 2026-10-03 (después) |

## Ficheros en `data/processed/` (no versionados)

| Fichero | Tipo | Contenido |
|---|---|---|
| `case.json` | JSON | Metadatos del caso (esquema abajo) |
| `sar_{t1,t2}_{hh,hv}_db.tif` | COG float32 | Retrodispersión en dB, recorte del AOI |
| `valid_mask.tif` | COG uint8 | 1 = válido en las 4 capas, 0 = inválido |
| `change_{hh,hv}_db.tif` | COG float32 | `dB(t2) − dB(t1)`, con signo |
| `change_index.tif` | COG float32 | Índice continuo combinado (método en `case.json.method`) |
| `highlight_mask.tif` | COG uint8 | **P1** · 1 = supera el umbral exploratorio |
| `perimeter_wfigs_58728.geojson` | GeoJSON 4326 | Perímetro de referencia con sus propiedades originales |
| `highlight_regions.geojson` | GeoJSON 4326 | **P1** · regiones conectadas con `region_id` y estadísticas por región |
| `stats.json` | JSON | Métricas globales (esquema abajo) |
| `tiles/<layer>/{z}/{x}/{y}.png` | XYZ PNG | Visualización web con paleta fija, una carpeta por capa |
| `tiles/legends.json` | JSON | Rango, paleta y unidades de cada capa de tiles |

## `case.json`

```json
{
  "case_id": "plaskett-2026",
  "name": "Plaskett Fire",
  "location": "Big Sur, Monterey County, California",
  "fire_start": "2026-08-26",
  "aoi_bbox_4326": [-121.0, 35.0, -120.0, 36.0],
  "epochs": {
    "t1": {"datetime": "2026-08-16T02:56:39Z", "granule": "G4284560161-ASF", "orbit": 5504},
    "t2": {"datetime": "2026-10-03T02:56:38Z", "granule": "G4340499432-ASF", "orbit": 6196}
  },
  "acquisition": {"track": 42, "frame": 70, "direction": "descending", "frequency": "A", "pols": ["HH", "HV"]},
  "product": "NISAR_L2_GCOV_PROVISIONAL_V1",
  "reference": {"source": "WFIGS", "objectid": 58728, "datetime": "2026-09-14T20:44:00Z"},
  "method": {"id": "abs-logratio-hhhv-v1", "description": "…", "params": {}},
  "pipeline_version": "git-sha"
}
```

(La bbox es un marcador: la pone el pipeline.)

## `stats.json`

```json
{
  "valid_pixels": 1948374,
  "total_pixels": 1948374,
  "valid_coverage_pct": 100.0,
  "pixel_area_m2": 100,
  "change_index": {"p5": 0.0, "p50": 0.0, "p95": 0.0},
  "inside_perimeter": {"valid_pixels": 0, "change_index_median": 0.0},
  "outside_perimeter": {"valid_pixels": 0, "change_index_median": 0.0},
  "highlight": null
}
```

En P1, `highlight` pasa a ser `{"threshold": …, "area_ha": …, "iou_vs_perimeter": …, "inside_ha": …, "outside_ha": …}`.

## API (FastAPI) — mínimo para el Evidence Inspector

| Endpoint | Respuesta |
|---|---|
| `GET /api/case` | `case.json` |
| `GET /api/stats` | `stats.json` |
| `GET /api/inspect/point?lon=&lat=` | Ver abajo |
| `GET /api/inspect/region?region_id=` | **P1** · estadísticas agregadas de la región |

```json
{
  "lon": -121.5, "lat": 36.1, "x_utm": 0, "y_utm": 0,
  "valid": true,
  "hh_db": {"t1": -12.3, "t2": -15.1, "delta": -2.8},
  "hv_db": {"t1": -18.0, "t2": -21.4, "delta": -3.4},
  "change_index": 3.1,
  "highlighted": null,
  "perimeter_relation": "inside",
  "method_id": "abs-logratio-hhhv-v1",
  "caveats": ["moisture", "slope_geometry", "vegetation_structure"]
}
```

`caveats` sale de reglas deterministas documentadas en el pipeline (por ejemplo pendiente desde el DEM), nunca de un LLM.
