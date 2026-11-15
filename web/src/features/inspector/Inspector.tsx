import { useQuery } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import type { operations } from '../../generated/api'
import { useMapStore } from '../../state/mapStore'

type PointEvidence =
  operations['inspectPoint']['responses'][200]['content']['application/json']
type CaseData =
  operations['getCase']['responses'][200]['content']['application/json']

export function Inspector({ caseData }: { caseData: CaseData | null }) {
  const selection = useMapStore((state) => state.selection)
  const panel = useMapStore((state) => state.panel)
  const select = useMapStore((state) => state.select)
  const setTool = useMapStore((state) => state.setTool)
  const tool = useMapStore((state) => state.tool)
  const [lon, setLon] = useState('')
  const [lat, setLat] = useState('')
  const [inputError, setInputError] = useState(false)
  const point = selection.type === 'point' ? selection.point : null
  const query = useQuery({
    queryKey: ['inspect-point', point?.[0], point?.[1]],
    enabled: point !== null && panel === 'inspector',
    retry: false,
    queryFn: async ({ signal }): Promise<PointEvidence> => {
      if (!point) throw new Error('No point selected')
      const params = new URLSearchParams({
        lon: String(point[0]),
        lat: String(point[1]),
      })
      const base = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/+$/, '')
      const response = await fetch(`${base}/api/inspect/point?${params}`, {
        signal,
      })
      if (!response.ok) throw new Error('Point inspection failed')
      return response.json() as Promise<PointEvidence>
    },
  })

  function inspectCoordinates(event: FormEvent) {
    event.preventDefault()
    const x = Number(lon),
      y = Number(lat)
    if (
      !lon.trim() ||
      !lat.trim() ||
      !Number.isFinite(x) ||
      !Number.isFinite(y) ||
      Math.abs(x) > 180 ||
      Math.abs(y) > 90
    ) {
      setInputError(true)
      return
    }
    setInputError(false)
    select({ type: 'point', point: [x, y] })
  }

  const value = (n: number | null | undefined) =>
    n == null ? 'Not available' : String(n)
  const data = query.data
  return (
    <div className="mt-6 space-y-3 rounded-lg border border-slate-300 p-4">
      <h2 className="text-xl font-semibold">Point selection</h2>
      <button
        type="button"
        aria-pressed={tool === 'inspect'}
        onClick={() => setTool(tool === 'inspect' ? 'pan' : 'inspect')}
        className={
          tool === 'inspect'
            ? 'rounded border bg-slate-900 px-3 py-2 text-white'
            : 'rounded border px-3 py-2'
        }
      >
        Inspect on map
      </button>
      <p>
        {tool === 'inspect'
          ? 'Inspection mode active: click a point on the map.'
          : 'Activate inspection mode to select a point on the map, or enter coordinates.'}
      </p>
      <form
        onSubmit={inspectCoordinates}
        className="flex flex-wrap items-end gap-2"
      >
        <label>
          Longitude{' '}
          <input
            className="block w-32 rounded border p-1"
            value={lon}
            onChange={(e) => setLon(e.target.value)}
            inputMode="decimal"
          />
        </label>
        <label>
          Latitude{' '}
          <input
            className="block w-32 rounded border p-1"
            value={lat}
            onChange={(e) => setLat(e.target.value)}
            inputMode="decimal"
          />
        </label>
        <button type="submit" className="rounded border px-3 py-1">
          Inspect coordinates
        </button>
      </form>
      {inputError && <p role="alert">Enter valid longitude and latitude.</p>}
      {!point && <p>Select a point to inspect its evidence.</p>}
      {point && (
        <p>
          Selected coordinates: {point[0]}, {point[1]}
        </p>
      )}
      {panel === 'inspector' && (
        <section aria-labelledby="inspector-heading" className="space-y-3">
          <h2 id="inspector-heading" className="text-xl font-semibold">
            Evidence Inspector
          </h2>
          {point && query.isFetching && (
            <p role="status">Loading point evidence…</p>
          )}
          {point && query.isError && (
            <p role="alert">Unable to load point evidence.</p>
          )}
          {point && data && !query.isFetching && (
            <div className="space-y-3">
              {data.data_status === 'mock' && (
                <p className="font-semibold">
                  MOCK — synthetic evidence, not scientific validation.
                </p>
              )}
              {!data.pixel ? (
                <p>Point is outside the analysis area.</p>
              ) : !data.valid ? (
                <p>
                  No valid radar data for this pixel. One or more inputs may be
                  masked in one or more layers or contain invalid values.
                </p>
              ) : (
                <>
                  <p>Backscatter (dB); delta = after − before.</p>
                  <table className="w-full text-left">
                    <caption className="sr-only">Radar backscatter</caption>
                    <thead>
                      <tr>
                        <th>Polarization</th>
                        <th>Before</th>
                        <th>After</th>
                        <th>Delta</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr>
                        <th>HH</th>
                        <td>{value(data.hh_db.t1)}</td>
                        <td>{value(data.hh_db.t2)}</td>
                        <td>{value(data.hh_db.delta)}</td>
                      </tr>
                      <tr>
                        <th>HV</th>
                        <td>{value(data.hv_db.t1)}</td>
                        <td>{value(data.hv_db.t2)}</td>
                        <td>{value(data.hv_db.delta)}</td>
                      </tr>
                    </tbody>
                  </table>
                  <p>Change index: {value(data.change_index)}</p>
                  <p>
                    Percentile among valid pixels:{' '}
                    <span>{value(data.change_index_percentile)}</span>
                  </p>
                </>
              )}
              <p>Official perimeter relation: {data.perimeter_relation}</p>
              <p>Observed radar changes are not confirmed burned area.</p>
              <p>Method ID: {data.method_id}</p>
              {caseData?.data_status === data.data_status &&
                caseData?.method?.id === data.method_id && (
                  <p>
                    {caseData.method.name} — {caseData.method.description}
                  </p>
                )}
              <p>
                Moisture, terrain, geometry and vegetation can affect radar
                signals.
              </p>
              {data.caveats.map((caveat) => (
                <p key={caveat.id}>
                  {caveat.label}: {caveat.reason}
                </p>
              ))}
              <h3 className="font-semibold">Sources</h3>
              <ul>
                {caseData?.data_status === data.data_status &&
                  caseData?.sources?.map((source) => (
                    <li key={source.url}>
                      {/^https?:\/\//i.test(source.url) ? (
                        <a href={source.url} className="underline">
                          {source.label}
                        </a>
                      ) : (
                        source.label
                      )}
                    </li>
                  ))}
              </ul>
            </div>
          )}
        </section>
      )}
    </div>
  )
}
