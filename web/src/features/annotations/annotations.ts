import type { LonLat, Selection } from '../../state/mapStore'

export type Verdict =
  'consistent_with_fire' | 'doubtful' | 'not_fire_related' | 'needs_field_check'
export type Evidence = {
  change_index: number | null
  hh_delta_db: number | null
  hv_delta_db: number | null
  perimeter_relation: 'inside' | 'outside' | 'crosses' | 'unknown'
  caveat_ids?: string[]
}
type Geometry = {
  type: 'Point' | 'LineString' | 'Polygon' | 'MultiPolygon'
  coordinates: unknown[]
}
export type Annotation = {
  type: 'Feature'
  id: string
  geometry: Geometry
  properties: {
    target: { type: 'zone' | 'point' | 'profile' | 'area'; zone_id?: string }
    verdict: Verdict
    note: string
    author: string
    created_at: string
    updated_at?: string
    evidence: Evidence
  }
}
export type AnnotationDocument = {
  type: 'FeatureCollection'
  contract_version: '1.2.0'
  case_id: string
  exported_at: string
  data_status: 'mock' | 'real'
  method_id?: string
  features: Annotation[]
}

const verdicts: Verdict[] = [
  'consistent_with_fire',
  'doubtful',
  'not_fire_related',
  'needs_field_check',
]
const relations = ['inside', 'outside', 'crosses', 'unknown']
const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value)
const allowed = (value: Record<string, unknown>, keys: string[]) =>
  Object.keys(value).every((key) => keys.includes(key))
const validDate = (value: unknown) => {
  if (typeof value !== 'string') return false
  const match =
    /^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(?:[Zz]|([+-])(\d{2}):(\d{2}))$/.exec(
      value,
    )
  if (!match) return false
  const [, year, month, day, hour, minute, second, , offsetHour, offsetMinute] =
    match
  const y = Number(year),
    m = Number(month),
    d = Number(day)
  const leap = y % 4 === 0 && (y % 100 !== 0 || y % 400 === 0)
  const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
  return (
    m >= 1 &&
    m <= 12 &&
    d >= 1 &&
    d <= days[m - 1] &&
    Number(hour) <= 23 &&
    Number(minute) <= 59 &&
    Number(second) <= 59 &&
    (offsetHour === undefined ||
      (Number(offsetHour) <= 23 && Number(offsetMinute) <= 59))
  )
}
const nullableNumber = (value: unknown) =>
  value === null || (typeof value === 'number' && Number.isFinite(value))
const point = (value: unknown): value is LonLat =>
  Array.isArray(value) &&
  value.length === 2 &&
  value.every((x) => typeof x === 'number' && Number.isFinite(x)) &&
  Math.abs(value[0]) <= 180 &&
  Math.abs(value[1]) <= 90
const line = (value: unknown) =>
  Array.isArray(value) && value.length >= 2 && value.every(point)
const ring = (value: unknown) =>
  Array.isArray(value) &&
  value.length >= 4 &&
  value.every(point) &&
  value[0][0] === value[value.length - 1][0] &&
  value[0][1] === value[value.length - 1][1]
const polygon = (value: unknown) =>
  Array.isArray(value) && value.length > 0 && value.every(ring)

export function validGeometry(value: unknown): value is Geometry {
  if (!isRecord(value) || !Array.isArray(value.coordinates)) return false
  if (value.type === 'Point') return point(value.coordinates)
  if (value.type === 'LineString') return line(value.coordinates)
  if (value.type === 'Polygon') return polygon(value.coordinates)
  if (value.type === 'MultiPolygon')
    return value.coordinates.length > 0 && value.coordinates.every(polygon)
  return false
}

