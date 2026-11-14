import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest'
import { setupServer } from 'msw/node'
import grid from '../../../contracts/fixtures/api/inspect-grid.json'
import { handlers } from './handlers'

const server = setupServer(...handlers)
beforeAll(() => server.listen())
afterEach(() => server.resetHandlers())
afterAll(() => server.close())

describe('mock API', () => {
  it('serves fixture data without a backend', async () => {
    for (const path of [
      '/api/case',
      '/api/stats',
      '/api/layers',
      '/api/health',
    ]) {
      const response = await fetch(`http://localhost${path}`)
      expect(response.status).toBe(200)
      expect((await response.json()).data_status).toBe('mock')
    }
  })

  it('returns mock grid evidence for a point and no data outside the AOI', async () => {
    const inside = await fetch(
      'http://localhost/api/inspect/point?lon=-121.4&lat=35.9',
    )
    const point = await inside.json()
    expect(inside.status).toBe(200)
    expect(point.data_status).toBe('mock')
    expect(point.query).toEqual({ lon: -121.4, lat: 35.9 })
    expect(point.pixel).not.toBeNull()
    expect(point.terrain).toHaveProperty('aspect_deg', null)
    const outside = await fetch(
      'http://localhost/api/inspect/point?lon=-120&lat=35.9',
    )
    expect(await outside.json()).toMatchObject({
      valid: false,
      pixel: null,
      hh_db: { t1: null, t2: null, delta: null },
      hv_db: { t1: null, t2: null, delta: null },
    })
  })

  it('samples a requested mock profile and rejects invalid lines', async () => {
    const line = [
      [-121.4, 35.9],
      [-121.401, 35.901],
    ]
    const response = await fetch('http://localhost/api/inspect/profile', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ line, spacing_m: 50 }),
    })
    const profile = await response.json()
    expect(response.status).toBe(200)
    expect(profile).toMatchObject({ data_status: 'mock', line, spacing_m: 50 })
    expect(profile.samples.length).toBeGreaterThan(1)
    expect(profile.samples[0]).toMatchObject({
      lon: line[0][0],
      lat: line[0][1],
      distance_m: 0,
    })
    const invalid = await fetch('http://localhost/api/inspect/profile', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ line: [[1, 2]], spacing_m: -1 }),
    })
    expect(invalid.status).toBe(422)
  })

  it('rejects missing and invalid coordinates', async () => {
    for (const query of [
      '',
      '?lon=&lat=35',
      '?lon=181&lat=35',
      '?lon=1&lat=NaN',
    ]) {
      expect(
        (await fetch(`http://localhost/api/inspect/point${query}`)).status,
      ).toBe(422)
    }
  })

  it('returns values from the sampled grid and preserves no-data cells', async () => {
    const [west, south, east, north] = grid.aoi_bbox
    const merc = (lat: number) =>
      Math.log(Math.tan(Math.PI / 4 + (lat * Math.PI) / 360))
    const latAt = (row: number) => {
      const y =
        merc(north) -
        ((row + 0.5) / grid.image_height) * (merc(north) - merc(south))
      return (360 / Math.PI) * Math.atan(Math.exp(y)) - 90
    }
    const pointAt = async (r: number, c: number) => {
      const lon =
        west + ((c * grid.step_px + 0.5) / grid.image_width) * (east - west)
      const lat = latAt(r * grid.step_px)
      return (
        await fetch(`http://localhost/api/inspect/point?lon=${lon}&lat=${lat}`)
      ).json()
    }
    const sample = await pointAt(0, 0)
    expect(sample.hh_db.t1).toBe(grid.fields.sar_t1_hh[0][0])
    expect(sample.pixel).toMatchObject({
      row: 0,
      col: 0,
      x: 600000,
      y: 3975000,
    })
    const invalidRow = grid.fields.sar_t1_hh.findIndex((row) =>
      row.includes(null),
    )
    const invalidCol = grid.fields.sar_t1_hh[invalidRow].indexOf(null)
    const invalid = await pointAt(invalidRow, invalidCol)
    expect(invalid.valid).toBe(false)
    expect(invalid.pixel).not.toBeNull()
    expect(invalid.hh_db).toEqual({ t1: null, t2: null, delta: null })
    expect(invalid.hv_db).toEqual({ t1: null, t2: null, delta: null })
    expect(invalid.change_index).toBeNull()
  })
})
