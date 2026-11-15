import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
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
import inside from '../../../../contracts/fixtures/api/inspect-point-inside.json'
import invalid from '../../../../contracts/fixtures/api/inspect-point-invalid.json'
import caseData from '../../../../contracts/fixtures/web/case.json'
import { mapStore } from '../../state/mapStore'
import { Inspector } from './Inspector'

function renderInspector(
  data: ComponentProps<
    typeof Inspector
  >['caseData'] = caseData as unknown as ComponentProps<
    typeof Inspector
  >['caseData'],
) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <Inspector caseData={data} />
    </QueryClientProvider>,
  )
}

describe('point inspector', () => {
  beforeEach(() =>
    mapStore.setState({
      selection: { type: 'none' },
      panel: 'none',
      tool: 'pan',
    }),
  )
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('shows point evidence, mock notice, method and cautions', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: true, json: async () => inside }),
    )
    renderInspector()
    act(() =>
      mapStore.getState().select({ type: 'point', point: [-121.38, 35.96] }),
    )
    expect(await screen.findByText('-11.61')).toBeTruthy()
    expect(screen.getByText('95.4')).toBeTruthy()
    expect(screen.getByText(/MOCK — synthetic evidence/i)).toBeTruthy()
    expect(screen.getByText(/not confirmed burned area/i)).toBeTruthy()
    expect(screen.getByText(/Absolute log-ratio change, HH \+ HV/)).toBeTruthy()
    expect(screen.getByText(/Soil moisture change between dates/)).toBeTruthy()
  })

  it('distinguishes invalid and outside pixels and never fabricates values', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValueOnce({ ok: true, json: async () => invalid })
        .mockResolvedValueOnce({
          ok: true,
          json: async () => ({ ...invalid, pixel: null }),
        }),
    )
    renderInspector()
    act(() =>
      mapStore.getState().select({ type: 'point', point: [-121.45, 35.89] }),
    )
    expect(await screen.findByText(/no valid radar data/i)).toBeTruthy()
    expect(screen.getByText(/masked in one or more/i)).toBeTruthy()
    act(() =>
      mapStore.getState().select({ type: 'point', point: [-120, 35.89] }),
    )
    expect(await screen.findByText(/outside the analysis area/i)).toBeTruthy()
  })

  it('does not associate real case metadata with mock evidence', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: true, json: async () => inside }),
    )
    const realCase = {
      ...caseData,
      data_status: 'real',
      method: { ...caseData.method, name: 'REAL CASE METHOD' },
      sources: [{ label: 'REAL CASE SOURCE', url: 'https://example.org' }],
    }
    renderInspector(
      realCase as unknown as ComponentProps<typeof Inspector>['caseData'],
    )
    act(() =>
      mapStore.getState().select({ type: 'point', point: [-121.38, 35.96] }),
    )
    expect(await screen.findByText(/MOCK — synthetic evidence/)).toBeTruthy()
    expect(screen.queryByText(/REAL CASE METHOD/)).toBeNull()
    expect(screen.queryByText('REAL CASE SOURCE')).toBeNull()
  })

  it('hides evidence when the shared panel is closed', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: true, json: async () => inside }),
    )
    renderInspector()
    act(() =>
      mapStore.getState().select({ type: 'point', point: [-121.38, 35.96] }),
    )
    expect(await screen.findByText('-11.61')).toBeTruthy()
    act(() => mapStore.getState().setPanel('none'))
    expect(
      screen.queryByRole('region', { name: 'Evidence Inspector' }),
    ).toBeNull()
  })

  it('allows keyboard-accessible coordinate selection and reports request errors', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('network')))
    renderInspector()
    fireEvent.change(screen.getByLabelText('Longitude'), {
      target: { value: '-121.4' },
    })
    fireEvent.change(screen.getByLabelText('Latitude'), {
      target: { value: '35.9' },
    })
    fireEvent.click(
      screen.getByRole('button', { name: /inspect coordinates/i }),
    )
    await waitFor(() =>
      expect(screen.getByRole('alert').textContent).toMatch(/unable to load/i),
    )
    expect(mapStore.getState().selection).toEqual({
      type: 'point',
      point: [-121.4, 35.9],
    })
  })

  it('keeps the newest selection when requests resolve out of order', async () => {
    let resolveFirst!: (response: unknown) => void
    const first = new Promise((resolve) => {
      resolveFirst = resolve
    })
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockReturnValueOnce(first)
        .mockResolvedValueOnce({
          ok: true,
          json: async () => ({
            ...inside,
            hh_db: { ...inside.hh_db, t2: -42 },
          }),
        }),
    )
    renderInspector()
    act(() =>
      mapStore.getState().select({ type: 'point', point: [-121.4, 35.9] }),
    )
    act(() =>
      mapStore.getState().select({ type: 'point', point: [-121.3, 35.9] }),
    )
    expect(await screen.findByText('-42')).toBeTruthy()
    await act(async () => resolveFirst({ ok: true, json: async () => inside }))
    expect(screen.getByText('-42')).toBeTruthy()
    expect(screen.queryByText('-11.61')).toBeNull()
  })
})
