// Phase 20A–20C.4: Users CRM — an operator console. Cookie auth only
// (credentials:include), never the legacy identity header. Dense table with trusted
// quick actions in every row + a compact two-column user card (actions above the fold).
// Every risky action requires a reason and is written to audit_logs. No tokens/hashes
// are ever requested or shown.
import { useCallback, useEffect, useState } from 'react'
import type { KeyboardEvent as ReactKeyboardEvent, MouseEvent as ReactMouseEvent, ReactElement } from 'react'
import { APP_BUILD_LABEL } from './diagMeta'

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

interface Dash { dashboard?: Record<string, number | Record<string, number>> }
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
  first_seen_at?: string | null; gallery_count?: number; marketing_source?: string | null; risk_level?: string | null
  gallery_access?: boolean; gallery_enabled?: boolean
  daily_tokens?: number; gallery_slots?: number; gallery_used?: number; gallery_free?: number; gallery_full?: boolean
  last_device?: { browser?: string | null; os?: string | null } | null
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
const shortId = (v: unknown, n = 8): string => { const s = v == null ? '' : String(v); return s ? s.slice(0, n) + (s.length > n ? '…' : '') : '—' }
const n0 = (v: unknown): number => (typeof v === 'number' && Number.isFinite(v) ? v : 0)
const deferred = 'Отложено: backend v2 пока не отдаёт эти данные.'
type ActivityKind = 'online' | 'today' | 'week' | 'month' | 'cold'
type UserSort = 'recent' | 'created_desc' | 'created_asc' | 'generations_desc' | 'tokens_desc' | 'balance_desc' | 'balance_asc' | 'code_asc' | 'plan_asc'
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
  return browser || os ? `${S(browser)} / ${S(os)} · MAC: недоступен` : 'MAC: недоступен'
}

function quotaLabel(u: CrmUserRow & AnyRec): string {
  const used = Number(u.gallery_used ?? u.gallery_count ?? 0)
  const total = Number(u.gallery_slots ?? 0)
  return `${used}/${total}`
}

function tokenLine(u: CrmUserRow): string {
  return `${n0(u.generations_count)} / ${n0(u.daily_tokens_used)} / ${n0(u.token_balance)} / ${n0(u.daily_tokens_limit)}`
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
  recent_generations?: AnyRec[]; recent_gallery?: AnyRec[]; token_ledger_recent?: AnyRec[]
  billing_summary?: AnyRec; invoices_recent?: AnyRec[]; payments_recent?: AnyRec[]; refunds_recent?: AnyRec[]
  loyalty_summary?: AnyRec; promo_redemptions_recent?: AnyRec[]; bonus_grants_recent?: AnyRec[]
  referral_link?: AnyRec; referral_relations?: AnyRec[]; referral_rewards_recent?: AnyRec[]
  security_summary?: AnyRec
  token_summary?: { spent?: number; entries?: number; balance?: number }
}

