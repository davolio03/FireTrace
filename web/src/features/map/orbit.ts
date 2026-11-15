import type { LonLat } from '../../state/mapStore'

/**
 * Illustrative NISAR ground track for the story opening. It is a great circle
 * with the mission's nominal inclination drawn through the centre of the real
 * frame footprint, heading south (descending pass). It ignores Earth rotation
 * and the real orbit state vectors, so the UI must label it "illustrative".
 */
export const NISAR_INCLINATION_DEG = 98.4
export const NISAR_ALTITUDE_KM = 747

const toRad = (deg: number) => (deg * Math.PI) / 180
const toDeg = (rad: number) => (rad * 180) / Math.PI

/** Mean of a closed ring's vertices (the repeated last vertex is ignored). */
export function ringCentre(ring: LonLat[]): LonLat {
  const open =
    ring.length > 1 &&
    ring[0][0] === ring[ring.length - 1][0] &&
    ring[0][1] === ring[ring.length - 1][1]
      ? ring.slice(0, -1)
      : ring
  const lon = open.reduce((sum, [x]) => sum + x, 0) / open.length
  const lat = open.reduce((sum, [, y]) => sum + y, 0) / open.length
  return [lon, lat]
}

/** Heading (degrees from north) of a descending pass at a given latitude. */
export function descendingHeadingDeg(
  latDeg: number,
  inclinationDeg = NISAR_INCLINATION_DEG,
) {
  const ratio = Math.cos(toRad(inclinationDeg)) / Math.cos(toRad(latDeg))
  const ascending = toDeg(Math.asin(Math.max(-1, Math.min(1, ratio))))
  return 180 - ascending
}

/** Point reached from `start` after `distanceDeg` of arc along `bearingDeg`. */
export function destination(
  [lon, lat]: LonLat,
  bearingDeg: number,
  distanceDeg: number,
): LonLat {
  const phi1 = toRad(lat)
  const lambda1 = toRad(lon)
  const theta = toRad(bearingDeg)
  const delta = toRad(distanceDeg)
  const phi2 = Math.asin(
    Math.sin(phi1) * Math.cos(delta) +
      Math.cos(phi1) * Math.sin(delta) * Math.cos(theta),
  )
  const lambda2 =
    lambda1 +
    Math.atan2(
      Math.sin(theta) * Math.sin(delta) * Math.cos(phi1),
      Math.cos(delta) - Math.sin(phi1) * Math.sin(phi2),
    )
  return [toDeg(lambda2), toDeg(phi2)]
}

/**
 * Track points from `spanDeg` of arc before the frame centre (north, where the
 * satellite comes from) to `spanDeg` after it.
 */
export function groundTrack(
  centre: LonLat,
  spanDeg = 60,
  steps = 120,
  inclinationDeg = NISAR_INCLINATION_DEG,
): LonLat[] {
  const heading = descendingHeadingDeg(centre[1], inclinationDeg)
  return Array.from({ length: steps + 1 }, (_, index) => {
    const distance = -spanDeg + (2 * spanDeg * index) / steps
    return destination(centre, heading, distance)
  })
}

/** Position along a polyline at `progress` (0..1), by vertex index. */
export function pointAlong(track: LonLat[], progress: number): LonLat {
  const clamped = Math.min(1, Math.max(0, progress))
  const position = clamped * (track.length - 1)
  const index = Math.min(track.length - 2, Math.floor(position))
  const t = position - index
  const [x0, y0] = track[index]
  const [x1, y1] = track[index + 1]
  return [x0 + (x1 - x0) * t, y0 + (y1 - y0) * t]
}
