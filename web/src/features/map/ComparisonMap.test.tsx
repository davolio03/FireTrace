import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import manifest from '../../../../contracts/fixtures/web/layers.json'
import type { components } from '../../generated/api'
import { mapStore } from '../../state/mapStore'
import { CaseMap } from './CaseMap'
import { isSupportedComparison } from './comparison'
import { visibleMapLayers } from './layers'

const mocks = vi.hoisted(() => {
  type Handler = (...args: unknown[]) => void
  const instances: Array<{
    events: Record<string, Handler>
    on: ReturnType<typeof vi.fn>
    off: ReturnType<typeof vi.fn>
    addSource: ReturnType<typeof vi.fn>
    addLayer: ReturnType<typeof vi.fn>
    setLayoutProperty: ReturnType<typeof vi.fn>
    setPaintProperty: ReturnType<typeof vi.fn>
    jumpTo: ReturnType<typeof vi.fn>
    remove: ReturnType<typeof vi.fn>
  }> = []
  return { instances }
})

vi.mock('maplibre-gl', () => ({
  setWorkerUrl: vi.fn(),
  NavigationControl: class {},
  Map: class {
    events: Record<string, (...args: unknown[]) => void> = {}
    on = vi.fn((event: string, callback: (...args: unknown[]) => void) => {
      this.events[event] = callback
    })
    off = vi.fn((event: string) => {
      delete this.events[event]
    })
    addControl = vi.fn()
    addSource = vi.fn()
    addLayer = vi.fn()
    getLayer = vi.fn(() => true)
    setLayoutProperty = vi.fn()
    setPaintProperty = vi.fn()
    fitBounds = vi.fn()
    getCenter = vi.fn(() => ({ lng: -121.4, lat: 35.9 }))
    getZoom = vi.fn(() => 11)
    getBearing = vi.fn(() => 0)
    getPitch = vi.fn(() => 0)
    getRoll = vi.fn(() => 0)
    getPadding = vi.fn(() => ({ top: 12, bottom: 13, left: 14, right: 15 }))
    jumpTo = vi.fn()
    remove = vi.fn()
    constructor(options: { container: HTMLElement }) {
      options.container.classList.add('maplibregl-map')
      mocks.instances.push(this)
    }
  },
}))

const layers = manifest.layers as components['schemas']['layer'][]

