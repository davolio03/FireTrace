import { useEffect, useRef, type KeyboardEvent } from 'react'
import {
  ArrowDown,
  ChevronLeft,
  ChevronRight,
  Compass,
  Pause,
  Play,
  RotateCcw,
} from 'lucide-react'
import { renderMarkdown } from './markdown'
import type { StoryPlayerApi } from './useStoryPlayer'

const button =
  'inline-flex items-center gap-1 rounded border border-slate-300 bg-white px-3 py-1.5 text-sm hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40 focus-visible:outline-2 focus-visible:outline-offset-2'
const primary =
  'inline-flex items-center gap-1 rounded bg-slate-900 px-3 py-1.5 text-sm text-white hover:bg-slate-700 focus-visible:outline-2 focus-visible:outline-offset-2'

const detailsAnchor = {
  inspector: 'inspector-heading',
  profile: 'profile-heading',
} as const

/** Story card drawn over the map, or a resume pill while exploring. */
export function StoryPlayer({
  player,
  isMock,
  reducedMotion,
}: {
  player: StoryPlayerApi
  isMock: boolean
  reducedMotion: boolean
}) {
  const card = useRef<HTMLElement>(null)
  const wasActive = useRef(false)
  useEffect(() => {
    if (player.active && !wasActive.current) card.current?.focus()
    wasActive.current = player.active
  }, [player.active])

  if (player.status === 'exploring') {
    return (
      <button
        type="button"
        onClick={player.resume}
        className={`${primary} absolute bottom-3 left-3 z-10 shadow`}
      >
        <Play aria-hidden="true" className="size-4" />
        Resume story · {player.index + 1}/{player.count}
      </button>
    )
  }
  if (!player.active || !player.step) return null

  const { step, status, index, count } = player
  const panel = step.panel === 'inspector' || step.panel === 'profile'
  const onKeyDown = (event: KeyboardEvent) => {
    if (event.key === 'ArrowRight') player.next()
    if (event.key === 'ArrowLeft') player.prev()
  }
  const showDetails = () => {
    if (!panel) return
    document
      .getElementById(detailsAnchor[step.panel as keyof typeof detailsAnchor])
      ?.scrollIntoView({
        behavior: reducedMotion ? 'auto' : 'smooth',
        block: 'start',
      })
  }

  return (
    <section
      ref={card}
      data-story-card=""
      role="region"
      aria-label="Guided story"
      tabIndex={-1}
      onKeyDown={onKeyDown}
      className="absolute bottom-3 left-3 z-10 w-[min(24rem,calc(100%-1.5rem))] space-y-3 rounded-lg border border-slate-300 bg-white/95 p-4 text-slate-900 shadow-lg focus-visible:outline-2 focus-visible:outline-offset-2"
    >
      <div className="flex items-center justify-between text-xs text-slate-700">
        <span>
          Step {index + 1} of {count}
          {status === 'paused' && ' · paused'}
          {status === 'ended' && ' · end'}
        </span>
        {isMock && (
          <span className="rounded border border-amber-700 bg-amber-100 px-1.5 py-0.5 font-semibold text-amber-950">
            MOCK data
          </span>
        )}
      </div>
      <h2 aria-live="polite" className="text-lg font-semibold">
        {step.title}
      </h2>
      <div className="space-y-2 text-sm leading-relaxed">
        {renderMarkdown(step.body_md)}
      </div>
      {!reducedMotion && status !== 'ended' && (
        <div className="h-1 overflow-hidden rounded bg-slate-200">
          <div
            key={player.applied}
            data-testid="story-progress"
            className="h-full origin-left bg-slate-900"
            style={{
              animation: `story-progress ${player.dwellMs}ms linear forwards`,
              animationPlayState: status === 'playing' ? 'running' : 'paused',
            }}
          />
        </div>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={player.prev}
          disabled={index === 0}
          aria-label="Previous step"
          className={button}
        >
          <ChevronLeft aria-hidden="true" className="size-4" />
        </button>
        {status === 'playing' ? (
          <button type="button" onClick={player.pause} className={primary}>
            <Pause aria-hidden="true" className="size-4" /> Pause
          </button>
        ) : (
          <button type="button" onClick={player.play} className={primary}>
            {status === 'ended' ? (
              <>
                <RotateCcw aria-hidden="true" className="size-4" /> Replay
              </>
            ) : (
              <>
                <Play aria-hidden="true" className="size-4" /> Play
              </>
            )}
          </button>
        )}
        <button
          type="button"
          onClick={player.next}
          disabled={index === count - 1}
          aria-label="Next step"
          className={button}
        >
          <ChevronRight aria-hidden="true" className="size-4" />
        </button>
        <ol className="ml-auto flex gap-1" aria-label="Story steps">
          {Array.from({ length: count }, (_, dot) => (
            <li key={dot}>
              <button
                type="button"
                onClick={() => player.goTo(dot)}
                aria-label={`Go to step ${dot + 1}`}
                aria-current={dot === index ? 'step' : undefined}
                className={`block size-2.5 rounded-full focus-visible:outline-2 focus-visible:outline-offset-2 ${
                  dot === index ? 'bg-slate-900' : 'bg-slate-300'
                }`}
              />
            </li>
          ))}
        </ol>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2">
        {panel ? (
          <button type="button" onClick={showDetails} className={button}>
            <ArrowDown aria-hidden="true" className="size-4" /> Show details
          </button>
        ) : (
          <span />
        )}
        <button type="button" onClick={player.exit} className={button}>
          <Compass aria-hidden="true" className="size-4" /> Explore freely (Esc)
        </button>
      </div>
    </section>
  )
}
