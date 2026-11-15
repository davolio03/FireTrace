import { type ReactNode, useCallback, useEffect, useRef, useState } from 'react'
import * as maplibregl from 'maplibre-gl'
import mapWorkerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url'
import { isInitialCamera, mapStore, useMapStore } from '../../state/mapStore'
import { syncCamera } from './cameraSync'
import { ComparisonControls, type ComparisonDates } from './ComparisonControls'
import { ComparisonOverlay } from './ComparisonOverlay'
import { comparisonLabel, isSupportedComparison } from './comparison'
import { LayerControls } from './LayerControls'
import { type Layer, visibleMapLayers } from './layers'
import { addMapLayers, syncMapLayers } from './mapLayers'
import { createBaseMapStyle } from './mapStyle'
import { ProfileOverlay } from './ProfileOverlay'
import type { LonLat } from '../../state/mapStore'

const noLayers: Layer[] = []

export function CaseMap({
  layers = noLayers,
  dataBaseUrl = '/',
  dates = { before: 'Date unavailable', after: 'Date unavailable' },
  profileSample = null,
  onCaptureReady,
  overlay = null,
}: {
  layers?: Layer[]
  dataBaseUrl?: string
  dates?: ComparisonDates
  profileSample?: LonLat | null
  onCaptureReady?: (capture: (() => string) | null) => void
  /** Content drawn over the map (for example the guided story card). */
  overlay?: ReactNode
}) {
  const container = useRef<HTMLDivElement>(null)
  const [primary, setPrimary] = useState<maplibregl.Map | null>(null)
  const compare = useMapStore((state) => state.compare)
  const tool = useMapStore((state) => state.tool)
  const selection = useMapStore((state) => state.selection)
  const [error, setError] = useState(false)
  const errorRef = useRef(false)
  const showError = useCallback(() => {
    errorRef.current = true
    setError(true)
  }, [])

  useEffect(() => {
    if (!container.current) return
    const displayed = visibleMapLayers(layers)
    const { visible, opacity, setVisible, setOpacity } = mapStore.getState()
    if (
      displayed.length &&
      visible.length === 0 &&
      Object.keys(opacity).length === 0
    ) {
      setVisible(
        displayed
          .filter((layer) => layer.default_visible)
          .map((layer) => layer.id),
      )
      displayed.forEach((layer) => setOpacity(layer.id, layer.default_opacity))
    }

    maplibregl.setWorkerUrl(mapWorkerUrl)
    // The map is recreated when the manifest arrives; start from the shared
    // camera so a camera set by the user or the story is not lost.
    const { center, zoom, bearing, pitch } = mapStore.getState().camera
    const map = new maplibregl.Map({
      container: container.current,
      center,
      zoom,
      bearing: bearing ?? 0,
      pitch: pitch ?? 0,
      canvasContextAttributes: { preserveDrawingBuffer: true },
      style: createBaseMapStyle(),
    })
    onCaptureReady?.(() => {
      if (!map.loaded() || errorRef.current) throw new Error('Map is not ready')
      return map.getCanvas().toDataURL('image/png')
    })
    const stopCameraSync = syncCamera(map)
    setPrimary(map)
    map.addControl(new maplibregl.NavigationControl())
    map.on('click', (event) => {
      if (mapStore.getState().tool === 'inspect') {
        mapStore.getState().select({
          type: 'point',
          point: [event.lngLat.lng, event.lngLat.lat],
        })
      }
      if (mapStore.getState().tool === 'draw-profile') {
        const current = mapStore.getState().selection
        const line = current.type === 'profile' ? current.line : []
        mapStore.getState().select({
          type: 'profile',
          line: [...line, [event.lngLat.lng, event.lngLat.lat]],
        })
      }
    })
    map.on('error', showError)
    const syncLayers = () =>
      syncMapLayers(map, displayed, mapStore.getState(), 'left')
    const unsubscribe = mapStore.subscribe(syncLayers)
    map.on('load', () => {
      const footprint = displayed.find(
        (layer) => layer.kind === 'raster' && layer.coordinates?.length === 4,
      )?.coordinates
      // Fit the data only on first view; afterwards keep the shared camera.
      if (footprint && isInitialCamera(mapStore.getState().camera)) {
        const longitudes = footprint.map(([lon]) => lon)
        const latitudes = footprint.map(([, lat]) => lat)
        map.fitBounds(
          [
            [Math.min(...longitudes), Math.min(...latitudes)],
            [Math.max(...longitudes), Math.max(...latitudes)],
          ],
          { padding: 32, duration: 0 },
        )
      }
      addMapLayers(map, displayed, dataBaseUrl, showError)
      syncLayers()
    })
    return () => {
      stopCameraSync()
      unsubscribe()
      onCaptureReady?.(null)
      map.remove()
    }
  }, [layers, dataBaseUrl, showError, onCaptureReady])

  useEffect(() => {
    if (!primary) return
    const canvas = primary.getCanvas()
    canvas.style.cursor =
      tool === 'inspect' || tool === 'draw-profile' ? 'crosshair' : ''
    return () => {
      canvas.style.cursor = ''
    }
  }, [primary, tool])

  useEffect(() => {
    if (!primary || selection.type !== 'point') return
    const marker = new maplibregl.Marker()
      .setLngLat(selection.point)
      .addTo(primary)
    return () => {
      marker.remove()
    }
  }, [primary, selection])

  return (
    <div>
      {error && (
        <p role="alert" className="p-3 text-red-700">
          The map or a layer could not load. Check your connection and data.
        </p>
      )}
      <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_20rem]">
        <div className="relative h-[32rem] w-full">
          <div
            ref={container}
            role="region"
            aria-label="Map of Big Sur"
            className="h-full w-full"
          />
          {compare && primary && isSupportedComparison(compare, layers) && (
            <>
              <ComparisonOverlay
                primary={primary}
                layers={layers}
                dataBaseUrl={dataBaseUrl}
                position={compare.position}
                onError={showError}
              />
              <div
                aria-hidden="true"
                className="pointer-events-none absolute inset-y-0 w-0.5 bg-white shadow"
                style={{ left: `${compare.position * 100}%` }}
              />
              <span
                aria-hidden="true"
                className="pointer-events-none absolute left-2 top-2 rounded bg-white px-2 py-1 text-xs text-slate-900"
              >
                {comparisonLabel(compare.left, layers, dates)}
              </span>
              <span
                aria-hidden="true"
                className="pointer-events-none absolute right-2 top-2 rounded bg-white px-2 py-1 text-xs text-slate-900"
              >
                {comparisonLabel(compare.right, layers, dates)}
              </span>
            </>
          )}
          {primary && selection.type === 'profile' && (
            <ProfileOverlay
              map={primary}
              line={selection.line}
              sample={profileSample}
            />
          )}
          {overlay}
        </div>
        {layers.length > 0 && (
          <div className="space-y-4">
            <ComparisonControls layers={layers} dates={dates} />
            <LayerControls layers={layers} />
          </div>
        )}
      </div>
    </div>
  )
}
