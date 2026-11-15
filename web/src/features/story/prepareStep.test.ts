import { describe, expect, it } from 'vitest'
import manifest from '../../../../contracts/fixtures/web/layers.json'
import type { StoryStep } from '../../state/mapStore'
import type { Layer } from '../map/layers'
import { prepareStep } from './prepareStep'

const layers = manifest.layers as Layer[]
const base: StoryStep = {
  id: 'step',
  title: 'Step',
  body_md: 'Text',
  camera: { center: [-121.4, 35.9], zoom: 11, duration_ms: 2000 },
  layers: {
    visible: ['change_index', 'highlight_mask', 'perimeter'],
    opacity: { change_index: 0.5, highlight_mask: 0.9 },
  },
  compare: {
    left: 'sar_t1_hv',
    right: 'sar_t2_hv',
    position: 0.5,
    animate_to: 0.15,
  },
}

describe('prepareStep', () => {
  it('keeps only layers the map can draw', () => {
    const step = prepareStep(base, { layers, reducedMotion: false })
    expect(step.layers.visible).toEqual(['change_index', 'perimeter'])
    expect(step.layers.opacity).toEqual({ change_index: 0.5 })
    expect(step.compare).toEqual(base.compare)
    expect(step.camera.duration_ms).toBe(2000)
  })

  it('drops everything when no manifest is loaded', () => {
    const step = prepareStep(base, { layers: [], reducedMotion: false })
    expect(step.layers.visible).toEqual([])
    expect(step.compare).toBeUndefined()
  })

  it('removes comparisons the comparator does not support', () => {
    const step = prepareStep(
      {
        ...base,
        compare: { left: 'change_index', right: 'sar_t2_hv', position: 0.5 },
      },
      { layers, reducedMotion: false },
    )
    expect(step.compare).toBeUndefined()
  })

  it('disables animations under reduced motion', () => {
    const step = prepareStep(base, { layers, reducedMotion: true })
    expect(step.camera.duration_ms).toBe(0)
    expect(step.compare).toEqual({
      left: 'sar_t1_hv',
      right: 'sar_t2_hv',
      position: 0.15,
    })
  })

  it('skips zone focus while there is no zones panel', () => {
    const step = prepareStep(
      { ...base, focus: { type: 'zone', zone_id: 'CO-01' } },
      { layers, reducedMotion: false },
    )
    expect(step.focus).toBeUndefined()
    const point = prepareStep(
      { ...base, focus: { type: 'point', point: [-121.38, 35.96] } },
      { layers, reducedMotion: false },
    )
    expect(point.focus).toEqual({ type: 'point', point: [-121.38, 35.96] })
  })
})
