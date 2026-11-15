import type { Camera } from '../../state/mapStore'

// Narrow local types copied from contracts/schemas/review-zones.schema.json v1.2.0.
export type ZoneKind =
  | 'change_outside_perimeter'
  | 'no_change_inside_perimeter'
  | 'change_inside_perimeter'
export interface PolStats {
  t1_median: number
  t2_median: number
  delta_median: number
}
export interface Caveat {
  id: string
  label: string
  fraction: number
}
export interface ZoneProps {
  zone_id: string
  kind: ZoneKind
  rank: number
  area_ha: number
  centroid: [number, number]
  bbox: [number, number, number, number]
  valid_fraction: number
  hh_db: PolStats
  hv_db: PolStats
  change_index: { median: number; p90: number }
  distance_to_perimeter_m: number
  caveats: Caveat[]
}
export interface Zone {
  type: 'Feature'
  id: string
  geometry: { type: 'Polygon' | 'MultiPolygon'; coordinates: unknown[] }
  properties: ZoneProps
}
export interface ReviewZones {
  type: 'FeatureCollection'
  contract_version: '1.2.0'
  data_status: 'mock' | 'real'
  method: {
    change_threshold: number
    no_change_threshold: number
    smoothing: string
    min_area_ha: number
    max_zones_per_kind: number
  }
  features: Zone[]
}

export const caveatIds = [
  'steep_slope',
  'radar_shadow_layover',
  'soil_moisture_change',
  'vegetation_structure',
  'near_perimeter_edge',
  'low_backscatter',
  'other_disturbance',
]

export const kindOrder: ZoneKind[] = [
  'change_outside_perimeter',
  'no_change_inside_perimeter',
  'change_inside_perimeter',
]
export const kindLabels: Record<ZoneKind, string> = {
  change_outside_perimeter:
    'Observed radar change outside the official perimeter',
  no_change_inside_perimeter:
    'Little observed radar change inside the official perimeter',
  change_inside_perimeter:
    'Observed radar change inside the official perimeter',
}

type Rec = Record<string, unknown>
const isRec = (v: unknown): v is Rec => typeof v === 'object' && v !== null
const num = (v: unknown): v is number =>
  typeof v === 'number' && Number.isFinite(v)
const nums = (v: unknown, n: number): boolean =>
  Array.isArray(v) && v.length === n && v.every(num)
const pol = (v: unknown): boolean =>
  isRec(v) && num(v.t1_median) && num(v.t2_median) && num(v.delta_median)

function isZone(f: unknown): f is Zone {
  if (!isRec(f) || f.type !== 'Feature' || typeof f.id !== 'string')
    return false
  const p = f.properties
  return (
    isRec(f.geometry) &&
    (f.geometry.type === 'Polygon' || f.geometry.type === 'MultiPolygon') &&
    isRec(p) &&
    typeof p.zone_id === 'string' &&
    /^(CO|NI|CI)-[0-9]{2,}$/.test(p.zone_id) &&
    kindOrder.includes(p.kind as ZoneKind) &&
    Number.isInteger(p.rank) &&
    num(p.area_ha) &&
    nums(p.centroid, 2) &&
    nums(p.bbox, 4) &&
    num(p.valid_fraction) &&
    pol(p.hh_db) &&
    pol(p.hv_db) &&
    isRec(p.change_index) &&
    num(p.change_index.median) &&
    num(p.change_index.p90) &&
    num(p.distance_to_perimeter_m) &&
    Array.isArray(p.caveats) &&
    p.caveats.every(
      (c) =>
        isRec(c) &&
        typeof c.id === 'string' &&
        caveatIds.includes(c.id) &&
        typeof c.label === 'string' &&
        num(c.fraction),
    )
  )
}

export function isReviewZones(value: unknown): value is ReviewZones {
  if (!isRec(value)) return false
  const m = value.method
  return (
    value.type === 'FeatureCollection' &&
    value.contract_version === '1.2.0' &&
    (value.data_status === 'mock' || value.data_status === 'real') &&
    isRec(m) &&
    num(m.change_threshold) &&
    num(m.no_change_threshold) &&
    typeof m.smoothing === 'string' &&
    num(m.min_area_ha) &&
    num(m.max_zones_per_kind) &&
    Array.isArray(value.features) &&
    value.features.every(isZone)
  )
}

export function groupZones(
  data: ReviewZones,
): { kind: ZoneKind; zones: Zone[] }[] {
  return kindOrder.map((kind) => ({
    kind,
    zones: data.features
      .filter((f) => f.properties.kind === kind)
      .sort(
        (a, b) =>
          a.properties.rank - b.properties.rank ||
          b.properties.area_ha - a.properties.area_ha,
      ),
  }))
}

const mercY = (lat: number) =>
  0.5 - Math.log(Math.tan(Math.PI / 4 + (lat * Math.PI) / 360)) / (2 * Math.PI)

// Web-Mercator fit (512px tiles) of the bbox inside a viewport minus padding.
// shortcut: default viewport is a fixed size, not the real map container; pass the real one if exposed.
export function cameraForBbox(
  bbox: [number, number, number, number],
  viewport: { width: number; height: number } = { width: 640, height: 480 },
  padding = 48,
): Camera {
  const [w, s, e, n] = bbox
  const fx = Math.max((e - w) / 360, 1e-9)
  const fy = Math.max(mercY(s) - mercY(n), 1e-9)
  const zx = Math.log2(Math.max(viewport.width - 2 * padding, 1) / (512 * fx))
  const zy = Math.log2(Math.max(viewport.height - 2 * padding, 1) / (512 * fy))
  const zoom = Math.min(16, Math.max(0, Math.min(zx, zy)))
  return { center: [(w + e) / 2, (s + n) / 2], zoom }
}
