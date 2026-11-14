import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import App from './App'

vi.mock('./features/map/CaseMap', () => ({
  CaseMap: () => <div role="region" aria-label="Map of Big Sur" />,
}))

describe('application scaffold', () => {
  it('introduces the case and displays an accessible map', () => {
    render(<App />)
    expect(
      screen.getByRole('heading', { name: /firetrace explorer/i }),
    ).toBeTruthy()
    expect(screen.getByRole('region', { name: /map of big sur/i })).toBeTruthy()
  })
})
