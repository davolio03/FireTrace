import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import manifest from '../../../../contracts/fixtures/web/layers.json'
import type { components } from '../../generated/api'
import { mapStore } from '../../state/mapStore'
import { ComparisonControls } from './ComparisonControls'

const layers = manifest.layers as components['schemas']['layer'][]
const dates = { before: '2026-08-16', after: '2026-10-03' }

describe('before and after controls', () => {
  beforeEach(() =>
    mapStore.setState({
      compare: null,
      visible: ['perimeter', 'change_index'],
    }),
  )
  afterEach(cleanup)

  it('selects HH and HV pairs without changing the existing layer selection', () => {
    render(<ComparisonControls layers={layers} dates={dates} />)
    fireEvent.click(
      screen.getByRole('button', { name: /compare before and after/i }),
    )
    expect(mapStore.getState().compare).toEqual({
      left: 'sar_t1_hh',
      right: 'sar_t2_hh',
      position: 0.5,
    })
    expect(screen.getByText(/before.*2026-08-16.*HH/i)).toBeTruthy()
    expect(screen.getByText(/after.*2026-10-03.*HH/i)).toBeTruthy()
    fireEvent.click(screen.getByRole('radio', { name: 'HV' }))
    expect(mapStore.getState().compare).toEqual({
      left: 'sar_t1_hv',
      right: 'sar_t2_hv',
      position: 0.5,
    })
    expect(mapStore.getState().visible).toEqual(['perimeter', 'change_index'])
    fireEvent.click(screen.getByRole('button', { name: /exit comparison/i }))
    expect(mapStore.getState().compare).toBeNull()
    expect(mapStore.getState().visible).toEqual(['perimeter', 'change_index'])
  })

  it('updates shared divider position including both endpoints', () => {
    render(<ComparisonControls layers={layers} dates={dates} />)
    fireEvent.click(
      screen.getByRole('button', { name: /compare before and after/i }),
    )
    const slider = screen.getByRole('slider', { name: /comparison divider/i })
    fireEvent.change(slider, { target: { value: '0' } })
    expect(mapStore.getState().compare?.position).toBe(0)
    fireEvent.change(slider, { target: { value: '100' } })
    expect(mapStore.getState().compare?.position).toBe(1)
  })

  it('reports a missing comparison image and keeps comparison closed', () => {
    render(
      <ComparisonControls
        layers={layers.filter(
          (layer) =>
            layer.id !== 'sar_t2_hh' &&
            layer.id !== 'sar_t2_hv' &&
            layer.group !== 'optical_context',
        )}
        dates={dates}
      />,
    )
    fireEvent.click(
      screen.getByRole('button', { name: /compare before and after/i }),
    )
    expect(screen.getByRole('alert').textContent).toMatch(
      /comparison images.*unavailable/i,
    )
    expect(mapStore.getState().compare).toBeNull()
  })

  it('starts with HV when HH is unavailable but HV is complete', () => {
    render(
      <ComparisonControls
        layers={layers.filter((layer) => layer.id !== 'sar_t2_hh')}
        dates={dates}
      />,
    )
    fireEvent.click(
      screen.getByRole('button', { name: /compare before and after/i }),
    )
    expect(screen.getByRole('radio', { name: 'HV' })).toBeTruthy()
    expect(mapStore.getState().compare).toEqual({
      left: 'sar_t1_hv',
      right: 'sar_t2_hv',
      position: 0.5,
    })
  })
})
