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
type Cell = { enabled: boolean; tokenCost: number; isDefault: boolean; formula: string }
type MatrixRow = { modelProfileId: string; provider: string; displayName: string; modelId: string; tariffs: Record<Tariff, Cell> }
type Route = { routeId: string; displayName: string; icon: string; provider: string; modelProfileId: string; state: string; status: string; locked?: boolean; label?: string }
type Lora = {
  fileName: string; purpose: string; compatible: string[]; routes: string[]; requires: string[]; status: string
  kind?: string; recommended?: boolean; installed?: boolean; forKlein?: boolean
}
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

type ProductMode = {
  id: string
  title: string
  local: string
  apiNeed: string
  note: string
}

type ApiCandidate = {
  mode: string
  tier: 'cheap' | 'balanced' | 'premium' | 'special'
  model: string
  modelId: string
  capabilities: string
  price: string
  estimateUsd: number | null
  estimateRub: number | null
  risk: 'low' | 'mid' | 'high'
  recommendation: string
}

const USD_RUB = 90
const moneyRub = (value: number | null) => value == null ? 'usage' : `~${value.toFixed(2)} ₽`
const moneyUsd = (value: number | null) => value == null ? 'usage' : `$${value.toFixed(3)}`

const PRODUCT_MODES: ProductMode[] = [
  { id: 'text_to_image', title: 'Текст -> изображение', local: 'Flux 2 Klein 4B', apiNeed: 'дешевый txt2img, 1MP, быстрый fallback', note: 'Основной массовый режим, цена критична.' },
  { id: 'image_to_image', title: 'Изображение -> изображение', local: 'Flux 2 Klein 4B', apiNeed: 'image input + prompt + output image', note: 'Нужны reference/input image и управляемая сила изменения.' },
  { id: 'edit', title: 'Редактор / multi-reference', local: 'Flux 2 Klein 9B', apiNeed: 'несколько input_references, сохранение композиции', note: 'Самый сложный режим для API: важны референсы.' },
  { id: 'paint', title: 'Рисунок / sketch', local: 'Flux 2 Klein edit workflow', apiNeed: 'image input + prompt, хорошо понимает скетч', note: 'Можно вести через image-to-image модели.' },
  { id: 'inpaint', title: 'Inpaint', local: 'Flux 2 Klein inpaint workflow', apiNeed: 'маска/редактирование области', note: 'Нужна отдельная проверка: не все OpenRouter image-модели принимают маску.' },
  { id: 'outpaint', title: 'Outpaint', local: 'Flux 2 Klein outpaint workflow', apiNeed: 'расширение кадра / aspect ratio', note: 'Кандидаты с aspect_ratio и reference image.' },
  { id: 'faceswap', title: 'Лицо -> изображение', local: 'Flux 2 Klein 9B + BFS LoRA', apiNeed: 'identity/reference consistency', note: 'API-кандидаты только после ручного теста приватности и качества.' },
  { id: 'remove_background', title: 'Удаление фона', local: 'локальный workflow/утилита', apiNeed: 'transparent/background параметр', note: 'Лучше держать отдельно от генеративных моделей.' },
]

