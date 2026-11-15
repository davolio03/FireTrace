import type { components } from '../../generated/api'

export type Layer = components['schemas']['layer']

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function legendIsRenderable(value: unknown): boolean {
  if (!record(value)) return false
  if (value.note !== undefined && typeof value.note !== 'string') return false
  if (value.type === 'rgb') return true
  if (value.type === 'categorical') {
    return (
      Array.isArray(value.items) &&
      value.items.every(
        (item: unknown) =>
          record(item) &&
          (typeof item.value === 'string' || typeof item.value === 'number') &&
          typeof item.label === 'string' &&
          typeof item.color === 'string',
      )
    )
  }
  if (value.type === 'continuous') {
    return (
      typeof value.units === 'string' &&
      Array.isArray(value.stops) &&
      value.stops.every(
        (stop: unknown) =>
          record(stop) &&
          typeof stop.value === 'number' &&
          Number.isFinite(stop.value) &&
          typeof stop.color === 'string',
      )
    )
  }
  return false
}

export function layersAreRenderable(value: unknown): value is Layer[] {
  return (
    Array.isArray(value) &&
    value.every((layer: unknown) => {
      if (
        !record(layer) ||
        typeof layer.id !== 'string' ||
        typeof layer.title !== 'string' ||
        typeof layer.group !== 'string' ||
        (layer.kind !== 'raster' && layer.kind !== 'vector') ||
        typeof layer.url !== 'string' ||
        !layer.url.trim() ||
        typeof layer.default_visible !== 'boolean' ||
        typeof layer.default_opacity !== 'number' ||
        !Number.isFinite(layer.default_opacity) ||
        layer.default_opacity < 0 ||
        layer.default_opacity > 1 ||
        !legendIsRenderable(layer.legend)
      )
        return false
      if (layer.kind === 'raster') {
        return (
          Array.isArray(layer.coordinates) &&
          layer.coordinates.length === 4 &&
          layer.coordinates.every(
            (coordinate: unknown) =>
              Array.isArray(coordinate) &&
              coordinate.length === 2 &&
              coordinate.every(
                (n: unknown) => typeof n === 'number' && Number.isFinite(n),
              ),
          )
        )
      }
      return true
    })
  )
}

export function visibleMapLayers(layers: Layer[]) {
  return layers.filter(
    (layer) =>
      layer.group === 'sar' ||
      layer.group === 'observed_change' ||
      layer.id === 'perimeter' ||
      ['sar_t1_hh', 'sar_t2_hh', 'sar_t1_hv', 'sar_t2_hv'].includes(layer.id),
  )
}
