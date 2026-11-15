import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { AnimatedValue } from './AnimatedValue'

describe('measured readouts', () => {
  it('shows the exact value the contract returned', () => {
    render(<AnimatedValue value={95.4} />)
    expect(screen.getByText('95.4')).toBeTruthy()
  })
  it('reports unavailable values without inventing a number', () => {
    render(<AnimatedValue value={null} />)
    expect(screen.getByText('Not available')).toBeTruthy()
  })
})
