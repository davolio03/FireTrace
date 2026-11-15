import { useEffect, useState } from 'react'
import type { Map as MapLibreMap } from 'maplibre-gl'
import type { LonLat } from '../../state/mapStore'

export function ProfileOverlay({
  map,
  line,
  sample,
}: {
  map: MapLibreMap
  line: LonLat[]
  sample: LonLat | null
}) {
  const [, setRevision] = useState(0)
  useEffect(() => {
    const update = () => setRevision((value) => value + 1)
    map.on('move', update)
    map.on('resize', update)
    return () => {
      map.off('move', update)
      map.off('resize', update)
    }
  }, [map])
  const points = line.map((point) => map.project(point))
  const focus = sample ? map.project(sample) : null
  return (
    <svg
      aria-hidden="true"
      className="pointer-events-none absolute inset-0 h-full w-full"
    >
      {points.length >= 2 && (
        <polyline
          points={points.map((p) => `${p.x},${p.y}`).join(' ')}
          fill="none"
          stroke="#ffffff"
          strokeWidth="6"
        />
      )}
      {points.length >= 2 && (
        <polyline
          points={points.map((p) => `${p.x},${p.y}`).join(' ')}
          fill="none"
          stroke="#1d4ed8"
          strokeWidth="3"
        />
      )}
      {points.map((point, index) => (
        <circle
          key={index}
          cx={point.x}
          cy={point.y}
          r="5"
          fill="#1d4ed8"
          stroke="#ffffff"
          strokeWidth="2"
        />
      ))}
      {focus && (
        <circle
          cx={focus.x}
          cy={focus.y}
          r="8"
          fill="#facc15"
          stroke="#111827"
          strokeWidth="2"
        />
      )}
    </svg>
  )
}
