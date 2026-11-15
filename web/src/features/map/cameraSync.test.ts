import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { initialCamera, mapStore, type Camera } from '../../state/mapStore'
import { readCamera, sameCamera, syncCamera } from './cameraSync'

type Listener = (event: { originalEvent?: unknown }) => void

/** Minimal stand-in for the MapLibre camera API, with real moveend events. */
function fakeMap(start: Camera) {
  let camera = { bearing: 0, pitch: 0, ...start }
  const listeners = new Set<Listener>()
  const emitMoveEnd = (event: { originalEvent?: unknown } = {}) =>
    listeners.forEach((listener) => listener(event))
  const moveTo = (next: Partial<Camera>) => {
    camera = { ...camera, ...next }
  }
  const map = {
    getCenter: () => ({ lng: camera.center[0], lat: camera.center[1] }),
    getZoom: () => camera.zoom,
    getBearing: () => camera.bearing ?? 0,
    getPitch: () => camera.pitch ?? 0,
    jumpTo: vi.fn((next: Partial<Camera>) => {
      moveTo(next)
      emitMoveEnd()
      return map
    }),
    flyTo: vi.fn(() => map),
    on: vi.fn((_event: string, listener: Listener) => {
      listeners.add(listener)
      return map
    }),
    off: vi.fn((_event: string, listener: Listener) => {
      listeners.delete(listener)
      return map
    }),
    /** Simulates the user dragging or zooming the map. */
    userMove: (next: Partial<Camera>) => {
      moveTo(next)
      emitMoveEnd({ originalEvent: new Event('pointerup') })
    },
    /** Simulates MapLibre ending an animation on its own (no user event). */
    programmaticMove: (next: Partial<Camera>) => {
      moveTo(next)
      emitMoveEnd()
    },
  }
  return map
}

const story: Camera = { center: [-121.3865, 35.916], zoom: 11.5 }

describe('camera sync', () => {
  beforeEach(() => {
    mapStore.setState({
      camera: { center: [...initialCamera.center], zoom: initialCamera.zoom },
      cameraDurationMs: 0,
    })
  })
  afterEach(() => vi.clearAllMocks())

  it('compares cameras with a small tolerance', () => {
    expect(sameCamera(story, { ...story, zoom: 11.5000001 })).toBe(true)
    expect(sameCamera(story, { ...story, zoom: 11.6 })).toBe(false)
    expect(sameCamera(story, { ...story, bearing: 0, pitch: 0 })).toBe(true)
    expect(sameCamera(story, { ...story, bearing: 30 })).toBe(false)
  })

  it('animates the map over the duration requested by flyTo', () => {
    const map = fakeMap(mapStore.getState().camera)
    const stop = syncCamera(map as never)
    mapStore.getState().flyTo(story, 2500)
    expect(map.flyTo).toHaveBeenCalledWith(
      expect.objectContaining({
        center: story.center,
        zoom: story.zoom,
        duration: 2500,
      }),
    )
    expect(map.jumpTo).not.toHaveBeenCalled()
    stop()
  })

  it('jumps without animation when no duration is given', () => {
    const map = fakeMap(mapStore.getState().camera)
    const stop = syncCamera(map as never)
    mapStore.getState().flyTo(story)
    expect(map.jumpTo).toHaveBeenCalledWith(
      expect.objectContaining({ center: story.center, zoom: story.zoom }),
    )
    expect(map.flyTo).not.toHaveBeenCalled()
    expect(sameCamera(readCamera(map as never), story)).toBe(true)
    stop()
  })

  it('writes user movements back to the store without moving the map again', () => {
    const map = fakeMap(mapStore.getState().camera)
    const stop = syncCamera(map as never)
    map.userMove({ center: [-121.4, 35.9], zoom: 12 })
    expect(mapStore.getState().camera).toMatchObject({
      center: [-121.4, 35.9],
      zoom: 12,
    })
    expect(mapStore.getState().cameraDurationMs).toBe(0)
    expect(map.flyTo).not.toHaveBeenCalled()
    expect(map.jumpTo).not.toHaveBeenCalled()
    stop()
  })

  it('keeps the store target when an animation ends early by itself', () => {
    const map = fakeMap(mapStore.getState().camera)
    const stop = syncCamera(map as never)
    mapStore.getState().flyTo(story, 2500)
    // e.g. 3D terrain loading stops the flight half-way.
    map.programmaticMove({ center: [-121.42, 35.92], zoom: 10 })
    expect(mapStore.getState().camera).toEqual(story)
    stop()
  })

  it('ignores the moveend fired while starting a new camera change', () => {
    const map = fakeMap(mapStore.getState().camera)
    const stop = syncCamera(map as never)
    // jumpTo fires moveend synchronously at the target: no write-back loop.
    mapStore.getState().flyTo(story)
    expect(mapStore.getState().camera).toEqual(story)
    expect(map.jumpTo).toHaveBeenCalledOnce()
    stop()
  })

  it('stops syncing when released', () => {
    const map = fakeMap(mapStore.getState().camera)
    const stop = syncCamera(map as never)
    stop()
    mapStore.getState().flyTo(story, 1000)
    map.userMove({ zoom: 14 })
    expect(map.flyTo).not.toHaveBeenCalled()
    expect(mapStore.getState().camera).toEqual(story)
  })
})
