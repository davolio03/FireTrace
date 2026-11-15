import { webcrypto } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { loadVerifiedZones } from './zoneProvenance'

const caseData = {
  case_id: 'case-1',
  data_status: 'real',
  method: { id: 'method-1' },
}
const zones = {
  type: 'FeatureCollection',
  data_status: 'real',
  features: [
    {
      type: 'Feature',
      id: 'CO-01',
      geometry: {
        type: 'Polygon',
        coordinates: [
          [
            [-121, 35],
            [-120, 35],
            [-120, 36],
            [-121, 35],
          ],
        ],
      },
      properties: { zone_id: 'CO-01' },
    },
  ],
}
const encoder = new TextEncoder()
async function digest(text: string) {
  const bytes = await webcrypto.subtle.digest('SHA-256', encoder.encode(text))
  return Array.from(new Uint8Array(bytes), (b) =>
    b.toString(16).padStart(2, '0'),
  ).join('')
}
async function responses(overrides: Record<string, string> = {}) {
  const caseText = JSON.stringify(caseData)
  const zoneText = JSON.stringify(zones)
  const manifest = JSON.stringify({
    export_format_version: 1,
    case_id: caseData.case_id,
    outputs: {
      'case.json': await digest(caseText),
      'review_zones.geojson': await digest(zoneText),
    },
  })
  const files: Record<string, string> = {
    'case.json': caseText,
    'review_zones.geojson': zoneText,
    'export.json': manifest,
    ...overrides,
  }
  return vi.fn(async (url: string | URL | Request) => {
    const key = String(url).split('/').pop()!
    return new Response(files[key], {
      status: files[key] === undefined ? 404 : 200,
    })
  })
}
afterEach(() => vi.unstubAllGlobals())

describe('verified zone provenance', () => {
  it('accepts the published mock fixture bundle', async () => {
    vi.stubGlobal('crypto', webcrypto)
    const folder = '../contracts/fixtures/web/'
    const mockCase = JSON.parse(readFileSync(folder + 'case.json', 'utf8'))
    const files: Record<string, string> = {}
    for (const name of ['case.json', 'review_zones.geojson', 'export.json'])
      files[name] = readFileSync(folder + name, 'utf8')
    const fetcher = vi.fn(
      async (url: string | URL | Request) =>
        new Response(files[String(url).split('/').pop()!], { status: 200 }),
    )
    expect(
      (await loadVerifiedZones('/', mockCase, fetcher)).features.length,
    ).toBeGreaterThan(0)
  })
  it('rejects invalid zone identifiers even when hashes match', async () => {
    vi.stubGlobal('crypto', webcrypto)
    const invalid = structuredClone(zones)
    invalid.features[0].id = ''
    invalid.features[0].properties.zone_id = ''
    const zoneText = JSON.stringify(invalid)
    const manifest = JSON.stringify({
      export_format_version: 1,
      case_id: caseData.case_id,
      outputs: {
        'case.json': await digest(JSON.stringify(caseData)),
        'review_zones.geojson': await digest(zoneText),
      },
    })
    await expect(
      loadVerifiedZones(
        '/',
        caseData,
        await responses({
          'review_zones.geojson': zoneText,
          'export.json': manifest,
        }),
      ),
    ).rejects.toThrow()
  })
  it('accepts matching exact bytes and identifies the selected geometry', async () => {
    vi.stubGlobal('crypto', webcrypto)
    const result = await loadVerifiedZones('/', caseData, await responses())
    expect(result.features[0].id).toBe('CO-01')
  })
  it('rejects modified zone bytes and mismatched displayed cases', async () => {
    vi.stubGlobal('crypto', webcrypto)
    await expect(
      loadVerifiedZones(
        '/',
        caseData,
        await responses({
          'review_zones.geojson': JSON.stringify({
            ...zones,
            data_status: 'mock',
          }),
        }),
      ),
    ).rejects.toThrow()
    await expect(
      loadVerifiedZones(
        '/',
        { ...caseData, method: { id: 'different' } },
        await responses(),
      ),
    ).rejects.toThrow()
    const differentCase = { ...caseData, name: 'A different displayed case' }
    await expect(
      loadVerifiedZones('/', differentCase, await responses()),
    ).rejects.toThrow()
  })
  it('rejects a missing manifest without relying on mock status', async () => {
    vi.stubGlobal('crypto', webcrypto)
    await expect(
      loadVerifiedZones('/', caseData, await responses({ 'export.json': '' })),
    ).rejects.toThrow()
  })
})
