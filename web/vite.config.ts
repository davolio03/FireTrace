import { fileURLToPath, URL } from 'node:url'
import { readFileSync } from 'node:fs'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vitest/config'

// Local real-data mode: the browser and the API share the dev/preview origin,
// so neither the API nor the bundle server needs CORS. See web/README.md.
const apiProxyTarget =
  process.env.FIRETRACE_API_PROXY ?? 'http://127.0.0.1:8000'
const dataProxyTarget =
  process.env.FIRETRACE_DATA_PROXY ?? 'http://127.0.0.1:8001'

const proxy = {
  '/api': { target: apiProxyTarget, changeOrigin: true },
  '/data': {
    target: dataProxyTarget,
    changeOrigin: true,
    // The static server hosts data/processed/web at its root.
    rewrite: (path: string) => path.replace(/^\/data/, ''),
  },
}

export default defineConfig({
  publicDir: '../contracts/fixtures/web',
  server: { proxy },
  preview: { proxy },
  plugins: [
    react(),
    tailwindcss(),
    {
      name: 'mock-service-worker',
      configureServer(server) {
        server.middlewares.use('/mockServiceWorker.js', (_req, res) => {
          res.setHeader('Content-Type', 'application/javascript')
          res.end(
            readFileSync(
              new URL(
                './node_modules/msw/lib/mockServiceWorker.js',
                import.meta.url,
              ),
            ),
          )
        })
      },
      generateBundle() {
        this.emitFile({
          type: 'asset',
          fileName: 'mockServiceWorker.js',
          source: readFileSync(
            new URL(
              './node_modules/msw/lib/mockServiceWorker.js',
              import.meta.url,
            ),
          ),
        })
      },
    },
  ],
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  test: { environment: 'jsdom' },
})
