// Phase 20A–20C.4: Users CRM — an operator console. Cookie auth only
// (credentials:include), never the legacy identity header. Dense table with trusted
// quick actions in every row + a compact two-column user card (actions above the fold).
// Every risky action requires a reason and is written to audit_logs. No tokens/hashes
// are ever requested or shown.
import { useCallback, useEffect, useState } from 'react'
import type { KeyboardEvent as ReactKeyboardEvent, MouseEvent as ReactMouseEvent, ReactElement } from 'react'
import { APP_BUILD_LABEL } from './diagMeta'
import { avatarPresets } from './profileSupport'
import './crmViewport.css'
import './crmDossier.css'

const API = (import.meta as ImportMeta & { env?: { VITE_API_BASE_URL?: string } }).env?.VITE_API_BASE_URL || '/api'
const MODE = (import.meta as ImportMeta & { env?: { MODE?: string } }).env?.MODE || 'unknown'
const IS_PROD = Boolean((import.meta as ImportMeta & { env?: { PROD?: boolean } }).env?.PROD)

async function adminGet<T>(path: string): Promise<T | null> {
  try {
    const r = await fetch(`${API}${path}`, { credentials: 'include' })
    if (!r.ok) return null
    return (await r.json()) as T
  } catch { return null }
}

// Trusted admin mutation (cookie auth). Returns {ok, status, detail?}.
async function adminPost(path: string, body: Record<string, unknown>): Promise<{ ok: boolean; status: number; detail?: string }> {
  try {
    const r = await fetch(`${API}${path}`, {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    })
    let detail: string | undefined
    try { detail = (await r.json())?.detail } catch { /* ignore */ }
    return { ok: r.ok, status: r.status, detail }
  } catch { return { ok: false, status: 0 } }
}

const PROVIDER_BADGE: Record<string, string> = { web_email: 'Web', telegram: 'TG', max: 'MAX' }

interface Dash { dashboard?: AnyRec }
export interface CrmUserRow {
  internal_user_id?: string // for the card fetch + technical section only (never a primary label)
  public_user_code?: string; display_name?: string; primary_provider?: string; providers?: string[]
  avatar_url?: string | null; avatar_preset?: string | null
  email?: string | null; username?: string | null; phone?: string | null; plan?: string | null
  last_seen_at?: string | null; last_platform?: string | null; last_ip?: string | null
  country?: string | null; city?: string | null; language_code?: string | null; timezone?: string | null
  gender?: string | null; age?: number | null
  device_count?: number; active_sessions_count?: number
  generations_count?: number; tokens_spent?: number; token_balance?: number; status?: string; role?: string
  daily_tokens_used?: number; daily_tokens_limit?: number
  daily_tokens_remaining?: number; main_token_balance?: number
  last_login_at?: string | null; last_generation_at?: string | null
  period_metrics?: AnyRec
  first_seen_at?: string | null; gallery_count?: number; marketing_source?: string | null; risk_level?: string | null
  gallery_access?: boolean; gallery_enabled?: boolean
  account_group?: 'customer' | 'admin' | 'demo'
  daily_tokens?: number; gallery_slots?: number; gallery_used?: number; gallery_free?: number; gallery_full?: boolean
  last_device?: { browser?: string | null; os?: string | null; device_type?: string | null } | null
  internal_user_id_short?: string
}

function Badge({ p }: { p: string }): ReactElement {
  return <span className={`src-badge src-${p}`}>{PROVIDER_BADGE[p] || p}</span>
}
function shortTime(iso?: unknown): string {
  if (!iso) return '—'
  try { return new Date(iso as string).toLocaleString() } catch { return String(iso) }
}
type AnyRec = Record<string, unknown>
const S = (v: unknown): string => (v === null || v === undefined || v === '' ? '—' : String(v))
const jsonSummary = (v: unknown): string => v && typeof v === 'object'
  ? Object.entries(v as AnyRec).map(([k, value]) => `${k}: ${S(value)}`).join(' · ') || '—'
  : S(v)
const shortId = (v: unknown, n = 8): string => { const s = v == null ? '' : String(v); return s ? s.slice(0, n) + (s.length > n ? '…' : '') : '—' }
const n0 = (v: unknown): number => (typeof v === 'number' && Number.isFinite(v) ? v : 0)
const moneyExact = (v: unknown, currency = 'RUB'): string => `${n0(v).toLocaleString('ru-RU', { minimumFractionDigits: currency === 'USD' ? 4 : 0, maximumFractionDigits: currency === 'USD' ? 6 : 2 })} ${currency === 'RUB' ? '₽' : currency}`
const durationLabel = (v: unknown): string => {
  const seconds = n0(v)
  if (!seconds) return '—'
  if (seconds < 60) return `${Math.round(seconds)} сек.`
  const minutes = Math.floor(seconds / 60)
  return `${minutes} мин. ${Math.round(seconds % 60)} сек.`
}
const generationStatusLabel = (v: unknown): string => ({ completed: 'Готово', failed: 'Ошибка', queued: 'В очереди', running: 'В работе', submitting: 'Запуск' }[String(v)] || S(v))
const modeLabel = (v: unknown): string => ({ text_to_image: 'Текст → изображение', image_to_image: 'Изображение → изображение', edit: 'Редактор', paint: 'Рисование', inpaint: 'Маска', outpaint: 'Расширение', faceswap: 'Лицо', remove_background: 'Удаление фона', text_to_video: 'Текст → видео', image_to_video: 'Изображение → видео', first_last_frame: 'Начало и конец', reference_to_video: 'Видео по референсам' }[String(v)] || S(v))
const tokenReasonLabel = (v: unknown): string => ({ generation: 'Списание за генерацию', daily_generation: 'Списание дневных токенов', generation_refund: 'Возврат за неудачную генерацию', tariff_monthly_grant: 'Начисление по тарифу', promo_code_redeemed: 'Начисление по промокоду', manual_admin_adjustment: 'Ручная корректировка' }[String(v)] || S(v))
const eventLabel = (v: unknown): string => ({
  me_opened: 'Открыт профиль', app_opened: 'Открыто приложение',
  login_started: 'Начат вход', login_succeeded: 'Успешный вход',
  password_login_succeeded: 'Вход по паролю', password_login_failed: 'Ошибка входа по паролю',
  password_register_succeeded: 'Регистрация', profile_updated: 'Профиль изменён',
  avatar_uploaded: 'Аватар изменён', prompt_improved: 'Промпт улучшен',
  voice_transcribed: 'Голос преобразован в текст', frontend_runtime_error: 'Ошибка интерфейса',
  generation_started: 'Запущена генерация', generation_created: 'Создана генерация',
  generation_completed: 'Генерация завершена', generation_failed: 'Ошибка генерации',
  admin_tokens_adjusted: 'Администратор изменил токены', crm_bonus_granted: 'Начислен CRM-бонус',
  promo_code_redeemed: 'Активирован промокод', session_revoked: 'Пользовательская сессия завершена',
  session_expired: 'Истёк срок пользовательской сессии',
}[String(v)] || S(v).replaceAll('_', ' '))
const publicationStatusLabel = (v: unknown): string => ({ published: 'В ленте', pending_review: 'На модерации', hidden: 'Скрыто', rejected: 'Отклонено' }[String(v)] || S(v))
const sourceRoleLabel = (v: unknown, slot: unknown): string => ({ base: 'Основа', face: 'Лицо', reference: `Референс ${S(slot)}`, first_frame: 'Первый кадр', last_frame: 'Последний кадр', mask: 'Маска' }[String(v)] || `Исходник ${S(slot)}`)
const deferred = 'Отложено: backend v2 пока не отдаёт эти данные.'
type ActivityKind = 'online' | 'today' | 'week' | 'month' | 'cold'
type UserSort = 'recent' | 'activity_asc' | 'created_desc' | 'created_asc' | 'generations_desc' | 'generations_asc' | 'tokens_desc' | 'tokens_asc' | 'balance_desc' | 'balance_asc' | 'code_asc' | 'plan_asc' | 'plan_desc' | 'name_asc' | 'name_desc' | 'source_asc' | 'source_desc' | 'contact_asc' | 'contact_desc'
const ACTIVITY_LABEL: Record<ActivityKind, string> = { online: 'Онлайн', today: 'Был сегодня', week: 'Был на неделе', month: 'Был в месяце', cold: 'Нет генераций / холодный' }

function activityKind(u: CrmUserRow): ActivityKind {
  if (n0(u.active_sessions_count) > 0) return 'online'
  const t = u.last_seen_at ? new Date(u.last_seen_at).getTime() : 0
  const days = t ? (Date.now() - t) / 86400000 : Number.POSITIVE_INFINITY
  if (n0(u.generations_count) === 0 || days > 30) return 'cold'
  if (days <= 1) return 'today'
  if (days <= 7) return 'week'
  return 'month'
}

function initials(u: CrmUserRow & AnyRec, ids?: AnyRec[]): string {
  const name = parsedName(u, ids)
  const parts = name.split(/[\s._-]+/).filter(Boolean)
  const raw = parts.length > 1 ? `${parts[0][0]}${parts[1][0]}` : name.slice(0, 2)
  return raw.toUpperCase()
}

function AvatarMark({ u, ids, className }: { u: CrmUserRow & AnyRec; ids?: AnyRec[]; className: string }): ReactElement {
  const providerAvatar = ids?.map((i) => i.avatar_url).find((a): a is string => typeof a === 'string' && a.length > 0)
  const src = (typeof u.avatar_url === 'string' && u.avatar_url) ? u.avatar_url : (providerAvatar || '')
  return <span className={className}>{src ? <img src={src} alt="" /> : initials(u, ids)}</span>
}

function riskLabel(u: CrmUserRow & AnyRec): string {
  const explicit = String(u.risk_level || '').trim()
  if (explicit) return explicit
  if (u.status === 'banned') return 'Высокий'
  const sec = Array.isArray(u.recent_security_events) ? u.recent_security_events.length : 0
  if (sec > 2) return 'Средний'
  return 'Низкий'
}

function deviceLabel(u: CrmUserRow): string {
  const browser = u.last_device?.browser
  const os = u.last_device?.os
  const device = u.last_device?.device_type
  return [browser, os, device].filter(Boolean).join(' · ') || 'Данных пока нет'
}

function quotaLabel(u: CrmUserRow & AnyRec): string {
  const used = Number(u.gallery_used ?? u.gallery_count ?? 0)
  const total = Number(u.gallery_slots ?? 0)
  return `${used}/${total}`
}

function genderAgeLabel(u: CrmUserRow & AnyRec): string {
  const gender = u.gender === 'male' ? 'муж.' : u.gender === 'female' ? 'жен.' : 'пол —'
  const age = u.age ? `${u.age} лет` : 'возраст —'
  return `${gender} · ${age}`
}

// Block 6 — parsed display name fallback (display_name → first+last → username →
// provider username → public_user_code).
function parsedName(sm: AnyRec, ids?: AnyRec[]): string {
  const id0 = ids?.[0]
  const fn = [id0?.first_name, id0?.last_name].filter(Boolean).join(' ')
  return String(sm.display_name || fn || sm.username || id0?.provider_username || sm.public_user_code || '—')
}

interface UserDetail {
  summary?: CrmUserRow & AnyRec
  identities?: AnyRec[]; sessions?: AnyRec[]; devices?: AnyRec[]
  recent_events?: AnyRec[]; recent_security_events?: AnyRec[]; admin_actions?: AnyRec[]
  recent_generations?: AnyRec[]; recent_gallery?: AnyRec[]; recent_videos?: AnyRec[]; token_ledger_recent?: AnyRec[]
  billing_summary?: AnyRec; invoices_recent?: AnyRec[]; payments_recent?: AnyRec[]; refunds_recent?: AnyRec[]
  loyalty_summary?: AnyRec; promo_redemptions_recent?: AnyRec[]; bonus_grants_recent?: AnyRec[]
  referral_link?: AnyRec; referral_relations?: AnyRec[]; referral_rewards_recent?: AnyRec[]
  security_summary?: AnyRec
  access_summary?: AnyRec; ip_history?: AnyRec[]; client_history?: AnyRec[]; model_usage?: AnyRec[]; history_totals?: AnyRec
  token_summary?: { spent?: number; entries?: number; balance?: number }
  token_economics?: AnyRec; generation_economics?: AnyRec; cash_economics?: AnyRec; activity_series?: AnyRec
}

interface HistoryPage { items?: AnyRec[]; total?: number; has_more?: boolean; offset?: number; limit?: number }