function validFeature(value: unknown): value is Annotation {
  if (
    !isRecord(value) ||
    !allowed(value, ['type', 'id', 'geometry', 'properties']) ||
    value.type !== 'Feature' ||
    typeof value.id !== 'string' ||
    !value.id ||
    !validGeometry(value.geometry) ||
    !isRecord(value.properties)
  )
    return false
  const p = value.properties
  if (
    !allowed(p, [
      'target',
      'verdict',
      'note',
      'author',
      'created_at',
      'updated_at',
      'evidence',
    ]) ||
    !isRecord(p.target) ||
    !allowed(p.target, ['type', 'zone_id']) ||
    typeof p.target.type !== 'string' ||
    !['zone', 'point', 'profile', 'area'].includes(p.target.type) ||
    (p.target.zone_id !== undefined && typeof p.target.zone_id !== 'string') ||
    !verdicts.includes(p.verdict as Verdict) ||
    typeof p.note !== 'string' ||
    Array.from(p.note).length > 2000 ||
    typeof p.author !== 'string' ||
    !validDate(p.created_at) ||
    (p.updated_at !== undefined && !validDate(p.updated_at)) ||
    !isRecord(p.evidence)
  )
    return false
  const e = p.evidence
  return (
    allowed(e, [
      'change_index',
      'hh_delta_db',
      'hv_delta_db',
      'perimeter_relation',
      'caveat_ids',
    ]) &&
    nullableNumber(e.change_index) &&
    nullableNumber(e.hh_delta_db) &&
    nullableNumber(e.hv_delta_db) &&
    typeof e.perimeter_relation === 'string' &&
    relations.includes(e.perimeter_relation) &&
    (e.caveat_ids === undefined ||
      (Array.isArray(e.caveat_ids) &&
        e.caveat_ids.every((id: unknown) => typeof id === 'string')))
  )
}

export function parseExport(text: string, caseId: string): AnnotationDocument {
  const doc: unknown = JSON.parse(text)
  if (
    !isRecord(doc) ||
    !allowed(doc, [
      'type',
      'contract_version',
      'case_id',
      'exported_at',
      'data_status',
      'method_id',
      'features',
    ]) ||
    doc.type !== 'FeatureCollection' ||
    doc.contract_version !== '1.2.0' ||
    doc.case_id !== caseId ||
    !validDate(doc.exported_at) ||
    (doc.data_status !== 'mock' && doc.data_status !== 'real') ||
    (doc.method_id !== undefined && typeof doc.method_id !== 'string') ||
    !Array.isArray(doc.features) ||
    !doc.features.every(validFeature) ||
    new Set(doc.features.map((feature: Annotation) => feature.id)).size !==
      doc.features.length
  ) {
    throw new Error('Invalid or incompatible annotations')
  }
  return doc as AnnotationDocument
}

export function createAnnotation(input: {
  selection: Selection
  author: string
  note: string
  verdict: Verdict
  evidence: Evidence
  zoneGeometry?: Geometry
}): Annotation {
  const { selection } = input
  const geometry: Geometry | undefined =
    selection.type === 'point'
      ? { type: 'Point', coordinates: selection.point }
      : selection.type === 'profile'
        ? { type: 'LineString', coordinates: selection.line }
        : selection.type === 'zone'
          ? input.zoneGeometry
          : undefined
  if (
    !geometry ||
    !validGeometry(geometry) ||
    !input.author.trim() ||
    Array.from(input.note).length > 2000 ||
    !verdicts.includes(input.verdict)
  )
    throw new Error('Annotation is incomplete')
  const target =
    selection.type === 'zone'
      ? { type: 'zone' as const, zone_id: selection.zoneId }
      : selection.type === 'point'
        ? { type: 'point' as const }
        : { type: 'profile' as const }
  return {
    type: 'Feature',
    id: crypto.randomUUID(),
    geometry,
    properties: {
      target,
      verdict: input.verdict,
      note: input.note,
      author: input.author.trim(),
      created_at: new Date().toISOString(),
      evidence: input.evidence,
    },
  }
}

const key = (caseId: string) => `firetrace.annotations.${caseId}`
export function loadAnnotations(caseId: string): AnnotationDocument | null {
  const stored = localStorage.getItem(key(caseId))
  return stored === null ? null : parseExport(stored, caseId)
}
export function saveAnnotations(document: AnnotationDocument): void {
  parseExport(JSON.stringify(document), document.case_id)
  localStorage.setItem(key(document.case_id), JSON.stringify(document))
}
