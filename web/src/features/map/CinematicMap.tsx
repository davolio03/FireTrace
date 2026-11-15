import { useEffect, useRef, useState } from 'react'
import * as maplibregl from 'maplibre-gl'
import mapWorkerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url'
import { mapStore, type LonLat } from '../../state/mapStore'
import { readCamera, sameCamera, syncCamera } from './cameraSync'
import { storyMapLayers, syncCinematicLayers } from './cinematicLayers'
import type { Layer } from './layers'
import { addMapLayers } from './mapLayers'
import { createCinematicMapStyle } from './mapStyle'
import { groundTrack, pointAlong, ringCentre } from './orbit'
import { parseTerrainTiles, TERRAIN_EXAGGERATION } from './terrainTiles'

const SATELLITE_LAP_MS = 14_000
const SPIN_DEGREES = 30
const SPIN_MS = 24_000

const zoomFade = (stops: [number, number][]) =>
  [
    'interpolate',
    ['linear'],
    ['zoom'],
    ...stops.flat(),
  ] as maplibregl.ExpressionSpecification

function addOrbitLayers(map: maplibregl.Map, frame: LonLat[], track: LonLat[]) {
  map.addSource('nisar-frame', {
    type: 'geojson',
    data: {
      type: 'Feature',
      properties: {},
      geometry: { type: 'Polygon', coordinates: [frame] },
    },
  })
  map.addSource('nisar-track', {
    type: 'geojson',
    data: {
      type: 'Feature',
      properties: {},
      geometry: { type: 'LineString', coordinates: track },
    },
  })
  map.addSource('nisar-satellite', {
    type: 'geojson',
    data: {
      type: 'Feature',
      properties: {},
      geometry: { type: 'Point', coordinates: ringCentre(frame) },
    },
  })
  map.addLayer({
    id: 'nisar-frame-fill',
    type: 'fill',
    source: 'nisar-frame',
    paint: {
      'fill-color': '#f97316',
      'fill-opacity': zoomFade([
        [3, 0.28],
        [8, 0.1],
        [10, 0],
      ]),
    },
  })
  map.addLayer({
    id: 'nisar-frame-line',
    type: 'line',
    source: 'nisar-frame',
    paint: {
      'line-color': '#fb923c',
      'line-width': 2,
      'line-opacity': zoomFade([
        [3, 1],
        [8, 0.7],
        [10, 0],
      ]),
    },
  })
  map.addLayer({
    id: 'nisar-track',
    type: 'line',
    source: 'nisar-track',
    paint: {
      'line-color': '#e2e8f0',
      'line-width': 1.5,
      'line-dasharray': [2, 2],
      'line-opacity': zoomFade([
        [2, 0.9],
        [6, 0.5],
        [8, 0],
      ]),
    },
  })
  map.addLayer({
    id: 'nisar-satellite',
    type: 'circle',
    source: 'nisar-satellite',
    paint: {
      'circle-radius': 6,
      'circle-color': '#ffffff',
      'circle-stroke-color': '#38bdf8',
      'circle-stroke-width': 3,
      'circle-opacity': zoomFade([
        [2, 1],
        [6, 1],
        [7, 0],
      ]),
      'circle-stroke-opacity': zoomFade([
        [2, 1],
        [6, 1],
        [7, 0],
      ]),
    },
  })
}

function stylePerimeter(map: maplibregl.Map) {
  if (!map.getLayer('firetrace-perimeter')) return
  map.addLayer(
    {
      id: 'firetrace-perimeter-glow',
      type: 'line',
      source: 'firetrace-perimeter',
      paint: {
        'line-color': '#fbbf24',
        'line-width': 10,
        'line-blur': 8,
        'line-opacity': 0.45,
      },
    },
    'firetrace-perimeter',
  )
  map.setPaintProperty('firetrace-perimeter', 'line-color', '#fde68a')
  map.setPaintProperty('firetrace-perimeter', 'line-width', 2.5)
}

/**
 * Full-screen 3D map for the guided story: a globe that zooms down onto the
 * case, Copernicus relief when `terrain/tiles.json` is published, the radar
 * layers draped over it, the real NISAR frame and an illustrative ground
 * track. It shares the store camera and layers with the analysis map.
 */
