import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import manifest from '../../../../contracts/fixtures/web/layers.json'
import storyJson from '../../story/story.json'
import { initialCamera, mapStore } from '../../state/mapStore'
import type { Layer } from '../map/layers'
import { parseStory } from './story'
import { StoryView } from './StoryView'
import { stepDwellMs } from './timing'
import { useStoryPlayer } from './useStoryPlayer'

vi.mock('../map/CinematicMap', () => ({
  CinematicMap: ({
    spinning,
    satellite,
    onTerrain,
  }: {
    spinning: boolean
    satellite: boolean
    onTerrain?: (ok: boolean) => void
  }) => (
    <div
      data-testid="cinematic-map"
      data-spinning={String(spinning)}
      data-satellite={String(satellite)}
    >
      <button type="button" onClick={() => onTerrain?.(true)}>
        terrain loaded
      </button>
    </div>
  ),
}))

const layers = manifest.layers as Layer[]
const story = parseStory(storyJson)!
const steps = story.steps

function Harness({
  reducedMotion = false,
  onLeave = () => undefined,
  onExplore = () => undefined,
}: {
  reducedMotion?: boolean
  onLeave?: () => void
  onExplore?: () => void
}) {
  const player = useStoryPlayer(story, layers, reducedMotion)
  return (
    <div>
      <button type="button" onClick={() => player.start(0)}>
        Start story
      </button>
      <span data-testid="status">{player.status}</span>
      {player.active && (
        <StoryView
          player={player}
          layers={layers}
          dataBaseUrl="/"
          dates={{ before: '2026-08-16', after: '2026-10-03' }}
          isMock
          reducedMotion={reducedMotion}
          onLeave={onLeave}
          onExplore={onExplore}
        />
      )}
    </div>
  )
}

const heading = () => screen.getByRole('heading', { level: 2 }).textContent
const caption = () => screen.getByRole('region', { name: 'Guided story' })
const start = () => fireEvent.click(screen.getByText('Start story'))
const wait = (ms: number) => act(() => vi.advanceTimersByTime(ms))

