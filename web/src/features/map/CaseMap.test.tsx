import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import manifest from '../../../../contracts/fixtures/web/layers.json'
import type { components } from '../../generated/api'
import { initialCamera, mapStore } from '../../state/mapStore'
import { CaseMap } from './CaseMap'

const map = vi.hoisted(() => ({
  create: vi.fn(),
  addControl: vi.fn(),
  setWorkerUrl: vi.fn(),
  remove: vi.fn(),
  on: vi.fn(),
  addSource: vi.fn(),
  addLayer: vi.fn(),
  getLayer: vi.fn(() => true),
  setLayoutProperty: vi.fn(),
  setPaintProperty: vi.fn(),
  fitBounds: vi.fn(),
  loaded: vi.fn(() => true),
  canvas: {
    style: { cursor: '' },
    toDataURL: () => 'data:image/png;base64,AAAA',
  },
  markerSet: vi.fn(),
  markerAdd: vi.fn(),
  markerRemove: vi.fn(),
  markerOptions: vi.fn(),
  off: vi.fn(),
  project: vi.fn(() => ({ x: 10, y: 20 })),
}))

vi.mock('maplibre-gl', () => ({
  Map: class {
    constructor(options: unknown) {
      map.create(options)
    }
    addControl = map.addControl
    remove = map.remove
    on = map.on
    addSource = map.addSource
    addLayer = map.addLayer
    getLayer = map.getLayer
    setLayoutProperty = map.setLayoutProperty
    setPaintProperty = map.setPaintProperty
    fitBounds = map.fitBounds
    getCanvas = () => map.canvas
    loaded = map.loaded
    off = map.off
    project = map.project
  },
  Marker: class {
    constructor(options?: unknown) {
      map.markerOptions(options)
    }
    setLngLat(point: unknown) {
      map.markerSet(point)
      return this
    }
    addTo(mapInstance: unknown) {
      map.markerAdd(mapInstance)
      return this
    }
    remove = map.markerRemove
  },
  NavigationControl: class {},
  ScaleControl: class {},
  getBearing: () => 0,
  setWorkerUrl: map.setWorkerUrl,
}))

