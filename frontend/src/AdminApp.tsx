import { lazy, Suspense, useCallback, useEffect, useState } from 'react'
import { Lock, Shield, WandSparkles } from 'lucide-react'
import {
  AuthV2Modal,
  ensureSessionRefreshedV2,
  initAuthV2,
  refreshAuthStateV2,
  useAuthV2,
} from './authV2'
import { DiagPanel } from './diag'
import { isDiagMode } from './diagMeta'
import { DEFAULT_TARIFFS, normalizeTariffs, resolutionOptions, tariffKeys, type TariffConfig, type TariffKey } from './profileSupport'
import './index.css'

const AdminAnalyticsV2 = lazy(() => import('./adminAnalytics').then((module) => ({ default: module.AdminAnalyticsV2 })))
const AdminModelsV2 = lazy(() => import('./adminModels'))

const API = (import.meta as ImportMeta & { env?: { VITE_API_BASE_URL?: string } }).env?.VITE_API_BASE_URL || '/api'

type AdminTab = 'dashboard' | 'users' | 'models' | 'tariffs' | 'mail' | 'logs'
type AnyRec = Record<string, unknown>
type SeriesPoint = { date: string; value: number }
type DashboardRange = 1 | 6 | 12 | 24 | 7 | 30 | 90
type PromoCode = {
  code: string
  tokens: number
  activation_limit: number
  activation_count: number
  enabled: number
}

const HOURLY_DASHBOARD_RANGES = new Set<DashboardRange>([1, 6, 12, 24])

function asSeries(value: unknown): SeriesPoint[] {
  return Array.isArray(value)
    ? value.map((item) => {
      const row = item as Partial<SeriesPoint>
      return { date: String(row.date || ''), value: Number(row.value || 0) }
    })
    : []
}

function shortChartDate(value: string): string {
  if (!value) return '—'
  if (value.includes('T')) {
    const parsedHour = new Date(value)
    return Number.isNaN(parsedHour.getTime()) ? value.slice(11, 16) : parsedHour.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
  }
  const parsed = new Date(`${value}T00:00:00`)
  return Number.isNaN(parsed.getTime()) ? value.slice(5) : parsed.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit' })
}

