import { useEffect, useState } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { loadCaseData } from './data/caseData'
import { CaseMap } from './features/map/CaseMap'
import { LocationMap } from './features/map/LocationMap'
import { Inspector } from './features/inspector/Inspector'
import type { ComparisonDates } from './features/map/ComparisonControls'
import { layersAreRenderable, type Layer } from './features/map/layers'

type CaseData = Awaited<ReturnType<typeof loadCaseData>>['case']

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
  const [view, setView] = useState<'overview' | 'analysis'>('overview')

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
          <button
            type="button"
            onClick={() => setView('analysis')}
            className="mt-6 rounded bg-slate-900 px-4 py-2 text-white focus-visible:outline-2 focus-visible:outline-offset-2"
          >
            Explore analysis
          </button>
        </>
      ) : (
        <>
          <button
            type="button"
            onClick={() => setView('overview')}
            className="mt-4 rounded border px-4 py-2 focus-visible:outline-2 focus-visible:outline-offset-2"
          >
            Back to overview
          </button>
          <div className="mt-6 overflow-hidden rounded-lg border border-slate-300">
            <CaseMap
              layers={layers}
              dates={dates}
              dataBaseUrl={import.meta.env.VITE_DATA_BASE_URL || '/'}
            />
          </div>
          <Inspector caseData={caseData} />
        </>
      )}
    </main>
  )
}