describe('synchronized map comparison', () => {
  beforeEach(() => {
    mocks.instances.length = 0
    mapStore.setState({
      compare: null,
      visible: ['perimeter', 'change_index'],
      opacity: {},
    })
  })
  afterEach(cleanup)

  it('uses one synchronized viewport and restores prior layer selection after comparison', () => {
    render(
      <CaseMap
        layers={layers}
        dates={{ before: '2026-08-16', after: '2026-10-03' }}
      />,
    )
    const primary = mocks.instances[0]
    act(() => primary.events.load())
    fireEvent.click(
      screen.getByRole('button', { name: /compare before and after/i }),
    )
    expect(mocks.instances).toHaveLength(2)
    const overlay = mocks.instances[1]
    act(() => overlay.events.load())
    expect(primary.setLayoutProperty).toHaveBeenCalledWith(
      'firetrace-sar_t1_hh',
      'visibility',
      'visible',
    )
    expect(primary.setLayoutProperty).toHaveBeenCalledWith(
      'firetrace-change_index',
      'visibility',
      'none',
    )
    expect(overlay.setLayoutProperty).toHaveBeenCalledWith(
      'firetrace-sar_t2_hh',
      'visibility',
      'visible',
    )
    expect(overlay.setLayoutProperty).toHaveBeenCalledWith(
      'firetrace-perimeter',
      'visibility',
      'visible',
    )
    act(() => primary.events.move())
    expect(overlay.jumpTo).toHaveBeenCalledWith(
      expect.objectContaining({
        center: [-121.4, 35.9],
        zoom: 11,
        roll: 0,
        padding: { top: 12, bottom: 13, left: 14, right: 15 },
      }),
    )
    fireEvent.click(screen.getByRole('button', { name: /exit comparison/i }))
    expect(overlay.remove).toHaveBeenCalledOnce()
    expect(mapStore.getState().visible).toEqual(['perimeter', 'change_index'])
    expect(primary.setLayoutProperty).toHaveBeenCalledWith(
      'firetrace-change_index',
      'visibility',
      'visible',
    )
  })

  it('clips the right map at both divider endpoints', () => {
    render(
      <CaseMap
        layers={layers}
        dates={{ before: '2026-08-16', after: '2026-10-03' }}
      />,
    )
    fireEvent.click(
      screen.getByRole('button', { name: /compare before and after/i }),
    )
    const slider = screen.getByRole('slider', { name: /comparison divider/i })
    const right = screen.getByTestId('comparison-right-map')
    fireEvent.change(slider, { target: { value: '0' } })
    expect(right.style.clipPath).toMatch(/0%\)$/)
    fireEvent.change(slider, { target: { value: '100' } })
    expect(right.style.clipPath).toMatch(/100%\)$/)
  })

  it('keeps the comparison map anchored when MapLibre adds its own map class', () => {
    render(
      <CaseMap
        layers={layers}
        dates={{ before: '2026-08-16', after: '2026-10-03' }}
      />,
    )
    fireEvent.click(
      screen.getByRole('button', { name: /compare before and after/i }),
    )
    const right = screen.getByTestId('comparison-right-map')
    expect(right.classList.contains('maplibregl-map')).toBe(true)
    expect(right.style.position).toBe('absolute')
    expect(right.style.inset).toBe('0px')
  })

  it('applies the latest polarization when the overlay loads late', () => {
    render(<CaseMap layers={layers} />)
    const primary = mocks.instances[0]
    act(() => primary.events.load())
    fireEvent.click(
      screen.getByRole('button', { name: /compare before and after/i }),
    )
    const overlay = mocks.instances[1]
    fireEvent.click(screen.getByRole('radio', { name: 'HV' }))
    act(() => overlay.events.load())
    expect(overlay.setLayoutProperty).toHaveBeenCalledWith(
      'firetrace-sar_t2_hv',
      'visibility',
      'visible',
    )
    expect(overlay.setLayoutProperty).toHaveBeenCalledWith(
      'firetrace-sar_t2_hh',
      'visibility',
      'none',
    )
  })

  it('initializes comparison when shared state was set before the map mounts', () => {
    mapStore.setState({
      compare: { left: 'sar_t1_hh', right: 'sar_t2_hh', position: 0.5 },
    })
    render(
      <CaseMap
        layers={layers}
        dates={{ before: '2026-08-16', after: '2026-10-03' }}
      />,
    )
    expect(mocks.instances).toHaveLength(2)
    expect(screen.getByTestId('comparison-right-map')).toBeTruthy()
  })

  it('reports errors from the comparison map', () => {
    render(
      <CaseMap
        layers={layers}
        dates={{ before: '2026-08-16', after: '2026-10-03' }}
      />,
    )
    fireEvent.click(
      screen.getByRole('button', { name: /compare before and after/i }),
    )
    const overlay = mocks.instances[1]
    act(() =>
      overlay.events.error({ error: new Error('missing comparison image') }),
    )
    expect(screen.getByRole('alert').textContent).toMatch(/could not load/i)
  })

  it('keeps the perimeter independently controllable on both maps', () => {
    render(
      <CaseMap
        layers={layers}
        dates={{ before: '2026-08-16', after: '2026-10-03' }}
      />,
    )
    const primary = mocks.instances[0]
    act(() => primary.events.load())
    fireEvent.click(
      screen.getByRole('button', { name: /compare before and after/i }),
    )
    const overlay = mocks.instances[1]
    act(() => overlay.events.load())
    fireEvent.click(
      screen.getByRole('checkbox', { name: 'Official fire perimeter' }),
    )
    expect(primary.setLayoutProperty).toHaveBeenCalledWith(
      'firetrace-perimeter',
      'visibility',
      'none',
    )
    expect(overlay.setLayoutProperty).toHaveBeenCalledWith(
      'firetrace-perimeter',
      'visibility',
      'none',
    )
  })

  it('does not hide normal layers or mislabel an unsupported shared comparison', () => {
    mapStore.setState({
      compare: { left: 'optical_during', right: 'sar_t2_hv', position: 0.5 },
    })
    render(
      <CaseMap
        layers={layers}
        dates={{ before: '2026-08-16', after: '2026-10-03' }}
      />,
    )
    const primary = mocks.instances[0]
    act(() => primary.events.load())
    expect(mocks.instances).toHaveLength(1)
    expect(primary.setLayoutProperty).toHaveBeenCalledWith(
      'firetrace-change_index',
      'visibility',
      'visible',
    )
    expect(screen.getByRole('alert').textContent).toMatch(/only.*HH.*HV/i)
    expect(screen.queryByText(/before.*2026-08-16.*HH/i)).toBeNull()
  })

  it('renders every comparison source accepted from the manifest', () => {
    const altered = layers.map((layer) =>
      layer.id === 'sar_t2_hh'
        ? { ...layer, group: 'reference' as const }
        : layer,
    )
    const compare = {
      left: 'sar_t1_hh' as const,
      right: 'sar_t2_hh' as const,
      position: 0.5,
    }
    expect(isSupportedComparison(compare, altered)).toBe(true)
    expect(
      visibleMapLayers(altered).some((layer) => layer.id === compare.right),
    ).toBe(true)
    render(<CaseMap layers={altered} />)
    fireEvent.click(
      screen.getByRole('button', { name: /compare before and after/i }),
    )
    const overlay = mocks.instances[1]
    act(() => overlay.events.load())
    expect(overlay.addSource).toHaveBeenCalledWith(
      'firetrace-sar_t2_hh',
      expect.objectContaining({ type: 'image' }),
    )
  })
})
