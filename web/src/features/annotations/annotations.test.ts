import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  createAnnotation,
  parseExport,
  saveAnnotations,
  loadAnnotations,
} from './annotations'

const context = {
  case_id: 'plaskett-2026',
  data_status: 'mock' as const,
  method_id: 'method',
}
const evidence = {
  change_index: 2.5,
  hh_delta_db: -1,
  hv_delta_db: null,
  perimeter_relation: 'inside' as const,
}

describe('annotation persistence and import', () => {
  beforeEach(() => localStorage.clear())
  it('preserves analyst judgement, geometry and evidence through storage and export', () => {
    const feature = createAnnotation({
      selection: { type: 'point', point: [-121.4, 35.9] },
      author: 'Analyst',
      note: 'Check field',
      verdict: 'needs_field_check',
      evidence,
    })
    const doc = {
      type: 'FeatureCollection' as const,
      contract_version: '1.2.0' as const,
      ...context,
      exported_at: '2026-11-15T00:00:00Z',
      features: [feature],
    }
    saveAnnotations(doc)
    expect(loadAnnotations(context.case_id)).toEqual(doc)
    expect(parseExport(JSON.stringify(doc), context.case_id)).toEqual(doc)
  })
  it('rejects invalid, incompatible or unsafe imports without touching saved data', () => {
    localStorage.setItem('firetrace.annotations.plaskett-2026', 'original')
    expect(() =>
      parseExport('{"type":"FeatureCollection"}', context.case_id),
    ).toThrow()
    expect(() => parseExport('not JSON', context.case_id)).toThrow()
    expect(localStorage.getItem('firetrace.annotations.plaskett-2026')).toBe(
      'original',
    )
  })
  it('rejects timestamps that are not valid RFC 3339 date-times', () => {
    const doc = {
      type: 'FeatureCollection',
      contract_version: '1.2.0',
      ...context,
      exported_at: '2026-02-30T12:00:00Z',
      features: [],
    }
    expect(() => parseExport(JSON.stringify(doc), context.case_id)).toThrow()
    doc.exported_at = '2026-11-15T12:00:00'
    expect(() => parseExport(JSON.stringify(doc), context.case_id)).toThrow()
  })
  it('rejects array-valued enums without changing stored bytes', () => {
    const feature = createAnnotation({
      selection: { type: 'point', point: [-121, 35] },
      author: 'a',
      note: 'x',
      verdict: 'doubtful',
      evidence,
    })
    const doc = {
      type: 'FeatureCollection',
      contract_version: '1.2.0',
      ...context,
      exported_at: '2026-11-15T00:00:00Z',
      features: [
        {
          ...feature,
          properties: {
            ...feature.properties,
            target: { type: ['point'] },
            evidence: { ...evidence, perimeter_relation: ['inside'] },
          },
        },
      ],
    }
    const key = 'firetrace.annotations.plaskett-2026'
    localStorage.setItem(key, 'original')
    expect(() => parseExport(JSON.stringify(doc), doc.case_id)).toThrow()
    expect(localStorage.getItem(key)).toBe('original')
    doc.features[0].properties.evidence.perimeter_relation =
      'inside' as unknown as string[]
    expect(() => parseExport(JSON.stringify(doc), doc.case_id)).toThrow()
    doc.features[0].properties.target.type = 'point' as unknown as string[]
    doc.features[0].properties.evidence.perimeter_relation = ['inside']
    expect(() => parseExport(JSON.stringify(doc), doc.case_id)).toThrow()
  })
  it('accepts a schema-valid 1500-character Unicode note', () => {
    const feature = createAnnotation({
      selection: { type: 'point', point: [-121, 35] },
      author: 'a',
      note: '',
      verdict: 'doubtful',
      evidence,
    })
    feature.properties.note = '🔥'.repeat(1500)
    const doc = {
      type: 'FeatureCollection',
      contract_version: '1.2.0',
      ...context,
      exported_at: '2026-11-15T00:00:00Z',
      features: [feature],
    }
    expect(() => parseExport(JSON.stringify(doc), doc.case_id)).not.toThrow()
  })
  it('propagates storage failures without reporting success', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementationOnce(() => {
      throw new Error('quota')
    })
    expect(() =>
      saveAnnotations({
        type: 'FeatureCollection',
        contract_version: '1.2.0',
        ...context,
        exported_at: '2026-11-15T00:00:00Z',
        features: [],
      }),
    ).toThrow()
  })
})
