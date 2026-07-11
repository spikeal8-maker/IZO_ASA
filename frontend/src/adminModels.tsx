// Админ → Модели v2. Provider-aware страница управления моделями/маршрутами/тарифами,
// OpenRouter и серверной моделью. Структура по референсу admin-models-v2.html.
// Реальные данные приходят из GET /api/admin/models-page (см. backend). Тарифная матрица,
// маршруты и user-choice сохраняются через /api/admin/settings/{key}.
import { Fragment, useCallback, useEffect, useMemo, useState } from 'react'
import { normalizeTariffs, tariffKeys, type TariffConfig, type TariffKey } from './profileSupport'
import { IMAGE_RESOLUTIONS, normalizeResolutionIds, resolutionLabel, type ResolutionFormat, type ResolutionTier } from './resolutionPolicy'

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
  workflowReady?: boolean
  requiredModel?: string
}
type UserChoiceItem = { key?: string; label: string; model?: string; cost?: number | string; plan?: string; provider?: string }
type CatalogItem = { provider: string; displayName: string; modelId: string; capabilities: string[]; cost: string; margin: string; status: string }
type ProfileOption = { id: string; name: string; supportsPose?: boolean }
type ServerModelProfileSettings = { width: number; height: number; steps: number; sampler: string; seedMode: 'random' | 'fixed'; seed: number }
const CONFIG_RESOLUTION_FORMATS: ResolutionFormat[] = ['square', 'portrait', 'wide', 'photo']
const CONFIG_RESOLUTION_TIERS: ResolutionTier[] = ['sd', 'hd', 'full_hd']
type ConfigUiResolutionAccess = { plans?: Partial<Record<TariffKey, string[]>> }

function applyConfigUiResolutionAccess(config: TariffConfig, raw: unknown): TariffConfig {
  const plans = raw && typeof raw === 'object' ? (raw as ConfigUiResolutionAccess).plans : undefined
  if (!plans) return config
  return tariffKeys.reduce((next, plan) => {
    if (!Array.isArray(plans[plan])) return next
    next[plan] = { ...next[plan], allowed_resolutions: normalizeResolutionIds(plans[plan], next[plan].allowed_resolutions) }
    return next
  }, { ...config })
}
type OpenRouterFormatEconomics = {
  id: string
  label: string
  short: string
  inputWidth: number
  inputHeight: number
  requestSize?: string
  requestSizeStrategy?: string
  billingWidth?: number
  billingHeight?: number
  megapixels?: number
  costUsd?: number | null
  costRub?: number | null
  tokens?: number | null
  revenueRub?: number | null
  profitRub?: number | null
  marginPercent?: number | null
  supported?: boolean
}
type BackendOpenRouterPrice = { id: string; name: string; provider: string; pricing_type: string; usd: number; min_tokens: number; source: string; formats?: OpenRouterFormatEconomics[] }
type OpenRouterCapabilityModel = {
  id: string
  name: string
  description: string
  inputModalities: string[]
  outputModalities: string[]
  parameters: string[]
  maxInputReferences: number
  supportsStreaming: boolean
  modes: string[]
  features: { seed?: boolean; quality?: boolean; aspectRatio?: boolean; resolution?: boolean; transparentBackground?: boolean; multipleOutputs?: boolean }
}
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
  loraSettings?: { enabled?: Record<string, boolean> }
  serverModelProfiles?: { profiles?: Record<string, ServerModelProfileSettings> }
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
    exchange?: { rate?: number | null; source?: string; sourceUrl?: string; sourceDate?: string; fetchedAt?: string; cache?: string; error?: string; fallback?: boolean; warning?: string }
    economy?: { minMarginPercent?: number; tokenRub?: number }
    backendPricing?: BackendOpenRouterPrice[]
    capabilityCatalog?: OpenRouterCapabilityModel[]
    capabilityError?: string | null
    capabilityCacheTtlSeconds?: number
  }
  comfyFiles: Record<string, unknown>
  profiles: ProfileOption[]
}
type OpenRouterTier = 'mini' | 'plus' | 'pro' | 'business'
type OpenRouterQuality = 'fast' | 'standard' | 'max'
type OpenRouterAccess = Record<string, Partial<Record<OpenRouterTier, string[]>>>
type OpenRouterQualityDefaults = Record<string, Partial<Record<OpenRouterQuality, string>>>
type OpenRouterConfig = {
  enabled?: Record<string, string[]>
  defaults?: Record<string, string>
  access?: OpenRouterAccess
  qualityDefaults?: OpenRouterQualityDefaults
}
type OpenRouterTestResult = { image?: { url?: string; thumbnailUrl?: string }; costUsd?: number | null; model?: string; usage?: Record<string, unknown> }

const USD_FEE_RATE = 0.30
const DEFAULT_TOKEN_RUB = 5
const OPENROUTER_TIERS: Array<{ id: OpenRouterTier; label: string }> = [
  { id: 'mini', label: 'Mini' },
  { id: 'plus', label: 'Plus' },
  { id: 'pro', label: 'Pro' },
  { id: 'business', label: 'Business' },
]
const OPENROUTER_QUALITY: Array<{ id: OpenRouterQuality; label: string }> = [
  { id: 'fast', label: 'Быстро' },
  { id: 'standard', label: 'Стандарт' },
  { id: 'max', label: 'Максимум' },
]
const OPENROUTER_FORMAT_COLUMNS = [
  { id: 'square', label: '1:1' },
  { id: 'portrait', label: '9:16' },
  { id: 'wide', label: '16:9' },
  { id: 'soft_wide', label: '3:2' },
] as const
type ApiImageModel = {
  id: string; name: string; provider: string; input: string; output: string; params: string; pricing: string
  mpUsd?: number; imageUsd?: number; token?: boolean; tiered?: boolean
  modes?: string[]; maxInputReferences?: number; description?: string; supportsStreaming?: boolean
}
type ApiSortKey = 'price' | 'name' | 'provider' | 'tokens' | 'revenue' | 'profit' | 'margin'
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
  { id: 'microsoft/mai-image-2.5', name: 'Microsoft: MAI-Image-2.5', provider: 'Azure', input: 'text+image', output: 'image', params: 'aspect_ratio, n, input_references', pricing: 'оценка: output_image ~$0.00006/token', token: true },
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
  { id: 'sourceful/riverflow-v2-pro', name: 'Sourceful: Riverflow V2 Pro', provider: 'Sourceful', input: 'text+image', output: 'image', params: 'resolution, n, input_references', pricing: 'оценка: output_image ~$0.13/image', imageUsd: 0.13 },
  { id: 'sourceful/riverflow-v2-fast', name: 'Sourceful: Riverflow V2 Fast', provider: 'Sourceful', input: 'text+image', output: 'image', params: 'resolution, n, input_references', pricing: 'оценка: output_image ~$0.04/image', imageUsd: 0.04 },
  { id: 'black-forest-labs/flux.2-klein-4b', name: 'Black Forest Labs: FLUX.2 Klein 4B', provider: 'Black Forest Labs', input: 'text+image', output: 'image', params: 'output_format, n, input_references, seed', pricing: 'output_image: $0.014/megapixel', mpUsd: 0.014 },
  { id: 'bytedance-seed/seedream-4.5', name: 'ByteDance Seed: Seedream 4.5', provider: 'Seed', input: 'image+text', output: 'image', params: 'resolution, aspect_ratio, n, input_references, seed', pricing: 'output_image: $0.04/image', imageUsd: 0.04 },
  { id: 'black-forest-labs/flux.2-max', name: 'Black Forest Labs: FLUX.2 Max', provider: 'Black Forest Labs', input: 'text+image', output: 'image', params: 'output_format, n, input_references, seed', pricing: 'output_image: $0.07/megapixel', mpUsd: 0.07 },
  { id: 'sourceful/riverflow-v2-max-preview', name: 'Sourceful: Riverflow V2 Max Preview', provider: 'Sourceful', input: 'text+image', output: 'image', params: '', pricing: 'оценка: output_image ~$0.13/image', imageUsd: 0.13 },
  { id: 'sourceful/riverflow-v2-standard-preview', name: 'Sourceful: Riverflow V2 Standard Preview', provider: 'Sourceful', input: 'text+image', output: 'image', params: '', pricing: 'оценка: output_image ~$0.08/image', imageUsd: 0.08 },
  { id: 'sourceful/riverflow-v2-fast-preview', name: 'Sourceful: Riverflow V2 Fast Preview', provider: 'Sourceful', input: 'text+image', output: 'image', params: '', pricing: 'оценка: output_image ~$0.04/image', imageUsd: 0.04 },
  { id: 'black-forest-labs/flux.2-flex', name: 'Black Forest Labs: FLUX.2 Flex', provider: 'Black Forest Labs', input: 'text+image', output: 'image', params: 'output_format, n, input_references, seed', pricing: 'input_image: $0.06/megapixel + output_image: $0.06/megapixel', mpUsd: 0.12 },
  { id: 'black-forest-labs/flux.2-pro', name: 'Black Forest Labs: FLUX.2 Pro', provider: 'Black Forest Labs', input: 'text+image', output: 'image', params: 'output_format, n, input_references, seed', pricing: 'output_image: $0.03/megapixel', mpUsd: 0.03 },
  { id: 'google/gemini-3-pro-image-preview', name: 'Google: Nano Banana Pro (Gemini 3 Pro Image Preview)', provider: 'Google Vertex', input: 'image+text', output: 'image+text', params: 'resolution, aspect_ratio, n, input_references', pricing: 'оценка: output_image ~$0.00012/token', token: true },
  { id: 'openai/gpt-5-image-mini', name: 'OpenAI: GPT-5 Image Mini', provider: 'OpenAI', input: 'file+image+text', output: 'image+text', params: 'quality, background, n, input_references, output_compression', pricing: 'output_image: $0.000008/token', token: true },
  { id: 'openai/gpt-5-image', name: 'OpenAI: GPT-5 Image', provider: 'OpenAI', input: 'image+text+file', output: 'image+text', params: 'quality, background, n, input_references, output_compression', pricing: 'output_image: $0.00004/token', token: true },
  { id: 'google/gemini-2.5-flash-image', name: 'Google: Nano Banana (Gemini 2.5 Flash Image)', provider: 'Google AI Studio', input: 'image+text', output: 'image+text', params: 'aspect_ratio, n, input_references', pricing: 'оценка: output_image ~$0.00006/token', token: true },
  { id: 'google/gemini-2.5-flash-image-preview', name: 'Google: Gemini 2.5 Flash Image Preview (Nano Banana)', provider: 'Google', input: 'image+text', output: 'image+text', params: '', pricing: 'оценка: output_image ~$0.00006/token', token: true },
  { id: 'openrouter/auto', name: 'Auto Router', provider: 'OpenRouter', input: 'text+image+audio+file+video', output: 'text+image', params: '', pricing: 'оценка: fallback до $0.15/image', imageUsd: 0.15 },
]

const API_MODE_SECTIONS: ApiModeSection[] = [
  { id: 'text_to_image', title: 'По тексту', local: 'Flux 2 Klein 4B', note: 'Принимает текст и возвращает растровое изображение.', filter: (m) => Boolean(m.modes?.includes('text_to_image')) },
  { id: 'image_to_image', title: 'По фото — одно изображение', local: 'Flux 2 Klein 4B', note: 'Только модели с input_references и лимитом не меньше одного изображения.', filter: (m) => Boolean(m.modes?.includes('image_to_image')) },
  { id: 'edit', title: 'Сборка — несколько изображений', local: 'Flux 2 Klein 9B', note: 'Только модели, которые официально принимают два и более референса.', filter: (m) => Boolean(m.modes?.includes('edit')) },
  { id: 'paint', title: 'Редактор — эскиз и правки', local: 'Flux 2 Klein edit workflow', note: 'Модель принимает нарисованный или загруженный исходник как референс.', filter: (m) => Boolean(m.modes?.includes('paint')) },
  { id: 'inpaint', title: 'Редактор — маска', local: 'Flux 2 Klein inpaint workflow', note: 'Строгий список: только модели с явно заявленным mask/inpaint параметром.', filter: (m) => Boolean(m.modes?.includes('inpaint')) },
  { id: 'outpaint', title: 'Редактор — расширение', local: 'Flux 2 Klein outpaint workflow', note: 'Строгий список: только модели с явно заявленным outpaint/canvas параметром.', filter: (m) => Boolean(m.modes?.includes('outpaint')) },
  { id: 'remove_background', title: 'Редактор — удалить фон', local: 'локальный workflow/утилита', note: 'Исходник плюс официальная поддержка прозрачного background.', filter: (m) => Boolean(m.modes?.includes('remove_background')) },
]

