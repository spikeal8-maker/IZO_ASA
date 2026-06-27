// Static smoke checks for the auth-v2 migration (Phase 12 + Phase 13 cookie sessions).
// Mirrors smoke-ui.mjs style: assert on source content, no browser.
import { readFileSync } from 'node:fs'

const auth = readFileSync(new URL('./src/authV2.tsx', import.meta.url), 'utf8')
const app = readFileSync(new URL('./src/App.tsx', import.meta.url), 'utf8')

// Strip comments so negative ("must not use X") checks reflect real code, not the
// explanatory comments that intentionally name the forbidden patterns.
const stripComments = (s) => s.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/[^\n]*/g, '')
const authCode = stripComments(auth)

const failures = []
const ok = (cond, msg) => { if (!cond) failures.push(msg) }

// Startup + bootstrap (initAuthV2 runs bootstrap then the cookie restore).
ok(app.includes('initAuthV2()'), 'App does not call initAuthV2() at startup')
ok(authCode.includes('/auth/bootstrap-v2'), 'authV2 does not POST /auth/bootstrap-v2')

// Device ids in localStorage (allowed); never auth.
ok(authCode.includes('onenode_installation_id') && authCode.includes('onenode_anonymous_id'), 'device ids not persisted')

// Login endpoints + me-v2 restore.
ok(authCode.includes('/auth/email/request-code-v2'), 'missing request-code-v2 call')
ok(authCode.includes('/auth/email/verify-code-v2'), 'missing verify-code-v2 call')
ok(authCode.includes('/auth/password/login-v2'), 'missing password login-v2 call')
ok(authCode.includes('/auth/password/register-v2'), 'missing password register-v2 call')
ok(authCode.includes('/me-v2'), 'missing /me-v2 restore call')
ok(authCode.includes('/auth/telegram-v2'), 'missing telegram-v2 call')
ok(authCode.includes('init_data: initData'), 'telegram-v2 does not send raw init_data')
ok(!authCode.includes('initDataUnsafe'), 'authV2 must not use initDataUnsafe')
ok(authCode.includes('/auth/max-v2'), 'missing max-v2 call')
ok(authCode.includes('web_app_data: webAppData'), 'max-v2 does not send raw web_app_data')

// Phase 13: cookie-first.
ok(authCode.includes("credentials: 'include'"), 'v2 fetch must use credentials:include')
ok(authCode.includes('/auth/session/refresh-v2'), 'missing cookie refresh call')
ok(authCode.includes('/auth/session/logout-v2'), 'missing logout-v2 call')

// No header/legacy-cookie auth for v2.
ok(!authCode.includes('X-OneNode-User'), 'authV2 must not set X-OneNode-User')
ok(!authCode.includes("getItem('onenode_user')"), 'authV2 must not read onenode_user')

// No token storage anywhere; tokens are NOT kept in JS at all (cookie-only).
ok(!/(local|session)Storage\.setItem\([^)]*(session_token|refresh_token)/i.test(authCode), 'tokens must not be stored')
ok(!authCode.includes('sessionStorage'), 'authV2 must not use sessionStorage')
ok(!authCode.includes('sessionToken'), 'no in-JS session token variable (cookie-only)')
ok(!authCode.includes('applyTokens'), 'login must not capture JSON tokens (cookie-only)')

// Login ignores JSON tokens: success is based on res.ok, not token capture.
ok(authCode.includes('return res.ok'), 'login should rely on res.ok (cookies), not JSON tokens')

// Hotfix guard (13.0): preview aspect vars must be declared if referenced.
for (const v of ['previewAspectWidth', 'previewAspectHeight']) {
  const used = app.includes(`\${${v}}`) || new RegExp(`[^.\\w]${v}\\b`).test(app.replace(`const ${v} =`, ''))
  const declared = app.includes(`const ${v} =`)
  ok(!used || declared, `${v} is referenced but not declared (runtime ReferenceError risk)`)
}

// Old generation/gallery UI still present.
ok(app.includes("apiFetch('/generate'"), 'legacy generate flow missing')
ok(app.includes('GalleryView'), 'gallery UI missing')
// Phase 14.7: Settings account card replaces legacy AuthV2Panel in main UI.
ok(app.includes('account-card'), 'account card (Phase 14.7) missing in settings')
ok(app.includes('updateProfileV2'), 'updateProfileV2 not imported in App')

// Minimal UI states: auth statuses + email/otp view + error surface.
for (const state of ['loading', 'anon', 'authed', 'email', 'otp']) {
  ok(authCode.includes(`'${state}'`), `auth UI state ${state} missing`)
}
ok(authCode.includes('auth-v2-error'), 'auth error UI state missing')

if (failures.length) {
  console.error('smoke-auth-v2 FAILED:')
  for (const f of failures) console.error(' -', f)
  process.exit(1)
}
console.log('smoke-auth-v2 OK — all checks passed')
