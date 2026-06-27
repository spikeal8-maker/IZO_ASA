// Users CRM UX patch visual/interactions QA. Mocks admin APIs in the browser only.
import { chromium } from 'playwright'
import { mkdirSync } from 'node:fs'

const OUT = 'visual-out'; mkdirSync(OUT, { recursive: true })
const J = (o) => ({ status: 200, contentType: 'application/json', body: JSON.stringify(o) })
const PNG_1X1 = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII=', 'base64')
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
  recent_generations: [
    { id: 'job_20260627...', mode: 'text_to_image', provider: 'comfyui', model: 'flux', status: 'completed', prompt: 'cyberpunk city at night, rain, neon lights, reflections', token_cost: 12, created_at: isoDaysAgo(0.1), completed_at: isoDaysAgo(0.1), result_image_id: 'img_abc...', result_image_url: '/api/media/result.png?userId=x', error: null },
    { id: 'job_20260626...', mode: 'edit', provider: 'comfyui', model: 'flux', status: 'failed', prompt: 'portrait cleanup and detailed lighting', token_cost: 8, created_at: isoDaysAgo(1), completed_at: isoDaysAgo(1), result_image_id: null, result_image_url: null, error: 'Ошибка генерации. Детали скрыты.' },
  ],
  recent_gallery: [
    { id: 'img_abc...', thumbnail_url: '/api/media/thumb1.webp?userId=x', job_id: 'job_20260627...', mode: 'text_to_image', provider: 'comfyui', prompt: 'cyberpunk city at night', created_at: isoDaysAgo(0.1), favorite: true },
    { id: 'img_def...', thumbnail_url: '/api/media/thumb2.webp?userId=x', job_id: 'job_20260626...', mode: 'edit', provider: 'comfyui', prompt: 'portrait cleanup', created_at: isoDaysAgo(1), favorite: false },
  ],
  token_ledger_recent: [
    { id: 'ledger_1...', delta: -12, reason: 'generation', source: 'comfyui', job_id: 'job_20260627...', admin_action: null, created_at: isoDaysAgo(0.1), metadata: { job_id: 'job_20260627...', mode: 'text_to_image', provider: 'comfyui' } },
    { id: 'ledger_2...', delta: 50, reason: 'admin_adjust', source: 'admin_adjust', job_id: null, admin_action: 'admin_adjust_tokens', created_at: isoDaysAgo(1), metadata: { actor: 'iuid-web', reason: 'support correction' } },
    { id: 'ledger_3...', delta: 500, reason: 'payment_grant', source: 'payment_grant', job_id: null, admin_action: null, created_at: isoDaysAgo(2), metadata: { reason: 'manual payment' } },
  ],
  billing_summary: { invoice_count: 2, paid_count: 1, unpaid_count: 1, total_paid: 1200, total_refunded: 200, last_invoice_at: isoDaysAgo(0.8), last_payment_at: isoDaysAgo(2) },
  invoices_recent: [
    { id: 'inv_issued_1', id_short: 'inv_issue…', invoice_code: 'INV-20260627-ABC123', status: 'issued', currency: 'RUB', total_amount: 900, tokens_total: 300, created_at: isoDaysAgo(0.8), issued_at: isoDaysAgo(0.8), paid_at: null },
    { id: 'inv_paid_1', id_short: 'inv_paid…', invoice_code: 'INV-20260625-DEF456', status: 'partially_refunded', currency: 'RUB', total_amount: 1200, tokens_total: 500, created_at: isoDaysAgo(2), issued_at: isoDaysAgo(2), paid_at: isoDaysAgo(2) },
  ],
  payments_recent: [
    { id: 'pay_manual_1', id_short: 'pay_manua…', invoice_id: 'inv_paid_1', status: 'partially_refunded', amount: 1200, currency: 'RUB', method: 'manual', provider: 'manual', paid_at: isoDaysAgo(2), token_ledger_id: 'ledger_3…' },
  ],
  refunds_recent: [
    { id: 'ref_manual_1', id_short: 'ref_manua…', payment_id: 'pay_manual_1', invoice_id: 'inv_paid_1', status: 'completed', amount: 200, currency: 'RUB', created_at: isoDaysAgo(1), completed_at: isoDaysAgo(1), token_reversal_policy: 'deferred' },
  ],
  loyalty_summary: { promo_redemption_count: 1, bonus_count: 1, referral_children_count: 2, referral_rewards_total: 150, active_referral_code: 'REF-WEB100001' },
  referral_link: { id: 'link_1', id_short: 'link_1', referral_code: 'REF-WEB100001', status: 'active', created_at: isoDaysAgo(20) },
  promo_redemptions_recent: [
    { id: 'promo_red_1', id_short: 'promo_red…', promo_code: 'WELCOME', status: 'applied', token_bonus: 25, discount_amount: 0, token_ledger_id: 'ledger_p…', created_at: isoDaysAgo(0.9) },
  ],
  bonus_grants_recent: [
    { id: 'bonus_1', id_short: 'bonus_1', bonus_type: 'manual', status: 'granted', token_amount: 100, token_ledger_id: 'ledger_b…', created_at: isoDaysAgo(0.5) },
  ],
  referral_relations: [
    { id: 'rel_1', id_short: 'rel_1', parent_internal_user_id: 'iuid-web…', child_internal_user_id: 'iuid-tg…', referral_code: 'REF-WEB100001', status: 'active', created_at: isoDaysAgo(10) },
  ],
  referral_rewards_recent: [
    { id: 'rew_1', id_short: 'rew_1', referral_relation_id: 'rel_1', reward_type: 'tokens', status: 'granted', token_amount: 150, token_ledger_id: 'ledger_r…', created_at: isoDaysAgo(3), granted_at: isoDaysAgo(3) },
  ],
  security_summary: { failed_login_count: 1, password_reset_count: 1, ban_count: 0, role_change_count: 1, session_revocation_count: 2, suspicious_ip_count: 1 },
}
const dashboard = { dashboard: { total_users: 3, active_today: 2, active_7d: 2, sessions_active: 2, generations_total: 173, tokens_spent_total: 750, users_by_provider: { web_email: 1, telegram: 1, max: 1 }, failed_logins_24h: 0 } }
const diag = { ok: true, backend_build: '20C.4-2026-06-27', db_file: 'onenode.sqlite3', user_count: 3, auth_mode: 'trusted_cookie_session', admin_role: 'admin', admin_user_code: 'WEB-100001', admin_provider: 'web_email' }
const bootstrap = { user: { id: 'web_100001', role: 'admin', username: 'operator', firstName: 'Operator', plan: 'pro', galleryEnabled: true }, admin: { users: 3 }, fluxKleinConfig: { ok: false } }
const me = { ok: true, user: { id: 'web_100001', role: 'admin', username: 'operator', firstName: 'Operator', plan: 'pro', galleryEnabled: true } }

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
async function closeAuthModalIfPresent(page) {
  const overlay = page.locator('.auth-modal-overlay')
  if (await overlay.count()) {
    await overlay.locator('.auth-modal-close').first().click().catch(() => {})
    await page.waitForSelector('.auth-modal-overlay', { state: 'detached', timeout: 5000 }).catch(() => {})
  }
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
await page.route('**/api/me-v2', (r) => r.fulfill(J(me)))
await page.route('**/api/admin/dashboard-v2', (r) => r.fulfill(J(dashboard)))
await page.route('**/api/admin/users-analytics-v2*', (r) => r.fulfill(J({ items: users })))
await page.route('**/api/admin/users/*/analytics-v2', (r) => r.fulfill(J(detail)))
await page.route('**/api/admin/diagnostics-v2', (r) => r.fulfill(J(diag)))
await page.route('**/api/media/*', (r) => r.fulfill({ status: 200, contentType: 'image/png', body: PNG_1X1 }))

await openAdmin(page)
await closeAuthModalIfPresent(page)
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
await closeAuthModalIfPresent(page)
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
await page.screenshot({ path: `${OUT}/crm-card-real-generations.png` })
await page.screenshot({ path: `${OUT}/crm-card-token-ledger.png` })
await page.screenshot({ path: `${OUT}/crm-card-sessions-devices.png` })
await page.locator('.crm-card').getByRole('button', { name: 'Галерея' }).click()
await page.waitForSelector('.crm-gallery-strip img', { timeout: 4000 })
await page.screenshot({ path: `${OUT}/crm-card-gallery-real.png` })
await page.locator('.crm-card').getByRole('button', { name: 'Лояльность' }).click()
await page.waitForTimeout(300)
await page.screenshot({ path: `${OUT}/crm-card-loyalty-real.png` })
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
    'crm-card-real-generations.png',
    'crm-card-token-ledger.png',
    'crm-card-sessions-devices.png',
    'crm-card-gallery-real.png',
    'crm-card-loyalty-real.png',
    'crm-settings-opened.png',
  ],
}
console.log(JSON.stringify(result, null, 2))
await browser.close()
