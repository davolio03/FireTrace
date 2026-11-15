import { describe, expect, it } from 'vitest'
import caseFixture from '../../../../contracts/fixtures/web/case.json'
import manifest from '../../../../contracts/fixtures/web/layers.json'
import storyJson from '../../story/story.json'
import storyFixture from '../../../../contracts/fixtures/web/story.json'
import { storyMapLayers } from '../map/cinematicLayers'
import type { Layer } from '../map/layers'
import { parseStory } from './story'
import { storyDurationMs } from './timing'

const layers = manifest.layers as Layer[]
const story = parseStory(storyJson)!

describe('production story', () => {
  it('is playable and written for this case', () => {
    expect(story).not.toBeNull()
    expect(story.contract_version).toBe('1.2.0')
    expect(story.case_id).toBe(caseFixture.case_id)
    expect(story.steps.length).toBeGreaterThanOrEqual(5)
    expect(story.steps.length).toBeLessThanOrEqual(10)
  })

  it('respects the schema limits for ids, titles and text', () => {
    const ids = story.steps.map((step) => step.id)
    expect(new Set(ids).size).toBe(ids.length)
    for (const step of story.steps) {
      expect(step.id).toMatch(/^[a-z0-9-]+$/)
      expect(step.title.length).toBeLessThanOrEqual(80)
      expect(step.body_md.length).toBeLessThanOrEqual(600)
    }
  })

  it('only names layers the story map draws', () => {
    const drawn = new Set(storyMapLayers(layers).map((layer) => layer.id))
    for (const step of story.steps) {
      for (const id of step.layers.visible) expect(drawn).toContain(id)
      if (step.compare) {
        expect(drawn).toContain(step.compare.left)
        expect(drawn).toContain(step.compare.right)
      }
    }
  })

  it('opens from orbit and tilts the camera over the fire', () => {
    expect(story.steps[0].id).toBe('orbit')
    expect(story.steps[0].camera.zoom).toBeLessThan(4)
    for (const step of story.steps.slice(1))
      expect(step.camera.pitch ?? 0).toBeGreaterThan(30)
  })

  it('does not rely on mock-only review zones', () => {
    for (const step of story.steps) {
      expect(step.focus?.type).not.toBe('zone')
      expect(step.layers.visible).not.toContain('review_zones')
    }
  })

  it('plays in about two minutes (DEMO.md: 90-120 s)', () => {
    const seconds = storyDurationMs(story.steps) / 1000
    expect(seconds).toBeGreaterThanOrEqual(90)
    expect(seconds).toBeLessThanOrEqual(130)
  })

  it('avoids claims the radar cannot support', () => {
    const text = story.steps
      .map((step) => step.body_md)
      .join(' ')
      .toLowerCase()
    expect(text).not.toMatch(/burned area|burn severity|confirmed burn/)
    expect(text).not.toMatch(/wet(ter)? soil|\brain(fall|ed|y)?\b/)
    expect(text).toContain('not confirmed fire')
  })

  it('still accepts the contract fixture story', () => {
    expect(parseStory(storyFixture)).not.toBeNull()
  })
})

describe('parseStory', () => {
  it('rejects stories the player cannot play', () => {
    expect(parseStory(null)).toBeNull()
    expect(parseStory({ ...storyJson, steps: [] })).toBeNull()
    expect(
      parseStory({
        ...storyJson,
        steps: [{ ...storyJson.steps[0], camera: { zoom: 10 } }],
      }),
    ).toBeNull()
    expect(
      parseStory({
        ...storyJson,
        steps: [
          {
            ...storyJson.steps[0],
            camera: { ...storyJson.steps[0].camera, duration_ms: -1 },
          },
        ],
      }),
    ).toBeNull()
  })
})
