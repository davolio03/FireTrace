import { describe, expect, it } from 'vitest'
import frame from '../../story/nisar-frame.json'
import type { LonLat } from '../../state/mapStore'
import {
  descendingHeadingDeg,
  destination,
  groundTrack,
  pointAlong,
  ringCentre,
} from './orbit'

const ring = frame.geometry.coordinates[0] as LonLat[]

describe('illustrative NISAR ground track', () => {
  it('centres on the real frame footprint', () => {
    const [lon, lat] = ringCentre(ring)
    expect(lon).toBeCloseTo(-121.108, 2)
    expect(lat).toBeCloseTo(36.69, 2)
  })

  it('heads south, slightly west, on a descending sun-synchronous pass', () => {
    const heading = descendingHeadingDeg(36.7)
    expect(heading).toBeGreaterThan(180)
    expect(heading).toBeLessThan(195)
    expect(descendingHeadingDeg(0)).toBeCloseTo(180 + 8.4, 6)
  })

  it('moves along great circles', () => {
    const [lon, lat] = destination([0, 0], 0, 10)
    expect(lon).toBeCloseTo(0, 9)
    expect(lat).toBeCloseTo(10, 9)
    const east = destination([0, 0], 90, 90)
    expect(east[0]).toBeCloseTo(90, 9)
  })

  it('passes through the frame centre, coming from the north', () => {
    const centre = ringCentre(ring)
    const track = groundTrack(centre, 60, 120)
    expect(track).toHaveLength(121)
    expect(track[60][0]).toBeCloseTo(centre[0], 9)
    expect(track[60][1]).toBeCloseTo(centre[1], 9)
    expect(track[0][1]).toBeGreaterThan(track[120][1])
    expect(Math.max(...track.map(([, lat]) => lat))).toBeLessThanOrEqual(81.7)
  })

  it('interpolates positions along the track', () => {
    const track: LonLat[] = [
      [0, 0],
      [10, 0],
      [10, 10],
    ]
    expect(pointAlong(track, 0)).toEqual([0, 0])
    expect(pointAlong(track, 0.25)).toEqual([5, 0])
    expect(pointAlong(track, 1)).toEqual([10, 10])
    expect(pointAlong(track, 2)).toEqual([10, 10])
  })
})
