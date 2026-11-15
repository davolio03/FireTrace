import type { StoryStep } from '../../state/mapStore'

/** About 200 words per minute, plus a few seconds to look at the map. */
export const READ_MS_PER_WORD = 300
export const BASE_MS = 5_000
export const MIN_READ_MS = 12_000
export const MAX_READ_MS = 22_000

const clamp = (value: number, min: number, max: number) =>
  Math.min(max, Math.max(min, value))

/** How long autoplay stays on a step: its camera animation plus reading time. */
export function stepDwellMs(step: StoryStep) {
  const words = step.body_md.trim().split(/\s+/).filter(Boolean).length
  return (
    (step.camera.duration_ms ?? 0) +
    clamp(words * READ_MS_PER_WORD + BASE_MS, MIN_READ_MS, MAX_READ_MS)
  )
}

export function storyDurationMs(steps: StoryStep[]) {
  return steps.reduce((total, step) => total + stepDwellMs(step), 0)
}
