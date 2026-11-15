import type { ReactNode } from 'react'

const INLINE = /(\*\*[^*\n]+\*\*|\*[^*\n]+\*)/g

function inline(text: string, keyPrefix: string): ReactNode[] {
  return text
    .split(INLINE)
    .filter((part) => part !== '')
    .map((part, index) => {
      const key = `${keyPrefix}-${index}`
      if (part.startsWith('**') && part.endsWith('**') && part.length > 4)
        return <strong key={key}>{part.slice(2, -2)}</strong>
      if (part.startsWith('*') && part.endsWith('*') && part.length > 2)
        return <em key={key}>{part.slice(1, -1)}</em>
      return part
    })
}

/**
 * Minimal Markdown for hand-written story text: paragraphs, **bold** and
 * *italic*. It builds React elements (never HTML strings), so any other
 * syntax stays literal text.
 */
export function renderMarkdown(markdown: string): ReactNode {
  return markdown
    .split(/\n{2,}/)
    .map((paragraph) => paragraph.trim())
    .filter(Boolean)
    .map((paragraph, index) => (
      <p key={index}>{inline(paragraph, String(index))}</p>
    ))
}
