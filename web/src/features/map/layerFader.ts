/** Time constant of the opacity follower: ~95 % of a change after 3τ. */
export const FADE_TIME_CONSTANT_MS = 350
const SETTLED = 0.004

export interface LayerFader {
  /** New target opacities; layers not listed keep their target. */
  set(targets: ReadonlyMap<string, number>): void
  /** Cancels any running fade. */
  stop(): void
}

/**
 * Eases layer opacities towards their targets instead of switching them, so
 * story steps dissolve into each other. It is a damped follower, not a fixed
 * tween: targets that change every frame (the comparison crossfade) are
 * followed smoothly with a short lag, and a new step can interrupt a fade at
 * any point without a jump. A layer seen for the first time fades in from 0.
 * `instant` (reduced motion) writes the targets straight away.
 */
export function createLayerFader(
  write: (id: string, opacity: number) => void,
  {
    instant = false,
    timeConstantMs = FADE_TIME_CONSTANT_MS,
    requestFrame = (callback: FrameRequestCallback) =>
      requestAnimationFrame(callback),
    cancelFrame = (handle: number) => cancelAnimationFrame(handle),
  }: {
    instant?: boolean
    timeConstantMs?: number
    requestFrame?: (callback: FrameRequestCallback) => number
    cancelFrame?: (handle: number) => void
  } = {},
): LayerFader {
  const shown = new Map<string, number>()
  const targets = new Map<string, number>()
  let handle: number | null = null
  let last: number | null = null

  const tick = (now: number) => {
    handle = null
    const elapsed = last === null ? 16 : Math.max(0, now - last)
    last = now
    const k = 1 - Math.exp(-elapsed / timeConstantMs)
    let moving = false
    for (const [id, target] of targets) {
      const from = shown.get(id) ?? 0
      if (from === target) continue
      let next = from + (target - from) * k
      if (Math.abs(target - next) < SETTLED) next = target
      else moving = true
      shown.set(id, next)
      write(id, next)
    }
    if (moving) handle = requestFrame(tick)
    else last = null
  }

  return {
    set(next) {
      for (const [id, value] of next) targets.set(id, value)
      if (instant) {
        for (const [id, value] of next) {
          if (shown.get(id) === value) continue
          shown.set(id, value)
          write(id, value)
        }
        return
      }
      if (handle === null) handle = requestFrame(tick)
    },
    stop() {
      if (handle !== null) cancelFrame(handle)
      handle = null
      last = null
    },
  }
}
