import { validGeometry } from './annotations'

type CaseIdentity = {
  case_id: string
  data_status: string
  method: { id: string }
}
type VerifiedZone = {
  id: string
  geometry: { type: 'Polygon' | 'MultiPolygon'; coordinates: unknown[] }
  properties: Record<string, unknown>
}
const record = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value)

export async function loadVerifiedZones(
  baseUrl: string,
  displayed: CaseIdentity,
  fetcher: typeof fetch = fetch,
) {
  const base = baseUrl.replace(/\/+$/, '')
  if (!globalThis.crypto?.subtle || !displayed.method?.id)
    throw new Error('Zone provenance unavailable')
  const read = async (name: string) => {
    const response = await fetcher(`${base}/${name}`)
    if (!response.ok) throw new Error('Zone provenance unavailable')
    return response.arrayBuffer()
  }
  const [manifestBytes, caseBytes, zoneBytes] = await Promise.all([
    read('export.json'),
    read('case.json'),
    read('review_zones.geojson'),
  ])
  const parse = (bytes: ArrayBuffer): unknown =>
    JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes))
  const manifest = parse(manifestBytes)
  if (
    !record(manifest) ||
    manifest.export_format_version !== 1 ||
    manifest.case_id !== displayed.case_id ||
    !record(manifest.outputs)
  )
    throw new Error('Invalid zone provenance manifest')
  const matches = async (name: string, bytes: ArrayBuffer) => {
    const expected = (manifest.outputs as Record<string, unknown>)[name]
    if (typeof expected !== 'string' || !/^[0-9a-f]{64}$/.test(expected))
      return false
    const digest = await crypto.subtle.digest('SHA-256', bytes)
    return (
      Array.from(new Uint8Array(digest), (b) =>
        b.toString(16).padStart(2, '0'),
      ).join('') === expected
    )
  }
  if (
    !(await matches('case.json', caseBytes)) ||
    !(await matches('review_zones.geojson', zoneBytes))
  )
    throw new Error('Zone provenance hash mismatch')
  const actualCase = parse(caseBytes)
  const collection = parse(zoneBytes)
  if (
    !record(actualCase) ||
    JSON.stringify(actualCase) !== JSON.stringify(displayed) ||
    actualCase.case_id !== displayed.case_id ||
    actualCase.data_status !== displayed.data_status ||
    !record(actualCase.method) ||
    actualCase.method.id !== displayed.method.id ||
    !record(collection) ||
    collection.type !== 'FeatureCollection' ||
    collection.data_status !== displayed.data_status ||
    !Array.isArray(collection.features)
  )
    throw new Error('Zone provenance does not match this case')
  const features: VerifiedZone[] = []
  const ids = new Set<string>()
  for (const feature of collection.features) {
    if (
      !record(feature) ||
      feature.type !== 'Feature' ||
      typeof feature.id !== 'string' ||
      !/^(CO|NI|CI)-[0-9]{2,}$/.test(feature.id) ||
      !record(feature.properties) ||
      feature.properties.zone_id !== feature.id ||
      ids.has(feature.id) ||
      !validGeometry(feature.geometry) ||
      (feature.geometry.type !== 'Polygon' &&
        feature.geometry.type !== 'MultiPolygon')
    )
      throw new Error('Invalid or ambiguous zone')
    ids.add(feature.id)
    features.push({
      id: feature.id,
      geometry: feature.geometry as VerifiedZone['geometry'],
      properties: feature.properties,
    })
  }
  return { features }
}
