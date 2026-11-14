import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import 'maplibre-gl/dist/maplibre-gl.css'
import './index.css'
import App from './App'

const root = createRoot(document.getElementById('root')!)

async function start() {
  if (import.meta.env.VITE_USE_MOCKS !== 'false') {
    const { worker } = await import('./mocks/browser')
    await worker.start()
  }
  root.render(
    <StrictMode>
      <App />
    </StrictMode>,
  )
}

start().catch(() =>
  root.render(<p role="alert">Unable to start the application.</p>),
)
