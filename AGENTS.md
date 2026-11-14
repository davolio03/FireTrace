# AGENTS.md — FireTrace Explorer

Instrucciones para **cualquier agente de IA** (Claude Code, Codex, Cursor, Gemini, OpenCode…) y para las personas del equipo. Si algo de aquí contradice a otro documento, manda este fichero; si contradice a `docs/propuesta.md` en cuestiones científicas o de alcance, manda la propuesta y hay que avisar.

## 1. Qué construimos

App web para el NASA Space Apps Challenge 2026 (reto *Dancing with the SARs*). Muestra **qué cambió en el radar NISAR antes y después del Plaskett Fire** (Big Sur, 2026), permite inspeccionar la señal HH/HV píxel a píxel y contrastarla con el perímetro oficial WFIGS 58728.

- Propuesta completa, alcance y criterios: [`docs/propuesta.md`](docs/propuesta.md). **Léela antes de tu primera tarea.**
- Contratos entre pipeline, API y web: [`docs/contracts/`](docs/contracts/).

### Reglas científicas innegociables

1. **Observación ≠ interpretación ≠ contraste.** Nunca etiquetes un cambio radar como "área quemada" ni "incendio confirmado". Usa *observed radar change* / *highlighted radar change*.
2. **NISAR es el dato principal.** Sentinel‑1/2, RAVG, etc. solo como complemento.
3. **Nada de cifras inventadas.** Ninguna confianza, AUC o porcentaje que no salga de un cálculo reproducible del repo. El AUC 0,984 de Döweler et al. es externo y nunca se presenta como nuestro.
4. **El Evidence Inspector muestra valores calculados y el método real**, no texto generado por un LLM.
5. Potencias a dB con `10 * log10(x)` solo para `x > 0`; los píxeles inválidos se enmascaran y se excluyen de todas las métricas.
6. El perímetro (14‑sep‑2026) es una referencia, no verdad píxel a píxel.

## 2. Arquitectura y estructura del repo

```text
pipeline/        Python. GeoTIFF NISAR → productos precalculados (dB, índice de cambio, tiles, stats)
api/             Python FastAPI. Consultas del Evidence Inspector (píxel/región) sobre los productos
web/             React + TypeScript + Vite. Mapa, comparador, capas, métricas, inspector
docs/            Propuesta, contratos, decisiones (docs/decisions/NNN-titulo.md)
data/raw/        GeoTIFF originales (NO versionado)
data/processed/  Salidas del pipeline (NO versionado; se regeneran con un comando)
kanvas.json      Tablero de tareas (ver §4)
.engram/         Memoria compartida de agentes (ver §6)
```

**Principio:** todo lo pesado se precalcula. La demo nunca descarga escenas ni entrena en directo.

### Stack

| Capa | Tecnología |
|---|---|
| Pipeline | Python 3.11, `uv`, `rasterio`, `numpy`, `xarray`, `geopandas`, `shapely`, `scikit-image`, `rio-cogeo` |
| ML (P1, opcional) | PyTorch |
| API | FastAPI + `rasterio` (lectura puntual de COG), `pydantic` |
| Web | React 19 + TypeScript + Vite, **MapLibre GL JS** (mapa) + **deck.gl** si hace falta, Tailwind CSS + shadcn/ui, TanStack Query, Zustand para estado de UI, Recharts para gráficos |
| Calidad | `ruff` + `pytest` (Python); `eslint` + `prettier` + `vitest` (web) |

Cambiar una pieza del stack requiere un ADR corto en `docs/decisions/` y aprobación en el tablero.

### Comandos (se irán completando según exista cada parte)

```bash
# Pipeline / API
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run python -m pipeline.run --all          # regenera data/processed/
uv run uvicorn api.main:app --reload

# Web
cd web && npm install
npm run dev
npm run lint && npm run test && npm run build
```

Si añades o cambias un comando, actualiza esta sección en el mismo PR.

## 3. Flujo de trabajo: una feature = un worktree = un PR

1. **Coge una tarea** del tablero Kanvas (§4) que esté `todo` y no bloqueada.
2. **Crea un worktree** fuera del repo principal, con rama a partir de `main` actualizado:

   ```bash
   git fetch origin
   git worktree add ../FireTrace-wt/<ID>-<slug> -b <tipo>/<ID>-<slug> origin/main
   # ej.: git worktree add ../FireTrace-wt/CH-01-change-index -b feat/CH-01-change-index origin/main
   ```

   `<tipo>`: `feat`, `fix`, `data`, `docs`, `chore`, `exp` (experimentos ML).
3. **Trabaja solo dentro de tu worktree** y solo en el alcance de la tarea. Si descubres trabajo extra, propónlo en el tablero en vez de hacerlo.
4. **Commits** pequeños con Conventional Commits y el ID de la tarea: `feat(web): add before/after swipe [AP-03]`.
5. **Antes del PR:** lint + tests de las partes tocadas en verde; si cambias un contrato, actualiza `docs/contracts/` y avisa en Engram.
6. **PR contra `main`** con título `[<ID>] Descripción` y la plantilla:
   - Qué cambia para el usuario / para otros módulos
   - Cómo se ha verificado (comandos, capturas)
   - Contratos tocados (sí/no)
   - Tarea Kanvas: `<ID>`
