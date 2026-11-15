import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import manifest from '../../../../contracts/fixtures/web/layers.json'
import storyJson from '../../story/story.json'
import { initialCamera, mapStore } from '../../state/mapStore'
import type { Layer } from '../map/layers'
import { parseStory } from './story'
import { StoryPlayer } from './StoryPlayer'
import { stepDwellMs } from './timing'
import { useStoryPlayer } from './useStoryPlayer'

const layers = manifest.layers as Layer[]
const story = parseStory(storyJson)!
const steps = story.steps

function Harness({ reducedMotion = false }: { reducedMotion?: boolean }) {
  const player = useStoryPlayer(story, layers, reducedMotion)
  return (
    <div>
      <button type="button" onClick={() => player.start(0)}>
        Start story
      </button>
      <StoryPlayer player={player} isMock reducedMotion={reducedMotion} />
    </div>
  )
}

const heading = () => screen.getByRole('heading', { level: 2 }).textContent
const start = () => fireEvent.click(screen.getByText('Start story'))
const wait = (ms: number) => act(() => vi.advanceTimersByTime(ms))

describe('story player', () => {
  beforeEach(() => {
    vi.useFakeTimers({
      toFake: [
        'setTimeout',
        'clearTimeout',
        'Date',
        'requestAnimationFrame',
        'cancelAnimationFrame',
        'performance',
      ],
    })
    mapStore.setState({
      camera: { center: [...initialCamera.center], zoom: initialCamera.zoom },
      cameraDurationMs: 0,
      visible: [],
      opacity: {},
      compare: null,
      selection: { type: 'none' },
      panel: 'none',
      tool: 'pan',
      story: { active: false, stepIndex: 0 },
    })
  })
  afterEach(() => {
    cleanup()
    vi.useRealTimers()
  })

  it('waits for an explicit start', () => {
    render(<Harness />)
    wait(200_000)
    expect(screen.queryByRole('region', { name: 'Guided story' })).toBeNull()
    expect(mapStore.getState().story.active).toBe(false)
  })

  it('applies the first step through the store and focuses the card', () => {
    mapStore.getState().setTool('inspect')
    render(<Harness />)
    start()
    const card = screen.getByRole('region', { name: 'Guided story' })
    expect(document.activeElement).toBe(card)
    expect(heading()).toBe(steps[0].title)
    expect(card.textContent).toContain('Step 1 of 6')
    expect(card.textContent).toContain('MOCK data')
    const state = mapStore.getState()
    expect(state.tool).toBe('pan')
    expect(state.camera.center).toEqual(steps[0].camera.center)
    expect(state.cameraDurationMs).toBe(steps[0].camera.duration_ms)
    expect(state.visible).toEqual(['hillshade', 'perimeter'])
    expect(state.story).toEqual({ active: true, stepIndex: 0 })
  })

  it('advances by itself and animates the swipe', () => {
    render(<Harness />)
    start()
    wait(stepDwellMs(steps[0]))
    expect(heading()).toBe(steps[1].title)
    expect(mapStore.getState().compare).toMatchObject({
      left: 'optical_during',
      right: 'sar_t2_hv',
    })
    wait(1000)
    const midway = mapStore.getState().compare!.position
    expect(midway).toBeLessThan(0.9)
    expect(midway).toBeGreaterThan(0.3)
    wait(1500)
    expect(mapStore.getState().compare!.position).toBeCloseTo(0.3, 6)
  })

  it('pauses, keeps the remaining time and resumes', () => {
    render(<Harness />)
    start()
    wait(stepDwellMs(steps[0]) - 3000)
    fireEvent.click(screen.getByText('Pause'))
    wait(100_000)
    expect(heading()).toBe(steps[0].title)
    expect(
      screen.getByRole('region', { name: 'Guided story' }).textContent,
    ).toContain('paused')
    fireEvent.click(screen.getByText('Play'))
    wait(2900)
    expect(heading()).toBe(steps[0].title)
    wait(200)
    expect(heading()).toBe(steps[1].title)
  })

  it('pauses when the tab is hidden', () => {
    render(<Harness />)
    start()
    Object.defineProperty(document, 'hidden', {
      configurable: true,
      value: true,
    })
    act(() => {
      document.dispatchEvent(new Event('visibilitychange'))
    })
    Object.defineProperty(document, 'hidden', {
      configurable: true,
      value: false,
    })
    wait(100_000)
    expect(heading()).toBe(steps[0].title)
  })

  it('moves with buttons, arrow keys and step dots', () => {
    render(<Harness />)
    start()
    fireEvent.click(screen.getByLabelText('Next step'))
    expect(heading()).toBe(steps[1].title)
    const card = screen.getByRole('region', { name: 'Guided story' })
    fireEvent.keyDown(card, { key: 'ArrowRight' })
    expect(heading()).toBe(steps[2].title)
    fireEvent.keyDown(card, { key: 'ArrowLeft' })
    expect(heading()).toBe(steps[1].title)
    fireEvent.click(screen.getByLabelText('Go to step 6'))
    expect(heading()).toBe(steps[5].title)
    expect(
      screen.getByLabelText('Go to step 6').getAttribute('aria-current'),
    ).toBe('step')
    expect(
      (screen.getByLabelText('Next step') as HTMLButtonElement).disabled,
    ).toBe(true)
    expect(mapStore.getState().selection).toEqual({
      type: 'point',
      point: steps[5].focus?.type === 'point' ? steps[5].focus.point : null,
    })
    expect(mapStore.getState().panel).toBe('inspector')
    expect(screen.getByText('Show details')).toBeTruthy()
  })

  it('leaves with Esc, keeps the map state and can resume', () => {
    render(<Harness />)
    start()
    fireEvent.click(screen.getByLabelText('Next step'))
    const before = mapStore.getState()
    fireEvent.keyDown(document.body, { key: 'Escape' })
    expect(screen.queryByRole('region', { name: 'Guided story' })).toBeNull()
    const after = mapStore.getState()
    expect(after.story).toEqual({ active: false, stepIndex: 1 })
    expect(after.visible).toEqual(before.visible)
    expect(after.compare).toEqual(before.compare)
    wait(200_000)
    expect(mapStore.getState().story.active).toBe(false)
    fireEvent.click(screen.getByText('Resume story · 2/6'))
    expect(heading()).toBe(steps[1].title)
    expect(mapStore.getState().story.active).toBe(true)
  })

  it('stops at the end and offers a replay', () => {
    render(<Harness />)
    start()
    for (const step of steps) wait(stepDwellMs(step))
    expect(heading()).toBe(steps[5].title)
    expect(
      screen.getByRole('region', { name: 'Guided story' }).textContent,
    ).toContain('end')
    fireEvent.click(screen.getByText('Replay'))
    expect(heading()).toBe(steps[0].title)
  })

  it('skips animations under reduced motion', () => {
    render(<Harness reducedMotion />)
    start()
    expect(mapStore.getState().cameraDurationMs).toBe(0)
    expect(screen.queryByTestId('story-progress')).toBeNull()
    fireEvent.click(screen.getByLabelText('Next step'))
    expect(mapStore.getState().compare?.position).toBe(0.3)
  })

  it('cancels its timer when unmounted', () => {
    const { unmount } = render(<Harness />)
    start()
    unmount()
    expect(vi.getTimerCount()).toBe(0)
  })
})
