// Static smoke for the separated AdminApp route.
import { readFileSync } from 'node:fs'

const app = readFileSync(new URL('./src/App.tsx', import.meta.url), 'utf8')
const adminApp = readFileSync(new URL('./src/AdminApp.tsx', import.meta.url), 'utf8')
const adminAnalytics = readFileSync(new URL('./src/adminAnalytics.tsx', import.meta.url), 'utf8')
const adminApi = readFileSync(new URL('./src/adminApi.ts', import.meta.url), 'utf8')
const adminMail = readFileSync(new URL('./src/adminMail.tsx', import.meta.url), 'utf8')
const topbar = readFileSync(new URL('./src/TopBarV3.tsx', import.meta.url), 'utf8')
const newUi = readFileSync(new URL('./src/newUi.tsx', import.meta.url), 'utf8')
const legacy = readFileSync(new URL('./src/LegacyApp.tsx', import.meta.url), 'utf8')

const failures = []
const ok = (condition, message) => { if (!condition) failures.push(message) }
const stripComments = (s) => s.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/[^\n]*/g, '')

// /admin must be a dedicated app route, not the legacy generator host.
ok(app.includes("const AdminApp = lazy(() => import('./AdminApp'))"), 'App.tsx must lazy-load AdminApp')
ok(/isAdminRoute\(path\) \? AdminApp/.test(app), '/admin must route to AdminApp')
ok(!/isAdminRoute\(path\) \? LegacyApp/.test(app), '/admin must not route to LegacyApp')

// AdminApp owns auth/role gating and must not import the legacy generator.
ok(adminApp.includes('useAuthV2') && adminApp.includes('initAuthV2'), 'AdminApp must own trusted auth bootstrap')
ok(adminApp.includes("me?.account?.role === 'admin'"), 'AdminApp must check trusted admin role')
ok(adminApp.includes('AdminAccessPage') && adminApp.includes('403'), 'AdminApp must render denied state')
ok(!adminApp.includes("from './LegacyApp'"), 'AdminApp must not import LegacyApp')
ok(!stripComments(adminApp).includes('X-OneNode-User'), 'AdminApp must not use legacy identity header')
ok(adminApp.includes("from './adminApi'"), 'AdminApp must use the shared admin API client')
ok(adminApi.includes("credentials: 'include'"), 'shared admin API client must use cookie credentials')
ok(adminApp.includes("import('./adminAnalytics')"), 'AdminApp must mount CRM users module directly')
ok(adminApp.includes("import('./adminModels')"), 'AdminApp must mount models module directly')
for (const endpoint of ['/admin/summary', '/admin/settings', '/admin/promos', '/admin/logs-v2']) {
  ok(adminApp.includes(endpoint), `AdminApp missing ${endpoint}`)
}
ok(adminMail.includes('/admin/mail/status-v2'), 'admin mail module missing /admin/mail/status-v2')

// The shared admin shell must have one operational strip, one real tab row and
// one combined generation chart instead of duplicated dashboard cards/charts.
ok(adminApp.includes('aria-label="Оперативные показатели"'), 'admin shell missing the consolidated operational strip')
ok(adminApp.includes('активных сессий'), 'operational strip missing active sessions')
ok(adminApp.includes('ошибок генерации сегодня'), 'operational strip missing generation errors')
ok(adminApp.includes('aria-label="Разделы админки"'), 'admin navigation must be exposed as a tab row')
ok(!adminApp.includes('className="admin-topline"'), 'legacy admin top line must be removed')
ok(!adminApp.includes('admin-grid admin-grid-compact'), 'duplicated dashboard KPI grid must be removed')
ok(adminApp.includes('AdminGenerationChart'), 'dashboard must render the combined generation chart')
ok(adminApp.includes('AdminTimeSeriesChart'), 'dashboard must render reusable time-series charts')
for (const label of ['Всего', 'Базовая модель', 'Платные изображения', 'Видео']) {
  ok(adminApp.includes(`label: '${label}'`), `combined generation chart missing ${label}`)
}
for (const title of ['Активность пользователей', 'Оплаты', 'Энергопотребление']) {
  ok(adminApp.includes(`title="${title}"`), `dashboard missing ${title} chart`)
}
ok(adminApp.includes('aria-pressed={!disabled.has(item.key)}'), 'dashboard chart legends must toggle individual series')
ok(adminAnalytics.includes('active_minutes'), 'CRM activity chart must expose heartbeat minutes')
ok(adminAnalytics.includes("aria-pressed={visible(key)}"), 'CRM chart legends must toggle individual series')

// New UI must expose Admin instead of Help for admins.
ok(topbar.includes("'admin'"), 'TopBarV3 must support admin section')
ok(topbar.includes('isAdmin') && topbar.includes('onOpenAdmin'), 'TopBarV3 must accept admin props')
ok(topbar.includes("isAdmin ? 'Админ' : 'Помощь'"), 'TopBarV3 must replace Help label for admins')
ok(newUi.includes("me?.account?.role === 'admin'"), 'newUi must derive isAdmin from trusted auth state')
ok(newUi.includes('onOpenAdmin') && newUi.includes("window.location.href = '/admin'"), 'newUi must navigate admins to /admin')

// Legacy buttons may still exist in the old app, but they must leave the old SPA.
ok(/const openAdminPage = useCallback\(\(\) => \{\s*window\.location\.href = '\/admin'/.test(legacy), 'Legacy admin button must hard-navigate to /admin')

// CRM module remains trusted-cookie only and keeps dangerous actions reason-gated.
const analyticsCode = stripComments(adminAnalytics)
ok(adminAnalytics.includes('/admin/users-analytics-v2'), 'CRM must fetch users-analytics-v2')
ok(adminAnalytics.includes('/admin/dashboard-v2'), 'CRM must fetch dashboard-v2')
ok(adminAnalytics.includes('/analytics-v2'), 'CRM card must fetch users/{id}/analytics-v2')
ok(adminAnalytics.includes("credentials: 'include'"), 'CRM must use cookie credentials')
ok(!analyticsCode.includes('X-OneNode-User'), 'CRM must not use X-OneNode-User')
ok(/reason\.trim\(\)/.test(adminAnalytics), 'admin actions must require a reason')
for (const endpoint of ['/tokens-v2', '/role-v2', '/plan-v2', '/profile-v2', '/block-v2', '/unblock-v2', '/password-reset-v2']) {
  ok(adminAnalytics.includes(endpoint), `CRM action missing ${endpoint}`)
}
for (const forbidden of ['session_token_hash', 'refresh_token_hash', 'password_hash', 'code_hash', 'initData', 'webAppData']) {
  ok(!adminAnalytics.includes(forbidden), `forbidden field "${forbidden}" in CRM`)
}

if (failures.length) {
  console.error('smoke-admin-analytics FAILED:')
  for (const failure of failures) console.error(' -', failure)
  process.exit(1)
}
console.log('smoke-admin-analytics OK — separated AdminApp route is protected and wired')
