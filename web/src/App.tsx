import { useCallback, useEffect, useRef, useState } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  domAnimation,
  LazyMotion,
  MotionConfig,
  type Variants,
} from 'motion/react'
import * as m from 'motion/react-m'
import {
  Activity,
  ArrowLeft,
  ArrowRight,
  BarChart3,
  Crosshair,
  Layers,
  MapPin,
  NotebookPen,
  Play,
  Route,
  X,
} from 'lucide-react'
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
import { MetricsPanel } from './features/metrics/MetricsPanel'
import { WeatherPanel } from './features/weather/WeatherPanel'
import { ProfilePanel } from './features/profile/ProfilePanel'
import { AnnotationPanel } from './features/annotations/AnnotationPanel'
import { mapStore, useMapStore, type LonLat } from './state/mapStore'
import {
  ComparisonControls,
  type ComparisonDates,
} from './features/map/ComparisonControls'
import { LayerControls } from './features/map/LayerControls'
import { layersAreRenderable, type Layer } from './features/map/layers'

type CaseData = Awaited<ReturnType<typeof loadCaseData>>['case']
type WorkspacePanel =
  'layers' | 'inspect' | 'transect' | 'annotations' | 'results'
const workspacePanels = [
  { id: 'layers', label: 'Layers', icon: Layers },
  { id: 'inspect', label: 'Inspect', icon: Crosshair },
  { id: 'transect', label: 'Transect', icon: Route },
  { id: 'annotations', label: 'Annotations', icon: NotebookPen },
  { id: 'results', label: 'Results', icon: BarChart3 },
] as const

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

/**
 * Entrance choreography: the overview reads in order instead of appearing at
 * once. With reduced motion the elements are simply present.
 */
const revealContainer: Variants = {
  hidden: {},
  show: {
    transition: { staggerChildren: 0.07, delayChildren: 0.04 },
  },
}