function FinanceEvent({ item }: { item: AnyRec }): ReactElement {
  const kind = String(item.kind || '')
  const status = String(item.status || '')
  const failed = status === 'failed' || status === 'cancelled'
  if (kind === 'payment') {
    const title = status === 'paid' ? 'Оплата получена' : status === 'failed' ? 'Попытка оплаты не прошла' : status === 'refunded' ? 'Оплата возвращена' : 'Операция оплаты'
    return <details className={`crm-ledger-row ${failed ? 'failed' : status === 'paid' ? 'ok' : ''}`}><summary><b>{title}</b><span>{moneyExact(item.amount, S(item.currency))} · токены {item.tokens_credited ? 'зачислены' : 'не зачислены'}</span><small>{shortTime(item.paid_at || item.created_at)}</small></summary><p>{S(item.provider)} / {S(item.method)} · платёж {S(item.id)}{item.reason ? ` · ${S(item.reason)}` : ''}</p></details>
  }
  if (kind === 'invoice') {
    const title = status === 'cancelled' ? 'Счёт отменён' : status === 'paid' ? 'Счёт оплачен' : status === 'issued' ? 'Счёт выставлен' : 'Счёт создан'
    return <details className={`crm-ledger-row ${failed ? 'failed' : status === 'paid' ? 'ok' : ''}`}><summary><b>{title}</b><span>{S(item.code)} · {moneyExact(item.amount, S(item.currency))} · {S(item.tokens)} токенов</span><small>{shortTime(item.cancelled_at || item.paid_at || item.created_at)}</small></summary><p>{item.reason ? S(item.reason) : 'Дополнительных пояснений нет.'}</p></details>
  }
  if (kind === 'refund') return <details className={`crm-ledger-row ${status === 'completed' || status === 'succeeded' ? 'ok' : ''}`}><summary><b>Возврат денег</b><span>{moneyExact(item.amount, S(item.currency))} · токены {item.tokens_reversed ? 'отозваны' : 'не менялись'}</span><small>{shortTime(item.completed_at || item.created_at)}</small></summary><p>Возврат {S(item.id)}{item.reason ? ` · ${S(item.reason)}` : ''}</p></details>
  const delta = n0(item.delta)
  const daily = n0(item.daily_part)
  const main = n0(item.main_part)
  return <details className={`crm-ledger-row ${delta > 0 || String(item.reason).includes('refund') ? 'ok' : ''}`}><summary><b>{tokenReasonLabel(item.reason)}</b><span>{delta > 0 ? `+${delta}` : daily ? `−${daily} дневных` : `−${main || Math.abs(delta)}`} ток.</span><small>{shortTime(item.created_at)}</small></summary><p>{item.job_id ? `Связанная генерация: ${S(item.job_id)}` : 'Операция не связана с генерацией.'}</p></details>
}

function GenerationEvent({ item }: { item: AnyRec }): ReactElement {
  const tokens = (item.tokens || {}) as AnyRec
  const cost = item.cost_kind === 'actual'
    ? `Фактическая цена API: ${moneyExact(item.actual_cost_rub)} / ${moneyExact(item.actual_cost_usd, 'USD')}`
    : item.cost_kind === 'unreconciled_estimate'
      ? `Не сверено с OpenRouter: вероятный расход ${moneyExact(item.unreconciled_cost_rub)} / ${moneyExact(item.unreconciled_cost_usd, 'USD')} — пользовательские токены возвращены`
    : item.cost_kind === 'estimated'
      ? `Расчётная цена до запуска: ${moneyExact(item.estimated_cost_rub)} / ${moneyExact(item.estimated_cost_usd, 'USD')} — не списание`
      : item.provider_kind === 'local' ? 'Локальная себестоимость: тариф мощности пока не настроен' : 'Цена провайдера не записана'
  return <details className={item.status === 'failed' ? 'crm-generation-row failed' : 'crm-generation-row'}>
    <summary>
      <span className="crm-generation-preview">{item.preview_type === 'video' ? <video src={S(item.preview_url)} muted preload="metadata" /> : item.preview_url ? <img src={S(item.preview_url)} alt="" /> : <span>∅</span>}</span>
      <span className="crm-generation-name"><b>{S(item.model || item.provider)}</b><small>{modeLabel(item.mode)}</small></span>
      <span className="crm-generation-prompt" title={S(item.prompt)}>{S(item.prompt || item.error || 'Промпт не сохранён')}</span>
      <span className={`crm-generation-status status-${S(item.status)}`}>{generationStatusLabel(item.status)}</span>
      <span>{S(tokens.net)} ток.</span><span>{durationLabel(item.elapsed_seconds)}</span><small>{shortTime(item.created_at)}</small>
    </summary>
    <div className="crm-generation-detail"><div className="crm-generation-chips"><span>{item.provider_kind === 'local' ? 'Локальная модель · ComfyUI' : `API · ${S(item.provider)}`}</span><span>{cost}</span><span>Job: {S(item.id)}</span>{n0(tokens.refunded) ? <span>Возврат: {S(tokens.refunded)} ток.</span> : null}</div><p>{S(item.prompt || 'Промпт не сохранён')}</p>{Boolean(item.settings) && <small>{Object.entries(item.settings as AnyRec).map(([k, v]) => `${k}: ${S(v)}`).join(' · ')}</small>}{item.error ? <small className="crm-err">Ошибка: {S(item.error)}</small> : null}</div>
  </details>
}

function UserActivityChart({ series }: { series: AnyRec }): ReactElement {
  const days = Array.isArray(series.days) ? series.days as AnyRec[] : []
  const [disabled, setDisabled] = useState<Set<string>>(() => new Set())
  if (!days.length) return <p className="crm-card-note">Для графика пока недостаточно данных.</p>
  const width = 920
  const height = 210
  const top = 20
  const bottom = 168
  const step = width / days.length
  const maxGeneration = Math.max(1, ...days.map((day) => n0(day.local_images) + n0(day.api_images) + n0(day.videos)))
  const maxLogins = Math.max(1, ...days.map((day) => n0(day.logins)))
  const maxActivity = Math.max(1, ...days.map((day) => n0(day.active_minutes)))
  const barWidth = Math.max(5, Math.min(14, step / 5))
  const barHeight = (value: unknown) => (n0(value) / maxGeneration) * (bottom - top)
  const loginPoints = days.map((day, index) => {
    const x = index * step + step / 2
    const y = bottom - (n0(day.logins) / maxLogins) * (bottom - top)
    return `${x.toFixed(1)},${y.toFixed(1)}`
  }).join(' ')
  const activityPoints = days.map((day, index) => {
    const x = index * step + step / 2
    const y = bottom - (n0(day.active_minutes) / maxActivity) * (bottom - top)
    return `${x.toFixed(1)},${y.toFixed(1)}`
  }).join(' ')
  const visible = (key: string) => !disabled.has(key)
  const toggle = (key: string) => setDisabled((current) => {
    const next = new Set(current)
    if (next.has(key)) next.delete(key)
    else next.add(key)
    return next
  })
  const legends = [
    ['local', 'Базовая модель'], ['api', 'Платные модели'], ['video', 'Видео'],
    ['activity', 'Активность, мин.'], ['login', 'Входы'],
  ]
  return <div className="crm-profile-chart">
    <div className="crm-chart-legend">{legends.map(([key, label]) => <button type="button" key={key} className={`${key} ${visible(key) ? '' : 'disabled'}`} aria-pressed={visible(key)} onClick={() => toggle(key)}>{label}</button>)}</div>
    <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Входы и генерации пользователя за 14 дней">
      <line x1="0" y1={bottom} x2={width} y2={bottom} className="axis" />
      {days.map((day, index) => {
        const center = index * step + step / 2
        const localHeight = barHeight(day.local_images)
        const apiHeight = barHeight(day.api_images)
        const videoHeight = barHeight(day.videos)
        return <g key={S(day.date)}>
          <title>{`${S(day.date)}: базовая ${S(day.local_images)}, платные ${S(day.api_images)}, видео ${S(day.videos)}, входы ${S(day.logins)}`}</title>
          {visible('local') && <rect className="local" x={center - barWidth * 1.7} y={bottom - localHeight} width={barWidth} height={localHeight} rx="2" />}
          {visible('api') && <rect className="api" x={center - barWidth / 2} y={bottom - apiHeight} width={barWidth} height={apiHeight} rx="2" />}
          {visible('video') && <rect className="video" x={center + barWidth * .7} y={bottom - videoHeight} width={barWidth} height={videoHeight} rx="2" />}
          {(index % 2 === 0 || index === days.length - 1) && <text x={center} y="193" textAnchor="middle">{String(day.date || '').slice(5)}</text>}
        </g>
      })}
      {visible('activity') && <polyline className="activity-line" points={activityPoints} />}
      {visible('activity') && days.map((day, index) => <circle key={`activity-${S(day.date)}`} className="activity-dot" cx={index * step + step / 2} cy={bottom - (n0(day.active_minutes) / maxActivity) * (bottom - top)} r="3" />)}
      {visible('login') && <polyline className="login-line" points={loginPoints} />}
      {visible('login') && days.map((day, index) => <circle key={`login-${S(day.date)}`} className="login-dot" cx={index * step + step / 2} cy={bottom - (n0(day.logins) / maxLogins) * (bottom - top)} r="3" />)}
    </svg>
  </div>
}

