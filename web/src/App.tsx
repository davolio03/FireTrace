import { useCallback, useEffect, useRef, useState } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import storyJson from './story/story.json'
import { parseStory } from './features/story/story'
import { StoryView } from './features/story/StoryView'
import { storyDurationMs } from './features/story/timing'
import {
  usePrefersReducedMotion,
  useStoryPlayer,
} from './features/story/useStoryPlayer'
import { loadCaseData } from './data/caseData'
import { CaseMap } from './features/map/CaseMap'
import { LocationMap } from './features/map/LocationMap'
import { Inspector } from './features/inspector/Inspector'
import { ZonesPanel } from './features/zones/ZonesPanel'
import { MetricsPanel } from './features/metrics/MetricsPanel'
import { WeatherPanel } from './features/weather/WeatherPanel'
import { ProfilePanel } from './features/profile/ProfilePanel'
import { AnnotationPanel } from './features/annotations/AnnotationPanel'
import { mapStore, type LonLat } from './state/mapStore'
import type { ComparisonDates } from './features/map/ComparisonControls'
import { layersAreRenderable, type Layer } from './features/map/layers'

type CaseData = Awaited<ReturnType<typeof loadCaseData>>['case']

/**
 * Leaving the story keeps its layers and selection, but levels the camera for
 * the 2D analysis map and keeps it on the case (the story may end on a globe).
 */
function levelCamera() {
  const { camera, flyTo } = mapStore.getState()
  flyTo({
    center: camera.zoom < 8 ? [-121.3865, 35.916] : camera.center,
    zoom: Math.max(camera.zoom, 10),
    bearing: 0,
    pitch: 0,
  })
}

const productionStory = parseStory(storyJson)
const storyMinutes = productionStory
  ? Math.max(1, Math.round(storyDurationMs(productionStory.steps) / 60_000))
  : 0

function isValidSource(
  value: unknown,
): value is { label: string; url: string } {
  return (
    typeof value === 'object' &&
    value !== null &&
    'label' in value &&
    typeof value.label === 'string' &&
    value.label.length > 0 &&
    'url' in value &&
    typeof value.url === 'string' &&
    value.url.length > 0
  )
}

const queryClient = new QueryClient()

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AppContent />
    </QueryClientProvider>
  )
}

