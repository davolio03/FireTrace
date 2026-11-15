import { useEffect, useRef, useState, type KeyboardEvent } from 'react'
import {
  ChevronLeft,
  ChevronRight,
  Compass,
  Pause,
  Play,
  RotateCcw,
  X,
} from 'lucide-react'
import type { LonLat } from '../../state/mapStore'
import { CinematicMap } from '../map/CinematicMap'
import { TERRAIN_EXAGGERATION } from '../map/terrainTiles'
import { mapStore } from '../../state/mapStore'
import type { Layer } from '../map/layers'
import frameFeature from '../../story/nisar-frame.json'
import { renderMarkdown } from './markdown'
import type { StoryPlayerApi } from './useStoryPlayer'

const FRAME_RING = frameFeature.geometry.coordinates[0] as LonLat[]
const CONTROLS_HIDE_MS = 2500
const CASE_CENTRE: LonLat = [-121.3865, 35.916]

const glass =
  'rounded-xl border border-white/10 bg-slate-950/70 text-white shadow-2xl backdrop-blur-md'
const iconButton =
  'inline-flex size-10 items-center justify-center rounded-full border border-white/20 bg-white/10 text-white hover:bg-white/20 disabled:cursor-not-allowed disabled:opacity-30 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-amber-300'

const pad = (n: number) => String(n).padStart(2, '0')

function legendFor(layers: Layer[], visible: string[]) {
  return visible
    .map((id) => layers.find((layer) => layer.id === id))
    .find(
      (layer): layer is Layer =>
        !!layer &&
        layer.kind === 'raster' &&
        layer.legend.type === 'continuous',
    )
}

/**
 * Full-screen guided story: a 3D globe-to-terrain map with a documentary
 * lower third, a chapter bar and controls that hide while it plays.
 */
