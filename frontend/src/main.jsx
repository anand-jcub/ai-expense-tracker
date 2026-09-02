import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { captureHubKey } from './api/mode'
import './index.css'
import App from './App.jsx'

captureHubKey()

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
)

if (import.meta.env.PROD && 'serviceWorker' in navigator) {
  navigator.serviceWorker.register('/app/sw.js').then((reg) => {
    reg.update().catch(() => {})
  }).catch(() => {})
}
