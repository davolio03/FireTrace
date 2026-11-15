import { useQuery } from '@tanstack/react-query'
import type { operations } from '../../generated/api'

type Stats =
  operations['getStats']['responses'][200]['content']['application/json']
type Zone = Stats['inside_perimeter']

function validNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

function validZone(zone: unknown): zone is Zone {
  if (
    typeof zone !== 'object' ||
    zone === null ||
    !('valid_pixels' in zone) ||
    !('area_ha' in zone) ||
    !('change_index' in zone)
  )
    return false
  const dist = zone.change_index
  return (
    validNumber(zone.valid_pixels) &&
    zone.valid_pixels >= 0 &&
    validNumber(zone.area_ha) &&
    zone.area_ha >= 0 &&
    typeof dist === 'object' &&
    dist !== null &&
    ['p5', 'p25', 'p50', 'p75', 'p95', 'mean'].every(
      (key) => key in dist && validNumber(dist[key as keyof typeof dist]),
    )
  )
}

function validStats(value: unknown): value is Stats {
  if (
    typeof value !== 'object' ||
    value === null ||
    !('data_status' in value) ||
    !('valid_pixels' in value) ||
    !('total_pixels' in value) ||
    !('valid_coverage_pct' in value) ||
    !('inside_perimeter' in value) ||
    !('outside_perimeter' in value)
  )
    return false
  return (
    (value.data_status === 'mock' || value.data_status === 'real') &&
    validNumber(value.valid_pixels) &&
    value.valid_pixels >= 0 &&
    validNumber(value.total_pixels) &&
    value.total_pixels >= 0 &&
    value.valid_pixels <= value.total_pixels &&
    validNumber(value.valid_coverage_pct) &&
    value.valid_coverage_pct >= 0 &&
    value.valid_coverage_pct <= 100 &&
    (value.valid_pixels !== 0 || value.valid_coverage_pct === 0) &&
    validZone(value.inside_perimeter) &&
    validZone(value.outside_perimeter)
  )
}

function Distribution({ title, zone }: { title: string; zone: Zone }) {
  const metrics = [
    ['Mean', zone.change_index.mean],
    ['P5', zone.change_index.p5],
    ['P25', zone.change_index.p25],
    ['Median (P50)', zone.change_index.p50],
    ['P75', zone.change_index.p75],
    ['P95', zone.change_index.p95],
  ] as const
  return (
    <section aria-label={title} className="rounded border border-slate-300 p-3">
      <h3 className="font-semibold">{title}</h3>
      <p>Valid pixels: {zone.valid_pixels}</p>
      {zone.valid_pixels === 0 ? (
        <p>No valid pixels in this region.</p>
      ) : (
        <>
          <p>Reported region area: {zone.area_ha} ha</p>
          <dl>
            {metrics.map(([label, number]) => (
              <div key={label} className="flex justify-between gap-4">
                <dt>{label}</dt>
                <dd>{number}</dd>
              </div>
            ))}
          </dl>
        </>
      )}
    </section>
  )
}

export function MetricsPanel() {
  const query = useQuery({
    queryKey: ['web-stats', import.meta.env.VITE_DATA_BASE_URL || '/'],
    retry: false,
    queryFn: async ({ signal }): Promise<unknown> => {
      const base = (import.meta.env.VITE_DATA_BASE_URL || '/').replace(
        /\/+$/,
        '',
      )
      const response = await fetch(`${base}/stats.json`, { signal })
      if (!response.ok) throw new Error('Unable to load statistics')
      return response.json() as Promise<unknown>
    },
  })
  const result = query.data
  const mock =
    typeof result === 'object' &&
    result !== null &&
    'data_status' in result &&
    result.data_status === 'mock'
  return (
    <section
      aria-labelledby="results-heading"
      className="mt-6 space-y-3 rounded-lg border border-slate-300 p-4"
    >
      <h2 id="results-heading" className="text-xl font-semibold">
        Results
      </h2>
      {query.isPending && <p role="status">Loading statistics…</p>}
      {query.isError && <p role="alert">Unable to load statistics.</p>}
      {mock && <p>MOCK — synthetic statistics, not scientific validation.</p>}
      {result !== undefined && !validStats(result) && (
        <p role="alert">Statistics are incomplete or invalid.</p>
      )}
      {validStats(result) && (
        <>
          <h3 className="font-semibold">Valid coverage</h3>
          <dl className="grid gap-2 sm:grid-cols-3">
            <div>
              <dt>Valid pixels</dt>
              <dd>{result.valid_pixels}</dd>
            </div>
            <div>
              <dt>Total pixels</dt>
              <dd>{result.total_pixels}</dd>
            </div>
            <div>
              <dt>Valid coverage</dt>
              <dd>{result.valid_coverage_pct}%</dd>
            </div>
          </dl>
          <p>
            Observed radar changes are not confirmed burned area. The
            operational perimeter predates the after observation and is not
            pixel-level ground truth.
          </p>
          {result.valid_pixels === 0 ? (
            <p>No valid pixels are available.</p>
          ) : (
            <>
              <h3 className="font-semibold">Change-index statistics</h3>
              <div className="grid gap-3 sm:grid-cols-2">
                <Distribution
                  title="Inside official perimeter"
                  zone={result.inside_perimeter}
                />
                <Distribution
                  title="Outside official perimeter"
                  zone={result.outside_perimeter}
                />
              </div>
            </>
          )}
        </>
      )}
    </section>
  )
}
