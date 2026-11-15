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
import { useMapStore, type LonLat } from '../../state/mapStore'
import { CinematicMap } from '../map/CinematicMap'
import { TERRAIN_EXAGGERATION } from '../map/terrainTiles'
import type { Layer } from '../map/layers'
import frameFeature from '../../story/nisar-frame.json'
import { renderMarkdown } from './markdown'
import type { StoryPlayerApi } from './useStoryPlayer'

const FRAME_RING = frameFeature.geometry.coordinates[0] as LonLat[]
const CONTROLS_HIDE_MS = 2500

const glass =
  'rounded-2xl border border-white/10 bg-slate-950/80 text-white shadow-2xl shadow-black/50 backdrop-blur-xl'
const iconButton =
  'inline-flex size-11 items-center justify-center rounded-full border border-white/15 bg-slate-950/70 text-white backdrop-blur-md transition hover:bg-white/15 disabled:cursor-not-allowed disabled:opacity-30 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-amber-300'

const pad = (n: number) => String(n).padStart(2, '0')

/** "2026-08-16" → "16 Aug 2026"; anything else is shown as given. */
function formatStoryDate(value: string) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return value
  return new Date(`${value}T00:00:00Z`).toLocaleDateString('en-GB', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    timeZone: 'UTC',
  })
}

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
 * Which of the two crossfaded layers dominates right now. It reads the shared
 * comparison, so it follows the fade frame by frame.
 */
function CrossfadeMeter({ layers }: { layers: Layer[] }) {
  const compare = useMapStore((state) => state.compare)
  if (!compare) return null
  const title = (id: string) =>
    layers.find((layer) => layer.id === id)?.title ?? id
  // position 1 shows the left layer, 0 the right one.
  const toRight = 1 - compare.position
  return (
    <div
      className="space-y-1.5 border-t border-white/10 pt-3"
      aria-label="Crossfade"
    >
      <div className="flex justify-between gap-3 text-xs font-medium">
        <span
          className="transition-colors"
          style={{ color: toRight < 0.5 ? '#fde68a' : '#94a3b8' }}
        >
          {title(compare.left)}
        </span>
        <span
          className="text-right transition-colors"
          style={{ color: toRight >= 0.5 ? '#fde68a' : '#94a3b8' }}
        >
          {title(compare.right)}
        </span>
      </div>
      <div className="relative h-1 rounded-full bg-white/15">
        <span
          className="absolute inset-y-0 left-0 rounded-full bg-amber-300/70"
          style={{ width: `${toRight * 100}%` }}
        />
        <span
          className="absolute top-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rounded-full bg-amber-200 shadow-[0_0_10px_rgba(253,230,138,0.9)]"
          style={{ left: `${toRight * 100}%` }}
        />
      </div>
    </div>
  )
}

