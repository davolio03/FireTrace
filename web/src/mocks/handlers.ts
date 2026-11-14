import { http, HttpResponse } from 'msw'
import caseFixture from '../../../contracts/fixtures/web/case.json'
import statsFixture from '../../../contracts/fixtures/web/stats.json'
import layersFixture from '../../../contracts/fixtures/web/layers.json'
import grid from '../../../contracts/fixtures/api/inspect-grid.json'
import type { operations } from '../generated/api'

const mercator = (lat: number) =>
  Math.log(Math.tan(Math.PI / 4 + (lat * Math.PI) / 360))
const latitude = (y: number) => (360 / Math.PI) * Math.atan(Math.exp(y)) - 90
const round = (value: number, places: number) => Number(value.toFixed(places))

function inspectPoint(lon: number, lat: number) {
  const [west, south, east, north] = grid.aoi_bbox
  const base = {
    contract_version: caseFixture.contract_version,
    data_status: 'mock' as const,
    query: { lon, lat },
    method_id: caseFixture.method.id,
  }
  const empty = { t1: null, t2: null, delta: null }
  if (lon < west || lon >= east || lat <= south || lat > north) {
    return {
      ...base,
      pixel: null,
      valid: false,
      hh_db: empty,
      hv_db: empty,
      change_index: null,
      change_index_percentile: null,
      highlighted: null,
      perimeter_relation: 'unknown',
      caveats: [],
    }
  }
  const col = Math.floor(((lon - west) / (east - west)) * grid.image_width)
  const row = Math.floor(
    ((mercator(north) - mercator(lat)) / (mercator(north) - mercator(south))) *
      grid.image_height,
  )
  const r = Math.floor(row / grid.step_px)
  const c = Math.floor(col / grid.step_px)
  const sampleRow = r * grid.step_px
  const sampleCol = c * grid.step_px
  const value = (field: keyof typeof grid.fields) => grid.fields[field][r][c]
  const hh1 = value('sar_t1_hh')
  const hh2 = value('sar_t2_hh')
  const hv1 = value('sar_t1_hv')
  const hv2 = value('sar_t2_hv')
  const valid = hh1 !== null && hh2 !== null && hv1 !== null && hv2 !== null
  const pol = (t1: number | null, t2: number | null) =>
    valid && t1 !== null && t2 !== null
      ? { t1, t2, delta: round(t2 - t1, 2) }
      : empty
  const centerLon =
    west + ((sampleCol + 0.5) / grid.image_width) * (east - west)
  const centerY =
    mercator(north) -
    ((sampleRow + 0.5) / grid.image_height) *
      (mercator(north) - mercator(south))
  return {
    ...base,
    // These are the mock generator's synthetic coordinates, not measured UTM positions.
    pixel: {
      row: sampleRow,
      col: sampleCol,
      x: 600000 + sampleCol * 10,
      y: 3975000 - sampleRow * 10,
      crs: 'EPSG:32610',
      center_lon: round(centerLon, 6),
      center_lat: round(latitude(centerY), 6),
    },
    valid,
    hh_db: pol(hh1, hh2),
    hv_db: pol(hv1, hv2),
    change_index: valid ? value('change_index') : null,
    change_index_percentile: null,
    highlighted: null,
    perimeter_relation: grid.inside[r][c] ? 'inside' : 'outside',
    caveats: [],
    terrain: {
      elevation_m: grid.terrain.elevation_m[r][c],
      slope_deg: grid.terrain.slope_deg[r][c],
      aspect_deg: null,
    },
  }
}

type Coordinate = [number, number]
type Profile =
  operations['inspectProfile']['responses'][200]['content']['application/json']

function distance(a: Coordinate, b: Coordinate) {
  const rad = Math.PI / 180
  const dLat = (b[1] - a[1]) * rad
  const dLon = (b[0] - a[0]) * rad
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(a[1] * rad) * Math.cos(b[1] * rad) * Math.sin(dLon / 2) ** 2
  return 12742000 * Math.asin(Math.min(1, Math.sqrt(h)))
}

