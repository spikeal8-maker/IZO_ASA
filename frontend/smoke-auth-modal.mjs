// Static smoke checks for the Phase 14.5A/14.6 auth modal UX (password login/register).
import { readFileSync } from 'node:fs'

const app = readFileSync(new URL('./src/App.tsx', import.meta.url), 'utf8')
const auth = readFileSync(new URL('./src/authV2.tsx', import.meta.url), 'utf8')
const css = readFileSync(new URL('./src/index.css', import.meta.url), 'utf8')

// Comment-stripped auth source for negative ("must not use X") checks.
const authCode = auth.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/[^\n]*/g, '')

// Isolate the AuthV2Modal function body for modal-specific checks.
const modalMatch = auth.match(/export function AuthV2Modal[\s\S]*?\n\}/)
const modalBody = modalMatch ? modalMatch[0] : ''

const failures = []
const ok = (cond, msg) => { if (!cond) failures.push(msg) }

// Portal + true overlay (Phase 14.2 fix).
ok(auth.includes("from 'react-dom'") && auth.includes('createPortal('), 'modal must render via React portal')
ok(auth.includes('document.body') , 'modal portal target must be document.body')
ok(/\.auth-modal-overlay\s*\{[^}]*position:\s*fixed/.test(css), 'overlay must be position:fixed')
ok(/\.auth-modal-overlay\s*\{[^}]*inset:\s*0/.test(css), 'overlay must use inset:0')
ok(/\.auth-modal-overlay\s*\{[^}]*z-index:\s*\d{3,}/.test(css), 'overlay must have a high z-index')
ok(/\.auth-modal-overlay\s*\{[^}]*background:\s*rgba/.test(css), 'overlay must have a backdrop')
// card not full-page width
ok(/\.auth-modal\s*\{[^}]*width:\s*min\(/.test(css), 'modal card must have a constrained width (min())')

// Locked button opens the modal (not Settings), single CTA with lock.
ok(/onClick=\{\(\)\s*=>\s*setAuthModalOpen\(true\)\}/.test(app), 'locked CTA must open the auth modal')
ok(app.includes('<AuthV2Modal'), 'AuthV2Modal not mounted at app root')
ok(!/generate-locked[^>]*setTab\('settings'\)/.test(app), 'locked CTA must not jump to Settings tab')
ok(app.includes('Войдите, чтобы генерировать'), 'locked CTA text missing')

// Modal structure & copy.
ok(auth.includes('export function AuthV2Modal'), 'AuthV2Modal not exported')
ok(modalBody.includes('role="dialog"'), 'modal must be a dialog (role="dialog")')
ok(modalBody.includes('aria-modal="true"'), 'modal must set aria-modal')
ok(modalBody.includes('aria-labelledby'), 'modal must set aria-labelledby')
ok(modalBody.includes('Аккаунт создаётся автоматически после первого входа'), 'modal subtitle missing')

// Phase 14.6: login/register tabs with password forms.
ok(modalBody.includes('Вход') && modalBody.includes('Регистрация'), 'modal missing login/register tabs')
ok(modalBody.includes("type=\"password\""), 'modal must have password input fields')
ok(modalBody.includes('Повторите пароль'), 'register tab must have password repeat field')
ok(modalBody.includes('Создать аккаунт и принять условия'), 'register CTA button text missing')
ok(modalBody.includes('Нажимая кнопку, вы принимаете'), 'register consent text missing')
ok(modalBody.includes('Пароли не совпадают'), 'register mismatch error missing')
ok(modalBody.includes('Неверная почта или пароль'), 'login generic error copy missing')
ok(modalBody.includes('Пароль должен быть не короче 8 символов'), 'short password error missing')
ok(modalBody.includes('Пароль не должен быть длиннее 128 символов'), 'long password error missing')
ok(modalBody.includes('Минимум 8 символов'), 'password length hint missing')
ok(modalBody.includes('Введите пароль от аккаунта'), 'login password hint missing')
ok(modalBody.includes('Аккаунт уже существует'), 'register 409 error copy missing')
ok(modalBody.includes('Проверьте email, пароль и условия регистрации'), 'register 400/422 error copy missing')
ok(modalBody.includes('Не удалось создать аккаунт. Попробуйте позже'), 'register fallback error copy missing')
ok(!modalBody.includes('Получить код'), 'OTP request-code must not be primary CTA in modal')

// Phase 14.6: password endpoint URLs called from modal.
ok(modalBody.includes('passwordLoginV2') || authCode.includes('/auth/password/login-v2'), 'password login endpoint not called from modal')
ok(modalBody.includes('passwordRegisterV2') || authCode.includes('/auth/password/register-v2'), 'password register endpoint not called from modal')

// Close affordances.
ok(modalBody.includes('auth-modal-close'), 'modal close (X) missing')
ok(modalBody.includes("e.key === 'Escape'"), 'Esc-to-close missing')
ok(/className="auth-modal-overlay" onClick=\{onClose\}/.test(auth), 'backdrop click must close')

// Telegram/MAX diagnostics — booleans only, raw initData/userId never used as identity.
ok(auth.includes('telegramDiagnostics') && auth.includes('hasInitData'), 'telegram diagnostics helper missing')
ok(auth.includes('maxDiagnostics') && auth.includes('hasWebAppData'), 'max diagnostics helper missing')
ok(authCode.includes('init_data: initData') && !authCode.includes('initDataUnsafe'), 'telegram must send raw initData, not initDataUnsafe')
ok(authCode.includes('web_app_data: webAppData'), 'max must send raw web_app_data')
ok(!/userId/.test(authCode), 'must not send a platform userId as identity')

// Settings logged-out cleanup + Phase 14.7 account card.
ok(app.includes('Войдите, чтобы управлять аккаунтом'), 'unauth settings CTA missing')
ok(app.includes('if (!isAuthedV2) {'), 'settings must branch on auth-v2 status')
ok(app.includes('auth-cta-card'), 'unauth settings card missing')
const idxBranch = app.indexOf('if (!isAuthedV2) {')
const idxAccount = app.indexOf('Статус: вход выполнен')
ok(idxBranch !== -1 && idxAccount !== -1 && idxAccount > idxBranch, 'account status must be gated behind the authed branch')

// No token storage / no X-OneNode-User.
ok(!/(local|session)Storage\.setItem\([^)]*(session_token|refresh_token)/i.test(authCode), 'tokens must not be stored')
ok(!authCode.includes('X-OneNode-User'), 'auth modal must not use X-OneNode-User')
ok(authCode.includes("credentials: 'include'"), 'v2 fetch must use cookie credentials')

if (failures.length) {
  console.error('smoke-auth-modal FAILED:')
  for (const f of failures) console.error(' -', f)
  process.exit(1)
}
console.log('smoke-auth-modal OK — all checks passed')
