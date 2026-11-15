import { act, cleanup, render, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import manifest from '../../../../contracts/fixtures/web/layers.json'
import tiles from '../../../../contracts/fixtures/web/terrain/tiles.json'
import frame from '../../story/nisar-frame.json'
import { initialCamera, mapStore, type LonLat } from '../../state/mapStore'
import { CinematicMap } from './CinematicMap'
import { parseTerrainTiles } from './terrainTiles'
import type { Layer } from './layers'

type Handler = (...args: unknown[]) => void

const mock = vi.hoisted(() => {
  const handlers = new Map<string, Handler[]>()
  const added = new Set<string>()
  return {
    handlers,
    added,
    create: vi.fn(),
    addSource: vi.fn(),
    addLayer: vi.fn((...args: [{ id: string }, string?]) =>
      added.add(args[0].id),
    ),
    setTerrain: vi.fn(),
    easeTo: vi.fn(),
    stop: vi.fn(),
    remove: vi.fn(),
    setLayoutProperty: vi.fn(),
    setPaintProperty: vi.fn(),
    moving: false,
  }
})

vi.mock('maplibre-gl', () => ({
  Map: class {
    constructor(options: unknown) {
      mock.create(options)
    }
    on = (event: string, handler: Handler) => {
      mock.handlers.set(event, [...(mock.handlers.get(event) ?? []), handler])
    }
    off = (event: string, handler: Handler) => {
      mock.handlers.set(
        event,
        (mock.handlers.get(event) ?? []).filter((h) => h !== handler),
      )
    }
    addSource = mock.addSource
    addLayer = mock.addLayer
    getLayer = (id: string) => mock.added.has(id)
    getSource = () => undefined
    setLayoutProperty = mock.setLayoutProperty
    setPaintProperty = mock.setPaintProperty
    setTerrain = mock.setTerrain
    easeTo = mock.easeTo
    stop = mock.stop
    remove = mock.remove
    isMoving = () => mock.moving
    getBearing = () => 10
    getCenter = () => ({ lng: -121.47, lat: 35.92 })
    getZoom = () => 9
    getPitch = () => 0
    flyTo = vi.fn()
    jumpTo = vi.fn()
  },
  setWorkerUrl: vi.fn(),
}))

const layers = manifest.layers as Layer[]
const ring = frame.geometry.coordinates[0] as LonLat[]
const fire = (event: string) =>
  act(() => (mock.handlers.get(event) ?? []).forEach((handler) => handler()))

describe('cinematic map', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mock.handlers.clear()
    mock.added.clear()
    mock.moving = false
    mapStore.setState({
      camera: { center: [...initialCamera.center], zoom: initialCamera.zoom },
      visible: ['perimeter'],
      opacity: {},
      compare: null,
    })
  })
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('reads the terrain manifest defensively', () => {
    expect(parseTerrainTiles(tiles)).toMatchObject({
      tileSize: 256,
      minzoom: 8,
      maxzoom: 12,
    })
    expect(parseTerrainTiles({ ...tiles, encoding: 'mapbox' })).toBeNull()
    expect(parseTerrainTiles(null)).toBeNull()
  })

  it('opens on a globe and adds terrain, layers, frame and track', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: true, json: async () => tiles }),
    )
    const onTerrain = vi.fn()
    render(
      <CinematicMap
        layers={layers}
        dataBaseUrl="/data"
        frame={ring}
        onTerrain={onTerrain}
      />,
    )
    const options = mock.create.mock.calls[0][0]
    expect(options.style.projection).toEqual({ type: 'globe' })
    expect(options.maxPitch).toBe(75)
    fire('load')
    expect(mock.added).toContain('nisar-frame-line')
    expect(mock.added).toContain('nisar-track')
    expect(mock.added).toContain('firetrace-highlight_mask')
    expect(mock.added).toContain('firetrace-perimeter-glow')
    await waitFor(() => expect(onTerrain).toHaveBeenCalledWith(true))
    expect(fetch).toHaveBeenCalledWith('/data/terrain/tiles.json')
    const dem = mock.addSource.mock.calls.find(([id]) => id === 'terrain-dem')
    expect(dem?.[1]).toMatchObject({
      type: 'raster-dem',
      encoding: 'terrarium',
      maxzoom: 12,
    })
    expect(dem?.[1].tiles[0]).toMatch(
      /\/data\/terrain\/\{z\}\/\{x\}\/\{y\}\.png$/,
    )
    expect(mock.setTerrain).toHaveBeenCalledWith({
      source: 'terrain-dem',
      exaggeration: 1.6,
    })
    // The hillshade goes under the radar layers.
    const hillshade = mock.addLayer.mock.calls.find(
      ([layer]) => layer.id === 'terrain-hillshade',
    )
    expect(hillshade?.[1]).toMatch(/^firetrace-/)
  })

  it('stays 2D when no terrain is published', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false }))
    const onTerrain = vi.fn()
    render(<CinematicMap layers={layers} frame={ring} onTerrain={onTerrain} />)
    fire('load')
    await waitFor(() => expect(onTerrain).toHaveBeenCalledWith(false))
    expect(mock.setTerrain).not.toHaveBeenCalled()
  })

  it('crossfades a comparison through the shared store', () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false }))
    render(<CinematicMap layers={layers} frame={ring} />)
    fire('load')
    act(() =>
      mapStore.getState().setCompare({
        left: 'sar_t1_hv',
        right: 'sar_t2_hv',
        position: 0.25,
      }),
    )
    expect(mock.setPaintProperty).toHaveBeenCalledWith(
      'firetrace-sar_t2_hv',
      'raster-opacity',
      0.75,
    )
    expect(mock.setLayoutProperty).toHaveBeenCalledWith(
      'firetrace-sar_t1_hv',
      'visibility',
      'visible',
    )
  })

  it('spins slowly while asked to, and stops', () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false }))
    const { rerender } = render(
      <CinematicMap layers={layers} frame={ring} spinning />,
    )
    expect(mock.easeTo).toHaveBeenCalledWith(
      expect.objectContaining({ bearing: 40, duration: 24_000 }),
    )
    rerender(<CinematicMap layers={layers} frame={ring} spinning={false} />)
    expect(mock.stop).toHaveBeenCalled()
  })

  it('does not spin under reduced motion', () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false }))
    render(<CinematicMap layers={layers} frame={ring} spinning reducedMotion />)
    expect(mock.easeTo).not.toHaveBeenCalled()
  })
})
