import { useQuery } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import type { operations } from '../../generated/api'
import { useMapStore } from '../../state/mapStore'
import { ZoneEvidence } from '../zones/ZoneEvidence'

type PointEvidence =
  operations['inspectPoint']['responses'][200]['content']['application/json']
type CaseData =
  operations['getCase']['responses'][200]['content']['application/json']

type Failure = 'invalid' | 'unavailable' | 'unreachable' | 'unknown'

/** Request failure that keeps the UI message independent of server detail. */
class InspectionFailure extends Error {
  constructor(readonly kind: Failure) {
    super(kind)
  }
}

function failureMessage(kind: Failure): string {
  switch (kind) {
    case 'invalid':
      return 'The point query was rejected as invalid (422).'
    case 'unavailable':
      return 'Inspection products are unavailable or incompatible on the server (503).'
    case 'unreachable':
      return 'Unable to load point evidence: the API is unreachable.'
    default:
      return 'Unable to load point evidence.'
  }
}

function errorMessage(error: unknown): string {
  return failureMessage(
    error instanceof InspectionFailure ? error.kind : 'unknown',
  )
}

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
      if (!point) throw new InspectionFailure('unknown')
      const params = new URLSearchParams({
        lon: String(point[0]),
        lat: String(point[1]),
      })
      const base = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/+$/, '')
      let response: Response
      try {
        response = await fetch(`${base}/api/inspect/point?${params}`, {
          signal,
        })
      } catch {
        throw new InspectionFailure('unreachable')
      }
      if (!response.ok) {
        throw new InspectionFailure(
          response.status === 422
            ? 'invalid'
            : response.status === 503
              ? 'unavailable'
              : 'unknown',
        )
      }
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
  const measured = (n: number | null | undefined, unit: string) =>
    n == null ? 'Not available' : `${n}${unit}`
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
      {selection.type === 'zone' && <ZoneEvidence zoneId={selection.zoneId} />}
      {panel === 'inspector' && (
        <section aria-labelledby="inspector-heading" className="space-y-3">
          <h2 id="inspector-heading" className="text-xl font-semibold">
            Evidence Inspector
          </h2>
          {point && query.isFetching && (
            <p role="status">Loading point evidence…</p>
          )}
          {point && query.isError && (
            <p role="alert">{errorMessage(query.error)}</p>
          )}
          {point && data && !query.isFetching && (
            <div className="space-y-3">
              {data.data_status === 'mock' && (
                <p className="font-semibold">
                  MOCK — synthetic evidence, not scientific validation.
                </p>
              )}
              {data.pixel ? (
                <dl className="grid gap-2 sm:grid-cols-2">
                  <div>
                    <dt className="font-semibold">Sampled pixel</dt>
                    <dd>
                      row {data.pixel.row}, col {data.pixel.col} (10 m analysis
                      grid)
                    </dd>
                  </div>
                  <div>
                    <dt className="font-semibold">Projected centre</dt>
                    <dd>
                      {value(data.pixel.x)}, {value(data.pixel.y)} m (
                      {data.pixel.crs})
                    </dd>
                  </div>
                  <div>
                    <dt className="font-semibold">Centre (WGS84)</dt>
                    <dd>
                      {value(data.pixel.center_lon)},{' '}
                      {value(data.pixel.center_lat)}
                    </dd>
                  </div>
                  <div>
                    <dt className="font-semibold">Contract version</dt>
                    <dd>{data.contract_version}</dd>
                  </div>
                </dl>
              ) : (
                <p>Point is outside the analysis area.</p>
              )}
              {data.pixel && !data.valid && (
                <p>
                  No valid radar data for this pixel. One or more inputs may be
                  masked in one or more layers or contain invalid values.
                </p>
              )}
              {data.pixel && data.valid && (
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
              {data.terrain && (
                <section aria-labelledby="inspector-terrain-heading">
                  <h3 id="inspector-terrain-heading" className="font-semibold">
                    Terrain at this pixel
                  </h3>
                  <dl className="grid gap-2 sm:grid-cols-3">
                    <div>
                      <dt className="font-semibold">Elevation</dt>
                      <dd>{measured(data.terrain.elevation_m, ' m')}</dd>
                    </div>
                    <div>
                      <dt className="font-semibold">Slope</dt>
                      <dd>{measured(data.terrain.slope_deg, '°')}</dd>
                    </div>
                    <div>
                      <dt className="font-semibold">Aspect</dt>
                      <dd>{measured(data.terrain.aspect_deg, '°')}</dd>
                    </div>
                  </dl>
                  <p>
                    Terrain context comes from the DEM resampled to the analysis
                    grid; it neither explains nor confirms the radar change.
                  </p>
                </section>
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