// --- Shared trusted-action confirm (compact popover, reason-gated, audited). ---
type ActKind = 'tokens' | 'discount' | 'role' | 'plan' | 'profile' | 'ban' | 'unban' | 'reset' | 'deactivate' | 'invoice' | 'mark_paid' | 'refund' | 'cancel_invoice' | 'bonus' | 'cancel_bonus' | 'promo' | 'referral_reward'
function ActionConfirm({ target, kind, preset, context, onClose, onDone }: {
  target: CrmUserRow; kind: ActKind; preset?: string; context?: AnyRec; onClose: () => void; onDone: () => void
}): ReactElement {
  const isAdmin = target.role === 'admin'
  const [reason, setReason] = useState('')
  const [value, setValue] = useState(preset ?? (kind === 'profile' ? String(target.display_name ?? '') : ''))
  const [tokens, setTokens] = useState(kind === 'invoice' ? '0' : '')
  const [bonusType, setBonusType] = useState('manual')
  const [email, setEmail] = useState(typeof target.email === 'string' ? target.email : '')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const iuid = target.internal_user_id
  const title: Record<ActKind, string> = {
    tokens: 'Изменить токены', discount: 'Персональная скидка', role: isAdmin ? 'Снять админа' : 'Сделать админом', plan: 'Изменить тариф',
    profile: 'Изменить профиль', ban: 'Забанить / отключить', unban: 'Разбанить', reset: 'Сбросить пароль', deactivate: 'Деактивировать',
    invoice: 'Выставить счёт', mark_paid: 'Отметить оплату', refund: 'Возврат', cancel_invoice: 'Отменить счёт',
    bonus: 'Начислить бонус', cancel_bonus: 'Отменить бонус', promo: 'Применить промокод', referral_reward: 'Реферальная корректировка',
  }
  const danger = kind === 'ban' || kind === 'deactivate' || kind === 'reset' || kind === 'refund' || kind === 'cancel_invoice' || kind === 'cancel_bonus' || (kind === 'role' && isAdmin)
  const changePreview = kind === 'tokens' ? `${Number(value) > 0 ? '+' : ''}${value || '—'} токенов`
    : kind === 'discount' ? `Скидка на оплату: ${value || '0'}%`
    : kind === 'role' ? `${isAdmin ? 'admin → user' : 'user → admin'}`
    : kind === 'plan' ? `Тариф: ${value || '—'}`
    : kind === 'profile' ? `Имя/email будут обновлены`
    : kind === 'reset' ? 'Новый пароль будет установлен'
    : kind === 'deactivate' ? 'Пользователь не сможет входить и генерировать'
    : kind === 'ban' ? 'Доступ будет заблокирован'
    : kind === 'invoice' ? `Счёт: ${value || '—'} ₽ · ${tokens || 0} токенов`
    : kind === 'mark_paid' ? `Оплата: ${value || S(context?.total_amount)} ${S(context?.currency || 'RUB')}`
    : kind === 'refund' ? `Возврат: ${value || S(context?.amount)} ${S(context?.currency || 'RUB')}`
    : kind === 'cancel_invoice' ? `Счёт ${S(context?.invoice_code)} будет отменён`
    : kind === 'bonus' ? `Бонус: +${value || '—'} токенов`
    : kind === 'cancel_bonus' ? `Бонус ${S(context?.id_short || context?.id)} будет отменён`
    : kind === 'promo' ? `Промокод: ${value || '—'}`
    : kind === 'referral_reward' ? `Реферальная корректировка: +${value || '—'} токенов`
    : 'Доступ будет восстановлен'
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const submit = async () => {
    if (!iuid) { setMsg('Нет внутреннего id.'); return }
    if (!reason.trim()) { setMsg('Укажите причину.'); return }
    setBusy(true); setMsg('')
    const base = `/admin/users/${encodeURIComponent(iuid)}`
    let res: { ok: boolean; status: number; detail?: string } = { ok: false, status: 0 }
    if (kind === 'tokens') { const d = Number(value); if (!d) { setBusy(false); setMsg('Введите ненулевое число.'); return } res = await adminPost(`${base}/tokens-v2`, { delta: d, reason }) }
    else if (kind === 'discount') { const percent = Number(value); if (!Number.isInteger(percent) || percent < 0 || percent > 90) { setBusy(false); setMsg('Скидка должна быть целым числом от 0 до 90%.'); return } res = await adminPost(`${base}/discount-v2`, { percent, reason }) }
    else if (kind === 'role') res = await adminPost(`${base}/role-v2`, { role: isAdmin ? 'user' : 'admin', reason })
    else if (kind === 'plan') { if (!value) { setBusy(false); setMsg('Выберите тариф.'); return } res = await adminPost(`${base}/plan-v2`, { plan: value, reason }) }
    else if (kind === 'profile') { const body: Record<string, unknown> = { reason }; if (value.trim()) body.display_name = value.trim(); if (email.trim()) body.email = email.trim(); if (!body.display_name && !body.email) { setBusy(false); setMsg('Нет полей для изменения.'); return } res = await adminPost(`${base}/profile-v2`, body) }
    else if (kind === 'ban') res = await adminPost(`${base}/block-v2`, { reason })
    else if (kind === 'deactivate') res = await adminPost(`${base}/block-v2`, { reason })
    else if (kind === 'unban') res = await adminPost(`${base}/unblock-v2`, { reason })
    else if (kind === 'reset') { if (value.length < 8) { setBusy(false); setMsg('Пароль не короче 8 символов.'); return } res = await adminPost(`${base}/password-reset-v2`, { new_password: value, reason }) }
    else if (kind === 'invoice') {
      const amount = Number(value); const tokenAmount = Number(tokens || 0)
      if (!amount || amount < 0 || tokenAmount < 0) { setBusy(false); setMsg('Укажите корректную сумму и токены.'); return }
      res = await adminPost(`${base}/invoices-v2`, { currency: 'RUB', reason, status: 'issued', items: [{ title: 'Ручной счёт CRM', quantity: 1, unit_amount: amount, token_amount: tokenAmount }] })
    }
    else if (kind === 'mark_paid') {
      const invoiceId = String(context?.id || '')
      const amount = Number(value || context?.total_amount || 0)
      if (!invoiceId || !amount) { setBusy(false); setMsg('Нет счёта для оплаты.'); return }
      res = await adminPost(`/admin/invoices/${encodeURIComponent(invoiceId)}/mark-paid-v2`, { amount, method: 'manual', reason, idempotency_key: `manual-ui-${invoiceId}-${Date.now()}` })
    }
    else if (kind === 'refund') {
      const paymentId = String(context?.id || '')
      const amount = Number(value || context?.amount || 0)
      if (!paymentId || !amount) { setBusy(false); setMsg('Нет платежа для возврата.'); return }
      res = await adminPost(`/admin/payments/${encodeURIComponent(paymentId)}/refund-v2`, { amount, reason, idempotency_key: `refund-ui-${paymentId}-${Date.now()}` })
    }
    else if (kind === 'cancel_invoice') {
      const invoiceId = String(context?.id || '')
      if (!invoiceId) { setBusy(false); setMsg('Нет счёта для отмены.'); return }
      res = await adminPost(`/admin/invoices/${encodeURIComponent(invoiceId)}/cancel-v2`, { reason })
    }
    else if (kind === 'bonus') {
      const tokenAmount = Number(value)
      if (!tokenAmount || tokenAmount <= 0) { setBusy(false); setMsg('Укажите положительный бонус.'); return }
      res = await adminPost(`${base}/bonus-v2`, { token_amount: tokenAmount, bonus_type: bonusType, reason, idempotency_key: `bonus-ui-${iuid}-${Date.now()}` })
    }
    else if (kind === 'cancel_bonus') {
      const bonusId = String(context?.id || '')
      if (!bonusId) { setBusy(false); setMsg('Нет бонуса для отмены.'); return }
      res = await adminPost(`${base}/bonus/${encodeURIComponent(bonusId)}/cancel-v2`, { reason })
    }
    else if (kind === 'promo') {
      if (!value.trim()) { setBusy(false); setMsg('Укажите промокод.'); return }
      res = await adminPost(`${base}/apply-promo-v2`, { promo_code: value.trim(), reason, idempotency_key: `promo-ui-${iuid}-${value.trim()}-${Date.now()}` })
    }
    else if (kind === 'referral_reward') {
      const tokenAmount = Number(value)
      if (!tokenAmount || tokenAmount <= 0) { setBusy(false); setMsg('Укажите положительную корректировку.'); return }
      res = await adminPost(`${base}/referral-reward-v2`, { token_amount: tokenAmount, reason, idempotency_key: `ref-ui-${iuid}-${Date.now()}` })
    }
    setBusy(false)
    if (res.ok) { setMsg('Готово. Записано в audit log.'); onDone(); window.setTimeout(onClose, 650) }
    else setMsg(res.detail || (res.status === 403 ? 'Недостаточно прав или действие запрещено.' : 'Не удалось выполнить действие.'))
  }

  return (
    <div className="crm-confirm-overlay" onClick={onClose}>
      <div className={danger ? 'crm-confirm danger' : 'crm-confirm'} role="dialog" aria-label="Подтверждение действия" onClick={(e) => e.stopPropagation()}>
        <strong>{title[kind]}</strong>
        <div className="crm-confirm-summary">
          <span>Пользователь</span><b>{parsedName(target as AnyRec)} · {S(target.public_user_code)}</b>
          <span>Действие</span><b>{title[kind]}</b>
          <span>Значение</span><b>{changePreview}</b>
        </div>
        {kind === 'tokens' && (
          <div className="crm-confirm-field">
            <div className="crm-quick"><button className="secondary" onClick={() => setValue('50')}>+50</button><button className="secondary" onClick={() => setValue('-50')}>-50</button><button className="secondary" onClick={() => setValue('1')}>+1</button><button className="secondary" onClick={() => setValue('-1')}>-1</button></div>
            <label>Изменение баланса<input value={value} onChange={(e) => setValue(e.target.value)} placeholder="например 50 или -50" /></label>
          </div>
        )}
        {kind === 'discount' && <label>Скидка, %<input value={value} onChange={(e) => setValue(e.target.value)} inputMode="numeric" placeholder="от 0 до 90" /></label>}
        {kind === 'invoice' && <><label>Сумма счёта, ₽<input value={value} onChange={(e) => setValue(e.target.value)} inputMode="numeric" placeholder="например 1250" /></label><label>Токены к начислению после оплаты<input value={tokens} onChange={(e) => setTokens(e.target.value)} inputMode="numeric" placeholder="например 500" /></label></>}
        {(kind === 'mark_paid' || kind === 'refund') && <label>Сумма<input value={value} onChange={(e) => setValue(e.target.value)} inputMode="numeric" placeholder={S(context?.total_amount || context?.amount)} /></label>}
        {kind === 'bonus' && <label>Тип бонуса<select value={bonusType} onChange={(e) => setBonusType(e.target.value)}><option value="manual">manual</option><option value="compensation">compensation</option><option value="campaign">campaign</option><option value="referral">referral</option></select></label>}
        {(kind === 'bonus' || kind === 'referral_reward') && <label>Токены<input value={value} onChange={(e) => setValue(e.target.value)} inputMode="numeric" placeholder="например 100" /></label>}
        {kind === 'promo' && <label>Промокод<input value={value} onChange={(e) => setValue(e.target.value)} autoComplete="off" placeholder="WELCOME" /></label>}
        {kind === 'plan' && <label>Тариф<select value={value} onChange={(e) => setValue(e.target.value)}><option value="">Выбрать…</option><option value="free">free</option><option value="mini">mini</option><option value="plus">plus</option><option value="pro">pro</option><option value="business">business</option></select></label>}
        {kind === 'profile' && <><label>Отображаемое имя<input value={value} onChange={(e) => setValue(e.target.value)} autoComplete="off" /></label><label>Email<input value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="off" /></label></>}
        {kind === 'reset' && <label>Новый пароль (не сохраняется)<input type="password" value={value} onChange={(e) => setValue(e.target.value)} autoComplete="off" /></label>}
        <label>Причина (обязательно)<input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Причина действия" /></label>
        <p className="crm-audit-note">Действие будет записано в audit log. Оператор, цель, значение и причина сохраняются для аудита.</p>
        <div className="crm-action-buttons">
          <button className="generate small-action" disabled={busy || !reason.trim()} onClick={() => void submit()}>{busy ? '…' : 'Подтвердить'}</button>
          <button className="secondary" onClick={onClose}>Отмена</button>
        </div>
        {msg && <p className={msg.startsWith('Готово') ? 'crm-action-ok' : 'crm-err'}>{msg}</p>}
      </div>
    </div>
  )
}

