import { describe, expect, it, vi } from 'vitest'
import storyFixture from '../../../contracts/fixtures/web/story.json'
import { createMapStore, type StoryStep } from './mapStore'

describe('shared map state', () => {
  it('stores camera updates without controlling MapLibre', () => {
    const store = createMapStore()
    const camera = { center: [-121.4, 35.9] as [number, number], zoom: 12 }
    store.getState().flyTo(camera, 500)
    expect(store.getState().camera).toEqual(camera)
  })

  it('sets and toggles visible layers without duplicates and stores opacity', () => {
    const store = createMapStore()
    store.getState().setVisible(['perimeter', 'perimeter', 'sar_t1_hh'])
    expect(store.getState().visible).toEqual(['perimeter', 'sar_t1_hh'])
    store.getState().toggleLayer('perimeter')
    store.getState().toggleLayer('sar_t2_hh')
    store.getState().setOpacity('sar_t2_hh', 0.4)
    expect(store.getState().visible).toEqual(['sar_t1_hh', 'sar_t2_hh'])
    expect(store.getState().opacity.sar_t2_hh).toBe(0.4)
  })

  it('sets, animates as a stub, and disables comparison', () => {
    const store = createMapStore()
    store
      .getState()
      .setCompare({ left: 'sar_t1_hh', right: 'sar_t2_hh', position: 0.5 })
    store.getState().animateCompare(0.2, 1000)
    expect(store.getState().compare?.position).toBe(0.2)
    store.getState().setCompare(null)
    store.getState().animateCompare(0.7, 1000)
    expect(store.getState().compare).toBeNull()
  })

  it('selects the matching panel and switches tools', () => {
    const store = createMapStore()
    store.getState().select({ type: 'point', point: [-121.4, 35.9] })
    expect(store.getState().panel).toBe('inspector')
    store.getState().select({ type: 'zone', zoneId: 'CO-1' })
    expect(store.getState().panel).toBe('zones')
    store.getState().select({
      type: 'profile',
      line: [
        [-121.4, 35.9],
        [-121.41, 35.91],
      ],
    })
    expect(store.getState().panel).toBe('profile')
    store.getState().select({ type: 'none' })
    expect(store.getState().panel).toBe('none')
    store.getState().setTool('draw-profile')
    expect(store.getState().tool).toBe('draw-profile')
    store.getState().setStory({ active: true, stepIndex: 1 })
    expect(store.getState().story).toEqual({ active: true, stepIndex: 1 })
  })

  it('applies story fields through the same public actions', () => {
    const store = createMapStore()
    const calls = {
      flyTo: vi.fn(store.getState().flyTo),
      setVisible: vi.fn(store.getState().setVisible),
      setOpacity: vi.fn(store.getState().setOpacity),
      setCompare: vi.fn(store.getState().setCompare),
      animateCompare: vi.fn(store.getState().animateCompare),
      select: vi.fn(store.getState().select),
      setPanel: vi.fn(store.getState().setPanel),
    }
    store.setState(calls)
    const step: StoryStep = {
      id: 'test',
      title: 'Test',
      body_md: 'Mock',
      camera: { center: [-121.4, 35.9], zoom: 12, duration_ms: 400 },
      layers: { visible: ['perimeter'], opacity: { perimeter: 0.4 } },
      compare: {
        left: 'sar_t1_hh',
        right: 'sar_t2_hh',
        position: 0.5,
        animate_to: 0.2,
      },
      focus: { type: 'zone', zone_id: 'CO-1' },
      panel: 'metrics',
    }
    store.getState().applyStoryStep(step)
    expect(calls.flyTo).toHaveBeenCalledWith(
      { center: [-121.4, 35.9], zoom: 12 },
      400,
    )
    expect(calls.setVisible).toHaveBeenCalledWith(['perimeter'])
    expect(calls.setOpacity).toHaveBeenCalledWith('perimeter', 0.4)
    expect(calls.setCompare).toHaveBeenCalledWith({
      left: 'sar_t1_hh',
      right: 'sar_t2_hh',
      position: 0.5,
    })
    expect(calls.animateCompare).toHaveBeenCalledWith(0.2, 400)
    expect(calls.select).toHaveBeenCalledWith({ type: 'zone', zoneId: 'CO-1' })
    expect(calls.setPanel).toHaveBeenCalledWith('metrics')
    expect(store.getState().panel).toBe('metrics')
  })

  it('clears comparison and selection when the story step omits them', () => {
    const store = createMapStore()
    store
      .getState()
      .setCompare({ left: 'sar_t1_hh', right: 'sar_t2_hh', position: 0.5 })
    store.getState().select({ type: 'zone', zoneId: 'CO-1' })
    store.getState().applyStoryStep({
      id: 'context',
      title: 'Context',
      body_md: '',
      camera: { center: [-121.4, 35.9], zoom: 10 },
      layers: { visible: ['perimeter'] },
    })
    expect(store.getState().compare).toBeNull()
    expect(store.getState().selection).toEqual({ type: 'none' })
    expect(store.getState().panel).toBe('none')
  })

  it('accepts every contract story fixture step', () => {
    const store = createMapStore()
    for (const step of storyFixture.steps as StoryStep[]) {
      store.getState().applyStoryStep(step)
      expect(store.getState().camera.center).toEqual(step.camera.center)
      expect(store.getState().visible).toEqual(step.layers.visible)
      if (step.panel) expect(store.getState().panel).toBe(step.panel)
    }
  })

  it('applies valid zero-valued story fields', () => {
    const store = createMapStore()
    store.getState().applyStoryStep({
      id: 'zero',
      title: '',
      body_md: '',
      camera: { center: [0, 0], zoom: 0, duration_ms: 0 },
      layers: { visible: [], opacity: { perimeter: 0 } },
      compare: {
        left: 'perimeter',
        right: 'slope',
        position: 0,
        animate_to: 0,
      },
      focus: { type: 'point', point: [0, 0] },
      panel: 'weather',
    })
    expect(store.getState()).toMatchObject({
      camera: { center: [0, 0], zoom: 0 },
      visible: [],
      opacity: { perimeter: 0 },
      compare: { left: 'perimeter', right: 'slope', position: 0 },
      selection: { type: 'point', point: [0, 0] },
      panel: 'weather',
    })
  })
})
