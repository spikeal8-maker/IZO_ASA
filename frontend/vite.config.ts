import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const exactAllowedHosts = ['izo.alikinas.ru'] as const
const configuredRelease = process.env.FRONTEND_BUILD_LABEL || process.env.GITHUB_SHA || ''
const isProductionBuild = process.argv.includes('build')
if (isProductionBuild && (!configuredRelease || /^(dev|unknown)$/i.test(configuredRelease))) {
  throw new Error('FRONTEND_BUILD_LABEL must identify the immutable release for production builds')
}
const appRelease = configuredRelease || 'dev'
const devPort = Number(process.env.VITE_DEV_PORT || 5173)
const apiProxyTarget = process.env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8000'
const releaseMetaPlugin = {
  name: 'izo-release-meta',
  transformIndexHtml() {
    return [
      {
        tag: 'meta',
        attrs: { name: 'izo-release', content: appRelease },
        injectTo: 'head' as const,
      },
    ]
  },
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), releaseMetaPlugin],
  define: {
    __APP_RELEASE__: JSON.stringify(appRelease),
  },
  server: {
    port: devPort,
    allowedHosts: [...exactAllowedHosts],
    hmr: false,
    proxy: {
      '/api': {
        target: apiProxyTarget,
        changeOrigin: true,
      },
      '/media': {
        target: apiProxyTarget,
        changeOrigin: true,
      },
      '/feed': {
        target: apiProxyTarget,
        changeOrigin: true,
      },
      '/gallery': {
        target: apiProxyTarget,
        changeOrigin: true,
      },
      '/static': {
        target: apiProxyTarget,
        changeOrigin: true,
      },
    },
  },
  // Phase 16.4B: `vite preview` serves the built dist (no /@vite/client, no raw
  // /src). It uses preview.* (not server.*), so mirror the API/media proxy here.
  preview: {
    port: devPort,
    allowedHosts: [...exactAllowedHosts],
    proxy: {
      '/api': {
        target: apiProxyTarget,
        changeOrigin: true,
      },
      '/media': {
        target: apiProxyTarget,
        changeOrigin: true,
      },
      '/feed': {
        target: apiProxyTarget,
        changeOrigin: true,
      },
      '/gallery': {
        target: apiProxyTarget,
        changeOrigin: true,
      },
      '/static': {
        target: apiProxyTarget,
        changeOrigin: true,
      },
    },
  },
})
