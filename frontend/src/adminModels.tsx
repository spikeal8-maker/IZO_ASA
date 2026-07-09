// Админ → Модели v2. Provider-aware страница управления моделями/маршрутами/тарифами,
// OpenRouter и LoRA из ComfyUI. Структура по референсу admin-models-v2.html.
// Реальные данные приходят из GET /api/admin/models-page (см. backend). Тарифная матрица,
// маршруты и user-choice сохраняются через /api/admin/settings/{key}.
import { Fragment, useCallback, useEffect, useMemo, useState } from 'react'

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
  openrouter: {
    keyConfigured: boolean
    status?: { ok?: boolean; configured?: boolean; source?: string; status_code?: number; error?: unknown; data?: Record<string, unknown>; credits?: Record<string, unknown> }
    usage?: {
      pricedImages?: number
      totalCostUsd?: number
      avgCostUsd?: number | null
      avgCostPerMpUsd?: number | null
      lastCostUsd?: number | null
      models?: Array<Record<string, unknown>>
      modes?: Array<Record<string, unknown>>
    }
    config?: OpenRouterConfig
    exchange?: { rate?: number | null; source?: string; sourceUrl?: string; sourceDate?: string; fetchedAt?: string; cache?: string; error?: string }
  }
  comfyFiles: Record<string, unknown>
  profiles: ProfileOption[]
}
type OpenRouterConfig = { enabled?: Record<string, string[]>; defaults?: Record<string, string> }
type OpenRouterTestResult = { image?: { url?: string; thumbnailUrl?: string }; costUsd?: number | null; model?: string; usage?: Record<string, unknown> }

const USD_FEE_RATE = 0.30
const TOKEN_RUB = 5
type ApiImageModel = {
  id: string; name: string; provider: string; input: string; output: string; params: string; pricing: string
  mpUsd?: number; imageUsd?: number; token?: boolean; tiered?: boolean
}
type ApiSortKey = 'price' | 'name' | 'provider'
type ApiSortState = { key: ApiSortKey; dir: 'asc' | 'desc' }
type ApiModeSection = {
  id: string
  title: string
  local: string
  note: string
  filter: (m: ApiImageModel) => boolean
}

