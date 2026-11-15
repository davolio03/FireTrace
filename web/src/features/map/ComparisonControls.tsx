import { useState } from 'react'
import { useMapStore } from '../../state/mapStore'
import type { Layer } from './layers'
import {
  comparisonPair,
  isSupportedComparison,
  type Polarization,
  comparisonLabel,
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
  const opticalMode = compare?.left.startsWith('optical_') ?? false

  function selectOptical(left?: string, right?: string) {
    const optical =
      layers.find(
        (layer) =>
          layer.id === (left ?? 'optical_during') && layer.kind === 'raster',
      ) ??
      layers.find(
        (layer) =>
          (layer.id === 'optical_during' || layer.id === 'optical_after') &&
          layer.kind === 'raster',
      )
    const radar =
      layers.find(
        (layer) =>
          layer.id === (right ?? 'sar_t1_hh') && layer.kind === 'raster',
      ) ??
      layers.find(
        (layer) =>
          ['sar_t1_hh', 'sar_t2_hh', 'sar_t1_hv', 'sar_t2_hv'].includes(
            layer.id,
          ) && layer.kind === 'raster',
      )
    if (
      !optical ||
      !radar ||
      !isSupportedComparison(
        {
          left: optical.id,
          right: radar.id,
          position: compare?.position ?? 0.5,
        },
        layers,
      )
    ) {
      setError(true)
      return
    }
    setError(false)
    setCompare({
      left: optical.id,
      right: radar.id,
      position: compare?.position ?? 0.5,
    })
  }

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
    } else if (
      isSupportedComparison({ ...comparisonPair('HV'), position: 0.5 }, layers)
    ) {
      selectPair('HV')
    } else {
      selectOptical()
    }
  }

  function selectRadarMode() {
    if (
      isSupportedComparison({ ...comparisonPair('HH'), position: 0.5 }, layers)
    ) {
      selectPair('HH')
    } else if (
      isSupportedComparison({ ...comparisonPair('HV'), position: 0.5 }, layers)
    ) {
      selectPair('HV')
    } else {
      setError(true)
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
            Only available HH or HV before/after pairs or optical and radar
            pairs can be compared here.
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
            <legend>Comparison mode</legend>
            <label>
              <input
                type="radio"
                name="comparison-mode"
                checked={!opticalMode}
                onChange={selectRadarMode}
              />{' '}
              Before and after radar
            </label>{' '}
            <label>
              <input
                type="radio"
                name="comparison-mode"
                checked={opticalMode}
                onChange={() => selectOptical()}
              />{' '}
              Optical and radar
            </label>
          </fieldset>
          {opticalMode ? (
            <>
              <p className="mt-2 text-sm">
                Optical imagery is complementary context; it does not validate
                radar change or confirm burned area.
              </p>
              <label className="mt-3 block">
                Optical image
                <select
                  value={compare.left}
                  onChange={(event) =>
                    selectOptical(event.target.value, compare.right)
                  }
                >
                  {layers
                    .filter((layer) =>
                      ['optical_during', 'optical_after'].includes(layer.id),
                    )
                    .map((layer) => (
                      <option key={layer.id} value={layer.id}>
                        {layer.title}
                      </option>
                    ))}
                </select>
              </label>
              <label className="mt-3 block">
                Radar observation
                <select
                  value={compare.right}
                  onChange={(event) =>
                    selectOptical(compare.left, event.target.value)
                  }
                >
                  {layers
                    .filter((layer) =>
                      [
                        'sar_t1_hh',
                        'sar_t2_hh',
                        'sar_t1_hv',
                        'sar_t2_hv',
                      ].includes(layer.id),
                    )
                    .map((layer) => (
                      <option key={layer.id} value={layer.id}>
                        {layer.title}
                      </option>
                    ))}
                </select>
              </label>
            </>
          ) : (
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
          )}
          <div className="mt-3 flex justify-between gap-2 text-sm">
            <span>{comparisonLabel(compare.left, layers, dates)}</span>
            <span>{comparisonLabel(compare.right, layers, dates)}</span>
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