function AdminLineChart({
  title,
  note,
  series,
  range,
  color = '#dfff22',
}: {
  title: string
  note: string
  series: SeriesPoint[]
  range: DashboardRange
  color?: string
}) {
  const rows = series.length ? series : [{ date: '', value: 0 }]
  const max = Math.max(1, ...rows.map((p) => Number(p.value) || 0))
  const width = 460
  const height = 176
  const padLeft = 40
  const padRight = 14
  const padTop = 18
  const padBottom = 30
  const plotWidth = width - padLeft - padRight
  const plotHeight = height - padTop - padBottom
  const points = rows.map((p, index) => {
    const x = padLeft + (rows.length <= 1 ? 0 : (index / (rows.length - 1)) * plotWidth)
    const y = padTop + plotHeight - ((Number(p.value) || 0) / max) * plotHeight
    return `${x.toFixed(1)},${y.toFixed(1)}`
  }).join(' ')
  const total = rows.reduce((sum, p) => sum + (Number(p.value) || 0), 0)
  const last = rows.at(-1)?.value ?? 0
  const average = rows.length ? Math.round(total / rows.length) : 0
  const peak = rows.reduce((best, point) => (Number(point.value) > Number(best.value) ? point : best), rows[0] || { date: '', value: 0 })
  const tickStep = rows.length <= 12 ? 3 : rows.length <= 24 ? 6 : range === 7 ? 2 : range === 30 ? 10 : 30
  const dateTicks = rows.filter((_, index) => index === 0 || index === rows.length - 1 || index % tickStep === 0)
  const valueTicks = Array.from(new Set([max, Math.round(max * 0.75), Math.round(max * 0.5), Math.round(max * 0.25), 0])).sort((a, b) => b - a)
  const verticalTicks = rows.filter((_, index) => index === 0 || index === rows.length - 1 || index % tickStep === 0)
  const valueLabels = rows.filter((point, index) => Number(point.value || 0) > 0 && (index === rows.length - 1 || Number(point.value) === Number(peak.value)))
  const rangeLabel = rows[0]?.date ? `${shortChartDate(rows[0].date)} - ${shortChartDate(rows.at(-1)?.date || rows[0].date)}` : `${range} ${HOURLY_DASHBOARD_RANGES.has(range) ? 'ч' : 'дней'}`
  return (
    <article className="admin-line-chart">
      <header>
        <h3>{title}</h3>
        <p className="admin-line-meta">Сумма {total.toLocaleString('ru-RU')} · пик {Number(peak.value || 0).toLocaleString('ru-RU')} {shortChartDate(peak.date)} · среднее {average.toLocaleString('ru-RU')} · сейчас {Number(last || 0).toLocaleString('ru-RU')}</p>
      </header>
      <svg viewBox={`0 0 ${width} ${height}`} aria-label={title}>
        {valueTicks.map((value) => {
          const y = padTop + plotHeight - (value / max) * plotHeight
          return <g key={`y-${value}-${y}`}><line className="grid horizontal" x1={padLeft} x2={width - padRight} y1={y} y2={y} /><text className="axis value" x={8} y={y + 5}>{value.toLocaleString('ru-RU')}</text></g>
        })}
        {verticalTicks.map((point, index) => {
          const rowIndex = rows.indexOf(point)
          const x = padLeft + (rows.length <= 1 ? 0 : (rowIndex / (rows.length - 1)) * plotWidth)
          return <line className="grid vertical" key={`v-${point.date}-${index}`} x1={x} x2={x} y1={padTop} y2={padTop + plotHeight} />
        })}
        {dateTicks.map((point, index) => {
          const rowIndex = rows.indexOf(point)
          const x = padLeft + (rows.length <= 1 ? 0 : (rowIndex / (rows.length - 1)) * plotWidth)
          return <text className="axis date" key={`${point.date}-${index}`} x={x} y={height - 10}>{shortChartDate(point.date)}</text>
        })}
        <polyline points={points} style={{ stroke: color }} />
        {rows.map((point, index) => {
          const rowIndex = rows.indexOf(point)
          const x = padLeft + (rows.length <= 1 ? 0 : (rowIndex / (rows.length - 1)) * plotWidth)
          const y = padTop + plotHeight - ((Number(point.value) || 0) / max) * plotHeight
          return <circle key={`${point.date}-${index}`} cx={x} cy={y} r={Number(point.value || 0) > 0 ? 4 : 2.2} style={{ fill: color }}><title>{shortChartDate(point.date)}: {Number(point.value || 0).toLocaleString('ru-RU')}</title></circle>
        })}
        {valueLabels.map((point, index) => {
          const rowIndex = rows.indexOf(point)
          const x = padLeft + (rows.length <= 1 ? 0 : (rowIndex / (rows.length - 1)) * plotWidth)
          const y = padTop + plotHeight - ((Number(point.value) || 0) / max) * plotHeight
          const labelY = Math.max(14, y - 9)
          return <text className="axis point-value" key={`label-${point.date}-${index}`} x={x} y={labelY}>{Number(point.value || 0).toLocaleString('ru-RU')}</text>
        })}
      </svg>
      <footer><small>{note}</small><b>{rangeLabel}</b></footer>
    </article>
  )
}

async function adminFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers)
  const request = () => fetch(`${API}${path}`, { ...init, headers, credentials: 'include' })
  let response = await request()
  if (response.status === 401 && !path.includes('/auth/session/refresh-v2')) {
    const refreshed = await ensureSessionRefreshedV2()
    if (refreshed) {
      await refreshAuthStateV2().catch(() => null)
      response = await request()
    }
  }
  return response
}

async function adminGet<T>(path: string): Promise<T | null> {
  const res = await adminFetch(path)
  if (!res.ok) return null
  return await res.json() as T
}

async function adminPost<T>(path: string, body: unknown): Promise<T | null> {
  const res = await adminFetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) return null
  return await res.json() as T
}

