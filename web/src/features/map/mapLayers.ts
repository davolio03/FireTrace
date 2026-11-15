import type { Map as MapLibreMap } from 'maplibre-gl'
import type { MapStore } from '../../state/mapStore'
import type { Layer } from './layers'
import { isSupportedComparison } from './comparison'

export function addMapLayers(
  map: MapLibreMap,
  layers: Layer[],
  baseUrl: string,
  onError: () => void,
) {
  for (const layer of layers) {
    try {
      if (!layer.url) throw new Error('Layer URL missing')
      const id = `firetrace-${layer.id}`
      const url = `${baseUrl.replace(/\/+$/, '')}/${layer.url.replace(/^\/+/, '')}`
      if (layer.kind === 'raster') {
        const corners = layer.coordinates
        if (!corners || corners.length !== 4)
          throw new Error('Layer corners missing')
        map.addSource(id, {
          type: 'image',
          url,
          coordinates: [corners[0], corners[1], corners[2], corners[3]],
        })
        map.addLayer({
          id,
          type: 'raster',
          source: id,
          paint: {
            // MapLibre tweens transitionable paint properties, so switching a
            // layer dissolves it instead of popping.
            'raster-opacity': 1,
            // Additive compositing over the dark basemap makes the radar read
            // as luminous data instead of a flat translucent sheet.
            'raster-layer-blend': 'screen',
          },
        })
      } else {
        map.addSource(id, { type: 'geojson', data: url })
        const color =
          layer.legend.type === 'categorical'
            ? layer.legend.items[0]?.color
            : undefined
        // A pale casing keeps the perimeter readable over both the dark
        // basemap and the bright raster layers, without changing its colour.
        map.addLayer({
          id: `${id}-casing`,
          type: 'line',
          source: id,
          paint: {
            'line-color': 'rgba(226, 240, 255, 0.75)',
            'line-width': 5,
            'line-opacity': 0.55,
          },
        })
        map.addLayer({
          id,
          type: 'line',
          source: id,
          paint: {
            'line-color': color ?? '#000000',
            'line-width': 2,
            'line-opacity': 1,
          },
        })
      }
    } catch {
      onError()
    }
  }
}

export function syncMapLayers(
  map: MapLibreMap,
  layers: Layer[],
  state: MapStore,
  side: 'left' | 'right',
) {
  for (const layer of layers) {
    const id = `firetrace-${layer.id}`
    if (!map.getLayer(id)) continue
    const comparingRaster =
      isSupportedComparison(state.compare, layers) && layer.kind === 'raster'
    const visible = comparingRaster
      ? layer.id === state.compare![side]
      : state.visible.includes(layer.id)
    const opacity = comparingRaster
      ? 1
      : (state.opacity[layer.id] ?? layer.default_opacity)
    map.setLayoutProperty(id, 'visibility', visible ? 'visible' : 'none')
    map.setPaintProperty(
      id,
      layer.kind === 'raster' ? 'raster-opacity' : 'line-opacity',
      opacity,
    )
    // The casing follows the line it frames.
    const casing = `${id}-casing`
    if (map.getLayer(casing)) {
      map.setLayoutProperty(casing, 'visibility', visible ? 'visible' : 'none')
      map.setPaintProperty(casing, 'line-opacity', opacity * 0.55)
    }
  }
}
