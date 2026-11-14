import { fileURLToPath, URL } from 'node:url'
import { readFileSync } from 'node:fs'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  publicDir: '../contracts/fixtures/web',
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