const OPENROUTER_IMAGE_MODELS: ApiImageModel[] = [
  { id: 'google/gemini-3.1-flash-lite-image', name: 'Google: Nano Banana 2 Lite (Gemini 3.1 Flash Lite Image)', provider: 'Google Vertex', input: 'image+text', output: 'image+text', params: 'resolution, aspect_ratio, n, input_references', pricing: 'output_image: $0.00003/token', token: true },
  { id: 'openai/gpt-image-2', name: 'OpenAI: GPT Image 2', provider: 'OpenAI', input: 'text+image', output: 'image', params: 'quality, background, n, input_references, output_compression', pricing: 'output_image: $0.00003/token', token: true },
  { id: 'openai/gpt-image-1-mini', name: 'OpenAI: GPT Image 1 Mini', provider: 'OpenAI', input: 'text+image', output: 'image', params: 'quality, background, n, input_references, output_compression', pricing: 'output_image: $0.000008/token', token: true },
  { id: 'openai/gpt-image-1', name: 'OpenAI: GPT Image 1', provider: 'OpenAI', input: 'text+image', output: 'image', params: 'quality, background, n, input_references, output_compression', pricing: 'output_image: $0.00004/token', token: true },
  { id: 'google/gemini-3.1-flash-image', name: 'Google: Nano Banana 2 (Gemini 3.1 Flash Image)', provider: 'Google Vertex', input: 'image+text', output: 'image+text', params: 'resolution, aspect_ratio, n, input_references', pricing: 'output_image: $0.00006/token', token: true },
  { id: 'google/gemini-3-pro-image', name: 'Google: Nano Banana Pro (Gemini 3 Pro Image)', provider: 'Google Vertex', input: 'image+text', output: 'image+text', params: 'resolution, aspect_ratio, n, input_references', pricing: 'input_image: $0.000002/token + output_image: $0.00012/token', token: true },
  { id: 'sourceful/riverflow-v2.5-pro', name: 'Sourceful: Riverflow V2.5 Pro', provider: 'Sourceful', input: 'text+image', output: 'image', params: 'resolution, output_format, background, n, input_references', pricing: 'output_image: $0.13/image + $0.15/image + $0.17/image', tiered: true },
  { id: 'sourceful/riverflow-v2.5-fast', name: 'Sourceful: Riverflow V2.5 Fast', provider: 'Sourceful', input: 'text+image', output: 'image', params: 'resolution, output_format, background, n, input_references', pricing: 'output_image: $0.019/image + $0.021/image', tiered: true },
  { id: 'microsoft/mai-image-2.5', name: 'Microsoft: MAI-Image-2.5', provider: 'Azure', input: 'text+image', output: 'image', params: 'aspect_ratio, n, input_references', pricing: 'input_text/image/output_image token pricing', token: true },
  { id: 'x-ai/grok-imagine-image-quality', name: 'xAI: Grok Imagine Image Quality', provider: 'xAI', input: 'text+image', output: 'image', params: 'resolution, aspect_ratio, n, input_references', pricing: 'input_image: $0.01/image + output_image: $0.05/$0.07 image', tiered: true },
  { id: 'recraft/recraft-v4.1-pro-vector', name: 'Recraft: Recraft V4.1 Pro Vector', provider: 'Recraft', input: 'text+image', output: 'image', params: 'n, input_references', pricing: 'output_image: $0.3/image', imageUsd: 0.3 },
  { id: 'recraft/recraft-v4.1-vector', name: 'Recraft: Recraft V4.1 Vector', provider: 'Recraft', input: 'text+image', output: 'image', params: 'n, input_references', pricing: 'output_image: $0.08/image', imageUsd: 0.08 },
  { id: 'recraft/recraft-v4.1-utility-pro', name: 'Recraft: Recraft V4.1 Utility Pro', provider: 'Recraft', input: 'text+image', output: 'image', params: 'n, input_references', pricing: 'output_image: $0.21/image', imageUsd: 0.21 },
  { id: 'recraft/recraft-v4.1-utility', name: 'Recraft: Recraft V4.1 Utility', provider: 'Recraft', input: 'text+image', output: 'image', params: 'n, input_references', pricing: 'output_image: $0.035/image', imageUsd: 0.035 },
  { id: 'recraft/recraft-v4.1-pro', name: 'Recraft: Recraft V4.1 Pro', provider: 'Recraft', input: 'text+image', output: 'image', params: 'n, input_references', pricing: 'output_image: $0.21/image', imageUsd: 0.21 },
  { id: 'recraft/recraft-v4.1', name: 'Recraft: Recraft V4.1', provider: 'Recraft', input: 'text+image', output: 'image', params: 'n, input_references', pricing: 'output_image: $0.035/image', imageUsd: 0.035 },
  { id: 'recraft/recraft-v4-pro-vector', name: 'Recraft: Recraft V4 Pro Vector', provider: 'Recraft', input: 'text+image', output: 'image', params: 'n, input_references', pricing: 'output_image: $0.3/image', imageUsd: 0.3 },
  { id: 'recraft/recraft-v4-vector', name: 'Recraft: Recraft V4 Vector', provider: 'Recraft', input: 'text+image', output: 'image', params: 'n, input_references', pricing: 'output_image: $0.08/image', imageUsd: 0.08 },
  { id: 'recraft/recraft-v4-pro', name: 'Recraft: Recraft V4 Pro', provider: 'Recraft', input: 'text+image', output: 'image', params: 'n, input_references', pricing: 'output_image: $0.25/image', imageUsd: 0.25 },
  { id: 'recraft/recraft-v4', name: 'Recraft: Recraft V4', provider: 'Recraft', input: 'text+image', output: 'image', params: 'n, input_references', pricing: 'output_image: $0.04/image', imageUsd: 0.04 },
  { id: 'recraft/recraft-v3', name: 'Recraft: Recraft V3', provider: 'Recraft', input: 'text+image', output: 'image', params: 'n, input_references', pricing: 'output_image: $0.04/image', imageUsd: 0.04 },
  { id: 'openai/gpt-5.4-image-2', name: 'OpenAI: GPT-5.4 Image 2', provider: 'OpenAI', input: 'image+text+file', output: 'image+text', params: 'quality, background, n, input_references, output_compression', pricing: 'output_image: $0.00003/token', token: true },
  { id: 'google/gemini-3.1-flash-image-preview', name: 'Google: Nano Banana 2 (Gemini 3.1 Flash Image Preview)', provider: 'Google Vertex', input: 'image+text', output: 'image+text', params: 'resolution, aspect_ratio, n, input_references', pricing: 'output_image: $0.00006/token', token: true },
  { id: 'sourceful/riverflow-v2-pro', name: 'Sourceful: Riverflow V2 Pro', provider: 'Sourceful', input: 'text+image', output: 'image', params: 'resolution, n, input_references', pricing: 'tiered image pricing + input_reference fee', tiered: true },
  { id: 'sourceful/riverflow-v2-fast', name: 'Sourceful: Riverflow V2 Fast', provider: 'Sourceful', input: 'text+image', output: 'image', params: 'resolution, n, input_references', pricing: 'tiered image pricing + input_reference fee', tiered: true },
  { id: 'black-forest-labs/flux.2-klein-4b', name: 'Black Forest Labs: FLUX.2 Klein 4B', provider: 'Black Forest Labs', input: 'text+image', output: 'image', params: 'output_format, n, input_references, seed', pricing: 'output_image: $0.014/megapixel', mpUsd: 0.014 },
  { id: 'bytedance-seed/seedream-4.5', name: 'ByteDance Seed: Seedream 4.5', provider: 'Seed', input: 'image+text', output: 'image', params: 'resolution, aspect_ratio, n, input_references, seed', pricing: 'output_image: $0.04/image', imageUsd: 0.04 },
  { id: 'black-forest-labs/flux.2-max', name: 'Black Forest Labs: FLUX.2 Max', provider: 'Black Forest Labs', input: 'text+image', output: 'image', params: 'output_format, n, input_references, seed', pricing: 'output_image: $0.07/megapixel', mpUsd: 0.07 },
  { id: 'sourceful/riverflow-v2-max-preview', name: 'Sourceful: Riverflow V2 Max Preview', provider: '-', input: 'text+image', output: 'image', params: '', pricing: 'нет endpoint pricing' },
  { id: 'sourceful/riverflow-v2-standard-preview', name: 'Sourceful: Riverflow V2 Standard Preview', provider: '-', input: 'text+image', output: 'image', params: '', pricing: 'нет endpoint pricing' },
  { id: 'sourceful/riverflow-v2-fast-preview', name: 'Sourceful: Riverflow V2 Fast Preview', provider: '-', input: 'text+image', output: 'image', params: '', pricing: 'нет endpoint pricing' },
  { id: 'black-forest-labs/flux.2-flex', name: 'Black Forest Labs: FLUX.2 Flex', provider: 'Black Forest Labs', input: 'text+image', output: 'image', params: 'output_format, n, input_references, seed', pricing: 'input_image: $0.06/megapixel + output_image: $0.06/megapixel', mpUsd: 0.12 },
  { id: 'black-forest-labs/flux.2-pro', name: 'Black Forest Labs: FLUX.2 Pro', provider: 'Black Forest Labs', input: 'text+image', output: 'image', params: 'output_format, n, input_references, seed', pricing: 'output_image: $0.03/megapixel', mpUsd: 0.03 },
  { id: 'google/gemini-3-pro-image-preview', name: 'Google: Nano Banana Pro (Gemini 3 Pro Image Preview)', provider: 'Google Vertex', input: 'image+text', output: 'image+text', params: 'resolution, aspect_ratio, n, input_references', pricing: 'input_image/output_image token pricing', token: true },
  { id: 'openai/gpt-5-image-mini', name: 'OpenAI: GPT-5 Image Mini', provider: 'OpenAI', input: 'file+image+text', output: 'image+text', params: 'quality, background, n, input_references, output_compression', pricing: 'output_image: $0.000008/token', token: true },
  { id: 'openai/gpt-5-image', name: 'OpenAI: GPT-5 Image', provider: 'OpenAI', input: 'image+text+file', output: 'image+text', params: 'quality, background, n, input_references, output_compression', pricing: 'output_image: $0.00004/token', token: true },
  { id: 'google/gemini-2.5-flash-image', name: 'Google: Nano Banana (Gemini 2.5 Flash Image)', provider: 'Google AI Studio', input: 'image+text', output: 'image+text', params: 'aspect_ratio, n, input_references', pricing: 'input_image/output_image token pricing', token: true },
  { id: 'google/gemini-2.5-flash-image-preview', name: 'Google: Gemini 2.5 Flash Image Preview (Nano Banana)', provider: '-', input: 'image+text', output: 'image+text', params: '', pricing: 'нет endpoint pricing' },
  { id: 'openrouter/auto', name: 'Auto Router', provider: '-', input: 'text+image+audio+file+video', output: 'text+image', params: '', pricing: 'нет endpoint pricing' },
]

