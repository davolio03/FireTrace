import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react'
import type { ReactNode } from 'react'
import { useEffect, useRef } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import caseFixture from '../../contracts/fixtures/web/case.json'
import storyJson from './story/story.json'
import { mapStore } from './state/mapStore'
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
    sidebar,
  }: {
    dates?: { before: string; after: string }
    overlay?: ReactNode
    sidebar?: ReactNode
  }) => (
    <>
      <div role="region" aria-label="Map of Big Sur">
        {dates.before} / {dates.after}
        {overlay}
      </div>
      {sidebar}
    </>
  ),
}))

vi.mock('./features/map/CinematicMap', () => ({
  CinematicMap: () => <div data-testid="cinematic-map" />,
}))

let diveAutoCompletes = true

vi.mock('./features/map/LocationMap', () => ({
  LocationMap: ({
    bbox,
    diveToken,
    onDiveComplete,
  }: {
    bbox: number[]
    diveToken?: number
    onDiveComplete?: (camera: {
      center: [number, number]
      zoom: number
    }) => void
  }) => {
    const seen = useRef(diveToken ?? 0)
    useEffect(() => {
      if (!diveToken || diveToken === seen.current) return
      seen.current = diveToken
      if (!diveAutoCompletes) return
      onDiveComplete?.({ center: [-121.47, 35.92], zoom: 11 })
    }, [diveToken, onDiveComplete])
    return (
      <div role="region" aria-label="Location map">
        {bbox.join(',')}
      </div>
    )
  },
}))

