import type { StyleSpecification } from 'maplibre-gl'

/**
 * Full-screen story style: the same OSM basemap on a globe, with a dark space
 * background and an atmosphere that fades out as the camera comes down.
 */
export function createCinematicMapStyle(): StyleSpecification {
  const base = createBaseMapStyle()
  return {
    ...base,
    projection: { type: 'globe' },
    sky: {
      'sky-color': '#0b1d3a',
      'horizon-color': '#9cc9ff',
      'fog-color': '#c9dcff',
      'sky-horizon-blend': 0.6,
      'horizon-fog-blend': 0.5,
      'fog-ground-blend': 0.25,
      'atmosphere-blend': [
        'interpolate',
        ['linear'],
        ['zoom'],
        0,
        1,
        5,
        1,
        8,
        0,
      ],
    },
    layers: base.layers.map((layer) =>
      layer.type === 'background'
        ? { ...layer, paint: { 'background-color': '#020617' } }
        : layer,
    ),
  }
}

export function createBaseMapStyle(): StyleSpecification {
  return {
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
  }
}