function AdminAccessPage({ status, onOpenAuth }: { status: 'loading' | 'denied'; onOpenAuth: () => void }) {
  return (
    <section className="admin-page admin-access-page">
      <div className="view-actions in-panel">
        <button className="secondary" onClick={() => { window.location.href = '/' }}>
          <WandSparkles size={16} />К генерации
        </button>
      </div>
      <div className="admin-head">
        <div>
          <h2>Админ</h2>
          <p>{status === 'loading' ? 'Проверяем trusted admin-сессию.' : 'Админка доступна только trusted admin-сессии.'}</p>
        </div>
        <strong>{status === 'loading' ? 'loading' : '403'}</strong>
      </div>
      {status === 'denied' && (
        <div className="admin-note">
          <strong>Доступ закрыт</strong>
          <p>Войдите под аккаунтом администратора. UI скрывает админку для обычных пользователей, а backend дополнительно защищает все admin API.</p>
          <button className="generate small-action" onClick={onOpenAuth}><Lock size={16} />Войти</button>
        </div>
      )}
    </section>
  )
}

function AdminDashboard({ summary }: { summary: AnyRec | null }) {
  const finance = (summary?.finance || {}) as AnyRec
  const timeline = (summary?.timeline || {}) as AnyRec
  const [range, setRange] = useState<DashboardRange>(24)
  const isHourlyRange = HOURLY_DASHBOARD_RANGES.has(range)
  const sliceSeries = (key: string): SeriesPoint[] => {
    const sourceKey = isHourlyRange ? `${key}_${range}h` : key
    const source = asSeries(timeline[sourceKey])
    return isHourlyRange ? source : source.slice(-range)
  }
  const charts = [
    { title: 'Активность пользователей', note: 'last_seen по времени', key: 'active_users', color: '#dfff22' },
    { title: 'Новые пользователи', note: 'созданные аккаунты', key: 'registrations', color: '#72ff69' },
    { title: 'Успешные входы', note: 'login/register события', key: 'logins', color: '#64b5ff' },
    { title: 'Ошибки входа', note: 'неудачные auth попытки', key: 'login_errors', color: '#ffd45c' },
    { title: 'Генерации', note: 'старты генераций', key: 'generations', color: '#dfff22' },
    { title: 'Ошибки генерации', note: 'failed jobs', key: 'generation_errors', color: '#ff6b6b' },
  ].map((chart) => ({ ...chart, series: sliceSeries(chart.key) }))
  const kpi = (title: string, value: unknown, note: string) => (
    <div><strong>{title}</strong><span>{String(value ?? '—')}</span><small>{note}</small></div>
  )
  return (
    <div className="admin-section admin-dashboard-v2">
      <div className="admin-grid admin-grid-compact">
        {kpi('Пользователи', summary?.users, 'аккаунтов в базе')}
        {kpi('Сегодня', summary?.activeToday, 'активных пользователей')}
        {kpi('Генерации', summary?.generationsToday, 'создано сегодня')}
        {kpi('Сессии', summary?.activeSessions, 'активны сейчас')}
        {kpi('Ошибки входа', summary?.errors24h, 'за 24 часа')}
        {kpi('Ошибки генерации', summary?.errors, 'failed jobs')}
      </div>
      {Boolean(summary?.finance) && (
        <div className="admin-grid admin-grid-compact">
          {kpi('Доход', `${Number(finance.tokenRevenue ?? 0).toLocaleString('ru-RU')} ₽`, 'оценка')}
          {kpi('Себестоимость', `${Number(finance.tokenCost ?? 0).toLocaleString('ru-RU')} ₽`, 'оценка')}
          {kpi('Свет', `${Number(finance.electricity ?? 0).toLocaleString('ru-RU')} ₽`, 'оценка')}
          {kpi('Акции', `${Number(finance.promoBudget ?? 0).toLocaleString('ru-RU')} ₽`, 'оценка')}
        </div>
      )}
      <div className="admin-dashboard-toolbar">
        <strong>Графики по времени</strong>
        {[
          [1, '1 час'],
          [6, '6 часов'],
          [12, '12 часов'],
          [24, 'сутки'],
          [7, '7 дней'],
          [30, '30 дней'],
          [90, '90 дней'],
        ].map(([value, label]) => <button key={value} className={range === value ? 'active' : ''} onClick={() => setRange(value as DashboardRange)}>{label}</button>)}
      </div>
      <div className="admin-chart-grid">
        {charts.map((chart) => <AdminLineChart key={chart.key} title={chart.title} note={chart.note} series={chart.series} range={range} color={chart.color} />)}
      </div>
      <div className="admin-note">
        <strong>Статус страницы</strong>
        <p>Это отдельная админская оболочка. Она не рендерит старый генератор и использует только trusted cookie auth.</p>
      </div>
    </div>
  )
}

