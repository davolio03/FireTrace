import type { ExpressionSpecification, StyleSpecification } from 'maplibre-gl'

/** A value for the globe view (zoom ≤ 4) easing into one for the terrain (≥ 9). */
const zoomRamp = (globe: number, terrain: number): ExpressionSpecification => [
  'interpolate',
  ['linear'],
  ['zoom'],
  4,
  globe,
  9,
  terrain,
]

/**
 * Full-screen story style: the same OSM basemap, dimmed, on a globe, with a
 * dark space background and an atmosphere that fades out as the camera comes
 * down.
 */
export function createCinematicMapStyle(): StyleSpecification {
  const base = createBaseMapStyle()
  return {
    ...base,
    projection: { type: 'globe' },
    // Dusk palette: a deep sky, a soft blue horizon glow and a dark haze
    // that matches the dimmed basemap instead of washing it out.
    sky: {
      'sky-color': '#071330',
      'horizon-color': '#3b6db3',
      'fog-color': '#16233b',
      'sky-horizon-blend': 0.5,
      'horizon-fog-blend': 0.6,
      'fog-ground-blend': 0.35,
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
    // A dimmed, desaturated basemap: the radar, the perimeter and the text
    // stay the brightest things on screen.
    layers: base.layers.map((layer) =>
      layer.type === 'background'
        ? { ...layer, paint: { 'background-color': '#020617' } }
        : layer.type === 'raster'
          ? {
              ...layer,
              // Colourful from space, dim once the radar takes the stage.
              paint: {
                'raster-saturation': zoomRamp(-0.1, -0.65),
                'raster-brightness-max': zoomRamp(0.85, 0.5),
                'raster-contrast': 0.15,
                'raster-fade-duration': 600,
              },
            }
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
