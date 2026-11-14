import { render } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { CaseMap } from './CaseMap'

const map = vi.hoisted(() => ({
  create: vi.fn(),
  addControl: vi.fn(),
  remove: vi.fn(),
}))

vi.mock('maplibre-gl', () => ({
  Map: class {
    constructor(options: unknown) {
      map.create(options)
    }
    addControl = map.addControl
    remove = map.remove
  },
  NavigationControl: class {},
}))

describe('case map', () => {
  it('centers on Big Sur and releases its map when unmounted', () => {
    const { unmount } = render(<CaseMap />)
    expect(map.create).toHaveBeenCalledWith(
      expect.objectContaining({
        center: [-121.47, 35.92],
        zoom: 9,
        style: expect.objectContaining({
          sources: expect.objectContaining({
            osm: expect.objectContaining({
              tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
              attribution: expect.stringContaining('OpenStreetMap'),
            }),
          }),
        }),
      }),
    )
    unmount()
    expect(map.remove).toHaveBeenCalledOnce()
  })
})