function AdminTokens() {
  const [tariffs, setTariffs] = useState<TariffConfig>(DEFAULT_TARIFFS)
  const [finance, setFinance] = useState({ tokenRevenue: 0, tokenCost: 0, electricity: 0, promoBudget: 0 })
  const [promos, setPromos] = useState<PromoCode[]>([])
  const [promoDraft, setPromoDraft] = useState({ code: 'START50', tokens: 50, activations: 100 })
  const [msg, setMsg] = useState('')

  const load = useCallback(async () => {
    const [settings, promoRows] = await Promise.all([
      adminGet<AnyRec>('/admin/settings'),
      adminGet<PromoCode[]>('/admin/promos'),
    ])
    if (settings?.tariffs) setTariffs(normalizeTariffs(settings.tariffs as Partial<Record<TariffKey, Partial<TariffConfig[TariffKey]>>>))
    if (settings?.finance) setFinance((current) => ({ ...current, ...(settings.finance as Partial<typeof finance>) }))
    setPromos(Array.isArray(promoRows) ? promoRows : [])
  }, [])

  useEffect(() => {
    queueMicrotask(() => { void load() })
  }, [load])

  const saveTariffs = async () => {
    const result = await adminPost<{ ok?: boolean; settings?: Partial<Record<TariffKey, Partial<TariffConfig[TariffKey]>>> }>('/admin/settings/tariffs', { settings: tariffs })
    if (result?.ok) {
      setTariffs(normalizeTariffs(result.settings))
      setMsg('Тарифы сохранены')
    } else setMsg('Ошибка сохранения тарифов')
  }
  const saveFinance = async () => {
    const result = await adminPost<{ ok?: boolean }>('/admin/settings/finance', { settings: finance })
    setMsg(result?.ok ? 'Финансы сохранены' : 'Ошибка сохранения финансов')
  }
  const toggleResolution = (plan: TariffKey, resolutionId: string, checked: boolean) => {
    setTariffs((current) => {
      const currentIds = current[plan].allowed_resolutions || []
      const nextIds = checked
        ? Array.from(new Set([...currentIds, resolutionId]))
        : currentIds.filter((id) => id !== resolutionId)
      return { ...current, [plan]: { ...current[plan], allowed_resolutions: nextIds } }
    })
  }
  const createPromo = async () => {
    const result = await adminPost<{ ok?: boolean; promo?: PromoCode }>('/admin/promos', {
      code: promoDraft.code,
      tokens: Number(promoDraft.tokens),
      activationLimit: Number(promoDraft.activations),
    })
    setMsg(result?.ok ? `Промокод ${result.promo?.code || promoDraft.code} сохранён` : 'Ошибка промокода')
    await load()
  }

  return (
    <div className="admin-section">
      <h3>Тарифы, токены, финансы и акции</h3>
      {msg && <small>{msg}</small>}
      <div className="admin-two-col">
        <article>
          <h3>Финансы</h3>
          <label>Доход от токенов<input type="number" value={finance.tokenRevenue} onChange={(e) => setFinance({ ...finance, tokenRevenue: Number(e.target.value) })} /></label>
          <label>Себестоимость API<input type="number" value={finance.tokenCost} onChange={(e) => setFinance({ ...finance, tokenCost: Number(e.target.value) })} /></label>
          <label>Свет<input type="number" value={finance.electricity} onChange={(e) => setFinance({ ...finance, electricity: Number(e.target.value) })} /></label>
          <label>Акции<input type="number" value={finance.promoBudget} onChange={(e) => setFinance({ ...finance, promoBudget: Number(e.target.value) })} /></label>
          <button className="secondary" onClick={saveFinance}>Сохранить финансы</button>
        </article>
        <article>
          <h3>Промокод</h3>
          <label>Код<input value={promoDraft.code} onChange={(e) => setPromoDraft({ ...promoDraft, code: e.target.value.toUpperCase() })} /></label>
          <label>Токены<input type="number" value={promoDraft.tokens} onChange={(e) => setPromoDraft({ ...promoDraft, tokens: Number(e.target.value) })} /></label>
          <label>Активации<input type="number" value={promoDraft.activations} onChange={(e) => setPromoDraft({ ...promoDraft, activations: Number(e.target.value) })} /></label>
          <button className="secondary" onClick={createPromo}>Создать промокод</button>
        </article>
      </div>
      <div className="admin-section">
        <div className="admin-section-head">
          <h3>Настройки тарифов</h3>
          <button className="secondary" onClick={saveTariffs}>Сохранить тарифы</button>
        </div>
        <div className="admin-grid">
          {tariffKeys.map((plan) => (
            <div key={plan}>
              <strong>{plan.toUpperCase()}</strong>
              <label>Название<input value={tariffs[plan].title} onChange={(e) => setTariffs((current) => ({ ...current, [plan]: { ...current[plan], title: e.target.value } }))} /></label>
              <label>Описание<input value={tariffs[plan].note} onChange={(e) => setTariffs((current) => ({ ...current, [plan]: { ...current[plan], note: e.target.value } }))} /></label>
              <label>Цена, ₽/мес<input type="number" min="0" value={tariffs[plan].price_rub_month} onChange={(e) => setTariffs((current) => ({ ...current, [plan]: { ...current[plan], price_rub_month: Number(e.target.value) } }))} /></label>
              <label>Токенов/день<input type="number" min="0" value={tariffs[plan].daily_tokens} onChange={(e) => setTariffs((current) => ({ ...current, [plan]: { ...current[plan], daily_tokens: Number(e.target.value) } }))} /></label>
              <label>Слоты галереи<input type="number" min="0" value={tariffs[plan].gallery_slots} onChange={(e) => setTariffs((current) => ({ ...current, [plan]: { ...current[plan], gallery_slots: Number(e.target.value) } }))} /></label>
              <label>Качество в карточке<input value={tariffs[plan].quality_label} onChange={(e) => setTariffs((current) => ({ ...current, [plan]: { ...current[plan], quality_label: e.target.value } }))} /></label>
              <label>Очередь<input value={tariffs[plan].queue_label} onChange={(e) => setTariffs((current) => ({ ...current, [plan]: { ...current[plan], queue_label: e.target.value } }))} /></label>
              <label className="admin-checkline"><input type="checkbox" checked={tariffs[plan].pro_mode_enabled} onChange={(e) => setTariffs((current) => ({ ...current, [plan]: { ...current[plan], pro_mode_enabled: e.target.checked } }))} /> Режим профи</label>
              <label className="admin-checkline"><input type="checkbox" checked={tariffs[plan].video_enabled} onChange={(e) => setTariffs((current) => ({ ...current, [plan]: { ...current[plan], video_enabled: e.target.checked } }))} /> Видео</label>
              <label>Видео, шт.<input type="number" min="0" value={tariffs[plan].video_slots} onChange={(e) => setTariffs((current) => ({ ...current, [plan]: { ...current[plan], video_slots: Number(e.target.value) } }))} /></label>
              <details className="admin-resolution-picker">
                <summary>Разрешения: {tariffs[plan].allowed_resolutions.length}</summary>
                <div>
                  {resolutionOptions.map((item) => <label className="admin-checkline" key={item.id}>
                    <input type="checkbox" checked={tariffs[plan].allowed_resolutions.includes(item.id)} onChange={(e) => toggleResolution(plan, item.id, e.target.checked)} />
                    {item.label}
                  </label>)}
                </div>
              </details>
              <small>{tariffs[plan].title}: {tariffs[plan].daily_tokens} ток./день · {tariffs[plan].gallery_slots} слот(ов) · профи {tariffs[plan].pro_mode_enabled ? 'да' : 'нет'} · видео {tariffs[plan].video_enabled ? tariffs[plan].video_slots : 'нет'}</small>
            </div>
          ))}
        </div>
      </div>
      <div className="admin-section">
        <h3>Промокоды в базе</h3>
        <div className="admin-grid">
          {promos.length ? promos.map((item) => (
            <div key={item.code}>
              <strong>{item.code}</strong>
              <span>{item.tokens} ток.</span>
              <small>{item.activation_count}/{item.activation_limit} · {item.enabled ? 'активен' : 'выключен'}</small>
            </div>
          )) : <p>Промокодов пока нет.</p>}
        </div>
      </div>
    </div>
  )
}

