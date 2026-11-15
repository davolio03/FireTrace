import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { webcrypto } from 'node:crypto'
import { readFileSync } from 'node:fs'
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ComponentProps } from 'react'
import caseFixture from '../../../../contracts/fixtures/web/case.json'
import pointFixture from '../../../../contracts/fixtures/api/inspect-point-inside.json'
import { mapStore } from '../../state/mapStore'
import { AnnotationPanel } from './AnnotationPanel'
import { loadAnnotations } from './annotations'

function show() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  client.setQueryData(['inspect-point', -121.4, 35.9], pointFixture)
  render(
    <QueryClientProvider client={client}>
      <AnnotationPanel
        caseData={
          caseFixture as unknown as ComponentProps<
            typeof AnnotationPanel
          >['caseData']
        }
        captureMap={() => 'data:image/png;base64,AAAA'}
        displayStatus="mock"
      />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  localStorage.clear()
  mapStore.setState({ selection: { type: 'none' }, panel: 'none' })
})
afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('analyst annotations', () => {
  it('saves the selected point and available evidence as analyst judgement', async () => {
    show()
    act(() =>
      mapStore.getState().select({ type: 'point', point: [-121.4, 35.9] }),
    )
    fireEvent.change(screen.getByLabelText('Author'), {
      target: { value: 'Analyst' },
    })
    fireEvent.change(screen.getByLabelText('Note'), {
      target: { value: 'Inspect this point' },
    })
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: /save annotation/i }),
      ).not.toHaveProperty('disabled', true),
    )
    fireEvent.click(screen.getByRole('button', { name: /save annotation/i }))
    const doc = loadAnnotations(caseFixture.case_id)
    expect(doc?.features[0].properties.evidence.hh_delta_db).toBe(
      pointFixture.hh_db.delta,
    )
    expect(doc?.features[0].geometry).toEqual({
      type: 'Point',
      coordinates: [-121.4, 35.9],
    })
    expect(screen.getByText(/analyst judgement/i)).toBeTruthy()
    expect(screen.getByText('Annotation saved locally.')).toBeTruthy()
  })

  it('does not save without a supported selection', async () => {
    show()
    fireEvent.change(screen.getByLabelText('Author'), {
      target: { value: 'Analyst' },
    })
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: /save annotation/i }),
      ).not.toHaveProperty('disabled', true),
    )
    fireEvent.click(screen.getByRole('button', { name: /save annotation/i }))
    expect(screen.getByRole('alert')).toBeTruthy()
    expect(loadAnnotations(caseFixture.case_id)).toBeNull()
  })

  it('clears the success notice when a later storage operation fails', async () => {
    show()
    act(() =>
      mapStore.getState().select({ type: 'point', point: [-121.4, 35.9] }),
    )
    fireEvent.change(screen.getByLabelText('Author'), {
      target: { value: 'Analyst' },
    })
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: /save annotation/i }),
      ).not.toHaveProperty('disabled', true),
    )
    fireEvent.click(screen.getByRole('button', { name: /save annotation/i }))
    const saved = loadAnnotations(caseFixture.case_id)
    expect(screen.getByText('Annotation saved locally.')).toBeTruthy()
    vi.spyOn(Storage.prototype, 'setItem').mockImplementationOnce(() => {
      throw new Error('Storage full')
    })
    fireEvent.click(screen.getByRole('button', { name: /save annotation/i }))
    expect(screen.queryByText('Annotation saved locally.')).toBeNull()
    expect(screen.getByRole('alert').textContent).toMatch(/storage full/i)
    expect(loadAnnotations(caseFixture.case_id)).toEqual(saved)
  })

  it('saves and shows a profile annotation without inventing aggregate evidence', async () => {
    show()
    act(() =>
      mapStore.getState().select({
        type: 'profile',
        line: [
          [-121.4, 35.9],
          [-121.3, 35.8],
        ],
      }),
    )
    fireEvent.change(screen.getByLabelText('Author'), {
      target: { value: 'Analyst' },
    })
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: /save annotation/i }),
      ).not.toHaveProperty('disabled', true),
    )
    fireEvent.click(screen.getByRole('button', { name: /save annotation/i }))
    expect(
      loadAnnotations(caseFixture.case_id)?.features[0].geometry.type,
    ).toBe('LineString')
    expect(
      loadAnnotations(caseFixture.case_id)?.features[0].properties.evidence
        .change_index,
    ).toBeNull()
    expect(screen.getByText(/target: profile/i)).toBeTruthy()
    expect(screen.getByText(/change index: unavailable/i)).toBeTruthy()
  })

  it('does not replace saved annotations until import is confirmed', async () => {
    show()
    act(() =>
      mapStore.getState().select({ type: 'point', point: [-121.4, 35.9] }),
    )
    fireEvent.change(screen.getByLabelText('Author'), {
      target: { value: 'Analyst' },
    })
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: /save annotation/i }),
      ).not.toHaveProperty('disabled', true),
    )
    fireEvent.click(screen.getByRole('button', { name: /save annotation/i }))
    const saved = loadAnnotations(caseFixture.case_id)!
    const imported = { ...saved, features: [] }
    const file = new File([], 'annotations.geojson', {
      type: 'application/geo+json',
    })
    Object.defineProperty(file, 'text', {
      value: async () => JSON.stringify(imported),
    })
    fireEvent.change(screen.getByLabelText(/import geojson/i), {
      target: { files: [file] },
    })
    await screen.findByRole('button', { name: /confirm replace annotations/i })
    expect(loadAnnotations(caseFixture.case_id)).toEqual(saved)
    fireEvent.click(
      screen.getByRole('button', { name: /confirm replace annotations/i }),
    )
    expect(loadAnnotations(caseFixture.case_id)).toEqual(imported)
    expect(screen.getByText('Annotations imported locally.')).toBeTruthy()
  })

  it('exports a report with a mock notice and the reference perimeter caution', async () => {
    let exported: Blob | undefined
    vi.stubGlobal('URL', {
      createObjectURL: (blob: Blob) => {
        exported = blob
        return 'blob:test'
      },
      revokeObjectURL: () => {},
    })
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    show()
    act(() =>
      mapStore.getState().select({ type: 'point', point: [-121.4, 35.9] }),
    )
    fireEvent.change(screen.getByLabelText('Author'), {
      target: { value: 'Analyst' },
    })
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: /save annotation/i }),
      ).not.toHaveProperty('disabled', true),
    )
    fireEvent.click(screen.getByRole('button', { name: /save annotation/i }))
    fireEvent.click(
      screen.getByRole('button', { name: /export markdown report/i }),
    )
    expect(exported).toBeDefined()
    const content = await new Promise<string>((resolve, reject) => {
      const reader = new FileReader()
      reader.onload = () => resolve(String(reader.result))
      reader.onerror = () => reject(reader.error)
      reader.readAsText(exported!)
    })
    expect(content).toContain('MOCK')
    expect(content).toContain('data:image/png;base64,AAAA')
    expect(content).toContain(caseFixture.reference.note)
    expect(content).toContain(caseFixture.reference.datetime)
  })

  it('refuses to save a zone when its case and method provenance cannot be verified', async () => {
    const zonesFixture = {
      features: [
        {
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
          properties: {
            kind: 'change_outside_perimeter',
            hh_db: { delta_median: 4.12 },
          },
        },
      ],
    }
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => zonesFixture,
    } as Response)
    show()
    act(() => mapStore.getState().select({ type: 'zone', zoneId: 'CO-01' }))
    fireEvent.change(screen.getByLabelText('Author'), {
      target: { value: 'Analyst' },
    })
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: /save annotation/i }),
      ).not.toHaveProperty('disabled', true),
    )
    fireEvent.click(screen.getByRole('button', { name: /save annotation/i }))
    expect(loadAnnotations(caseFixture.case_id)).toBeNull()
    expect(screen.getByText(/zone provenance cannot be verified/i)).toBeTruthy()
  })

  it('saves zone evidence only from a verified bundle', async () => {
    vi.stubGlobal('crypto', webcrypto)
    const zones = {
      type: 'FeatureCollection',
      data_status: 'mock',
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
          properties: {
            zone_id: 'CO-01',
            kind: 'change_outside_perimeter',
            hh_db: { delta_median: 4.12 },
            caveats: [
              { id: 'steep_slope', fraction: 0.12 },
              { id: 'near_perimeter_edge', fraction: 0 },
            ],
          },
        },
      ],
    }
    const bytes = {
      'case.json': JSON.stringify(caseFixture),
      'review_zones.geojson': JSON.stringify(zones),
    }
    const hash = async (text: string) =>
      Array.from(
        new Uint8Array(
          await webcrypto.subtle.digest(
            'SHA-256',
            new TextEncoder().encode(text),
          ),
        ),
        (b) => b.toString(16).padStart(2, '0'),
      ).join('')
    const files: Record<string, string> = {
      ...bytes,
      'export.json': JSON.stringify({
        export_format_version: 1,
        case_id: caseFixture.case_id,
        outputs: {
          'case.json': await hash(bytes['case.json']),
          'review_zones.geojson': await hash(bytes['review_zones.geojson']),
        },
      }),
    }
    vi.spyOn(globalThis, 'fetch').mockImplementation(
      async (url) =>
        new Response(files[String(url).split('/').pop()!], { status: 200 }),
    )
    show()
    const select = await screen.findByLabelText('Select a zone')
    fireEvent.change(select, { target: { value: 'CO-01' } })
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: /save annotation/i }),
      ).not.toHaveProperty('disabled', true),
    )
    fireEvent.change(screen.getByLabelText('Author'), {
      target: { value: 'Analyst' },
    })
    fireEvent.click(screen.getByRole('button', { name: /save annotation/i }))
    expect(
      loadAnnotations(caseFixture.case_id)?.features[0].properties.evidence
        .hh_delta_db,
    ).toBe(4.12)
    expect(
      loadAnnotations(caseFixture.case_id)?.features[0].properties.evidence
        .caveat_ids,
    ).toEqual(['steep_slope'])
  })
  it('saves a zone from the shipped mock fixtures', async () => {
    vi.stubGlobal('crypto', webcrypto)
    const files: Record<string, string> = {}
    for (const name of ['case.json', 'review_zones.geojson', 'export.json'])
      files[name] = readFileSync(`../contracts/fixtures/web/${name}`, 'utf8')
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      const value = files[String(url).split('/').pop()!]
      return new Response(value, { status: value ? 200 : 404 })
    })
    show()
    fireEvent.change(await screen.findByLabelText('Select a zone'), {
      target: { value: 'CO-01' },
    })
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: /save annotation/i }),
      ).not.toHaveProperty('disabled', true),
    )
    fireEvent.change(screen.getByLabelText('Author'), {
      target: { value: 'Analyst' },
    })
    fireEvent.click(screen.getByRole('button', { name: /save annotation/i }))
    const feature = loadAnnotations(caseFixture.case_id)?.features[0]
    expect(feature?.properties.target).toEqual({
      type: 'zone',
      zone_id: 'CO-01',
    })
    expect(feature?.properties.evidence.hh_delta_db).toBe(4.12)
  })
})
