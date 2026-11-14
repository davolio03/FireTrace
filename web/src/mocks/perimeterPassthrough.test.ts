// @vitest-environment node
import { createServer, type Server } from 'node:http'
import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest'
import { setupServer } from 'msw/node'
import { handlers } from './handlers'

const mockServer = setupServer(...handlers)
let staticServer: Server
let origin: string

beforeAll(async () => {
  staticServer = createServer((_request, response) => {
    response.setHeader('Content-Type', 'application/geo+json')
    response.end('{"type":"FeatureCollection","features":[]}')
  })
  await new Promise<void>((resolve) =>
    staticServer.listen(0, '127.0.0.1', resolve),
  )
  const address = staticServer.address()
  if (!address || typeof address === 'string') throw new Error('No local port')
  origin = `http://127.0.0.1:${address.port}`
  mockServer.listen()
})

afterAll(async () => {
  mockServer.close()
  await new Promise<void>((resolve, reject) =>
    staticServer.close((error) => (error ? reject(error) : resolve())),
  )
})

describe('mock perimeter requests', () => {
  it('passes the static GeoJSON through without unhandled-request warnings', async () => {
    const warn = vi.spyOn(console, 'warn')
    try {
      const response = await fetch(`${origin}/perimeter.geojson`)
      expect(response.status).toBe(200)
      expect(await response.json()).toEqual({
        type: 'FeatureCollection',
        features: [],
      })
      expect(warn).not.toHaveBeenCalled()
    } finally {
      warn.mockRestore()
    }
  })

  it('keeps known and unknown API routes mocked instead of passing them through', async () => {
    for (const [path, method, status] of [
      ['/api/health', 'GET', 200],
      ['/api/perimeter.geojson', 'GET', 501],
      ['/api/x/perimeter.geojson', 'GET', 501],
      ['/api/perimeter.geojson', 'POST', 501],
      ['/api/not-found', 'GET', 501],
    ] as const) {
      const response = await fetch(`${origin}${path}`, { method })
      expect(response.status, `${method} ${path}`).toBe(status)
    }
  })
})