function AppContent() {
  const [status, setStatus] = useState<'loading' | 'mock' | 'real' | 'error'>(
    'loading',
  )
  const [layers, setLayers] = useState<Layer[]>([])
  const [dates, setDates] = useState<ComparisonDates>({
    before: 'Date unavailable',
    after: 'Date unavailable',
  })
  const [manifestError, setManifestError] = useState(false)
  const [caseData, setCaseData] = useState<CaseData | null>(null)
  const [view, setView] = useState<'overview' | 'analysis' | 'story'>(
    'overview',
  )
  const [profileSample, setProfileSample] = useState<LonLat | null>(null)
  const mapCapture = useRef<(() => string) | null>(null)
  const setCapture = useCallback((capture: (() => string) | null) => {
    mapCapture.current = capture
  }, [])

  const reducedMotion = usePrefersReducedMotion()
  // Only play the story written for the loaded case.
  const story =
    productionStory && caseData?.case_id === productionStory.case_id
      ? productionStory
      : null
  const player = useStoryPlayer(story, layers, reducedMotion, levelCamera)
  const { start, resume } = player
  const watchStory = () => {
    setView('story')
    start(0)
  }
  const canResume =
    player.status === 'exploring' && player.index < player.count - 1
  const resumeStory = () => {
    setView('story')
    resume()
  }
  useEffect(() => {
    let active = true
    loadCaseData(import.meta.env.VITE_DATA_BASE_URL || '/')
      .then((data) => {
        if (active) {
          setStatus(
            [data.case, data.stats, data.layers].some(
              (item) => item.data_status === 'mock',
            )
              ? 'mock'
              : 'real',
          )
          const currentCase = data.case
          setCaseData(currentCase)
          if (
            !currentCase.name ||
            !currentCase.location ||
            !currentCase.fire_start ||
            !currentCase.product ||
            !currentCase.epochs?.t1?.datetime ||
            !currentCase.epochs?.t2?.datetime ||
            !Array.isArray(currentCase.aoi_bbox) ||
            currentCase.aoi_bbox.length !== 4 ||
            !currentCase.aoi_bbox.every(Number.isFinite) ||
            !Array.isArray(currentCase.sources) ||
            currentCase.sources.length === 0 ||
            !currentCase.sources.every(isValidSource)
          ) {
            setManifestError(true)
          }
          if (!layersAreRenderable(data.layers.layers)) {
            setManifestError(true)
            return
          }
          const before = data.case.epochs?.t1?.datetime
          const after = data.case.epochs?.t2?.datetime
          if (typeof before !== 'string' || typeof after !== 'string') {
            setManifestError(true)
            return
          }
          setLayers(data.layers.layers)
          setDates({
            before: before.slice(0, 10),
            after: after.slice(0, 10),
          })
        }
      })
      .catch(() => {
        if (active) setStatus('error')
      })
    return () => {
      active = false
    }
  }, [])

  return (
    <main className="mx-auto max-w-6xl p-6">
      {status === 'mock' && (
        <p
          role="status"
          className="mb-4 rounded border border-amber-700 bg-amber-100 p-3 text-amber-950"
        >
          MOCK — synthetic data for development, not scientific validation.
        </p>
      )}
      {(status === 'error' || manifestError) && (
        <p role="alert" className="mb-4 text-red-700">
          Unable to load case data.
        </p>
      )}
      <h1 className="text-3xl font-semibold">FireTrace Explorer</h1>
      {view === 'overview' ? (
        <>
          {caseData && (
            <div className="mt-6 grid gap-6 lg:grid-cols-2">
              <section aria-labelledby="case-heading" className="space-y-4">
                <h2 id="case-heading" className="text-2xl font-semibold">
                  {caseData.name}
                </h2>
                <p>{caseData.location}</p>
                <dl className="grid gap-3 sm:grid-cols-2">
                  <div>
                    <dt className="font-semibold">Fire start</dt>
                    <dd>{caseData.fire_start || 'Unavailable'}</dd>
                  </div>
                  <div>
                    <dt className="font-semibold">Before observation (UTC)</dt>
                    <dd>{caseData.epochs?.t1?.datetime || 'Unavailable'}</dd>
                  </div>
                  <div>
                    <dt className="font-semibold">After observation (UTC)</dt>
                    <dd>{caseData.epochs?.t2?.datetime || 'Unavailable'}</dd>
                  </div>
                  <div>
                    <dt className="font-semibold">Radar product</dt>
                    <dd>{caseData.product || 'Unavailable'}</dd>
                  </div>
                </dl>
                <p>
                  Synthetic aperture radar (SAR) observes how the surface
                  scatters radar signals. Comparing observations can reveal
                  changes worth investigating.
                </p>
                <p className="rounded border border-amber-700 bg-amber-50 p-3 text-amber-950">
                  Exploratory evidence: observed radar changes are not confirmed
                  burned area. Moisture, terrain, geometry and vegetation can
                  also affect the signal.
                </p>
                <h3 className="font-semibold">Sources</h3>
                <ul className="list-inside list-disc">
                  {Array.isArray(caseData.sources) &&
                    caseData.sources
                      .filter(isValidSource)
                      .map((source) => (
                        <li key={source.url}>{source.label}</li>
                      ))}
                </ul>
              </section>
              {Array.isArray(caseData.aoi_bbox) &&
                caseData.aoi_bbox.length === 4 &&
                caseData.aoi_bbox.every(Number.isFinite) && (
                  <LocationMap bbox={caseData.aoi_bbox} />
                )}
            </div>
          )}
          <div className="mt-6 flex flex-wrap gap-3">
            {player.available && (
              <button
                type="button"
                onClick={watchStory}
                className="rounded bg-slate-900 px-4 py-2 text-white focus-visible:outline-2 focus-visible:outline-offset-2"
              >
                Watch the story ({storyMinutes} min)
              </button>
            )}
            <button
              type="button"
              onClick={() => setView('analysis')}
              className={
                player.available
                  ? 'rounded border px-4 py-2 focus-visible:outline-2 focus-visible:outline-offset-2'
                  : 'rounded bg-slate-900 px-4 py-2 text-white focus-visible:outline-2 focus-visible:outline-offset-2'
              }
            >
              Explore analysis
            </button>
          </div>
        </>
      ) : view === 'story' && player.active ? (
        <StoryView
          player={player}
          layers={layers}
          dataBaseUrl={import.meta.env.VITE_DATA_BASE_URL || '/'}
          dates={dates}
          isMock={status === 'mock'}
          reducedMotion={reducedMotion}
          onLeave={player.exit}
          onExplore={player.exit}
        />
      ) : (
        <>
          <div className="mt-4 flex flex-wrap gap-3">
            <button
              type="button"
              onClick={() => {
                player.exit()
                setView('overview')
              }}
              className="rounded border px-4 py-2 focus-visible:outline-2 focus-visible:outline-offset-2"
            >
              Back to overview
            </button>
            {/* One story button: resume where the user left it mid-way,
                otherwise (never started, or finished) play from the start. */}
            {canResume ? (
              <button
                type="button"
                onClick={resumeStory}
                className="rounded bg-slate-900 px-4 py-2 text-white focus-visible:outline-2 focus-visible:outline-offset-2"
              >
                Resume story · {player.index + 1}/{player.count}
              </button>
            ) : (
              player.available && (
                <button
                  type="button"
                  onClick={watchStory}
                  className="rounded border px-4 py-2 focus-visible:outline-2 focus-visible:outline-offset-2"
                >
                  Play story
                </button>
              )
            )}
          </div>
          <div className="mt-6 grid gap-4">
            <div className="overflow-hidden rounded-lg border border-slate-300">
              <CaseMap
                layers={layers}
                dates={dates}
                dataBaseUrl={import.meta.env.VITE_DATA_BASE_URL || '/'}
                profileSample={profileSample}
                onCaptureReady={setCapture}
              />
            </div>
            <ZonesPanel />
          </div>
          <Inspector caseData={caseData} />
          <ProfilePanel onSample={setProfileSample} />
          <AnnotationPanel
            caseData={caseData}
            displayStatus={status}
            captureMap={() => {
              if (!mapCapture.current) throw new Error('Map is unavailable')
              return mapCapture.current()
            }}
          />
          <MetricsPanel />
          <WeatherPanel dates={dates} />
        </>
      )}
    </main>
  )
}
