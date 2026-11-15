import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import weather from '../../../../contracts/fixtures/web/weather.json'
import { WeatherPanel } from './WeatherPanel'

function show() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  render(
    <QueryClientProvider client={client}>
      <WeatherPanel dates={{ before: '2026-08-16', after: '2026-10-03' }} />
    </QueryClientProvider>,
  )
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('rainfall context', () => {
  it('shows source, aggregation, units, observation dates and mock notice', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: true, json: async () => weather }),
    )
    show()
    expect(await screen.findByText(/AOI mean \(mock\)/)).toBeTruthy()
    expect(screen.getAllByText(/mm\/day/).length).toBeGreaterThan(0)
    expect(screen.getByText(/MOCK.*synthetic/i)).toBeTruthy()
    expect(screen.getAllByText(/2026-08-16.*before/i).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/2026-10-03.*after/i).length).toBeGreaterThan(0)
    expect(screen.getByText(/NASA GPM IMERG/)).toBeTruthy()
  })

  it('distinguishes missing data from zero', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          ...weather,
          daily: [
            { date: '2026-08-16', value: null },
            { date: '2026-08-17', value: 0 },
          ],
        }),
      }),
    )
    show()
    expect(await screen.findByText('Not available')).toBeTruthy()
    expect(screen.getByText('0')).toBeTruthy()
  })

  it('reports missing and incomplete data', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false }))
    show()
    expect(await screen.findByRole('alert')).toBeTruthy()
  })

  it('warns when a date is absent from the reported period', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ ...weather, daily: weather.daily.slice(1) }),
      }),
    )
    show()
    expect(await screen.findByText(/some days are missing/i)).toBeTruthy()
  })

  it('rejects a weather variable other than precipitation', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ ...weather, variable: 'temperature' }),
      }),
    )
    show()
    expect(await screen.findByRole('alert')).toBeTruthy()
    expect(screen.queryByRole('table')).toBeNull()
  })
})
