import { useEffect, useRef } from 'react'
import * as maplibregl from 'maplibre-gl'

export function CaseMap() {
  const container = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!container.current) return
    const map = new maplibregl.Map({
      container: container.current,
      center: [-121.47, 35.92],
      zoom: 9,
      style: {
        version: 8,
        sources: {
          osm: {
            type: 'raster',
            tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
            tileSize: 256,
            maxzoom: 19,
            attribution:
              '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
          },
        },
        layers: [
          {
            id: 'background',
            type: 'background',
            paint: { 'background-color': '#dbeafe' },
          },
          { id: 'basemap', type: 'raster', source: 'osm' },
        ],
      },
    })
    map.addControl(new maplibregl.NavigationControl())
    return () => map.remove()
  }, [])

  return (
    <div
      ref={container}
      role="region"
      aria-label="Map of Big Sur"
      className="h-[32rem] w-full"
    />
  )
}
