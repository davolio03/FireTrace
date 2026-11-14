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

export function createMapStore() {
  return createStore<MapStore>()((set, get) => ({
    camera: { center: [-121.47, 35.92], zoom: 9 },
    visible: [],
    opacity: {},
    compare: null,
    selection: { type: 'none' },
    panel: 'none',
    tool: 'pan',
    story: { active: false, stepIndex: 0 },
    // Map animations are intentionally deferred to the map lane.
    flyTo: (camera) => set({ camera }),
    setVisible: (ids) => set({ visible: [...new Set(ids)] }),
    toggleLayer: (id) =>
      set((state) => ({
        visible: state.visible.includes(id)
          ? state.visible.filter((layer) => layer !== id)
          : [...state.visible, id],
      })),
    setOpacity: (id, value) =>
      set((state) => ({ opacity: { ...state.opacity, [id]: value } })),
    setCompare: (compare) => set({ compare }),
    animateCompare: (position) =>
      set((state) => ({
        compare: state.compare ? { ...state.compare, position } : null,
      })),
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