describe('story view', () => {
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
    expect(screen.queryByTestId('cinematic-map')).toBeNull()
    expect(mapStore.getState().story.active).toBe(false)
  })

  it('opens on the orbit with the satellite, dates and honest labels', () => {
    mapStore.getState().setTool('inspect')
    render(<Harness />)
    start()
    expect(document.activeElement).toBe(caption())
    expect(heading()).toBe(steps[0].title)
    expect(caption().textContent).toContain('01 / 07')
    const map = screen.getByTestId('cinematic-map')
    expect(map.getAttribute('data-satellite')).toBe('true')
    expect(map.getAttribute('data-spinning')).toBe('false')
    expect(screen.getByText(/MOCK data/)).toBeTruthy()
    expect(screen.getByText(/illustrative ground track/)).toBeTruthy()
    expect(screen.getByText(/G4340499432-ASF/)).toBeTruthy()
    expect(screen.queryByText(/Relief ×1.6/)).toBeNull()
    fireEvent.click(screen.getByText('terrain loaded'))
    expect(screen.getByText(/Relief ×1.6 · Copernicus DEM GLO-30/)).toBeTruthy()
    const state = mapStore.getState()
    expect(state.tool).toBe('pan')
    expect(state.camera.center).toEqual(steps[0].camera.center)
    expect(state.camera.pitch).toBe(0)
    expect(state.story).toEqual({ active: true, stepIndex: 0 })
  })

  it('dives to the fire, spins and crossfades as it plays', () => {
    render(<Harness />)
    start()
    wait(stepDwellMs(steps[0]))
    expect(heading()).toBe(steps[1].title)
    expect(mapStore.getState().camera.pitch).toBe(62)
    expect(mapStore.getState().cameraDurationMs).toBe(6000)
    const map = screen.getByTestId('cinematic-map')
    expect(map.getAttribute('data-spinning')).toBe('true')
    expect(map.getAttribute('data-satellite')).toBe('false')
    wait(stepDwellMs(steps[1]))
    expect(heading()).toBe(steps[2].title)
    expect(mapStore.getState().compare).toMatchObject({
      left: 'optical_during',
      right: 'sar_t2_hv',
      position: 1,
    })
    wait(1250)
    const midway = mapStore.getState().compare!.position
    expect(midway).toBeGreaterThan(0)
    expect(midway).toBeLessThan(1)
    wait(1500)
    expect(mapStore.getState().compare!.position).toBeCloseTo(0, 6)
  })

  it('shows the legend of the main layer', () => {
    render(<Harness />)
    start()
    fireEvent.click(screen.getByLabelText('Go to step 5'))
    expect(heading()).toBe(steps[4].title)
    expect(
      screen.getByText('Observed radar changes — combined index'),
    ).toBeTruthy()
  })

  it('hides the controls while playing and shows them on movement', () => {
    render(<Harness />)
    start()
    const controls = screen.getByLabelText('Pause').parentElement!
    expect(controls.className).toContain('opacity-100')
    wait(2600)
    expect(controls.className).toContain('opacity-0')
    fireEvent.mouseMove(caption())
    expect(controls.className).toContain('opacity-100')
    fireEvent.click(screen.getByLabelText('Pause'))
    wait(10_000)
    expect(controls.className).toContain('opacity-100')
  })

  it('pauses, keeps the remaining time and resumes', () => {
    render(<Harness />)
    start()
    wait(stepDwellMs(steps[0]) - 3000)
    fireEvent.click(screen.getByLabelText('Pause'))
    wait(100_000)
    expect(heading()).toBe(steps[0].title)
    expect(caption().textContent).toContain('PAUSED')
    fireEvent.click(screen.getByLabelText('Play'))
    wait(2900)
    expect(heading()).toBe(steps[0].title)
    wait(200)
    expect(heading()).toBe(steps[1].title)
  })

  it('pauses when the user touches the map', () => {
    render(<Harness />)
    start()
    fireEvent.pointerDown(screen.getByTestId('cinematic-map'))
    expect(screen.getByTestId('status').textContent).toBe('paused')
  })

  it('moves with buttons, arrow keys and the chapter bar', () => {
    render(<Harness />)
    start()
    fireEvent.click(screen.getByLabelText('Next step'))
    expect(heading()).toBe(steps[1].title)
    fireEvent.keyDown(caption(), { key: 'ArrowRight' })
    expect(heading()).toBe(steps[2].title)
    fireEvent.keyDown(caption(), { key: 'ArrowLeft' })
    expect(heading()).toBe(steps[1].title)
    fireEvent.click(screen.getByLabelText('Go to step 7'))
    expect(heading()).toBe(steps[6].title)
    expect(
      screen.getByLabelText('Go to step 7').getAttribute('aria-current'),
    ).toBe('step')
    expect(
      (screen.getByLabelText('Next step') as HTMLButtonElement).disabled,
    ).toBe(true)
    expect(mapStore.getState().panel).toBe('inspector')
  })

  it('ends with a call to explore the evidence', () => {
    const onExplore = vi.fn()
    render(<Harness onExplore={onExplore} />)
    start()
    for (const step of steps) wait(stepDwellMs(step))
    expect(heading()).toBe(steps[6].title)
    expect(screen.getByLabelText('Replay')).toBeTruthy()
    fireEvent.click(screen.getByText('Explore the evidence'))
    expect(onExplore).toHaveBeenCalledOnce()
    fireEvent.click(screen.getByLabelText('Replay'))
    expect(heading()).toBe(steps[0].title)
  })

  it('leaves with Esc or the close button, keeping the map state', () => {
    const onLeave = vi.fn()
    render(<Harness onLeave={onLeave} />)
    start()
    fireEvent.click(screen.getByLabelText('Next step'))
    const before = mapStore.getState()
    fireEvent.keyDown(document.body, { key: 'Escape' })
    expect(screen.getByTestId('status').textContent).toBe('exploring')
    expect(mapStore.getState().visible).toEqual(before.visible)
    expect(mapStore.getState().story.active).toBe(false)
    start()
    fireEvent.click(screen.getByLabelText('Close the story'))
    expect(onLeave).toHaveBeenCalledOnce()
  })

  it('skips animations under reduced motion', () => {
    render(<Harness reducedMotion />)
    start()
    expect(mapStore.getState().cameraDurationMs).toBe(0)
    expect(
      screen.getByTestId('story-progress').getAttribute('style'),
    ).toBeNull()
    fireEvent.click(screen.getByLabelText('Go to step 3'))
    expect(mapStore.getState().compare?.position).toBe(0)
  })

  it('cancels its timers when unmounted', () => {
    const { unmount } = render(<Harness />)
    start()
    unmount()
    expect(vi.getTimerCount()).toBe(0)
  })
})
