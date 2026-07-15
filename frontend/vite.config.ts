import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const exactAllowedHosts = ['izo.alikinas.ru'] as const
const appRelease = process.env.FRONTEND_BUILD_LABEL || process.env.GITHUB_SHA || 'dev'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  define: {
    __APP_RELEASE__: JSON.stringify(appRelease),
  },
  server: {
    port: 5173,
    allowedHosts: [...exactAllowedHosts],
    hmr: false,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/media': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/feed': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/gallery': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/static': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  // Phase 16.4B: `vite preview` serves the built dist (no /@vite/client, no raw
  // /src). It uses preview.* (not server.*), so mirror the API/media proxy here.
  preview: {
    port: 5173,
    allowedHosts: [...exactAllowedHosts],
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/media': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/feed': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/gallery': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/static': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