const has = (m: ApiImageModel, value: string) => `${m.input} ${m.output} ${m.params} ${m.id} ${m.name}`.toLowerCase().includes(value)
const textImageModels = () => OPENROUTER_IMAGE_MODELS.filter((m) => m.input.includes('text') && m.output.includes('image'))
const imageInputModels = () => textImageModels().filter((m) => m.input.includes('image') || has(m, 'input_references'))
const transparentModels = () => textImageModels().filter((m) => has(m, 'background') || has(m, 'transparent') || m.id.includes('gpt-image'))
const API_MODE_SECTIONS: ApiModeSection[] = [
  { id: 'text_to_image', title: 'Текст -> изображение', local: 'Flux 2 Klein 4B', note: 'Все OpenRouter image-модели, которые принимают text и возвращают image.', filter: (m) => m.input.includes('text') && m.output.includes('image') },
  { id: 'image_to_image', title: 'Изображение -> изображение', local: 'Flux 2 Klein 4B', note: 'Модели с image input или input_references. Здесь допускаются дубли из txt2img.', filter: (m) => imageInputModels().includes(m) },
  { id: 'edit', title: 'Редактор / multi-reference', local: 'Flux 2 Klein 9B', note: 'Модели, где явно есть input_references или OpenAI/Gemini image-edit capabilities.', filter: (m) => has(m, 'input_references') || m.id.includes('gpt-image') || m.id.includes('gemini') },
  { id: 'paint', title: 'Рисунок / sketch', local: 'Flux 2 Klein edit workflow', note: 'То же семейство image-input моделей: скетч передается как reference/input image.', filter: (m) => imageInputModels().includes(m) },
  { id: 'inpaint', title: 'Редактор - маска / inpaint', local: 'Flux 2 Klein inpaint workflow', note: 'OpenRouter image models не всегда явно обещают mask API; сначала тестируем OpenAI background/quality и image-reference модели.', filter: (m) => m.id.includes('gpt-image') || has(m, 'background') || has(m, 'quality') },
  { id: 'outpaint', title: 'Редактор - расширение / outpaint', local: 'Flux 2 Klein outpaint workflow', note: 'Кандидаты с aspect_ratio/resolution/input_references. Нужен ручной тест расширения границ.', filter: (m) => has(m, 'aspect_ratio') || has(m, 'resolution') || has(m, 'input_references') },
  { id: 'faceswap', title: 'Лицо / reference identity', local: 'Flux 2 Klein 9B + BFS LoRA', note: 'Все image-reference модели, но включать только после теста identity consistency и приватности.', filter: (m) => imageInputModels().includes(m) },
  { id: 'remove_background', title: 'Удаление фона / прозрачность', local: 'локальный workflow/утилита', note: 'Только модели с background/transparent-like параметрами; это отдельный инструмент, не массовый txt2img.', filter: (m) => transparentModels().includes(m) },
]

const exchangeRate = (exchange?: PageData['openrouter']['exchange']) => typeof exchange?.rate === 'number' ? exchange.rate : null
const effectiveUsdRub = (exchange?: PageData['openrouter']['exchange']) => {
  const rate = exchangeRate(exchange)
  return rate === null ? null : rate * (1 + USD_FEE_RATE)
}
const rub = (usd: number, rate: number | null) => rate === null ? 'курс не загружен' : `${(usd * rate).toFixed(2)} ₽`
const SHORT_PROMPT_TEXT_TOKENS = 40
const OUTPUT_IMAGE_TOKENS_1MP = 1300
const usd = (value: number) => `$${value.toFixed(value < 0.01 ? 4 : 3)}`
const modelBrand = (m: ApiImageModel) => {
  const fromName = m.name.includes(':') ? m.name.split(':')[0].trim() : ''
  const fromId = m.id.split('/')[0] || ''
  return (fromName || m.provider || fromId || 'Unknown').replace('Black Forest Labs', 'BFL')
}
const modelShortName = (m: ApiImageModel) => {
  const withoutBrand = m.name.includes(':') ? m.name.split(':').slice(1).join(':').trim() : m.name
  return withoutBrand.replace(/\s*\([^)]*\)\s*/g, ' ').replace(/\s+/g, ' ').trim()
}
const modelLabelById = (id: unknown) => {
  const value = String(id || '')
  const found = OPENROUTER_IMAGE_MODELS.find((m) => m.id === value)
  return found ? modelShortName(found) : value || '—'
}
const extractTokenRate = (pricing: string, key: string) => {
  const match = pricing.match(new RegExp(`${key}: \\$(\\d+(?:\\.\\d+)?)/token`))
  return match ? Number(match[1]) : null
}
const extractDollarValues = (pricing: string) => Array.from(pricing.matchAll(/\$(\d+(?:\.\d+)?)/g)).map((m) => Number(m[1])).filter(Number.isFinite)
const extractOutputImageDollars = (pricing: string) => {
  const outputIndex = pricing.indexOf('output_image')
  return outputIndex >= 0 ? extractDollarValues(pricing.slice(outputIndex)) : []
}
const estimatedUsdPerMp = (m: ApiImageModel) => {
  if (typeof m.mpUsd === 'number') return m.mpUsd
  if (typeof m.imageUsd === 'number') return m.imageUsd
  if (m.token) {
    const outputRate = extractTokenRate(m.pricing, 'output_image')
    const inputTextRate = extractTokenRate(m.pricing, 'input_text') || 0
    if (outputRate !== null) return outputRate * OUTPUT_IMAGE_TOKENS_1MP + inputTextRate * SHORT_PROMPT_TEXT_TOKENS
  }
  if (m.tiered) {
    const values = extractOutputImageDollars(m.pricing)
    if (values.length) return Math.min(...values)
  }
  return null
}
const priceConfidence = (m: ApiImageModel) => {
  if (typeof m.mpUsd === 'number') return 'точно за MP'
  if (typeof m.imageUsd === 'number') return 'за image, считаем как 1MP'
  if (m.token) return `оценка: ${OUTPUT_IMAGE_TOKENS_1MP} image-токенов + ~${SHORT_PROMPT_TEXT_TOKENS} текстовых`
  if (m.tiered) return 'минимальный тариф из OpenRouter'
  return 'нет endpoint pricing'
}
const modelRubPrice = (m: ApiImageModel, rate: number | null) => {
  const value = estimatedUsdPerMp(m)
  return value === null ? 'нет данных' : `${rub(value, rate)}`
}
const modelUsdPrice = (m: ApiImageModel) => {
  const value = estimatedUsdPerMp(m)
  return value === null ? 'нет данных' : usd(value)
}
const minTokenTier = (m: ApiImageModel) => {
  if (m.id === 'black-forest-labs/flux.2-klein-4b') return 1
  if (m.id === 'black-forest-labs/flux.2-pro') return 2
  if (m.id === 'black-forest-labs/flux.2-max') return 3
  if (m.id === 'black-forest-labs/flux.2-flex') return 4
  return 1
}
const tokenPriceForModel = (m: ApiImageModel, actualUsdPerMp: number | null | undefined, rate: number | null) => {
  const estimated = estimatedUsdPerMp(m)
  const value = typeof actualUsdPerMp === 'number' ? Math.max(estimated || 0, actualUsdPerMp) : estimated
  if (value === null || rate === null) return null
  return Math.max(minTokenTier(m), Math.ceil((value * rate) / TOKEN_RUB))
}
const valueText = (value: unknown) => value === null || value === undefined || value === '' ? '—' : String(value)
const moneyUsdText = (value: unknown) => typeof value === 'number' ? `$${value.toFixed(4)}` : valueText(value)
const openrouterErrorText = (error: unknown) => {
  if (!error) return ''
  if (typeof error === 'string') return error
  try { return JSON.stringify(error) } catch { return String(error) }
}
const usageModelMap = (models?: Array<Record<string, unknown>>) => new Map((models || []).map((item) => [String(item.model || ''), item]))
const usageModeMap = (modes?: Array<Record<string, unknown>>) => new Map((modes || []).map((item) => [String(item.mode || ''), item]))
const modelStatText = (value: unknown, suffix = '') => typeof value === 'number' ? `${value}${suffix}` : '—'
const moneyPair = (usdValue: unknown, rate: number | null) => typeof usdValue === 'number' ? `${rub(usdValue, rate)} - $${usdValue.toFixed(4)}` : '—'
const projectTokensForUsd = (usdValue: unknown, rate: number | null) => typeof usdValue === 'number' && rate !== null ? Math.ceil((usdValue * rate) / TOKEN_RUB) : null
const tokensText = (usdValue: unknown, rate: number | null) => {
  const tokens = projectTokensForUsd(usdValue, rate)
  return tokens === null ? '—' : `${tokens} ток.`
}
const sortedApiRows = (rows: ApiImageModel[], sort: ApiSortState) => [...rows].sort((a, b) => {
  let result = 0
  if (sort.key === 'name') result = modelShortName(a).localeCompare(modelShortName(b), 'ru')
  if (sort.key === 'provider') result = modelBrand(a).localeCompare(modelBrand(b), 'ru') || modelShortName(a).localeCompare(modelShortName(b), 'ru')
  if (sort.key === 'price') {
    const ap = estimatedUsdPerMp(a)
    const bp = estimatedUsdPerMp(b)
    if (ap === null && bp === null) result = modelShortName(a).localeCompare(modelShortName(b), 'ru')
    else if (ap === null) return 1
    else if (bp === null) return -1
    else {
      result = ap - bp || modelShortName(a).localeCompare(modelShortName(b), 'ru')
      return sort.dir === 'desc' ? -result : result
    }
  }
  return sort.dir === 'desc' ? -result : result
})

