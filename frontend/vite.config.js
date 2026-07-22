import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Built assets served by Python at /app/
export default defineConfig({
  plugins: [react()],
  base: '/app/',
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8765',
      '/login': 'http://127.0.0.1:8765',
      '/logout': 'http://127.0.0.1:8765',
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
})