/**
 * Full-screen guided story: a 3D globe-to-terrain map with a documentary
 * caption card, a titled chapter bar and controls that hide while it plays.
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
  const { step, status, index, count, titles } = player
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
      <div className="story-stars pointer-events-none absolute inset-0" />
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
      {/* Cinematic framing: vignette plus darker top and bottom bands. */}
      <div className="story-vignette pointer-events-none absolute inset-0" />
      <div className="pointer-events-none absolute inset-x-0 top-0 h-32 bg-gradient-to-b from-black/75 to-transparent" />
      <div className="pointer-events-none absolute inset-x-0 bottom-0 h-80 bg-gradient-to-t from-black/85 via-black/40 to-transparent" />

      <header className="absolute inset-x-0 top-0 flex items-start justify-between gap-4 p-4 sm:p-6">
        <div>
          <p className="text-sm font-bold uppercase tracking-[0.35em] text-amber-300">
            FireTrace
          </p>
          <p className="mt-0.5 text-sm text-slate-200">
            Plaskett Fire · NISAR L-band radar
          </p>
          {isMock && (
            <p className="mt-2 inline-block rounded-md border border-amber-400/70 bg-amber-950/80 px-2 py-0.5 text-xs font-semibold text-amber-200">
              MOCK data — not scientific evidence
            </p>
          )}
        </div>
        <div className="flex items-center gap-2">
          <p
            className={`${glass} hidden items-center gap-2 px-4 py-2 text-sm sm:flex`}
          >
            <span className="text-xs uppercase tracking-wider text-slate-400">
              Before
            </span>
            <span className="font-medium">{formatStoryDate(dates.before)}</span>
            <span aria-hidden="true" className="text-amber-300">
              →
            </span>
            <span className="text-xs uppercase tracking-wider text-slate-400">
              After
            </span>
            <span className="font-medium">{formatStoryDate(dates.after)}</span>
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
        className="absolute bottom-32 left-4 right-4 max-w-[30rem] focus:outline-none sm:left-6 lg:bottom-36"
      >
        <div
          key={step.id}
          className={`${glass} story-caption relative overflow-hidden p-5 sm:p-6`}
        >
          <span
            aria-hidden="true"
            className="absolute inset-y-5 left-0 w-1 rounded-r-full bg-gradient-to-b from-amber-300 to-orange-500"
          />
          <p className="flex items-center gap-2 text-xs font-semibold tracking-[0.25em] text-amber-300">
            <span>
              {pad(index + 1)} / {pad(count)}
            </span>
            {status === 'paused' && (
              <span className="rounded bg-white/10 px-1.5 py-0.5 tracking-[0.15em] text-slate-200">
                PAUSED
              </span>
            )}
          </p>
          <h2
            aria-live="polite"
            className="story-caption-title mt-2 text-2xl font-semibold leading-tight tracking-tight text-white sm:text-[1.75rem]"
          >
            {step.title}
          </h2>
          <div className="story-caption-body mt-3 space-y-2 text-[15px] leading-relaxed text-slate-200 sm:text-base [&_strong]:font-semibold [&_strong]:text-amber-100">
            {renderMarkdown(step.body_md)}
          </div>
          <div className="story-caption-body mt-4 space-y-3">
            <CrossfadeMeter layers={layers} />
            {!step.compare && legend && legendStops.length > 1 && (
              <div className="space-y-1.5 border-t border-white/10 pt-3 text-xs text-slate-300">
                <p className="font-medium text-slate-100">{legend.title}</p>
                <div
                  className="h-2 rounded-full"
                  style={{
                    background: `linear-gradient(to right, ${legendStops
                      .map((stop) => stop.color)
                      .join(', ')})`,
                  }}
                />
                <p className="flex justify-between tabular-nums">
                  <span>{legendStops[0].value}</span>
                  <span>
                    {legendStops[legendStops.length - 1].value}{' '}
                    {legend.legend.type === 'continuous'
                      ? legend.legend.units
                      : ''}
                  </span>
                </p>
              </div>
            )}
          </div>
          {last && (
            <button
              type="button"
              onClick={onExplore}
              className="mt-5 inline-flex items-center gap-2 rounded-full bg-amber-400 px-5 py-2.5 font-semibold text-slate-950 shadow-lg shadow-amber-500/30 transition hover:bg-amber-300 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white"
            >
              Explore the evidence <span aria-hidden="true">→</span>
            </button>
          )}
        </div>
      </section>

      <div className="absolute bottom-32 right-4 hidden max-w-xs space-y-1 text-right text-xs text-slate-300 [text-shadow:0_1px_3px_rgba(0,0,0,0.9)] sm:right-6 sm:block lg:bottom-36">
        {step.id === 'orbit' && (
          <p>
            <span className="text-orange-300">Orange</span>: real NISAR frame
            (NASA CMR {frameFeature.properties.granule_id}).{' '}
            <span className="text-slate-100">Dashed</span>: illustrative ground
            track.
          </p>
        )}
        {terrain && (
          <p>Relief ×{TERRAIN_EXAGGERATION} · Copernicus DEM GLO-30</p>
        )}
      </div>

      <div
        className={`absolute bottom-16 left-1/2 flex -translate-x-1/2 items-center gap-2 transition-all duration-500 lg:bottom-20 ${
          shown
            ? 'translate-y-0 opacity-100'
            : 'pointer-events-none translate-y-2 opacity-0'
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
          className="ml-1 hidden h-11 items-center gap-2 rounded-full border border-white/15 bg-slate-950/70 px-4 text-sm text-white backdrop-blur-md transition hover:bg-white/15 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-amber-300 sm:inline-flex"
        >
          <Compass aria-hidden="true" className="size-4" /> Explore freely
          <kbd className="rounded border border-white/20 px-1 text-[10px] text-slate-300">
            Esc
          </kbd>
        </button>
      </div>

      <nav
        aria-label="Story chapters"
        className="absolute inset-x-0 bottom-0 flex gap-2 pb-4 pl-4 pr-14 sm:pl-6"
      >
        {Array.from({ length: count }, (_, chapter) => {
          const current = chapter === index
          return (
            <button
              key={chapter}
              type="button"
              onClick={() => player.goTo(chapter)}
              aria-label={`Go to step ${chapter + 1}`}
              title={titles[chapter]}
              aria-current={current ? 'step' : undefined}
              className="group relative flex min-w-0 flex-1 flex-col gap-1.5 pt-2 text-left focus-visible:outline-2 focus-visible:outline-amber-300"
            >
              <span className="relative h-1 w-full overflow-hidden rounded-full bg-white/20 transition-all group-hover:h-1.5">
                {chapter < index && (
                  <span className="absolute inset-0 bg-amber-300/80" />
                )}
                {current && (
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
              <span
                aria-hidden="true"
                className={`hidden truncate text-[11px] transition-colors lg:block ${
                  current
                    ? 'font-medium text-white'
                    : 'text-slate-400 group-hover:text-slate-200'
                }`}
              >
                {titles[chapter]}
              </span>
            </button>
          )
        })}
      </nav>
    </div>
  )
}