export function CinematicMap({
  layers,
  dataBaseUrl = '/',
  frame,
  spinning = false,
  satellite = false,
  reducedMotion = false,
  onTerrain,
}: {
  layers: Layer[]
  dataBaseUrl?: string
  /** Closed ring of the real NISAR frame footprint, [lon, lat]. */
  frame: LonLat[]
  /** Slowly rotate the camera (drone shot) while true. */
  spinning?: boolean
  /** Move the satellite marker along the ground track while true. */
  satellite?: boolean
  reducedMotion?: boolean
  onTerrain?: (available: boolean) => void
}) {
  const container = useRef<HTMLDivElement>(null)
  const [map, setMap] = useState<maplibregl.Map | null>(null)
  const track = useRef<LonLat[]>([])
  const reportTerrain = useRef(onTerrain)
  useEffect(() => {
    reportTerrain.current = onTerrain
  }, [onTerrain])

  useEffect(() => {
    if (!container.current) return
    const base = dataBaseUrl.replace(/\/+$/, '')
    const drawn = storyMapLayers(layers)
    let cancelled = false
    maplibregl.setWorkerUrl(mapWorkerUrl)
    const { center, zoom, bearing, pitch } = mapStore.getState().camera
    const instance = new maplibregl.Map({
      container: container.current,
      style: createCinematicMapStyle(),
      center,
      zoom,
      bearing: bearing ?? 0,
      pitch: pitch ?? 0,
      maxPitch: 75,
      attributionControl: { compact: true },
    })
    setMap(instance)
    const stopCamera = syncCamera(instance)
    const sync = () => syncCinematicLayers(instance, drawn, mapStore.getState())
    const unsubscribe = mapStore.subscribe(sync)
    track.current = groundTrack(ringCentre(frame), 60, 160)

    instance.on('load', () => {
      // Keep the attribution folded into its (i) button: open, it covers the
      // story's chapter bar. It still opens on demand.
      const attribution = instance
        .getContainer()
        .querySelector('.maplibregl-ctrl-attrib')
      attribution?.classList.remove('maplibregl-compact-show')
      attribution?.removeAttribute('open')
      addOrbitLayers(instance, frame, track.current)
      addMapLayers(instance, drawn, dataBaseUrl, () => undefined)
      stylePerimeter(instance)
      sync()
      fetch(`${base}/terrain/tiles.json`)
        .then((response) => (response.ok ? response.json() : null))
        .then((value: unknown) => {
          if (cancelled) return
          const tiles = parseTerrainTiles(value)
          if (!tiles) {
            reportTerrain.current?.(false)
            return
          }
          const template = new URL(
            `${base}/terrain/{z}/{x}/{y}.png`,
            window.location.href,
          ).href
            .replace(/%7B/g, '{')
            .replace(/%7D/g, '}')
          const dem = {
            type: 'raster-dem' as const,
            tiles: [template],
            encoding: 'terrarium' as const,
            tileSize: tiles.tileSize,
            minzoom: tiles.minzoom,
            maxzoom: tiles.maxzoom,
            bounds: tiles.bounds,
          }
          // Separate sources for relief and shading, as MapLibre recommends.
          instance.addSource('terrain-dem', {
            ...dem,
            attribution: tiles.attribution,
          })
          instance.addSource('terrain-shade', dem)
          const firstData = drawn
            .map((layer) => `firetrace-${layer.id}`)
            .find((id) => instance.getLayer(id))
          instance.addLayer(
            {
              id: 'terrain-hillshade',
              type: 'hillshade',
              source: 'terrain-shade',
              paint: {
                'hillshade-exaggeration': 0.35,
                'hillshade-shadow-color': '#0f172a',
              },
            },
            firstData,
          )
          instance.setTerrain({
            source: 'terrain-dem',
            exaggeration: TERRAIN_EXAGGERATION,
          })
          // Switching terrain on stops a running flight; finish it.
          const { camera, cameraDurationMs } = mapStore.getState()
          if (!sameCamera(readCamera(instance), camera)) {
            const { center, zoom, bearing, pitch } = camera
            instance.flyTo({
              center,
              zoom,
              bearing,
              pitch,
              duration: Math.max(1500, cameraDurationMs / 2),
            })
          }
          reportTerrain.current?.(true)
        })
        .catch(() => {
          if (!cancelled) reportTerrain.current?.(false)
        })
    })

    return () => {
      cancelled = true
      stopCamera()
      unsubscribe()
      instance.remove()
      setMap(null)
    }
  }, [layers, dataBaseUrl, frame])

  // Drone shot: keep turning slowly while the step plays.
  useEffect(() => {
    if (!map || !spinning || reducedMotion) return
    let active = true
    const spin = () => {
      if (!active || map.isMoving()) return
      map.easeTo({
        bearing: map.getBearing() + SPIN_DEGREES,
        duration: SPIN_MS,
        easing: (t) => t,
      })
    }
    map.on('moveend', spin)
    spin()
    return () => {
      active = false
      map.off('moveend', spin)
      map.stop()
    }
  }, [map, spinning, reducedMotion])

  // Satellite marker riding the illustrative ground track.
  useEffect(() => {
    if (!map || !satellite || reducedMotion) return
    let frameId = 0
    const startedAt = performance.now()
    const tick = (now: number) => {
      const source = map.getSource('nisar-satellite') as
        maplibregl.GeoJSONSource | undefined
      const progress = ((now - startedAt) % SATELLITE_LAP_MS) / SATELLITE_LAP_MS
      source?.setData({
        type: 'Feature',
        properties: {},
        geometry: {
          type: 'Point',
          coordinates: pointAlong(track.current, progress),
        },
      })
      frameId = requestAnimationFrame(tick)
    }
    frameId = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frameId)
  }, [map, satellite, reducedMotion])

  return (
    <div
      ref={container}
      role="region"
      aria-label="3D story map of Big Sur"
      // Not `absolute`: maplibre-gl.css sets `.maplibregl-map { position:
      // relative }`, which beats Tailwind's layered utilities and collapses
      // the map to 0 px. The parent positions it; the map just fills it.
      className="h-full w-full"
    />
  )
}
