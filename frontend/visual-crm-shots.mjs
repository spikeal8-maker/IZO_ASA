// Users CRM UX patch visual/interactions QA. Mocks admin APIs in the browser only.
import { chromium } from 'playwright'
import { mkdirSync } from 'node:fs'

const OUT = 'visual-out'; mkdirSync(OUT, { recursive: true })
const J = (o) => ({ status: 200, contentType: 'application/json', body: JSON.stringify(o) })
const now = new Date()
const isoDaysAgo = (days) => new Date(now.getTime() - days * 86400000).toISOString()

const users = [
  { internal_user_id: 'iuid-web-1', public_user_code: 'WEB-100001', display_name: 'Operator One', providers: ['web_email'], primary_provider: 'web_email', email: 'a***z@mail.ru', username: 'oper1', phone: '+*******21', plan: 'pro', role: 'admin', status: 'active', token_balance: 980, tokens_spent: 220, generations_count: 142, gallery_count: 48, last_seen_at: isoDaysAgo(0.2), first_seen_at: '2026-01-04T10:00:00Z', last_platform: 'web', last_ip: '10.0.0.5', marketing_source: 'utm: admin_panel', last_device: { browser: 'Chrome', os: 'Windows' }, active_sessions_count: 2, device_count: 2, internal_user_id_short: 'iuid-web...' },
  { internal_user_id: 'iuid-tg-2', public_user_code: 'TG-100002', display_name: 'Анна Клиент', providers: ['telegram'], primary_provider: 'telegram', email: null, username: 'anna_k', phone: null, plan: 'mini', role: 'user', status: 'active', token_balance: 50, tokens_spent: 130, generations_count: 31, gallery_count: 12, last_seen_at: isoDaysAgo(0.6), first_seen_at: '2026-05-01T08:10:00Z', last_platform: 'telegram', last_ip: '95.1.2.3', last_device: { browser: 'Telegram', os: 'Android' }, active_sessions_count: 0, device_count: 1, internal_user_id_short: 'iuid-tg-...' },
  { internal_user_id: 'iuid-max-3', public_user_code: 'MAX-100003', display_name: 'Banned User', providers: ['max'], primary_provider: 'max', email: 'b***n@x.io', username: null, phone: null, plan: 'free', role: 'user', status: 'banned', token_balance: 0, tokens_spent: 400, generations_count: 0, gallery_count: 0, last_seen_at: isoDaysAgo(45), first_seen_at: '2026-04-11T11:00:00Z', last_platform: 'max', last_ip: '88.9.9.9', last_device: { browser: 'MAX', os: 'Windows' }, active_sessions_count: 0, device_count: 1, internal_user_id_short: 'iuid-max...' },
]
const detail = {
  ok: true, summary: { ...users[0], first_seen_at: '2026-01-04T10:00:00Z', city: 'Москва', country: 'RU' },
  identities: [{ provider: 'web_email', provider_user_id: '900001abc', provider_username: 'oper1', provider_email: 'a***z@mail.ru', first_name: 'Operator', last_name: 'One', phone: '+*******21', language_code: 'ru', linked_at: '2026-01-04T10:00:00Z', verified_at: '2026-01-04T10:05:00Z', last_login_at: isoDaysAgo(0.2), has_raw_profile: true }],
  sessions: [{ id: 's1', provider: 'web_email', platform: 'web', ip_address: '10.0.0.5', device: { browser: 'Chrome', os: 'Windows', device_type: 'desktop' }, created_at: isoDaysAgo(0.2), last_seen_at: isoDaysAgo(0.1), expires_at: '2026-07-26T18:00:00Z', revoked_at: null, revoke_reason: null }],
  devices: [{ installation_id: 'inst-abcdef123456', anonymous_id: 'anon-zzz9988', platform: 'web', storage_type: 'local', first_seen_at: '2026-01-04T10:00:00Z', last_seen_at: isoDaysAgo(0.1), metadata: { language: 'ru', timezone: 'Europe/Moscow', app_version: '20C.4' } }],
  recent_events: [{ event_name: 'login_succeeded', platform: 'web', created_at: isoDaysAgo(0.2) }],
  recent_security_events: [{ severity: 'info', event_type: 'password_login_succeeded', ip_address: '10.0.0.5', created_at: isoDaysAgo(0.2) }],
  admin_actions: [{ action: 'admin_adjust_tokens', actor: 'iuid-web', created_at: isoDaysAgo(1) }],
  token_summary: { spent: 220, entries: 9, balance: 980 },
}
const dashboard = { dashboard: { total_users: 3, active_today: 2, active_7d: 2, sessions_active: 2, generations_total: 173, tokens_spent_total: 750, users_by_provider: { web_email: 1, telegram: 1, max: 1 }, failed_logins_24h: 0 } }
const diag = { ok: true, backend_build: '20C.4-2026-06-27', db_file: 'onenode.sqlite3', user_count: 3, auth_mode: 'trusted_cookie_session', admin_role: 'admin', admin_user_code: 'WEB-100001', admin_provider: 'web_email' }
const bootstrap = { user: { id: 'web_100001', role: 'admin', username: 'operator', firstName: 'Operator', plan: 'pro', galleryEnabled: true }, admin: { users: 3 }, fluxKleinConfig: { ok: false } }

