/// <reference types="vitest/config" />
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      // All backend HTTP calls go through /api -> FastAPI :8000 (prefix stripped),
      // so the frontend never hardcodes the backend host or route names.
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
      // WS for F6 live (P2 backend not built yet — proxy wired ahead of time).
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,
      },
      // Pre-generated question TTS audio (SCHEMA §6.5): tts_url is
      // /static/tts/{id}.wav served by FastAPI — path passed through as-is.
      '/static': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: 'node',
    include: ['src/**/*.test.{js,jsx}'],
  },
})
