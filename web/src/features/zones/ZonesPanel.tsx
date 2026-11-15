import { useMapStore } from '../../state/mapStore'
import {
  cameraForBbox,
  groupZones,
  kindLabels,
  type ReviewZones,
  type ZoneKind,
} from './reviewZones'
import { useReviewZones } from './useReviewZones'

const sections: { title: string; kinds: ZoneKind[] }[] = [
  {
    title: 'Discrepancies to investigate',
    kinds: ['change_outside_perimeter', 'no_change_inside_perimeter'],
  },
  { title: 'Agreement examples', kinds: ['change_inside_perimeter'] },
]

export function ZonesPanel() {
  const query = useReviewZones()
  const selection = useMapStore((state) => state.selection)
  const select = useMapStore((state) => state.select)
  const flyTo = useMapStore((state) => state.flyTo)
  const data: ReviewZones | undefined = query.data
  const selectedId = selection.type === 'zone' ? selection.zoneId : null
  const groups = data ? groupZones(data) : []

  return (
    <section
      aria-labelledby="zones-heading"
      className="space-y-3 rounded-lg border border-slate-300 p-4"
    >
      <h2 id="zones-heading" className="text-xl font-semibold">
        Zones to review
      </h2>
      {query.isPending && <p role="status">Loading zones…</p>}
      {query.isError && <p role="alert">Unable to load review zones.</p>}
      {data?.data_status === 'mock' && (
        <p className="font-semibold">
          MOCK — synthetic zones, not scientific validation.
        </p>
      )}
      {data &&
        sections.map((section) => (
          <div key={section.title} className="space-y-2">
            <h3 className="font-semibold">{section.title}</h3>
            {groups
              .filter((g) => section.kinds.includes(g.kind))
              .map((group) => (
                <section key={group.kind} className="space-y-1">
                  <h4 className="text-sm">{kindLabels[group.kind]}</h4>
                  {group.zones.length === 0 ? (
                    <p className="text-sm">
                      No zones of this kind ≥ {data.method.min_area_ha} ha
                    </p>
                  ) : (
                    <ul className="space-y-1">
                      {group.zones.map(({ properties: zone }) => {
                        const selected = zone.zone_id === selectedId
                        return (
                          <li key={zone.zone_id}>
                            <button
                              type="button"
                              aria-pressed={selected}
                              onClick={() => {
                                select({ type: 'zone', zoneId: zone.zone_id })
                                flyTo(cameraForBbox(zone.bbox), 1000)
                              }}
                              className={`w-full rounded border px-2 py-1 text-left focus-visible:outline-2 focus-visible:outline-offset-2 ${
                                selected
                                  ? 'border-2 border-slate-900 bg-slate-100 font-semibold'
                                  : ''
                              }`}
                            >
                              {zone.zone_id} · {zone.area_ha} ha
                              {selected ? ' · selected' : ''}
                            </button>
                          </li>
                        )
                      })}
                    </ul>
                  )}
                </section>
              ))}
          </div>
        ))}
      {data && (
        <p className="text-xs text-slate-700">
          Method: change index above {data.method.change_threshold} counts as
          changed; below {data.method.no_change_threshold} inside the perimeter
          counts as little change. {data.method.smoothing}. Minimum{' '}
          {data.method.min_area_ha} ha, up to {data.method.max_zones_per_kind}{' '}
          zones per kind.
        </p>
      )}
    </section>
  )
}