7. Pasa la tarea a `review` en Kanvas (`finish`). **Una persona revisa y hace merge**; el agente nunca hace merge ni push a `main`.
8. Tras el merge: `git worktree remove ../FireTrace-wt/<ID>-<slug>` y borra la rama.

Prohibido: `push --force` a ramas compartidas, `--no-verify`, commitear datos (`*.tif`, `*.h5`, `*.nc`, checkpoints) o secretos (`.env`, tokens de Earthdata).

## 4. Tablero: Kanvas

El tablero es `kanvas.json`; se maneja **solo** con la CLI, nunca editándolo a mano. Las instrucciones completas están en [`.agents/skills/kanvas/SKILL.md`](.agents/skills/kanvas/SKILL.md).

```bash
python .agents/skills/kanvas/kanvas.py status      # al empezar cada sesión
python .agents/skills/kanvas/kanvas.py ready
python .agents/skills/kanvas/kanvas.py start <ID> -m "Plan: ..."
python .agents/skills/kanvas/kanvas.py finish <ID> --file resumen.md
```

- Firma siempre con `--as <herramienta>-<persona>` (ej. `--as claude-david`, `--as codex-lucia`) o exporta `KANVAS_AGENT`.
- **Un único tablero de verdad:** el del checkout principal en `main`. Desde un worktree, apunta a él con `-b <ruta-checkout-principal>/kanvas.json`. No modifiques `kanvas.json` dentro de tu rama de feature (provoca conflictos de merge).
- Los humanos aprueban propuestas y marcan `done`; los agentes proponen, empiezan, anotan y pasan a `review`.
- Grupos: `BS` Base · `DT` Datos/pipeline · `CH` Índice de cambio · `AP` App web · `EV` Evidencia y métricas · `XP` Exploratorio P1 · `DL` Entrega.

## 5. Contratos entre módulos

Los ficheros de `docs/contracts/` definen rutas, formatos, unidades y esquemas JSON que producen el pipeline y consumen la API y la web. Son el punto de coordinación entre personas: **mientras el pipeline real no exista, la web y la API trabajan con datos mock que cumplen el contrato** (`web/src/mocks/`, `api/tests/fixtures/`).

Cambiar un contrato = PR propio (`docs/contract-...`) revisado por al menos un miembro de cada lado afectado.

## 6. Memoria compartida: Engram

Proyecto Engram: **`firetrace`** (`.engram/config.json`). Úsalo para lo que otro agente necesitará saber y no está en el código:

- **Guarda** (`mem_save` / `engram save`): decisiones y su porqué, descubrimientos sobre los datos (rangos, nodata, rarezas de NISAR), bugs no obvios, cambios de contrato, bloqueos.
- **Busca** (`mem_search`) antes de empezar una tarea y antes de tomar una decisión de diseño.
- Formato del título: `[<ID>] <tema>`; tipo: `decision`, `discovery`, `bugfix`, `architecture`.
- No guardes secretos, datos crudos ni lo que ya cuenta git.

**Sincronización (por defecto, sin servidor):** la memoria viaja por git en `.engram/`.

```bash
engram sync --import      # al empezar: importa lo que han subido los demás
engram sync               # al terminar: exporta tus memorias nuevas a .engram/ (commitéalo en tu PR)
```

Si el equipo levanta un servidor Engram Cloud, se documentará aquí (`engram cloud config --server <url>` + `engram cloud enroll firetrace`).

Las **decisiones que cambian interfaces** van además a `docs/contracts/` o `docs/decisions/` vía PR: Engram es memoria de trabajo, el repo es la fuente de verdad.

## 7. Convenciones de código

- **Python:** tipado, funciones puras en `pipeline/` (entrada→salida, sin estado global), rutas con `pathlib`, CRS explícito siempre (EPSG:32610 para análisis, EPSG:4326/3857 solo para web). Tests con rásteres sintéticos pequeños, nunca con los GeoTIFF reales.
- **Web:** componentes funcionales, TypeScript estricto, sin `any`. Textos de UI en inglés (jurado internacional), con nombres de capa del §6 de la propuesta (*Observed radar changes*, *Highlighted radar changes*, *Official fire perimeter*). Accesible: contraste AA, leyendas en todas las capas, paletas aptas para daltonismo.
- **Docs y comentarios:** español o inglés, pero consistentes dentro del fichero.
- Commits y PRs en inglés o español, con el ID de tarea.

## 8. Roles del equipo

| Rol | Persona | Grupos principales |
|---|---|---|
| Datos NISAR + modelos | David (orquestador) | DT, CH, XP |
| Procesamiento geoespacial | _por asignar_ | DT, EV |
| CV / ML | _por asignar_ | CH, XP |
| Evaluación científica | _por asignar_ | EV |
| Frontend | _por asignar_ | AP |
| Integración y storytelling | _por asignar_ | BS, DL |