const API_CANDIDATES: ApiCandidate[] = [
  { mode: 'text_to_image', tier: 'cheap', model: 'FLUX.2 Klein 4B', modelId: 'black-forest-labs/flux.2-klein-4b', capabilities: 'text+image -> image, seed, input_references', price: '$0.014 / MP output', estimateUsd: 0.014, estimateRub: 0.014 * USD_RUB, risk: 'low', recommendation: 'Лучший первый платный baseline: похож на локальную модель, понятная цена за 1MP.' },
  { mode: 'text_to_image', tier: 'balanced', model: 'FLUX.2 Pro', modelId: 'black-forest-labs/flux.2-pro', capabilities: 'text+image -> image, seed, input_references', price: '$0.030 / MP output', estimateUsd: 0.03, estimateRub: 0.03 * USD_RUB, risk: 'mid', recommendation: 'Качество выше, можно включать для Pro после теста.' },
  { mode: 'image_to_image', tier: 'balanced', model: 'FLUX.2 Flex', modelId: 'black-forest-labs/flux.2-flex', capabilities: 'input_image + output_image, seed, input_references', price: '$0.060 / MP input + $0.060 / MP output', estimateUsd: 0.12, estimateRub: 0.12 * USD_RUB, risk: 'high', recommendation: 'Дорого для массового режима, но честный кандидат для i2i/edit.' },
  { mode: 'edit', tier: 'premium', model: 'GPT Image 1 Mini', modelId: 'openai/gpt-image-1-mini', capabilities: 'quality, background, input_references, compression', price: '$0.000008 / output token', estimateUsd: null, estimateRub: null, risk: 'mid', recommendation: 'Кандидат для редактирования; фактическая цена берется из usage/cost после тестового запроса.' },
  { mode: 'edit', tier: 'premium', model: 'GPT Image 2', modelId: 'openai/gpt-image-2', capabilities: 'quality, background, input_references, compression', price: '$0.000030 / output token', estimateUsd: null, estimateRub: null, risk: 'high', recommendation: 'Премиум-качество, но пока нельзя обещать цену 1MP без тестового usage.' },
  { mode: 'paint', tier: 'cheap', model: 'Gemini 2.5 Flash Image', modelId: 'google/gemini-2.5-flash-image', capabilities: 'image+text -> image+text, aspect_ratio, input_references', price: '$0.0000003 input token + $0.0000025 output token', estimateUsd: null, estimateRub: null, risk: 'mid', recommendation: 'Хороший дешевый кандидат для sketch/i2i, но нужен тест цены по usage.' },
  { mode: 'outpaint', tier: 'balanced', model: 'Gemini 3.1 Flash Lite Image', modelId: 'google/gemini-3.1-flash-lite-image', capabilities: 'resolution, aspect_ratio, input_references', price: '$0.000030 / output token', estimateUsd: null, estimateRub: null, risk: 'mid', recommendation: 'Подходит для экспериментов с aspect ratio и расширением кадра.' },
  { mode: 'faceswap', tier: 'premium', model: 'Gemini 3 Pro Image', modelId: 'google/gemini-3-pro-image', capabilities: 'image+text -> image+text, resolution, input_references', price: '$0.000002 input token + $0.000120 output token', estimateUsd: null, estimateRub: null, risk: 'high', recommendation: 'Только после ручного теста identity consistency и стоимости.' },
  { mode: 'text_to_image', tier: 'special', model: 'Recraft V4.1', modelId: 'recraft/recraft-v4.1', capabilities: 'text+image -> image, input_references', price: '$0.035 / image', estimateUsd: 0.035, estimateRub: 0.035 * USD_RUB, risk: 'mid', recommendation: 'Хорош для дизайна/постеров/текста, не основной универсальный генератор.' },
  { mode: 'text_to_image', tier: 'special', model: 'Seedream 4.5', modelId: 'bytedance-seed/seedream-4.5', capabilities: 'resolution, aspect_ratio, input_references, seed', price: '$0.040 / image', estimateUsd: 0.04, estimateRub: 0.04 * USD_RUB, risk: 'mid', recommendation: 'Кандидат для красивого txt2img, дороже Flux Klein 4B.' },
]

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
.amv2 .api-key-panel{padding:12px;display:grid;grid-template-columns:1.1fr 1.4fr;gap:12px;border-bottom:1px solid var(--line)}
.amv2 .api-key-box{border:1px solid var(--line);border-radius:var(--radius);padding:12px;background:rgba(255,255,255,.032);display:grid;gap:8px;align-content:start}
.amv2 .api-key-box input{font-family:ui-monospace,SFMono-Regular,Consolas,monospace}
.amv2 .mode-board{padding:12px;display:grid;grid-template-columns:repeat(4,minmax(180px,1fr));gap:10px}
.amv2 .mode-card{border:1px solid var(--line);border-radius:var(--radius);padding:12px;background:rgba(255,255,255,.032);display:grid;gap:8px;align-content:start}
.amv2 .mode-card strong{font-size:13px}.amv2 .mode-card span{color:var(--muted);font-size:12px;line-height:1.35}
.amv2 .api-table td,.amv2 .api-table th{vertical-align:top}
.amv2 .money{font-weight:950;color:var(--lime);white-space:nowrap}
.amv2 .risk-low{color:var(--green)}.amv2 .risk-mid{color:var(--yellow)}.amv2 .risk-high{color:var(--red)}
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
@media (max-width:1360px){.amv2 .dashboard{grid-template-columns:1fr}.amv2 .metric-grid,.amv2 .lora-grid,.amv2 .status-grid,.amv2 .mode-board{grid-template-columns:repeat(2,minmax(0,1fr))}.amv2 .grid-main{grid-template-columns:1fr}.amv2 .side-panel{position:static}}
@media (max-width:880px){.amv2 .route-row,.amv2 .toolbar,.amv2 .ops-row,.amv2 .job-row,.amv2 .api-key-panel{grid-template-columns:1fr}.amv2 .matrix-wrap{overflow-x:auto}.amv2 .matrix-wrap table{min-width:980px}.amv2 .mobile-models{display:grid}}
@media (max-width:580px){.amv2 .metric-grid,.amv2 .two-col,.amv2 .price-row,.amv2 .lora-grid,.amv2 .advanced-grid,.amv2 .status-grid,.amv2 .mode-board{grid-template-columns:1fr}}
`

export default function AdminModelsV2() {
  const [data, setData] = useState<PageData | null>(null)
  const [pageTab, setPageTab] = useState<'config' | 'api'>('config')
  const [configStatus, setConfigStatus] = useState<ConfigStatus | null>(null)
  const [routes, setRoutes] = useState<Route[]>([])
  const [query, setQuery] = useState('')
  const [msg, setMsg] = useState('')
  const [err, setErr] = useState('')
  const [configErr, setConfigErr] = useState('')
  const [opsReason, setOpsReason] = useState('config api завис / ручная проверка')
  const [opsBusy, setOpsBusy] = useState(false)

  const load = useCallback(async () => {
    const [d, status] = await Promise.all([
      amvFetch('/admin/models-page').then((r) => (r.ok ? r.json() : null)).catch(() => null) as Promise<PageData | null>,
      amvFetch('/admin/config-ui/status-v2').then(async (r) => {
        if (r.ok) { setConfigErr(''); return await r.json() as ConfigStatus }
        setConfigErr(`/api/admin/config-ui/status-v2 -> HTTP ${r.status}`)
        return null
      }).catch((e) => { setConfigErr(e instanceof Error ? e.message : 'config status недоступен'); return null }) as Promise<ConfigStatus | null>,
    ])
    if (status) setConfigStatus(status)
    // Принимаем ответ только полной формы. Иначе — сообщение об ошибке, а не падение:
    // живой backend мог не содержать /api/admin/models-page или вернуть 403/500 с JSON-телом.
    const ok = !!d && Array.isArray(d.matrix) && Array.isArray(d.routes) && !!d.economy
      && !!d.userChoice && Array.isArray(d.userChoice.simple) && Array.isArray(d.userChoice.pro)
      && Array.isArray(d.catalog) && Array.isArray(d.loras) && !!d.comfyFiles && !!d.openrouter
    if (ok && d) {
      setErr(''); setData(d); setRoutes(d.routes)
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
  const saveRoutes = (next: Route[]) => { setRoutes(next); void saveSetting('generation_routes', { routes: next }, 'Маршруты') }

  const setRouteModel = (ri: number, modelProfileId: string) => {
    const next = routes.map((r, i) => i === ri ? { ...r, modelProfileId } : r)
    saveRoutes(next)
  }

  const kleinLoras = useMemo(() => (data?.loras || []).filter((l) => l.forKlein !== false), [data?.loras])
  const otherLoras = useMemo(() => (data?.loras || []).filter((l) => l.forKlein === false), [data?.loras])

  const profiles = data?.profiles || []
  const localOptions = profiles.map((p) => ({ id: p.id, name: p.name }))
  const fmtTime = (value?: string) => value ? new Date(value).toLocaleString('ru-RU') : '—'
  const fmtState = (ok?: boolean) => configErr ? 'unknown' : ok ? 'ok' : 'fail'
  const statusColor = (ok?: boolean) => configErr ? 'var(--yellow)' : ok ? 'var(--green)' : 'var(--red)'

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
        <span className={`state ${configStatus?.status === 'ready' ? 'ok' : 'warn'}`}>{configErr ? 'status api fail' : configStatus?.status || 'unknown'}</span>
      </div>
      {configErr && <p className="hint" style={{ margin: '12px 12px 0', color: 'var(--yellow)' }}>Статус Config UI не загрузился: {configErr}. Если ComfyUI открыт, перезапустите backend/dev-сервер, чтобы он подхватил новые endpoint'ы.</p>}
      <div className="status-grid">
        <div className="status-card">
          <strong>ComfyUI</strong>
          <span style={{ color: statusColor(configStatus?.comfyui?.available) }}>{configErr ? 'unknown' : configStatus?.comfyui?.available ? 'online' : 'offline'}</span>
          <small>{configStatus?.comfyui?.base_url || '—'}</small>
        </div>
        <div className="status-card">
          <strong>Config API</strong>
          <span style={{ color: statusColor(configStatus?.config_api?.ok) }}>{fmtState(configStatus?.config_api?.ok)}</span>
          <small>{configStatus?.config_api?.error || Object.entries(configStatus?.config_api?.sections || {}).map(([k, v]) => `${k}: ${v}`).join(' · ') || '—'}</small>
        </div>
        <div className="status-card">
          <strong>Models API</strong>
          <span style={{ color: statusColor(configStatus?.models_api?.ok) }}>{fmtState(configStatus?.models_api?.ok)}</span>
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

    <article className="card">
      <div className="card-head">
        <div><h2 className="card-title">Доступные LoRA из ComfyUI</h2><p className="card-note">Только локальные LoRA и совместимость с Flux 2 Klein 4B/9B. API-модели здесь больше не смешиваются.</p></div>
        <div className="actions"><button className="ghost" onClick={() => void load()}>Сканировать ComfyUI</button></div>
      </div>
      <div className="lora-grid">{kleinLoras.map((l) => <article className="lora-card" key={l.fileName}>
        <span className={`provider ${l.installed === false ? 'openrouter' : 'local'}`}>{l.installed === false ? 'Нужно добавить' : 'Klein LoRA'}</span>
        <h3>{l.fileName}</h3>
        <p className="lora-meta">Назначение: {l.purpose}.{l.compatible.length ? ` Совместимость: ${l.compatible.join(', ')}.` : ''}{l.requires.length ? ` Требует: ${l.requires.join(', ')}.` : ''}</p>
        <div className="lora-actions"><select>{(l.routes.length ? l.routes : ['Не назначена']).map((r) => <option key={r}>{r}</option>)}</select><span className={`state ${l.status === 'active' || l.status === 'found' ? 'ok' : l.status === 'untested' ? 'warn' : 'bad'}`}>{l.status}</span></div>
      </article>)}</div>
      {otherLoras.length > 0 && <div className="hint" style={{ margin: '0 12px 12px' }}>Не используются в Flux Klein: {otherLoras.map((l) => l.fileName).join(', ')}</div>}
    </article>

    <details>
      <summary>Расширенные файлы ComfyUI</summary>
      <div className="advanced-grid">
        {Object.entries(data.comfyFiles).map(([k, v]) => <div className="field" key={k}><label>{k}</label><input defaultValue={String(v)} /></div>)}
      </div>
    </details>
    </>}

    {pageTab === 'api' && <>
      <article className="card">
        <div className="card-head">
          <div><h2 className="card-title">API модели: OpenRouter планирование</h2><p className="card-note">Первый рабочий слой: какие платные image-модели подходят под режимы генератора, сколько они примерно стоят, где нужен тест.</p></div>
          <span className={`state ${data.openrouter.keyConfigured ? 'ok' : 'bad'}`}>{data.openrouter.keyConfigured ? 'OPENROUTER_API_KEY есть' : 'нет OPENROUTER_API_KEY'}</span>
        </div>
        <div className="api-key-panel">
          <div className="api-key-box">
            <strong>Ключ OpenRouter</strong>
            <input type="password" placeholder="sk-or-... пока не сохраняется из UI" disabled />
            <small>Безопасное сохранение ключа лучше делать отдельным backend-шагом: шифрование/secret storage/audit. Сейчас backend проверяет переменную окружения <b>OPENROUTER_API_KEY</b>.</small>
          </div>
          <div className="api-key-box">
            <strong>Что уже понятно</strong>
            <small>OpenRouter image API отдает список моделей через /api/v1/images/models. Для части моделей цена фиксирована за megapixel/image, для token-billed моделей точная стоимость должна браться из usage/cost после тестового запроса.</small>
            <span className="mini">курс для планирования: $1 = {USD_RUB} ₽</span>
          </div>
        </div>
      </article>

      <article className="card">
        <div className="card-head"><div><h2 className="card-title">Режимы генератора - что нужно от API</h2><p className="card-note">Это карта продукта: сначала режимы, потом модели. Не наоборот.</p></div></div>
        <div className="mode-board">
          {PRODUCT_MODES.map((m) => <div className="mode-card" key={m.id}>
            <strong>{m.title}</strong>
            <span>Локально: {m.local}</span>
            <span>API нужно: {m.apiNeed}</span>
            <small>{m.note}</small>
          </div>)}
        </div>
      </article>

      <article className="card">
        <div className="card-head">
          <div><h2 className="card-title">Кандидаты OpenRouter по режимам</h2><p className="card-note">Таблица для следующего шага: включатели, лимиты и тестовые запросы. Пока ничего не включает пользователям автоматически.</p></div>
        </div>
        <div className="toolbar">
          <input type="search" placeholder="Поиск по режиму, модели, цене" value={query} onChange={(e) => setQuery(e.target.value)} />
          <button className="ghost" onClick={() => setQuery('')}>Сбросить</button>
        </div>
        <div className="matrix-wrap">
          <table className="api-table">
            <thead><tr><th>Режим</th><th>Уровень</th><th>Модель</th><th>Capabilities</th><th>Цена OpenRouter</th><th>Оценка 1MP</th><th>Риск</th><th>Рекомендация</th></tr></thead>
            <tbody>{API_CANDIDATES.filter((c) => {
              const hay = `${c.mode} ${c.tier} ${c.model} ${c.modelId} ${c.price} ${c.recommendation}`.toLowerCase()
              return !query || hay.includes(query.toLowerCase())
            }).map((c) => <tr key={`${c.mode}-${c.modelId}`}>
              <td><strong>{PRODUCT_MODES.find((m) => m.id === c.mode)?.title || c.mode}</strong><br /><span className="model-id">{c.mode}</span></td>
              <td><span className="mini">{c.tier}</span></td>
              <td><strong>{c.model}</strong><br /><span className="model-id">{c.modelId}</span></td>
              <td>{c.capabilities}</td>
              <td>{c.price}</td>
              <td><span className="money">{moneyUsd(c.estimateUsd)}</span><br /><small>{moneyRub(c.estimateRub)}</small></td>
              <td><strong className={`risk-${c.risk}`}>{c.risk}</strong></td>
              <td>{c.recommendation}</td>
            </tr>)}</tbody>
          </table>
        </div>
      </article>

      <article className="card">
        <div className="card-head"><div><h2 className="card-title">Локальная база для сравнения</h2><p className="card-note">То, с чем сравниваем платные API-модели.</p></div></div>
        <div className="mode-board">
          <div className="mode-card"><strong>Локальный Flux 2 Klein 4B</strong><span>Массовый бесплатный txt2img/i2i.</span><span>OpenRouter аналог: black-forest-labs/flux.2-klein-4b = $0.014/MP (~{(0.014 * USD_RUB).toFixed(2)} ₽).</span><small>Локальная себестоимость у нас пока не посчитана: нужен расчет электричество/GPU/амортизация.</small></div>
          <div className="mode-card"><strong>Локальный Flux 2 Klein 9B</strong><span>Редактор, лицо, pose через DWPose + LoRA.</span><span>API-кандидаты дороже и требуют тестов на reference consistency.</span><small>Этот локальный слой должен оставаться в Config UI, а не в API-моделях.</small></div>
        </div>
      </article>
    </>}
  </div>
}
