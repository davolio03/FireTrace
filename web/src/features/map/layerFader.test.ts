import { describe, expect, it, vi } from 'vitest'
import { createLayerFader } from './layerFader'

function frames() {
  const queue: FrameRequestCallback[] = []
  return {
    requestFrame: (callback: FrameRequestCallback) => queue.push(callback),
    cancelFrame: vi.fn(),
    run(fromMs: number, toMs: number, stepMs = 16) {
      for (let t = fromMs; t <= toMs && queue.length > 0; t += stepMs)
        queue.shift()!(t)
    },
    get pending() {
      return queue.length
    },
  }
}

describe('layer fader', () => {
  it('eases a new layer in from 0 and settles on the target', () => {
    const clock = frames()
    const write = vi.fn()
    const fader = createLayerFader(write, clock)
    fader.set(new Map([['a', 0.8]]))
    clock.run(0, 3000)
    const values = write.mock.calls.map(([, value]) => value as number)
    expect(values[0]).toBeGreaterThan(0)
    expect(values[0]).toBeLessThan(0.1)
    for (let i = 1; i < values.length; i++)
      expect(values[i]).toBeGreaterThan(values[i - 1])
    expect(values.at(-1)).toBe(0.8)
    expect(clock.pending).toBe(0)
  })

  it('turns around mid-fade without jumping', () => {
    const clock = frames()
    const write = vi.fn()
    const fader = createLayerFader(write, clock)
    fader.set(new Map([['a', 1]]))
    clock.run(0, 300)
    const reached = write.mock.lastCall![1] as number
    fader.set(new Map([['a', 0]]))
    clock.run(316, 316)
    const next = write.mock.lastCall![1] as number
    expect(next).toBeLessThan(reached)
    expect(reached - next).toBeLessThan(0.1)
    clock.run(332, 5000)
    expect(write.mock.lastCall![1]).toBe(0)
  })

  it('writes targets at once under reduced motion', () => {
    const clock = frames()
    const write = vi.fn()
    const fader = createLayerFader(write, { ...clock, instant: true })
    fader.set(new Map([['a', 0.5]]))
    expect(write).toHaveBeenCalledWith('a', 0.5)
    expect(clock.pending).toBe(0)
  })
})
