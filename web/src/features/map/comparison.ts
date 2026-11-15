import type { Compare, LayerId } from '../../state/mapStore'
import type { Layer } from './layers'

export type Polarization = 'HH' | 'HV'

export function comparisonPair(
  polarization: Polarization,
): Pick<Compare, 'left' | 'right'> {
  return polarization === 'HH'
    ? { left: 'sar_t1_hh', right: 'sar_t2_hh' }
    : { left: 'sar_t1_hv', right: 'sar_t2_hv' }
}

export function isSupportedComparison(
  compare: Compare | null,
  layers: Layer[],
) {
  if (!compare) return false
  const pairMatches =
    (['HH', 'HV'] as const).some((polarization) => {
      const pair = comparisonPair(polarization)
      return compare.left === pair.left && compare.right === pair.right
    }) ||
    (['optical_during', 'optical_after'].includes(compare.left) &&
      ['sar_t1_hh', 'sar_t2_hh', 'sar_t1_hv', 'sar_t2_hv'].includes(
        compare.right,
      ))
  const available = (id: LayerId) =>
    layers.some(
      (layer) =>
        layer.id === id &&
        layer.kind === 'raster' &&
        !!layer.url &&
        layer.coordinates?.length === 4,
    )
  return pairMatches && available(compare.left) && available(compare.right)
}

export function comparisonLabel(
  id: LayerId,
  layers: Layer[],
  dates: { before: string; after: string },
) {
  const layer = layers.find((item) => item.id === id)
  if (id.startsWith('optical_'))
    return `${layer?.title ?? 'Optical image'} — ${typeof layer?.acquired === 'string' ? layer.acquired : 'Date unavailable'}`
  const date = id.startsWith('sar_t1_') ? dates.before : dates.after
  return `${id.startsWith('sar_t1_') ? 'Before' : 'After'} — ${date} — ${id.endsWith('_hv') ? 'HV' : 'HH'}`
}
