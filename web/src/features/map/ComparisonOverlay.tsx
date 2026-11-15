import { useEffect, useRef } from 'react'
import * as maplibregl from 'maplibre-gl'
import { mapStore } from '../../state/mapStore'
import { type Layer, visibleMapLayers } from './layers'
import { addMapLayers, syncMapLayers } from './mapLayers'
import { createBaseMapStyle } from './mapStyle'

export function ComparisonOverlay({
  primary,
  layers,
  dataBaseUrl,
  position,
  onError,
}: {
  primary: maplibregl.Map
  layers: Layer[]
  dataBaseUrl: string
  position: number
  onError: () => void
}) {
  const container = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!container.current) return
    const main = primary
    const displayed = visibleMapLayers(layers)
    const map = new maplibregl.Map({
      container: container.current,
      center: [-121.47, 35.92],
      zoom: 9,
      interactive: false,
      style: createBaseMapStyle(),
    })
    map.on('error', onError)
    const syncCamera = () => {
      const center = main.getCenter()
      map.jumpTo({
        center: [center.lng, center.lat],
        zoom: main.getZoom(),
        bearing: main.getBearing(),
        pitch: main.getPitch(),
        roll: main.getRoll(),
        padding: main.getPadding(),
      })
    }
    main.on('move', syncCamera)
    syncCamera()
    const syncLayers = () =>
      syncMapLayers(map, displayed, mapStore.getState(), 'right')
    const unsubscribe = mapStore.subscribe(syncLayers)
    map.on('load', () => {
      addMapLayers(map, displayed, dataBaseUrl, onError)
      syncLayers()
      syncCamera()
    })
    return () => {
      unsubscribe()
      main.off('move', syncCamera)
      map.remove()
    }
  }, [primary, layers, dataBaseUrl, onError])

  // MapLibre adds an unlayered `.maplibregl-map { position: relative }`.
  // Inline positioning keeps this map above the primary one.
  return (
    <div
      ref={container}
      data-testid="comparison-right-map"
      aria-hidden="true"
      style={{
        position: 'absolute',
        inset: 0,
        pointerEvents: 'none',
        clipPath: `inset(0 0 0 ${position * 100}%)`,
      }}
    />
  )
}
