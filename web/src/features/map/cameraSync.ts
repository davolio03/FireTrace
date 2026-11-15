import type * as maplibregl from 'maplibre-gl'
import type { Camera } from '../../state/mapStore'
import { mapStore } from '../../state/mapStore'

type CameraMap = Pick<
  maplibregl.Map,
  | 'getCenter'
  | 'getZoom'
  | 'getBearing'
  | 'getPitch'
  | 'flyTo'
  | 'jumpTo'
  | 'on'
  | 'off'
>

const CENTER_TOLERANCE_DEG = 1e-6
const ZOOM_TOLERANCE = 1e-3
const ANGLE_TOLERANCE_DEG = 1e-2

export function readCamera(map: CameraMap): Camera {
  const { lng, lat } = map.getCenter()
  return {
    center: [lng, lat],
    zoom: map.getZoom(),
    bearing: map.getBearing(),
    pitch: map.getPitch(),
  }
}

export function sameCamera(a: Camera, b: Camera) {
  return (
    Math.abs(a.center[0] - b.center[0]) < CENTER_TOLERANCE_DEG &&
    Math.abs(a.center[1] - b.center[1]) < CENTER_TOLERANCE_DEG &&
    Math.abs(a.zoom - b.zoom) < ZOOM_TOLERANCE &&
    Math.abs((a.bearing ?? 0) - (b.bearing ?? 0)) < ANGLE_TOLERANCE_DEG &&
    Math.abs((a.pitch ?? 0) - (b.pitch ?? 0)) < ANGLE_TOLERANCE_DEG
  )
}

/**
 * Keeps the store camera and the map camera in sync both ways
 * (contracts/web-state.md):
 * - store -> map: a new store camera animates the map over
 *   `cameraDurationMs` (MapLibre skips the animation under
 *   prefers-reduced-motion because it is not marked essential);
 * - map -> store: every finished movement writes the map camera back.
 * Both directions compare with a tolerance, so they never loop.
 */
export function syncCamera(map: CameraMap) {
  // Starting a camera change stops any running animation, which fires
  // `moveend` mid-flight; that position must not overwrite the new target.
  let applying = false
  const unsubscribe = mapStore.subscribe((state, previous) => {
    if (state.camera === previous.camera) return
    if (sameCamera(readCamera(map), state.camera)) return
    const { center, zoom, bearing, pitch } = state.camera
    const target = { center, zoom, bearing, pitch }
    applying = true
    try {
      if (state.cameraDurationMs > 0) {
        map.flyTo({ ...target, duration: state.cameraDurationMs })
      } else {
        map.jumpTo(target)
      }
    } finally {
      applying = false
    }
  })
  const onMoveEnd = () => {
    if (applying) return
    const current = readCamera(map)
    const { camera, flyTo } = mapStore.getState()
    if (!sameCamera(current, camera)) flyTo(current, 0)
  }
  map.on('moveend', onMoveEnd)
  return () => {
    unsubscribe()
    map.off('moveend', onMoveEnd)
  }
}
