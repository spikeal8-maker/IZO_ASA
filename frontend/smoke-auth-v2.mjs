import { readFileSync } from 'node:fs'

const auth = readFileSync(new URL('./src/authV2.tsx', import.meta.url), 'utf8')
const studio = readFileSync(new URL('./src/newUi.tsx', import.meta.url), 'utf8')
const css = readFileSync(new URL('./src/index.css', import.meta.url), 'utf8')
const authCode = auth.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/[^\n]*/g, '')
const failures = []
const ok = (condition, message) => { if (!condition) failures.push(message) }

ok(studio.includes('useAuthV2()'), 'active studio must subscribe to auth-v2')
ok(studio.includes('initAuthV2()'), 'active studio must restore the cookie session')
ok(studio.includes('<AuthV2Modal'), 'active studio must mount AuthV2Modal')
ok(studio.includes('setAuthOpen(true)'), 'unauthenticated generation must open AuthV2Modal')
ok(studio.includes("authStatus === 'authed'"), 'authenticated UI must use auth-v2 status')

for (const endpoint of [
  '/auth/bootstrap-v2',
  '/auth/password/login-v2',
  '/auth/password/register-v2',
  '/auth/session/refresh-v2',
  '/auth/session/logout-v2',
  '/me-v2',
  '/auth/telegram-v2',
  '/auth/max-v2',
]) ok(authCode.includes(endpoint), `missing auth endpoint ${endpoint}`)

ok(authCode.includes("credentials: 'include'"), 'auth-v2 must use cookie credentials')
ok(!authCode.includes('X-OneNode-User'), 'auth-v2 must not use the legacy identity header')
ok(!/(local|session)Storage\.setItem\([^)]*(session_token|refresh_token)/i.test(authCode), 'auth tokens must not be stored in JS storage')
ok(!authCode.includes('sessionStorage'), 'auth-v2 must not use sessionStorage')
ok(auth.includes('createPortal(') && auth.includes('document.body'), 'auth modal must render through a body portal')
ok(auth.includes('role="dialog"') && auth.includes('aria-modal="true"'), 'auth modal must expose dialog semantics')
ok(auth.includes("e.key === 'Escape'"), 'auth modal must close on Escape')
ok(/\.auth-modal-overlay\s*\{[^}]*position:\s*fixed/.test(css), 'auth modal overlay must remain fixed')

if (failures.length) {
  console.error('smoke-auth-v2 FAILED:')
  failures.forEach((failure) => console.error(` - ${failure}`))
  process.exit(1)
}

console.log('smoke-auth-v2 OK')