export function StoryView({
  player,
  layers,
  dataBaseUrl,
  dates,
  isMock,
  reducedMotion,
  onLeave,
  onExplore,
}: {
  player: StoryPlayerApi
  layers: Layer[]
  dataBaseUrl: string
  dates: { before: string; after: string }
  isMock: boolean
  reducedMotion: boolean
  /** Close the story view (header button). */
  onLeave: () => void
  /** Final call to action: open the analysis on the story's evidence. */
  onExplore: () => void
}) {
  const [terrain, setTerrain] = useState(false)
  const [controlsShown, setControlsShown] = useState(true)
  const hideTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const caption = useRef<HTMLElement>(null)
  const { step, status, index, count } = player
  const playing = status === 'playing'

  const revealControls = () => {
    setControlsShown(true)
    if (hideTimer.current) clearTimeout(hideTimer.current)
    hideTimer.current = setTimeout(
      () => setControlsShown(false),
      CONTROLS_HIDE_MS,
    )
  }
  useEffect(() => {
    if (!playing) {
      if (hideTimer.current) clearTimeout(hideTimer.current)
      return
    }
    hideTimer.current = setTimeout(
      () => setControlsShown(false),
      CONTROLS_HIDE_MS,
    )
    return () => {
      if (hideTimer.current) clearTimeout(hideTimer.current)
    }
  }, [playing])
  useEffect(() => {
    caption.current?.focus()
    // Leaving the story keeps its layers and selection, but levels the camera
    // for the 2D analysis map and keeps it on the case.
    return () => {
      const { camera, flyTo } = mapStore.getState()
      flyTo({
        center: camera.zoom < 8 ? CASE_CENTRE : camera.center,
        zoom: Math.max(camera.zoom, 10),
        bearing: 0,
        pitch: 0,
      })
    }
  }, [])

  if (!step) return null
  const shown = controlsShown || !playing
  const last = index === count - 1
  const legend = legendFor(layers, step.layers.visible)
  const legendStops =
    legend?.legend.type === 'continuous' ? legend.legend.stops : []
  const onKeyDown = (event: KeyboardEvent) => {
    revealControls()
    if (event.key === 'ArrowRight') player.next()
    if (event.key === 'ArrowLeft') player.prev()
  }

  return (
    <div
      className="fixed inset-0 z-50 overflow-hidden bg-black text-white"
      onMouseMove={revealControls}
      onFocusCapture={revealControls}
      onKeyDown={onKeyDown}
    >
      {/* Touching the map takes over the camera, so the story pauses. */}
      <div
        className="absolute inset-0"
        onPointerDownCapture={playing ? player.pause : undefined}
        onWheelCapture={playing ? player.pause : undefined}
      >
        <CinematicMap
          layers={layers}
          dataBaseUrl={dataBaseUrl}
          frame={FRAME_RING}
          spinning={playing && step.id !== 'orbit'}
          satellite={step.id === 'orbit'}
          reducedMotion={reducedMotion}
          onTerrain={setTerrain}
        />
      </div>
      <div className="pointer-events-none absolute inset-x-0 top-0 h-36 bg-gradient-to-b from-black/70 to-transparent" />
      <div className="pointer-events-none absolute inset-x-0 bottom-0 h-72 bg-gradient-to-t from-black/80 to-transparent" />

      <header className="absolute inset-x-0 top-0 flex items-start justify-between gap-4 p-4 sm:p-6">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.3em] text-amber-300">
            FireTrace
          </p>
          <p className="text-sm text-slate-200">
            Plaskett Fire · NISAR L-band radar
          </p>
          {isMock && (
            <p className="mt-2 inline-block rounded border border-amber-400 bg-amber-950/80 px-2 py-0.5 text-xs font-semibold text-amber-200">
              MOCK data — not scientific evidence
            </p>
          )}
        </div>
        <div className="flex items-center gap-2">
          <p className={`${glass} hidden px-3 py-1.5 text-sm sm:block`}>
            <span className="text-slate-300">Before</span> {dates.before}{' '}
            <span aria-hidden="true">→</span>{' '}
            <span className="text-slate-300">After</span> {dates.after}
          </p>
          <button
            type="button"
            onClick={onLeave}
            aria-label="Close the story"
            className={iconButton}
          >
            <X aria-hidden="true" className="size-5" />
          </button>
        </div>
      </header>

      <section
        ref={caption}
        tabIndex={-1}
        role="region"
        aria-label="Guided story"
        className="absolute bottom-28 left-4 right-4 max-w-md focus:outline-none sm:left-6"
      >
        <div key={step.id} className="story-caption space-y-2">
          <p className="text-xs font-semibold tracking-[0.3em] text-amber-300">
            {pad(index + 1)} / {pad(count)}
            {status === 'paused' && ' · PAUSED'}
          </p>
          <h2
            aria-live="polite"
            className="text-2xl font-semibold leading-tight drop-shadow sm:text-3xl"
          >
            {step.title}
          </h2>
          <div className="space-y-2 text-sm leading-relaxed text-slate-100 drop-shadow sm:text-base">
            {renderMarkdown(step.body_md)}
          </div>
          {last && (
            <button
              type="button"
              onClick={onExplore}
              className="mt-2 inline-flex items-center gap-2 rounded-full bg-amber-400 px-5 py-2 font-semibold text-slate-950 hover:bg-amber-300 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white"
            >
              Explore the evidence <span aria-hidden="true">→</span>
            </button>
          )}
        </div>
      </section>

      <div
        className={`absolute bottom-12 left-1/2 flex -translate-x-1/2 items-center gap-2 transition-opacity duration-300 ${
          shown ? 'opacity-100' : 'pointer-events-none opacity-0'
        }`}
      >
        <button
          type="button"
          onClick={player.prev}
          disabled={index === 0}
          aria-label="Previous step"
          className={iconButton}
        >
          <ChevronLeft aria-hidden="true" className="size-5" />
        </button>
        {playing ? (
          <button
            type="button"
            onClick={player.pause}
            aria-label="Pause"
            className={iconButton}
          >
            <Pause aria-hidden="true" className="size-5" />
          </button>
        ) : (
          <button
            type="button"
            onClick={player.play}
            aria-label={status === 'ended' ? 'Replay' : 'Play'}
            className={iconButton}
          >
            {status === 'ended' ? (
              <RotateCcw aria-hidden="true" className="size-5" />
            ) : (
              <Play aria-hidden="true" className="size-5" />
            )}
          </button>
        )}
        <button
          type="button"
          onClick={player.next}
          disabled={last}
          aria-label="Next step"
          className={iconButton}
        >
          <ChevronRight aria-hidden="true" className="size-5" />
        </button>
        <button
          type="button"
          onClick={player.exit}
          className={`${glass} hidden items-center gap-2 px-3 py-2 text-sm sm:inline-flex`}
        >
          <Compass aria-hidden="true" className="size-4" /> Explore freely (Esc)
        </button>
      </div>

      <div className="absolute bottom-24 right-4 hidden max-w-xs space-y-2 text-right text-[11px] text-slate-300 sm:right-6 sm:block">
        {legend && legendStops.length > 1 && (
          <div className={`${glass} p-2 text-left`}>
            <p className="mb-1 font-semibold text-white">{legend.title}</p>
            <div
              className="h-2 w-40 rounded"
              style={{
                background: `linear-gradient(to right, ${legendStops
                  .map((stop) => stop.color)
                  .join(', ')})`,
              }}
            />
            <p className="mt-0.5 flex justify-between">
              <span>{legendStops[0].value}</span>
              <span>
                {legendStops[legendStops.length - 1].value}{' '}
                {legend.legend.type === 'continuous' ? legend.legend.units : ''}
              </span>
            </p>
          </div>
        )}
        {step.id === 'orbit' && (
          <p>
            Orange: real NISAR frame (NASA CMR{' '}
            {frameFeature.properties.granule_id}). Dashed: illustrative ground
            track.
          </p>
        )}
        {terrain && (
          <p>Relief ×{TERRAIN_EXAGGERATION} · Copernicus DEM GLO-30</p>
        )}
      </div>

      <nav
        aria-label="Story chapters"
        className="absolute inset-x-0 bottom-0 flex gap-1.5 px-4 pb-5 sm:px-6"
      >
        {Array.from({ length: count }, (_, chapter) => (
          <button
            key={chapter}
            type="button"
            onClick={() => player.goTo(chapter)}
            aria-label={`Go to step ${chapter + 1}`}
            aria-current={chapter === index ? 'step' : undefined}
            className="group relative h-6 flex-1 focus-visible:outline-2 focus-visible:outline-amber-300"
          >
            <span className="absolute inset-x-0 top-1/2 h-1 -translate-y-1/2 overflow-hidden rounded-full bg-white/25 group-hover:h-1.5">
              {chapter < index && (
                <span className="absolute inset-0 bg-amber-300" />
              )}
              {chapter === index && (
                <span
                  key={player.applied}
                  data-testid="story-progress"
                  className="absolute inset-0 origin-left bg-amber-300"
                  style={
                    reducedMotion || status === 'ended'
                      ? undefined
                      : {
                          animation: `story-progress ${player.dwellMs}ms linear forwards`,
                          animationPlayState: playing ? 'running' : 'paused',
                        }
                  }
                />
              )}
            </span>
          </button>
        ))}
      </nav>
    </div>
  )
}