function AdminMail() {
  const [data, setData] = useState<AnyRec | null>(null)
  const [email, setEmail] = useState('')
  const [msg, setMsg] = useState('')
  const load = useCallback(async () => setData(await adminGet<AnyRec>('/admin/mail/status-v2')), [])
  useEffect(() => {
    queueMicrotask(() => { void load() })
  }, [load])
  const sendTest = async () => {
    const result = await adminPost<AnyRec>('/admin/mail/test-v2', { email, template: 'verify_email' })
    setMsg(result?.ok ? `Тест отправлен на ${String(result.email || email)}` : 'Не удалось отправить тест')
    await load()
  }
  const summary = (data?.summary || {}) as AnyRec
  const config = (data?.config || {}) as AnyRec
  return (
    <div className="admin-section admin-mail-page">
      <div className="admin-mail-grid">
        <article className="admin-mail-card">
          <h4>Статус почты</h4>
          <p>{data?.service_ready ? 'Готово к отправке' : 'Провайдер не настроен или адаптер недоступен'}</p>
          <div className="admin-mail-flags">
            {Object.entries(config).map(([key, value]) => <span key={key} className={value ? 'ok' : 'warn'}>{key}: {value ? 'yes' : 'no'}</span>)}
          </div>
        </article>
        <article className="admin-mail-card">
          <h4>Тест отправки</h4>
          <label>Email<input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="admin@example.com" /></label>
          <button className="secondary" disabled={!email.trim()} onClick={sendTest}>Отправить тест</button>
          {msg && <small>{msg}</small>}
        </article>
        <article className="admin-mail-card">
          <h4>Сводка</h4>
          {Object.entries(summary).map(([key, value]) => <p key={key}><b>{key}</b>: {String(value)}</p>)}
        </article>
      </div>
    </div>
  )
}

