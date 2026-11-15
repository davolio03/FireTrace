import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import caseFixture from '../../contracts/fixtures/web/case.json'
import storyJson from './story/story.json'
import App from './App'

vi.mock('./data/caseData', () => ({
  loadCaseData: vi.fn(async () => ({
    case: caseFixture,
    stats: { data_status: 'mock' },
    layers: { data_status: 'mock', layers: [] },
  })),
}))

vi.mock('./features/map/CaseMap', () => ({
  CaseMap: ({
    dates = { before: '', after: '' },
    overlay = null,
  }: {
    dates?: { before: string; after: string }
    overlay?: ReactNode
  }) => (
    <div role="region" aria-label="Map of Big Sur">
      {dates.before} / {dates.after}
      {overlay}
    </div>
  ),
}))

vi.mock('./features/map/LocationMap', () => ({
  LocationMap: ({ bbox }: { bbox: number[] }) => (
    <div role="region" aria-label="Location map">
      {bbox.join(',')}
    </div>
  ),
}))

describe('application scaffold', () => {
  afterEach(cleanup)
  it('introduces the case, displays an accessible map and labels mock data', async () => {
    render(<App />)
    expect(
      screen.getByRole('heading', { name: /firetrace explorer/i }),
    ).toBeTruthy()
    expect(await screen.findByText(caseFixture.fire_start)).toBeTruthy()
    expect(screen.getByText(caseFixture.epochs.t1.datetime)).toBeTruthy()
    expect(screen.getByText(caseFixture.epochs.t2.datetime)).toBeTruthy()
    expect(screen.getByText(caseFixture.product)).toBeTruthy()
    expect(screen.getByText(/not confirmed burned area/i)).toBeTruthy()
    expect(screen.getByRole('region', { name: /location map/i })).toBeTruthy()
    expect(await screen.findByText(/MOCK.*synthetic/i)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: /explore analysis/i }))
    expect(screen.getByRole('region', { name: /map of big sur/i })).toBeTruthy()
    expect(await screen.findByText('2026-08-16 / 2026-10-03')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: /back to overview/i }))
    expect(
      screen.getByRole('button', { name: /explore analysis/i }),
    ).toBeTruthy()
  })

  it('starts the guided story from the overview and leaves it with Esc', async () => {
    render(<App />)
    const watch = await screen.findByRole('button', {
      name: /watch the story \(2 min\)/i,
    })
    fireEvent.click(watch)
    const card = screen.getByRole('region', { name: /guided story/i })
    expect(card.textContent).toContain(storyJson.steps[0].title)
    expect(card.textContent).toContain('MOCK data')
    expect(screen.queryByRole('button', { name: /play story/i })).toBeNull()
    fireEvent.keyDown(document.body, { key: 'Escape' })
    expect(screen.queryByRole('region', { name: /guided story/i })).toBeNull()
    expect(
      screen.getByRole('button', { name: /resume story · 1\/6/i }),
    ).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: /back to overview/i }))
  })

  it('hides the story when it was written for another case', async () => {
    const { loadCaseData } = await import('./data/caseData')
    vi.mocked(loadCaseData).mockResolvedValueOnce({
      case: { ...caseFixture, case_id: 'another-fire' },
      stats: { data_status: 'mock' },
      layers: { data_status: 'mock', layers: [] },
    } as unknown as Awaited<ReturnType<typeof loadCaseData>>)
    render(<App />)
    expect(await screen.findByText(caseFixture.fire_start)).toBeTruthy()
    expect(
      screen.queryByRole('button', { name: /watch the story/i }),
    ).toBeNull()
  })

  it('reports failure when the case manifest cannot be loaded', async () => {
    const { loadCaseData } = await import('./data/caseData')
    vi.mocked(loadCaseData).mockRejectedValueOnce(new Error('missing manifest'))
    render(<App />)
    await waitFor(() =>
      expect(screen.getByRole('alert').textContent).toMatch(/unable to load/i),
    )
  })

  it('keeps the MOCK notice and shows an error for a malformed layer', async () => {
    const { loadCaseData } = await import('./data/caseData')
    vi.mocked(loadCaseData).mockResolvedValueOnce({
      case: { data_status: 'mock' },
      stats: { data_status: 'mock' },
      layers: {
        data_status: 'mock',
        layers: [
          {
            id: 'sar_t1_hh',
            title: 'SAR',
            kind: 'raster',
            group: 'sar',
            default_visible: true,
            default_opacity: 1,
          },
        ],
      },
    } as unknown as Awaited<ReturnType<typeof loadCaseData>>)
    render(<App />)
    expect(await screen.findByRole('alert')).toBeTruthy()
    expect(screen.getByText(/MOCK.*synthetic/i)).toBeTruthy()
    expect(
      screen.getByRole('heading', { name: /firetrace explorer/i }),
    ).toBeTruthy()
  })

  it('keeps the MOCK notice and reports missing observation dates', async () => {
    const { loadCaseData } = await import('./data/caseData')
    vi.mocked(loadCaseData).mockResolvedValueOnce({
      case: { data_status: 'mock' },
      stats: { data_status: 'mock' },
      layers: { data_status: 'mock', layers: [] },
    } as unknown as Awaited<ReturnType<typeof loadCaseData>>)
    render(<App />)
    expect(await screen.findByRole('alert')).toBeTruthy()
    expect(screen.getByText(/MOCK.*synthetic/i)).toBeTruthy()
  })

  it('reports missing case fields without inventing values', async () => {
    const { loadCaseData } = await import('./data/caseData')
    vi.mocked(loadCaseData).mockResolvedValueOnce({
      case: { ...caseFixture, fire_start: undefined },
      stats: { data_status: 'mock' },
      layers: { data_status: 'mock', layers: [] },
    } as unknown as Awaited<ReturnType<typeof loadCaseData>>)
    render(<App />)
    expect(await screen.findByRole('alert')).toBeTruthy()
    expect(screen.queryByText(caseFixture.fire_start)).toBeNull()
    expect(screen.getByText(/MOCK.*synthetic/i)).toBeTruthy()
  })

  it('reports malformed sources without crashing the application', async () => {
    const { loadCaseData } = await import('./data/caseData')
    vi.mocked(loadCaseData).mockResolvedValueOnce({
      case: { ...caseFixture, sources: 'bad' },
      stats: { data_status: 'mock' },
      layers: { data_status: 'mock', layers: [] },
    } as unknown as Awaited<ReturnType<typeof loadCaseData>>)
    render(<App />)
    expect(await screen.findByRole('alert')).toBeTruthy()
    expect(screen.getByText(/MOCK.*synthetic/i)).toBeTruthy()
  })

  it('reports malformed source entries without rendering fabricated sources', async () => {
    const { loadCaseData } = await import('./data/caseData')
    vi.mocked(loadCaseData).mockResolvedValueOnce({
      case: { ...caseFixture, sources: [null, { label: 'Incomplete' }] },
      stats: { data_status: 'mock' },
      layers: { data_status: 'mock', layers: [] },
    } as unknown as Awaited<ReturnType<typeof loadCaseData>>)
    render(<App />)
    expect(await screen.findByRole('alert')).toBeTruthy()
    expect(screen.queryByText('Incomplete')).toBeNull()
  })
})