const assert = (condition, message) => { if (!condition) throw new Error(message) }
async function openAdmin(page) {
  await page.goto('http://127.0.0.1:5173/?userId=web_100001', { waitUntil: 'domcontentloaded', timeout: 40000 })
  await page.waitForTimeout(1200)
  await page.getByRole('button', { name: 'Админ' }).first().click().catch(() => {})
  await page.waitForTimeout(400)
  await page.getByRole('button', { name: 'Админы и пользователи' }).first().click().catch(() => {})
  await page.waitForSelector('.analytics-table.dense .crm-row', { timeout: 15000 })
}
async function closeCard(page) {
  await page.locator('.crm-card .auth-modal-close').first().click()
  await page.waitForSelector('.crm-card', { state: 'detached', timeout: 5000 })
}
async function assertCardFrom(page, locator, message) {
  await locator.click()
  await page.waitForSelector('.crm-card', { timeout: 6000 })
  assert(await page.locator('.crm-card').count() === 1, message)
  await closeCard(page)
}
async function assertConfirmNotCard(page, locator, message) {
  await locator.click()
  await page.waitForSelector('.crm-confirm', { timeout: 6000 })
  assert(await page.locator('.crm-card').count() === 0, message)
  await page.getByRole('button', { name: 'Отмена' }).first().click()
  await page.waitForSelector('.crm-confirm', { state: 'detached', timeout: 5000 })
}

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1720, height: 980 } })
await page.route('**/api/app/bootstrap', (r) => r.fulfill(J(bootstrap)))
await page.route('**/api/admin/dashboard-v2', (r) => r.fulfill(J(dashboard)))
await page.route('**/api/admin/users-analytics-v2*', (r) => r.fulfill(J({ items: users })))
await page.route('**/api/admin/users/*/analytics-v2', (r) => r.fulfill(J(detail)))
await page.route('**/api/admin/diagnostics-v2', (r) => r.fulfill(J(diag)))

await openAdmin(page)
await page.screenshot({ path: `${OUT}/crm-table-default.png` })

const table = page.locator('.analytics-table.dense')
const firstRow = table.locator('.crm-row').first()
const visibleActionCount = await firstRow.locator('.crm-row-actions > button.mini, .crm-row-actions > .crm-row-menu > summary').count()
assert(visibleActionCount <= 4, `row has ${visibleActionCount} visible action controls`)
assert(await page.locator('.crm-settings').count() === 0, 'CRM settings must be collapsed by default')

await firstRow.hover()
await page.screenshot({ path: `${OUT}/crm-row-hover.png` })

await assertCardFrom(page, firstRow.locator('strong').first(), 'client name click did not open card')
await assertCardFrom(page, firstRow.locator('span').nth(1), 'activity area click did not open card')
await assertCardFrom(page, firstRow.locator('span').nth(3), 'contact area click did not open card')
await assertCardFrom(page, firstRow.locator('span').nth(5), 'balance area click did not open card')

await firstRow.focus()
await page.keyboard.press('Enter')
await page.waitForSelector('.crm-card', { timeout: 6000 })
await closeCard(page)
await firstRow.focus()
await page.keyboard.press('Space')
await page.waitForSelector('.crm-card', { timeout: 6000 })
await closeCard(page)

await firstRow.locator('.crm-row-menu summary').click()
await page.waitForSelector('.crm-row-menu[open] .crm-row-menu-pop', { timeout: 4000 })
assert(await page.locator('.crm-card').count() === 0, 'dropdown click opened card')
await page.screenshot({ path: `${OUT}/crm-action-dropdown-open.png` })
await firstRow.locator('.crm-row-menu-pop button', { hasText: 'Редактировать профиль' }).click()
await page.waitForSelector('.crm-confirm', { timeout: 6000 })
assert(await page.locator('.crm-card').count() === 0, 'dropdown item opened card')
await page.getByRole('button', { name: 'Отмена' }).first().click()
await page.waitForSelector('.crm-confirm', { state: 'detached', timeout: 5000 })
await firstRow.locator('.crm-row-menu[open] summary').click().catch(() => {})
await page.waitForTimeout(150)

await assertConfirmNotCard(page, firstRow.locator('.crm-row-actions > button.mini').nth(1), '+50 opened card instead of confirm')
await firstRow.locator('.crm-row-actions > button.mini').nth(1).click()
await page.waitForSelector('.crm-confirm', { timeout: 6000 })
await page.screenshot({ path: `${OUT}/crm-plus50-confirm-open.png` })
await page.getByRole('button', { name: 'Отмена' }).first().click()
await page.waitForSelector('.crm-confirm', { state: 'detached', timeout: 5000 })
await assertConfirmNotCard(page, firstRow.locator('.crm-row-actions > button.mini').nth(2), '-50 opened card instead of confirm')

await firstRow.click()
await page.waitForSelector('.crm-card', { timeout: 6000 })
await page.waitForTimeout(900)
await page.screenshot({ path: `${OUT}/crm-card-opened-by-row-click.png` })
await closeCard(page)

await page.getByRole('button', { name: 'Вид и колонки' }).click()
await page.waitForSelector('.crm-settings', { timeout: 4000 })
await page.screenshot({ path: `${OUT}/crm-settings-opened.png` })

const bodyText = await page.locator('body').innerText()
const result = {
  dense_table_rendered: await table.count() > 0,
  row_visible_controls: visibleActionCount,
  settings_collapsed_by_default: true,
  row_click_and_keyboard_open_card: true,
  quick_actions_do_not_open_card: true,
  dropdown_does_not_open_card: true,
  mac_unavailable: bodyText.includes('MAC: недоступен'),
  shots: [
    'crm-table-default.png',
    'crm-row-hover.png',
    'crm-action-dropdown-open.png',
    'crm-plus50-confirm-open.png',
    'crm-card-opened-by-row-click.png',
    'crm-settings-opened.png',
  ],
}
console.log(JSON.stringify(result, null, 2))
await browser.close()
