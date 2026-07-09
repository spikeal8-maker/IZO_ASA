// Админ → Модели v2. Provider-aware страница управления моделями/маршрутами/тарифами,
// OpenRouter и LoRA из ComfyUI. Структура по референсу admin-models-v2.html.
// Реальные данные приходят из GET /api/admin/models-page (см. backend). Тарифная матрица,
// маршруты и user-choice сохраняются через /api/admin/settings/{key}.
import { useCallback, useEffect, useMemo, useState } from 'react'

const API = (import.meta as ImportMeta & { env?: { VITE_API_BASE_URL?: string } }).env?.VITE_API_BASE_URL || '/api'
function amvFetch(path: string, init: RequestInit = {}) {
  const headers = new Headers(init.headers)
  return fetch(`${API}${path}`, { ...init, headers, credentials: 'include' })
}

type Tariff = 'free' | 'basic' | 'pro' | 'admin'
const TARIFFS: Tariff[] = ['free', 'basic', 'pro', 'admin']
type Cell = { enabled: boolean; tokenCost: number; isDefault: boolean; formula: string }
type MatrixRow = { modelProfileId: string; provider: string; displayName: string; modelId: string; tariffs: Record<Tariff, Cell> }
type Route = { routeId: string; displayName: string; icon: string; provider: string; modelProfileId: string; state: string; status: string; locked?: boolean; label?: string }
type Lora = { fileName: string; purpose: string; compatible: string[]; routes: string[]; requires: string[]; status: string }
type UserChoiceItem = { key?: string; label: string; model?: string; cost?: number | string; plan?: string; provider?: string }
type CatalogItem = { provider: string; displayName: string; modelId: string; capabilities: string[]; cost: string; margin: string; status: string }
type ProfileOption = { id: string; name: string; supportsPose?: boolean }
type ConfigStatus = {
  status?: string
  checked_at?: string
  duration_ms?: number
  comfyui?: { available?: boolean; base_url?: string }
  config_api?: { ok?: boolean; error?: string; sections?: Record<string, number> }
  models_api?: { ok?: boolean; error?: string; counts?: Record<string, number> }
  nodes?: { ok?: boolean; count?: number; required?: Record<string, boolean>; error?: string }
  active_jobs?: Array<{ id?: string; status?: string; mode?: string; provider?: string; progress?: number; message?: string }>
  cache?: { models_page_cached?: boolean; models_page_cached_age_seconds?: number | null; models_page_ttl_seconds?: number }
}
type PageData = {
  economy: { activeModels: number; routesAssigned: string; expensiveRoutes: number; priceConflicts: number }
  routes: Route[]
  userChoice: { simple: UserChoiceItem[]; pro: UserChoiceItem[] }
  matrix: MatrixRow[]
  catalog: CatalogItem[]
  loras: Lora[]
  comfyuiAvailable: boolean
  openrouter: { keyConfigured: boolean }
  comfyFiles: Record<string, unknown>
  profiles: ProfileOption[]
}

