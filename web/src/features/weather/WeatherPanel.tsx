import { useQuery } from '@tanstack/react-query'
import type { ComparisonDates } from '../map/ComparisonControls'

type Weather = {
  data_status: 'mock' | 'real'
  units: string
  aggregation: string
  source: { label: string }
  period: { start: string; end: string }
  daily: { date: string; value: number | null }[]
}

function isWeather(value: unknown): value is Weather {
  if (
    typeof value !== 'object' ||
    value === null ||
    !('data_status' in value) ||
    !('variable' in value) ||
    !('units' in value) ||
    !('aggregation' in value) ||
    !('source' in value) ||
    !('period' in value) ||
    !('daily' in value)
  )
    return false
  const source = value.source
  const period = value.period
  return (
    (value.data_status === 'mock' || value.data_status === 'real') &&
    value.variable === 'precipitation' &&
    value.units === 'mm/day' &&
    typeof value.aggregation === 'string' &&
    typeof source === 'object' &&
    source !== null &&
    'label' in source &&
    typeof source.label === 'string' &&
    typeof period === 'object' &&
    period !== null &&
    'start' in period &&
    typeof period.start === 'string' &&
    'end' in period &&
    typeof period.end === 'string' &&
    /^\d{4}-\d{2}-\d{2}$/.test(period.start) &&
    /^\d{4}-\d{2}-\d{2}$/.test(period.end) &&
    Number.isFinite(Date.parse(period.start)) &&
    Number.isFinite(Date.parse(period.end)) &&
    period.start <= period.end &&
    Array.isArray(value.daily) &&
    value.daily.every(
      (day: unknown) =>
        typeof day === 'object' &&
        day !== null &&
        'date' in day &&
        typeof day.date === 'string' &&
        /^\d{4}-\d{2}-\d{2}$/.test(day.date) &&
        'value' in day &&
        (day.value === null ||
          (typeof day.value === 'number' &&
            Number.isFinite(day.value) &&
            day.value >= 0)),
    )
  )
}

export function WeatherPanel({ dates }: { dates: ComparisonDates }) {
  const base = import.meta.env.VITE_DATA_BASE_URL || '/'
  const query = useQuery({
    queryKey: ['weather', base],
    retry: false,
    queryFn: async ({ signal }): Promise<unknown> => {
      const response = await fetch(`${base.replace(/\/+$/, '')}/weather.json`, {
        signal,
      })
      if (!response.ok) throw new Error('Unable to load weather')
      return response.json() as Promise<unknown>
    },
  })
  const data = query.data
  const mock =
    typeof data === 'object' &&
    data !== null &&
    'data_status' in data &&
    data.data_status === 'mock'
  const max = isWeather(data)
    ? Math.max(0, ...data.daily.map((day) => day.value ?? 0))
    : 0
  const missingDays =
    isWeather(data) &&
    new Set(
      data.daily
        .filter(
          (day) => day.date >= data.period.start && day.date <= data.period.end,
        )
        .map((day) => day.date),
    ).size <
      (Date.parse(data.period.end) - Date.parse(data.period.start)) / 86400000 +
        1
  return (
    <section
      aria-labelledby="weather-heading"
      className="mt-6 space-y-3 rounded-lg border border-slate-300 p-4"
    >
      <h2 id="weather-heading" className="text-xl font-semibold">
        Rainfall context
      </h2>
      {query.isPending && <p role="status">Loading rainfall context…</p>}
      {query.isError && <p role="alert">Unable to load rainfall context.</p>}
      {mock && <p>MOCK — synthetic weather data, not scientific validation.</p>}
      {data !== undefined && !isWeather(data) && (
        <p role="alert">Rainfall data is incomplete or invalid.</p>
      )}
      {isWeather(data) && (
        <>
          <p>Source: {data.source.label}</p>
          <p>
            Aggregation: {data.aggregation}; precipitation in {data.units}.
          </p>
          <p>
            Radar observations: {dates.before} — before; {dates.after} — after.
          </p>
          <p>
            Rainfall is complementary context, not proof of the cause of radar
            changes.
          </p>
          {data.daily.length === 0 && (
            <p>No daily rainfall data is available.</p>
          )}
          {missingDays && (
            <p>Some days are missing from the reported period.</p>
          )}
          {data.daily.some((day) => day.value === null) && (
            <p>Some daily values are not available.</p>
          )}
          <div className="max-h-80 overflow-auto">
            <table className="w-full text-left">
              <caption className="text-left font-semibold">
                Daily precipitation ({data.units})
              </caption>
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Precipitation</th>
                  <th>Relative bar</th>
                </tr>
              </thead>
              <tbody>
                {data.daily.map((day, index) => (
                  <tr key={`${day.date}-${index}`}>
                    <th scope="row">
                      {day.date}
                      {day.date === dates.before ? ' — before' : ''}
                      {day.date === dates.after ? ' — after' : ''}
                    </th>
                    <td>{day.value === null ? 'Not available' : day.value}</td>
                    <td aria-hidden="true">
                      {day.value !== null && (
                        <span
                          className="block h-3 bg-blue-700"
                          style={{
                            width: `${max > 0 ? (day.value / max) * 100 : 0}%`,
                          }}
                        />
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  )
}
