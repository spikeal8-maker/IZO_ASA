// Safe live-delivery diagnostics metadata. Keep non-component exports out of
// diag.tsx so React Fast Refresh can treat that file as component-only.
import { FRONTEND_RELEASE_ID } from './releaseIdentity'

export const APP_BUILD_LABEL = FRONTEND_RELEASE_ID

export function isDiagMode(): boolean {
  try {
    const params = new URLSearchParams(window.location.search)
    return params.get('diag') === '1' || window.location.hash.includes('diag')
  } catch {
    return false
  }
}
