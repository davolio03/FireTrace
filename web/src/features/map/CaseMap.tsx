import { useEffect, useRef, useState } from 'react'
import * as maplibregl from 'maplibre-gl'
import mapWorkerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url'
import { mapStore } from '../../state/mapStore'
import { LayerControls } from './LayerControls'
import { type Layer, visibleMapLayers } from './layers'

const noLayers: Layer[] = []

export function CaseMap({
  layers = noLayers,
  dataBaseUrl = '/',
}: {
  layers?: Layer[]
  dataBaseUrl?: string
}) {
  const container = useRef<HTMLDivElement>(null)
  const [error, setError] = useState(false)

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
      style: {
        version: 8,
        sources: {
          osm: {
            type: 'raster',
            tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
            tileSize: 256,
            maxzoom: 19,
            attribution:
              '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
          },
        },
        layers: [
          {
            id: 'background',
            type: 'background',
            paint: { 'background-color': '#dbeafe' },
          },
          { id: 'basemap', type: 'raster', source: 'osm' },
        ],
      },
    })
    map.addControl(new maplibregl.NavigationControl())
    map.on('error', () => setError(true))
    const syncLayers = () => {
      const { visible, opacity } = mapStore.getState()
      for (const layer of displayed) {
        const id = `firetrace-${layer.id}`
        if (!map.getLayer(id)) continue
        map.setLayoutProperty(
          id,
          'visibility',
          visible.includes(layer.id) ? 'visible' : 'none',
        )
        map.setPaintProperty(
          id,
          layer.kind === 'raster' ? 'raster-opacity' : 'line-opacity',
          opacity[layer.id] ?? layer.default_opacity,
        )
      }
    }
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
      for (const layer of displayed) {
        try {
          if (!layer.url) throw new Error('Layer URL missing')
          const id = `firetrace-${layer.id}`
          const url = `${dataBaseUrl.replace(/\/+$/, '')}/${layer.url.replace(/^\/+/, '')}`
          if (layer.kind === 'raster') {
            const corners = layer.coordinates
            if (!corners || corners.length !== 4)
              throw new Error('Layer corners missing')
            map.addSource(id, {
              type: 'image',
              url,
              coordinates: [corners[0], corners[1], corners[2], corners[3]],
            })
            map.addLayer({ id, type: 'raster', source: id })
          } else {
            map.addSource(id, { type: 'geojson', data: url })
            const color =
              layer.legend.type === 'categorical'
                ? layer.legend.items[0]?.color
                : undefined
            map.addLayer({
              id,
              type: 'line',
              source: id,
              paint: { 'line-color': color ?? '#000000', 'line-width': 2 },
            })
          }
        } catch {
          setError(true)
        }
      }
      syncLayers()
    })
    return () => {
      unsubscribe()
      map.remove()
    }
  }, [layers, dataBaseUrl])

  return (
    <div>
      {error && (
        <p role="alert" className="p-3 text-red-700">
          The map or a layer could not load. Check your connection and data.
        </p>
      )}
      <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_20rem]">
        <div
          ref={container}
          role="region"
          aria-label="Map of Big Sur"
          className="h-[32rem] w-full"
        />
        {layers.length > 0 && <LayerControls layers={layers} />}
      </div>
    </div>
  )
}
