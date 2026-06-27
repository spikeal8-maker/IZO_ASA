// Static smoke checks for the Phase 14 frontend generation lock (auth-v2 gated).
// Mirrors smoke-ui.mjs style: assert on source content, no browser.
import { readFileSync } from 'node:fs'

const app = readFileSync(new URL('./src/App.tsx', import.meta.url), 'utf8')
const auth = readFileSync(new URL('./src/authV2.tsx', import.meta.url), 'utf8')

const failures = []
const ok = (cond, msg) => { if (!cond) failures.push(msg) }

// 1. Lock text shown for unauthenticated state.
ok(app.includes('Войдите, чтобы генерировать'), 'missing generation lock text')

// 2. Unauthenticated click does NOT call generate; it opens the auth modal.
ok(app.includes("generate-locked"), 'missing locked generate button variant')
ok(/generate-locked[^>]*onClick=\{\(\)\s*=>\s*setAuthModalOpen\(true\)\}/.test(app),
  'locked generate button must open the auth modal (setAuthModalOpen(true))')
ok(!/generate-locked[^>]*onClick=\{generate\}/.test(app), 'locked button must not call generate')

// 3 & 4. Auth-gated rendering: authed -> real button, else -> locked.
ok(app.includes('isAuthedV2'), 'missing isAuthedV2 gate')
ok(/isAuthedV2\s*\n?\s*\?\s*<button className="generate"/.test(app) || app.includes('isAuthedV2\n'),
  'generate button must be gated on isAuthedV2')
ok(app.includes("authV2Status === 'authed'"), 'isAuthedV2 must derive from auth-v2 status')

// 5. Auth state is from /api/me-v2, not localStorage('onenode_user').
ok(auth.includes('/me-v2'), 'auth state must come from /api/me-v2')
ok(app.includes('useAuthV2('), 'App must consume the shared auth-v2 hook')
ok(!/isAuthedV2\s*=.*onenode_user/.test(app), 'auth gate must not use onenode_user')

// 6. installation_id/anonymous_id do not unlock generation (status only from me-v2).
ok(!/isAuthedV2[^\n]*(installation_id|anonymous_id)/.test(app), 'device ids must not unlock generation')
ok(auth.includes("setAuthState(me ? 'authed' : 'anon'"), 'authed status must require a me-v2 result')

// 7. No token storage anywhere in auth code.
const authCode = auth.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/[^\n]*/g, '')
ok(!/(local|session)Storage\.setItem\([^)]*(session_token|refresh_token)/i.test(authCode), 'tokens must not be stored')
ok(!authCode.includes('sessionStorage'), 'no sessionStorage for tokens')

// 8. v2 requests do not use X-OneNode-User.
ok(!authCode.includes('X-OneNode-User'), 'authV2 must not use X-OneNode-User')
ok(authCode.includes("credentials: 'include'"), 'v2 fetch must use cookie credentials')

// Regression (16.4D): gallery state must be array-guarded. /api/gallery returns 401
// ({detail} object) when unauthenticated — an unguarded setGallery makes gallery a
// non-array and gallery.slice(...) crashes the app (Ce.slice is not a function).
{
  const setters = [...app.matchAll(/setGallery\(([^)]*)\)/g)].map((m) => m[1])
  ok(setters.length > 0, 'no setGallery call found')
  ok(setters.every((arg) => /Array\.isArray/.test(arg)), 'every setGallery must Array.isArray-guard its value')
  ok(!/'\/gallery'\)\.then\(\(r\)\s*=>\s*r\.json\(\)\)\.then\(setGallery\)/.test(app), 'raw setGallery from /gallery json is unguarded')
}

// 9 & 10. Legacy generation + gallery/templates UI still present.
ok(app.includes("apiFetch('/generate'"), 'legacy generate flow removed')
ok(app.includes('GalleryView'), 'gallery UI removed')
ok(app.includes('PresetsView') || app.includes('workflowPresets'), 'templates/presets UI removed')

if (failures.length) {
  console.error('smoke-generation-lock FAILED:')
  for (const f of failures) console.error(' -', f)
  process.exit(1)
}
console.log('smoke-generation-lock OK — all checks passed')
