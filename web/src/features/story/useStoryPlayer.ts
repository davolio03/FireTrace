import { useCallback, useEffect, useReducer, useRef, useState } from 'react'
import { mapStore } from '../../state/mapStore'
import type { Layer } from '../map/layers'
import { prepareStep } from './prepareStep'
import type { Story } from './story'
import { stepDwellMs } from './timing'

export type StoryStatus = 'idle' | 'playing' | 'paused' | 'ended' | 'exploring'

interface PlayerState {
  status: StoryStatus
  index: number
  /** Increments every time a step must be (re)applied to the map. */
  applied: number
}

type PlayerAction =
  | { type: 'start'; index: number }
  | { type: 'play' }
  | { type: 'pause' }
  | { type: 'next' }
  | { type: 'prev' }
  | { type: 'goTo'; index: number }
  | { type: 'advance' }
  | { type: 'exit' }
  | { type: 'resume' }

function reducer(count: number) {
  return (state: PlayerState, action: PlayerAction): PlayerState => {
    const last = count - 1
    const applyAt = (index: number, status: StoryStatus): PlayerState => ({
      status,
      index: Math.min(last, Math.max(0, index)),
      applied: state.applied + 1,
    })
    switch (action.type) {
      case 'start':
        return applyAt(action.index, 'playing')
      case 'play':
        if (state.status === 'paused') return { ...state, status: 'playing' }
        if (state.status === 'ended') return applyAt(0, 'playing')
        return state
      case 'pause':
        return state.status === 'playing'
          ? { ...state, status: 'paused' }
          : state
      case 'advance':
        if (state.status !== 'playing') return state
        return state.index < last
          ? applyAt(state.index + 1, 'playing')
          : { ...state, status: 'ended' }
      case 'next':
        if (state.index >= last) return state
        return applyAt(
          state.index + 1,
          state.status === 'playing' ? 'playing' : 'paused',
        )
      case 'prev':
        if (state.index <= 0) return state
        return applyAt(
          state.index - 1,
          state.status === 'playing' ? 'playing' : 'paused',
        )
      case 'goTo':
        return applyAt(
          action.index,
          state.status === 'playing' ? 'playing' : 'paused',
        )
      case 'exit':
        return state.status === 'idle' || state.status === 'exploring'
          ? state
          : { ...state, status: 'exploring' }
      case 'resume':
        return applyAt(state.index, 'playing')
    }
  }
}

export function usePrefersReducedMotion() {
  const query = '(prefers-reduced-motion: reduce)'
  const [reduced, setReduced] = useState(
    () =>
      typeof window !== 'undefined' &&
      window.matchMedia?.(query).matches === true,
  )
  useEffect(() => {
    const media = window.matchMedia?.(query)
    if (!media?.addEventListener) return
    const onChange = () => setReduced(media.matches)
    media.addEventListener('change', onChange)
    return () => media.removeEventListener('change', onChange)
  }, [])
  return reduced
}

const isTyping = (target: EventTarget | null) =>
  target instanceof HTMLElement &&
  (target.isContentEditable ||
    ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName))

/**
 * Plays a guided story through the shared store actions only. Autoplay waits
 * for an explicit start; it pauses when the tab is hidden; Esc leaves the
 * story and keeps whatever the map shows.
 */
export function useStoryPlayer(
  story: Story | null,
  layers: Layer[],
  reducedMotion: boolean,
  /** Called when the user leaves the story (Esc or `exit`). */
  onExit?: () => void,
) {
  const count = story?.steps.length ?? 0
  const [state, dispatch] = useReducer(reducer(count), {
    status: 'idle',
    index: 0,
    applied: 0,
  })
  const active = ['playing', 'paused', 'ended'].includes(state.status)
  const step = story?.steps[state.index] ?? null
  const dwellMs = step
    ? stepDwellMs(
        reducedMotion
          ? { ...step, camera: { ...step.camera, duration_ms: 0 } }
          : step,
      )
    : 0

  const exitHandler = useRef(onExit)
  useEffect(() => {
    exitHandler.current = onExit
  }, [onExit])
  const leave = useCallback(() => {
    dispatch({ type: 'exit' })
    exitHandler.current?.()
  }, [])

  // Latest context without re-applying a step when unrelated props change.
  // Effects run in order, so this refresh lands before the step is applied.
  const context = useRef({ layers, reducedMotion })
  useEffect(() => {
    context.current = { layers, reducedMotion }
  }, [layers, reducedMotion])
  const layersReady = layers.length > 0

  useEffect(() => {
    if (!story || state.applied === 0) return
    const current = story.steps[state.index]
    if (!current) return
    const { setTool, applyStoryStep } = mapStore.getState()
    setTool('pan')
    applyStoryStep(prepareStep(current, context.current))
  }, [story, state.applied, state.index, layersReady])

  useEffect(() => {
    mapStore.getState().setStory({ active, stepIndex: state.index })
  }, [active, state.index])

  // Autoplay timer; keeps the remaining time across pause and play.
  const remaining = useRef<{ applied: number; ms: number } | null>(null)
  useEffect(() => {
    if (state.status !== 'playing' || !step) return
    const ms =
      remaining.current?.applied === state.applied
        ? remaining.current.ms
        : dwellMs
    const startedAt = Date.now()
    const timer = setTimeout(() => dispatch({ type: 'advance' }), ms)
    return () => {
      clearTimeout(timer)
      remaining.current = {
        applied: state.applied,
        ms: Math.max(0, ms - (Date.now() - startedAt)),
      }
    }
  }, [state.status, state.applied, step, dwellMs])

  useEffect(() => {
    if (!active) return
    const onVisibility = () => {
      if (document.hidden) dispatch({ type: 'pause' })
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !isTyping(event.target)) leave()
    }
    document.addEventListener('visibilitychange', onVisibility)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('visibilitychange', onVisibility)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [active, leave])

  return {
    available: count > 0,
    status: state.status,
    active,
    index: state.index,
    count,
    step,
    dwellMs,
    /** Changes whenever a step is (re)applied; use it to restart progress. */
    applied: state.applied,
    start: useCallback((index = 0) => dispatch({ type: 'start', index }), []),
    play: useCallback(() => dispatch({ type: 'play' }), []),
    pause: useCallback(() => dispatch({ type: 'pause' }), []),
    next: useCallback(() => dispatch({ type: 'next' }), []),
    prev: useCallback(() => dispatch({ type: 'prev' }), []),
    goTo: useCallback((index: number) => dispatch({ type: 'goTo', index }), []),
    exit: leave,
    resume: useCallback(() => dispatch({ type: 'resume' }), []),
  }
}

export type StoryPlayerApi = ReturnType<typeof useStoryPlayer>
