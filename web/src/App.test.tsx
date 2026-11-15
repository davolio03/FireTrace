import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from './App'

vi.mock('./data/caseData', () => ({
  loadCaseData: vi.fn(async () => ({
    case: {
      data_status: 'mock',
      epochs: {
        t1: { datetime: '2026-08-16T02:56:39Z' },
        t2: { datetime: '2026-10-03T02:56:38Z' },
      },
    },
    stats: { data_status: 'mock' },
    layers: { data_status: 'mock', layers: [] },
  })),
}))

vi.mock('./features/map/CaseMap', () => ({
  CaseMap: ({ dates }: { dates: { before: string; after: string } }) => (
    <div role="region" aria-label="Map of Big Sur">
      {dates.before} / {dates.after}
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
    expect(screen.getByRole('region', { name: /map of big sur/i })).toBeTruthy()
    expect(await screen.findByText(/MOCK.*synthetic/i)).toBeTruthy()
    expect(await screen.findByText('2026-08-16 / 2026-10-03')).toBeTruthy()
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
})
