import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import profile from '../../../../contracts/fixtures/api/profile-example.json'
import { mapStore } from '../../state/mapStore'
import { ProfilePanel } from './ProfilePanel'

vi.mock('recharts', () => {
  const Component = ({ children }: { children?: React.ReactNode }) => (
    <div>{children}</div>
  )
  return {
    ResponsiveContainer: Component,
    LineChart: Component,
    Line: Component,
    XAxis: Component,
    YAxis: Component,
    CartesianGrid: Component,
    Legend: Component,
    Tooltip: Component,
    ReferenceLine: Component,
  }
})

function show() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  const onSample = vi.fn()
  render(
    <QueryClientProvider client={client}>
      <ProfilePanel onSample={onSample} />
    </QueryClientProvider>,
  )
  return { onSample }
}

beforeEach(() =>
  mapStore.setState({
    selection: { type: 'none' },
    panel: 'none',
    tool: 'pan',
    visible: ['perimeter'],
    compare: null,
  }),
)
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('transect profile', () => {
  it('requires two vertices, requests the selected line and preserves layers', async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue({ ok: true, json: async () => profile })
    vi.stubGlobal('fetch', fetcher)
    show()
    fireEvent.click(screen.getByRole('button', { name: /draw transect/i }))
    expect(mapStore.getState().tool).toBe('draw-profile')
    expect(
      screen.getByRole('button', { name: /finish transect/i }),
    ).toHaveProperty('disabled', true)
    act(() =>
      mapStore.getState().select({
        type: 'profile',
        line: [
          [-121.34, 35.97],
          [-121.35, 35.93],
        ],
      }),
    )
    fireEvent.click(screen.getByRole('button', { name: /finish transect/i }))
    expect(await screen.findByText(/MOCK.*synthetic/i)).toBeTruthy()
    expect(fetcher).toHaveBeenCalledWith(
      expect.stringMatching(/\/api\/inspect\/profile$/),
      expect.objectContaining({
        method: 'POST',
        body: expect.stringContaining('-121.34'),
      }),
    )
    expect(mapStore.getState().visible).toEqual(['perimeter'])
    expect(screen.getByText(/Perimeter crossings.*2518.6/)).toBeTruthy()
  })

  it('cancels drawing without requesting a profile', () => {
    const fetcher = vi.fn()
    vi.stubGlobal('fetch', fetcher)
    show()
    fireEvent.click(screen.getByRole('button', { name: /draw transect/i }))
    fireEvent.click(screen.getByRole('button', { name: /cancel/i }))
    expect(mapStore.getState().selection).toEqual({ type: 'none' })
    expect(mapStore.getState().tool).toBe('pan')
    expect(fetcher).not.toHaveBeenCalled()
  })

  it('identifies invalid values and truncated profiles with accessible sample selection', async () => {
    const samples = [
      {
        ...profile.samples[0],
        valid: false,
        hh_t1: null,
        hh_t2: null,
        hv_t1: null,
        hv_t2: null,
        change_index: null,
      },
    ]
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ ...profile, samples, truncated: true }),
      }),
    )
    const { onSample } = show()
    act(() =>
      mapStore.getState().select({
        type: 'profile',
        line: [
          [-121.34, 35.97],
          [-121.35, 35.93],
        ],
      }),
    )
    expect(await screen.findByText(/profile was truncated/i)).toBeTruthy()
    expect(screen.getAllByText('Not available').length).toBeGreaterThan(0)
    fireEvent.click(screen.getByRole('button', { name: /sample at 0/i }))
    expect(onSample).toHaveBeenCalledWith([samples[0].lon, samples[0].lat])
  })

  it('shows profile load errors', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')))
    show()
    act(() =>
      mapStore.getState().select({
        type: 'profile',
        line: [
          [-121.34, 35.97],
          [-121.35, 35.93],
        ],
      }),
    )
    expect(await screen.findByRole('alert')).toBeTruthy()
  })

  it('explains an empty profile and all-invalid samples', async () => {
    const invalidSample = { ...profile.samples[0], valid: false }
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValueOnce({
          ok: true,
          json: async () => ({ ...profile, samples: [] }),
        })
        .mockResolvedValueOnce({
          ok: true,
          json: async () => ({ ...profile, samples: [invalidSample] }),
        }),
    )
    show()
    act(() =>
      mapStore.getState().select({
        type: 'profile',
        line: [
          [-121.34, 35.97],
          [-121.35, 35.93],
        ],
      }),
    )
    expect(
      await screen.findByText(/No profile samples are available/i),
    ).toBeTruthy()
    act(() =>
      mapStore.getState().select({
        type: 'profile',
        line: [
          [-120, 35.97],
          [-120, 35.93],
        ],
      }),
    )
    expect(
      await screen.findByText(/outside the analysis area or masked/i),
    ).toBeTruthy()
    expect(screen.queryByText(String(invalidSample.hh_t1))).toBeNull()
  })

  it('does not replace the latest profile with an older response', async () => {
    let resolveOld!: (value: unknown) => void
    const oldRequest = new Promise((resolve) => {
      resolveOld = resolve
    })
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockReturnValueOnce(oldRequest)
        .mockResolvedValueOnce({
          ok: true,
          json: async () => ({ ...profile, length_m: 123 }),
        }),
    )
    show()
    act(() =>
      mapStore.getState().select({
        type: 'profile',
        line: [
          [-121.34, 35.97],
          [-121.35, 35.93],
        ],
      }),
    )
    act(() =>
      mapStore.getState().select({
        type: 'profile',
        line: [
          [-121.34, 35.97],
          [-121.36, 35.93],
        ],
      }),
    )
    expect(await screen.findByText(/Length: 123 m/)).toBeTruthy()
    await act(async () => resolveOld({ ok: true, json: async () => profile }))
    expect(screen.getByText(/Length: 123 m/)).toBeTruthy()
  })

  it.each([
    { ...profile, length_m: -1 },
    { ...profile, contract_version: undefined },
    { ...profile, samples: [{ ...profile.samples[0], lat: 100 }] },
  ])('rejects invalid profile responses', async (response) => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: true, json: async () => response }),
    )
    show()
    act(() =>
      mapStore.getState().select({
        type: 'profile',
        line: [
          [-121.34, 35.97],
          [-121.35, 35.93],
        ],
      }),
    )
    expect(await screen.findByRole('alert')).toBeTruthy()
  })
})
