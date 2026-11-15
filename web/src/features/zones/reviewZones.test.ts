import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
const fixture = readFileSync(
  '../contracts/fixtures/web/review_zones.geojson',
  'utf8',
)
import {
  cameraForBbox,
  groupZones,
  isReviewZones,
  type ReviewZones,
} from './reviewZones'

const data: unknown = JSON.parse(fixture)

function valid(): ReviewZones {
  if (!isReviewZones(data)) throw new Error('fixture must satisfy the guard')
  return structuredClone(data)
}

describe('review zones guard', () => {
  it('accepts the contract fixture', () => {
    expect(isReviewZones(data)).toBe(true)
  })

  it('rejects a bad data_status, wrong version and non-objects', () => {
    expect(isReviewZones({ ...valid(), data_status: 'fake' })).toBe(false)
    expect(isReviewZones({ ...valid(), contract_version: '1.1.0' })).toBe(false)
    expect(isReviewZones(null)).toBe(false)
    expect(isReviewZones('x')).toBe(false)
  })

  it('rejects zones with missing or malformed properties', () => {
    const missing = valid()
    delete (
      missing.features[0].properties as Partial<object> & {
        hh_db?: unknown
      }
    ).hh_db
    expect(isReviewZones(missing)).toBe(false)
    const badKind = valid()
    ;(badKind.features[0].properties as { kind: string }).kind = 'burned'
    expect(isReviewZones(badKind)).toBe(false)
    const noMethod = { ...valid(), method: { min_area_ha: 'x' } }
    expect(isReviewZones(noMethod)).toBe(false)
  })
})

describe('groupZones', () => {
  it('orders groups CO, NI, CI and sorts by rank then area', () => {
    const groups = groupZones(valid())
    expect(groups.map((g) => g.kind)).toEqual([
      'change_outside_perimeter',
      'no_change_inside_perimeter',
      'change_inside_perimeter',
    ])
    expect(groups[1].zones.map((z) => z.properties.zone_id)).toEqual([
      'NI-01',
      'NI-02',
      'NI-03',
      'NI-04',
      'NI-05',
      'NI-06',
    ])
  })

  it('keeps empty groups', () => {
    const collection = valid()
    collection.features = collection.features.filter(
      (f) => f.properties.kind !== 'no_change_inside_perimeter',
    )
    const groups = groupZones(collection)
    expect(groups).toHaveLength(3)
    expect(groups[1].zones).toEqual([])
  })

  it('breaks equal ranks by larger area first', () => {
    const collection = valid()
    const [a, b] = collection.features.filter(
      (f) => f.properties.kind === 'change_inside_perimeter',
    )
    a.properties.rank = 1
    b.properties.rank = 1
    a.properties.area_ha = 10
    b.properties.area_ha = 20
    const ci = groupZones(collection)[2].zones
    expect(ci[0].properties.zone_id).toBe(b.properties.zone_id)
    expect(ci[1].properties.zone_id).toBe(a.properties.zone_id)
  })
})

describe('cameraForBbox', () => {
  it('centres on the bbox and zooms in on smaller boxes', () => {
    const small = cameraForBbox([-121.5, 35.8, -121.4, 35.9])
    expect(small.center[0]).toBeCloseTo(-121.45)
    expect(small.center[1]).toBeCloseTo(35.85)
    const large = cameraForBbox([-122, 35, -121, 36])
    expect(small.zoom).toBeGreaterThan(large.zoom)
    expect(Number.isFinite(cameraForBbox([1, 1, 1, 1]).zoom)).toBe(true)
  })
})