function mockProfile(line: Coordinate[], spacing: number) {
  const lengths = line
    .slice(1)
    .map((point, index) => distance(line[index], point))
  const total = lengths.reduce((sum, length) => sum + length, 0)
  const limit = Math.min(total, spacing * 1999)
  const samples: Profile['samples'] = []
  let segment = 0
  let offset = 0
  for (let i = 0; i <= Math.floor(limit / spacing); i++) {
    const d = i * spacing
    while (segment < lengths.length - 1 && d > offset + lengths[segment]) {
      offset += lengths[segment++]
    }
    const fraction = lengths[segment] ? (d - offset) / lengths[segment] : 0
    const start = line[segment]
    const end = line[segment + 1]
    const lon = start[0] + (end[0] - start[0]) * fraction
    const lat = start[1] + (end[1] - start[1]) * fraction
    const point = inspectPoint(lon, lat)
    samples.push({
      distance_m: d,
      lon,
      lat,
      valid: point.valid,
      hh_t1: point.hh_db.t1,
      hh_t2: point.hh_db.t2,
      hv_t1: point.hv_db.t1,
      hv_t2: point.hv_db.t2,
      change_index: point.change_index,
      inside_perimeter:
        point.perimeter_relation === 'unknown'
          ? null
          : point.perimeter_relation === 'inside',
      elevation_m: 'terrain' in point ? point.terrain.elevation_m : null,
    })
  }
  const crossings = samples
    .slice(1)
    .flatMap((sample, i) =>
      sample.inside_perimeter !== null &&
      samples[i].inside_perimeter !== null &&
      sample.inside_perimeter !== samples[i].inside_perimeter
        ? [sample.distance_m]
        : [],
    )
  return {
    contract_version: caseFixture.contract_version,
    data_status: 'mock',
    line,
    length_m: limit,
    spacing_m: spacing,
    truncated: total > spacing * 1999,
    samples,
    perimeter_crossings_m: crossings,
  }
}

export const handlers = [
  http.get('*/api/health', () =>
    HttpResponse.json({ status: 'ok', data_status: 'mock' }),
  ),
  http.get('*/api/case', () => HttpResponse.json(caseFixture)),
  http.get('*/api/stats', () => HttpResponse.json(statsFixture)),
  http.get('*/api/layers', () => HttpResponse.json(layersFixture)),
  http.get('*/api/inspect/point', ({ request }) => {
    const query = new URL(request.url).searchParams
    const lonText = query.get('lon')
    const latText = query.get('lat')
    const lon = Number(lonText)
    const lat = Number(latText)
    if (
      !lonText?.trim() ||
      !latText?.trim() ||
      !Number.isFinite(lon) ||
      !Number.isFinite(lat) ||
      Math.abs(lon) > 180 ||
      Math.abs(lat) > 90
    ) {
      return HttpResponse.json(
        { detail: 'Invalid coordinates' },
        { status: 422 },
      )
    }
    return HttpResponse.json(inspectPoint(lon, lat))
  }),
  http.post('*/api/inspect/profile', async ({ request }) => {
    let body: unknown
    try {
      body = await request.json()
    } catch {
      return HttpResponse.json({ detail: 'Invalid profile' }, { status: 422 })
    }
    if (
      typeof body !== 'object' ||
      body === null ||
      !('line' in body) ||
      !Array.isArray(body.line)
    ) {
      return HttpResponse.json({ detail: 'Invalid profile' }, { status: 422 })
    }
    const line: unknown[] = body.line
    const spacing = 'spacing_m' in body ? body.spacing_m : 10
    if (
      line.length < 2 ||
      !line.every(
        (p) =>
          Array.isArray(p) &&
          p.length === 2 &&
          p.every(
            (v: unknown) => typeof v === 'number' && Number.isFinite(v),
          ) &&
          Math.abs(p[0]) <= 180 &&
          Math.abs(p[1]) <= 90,
      ) ||
      typeof spacing !== 'number' ||
      !Number.isFinite(spacing) ||
      spacing <= 0
    ) {
      return HttpResponse.json({ detail: 'Invalid profile' }, { status: 422 })
    }
    return HttpResponse.json(mockProfile(line as Coordinate[], spacing))
  }),
  http.all('*/api/*', () =>
    HttpResponse.json(
      { detail: 'Mock endpoint not implemented' },
      { status: 501 },
    ),
  ),
]
