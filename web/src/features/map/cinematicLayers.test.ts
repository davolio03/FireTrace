import { describe, expect, it } from 'vitest'
import manifest from '../../../../contracts/fixtures/web/layers.json'
import type { Layer } from './layers'
import { cinematicLayerLooks, storyMapLayers } from './cinematicLayers'

const layers = manifest.layers as Layer[]
const story = storyMapLayers(layers)

describe('cinematic layers', () => {
  it('adds the highlight to the layers the analysis map draws', () => {
    const ids = story.map((layer) => layer.id)
    expect(ids).toContain('highlight_mask')
    expect(ids).toContain('perimeter')
    expect(ids).not.toContain('review_zones')
    expect(ids).not.toContain('valid_mask')
  })

  it('follows shared visibility and opacity without a comparison', () => {
    const looks = cinematicLayerLooks(story, {
      visible: ['change_index', 'perimeter'],
      opacity: { change_index: 0.4 },
      compare: null,
    })
    expect(looks.get('change_index')).toEqual({ visible: true, opacity: 0.4 })
    expect(looks.get('sar_t1_hv')?.visible).toBe(false)
  })

  it('turns a comparison into a crossfade of the upper layer', () => {
    // optical_during is drawn above sar_t2_hv in the manifest order.
    const start = cinematicLayerLooks(story, {
      visible: [],
      opacity: {},
      compare: { left: 'optical_during', right: 'sar_t2_hv', position: 0.9 },
    })
    expect(start.get('optical_during')).toEqual({ visible: true, opacity: 0.9 })
    expect(start.get('sar_t2_hv')).toEqual({ visible: true, opacity: 1 })
    // sar_t2_hv is drawn above sar_t1_hv: the right layer fades in.
    const fade = cinematicLayerLooks(story, {
      visible: [],
      opacity: {},
      compare: { left: 'sar_t1_hv', right: 'sar_t2_hv', position: 0.15 },
    })
    expect(fade.get('sar_t1_hv')).toEqual({ visible: true, opacity: 1 })
    expect(fade.get('sar_t2_hv')?.opacity).toBeCloseTo(0.85, 9)
  })

  it('ignores comparisons with missing layers', () => {
    const looks = cinematicLayerLooks(story, {
      visible: ['perimeter'],
      opacity: {},
      compare: { left: 'review_zones', right: 'sar_t2_hv', position: 0.5 },
    })
    expect(looks.get('sar_t2_hv')?.visible).toBe(false)
  })
})