const CSS = `
.amv2{--panel:#101310;--line:rgba(255,255,255,.10);--line-strong:rgba(255,255,255,.18);--text:#f5f7ef;--muted:#a6aea3;--dim:#727b70;--lime:#eaff10;--green:#43df62;--yellow:#ffd24a;--red:#ff5c62;--radius:8px;color:var(--text);}
.amv2 h1,.amv2 h2,.amv2 h3,.amv2 p{margin:0}
.amv2 button{cursor:pointer;font:inherit}
.amv2 .state,.amv2 .provider,.amv2 .mini,.amv2 .plan{display:inline-flex;align-items:center;gap:6px;border-radius:999px;border:1px solid var(--line-strong);background:rgba(255,255,255,.045);color:var(--muted);font-size:12px;font-weight:800;padding:4px 8px;white-space:nowrap}
.amv2 .provider.local{color:var(--lime);border-color:rgba(234,255,16,.30);background:rgba(234,255,16,.07)}
.amv2 .provider.openrouter{color:#7bc3ff;border-color:rgba(85,169,255,.35);background:rgba(85,169,255,.08)}
.amv2 .state.ok{color:var(--green)}.amv2 .state.warn{color:var(--yellow)}.amv2 .state.bad{color:var(--red)}
.amv2 .ghost,.amv2 .primary,.amv2 .danger{min-height:32px;border:1px solid var(--line-strong);border-radius:var(--radius);padding:0 12px;color:var(--text);background:rgba(18,21,18,.78);font-size:13px;font-weight:800}
.amv2 .primary{color:#080a07;border-color:rgba(234,255,16,.8);background:var(--lime)}
.amv2 .danger{color:#ffe6e7;border-color:rgba(255,92,98,.28);background:rgba(255,92,98,.12)}
.amv2 .card{border:1px solid var(--line);border-radius:var(--radius);background:linear-gradient(180deg,rgba(255,255,255,.035),rgba(255,255,255,.012)),rgba(16,19,16,.92);overflow:hidden;margin-bottom:12px}
.amv2 .card-head{min-height:54px;padding:14px;display:flex;justify-content:space-between;align-items:flex-start;gap:14px;border-bottom:1px solid var(--line)}
.amv2 .card-title{font-size:15px;line-height:1.2}
.amv2 .card-note{margin-top:5px;color:var(--muted);font-size:12px;line-height:1.35}
.amv2 .page-tabs{display:flex;gap:8px;margin-bottom:12px;overflow-x:auto}
.amv2 .page-tabs button{min-height:38px;border:1px solid var(--line-strong);border-radius:var(--radius);padding:0 14px;background:rgba(255,255,255,.04);color:var(--muted);font-weight:900;white-space:nowrap}
.amv2 .page-tabs button.active{background:var(--lime);border-color:var(--lime);color:#080a07}
.amv2 .status-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;padding:12px}
.amv2 .status-card{border:1px solid var(--line);border-radius:var(--radius);background:rgba(255,255,255,.035);padding:12px;display:grid;gap:6px;align-content:start}
.amv2 .status-card strong{font-size:13px}.amv2 .status-card span{font-size:22px;font-weight:950}.amv2 .status-card small{color:var(--muted);overflow-wrap:anywhere}
.amv2 .ops-row{display:grid;grid-template-columns:minmax(220px,1fr) auto auto auto;gap:10px;padding:12px;border-top:1px solid var(--line);align-items:center}
.amv2 .job-list{padding:0 12px 12px;display:grid;gap:6px}
.amv2 .job-row{display:grid;grid-template-columns:minmax(120px,1fr) 96px 90px minmax(140px,1.2fr);gap:8px;align-items:center;border:1px solid var(--line);border-radius:var(--radius);padding:8px;background:rgba(255,255,255,.028);font-size:12px}
.amv2 .dashboard{display:grid;grid-template-columns:1fr 1.18fr .82fr;gap:12px;margin-bottom:12px}
.amv2 .metric-grid{padding:12px;display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
.amv2 .metric{border:1px solid var(--line);border-radius:var(--radius);padding:12px;background:rgba(255,255,255,.035)}
.amv2 .metric .label{color:var(--muted);font-size:12px;font-weight:800;display:block}
.amv2 .metric .value{display:block;margin-top:6px;font-size:26px;line-height:1}
.amv2 .metric .delta{margin-top:8px;color:var(--green);font-size:12px;display:block}
.amv2 .metric.warn .value,.amv2 .metric.warn .delta{color:var(--yellow)}.amv2 .metric.bad .value,.amv2 .metric.bad .delta{color:var(--red)}
.amv2 .route-list,.amv2 .user-preview{padding:12px;display:grid;gap:8px}
.amv2 .route-row{display:grid;grid-template-columns:160px 120px minmax(180px,1fr) 110px;gap:10px;align-items:center;padding:10px;border:1px solid var(--line);border-radius:var(--radius);background:rgba(255,255,255,.03)}
.amv2 .route-name{display:flex;align-items:center;gap:9px;font-size:13px;font-weight:800}
.amv2 .route-icon,.amv2 .choice-icon{width:26px;height:26px;display:grid;place-items:center;border-radius:8px;color:var(--lime);border:1px solid rgba(234,255,16,.24);background:rgba(234,255,16,.065);font-size:12px;font-weight:900}
.amv2 select,.amv2 input{width:100%;min-height:34px;border:1px solid var(--line-strong);border-radius:var(--radius);color:var(--text);background:rgba(255,255,255,.055);padding:0 10px;outline:none}
.amv2 select:focus,.amv2 input:focus{border-color:rgba(234,255,16,.72)}
.amv2 .user-mode-title{display:flex;justify-content:space-between;gap:10px;color:var(--muted);font-size:12px;font-weight:800;text-transform:uppercase;letter-spacing:.06em}
.amv2 .choice-card{display:grid;grid-template-columns:36px minmax(0,1fr) auto;align-items:center;gap:10px;padding:10px;border:1px solid var(--line);border-radius:var(--radius);background:rgba(255,255,255,.035)}
.amv2 .choice-icon{width:36px;height:36px}
.amv2 .choice-card strong{display:block;font-size:13px}.amv2 .choice-card span{color:var(--muted);font-size:12px}
.amv2 .default-mark{color:#111;background:var(--lime);border-radius:999px;padding:2px 7px;font-size:10px;font-weight:900;width:max-content}
.amv2 .grid-main{display:grid;grid-template-columns:minmax(0,1fr) 400px;gap:12px;align-items:start}
.amv2 .work-area{display:grid;gap:0;min-width:0}
.amv2 .toolbar{padding:12px;display:grid;grid-template-columns:minmax(200px,1fr) auto auto auto;gap:10px;border-bottom:1px solid var(--line)}
.amv2 .segmented{display:flex;border:1px solid var(--line-strong);border-radius:var(--radius);overflow:hidden;min-height:34px}
.amv2 .segmented button{border:0;border-right:1px solid var(--line);color:var(--muted);background:rgba(255,255,255,.035);padding:0 12px;font-weight:800;white-space:nowrap}
.amv2 .segmented button.active{color:#080a07;background:var(--lime)}
.amv2 .matrix-wrap{overflow-x:auto}
.amv2 table{width:100%;border-collapse:collapse;min-width:820px}
.amv2 th,.amv2 td{padding:10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top;font-size:12px}
.amv2 th{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.06em;background:rgba(255,255,255,.025)}
.amv2 tr.selected td{background:rgba(234,255,16,.055)}
.amv2 .model-cell{display:grid;gap:5px}.amv2 .model-name{font-size:14px;font-weight:900}.amv2 .model-id{color:var(--dim);font-size:11px;overflow-wrap:anywhere}
.amv2 .tariff-cell{display:grid;grid-template-columns:auto 1fr;gap:6px 10px;align-items:center;min-width:140px}
.amv2 .tariff-cell.off{opacity:.48}
.amv2 .toggle{position:relative;width:36px;height:20px}
.amv2 .toggle input{position:absolute;inset:0;opacity:0;cursor:pointer}
.amv2 .toggle span{position:absolute;inset:0;border:1px solid var(--line-strong);border-radius:999px;background:rgba(255,255,255,.08)}
.amv2 .toggle span::after{content:"";position:absolute;width:14px;height:14px;top:2px;left:2px;border-radius:50%;background:var(--muted);transition:.18s}
.amv2 .toggle input:checked+span{border-color:rgba(234,255,16,.45);background:rgba(234,255,16,.2)}
.amv2 .toggle input:checked+span::after{left:18px;background:var(--lime)}
.amv2 .cost-main{font-weight:900;color:var(--lime);font-size:15px}
.amv2 .cost-sub{grid-column:1/-1;color:var(--muted);font-size:11px}
.amv2 .side-panel{display:grid;gap:12px;position:sticky;top:12px}
.amv2 .editor-hero{padding:14px;display:grid;gap:12px;border-bottom:1px solid var(--line)}
.amv2 .editor-title{display:grid;grid-template-columns:46px minmax(0,1fr);gap:12px;align-items:center}
.amv2 .model-avatar{width:46px;height:46px;display:grid;place-items:center;border-radius:10px;color:var(--lime);border:1px solid rgba(234,255,16,.3);background:rgba(234,255,16,.08);font-weight:900}
.amv2 .editor-title h2{font-size:17px}.amv2 .editor-title p{margin-top:4px;color:var(--muted);font-size:12px;overflow-wrap:anywhere}
.amv2 .pill-row{display:flex;gap:8px;flex-wrap:wrap}
.amv2 .form-grid{padding:14px;display:grid;gap:12px}
.amv2 .two-col{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.amv2 .field{display:grid;gap:6px}
.amv2 label{color:var(--muted);font-size:11px;font-weight:900;text-transform:uppercase;letter-spacing:.06em}
.amv2 .price-row{display:grid;grid-template-columns:minmax(0,1fr) 64px 64px;gap:8px;align-items:center;padding:9px;border:1px solid var(--line);border-radius:var(--radius);background:rgba(255,255,255,.032)}
.amv2 .price-row strong{display:block;font-size:12px}.amv2 .price-row span{color:var(--muted);font-size:11px}
.amv2 .hint{padding:10px 12px;border:1px solid rgba(234,255,16,.18);border-radius:var(--radius);color:var(--muted);background:rgba(234,255,16,.045);font-size:12px;line-height:1.4}
.amv2 .conflict{padding:12px;display:grid;gap:8px}
.amv2 .conflict-item{display:grid;grid-template-columns:28px minmax(0,1fr) auto;gap:10px;align-items:center;padding:10px;border-radius:var(--radius);border:1px solid rgba(255,210,74,.24);background:rgba(255,210,74,.07)}
.amv2 .conflict-item .mark{width:28px;height:28px;display:grid;place-items:center;border-radius:50%;color:#161100;background:var(--yellow);font-weight:900}
.amv2 .conflict-item strong{display:block;font-size:12px}.amv2 .conflict-item span{color:var(--muted);font-size:11px}
.amv2 .lora-grid{padding:12px;display:grid;grid-template-columns:repeat(4,minmax(220px,1fr));gap:10px}
.amv2 .lora-card{border:1px solid var(--line);border-radius:var(--radius);padding:12px;background:rgba(255,255,255,.032);display:grid;gap:9px}
.amv2 .lora-card h3{font-size:13px;line-height:1.25;overflow-wrap:anywhere}
.amv2 .lora-meta{color:var(--muted);font-size:11px;line-height:1.35}
.amv2 .lora-actions{display:grid;grid-template-columns:1fr 72px;gap:8px;align-items:center}
.amv2 details{border:1px solid var(--line);border-radius:var(--radius);background:rgba(255,255,255,.025);margin-bottom:12px}
.amv2 summary{cursor:pointer;padding:13px 14px;color:var(--lime);font-weight:900}
.amv2 .advanced-grid{padding:0 14px 14px;display:grid;grid-template-columns:repeat(4,minmax(150px,1fr));gap:10px}
.amv2 .actions{display:flex;gap:8px}
.amv2 .mobile-models{display:none;padding:12px;gap:10px}
.amv2 .mobile-model{border:1px solid var(--line);border-radius:var(--radius);padding:12px;background:rgba(255,255,255,.035);display:grid;gap:10px}
@media (max-width:1360px){.amv2 .dashboard{grid-template-columns:1fr}.amv2 .metric-grid,.amv2 .lora-grid,.amv2 .status-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.amv2 .grid-main{grid-template-columns:1fr}.amv2 .side-panel{position:static}}
@media (max-width:880px){.amv2 .route-row,.amv2 .toolbar,.amv2 .ops-row,.amv2 .job-row{grid-template-columns:1fr}.amv2 .matrix-wrap{display:none}.amv2 .mobile-models{display:grid}}
@media (max-width:580px){.amv2 .metric-grid,.amv2 .two-col,.amv2 .price-row,.amv2 .lora-grid,.amv2 .advanced-grid,.amv2 .status-grid{grid-template-columns:1fr}}
`

