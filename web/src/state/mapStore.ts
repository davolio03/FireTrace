import { useStore } from 'zustand'
import { createStore } from 'zustand/vanilla'
import type { components } from '../generated/api'

export type LayerId = components['schemas']['layer']['id']
export type LonLat = [number, number]
export interface Camera {
  center: LonLat
  zoom: number
  bearing?: number
  pitch?: number
}
export type Selection =
  | { type: 'none' }
  | { type: 'point'; point: LonLat }
  | { type: 'zone'; zoneId: string }
  | { type: 'profile'; line: LonLat[] }
export type Panel =
  'none' | 'inspector' | 'zones' | 'metrics' | 'weather' | 'profile'
export type Tool = 'pan' | 'inspect' | 'draw-profile'
export type Compare = { left: LayerId; right: LayerId; position: number }
export interface StoryStep {
  id: string
  title: string
  body_md: string
  camera: Camera & { duration_ms?: number }
  layers: { visible: LayerId[]; opacity?: Partial<Record<LayerId, number>> }
  compare?: Compare & { animate_to?: number }
  focus?:
    | { type: 'point'; point: LonLat }
    | { type: 'zone'; zone_id: string }
    | { type: 'profile'; line: LonLat[] }
  panel?: Panel
}

export interface MapStore {
  camera: Camera
  /** Animation duration requested by the last flyTo; 0 means jump. */
  cameraDurationMs: number
  visible: LayerId[]
  opacity: Partial<Record<LayerId, number>>
  compare: Compare | null
  selection: Selection
  panel: Panel
  tool: Tool
  story: { active: boolean; stepIndex: number }
  flyTo: (camera: Camera, durationMs?: number) => void
  setVisible: (ids: LayerId[]) => void
  toggleLayer: (id: LayerId) => void
  setOpacity: (id: LayerId, value: number) => void
  setCompare: (config: Compare | null) => void
  animateCompare: (to: number, ms: number) => void
  select: (selection: Selection) => void
  setPanel: (panel: Panel) => void
  setTool: (tool: Tool) => void
  setStory: (story: { active: boolean; stepIndex: number }) => void
  applyStoryStep: (step: StoryStep) => void
}

const panelForSelection: Record<Selection['type'], Panel> = {
  none: 'none',
  point: 'inspector',
  zone: 'zones',
  profile: 'profile',
}

/** Camera before anyone (map fit, user or story) has moved it. */
export const initialCamera: Readonly<Camera> = Object.freeze({
  center: [-121.47, 35.92] as LonLat,
  zoom: 9,
})

export function isInitialCamera(camera: Camera) {
  return (
    camera.center[0] === initialCamera.center[0] &&
    camera.center[1] === initialCamera.center[1] &&
    camera.zoom === initialCamera.zoom &&
    (camera.bearing ?? 0) === 0 &&
    (camera.pitch ?? 0) === 0
  )
}

function prefersReducedMotion() {
  return (
    typeof window !== 'undefined' &&
    window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true
  )
}

const easeInOutCubic = (t: number) =>
  t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2

const clamp01 = (value: number) => Math.min(1, Math.max(0, value))

export function createMapStore() {
  // At most one swipe animation runs per store; any new swipe change cancels it.
  let compareFrame: number | null = null
  const cancelCompareAnimation = () => {
    if (compareFrame !== null) cancelAnimationFrame(compareFrame)
    compareFrame = null
  }
  return createStore<MapStore>()((set, get) => ({
    camera: { center: [...initialCamera.center], zoom: initialCamera.zoom },
    cameraDurationMs: 0,
    visible: [],
    opacity: {},
    compare: null,
    selection: { type: 'none' },
    panel: 'none',
    tool: 'pan',
    story: { active: false, stepIndex: 0 },
    // features/map animates the map to `camera` over `cameraDurationMs`.
    flyTo: (camera, durationMs = 0) =>
      set({ camera, cameraDurationMs: Math.max(0, durationMs) }),
    setVisible: (ids) => set({ visible: [...new Set(ids)] }),
    toggleLayer: (id) =>
      set((state) => ({
        visible: state.visible.includes(id)
          ? state.visible.filter((layer) => layer !== id)
          : [...state.visible, id],
      })),
    setOpacity: (id, value) =>
      set((state) => ({ opacity: { ...state.opacity, [id]: value } })),
    setCompare: (compare) => {
      cancelCompareAnimation()
      set({ compare })
    },
    animateCompare: (to, ms) => {
      cancelCompareAnimation()
      const start = get().compare
      if (!start) return
      const target = clamp01(to)
      if (
        ms <= 0 ||
        prefersReducedMotion() ||
        typeof requestAnimationFrame !== 'function'
      ) {
        set({ compare: { ...start, position: target } })
        return
      }
      const from = start.position
      const startedAt = performance.now()
      const step = (now: number) => {
        const current = get().compare
        if (!current) {
          compareFrame = null
          return
        }
        const progress = clamp01((now - startedAt) / ms)
        set({
          compare: {
            ...current,
            position: from + (target - from) * easeInOutCubic(progress),
          },
        })
        compareFrame = progress < 1 ? requestAnimationFrame(step) : null
      }
      compareFrame = requestAnimationFrame(step)
    },
    select: (selection) =>
      set({ selection, panel: panelForSelection[selection.type] }),
    setPanel: (panel) => set({ panel }),
    setTool: (tool) => set({ tool }),
    setStory: (story) => set({ story }),
    applyStoryStep: (step) => {
      const { duration_ms, ...camera } = step.camera
      get().flyTo(camera, duration_ms)
      get().setVisible(step.layers.visible)
      for (const [id, value] of Object.entries(step.layers.opacity ?? {})) {
        get().setOpacity(id as LayerId, value)
      }
      if (step.compare) {
        const { animate_to, ...compare } = step.compare
        get().setCompare(compare)
        if (animate_to !== undefined)
          get().animateCompare(animate_to, duration_ms ?? 0)
      } else {
        get().setCompare(null)
      }
      const focus = step.focus
      const selection: Selection = !focus
        ? { type: 'none' }
        : focus.type === 'zone'
          ? { type: 'zone', zoneId: focus.zone_id }
          : focus
      get().select(selection)
      if (step.panel !== undefined) get().setPanel(step.panel)
    },
  }))
}

export const mapStore = createMapStore()
export function useMapStore<T>(selector: (state: MapStore) => T): T {
  return useStore(mapStore, selector)
}
