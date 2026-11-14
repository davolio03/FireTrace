import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import App from './App'

vi.mock('./data/caseData', () => ({
  loadCaseData: vi.fn(async () => ({
    case: { data_status: 'mock' },
    stats: { data_status: 'mock' },
    layers: { data_status: 'mock' },
  })),
}))

vi.mock('./features/map/CaseMap', () => ({
  CaseMap: () => <div role="region" aria-label="Map of Big Sur" />,
}))

describe('application scaffold', () => {
  it('introduces the case, displays an accessible map and labels mock data', async () => {
    render(<App />)
    expect(
      screen.getByRole('heading', { name: /firetrace explorer/i }),
    ).toBeTruthy()
    expect(screen.getByRole('region', { name: /map of big sur/i })).toBeTruthy()
    expect(await screen.findByText(/MOCK.*synthetic/i)).toBeTruthy()
  })
})
