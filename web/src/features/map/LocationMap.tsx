import { useEffect, useRef, useState } from 'react'
import * as maplibregl from 'maplibre-gl'
import mapWorkerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url'
import { createGlobeMapStyle } from './mapStyle'

const GLOBE_ZOOM = 1.5
const CASE_ZOOM = 11

function prefersReducedMotion() {
  return (
    typeof window !== 'undefined' &&
    window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true
  )
}

/**
 * Overview map: the case seen from space on a globe with an atmosphere. When
 * the reader asks for the analysis, the globe descends into the case and the
 * shared camera is left where the descent ended.
 */
export function LocationMap({
  bbox,
  diveToken,
  onDiveComplete,
}: {
  bbox: number[]
  /** Increment to start the descent into the case. */
  diveToken?: number
  onDiveComplete?: (camera: { center: [number, number]; zoom: number }) => void
}) {
  const container = useRef<HTMLDivElement>(null)
  const [error, setError] = useState(false)
  const [marker, setMarker] = useState<{ x: number; y: number } | null>(null)
  const mapRef = useRef<maplibregl.Map | null>(null)
  const diveTokenRef = useRef(diveToken ?? 0)

  useEffect(() => {
    if (!container.current) return
    maplibregl.setWorkerUrl(mapWorkerUrl)
    const center: [number, number] = [
      (bbox[0] + bbox[2]) / 2,
      (bbox[1] + bbox[3]) / 2,
    ]
    const map = new maplibregl.Map({
      container: container.current,
      center,
      zoom: GLOBE_ZOOM,
      style: createGlobeMapStyle(),
    })
    mapRef.current = map
    map.on('error', () => setError(true))
    // The globe sits to the right of the title block, so the case is never
    // hidden behind the copy. Padding shifts the vanishing point.
    const placeGlobe = () => {
      const width = container.current?.clientWidth ?? 0
      const left = width > 760 ? Math.round(width * 0.2) : 0
      map.jumpTo({
        center,
        zoom: GLOBE_ZOOM,
        padding: { left, top: 0, right: 0, bottom: 0 },
      })
      const point = map.project(center)
      setMarker({ x: point.x, y: point.y })
    }
    const onMove = () => {
      const point = map.project(center)
      setMarker({ x: point.x, y: point.y })
    }
    map.on('load', () => {
      placeGlobe()
    })
    map.on('move', onMove)
    map.on('resize', placeGlobe)
    return () => {
      mapRef.current = null
      map.remove()
    }
  }, [bbox])

  useEffect(() => {
    const map = mapRef.current
    if (!map || diveToken === undefined) return
    if (diveToken === diveTokenRef.current) return
    diveTokenRef.current = diveToken
    const center: [number, number] = [
      (bbox[0] + bbox[2]) / 2,
      (bbox[1] + bbox[3]) / 2,
    ]
    const finish = () => onDiveComplete?.({ center, zoom: CASE_ZOOM })
    if (prefersReducedMotion()) {
      map.jumpTo({ center, zoom: CASE_ZOOM })
      finish()
      return
    }
    map.once('moveend', finish)
    map.flyTo({
      center,
      zoom: CASE_ZOOM,
      duration: 1600,
      curve: 1.4,
      essential: true,
    })
  }, [diveToken, bbox, onDiveComplete])

  return (
    <section
      aria-label="Location map"
      className="overview-map-frame relative overflow-hidden rounded-lg"
    >
      <div ref={container} className="h-full w-full" />
      {error && (
        <p role="alert" className="data-error absolute inset-x-3 bottom-3">
          The location map could not load. Check your connection.
        </p>
      )}
      <div className="overview-map-scan" aria-hidden="true" />
      {marker && (
        <div
          aria-hidden="true"
          className="overview-map-reticle"
          style={{ left: marker.x, top: marker.y }}
        />
      )}
    </section>
  )
}
