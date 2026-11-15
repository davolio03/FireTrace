import type { LayerId, StoryStep } from '../../state/mapStore'
import { isSupportedComparison } from '../map/comparison'
import { type Layer, visibleMapLayers } from '../map/layers'

export interface StepContext {
  /** Layers from the loaded manifest. */
  layers: Layer[]
  reducedMotion: boolean
}

/**
 * Adapts a story step to what the app can show right now, so a step never
 * asks for something a user could not do: layers the map does not draw are
 * dropped, unsupported comparisons are removed, zone focus is skipped (there
 * is no zones panel yet) and animations are disabled under reduced motion.
 */
export function prepareStep(step: StoryStep, context: StepContext): StoryStep {
  const drawable = new Set<LayerId>(
    visibleMapLayers(context.layers).map((layer) => layer.id),
  )
  const visible = step.layers.visible.filter((id) => drawable.has(id))
  const opacity = Object.fromEntries(
    Object.entries(step.layers.opacity ?? {}).filter(([id]) =>
      drawable.has(id as LayerId),
    ),
  ) as Partial<Record<LayerId, number>>

  let compare = step.compare
  if (compare && !isSupportedComparison(compare, context.layers)) {
    compare = undefined
  }
  const camera = { ...step.camera }
  if (context.reducedMotion) {
    camera.duration_ms = 0
    if (compare) {
      const { animate_to, ...rest } = compare
      compare = { ...rest, position: animate_to ?? rest.position }
    }
  }

  const prepared: StoryStep = {
    ...step,
    camera,
    layers: { visible, opacity },
  }
  if (compare) prepared.compare = compare
  else delete prepared.compare
  if (step.focus?.type === 'zone') delete prepared.focus
  return prepared
}