describe('application scaffold', () => {
  afterEach(cleanup)
  it('shows the selected evidence after leaving the final story chapter', async () => {
    render(<App />)
    fireEvent.click(
      await screen.findByRole('button', { name: /watch the story/i }),
    )
    fireEvent.click(screen.getByLabelText('Go to step 7'))
    fireEvent.click(screen.getByText('Explore the evidence'))

    expect(mapStore.getState().panel).toBe('inspector')
    expect(
      screen.getByRole('heading', { name: 'Evidence Inspector' }),
    ).toBeTruthy()
  })
  it('shows the selected evidence after leaving the final chapter with Escape', async () => {
    render(<App />)
    fireEvent.click(
      await screen.findByRole('button', { name: /watch the story/i }),
    )
    fireEvent.click(screen.getByLabelText('Go to step 7'))
    fireEvent.keyDown(document.body, { key: 'Escape' })
    expect(mapStore.getState().panel).toBe('inspector')
    expect(
      screen.getByRole('heading', { name: 'Evidence Inspector' }),
    ).toBeTruthy()
  })
  it('enters the analysis even when the globe never reports the descent', async () => {
    diveAutoCompletes = false
    try {
      render(<App />)
      fireEvent.click(
        await screen.findByRole('button', { name: /explore analysis/i }),
      )
      expect(
        await screen.findByRole(
          'region',
          { name: /map of big sur/i },
          { timeout: 4000 },
        ),
      ).toBeTruthy()
    } finally {
      diveAutoCompletes = true
    }
  })
  it('exposes the analysis as an instrument rail with one floating panel', async () => {
    render(<App />)
    fireEvent.click(
      await screen.findByRole('button', { name: /explore analysis/i }),
    )
    const rail = screen.getByRole('navigation', { name: /analysis tools/i })
    expect(rail).toBeTruthy()
    const inspect = screen.getByRole('button', { name: 'Inspect' })
    fireEvent.click(inspect)
    expect(inspect.getAttribute('aria-pressed')).toBe('true')
    expect(screen.getByRole('region', { name: /map of big sur/i })).toBeTruthy()
    expect(screen.getByLabelText(/inspect panel/i)).toBeTruthy()
    // Number keys switch instruments.
    fireEvent.keyDown(document.body, { key: '3' })
    expect(
      screen
        .getByRole('button', { name: 'Transect' })
        .getAttribute('aria-pressed'),
    ).toBe('true')
  })
  it('keeps the MOCK notice visible in the analysis HUD', async () => {
    render(<App />)
    fireEvent.click(
      await screen.findByRole('button', { name: /explore analysis/i }),
    )
    expect(
      screen.getByText(/MOCK DATA - NOT SCIENTIFIC VALIDATION/i),
    ).toBeTruthy()
  })
  it('organizes analysis tools beside the map and preserves form state across panels', async () => {
    render(<App />)
    await screen.findByText(caseFixture.fire_start)
    fireEvent.click(screen.getByRole('button', { name: /explore analysis/i }))
    expect(
      screen.getByRole('navigation', { name: /analysis tools/i }),
    ).toBeTruthy()
    const annotations = screen.getByRole('button', { name: 'Annotations' })
    fireEvent.click(annotations)
    expect(annotations.getAttribute('aria-pressed')).toBe('true')
    fireEvent.change(screen.getByLabelText('Author'), {
      target: { value: 'Analyst' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Layers' }))
    fireEvent.click(annotations)
    expect((screen.getByLabelText('Author') as HTMLInputElement).value).toBe(
      'Analyst',
    )
    expect(screen.getByRole('region', { name: /map of big sur/i })).toBeTruthy()
  })
  it('keeps the active map tool and selection visible while another panel is open', async () => {
    render(<App />)
    await screen.findByText(caseFixture.fire_start)
    fireEvent.click(screen.getByRole('button', { name: /explore analysis/i }))
    act(() => {
      mapStore.getState().setTool('inspect')
      mapStore.getState().select({ type: 'point', point: [-121.4, 35.9] })
    })
    expect(screen.getByText('Inspect mode')).toBeTruthy()
    expect(screen.getByText('Point selected')).toBeTruthy()
    act(() => {
      mapStore.getState().setTool('pan')
      mapStore.getState().select({ type: 'none' })
    })
  })
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
    fireEvent.click(screen.getByRole('button', { name: /overview/i }))
    expect(
      screen.getByRole('button', { name: /explore analysis/i }),
    ).toBeTruthy()
  })

  it('plays the story full screen and leaves it with Esc', async () => {
    render(<App />)
    const watch = await screen.findByRole('button', {
      name: /watch the story \(2 min\)/i,
    })
    fireEvent.click(watch)
    const caption = screen.getByRole('region', { name: /guided story/i })
    expect(caption.textContent).toContain(storyJson.steps[0].title)
    expect(screen.getByTestId('cinematic-map')).toBeTruthy()
    expect(screen.queryByRole('region', { name: /map of big sur/i })).toBeNull()
    expect(screen.getByText(/MOCK data/)).toBeTruthy()
    fireEvent.keyDown(document.body, { key: 'Escape' })
    expect(screen.queryByTestId('cinematic-map')).toBeNull()
    expect(screen.getByRole('region', { name: /map of big sur/i })).toBeTruthy()
    const camera = mapStore.getState().camera
    expect(camera.pitch).toBe(0)
    expect(camera.zoom).toBeGreaterThanOrEqual(10)
    // Left mid-way: one button, to resume (no separate "Play story").
    expect(screen.queryByRole('button', { name: /^play story$/i })).toBeNull()
    fireEvent.click(
      screen.getByRole('button', { name: /resume story · 1\/7/i }),
    )
    expect(screen.getByTestId('cinematic-map')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: /close the story/i }))
    expect(screen.getByRole('region', { name: /map of big sur/i })).toBeTruthy()
    // Finished through the final call to action: nothing left to resume.
    fireEvent.click(
      screen.getByRole('button', { name: /resume story · 1\/7/i }),
    )
    fireEvent.click(screen.getByLabelText('Go to step 7'))
    fireEvent.click(screen.getByText('Explore the evidence'))
    expect(screen.queryByRole('button', { name: /resume story/i })).toBeNull()
    expect(screen.getByRole('button', { name: /^play story$/i })).toBeTruthy()
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
