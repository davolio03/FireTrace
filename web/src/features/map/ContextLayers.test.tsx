import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import manifest from '../../../../contracts/fixtures/web/layers.json'
import type { components } from '../../generated/api'
import { mapStore } from '../../state/mapStore'
import { ComparisonControls } from './ComparisonControls'
import { LayerControls } from './LayerControls'

const layers = manifest.layers as components['schemas']['layer'][]
const dates = { before: '2026-08-16', after: '2026-10-03' }

describe('context layers and comparison', () => {
  beforeEach(() =>
    mapStore.setState({ compare: null, visible: ['perimeter'], opacity: {} }),
  )
  afterEach(cleanup)

  it('groups context layers and exposes source, acquisition date and controls', () => {
    render(<LayerControls layers={layers} />)
    const optical = screen.getByRole('group', { name: 'Optical context' })
    expect(within(optical).getAllByText(/MOCK optical/)).toHaveLength(2)
    expect(within(optical).getByText(/2026-09-05/)).toBeTruthy()
    expect(screen.getByRole('group', { name: 'Terrain' })).toBeTruthy()
    fireEvent.click(
      within(optical).getByRole('checkbox', { name: /Optical image during/i }),
    )
    expect(mapStore.getState().visible).toContain('optical_during')
  })

  it('compares chosen optical and radar layers while preserving other selections', () => {
    render(<ComparisonControls layers={layers} dates={dates} />)
    fireEvent.click(
      screen.getByRole('button', { name: /compare before and after/i }),
    )
    fireEvent.click(screen.getByRole('radio', { name: /optical and radar/i }))
    fireEvent.change(screen.getByLabelText('Optical image'), {
      target: { value: 'optical_after' },
    })
    fireEvent.change(screen.getByLabelText('Radar observation'), {
      target: { value: 'sar_t2_hv' },
    })
    expect(mapStore.getState().compare).toEqual({
      left: 'optical_after',
      right: 'sar_t2_hv',
      position: 0.5,
    })
    expect(screen.getByText(/2026-10-05/)).toBeTruthy()
    expect(screen.getByText(/2026-10-03.*HV/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: /exit comparison/i }))
    expect(mapStore.getState().visible).toEqual(['perimeter'])
  })

  it('starts optical comparison if no complete radar pair is available', () => {
    render(
      <ComparisonControls
        layers={layers.filter((layer) =>
          ['optical_during', 'sar_t1_hv'].includes(layer.id),
        )}
        dates={dates}
      />,
    )
    fireEvent.click(
      screen.getByRole('button', { name: /compare before and after/i }),
    )
    expect(mapStore.getState().compare).toEqual({
      left: 'optical_during',
      right: 'sar_t1_hv',
      position: 0.5,
    })
  })

  it('reports unavailable optical imagery without changing the selected radar pair', () => {
    render(
      <ComparisonControls
        layers={layers.filter((layer) => layer.group !== 'optical_context')}
        dates={dates}
      />,
    )
    fireEvent.click(
      screen.getByRole('button', { name: /compare before and after/i }),
    )
    const prior = mapStore.getState().compare
    fireEvent.click(screen.getByRole('radio', { name: /optical and radar/i }))
    expect(screen.getByRole('alert').textContent).toMatch(/unavailable/i)
    expect(mapStore.getState().compare).toEqual(prior)
  })

  it('does not change optical selection when no full radar pair exists', () => {
    const available = layers.filter((layer) =>
      ['optical_during', 'optical_after', 'sar_t1_hv'].includes(layer.id),
    )
    mapStore.setState({
      compare: { left: 'optical_after', right: 'sar_t1_hv', position: 0.5 },
    })
    render(<ComparisonControls layers={available} dates={dates} />)
    fireEvent.click(
      screen.getByRole('radio', { name: /before and after radar/i }),
    )
    expect(screen.getByRole('alert')).toBeTruthy()
    expect(mapStore.getState().compare?.left).toBe('optical_after')
  })

  it('handles malformed optional context metadata without crashing', () => {
    const altered = layers.map((layer) =>
      layer.id === 'optical_during'
        ? {
            ...layer,
            source: { label: { invalid: true } },
            acquired: { invalid: true },
          }
        : layer,
    ) as unknown as typeof layers
    render(<LayerControls layers={altered} />)
    expect(screen.getByText(/Source: Not available/i)).toBeTruthy()
  })
})
