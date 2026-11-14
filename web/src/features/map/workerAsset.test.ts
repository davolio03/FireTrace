// @vitest-environment node
import { build } from 'vite'
import { describe, expect, it } from 'vitest'

describe('MapLibre worker build', () => {
  it('publishes and references the MapLibre worker asset', async () => {
    const result = await build({
      logLevel: 'silent',
      build: { write: false, emptyOutDir: false },
    })
    const outputs = (Array.isArray(result) ? result : [result]).flatMap(
      (bundle) => ('output' in bundle ? bundle.output : []),
    )
    const worker = outputs.find(
      (item) =>
        item.type === 'asset' &&
        /maplibre-gl-worker-.*\.mjs$/.test(item.fileName),
    )
    expect(worker).toBeDefined()
    const chunks = outputs.filter((item) => item.type === 'chunk')
    expect(chunks.some((chunk) => chunk.code.includes(worker!.fileName))).toBe(
      true,
    )
  }, 30_000)

  it('resolves the emitted worker relative to the bundle for a relative base', async () => {
    const result = await build({
      base: './',
      logLevel: 'silent',
      build: { write: false, emptyOutDir: false },
    })
    const outputs = (Array.isArray(result) ? result : [result]).flatMap(
      (bundle) => ('output' in bundle ? bundle.output : []),
    )
    const worker = outputs.find(
      (item) =>
        item.type === 'asset' &&
        /maplibre-gl-worker-.*\.mjs$/.test(item.fileName),
    )
    expect(worker).toBeDefined()
    const filename = worker!.fileName.split('/').pop()
    const chunks = outputs.filter((item) => item.type === 'chunk')
    expect(
      chunks.some(
        (chunk) =>
          chunk.code.includes(filename!) &&
          chunk.code.includes('import.meta.url'),
      ),
    ).toBe(true)
  }, 30_000)
})
