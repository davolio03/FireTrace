import { useCallback, useEffect, useRef, useState } from 'react'
import * as maplibregl from 'maplibre-gl'
import mapWorkerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url'
import { mapStore, useMapStore } from '../../state/mapStore'
import { ComparisonControls, type ComparisonDates } from './ComparisonControls'
import { ComparisonOverlay } from './ComparisonOverlay'
import { isSupportedComparison } from './comparison'
import { LayerControls } from './LayerControls'
import { type Layer, visibleMapLayers } from './layers'
import { addMapLayers, syncMapLayers } from './mapLayers'
import { createBaseMapStyle } from './mapStyle'

const noLayers: Layer[] = []

export function CaseMap({
  layers = noLayers,
  dataBaseUrl = '/',
  dates = { before: 'Date unavailable', after: 'Date unavailable' },
}: {
  layers?: Layer[]
  dataBaseUrl?: string
  dates?: ComparisonDates
}) {
  const container = useRef<HTMLDivElement>(null)
  const [primary, setPrimary] = useState<maplibregl.Map | null>(null)
  const compare = useMapStore((state) => state.compare)
  const [error, setError] = useState(false)
  const showError = useCallback(() => setError(true), [])

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
    const map = new maplibregl.Map({
      container: container.current,
      center: [-121.47, 35.92],
      zoom: 9,
      style: createBaseMapStyle(),
    })
    setPrimary(map)
    map.addControl(new maplibregl.NavigationControl())
    map.on('error', showError)
    const syncLayers = () =>
      syncMapLayers(map, displayed, mapStore.getState(), 'left')
    const unsubscribe = mapStore.subscribe(syncLayers)
    map.on('load', () => {
      const footprint = displayed.find(
        (layer) => layer.kind === 'raster' && layer.coordinates?.length === 4,
      )?.coordinates
      if (footprint) {
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
      unsubscribe()
      map.remove()
    }
  }, [layers, dataBaseUrl, showError])

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
                Before — {dates.before} —{' '}
                {compare.left.endsWith('_hv') ? 'HV' : 'HH'}
              </span>
              <span
                aria-hidden="true"
                className="pointer-events-none absolute right-2 top-2 rounded bg-white px-2 py-1 text-xs text-slate-900"
              >
                After — {dates.after} —{' '}
                {compare.right.endsWith('_hv') ? 'HV' : 'HH'}
              </span>
            </>
          )}
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