const CSS = `
.amv2{--panel:#101310;--line:rgba(255,255,255,.10);--line-strong:rgba(255,255,255,.18);--text:#f5f7ef;--muted:#a6aea3;--dim:#727b70;--lime:#cfe56b;--green:#70dd78;--yellow:#d8bb61;--red:#ff7479;--radius:8px;color:var(--text);font-weight:500}
.amv2 h1,.amv2 h2,.amv2 h3,.amv2 p{margin:0;text-transform:none}
.amv2 button{cursor:pointer;font:inherit}
.amv2 .state,.amv2 .provider,.amv2 .mini,.amv2 .plan{display:inline-flex;align-items:center;gap:6px;border-radius:999px;border:1px solid var(--line-strong);background:rgba(255,255,255,.045);color:var(--muted);font-size:12px;font-weight:650;padding:4px 8px;white-space:nowrap}
.amv2 .provider.local{color:var(--lime);border-color:rgba(234,255,16,.30);background:rgba(234,255,16,.07)}
.amv2 .provider.openrouter{color:#7bc3ff;border-color:rgba(85,169,255,.35);background:rgba(85,169,255,.08)}
.amv2 .state.ok{color:var(--green)}.amv2 .state.warn{color:var(--yellow)}.amv2 .state.bad{color:var(--red)}
.amv2 .ghost,.amv2 .primary,.amv2 .danger{min-height:32px;border:1px solid var(--line-strong);border-radius:var(--radius);padding:0 12px;color:var(--text);background:rgba(18,21,18,.78);font-size:13px;font-weight:650}
.amv2 .primary{color:#080a07;border-color:rgba(234,255,16,.8);background:var(--lime)}
.amv2 .danger{color:#ffe6e7;border-color:rgba(255,92,98,.28);background:rgba(255,92,98,.12)}
.amv2 .card{border:1px solid var(--line);border-radius:var(--radius);background:linear-gradient(180deg,rgba(255,255,255,.035),rgba(255,255,255,.012)),rgba(16,19,16,.92);overflow:hidden;margin-bottom:12px}
.amv2 .card-head{min-height:54px;padding:14px;display:flex;justify-content:space-between;align-items:flex-start;gap:14px;border-bottom:1px solid var(--line)}
.amv2 .card-title{font-size:15px;line-height:1.2}
.amv2 .card-note{margin-top:5px;color:var(--muted);font-size:12px;line-height:1.35}
.amv2 .page-tabs{display:flex;gap:8px;margin-bottom:12px;overflow-x:auto}
.amv2 .page-tabs button{min-height:38px;border:1px solid var(--line-strong);border-radius:var(--radius);padding:0 14px;background:rgba(255,255,255,.04);color:var(--muted);font-weight:650;white-space:nowrap}
.amv2 .page-tabs button.active{background:var(--lime);border-color:var(--lime);color:#080a07}
.amv2 .tab-status{margin-left:auto;display:flex;align-items:center;gap:8px;white-space:nowrap}
.amv2 .status-dot{width:9px;height:9px;border-radius:50%;background:var(--red);box-shadow:0 0 0 3px rgba(255,116,121,.12)}
.amv2 .status-dot.ok{background:var(--green);box-shadow:0 0 0 3px rgba(112,221,120,.12)}
.amv2 .status-dot.warn{background:var(--yellow);box-shadow:0 0 0 3px rgba(216,187,97,.12)}
.amv2 .status-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;padding:12px}
.amv2 .status-card{border:1px solid var(--line);border-radius:var(--radius);background:rgba(255,255,255,.035);padding:12px;display:grid;gap:6px;align-content:start}
.amv2 .status-card strong{font-size:13px}.amv2 .status-card span{font-size:22px;font-weight:700}.amv2 .status-card small{color:var(--muted);overflow-wrap:anywhere}
.amv2 .ops-row{display:grid;grid-template-columns:minmax(220px,1fr) auto auto auto;gap:10px;padding:12px;border-top:1px solid var(--line);align-items:center}
.amv2 .job-list{padding:0 12px 12px;display:grid;gap:6px}
.amv2 .job-row{display:grid;grid-template-columns:minmax(120px,1fr) 96px 90px minmax(140px,1.2fr);gap:8px;align-items:center;border:1px solid var(--line);border-radius:var(--radius);padding:8px;background:rgba(255,255,255,.028);font-size:12px}
.amv2 .api-key-panel{padding:12px;display:grid;grid-template-columns:minmax(0,1fr);gap:12px;border-bottom:1px solid var(--line)}
.amv2 .api-key-box{border:1px solid var(--line);border-radius:var(--radius);padding:12px;background:rgba(255,255,255,.032);display:grid;gap:8px;align-content:start}
.amv2 .api-key-box input{font-family:ui-monospace,SFMono-Regular,Consolas,monospace}
.amv2 .api-key-main{display:grid;grid-template-columns:minmax(260px,1fr) auto;gap:10px;align-items:center}
.amv2 .key-status{border:1px solid var(--line);border-radius:var(--radius);background:rgba(255,255,255,.028);padding:8px;display:grid;gap:6px}
.amv2 .key-status-row{display:flex;justify-content:space-between;gap:10px;font-size:12px;border-bottom:1px solid rgba(255,255,255,.06);padding-bottom:5px}
.amv2 .key-status-row:last-child{border-bottom:0;padding-bottom:0}
.amv2 .key-status-row span{color:var(--muted)}.amv2 .key-status-row strong{color:var(--text);text-align:right;overflow-wrap:anywhere}
.amv2 .key-ok strong{color:var(--green)}.amv2 .key-bad strong{color:var(--red)}.amv2 .key-warn strong{color:var(--yellow)}
.amv2 .or-test{border:1px solid rgba(234,255,16,.18);border-radius:var(--radius);background:rgba(234,255,16,.04);padding:8px;display:grid;grid-template-columns:72px minmax(0,1fr);gap:10px;align-items:center}
.amv2 .or-test img{width:72px;height:72px;object-fit:cover;border-radius:6px;border:1px solid var(--line)}
.amv2 .or-test strong{font-size:12px}.amv2 .or-test span{display:block;margin-top:4px;color:var(--muted);font-size:11px;overflow-wrap:anywhere}
.amv2 .or-stats{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:8px;padding:0 0 12px;border-bottom:1px solid var(--line)}
.amv2 .or-stat{border:1px solid var(--line);border-radius:var(--radius);padding:10px;background:rgba(255,255,255,.032)}
.amv2 .or-stat span{display:block;color:var(--muted);font-size:11px;font-weight:650}.amv2 .or-stat strong{display:block;margin-top:5px;font-size:15px;color:var(--lime);font-weight:700}
.amv2 .mode-board{padding:12px;display:grid;grid-template-columns:repeat(4,minmax(180px,1fr));gap:10px}
.amv2 .mode-card{border:1px solid var(--line);border-radius:var(--radius);padding:12px;background:rgba(255,255,255,.032);display:grid;gap:8px;align-content:start}
.amv2 .mode-card strong{font-size:13px}.amv2 .mode-card span{color:var(--muted);font-size:12px;line-height:1.35}
.amv2 .api-count{display:flex;align-items:center;gap:8px;white-space:nowrap;justify-content:flex-end}
.amv2 .api-section-head{width:100%;border:0;background:transparent;color:inherit;text-align:left;display:grid;grid-template-columns:minmax(220px,1.3fr) repeat(5,minmax(100px,.7fr)) minmax(170px,1fr) minmax(170px,1fr);gap:10px;align-items:center;padding:10px 14px}
.amv2 .api-section-head .card-title::before{content:"▾";display:inline-block;margin-right:8px;color:var(--lime)}
.amv2 .api-section-head.collapsed .card-title::before{content:"▸"}
.amv2 .section-cell{display:grid;gap:2px;min-width:0}
.amv2 .section-cell span{color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:.04em}
.amv2 .section-cell strong{font-size:12px;font-weight:650;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.amv2 .api-table{min-width:980px}
.amv2 .api-table td,.amv2 .api-table th{vertical-align:middle}
.amv2 .api-table th{padding:6px 8px}
.amv2 .api-table td{padding:2px 8px;height:26px;line-height:1.15}
.amv2 .api-table tr.api-model-row{cursor:pointer}
.amv2 .api-table tr.api-model-row:hover td{background:rgba(234,255,16,.035)}
.amv2 .api-table tr.api-model-row.expanded td{background:rgba(234,255,16,.05)}
.amv2 .sort-head{appearance:none;border:0;background:transparent;color:var(--muted);font:inherit;font-size:11px;font-weight:650;text-transform:uppercase;letter-spacing:.04em;padding:0;display:inline-flex;align-items:center;gap:6px}
.amv2 .sort-head.active{color:var(--lime)}
.amv2 .detail-cell{padding:0 10px 9px 10px!important;background:rgba(255,255,255,.018)}
.amv2 .detail-box{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:6px 14px;color:var(--muted);line-height:1.35;font-size:11px}
.amv2 .detail-box span{overflow-wrap:anywhere}
.amv2 .api-table .model-name{white-space:nowrap;font-size:12px;font-weight:700}
.amv2 .api-enabled{width:28px;text-align:center}
.amv2 .api-enabled input{width:14px;height:14px;min-height:14px;padding:0;margin:0;vertical-align:middle}
.amv2 .api-table .provider{font-size:11px;padding:2px 6px}
.amv2 .api-table .money{font-size:12px}
.amv2 .money{font-weight:650;color:var(--lime);white-space:nowrap}
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
.amv2 .model-cell{display:grid;gap:5px}.amv2 .model-name{font-size:14px;font-weight:750}.amv2 .model-id{color:var(--dim);font-size:11px;overflow-wrap:anywhere}
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
@media (max-width:1360px){.amv2 .dashboard{grid-template-columns:1fr}.amv2 .metric-grid,.amv2 .lora-grid,.amv2 .status-grid,.amv2 .mode-board{grid-template-columns:repeat(2,minmax(0,1fr))}.amv2 .api-section-head{grid-template-columns:minmax(220px,1.4fr) repeat(3,minmax(100px,.8fr)) minmax(150px,1fr)}.amv2 .grid-main{grid-template-columns:1fr}.amv2 .side-panel{position:static}}
@media (max-width:880px){.amv2 .route-row,.amv2 .toolbar,.amv2 .ops-row,.amv2 .job-row,.amv2 .api-key-panel,.amv2 .or-stats,.amv2 .api-section-head{grid-template-columns:1fr}.amv2 .tab-status{margin-left:0;width:100%;flex-wrap:wrap}.amv2 .page-tabs{flex-wrap:wrap}.amv2 .matrix-wrap{overflow-x:auto}.amv2 .matrix-wrap table{min-width:980px}.amv2 .matrix-wrap .api-table{min-width:760px}.amv2 .mobile-models{display:grid}}
@media (max-width:580px){.amv2 .metric-grid,.amv2 .two-col,.amv2 .price-row,.amv2 .lora-grid,.amv2 .advanced-grid,.amv2 .status-grid,.amv2 .mode-board,.amv2 .or-stats{grid-template-columns:1fr}}
`

