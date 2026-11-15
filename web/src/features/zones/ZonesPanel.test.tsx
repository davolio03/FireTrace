import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from '@testing-library/react'
import { readFileSync } from 'node:fs'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
const fixture = readFileSync(
  '../contracts/fixtures/web/review_zones.geojson',
  'utf8',
)
import { mapStore } from '../../state/mapStore'
import { cameraForBbox } from './reviewZones'
import { ZonesPanel } from './ZonesPanel'

const data = JSON.parse(fixture) as {
  features: { properties: { kind: string; bbox: number[] } }[]
}

function show(body: unknown, ok = true) {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({ ok, json: async () => body }),
  )
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <ZonesPanel />
    </QueryClientProvider>,
  )
}

beforeEach(() =>
  mapStore.setState({
    selection: { type: 'none' },
    panel: 'none',
    camera: { center: [0, 0], zoom: 1 },
  }),
)
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('zones panel', () => {
  it('lists three groups in order with the MOCK notice and thresholds', async () => {
    show(data)
    expect(await screen.findByText('CO-01', { exact: false })).toBeTruthy()
    expect(
      screen.getAllByRole('heading', { level: 3 }).map((h) => h.textContent),
    ).toEqual([
      'Change outside the perimeter',
      'Discrepancies to investigate',
      'Agreement examples',
    ])
    const kinds = screen
      .getAllByRole('heading', { level: 4 })
      .map((h) => h.textContent ?? '')
    expect(kinds).toHaveLength(3)
    expect(kinds[0]).toMatch(/outside/i)
    expect(kinds[1]).toMatch(/little/i)
    expect(kinds[2]).toMatch(/^Observed radar change inside/i)
    const ids = screen
      .getAllByRole('button')
      .map((b) => b.textContent?.slice(0, 5))
    expect(ids[0]).toBe('CO-01')
    expect(ids[1]).toBe('NI-01')
    expect(ids.at(-1)).toBe('CI-06')
    expect(screen.getByText(/MOCK — synthetic zones/)).toBeTruthy()
    expect(screen.getByText(/2\.962/)).toBeTruthy()
  })

  it('shows the empty state with the data threshold and keeps the group', async () => {
    show({
      ...data,
      features: data.features.filter(
        (f) => f.properties.kind !== 'no_change_inside_perimeter',
      ),
    })
    const empty = await screen.findByText('No zones of this kind ≥ 15 ha')
    const section = empty.closest('section')!
    expect(
      within(section).getByRole('heading', { level: 4 }).textContent,
    ).toMatch(/little/i)
  })

  it('keeps the CO group with its empty state when no CO zones exist', async () => {
    show({
      ...data,
      features: data.features.filter(
        (f) => f.properties.kind !== 'change_outside_perimeter',
      ),
    })
    const empty = await screen.findByText('No zones of this kind ≥ 15 ha')
    const group = empty.closest('div')!
    expect(within(group).getByRole('heading', { level: 3 }).textContent).toBe(
      'Change outside the perimeter',
    )
    expect(
      within(empty.closest('section')!).getByRole('heading', { level: 4 })
        .textContent,
    ).toMatch(/outside/i)
  })

  it('selects a zone and flies to its bbox on click', async () => {
    show(data)
    fireEvent.click(await screen.findByRole('button', { name: /CO-01/ }))
    expect(mapStore.getState().selection).toEqual({
      type: 'zone',
      zoneId: 'CO-01',
    })
    expect(mapStore.getState().camera).toEqual(
      cameraForBbox(data.features[0].properties.bbox as never),
    )
    expect(
      screen
        .getByRole('button', { name: /CO-01/ })
        .getAttribute('aria-pressed'),
    ).toBe('true')
  })

  it('reports load errors and never uses burn wording', async () => {
    const { container } = show(data)
    await screen.findByText('CO-01', { exact: false })
    expect(container.textContent).not.toMatch(/burn|quemad/i)
    cleanup()
    show({ nope: 1 })
    expect((await screen.findByRole('alert')).textContent).toMatch(/unable/i)
  })
})