// --- Shared trusted-action confirm (compact popover, reason-gated, audited). ---
type ActKind = 'tokens' | 'role' | 'plan' | 'profile' | 'ban' | 'unban' | 'reset' | 'deactivate' | 'invoice' | 'mark_paid' | 'refund' | 'cancel_invoice' | 'bonus' | 'cancel_bonus' | 'promo' | 'referral_reward'
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
    tokens: 'Изменить токены', role: isAdmin ? 'Снять админа' : 'Сделать админом', plan: 'Изменить тариф',
    profile: 'Изменить профиль', ban: 'Забанить / отключить', unban: 'Разбанить', reset: 'Сбросить пароль', deactivate: 'Деактивировать',
    invoice: 'Выставить счёт', mark_paid: 'Отметить оплату', refund: 'Возврат', cancel_invoice: 'Отменить счёт',
    bonus: 'Начислить бонус', cancel_bonus: 'Отменить бонус', promo: 'Применить промокод', referral_reward: 'Реферальная корректировка',
  }
  const danger = kind === 'ban' || kind === 'deactivate' || kind === 'reset' || kind === 'refund' || kind === 'cancel_invoice' || kind === 'cancel_bonus' || (kind === 'role' && isAdmin)
  const changePreview = kind === 'tokens' ? `${Number(value) > 0 ? '+' : ''}${value || '—'} токенов`
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
        {kind === 'invoice' && <><label>Сумма счёта, ₽<input value={value} onChange={(e) => setValue(e.target.value)} inputMode="numeric" placeholder="например 1250" /></label><label>Токены к начислению после оплаты<input value={tokens} onChange={(e) => setTokens(e.target.value)} inputMode="numeric" placeholder="например 500" /></label></>}
        {(kind === 'mark_paid' || kind === 'refund') && <label>Сумма<input value={value} onChange={(e) => setValue(e.target.value)} inputMode="numeric" placeholder={S(context?.total_amount || context?.amount)} /></label>}
        {kind === 'bonus' && <label>Тип бонуса<select value={bonusType} onChange={(e) => setBonusType(e.target.value)}><option value="manual">manual</option><option value="compensation">compensation</option><option value="campaign">campaign</option><option value="referral">referral</option></select></label>}
        {(kind === 'bonus' || kind === 'referral_reward') && <label>Токены<input value={value} onChange={(e) => setValue(e.target.value)} inputMode="numeric" placeholder="например 100" /></label>}
        {kind === 'promo' && <label>Промокод<input value={value} onChange={(e) => setValue(e.target.value)} autoComplete="off" placeholder="WELCOME" /></label>}
        {kind === 'plan' && <label>Тариф<select value={value} onChange={(e) => setValue(e.target.value)}><option value="">Выбрать…</option><option value="free">free</option><option value="mini">mini</option><option value="plus">plus</option><option value="pro">pro</option></select></label>}
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
  const [tab, setTab] = useState<'logs' | 'payments' | 'loyalty' | 'prompts' | 'gallery' | 'tech'>('logs')
  const [selectedImage, setSelectedImage] = useState<AnyRec | null>(null)
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
  const imageUrl = (img: AnyRec) => String(img.image_url || img.thumbnail_url || img.result_image_url || '')
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

  return (
    <div className="crm-card-overlay" onClick={onClose}>
      <div className="crm-card" role="dialog" aria-label="Карточка пользователя" onClick={(e) => e.stopPropagation()}>
        <header className="crm-card-header">
          <div className="crm-card-hero">
            <div className="crm-card-id crm-card-id-rich">
              <AvatarMark u={sm} ids={ids} className={`crm-avatar activity-${active} ${isBanned ? 'risk' : ''}`} />
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
                </div>
                <div className="crm-preview-badges">{((sm.providers as string[]) || u.providers || []).map((p) => <Badge key={p} p={p} />)}</div>
                <div className="crm-activity-legend">
                  <span className={`crm-dot activity-${active}`} />{ACTIVITY_LABEL[active]}
                  <span className="crm-dot activity-online" />Онлайн
                  <span className="crm-dot activity-today" />Сегодня
                  <span className="crm-dot activity-week" />Неделя
                  <span className="crm-dot activity-cold" />Нет генераций
                </div>
              </div>
            </div>
            <div className="crm-card-top-actions">
              <button className="secondary crm-card-icon-action" title="Копировать код" onClick={() => navigator.clipboard?.writeText(S(sm.public_user_code)).catch(() => undefined)}>□</button>
              <button className="secondary" onClick={() => setTab('tech')}>Открыть профиль</button>
              <button className="auth-modal-close" aria-label="Закрыть" onClick={onClose}>×</button>
            </div>
          </div>
          <div className="crm-card-kpis">
            <span>Баланс <b>{S(sm.token_balance)}</b></span><span>Списано <b>{S(sm.tokens_spent)}</b></span>
            <span>Генераций <b>{S(sm.generations_count)}</b></span><span>Галерея <b>{quotaLabel(sm)}</b></span>
            <span>Вход {shortTime(sm.last_seen_at)}</span><span>Создан {shortTime(sm.first_seen_at)}</span><span>Риск <b>{riskLabel(sm)}</b></span>
          </div>
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
                  <span><Badge p={String(i.provider)} /> {nm ? `${nm} · ` : ''}@{S(i.provider_username)} · {S(i.provider_email)} · id {shortId(i.provider_user_id, 6)}</span>
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
                  <button type="button" className="crm-panel-link" onClick={() => setTab('gallery')}>Галерея</button>
                </div>
              </div>
              <dl className="crm-preview-list crm-content-stats">
                {row('Генерации', sm.generations_count)}{row('Промпты', recentGenerations.length)}{row('Галерея', quotaLabel(sm))}{row('Последний контент', shortTime(recentGenerations[0]?.created_at || recentGallery[0]?.created_at))}
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
                <div className="crm-gallery-preview" aria-label="Последние изображения пользователя">
                  {recentGallery.slice(0, 6).map((img, n) => (
                    <button type="button" className="crm-gallery-thumb" key={n} onClick={() => openImage(img)} title={S(img.prompt)}>
                      {imageUrl(img) ? <img src={imageUrl(img)} alt="" /> : <span className="crm-gallery-empty">Нет превью</span>}
                      <small>{S(img.mode)} · {shortTime(img.created_at)}</small>
                    </button>
                  ))}
                  {!recentGallery.length && <p className="crm-card-note">В галерее нет доступных миниатюр.</p>}
                </div>
              </div>
            </div>
            <div className="crm-panel">
              <h4>Финансы и токены</h4>
              <dl className="crm-preview-list">
                {row('Баланс токенов', data?.token_summary?.balance ?? sm.token_balance)}{row('Потрачено токенов', data?.token_summary?.spent ?? sm.tokens_spent)}
                {row('Операций ledger', data?.token_summary?.entries ?? 0)}
                {row('Счетов', data?.billing_summary?.invoice_count ?? 0)}{row('Неоплачено', data?.billing_summary?.unpaid_count ?? 0)}
                {row('Оплачено', money(data?.billing_summary?.total_paid))}{row('Возвраты', money(data?.billing_summary?.total_refunded))}
                {row('Бонусы', data?.loyalty_summary?.bonus_count ?? 0)}
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
                  <div className="crm-subrow" key={n}><small><strong>{S(s.platform)}</strong> · {S(s.ip_address)} {s.revoked_at ? '· отозв.' : '· активна'}</small><small>{S((s.device as AnyRec)?.browser)}/{S((s.device as AnyRec)?.os)} · {S((s.device as AnyRec)?.device_type)} · {S((s.device as AnyRec)?.app_build)} · {S((s.device as AnyRec)?.mac_status)}</small></div>
                ))}{!data?.sessions?.length && <p className="crm-card-note">—</p>}
              </div>
              <div className="crm-panel">
                <h4>MAC: недоступен</h4>
                {(data?.devices || []).slice(0, 6).map((d, n) => (
                  <div className="crm-subrow" key={n}><small><strong>{S(d.platform)}</strong> · inst {S(d.installation_id)}</small><small>{S((d.metadata as AnyRec)?.browser)}/{S((d.metadata as AnyRec)?.os)} · anon {S(d.anonymous_id)} · {S(d.mac_status)} · {shortTime(d.last_seen_at)}</small></div>
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

            <div className="crm-bottom-tabs">
              <button className={tab === 'logs' ? 'active' : ''} onClick={() => setTab('logs')}>Логи</button>
              <button className={tab === 'payments' ? 'active' : ''} onClick={() => setTab('payments')}>Платежи</button>
              <button className={tab === 'loyalty' ? 'active' : ''} onClick={() => setTab('loyalty')}>Лояльность</button>
              <button className={tab === 'prompts' ? 'active' : ''} onClick={() => setTab('prompts')}>Промпты</button>
              <button className={tab === 'gallery' ? 'active' : ''} onClick={() => setTab('gallery')}>Галерея</button>
              <button className={tab === 'tech' ? 'active' : ''} onClick={() => setTab('tech')}>Техническое</button>
            </div>
            {tab === 'logs' && <div className="crm-acc">
              <strong>Логи ({(data?.recent_events?.length || 0) + (data?.recent_security_events?.length || 0) + (data?.admin_actions?.length || 0)})</strong>
              <div className="crm-rows">
                {(data?.recent_events || []).slice(0, 10).map((e, n) => <small key={`e${n}`}>{shortTime(e.created_at)} · {S(e.event_name)} · {S(e.platform)}</small>)}
                {(data?.recent_security_events || []).slice(0, 10).map((e, n) => <small key={`s${n}`}>⚠ {shortTime(e.created_at)} · {S(e.severity)} · {S(e.event_type)} · {S(e.ip_address)}</small>)}
                {(data?.admin_actions || []).slice(0, 10).map((e, n) => <small key={`a${n}`}>★ {shortTime(e.created_at)} · {S(e.action)} · {S(e.actor)}</small>)}
              </div>
            </div>}
            {tab === 'payments' && <div className="crm-acc"><strong>Финансы</strong><div className="crm-rows">
              {(data?.invoices_recent || []).map((i, n) => <small key={`ti${n}`}>Счёт {S(i.invoice_code)} · {S(i.status)} · {money(i.total_amount, S(i.currency))} · {S(i.tokens_total)} ток. · {shortTime(i.created_at)}</small>)}
              {(data?.payments_recent || []).map((p, n) => <small key={`tp${n}`}>Оплата {shortId(p.id)} · {S(p.provider)} · {money(p.amount, S(p.currency))} · ledger {S(p.token_ledger_id)}</small>)}
              {(data?.refunds_recent || []).map((r, n) => <small key={`tr${n}`}>Возврат {shortId(r.id)} · {money(r.amount, S(r.currency))} · {S(r.token_reversal_policy)}</small>)}
            </div>{!data?.invoices_recent?.length && !data?.payments_recent?.length && !data?.refunds_recent?.length && <p className="crm-card-note">Нет реальных счетов/оплат/возвратов.</p>}</div>}
            {tab === 'loyalty' && <div className="crm-acc"><strong>Промо / бонусы / рефералы</strong><div className="crm-rows">
              {(data?.promo_redemptions_recent || []).map((p, n) => <small key={`lp${n}`}>Промо {S(p.promo_code)} · {S(p.status)} · +{S(p.token_bonus)} ток. · ledger {S(p.token_ledger_id)}</small>)}
              {(data?.bonus_grants_recent || []).map((b, n) => <small key={`lb${n}`}>Бонус {shortId(b.id)} · {S(b.bonus_type)} · {S(b.status)} · +{S(b.token_amount)} ток. · ledger {S(b.token_ledger_id)}</small>)}
              {(data?.referral_relations || []).map((r, n) => <small key={`lr${n}`}>Реф. связь {S(r.referral_code)} · {S(r.status)} · parent {S(r.parent_internal_user_id)} · child {S(r.child_internal_user_id)}</small>)}
              {(data?.referral_rewards_recent || []).map((r, n) => <small key={`lw${n}`}>Реф. награда {shortId(r.id)} · {S(r.status)} · +{S(r.token_amount)} ток. · ledger {S(r.token_ledger_id)}</small>)}
            </div>{!data?.promo_redemptions_recent?.length && !data?.bonus_grants_recent?.length && !data?.referral_rewards_recent?.length && <p className="crm-card-note">Нет реальных промо/бонусов/реферальных начислений.</p>}</div>}
            {tab === 'prompts' && <div className="crm-acc"><strong>Промпты</strong><div className="crm-rows">{(data?.recent_generations || []).slice(0, 12).map((g, n) => <small key={n}>{shortTime(g.created_at)} · {S(g.mode)} · {S(g.status)} · {S(g.prompt)}</small>)}</div>{!data?.recent_generations?.length && <p className="crm-card-note">—</p>}</div>}
            {tab === 'gallery' && <div className="crm-acc"><strong>Галерея</strong><div className="crm-gallery-strip">{(data?.recent_gallery || []).slice(0, 8).map((img, n) => <button type="button" className="crm-gallery-strip-item" key={n} onClick={() => openImage(img)}><img src={imageUrl(img)} alt="" /><small>{S(img.mode)} · {shortTime(img.created_at)}</small></button>)}</div>{!data?.recent_gallery?.length && <p className="crm-card-note">—</p>}</div>}
            {tab === 'tech' && <div className="crm-acc">
              <strong>Технические идентификаторы</strong>
              <p className="legacy-admin-warn">Не показывать пользователю.</p>
              <dl className="crm-preview-list">{row('internal_user_id', u.internal_user_id)}{row('public_user_code', sm.public_user_code)}{row('primary_provider', sm.primary_provider)}</dl>
            </div>}
          </div>

          <aside className="crm-card-actions">
            <h4>Админ-действия</h4>
            <p className="crm-card-note">{adminReady ? 'Каждое поддержанное действие требует причину и пишется в audit log.' : 'Войдите как админ: мутационные действия заблокированы.'}</p>
            <div className="crm-action-group"><strong>Токены</strong><div className="crm-quick"><button className="secondary crm-supported-action" disabled={!adminReady} title={adminReady ? undefined : 'Войдите как админ'} onClick={() => adminReady && setAct({ kind: 'tokens', preset: '50' })}>+50</button><button className="secondary crm-supported-action" disabled={!adminReady} title={adminReady ? undefined : 'Войдите как админ'} onClick={() => adminReady && setAct({ kind: 'tokens', preset: '-50' })}>-50</button>{actionButton('tokens', 'Другое')}</div></div>
            <div className="crm-action-group"><strong>Биллинг</strong>{actionButton('plan', 'Изменить тариф')}<button className="secondary crm-supported-action" disabled={!adminReady} title={adminReady ? undefined : 'Войдите как админ'} onClick={() => adminReady && setAct({ kind: 'invoice', preset: '0' })}>Выставить счёт</button><button className="secondary crm-supported-action" disabled={!adminReady || !unpaidInvoice} onClick={() => adminReady && unpaidInvoice && setAct({ kind: 'mark_paid', preset: S(unpaidInvoice.total_amount), context: unpaidInvoice })}>Отметить оплату</button><button className="secondary danger crm-supported-action" disabled={!adminReady || !refundablePayment} onClick={() => adminReady && refundablePayment && setAct({ kind: 'refund', preset: S(refundablePayment.amount), context: refundablePayment })}>Возврат</button><button className="secondary danger crm-supported-action" disabled={!adminReady || !unpaidInvoice} onClick={() => adminReady && unpaidInvoice && setAct({ kind: 'cancel_invoice', context: unpaidInvoice })}>Отменить счёт</button></div>
            <div className="crm-action-group"><strong>Маркетинг</strong><button className="secondary crm-supported-action" disabled={!adminReady} title={adminReady ? undefined : 'Войдите как админ'} onClick={() => adminReady && setAct({ kind: 'bonus', preset: '100' })}>Бонус / компенсация</button><button className="secondary crm-supported-action" disabled={!adminReady} title={adminReady ? undefined : 'Войдите как админ'} onClick={() => adminReady && setAct({ kind: 'promo' })}>Применить промокод</button><button className="secondary crm-supported-action" disabled={!adminReady} title={adminReady ? undefined : 'Войдите как админ'} onClick={() => adminReady && setAct({ kind: 'referral_reward', preset: '100' })}>Реферальная корректировка</button><button className="secondary danger crm-supported-action" disabled={!adminReady || !cancellableBonus} onClick={() => adminReady && cancellableBonus && setAct({ kind: 'cancel_bonus', context: cancellableBonus })}>Отменить бонус</button></div>
            <div className="crm-action-group"><strong>Доступ</strong>{actionButton(isBanned ? 'unban' : 'ban', isBanned ? 'Разбанить' : 'Бан/Разбан', undefined, !isBanned)}{actionButton('reset', 'Сбросить пароль', undefined, true)}</div>
            <div className="crm-action-group"><strong>Аккаунт</strong>{actionButton('profile', 'Редактировать профиль')}{actionButton('role', isAdmin ? 'Снять админа' : 'Сделать админом')}<button className="secondary danger crm-supported-action" disabled={!adminReady || isAdmin || isBanned} onClick={() => adminReady && setAct({ kind: 'deactivate' })}>Деактивировать</button>{disabledAction('Анонимизировать')}</div>
          </aside>
        </div>

        {act && <ActionConfirm target={merged} kind={act.kind} preset={act.preset} context={act.context} onClose={() => setAct(null)} onDone={() => { setReloadKey((k) => k + 1); onChanged?.() }} />}
        {selectedImage && (
          <div className="crm-image-modal" onClick={() => setSelectedImage(null)}>
            <div className="crm-image-dialog" role="dialog" aria-label="Изображение пользователя" onClick={(e) => e.stopPropagation()}>
              <div className="crm-image-head">
                <strong>Изображение пользователя</strong>
                <button className="auth-modal-close" aria-label="Закрыть" onClick={() => setSelectedImage(null)}>×</button>
              </div>
              <div className="crm-image-body">
                <div className="crm-image-frame">{imageUrl(selectedImage) ? <img src={imageUrl(selectedImage)} alt="" /> : <span>Нет превью</span>}</div>
                <aside className="crm-image-side">
                  <dl className="crm-preview-list">
                    {row('Режим', selectedImage.mode)}{row('Провайдер', selectedImage.provider)}{row('Создано', shortTime(selectedImage.created_at))}
                    {row('Image', selectedImage.id)}{row('Job', selectedImage.job_id)}{row('Избранное', selectedImage.favorite ? 'да' : 'нет')}
                  </dl>
                  <div className="crm-image-prompt">
                    <strong>Промпт</strong>
                    <p>{S(selectedImage.prompt || 'Промпт не сохранён')}</p>
                  </div>
                  <div className="crm-image-danger">
                    <strong>Удаление из галереи</strong>
                    <p className="crm-card-note">Картинка будет скрыта у пользователя, действие попадёт в audit log.</p>
                    <input value={deleteReason} onChange={(e) => setDeleteReason(e.target.value)} placeholder="Причина удаления" />
                    <button className="secondary danger crm-supported-action" disabled={!adminReady || deleteBusy || !deleteReason.trim()} onClick={() => void deleteGalleryImage()}>{deleteBusy ? 'Удаляю…' : 'Удалить изображение'}</button>
                    {deleteMsg && <p className="crm-err">{deleteMsg}</p>}
                  </div>
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
  const [sort, setSort] = useState<UserSort>('recent')
  const [loading, setLoading] = useState(true)
  const [card, setCard] = useState<CrmUserRow | null>(null)
  const [rowAct, setRowAct] = useState<{ u: CrmUserRow; kind: ActKind; preset?: string } | null>(null)
  const [settingsOpen, setSettingsOpen] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    const d = await adminGet<Dash>('/admin/dashboard-v2')
    const params = new URLSearchParams({ limit: '100', sort })
    if (q.trim()) params.set('q', q.trim())
    if (source !== 'all') params.set('provider', source)
    if (statusFilter === 'active' || statusFilter === 'banned') params.set('status', statusFilter)
    const u = await adminGet<{ items: CrmUserRow[] }>(`/admin/users-analytics-v2?${params.toString()}`)
    setDash(d?.dashboard ?? null)
    let items = Array.isArray(u?.items) ? u!.items : []
    if (statusFilter === 'admin') items = items.filter((i) => i.role === 'admin') // server has no admin filter yet
    setUsers(items)
    setLoading(false)
  }, [q, source, statusFilter, sort])
  useEffect(() => {
    const id = window.setTimeout(() => { void load() }, 0)
    return () => window.clearTimeout(id)
  }, [load])

  const card_ = (label: string, value: unknown) => <div className="analytics-card" key={label}><strong>{String(value ?? '—')}</strong><span>{label}</span></div>
  const byProvider = (dash?.users_by_provider as Record<string, number>) || {}

  return (
    <section className="admin-analytics">
      <div className="crm-head"><h3>Пользователи</h3><p className="crm-sub">Операторская CRM: входы, источники, активность и трасты-действия в строке.</p></div>
      <AdminDiagnostics />
      <div className="analytics-cards compact">
        {card_('Всего', dash?.total_users)}{card_('Сегодня', dash?.active_today)}{card_('7 дней', dash?.active_7d)}
        {card_('Сессии', dash?.sessions_active)}{card_('Генерации', dash?.generations_total)}{card_('Токены', dash?.tokens_spent_total)}
        {card_('Web', byProvider.web_email ?? 0)}{card_('TG', byProvider.telegram ?? 0)}{card_('MAX', byProvider.max ?? 0)}{card_('Ошибки 24ч', dash?.failed_logins_24h)}
      </div>
      <div className="analytics-search">
        <input placeholder="Код, имя, email, username" value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') void load() }} />
        <select value={source} onChange={(e) => setSource(e.target.value as typeof source)}><option value="all">Все источники</option><option value="web_email">Web</option><option value="telegram">Telegram</option><option value="max">MAX</option></select>
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value as typeof statusFilter)}><option value="all">Все статусы</option><option value="active">Активные</option><option value="banned">Забанены</option><option value="admin">Админы</option></select>
        <select value={sort} onChange={(e) => setSort(e.target.value as UserSort)} aria-label="Сортировка пользователей"><option value="recent">Сначала активные</option><option value="created_desc">Новые регистрации</option><option value="created_asc">Старые регистрации</option><option value="generations_desc">Больше генераций</option><option value="tokens_desc">Больше списаний</option><option value="balance_desc">Больше баланс</option><option value="balance_asc">Меньше баланс</option><option value="code_asc">Код пользователя</option><option value="plan_asc">Тариф</option></select>
        <button className="secondary" onClick={() => void load()}>Найти</button>
      </div>
      <div className="crm-viewbar">
        <button className="secondary crm-settings-toggle" aria-expanded={settingsOpen} onClick={() => setSettingsOpen((v) => !v)}>Вид и колонки</button>
      </div>
      {settingsOpen && <CrmSettingsScaffold onClose={() => setSettingsOpen(false)} />}
      {loading ? <p>Загрузка…</p> : (
        <div className="analytics-table dense">
          <div className="analytics-row analytics-head">
            <span>Клиент</span><span>Активность</span><span>Источник</span><span>Контакт</span><span>Тариф / галерея</span><span>Генерации / токены</span><span>Устройство</span><span>Действия</span>
          </div>
          {users.map((u) => {
            const sourceList = u.providers?.length ? u.providers : u.primary_provider ? [u.primary_provider] : []
            const active = activityKind(u)
            const openCard = () => setCard(u)
            const stop = (e: ReactMouseEvent) => e.stopPropagation()
            const rowKey = (e: ReactKeyboardEvent<HTMLDivElement>) => {
              if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openCard() }
            }
            return (
              <div key={u.public_user_code || u.internal_user_id_short} className={`analytics-row crm-row activity-${active}`} role="button" tabIndex={0} aria-label={`Открыть карточку ${u.display_name || u.username || u.public_user_code}`} onClick={openCard} onKeyDown={rowKey}>
                <span className="crm-client-cell"><AvatarMark u={u as CrmUserRow & AnyRec} className={`crm-avatar crm-row-avatar activity-${active}`} /><span><span className="crm-client-line"><strong>{u.display_name || u.username || u.public_user_code}</strong><em className="crm-chip">{u.role === 'admin' ? 'admin' : 'user'}</em></span><span className="crm-client-line"><small>{u.public_user_code}</small><em className="crm-chip plan">{u.plan || 'mini'}</em></span></span></span>
                <span><small><i className={`crm-dot activity-${active}`} />{ACTIVITY_LABEL[active]}</small><small>{shortTime(u.last_seen_at)}</small><small>{u.active_sessions_count ?? 0} сесс. · {u.last_platform || '—'}</small></span>
                <span>{sourceList.map((p) => <Badge key={p} p={p} />)}<small>{u.last_ip || 'IP —'}</small></span>
                <span><small>{u.email || '—'}</small><small>{genderAgeLabel(u as CrmUserRow & AnyRec)}</small><small>{u.username ? `@${u.username}` : ''}{u.phone ? ` · ${u.phone}` : ''}</small></span>
                <span><small>{u.plan || 'mini'} · галерея открыта</small><strong>{quotaLabel(u as CrmUserRow & AnyRec)}</strong><small>свободно {n0(u.gallery_free)}</small></span>
                <span><strong>{tokenLine(u)}</strong><small>всего / сегодня / баланс / день</small><small>списано {n0(u.tokens_spent)}</small></span>
                <span><small>{deviceLabel(u)}</small><small>{u.device_count ?? 0} устр.</small></span>
                <span className="crm-row-actions">
                  <button className="mini" onClick={(e) => { stop(e); setCard(u) }}>Карточка</button>
                  <RowActionMenu u={u} onCard={() => setCard(u)} onAct={(kind, preset) => setRowAct({ u, kind, preset })} />
                </span>
              </div>
            )
          })}
          {users.length === 0 && <p>Пользователи не найдены.</p>}
        </div>
      )}
      {card && <UserCard u={card} onClose={() => setCard(null)} onChanged={() => void load()} />}
      {rowAct && <ActionConfirm target={rowAct.u} kind={rowAct.kind} preset={rowAct.preset} onClose={() => setRowAct(null)} onDone={() => void load()} />}
    </section>
  )
}
