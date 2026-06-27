// Phase 20C.3 — visual QA of the operational CRM. Mocks the admin APIs client-side
// (route interception) so the REAL new components render with sample data for screenshots.
// This is screenshot-only; it does NOT bypass server auth (the server still requires a
// trusted admin cookie — these mocks live only in the headless page).
import { chromium } from 'playwright'
import { mkdirSync } from 'node:fs'

const OUT = 'visual-out'; mkdirSync(OUT, { recursive: true })
const J = (o) => ({ status: 200, contentType: 'application/json', body: JSON.stringify(o) })

const users = [
  { internal_user_id: 'iuid-web-1', public_user_code: 'WEB-100001', display_name: 'Operator One', providers: ['web_email'], primary_provider: 'web_email', email: 'a***z@mail.ru', username: 'oper1', phone: '+*******21', plan: 'pro', role: 'admin', status: 'active', token_balance: 980, tokens_spent: 220, generations_count: 142, last_seen_at: '2026-06-26T18:00:00Z', last_platform: 'web', last_ip: '10.0.0.5', internal_user_id_short: 'iuid-web…' },
  { internal_user_id: 'iuid-tg-2', public_user_code: 'TG-100002', display_name: 'Анна Клиент', providers: ['telegram'], primary_provider: 'telegram', email: null, username: 'anna_k', phone: null, plan: 'mini', role: 'user', status: 'active', token_balance: 50, tokens_spent: 130, generations_count: 31, last_seen_at: '2026-06-27T08:10:00Z', last_platform: 'telegram', last_ip: '95.1.2.3', internal_user_id_short: 'iuid-tg-…' },
  { internal_user_id: 'iuid-max-3', public_user_code: 'MAX-100003', display_name: 'Banned User', providers: ['max'], primary_provider: 'max', email: 'b***n@x.io', username: null, phone: null, plan: 'free', role: 'user', status: 'banned', token_balance: 0, tokens_spent: 400, generations_count: 5, last_seen_at: '2026-06-20T11:00:00Z', last_platform: 'max', last_ip: '88.9.9.9', internal_user_id_short: 'iuid-max…' },
]
const detail = {
  ok: true, summary: { ...users[0], first_seen_at: '2026-01-04T10:00:00Z', city: 'Москва', country: 'RU', active_sessions_count: 2, device_count: 2 },
  identities: [{ provider: 'web_email', provider_user_id: '900001abc', provider_username: 'oper1', provider_email: 'a***z@mail.ru', first_name: 'Operator', last_name: 'One', phone: '+*******21', language_code: 'ru', linked_at: '2026-01-04T10:00:00Z', verified_at: '2026-01-04T10:05:00Z', last_login_at: '2026-06-26T18:00:00Z', has_raw_profile: true }],
  sessions: [{ id: 's1', provider: 'web_email', platform: 'web', ip_address: '10.0.0.5', device: { browser: 'Chrome', os: 'Windows', device_type: 'desktop' }, created_at: '2026-06-26T18:00:00Z', last_seen_at: '2026-06-26T19:00:00Z', expires_at: '2026-07-26T18:00:00Z', revoked_at: null, revoke_reason: null }],
  devices: [{ installation_id: 'inst-abcdef123456', anonymous_id: 'anon-zzz9988', platform: 'web', storage_type: 'local', first_seen_at: '2026-01-04T10:00:00Z', last_seen_at: '2026-06-26T19:00:00Z', metadata: { language: 'ru', timezone: 'Europe/Moscow', app_version: '20C.3' } }],
  recent_events: [{ event_name: 'login_succeeded', platform: 'web', created_at: '2026-06-26T18:00:00Z' }],
  recent_security_events: [{ severity: 'info', event_type: 'password_login_succeeded', ip_address: '10.0.0.5', created_at: '2026-06-26T18:00:00Z' }],
  admin_actions: [{ action: 'admin_adjust_tokens', actor: 'iuid-web', created_at: '2026-06-25T12:00:00Z' }],
  token_summary: { spent: 220, entries: 9, balance: 980 },
}
const dashboard = { dashboard: { total_users: 3, active_today: 1, active_7d: 3, sessions_active: 2, generations_total: 178, tokens_spent_total: 750, users_by_provider: { web_email: 1, telegram: 1, max: 1 }, failed_logins_24h: 0 } }
const diag = { ok: true, backend_build: '20C.3-2026-06-27', db_file: 'onenode.sqlite3', user_count: 3, auth_mode: 'trusted_cookie_session', admin_role: 'admin', admin_user_code: 'WEB-100001', admin_provider: 'web_email' }
const bootstrap = { user: { id: 'web_100001', role: 'admin', username: 'operator', firstName: 'Operator', plan: 'pro', galleryEnabled: true }, admin: { users: 3 }, fluxKleinConfig: { ok: false } }

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1366, height: 900 } })
await page.route('**/api/app/bootstrap', (r) => r.fulfill(J(bootstrap)))
await page.route('**/api/admin/dashboard-v2', (r) => r.fulfill(J(dashboard)))
await page.route('**/api/admin/users-analytics-v2*', (r) => r.fulfill(J({ items: users })))
await page.route('**/api/admin/users/*/analytics-v2', (r) => r.fulfill(J(detail)))
await page.route('**/api/admin/diagnostics-v2', (r) => r.fulfill(J(diag)))

await page.goto('http://127.0.0.1:5173/?userId=web_100001', { waitUntil: 'domcontentloaded', timeout: 40000 })
await page.waitForTimeout(1500)
await page.getByRole('button', { name: 'Админ' }).first().click().catch(() => {})
await page.waitForTimeout(500)
await page.getByRole('button', { name: 'Админы и пользователи' }).first().click().catch(() => {})
await page.waitForTimeout(1200)
await page.screenshot({ path: `${OUT}/crm-table.png` })

// Row quick action -> compact confirm popover
await page.getByRole('button', { name: '+50' }).first().click().catch(() => {})
await page.waitForTimeout(600)
await page.screenshot({ path: `${OUT}/crm-confirm.png` })
await page.getByRole('button', { name: 'Отмена' }).first().click().catch(() => {})
await page.waitForTimeout(300)

// Compact card (actions above the fold)
await page.getByRole('button', { name: 'Карточка' }).first().click().catch(() => {})
await page.waitForTimeout(1200)
await page.screenshot({ path: `${OUT}/crm-card.png` })

const adminVisible = await page.locator('.analytics-table.dense').count()
console.log(JSON.stringify({ dense_table_rendered: adminVisible > 0, shots: ['crm-table.png', 'crm-confirm.png', 'crm-card.png'] }, null, 2))
await browser.close()