const revealItem: Variants = {
  hidden: { opacity: 0, y: 18 },
  show: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.5, ease: [0.2, 0.7, 0.2, 1] },
  },
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <MotionConfig reducedMotion="user">
        <LazyMotion features={domAnimation} strict>
          <AppContent />
        </LazyMotion>
      </MotionConfig>
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
  const [activePanel, setActivePanel] = useState<WorkspacePanel>('layers')
  const [diveToken, setDiveToken] = useState(0)
  const mapTool = useMapStore((state) => state.tool)
  const mapSelection = useMapStore((state) => state.selection)
  const comparison = useMapStore((state) => state.compare)
  const mapCapture = useRef<(() => string) | null>(null)
  const setCapture = useCallback((capture: (() => string) | null) => {
    mapCapture.current = capture
  }, [])
  // The descent from the globe ends where the analysis map starts, so the
  // shared camera keeps the reader's place. If the map never reports the
  // descent, the reader still enters the analysis after a short wait.
  const [diving, setDiving] = useState(false)
  const completeDive = useCallback(
    (camera: { center: [number, number]; zoom: number }) => {
      mapStore
        .getState()
        .flyTo(
          { center: camera.center, zoom: camera.zoom, bearing: 0, pitch: 0 },
          0,
        )
      setDiving(false)
      setView('analysis')
    },
    [],
  )
  useEffect(() => {
    if (!diving) return
    const fallback = setTimeout(() => {
      setDiving(false)
      setView('analysis')
    }, 2500)
    return () => clearTimeout(fallback)
  }, [diving])

  const reducedMotion = usePrefersReducedMotion()
  const activeToolLabel =
    workspacePanels.find((panel) => panel.id === activePanel)?.label ?? 'Tools'
  const mapToolLabel =
    mapTool === 'inspect'
      ? 'Inspect mode'
      : mapTool === 'draw-profile'
        ? 'Draw transect'
        : 'Pan mode'
  const mapSelectionLabel =
    mapSelection.type === 'point'
      ? 'Point selected'
      : mapSelection.type === 'profile'
        ? `Transect ${mapSelection.line.length} pts`
        : mapSelection.type === 'zone'
          ? `Zone ${mapSelection.zoneId}`
          : 'No selection'
  // Number keys switch tools, like an instrument panel.
  useEffect(() => {
    if (view !== 'analysis') return
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null
      if (
        target &&
        (target.isContentEditable ||
          ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName))
      )
        return
      const index = Number(event.key) - 1
      const panel = workspacePanels[index]
      if (!panel) return
      setActivePanel(panel.id)
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [view])
  // Only play the story written for the loaded case.
  const story =
    productionStory && caseData?.case_id === productionStory.case_id
      ? productionStory
      : null
  const onStoryExit = () => {
    const panel = mapStore.getState().panel
    if (panel === 'inspector') setActivePanel('inspect')
    else if (panel === 'profile') setActivePanel('transect')
    else if (panel === 'metrics' || panel === 'weather')
      setActivePanel('results')
    levelCamera()
  }
  const player = useStoryPlayer(story, layers, reducedMotion, onStoryExit)
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

  const isHud = view === 'analysis'

  return (
    <main className={isHud ? 'app-shell app-shell--hud' : 'app-shell'}>
      {!isHud && (
        <header className="app-header">
          <div className="app-brand">
            <span className="brand-mark" aria-hidden="true">
              <Activity size={21} />
            </span>
            <div>
              <span className="brand-eyebrow">NISAR · FIELD EXPLORER</span>
              <h1>FireTrace Explorer</h1>
            </div>
          </div>
          <div className="header-meta">
            <span className="header-location">
              <MapPin size={14} aria-hidden="true" />{' '}
              {caseData?.location || 'Location unavailable'}
            </span>
            <span className={`data-badge data-badge--${status}`}>
              <span className="status-dot" aria-hidden="true" />
              {status === 'mock'
                ? 'MOCK DATA'
                : status === 'real'
                  ? 'REAL DATA'
                  : status === 'error'
                    ? 'DATA UNAVAILABLE'
                    : 'LOADING DATA'}
            </span>
          </div>
        </header>
      )}
      <div className={isHud ? 'hud-root' : 'app-content'}>
        {(status === 'error' || manifestError) && (
          <p role="alert" className="data-error">
            Unable to load case data.
          </p>
        )}
        {view === 'overview' ? (
          <div className="overview">
            {caseData && (
              <>
                {Array.isArray(caseData.aoi_bbox) &&
                  caseData.aoi_bbox.length === 4 &&
                  caseData.aoi_bbox.every(Number.isFinite) && (
                    <m.div
                      className="overview-globe"
                      initial={{ opacity: 0, scale: 1.04 }}
                      animate={{ opacity: 1, scale: 1 }}
                      transition={{ duration: 0.9, ease: [0.2, 0.7, 0.2, 1] }}
                    >
                      <LocationMap
                        bbox={caseData.aoi_bbox}
                        diveToken={diveToken}
                        onDiveComplete={completeDive}
                      />
                    </m.div>
                  )}
                <m.div
                  className="overview-overlay"
                  initial="hidden"
                  animate="show"
                  variants={revealContainer}
                >
                  <m.section
                    aria-labelledby="case-heading"
                    className="overview-copy"
                    variants={revealItem}
                  >
                    <p className="section-kicker">
                      <span /> NISAR CASE STUDY / 01
                    </p>
                    <h2 id="case-heading" className="overview-title">
                      {caseData.name}
                    </h2>
                    <p className="overview-location">
                      <MapPin size={17} aria-hidden="true" />{' '}
                      {caseData.location}
                    </p>
                    <p className="overview-lead">
                      Explore how the landscape changed through the lens of
                      radar.
                    </p>
                    <p className="overview-description">
                      Synthetic aperture radar (SAR) observes how the surface
                      scatters radar signals. Comparing observations can reveal
                      changes worth investigating.
                    </p>
                    <div className="overview-actions">
                      <button
                        type="button"
                        onClick={() => {
                          setDiving(true)
                          setDiveToken((token) => token + 1)
                        }}
                        className="button-primary"
                      >
                        Explore analysis{' '}
                        <ArrowRight size={17} aria-hidden="true" />
                      </button>
                      {player.available && (
                        <button
                          type="button"
                          onClick={watchStory}
                          className="button-secondary"
                        >
                          <Play size={15} aria-hidden="true" /> Watch the story
                          ({storyMinutes} min)
                        </button>
                      )}
                    </div>
                    <p className="science-note">
                      Exploratory evidence: observed radar changes are not
                      confirmed burned area. Moisture, terrain, geometry and
                      vegetation can also affect the signal.
                    </p>
                    <details className="source-details">
                      <summary>View data sources</summary>
                      <ul>
                        {Array.isArray(caseData.sources) &&
                          caseData.sources
                            .filter(isValidSource)
                            .map((source) => (
                              <li key={source.url}>{source.label}</li>
                            ))}
                      </ul>
                    </details>
                  </m.section>
                  <m.aside
                    className="overview-meta"
                    aria-label="Case metadata"
                    variants={revealItem}
                  >
                    <div>
                      <span className="overview-meta-label">Fire start</span>
                      <span className="overview-meta-value">
                        {caseData.fire_start || 'Unavailable'}
                      </span>
                    </div>
                    <div>
                      <span className="overview-meta-label">
                        Before observation (UTC)
                      </span>
                      <span className="overview-meta-value">
                        {caseData.epochs?.t1?.datetime || 'Unavailable'}
                      </span>
                    </div>
                    <div>
                      <span className="overview-meta-label">
                        After observation (UTC)
                      </span>
                      <span className="overview-meta-value">
                        {caseData.epochs?.t2?.datetime || 'Unavailable'}
                      </span>
                    </div>
                    <div>
                      <span className="overview-meta-label">Radar product</span>
                      <span className="overview-meta-value">
                        {caseData.product || 'Unavailable'}
                      </span>
                    </div>
                  </m.aside>
                </m.div>
              </>
            )}
            {status === 'mock' && (
              <p role="status" className="overview-mock">
                <span className="status-dot" aria-hidden="true" />
                MOCK — synthetic data for development, not scientific
                validation.
              </p>
            )}
          </div>
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
          <div className="hud">
            <header className="hud-bar">
              <div className="hud-identity">
                <span className="h-mark" aria-hidden="true">
                  <Activity size={15} />
                </span>
                <span className="hud-case">{caseData?.name ?? 'Case'}</span>
                <span className="hud-window">
                  {caseData?.epochs?.t1?.datetime?.slice(0, 10) ?? '-'} to{' '}
                  {caseData?.epochs?.t2?.datetime?.slice(0, 10) ?? '-'}
                </span>
              </div>
              <div className="hud-bar-actions">
                {status === 'mock' && (
                  <span className="hud-mock" role="status">
                    <span className="status-dot" aria-hidden="true" />
                    <span className="hud-mock-full">
                      MOCK DATA - NOT SCIENTIFIC VALIDATION
                    </span>
                    <span className="hud-mock-short" aria-hidden="true">
                      MOCK
                    </span>
                  </span>
                )}
                <button
                  type="button"
                  onClick={() => {
                    player.exit()
                    setView('overview')
                  }}
                  className="hud-button"
                >
                  <ArrowLeft size={14} aria-hidden="true" /> Overview
                </button>
                {canResume ? (
                  <button
                    type="button"
                    onClick={resumeStory}
                    className="hud-button"
                  >
                    <Play size={13} aria-hidden="true" /> Resume story ·{' '}
                    {player.index + 1}/{player.count}
                  </button>
                ) : (
                  player.available && (
                    <button
                      type="button"
                      onClick={watchStory}
                      className="hud-button"
                    >
                      <Play size={13} aria-hidden="true" /> Play story
                    </button>
                  )
                )}
              </div>
            </header>
            <div className="hud-stage">
              <CaseMap
                layers={layers}
                dates={dates}
                dataBaseUrl={import.meta.env.VITE_DATA_BASE_URL || '/'}
                profileSample={profileSample}
                onCaptureReady={setCapture}
                sidebar={
                  <>
                    <nav className="hud-rail" aria-label="Analysis tools">
                      {workspacePanels.map(({ id, label, icon: Icon }) => (
                        <button
                          key={id}
                          type="button"
                          aria-pressed={activePanel === id}
                          aria-label={label}
                          title={label}
                          onClick={() => setActivePanel(id)}
                          className="hud-rail-button"
                        >
                          <Icon size={18} aria-hidden="true" />
                          <span className="hud-rail-tip" aria-hidden="true">
                            {label}
                          </span>
                        </button>
                      ))}
                    </nav>
                    <m.section
                      className="hud-panel"
                      aria-label={activeToolLabel + ' panel'}
                      initial={{ opacity: 0, x: -24 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{
                        type: 'spring',
                        stiffness: 320,
                        damping: 32,
                      }}
                    >
                      <div className="hud-panel-head">
                        <span className="hud-panel-title">
                          {activeToolLabel}
                        </span>
                        <button
                          type="button"
                          className="hud-panel-close"
                          onClick={() => setActivePanel('layers')}
                          aria-label="Show layers panel"
                        >
                          <X size={14} aria-hidden="true" />
                        </button>
                      </div>
                      <div className="hud-panel-body">
                        <div hidden={activePanel !== 'layers'}>
                          <ComparisonControls layers={layers} dates={dates} />
                          <LayerControls layers={layers} />
                        </div>
                        <div hidden={activePanel !== 'inspect'}>
                          <Inspector caseData={caseData} />
                        </div>
                        <div hidden={activePanel !== 'transect'}>
                          <ProfilePanel onSample={setProfileSample} />
                        </div>
                        <div hidden={activePanel !== 'annotations'}>
                          <AnnotationPanel
                            caseData={caseData}
                            displayStatus={status}
                            captureMap={() => {
                              if (!mapCapture.current)
                                throw new Error('Map is unavailable')
                              return mapCapture.current()
                            }}
                          />
                        </div>
                        <div hidden={activePanel !== 'results'}>
                          <MetricsPanel />
                          <WeatherPanel dates={dates} />
                        </div>
                      </div>
                    </m.section>
                    <div className="hud-readout" aria-label="Map readout">
                      <span>{mapToolLabel}</span>
                      <span>{mapSelectionLabel}</span>
                      <span>{comparison ? 'Comparison' : 'Single view'}</span>
                    </div>
                  </>
                }
              />
              <div className="hud-boot" aria-hidden="true" />
            </div>
          </div>
        )}
      </div>
    </main>
  )
}
