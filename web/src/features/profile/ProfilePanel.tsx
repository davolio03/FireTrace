import { useQuery } from '@tanstack/react-query'
import { useEffect } from 'react'
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { operations } from '../../generated/api'
import { useMapStore, type LonLat } from '../../state/mapStore'

type Profile =
  operations['inspectProfile']['responses'][200]['content']['application/json']

function validProfile(value: unknown): value is Profile {
  if (
    typeof value !== 'object' ||
    value === null ||
    !('contract_version' in value) ||
    value.contract_version !== '1.2.0' ||
    !('data_status' in value) ||
    (value.data_status !== 'mock' && value.data_status !== 'real') ||
    !('samples' in value) ||
    !Array.isArray(value.samples) ||
    !('perimeter_crossings_m' in value) ||
    !Array.isArray(value.perimeter_crossings_m) ||
    !value.perimeter_crossings_m.every(
      (x: unknown) => typeof x === 'number' && Number.isFinite(x) && x >= 0,
    ) ||
    !('length_m' in value) ||
    typeof value.length_m !== 'number' ||
    !Number.isFinite(value.length_m) ||
    value.length_m < 0 ||
    !('spacing_m' in value) ||
    typeof value.spacing_m !== 'number' ||
    !Number.isFinite(value.spacing_m) ||
    value.spacing_m <= 0
  )
    return false
  return value.samples.every((sample: unknown) => {
    if (typeof sample !== 'object' || sample === null) return false
    const item = sample as Record<string, unknown>
    return (
      ['distance_m', 'lon', 'lat'].every(
        (key) => typeof item[key] === 'number' && Number.isFinite(item[key]),
      ) &&
      typeof item.distance_m === 'number' &&
      item.distance_m >= 0 &&
      typeof item.lon === 'number' &&
      Math.abs(item.lon) <= 180 &&
      typeof item.lat === 'number' &&
      Math.abs(item.lat) <= 90 &&
      typeof item.valid === 'boolean' &&
      ['hh_t1', 'hh_t2', 'hv_t1', 'hv_t2', 'change_index'].every(
        (key) =>
          item[key] === null ||
          (typeof item[key] === 'number' && Number.isFinite(item[key])),
      )
    )
  })
}

