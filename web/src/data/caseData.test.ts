import { afterEach, describe, expect, it, vi } from 'vitest'
import { loadCaseData } from './caseData'

afterEach(() => vi.unstubAllGlobals())

describe('case data', () => {
  it('loads case, stats and layers from the configured data base', async () => {
    const fetch = vi.fn(async (url: string) => ({
      ok: true,
      json: async () => ({ data_status: 'mock', url }),
    }))
    vi.stubGlobal('fetch', fetch)
    const data = await loadCaseData('/fixtures/web')
    expect(fetch.mock.calls.map(([url]) => url)).toEqual([
      '/fixtures/web/case.json',
      '/fixtures/web/stats.json',
      '/fixtures/web/layers.json',
    ])
    expect(data.case.data_status).toBe('mock')
    expect(data.stats.data_status).toBe('mock')
    expect(data.layers.data_status).toBe('mock')
  })

  it('surfaces an unsuccessful response', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({ ok: false, status: 404 })),
    )
    await expect(loadCaseData('/fixtures/web')).rejects.toThrow('404')
  })

  it('rejects missing or unsupported data status instead of treating it as real', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({ ok: true, json: async () => ({}) })),
    )
    await expect(loadCaseData('/fixtures/web')).rejects.toThrow('data_status')
  })
})
