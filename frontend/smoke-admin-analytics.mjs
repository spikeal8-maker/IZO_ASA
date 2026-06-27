// Static smoke for the Phase 20A Users CRM (primary admin Users tab).
import { readFileSync } from 'node:fs'

const admin = readFileSync(new URL('./src/adminAnalytics.tsx', import.meta.url), 'utf8')
const app = readFileSync(new URL('./src/App.tsx', import.meta.url), 'utf8')

const authCode = admin.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/[^\n]*/g, '')
const failures = []
const ok = (c, m) => { if (!c) failures.push(m) }

// One primary CRM table, mounted inside the Users tab (not globally).
ok((app.match(/<AdminAnalyticsV2/g) || []).length === 1, 'AdminAnalyticsV2 must be mounted exactly once (Users tab)')
ok(/tab === 'users'[\s\S]{0,80}<AdminAnalyticsV2/.test(app), 'CRM must be the primary content of the Users tab')
ok(app.includes("from './adminAnalytics'"), 'adminAnalytics not imported')

// CRM uses trusted cookie endpoints, never the legacy identity header.
ok(authCode.includes('/admin/users-analytics-v2'), 'CRM must fetch users-analytics-v2')
ok(authCode.includes('/admin/dashboard-v2'), 'CRM must fetch dashboard-v2')
ok(authCode.includes("credentials: 'include'"), 'CRM must use cookie credentials')
ok(!authCode.includes('X-OneNode-User'), 'CRM must not use X-OneNode-User')

// Human-readable rows; no raw technical id as a primary field.
ok(admin.includes('public_user_code'), 'public_user_code must be shown')
ok(admin.includes('display_name'), 'display_name must be shown')
ok(/src-badge|PROVIDER_BADGE/.test(admin), 'Web/TG/MAX source badges required')
// internal_user_id may be used for the drawer fetch + technical section, but never as a
// bold primary label in a table row.
ok(!/<strong>\{[^}]*internal_user_id/.test(admin), 'internal_user_id must not be a primary bold label')

// Phase 20C.3: compact CRM card fetched via the trusted detail endpoint.
ok(admin.includes('UserCard'), 'UserCard component missing')
ok(admin.includes('/admin/users/') && admin.includes('/analytics-v2'), 'card must fetch users/{id}/analytics-v2')
ok(/state === 'loading'|'notfound'|'forbidden'/.test(admin), 'card must handle loading/error states')
ok(admin.includes('Технические идентификаторы'), 'technical section must be labeled/collapsed')
// Compact two-column card: actions live in a sticky right panel (above the fold), details left.
ok(admin.includes('crm-card-overlay') && admin.includes('crm-card-actions'), 'compact card layout (sticky actions panel) missing')
ok(admin.includes('crm-card-cols') && admin.includes('crm-card-left'), 'two-column card layout missing')
// Detail-heavy sections collapsed into accordions (no endless scroll).
ok(admin.includes('crm-acc') && admin.includes('<details'), 'detail accordions missing')
ok(!admin.includes('UserDrawer'), 'old narrow UserDrawer must be gone')
ok(!admin.includes('crm-card-nav'), 'old landing-style left nav must be removed')
// Block 6: parsed profile fallback chain + raw-profile presence (yes/no only, no JSON).
ok(admin.includes('parsedName'), 'parsed display-name fallback chain missing')
ok(admin.includes('has_raw_profile') && !admin.includes('raw_profile_json'), 'raw profile must show yes/no only, never the JSON')
// Block 2: admin diagnostics (collapsed unless no auth).
ok(admin.includes('AdminDiagnostics') && admin.includes('/admin/diagnostics-v2'), 'admin diagnostics missing')
ok(admin.includes('APP_BUILD_LABEL') && admin.includes('window.location.origin'), 'diagnostics must show build + origin')