const fallbackReferenceLimit = (model: ApiImageModel) => {
  if (!model.params.includes('input_references')) return 0
  if (model.id.startsWith('openai/')) return 16
  if (model.id.includes('gemini-3')) return 14
  if (model.id === 'google/gemini-2.5-flash-image') return 3
  if (model.id === 'bytedance-seed/seedream-4.5') return 14
  if (model.id === 'black-forest-labs/flux.2-klein-4b') return 4
  if (model.id.startsWith('black-forest-labs/')) return 8
  if (model.id === 'sourceful/riverflow-v2-pro' || model.id === 'sourceful/riverflow-v2.5-pro') return 10
  if (model.id.startsWith('sourceful/riverflow-v2')) return 4
  if (model.id.startsWith('recraft/')) return 1
  if (model.id.startsWith('microsoft/')) return 1
  if (model.id.startsWith('x-ai/')) return 3
  return 0
}

type AssistantModelPlan = {
  task: 'Транскрибация' | 'Улучшение промпта'
  role: 'Основная' | 'Резерв' | 'Кандидат' | 'Аварийная'
  model: string
  runtime: string
  hardware: string
  strengths: string
  limitations: string
  status: 'Рекомендуется' | 'Проверить' | 'Планируется'
}

type AssistantConfig = {
  voice: { localModel: string; apiModel: string; route: string; queueTimeoutSeconds: number; requestTimeoutSeconds: number; minRecordingSeconds: number }
  improve: { route: 'local' | 'api' | 'auto'; localModel: string; apiModel: string; localTimeoutSeconds: number; apiTimeoutSeconds: number; systemPrompt: string; modePrompts: Record<string, string> }
}
type AssistantAdminData = {
  ok?: boolean
  config: AssistantConfig
  ollama: { ok: boolean; baseUrl: string; error?: string; models: Array<{ name?: string; model?: string; size?: number; details?: { parameter_size?: string; quantization_level?: string } }> }
  openrouterConfigured: boolean
  openrouterModels: Array<{ id: string; name: string; inputPerMillionUsd: number; outputPerMillionUsd: number; contextLength: number }>
  openrouterModelsError?: string | null
}
type AssistantTestResult = { ok?: boolean; provider?: string; model?: string; improvedPrompt?: string; latencyMs?: number; costUsd?: number; detail?: string }

const ASSISTANT_MODE_LABELS: Record<string, string> = {
  text: 'По тексту', i2i: 'По фото', edit: 'Сборка', sketch: 'Эскиз', mask: 'Маска', outpaint: 'Расширение', remove_bg: 'Удалить фон',
}

const ASSISTANT_MODEL_PLAN: AssistantModelPlan[] = [
  { task: 'Транскрибация', role: 'Основная', model: 'Qwen3-ASR 1.7B', runtime: 'Локально', hardware: 'RTX 4070 12 ГБ', strengths: 'Лёгкая современная ASR, высокая скорость, русский язык', limitations: 'До запуска нужен собственный тест речи, шума и пауз', status: 'Проверить' },
  { task: 'Транскрибация', role: 'Кандидат', model: 'Faster Whisper Large V3 Turbo', runtime: 'Локально', hardware: 'RTX 4070 12 ГБ', strengths: 'Зрелый production-стек, VAD, предсказуемая интеграция', limitations: 'Тяжелее Qwen3-ASR; нужна защита от текста на тишине', status: 'Рекомендуется' },
  { task: 'Транскрибация', role: 'Кандидат', model: 'Qwen3-ASR 0.6B', runtime: 'Локально', hardware: 'RTX 4070 или CPU', strengths: 'Минимальная нагрузка и быстрая короткая диктовка', limitations: 'Качество русского требуется сравнить с версией 1.7B', status: 'Проверить' },
  { task: 'Транскрибация', role: 'Аварийная', model: 'Whisper Medium INT8', runtime: 'Локально', hardware: 'i5 10-го поколения / RAM', strengths: 'Работает без GPU и внешнего API', limitations: 'Высокая нагрузка CPU и очередь при параллельных запросах', status: 'Планируется' },
  { task: 'Транскрибация', role: 'Резерв', model: 'Gemini 3.1 Flash Lite Audio', runtime: 'OpenRouter API', hardware: 'Облако', strengths: 'Аудиовход, дешёвый автоматический резерв', limitations: 'Платный вызов; форматы WebM/Opus нужно проверить живым тестом', status: 'Планируется' },
  { task: 'Транскрибация', role: 'Резерв', model: 'GPT Audio Mini', runtime: 'OpenRouter API', hardware: 'Облако', strengths: 'Альтернативный провайдер аудиораспознавания', limitations: 'Использовать только при недоступности основного API-маршрута', status: 'Планируется' },
  { task: 'Улучшение промпта', role: 'Основная', model: 'Gemma 4 12B Q4', runtime: 'Локально', hardware: 'RTX 4070 12 ГБ', strengths: 'Быстрый локальный текстовый помощник без цены за вызов', limitations: 'Нужны короткий контекст и диспетчер VRAM; это не ASR-модель', status: 'Рекомендуется' },
  { task: 'Улучшение промпта', role: 'Резерв', model: 'DeepSeek V4 Flash', runtime: 'OpenRouter API', hardware: 'Облако', strengths: 'Недорогой structured output и хороший русский текст', limitations: 'Только текст: аудио не принимает', status: 'Планируется' },
]

const fallbackCapabilityModel = (model: ApiImageModel): ApiImageModel => {
  const maxInputReferences = fallbackReferenceLimit(model)
  const modes = ['text_to_image']
  if (maxInputReferences >= 1) modes.push('image_to_image', 'paint')
  if (maxInputReferences >= 2) modes.push('edit')
  if (maxInputReferences >= 1 && model.params.includes('background')) modes.push('remove_background')
  return { ...model, modes, maxInputReferences, description: 'Локальный резерв метаданных; обновится после подключения capability API.' }
}

