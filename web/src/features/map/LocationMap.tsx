import { useEffect, useRef, useState } from 'react'
import * as maplibregl from 'maplibre-gl'
import mapWorkerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url'
import { createBaseMapStyle } from './mapStyle'

export function LocationMap({ bbox }: { bbox: number[] }) {
  const container = useRef<HTMLDivElement>(null)
  const [error, setError] = useState(false)

  useEffect(() => {
    if (!container.current) return
    maplibregl.setWorkerUrl(mapWorkerUrl)
    const map = new maplibregl.Map({
      container: container.current,
      center: [(bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2],
      zoom: 9,
      style: createBaseMapStyle(),
    })
    map.on('error', () => setError(true))
    map.on('load', () => {
      map.fitBounds(
        [
          [bbox[0], bbox[1]],
          [bbox[2], bbox[3]],
        ],
        { padding: 32, duration: 0 },
      )
    })
    return () => map.remove()
  }, [bbox])

  return (
    <section
      aria-label="Location map"
      className="overflow-hidden rounded-lg border border-slate-300"
    >
      {error && (
        <p role="alert" className="p-3">
          The location map could not load. Check your connection.
        </p>
      )}
      <div ref={container} className="h-72 w-full" />
    </section>
  )
}