const TARIFF_LABEL: Record<Tariff, string> = { free: 'Free', basic: 'Basic', pro: 'Pro', admin: 'Admin' }

export default function AdminModelsV2() {
  const [data, setData] = useState<PageData | null>(null)
  const [pageTab, setPageTab] = useState<'config' | 'api'>('config')
  const [configStatus, setConfigStatus] = useState<ConfigStatus | null>(null)
  const [matrix, setMatrix] = useState<MatrixRow[]>([])
  const [routes, setRoutes] = useState<Route[]>([])
  const [filter, setFilter] = useState<'all' | 'local' | 'openrouter'>('all')
  const [query, setQuery] = useState('')
  const [selected, setSelected] = useState<string>('')
  const [msg, setMsg] = useState('')
  const [err, setErr] = useState('')
  const [opsReason, setOpsReason] = useState('config api завис / ручная проверка')
  const [opsBusy, setOpsBusy] = useState(false)

  const load = useCallback(async () => {
    const [d, status] = await Promise.all([
      amvFetch('/admin/models-page').then((r) => (r.ok ? r.json() : null)).catch(() => null) as Promise<PageData | null>,
      amvFetch('/admin/config-ui/status-v2').then((r) => (r.ok ? r.json() : null)).catch(() => null) as Promise<ConfigStatus | null>,
    ])
    if (status) setConfigStatus(status)
    // Принимаем ответ только полной формы. Иначе — сообщение об ошибке, а не падение:
    // живой backend мог не содержать /api/admin/models-page или вернуть 403/500 с JSON-телом.
    const ok = !!d && Array.isArray(d.matrix) && Array.isArray(d.routes) && !!d.economy
      && !!d.userChoice && Array.isArray(d.userChoice.simple) && Array.isArray(d.userChoice.pro)
      && Array.isArray(d.catalog) && Array.isArray(d.loras) && !!d.comfyFiles && !!d.openrouter
    if (ok && d) {
      setErr(''); setData(d); setMatrix(d.matrix); setRoutes(d.routes)
      setSelected((cur) => cur || d.matrix[1]?.modelProfileId || d.matrix[0]?.modelProfileId || '')
    } else {
      setData(null)
      setErr('Не удалось загрузить страницу моделей. Нужен доступ администратора и обновлённый backend (/api/admin/models-page).')
    }
  }, [])
  useEffect(() => { queueMicrotask(() => { void load() }) }, [load])

  async function configAction(kind: 'reload' | 'interrupt') {
    const reason = opsReason.trim()
    if (!reason) { setMsg('Укажите причину операции'); return }
    setOpsBusy(true); setMsg('')
    const r = await amvFetch(`/admin/config-ui/${kind}-v2`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason }),
    }).then((x) => x.json()).catch(() => null) as { ok?: boolean; status?: ConfigStatus; detail?: string } | null
    setOpsBusy(false)
    if (r?.ok) {
      if (r.status) setConfigStatus(r.status)
      setMsg(kind === 'reload' ? 'Config UI перечитан и кэш сброшен' : 'ComfyUI interrupt отправлен')
      await load()
    } else setMsg(r?.detail || 'Операция не выполнена')
  }

  async function saveSetting(key: string, payload: unknown, label: string) {
    const r = await amvFetch(`/admin/settings/${key}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ settings: payload }) }).then((x) => x.json()).catch(() => null)
    setMsg(r?.ok ? `${label} сохранено` : `Ошибка сохранения: ${label}`)
  }
  const saveMatrix = (next: MatrixRow[]) => { setMatrix(next); void saveSetting('tariff_matrix', { matrix: next }, 'Матрица тарифов') }
  const saveRoutes = (next: Route[]) => { setRoutes(next); void saveSetting('generation_routes', { routes: next }, 'Маршруты') }

  const toggleCell = (mi: number, t: Tariff) => {
    const next = matrix.map((row, i) => i !== mi ? row : { ...row, tariffs: { ...row.tariffs, [t]: { ...row.tariffs[t], enabled: !row.tariffs[t].enabled } } })
    saveMatrix(next)
  }
  const setRouteModel = (ri: number, modelProfileId: string) => {
    const next = routes.map((r, i) => i === ri ? { ...r, modelProfileId } : r)
    saveRoutes(next)
  }

  const filtered = useMemo(() => matrix.filter((m) => {
    const okP = filter === 'all' || m.provider === filter
    const hay = `${m.displayName} ${m.modelId} ${m.provider}`.toLowerCase()
    return okP && (!query || hay.includes(query.toLowerCase()))
  }), [matrix, filter, query])
  const apiMatrix = useMemo(() => matrix.filter((m) => m.provider === 'openrouter'), [matrix])
  const apiCatalog = useMemo(() => (data?.catalog || []).filter((c) => c.provider === 'openrouter'), [data?.catalog])

  const sel = matrix.find((m) => m.modelProfileId === selected) || null
  const profiles = data?.profiles || []
  const localOptions = profiles.map((p) => ({ id: p.id, name: p.name }))
  const fmtTime = (value?: string) => value ? new Date(value).toLocaleString('ru-RU') : '—'

  if (!data) return <div className="amv2"><style>{CSS}</style><div style={{ padding: 12, display: 'grid', gap: 10 }}><p style={{ color: err ? 'var(--red)' : 'var(--muted)' }}>{err || 'Загрузка страницы моделей…'}</p>{err && <button className="ghost" style={{ width: 'max-content' }} onClick={() => void load()}>Повторить</button>}</div></div>

  return <div className="amv2">
    <style>{CSS}</style>
    {msg && <p style={{ color: 'var(--lime)', fontSize: 12, margin: '0 0 8px' }}>{msg}</p>}
    <div className="page-tabs" aria-label="Разделы моделей">
      <button className={pageTab === 'config' ? 'active' : ''} onClick={() => setPageTab('config')}>Config UI</button>
      <button className={pageTab === 'api' ? 'active' : ''} onClick={() => setPageTab('api')}>API модели</button>
    </div>

    {pageTab === 'config' && <>
    <article className="card">
      <div className="card-head">
        <div>
          <h2 className="card-title">Config UI: состояние и операции</h2>
          <p className="card-note">Наблюдение за ComfyUI config API, моделями, нодами, кэшем и зависшими задачами.</p>
        </div>
        <span className={`state ${configStatus?.status === 'ready' ? 'ok' : 'warn'}`}>{configStatus?.status || 'unknown'}</span>
      </div>
      <div className="status-grid">
        <div className="status-card">
          <strong>ComfyUI</strong>
          <span style={{ color: configStatus?.comfyui?.available ? 'var(--green)' : 'var(--red)' }}>{configStatus?.comfyui?.available ? 'online' : 'offline'}</span>
          <small>{configStatus?.comfyui?.base_url || '—'}</small>
        </div>
        <div className="status-card">
          <strong>Config API</strong>
          <span style={{ color: configStatus?.config_api?.ok ? 'var(--green)' : 'var(--red)' }}>{configStatus?.config_api?.ok ? 'ok' : 'fail'}</span>
          <small>{configStatus?.config_api?.error || Object.entries(configStatus?.config_api?.sections || {}).map(([k, v]) => `${k}: ${v}`).join(' · ') || '—'}</small>
        </div>
        <div className="status-card">
          <strong>Models API</strong>
          <span style={{ color: configStatus?.models_api?.ok ? 'var(--green)' : 'var(--red)' }}>{configStatus?.models_api?.ok ? 'ok' : 'fail'}</span>
          <small>{configStatus?.models_api?.error || Object.entries(configStatus?.models_api?.counts || {}).map(([k, v]) => `${k}: ${v}`).join(' · ') || '—'}</small>
        </div>
        <div className="status-card">
          <strong>Кэш / проверка</strong>
          <span>{configStatus?.duration_ms ?? '—'} ms</span>
          <small>{fmtTime(configStatus?.checked_at)} · cache {configStatus?.cache?.models_page_cached ? `${configStatus.cache.models_page_cached_age_seconds}s` : 'empty'}</small>
        </div>
      </div>
      <div className="ops-row">
        <input value={opsReason} onChange={(e) => setOpsReason(e.target.value)} placeholder="Причина операции для audit log" />
        <button className="ghost" disabled={opsBusy} onClick={() => void load()}>Обновить статус</button>
        <button className="primary" disabled={opsBusy} onClick={() => void configAction('reload')}>Перезапустить config UI</button>
        <button className="danger" disabled={opsBusy} onClick={() => void configAction('interrupt')}>Interrupt Comfy</button>
      </div>
      <div className="job-list">
        {(configStatus?.active_jobs || []).length ? (configStatus?.active_jobs || []).map((job) => (
          <div className="job-row" key={job.id}>
            <strong>{job.id}</strong><span>{job.status}</span><span>{job.progress ?? 0}%</span><small>{job.mode} · {job.provider} · {job.message || '—'}</small>
          </div>
        )) : <p className="card-note">Активных задач в очереди backend сейчас нет.</p>}
      </div>
    </article>

    {/* 1-3: Сводка экономики / Маршруты / Пользовательский выбор */}
    <section className="dashboard">
      <article className="card">
        <div className="card-head"><div><h2 className="card-title">Сводка экономики</h2><p className="card-note">Где модели активны, где риск себестоимости и что проверить.</p></div><span className={`state ${data.economy.priceConflicts ? 'warn' : 'ok'}`}>{data.economy.priceConflicts ? `${data.economy.priceConflicts} внимания` : 'ок'}</span></div>
        <div className="metric-grid">
          <div className="metric"><span className="label">Активные модели</span><strong className="value">{data.economy.activeModels}</strong><span className="delta">в матрице</span></div>
          <div className="metric"><span className="label">Маршруты назначены</span><strong className="value">{data.economy.routesAssigned}</strong><span className="delta">готово</span></div>
          <div className="metric warn"><span className="label">Дорогие маршруты</span><strong className="value">{data.economy.expensiveRoutes}</strong><span className="delta">OpenRouter Pro</span></div>
          <div className="metric bad"><span className="label">Конфликты цен</span><strong className="value">{data.economy.priceConflicts}</strong><span className="delta">проверить</span></div>
        </div>
      </article>

      <article className="card">
        <div className="card-head"><div><h2 className="card-title">Маршруты по умолчанию</h2><p className="card-note">Модель по умолчанию, если пользователь не выбрал вручную.</p></div></div>
        <div className="route-list">{routes.map((r, ri) => <div className="route-row" key={r.routeId}>
          <div className="route-name"><span className="route-icon">{r.icon}</span>{r.displayName}</div>
          <span className={`provider ${r.provider === 'local' ? 'local' : 'openrouter'}`}>{r.provider === 'local' ? 'Local ComfyUI' : 'OpenRouter'}</span>
          {r.routeId === 'edit_pose'
            ? <select value="flux_klein_9b" disabled title="Pose: только 9B + DWPose"><option value="flux_klein_9b">Flux 2 Klein 9B + DWPose</option><option disabled>Flux 2 Klein 4B — не поддерживает</option></select>
            : <select value={r.modelProfileId} onChange={(e) => setRouteModel(ri, e.target.value)}>{localOptions.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}</select>}
          <span className={`state ${r.status}`}>{r.state}</span>
        </div>)}</div>
      </article>

      <article className="card">
        <div className="card-head"><div><h2 className="card-title">Ноды и зависимости</h2><p className="card-note">Ключевые custom nodes для локального workflow.</p></div></div>
        <div className="user-preview">
          {Object.entries(configStatus?.nodes?.required || {}).map(([key, ok]) => <div className="choice-card" key={key}><span className="choice-icon">{ok ? '✓' : '!'}</span><div><strong>{key}</strong><span>{ok ? 'доступна' : 'не найдена'}</span></div><span className={`state ${ok ? 'ok' : 'bad'}`}>{ok ? 'ok' : 'missing'}</span></div>)}
          <p className="card-note">Всего нод: {configStatus?.nodes?.count ?? '—'}{configStatus?.nodes?.error ? ` · ${configStatus.nodes.error}` : ''}</p>
        </div>
      </article>
    </section>

    <section className="grid-main">
      <div className="work-area">
        {/* 6: Матрица тарифов */}
        <article className="card">
          <div className="card-head"><div><h2 className="card-title">Матрица доступности и списания</h2><p className="card-note">Включить модель на тарифе, цена и default. Изменения сохраняются сразу.</p></div></div>
          <div className="toolbar">
            <input type="search" placeholder="Поиск по модели, провайдеру или capability" value={query} onChange={(e) => setQuery(e.target.value)} />
            <div className="segmented">{(['all', 'local', 'openrouter'] as const).map((f) => <button key={f} className={filter === f ? 'active' : ''} onClick={() => setFilter(f)}>{f === 'all' ? 'Все' : f === 'local' ? 'Local' : 'OpenRouter'}</button>)}</div>
            <button className="ghost" onClick={() => void load()}>Обновить</button>
            <button className="ghost" onClick={() => void load()}>Синхронизировать OpenRouter</button>
          </div>
          <div className="matrix-wrap">
            <table>
              <thead><tr><th style={{ width: 240 }}>Модель</th>{TARIFFS.map((t) => <th key={t}>{TARIFF_LABEL[t]}</th>)}</tr></thead>
              <tbody>{filtered.map((m) => {
                const mi = matrix.indexOf(m)
                return <tr key={m.modelProfileId} className={selected === m.modelProfileId ? 'selected' : ''} onClick={() => setSelected(m.modelProfileId)}>
                  <td><div className="model-cell"><span className={`provider ${m.provider === 'local' ? 'local' : 'openrouter'}`}>{m.provider === 'local' ? 'Local ComfyUI' : 'OpenRouter'}</span><span className="model-name">{m.displayName}</span><span className="model-id">{m.modelId}</span></div></td>
                  {TARIFFS.map((t) => { const c = m.tariffs[t]; return <td key={t}><div className={`tariff-cell ${c.enabled ? '' : 'off'}`}>
                    <label className="toggle" onClick={(e) => e.stopPropagation()}><input type="checkbox" checked={c.enabled} onChange={() => toggleCell(mi, t)} /><span></span></label>
                    <span className="cost-main">{c.enabled ? `${c.tokenCost} ток.` : '—'}</span>
                    {c.isDefault && c.enabled ? <span className="default-mark">default</span> : <span />}
                    <span className="cost-sub">{c.formula}</span>
                  </div></td> })}
                </tr>
              })}</tbody>
            </table>
          </div>
          <div className="mobile-models">{filtered.map((m) => <article className="mobile-model" key={m.modelProfileId} onClick={() => setSelected(m.modelProfileId)}>
            <div className="model-cell"><span className={`provider ${m.provider === 'local' ? 'local' : 'openrouter'}`}>{m.provider === 'local' ? 'Local ComfyUI' : 'OpenRouter'}</span><span className="model-name">{m.displayName}</span><span className="model-id">{m.modelId}</span></div>
            <div className="actions">{TARIFFS.map((t) => <span className="mini" key={t}>{TARIFF_LABEL[t]}: {m.tariffs[t].enabled ? `${m.tariffs[t].tokenCost}т` : '—'}</span>)}</div>
            <button className="ghost" onClick={(e) => { e.stopPropagation(); setSelected(m.modelProfileId) }}>Настроить</button>
          </article>)}</div>
        </article>

        {/* 8: Глобальный каталог */}
        <article className="card">
          <div className="card-head"><div><h2 className="card-title">Глобальный каталог моделей</h2><p className="card-note">Справочник: provider, capabilities, себестоимость, статус.</p></div></div>
          <div className="matrix-wrap"><table>
            <thead><tr><th>Провайдер</th><th>Модель</th><th>Возможности</th><th>Себестоимость</th><th>Маржа</th><th>Статус</th><th>Действия</th></tr></thead>
            <tbody>{data.catalog.map((c, i) => <tr key={i}>
              <td><span className={`provider ${c.provider === 'local' ? 'local' : 'openrouter'}`}>{c.provider === 'local' ? 'Local ComfyUI' : 'OpenRouter'}</span></td>
              <td><strong>{c.displayName}</strong><br /><span className="model-id">{c.modelId}</span></td>
              <td>{c.capabilities.map((x: string) => <span className="mini" key={x} style={{ marginRight: 4 }}>{x}</span>)}</td>
              <td>{c.cost}</td><td>{c.margin}</td>
              <td><span className={`state ${c.status === 'active' ? 'ok' : 'warn'}`}>{c.status}</span></td>
              <td><button className="ghost">Тест</button></td>
            </tr>)}</tbody>
          </table></div>
        </article>

        {/* 9: LoRA из ComfyUI */}
        <article className="card">
          <div className="card-head"><div><h2 className="card-title">Доступные LoRA из ComfyUI</h2><p className="card-note">LoRA — слой поверх модели/workflow. Назначать только совместимым.</p></div><div className="actions"><button className="ghost" onClick={() => void load()}>Сканировать ComfyUI</button></div></div>
          <div className="lora-grid">{data.loras.map((l) => <article className="lora-card" key={l.fileName}>
            <span className="provider local">ComfyUI LoRA</span>
            <h3>{l.fileName}</h3>
            <p className="lora-meta">Назначение: {l.purpose}.{l.compatible.length ? ` Совместимость: ${l.compatible.join(', ')}.` : ''}{l.requires.length ? ` Требует: ${l.requires.join(', ')}.` : ''}</p>
            <div className="lora-actions"><select>{(l.routes.length ? l.routes : ['Не назначена']).map((r) => <option key={r}>{r}</option>)}</select><span className={`state ${l.status === 'active' || l.status === 'found' ? 'ok' : l.status === 'untested' ? 'warn' : 'bad'}`}>{l.status}</span></div>
          </article>)}</div>
        </article>

        {/* 11: Advanced ComfyUI files (collapsed) */}
        <details>
          <summary>Расширенные файлы ComfyUI</summary>
          <div className="advanced-grid">
            {Object.entries(data.comfyFiles).map(([k, v]) => <div className="field" key={k}><label>{k}</label><input defaultValue={String(v)} /></div>)}
          </div>
        </details>
      </div>

      {/* 7: Правая панель — настройка выбранной модели */}
      <aside className="side-panel">
        <article className="card">
          <div className="editor-hero">
            <div className="editor-title"><div className="model-avatar">{sel?.provider === 'local' ? 'LC' : 'OR'}</div><div><h2>{sel ? `${sel.provider === 'local' ? 'Local ComfyUI' : 'OpenRouter'} — ${sel.displayName}` : 'Выберите модель'}</h2><p>{sel?.modelId}</p></div></div>
            <div className="pill-row"><span className={`provider ${sel?.provider === 'local' ? 'local' : 'openrouter'}`}>{sel?.provider === 'local' ? 'Local ComfyUI' : 'OpenRouter'}</span>{sel && profiles.find((p) => p.id === sel.modelProfileId)?.supportsPose ? <span className="mini">pose</span> : null}</div>
          </div>
          <div className="form-grid">
            <div className="two-col">
              <div className="field"><label>Название для пользователя</label><input defaultValue={sel?.displayName || ''} /></div>
              <div className="field"><label>Минимальный тариф</label><select defaultValue="basic">{TARIFFS.map((t) => <option key={t} value={t}>{TARIFF_LABEL[t]}</option>)}</select></div>
            </div>
            <div className="field"><label>Правила списания (токены по режимам)</label>
              {(['Текст → Изо', 'Изо → Изо', 'Редактор', 'Редактор - поза', 'Multi-reference']).map((r, i) => <div className="price-row" key={r}><div><strong>{r}</strong><span>{r === 'Редактор - поза' ? 'DWPose + refcontrol LoRA' : 'base'}</span></div><input type="number" defaultValue={sel ? (sel.tariffs.pro.tokenCost + (i === 4 ? 3 : i === 1 ? 2 : 0)) : 0} /><input type="number" defaultValue={i === 4 ? 2 : i === 1 ? 1 : 0} title="доплата" /></div>)}
            </div>
            {sel?.provider === 'openrouter'
              ? <p className="hint">OpenRouter: model id {sel.modelId}. Хранятся capabilities, pricing, лимит референсов, last checked. {data.openrouter.keyConfigured ? 'API key настроен.' : 'OpenRouter API key не настроен.'}</p>
              : <p className="hint">Local ComfyUI: workflow + файлы (model/text encoder/VAE) + LoRA + себестоимость сервера. {sel && profiles.find((p) => p.id === sel.modelProfileId)?.supportsPose ? 'Поддерживает pose workflow.' : ''}</p>}
            <div className="two-col"><button className="danger">Отключить</button><button className="primary" onClick={() => saveMatrix(matrix)}>Сохранить модель</button></div>
          </div>
        </article>

        {/* Проверки перед публикацией */}
        <article className="card">
          <div className="card-head"><div><h2 className="card-title">Проверки перед публикацией</h2><p className="card-note">Что нельзя отдавать пользователям.</p></div></div>
          <div className="conflict">
            {!data.openrouter.keyConfigured && <div className="conflict-item"><span className="mark">!</span><div><strong>OpenRouter API key не настроен</strong><span>Cloud-модели не будут работать у пользователей.</span></div></div>}
            {data.loras.filter((l) => l.status === 'untested').map((l) => <div className="conflict-item" key={l.fileName}><span className="mark">!</span><div><strong>LoRA {l.fileName} не протестирована</strong><span>Проверьте перед включением в Pro выбор.</span></div></div>)}
            {data.economy.priceConflicts === 0 && data.openrouter.keyConfigured && <div className="conflict-item" style={{ borderColor: 'rgba(67,223,98,.24)', background: 'rgba(67,223,98,.07)' }}><span className="mark" style={{ background: 'var(--green)' }}>✓</span><div><strong>Конфликтов не найдено</strong><span>Можно публиковать.</span></div></div>}
          </div>
        </article>
      </aside>
    </section>
    </>}

    {pageTab === 'api' && <section className="grid-main">
      <div className="work-area">
        <article className="card">
          <div className="card-head">
            <div><h2 className="card-title">API модели</h2><p className="card-note">OpenRouter/API-слой отдельно от локального Config UI.</p></div>
            <span className={`state ${data.openrouter.keyConfigured ? 'ok' : 'bad'}`}>{data.openrouter.keyConfigured ? 'API key настроен' : 'нет API key'}</span>
          </div>
          <div className="user-preview">
            <div className="user-mode-title"><span>Pro/API выбор</span><span>точные модели</span></div>
            {data.userChoice.pro.filter((c) => c.provider === 'openrouter').map((c) => <div className="choice-card" key={c.label}><span className="choice-icon">OR</span><div><strong>{c.label}</strong><span>{c.provider} — {c.cost} ток.</span></div><span className="mini">API</span></div>)}
          </div>
        </article>

        <article className="card">
          <div className="card-head"><div><h2 className="card-title">Матрица API-моделей</h2><p className="card-note">Доступность и списание только для внешних API-моделей.</p></div></div>
          <div className="toolbar">
            <input type="search" placeholder="Поиск по API-модели" value={query} onChange={(e) => setQuery(e.target.value)} />
            <button className="ghost" onClick={() => void load()}>Синхронизировать OpenRouter</button>
          </div>
          <div className="matrix-wrap">
            <table>
              <thead><tr><th style={{ width: 240 }}>API модель</th>{TARIFFS.map((t) => <th key={t}>{TARIFF_LABEL[t]}</th>)}</tr></thead>
              <tbody>{apiMatrix.filter((m) => !query || `${m.displayName} ${m.modelId}`.toLowerCase().includes(query.toLowerCase())).map((m) => {
                const mi = matrix.indexOf(m)
                return <tr key={m.modelProfileId} className={selected === m.modelProfileId ? 'selected' : ''} onClick={() => setSelected(m.modelProfileId)}>
                  <td><div className="model-cell"><span className="provider openrouter">OpenRouter</span><span className="model-name">{m.displayName}</span><span className="model-id">{m.modelId}</span></div></td>
                  {TARIFFS.map((t) => { const c = m.tariffs[t]; return <td key={t}><div className={`tariff-cell ${c.enabled ? '' : 'off'}`}>
                    <label className="toggle" onClick={(e) => e.stopPropagation()}><input type="checkbox" checked={c.enabled} onChange={() => toggleCell(mi, t)} /><span></span></label>
                    <span className="cost-main">{c.enabled ? `${c.tokenCost} ток.` : '—'}</span>
                    {c.isDefault && c.enabled ? <span className="default-mark">default</span> : <span />}
                    <span className="cost-sub">{c.formula}</span>
                  </div></td> })}
                </tr>
              })}</tbody>
            </table>
          </div>
        </article>

        <article className="card">
          <div className="card-head"><div><h2 className="card-title">Каталог API</h2><p className="card-note">Справочник внешних моделей: capabilities, себестоимость, статус.</p></div></div>
          <div className="matrix-wrap"><table>
            <thead><tr><th>Провайдер</th><th>Модель</th><th>Возможности</th><th>Себестоимость</th><th>Маржа</th><th>Статус</th><th>Действия</th></tr></thead>
            <tbody>{apiCatalog.map((c, i) => <tr key={i}>
              <td><span className="provider openrouter">OpenRouter</span></td>
              <td><strong>{c.displayName}</strong><br /><span className="model-id">{c.modelId}</span></td>
              <td>{c.capabilities.map((x: string) => <span className="mini" key={x} style={{ marginRight: 4 }}>{x}</span>)}</td>
              <td>{c.cost}</td><td>{c.margin}</td>
              <td><span className={`state ${c.status === 'active' ? 'ok' : 'warn'}`}>{c.status}</span></td>
              <td><button className="ghost">Тест API</button></td>
            </tr>)}</tbody>
          </table></div>
        </article>
      </div>

      <aside className="side-panel">
        <article className="card">
          <div className="editor-hero">
            <div className="editor-title"><div className="model-avatar">API</div><div><h2>{sel?.provider === 'openrouter' ? sel.displayName : 'Выберите API-модель'}</h2><p>{sel?.provider === 'openrouter' ? sel.modelId : 'OpenRouter / внешние модели'}</p></div></div>
            <div className="pill-row"><span className="provider openrouter">OpenRouter</span>{data.openrouter.keyConfigured ? <span className="state ok">key ok</span> : <span className="state bad">no key</span>}</div>
          </div>
          <div className="form-grid">
            {sel?.provider === 'openrouter' ? <p className="hint">OpenRouter: model id {sel.modelId}. Настройки тарифа сохраняются в матрицу. API key настраивается в окружении backend и не показывается в UI.</p> : <p className="hint">Откройте строку API-модели слева, чтобы редактировать доступность и стоимость.</p>}
            <button className="primary" onClick={() => saveMatrix(matrix)}>Сохранить API-модели</button>
          </div>
        </article>
      </aside>
    </section>}
  </div>
}