function AdminLogs({ logsData }: { logsData: AnyRec | null }) {
  const [tab, setTab] = useState<'overview' | 'generation' | 'security' | 'events' | 'audit' | 'config'>('overview')
  const items = (key: string) => Array.isArray(logsData?.[key]) ? logsData[key] as AnyRec[] : []
  const row = (source: string, item: AnyRec, index: number) => {
    const title = item.event_type || item.event_name || item.action || item.id || source
    const time = item.created_at || item.completed_at || item.time || ''
    const level = String(item.severity || item.status || title).toLowerCase()
    const cls = level.includes('error') || level.includes('fail') || level.includes('critical') ? 'danger' : level.includes('warn') || level.includes('spoof') ? 'warning' : 'success'
    return (
      <div className={`admin-log-item ${cls}`} key={`${source}-${index}`}>
        <time>{time ? new Date(String(time)).toLocaleString('ru-RU') : '—'}</time>
        <em>{source}</em>
        <div>
          <strong>{String(title)}</strong>
          <span>{String(item.error || item.detail || item.ip_address || item.entity_type || item.platform || '—')}</span>
        </div>
      </div>
    )
  }
  const rows = tab === 'generation' ? items('generation_errors').map((x, i) => row('generation', x, i))
    : tab === 'security' ? items('security_events').map((x, i) => row('security', x, i))
    : tab === 'events' ? items('event_logs').map((x, i) => row('event', x, i))
    : tab === 'audit' ? items('audit_logs').map((x, i) => row('audit', x, i))
    : [...items('generation_errors').slice(0, 10).map((x, i) => row('generation', x, i)), ...items('security_events').slice(0, 10).map((x, i) => row('security', x, i)), ...items('event_logs').slice(0, 10).map((x, i) => row('event', x, i))]
  return (
    <div className="admin-section">
      <div className="admin-log-tabs">
        {[
          ['overview', 'Все'],
          ['generation', 'Генерации'],
          ['security', 'Security'],
          ['events', 'События'],
          ['audit', 'Аудит'],
          ['config', 'Config'],
        ].map(([id, label]) => <button key={id} className={tab === id ? 'active' : ''} onClick={() => setTab(id as typeof tab)}>{label}</button>)}
      </div>
      {tab === 'config' ? <details open className="admin-config-details"><summary>Сводка логов</summary><pre>{JSON.stringify(logsData, null, 2)}</pre></details> : <div className="admin-log-table">{rows.length ? rows : <p className="admin-empty-line">Событий пока нет.</p>}</div>}
    </div>
  )
}