export function ProfilePanel({
  onSample,
}: {
  onSample: (point: LonLat | null) => void
}) {
  const selection = useMapStore((state) => state.selection)
  const panel = useMapStore((state) => state.panel)
  const tool = useMapStore((state) => state.tool)
  const select = useMapStore((state) => state.select)
  const setTool = useMapStore((state) => state.setTool)
  const line = selection.type === 'profile' ? selection.line : null
  const drawing = tool === 'draw-profile'
  const query = useQuery({
    queryKey: ['profile', line],
    enabled:
      !!line && line.length >= 2 && tool === 'pan' && panel === 'profile',
    retry: false,
    queryFn: async ({ signal }): Promise<unknown> => {
      const base = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/+$/, '')
      const response = await fetch(`${base}/api/inspect/profile`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ line }),
        signal,
      })
      if (!response.ok) throw new Error('Unable to load profile')
      return response.json() as Promise<unknown>
    },
  })

  const data = validProfile(query.data) ? query.data : null
  useEffect(() => {
    onSample(null)
  }, [line, onSample])
  const rows =
    data?.samples.map((sample) => ({
      ...sample,
      hh_t1: sample.valid ? sample.hh_t1 : null,
      hh_t2: sample.valid ? sample.hh_t2 : null,
      hv_t1: sample.valid ? sample.hv_t1 : null,
      hv_t2: sample.valid ? sample.hv_t2 : null,
      change_index: sample.valid ? sample.change_index : null,
    })) ?? []
  const display = (value: number | null) =>
    value === null ? 'Not available' : String(value)

  return (
    <section
      aria-labelledby="profile-heading"
      className="mt-6 space-y-3 rounded-lg border border-slate-300 p-4"
    >
      <h2 id="profile-heading" className="text-xl font-semibold">
        Transect profile
      </h2>
      {!drawing ? (
        <button
          type="button"
          className="rounded border px-3 py-2"
          onClick={() => {
            onSample(null)
            select({ type: 'profile', line: [] })
            setTool('draw-profile')
          }}
        >
          Draw transect
        </button>
      ) : (
        <>
          <p>Click at least two points on the map, then finish the transect.</p>
          <p>Vertices: {line?.length ?? 0}</p>
          <button
            type="button"
            className="rounded border px-3 py-2"
            disabled={!line || line.length < 2}
            onClick={() => setTool('pan')}
          >
            Finish transect
          </button>{' '}
          <button
            type="button"
            className="rounded border px-3 py-2"
            onClick={() => {
              onSample(null)
              select({ type: 'none' })
              setTool('pan')
            }}
          >
            Cancel
          </button>
        </>
      )}
      {!drawing && panel === 'profile' && line && line.length >= 2 && (
        <>
          {query.isFetching && <p role="status">Loading profile…</p>}
          {query.isError && <p role="alert">Unable to load profile.</p>}
          {query.data !== undefined && !data && (
            <p role="alert">Profile data is incomplete or invalid.</p>
          )}
          {data && !query.isFetching && (
            <>
              {data.data_status === 'mock' && (
                <p>
                  MOCK — synthetic profile; distances, spacing and crossings are
                  illustrative, not scientific validation.
                </p>
              )}
              {data.truncated && (
                <p role="status">
                  The profile was truncated by the sample limit.
                </p>
              )}
              <p>
                Length: {data.length_m} m; spacing: {data.spacing_m} m.
              </p>
              <p>
                Radar changes are not confirmed burned area. The official
                perimeter is an operational reference.
              </p>
              {rows.length === 0 && <p>No profile samples are available.</p>}
              {rows.length > 0 && rows.every((row) => !row.valid) && (
                <p>
                  No valid samples; the line may be outside the analysis area or
                  masked.
                </p>
              )}
              {rows.length > 0 && (
                <>
                  <p>
                    Backscatter is shown in dB; the change index uses its own
                    axis. Gaps indicate unavailable values.
                  </p>
                  <div className="h-80 w-full" aria-label="Transect chart">
                    <ResponsiveContainer width="100%" height="100%">
                      <LineChart
                        data={rows}
                        onMouseLeave={() => onSample(null)}
                        onMouseMove={(event) => {
                          if (event.activeTooltipIndex == null) {
                            onSample(null)
                            return
                          }
                          const index = Number(event.activeTooltipIndex)
                          const sample = rows[index]
                          if (sample) onSample([sample.lon, sample.lat])
                        }}
                      >
                        <CartesianGrid strokeDasharray="3 3" />
                        <XAxis
                          dataKey="distance_m"
                          type="number"
                          domain={['dataMin', 'dataMax']}
                          label={{
                            value: 'Distance (m)',
                            position: 'insideBottom',
                            offset: -5,
                          }}
                        />
                        <YAxis
                          yAxisId="db"
                          label={{
                            value: 'Backscatter (dB)',
                            angle: -90,
                            position: 'insideLeft',
                          }}
                        />
                        <YAxis
                          yAxisId="index"
                          orientation="right"
                          label={{
                            value: 'Change index',
                            angle: 90,
                            position: 'insideRight',
                          }}
                        />
                        <Tooltip />
                        <Legend />
                        {data.perimeter_crossings_m.map((distance, index) => (
                          <ReferenceLine
                            key={`${distance}-${index}`}
                            x={distance}
                            yAxisId="db"
                            stroke="#111827"
                            strokeDasharray="3 3"
                          />
                        ))}
                        <Line
                          yAxisId="db"
                          dataKey="hh_t1"
                          name="HH before"
                          stroke="#1d4ed8"
                          dot={false}
                          connectNulls={false}
                        />
                        <Line
                          yAxisId="db"
                          dataKey="hh_t2"
                          name="HH after"
                          stroke="#1d4ed8"
                          strokeDasharray="5 3"
                          dot={false}
                          connectNulls={false}
                        />
                        <Line
                          yAxisId="db"
                          dataKey="hv_t1"
                          name="HV before"
                          stroke="#b45309"
                          dot={false}
                          connectNulls={false}
                        />
                        <Line
                          yAxisId="db"
                          dataKey="hv_t2"
                          name="HV after"
                          stroke="#b45309"
                          strokeDasharray="5 3"
                          dot={false}
                          connectNulls={false}
                        />
                        <Line
                          yAxisId="index"
                          dataKey="change_index"
                          name="Change index"
                          stroke="#6d28d9"
                          dot={false}
                          connectNulls={false}
                        />
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                  <p>
                    Perimeter crossings (m):{' '}
                    {data.perimeter_crossings_m.length
                      ? data.perimeter_crossings_m.join(', ')
                      : 'None reported'}
                  </p>
                  <div className="max-h-80 overflow-auto">
                    <table className="w-full text-left text-sm">
                      <caption>
                        Profile samples; use a sample button to mark it on the
                        map
                      </caption>
                      <thead>
                        <tr>
                          <th>Distance (m)</th>
                          <th>HH before</th>
                          <th>HH after</th>
                          <th>HV before</th>
                          <th>HV after</th>
                          <th>Change index</th>
                        </tr>
                      </thead>
                      <tbody>
                        {rows.map((row, index) => (
                          <tr key={`${row.distance_m}-${index}`}>
                            <th scope="row">
                              <button
                                type="button"
                                className="underline"
                                onFocus={() => onSample([row.lon, row.lat])}
                                onClick={() => onSample([row.lon, row.lat])}
                              >
                                Sample at {row.distance_m} m
                              </button>
                            </th>
                            <td>{display(row.hh_t1)}</td>
                            <td>{display(row.hh_t2)}</td>
                            <td>{display(row.hv_t1)}</td>
                            <td>{display(row.hv_t2)}</td>
                            <td>{display(row.change_index)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </>
              )}
            </>
          )}
        </>
      )}
    </section>
  )
}
