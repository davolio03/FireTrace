import { useState } from 'react'
import { useMapStore } from '../../state/mapStore'
import type { Layer } from './layers'
import {
  comparisonPair,
  isSupportedComparison,
  type Polarization,
} from './comparison'

export interface ComparisonDates {
  before: string
  after: string
}

export function ComparisonControls({
  layers,
  dates,
}: {
  layers: Layer[]
  dates: ComparisonDates
}) {
  const compare = useMapStore((state) => state.compare)
  const setCompare = useMapStore((state) => state.setCompare)
  const [error, setError] = useState(false)

  function selectPair(polarization: Polarization) {
    const selected = comparisonPair(polarization)
    if (
      !isSupportedComparison(
        { ...selected, position: compare?.position ?? 0.5 },
        layers,
      )
    ) {
      setError(true)
      return
    }
    setError(false)
    setCompare({ ...selected, position: compare?.position ?? 0.5 })
  }

  function startComparison() {
    const hh = { ...comparisonPair('HH'), position: 0.5 }
    if (isSupportedComparison(hh, layers)) {
      selectPair('HH')
    } else {
      selectPair('HV')
    }
  }

  return (
    <section
      aria-label="Before and after comparison"
      className="rounded-lg border border-slate-300 p-4"
    >
      <h2 className="text-xl font-semibold">Before / after</h2>
      {error && (
        <p role="alert" className="mt-2 text-red-700">
          Comparison images are unavailable.
        </p>
      )}
      {compare && !isSupportedComparison(compare, layers) ? (
        <>
          <p role="alert" className="mt-2 text-red-700">
            Only available HH or HV before/after pairs can be compared here.
          </p>
          <button
            type="button"
            className="mt-3 rounded border px-3 py-2"
            onClick={() => setCompare(null)}
          >
            Exit comparison
          </button>
        </>
      ) : !compare ? (
        <button
          type="button"
          className="mt-3 rounded border px-3 py-2"
          onClick={startComparison}
        >
          Compare before and after
        </button>
      ) : (
        <>
          <p className="mt-2 text-sm">
            Only the comparison images are shown. Other raster selections are
            preserved and return when comparison ends.
          </p>
          <fieldset className="mt-3">
            <legend>Polarization</legend>
            {(['HH', 'HV'] as const).map((pol) => (
              <label key={pol} className="mr-4">
                <input
                  type="radio"
                  name="compare-polarization"
                  checked={
                    compare.left === comparisonPair(pol).left &&
                    compare.right === comparisonPair(pol).right
                  }
                  onChange={() => selectPair(pol)}
                />{' '}
                {pol}
              </label>
            ))}
          </fieldset>
          <div className="mt-3 flex justify-between gap-2 text-sm">
            <span>
              Before — {dates.before} —{' '}
              {compare.left.endsWith('_hv') ? 'HV' : 'HH'}
            </span>
            <span>
              After — {dates.after} —{' '}
              {compare.right.endsWith('_hv') ? 'HV' : 'HH'}
            </span>
          </div>
          <label className="mt-3 block text-sm">
            Comparison divider
            <input
              type="range"
              min="0"
              max="100"
              step="1"
              value={Math.round(compare.position * 100)}
              onChange={(event) =>
                setCompare({
                  ...compare,
                  position: Number(event.target.value) / 100,
                })
              }
              className="block w-full"
            />
          </label>
          <button
            type="button"
            className="mt-3 rounded border px-3 py-2"
            onClick={() => {
              setError(false)
              setCompare(null)
            }}
          >
            Exit comparison
          </button>
        </>
      )}
    </section>
  )
}
