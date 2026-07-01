// Safe live-delivery diagnostics metadata. Keep non-component exports out of
// diag.tsx so React Fast Refresh can treat that file as component-only.

// Bump this string on every frontend deploy so you can confirm which bundle is live.
export const APP_BUILD_LABEL = 'MAIN-UI-STABILITY-20260701'

export function isDiagMode(): boolean {
  try {
    const params = new URLSearchParams(window.location.search)
    return params.get('diag') === '1' || window.location.hash.includes('diag')
  } catch {
    return false
  }
}