describe('case map', () => {
  afterEach(cleanup)
  beforeEach(() => {
    vi.clearAllMocks()
    mapStore.setState({
      camera: { center: [...initialCamera.center], zoom: initialCamera.zoom },
      cameraDurationMs: 0,
      visible: [],
      opacity: {},
      tool: 'pan',
      selection: { type: 'none' },
    })
  })
  it('centers on Big Sur and releases its map when unmounted', () => {
    const { unmount } = render(<CaseMap />)
    expect(map.setWorkerUrl).toHaveBeenCalledOnce()
    expect(map.setWorkerUrl.mock.calls[0][0]).toContain('maplibre-gl-worker')
    expect(map.setWorkerUrl.mock.invocationCallOrder[0]).toBeLessThan(
      map.create.mock.invocationCallOrder[0],
    )
    expect(map.create).toHaveBeenCalledWith(
      expect.objectContaining({
        center: [-121.47, 35.92],
        zoom: 9,
        style: expect.objectContaining({
          sources: expect.objectContaining({
            osm: expect.objectContaining({
              tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
              attribution: expect.stringContaining('OpenStreetMap'),
            }),
          }),
        }),
      }),
    )
    unmount()
    expect(map.remove).toHaveBeenCalledOnce()
  })
  it('refuses map capture after a layer or map error', () => {
    let capture: (() => string) | null = null
    render(
      <CaseMap
        onCaptureReady={(value) => {
          capture = value
        }}
      />,
    )
    expect(capture!()).toBe('data:image/png;base64,AAAA')
    const fail = map.on.mock.calls.find(([event]) => event === 'error')?.[1]
    act(() => fail())
    expect(() => capture!()).toThrow()
  })
  it('rejects unloaded maps and synchronous errors and unregisters capture', () => {
    let capture: (() => string) | null = null
    const { unmount } = render(
      <CaseMap
        onCaptureReady={(value) => {
          capture = value
        }}
      />,
    )
    map.loaded.mockReturnValueOnce(false)
    expect(() => capture!()).toThrow('Map is not ready')
    expect(capture!()).toBe('data:image/png;base64,AAAA')
    const fail = map.on.mock.calls.find(([event]) => event === 'error')?.[1]
    act(() => {
      fail()
      expect(() => capture!()).toThrow('Map is not ready')
    })
    unmount()
    expect(capture).toBeNull()
  })
  it('captures with a story overlay and shared camera and cleans up', () => {
    mapStore.setState({
      camera: { center: [-121.38, 35.95], zoom: 12, bearing: 10, pitch: 20 },
      cameraDurationMs: 0,
      visible: [],
      opacity: {},
      selection: { type: 'none' },
      tool: 'pan',
    })
    let capture: (() => string) | null = null
    const { unmount } = render(
      <CaseMap
        overlay={<p>Story overlay</p>}
        onCaptureReady={(value) => {
          capture = value
        }}
      />,
    )
    expect(screen.getByText('Story overlay')).toBeTruthy()
    expect(map.create).toHaveBeenLastCalledWith(
      expect.objectContaining({
        center: [-121.38, 35.95],
        zoom: 12,
        bearing: 10,
        pitch: 20,
        canvasContextAttributes: { preserveDrawingBuffer: true },
      }),
    )
    expect(capture!()).toBe('data:image/png;base64,AAAA')
    unmount()
    expect(capture).toBeNull()
    expect(map.off).toHaveBeenCalledWith('moveend', expect.any(Function))
  })

  it('selects map points only in inspect mode', () => {
    mapStore.setState({ tool: 'pan', selection: { type: 'none' } })
    render(<CaseMap />)
    const click = map.on.mock.calls.find(([event]) => event === 'click')?.[1]
    act(() => click({ lngLat: { lng: -121.4, lat: 35.9 } }))
    expect(mapStore.getState().selection).toEqual({ type: 'none' })
    act(() => {
      mapStore.getState().setTool('inspect')
      click({ lngLat: { lng: -121.4, lat: 35.9 } })
    })
    expect(mapStore.getState().selection).toEqual({
      type: 'point',
      point: [-121.4, 35.9],
    })
    expect(mapStore.getState().panel).toBe('inspector')
  })

  it('adds clicked vertices to the shared profile while drawing', () => {
    mapStore.setState({
      tool: 'draw-profile',
      selection: { type: 'profile', line: [] },
    })
    render(<CaseMap />)
    const click = map.on.mock.calls.find(([event]) => event === 'click')?.[1]
    act(() => {
      click({ lngLat: { lng: -121.4, lat: 35.9 } })
      click({ lngLat: { lng: -121.3, lat: 35.8 } })
    })
    expect(mapStore.getState().selection).toEqual({
      type: 'profile',
      line: [
        [-121.4, 35.9],
        [-121.3, 35.8],
      ],
    })
    expect(mapStore.getState().panel).toBe('profile')
  })

  it('shows an inspect cursor and marks the selected point', () => {
    const { unmount } = render(<CaseMap />)
    act(() => mapStore.getState().setTool('inspect'))
    expect(map.canvas.style.cursor).toBe('crosshair')
    act(() =>
      mapStore.getState().select({ type: 'point', point: [-121.4, 35.9] }),
    )
    expect(map.markerSet).toHaveBeenCalledWith([-121.4, 35.9])
    expect(map.markerAdd).toHaveBeenCalled()
    act(() => mapStore.getState().setTool('pan'))
    expect(map.canvas.style.cursor).toBe('')
    unmount()
    expect(map.markerRemove).toHaveBeenCalled()
  })

  it('uses fixture corners, draws the perimeter and follows shared visibility and opacity', () => {
    const layers = manifest.layers as components['schemas']['layer'][]
    render(<CaseMap layers={layers} dataBaseUrl="/fixtures" />)
    const load = map.on.mock.calls.find(([event]) => event === 'load')?.[1]
    expect(load).toBeTypeOf('function')
    act(() => load())
    expect(map.fitBounds).toHaveBeenCalledWith(
      [
        [-121.495, 35.84],
        [-121.278, 35.992],
      ],
      expect.objectContaining({ duration: 0 }),
    )
    const sar = layers.find((layer) => layer.id === 'sar_t1_hh')!
    expect(map.addSource).toHaveBeenCalledWith(
      'firetrace-sar_t1_hh',
      expect.objectContaining({
        type: 'image',
        url: '/fixtures/layers/sar_t1_hh.png',
        coordinates: sar.coordinates,
      }),
    )
    expect(map.addSource).toHaveBeenCalledWith(
      'firetrace-perimeter',
      expect.objectContaining({
        type: 'geojson',
        data: '/fixtures/perimeter.geojson',
      }),
    )
    expect(map.addLayer).toHaveBeenCalledWith(
      expect.objectContaining({ id: 'firetrace-perimeter', type: 'line' }),
    )
    expect(map.addLayer.mock.calls.map(([layer]) => layer.id)).toEqual([
      'firetrace-sar_t1_hh',
      'firetrace-sar_t2_hh',
      'firetrace-sar_t1_hv',
      'firetrace-sar_t2_hv',
      'firetrace-change_hh',
      'firetrace-change_hv',
      'firetrace-change_index',
      'firetrace-hillshade',
      'firetrace-slope',
      'firetrace-optical_during',
      'firetrace-optical_after',
      'firetrace-perimeter-casing',
      'firetrace-perimeter',
    ])
    act(() => {
      mapStore.getState().toggleLayer('perimeter')
      mapStore.getState().setOpacity('sar_t1_hh', 0.35)
    })
    expect(map.setLayoutProperty).toHaveBeenCalledWith(
      'firetrace-perimeter',
      'visibility',
      'none',
    )
    expect(map.setPaintProperty).toHaveBeenCalledWith(
      'firetrace-sar_t1_hh',
      'raster-opacity',
      0.35,
    )
  })

  it('starts from the shared camera and keeps it instead of refitting', () => {
    const layers = manifest.layers as components['schemas']['layer'][]
    mapStore.setState({
      camera: { center: [-121.38, 35.95], zoom: 12, bearing: 10, pitch: 20 },
    })
    render(<CaseMap layers={layers} dataBaseUrl="/" />)
    expect(map.create).toHaveBeenCalledWith(
      expect.objectContaining({
        center: [-121.38, 35.95],
        zoom: 12,
        bearing: 10,
        pitch: 20,
      }),
    )
    const load = map.on.mock.calls.find(([event]) => event === 'load')?.[1]
    act(() => load())
    expect(map.fitBounds).not.toHaveBeenCalled()
    expect(map.on).toHaveBeenCalledWith('moveend', expect.any(Function))
  })

  it('draws overlay content on top of the map', () => {
    render(<CaseMap overlay={<p>Story card</p>} />)
    expect(screen.getByText('Story card')).toBeTruthy()
  })

  it('does not fit bounds when the manifest contains no raster', () => {
    const perimeter = manifest.layers.find((layer) => layer.id === 'perimeter')
    render(<CaseMap layers={[perimeter as components['schemas']['layer']]} />)
    const load = map.on.mock.calls.find(([event]) => event === 'load')?.[1]
    act(() => load())
    expect(map.fitBounds).not.toHaveBeenCalled()
  })

  it('shows a clear error when map loading fails', () => {
    render(
      <CaseMap
        layers={manifest.layers as components['schemas']['layer'][]}
        dataBaseUrl="/"
      />,
    )
    const onError = map.on.mock.calls.find(([event]) => event === 'error')?.[1]
    act(() => onError({ error: new Error('missing image') }))
    expect(screen.getByRole('alert').textContent).toMatch(/could not load/i)
    expect(screen.getByRole('alert').classList.contains('data-error')).toBe(
      true,
    )
  })

  it('preserves intentionally hidden layers when the map remounts', () => {
    const layers = manifest.layers as components['schemas']['layer'][]
    const first = render(<CaseMap layers={layers} dataBaseUrl="/" />)
    act(() => mapStore.getState().setVisible([]))
    first.unmount()
    render(<CaseMap layers={layers} dataBaseUrl="/" />)
    expect(mapStore.getState().visible).toEqual([])
  })

  it('checks the fixture raster footprint against the reference geometry', () => {
    const layers = manifest.layers as components['schemas']['layer'][]
    const raster = layers.filter(
      (layer) => layer.group === 'sar' || layer.group === 'observed_change',
    )
    const corners = raster[0].coordinates!
    for (const layer of raster) expect(layer.coordinates).toEqual(corners)
    const [west, north] = corners[0]
    const [east, south] = corners[2]
    const geojson = JSON.parse(
      readFileSync('../contracts/fixtures/web/perimeter.geojson', 'utf8'),
    ) as {
      features: { geometry: { coordinates: number[][][][] } }[]
    }
    for (const polygon of geojson.features[0].geometry.coordinates) {
      for (const ring of polygon) {
        for (const [lon, lat] of ring) {
          expect(lon).toBeGreaterThanOrEqual(west)
          expect(lon).toBeLessThanOrEqual(east)
          expect(lat).toBeGreaterThanOrEqual(south)
          expect(lat).toBeLessThanOrEqual(north)
        }
      }
    }
  })
})
