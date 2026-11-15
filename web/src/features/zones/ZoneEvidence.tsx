import { kindLabels } from './reviewZones'
import { useReviewZones } from './useReviewZones'

export function ZoneEvidence({ zoneId }: { zoneId: string }) {
  const { data, isPending, isError } = useReviewZones()
  const zone = data?.features.find(
    (f) => f.properties.zone_id === zoneId,
  )?.properties
  const pct = (n: number) => `${Math.round(n * 100)}%`

  return (
    <section aria-labelledby="zone-evidence-heading" className="space-y-3">
      <h2 id="zone-evidence-heading" className="text-xl font-semibold">
        Zone evidence: {zoneId}
      </h2>
      {isPending && <p role="status">Loading zone evidence…</p>}
      {(isError || (data && !zone)) && (
        <p role="alert">Unable to load zone evidence.</p>
      )}
      {data?.data_status === 'mock' && (
        <p className="font-semibold">
          MOCK — synthetic evidence, not scientific validation.
        </p>
      )}
      {zone && (
        <>
          <p>{kindLabels[zone.kind]}</p>
          <p>Observed radar changes; to investigate, not errors.</p>
          <table className="w-full text-left">
            <caption className="sr-only">Zone radar backscatter</caption>
            <thead>
              <tr>
                <th>Polarization (dB, median)</th>
                <th>Before</th>
                <th>After</th>
                <th>Delta</th>
              </tr>
            </thead>
            <tbody>
              {(
                [
                  ['HH', zone.hh_db],
                  ['HV', zone.hv_db],
                ] as const
              ).map(([name, stats]) => (
                <tr key={name}>
                  <th>{name}</th>
                  <td>{stats.t1_median}</td>
                  <td>{stats.t2_median}</td>
                  <td>{stats.delta_median}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p>
            Change index: median {zone.change_index.median}, P90{' '}
            {zone.change_index.p90}
          </p>
          <p>Distance to perimeter: {zone.distance_to_perimeter_m} m</p>
          <p>Valid data: {pct(zone.valid_fraction)}</p>
          {zone.caveats.map((caveat) => (
            <p key={caveat.id}>
              {caveat.label}: {pct(caveat.fraction)}
            </p>
          ))}
        </>
      )}
    </section>
  )
}