// Block 2/9: dense Users table with trusted quick actions in every row.
ok(admin.includes('analytics-table dense') && admin.includes('crm-row-actions'), 'dense table with row action cell missing')
ok(admin.includes('button className="mini"') || admin.includes("'mini'") || admin.includes('"mini"'), 'row mini action buttons missing')
ok(admin.includes('ActionConfirm'), 'shared confirm popover missing')
// Quick actions in the row open a reason-gated confirm using trusted-v2 endpoints.
for (const ep of ['/tokens-v2', '/role-v2', '/plan-v2', '/profile-v2', '/block-v2', '/unblock-v2', '/password-reset-v2']) {
  ok(admin.includes(ep), `quick action must call ${ep}`)
}
ok(/setRowAct\(\{ u, kind: 'tokens', preset: '50'/.test(admin), 'row +50 quick token action missing')
ok(/setRowAct\(\{ u, kind: 'tokens', preset: '-50'/.test(admin), 'row -50 quick token action missing')
ok(/reason\.trim\(\)/.test(admin), 'actions must require a reason')
ok(admin.includes('Действие будет записано в audit log'), 'confirm must show audit-log note')

// Phase 20C.4: trusted admin actions in the card/action panel.
ok(admin.includes('Админ-действия'), 'drawer must have an Админ-действия tab')
for (const ep of ['/role-v2', '/tokens-v2', '/plan-v2', '/profile-v2', '/block-v2', '/unblock-v2', '/password-reset-v2']) {
  ok(admin.includes(ep), `admin action must call ${ep}`)
}
ok(admin.includes('adminPost') && admin.includes("credentials: 'include'"), 'admin actions must POST with cookie credentials')
ok(/reason\.trim\(\)/.test(admin), 'admin actions must require a reason')
ok(admin.includes('Забанить') && admin.includes('Разбанить'), 'ban/unban controls missing')
ok(/Сделать админом|Снять админа/.test(admin), 'role controls missing')
ok(admin.includes('Изменить токены') && admin.includes('+50') && admin.includes('-50'), 'token adjust controls missing')
ok(admin.includes('Сбросить пароль'), 'reset password control missing')
ok(admin.includes('audit log'), 'must indicate audit-log writing')
// reset password input must not be persisted
ok(!/localStorage[\s\S]{0,40}(new_password|password)/.test(admin), 'admin-entered password must not be stored')

// Columns / labels are clean (Phase 20C.4 spec wording).
for (const label of ['Клиент', 'Активность', 'Источник', 'Контакт', 'Сегмент', 'Финансы', 'Генерации', 'Устройство', 'Маркетинг', 'Риск', 'Действия']) {
  ok(admin.includes(label), `column label "${label}" missing`)
}
ok(admin.includes('RowActionMenu') && admin.includes('crm-row-menu'), 'grouped row action dropdown missing')
ok(admin.includes('CrmSettingsScaffold') && admin.includes('Колонки списка') && admin.includes('Уровни админки'), 'CRM settings scaffold missing')
ok(admin.includes('settingsOpen') && admin.includes('Вид и колонки') && /settingsOpen && <CrmSettingsScaffold/.test(admin), 'CRM settings must be collapsed behind the Вид и колонки button')
ok(admin.includes('role="button"') && admin.includes('tabIndex={0}') && admin.includes('onKeyDown={rowKey}'), 'user rows must be keyboard-focusable buttons')
ok(admin.includes("e.key === 'Enter'") && admin.includes("e.key === ' '"), 'Enter/Space keyboard row open missing')
ok(admin.includes('onClick={openCard}') && admin.includes('aria-label={`Открыть карточку'), 'whole row click must open the client card')
ok(admin.includes('e.stopPropagation()'), 'row controls/dropdowns must stop click propagation')
ok(admin.includes('activityKind') && admin.includes('ACTIVITY_LABEL') && admin.includes('crm-row-avatar'), 'activity ring/labels missing')
ok(admin.includes('crm-chip') && admin.includes('status-active') && admin.includes('status-banned'), 'role/status/plan chips missing')
for (const field of ['recent_generations', 'recent_gallery', 'token_ledger_recent', 'security_summary', 'failed_login_count', 'mac_status']) {
  ok(admin.includes(field), `CRM card must render real analytics-v2 field ${field}`)
}
ok(admin.includes('crm-gallery-strip') && admin.includes('thumbnail_url'), 'gallery thumbnails must render when safe URLs exist')
ok(admin.includes('Операций ledger') && admin.includes('Ошибки входа') && admin.includes('Сбросы пароля'), 'token/security real-data labels missing')
ok(admin.includes('MAC: недоступен') && !/MAC:\s*агент/.test(admin), 'MAC must be unavailable unless explicitly agent-collected')
ok(admin.includes('Удаление/анонимизация') && /<button disabled title=\{deferred\}>Удаление\/анонимизация<\/button>/.test(admin), 'delete/anonymize must be present only as disabled/deferred')
ok(admin.includes('Отложено: backend v2 пока не отдаёт эти данные.'), 'deferred backend data must be clearly labeled')
// No nonsense labels.
for (const bad of ['тектон', 'золото', 'исидо', 'туалет', 'каменная фигура', 'регион. идентификатор']) {
  ok(!admin.includes(bad), `unclear label "${bad}" present`)
}

// "Карточка" preview button + filters present.
ok(admin.includes('Карточка'), '"Карточка" button missing')
ok(admin.includes('Все источники') && admin.includes('Все статусы'), 'source/status filters missing')

// Legacy table preserved but collapsed by default behind a toggle + warning.
ok(app.includes('showLegacyUsers'), 'legacy table must be collapsible (showLegacyUsers)')
ok(app.includes('Старые действия — временно'), 'legacy section warning label missing')
ok(/showLegacyUsers && <div className="legacy-admin-table"/.test(app), 'legacy table must be gated behind the toggle')

// No secret material in CRM UI.
for (const forbidden of ['session_token_hash', 'refresh_token_hash', 'password_hash', 'code_hash', 'initData', 'webAppData']) {
  ok(!admin.includes(forbidden), `forbidden field "${forbidden}" in CRM`)
}

if (failures.length) {
  console.error('smoke-admin-analytics FAILED:')
  for (const f of failures) console.error(' -', f)
  process.exit(1)
}
console.log('smoke-admin-analytics OK — all checks passed')
