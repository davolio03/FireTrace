import { cleanup, render } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { renderMarkdown } from './markdown'

describe('story markdown', () => {
  afterEach(cleanup)

  it('renders paragraphs, bold and italic as elements', () => {
    const { container } = render(
      <div>{renderMarkdown('One **strong** and *soft*.\n\nTwo.')}</div>,
    )
    const paragraphs = container.querySelectorAll('p')
    expect(paragraphs).toHaveLength(2)
    expect(container.querySelector('strong')?.textContent).toBe('strong')
    expect(container.querySelector('em')?.textContent).toBe('soft')
    expect(paragraphs[1].textContent).toBe('Two.')
  })

  it('never interprets HTML and leaves other syntax literal', () => {
    const { container } = render(
      <div>
        {renderMarkdown('<img src=x onerror=alert(1)> [link](http://x) # h')}
      </div>,
    )
    expect(container.querySelector('img')).toBeNull()
    expect(container.querySelector('a')).toBeNull()
    expect(container.textContent).toBe(
      '<img src=x onerror=alert(1)> [link](http://x) # h',
    )
  })
})
