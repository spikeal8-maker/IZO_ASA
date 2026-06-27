// Phase 20A–20C.3: Users CRM — an operator console. Cookie auth only
// (credentials:include), never the legacy identity header. Dense table with trusted
// quick actions in every row + a compact two-column user card (actions above the fold).
// Every risky action requires a reason and is written to audit_logs. No tokens/hashes
// are ever requested or shown.
import { useEffect, useState } from 'react'
import type { ReactElement } from 'react'
import { APP_BUILD_LABEL } from './diag'

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
  email?: string | null; username?: string | null; phone?: string | null; plan?: string | null
  last_seen_at?: string | null; last_platform?: string | null; last_ip?: string | null
  country?: string | null; city?: string | null; device_count?: number; active_sessions_count?: number
  generations_count?: number; tokens_spent?: number; token_balance?: number; status?: string; role?: string
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
  token_summary?: { spent?: number; entries?: number; balance?: number }
}

// --- Shared trusted-action confirm (compact popover, reason-gated, audited). ---
type ActKind = 'tokens' | 'role' | 'plan' | 'profile' | 'ban' | 'unban' | 'reset'
function ActionConfirm({ target, kind, preset, onClose, onDone }: {
  target: CrmUserRow; kind: ActKind; preset?: string; onClose: () => void; onDone: () => void
}): ReactElement {
  const isAdmin = target.role === 'admin'
  const [reason, setReason] = useState('')
  const [value, setValue] = useState(preset ?? (kind === 'profile' ? String(target.display_name ?? '') : ''))
  const [email, setEmail] = useState(typeof target.email === 'string' ? target.email : '')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const iuid = target.internal_user_id
  const title: Record<ActKind, string> = {
    tokens: 'Изменить токены', role: isAdmin ? 'Снять админа' : 'Сделать админом', plan: 'Изменить тариф',
    profile: 'Изменить профиль', ban: 'Забанить / отключить', unban: 'Разбанить', reset: 'Сбросить пароль',
  }
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
    else if (kind === 'unban') res = await adminPost(`${base}/unblock-v2`, { reason })
    else if (kind === 'reset') { if (value.length < 8) { setBusy(false); setMsg('Пароль не короче 8 символов.'); return } res = await adminPost(`${base}/password-reset-v2`, { new_password: value, reason }) }
    setBusy(false)
    if (res.ok) { setMsg('Готово. Записано в audit log.'); onDone(); window.setTimeout(onClose, 650) }
    else setMsg(res.detail || (res.status === 403 ? 'Недостаточно прав или действие запрещено.' : 'Не удалось выполнить действие.'))
  }

  return (
    <div className="crm-confirm-overlay" onClick={onClose}>
      <div className="crm-confirm" role="dialog" aria-label="Подтверждение действия" onClick={(e) => e.stopPropagation()}>
        <strong>{title[kind]}</strong>
        <span className="crm-confirm-target">{parsedName(target as AnyRec)} · {S(target.public_user_code)}</span>
        {kind === 'tokens' && (
          <div className="crm-confirm-field">
            <div className="crm-quick"><button className="secondary" onClick={() => setValue('50')}>+50</button><button className="secondary" onClick={() => setValue('-50')}>-50</button><button className="secondary" onClick={() => setValue('1')}>+1</button><button className="secondary" onClick={() => setValue('-1')}>-1</button></div>
            <label>Изменение баланса<input value={value} onChange={(e) => setValue(e.target.value)} placeholder="например 50 или -50" /></label>
          </div>
        )}
        {kind === 'plan' && <label>Тариф<select value={value} onChange={(e) => setValue(e.target.value)}><option value="">Выбрать…</option><option value="free">free</option><option value="mini">mini</option><option value="plus">plus</option><option value="pro">pro</option></select></label>}
        {kind === 'profile' && <><label>Отображаемое имя<input value={value} onChange={(e) => setValue(e.target.value)} autoComplete="off" /></label><label>Email<input value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="off" /></label></>}
        {kind === 'reset' && <label>Новый пароль (не сохраняется)<input type="password" value={value} onChange={(e) => setValue(e.target.value)} autoComplete="off" /></label>}
        <label>Причина (обязательно)<input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Причина действия" /></label>
        <p className="crm-card-note">Действие будет записано в audit log.</p>
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
  const [act, setAct] = useState<{ kind: ActKind; preset?: string } | null>(null)

  useEffect(() => {
    let alive = true
    const iuid = u.internal_user_id
    if (!iuid) { setState('error'); return }
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
  const isAdmin = String(sm.role) === 'admin'
  const isBanned = sm.status === 'banned'
  const row = (k: string, v: unknown) => <><dt>{k}</dt><dd>{S(v)}</dd></>
  const banner = state === 'loading' ? 'Загрузка…'
    : state === 'notfound' ? 'Пользователь не найден.'
    : state === 'forbidden' ? 'Нет trusted-сессии администратора. Войдите как админ.'
    : state === 'error' ? 'Не удалось загрузить данные.' : ''

  const ActBtn = ({ kind, preset, label, danger }: { kind: ActKind; preset?: string; label: string; danger?: boolean }) =>
    <button className={danger ? 'secondary danger' : 'secondary'} onClick={() => setAct({ kind, preset })}>{label}</button>

  return (
    <div className="crm-card-overlay" onClick={onClose}>
      <div className="crm-card" role="dialog" aria-label="Карточка пользователя" onClick={(e) => e.stopPropagation()}>
        <header className="crm-card-header">
          <button className="auth-modal-close" aria-label="Закрыть" onClick={onClose}>×</button>
          <div className="crm-card-id">
            <h2>{parsedName(sm, ids)}</h2>
            <span className="crm-preview-code">{S(sm.public_user_code)}</span>
            <span className="crm-preview-badges">{((sm.providers as string[]) || u.providers || []).map((p) => <Badge key={p} p={p} />)}</span>
            <span className={isBanned ? 'status-banned' : 'status-active'}>{S(sm.status)}{isAdmin ? ' · admin' : ''}</span>
          </div>
          <div className="crm-card-kpis">
            <span>Баланс <b>{S(sm.token_balance)}</b></span><span>Списано <b>{S(sm.tokens_spent)}</b></span>
            <span>Генераций <b>{S(sm.generations_count)}</b></span><span>Тариф <b>{S(sm.plan)}</b></span>
            <span>Рег. {shortTime(sm.first_seen_at)}</span><span>Вход {shortTime(sm.last_seen_at)}</span>
          </div>
        </header>

        <div className="crm-card-cols">
          <div className="crm-card-left">
            {banner && <p className={state === 'ok' ? 'crm-card-note' : 'crm-err'}>{banner}</p>}
            <div className="crm-panel">
              <h4>Профиль и контакты</h4>
              <dl className="crm-preview-list">
                {row('Имя', parsedName(sm, ids))}{row('Email', sm.email)}{row('Username', sm.username)}{row('Телефон', sm.phone)}
                {row('Язык', (ids?.[0] as AnyRec)?.language_code)}{row('Гео', `${S(sm.city)} / ${S(sm.country)}`)}{row('Роль', sm.role)}{row('Тариф', sm.plan)}
              </dl>
            </div>
            <div className="crm-panel">
              <h4>Источники входа</h4>
              {(ids || []).map((i, n) => (
                <div className="crm-subrow" key={n}>
                  <span><Badge p={String(i.provider)} /> @{S(i.provider_username)} · {S(i.provider_email)} · id {shortId(i.provider_user_id, 6)}</span>
                  <small>вход {shortTime(i.last_login_at)} · {i.verified_at ? 'verified' : 'не подтв.'} · raw-профиль: {i.has_raw_profile ? 'да' : 'нет'}</small>
                </div>
              ))}{!ids?.length && <p className="crm-card-note">—</p>}
            </div>
            <div className="crm-two">
              <div className="crm-panel">
                <h4>Сессии</h4>
                {(data?.sessions || []).slice(0, 6).map((s, n) => (
                  <div className="crm-subrow" key={n}><small><strong>{S(s.platform)}</strong> · {S(s.ip_address)} {s.revoked_at ? '· отозв.' : '· активна'}</small><small>{S((s.device as AnyRec)?.browser)}/{S((s.device as AnyRec)?.os)} · {shortTime(s.created_at)}</small></div>
                ))}{!data?.sessions?.length && <p className="crm-card-note">—</p>}
              </div>
              <div className="crm-panel">
                <h4>Устройства</h4>
                {(data?.devices || []).slice(0, 6).map((d, n) => (
                  <div className="crm-subrow" key={n}><small><strong>{S(d.platform)}</strong> · inst {shortId(d.installation_id)}</small><small>anon {shortId(d.anonymous_id)} · {shortTime(d.last_seen_at)}</small></div>
                ))}{!data?.devices?.length && <p className="crm-card-note">—</p>}
              </div>
            </div>

            <details className="crm-acc"><summary>Логи ({(data?.recent_events?.length || 0) + (data?.recent_security_events?.length || 0) + (data?.admin_actions?.length || 0)})</summary>
              <div className="crm-rows">
                {(data?.recent_events || []).slice(0, 10).map((e, n) => <small key={`e${n}`}>{shortTime(e.created_at)} · {S(e.event_name)} · {S(e.platform)}</small>)}
                {(data?.recent_security_events || []).slice(0, 10).map((e, n) => <small key={`s${n}`}>⚠ {shortTime(e.created_at)} · {S(e.severity)} · {S(e.event_type)} · {S(e.ip_address)}</small>)}
                {(data?.admin_actions || []).slice(0, 10).map((e, n) => <small key={`a${n}`}>★ {shortTime(e.created_at)} · {S(e.action)} · {S(e.actor)}</small>)}
              </div>
            </details>
            <details className="crm-acc"><summary>Токены и генерации</summary>
              <dl className="crm-preview-list">
                {row('Баланс', data?.token_summary?.balance ?? sm.token_balance)}{row('Списано', data?.token_summary?.spent ?? sm.tokens_spent)}{row('Записей в журнале', data?.token_summary?.entries)}{row('Генераций', sm.generations_count)}
              </dl>
              <p className="crm-card-note">Детальный журнал и история генераций — Phase 23.</p>
            </details>
            <details className="crm-acc"><summary>Технические идентификаторы</summary>
              <p className="legacy-admin-warn">Не показывать пользователю.</p>
              <dl className="crm-preview-list">{row('internal_user_id', u.internal_user_id)}{row('public_user_code', sm.public_user_code)}{row('primary_provider', sm.primary_provider)}</dl>
            </details>
          </div>

          <aside className="crm-card-actions">
            <h4>Админ-действия</h4>
            <p className="crm-card-note">Каждое действие требует причину и пишется в audit log.</p>
            <div className="crm-act-stack">
              <div className="crm-quick"><button className="secondary" onClick={() => setAct({ kind: 'tokens', preset: '50' })}>+50</button><button className="secondary" onClick={() => setAct({ kind: 'tokens', preset: '-50' })}>-50</button><ActBtn kind="tokens" label="Токены…" /></div>
              <ActBtn kind={isBanned ? 'unban' : 'ban'} label={isBanned ? 'Разбанить' : 'Забанить / отключить'} danger={!isBanned} />
              <ActBtn kind="role" label={isAdmin ? 'Снять админа' : 'Сделать админом'} />
              <ActBtn kind="plan" label="Изменить тариф" />
              <ActBtn kind="profile" label="Изменить профиль" />
              <ActBtn kind="reset" label="Сбросить пароль" />
            </div>
          </aside>
        </div>

        {act && <ActionConfirm target={merged} kind={act.kind} preset={act.preset} onClose={() => setAct(null)} onDone={() => { setReloadKey((k) => k + 1); onChanged?.() }} />}
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

export function AdminAnalyticsV2(): ReactElement {
  const [dash, setDash] = useState<Dash['dashboard'] | null>(null)
  const [users, setUsers] = useState<CrmUserRow[]>([])
  const [q, setQ] = useState('')
  const [source, setSource] = useState<'all' | 'web_email' | 'telegram' | 'max'>('all')
  const [statusFilter, setStatusFilter] = useState<'all' | 'active' | 'banned' | 'admin'>('all')
  const [loading, setLoading] = useState(true)
  const [card, setCard] = useState<CrmUserRow | null>(null)
  const [rowAct, setRowAct] = useState<{ u: CrmUserRow; kind: ActKind; preset?: string } | null>(null)

  const load = async () => {
    setLoading(true)
    const d = await adminGet<Dash>('/admin/dashboard-v2')
    const params = new URLSearchParams({ limit: '100' })
    if (q.trim()) params.set('q', q.trim())
    if (source !== 'all') params.set('provider', source)
    if (statusFilter === 'active' || statusFilter === 'banned') params.set('status', statusFilter)
    const u = await adminGet<{ items: CrmUserRow[] }>(`/admin/users-analytics-v2?${params.toString()}`)
    setDash(d?.dashboard ?? null)
    let items = Array.isArray(u?.items) ? u!.items : []
    if (statusFilter === 'admin') items = items.filter((i) => i.role === 'admin') // server has no admin filter yet
    setUsers(items)
    setLoading(false)
  }
  useEffect(() => { void load() }, [])

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
        <button className="secondary" onClick={() => void load()}>Найти</button>
      </div>
      {loading ? <p>Загрузка…</p> : (
        <div className="analytics-table dense">
          <div className="analytics-row analytics-head">
            <span>Пользователь</span><span>Источ.</span><span>Контакты</span><span>Роль·Тариф</span><span>Баланс</span><span>Ген.</span><span>Активность</span><span>Статус</span><span>Действия</span>
          </div>
          {users.map((u) => {
            const banned = u.status === 'banned'; const admin = u.role === 'admin'
            return (
              <div key={u.public_user_code || u.internal_user_id_short} className="analytics-row crm-row">
                <span><strong>{u.display_name}</strong><small>{u.public_user_code}</small></span>
                <span>{(u.providers || []).map((p) => <Badge key={p} p={p} />)}</span>
                <span><small>{u.email || '—'}</small><small>{u.username ? `@${u.username}` : ''}{u.phone ? ` · ${u.phone}` : ''}</small></span>
                <span><small>{u.role}</small><small>{u.plan || '—'}</small></span>
                <span><small>{u.token_balance ?? 0} / {u.tokens_spent ?? 0}</small></span>
                <span>{u.generations_count ?? 0}</span>
                <span><small>{shortTime(u.last_seen_at)}</small><small>{u.last_platform || '—'} · {u.last_ip || '—'}</small></span>
                <span className={banned ? 'status-banned' : 'status-active'}>{u.status}</span>
                <span className="crm-row-actions">
                  <button className="mini" onClick={() => setCard(u)}>Карточка</button>
                  <button className="mini" onClick={() => setRowAct({ u, kind: 'tokens', preset: '50' })}>+50</button>
                  <button className="mini" onClick={() => setRowAct({ u, kind: 'tokens', preset: '-50' })}>-50</button>
                  <button className={banned ? 'mini' : 'mini danger'} onClick={() => setRowAct({ u, kind: banned ? 'unban' : 'ban' })}>{banned ? 'Разбан' : 'Бан'}</button>
                  <button className="mini" onClick={() => setRowAct({ u, kind: 'role' })}>{admin ? 'Снять' : 'Админ'}</button>
                  <button className="mini" onClick={() => setRowAct({ u, kind: 'plan' })}>Тариф</button>
                  <button className="mini" onClick={() => setRowAct({ u, kind: 'reset' })}>Пароль</button>
                  <button className="mini" onClick={() => setRowAct({ u, kind: 'profile' })}>Ред.</button>
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
