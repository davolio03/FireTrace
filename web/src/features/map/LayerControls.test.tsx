import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import manifest from '../../../../contracts/fixtures/web/layers.json'
import type { components } from '../../generated/api'
import { mapStore } from '../../state/mapStore'
import { LayerControls } from './LayerControls'

type Layer = components['schemas']['layer']
const layers = manifest.layers as Layer[]

describe('layer controls', () => {
  afterEach(cleanup)
  beforeEach(() => {
    mapStore.getState().setVisible([])
    mapStore.setState({ opacity: {} })
  })

  it('toggles layers independently and changes opacity through the shared store', () => {
    render(<LayerControls layers={layers} />)
    fireEvent.click(
      screen.getByRole('checkbox', { name: 'SAR backscatter HH — before' }),
    )
    fireEvent.click(
      screen.getByRole('checkbox', { name: 'Official fire perimeter' }),
    )
    expect(mapStore.getState().visible).toEqual(['sar_t1_hh', 'perimeter'])
    fireEvent.change(
      screen.getByRole('slider', {
        name: 'Opacity for Official fire perimeter',
      }),
      {
        target: { value: '0.4' },
      },
    )
    expect(mapStore.getState().opacity.perimeter).toBe(0.4)
    fireEvent.click(
      screen.getByRole('checkbox', { name: 'SAR backscatter HH — before' }),
    )
    expect(mapStore.getState().visible).toEqual(['perimeter'])
  })

  it('shows contract legends and units while hiding P1 layers', () => {
    render(<LayerControls layers={layers} />)
    expect(screen.getAllByText('dB').length).toBeGreaterThan(0)
    expect(
      screen.getByText('Official fire perimeter', { selector: 'span' }),
    ).toBeTruthy()
    expect(screen.queryByRole('checkbox', { name: /highlighted/i })).toBeNull()
    expect(screen.getAllByRole('checkbox', { name: /optical/i })).toHaveLength(
      2,
    )
  })

  it('explains stacking order and disables opacity for hidden layers', () => {
    render(<LayerControls layers={layers} />)
    expect(screen.getByText(/first.*bottom.*last.*top/i)).toBeTruthy()
    const slider = screen.getByRole('slider', {
      name: 'Opacity for SAR backscatter HH — before',
    }) as HTMLInputElement
    expect(slider.disabled).toBe(true)
    fireEvent.click(
      screen.getByRole('checkbox', { name: 'SAR backscatter HH — before' }),
    )
    expect(slider.disabled).toBe(false)
  })

  it('labels legends as read-only and explains transparent raster pixels', () => {
    render(<LayerControls layers={layers} />)
    expect(screen.getAllByText('Legend').length).toBeGreaterThan(0)
    expect(screen.getAllByText(/transparent.*no data/i).length).toBeGreaterThan(
      0,
    )
  })
})
