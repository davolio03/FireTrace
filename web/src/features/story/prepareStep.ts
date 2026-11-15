import type { LayerId, StoryStep } from '../../state/mapStore'
import { storyMapLayers } from '../map/cinematicLayers'
import type { Layer } from '../map/layers'

export interface StepContext {
  /** Layers from the loaded manifest. */
  layers: Layer[]
  reducedMotion: boolean
}

/**
 * Adapts a story step to what the story map can show right now, so a step
 * never asks for something a user could not do: layers it does not draw are
 * dropped, comparisons need both layers (the story map crossfades them), zone
 * focus is skipped (there is no zones panel yet) and animations are disabled
 * under reduced motion.
 */
export function prepareStep(step: StoryStep, context: StepContext): StoryStep {
  const drawable = new Set<LayerId>(
    storyMapLayers(context.layers).map((layer) => layer.id),
  )
  const visible = step.layers.visible.filter((id) => drawable.has(id))
  const opacity = Object.fromEntries(
    Object.entries(step.layers.opacity ?? {}).filter(([id]) =>
      drawable.has(id as LayerId),
    ),
  ) as Partial<Record<LayerId, number>>

  let compare = step.compare
  if (compare && !(drawable.has(compare.left) && drawable.has(compare.right))) {
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
