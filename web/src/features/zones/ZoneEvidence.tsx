import { kindLabels, type ZoneKind } from './reviewZones'
import { useReviewZones } from './useReviewZones'

const legends: Record<ZoneKind, string> = {
  change_outside_perimeter:
    'Observed radar changes; to investigate, not errors.',
  no_change_inside_perimeter:
    'Little radar change inside the reference perimeter; discrepancy to investigate, not an error.',
  change_inside_perimeter:
    'Radar change inside the reference perimeter; agreement example.',
}

export function ZoneEvidence({ zoneId }: { zoneId: string }) {
  const { data, isPending, isError } = useReviewZones()
  const zone = data?.features.find(
    (f) => f.properties.zone_id === zoneId,
  )?.properties
  const db = (n: number) => `${n.toFixed(1)} dB`
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
          <p>{legends[zone.kind]}</p>
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
                  <td>{db(stats.t1_median)}</td>
                  <td>{db(stats.t2_median)}</td>
                  <td>{db(stats.delta_median)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p>
            Change index: median {zone.change_index.median.toFixed(2)}, P90{' '}
            {zone.change_index.p90.toFixed(2)}
          </p>
          <p>
            Distance to perimeter: {Math.round(zone.distance_to_perimeter_m)} m
          </p>
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
