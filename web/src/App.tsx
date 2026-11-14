import { CaseMap } from './features/map/CaseMap'

export default function App() {
  return (
    <main className="mx-auto max-w-6xl p-6">
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
