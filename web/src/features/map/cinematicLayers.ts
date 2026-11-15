import type { Map as MapLibreMap } from 'maplibre-gl'
import type { LayerId, MapStore } from '../../state/mapStore'
import { type Layer, visibleMapLayers } from './layers'

/** Layers the story view draws: the analysis map's layers plus the P1 highlight. */
export function storyMapLayers(layers: Layer[]): Layer[] {
  const drawn = visibleMapLayers(layers)
  const highlight = layers.find(
    (layer) => layer.id === 'highlight_mask' && layer.kind === 'raster',
  )
  return highlight && !drawn.includes(highlight) ? [...drawn, highlight] : drawn
}

export interface LayerLook {
  visible: boolean
  opacity: number
}

/**
 * Visibility and opacity for every story layer. A comparison becomes a
 * crossfade instead of a swipe: the lower of the two layers stays opaque and
 * the upper one fades, so `position` 1 shows the left layer and 0 the right.
 */
export function cinematicLayerLooks(
  layers: Layer[],
  state: Pick<MapStore, 'visible' | 'opacity' | 'compare'>,
): Map<LayerId, LayerLook> {
  const looks = new Map<LayerId, LayerLook>()
  const order = layers.map((layer) => layer.id)
  const compare = state.compare
  const fading =
    compare &&
    order.includes(compare.left) &&
    order.includes(compare.right) &&
    compare.left !== compare.right
      ? compare
      : null
  for (const layer of layers) {
    let visible = state.visible.includes(layer.id)
    let opacity = state.opacity[layer.id] ?? layer.default_opacity
    if (fading && (layer.id === fading.left || layer.id === fading.right)) {
      const leftOnTop = order.indexOf(fading.left) > order.indexOf(fading.right)
      const top = leftOnTop ? fading.left : fading.right
      const topOpacity = leftOnTop ? fading.position : 1 - fading.position
      visible = true
      opacity = layer.id === top ? topOpacity : 1
    }
    looks.set(layer.id, { visible, opacity })
  }
  return looks
}

export function syncCinematicLayers(
  map: MapLibreMap,
  layers: Layer[],
  state: Pick<MapStore, 'visible' | 'opacity' | 'compare'>,
) {
  for (const [id, look] of cinematicLayerLooks(layers, state)) {
    const layer = layers.find((item) => item.id === id)
    const mapId = `firetrace-${id}`
    if (!layer || !map.getLayer(mapId)) continue
    const visibility = look.visible ? 'visible' : 'none'
    map.setLayoutProperty(mapId, 'visibility', visibility)
    map.setPaintProperty(
      mapId,
      layer.kind === 'raster' ? 'raster-opacity' : 'line-opacity',
      look.opacity,
    )
    if (map.getLayer(`${mapId}-glow`))
      map.setLayoutProperty(`${mapId}-glow`, 'visibility', visibility)
  }
}