const exchangeRate = (exchange?: PageData['openrouter']['exchange']) => typeof exchange?.rate === 'number' ? exchange.rate : null
const effectiveUsdRub = (exchange?: PageData['openrouter']['exchange']) => {
  const rate = exchangeRate(exchange)
  return rate === null ? null : rate * (1 + USD_FEE_RATE)
}
const rub = (usd: number, rate: number | null) => rate === null ? 'курс не загружен' : `${(usd * rate).toFixed(2)} ₽`
const SHORT_PROMPT_TEXT_TOKENS = 40
const OUTPUT_IMAGE_TOKENS_1MP = 1300
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
  return 'стартовая оценка до фактических генераций'
}
const modelImageUsdPrice = (m: ApiImageModel, actualUsdPerImage?: number | null) => {
  const estimated = estimatedUsdPerMp(m)
  if (typeof actualUsdPerImage === 'number') return Math.max(estimated || 0, actualUsdPerImage)
  return estimated
}
const minTokenTier = (m: ApiImageModel) => {
  if (m.id === 'black-forest-labs/flux.2-klein-4b') return 1
  if (m.id === 'black-forest-labs/flux.2-pro') return 2
  if (m.id === 'black-forest-labs/flux.2-max') return 3
  if (m.id === 'black-forest-labs/flux.2-flex') return 4
  return 1
}
const clampMargin = (value: unknown) => {
  const n = typeof value === 'number' ? value : 40
  return Math.max(0, Math.min(95, n))
}
const clampTokenRub = (value: unknown) => {
  const n = typeof value === 'number' ? value : DEFAULT_TOKEN_RUB
  return Math.max(0.01, Math.min(100000, n))
}
const costRubForModel = (m: ApiImageModel, actualUsdPerImage: number | null | undefined, rate: number | null) => {
  const value = modelImageUsdPrice(m, actualUsdPerImage)
  return value === null || rate === null ? null : value * rate
}
const tokenPriceForModel = (m: ApiImageModel, actualUsdPerImage: number | null | undefined, rate: number | null, minMarginPercent: number, tokenRub: number) => {
  const costRub = costRubForModel(m, actualUsdPerImage, rate)
  if (costRub === null) return null
  const marginFactor = Math.max(0.05, 1 - clampMargin(minMarginPercent) / 100)
  return Math.max(minTokenTier(m), Math.ceil(costRub / tokenRub), Math.ceil(costRub / (tokenRub * marginFactor)))
}
const revenueRub = (tokens: number | null, tokenRub: number) => tokens === null ? null : tokens * tokenRub
const profitRub = (revenue: number | null, cost: number | null) => revenue === null || cost === null ? null : revenue - cost
const marginPercent = (revenue: number | null, profit: number | null) => revenue && profit !== null ? (profit / revenue) * 100 : null
const rubText = (value: number | null) => value === null ? '—' : `${value.toFixed(2)} ₽`
const percentText = (value: number | null) => value === null ? '—' : `${value.toFixed(0)}%`
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
const projectTokensForUsd = (usdValue: unknown, rate: number | null, tokenRub: number) => typeof usdValue === 'number' && rate !== null ? Math.ceil((usdValue * rate) / tokenRub) : null
const tokensText = (usdValue: unknown, rate: number | null, tokenRub: number) => {
  const tokens = projectTokensForUsd(usdValue, rate, tokenRub)
  return tokens === null ? '—' : `${tokens} ток.`
}
const formatMoneyRub = (value: unknown) => typeof value === 'number' ? `${value.toFixed(2)} ₽` : '—'
const formatMoneyUsd = (value: unknown) => typeof value === 'number' ? `$${value.toFixed(4)}` : '—'
const formatCompactRub = (value: unknown) => typeof value === 'number' ? `${value.toFixed(value >= 10 ? 0 : 2)} ₽` : '—'
const backendPrimaryFormat = (price?: BackendOpenRouterPrice) => price?.formats?.find((f) => f.id === 'square') || price?.formats?.[0]
const formatEconomicsCell = (fmt: OpenRouterFormatEconomics | undefined, minMarginPercent: number) => {
  if (!fmt || fmt.supported === false) return <span className="format-empty">—</span>
  const margin = typeof fmt.marginPercent === 'number' ? fmt.marginPercent : null
  const marginClass = margin !== null && margin < minMarginPercent ? 'risk-high' : 'risk-low'
  return <div className="format-econ" title={`${fmt.label}: запрос ${fmt.requestSize || 'auto'}, биллинг ${fmt.billingWidth || '?'}x${fmt.billingHeight || '?'}`}>
    <strong>{formatMoneyRub(fmt.costRub)} <em>{formatMoneyUsd(fmt.costUsd)}</em></strong>
    <span>{fmt.tokens ?? '—'} ток. · выр. {formatCompactRub(fmt.revenueRub)}</span>
    <span className={marginClass}>выг. {formatCompactRub(fmt.profitRub)} · {percentText(margin)}</span>
  </div>
}
const fetchBrowserUsdRub = async (): Promise<PageData['openrouter']['exchange']> => {
  try {
    const response = await fetch('https://www.cbr-xml-daily.ru/daily_json.js', { cache: 'no-store' })
    if (!response.ok) throw new Error(`CBR JSON HTTP ${response.status}`)
    const payload = await response.json() as { Date?: string; Timestamp?: string; Valute?: { USD?: { Value?: number } } }
    const rate = payload.Valute?.USD?.Value
    if (typeof rate !== 'number') throw new Error('CBR JSON: USD не найден')
    return {
      rate,
      source: 'ЦБ РФ',
      sourceUrl: 'https://www.cbr-xml-daily.ru/daily_json.js',
      sourceDate: payload.Date || payload.Timestamp || '',
      fetchedAt: new Date().toISOString(),
      cache: 'browser_cbr',
      fallback: false,
    }
  } catch (cbrError) {
    const response = await fetch('https://open.er-api.com/v6/latest/USD', { cache: 'no-store' })
    if (!response.ok) throw new Error(`market rate HTTP ${response.status}`, { cause: cbrError })
    const payload = await response.json() as { rates?: Record<string, number>; time_last_update_utc?: string }
    const rate = payload.rates?.RUB
    if (typeof rate !== 'number') throw new Error('market rate: RUB не найден', { cause: cbrError })
    return {
      rate,
      source: 'USD/RUB market',
      sourceUrl: 'https://open.er-api.com/v6/latest/USD',
      sourceDate: payload.time_last_update_utc || '',
      fetchedAt: new Date().toISOString(),
      cache: 'browser_market',
      fallback: false,
      warning: cbrError instanceof Error ? cbrError.message : String(cbrError),
    }
  }
}
const sortedApiRows = (rows: ApiImageModel[], sort: ApiSortState, stats: Map<string, Record<string, unknown>>, rate: number | null, minMarginPercent: number, tokenRub: number, backendPricing: Map<string, BackendOpenRouterPrice>) => [...rows].sort((a, b) => {
  const economics = (m: ApiImageModel) => {
    const backend = backendPrimaryFormat(backendPricing.get(m.id))
    if (backend) {
      return {
        cost: typeof backend.costRub === 'number' ? backend.costRub : null,
        tokens: typeof backend.tokens === 'number' ? backend.tokens : null,
        revenue: typeof backend.revenueRub === 'number' ? backend.revenueRub : null,
        profit: typeof backend.profitRub === 'number' ? backend.profitRub : null,
        margin: typeof backend.marginPercent === 'number' ? backend.marginPercent : null,
      }
    }
    const modelStats = stats.get(m.id)
    const avgImageUsd = typeof modelStats?.avgCostUsd === 'number' ? modelStats.avgCostUsd : null
    const cost = costRubForModel(m, avgImageUsd, rate)
    const tokens = tokenPriceForModel(m, avgImageUsd, rate, minMarginPercent, tokenRub)
    const revenue = revenueRub(tokens, tokenRub)
    const profit = profitRub(revenue, cost)
    const margin = marginPercent(revenue, profit)
    return { cost, tokens, revenue, profit, margin }
  }
  const compareNullable = (av: number | null, bv: number | null) => {
    if (av === null && bv === null) return modelShortName(a).localeCompare(modelShortName(b), 'ru')
    if (av === null) return 1
    if (bv === null) return -1
    return av - bv || modelShortName(a).localeCompare(modelShortName(b), 'ru')
  }
  let result = 0
  if (sort.key === 'name') result = modelShortName(a).localeCompare(modelShortName(b), 'ru')
  if (sort.key === 'provider') result = modelBrand(a).localeCompare(modelBrand(b), 'ru') || modelShortName(a).localeCompare(modelShortName(b), 'ru')
  if (sort.key === 'price') {
    result = compareNullable(economics(a).cost, economics(b).cost)
  }
  if (sort.key === 'tokens') result = compareNullable(economics(a).tokens, economics(b).tokens)
  if (sort.key === 'revenue') result = compareNullable(economics(a).revenue, economics(b).revenue)
  if (sort.key === 'profit') result = compareNullable(economics(a).profit, economics(b).profit)
  if (sort.key === 'margin') result = compareNullable(economics(a).margin, economics(b).margin)
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
.amv2 .state.rate-ok{color:var(--green);border-color:rgba(112,221,120,.28)}.amv2 .state.rate-stale{color:var(--yellow);border-color:rgba(216,187,97,.28)}.amv2 .state.rate-bad{color:var(--red);border-color:rgba(255,116,121,.28)}
.amv2 button.state{cursor:pointer}
.amv2 button.state:disabled{opacity:.75;cursor:wait}
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
.amv2 .server-command{display:flex;align-items:center;gap:10px;margin-bottom:12px;padding:10px 12px;border:1px solid var(--line);border-radius:var(--radius);background:var(--panel)}
.amv2 .server-command .server-title{min-width:0;margin-right:auto}.amv2 .server-command h2{margin:0;font-size:16px}.amv2 .server-command p{margin:2px 0 0;color:var(--muted);font-size:11px}
.amv2 .profile-switch{display:grid;grid-template-columns:1fr 1fr;gap:4px;padding:3px;border:1px solid var(--line-strong);border-radius:7px;background:#0b0e0b}
.amv2 .profile-switch button{min-width:86px;height:32px;border:0;border-radius:5px;background:transparent;color:var(--muted);font-weight:750}.amv2 .profile-switch button.active{background:var(--lime);color:#080a07}
.amv2 .server-restart{height:38px;white-space:nowrap}
.amv2 .server-stop{height:38px;white-space:nowrap}
.amv2 .server-layout{display:grid;grid-template-columns:minmax(0,1.55fr) minmax(320px,.75fr);gap:12px;margin-bottom:12px}
.amv2 .server-overview{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;padding:12px}
.amv2 .server-metric{min-height:76px;padding:10px;border:1px solid var(--line);border-radius:7px;background:rgba(255,255,255,.025)}
.amv2 .server-metric span{display:block;color:var(--muted);font-size:10px;text-transform:uppercase}.amv2 .server-metric strong{display:block;margin-top:8px;font-size:17px}.amv2 .server-metric small{display:block;margin-top:3px;color:var(--muted);font-size:10px}
.amv2 .profile-summary{padding:12px}.amv2 .profile-summary h3{margin:0 0 6px;font-size:17px}.amv2 .profile-summary p{margin:0 0 12px;color:var(--muted);font-size:12px;line-height:1.45}
.amv2 .profile-facts{display:grid;grid-template-columns:1fr 1fr;gap:7px}.amv2 .profile-facts div{padding:8px;border:1px solid var(--line);border-radius:6px}.amv2 .profile-facts span{display:block;color:var(--muted);font-size:9px;text-transform:uppercase}.amv2 .profile-facts strong{font-size:12px}
.amv2 .route-strip{display:flex;flex-wrap:wrap;gap:6px;padding:0 12px 12px}.amv2 .route-chip{display:flex;align-items:center;gap:6px;padding:5px 8px;border:1px solid var(--line);border-radius:6px;font-size:10px}.amv2 .route-chip b{color:var(--lime)}
.amv2 .lora-table{padding:0 12px 12px}.amv2 .lora-row{display:grid;grid-template-columns:34px minmax(190px,1.2fr) minmax(160px,.75fr) minmax(200px,1fr) 92px;align-items:center;gap:10px;min-height:54px;border-top:1px solid var(--line)}
.amv2 .lora-row:first-child{border-top:0}.amv2 .lora-row h3{margin:0;font-size:12px;overflow-wrap:anywhere}.amv2 .lora-row p{margin:2px 0 0;color:var(--muted);font-size:10px}.amv2 .lora-compat{display:flex;flex-wrap:wrap;gap:4px}.amv2 .lora-compat span{padding:3px 6px;border:1px solid var(--line);border-radius:5px;color:var(--muted);font-size:9px}.amv2 .lora-row.incompatible{opacity:.48}.amv2 .lora-row input[type=checkbox]{width:17px;height:17px;accent-color:var(--lime)}
.amv2 .lora-columns{display:grid;grid-template-columns:1fr 1fr;gap:12px;padding:12px}.amv2 .lora-column{min-width:0;border:1px solid var(--line);border-radius:7px;overflow:hidden}.amv2 .lora-column-head{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:10px 12px;background:rgba(255,255,255,.035);border-bottom:1px solid var(--line)}.amv2 .lora-column-head h3{margin:0;font-size:13px}.amv2 .lora-column .lora-row{grid-template-columns:28px minmax(160px,1fr) 88px;padding:0 10px}.amv2 .lora-column .lora-row>div:nth-child(3){grid-column:2 / -1;padding-bottom:8px}.amv2 .lora-empty{padding:18px 12px;color:var(--muted);font-size:11px}
.amv2 .config-profiles{display:grid;grid-template-columns:1fr 1fr;gap:12px;padding:12px}.amv2 .config-profile{border:1px solid var(--line);border-radius:7px;overflow:hidden}.amv2 .config-profile.active{border-color:rgba(218,255,47,.55)}.amv2 .config-profile-head{display:flex;align-items:center;justify-content:space-between;padding:10px 12px;border-bottom:1px solid var(--line);background:rgba(255,255,255,.025)}.amv2 .config-profile-head h3{margin:0;font-size:13px}.amv2 .config-fields{display:grid;grid-template-columns:1fr 1fr;gap:8px;padding:12px}.amv2 .config-field label{display:block;margin-bottom:4px;color:var(--muted);font-size:9px;text-transform:uppercase}.amv2 .config-field input,.amv2 .config-field select{width:100%;height:34px}.amv2 .dependency-note{display:grid;grid-template-columns:1fr 1fr;gap:8px;padding:0 12px 12px}.amv2 .dependency-note div{padding:9px;border:1px solid var(--line);border-radius:6px}.amv2 .dependency-note strong{display:block;font-size:11px}.amv2 .dependency-note span{display:block;margin-top:3px;color:var(--muted);font-size:10px;line-height:1.4}
.amv2 .resolution-matrix{margin:12px 12px 0;border:1px solid var(--line);border-radius:7px;overflow:auto}.amv2 .resolution-matrix table{min-width:940px;table-layout:fixed}.amv2 .resolution-matrix th,.amv2 .resolution-matrix td{height:auto;padding:9px 10px;text-align:left;border-bottom:1px solid var(--line);font-size:11px;vertical-align:top}.amv2 .resolution-matrix tr:last-child td{border-bottom:0}.amv2 .resolution-matrix th{color:var(--muted);background:rgba(255,255,255,.035);font-size:9px;text-transform:uppercase}.amv2 .resolution-matrix th:first-child{width:160px}.amv2 .resolution-format{display:grid;gap:3px}.amv2 .resolution-format strong{font-size:12px}.amv2 .resolution-format span,.amv2 .resolution-value small{color:var(--muted);font-size:9px}.amv2 .resolution-cell{display:grid;gap:7px;min-width:0}.amv2 .resolution-value{display:flex;align-items:baseline;justify-content:flex-start;gap:12px;white-space:nowrap}.amv2 .resolution-value strong{font-size:11px;font-variant-numeric:tabular-nums}.amv2 .resolution-plans{display:flex;align-items:flex-start;justify-content:flex-start;gap:9px;width:max-content}.amv2 .resolution-plan{display:grid;grid-template-rows:15px auto;justify-items:center;gap:3px;width:28px;color:var(--muted);font-size:8px;text-transform:uppercase;cursor:pointer}.amv2 .resolution-plan input{width:15px;height:15px;min-height:15px;margin:0;accent-color:var(--lime)}
.amv2 .server-tools{padding:10px 12px;border-top:1px solid var(--line)}.amv2 .server-tools summary{cursor:pointer;color:var(--muted);font-size:11px;font-weight:700}.amv2 .server-tools .ops-row{padding:10px 0 0;border:0;grid-template-columns:minmax(220px,1fr) auto auto}
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
.amv2 .or-stats{display:grid;grid-template-columns:repeat(9,minmax(0,1fr));gap:8px;padding:0 0 12px;border-bottom:1px solid var(--line)}
.amv2 .or-stat{border:1px solid var(--line);border-radius:var(--radius);padding:10px;background:rgba(255,255,255,.032)}
.amv2 .or-stat span{display:block;color:var(--muted);font-size:11px;font-weight:650}.amv2 .or-stat strong{display:block;margin-top:5px;font-size:15px;color:var(--lime);font-weight:700}
.amv2 .or-stat input{margin-top:5px;min-height:28px;padding:0 8px;font-size:13px;color:var(--lime);font-weight:700}
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
.amv2 .quality-row{display:grid;grid-template-columns:repeat(3,minmax(180px,1fr));gap:8px;margin:0 12px 8px}
.amv2 .quality-row label{display:grid;grid-template-columns:78px minmax(0,1fr);gap:8px;align-items:center;border:1px solid var(--line);border-radius:var(--radius);background:rgba(255,255,255,.026);padding:6px 8px}
.amv2 .quality-row span{color:var(--muted);font-size:11px;font-weight:750}
.amv2 .quality-row select{min-height:28px;font-size:12px;padding:0 8px}
.amv2 .api-table{min-width:1420px}
.amv2 .api-table.format-table{min-width:1680px}
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
.amv2 .tier-checks{display:flex;align-items:center;gap:5px;white-space:nowrap}
.amv2 .tier-checks label{display:inline-flex;align-items:center;gap:3px;color:var(--muted);font-size:10px;font-weight:800}
.amv2 .tier-checks input{width:13px;height:13px;min-height:13px;padding:0;margin:0}
.amv2 .tier-checks input:checked + span{color:var(--lime)}
.amv2 .tier-checks.tier-head label{font-size:10px;text-transform:none;letter-spacing:0}
.amv2 .api-table .provider{font-size:11px;padding:2px 6px}
.amv2 .api-table .money{font-size:12px}
.amv2 .money{font-weight:650;color:var(--lime);white-space:nowrap}
.amv2 .format-head{min-width:160px}
.amv2 .format-head span{display:block;margin-top:2px;color:var(--muted);font-size:9px;font-weight:650;text-transform:uppercase;letter-spacing:.03em}
.amv2 .format-cell{min-width:160px}
.amv2 .format-econ{display:grid;gap:2px;line-height:1.08;white-space:nowrap}
.amv2 .format-econ strong{color:var(--lime);font-size:11px;font-weight:700}
.amv2 .format-econ em{color:var(--text);font-style:normal;font-weight:650;margin-left:4px}
.amv2 .format-econ span{font-size:10px;color:var(--muted)}
.amv2 .format-empty{color:var(--muted);font-size:12px}
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
.amv2 select,.amv2 input{width:100%;min-height:34px;border:1px solid var(--line-strong);border-radius:var(--radius);color:var(--text);background:rgba(255,255,255,.055);padding:0 10px;outline:none;color-scheme:dark}
.amv2 select option,.amv2 select optgroup{color:#f4f5ee;background:#151815}
.amv2 select option:checked{color:#101204;background:#dfff20}
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
@media (hover:hover){.amv2 .primary:hover,.amv2 .page-tabs button.active:hover,.amv2 .segmented button.active:hover{color:#080a07}.amv2 .primary:hover *,.amv2 .page-tabs button.active:hover *,.amv2 .segmented button.active:hover *{color:#080a07}}
.amv2 .matrix-wrap{overflow-x:auto}
.amv2 table{width:100%;border-collapse:collapse;min-width:820px}
.amv2 .assistant-summary{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin-bottom:12px}
.amv2 .assistant-summary>div{padding:13px;border:1px solid var(--line);border-radius:var(--radius);background:rgba(255,255,255,.032);display:grid;gap:5px}
.amv2 .assistant-summary span{color:var(--muted);font-size:11px;font-weight:800;text-transform:uppercase}
.amv2 .assistant-summary strong{font-size:14px;color:var(--lime)}
.amv2 .assistant-summary small{color:var(--muted);line-height:1.35}
.amv2 .assistant-table th,.amv2 .assistant-table td{text-align:left;vertical-align:top;padding:10px 12px;border-bottom:1px solid var(--line);font-size:12px;line-height:1.35}
.amv2 .assistant-table th{color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:.04em;background:rgba(255,255,255,.025)}
.amv2 .assistant-table td strong{display:block;color:var(--text);margin-bottom:3px}
.amv2 .assistant-table td small{color:var(--muted)}
.amv2 .assistant-status{display:inline-flex;padding:3px 7px;border:1px solid var(--line-strong);border-radius:999px;white-space:nowrap;color:var(--muted)}
.amv2 .assistant-status.recommended{color:var(--lime);border-color:rgba(234,255,16,.35)}
.amv2 .assistant-config{display:grid;grid-template-columns:minmax(0,1.25fr) minmax(300px,.75fr);gap:12px}
.amv2 .assistant-form{padding:14px;display:grid;gap:12px}
.amv2 .assistant-form textarea,.amv2 .assistant-test textarea{font-size:13px;font-weight:400;letter-spacing:0;line-height:1.45}
.amv2 .assistant-form textarea{min-height:108px;resize:vertical}
.amv2 .assistant-form .mode-prompt{min-height:86px}
.amv2 .assistant-test{padding:14px;display:grid;gap:10px;align-content:start}
.amv2 .assistant-test-result{padding:12px;border:1px solid var(--line);border-radius:var(--radius);background:rgba(255,255,255,.03);display:grid;gap:6px}
.amv2 .assistant-test-result small{color:var(--muted)}
.amv2 .ollama-list{display:grid;gap:7px}
.amv2 .ollama-row{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:10px;padding:9px;border:1px solid var(--line);border-radius:var(--radius)}
.amv2 .ollama-row small{color:var(--muted)}
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
@media (max-width:1360px){.amv2 .dashboard,.amv2 .server-layout{grid-template-columns:1fr}.amv2 .metric-grid,.amv2 .lora-grid,.amv2 .status-grid,.amv2 .mode-board{grid-template-columns:repeat(2,minmax(0,1fr))}.amv2 .api-section-head{grid-template-columns:minmax(220px,1.4fr) repeat(3,minmax(100px,.8fr)) minmax(150px,1fr)}.amv2 .grid-main{grid-template-columns:1fr}.amv2 .side-panel{position:static}}
@media (max-width:880px){.amv2 .route-row,.amv2 .toolbar,.amv2 .ops-row,.amv2 .job-row,.amv2 .api-key-panel,.amv2 .or-stats,.amv2 .api-section-head,.amv2 .assistant-config{grid-template-columns:1fr}.amv2 .server-command{align-items:stretch;flex-wrap:wrap}.amv2 .server-command .server-title{width:100%}.amv2 .profile-switch{flex:1}.amv2 .lora-columns,.amv2 .config-profiles{grid-template-columns:1fr}.amv2 .lora-row{grid-template-columns:28px 1fr 80px}.amv2 .lora-row>div:nth-child(3),.amv2 .lora-row>div:nth-child(4){grid-column:2 / -1}.amv2 .tab-status{margin-left:0;width:100%;flex-wrap:wrap}.amv2 .page-tabs{flex-wrap:wrap}.amv2 .matrix-wrap{overflow-x:auto}.amv2 .matrix-wrap table{min-width:980px}.amv2 .matrix-wrap .api-table{min-width:760px}.amv2 .matrix-wrap .api-table.format-table{min-width:1500px}.amv2 .mobile-models{display:grid}}
@media (max-width:580px){.amv2 .metric-grid,.amv2 .two-col,.amv2 .price-row,.amv2 .lora-grid,.amv2 .advanced-grid,.amv2 .status-grid,.amv2 .mode-board,.amv2 .or-stats,.amv2 .server-overview,.amv2 .assistant-summary{grid-template-columns:1fr}.amv2 .profile-switch{width:100%}.amv2 .server-restart{width:100%}}
`

export default function AdminModelsV2() {
  const [data, setData] = useState<PageData | null>(null)
  const [pageTab, setPageTab] = useState<'config' | 'api' | 'voice' | 'improve'>('api')
  const [configStatus, setConfigStatus] = useState<ConfigStatus | null>(null)
  const [routes, setRoutes] = useState<Route[]>([])
  const [query, setQuery] = useState('')
  const [marginDraft, setMarginDraft] = useState('40')
  const [tokenRubDraft, setTokenRubDraft] = useState('5')
  const [apiSorts, setApiSorts] = useState<Record<string, ApiSortState>>({})
  const [apiSectionsOpen, setApiSectionsOpen] = useState<Record<string, boolean>>({ text_to_image: true })
  const [apiExpandedRows, setApiExpandedRows] = useState<Record<string, boolean>>({})
  const [openrouterKeyInput, setOpenrouterKeyInput] = useState('')
  const [openrouterBusy, setOpenrouterBusy] = useState(false)
  const [openrouterConfigBusy, setOpenrouterConfigBusy] = useState(false)
  const [openrouterTestBusy, setOpenrouterTestBusy] = useState(false)
  const [exchangeBusy, setExchangeBusy] = useState(false)
  const [openrouterTestResult, setOpenrouterTestResult] = useState<OpenRouterTestResult | null>(null)
  const [msg, setMsg] = useState('')
  const [err, setErr] = useState('')
  const [configErr, setConfigErr] = useState('')
  const opsReason = 'ручная операция в админке Config UI'
  const [opsBusy, setOpsBusy] = useState(false)
  const [loraAccess, setLoraAccess] = useState<Record<string, boolean>>({})
  const [serverProfiles, setServerProfiles] = useState<Record<string, ServerModelProfileSettings>>({})
  const [tariffs, setTariffs] = useState<TariffConfig>(() => normalizeTariffs(null))
  const [assistantData, setAssistantData] = useState<AssistantAdminData | null>(null)
  const [assistantBusy, setAssistantBusy] = useState(false)
  const [assistantTestPrompt, setAssistantTestPrompt] = useState('девушка стоит у окна вечером')
  const [assistantPreviewMode, setAssistantPreviewMode] = useState('text')
  const [assistantTestResult, setAssistantTestResult] = useState<AssistantTestResult | null>(null)

  const load = useCallback(async () => {
    const d = await amvFetch('/admin/models-page?local=0').then((r) => (r.ok ? r.json() : null)).catch(() => null) as PageData | null
    // Принимаем ответ только полной формы. Иначе — сообщение об ошибке, а не падение:
    // живой backend мог не содержать /api/admin/models-page или вернуть 403/500 с JSON-телом.
    const ok = !!d && Array.isArray(d.matrix) && Array.isArray(d.routes) && !!d.economy
      && !!d.userChoice && Array.isArray(d.userChoice.simple) && Array.isArray(d.userChoice.pro)
      && Array.isArray(d.catalog) && Array.isArray(d.loras) && !!d.comfyFiles && !!d.openrouter
    if (ok && d) {
      if (exchangeRate(d.openrouter.exchange) === null) {
        try {
          d.openrouter.exchange = await fetchBrowserUsdRub()
        } catch (e) {
          d.openrouter.exchange = {
            ...(d.openrouter.exchange || {}),
            rate: null,
            cache: 'error',
            error: e instanceof Error ? e.message : String(e),
          }
        }
      }
      setMarginDraft(String(clampMargin(d.openrouter.economy?.minMarginPercent)))
      setTokenRubDraft(String(clampTokenRub(d.openrouter.economy?.tokenRub)))
      setErr(''); setData(d); setRoutes(d.routes || [])
      setLoraAccess(d.loraSettings?.enabled || {})
      setServerProfiles(d.serverModelProfiles?.profiles || {})
    } else {
      setData(null)
      setErr('Не удалось загрузить страницу моделей. Нужен доступ администратора и обновлённый backend (/api/admin/models-page).')
    }
  }, [])
  useEffect(() => { queueMicrotask(() => { void load() }) }, [load])

  const loadLocalModelData = useCallback(async () => {
    const d = await amvFetch('/admin/models-page?local=1').then((r) => (r.ok ? r.json() : null)).catch(() => null) as PageData | null
    if (!d) return
    setData((current) => current ? { ...current, routes: d.routes, catalog: d.catalog, loras: d.loras, loraSettings: d.loraSettings, serverModelProfiles: d.serverModelProfiles, comfyuiAvailable: d.comfyuiAvailable, comfyFiles: d.comfyFiles, profiles: d.profiles, economy: d.economy } : d)
    setLoraAccess(d.loraSettings?.enabled || {})
    setServerProfiles(d.serverModelProfiles?.profiles || {})
    setRoutes(d.routes || [])
  }, [])

  const loadTariffs = useCallback(async () => {
    const result = await amvFetch('/admin/settings').then((r) => r.ok ? r.json() : null).catch(() => null) as { tariffs?: unknown; config_ui_resolution_access?: unknown } | null
    if (result?.tariffs) setTariffs(applyConfigUiResolutionAccess(normalizeTariffs(result.tariffs), result.config_ui_resolution_access))
  }, [])

  const loadConfigStatus = useCallback(async () => {
    const status = await amvFetch('/admin/config-ui/status-v2').then(async (r) => {
      if (r.ok) { setConfigErr(''); return await r.json() as ConfigStatus }
      setConfigErr(`/api/admin/config-ui/status-v2 -> HTTP ${r.status}`)
      return null
    }).catch((e) => {
      setConfigErr(e instanceof Error ? e.message : 'config status недоступен')
      return null
    }) as ConfigStatus | null
    if (status) setConfigStatus(status)
  }, [])

  useEffect(() => {
    if (pageTab !== 'config' || configStatus || configErr) return
    queueMicrotask(() => {
      void loadLocalModelData()
      void loadConfigStatus()
      void loadTariffs()
    })
  }, [configErr, configStatus, loadConfigStatus, loadLocalModelData, loadTariffs, pageTab])

  const loadAssistants = useCallback(async () => {
    const result = await amvFetch('/admin/assistants').then((r) => r.ok ? r.json() : null).catch(() => null) as AssistantAdminData | null
    if (result?.config) setAssistantData({ ...result, openrouterModels: Array.isArray(result.openrouterModels) ? result.openrouterModels : [] })
    else setMsg('Не удалось загрузить настройки голосового ввода и улучшения')
  }, [])

  useEffect(() => {
    if ((pageTab === 'voice' || pageTab === 'improve') && !assistantData) queueMicrotask(() => { void loadAssistants() })
  }, [assistantData, loadAssistants, pageTab])

  const updateAssistantConfig = (next: AssistantConfig) => setAssistantData((current) => current ? { ...current, config: next } : current)
  const saveAssistantConfig = async () => {
    if (!assistantData) return
    setAssistantBusy(true)
    await saveSetting('assistant_models', assistantData.config, 'Настройки помощников')
    setAssistantBusy(false)
    await loadAssistants()
  }
  const testPromptAssistant = async (provider: 'local' | 'api') => {
    setAssistantBusy(true); setAssistantTestResult(null)
    const result = await amvFetch('/admin/assistants/test', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider, prompt: assistantTestPrompt, mode: 'text', config: assistantData?.config.improve }),
    }).then(async (r) => ({ status: r.status, body: await r.json().catch(() => ({})) })).catch(() => null)
    setAssistantBusy(false)
    if (result?.status === 200) setAssistantTestResult(result.body as AssistantTestResult)
    else setAssistantTestResult({ detail: String((result?.body as { detail?: unknown } | undefined)?.detail || 'Тест не выполнен') })
  }

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
      setMsg(kind === 'reload' ? 'Config UI перезапущен, конфигурация и кэш обновлены' : 'Текущая задача Config UI остановлена')
      await loadConfigStatus()
    } else setMsg(r?.detail || 'Операция не выполнена')
  }

  async function saveSetting(key: string, payload: unknown, label: string) {
    const response = await amvFetch(`/admin/settings/${key}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ settings: payload }) }).catch(() => null)
    const result = response ? await response.json().catch(() => null) as { ok?: boolean; settings?: unknown; detail?: string } | null : null
    if (!response?.ok || !result?.ok) {
      setMsg(result?.detail || `Ошибка сохранения: ${label}`)
      return null
    }
    setMsg(`${label} сохранено`)
    return result.settings ?? payload
  }
  const globalLocalProfile = routes.find((route) => route.provider === 'local')?.modelProfileId || 'flux_klein_9b'
  const setGlobalLocalProfile = async (modelProfileId: string) => {
    setOpsBusy(true); setMsg('Переключаю модель и освобождаю память Config UI…')
    const result = await amvFetch('/admin/config-ui/switch-v2', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ profileId: modelProfileId, reason: 'глобальное переключение модели из админки' }) }).then((r) => r.json()).catch(() => null) as { ok?: boolean; status?: ConfigStatus; detail?: string } | null
    setOpsBusy(false)
    if (!result?.ok) { setMsg(result?.detail || 'Не удалось переключить модель Config UI'); return }
    setRoutes((current) => current.map((route) => route.provider === 'local' ? { ...route, modelProfileId } : route))
    if (result.status) setConfigStatus(result.status)
    setMsg(`Config UI переключён на ${modelProfileId.endsWith('9b') ? 'Klein 9B' : 'Klein 4B'}; предыдущая модель выгружена из памяти`)
    await loadLocalModelData()
  }
  const setLoraEnabled = (fileName: string, enabled: boolean) => {
    const next = { ...loraAccess, [fileName]: enabled }
    setLoraAccess(next)
    void saveSetting('server_model_loras', { enabled: next }, 'Доступность LoRA')
  }
  const updateServerProfile = (profileId: string, patch: Partial<ServerModelProfileSettings>) => setServerProfiles((current) => ({ ...current, [profileId]: { ...(current[profileId] || { width: 1024, height: 1024, steps: 4, sampler: 'er_sde', seedMode: 'random', seed: 42 }), ...patch } }))
  const toggleConfigResolution = (plan: TariffKey, resolutionId: string, enabled: boolean) => setTariffs((current) => {
    const ids = current[plan].allowed_resolutions
    const next = enabled ? Array.from(new Set([...ids, resolutionId])) : ids.filter((id) => id !== resolutionId)
    return { ...current, [plan]: { ...current[plan], allowed_resolutions: next } }
  })
  const saveConfigUiSettings = async () => {
    const resolutionAccess = { plans: Object.fromEntries(tariffKeys.map((plan) => [plan, tariffs[plan].allowed_resolutions])) }
    const accessSaved = await saveSetting('config_ui_resolution_access', resolutionAccess, 'Доступность разрешений по тарифам')
    if (!accessSaved) return
    const verified = await amvFetch('/admin/settings').then((r) => r.ok ? r.json() : null).catch(() => null) as { tariffs?: unknown; config_ui_resolution_access?: unknown } | null
    if (!verified?.tariffs || !verified.config_ui_resolution_access) { setMsg('Настройки сохранены, но контрольная проверка не выполнена'); return }
    const normalized = applyConfigUiResolutionAccess(normalizeTariffs(verified.tariffs), verified.config_ui_resolution_access)
    setTariffs(normalized)
    const expected = tariffKeys.every((plan) => [...tariffs[plan].allowed_resolutions].sort().join('|') === [...normalized[plan].allowed_resolutions].sort().join('|'))
    if (!expected) { setMsg('Сервер вернул другие настройки разрешений — изменения не применены полностью'); return }
    const profilesSaved = await saveSetting('server_model_profiles', { profiles: serverProfiles }, 'Параметры моделей Config UI')
    setMsg(profilesSaved ? 'Разрешения и параметры Config UI сохранены и проверены' : 'Разрешения сохранены; параметры модели сохранить не удалось')
  }
  const saveMinMargin = async () => {
    const minMarginPercent = clampMargin(Number(marginDraft))
    const tokenRub = clampTokenRub(data?.openrouter.economy?.tokenRub)
    setMarginDraft(String(minMarginPercent))
    setData((prev) => prev ? { ...prev, openrouter: { ...prev.openrouter, economy: { ...(prev.openrouter.economy || {}), minMarginPercent, tokenRub } } } : prev)
    await saveSetting('openrouter_economy', { minMarginPercent, tokenRub }, 'Экономика OpenRouter')
  }
  const saveTokenRub = async () => {
    const minMarginPercent = clampMargin(data?.openrouter.economy?.minMarginPercent)
    const tokenRub = clampTokenRub(Number(tokenRubDraft))
    setTokenRubDraft(String(tokenRub))
    setData((prev) => prev ? { ...prev, openrouter: { ...prev.openrouter, economy: { ...(prev.openrouter.economy || {}), minMarginPercent, tokenRub } } } : prev)
    await saveSetting('openrouter_economy', { minMarginPercent, tokenRub }, 'Экономика OpenRouter')
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
    const access: OpenRouterAccess = JSON.parse(JSON.stringify(current.access || {}))
    const qualityDefaults: OpenRouterQualityDefaults = JSON.parse(JSON.stringify(current.qualityDefaults || {}))
    const list = new Set(enabled[mode] || [])
    if (checked) list.add(modelId)
    else list.delete(modelId)
    const nextList = Array.from(list).sort()
    if (nextList.length) enabled[mode] = nextList
    else delete enabled[mode]
    if (!checked) {
      for (const q of OPENROUTER_QUALITY) {
        if (qualityDefaults[mode]?.[q.id] === modelId) delete qualityDefaults[mode]![q.id]
      }
    }
    if (checked && !defaults[mode]) defaults[mode] = modelId
    if (!checked && defaults[mode] === modelId) {
      if (nextList.length) defaults[mode] = nextList[0]
      else delete defaults[mode]
    }
    void saveOpenrouterConfig({ enabled, defaults, access, qualityDefaults })
  }

  const toggleOpenrouterSection = (mode: string, modelIds: string[], checked: boolean) => {
    if (!data) return
    const current = data.openrouter.config || { enabled: {}, defaults: {}, access: {}, qualityDefaults: {} }
    const enabled = { ...(current.enabled || {}) }
    const defaults = { ...(current.defaults || {}) }
    const access: OpenRouterAccess = JSON.parse(JSON.stringify(current.access || {}))
    const qualityDefaults: OpenRouterQualityDefaults = JSON.parse(JSON.stringify(current.qualityDefaults || {}))
    const ids = Array.from(new Set(modelIds)).sort()
    if (checked) {
      enabled[mode] = ids
      defaults[mode] = defaults[mode] && ids.includes(defaults[mode]) ? defaults[mode] : ids[0]
      access[mode] = { ...(access[mode] || {}) }
    } else {
      delete enabled[mode]
      delete defaults[mode]
      delete qualityDefaults[mode]
    }
    void saveOpenrouterConfig({ enabled, defaults, access, qualityDefaults })
  }

  const toggleOpenrouterTier = (mode: string, tier: OpenRouterTier, modelId: string, checked: boolean) => {
    if (!data) return
    const current = data.openrouter.config || { enabled: {}, defaults: {}, access: {}, qualityDefaults: {} }
    const enabled = { ...(current.enabled || {}) }
    const defaults = { ...(current.defaults || {}) }
    const access: OpenRouterAccess = JSON.parse(JSON.stringify(current.access || {}))
    const qualityDefaults: OpenRouterQualityDefaults = JSON.parse(JSON.stringify(current.qualityDefaults || {}))
    access[mode] = access[mode] || {}
    const values = new Set(access[mode][tier] || [])
    if (checked) values.add(modelId)
    else values.delete(modelId)
    if (values.size) access[mode][tier] = Array.from(values).sort()
    else delete access[mode][tier]
    if (!Object.keys(access[mode]).length) delete access[mode]
    void saveOpenrouterConfig({ enabled, defaults, access, qualityDefaults })
  }

  const toggleOpenrouterTierColumn = (mode: string, tier: OpenRouterTier, modelIds: string[], checked: boolean) => {
    if (!data) return
    const current = data.openrouter.config || { enabled: {}, defaults: {}, access: {}, qualityDefaults: {} }
    const enabled = { ...(current.enabled || {}) }
    const defaults = { ...(current.defaults || {}) }
    const access: OpenRouterAccess = JSON.parse(JSON.stringify(current.access || {}))
    const qualityDefaults: OpenRouterQualityDefaults = JSON.parse(JSON.stringify(current.qualityDefaults || {}))
    const ids = Array.from(new Set(modelIds)).sort()
    access[mode] = access[mode] || {}
    if (checked) access[mode][tier] = ids
    else delete access[mode][tier]
    if (!Object.keys(access[mode]).length) delete access[mode]
    void saveOpenrouterConfig({ enabled, defaults, access, qualityDefaults })
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

  const refreshExchange = async () => {
    setExchangeBusy(true); setMsg('Обновляю курс')
    let status = 0
    let raw = ''
    const r = await amvFetch('/admin/openrouter/exchange/refresh', { method: 'POST' })
      .then(async (x) => {
        status = x.status
        raw = await x.text()
        try { return JSON.parse(raw) } catch { return null }
      })
      .catch((e) => ({ ok: false, exchange: { error: e instanceof Error ? e.message : String(e) } })) as { ok?: boolean; exchange?: PageData['openrouter']['exchange'] } | null
    let exchange = r?.exchange
    let usedBrowserFallback = false
    if (!r?.ok || exchangeRate(exchange) === null) {
      try {
        exchange = await fetchBrowserUsdRub()
        usedBrowserFallback = true
      } catch (e) {
        exchange = { ...(exchange || {}), rate: null, cache: 'error', error: e instanceof Error ? e.message : String(e) }
      }
    }
    setExchangeBusy(false)
    if (exchange) {
      setData((prev) => prev ? { ...prev, openrouter: { ...prev.openrouter, exchange } } : prev)
    }
    const detail = exchange?.error || r?.exchange?.error || (status ? `HTTP ${status}: ${raw.slice(0, 120)}` : 'нет ответа backend')
    setMsg(exchangeRate(exchange) !== null ? (usedBrowserFallback ? 'Курс обновлён из браузера' : 'Курс обновлён') : `Курс не обновился: ${detail}`)
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

  const fmtTime = (value?: string) => value ? new Date(value).toLocaleString('ru-RU') : '—'
  const fmtState = (ok?: boolean) => configErr ? 'unknown' : ok ? 'ok' : 'fail'
  const statusColor = (ok?: boolean) => configErr ? 'var(--yellow)' : ok ? 'var(--green)' : 'var(--red)'

  if (!data) return <div className="amv2"><style>{CSS}</style><div style={{ padding: 12, display: 'grid', gap: 10 }}><p style={{ color: err ? 'var(--red)' : 'var(--muted)' }}>{err || 'Загрузка страницы моделей…'}</p>{err && <button className="ghost" style={{ width: 'max-content' }} onClick={() => void load()}>Повторить</button>}</div></div>

  const orStatus = data.openrouter.status || {}
  const orData = orStatus.data || {}
  const orCredits = orStatus.credits || {}
  const orCreditsData = orCredits.data && typeof orCredits.data === 'object' ? orCredits.data as Record<string, unknown> : {}
  const minMarginPercent = clampMargin(data.openrouter.economy?.minMarginPercent)
  const tokenRub = clampTokenRub(data.openrouter.economy?.tokenRub)
  const usdRubBase = exchangeRate(data.openrouter.exchange)
  const usdRubEffective = effectiveUsdRub(data.openrouter.exchange)
  const orStatusClass = orStatus.ok ? 'key-ok' : orStatus.configured ? 'key-bad' : 'key-warn'
  const orStatusText = orStatus.ok ? 'работает' : orStatus.configured ? 'ключ есть, проверка не прошла' : 'ключ не сохранён'
  const orLimit = orData.limit === null || orData.limit === undefined ? 'без лимита / не задан' : moneyUsdText(orData.limit)
  const orRemaining = orData.limit_remaining === null || orData.limit_remaining === undefined ? '—' : moneyUsdText(orData.limit_remaining)
  const orUsageModels = usageModelMap(data.openrouter.usage?.models)
  const orUsageModes = usageModeMap(data.openrouter.usage?.modes)
  const backendPricingMap = new Map((data.openrouter.backendPricing || []).map((m) => [m.id, m]))
  const liveCapabilityCatalog = data.openrouter.capabilityCatalog || []
  const capabilityModels: ApiImageModel[] = liveCapabilityCatalog.length ? liveCapabilityCatalog.map((model) => {
    const price = backendPricingMap.get(model.id)
    const provider = model.name.includes(':') ? model.name.split(':', 1)[0] : model.id.split('/', 1)[0]
    return {
      id: model.id,
      name: model.name,
      provider,
      input: model.inputModalities.join('+'),
      output: model.outputModalities.join('+'),
      params: model.parameters.join(', '),
      pricing: price ? `${price.pricing_type}: $${price.usd}` : 'нет проверенной backend-цены',
      modes: model.modes,
      maxInputReferences: model.maxInputReferences,
      description: model.description,
      supportsStreaming: model.supportsStreaming,
    }
  }) : OPENROUTER_IMAGE_MODELS.map(fallbackCapabilityModel)
  const backendPricedCount = backendPricingMap.size
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
    : `$1 ${usdRubBase.toFixed(2)} ₽ + ${Math.round(USD_FEE_RATE * 100)}% = ${usdRubEffective.toFixed(2)} ₽`
  const spentTokensText = tokensText(data.openrouter.usage?.totalCostUsd, usdRubEffective, tokenRub)
  const exchangeCache = data.openrouter.exchange?.cache || ''
  const exchangeStateClass = usdRubBase === null ? 'rate-bad' : exchangeCache === 'stale' ? 'rate-stale' : 'rate-ok'
  const exchangeStateText = usdRubBase === null ? 'курс не загружен' : exchangeCache === 'stale' ? 'курс из последнего кэша' : 'курс загружен'
  const selectedAssistantApiModel = assistantData?.openrouterModels.find((model) => model.id === assistantData.config.improve.apiModel)
  const assistantPreviewSystem = assistantData ? [
    assistantData.config.improve.systemPrompt.trim(),
    'Ответ верни на русском языке.',
    (assistantData.config.improve.modePrompts[assistantPreviewMode] || '').trim(),
    'Верни только JSON с одним строковым полем improved_prompt.',
  ].filter(Boolean).join(' ') : ''
  const assistantPreviewUser = JSON.stringify({ prompt: assistantTestPrompt.trim(), technical_context: null }, null, 2)

  return <div className="amv2">
    <style>{CSS}</style>
    {msg && <p style={{ color: 'var(--lime)', fontSize: 12, margin: '0 0 8px' }}>{msg}</p>}
    <div className="page-tabs" aria-label="Разделы моделей">
      <button className={pageTab === 'api' ? 'active' : ''} onClick={() => setPageTab('api')}>OpenRouter</button>
      <button className={pageTab === 'config' ? 'active' : ''} onClick={() => setPageTab('config')}>Config UI</button>
      <button className={pageTab === 'voice' ? 'active' : ''} onClick={() => setPageTab('voice')}>Голосовой ввод</button>
      <button className={pageTab === 'improve' ? 'active' : ''} onClick={() => setPageTab('improve')}>Улучшение промпта</button>
      {pageTab === 'api' && <div className="tab-status">
        <span className={`status-dot ${orStatus.ok ? 'ok' : data.openrouter.keyConfigured ? 'warn' : ''}`} aria-hidden="true" />
        <span className={`state ${orStatus.ok ? 'ok' : data.openrouter.keyConfigured ? 'warn' : 'bad'}`}>{orStatus.ok ? 'ключ работает' : data.openrouter.keyConfigured ? 'проверить ключ' : 'нет ключа'}</span>
        <span className="state ok">billing: {backendPricedCount} моделей</span>
        <button className={`state ${exchangeStateClass}`} disabled={exchangeBusy} onClick={refreshExchange}>{exchangeBusy ? 'обновляю курс…' : `${exchangeStateText}: ${effectiveRateText}`}</button>
      </div>}
    </div>

    {pageTab === 'voice' && <>
      <section className="assistant-summary">
        <div><span>Статус</span><strong>Проектируется</strong><small>Пользовательская кнопка пока не подключена к микрофону.</small></div>
        <div><span>Локальная цель</span><strong>Qwen3-ASR 1.7B</strong><small>RTX 4070 12 ГБ; до установки требуется русский benchmark.</small></div>
        <div><span>API-резерв</span><strong>Gemini Audio</strong><small>OpenRouter включается при timeout или перегрузке local worker.</small></div>
      </section>
      <article className="card">
        <div className="card-head"><div><h2 className="card-title">Голосовой ввод</h2><p className="card-note">Реестр кандидатов и будущая маршрутизация. Здесь пока нет ложного статуса «работает».</p></div></div>
        <div className="matrix-wrap"><table className="assistant-table"><thead><tr><th>Задача</th><th>Роль и модель</th><th>Исполнение</th><th>Сильные стороны</th><th>Ограничения</th><th>Статус</th></tr></thead>
          <tbody>{ASSISTANT_MODEL_PLAN.filter((item) => item.task === 'Транскрибация').map((item) => <tr key={`${item.role}-${item.model}`}><td>{item.task}</td><td><strong>{item.model}</strong><small>{item.role}</small></td><td><strong>{item.runtime}</strong><small>{item.hardware}</small></td><td>{item.strengths}</td><td>{item.limitations}</td><td><span className={`assistant-status${item.status === 'Рекомендуется' ? ' recommended' : ''}`}>{item.status}</span></td></tr>)}</tbody>
        </table></div>
      </article>
    </>}

    {pageTab === 'improve' && assistantData && <>
      <section className="assistant-summary">
        <div><span>Текущий маршрут</span><strong>{assistantData.config.improve.route === 'api' ? 'OpenRouter API' : assistantData.config.improve.route === 'local' ? 'Локальная Ollama' : 'Авто: local → API'}</strong><small>Изменение применяется ко всем вкладкам студии.</small></div>
        <div><span>Ollama</span><strong>{assistantData.ollama.ok ? 'В сети' : 'Не отвечает'}</strong><small>{assistantData.ollama.baseUrl}</small></div>
        <div><span>OpenRouter</span><strong>{assistantData.openrouterConfigured ? 'Ключ настроен' : 'Нет ключа'}</strong><small>Ключ управляется в существующей вкладке OpenRouter.</small></div>
      </section>
      <section className="assistant-config">
        <article className="card">
          <div className="card-head"><div><h2 className="card-title">Маршрут и инструкции</h2><p className="card-note">Настройки хранятся в базе и используются пользовательской кнопкой «Улучшить».</p></div></div>
          <div className="assistant-form">
            <div className="two-col">
              <div className="field"><label>Основной маршрут</label><select value={assistantData.config.improve.route} onChange={(e) => updateAssistantConfig({ ...assistantData.config, improve: { ...assistantData.config.improve, route: e.target.value as AssistantConfig['improve']['route'] } })}><option value="api">OpenRouter API</option><option value="local">Локальная Ollama</option><option value="auto">Авто: Ollama → OpenRouter</option></select></div>
              <div className="field"><label>Локальная или облачная модель Ollama</label><select value={assistantData.config.improve.localModel} onChange={(e) => updateAssistantConfig({ ...assistantData.config, improve: { ...assistantData.config.improve, localModel: e.target.value } })}>{assistantData.ollama.models.filter((m) => m.name).map((m) => <option key={m.name} value={m.name}>{m.name}{m.name?.endsWith(':cloud') ? ' · Ollama Cloud' : ''}</option>)}</select></div>
              <div className="field"><label>Модель OpenRouter</label><select value={assistantData.config.improve.apiModel} onChange={(e) => updateAssistantConfig({ ...assistantData.config, improve: { ...assistantData.config.improve, apiModel: e.target.value } })}>{!selectedAssistantApiModel && <option value={assistantData.config.improve.apiModel}>{assistantData.config.improve.apiModel}</option>}{assistantData.openrouterModels.map((m) => <option key={m.id} value={m.id}>{m.name} · вход ${m.inputPerMillionUsd}/M · выход ${m.outputPerMillionUsd}/M</option>)}</select>{selectedAssistantApiModel && <small>Цена: вход ${selectedAssistantApiModel.inputPerMillionUsd} / 1M токенов · выход ${selectedAssistantApiModel.outputPerMillionUsd} / 1M токенов</small>}{assistantData.openrouterModelsError && <small>Каталог временно недоступен: {assistantData.openrouterModelsError}</small>}</div>
              <div className="field"><label>Timeout local / API, секунд</label><div className="two-col"><input type="number" min="3" max="120" value={assistantData.config.improve.localTimeoutSeconds} onChange={(e) => updateAssistantConfig({ ...assistantData.config, improve: { ...assistantData.config.improve, localTimeoutSeconds: Number(e.target.value) } })} /><input type="number" min="3" max="30" value={assistantData.config.improve.apiTimeoutSeconds} onChange={(e) => updateAssistantConfig({ ...assistantData.config, improve: { ...assistantData.config.improve, apiTimeoutSeconds: Number(e.target.value) } })} /></div></div>
            </div>
            <div className="field"><label>Главный системный промпт</label><textarea value={assistantData.config.improve.systemPrompt} onChange={(e) => updateAssistantConfig({ ...assistantData.config, improve: { ...assistantData.config.improve, systemPrompt: e.target.value } })} /></div>
            {Object.entries(assistantData.config.improve.modePrompts).map(([mode, value]) => <div className="field" key={mode}><label>{ASSISTANT_MODE_LABELS[mode] || mode}</label><textarea className="mode-prompt" value={value} onChange={(e) => updateAssistantConfig({ ...assistantData.config, improve: { ...assistantData.config.improve, modePrompts: { ...assistantData.config.improve.modePrompts, [mode]: e.target.value } } })} /></div>)}
            <button className="primary" disabled={assistantBusy} onClick={() => void saveAssistantConfig()}>{assistantBusy ? 'Сохраняю…' : 'Сохранить настройки'}</button>
          </div>
        </article>
        <aside className="card">
          <div className="card-head"><div><h2 className="card-title">Проверка моделей</h2><p className="card-note">Тест не меняет пользовательские промпты.</p></div></div>
          <div className="assistant-test">
            <textarea value={assistantTestPrompt} onChange={(e) => setAssistantTestPrompt(e.target.value)} />
            <div className="actions"><button className="ghost" disabled={assistantBusy} onClick={() => void testPromptAssistant('local')}>Тест Ollama</button><button className="ghost" disabled={assistantBusy} onClick={() => void testPromptAssistant('api')}>Тест OpenRouter</button></div>
            {assistantTestResult && <div className="assistant-test-result"><strong>{assistantTestResult.detail || assistantTestResult.improvedPrompt}</strong>{assistantTestResult.model && <small>{assistantTestResult.provider} · {assistantTestResult.model} · {assistantTestResult.latencyMs} мс · ${Number(assistantTestResult.costUsd || 0).toFixed(6)}</small>}</div>}
            <div className="ollama-list">{assistantData.ollama.models.filter((m) => m.name).map((m) => <div className="ollama-row" key={m.name}><div><strong>{m.name}</strong><small>{m.name?.endsWith(':cloud') ? 'Ollama Cloud' : `${m.details?.parameter_size || '—'} · ${m.details?.quantization_level || '—'}`}</small></div><small>{m.name?.endsWith(':cloud') ? 'облако' : m.size ? `${(m.size / 1024 ** 3).toFixed(1)} ГБ` : '—'}</small></div>)}</div>
          </div>
        </aside>
      </section>
    </>}

    {pageTab === 'config' && <>
    <section className="server-command">
      <div className="server-title">
        <h2>Config UI</h2>
        <p>Управление локальным генератором, глобальной моделью и LoRA</p>
      </div>
      <span className={`state ${configStatus?.status === 'ready' ? 'ok' : 'warn'}`}>{configErr ? 'статус недоступен' : configStatus?.status === 'ready' ? 'сервер готов' : configStatus?.status || 'проверка'}</span>
      <div className="profile-switch" aria-label="Глобальная серверная модель">
        <button disabled={opsBusy} className={globalLocalProfile === 'flux_klein_9b' ? 'active' : ''} onClick={() => void setGlobalLocalProfile('flux_klein_9b')}>Klein 9B</button>
        <button disabled={opsBusy} className={globalLocalProfile === 'flux_klein_4b' ? 'active' : ''} onClick={() => void setGlobalLocalProfile('flux_klein_4b')}>Klein 4B</button>
      </div>
      <button className="primary server-restart" disabled={opsBusy} onClick={() => void configAction('reload')}>Перезапустить Config UI</button>
      <button className="danger server-stop" disabled={opsBusy || !(configStatus?.active_jobs || []).length} onClick={() => void configAction('interrupt')}>Остановить задачу{(configStatus?.active_jobs || []).length ? ` · ${configStatus?.active_jobs?.length}` : ''}</button>
    </section>

    {configErr && <p className="hint" style={{ margin: '0 0 12px', color: 'var(--red)' }}>Состояние сервера не загружено: {configErr}</p>}

    <section className="server-layout">
      <article className="card">
        <div className="card-head"><div><h2 className="card-title">Состояние сервера</h2><p className="card-note">Проверка ComfyUI, API, очереди и зависимостей.</p></div><button className="ghost" disabled={opsBusy} onClick={() => void loadConfigStatus()}>Обновить</button></div>
        <div className="server-overview">
          <div className="server-metric"><span>ComfyUI</span><strong style={{ color: statusColor(configStatus?.comfyui?.available) }}>{configErr ? '—' : configStatus?.comfyui?.available ? 'В сети' : 'Не отвечает'}</strong><small>{configStatus?.comfyui?.base_url || 'адрес не получен'}</small></div>
          <div className="server-metric"><span>Config API</span><strong style={{ color: statusColor(configStatus?.config_api?.ok) }}>{fmtState(configStatus?.config_api?.ok)}</strong><small>{configStatus?.config_api?.error || 'конфигурация workflow'}</small></div>
          <div className="server-metric"><span>Models API</span><strong style={{ color: statusColor(configStatus?.models_api?.ok) }}>{fmtState(configStatus?.models_api?.ok)}</strong><small>{configStatus?.models_api?.error || 'модели и LoRA'}</small></div>
          <div className="server-metric"><span>Активные задачи</span><strong>{configStatus?.active_jobs?.length ?? '—'}</strong><small>проверено {fmtTime(configStatus?.checked_at)}</small></div>
        </div>
        <div className="route-strip">{routes.filter((route) => route.provider === 'local').map((route) => <span className="route-chip" key={route.routeId}><b>{route.icon}</b>{route.displayName}<span>·</span><strong>{globalLocalProfile.endsWith('9b') ? '9B' : '4B'}</strong></span>)}</div>
        {(configStatus?.active_jobs || []).length > 0 && <div className="job-list">{(configStatus?.active_jobs || []).map((job) => <div className="job-row" key={job.id}><strong>{job.id}</strong><span>{job.status}</span><span>{job.progress ?? 0}%</span><small>{job.mode} · {job.message || '—'}</small></div>)}</div>}
      </article>

      <article className="card">
        <div className="card-head"><div><h2 className="card-title">Активный профиль</h2><p className="card-note">Меняется глобально для всех локальных генераций.</p></div></div>
        <div className="profile-summary">
          <h3>FLUX.2 Klein {globalLocalProfile.endsWith('9b') ? '9B' : '4B'}</h3>
          <p>{globalLocalProfile.endsWith('9b') ? 'Основной мощный профиль для качества, лица, сборки и управляемого редактирования.' : 'Облегчённый профиль для высокой скорости и снижения нагрузки на единственную видеокарту.'}</p>
          <div className="profile-facts">
            <div><span>Модель</span><strong>{String(data.comfyFiles.modelFile || '—')}</strong></div>
            <div><span>Text encoder</span><strong>{String(data.comfyFiles.textEncoder || '—')}</strong></div>
            <div><span>Sampler</span><strong>{String(data.comfyFiles.sampler || '—')}</strong></div>
            <div><span>Шаги</span><strong>{String(data.comfyFiles.steps || '—')}</strong></div>
          </div>
        </div>
      </article>
    </section>

    <article className="card">
      <div className="card-head">
        <div><h2 className="card-title">LoRA Config UI</h2><p className="card-note">Оба набора видны одновременно. Галочка определяет доступность функции в режиме Профи.</p></div>
        <div className="actions"><button className="ghost" onClick={() => { void loadLocalModelData(); void loadConfigStatus() }}>Пересканировать</button></div>
      </div>
      <div className="lora-columns">{(['9B', '4B'] as const).map((profileKey) => {
        const items = kleinLoras.filter((l) => l.compatible.some((item) => item.toLowerCase().includes(profileKey.toLowerCase())))
        const active = globalLocalProfile.toLowerCase().endsWith(profileKey.toLowerCase())
        return <section className="lora-column" key={profileKey}>
          <div className="lora-column-head"><h3>Klein {profileKey}</h3><span className={`state ${active ? 'ok' : ''}`}>{active ? 'активная модель' : 'резервный набор'}</span></div>
          {items.length ? items.map((l) => {
            const dependencyReady = l.status === 'active' || l.status === 'found'
            const enabled = dependencyReady && loraAccess[l.fileName] !== false && l.installed !== false
            return <div className="lora-row" key={l.fileName}>
              <input type="checkbox" checked={enabled} disabled={l.installed === false || !dependencyReady} onChange={(e) => setLoraEnabled(l.fileName, e.target.checked)} aria-label={`Доступность ${l.fileName}`} />
              <div><h3>{l.fileName}</h3><p>{l.purpose}</p></div>
              <span className={`state ${enabled ? 'ok' : 'warn'}`}>{l.installed === false ? 'не установлена' : l.status === 'model_missing' ? 'нужна Base-модель' : l.status === 'workflow_pending' ? 'нужно подключить' : !dependencyReady ? 'нет зависимости' : enabled ? 'доступна' : 'выключена'}</span>
              <div><p>{l.routes.length ? `Функции: ${l.routes.join(', ')}` : 'Функция ещё не назначена'}{l.requires.length ? ` · Нужен модуль: ${l.requires.join(', ')}` : ''}</p></div>
            </div>
          }) : <p className="lora-empty">Совместимые LoRA пока не найдены.</p>}
        </section>
      })}</div>
      {otherLoras.length > 0 && <div className="hint" style={{ margin: '0 12px 12px' }}>Не используются в Flux Klein: {otherLoras.map((l) => l.fileName).join(', ')}</div>}
    </article>

    <article className="card">
      <div className="card-head"><div><h2 className="card-title">Разрешения и настройки Config UI</h2><p className="card-note">Единая матрица для Klein 9B и 4B. Галочки определяют доступность разрешения каждому тарифу.</p></div><button className="primary" onClick={() => void saveConfigUiSettings()}>Сохранить параметры</button></div>
      <div className="resolution-matrix">
        <table>
          <thead><tr><th>Формат</th>{CONFIG_RESOLUTION_TIERS.map((tier) => <th key={tier}>{IMAGE_RESOLUTIONS.find((item) => item.tier === tier)?.tierLabel}</th>)}</tr></thead>
          <tbody>{CONFIG_RESOLUTION_FORMATS.map((format) => {
            const formatResolution = IMAGE_RESOLUTIONS.find((item) => item.format === format)
            return <tr key={format}>
              <td><div className="resolution-format"><strong>{formatResolution?.formatLabel} · {formatResolution?.aspect}</strong><span>{formatResolution?.format === 'square' ? 'Посты и карточки' : formatResolution?.format === 'portrait' ? 'Истории и клипы' : formatResolution?.format === 'wide' ? 'Обложки и баннеры' : 'Фото и портфолио'}</span></div></td>
              {CONFIG_RESOLUTION_TIERS.map((tier) => {
                const resolution = IMAGE_RESOLUTIONS.find((item) => item.format === format && item.tier === tier)
                if (!resolution) return <td key={tier}>—</td>
                return <td key={tier}><div className="resolution-cell">
                  <div className="resolution-value"><strong>{resolution.width}×{resolution.height}</strong><small>{resolution.megapixels.toFixed(2).replace('.', ',')} МП</small></div>
                  <div className="resolution-plans">{tariffKeys.map((plan) => <label className="resolution-plan" key={plan} title={tariffs[plan].title}>
                    <input type="checkbox" checked={tariffs[plan].allowed_resolutions.includes(resolution.id)} onChange={(e) => toggleConfigResolution(plan, resolution.id, e.target.checked)} aria-label={`${resolutionLabel(resolution)} — ${tariffs[plan].title}`} />
                    <span>{plan === 'business' ? 'Biz' : plan}</span>
                  </label>)}</div>
                </div></td>
              })}
            </tr>
          })}</tbody>
        </table>
      </div>
      <div className="config-profiles">{(['9B', '4B'] as const).map((profileKey) => {
        const active = globalLocalProfile.toLowerCase().endsWith(profileKey.toLowerCase())
        const profileId = profileKey === '9B' ? 'flux_klein_9b' : 'flux_klein_4b'
        const settings = serverProfiles[profileId] || { width: 1024, height: 1024, steps: 4, sampler: 'er_sde', seedMode: 'random', seed: 42 }
        return <section className={`config-profile ${active ? 'active' : ''}`} key={profileKey}>
          <div className="config-profile-head"><h3>FLUX.2 Klein {profileKey}</h3><span className={`state ${active ? 'ok' : ''}`}>{active ? 'используется' : 'не загружена'}</span></div>
          <div className="config-fields">
            <div className="config-field"><label>Разрешение по умолчанию</label><select value={`${settings.width}x${settings.height}`} onChange={(e) => { const [width, height] = e.target.value.split('x').map(Number); updateServerProfile(profileId, { width, height }) }}>{IMAGE_RESOLUTIONS.map((option) => <option key={option.id} value={`${option.width}x${option.height}`}>{resolutionLabel(option)}</option>)}</select></div>
            <div className="config-field"><label>Количество шагов</label><input type="number" min="1" max="80" value={settings.steps} onChange={(e) => updateServerProfile(profileId, { steps: Number(e.target.value) })} /></div>
            <div className="config-field"><label>Sampler</label><select value={settings.sampler} onChange={(e) => updateServerProfile(profileId, { sampler: e.target.value })}><option value="er_sde">ER-SDE</option><option value="euler">Euler</option><option value="dpmpp_2m">DPM++ 2M</option></select></div>
            <div className="config-field"><label>Seed</label><select value={settings.seedMode} onChange={(e) => updateServerProfile(profileId, { seedMode: e.target.value as 'random' | 'fixed' })}><option value="random">Случайный при каждой генерации</option><option value="fixed">Фиксированный</option></select></div>
            {settings.seedMode === 'fixed' && <div className="config-field"><label>Фиксированный seed</label><input type="number" min="0" value={settings.seed} onChange={(e) => updateServerProfile(profileId, { seed: Number(e.target.value) })} /></div>}
          </div>
        </section>
      })}</div>
      <div className="dependency-note">
        <div><strong>FluxKleinOneNode</strong><span>Основной модуль Config UI: загружает Klein, encoder и VAE и запускает генерацию.</span></div>
        <div><strong>DWPreprocessor</strong><span>Модуль распознавания позы. Нужен только функциям LoRA, которые управляют положением тела.</span></div>
      </div>
    </article>
    </>}

    {pageTab === 'api' && <>
      <div className="or-stats">
        <div className="or-stat"><span>Баланс OpenRouter</span><strong>{balanceText}</strong></div>
        <div className="or-stat"><span>Сгенерировано картинок</span><strong>{data.openrouter.usage?.pricedImages || 0}</strong></div>
        <div className="or-stat"><span>Потрачено всего</span><strong>{totalSpentPair}</strong></div>
        <div className="or-stat"><span>Списано токенов</span><strong>{spentTokensText}</strong></div>
        <div className="or-stat"><span>Средняя за картинку</span><strong>{avgImagePair}</strong></div>
        <div className="or-stat"><span>Справка 1MP</span><strong>{avgMpPair}</strong></div>
        <div className="or-stat"><span>Фаворит по генерациям</span><strong>{favoriteOverallName}</strong></div>
        <div className="or-stat">
          <span>Мин. маржа, %</span>
          <input
            type="number"
            min="0"
            max="95"
            value={marginDraft}
            onChange={(e) => setMarginDraft(e.target.value)}
            onBlur={() => void saveMinMargin()}
            onKeyDown={(e) => { if (e.key === 'Enter') { e.currentTarget.blur() } }}
          />
        </div>
        <div className="or-stat">
          <span>Цена токена, ₽</span>
          <input
            type="number"
            min="0.01"
            step="0.01"
            value={tokenRubDraft}
            onChange={(e) => setTokenRubDraft(e.target.value)}
            onBlur={() => void saveTokenRub()}
            onKeyDown={(e) => { if (e.key === 'Enter') { e.currentTarget.blur() } }}
          />
        </div>
      </div>

      <div className="toolbar">
        <input type="search" placeholder="Фильтр по всем карточкам: модель, provider, price, параметр" value={query} onChange={(e) => setQuery(e.target.value)} />
        <button className="ghost" onClick={() => setQuery('')}>Сбросить</button>
      </div>
      {!liveCapabilityCatalog.length ? <p className="hint" style={{ color: 'var(--yellow)' }}>Живой каталог возможностей пока не получен. Модели, цены и управление показаны из проверенного резервного каталога; перезапустите backend для автоматического обновления.</p> : null}
      {data.openrouter.capabilityError ? <p className="hint" style={{ color: 'var(--yellow)' }}>Каталог возможностей OpenRouter не загрузился: {data.openrouter.capabilityError}</p> : null}

      {API_MODE_SECTIONS.map((section) => {
        const sort = apiSorts[section.id] || { key: 'price' as const, dir: 'asc' as const }
        const sectionOpen = apiSectionsOpen[section.id] ?? false
        const enabledForSection = data.openrouter.config?.enabled?.[section.id] || []
        const defaultForSection = data.openrouter.config?.defaults?.[section.id] || ''
        const accessForSection = data.openrouter.config?.access?.[section.id] || {}
        const sectionStats = orUsageModes.get(section.id)
        const sectionCount = typeof sectionStats?.count === 'number' ? sectionStats.count : 0
        const sectionSpent = typeof sectionStats?.costUsd === 'number' ? moneyPair(sectionStats.costUsd, usdRubEffective) : '—'
        const sectionAvg = typeof sectionStats?.avgCostUsd === 'number' ? moneyPair(sectionStats.avgCostUsd, usdRubEffective) : '—'
        const sectionAvgMp = typeof sectionStats?.avgCostPerMpUsd === 'number' ? moneyPair(sectionStats.avgCostPerMpUsd, usdRubEffective) : '—'
        const sectionTokens = tokensText(sectionStats?.costUsd, usdRubEffective, tokenRub)
        const sectionFavorite = modelLabelById(sectionStats?.favoriteModel)
        const rows = capabilityModels
          .filter(section.filter)
          .filter((m) => {
            const hay = `${m.id} ${m.name} ${m.provider} ${m.input} ${m.output} ${m.params} ${m.pricing}`.toLowerCase()
            return !query || hay.includes(query.toLowerCase())
          })
        const sortedRows = sortedApiRows(rows, sort, orUsageModels, usdRubEffective, minMarginPercent, tokenRub, backendPricingMap)
        const billableIds = rows.filter((m) => backendPricingMap.has(m.id)).map((m) => m.id)
        const enabledBillableCount = billableIds.filter((id) => enabledForSection.includes(id)).length
        const allBillableEnabled = billableIds.length > 0 && enabledBillableCount === billableIds.length
        const enabledIds = billableIds.filter((id) => enabledForSection.includes(id))
        const allTierColumnChecked = (tier: OpenRouterTier) => enabledIds.length > 0 && enabledIds.every((id) => accessForSection[tier]?.includes(id))
        return <article className="card" key={section.id}>
          <button className={`api-section-head ${sectionOpen ? '' : 'collapsed'}`} onClick={() => setApiSectionsOpen((prev) => ({ ...prev, [section.id]: !sectionOpen }))}>
            <div className="section-cell">
              <h2 className="card-title">{section.title}</h2>
            </div>
            <div className="section-cell"><span>Сген.</span><strong>{sectionCount}</strong></div>
            <div className="section-cell"><span>Средняя картинка</span><strong>{sectionAvg}</strong></div>
            <div className="section-cell"><span>Справка 1MP</span><strong>{sectionAvgMp}</strong></div>
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
          <div className="matrix-wrap">
            <table className="api-table format-table">
              <thead><tr>
                <th className="api-enabled">
                  <input
                    type="checkbox"
                    checked={allBillableEnabled}
                    disabled={!billableIds.length}
                    aria-label={`Включить все модели ${section.title}`}
                    onChange={(e) => toggleOpenrouterSection(section.id, billableIds, e.target.checked)}
                  />
                </th>
                <th><button className={`sort-head ${sort.key === 'name' ? 'active' : ''}`} onClick={() => toggleApiSort(section.id, 'name')}>Модель {sortMark(sort, 'name')}</button></th>
                <th><button className={`sort-head ${sort.key === 'provider' ? 'active' : ''}`} onClick={() => toggleApiSort(section.id, 'provider')}>Производитель {sortMark(sort, 'provider')}</button></th>
                <th>
                  <div className="tier-checks tier-head">
                    {OPENROUTER_TIERS.map((tier) => <label key={tier.id} title={`Весь столбец ${tier.label}`}>
                      <input
                        type="checkbox"
                        checked={allTierColumnChecked(tier.id)}
                        disabled={!enabledIds.length}
                        aria-label={`Включить ${tier.label} для всех моделей ${section.title}`}
                        onChange={(e) => toggleOpenrouterTierColumn(section.id, tier.id, enabledIds, e.target.checked)}
                      />
                      <span>{tier.label}</span>
                    </label>)}
                  </div>
                </th>
                {OPENROUTER_FORMAT_COLUMNS.map((fmt) => <th key={fmt.id} className="format-head">
                  <button className={`sort-head ${sort.key === 'price' ? 'active' : ''}`} onClick={() => toggleApiSort(section.id, 'price')}>{fmt.label} {sortMark(sort, 'price')}</button>
                  <span>цена · токены · выгода</span>
                </th>)}
                <th>Сген.</th>
                <th>Потрачено</th>
              </tr></thead>
              <tbody>{sortedRows.map((m) => {
                const rowKey = `${section.id}-${m.id}`
                const enabled = enabledForSection.includes(m.id)
                const expanded = apiExpandedRows[rowKey] || false
                const backendPrice = backendPricingMap.get(m.id)
                const canBill = Boolean(backendPrice)
                const tierAccess = (tier: OpenRouterTier) => Boolean(accessForSection[tier]?.includes(m.id))
                const modelStats = orUsageModels.get(m.id)
                const avgActualUsd = typeof modelStats?.avgCostUsd === 'number' ? modelStats.avgCostUsd : null
                const generatedCount = modelStatText(modelStats?.count)
                const spentTotal = typeof modelStats?.costUsd === 'number' ? moneyPair(modelStats.costUsd, usdRubEffective) : '—'
                const primaryFormat = backendPrimaryFormat(backendPrice)
                const costRub = typeof primaryFormat?.costRub === 'number' ? primaryFormat.costRub : costRubForModel(m, avgActualUsd, usdRubEffective)
                const tokenCount = typeof primaryFormat?.tokens === 'number' ? primaryFormat.tokens : tokenPriceForModel(m, avgActualUsd, usdRubEffective, minMarginPercent, tokenRub)
                const revenue = revenueRub(tokenCount, tokenRub)
                const profit = profitRub(revenue, costRub)
                const margin = marginPercent(revenue, profit)
                return <Fragment key={rowKey}>
                  <tr className={`api-model-row ${expanded ? 'expanded' : ''}`} onClick={() => setApiExpandedRows((prev) => ({ ...prev, [rowKey]: !expanded }))}>
                    <td className="api-enabled">
                      <input
                        type="checkbox"
                        checked={enabled}
                        disabled={!canBill && !enabled}
                        aria-label={`Включить ${modelShortName(m)} для ${section.title}`}
                        onClick={(e) => e.stopPropagation()}
                        onChange={(e) => toggleOpenrouterModel(section.id, m.id, e.target.checked)}
                      />
                    </td>
                    <td><strong className="model-name">{modelShortName(m)}</strong>{defaultForSection === m.id ? <span className="mini" style={{ marginLeft: 8 }}>default</span> : null}{!canBill ? <span className="mini risk-high" style={{ marginLeft: 8 }}>нет backend цены</span> : null}</td>
                    <td><span className="provider openrouter">{modelBrand(m)}</span></td>
                    <td>
                      <div className="tier-checks">
                        {OPENROUTER_TIERS.map((tier) => <label key={tier.id} title={tier.id}>
                          <input
                            type="checkbox"
                            checked={tierAccess(tier.id)}
                            disabled={!enabled}
                            onClick={(e) => e.stopPropagation()}
                            onChange={(e) => toggleOpenrouterTier(section.id, tier.id, m.id, e.target.checked)}
                          />
                          <span>{tier.label}</span>
                        </label>)}
                      </div>
                    </td>
                    {OPENROUTER_FORMAT_COLUMNS.map((fmt) => <td key={fmt.id} className="format-cell">
                      {formatEconomicsCell(backendPrice?.formats?.find((item) => item.id === fmt.id), minMarginPercent)}
                    </td>)}
                    <td>{generatedCount}</td>
                    <td><span className="money">{spentTotal}</span></td>
                  </tr>
                  {expanded && <tr>
                    <td className="detail-cell" colSpan={10}>
                      <div className="detail-box">
                        <span><b>Полное имя:</b> {m.name}</span>
                        <span><b>OpenRouter id:</b> {m.id}</span>
                        <span><b>Backend billing:</b> {backendPrice ? `${backendPrice.pricing_type} · min ${backendPrice.min_tokens} ток. · ${backendPrice.source}` : 'не подключено, модель нельзя включать в реальную генерацию'}</span>
                        <span><b>Как посчитано:</b> {priceConfidence(m)}</span>
                        <span><b>Цена из OpenRouter:</b> {m.pricing}</span>
                        <span><b>Токены проекта:</b> {tokenCount ?? 'нужно измерить'} при {tokenRub} ₽/токен и марже от {minMarginPercent}%</span>
                        <span><b>Экономика:</b> себестоимость {rubText(costRub)} · выручка {rubText(revenue)} · выгода {rubText(profit)} · маржа {percentText(margin)}</span>
                        <span><b>Форматы:</b> {(backendPrice?.formats || []).map((fmt) => `${fmt.short}: ${formatMoneyRub(fmt.costRub)} / ${formatMoneyUsd(fmt.costUsd)}, ${fmt.tokens ?? '—'} ток., ${fmt.requestSize || 'auto'}`).join(' · ') || 'нет данных'}</span>
                        <span><b>Факт по проекту:</b> {generatedCount} шт · {spentTotal}</span>
                        <span><b>Вход/выход API:</b> {m.input} {'->'} {m.output}</span>
                        <span><b>Референсы:</b> максимум {m.maxInputReferences ?? 0} изображений</span>
                        <span><b>Подходит для:</b> {(m.modes || []).map((mode) => API_MODE_SECTIONS.find((item) => item.id === mode)?.title || mode).join(' · ') || 'только неподдерживаемые проектом операции'}</span>
                        <span><b>Streaming:</b> {m.supportsStreaming ? 'да' : 'нет'}</span>
                        <span><b>Параметры:</b> {m.params || 'нет в endpoint metadata'}</span>
                        {m.description ? <span><b>Описание OpenRouter:</b> {m.description}</span> : null}
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
