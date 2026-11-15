import { describe, expect, it } from 'vitest'
import type { StoryStep } from '../../state/mapStore'
import {
  MAX_READ_MS,
  MIN_READ_MS,
  stepDwellMs,
  storyDurationMs,
} from './timing'

const step = (words: number, duration_ms?: number): StoryStep => ({
  id: 'step',
  title: 'Step',
  body_md: Array.from({ length: words }, () => 'word').join(' '),
  camera: { center: [-121.4, 35.9], zoom: 10, duration_ms },
  layers: { visible: [] },
})

describe('story timing', () => {
  it('adds the camera animation to the reading time', () => {
    expect(stepDwellMs(step(30, 2000))).toBe(2000 + 30 * 300 + 5000)
  })

  it('keeps reading time between the minimum and maximum', () => {
    expect(stepDwellMs(step(1))).toBe(MIN_READ_MS)
    expect(stepDwellMs(step(500))).toBe(MAX_READ_MS)
  })

  it('sums the steps', () => {
    expect(storyDurationMs([step(1), step(500, 1000)])).toBe(
      MIN_READ_MS + MAX_READ_MS + 1000,
    )
  })
})
