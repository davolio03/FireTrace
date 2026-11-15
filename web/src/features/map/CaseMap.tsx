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
import {
  addMapLayers,
  addZoneHighlight,
  setZoneHighlight,
  syncMapLayers,
} from './mapLayers'
import { createBaseMapStyle, layerBounds } from './mapStyle'
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
  sidebar,
}: {
  layers?: Layer[]
  dataBaseUrl?: string
  dates?: ComparisonDates
  profileSample?: LonLat | null
  onCaptureReady?: (capture: (() => string) | null) => void
  /** Content drawn over the map (for example the guided story card). */
  overlay?: ReactNode
  sidebar?: ReactNode
}) {
  const container = useRef<HTMLDivElement>(null)
  const [primary, setPrimary] = useState<maplibregl.Map | null>(null)
  const compare = useMapStore((state) => state.compare)
  const tool = useMapStore((state) => state.tool)
  const selection = useMapStore((state) => state.selection)
  const visibleLayers = useMapStore((state) => state.visible)
  const visibleSignature = visibleLayers.join(',')
  const [error, setError] = useState(false)
  const [cursor, setCursor] = useState<{ lon: number; lat: number } | null>(
    null,
  )
  const [bearing, setBearing] = useState(0)
  const [sweep, setSweep] = useState(0)
  const instrumentRef = useRef('')
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
      style: createBaseMapStyle({
        graticule: layerBounds(displayed) ?? undefined,
      }),
    })
    onCaptureReady?.(() => {
      if (!map.loaded() || errorRef.current) throw new Error('Map is not ready')
      return map.getCanvas().toDataURL('image/png')
    })
    const stopCameraSync = syncCamera(map)
    setPrimary(map)
    map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }))
    // A real metric scale bar and a live compass reading: both come from the
    // map itself, never from a placeholder.
    map.addControl(
      new maplibregl.ScaleControl({ maxWidth: 120, unit: 'metric' }),
      'bottom-left',
    )
    map.on('move', () => setBearing(map.getBearing()))
    map.on('mousemove', (event) => {
      setCursor({ lon: event.lngLat.lng, lat: event.lngLat.lat })
    })
    map.on('mouseout', () => setCursor(null))
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
      const zoneLayer = layers.find((layer) => layer.id === 'review_zones')
      if (zoneLayer?.url) {
        addZoneHighlight(
          map,
          `${dataBaseUrl.replace(/\/+$/, '')}/${zoneLayer.url}`,
        )
      }
      const current = mapStore.getState().selection
      setZoneHighlight(map, current.type === 'zone' ? current.zoneId : null)
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

  // A single lit sweep whenever the instrumentation changes: the reader sees
  // the map react to the layer, comparison or selection they just changed.
  useEffect(() => {
    if (!primary) return
    const instrument = [
      tool,
      selection.type,
      compare ? `compare:${compare.left}:${compare.right}` : 'single',
      visibleSignature,
    ].join('|')
    if (instrumentRef.current === instrument) return
    const first = instrumentRef.current === ''
    instrumentRef.current = instrument
    if (first) return
    setSweep((value) => value + 1)
  }, [primary, tool, selection.type, compare, visibleSignature])

  useEffect(() => {
    if (!primary) return
    setZoneHighlight(
      primary,
      selection.type === 'zone' ? selection.zoneId : null,
    )
  }, [primary, selection])

  useEffect(() => {
    if (!primary || selection.type !== 'point') return
    // A mission-style crosshair instead of the default pin: the analyst's
    // own selection, animated only when motion is allowed.
    const element = document.createElement('div')
    element.className = 'map-selection-marker'
    element.setAttribute('aria-hidden', 'true')
    const marker = new maplibregl.Marker({ element })
      .setLngLat(selection.point)
      .addTo(primary)
    return () => {
      marker.remove()
      element.remove()
    }
  }, [primary, selection])

  return (
    <div className="analysis-map-layout">
      <div className="analysis-map-canvas relative w-full">
        <div
          ref={container}
          role="region"
          aria-label="Map of Big Sur"
          className="h-full w-full"
        />
        <div className="map-engineering-grid" aria-hidden="true" />
        {sweep > 0 && (
          <div className="map-sweep" aria-hidden="true" key={sweep} />
        )}
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
              className="comparison-divider"
              style={{ left: `${compare.position * 100}%` }}
            >
              <span className="comparison-divider-handle" />
            </div>
            <span
              aria-hidden="true"
              className="comparison-chip comparison-chip--left"
            >
              {comparisonLabel(compare.left, layers, dates)}
            </span>
            <span
              aria-hidden="true"
              className="comparison-chip comparison-chip--right"
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
        {sidebar}
        <div className="map-coordinate-readout" aria-live="off">
          <span>
            {cursor
              ? `${cursor.lat.toFixed(4)}°N  ${Math.abs(cursor.lon).toFixed(4)}°W`
              : '—'}
          </span>
          <span>HDG {Math.round(bearing).toString().padStart(3, '0')}°</span>
        </div>
      </div>
      {!sidebar && layers.length > 0 && (
        <div className="map-fallback-controls space-y-4">
          <ComparisonControls layers={layers} dates={dates} />
          <LayerControls layers={layers} />
        </div>
      )}
      {error && (
        <p role="alert" className="data-error map-error-bar">
          The map or a layer could not load. Check your connection and data.
        </p>
      )}
    </div>
  )
}
