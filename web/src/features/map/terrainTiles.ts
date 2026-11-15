/** Vertical exaggeration of the story relief; the view says so on screen. */
export const TERRAIN_EXAGGERATION = 1.6

export interface TerrainTiles {
  tileSize: number
  minzoom: number
  maxzoom: number
  bounds: [number, number, number, number]
  attribution: string
}

/** Reads the optional `terrain/tiles.json` manifest (terrain-tiles schema). */
export function parseTerrainTiles(value: unknown): TerrainTiles | null {
  if (typeof value !== 'object' || value === null) return null
  const doc = value as Record<string, unknown>
  const finite = (n: unknown): n is number =>
    typeof n === 'number' && Number.isFinite(n)
  if (
    doc.encoding !== 'terrarium' ||
    !(doc.tileSize === 256 || doc.tileSize === 512) ||
    !finite(doc.minzoom) ||
    !finite(doc.maxzoom) ||
    doc.minzoom > doc.maxzoom ||
    !Array.isArray(doc.bounds) ||
    doc.bounds.length !== 4 ||
    !doc.bounds.every(finite) ||
    typeof doc.attribution !== 'string'
  )
    return null
  return {
    tileSize: doc.tileSize,
    minzoom: doc.minzoom,
    maxzoom: doc.maxzoom,
    bounds: doc.bounds as [number, number, number, number],
    attribution: doc.attribution,
  }
}
