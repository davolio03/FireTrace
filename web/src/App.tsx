import { useEffect, useState } from 'react'
import { loadCaseData } from './data/caseData'
import { CaseMap } from './features/map/CaseMap'

export default function App() {
  const [status, setStatus] = useState<'loading' | 'mock' | 'real' | 'error'>(
    'loading',
  )

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
      {status === 'error' && (
        <p role="alert" className="mb-4 text-red-700">
          Unable to load case data.
        </p>
      )}
      <h1 className="text-3xl font-semibold">FireTrace Explorer</h1>
      <p className="mt-2 text-slate-600">Plaskett Fire · Big Sur, California</p>
      <p className="mt-2 text-sm text-slate-600">
        Map scaffold only. Scientific layers and evidence are not yet available.
      </p>
      <div className="mt-6 overflow-hidden rounded-lg border border-slate-300">
        <CaseMap />
      </div>
    </main>
  )
}