// --- Compact two-column user card (details left, sticky actions right). ---
function UserCard({ u, onClose, onChanged }: { u: CrmUserRow; onClose: () => void; onChanged?: () => void }): ReactElement {
  const [data, setData] = useState<UserDetail | null>(null)
  const [state, setState] = useState<'loading' | 'ok' | 'notfound' | 'forbidden' | 'error'>('loading')
  const [reloadKey, setReloadKey] = useState(0)
  const [act, setAct] = useState<{ kind: ActKind; preset?: string; context?: AnyRec } | null>(null)
  const [tab, setTab] = useState<'overview' | 'activity' | 'payments' | 'prompts' | 'gallery' | 'actions'>('overview')
  const [activityView, setActivityView] = useState<'logins' | 'events' | 'security'>('logins')
  const [history, setHistory] = useState<HistoryPage | null>(null)
  const [historyLoading, setHistoryLoading] = useState(false)
  const [historyError, setHistoryError] = useState('')
  const [avatarOpen, setAvatarOpen] = useState(false)
  const [avatarBusy, setAvatarBusy] = useState(false)
  const [avatarMsg, setAvatarMsg] = useState('')
  const [selectedImage, setSelectedImage] = useState<AnyRec | null>(null)
  const [selectedVideo, setSelectedVideo] = useState<AnyRec | null>(null)
  const [deleteReason, setDeleteReason] = useState('')
  const [deleteBusy, setDeleteBusy] = useState(false)
  const [deleteMsg, setDeleteMsg] = useState('')

  useEffect(() => {
    let alive = true
    const iuid = u.internal_user_id
    if (!iuid) {
      window.setTimeout(() => { if (alive) setState('error') }, 0)
      return () => { alive = false }
    }
    ;(async () => {
      try {
        const r = await fetch(`${API}/admin/users/${encodeURIComponent(iuid)}/analytics-v2`, { credentials: 'include' })
        if (!alive) return
        if (r.status === 404) { setState('notfound'); return }
        if (r.status === 401 || r.status === 403) { setState('forbidden'); return }
        if (!r.ok) { setState('error'); return }
        setData(await r.json()); setState('ok')
      } catch { if (alive) setState('error') }
    })()
    return () => { alive = false }
  }, [u.internal_user_id, reloadKey])
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  const historySection = tab === 'activity' ? activityView : tab === 'payments' ? 'finance' : tab === 'prompts' ? 'generations' : tab === 'gallery' ? 'media' : ''
  const loadHistory = useCallback(async (append = false) => {
    if (!u.internal_user_id || !historySection) return
    const offset = append ? (history?.items?.length || 0) : 0
    setHistoryLoading(true)
    setHistoryError('')
    try {
      const r = await fetch(`${API}/admin/users/${encodeURIComponent(u.internal_user_id)}/history-v2?section=${historySection}&limit=50&offset=${offset}`, { credentials: 'include' })
      if (!r.ok) { setHistoryError(r.status === 401 || r.status === 403 ? 'Админ-сессия истекла. Обновите вход в админку.' : `Не удалось загрузить данные (${r.status}).`); return }
      const page = await r.json() as HistoryPage
      setHistory((prev) => append ? { ...page, items: [...(prev?.items || []), ...(page.items || [])] } : page)
    } finally { setHistoryLoading(false) }
  }, [history?.items?.length, historySection, u.internal_user_id])
  useEffect(() => {
    let alive = true
    if (!historySection || !u.internal_user_id) return () => { alive = false }
    ;(async () => {
      await Promise.resolve()
      if (!alive) return
      setHistory(null)
      setHistoryError('')
      setHistoryLoading(true)
      const r = await fetch(`${API}/admin/users/${encodeURIComponent(u.internal_user_id || '')}/history-v2?section=${historySection}&limit=50&offset=0`, { credentials: 'include' })
      if (!alive) return
      if (r.ok) setHistory(await r.json() as HistoryPage)
      else setHistoryError(r.status === 401 || r.status === 403 ? 'Админ-сессия истекла. Обновите вход в админку.' : `Не удалось загрузить данные (${r.status}).`)
    })().catch(() => { if (alive) setHistoryError('Сервер не ответил.') }).finally(() => { if (alive) setHistoryLoading(false) })
    return () => { alive = false }
  }, [historySection, u.internal_user_id])

  const sm = (data?.summary || u) as CrmUserRow & AnyRec
  const ids = data?.identities
  const merged = { ...u, ...(data?.summary || {}) } as CrmUserRow
  const active = activityKind(merged)
  const isAdmin = String(sm.role) === 'admin'
  const isBanned = sm.status === 'banned'
  const row = (k: string, v: unknown) => <><dt>{k}</dt><dd>{S(v)}</dd></>
  const securityCount = (data?.recent_security_events || []).length
  const banner = state === 'loading' ? 'Загрузка…'
    : state === 'notfound' ? 'Пользователь не найден.'
    : state === 'forbidden' ? 'Нет trusted-сессии администратора. Войдите как админ.'
    : state === 'error' ? 'Не удалось загрузить данные.' : ''
  const adminReady = state === 'ok'

  const actionButton = (kind: ActKind, label: string, preset?: string, danger?: boolean) =>
    <button className={danger ? 'secondary danger crm-supported-action' : 'secondary crm-supported-action'} disabled={!adminReady} title={adminReady ? undefined : 'Войдите как админ'} onClick={() => adminReady && setAct({ kind, preset })}>{adminReady ? label : 'Войдите как админ'}</button>
  const disabledAction = (label: string) => <button className="secondary deferred-action" disabled title={deferred}>{label}<small>Отложено</small></button>
  const money = (v: unknown, currency = 'RUB') => `${n0(v).toLocaleString()} ${currency}`
  const unpaidInvoice = (data?.invoices_recent || []).find((i) => ['draft', 'issued'].includes(String(i.status)))
  const refundablePayment = (data?.payments_recent || []).find((p) => ['paid', 'partially_refunded'].includes(String(p.status)))
  const cancellableBonus = (data?.bonus_grants_recent || []).find((b) => String(b.status) === 'granted' && n0(b.token_amount) > 0)
  const recentGenerations = data?.recent_generations || []
  const recentGallery = data?.recent_gallery || []
  const recentVideos = data?.recent_videos || []
  const imageUrl = (img: AnyRec) => String(img.admin_media_url || img.media_url || img.image_url || img.thumbnail_url || img.admin_result_image_url || img.result_image_url || '')
  const fullImageUrl = (img: AnyRec) => String(img.admin_full_url || img.full_url || img.admin_media_url || img.media_url || img.image_url || img.result_image_url || '')
  const periodMetrics = (sm.period_metrics || {}) as AnyRec
  const generationPeriods = (periodMetrics.generations || {}) as AnyRec
  const totalJobs = (generationPeriods.total || {}) as AnyRec
  const tokenPeriods = (periodMetrics.token_usage || {}) as AnyRec
  const tokenEconomics = (data?.token_economics || {}) as AnyRec
  const generationEconomics = (data?.generation_economics || {}) as AnyRec
  const cashEconomics = (data?.cash_economics || {}) as AnyRec
  const activitySeries = (data?.activity_series || {}) as AnyRec
  const openImage = (img: AnyRec) => {
    setSelectedImage(img)
    setDeleteReason('')
    setDeleteMsg('')
  }
  const deleteGalleryImage = async () => {
    if (!selectedImage?.admin_delete_id || !u.internal_user_id || !deleteReason.trim()) return
    setDeleteBusy(true); setDeleteMsg('')
    try {
      const res = await adminPost(`/admin/users/${encodeURIComponent(u.internal_user_id)}/gallery/${encodeURIComponent(String(selectedImage.admin_delete_id))}/delete-v2`, { reason: deleteReason.trim() })
      if (!res.ok) { setDeleteMsg(res.detail || `Ошибка ${res.status}`); return }
      setSelectedImage(null); setDeleteReason(''); setReloadKey((k) => k + 1); onChanged?.()
    } finally {
      setDeleteBusy(false)
    }
  }
  const chooseAvatarPreset = async (presetId: string) => {
    if (!u.internal_user_id) return
    const preset = avatarPresets.find((item) => item.id === presetId)
    if (!preset) return
    setAvatarBusy(true); setAvatarMsg('')
    try {
      const result = await adminPost(`/admin/users/${encodeURIComponent(u.internal_user_id)}/profile-v2`, { avatar_preset: preset.id, avatar_url: preset.url, reason: 'Корректировка аватара администратором' })
      if (!result.ok) { setAvatarMsg(result.detail || `Ошибка ${result.status}`); return }
      setAvatarOpen(false); setReloadKey((key) => key + 1); onChanged?.()
    } finally { setAvatarBusy(false) }
  }

  return (
    <div className="crm-card-overlay" onClick={onClose}>
      <div className="crm-card" role="dialog" aria-label="Карточка пользователя" onClick={(e) => e.stopPropagation()}>
        <header className="crm-card-header">
          <div className="crm-card-hero">
            <div className="crm-card-id crm-card-id-rich">
              <button type="button" className="crm-avatar-button" aria-label="Изменить аватар пользователя" title="Изменить аватар" onClick={() => setAvatarOpen((value) => !value)}>
                <AvatarMark u={sm} ids={ids} className={`crm-avatar activity-${active} ${isBanned ? 'risk' : ''}`} />
                <span>✎</span>
              </button>
              <div className="crm-card-person">
                <div className="crm-card-titleline">
                  <h2>{parsedName(sm, ids)}</h2>
                  <span className={isBanned ? 'status-banned' : 'status-active'}>{S(sm.status)}</span>
                  <span className="crm-role-chip">{S(sm.role)}</span>
                  <span className="crm-plan-chip">{S(sm.plan)}</span>
                </div>
                <div className="crm-card-code-row">
                  <span className="crm-preview-code">{S(sm.public_user_code)}</span>
                  <button type="button" className="crm-copy-mini" onClick={() => navigator.clipboard?.writeText(S(sm.public_user_code)).catch(() => undefined)} title="Скопировать код">□</button>
                  <span className="crm-preview-badges">{((sm.providers as string[]) || u.providers || []).map((p) => <Badge key={p} p={p} />)}</span>
                </div>
              </div>
            </div>
            <div className="crm-header-kpis" aria-label="Краткая сводка пользователя">
              <span><small>Принёс денег</small><b>{moneyExact(cashEconomics.net_received_rub)}</b></span>
              <span><small>Баланс</small><b>{S(sm.main_token_balance ?? sm.token_balance)} ток.</b></span>
              <span><small>Последний вход</small><b>{shortTime(sm.last_login_at)}</b></span>
              <span><small>Последняя генерация</small><b>{shortTime(sm.last_generation_at)}</b></span>
              <span><small>Запуски</small><b>{S(totalJobs.total)} · {S(totalJobs.completed)}/{S(totalJobs.failed)}</b></span>
            </div>
            <div className="crm-card-top-actions">
              <button className="secondary" onClick={() => setTab('actions')}>Управление</button>
              <button className="auth-modal-close" aria-label="Закрыть" onClick={onClose}>×</button>
            </div>
          </div>
          {avatarOpen && <div className="crm-avatar-picker" role="dialog" aria-label="Выбор аватара пользователя">
            <div className="crm-avatar-picker-head"><strong>Изменить аватар</strong><button type="button" aria-label="Закрыть выбор аватара" onClick={() => setAvatarOpen(false)}>×</button></div>
            <small>Выберите новый аватар. Изменение сохранится в профиле и журнале аудита.</small>
            <div className="crm-avatar-presets">{avatarPresets.map((preset) => <button type="button" key={preset.id} disabled={avatarBusy} className={sm.avatar_preset === preset.id ? 'active' : ''} onClick={() => void chooseAvatarPreset(preset.id)}><img src={preset.url} alt={preset.label} /></button>)}</div>
            {avatarMsg && <small className="crm-err">{avatarMsg}</small>}
          </div>}
        </header>

        <div className="crm-card-cols">
          <div className="crm-card-left">
            {banner && <p className={state === 'ok' ? 'crm-card-note' : 'crm-err'}>{banner}</p>}
            <div className="crm-panel">
              <h4>Профиль и контакты</h4>
              <dl className="crm-preview-list">
                {row('Имя', parsedName(sm, ids))}{row('Email', sm.email)}{row('Username', sm.username)}{row('Телефон', sm.phone)}
                {row('Пол / возраст', genderAgeLabel(sm))}{row('Язык', sm.language_code || (ids?.[0] as AnyRec)?.language_code)}{row('Гео', `${S(sm.city)} / ${S(sm.country)}${sm.timezone ? ` · ${S(sm.timezone)}` : ''}`)}{row('Роль', sm.role)}{row('Тариф', sm.plan || 'mini')}{row('Галерея', quotaLabel(sm))}
              </dl>
            </div>
            <div className="crm-panel">
              <h4>Источники входа</h4>
              {(ids || []).map((i, n) => {
                const nm = [i.first_name, i.last_name].filter(Boolean).join(' ')
                return (
                <div className="crm-subrow" key={n}>
                  <span><Badge p={String(i.provider)} /> {nm ? `${nm} · ` : ''}@{S(i.provider_username)} · {S(i.provider_email)}{i.phone ? ` · ${S(i.phone)}` : ''} · id {shortId(i.provider_user_id, 6)}</span>
                  <small>вход {shortTime(i.last_login_at)} · {S(i.language_code)} · {i.verified_at ? 'verified' : 'не подтв.'} · аватар: {i.avatar_url ? 'есть' : 'нет'} · raw-профиль: {i.has_raw_profile ? 'да' : 'нет'}</small>
                </div>
                )
              })}{!ids?.length && <p className="crm-card-note">—</p>}
            </div>
            <div className="crm-panel crm-content-panel">
              <div className="crm-panel-titleline">
                <h4>Контент</h4>
                <div>
                  <button type="button" className="crm-panel-link" onClick={() => setTab('prompts')}>Промпты</button>
                  <button type="button" className="crm-panel-link" onClick={() => setTab('gallery')}>Медиа</button>
                </div>
              </div>
              <dl className="crm-preview-list crm-content-stats">
                {row('Сегодня / вчера', `${S((generationPeriods.today as AnyRec)?.total)} / ${S((generationPeriods.yesterday as AnyRec)?.total)}`)}{row('Изображения / видео всего', `${S((generationPeriods.total as AnyRec)?.images)} / ${S((generationPeriods.total as AnyRec)?.videos)}`)}{row('Галерея фото', quotaLabel(sm))}{row('Видео', `${recentVideos.length} последних`) }
              </dl>
              <div className="crm-content-grid">
                <div className="crm-prompt-feed" aria-label="Последние генерации и промпты">
                  {recentGenerations.slice(0, 5).map((g, n) => (
                    <button type="button" className="crm-prompt-row" key={n} onClick={() => setTab('prompts')}>
                      <span className="crm-prompt-meta">
                        <strong>{S(g.status || 'generation')}</strong>
                        <span>{S(g.mode)}</span>
                        <span>{S(g.provider || g.model)}</span>
                        <span>{shortTime(g.created_at)}</span>
                        {g.token_cost !== undefined && g.token_cost !== null && <span>{S(g.token_cost)} ток.</span>}
                      </span>
                      <span className="crm-prompt-text">{S(g.prompt || g.error || 'Промпт не сохранён')}</span>
                      <span className="crm-prompt-foot">job {S(g.id)}{g.result_image_id ? ` · image ${S(g.result_image_id)}` : ''}</span>
                    </button>
                  ))}
                  {!recentGenerations.length && <p className="crm-card-note">Пока нет сохранённых генераций с промптом.</p>}
                </div>
                <div className="crm-gallery-preview" aria-label="Последние медиа пользователя">
                  {recentGallery.slice(0, 6).map((img, n) => (
                    <button type="button" className="crm-gallery-thumb" key={n} onClick={() => openImage(img)} title={S(img.prompt)}>
                      {imageUrl(img) ? <img src={imageUrl(img)} alt="" /> : <span className="crm-gallery-empty">Нет превью</span>}
                      <small>{S(img.mode)} · {shortTime(img.created_at)}</small>
                    </button>
                  ))}
                  {recentVideos.slice(0, 4).map((video, n) => (
                    <button type="button" className="crm-gallery-thumb crm-video-thumb" key={`video-${n}`} onClick={() => setSelectedVideo(video)} title={S(video.prompt)}>
                      <video src={S(video.media_url)} muted preload="metadata" />
                      <small>Видео · {shortTime(video.created_at)}</small>
                    </button>
                  ))}
                  {!recentGallery.length && !recentVideos.length && <p className="crm-card-note">У пользователя пока нет доступных медиа.</p>}
                </div>
              </div>
            </div>
            <div className="crm-panel">
              <h4>Финансы и токены</h4>
              <dl className="crm-preview-list">
                {row('Основной баланс', data?.token_summary?.balance ?? sm.token_balance)}{row('Дневной лимит', `${S(sm.daily_tokens_used)} / ${S(sm.daily_tokens_limit)} · осталось ${S(sm.daily_tokens_remaining)}`)}
                {row('Сегодня: дневные / основные', `${S((tokenPeriods.today as AnyRec)?.daily)} / ${S((tokenPeriods.today as AnyRec)?.main)}`)}{row('Всего списано с основного', data?.token_summary?.spent ?? sm.tokens_spent)}
                {row('Операций ledger', data?.token_summary?.entries ?? 0)}
                {row('Счетов', data?.billing_summary?.invoice_count ?? 0)}{row('Неоплачено', data?.billing_summary?.unpaid_count ?? 0)}
                {row('Оплачено', money(data?.billing_summary?.total_paid))}{row('Возвраты', money(data?.billing_summary?.total_refunded))}
                {row('Скидка на оплату', `${n0(data?.billing_summary?.personal_discount_percent)}%`)}{row('Бонусы', data?.loyalty_summary?.bonus_count ?? 0)}
              </dl>
              <div className="crm-rows">
                {(data?.invoices_recent || []).slice(0, 4).map((i, n) => <small key={`inv${n}`}><strong>{S(i.invoice_code)}</strong> · {S(i.status)} · {money(i.total_amount, S(i.currency))} · {S(i.tokens_total)} ток. · {shortTime(i.created_at)}</small>)}
                {(data?.payments_recent || []).slice(0, 3).map((p, n) => <small key={`pay${n}`}>Оплата · <strong>{money(p.amount, S(p.currency))}</strong> · {S(p.status)} · {shortTime(p.paid_at || p.created_at)}</small>)}
                {(data?.refunds_recent || []).slice(0, 3).map((r, n) => <small key={`ref${n}`}>Возврат · <strong>{money(r.amount, S(r.currency))}</strong> · {S(r.status)} · {shortTime(r.completed_at || r.created_at)}</small>)}
                {(data?.token_ledger_recent || []).slice(0, 5).map((l, n) => <small key={n}><strong>{Number(l.delta) > 0 ? '+' : ''}{S(l.delta)}</strong> · {S(l.reason)} · {S(l.source)} · {S(l.job_id)} · {shortTime(l.created_at)}</small>)}
              </div>
            </div>
            <div className="crm-panel">
              <h4>Промо, бонусы и рефералы</h4>
              <dl className="crm-preview-list">
                {row('Промокодов', data?.loyalty_summary?.promo_redemption_count ?? 0)}
                {row('Бонусов', data?.loyalty_summary?.bonus_count ?? 0)}
                {row('Реф. детей', data?.loyalty_summary?.referral_children_count ?? 0)}
                {row('Реф. токенов', data?.loyalty_summary?.referral_rewards_total ?? 0)}
                {row('Реф. код', data?.loyalty_summary?.active_referral_code ?? data?.referral_link?.referral_code)}
              </dl>
              <div className="crm-rows">
                {(data?.promo_redemptions_recent || []).slice(0, 3).map((p, n) => <small key={`promo${n}`}>Промо · <strong>{S(p.promo_code)}</strong> · {S(p.status)} · +{S(p.token_bonus)} ток. · {shortTime(p.created_at)}</small>)}
                {(data?.bonus_grants_recent || []).slice(0, 3).map((b, n) => <small key={`bonus${n}`}>Бонус · <strong>{S(b.bonus_type)}</strong> · {S(b.status)} · +{S(b.token_amount)} ток. · {shortTime(b.created_at)}</small>)}
                {(data?.referral_rewards_recent || []).slice(0, 3).map((r, n) => <small key={`rew${n}`}>Реф. награда · <strong>{S(r.status)}</strong> · +{S(r.token_amount)} ток. · {shortTime(r.granted_at || r.created_at)}</small>)}
              </div>
            </div>
            <div className="crm-two">
              <div className="crm-panel">
                <h4>Устройства и сессии</h4>
                {(data?.sessions || []).slice(0, 6).map((s, n) => (
                  <div className="crm-subrow" key={n}><small><strong>{S(s.platform)}</strong> · {S(s.ip_address)} {s.revoked_at ? '· отозв.' : '· активна'}</small><small>{S((s.device as AnyRec)?.browser)} · {S((s.device as AnyRec)?.os)} · {S((s.device as AnyRec)?.device_type)} · {S((s.device as AnyRec)?.app_build)}</small></div>
                ))}{!data?.sessions?.length && <p className="crm-card-note">—</p>}
              </div>
              <div className="crm-panel">
                <h4>Устройства</h4>
                {(data?.devices || []).slice(0, 6).map((d, n) => (
                  <div className="crm-subrow" key={n}><small><strong>{S(d.platform)}</strong> · inst {S(d.installation_id)}</small><small>{S((d.metadata as AnyRec)?.browser)} · {S((d.metadata as AnyRec)?.os)} · {S((d.metadata as AnyRec)?.device_type)} · anon {S(d.anonymous_id)} · {shortTime(d.last_seen_at)}</small></div>
                ))}{!data?.devices?.length && <p className="crm-card-note">—</p>}
              </div>
            </div>
            <div className="crm-panel">
              <h4>Безопасность</h4>
              <dl className="crm-preview-list">
                {row('Риск', riskLabel(sm))}{row('Событий безопасности', securityCount)}{row('Последний IP', sm.last_ip)}{row('Активных сессий', sm.active_sessions_count)}
                {row('Ошибки входа', data?.security_summary?.failed_login_count ?? 0)}{row('Сбросы пароля', data?.security_summary?.password_reset_count ?? 0)}
                {row('Баны/разбаны', data?.security_summary?.ban_count ?? 0)}{row('Смены роли', data?.security_summary?.role_change_count ?? 0)}
                {row('Отозвано сессий', data?.security_summary?.session_revocation_count ?? 0)}{row('Подозр. IP', data?.security_summary?.suspicious_ip_count ?? 0)}
              </dl>
              <div className="crm-rows">
                {(data?.recent_security_events || []).slice(0, 5).map((e, n) => <small key={n}>{shortTime(e.created_at)} · {S(e.severity)} · {S(e.event_type)} · {S(e.ip_address)}</small>)}
              </div>
            </div>

            <nav className="crm-bottom-tabs crm-dossier-nav" aria-label="Разделы карточки пользователя">
              <button className={tab === 'overview' ? 'active' : ''} onClick={() => setTab('overview')}>Обзор</button>
              <button className={tab === 'activity' ? 'active' : ''} onClick={() => setTab('activity')}>Активность</button>
              <button className={tab === 'prompts' ? 'active' : ''} onClick={() => setTab('prompts')}>Генерации</button>
              <button className={tab === 'gallery' ? 'active' : ''} onClick={() => setTab('gallery')}>Медиатека</button>
              <button className={tab === 'payments' ? 'active' : ''} onClick={() => setTab('payments')}>Финансы</button>
              <button className={tab === 'actions' ? 'active' : ''} onClick={() => setTab('actions')}>Управление</button>
            </nav>
            {tab === 'overview' && <div className="crm-acc crm-dossier-overview">
              <section className="crm-overview-kpis crm-span-2" aria-label="Дашборд пользователя">
                <span className="revenue"><small>Принёс платформе</small><b>{moneyExact(cashEconomics.net_received_rub)}</b></span>
                <span className="cost"><small>Расход OpenRouter</small><b>{moneyExact(generationEconomics.actual_api_cost_rub)}</b></span>
                {n0(generationEconomics.unreconciled_api_jobs) > 0 && <span className="cost"><small>Не сверено с OpenRouter</small><b>{moneyExact(generationEconomics.unreconciled_api_cost_rub)}</b><em>{S(generationEconomics.unreconciled_api_jobs)} заявок после тайм-аута</em></span>}
                <span><small>Маржа до локальных расходов</small><b>{moneyExact(cashEconomics.margin_before_local_cost_rub)}</b></span>
                <span><small>Генерации</small><b>{S(totalJobs.total)}</b><em>{S(totalJobs.completed)} готово · {S(totalJobs.failed)} ошибок</em></span>
                <span><small>Изображения / видео</small><b>{S(totalJobs.images)} / {S(totalJobs.videos)}</b></span>
                <span><small>Потрачено токенов</small><b>{S(tokenEconomics.total_consumed)}</b><em>{S(tokenEconomics.main_consumed)} основных · {S(tokenEconomics.daily_consumed)} дневных</em></span>
                <span><small>Входы / устройства</small><b>{S(data?.access_summary?.successful_logins)} / {Math.max(n0(data?.access_summary?.devices), data?.client_history?.length || 0)}</b></span>
              </section>
              <section className="crm-dossier-section crm-span-2 crm-chart-section">
                <div className="crm-section-heading"><h3>Активность и генерации за 14 дней</h3><span>Москва · время онлайн, входы и генерации</span></div>
                <UserActivityChart series={activitySeries} />
              </section>
              <section className="crm-dossier-section">
                <h3>Профиль</h3>
                <dl className="crm-preview-list crm-profile-compact">
                  {row('Имя', parsedName(sm, ids))}{row('Email', sm.email)}{row('Username', sm.username)}{row('Телефон', sm.phone)}
                  {row('Создан', shortTime(sm.first_seen_at))}{row('Последний вход', shortTime(sm.last_login_at))}{row('Последняя активность', shortTime(sm.last_seen_at))}{row('Последняя генерация', shortTime(sm.last_generation_at))}
                  {row('Гео', `${S(sm.city)} / ${S(sm.country)}`)}{row('Язык / часовой пояс', `${S(sm.language_code)} / ${S(sm.timezone)}`)}{row('Тариф', sm.plan)}{row('Статус', sm.status)}
                </dl>
              </section>
              <section className="crm-dossier-section">
                <h3>Подключённые аккаунты и API</h3>
                {(ids || []).map((i, n) => <div className="crm-subrow" key={n}><span><Badge p={String(i.provider)} /> {S(i.provider_email || i.provider_username || i.phone)}</span><small>Связан {shortTime(i.linked_at)} · последний вход {shortTime(i.last_login_at)} · {i.verified_at ? 'подтверждён' : 'не подтверждён'}</small></div>)}
                {!ids?.length && <p className="crm-card-note">Подключённых внешних аккаунтов нет.</p>}
                <div className="crm-account-facts"><span><b>{S(data?.access_summary?.unique_ips)}</b> IP</span><span><b>{S(data?.access_summary?.sessions)}</b> сессий</span><span><b>{S(data?.access_summary?.failed_logins)}</b> ошибок входа</span></div>
              </section>
            </div>}
            {tab === 'activity' && <div className="crm-acc crm-activity-view">
              <div className="crm-inline-summary"><span><b>{S(data?.access_summary?.successful_logins)}</b> входов</span><span><b>{S(data?.access_summary?.failed_logins)}</b> ошибок</span><span><b>{S(data?.access_summary?.unique_ips)}</b> IP</span><span><b>{S(data?.access_summary?.sessions)}</b> сессий</span><span><b>{Math.max(n0(data?.access_summary?.devices), data?.client_history?.length || 0)}</b> устройств</span><span><b>{riskLabel(sm)}</b> риск</span></div>
              <div className="crm-subtabs" role="tablist" aria-label="Журнал активности"><button className={activityView === 'logins' ? 'active' : ''} onClick={() => setActivityView('logins')}>Входы и устройства</button><button className={activityView === 'events' ? 'active' : ''} onClick={() => setActivityView('events')}>События</button><button className={activityView === 'security' ? 'active' : ''} onClick={() => setActivityView('security')}>Безопасность</button></div>
              {historyError && <p className="crm-err crm-history-error">{historyError}</p>}
              {activityView === 'logins' && <div className="crm-activity-columns"><section className="crm-dossier-section"><h3>IP и входы</h3><div className="crm-ip-table"><div className="head"><span>IP</span><span>Первый</span><span>Последний</span><span>Набл.</span><span>Успех / ошибка</span></div>{(data?.ip_history || []).map((ip, n) => <div key={n}><code>{S(ip.ip_address)}</code><span>{shortTime(ip.first_seen_at)}</span><span>{shortTime(ip.last_seen_at)}</span><b>{S(ip.seen_count)}</b><span>{S(ip.successful_logins)} / {S(ip.failed_logins)}</span></div>)}</div></section><section className="crm-dossier-section"><h3>Браузеры и устройства</h3>{(data?.client_history || []).map((c, n) => <div className="crm-device-row" key={n}><b>{S(c.browser)} · {S(c.os)}</b><span>{S(c.device_type)} · {S(c.platform)}</span><small>{S(c.seen_count)} сессий · {shortTime(c.last_seen_at)}</small></div>)}</section><section className="crm-dossier-section crm-span-2"><h3>Попытки входа <small>{historyLoading ? 'загрузка…' : S(history?.total)}</small></h3><div className="crm-history-list">{(history?.items || []).map((x, n) => <details className={x.success === true ? 'crm-event-row ok' : 'crm-event-row failed'} key={n}><summary><b>{x.success === true ? 'Успешный вход' : 'Ошибка входа'}</b><span>{S(x.provider)} · {S(x.platform)} · <code>{S(x.ip_address)}</code></span><small>{shortTime(x.created_at)}</small></summary>{x.failure_reason ? <p>{S(x.failure_reason)}</p> : null}</details>)}</div></section></div>}
              {activityView === 'events' && <section className="crm-dossier-section"><h3>События пользователя <small>{historyLoading ? 'загрузка…' : S(history?.total)}</small></h3><div className="crm-history-list crm-event-list">{(history?.items || []).map((e, n) => <details className="crm-event-row" key={n}><summary><b>{eventLabel(e.event_name)}</b><span>{S(e.platform)} · {S(e.browser)} · {S(e.os)} · {S(e.device_type)}</span><small>{shortTime(e.created_at)} · <code>{S(e.ip_address)}</code></small></summary>{jsonSummary(e.details) !== '—' && <p>{jsonSummary(e.details)}</p>}</details>)}</div>{!historyLoading && !history?.items?.length && <p className="crm-card-note">За выбранный период событий нет.</p>}</section>}
              {activityView === 'security' && <section className="crm-dossier-section"><div className="crm-section-heading"><h3>Безопасность <small>{historyLoading ? 'загрузка…' : S(history?.total)}</small></h3><span>Только события аккаунта пользователя</span></div><p className="crm-security-note">«Истёк срок пользовательской сессии» — обычное завершение срока входа пользователя, а не ошибка вашей админ-сессии.</p><div className="crm-history-list crm-event-list">{(history?.items || []).map((e, n) => <details className={String(e.severity) === 'critical' ? 'crm-event-row failed' : 'crm-event-row'} key={n}><summary><b>{eventLabel(e.event_type)}</b><span>{S(e.severity)} · <code>{S(e.ip_address)}</code></span><small>{shortTime(e.created_at)}</small></summary>{jsonSummary(e.details) !== '—' && <p>{jsonSummary(e.details)}</p>}</details>)}</div>{!historyLoading && !history?.items?.length && <p className="crm-card-note">Подозрительных событий не зафиксировано.</p>}</section>}
              {history?.has_more && <button className="secondary crm-load-more" disabled={historyLoading} onClick={() => void loadHistory(true)}>{historyLoading ? 'Загрузка…' : `Показать ещё (${history.items?.length || 0} из ${history.total || 0})`}</button>}
            </div>}
            {tab === 'payments' && <div className="crm-acc crm-finance-view">
              <div className="crm-section-heading"><h3>Финансы и токены</h3><span>{historyLoading ? 'загрузка…' : `${S(history?.total)} операций`}</span></div>
              {historyError && <p className="crm-err crm-history-error">{historyError}</p>}
              <section className="crm-finance-kpis">
                <span><small>Основной баланс сейчас</small><b>{S(tokenEconomics.current_balance)} ток.</b></span>
                <span className="primary"><small>Потрачено основных</small><b>{S(tokenEconomics.main_consumed)} ток.</b></span>
                <span><small>Использовано дневных</small><b>{S(tokenEconomics.daily_consumed)} ток.</b></span>
                <span><small>Возвраты за ошибки</small><b>+{S(tokenEconomics.refunded)} ток.</b><em>{S(tokenEconomics.refund_entries)} операций</em></span>
                <span className="revenue"><small>Оплачено пользователем</small><b>{moneyExact(cashEconomics.paid_rub)}</b></span>
                <span><small>Чисто после возвратов</small><b>{moneyExact(cashEconomics.net_received_rub)}</b></span>
                <span className="cost"><small>Фактический OpenRouter</small><b>{moneyExact(generationEconomics.actual_api_cost_rub)}</b><em>{moneyExact(generationEconomics.actual_api_cost_usd, 'USD')}</em></span>
                <span className="cost"><small>Вероятные несверенные списания</small><b>{moneyExact(generationEconomics.unreconciled_api_cost_rub)}</b><em>{S(generationEconomics.unreconciled_api_jobs)} заявок · до {moneyExact(generationEconomics.potential_api_cost_rub)} вместе с фактическими</em></span>
                <span><small>Маржа до локальных расходов</small><b>{moneyExact(cashEconomics.margin_before_local_cost_rub)}</b></span>
                <span><small>Маржа с учётом риска</small><b>{moneyExact(cashEconomics.potential_margin_after_unreconciled_rub)}</b></span>
              </section>
              <details className="crm-summary-details"><summary>Как посчитаны токены и деньги</summary><div><span>Начислено основных: +{S(tokenEconomics.granted)}</span><span>Списано основных до возвратов: −{S(tokenEconomics.main_debited)}</span><span>Возвращено основных: +{S(tokenEconomics.main_refunded)}</span><span>Возвращено дневных: +{S(tokenEconomics.daily_refunded)}</span><span>Денежные возвраты: {moneyExact(cashEconomics.refunded_rub)}</span></div></details>
              <section className="crm-cost-note"><b>Локальная генерация</b><span>{S(generationEconomics.local_completed_jobs)} завершённых · {durationLabel(generationEconomics.local_compute_seconds)} работы. Денежная себестоимость не показывается, пока в админке не настроена цена электроэнергии и оборудования.</span></section>
              <section className="crm-dossier-section crm-finance-section"><h3>Счета и платежи</h3><div className="crm-history-list crm-finance-history">{(data?.payments_recent || []).map((item, n) => <FinanceEvent item={{ ...item, kind: 'payment' }} key={`payment-${S(item.id)}-${n}`} />)}{(data?.invoices_recent || []).map((item, n) => <FinanceEvent item={{ ...item, kind: 'invoice', code: item.invoice_code, amount: item.total_amount, tokens: item.tokens_total }} key={`invoice-${S(item.id)}-${n}`} />)}{(data?.refunds_recent || []).map((item, n) => <FinanceEvent item={{ ...item, kind: 'refund' }} key={`refund-${S(item.id)}-${n}`} />)}</div>{!data?.payments_recent?.length && !data?.invoices_recent?.length && !data?.refunds_recent?.length && <p className="crm-card-note">Счетов, оплат и возвратов пока нет.</p>}</section>
              <section className="crm-dossier-section"><h3>Полная история денег и токенов</h3><div className="crm-history-list crm-finance-history">{(history?.items || []).map((item, n) => <FinanceEvent item={item} key={`${S(item.kind)}-${S(item.id)}-${n}`} />)}</div>{!historyLoading && !history?.items?.length && <p className="crm-card-note">Финансовых операций пока нет.</p>}{history?.has_more && <button className="secondary crm-load-more" disabled={historyLoading} onClick={() => void loadHistory(true)}>{historyLoading ? 'Загрузка…' : `Показать ещё (${history.items?.length || 0} из ${history.total || 0})`}</button>}</section>
              <details className="crm-summary-details"><summary>Промокоды, бонусы и рефералы</summary><div className="crm-rows">{(data?.promo_redemptions_recent || []).map((p, n) => <small key={`lp${n}`}>Промо {S(p.promo_code)} · {S(p.status)} · +{S(p.token_bonus)} ток.</small>)}{(data?.bonus_grants_recent || []).map((b, n) => <small key={`lb${n}`}>Бонус {shortId(b.id)} · {S(b.bonus_type)} · +{S(b.token_amount)} ток.</small>)}{(data?.referral_rewards_recent || []).map((r, n) => <small key={`lw${n}`}>Реферальная награда · {S(r.status)} · +{S(r.token_amount)} ток.</small>)}{!data?.promo_redemptions_recent?.length && !data?.bonus_grants_recent?.length && !data?.referral_rewards_recent?.length && <small>Начислений нет.</small>}</div></details>
            </div>}
            {tab === 'prompts' && <div className="crm-acc crm-generations-view">
              <div className="crm-section-heading"><h3>Генерации</h3><span>{historyLoading ? 'загрузка…' : `${S(history?.total)} запусков`}</span></div>
              {historyError && <p className="crm-err crm-history-error">{historyError}</p>}
              <section className="crm-generation-kpis"><span><small>Всего</small><b>{S(totalJobs.total)}</b></span><span><small>Готово</small><b>{S(totalJobs.completed)}</b></span><span><small>Ошибки</small><b>{S(totalJobs.failed)}</b></span><span><small>Расход OpenRouter</small><b>{moneyExact(generationEconomics.actual_api_cost_rub)}</b></span><span><small>Не сверено</small><b>{moneyExact(generationEconomics.unreconciled_api_cost_rub)}</b></span><span><small>Локальное время</small><b>{durationLabel(generationEconomics.local_compute_seconds)}</b></span></section>
              <details className="crm-model-summary"><summary>Использованные модели: {S(data?.model_usage?.length || 0)}</summary><div className="crm-model-table">{(data?.model_usage || []).map((m, n) => <div key={n}><b>{S(m.model)}</b><span>{m.provider_kind === 'local' ? 'Локальная' : `API · ${S(m.provider)}`}</span><span>{S(m.total)} запусков · {S(m.completed)}/{S(m.failed)}</span><span>{S(m.net_tokens)} ток.{n0(m.actual_cost_rub) ? ` · факт ${moneyExact(m.actual_cost_rub)}` : ''}{n0(m.unreconciled_cost_rub) ? ` · не сверено ${moneyExact(m.unreconciled_cost_rub)}` : ''}</span><small>{durationLabel(m.elapsed_seconds)}</small></div>)}</div></details>
              <div className="crm-generation-list">{(history?.items || []).map((g, n) => <GenerationEvent item={g} key={`${S(g.job_id)}-${n}`} />)}</div>{history?.has_more && <button className="secondary crm-load-more" disabled={historyLoading} onClick={() => void loadHistory(true)}>{historyLoading ? 'Загрузка…' : `Показать ещё (${history.items?.length || 0} из ${history.total || 0})`}</button>}
            </div>}
            {tab === 'gallery' && <div className="crm-acc crm-media-view">
              <div className="crm-section-heading"><h3>Медиатека</h3><span>{historyLoading ? 'загрузка…' : `${S(history?.total)} материалов`}</span></div>
              <div className="crm-media-legend"><span>Результаты генераций</span><span>Загруженные исходники</span><span>Публикации в ленте отмечены на карточке</span></div>
              {historyError && <p className="crm-err crm-history-error">{historyError}</p>}
              <div className="crm-dossier-gallery">{(history?.items || []).map((media, n) => {
                const publication = (media.publication || {}) as AnyRec
                const isSource = media.type === 'source'
                return <button type="button" className={`crm-dossier-media ${isSource ? 'source' : ''}`} key={n} onClick={() => media.type === 'video' ? setSelectedVideo(media) : openImage(media)}>
                  {media.type === 'video' ? <video src={S(media.media_url)} muted preload="metadata" /> : <img src={imageUrl(media)} alt="" />}
                  <span>
                    <b>{isSource ? sourceRoleLabel(media.source_role, media.slot_index) : media.type === 'video' ? 'Видео' : 'Изображение'}{publication.status ? <em>{publicationStatusLabel(publication.status)}</em> : null}</b>
                    <small>{S(media.width)}×{S(media.height)} · {shortTime(media.created_at)}</small>
                    <small>{isSource ? `Загруженный исходник · ${S(media.source_kind)}` : `${S(media.model || media.provider)} · ${modeLabel(media.mode)}`}</small>
                    {publication.title ? <small className="feed-title">Лента: {S(publication.title)}</small> : null}
                  </span>
                </button>
              })}</div>
              {!historyLoading && !historyError && !history?.items?.length && <p className="crm-card-note">У пользователя нет доступных результатов, исходников и публикаций.</p>}
              {history?.has_more && <button className="secondary crm-load-more" disabled={historyLoading} onClick={() => void loadHistory(true)}>{historyLoading ? 'Загрузка…' : `Показать ещё (${history.items?.length || 0} из ${history.total || 0})`}</button>}
            </div>}
          </div>

          <aside className={`crm-card-actions ${tab === 'actions' ? 'is-open' : ''}`}>
            <div className="crm-management-head"><h4>Управление пользователем</h4><p>{adminReady ? 'Причина обязательна; каждое изменение записывается в аудит.' : 'Войдите как администратор, чтобы менять аккаунт.'}</p></div>
            <div className="crm-action-group compact"><strong>Токены</strong><small>Основной баланс: {S(tokenEconomics.current_balance)} ток.</small><div className="crm-quick"><button className="secondary crm-supported-action" disabled={!adminReady} title={adminReady ? undefined : 'Войдите как админ'} onClick={() => adminReady && setAct({ kind: 'tokens', preset: '50' })}>+50</button><button className="secondary crm-supported-action" disabled={!adminReady} title={adminReady ? undefined : 'Войдите как админ'} onClick={() => adminReady && setAct({ kind: 'tokens', preset: '-50' })}>−50</button>{actionButton('tokens', 'Своя сумма')}</div></div>
            <div className="crm-action-group"><strong>Тариф и оплаты</strong><small>{S(sm.plan)} · оплачено {moneyExact(cashEconomics.paid_rub)}</small><div className="crm-action-grid">{actionButton('plan', 'Изменить тариф')}<button className="secondary crm-supported-action" disabled={!adminReady} title={adminReady ? undefined : 'Войдите как админ'} onClick={() => adminReady && setAct({ kind: 'invoice', preset: '0' })}>Выставить счёт</button><button className="secondary crm-supported-action" disabled={!adminReady || !unpaidInvoice} onClick={() => adminReady && unpaidInvoice && setAct({ kind: 'mark_paid', preset: S(unpaidInvoice.total_amount), context: unpaidInvoice })}>Отметить оплату</button><button className="secondary danger crm-supported-action" disabled={!adminReady || !refundablePayment} onClick={() => adminReady && refundablePayment && setAct({ kind: 'refund', preset: S(refundablePayment.amount), context: refundablePayment })}>Возврат</button><button className="secondary danger crm-supported-action" disabled={!adminReady || !unpaidInvoice} onClick={() => adminReady && unpaidInvoice && setAct({ kind: 'cancel_invoice', context: unpaidInvoice })}>Отменить счёт</button></div></div>
            <div className="crm-action-group"><strong>Скидки и бонусы</strong><small>Скидка: {S(data?.billing_summary?.personal_discount_percent || 0)}%</small><div className="crm-action-grid"><button className="secondary crm-supported-action" disabled={!adminReady} title={adminReady ? undefined : 'Войдите как админ'} onClick={() => adminReady && setAct({ kind: 'discount', preset: S(data?.billing_summary?.personal_discount_percent || 0) })}>Скидка</button><button className="secondary crm-supported-action" disabled={!adminReady} title={adminReady ? undefined : 'Войдите как админ'} onClick={() => adminReady && setAct({ kind: 'bonus', preset: '100' })}>Бонус</button><button className="secondary crm-supported-action" disabled={!adminReady} title={adminReady ? undefined : 'Войдите как админ'} onClick={() => adminReady && setAct({ kind: 'promo' })}>Промокод</button><button className="secondary crm-supported-action" disabled={!adminReady} title={adminReady ? undefined : 'Войдите как админ'} onClick={() => adminReady && setAct({ kind: 'referral_reward', preset: '100' })}>Реферал</button><button className="secondary danger crm-supported-action" disabled={!adminReady || !cancellableBonus} onClick={() => adminReady && cancellableBonus && setAct({ kind: 'cancel_bonus', context: cancellableBonus })}>Отменить бонус</button></div></div>
            <div className="crm-action-group"><strong>Доступ и безопасность</strong><small>{isBanned ? 'Аккаунт заблокирован' : 'Аккаунт активен'}</small><div className="crm-action-grid">{actionButton(isBanned ? 'unban' : 'ban', isBanned ? 'Разбанить' : 'Заблокировать', undefined, !isBanned)}{actionButton('reset', 'Новый пароль', undefined, true)}</div></div>
            <div className="crm-action-group"><strong>Профиль и роль</strong><small>{S(sm.role)} · {S(sm.status)}</small><div className="crm-action-grid">{actionButton('profile', 'Изменить профиль')}{actionButton('role', isAdmin ? 'Снять админа' : 'Сделать админом')}<button className="secondary danger crm-supported-action" disabled={!adminReady || isAdmin || isBanned} onClick={() => adminReady && setAct({ kind: 'deactivate' })}>Деактивировать</button>{disabledAction('Анонимизировать')}</div></div>
          </aside>
        </div>

        {act && <ActionConfirm target={merged} kind={act.kind} preset={act.preset} context={act.context} onClose={() => setAct(null)} onDone={() => { setReloadKey((k) => k + 1); onChanged?.() }} />}
        {selectedImage && (
          <div className="crm-image-modal" onClick={() => setSelectedImage(null)}>
            <div className="crm-image-dialog" role="dialog" aria-label="Изображение пользователя" onClick={(e) => e.stopPropagation()}>
              <div className="crm-image-head">
                <strong>{selectedImage.type === 'source' ? 'Загруженный исходник' : 'Изображение пользователя'}</strong>
                <button className="auth-modal-close" aria-label="Закрыть" onClick={() => setSelectedImage(null)}>×</button>
              </div>
              <div className="crm-image-body">
                <div className="crm-image-frame">{fullImageUrl(selectedImage) ? <img src={fullImageUrl(selectedImage)} alt="" /> : <span>Нет превью</span>}</div>
                <aside className="crm-image-side">
                  <dl className="crm-preview-list">
                    {row('Режим', selectedImage.type === 'source' ? sourceRoleLabel(selectedImage.source_role, selectedImage.slot_index) : modeLabel(selectedImage.mode))}{row('Модель', selectedImage.model || selectedImage.provider)}{row('Создано', shortTime(selectedImage.created_at))}
                    {row('Image', selectedImage.id)}{row('Job', selectedImage.job_id)}{row('Избранное', selectedImage.favorite ? 'да' : 'нет')}
                  </dl>
                  <div className="crm-image-prompt">
                    <strong>Промпт</strong>
                    <p>{S(selectedImage.prompt || 'Промпт не сохранён')}</p>
                  </div>
                  {selectedImage.type !== 'source' && <div className="crm-image-danger">
                    <strong>Удаление из галереи</strong>
                    <p className="crm-card-note">Картинка будет скрыта у пользователя, действие попадёт в audit log.</p>
                    <input value={deleteReason} onChange={(e) => setDeleteReason(e.target.value)} placeholder="Причина удаления" />
                    <button className="secondary danger crm-supported-action" disabled={!adminReady || deleteBusy || !deleteReason.trim()} onClick={() => void deleteGalleryImage()}>{deleteBusy ? 'Удаляю…' : 'Удалить изображение'}</button>
                    {deleteMsg && <p className="crm-err">{deleteMsg}</p>}
                  </div>}
                </aside>
              </div>
            </div>
          </div>
        )}
        {selectedVideo && (
          <div className="crm-image-modal" onClick={() => setSelectedVideo(null)}>
            <div className="crm-image-dialog crm-video-dialog" role="dialog" aria-label="Видео пользователя" onClick={(e) => e.stopPropagation()}>
              <div className="crm-image-head">
                <strong>Видео пользователя</strong>
                <button className="auth-modal-close" aria-label="Закрыть" onClick={() => setSelectedVideo(null)}>×</button>
              </div>
              <div className="crm-image-body">
                <div className="crm-image-frame"><video src={S(selectedVideo.media_url)} controls autoPlay playsInline /></div>
                <aside className="crm-image-side">
                  <dl className="crm-preview-list">
                    {row('Режим', modeLabel(selectedVideo.mode))}{row('Модель', selectedVideo.model || selectedVideo.provider)}{row('Создано', shortTime(selectedVideo.created_at))}
                    {row('Размер', `${S(selectedVideo.width)} × ${S(selectedVideo.height)}`)}{row('Длительность', `${S(selectedVideo.duration_seconds)} сек.`)}{row('Файл', `${Math.round(n0(selectedVideo.stored_bytes) / 1048576)} МБ`)}
                  </dl>
                  <div className="crm-image-prompt"><strong>Промпт</strong><p>{S(selectedVideo.prompt || 'Промпт не сохранён')}</p></div>
                </aside>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// Block 2 — admin environment diagnostics (collapsed unless there is an auth/env problem).
function AdminDiagnostics(): ReactElement {
  const [d, setD] = useState<{ authed: boolean; backend?: AnyRec | null; probed: boolean }>({ authed: false, probed: false })
  useEffect(() => { void (async () => { const r = await adminGet<AnyRec>('/admin/diagnostics-v2'); setD({ authed: Boolean(r?.ok), backend: r, probed: true }) })() }, [])
  const authMode = d.authed ? 'trusted cookie session (admin)' : 'НЕТ trusted-сессии — CRM будет пустым (войдите как админ)'
  return (
    <details className="crm-diag" open={d.probed && !d.authed}>
      <summary>Диагностика среды · {IS_PROD ? 'PRODUCTION/PREVIEW' : 'DEV'} · {d.authed ? 'admin ✓' : 'нет admin-сессии'}</summary>
      <div className="crm-diag-grid">
        <span>Сборка фронта</span><b>{APP_BUILD_LABEL}</b><span>Бэкенд</span><b>{S(d.backend?.backend_build)}</b>
        <span>API base</span><b>{API}</b><span>Origin</span><b>{typeof window !== 'undefined' ? window.location.origin : '—'}</b>
        <span>Режим Vite</span><b>{MODE}{IS_PROD ? ' (prod)' : ' (dev)'}</b>
        <span>Авторизация</span><b className={d.authed ? 'status-active' : 'status-banned'}>{authMode}</b>
        <span>База данных</span><b>{S(d.backend?.db_file)}</b><span>Пользователей в БД</span><b>{S(d.backend?.user_count)}</b>
      </div>
    </details>
  )
}

function RowActionMenu({ u, onAct, onCard }: {
  u: CrmUserRow; onAct: (kind: ActKind, preset?: string) => void; onCard: () => void
}): ReactElement {
  const banned = u.status === 'banned'
  const admin = u.role === 'admin'
  const stop = (e: ReactMouseEvent) => e.stopPropagation()
  const run = (e: ReactMouseEvent, f: () => void) => { e.stopPropagation(); f() }
  return (
    <details className="crm-row-menu" onClick={stop}>
      <summary onClick={stop}>Действия</summary>
      <div className="crm-row-menu-pop">
        <strong>Профиль</strong>
        <button onClick={(e) => run(e, onCard)}>Карточка клиента</button>
        <button onClick={(e) => run(e, () => onAct('profile'))}>Редактировать профиль</button>
        <strong>Управление</strong>
        <button onClick={(e) => run(e, () => onAct('plan'))}>Изменить тариф</button>
        <button disabled title={deferred}>Выставить счёт</button>
        <button disabled title={deferred}>Начислить бонус</button>
        <button disabled title={deferred}>Применить промокод</button>
        <strong>Безопасность</strong>
        <button className={banned ? '' : 'danger'} onClick={(e) => run(e, () => onAct(banned ? 'unban' : 'ban'))}>Бан/Разбан</button>
        <button className="danger" onClick={(e) => run(e, () => onAct('reset'))}>Сбросить пароль</button>
        <button onClick={(e) => run(e, () => onAct('role'))}>{admin ? 'Снять админа' : 'Сделать админом'}</button>
        <strong>Прочее</strong>
        <button className="danger" onClick={(e) => run(e, () => onAct('deactivate'))}>Отключить пользователя</button>
      </div>
    </details>
  )
}

function CrmSettingsScaffold({ onClose }: { onClose: () => void }): ReactElement {
  const [compact, setCompact] = useState(true)
  const [stickyCard, setStickyCard] = useState(true)
  const [hideSensitive, setHideSensitive] = useState(true)
  const [auditHints, setAuditHints] = useState(true)
  return (
    <section className="crm-settings">
      <div className="crm-settings-head">
        <h4>Настройки CRM</h4>
        <span>Локально, без legacy settings endpoint</span>
        <button className="mini" onClick={onClose}>Закрыть</button>
      </div>
      <div className="crm-settings-grid">
        <label><span>Колонки списка</span><select defaultValue="operator"><option value="operator">Операторские 11 колонок</option><option value="compact">Компактный набор</option></select></label>
        <label><span>Карточка клиента</span><select value={stickyCard ? 'sticky' : 'plain'} onChange={(e) => setStickyCard(e.target.value === 'sticky')}><option value="sticky">Sticky действия справа</option><option value="plain">Обычная прокрутка</option></select></label>
        <label><span>Уровни админки</span><select defaultValue="trusted"><option value="trusted">Trusted v2 actions only</option><option value="view">Только просмотр</option></select></label>
        <label><span>Адаптивность</span><select value={compact ? 'dense' : 'roomy'} onChange={(e) => setCompact(e.target.value === 'dense')}><option value="dense">Плотная таблица</option><option value="roomy">Больше воздуха</option></select></label>
        <label><span>Чувствительные данные</span><select value={hideSensitive ? 'masked' : 'visible'} onChange={(e) => setHideSensitive(e.target.value === 'masked')}><option value="masked">Маскировать/не показывать</option><option value="visible">Показывать доступное</option></select></label>
        <label><span>Логи и аудит</span><select value={auditHints ? 'notice' : 'minimal'} onChange={(e) => setAuditHints(e.target.value === 'notice')}><option value="notice">Показывать audit notice</option><option value="minimal">Минимально</option></select></label>
      </div>
    </section>
  )
}

export function AdminAnalyticsV2(): ReactElement {
  const [dash, setDash] = useState<Dash['dashboard'] | null>(null)
  const [users, setUsers] = useState<CrmUserRow[]>([])
  const [q, setQ] = useState('')
  const [source, setSource] = useState<'all' | 'web_email' | 'telegram' | 'max'>('all')
  const [statusFilter, setStatusFilter] = useState<'all' | 'active' | 'banned' | 'admin'>('all')
  const [groupFilter, setGroupFilter] = useState<'all' | 'customer' | 'admin' | 'demo'>('all')
  const [sort, setSort] = useState<UserSort>('recent')
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [card, setCard] = useState<CrmUserRow | null>(null)
  const [rowAct, setRowAct] = useState<{ u: CrmUserRow; kind: ActKind; preset?: string } | null>(null)
  const [settingsOpen, setSettingsOpen] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setLoadError('')
    const params = new URLSearchParams({ limit: '100', sort })
    if (q.trim()) params.set('q', q.trim())
    if (source !== 'all') params.set('provider', source)
    if (statusFilter === 'active' || statusFilter === 'banned') params.set('status', statusFilter)
    if (statusFilter === 'admin') params.set('group', 'admin')
    if (groupFilter !== 'all') params.set('group', groupFilter)
    const [d, u] = await Promise.all([
      adminGet<Dash>('/admin/dashboard-v2'),
      adminGet<{ items: CrmUserRow[] }>(`/admin/users-analytics-v2?${params.toString()}`),
    ])
    setDash(d?.dashboard ?? null)
    setUsers(Array.isArray(u?.items) ? u.items : [])
    if (!d || !u) setLoadError('CRM не загрузилась. Проверьте админскую сессию и повторите запрос.')
    setLoading(false)
  }, [q, source, statusFilter, groupFilter, sort])
  useEffect(() => {
    const id = window.setTimeout(() => { void load() }, 0)
    return () => window.clearTimeout(id)
  }, [load])

  const byProvider = (dash?.users_by_provider as Record<string, number>) || {}
  const dashPeriods = (dash?.periods || {}) as AnyRec
  const dashToday = (dashPeriods.today || {}) as AnyRec
  const dashTodayJobs = (dashToday.generations || {}) as AnyRec
  const dashTodayTokens = (dashToday.tokens || {}) as AnyRec
  const sortHead = (label: string, asc: UserSort, desc: UserSort): ReactElement => {
    const active = sort === asc || sort === desc
    const next = sort === asc ? desc : asc
    const arrow = sort === asc ? '↑' : sort === desc ? '↓' : '↕'
    return <button type="button" className={active ? 'crm-sort-head active' : 'crm-sort-head'} onClick={() => setSort(next)}>{label} <span>{arrow}</span></button>
  }
  const groupedUsers = groupFilter === 'all'
    ? [
        { key: 'customer', label: 'Клиенты', items: users.filter((u) => (u.account_group || 'customer') === 'customer') },
        { key: 'admin', label: 'Администраторы', items: users.filter((u) => u.account_group === 'admin') },
        { key: 'demo', label: 'Демо-пользователи', items: users.filter((u) => u.account_group === 'demo') },
      ].filter((g) => g.items.length)
    : [{ key: groupFilter, label: groupFilter === 'customer' ? 'Клиенты' : groupFilter === 'admin' ? 'Администраторы' : 'Демо-пользователи', items: users }]

  return (
    <section className="admin-analytics">
      <div className="crm-head"><h3>Пользователи</h3><p className="crm-sub">Операторская CRM: входы, источники, активность и трасты-действия в строке.</p></div>
      <AdminDiagnostics />
      <div className="crm-summary-grid">
        <div className="crm-summary"><span>Аудитория</span><strong>{S(dash?.total_users)}</strong><small>{S(dash?.active_7d)} активны за 7 дней</small></div>
        <div className="crm-summary"><span>Сейчас</span><strong>{S(dash?.active_today)}</strong><small>{S(dash?.sessions_active)} активных сессий</small></div>
        <div className="crm-summary"><span>Генерации сегодня</span><strong>{S(dashTodayJobs.total ?? dash?.generations_today)}</strong><small>{S(dashTodayJobs.images)} изображений · {S(dashTodayJobs.videos)} видео</small></div>
        <div className="crm-summary"><span>Токены сегодня</span><strong>{S(dashTodayTokens.total)}</strong><small>{S(dashTodayTokens.daily)} дневных · {S(dashTodayTokens.main)} основных</small></div>
        <div className="crm-summary crm-summary-sources"><span>Источники</span><strong>Web {byProvider.web_email ?? 0}</strong><small>TG {byProvider.telegram ?? 0} · MAX {byProvider.max ?? 0}</small></div>
        <div className={n0(dash?.failed_logins_24h) ? 'crm-summary risk' : 'crm-summary'}><span>Контроль</span><strong>{S(dash?.failed_logins_24h)}</strong><small>ошибок входа за 24 часа</small></div>
      </div>
      <div className="analytics-search">
        <input placeholder="Код, имя, email, телефон или username" value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') void load() }} />
        <select value={source} onChange={(e) => setSource(e.target.value as typeof source)}><option value="all">Все источники</option><option value="web_email">Web</option><option value="telegram">Telegram</option><option value="max">MAX</option></select>
        <select value={groupFilter} onChange={(e) => setGroupFilter(e.target.value as typeof groupFilter)}><option value="all">Все группы</option><option value="customer">Клиенты</option><option value="admin">Админы</option><option value="demo">Демо</option></select>
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value as typeof statusFilter)}><option value="all">Все статусы</option><option value="active">Активные</option><option value="banned">Забанены</option></select>
        <select value={sort} onChange={(e) => setSort(e.target.value as UserSort)} aria-label="Сортировка пользователей"><option value="recent">Сначала активные</option><option value="created_desc">Новые регистрации</option><option value="created_asc">Старые регистрации</option><option value="generations_desc">Больше генераций</option><option value="tokens_desc">Больше списаний</option><option value="balance_desc">Больше баланс</option><option value="balance_asc">Меньше баланс</option><option value="code_asc">Код пользователя</option><option value="plan_asc">Тариф</option></select>
        <button className="secondary" onClick={() => void load()}>Найти</button>
      </div>
      <div className="crm-viewbar">
        <button className="secondary crm-settings-toggle" aria-expanded={settingsOpen} onClick={() => setSettingsOpen((v) => !v)}>Вид и колонки</button>
      </div>
      {settingsOpen && <CrmSettingsScaffold onClose={() => setSettingsOpen(false)} />}
      {loadError && <div className="crm-load-error"><span>{loadError}</span><button className="secondary" onClick={() => void load()}>Повторить</button></div>}
      {loading ? <p>Загрузка…</p> : !loadError && (
        <div className="analytics-table dense">
          <div className="analytics-row analytics-head">
            <span>{sortHead('Клиент', 'name_asc', 'name_desc')}</span><span>{sortHead('Активность', 'activity_asc', 'recent')}</span><span>{sortHead('Источник', 'source_asc', 'source_desc')}</span><span>{sortHead('Контакты', 'contact_asc', 'contact_desc')}</span><span>{sortHead('Тариф', 'plan_asc', 'plan_desc')}</span><span>{sortHead('Использование', 'generations_asc', 'generations_desc')}</span><span>Устройство</span><span>Действия</span>
          </div>
          {groupedUsers.map((section) => <div className="crm-group-block" key={section.key}>
            <div className="crm-group-title"><strong>{section.label}</strong><span>{section.items.length}</span></div>
          {section.items.map((u) => {
            const sourceList = u.providers?.length ? u.providers : u.primary_provider ? [u.primary_provider] : []
            const active = activityKind(u)
            const metrics = (u.period_metrics || {}) as AnyRec
            const generationMetrics = (metrics.generations || {}) as AnyRec
            const todayMetrics = (generationMetrics.today || {}) as AnyRec
            const yesterdayMetrics = (generationMetrics.yesterday || {}) as AnyRec
            const totalMetrics = (generationMetrics.total || {}) as AnyRec
            const openCard = () => setCard(u)
            const stop = (e: ReactMouseEvent) => e.stopPropagation()
            const rowKey = (e: ReactKeyboardEvent<HTMLDivElement>) => {
              if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openCard() }
            }
            return (
              <div key={u.public_user_code || u.internal_user_id_short} className={`analytics-row crm-row activity-${active}`} role="button" tabIndex={0} aria-label={`Открыть карточку ${u.display_name || u.username || u.public_user_code}`} onClick={openCard} onKeyDown={rowKey}>
                <span className="crm-client-cell"><AvatarMark u={u as CrmUserRow & AnyRec} className={`crm-avatar crm-row-avatar activity-${active}`} /><span><span className="crm-client-line"><strong>{u.display_name || u.username || u.public_user_code}</strong><em className="crm-chip">{u.account_group === 'demo' ? 'demo' : u.role === 'admin' ? 'admin' : 'client'}</em></span><span className="crm-client-line"><small>{u.public_user_code}</small><em className="crm-chip plan">{u.plan || 'mini'}</em></span></span></span>
                <span><small><i className={`crm-dot activity-${active}`} />{ACTIVITY_LABEL[active]}</small><small>вход: {shortTime(u.last_login_at)}</small><small>генерация: {shortTime(u.last_generation_at)}</small></span>
                <span>{sourceList.map((p) => <Badge key={p} p={p} />)}<small>{u.last_ip || 'IP —'}</small></span>
                <span className="crm-contact-cell"><small>{u.email || '—'}</small><small>{u.username ? `@${u.username}` : 'username —'}</small><small>{u.phone || genderAgeLabel(u as CrmUserRow & AnyRec)}</small></span>
                <span><strong>{u.plan || 'mini'}</strong><small>дневные {n0(u.daily_tokens_used)} / {n0(u.daily_tokens_limit)}</small><small>основной баланс {n0(u.main_token_balance ?? u.token_balance)}</small></span>
                <span><strong>сегодня {n0(todayMetrics.total)} · вчера {n0(yesterdayMetrics.total)}</strong><small>всего {n0(totalMetrics.total ?? u.generations_count)} · ошибок {n0(totalMetrics.failed)}</small><small>изображения {n0(totalMetrics.images)} · видео {n0(totalMetrics.videos)}</small></span>
                <span><small>{deviceLabel(u)}</small><small>{u.device_count ?? 0} устр.</small></span>
                <span className="crm-row-actions">
                  <button className="mini" onClick={(e) => { stop(e); setCard(u) }}>Карточка</button>
                  <RowActionMenu u={u} onCard={() => setCard(u)} onAct={(kind, preset) => setRowAct({ u, kind, preset })} />
                </span>
              </div>
            )
          })}
          </div>)}
          {users.length === 0 && <p>Пользователи не найдены.</p>}
        </div>
      )}
      {card && <UserCard u={card} onClose={() => setCard(null)} onChanged={() => void load()} />}
      {rowAct && <ActionConfirm target={rowAct.u} kind={rowAct.kind} preset={rowAct.preset} onClose={() => setRowAct(null)} onDone={() => void load()} />}
    </section>
  )
}
