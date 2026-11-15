import type {
  ExpressionSpecification,
  GeoJSONSourceSpecification,
  StyleSpecification,
} from 'maplibre-gl'
import type { Feature, FeatureCollection, LineString } from 'geojson'

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

type Bounds = [number, number, number, number]

/**
 * Latitude and longitude grid around the case. It is drawn from the case
 * footprint, so it stays a navigational reference and never implies data.
 */
export function createGraticule(bounds: number[]): FeatureCollection {
  const [west, south, east, north] = bounds as Bounds
  const pad = 1.5
  const step = 0.25
  const features: Feature<LineString>[] = []
  const minLon = Math.floor((west - pad) / step) * step
  const maxLon = Math.ceil((east + pad) / step) * step
  const minLat = Math.floor((south - pad) / step) * step
  const maxLat = Math.ceil((north + pad) / step) * step
  for (let lon = minLon; lon <= maxLon + 1e-9; lon += step) {
    features.push({
      type: 'Feature',
      properties: { kind: 'meridian', value: Number(lon.toFixed(2)) },
      geometry: {
        type: 'LineString',
        coordinates: [
          [lon, minLat],
          [lon, maxLat],
        ],
      },
    })
  }
  for (let lat = minLat; lat <= maxLat + 1e-9; lat += step) {
    features.push({
      type: 'Feature',
      properties: { kind: 'parallel', value: Number(lat.toFixed(2)) },
      geometry: {
        type: 'LineString',
        coordinates: [
          [minLon, lat],
          [maxLon, lat],
        ],
      },
    })
  }
  return { type: 'FeatureCollection', features }
}

/** Footprint of the displayed raster layers, used for the grid and the camera. */
export function layerBounds(
  layers: { coordinates?: [number, number][] }[],
): Bounds | null {
  const corners = layers
    .map((layer) => layer.coordinates)
    .filter(
      (value): value is [number, number][] =>
        Array.isArray(value) && value.length === 4,
    )
  if (corners.length === 0) return null
  const longitudes: number[] = []
  const latitudes: number[] = []
  for (const corner of corners) {
    for (const [lon, lat] of corner) {
      longitudes.push(lon)
      latitudes.push(lat)
    }
  }
  return [
    Math.min(...longitudes),
    Math.min(...latitudes),
    Math.max(...longitudes),
    Math.max(...latitudes),
  ]
}

/**
 * Analysis basemap: the same OpenStreetMap raster tiles, colour graded for a
 * dark mission console, with a latitude/longitude grid. Grading changes only
 * how the tiles are rendered; it never alters the data layers drawn above.
 */
export function createBaseMapStyle(
  options: { graticule?: number[] } = {},
): StyleSpecification {
  const sources: StyleSpecification['sources'] = {
    osm: {
      type: 'raster',
      tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
      tileSize: 256,
      maxzoom: 19,
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    },
  }
  const layers: StyleSpecification['layers'] = [
    {
      id: 'background',
      type: 'background',
      paint: { 'background-color': '#050d18' },
    },
    {
      id: 'basemap',
      type: 'raster',
      source: 'osm',
      paint: {
        'raster-saturation': -0.85,
        'raster-brightness-max': 0.42,
        'raster-brightness-min': 0.02,
        'raster-contrast': 0.3,
        'raster-hue-rotate': -12,
      },
    },
  ]
  if (options.graticule) {
    const graticule: GeoJSONSourceSpecification = {
      type: 'geojson',
      data: createGraticule(options.graticule),
    }
    sources.graticule = graticule
    layers.push({
      id: 'graticule',
      type: 'line',
      source: 'graticule',
      paint: {
        'line-color': 'rgba(125, 211, 252, 0.16)',
        'line-width': 1,
      },
    })
  }
  return { version: 8, sources, layers }
}

/**
 * Overview style: the same tiles on a globe with an atmosphere, so the case is
 * seen from space before the analysis map descends into it. The projection is
 * an expression, so zooming morphs the globe into the flat map natively.
 */
export function createGlobeMapStyle(): StyleSpecification {
  const base = createBaseMapStyle()
  return {
    ...base,
    projection: {
      type: [
        'interpolate',
        ['linear'],
        ['zoom'],
        1,
        'vertical-perspective',
        7,
        'mercator',
      ],
    },
    sky: {
      'sky-color': '#030a18',
      'horizon-color': '#1d4f7a',
      'fog-color': '#08182c',
      'sky-horizon-blend': 0.6,
      'horizon-fog-blend': 0.7,
      'fog-ground-blend': 0.4,
      'atmosphere-blend': [
        'interpolate',
        ['linear'],
        ['zoom'],
        0,
        1,
        6,
        0.35,
        8,
        0,
      ],
    },
    layers: base.layers.map((layer) =>
      layer.type === 'background'
        ? { ...layer, paint: { 'background-color': '#02060f' } }
        : layer,
    ),
  }
}

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
