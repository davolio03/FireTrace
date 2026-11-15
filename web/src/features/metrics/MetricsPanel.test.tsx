import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import stats from '../../../../contracts/fixtures/web/stats.json'
import { MetricsPanel } from './MetricsPanel'

function show() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <MetricsPanel />
    </QueryClientProvider>,
  )
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('results metrics', () => {
  it('shows provided coverage, both distributions and mock caveats without P1 widgets', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: true, json: async () => stats }),
    )
    show()
    expect(await screen.findByText('196517')).toBeTruthy()
    expect(screen.getByText('199200')).toBeTruthy()
    expect(screen.getByText('98.65%')).toBeTruthy()
    expect(
      within(
        screen.getByRole('region', { name: /inside official perimeter/i }),
      ).getByText('1.647'),
    ).toBeTruthy()
    expect(
      within(
        screen.getByRole('region', { name: /outside official perimeter/i }),
      ).getByText('-0.17'),
    ).toBeTruthy()
    expect(screen.getByText(/MOCK.*synthetic/i)).toBeTruthy()
    expect(screen.getByText(/not confirmed burned area/i)).toBeTruthy()
    expect(screen.getByText(/predates the after observation/i)).toBeTruthy()
    expect(screen.getByText(/change.index statistics/i)).toBeTruthy()
    expect(screen.queryByText(/highlighted area/i)).toBeNull()
  })

  it('reports load failure without inventing values', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')))
    show()
    expect(await screen.findByRole('alert')).toBeTruthy()
    expect(screen.queryByText('0%')).toBeNull()
  })

  it('reports incomplete metrics and does not turn missing values into zero', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ data_status: 'mock', valid_pixels: 0 }),
      }),
    )
    show()
    expect(await screen.findByRole('alert')).toBeTruthy()
    expect(screen.getByText(/MOCK.*synthetic/i)).toBeTruthy()
    expect(screen.queryByText('0%')).toBeNull()
  })

  it('reports absence of valid pixels without presenting distributions', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          ...stats,
          valid_pixels: 0,
          valid_coverage_pct: 0,
        }),
      }),
    )
    show()
    expect(await screen.findByText(/no valid pixels/i)).toBeTruthy()
    expect(screen.queryByText('1.647')).toBeNull()
  })

  it('rejects statistics with missing provenance instead of presenting them as real', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ ...stats, data_status: undefined }),
      }),
    )
    show()
    expect(await screen.findByRole('alert')).toBeTruthy()
    expect(screen.queryByText('196517')).toBeNull()
  })

  it.each([
    { ...stats, valid_pixels: 0, valid_coverage_pct: 98.65 },
    { ...stats, valid_pixels: 300000 },
  ])('rejects contradictory coverage values', async (data) => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: true, json: async () => data }),
    )
    show()
    expect(await screen.findByRole('alert')).toBeTruthy()
  })
})