export default function AdminModelsV2() {
  const [data, setData] = useState<PageData | null>(null)
  const [pageTab, setPageTab] = useState<'config' | 'api'>('api')
  const [configStatus, setConfigStatus] = useState<ConfigStatus | null>(null)
  const [routes, setRoutes] = useState<Route[]>([])
  const [query, setQuery] = useState('')
  const [apiSorts, setApiSorts] = useState<Record<string, ApiSortState>>({})
  const [apiSectionsOpen, setApiSectionsOpen] = useState<Record<string, boolean>>({ text_to_image: true })
  const [apiExpandedRows, setApiExpandedRows] = useState<Record<string, boolean>>({})
  const [openrouterKeyInput, setOpenrouterKeyInput] = useState('')
  const [openrouterBusy, setOpenrouterBusy] = useState(false)
  const [openrouterConfigBusy, setOpenrouterConfigBusy] = useState(false)
  const [openrouterTestBusy, setOpenrouterTestBusy] = useState(false)
  const [openrouterTestResult, setOpenrouterTestResult] = useState<OpenRouterTestResult | null>(null)
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

  const saveOpenrouterKey = async () => {
    const key = openrouterKeyInput.trim()
    if (!key) { setMsg('Вставьте ключ OpenRouter'); return }
    setOpenrouterBusy(true); setMsg('')
    const r = await amvFetch('/admin/openrouter/key', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key }),
    }).then((x) => x.json()).catch(() => null) as { ok?: boolean; key?: { ok?: boolean; error?: unknown } } | null
    setOpenrouterBusy(false)
    setOpenrouterKeyInput('')
    await load()
    setMsg(r?.key?.ok ? 'Ключ OpenRouter сохранён и проверен' : `Ключ сохранён, но проверка не прошла: ${String(r?.key?.error || 'unknown')}`)
  }

  const deleteOpenrouterKey = async () => {
    setOpenrouterBusy(true); setMsg('')
    const r = await amvFetch('/admin/openrouter/key', { method: 'DELETE' }).then((x) => x.json()).catch(() => null) as { ok?: boolean } | null
    setOpenrouterBusy(false)
    await load()
    setMsg(r?.ok ? 'UI-ключ OpenRouter удалён' : 'Не удалось удалить ключ')
  }

  const saveOpenrouterConfig = async (config: OpenRouterConfig) => {
    setOpenrouterConfigBusy(true)
    const r = await amvFetch('/admin/openrouter/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ config }),
    }).then((x) => x.json()).catch(() => null) as { ok?: boolean; config?: OpenRouterConfig } | null
    setOpenrouterConfigBusy(false)
    if (r?.ok && r.config) {
      setData((prev) => prev ? { ...prev, openrouter: { ...prev.openrouter, config: r.config } } : prev)
      setMsg('Настройки API-моделей сохранены')
    } else setMsg('Не удалось сохранить настройки API-моделей')
  }

  const toggleOpenrouterModel = (mode: string, modelId: string, checked: boolean) => {
    if (!data) return
    const current = data.openrouter.config || { enabled: {}, defaults: {} }
    const enabled = { ...(current.enabled || {}) }
    const defaults = { ...(current.defaults || {}) }
    const list = new Set(enabled[mode] || [])
    if (checked) list.add(modelId)
    else list.delete(modelId)
    const nextList = Array.from(list).sort()
    if (nextList.length) enabled[mode] = nextList
    else delete enabled[mode]
    if (checked && !defaults[mode]) defaults[mode] = modelId
    if (!checked && defaults[mode] === modelId) {
      if (nextList.length) defaults[mode] = nextList[0]
      else delete defaults[mode]
    }
    void saveOpenrouterConfig({ enabled, defaults })
  }

  const runOpenrouterTest = async () => {
    setOpenrouterTestBusy(true); setMsg('Тестовая генерация OpenRouter запущена')
    const r = await amvFetch('/admin/openrouter/test-generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model: 'black-forest-labs/flux.2-klein-4b', width: 1024, height: 1024 }),
    }).then((x) => x.json()).catch(() => null) as ({ ok?: boolean } & OpenRouterTestResult & { detail?: string }) | null
    setOpenrouterTestBusy(false)
    if (r?.ok) {
      setOpenrouterTestResult(r)
      setMsg(`OpenRouter test готов: ${typeof r.costUsd === 'number' ? `$${r.costUsd.toFixed(4)}` : 'cost не пришёл'}`)
      await load()
    } else setMsg(`OpenRouter test не выполнен: ${r?.detail || 'unknown error'}`)
  }

  const toggleApiSort = (sectionId: string, key: ApiSortKey) => {
    setApiSorts((prev) => {
      const current = prev[sectionId] || { key: 'price', dir: 'asc' as const }
      return { ...prev, [sectionId]: current.key === key ? { key, dir: current.dir === 'asc' ? 'desc' : 'asc' } : { key, dir: 'asc' } }
    })
  }
  const sortMark = (sort: ApiSortState, key: ApiSortKey) => sort.key === key ? (sort.dir === 'asc' ? '↑' : '↓') : ''

  const kleinLoras = useMemo(() => (data?.loras || []).filter((l) => l.forKlein !== false), [data?.loras])
  const otherLoras = useMemo(() => (data?.loras || []).filter((l) => l.forKlein === false), [data?.loras])

  const profiles = data?.profiles || []
  const localOptions = profiles.map((p) => ({ id: p.id, name: p.name }))
  const fmtTime = (value?: string) => value ? new Date(value).toLocaleString('ru-RU') : '—'
  const fmtState = (ok?: boolean) => configErr ? 'unknown' : ok ? 'ok' : 'fail'
  const statusColor = (ok?: boolean) => configErr ? 'var(--yellow)' : ok ? 'var(--green)' : 'var(--red)'

  if (!data) return <div className="amv2"><style>{CSS}</style><div style={{ padding: 12, display: 'grid', gap: 10 }}><p style={{ color: err ? 'var(--red)' : 'var(--muted)' }}>{err || 'Загрузка страницы моделей…'}</p>{err && <button className="ghost" style={{ width: 'max-content' }} onClick={() => void load()}>Повторить</button>}</div></div>

  const orStatus = data.openrouter.status || {}
  const orData = orStatus.data || {}
  const orCredits = orStatus.credits || {}
  const orCreditsData = orCredits.data && typeof orCredits.data === 'object' ? orCredits.data as Record<string, unknown> : {}
  const usdRubBase = exchangeRate(data.openrouter.exchange)
  const usdRubEffective = effectiveUsdRub(data.openrouter.exchange)
  const orStatusClass = orStatus.ok ? 'key-ok' : orStatus.configured ? 'key-bad' : 'key-warn'
  const orStatusText = orStatus.ok ? 'работает' : orStatus.configured ? 'ключ есть, проверка не прошла' : 'ключ не сохранён'
  const orLimit = orData.limit === null || orData.limit === undefined ? 'без лимита / не задан' : moneyUsdText(orData.limit)
  const orRemaining = orData.limit_remaining === null || orData.limit_remaining === undefined ? '—' : moneyUsdText(orData.limit_remaining)
  const orUsageModels = usageModelMap(data.openrouter.usage?.models)
  const orUsageModes = usageModeMap(data.openrouter.usage?.modes)
  const totalSpentPair = typeof data.openrouter.usage?.totalCostUsd === 'number' ? moneyPair(data.openrouter.usage.totalCostUsd, usdRubEffective) : '—'
  const avgImagePair = typeof data.openrouter.usage?.avgCostUsd === 'number' ? moneyPair(data.openrouter.usage.avgCostUsd, usdRubEffective) : '—'
  const avgMpPair = typeof data.openrouter.usage?.avgCostPerMpUsd === 'number' ? moneyPair(data.openrouter.usage.avgCostPerMpUsd, usdRubEffective) : '—'
  const favoriteOverall = (data.openrouter.usage?.models || [])[0]
  const favoriteOverallName = modelLabelById(favoriteOverall?.model)
  const creditsBalance = typeof orCredits.balance === 'number' ? orCredits.balance : null
  const balanceText = creditsBalance !== null
    ? moneyPair(creditsBalance, usdRubEffective)
    : orCredits.status_code === 403
      ? 'нужен management key'
      : orData.limit_remaining === null || orData.limit_remaining === undefined ? 'лимит не задан' : moneyUsdText(orData.limit_remaining)
  const effectiveRateText = usdRubBase === null || usdRubEffective === null
    ? 'курс ЦБ не загрузился'
    : `$1 ЦБ ${usdRubBase.toFixed(2)} ₽ + ${Math.round(USD_FEE_RATE * 100)}% = ${usdRubEffective.toFixed(2)} ₽`
  const spentTokensText = tokensText(data.openrouter.usage?.totalCostUsd, usdRubEffective)

  return <div className="amv2">
    <style>{CSS}</style>
    {msg && <p style={{ color: 'var(--lime)', fontSize: 12, margin: '0 0 8px' }}>{msg}</p>}
    <div className="page-tabs" aria-label="Разделы моделей">
      <button className={pageTab === 'api' ? 'active' : ''} onClick={() => setPageTab('api')}>OpenRouter</button>
      <button className={pageTab === 'config' ? 'active' : ''} onClick={() => setPageTab('config')}>Config UI</button>
      {pageTab === 'api' && <div className="tab-status">
        <span className={`status-dot ${orStatus.ok ? 'ok' : data.openrouter.keyConfigured ? 'warn' : ''}`} aria-hidden="true" />
        <span className={`state ${orStatus.ok ? 'ok' : data.openrouter.keyConfigured ? 'warn' : 'bad'}`}>{orStatus.ok ? 'ключ работает' : data.openrouter.keyConfigured ? 'проверить ключ' : 'нет ключа'}</span>
        <span className="state">{effectiveRateText}</span>
      </div>}
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
      <div className="or-stats">
        <div className="or-stat"><span>Баланс OpenRouter</span><strong>{balanceText}</strong></div>
        <div className="or-stat"><span>Сгенерировано картинок</span><strong>{data.openrouter.usage?.pricedImages || 0}</strong></div>
        <div className="or-stat"><span>Потрачено всего</span><strong>{totalSpentPair}</strong></div>
        <div className="or-stat"><span>Списано токенов</span><strong>{spentTokensText}</strong></div>
        <div className="or-stat"><span>Средняя за картинку</span><strong>{avgImagePair}</strong></div>
        <div className="or-stat"><span>Средняя за 1MP</span><strong>{avgMpPair}</strong></div>
        <div className="or-stat"><span>Фаворит по генерациям</span><strong>{favoriteOverallName}</strong></div>
      </div>

      <div className="toolbar">
        <input type="search" placeholder="Фильтр по всем карточкам: модель, provider, price, параметр" value={query} onChange={(e) => setQuery(e.target.value)} />
        <button className="ghost" onClick={() => setQuery('')}>Сбросить</button>
      </div>

      {API_MODE_SECTIONS.map((section) => {
        const sort = apiSorts[section.id] || { key: 'price' as const, dir: 'asc' as const }
        const sectionOpen = apiSectionsOpen[section.id] ?? false
        const enabledForSection = data.openrouter.config?.enabled?.[section.id] || []
        const defaultForSection = data.openrouter.config?.defaults?.[section.id] || ''
        const sectionStats = orUsageModes.get(section.id)
        const sectionCount = typeof sectionStats?.count === 'number' ? sectionStats.count : 0
        const sectionSpent = typeof sectionStats?.costUsd === 'number' ? moneyPair(sectionStats.costUsd, usdRubEffective) : '—'
        const sectionAvg = typeof sectionStats?.avgCostUsd === 'number' ? moneyPair(sectionStats.avgCostUsd, usdRubEffective) : '—'
        const sectionAvgMp = typeof sectionStats?.avgCostPerMpUsd === 'number' ? moneyPair(sectionStats.avgCostPerMpUsd, usdRubEffective) : '—'
        const sectionTokens = tokensText(sectionStats?.costUsd, usdRubEffective)
        const sectionFavorite = modelLabelById(sectionStats?.favoriteModel)
        const rows = OPENROUTER_IMAGE_MODELS
          .filter(section.filter)
          .filter((m) => {
            const hay = `${m.id} ${m.name} ${m.provider} ${m.input} ${m.output} ${m.params} ${m.pricing}`.toLowerCase()
            return !query || hay.includes(query.toLowerCase())
          })
        const sortedRows = sortedApiRows(rows, sort)
        return <article className="card" key={section.id}>
          <button className={`api-section-head ${sectionOpen ? '' : 'collapsed'}`} onClick={() => setApiSectionsOpen((prev) => ({ ...prev, [section.id]: !sectionOpen }))}>
            <div className="section-cell">
              <h2 className="card-title">{section.title}</h2>
            </div>
            <div className="section-cell"><span>Сген.</span><strong>{sectionCount}</strong></div>
            <div className="section-cell"><span>Средняя</span><strong>{sectionAvg}</strong></div>
            <div className="section-cell"><span>Средняя 1MP</span><strong>{sectionAvgMp}</strong></div>
            <div className="section-cell"><span>Токены</span><strong>{sectionTokens}</strong></div>
            <div className="section-cell"><span>Потрачено</span><strong>{sectionSpent}</strong></div>
            <div className="section-cell"><span>Фаворит</span><strong>{sectionFavorite}</strong></div>
            <div className="api-count">
              <span className="state ok">{rows.length} моделей</span>
              <span className={`state ${enabledForSection.length ? 'ok' : 'warn'}`}>{enabledForSection.length ? `${enabledForSection.length} включено` : 'не включено'}</span>
              {openrouterConfigBusy ? <span className="mini">сохраняю…</span> : null}
            </div>
          </button>
          {sectionOpen && <>
          <div className="hint" style={{ margin: '8px 12px' }}>Локальный аналог: {section.local}. Клик по строке раскрывает технические детали и оценку подключения.</div>
          <div className="matrix-wrap">
            <table className="api-table">
              <thead><tr>
                <th className="api-enabled">Вкл.</th>
                <th><button className={`sort-head ${sort.key === 'name' ? 'active' : ''}`} onClick={() => toggleApiSort(section.id, 'name')}>Модель {sortMark(sort, 'name')}</button></th>
                <th><button className={`sort-head ${sort.key === 'provider' ? 'active' : ''}`} onClick={() => toggleApiSort(section.id, 'provider')}>Производитель {sortMark(sort, 'provider')}</button></th>
                <th><button className={`sort-head ${sort.key === 'price' ? 'active' : ''}`} onClick={() => toggleApiSort(section.id, 'price')}>Цена за 1MP, ₽ {sortMark(sort, 'price')}</button></th>
                <th><button className={`sort-head ${sort.key === 'price' ? 'active' : ''}`} onClick={() => toggleApiSort(section.id, 'price')}>Цена за 1MP, $ {sortMark(sort, 'price')}</button></th>
                <th>Токены</th>
                <th>Сген.</th>
                <th>Потрачено</th>
              </tr></thead>
              <tbody>{sortedRows.map((m) => {
                const rowKey = `${section.id}-${m.id}`
                const enabled = enabledForSection.includes(m.id)
                const expanded = apiExpandedRows[rowKey] || false
                const modelStats = orUsageModels.get(m.id)
                const avgActualUsd = typeof modelStats?.avgCostPerMpUsd === 'number' ? modelStats.avgCostPerMpUsd : null
                const generatedCount = modelStatText(modelStats?.count)
                const spentTotal = typeof modelStats?.costUsd === 'number' ? moneyPair(modelStats.costUsd, usdRubEffective) : '—'
                const tokenCount = tokenPriceForModel(m, avgActualUsd, usdRubEffective)
                return <Fragment key={rowKey}>
                  <tr className={`api-model-row ${expanded ? 'expanded' : ''}`} onClick={() => setApiExpandedRows((prev) => ({ ...prev, [rowKey]: !expanded }))}>
                    <td className="api-enabled">
                      <input
                        type="checkbox"
                        checked={enabled}
                        aria-label={`Включить ${modelShortName(m)} для ${section.title}`}
                        onClick={(e) => e.stopPropagation()}
                        onChange={(e) => toggleOpenrouterModel(section.id, m.id, e.target.checked)}
                      />
                    </td>
                    <td><strong className="model-name">{modelShortName(m)}</strong>{defaultForSection === m.id ? <span className="mini" style={{ marginLeft: 8 }}>default</span> : null}</td>
                    <td><span className="provider openrouter">{modelBrand(m)}</span></td>
                    <td><span className="money">{modelRubPrice(m, usdRubEffective)}</span></td>
                    <td><span className="money">{modelUsdPrice(m)}</span></td>
                    <td><span className="money">{tokenCount ?? '—'}</span></td>
                    <td>{generatedCount}</td>
                    <td><span className="money">{spentTotal}</span></td>
                  </tr>
                  {expanded && <tr>
                    <td className="detail-cell" colSpan={8}>
                      <div className="detail-box">
                        <span><b>Полное имя:</b> {m.name}</span>
                        <span><b>OpenRouter id:</b> {m.id}</span>
                        <span><b>Как посчитано:</b> {priceConfidence(m)}</span>
                        <span><b>Цена из OpenRouter:</b> {m.pricing}</span>
                        <span><b>Токены проекта:</b> {tokenCount ?? 'нужно измерить'} при {TOKEN_RUB} ₽/токен</span>
                        <span><b>Факт по проекту:</b> {generatedCount} шт · {spentTotal}</span>
                        <span><b>Вход/выход API:</b> {m.input} {'->'} {m.output}</span>
                        <span><b>Параметры:</b> {m.params || 'нет в endpoint metadata'}</span>
                      </div>
                    </td>
                  </tr>}
                </Fragment>
              })}</tbody>
            </table>
          </div>
          </>}
        </article>
      })}

      <article className="card">
        <div className="card-head">
          <div><h2 className="card-title">Ключ и тест OpenRouter</h2><p className="card-note">Меняется редко, поэтому живет внизу страницы.</p></div>
          <span className={`state ${orStatus.ok ? 'ok' : orStatus.configured ? 'warn' : 'bad'}`}>{orStatusText}</span>
        </div>
        <div className="api-key-panel">
          <div className="api-key-box">
            <div className="api-key-main">
              <input
                type="password"
                placeholder={data.openrouter.keyConfigured ? 'ключ сохранён, можно заменить новым' : 'sk-or-...'}
                value={openrouterKeyInput}
                onChange={(e) => setOpenrouterKeyInput(e.target.value)}
                autoComplete="off"
              />
              <span className={`state ${orStatus.ok ? 'ok' : orStatus.configured ? 'warn' : 'bad'}`}>{orStatusText}</span>
            </div>
            <div className="actions">
              <button className="primary" disabled={openrouterBusy || !openrouterKeyInput.trim()} onClick={saveOpenrouterKey}>Сохранить и проверить</button>
              <button className="ghost" disabled={openrouterBusy} onClick={() => { void load(); setMsg('Статус OpenRouter обновлён') }}>Проверить</button>
              <button className="ghost" disabled={openrouterTestBusy || !data.openrouter.status?.ok} onClick={runOpenrouterTest}>Тест Klein 4B 1MP</button>
              <button className="danger" disabled={openrouterBusy || !data.openrouter.keyConfigured} onClick={deleteOpenrouterKey}>Удалить UI-ключ</button>
            </div>
            <details>
              <summary>Детали ключа и лимитов</summary>
              <div className="key-status">
                <div className={`key-status-row ${orStatusClass}`}><span>Проверка</span><strong>{orStatusText}</strong></div>
                <div className="key-status-row"><span>Источник</span><strong>{orStatus.source === 'admin_ui' ? 'ключ из админки' : orStatus.source === 'env' ? 'OPENROUTER_API_KEY env' : '—'}</strong></div>
                <div className="key-status-row"><span>Ответ OpenRouter</span><strong>{orStatus.status_code || '—'}</strong></div>
                <div className="key-status-row"><span>Метка ключа</span><strong>{valueText(orData.label)}</strong></div>
                <div className="key-status-row"><span>Usage месяц</span><strong>{moneyUsdText(orData.usage_monthly)}</strong></div>
                <div className="key-status-row"><span>Лимит / остаток</span><strong>{orLimit} / {orRemaining}</strong></div>
                <div className={`key-status-row ${orCredits.ok ? 'key-ok' : 'key-warn'}`}><span>Credits API</span><strong>{orCredits.ok ? 'management key работает' : orCredits.status_code === 403 ? 'нужен management key' : valueText(orCredits.status_code)}</strong></div>
                <div className="key-status-row"><span>Баланс credits</span><strong>{creditsBalance !== null ? moneyPair(creditsBalance, usdRubEffective) : '—'}</strong></div>
                <div className="key-status-row"><span>Кредиты / usage</span><strong>{moneyUsdText(orCreditsData.total_credits)} / {moneyUsdText(orCreditsData.total_usage)}</strong></div>
                <div className="key-status-row"><span>Курс USD</span><strong>{usdRubBase === null ? 'не загружен' : `${usdRubBase.toFixed(4)} ₽ ЦБ · ${usdRubEffective?.toFixed(4)} ₽ с комиссией`}</strong></div>
                <div className="key-status-row"><span>Источник курса</span><strong>{valueText(data.openrouter.exchange?.source)} · {valueText(data.openrouter.exchange?.sourceDate)} · {valueText(data.openrouter.exchange?.cache)}</strong></div>
                {!orStatus.ok && orStatus.error ? <div className="key-status-row key-bad"><span>Ошибка</span><strong>{openrouterErrorText(orStatus.error)}</strong></div> : null}
                {!orCredits.ok && orCredits.error ? <div className="key-status-row key-warn"><span>Credits ошибка</span><strong>{openrouterErrorText(orCredits.error)}</strong></div> : null}
                {data.openrouter.exchange?.error ? <div className="key-status-row key-warn"><span>Курс ошибка</span><strong>{data.openrouter.exchange.error}</strong></div> : null}
              </div>
            </details>
            {openrouterTestResult?.image?.thumbnailUrl ? <div className="or-test">
              <img src={openrouterTestResult.image.thumbnailUrl} alt="OpenRouter test" />
              <div>
                <strong>Последний тест OpenRouter</strong>
                <span>Модель: {openrouterTestResult.model || '—'}</span>
                <span>Стоимость: {typeof openrouterTestResult.costUsd === 'number' ? `${rub(openrouterTestResult.costUsd, usdRubEffective)} · $${openrouterTestResult.costUsd.toFixed(4)}` : 'cost не пришёл'}</span>
              </div>
            </div> : null}
          </div>
        </div>
      </article>
    </>}
  </div>
}
