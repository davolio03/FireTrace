import type { StoryStep } from '../../state/mapStore'

/** Production guided story (contracts/schemas/story.schema.json). */
export interface Story {
  contract_version: string
  case_id: string
  title: string
  steps: StoryStep[]
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

const finite = (value: unknown): value is number =>
  typeof value === 'number' && Number.isFinite(value)

const lonLat = (value: unknown) =>
  Array.isArray(value) && value.length === 2 && value.every(finite)

function stepIsPlayable(step: unknown): boolean {
  if (!record(step)) return false
  const { id, title, body_md, camera, layers } = step
  return (
    typeof id === 'string' &&
    typeof title === 'string' &&
    typeof body_md === 'string' &&
    record(camera) &&
    lonLat(camera.center) &&
    finite(camera.zoom) &&
    (camera.duration_ms === undefined ||
      (finite(camera.duration_ms) && camera.duration_ms >= 0)) &&
    record(layers) &&
    Array.isArray(layers.visible) &&
    layers.visible.every((layer) => typeof layer === 'string')
  )
}

/**
 * Checks the fields the player relies on. The full JSON Schema check runs in
 * CI with `contracts/tools/validate.py --story web/src/story/story.json`.
 * Returns null when the story cannot be played.
 */
export function parseStory(value: unknown): Story | null {
  if (
    !record(value) ||
    typeof value.case_id !== 'string' ||
    typeof value.title !== 'string' ||
    !Array.isArray(value.steps) ||
    value.steps.length === 0 ||
    !value.steps.every(stepIsPlayable)
  )
    return null
  return value as unknown as Story
}