export default function AdminApp() {
  const { status, me } = useAuthV2()
  const [authOpen, setAuthOpen] = useState(false)
  const [tab, setTab] = useState<AdminTab>('dashboard')
  const [summary, setSummary] = useState<AnyRec | null>(null)
  const [logsData, setLogsData] = useState<AnyRec | null>(null)
  const isAdmin = status === 'authed' && me?.account?.role === 'admin'

  useEffect(() => { void initAuthV2() }, [])
  useEffect(() => {
    if (!isAdmin) return
    void adminGet<AnyRec>('/admin/summary').then(setSummary)
  }, [isAdmin])
  useEffect(() => {
    if (!isAdmin || tab !== 'logs') return
    void adminGet<AnyRec>('/admin/logs-v2').then(setLogsData)
  }, [isAdmin, tab])

  if (status === 'loading') {
    return (
      <div className="app-shell admin-route-shell">
        <AuthV2Modal open={authOpen} onClose={() => setAuthOpen(false)} />
        <main className="workspace admin-workspace"><AdminAccessPage status="loading" onOpenAuth={() => setAuthOpen(true)} /></main>
      </div>
    )
  }
  if (!isAdmin) {
    return (
      <div className="app-shell admin-route-shell">
        <AuthV2Modal open={authOpen} onClose={() => setAuthOpen(false)} />
        <main className="workspace admin-workspace"><AdminAccessPage status="denied" onOpenAuth={() => setAuthOpen(true)} /></main>
      </div>
    )
  }

  const queue = Array.isArray(summary?.queue) ? summary.queue : []
  const errors = Number(summary?.errors ?? 0)
  const health = errors === 0 ? 'Стабильно' : `Ошибки генерации: ${errors}`
  const tabs: Array<[AdminTab, string]> = [
    ['dashboard', 'Дашборд'],
    ['users', 'Пользователи'],
    ['models', 'Модели'],
    ['tariffs', 'Тарифы'],
    ['mail', 'Почта'],
    ['logs', 'Логи'],
  ]

  return (
    <div className="app-shell admin-route-shell">
      {isDiagMode() && <DiagPanel />}
      <AuthV2Modal open={authOpen} onClose={() => setAuthOpen(false)} />
      <main className="workspace admin-workspace">
        <section className="admin-page">
          <div className="admin-topline">
            <button className="secondary" onClick={() => { window.location.href = '/' }}><WandSparkles size={16} />К генерации</button>
            <span className={errors === 0 ? 'admin-live-ok' : 'admin-live-warn'}>{health}</span>
            <small><Shield size={13} /> trusted admin · {me?.profile?.public_user_code || me?.internal_user_id?.slice(0, 8) || 'admin'}</small>
          </div>
          <div className="admin-kpi-strip">
            <span><b>{String(summary?.users ?? '—')}</b> пользователей</span>
            <span><b>{String(summary?.activeToday ?? '—')}</b> сегодня</span>
            <span><b>{String(summary?.generationsToday ?? '—')}</b> генераций</span>
            <span><b>{String(summary?.errors24h ?? '—')}</b> ошибок входа 24ч</span>
            <span><b>{String(queue.length)}</b> в очереди</span>
          </div>
          <div className="admin-tabbar">
            {tabs.map(([id, label]) => <button key={id} className={tab === id ? 'active' : ''} onClick={() => setTab(id)}>{label}</button>)}
          </div>
          {tab === 'dashboard' && <AdminDashboard summary={summary} />}
          {tab === 'users' && <div className="admin-section"><Suspense fallback={<div className="preview-empty">Загружаем пользователей...</div>}><AdminAnalyticsV2 /></Suspense></div>}
          {tab === 'models' && <div className="admin-section"><Suspense fallback={<div className="preview-empty">Загружаем модели...</div>}><AdminModelsV2 /></Suspense></div>}
          {tab === 'tariffs' && <AdminTokens />}
          {tab === 'mail' && <AdminMail />}
          {tab === 'logs' && <AdminLogs logsData={logsData} />}
        </section>
      </main>
    </div>
  )
}
