// Админ → Модели v2. Provider-aware страница управления моделями/маршрутами/тарифами,
// OpenRouter и серверной моделью. Структура по референсу admin-models-v2.html.
// Реальные данные приходят из GET /api/admin/models-page (см. backend). Тарифная матрица,
// маршруты и user-choice сохраняются через /api/admin/settings/{key}.
import { Fragment, lazy, Suspense, useCallback, useEffect, useMemo, useState } from 'react'
import { AdminModelsNavigation } from './adminModelsNavigation'
import { OpenRouterAudioPage, OpenRouterThreeDPage } from './adminOpenRouterAuxPages'
import {
  ADMIN_OPENROUTER_PAGES,
  adminModelsPageFromPath,
  adminModelsPath,
  adminOpenRouterPageFromPath,
  adminOpenRouterPath,
  type AdminModelsPage,
  type AdminOpenRouterPage,
} from './adminModelsRoutes'
import { ensureSessionRefreshedV2 } from './authV2'
import { publishedImageModelIds, setImageModelOperation, setImageModelPublished, setImageModelSection, setImageModelTier, setImageModelTierColumn } from './adminImageModelPublication'
import { normalizeTariffs, tariffKeys, type TariffConfig, type TariffKey } from './profileSupport'
import { IMAGE_RESOLUTIONS, normalizeResolutionIds, resolutionLabel, type ResolutionFormat, type ResolutionTier } from './resolutionPolicy'
import { setVideoPublication } from './adminVideoPublication'
import { AdminTextModelCatalog, type AdminTextModel, type TextModelEconomics, type TextModelUsage, type TextTariff } from './adminTextModelCatalog'

const AdminEnergy = lazy(() => import('./adminEnergy'))
const AdminVoice = lazy(() => import('./adminVoice'))

const API = (import.meta as ImportMeta & { env?: { VITE_API_BASE_URL?: string } }).env?.VITE_API_BASE_URL || '/api'
async function amvFetch(path: string, init: RequestInit = {}) {
  const headers = new Headers(init.headers)
  const request = () => fetch(`${API}${path}`, { ...init, headers, credentials: 'include' })
  let response = await request()
  if (response.status === 401 && await ensureSessionRefreshedV2()) response = await request()
  return response
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
const CONFIG_RESOLUTION_TIERS: ResolutionTier[] = ['sd', 'hd', 'full_hd', 'four_k']
const CONFIG_UI_RUNTIME_RESOLUTION_IDS = new Set(IMAGE_RESOLUTIONS.map((item) => item.id))
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
  created: number
  inputModalities: string[]
  outputModalities: string[]
  parameters: string[]
  maxInputReferences: number
  supportsStreaming: boolean
  modes: string[]
  features: { seed?: boolean; quality?: boolean; aspectRatio?: boolean; resolution?: boolean; transparentBackground?: boolean; multipleOutputs?: boolean }
}
type OpenRouterVideoModel = {
  id: string
  canonicalSlug: string
  name: string
  description: string
  created: number
  supportedResolutions: string[]
  supportedAspectRatios: string[]
  supportedSizes: string[]
  supportedDurations: number[]
  supportedFrameImages: string[]
  generateAudio: boolean | null
  seed: boolean | null
  pricingSkus: Record<string, number>
  allowedParameters: string[]
  modes: string[]
  referenceEvidence: 'description' | null
}
type OpenRouterVideoMode = 'text_to_video' | 'image_to_video' | 'first_last_frame' | 'reference_to_video'
type ShadowEconomics = { quoted?: number; priced?: number; missingActual?: number; underquoted?: number; belowMinimumMargin?: number; averageActualMarginPercent?: number | null; alert?: boolean }
type OpenRouterVideoConfig = { published?: string[]; enabled?: Partial<Record<OpenRouterVideoMode, string[]>>; access?: Partial<Record<OpenRouterVideoMode, Partial<Record<OpenRouterTier, string[]>>>> }
type OpenRouterVideoUsage = {
  count?: number
  priced?: number
  costUsd?: number
  avgCostUsd?: number | null
  models?: Array<Record<string, unknown>>
  modes?: Array<Record<string, unknown>>
  shadowEconomics?: ShadowEconomics
}
type OpenRouterAvailability = { state?: 'unknown' | 'available' | 'billing_blocked' | 'authorization_blocked' | 'service_error'; ready?: boolean | null; lastStatusCode?: number | null; lastFailureAt?: string | null; lastSuccessAt?: string | null }
type VideoPriceProfile = {
  id: string
  label: string
  resolution: string
  aspectRatio?: string
  size?: string
  sourceKey: string
  unit: 'second' | 'video_token'
  rateUsd: number
  inputFeeUsd: number
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
  runtime?: { imageEnabled?: boolean; videoEnabled?: boolean; videoProfile?: string }
  video?: {
    ready?: boolean; enabled?: boolean; base_url?: string; gpu?: string; error?: string
    active_jobs?: Array<{ id?: string; status?: string; progress?: number; created_at?: string }>
    profiles?: Array<{ id: string; label: string }>; aspect_ratios?: string[]; resolution?: string
  }
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
    status?: { ok?: boolean; ready?: boolean | null; configured?: boolean; source?: string; status_code?: number; error?: unknown; data?: Record<string, unknown>; credits?: Record<string, unknown>; availability?: OpenRouterAvailability }
    usage?: {
      pricedImages?: number
      totalCostUsd?: number
      avgCostUsd?: number | null
      avgCostPerMpUsd?: number | null
      lastCostUsd?: number | null
      shadowEconomics?: ShadowEconomics
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
    catalogState?: {
      refreshing?: boolean
      refreshStarted?: boolean
      lastAttemptAt?: string | null
      lastSuccessAt?: string | null
      lastError?: string | null
      source?: string
      modelCount?: number
      videoModelCount?: number
      cacheAgeSeconds?: number | null
    }
    videoCatalog?: OpenRouterVideoModel[]
    videoConfig?: OpenRouterVideoConfig
    videoUsage?: OpenRouterVideoUsage
    videoCatalogError?: string | null
    videoCatalogSource?: string
  }
  comfyFiles: Record<string, unknown>
  profiles: ProfileOption[]
}
type OpenRouterTier = 'mini' | 'plus' | 'pro' | 'business'
type OpenRouterQuality = 'fast' | 'standard' | 'max'
type OpenRouterAccess = Record<string, Partial<Record<OpenRouterTier, string[]>>>
type OpenRouterQualityDefaults = Record<string, Partial<Record<OpenRouterQuality, string>>>
type OpenRouterConfig = {
  published?: string[]
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
const OPENROUTER_FORMAT_COLUMNS = [
  { id: 'square', label: '1:1' },
  { id: 'portrait', label: '9:16' },
  { id: 'wide', label: '16:9' },
  { id: 'soft_wide', label: '3:2' },
] as const
type ApiImageModel = {
  id: string; name: string; provider: string; input: string; output: string; params: string; pricing: string
  mpUsd?: number; imageUsd?: number; token?: boolean; tiered?: boolean
  modes?: string[]; maxInputReferences?: number; description?: string; supportsStreaming?: boolean; created?: number
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
  { id: 'bytedance-seed/seedream-5-0-lite', name: 'ByteDance Seed: Seedream 5.0 Lite', provider: 'Seed', input: 'text+image', output: 'image', params: 'resolution, aspect_ratio, n, input_references, seed', pricing: 'output_image: $0.035/image', imageUsd: 0.035 },
  { id: 'bytedance-seed/seedream-5-0-pro', name: 'ByteDance Seed: Seedream 5.0 Pro', provider: 'Seed', input: 'text+image', output: 'image', params: 'resolution, aspect_ratio, n, input_references, seed', pricing: 'output_image: $0.045/$0.09 image + input_image: $0.003/image', tiered: true },
  { id: 'x-ai/grok-imagine-image-2.0', name: 'xAI: Grok Imagine Image 2.0', provider: 'xAI', input: 'text+image', output: 'image', params: 'resolution, aspect_ratio, quality, n, input_references', pricing: 'input_image: $0.01/image + output_image: $0.04/$0.06/$0.08 image', tiered: true },
  { id: 'qwen/qwen-image-3-pro', name: 'Qwen: Qwen Image 3 Pro', provider: 'Alibaba Cloud', input: 'text+image', output: 'image', params: 'resolution, aspect_ratio, n, input_references, seed', pricing: 'input_image: $0.003/image + output_image: $0.04/$0.075 image', tiered: true },
  { id: 'qwen/qwen-image-3', name: 'Qwen: Qwen Image 3', provider: 'Alibaba Cloud', input: 'text+image', output: 'image', params: 'resolution, aspect_ratio, n, input_references, seed', pricing: 'input_image: $0.003/image + output_image: $0.03/image', imageUsd: 0.03 },
  { id: 'microsoft/mai-image-2.5-pro', name: 'Microsoft: MAI-Image-2.5 Pro', provider: 'Azure', input: 'text+image', output: 'image', params: 'aspect_ratio, n, input_references', pricing: 'input_text: $0.000005/token + input_image: $0.000008/token + output_image: $0.000108/token', token: true },
  { id: 'krea/krea-2-large', name: 'Krea: Krea 2 Large', provider: 'Krea', input: 'text+image', output: 'image', params: 'resolution, aspect_ratio, input_references, seed', pricing: 'output_image: $0.0000143712574850299/token', token: true },
  { id: 'krea/krea-2-medium', name: 'Krea: Krea 2 Medium', provider: 'Krea', input: 'text+image', output: 'image', params: 'resolution, aspect_ratio, input_references, seed', pricing: 'output_image: $0.00000718562874251497/token', token: true },
  { id: 'krea/krea-2-medium-turbo', name: 'Krea: Krea 2 Medium Turbo', provider: 'Krea', input: 'text+image', output: 'image', params: 'resolution, aspect_ratio, input_references, seed', pricing: 'output_image: $0.00000359281437125749/token', token: true },
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
  { id: 'black-forest-labs/flux.2-flex', name: 'Black Forest Labs: FLUX.2 Flex', provider: 'Black Forest Labs', input: 'text+image', output: 'image', params: 'output_format, n, input_references, seed', pricing: 'input_image: $0.06/megapixel + output_image: $0.06/megapixel', mpUsd: 0.12 },
  { id: 'black-forest-labs/flux.2-pro', name: 'Black Forest Labs: FLUX.2 Pro', provider: 'Black Forest Labs', input: 'text+image', output: 'image', params: 'output_format, n, input_references, seed', pricing: 'output_image: $0.03/megapixel', mpUsd: 0.03 },
  { id: 'google/gemini-3-pro-image-preview', name: 'Google: Nano Banana Pro (Gemini 3 Pro Image Preview)', provider: 'Google Vertex', input: 'image+text', output: 'image+text', params: 'resolution, aspect_ratio, n, input_references', pricing: 'оценка: output_image ~$0.00012/token', token: true },
  { id: 'openai/gpt-5-image-mini', name: 'OpenAI: GPT-5 Image Mini', provider: 'OpenAI', input: 'file+image+text', output: 'image+text', params: 'quality, background, n, input_references, output_compression', pricing: 'output_image: $0.000008/token', token: true },
  { id: 'openai/gpt-5-image', name: 'OpenAI: GPT-5 Image', provider: 'OpenAI', input: 'image+text+file', output: 'image+text', params: 'quality, background, n, input_references, output_compression', pricing: 'output_image: $0.00004/token', token: true },
  { id: 'google/gemini-2.5-flash-image', name: 'Google: Nano Banana (Gemini 2.5 Flash Image)', provider: 'Google AI Studio', input: 'image+text', output: 'image+text', params: 'aspect_ratio, n, input_references', pricing: 'оценка: output_image ~$0.00006/token', token: true },
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
const VIDEO_MODE_SECTIONS = [
  { id: 'text_to_video', title: 'Видео по тексту', note: 'Текстовый сценарий без обязательного стартового кадра.' },
  { id: 'image_to_video', title: 'Видео по изображению', note: 'OpenRouter явно разрешает передать первый кадр.' },
  { id: 'first_last_frame', title: 'Первый и последний кадр', note: 'Модель явно принимает оба граничных кадра.' },
  { id: 'reference_to_video', title: 'Видео по референсам', note: 'Предварительный список по описанию модели. Перед запуском нужен отдельный контрактный тест.' },
] as const

function videoPriceLabel(pricing: Record<string, number>) {
  const labels: Record<string, string> = {
    duration_seconds: 'секунда видео',
    duration_seconds_720p: '720p/сек',
    duration_seconds_1080p: '1080p/сек',
    duration_seconds_1024p: '1024p/сек',
    duration_seconds_with_audio: 'с аудио/сек',
    duration_seconds_with_audio_720p: 'с аудио 720p/сек',
    duration_seconds_with_audio_4k: 'с аудио 4K/сек',
    duration_seconds_without_audio: 'без аудио/сек',
    duration_seconds_without_audio_720p: 'без аудио 720p/сек',
    duration_seconds_without_audio_4k: 'без аудио 4K/сек',
    video_tokens: 'видеотокен',
    video_tokens_without_audio: 'видеотокен без аудио',
    text_to_video_duration_seconds_480p: 'текст→видео 480p/сек',
    text_to_video_duration_seconds_720p: 'текст→видео 720p/сек',
    text_to_video_duration_seconds_1080p: 'текст→видео 1080p/сек',
    image_to_video_duration_seconds_720p: 'кадр→видео 720p/сек',
    image_to_video_duration_seconds_1080p: 'кадр→видео 1080p/сек',
    cents_per_second_output: 'выходное видео/сек',
    minimum_cents_per_generation: 'минимум за генерацию',
  }
  const entries = Object.entries(pricing)
  if (!entries.length) return 'цена не опубликована'
  return entries.map(([key, value]) => {
    const cents = key.startsWith('cents_per_')
    const normalized = cents ? value / 100 : value
    const centsLabel = key === 'cents_per_image_input' ? 'входное изображение' : key === 'cents_per_video_output_second_480p' ? 'выход 480p/сек' : key === 'cents_per_video_output_second_720p' ? 'выход 720p/сек' : key
    return `${labels[key] || centsLabel}: $${normalized.toFixed(normalized < 0.01 ? 6 : 4)}`
  }).join(' · ')
}

const videoResolutionFromKey = (key: string) => {
  const match = key.toLowerCase().match(/(?:_|-)(480p|720p|1024p|1080p|1k|2k|4k)$/)
  return match ? match[1].replace('k', 'K') : ''
}
const videoResolutionForSize = (size: string) => {
  const [width, height] = size.split('x').map(Number)
  const edge = Math.min(width || 0, height || 0)
  if (edge >= 2100) return '4K'
  if (edge >= 1080) return '1080p'
  if (edge >= 1024) return '1024p'
  if (edge >= 720) return '720p'
  if (edge >= 480) return '480p'
  return edge ? `${edge}p` : ''
}
const videoAspectForSize = (size: string, supported: string[]) => {
  const [width, height] = size.split('x').map(Number)
  if (!width || !height) return ''
  let best = ''
  let delta = Number.POSITIVE_INFINITY
  for (const value of supported) {
    const [a, b] = value.split(':').map(Number)
    if (!a || !b) continue
    const next = Math.abs(width / height - a / b)
    if (next < delta) { delta = next; best = value }
  }
  return best
}
const videoInputFeeUsd = (model: OpenRouterVideoModel, mode: OpenRouterVideoMode) => {
  const cents = model.pricingSkus.cents_per_image_input
  if (typeof cents !== 'number' || mode === 'text_to_video') return 0
  return (cents / 100) * (mode === 'first_last_frame' ? 2 : 1)
}
const videoPricingProfiles = (model: OpenRouterVideoModel, mode: OpenRouterVideoMode): VideoPriceProfile[] => {
  const supported = new Set(model.supportedResolutions.map((value) => value.toLowerCase()))
  const inputFeeUsd = videoInputFeeUsd(model, mode)
  const entries = Object.entries(model.pricingSkus)
  const modePrefix = mode === 'text_to_video' ? 'text_to_video_duration_seconds' : 'image_to_video_duration_seconds'
  const modeEntries = entries.filter(([key]) => key.startsWith(modePrefix))
  const genericEntries = entries.filter(([key]) => key === 'duration_seconds' || key.startsWith('duration_seconds_') || key.startsWith('cents_per_video_output_second') || key.startsWith('cents_per_second_output'))
  const audioEntries = entries.filter(([key]) => key.startsWith('duration_seconds_with_audio') || key.startsWith('duration_seconds_without_audio'))
  const selected = [...(modeEntries.length ? modeEntries : genericEntries), ...audioEntries]
  const profiles: VideoPriceProfile[] = []
  for (const [key, rawValue] of selected) {
    const cents = key.startsWith('cents_per_')
    const rateUsd = cents ? rawValue / 100 : rawValue
    const keyResolution = videoResolutionFromKey(key)
    if (keyResolution && supported.size && !supported.has(keyResolution.toLowerCase())) continue
    const family = key.replace(/_(?:480p|720p|1024p|1080p|1k|2k|4k)$/i, '')
    const siblingResolutions = selected.filter(([other]) => other !== key && other.replace(/_(?:480p|720p|1024p|1080p|1k|2k|4k)$/i, '') === family).map(([other]) => videoResolutionFromKey(other)).filter(Boolean)
    const resolutions = keyResolution ? [keyResolution] : model.supportedResolutions.filter((value) => !siblingResolutions.some((item) => item.toLowerCase() === value.toLowerCase()))
    const targetResolutions = resolutions.length ? resolutions : ['по умолчанию']
    for (const resolution of targetResolutions) {
      const audio = key.includes('without_audio') ? 'без аудио' : key.includes('with_audio') ? 'с аудио' : ''
      const flow = key.startsWith('text_to_video_') ? 'по тексту' : key.startsWith('image_to_video_') ? 'по кадру' : ''
      const label = [resolution, flow, audio].filter(Boolean).join(' · ')
      profiles.push({ id: `${key}:${resolution}`, label, resolution, sourceKey: key, unit: 'second', rateUsd, inputFeeUsd })
    }
  }

  const hasVideoTokenRate = entries.some(([key, value]) => typeof value === 'number' && /^video_tokens(?:_|$)/.test(key) && !key.includes('with_video_input'))
  if (hasVideoTokenRate) {
    for (const size of model.supportedSizes) {
      const resolution = videoResolutionForSize(size)
      if (resolution && supported.size && !supported.has(resolution.toLowerCase())) continue
      const aspectRatio = videoAspectForSize(size, model.supportedAspectRatios)
      const resolutionKey = resolution.toLowerCase()
      const tokenRate = model.pricingSkus[`video_tokens_${resolutionKey}`] ?? model.pricingSkus.video_tokens
      const tokenRateNoAudio = model.pricingSkus[`video_tokens_without_audio_${resolutionKey}`] ?? model.pricingSkus.video_tokens_without_audio
      if (typeof tokenRate !== 'number' && typeof tokenRateNoAudio !== 'number') continue
      const defaultRate = typeof tokenRate === 'number' ? tokenRate : Number(tokenRateNoAudio)
      const variants = typeof tokenRateNoAudio === 'number' && tokenRateNoAudio !== defaultRate
        ? [['с аудио', defaultRate] as const, ['без аудио', tokenRateNoAudio] as const]
        : [[model.generateAudio ? 'с аудио / без аудио' : '', defaultRate] as const]
      for (const [audio, rateUsd] of variants) {
        profiles.push({
          id: `video_tokens:${size}:${audio}`,
          label: [resolution, aspectRatio, size, audio].filter(Boolean).join(' · '),
          resolution,
          aspectRatio,
          size,
          sourceKey: audio === 'без аудио'
            ? (typeof model.pricingSkus[`video_tokens_without_audio_${resolutionKey}`] === 'number' ? `video_tokens_without_audio_${resolutionKey}` : 'video_tokens_without_audio')
            : (typeof model.pricingSkus[`video_tokens_${resolutionKey}`] === 'number' ? `video_tokens_${resolutionKey}` : 'video_tokens'),
          unit: 'video_token',
          rateUsd,
          inputFeeUsd,
        })
      }
    }
  }
  const seen = new Set<string>()
  return profiles.filter((profile) => {
    const key = `${profile.label}:${profile.rateUsd}:${profile.inputFeeUsd}`
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}
const videoEconomics = (profile: VideoPriceProfile, seconds: number, rate: number | null, minMarginPercent: number, tokenRub: number) => {
  let billedUnits = seconds
  if (profile.unit === 'video_token') {
    const [width, height] = (profile.size || '').split('x').map(Number)
    if (!width || !height) return null
    billedUnits = (width * height * seconds * 24) / 1024
  }
  const costUsd = profile.rateUsd * billedUnits + profile.inputFeeUsd
  if (rate === null) return { costUsd, costRub: null, tokens: null, revenueRub: null, profitRub: null, marginPercent: null }
  const costRub = costUsd * rate
  const marginFactor = Math.max(0.05, 1 - clampMargin(minMarginPercent) / 100)
  const tokens = Math.max(1, Math.ceil(costRub / (clampTokenRub(tokenRub) * marginFactor)))
  const revenue = tokens * clampTokenRub(tokenRub)
  const profit = revenue - costRub
  return { costUsd, costRub, tokens, revenueRub: revenue, profitRub: profit, marginPercent: revenue ? (profit / revenue) * 100 : null }
}

const videoResolutionRank = (value: string) => {
  const normalized = value.toLowerCase()
  if (normalized === '1080p') return 4
  if (normalized === '720p') return 3
  if (normalized === '4k' || normalized === '2160p') return 2
  if (normalized === '480p') return 1
  return 0
}
const videoRepresentativeScenario = (model: OpenRouterVideoModel, mode: OpenRouterVideoMode) => {
  const durations = [...model.supportedDurations].sort((a, b) => Math.abs(a - 5) - Math.abs(b - 5) || a - b)
  const seconds = durations[0] || null
  const profiles = videoPricingProfiles(model, mode)
  const resolutions = [...new Set(profiles.map((profile) => profile.resolution).filter(Boolean))]
  const resolution = resolutions.includes('1080p') ? '1080p'
    : resolutions.includes('720p') ? '720p'
      : [...resolutions].sort((a, b) => videoResolutionRank(b) - videoResolutionRank(a))[0]
  const candidates = resolution ? profiles.filter((profile) => profile.resolution === resolution) : profiles
  const profile = candidates.find((item) => model.generateAudio === true && !item.sourceKey.includes('without_audio'))
    || candidates.find((item) => !item.sourceKey.includes('without_audio'))
    || candidates[0]
    || profiles[0]
    || null
  return { seconds, resolution: profile?.resolution || resolution || '—', profile }
}

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
type AssistantConfig = {
  voice: { localModel: string; qwenModel: string; qwenBaseUrl: string; apiModel: string; route: string; queueTimeoutSeconds: number; requestTimeoutSeconds: number; minRecordingSeconds: number; transcriptionPublished: boolean; speechPublished: boolean }
  improve: { route: 'local' | 'api' | 'auto'; localModel: string; apiModel: string; localTimeoutSeconds: number; apiTimeoutSeconds: number; systemPrompt: string; modePrompts: Record<string, string> }
  chat: { enabled: boolean; localEnabled: boolean; localModel: string; localLabel: string; localTokenCost: number; defaultModel: string; publishedApiModels: string[]; enabledApiModels: string[]; apiTokenCosts: Record<string, number>; apiTierAccess: Partial<Record<Exclude<TariffKey, 'free'>, string[]>>; contextChars: number; localNumCtx: number; localTimeoutSeconds: number; apiTimeoutSeconds: number; usageBillingEnabled: boolean }
}
type AssistantAdminData = {
  ok?: boolean
  config: AssistantConfig
  ollama: { ok: boolean; baseUrl: string; error?: string; models: Array<{ name?: string; model?: string; size?: number; details?: { parameter_size?: string; quantization_level?: string } }> }
  ollamaResidency: { ok: boolean; models: Array<{ name?: string; model?: string; size_vram?: number; expires_at?: string }> }
  openrouterConfigured: boolean
  openrouterModels: Array<AdminTextModel & { economics?: TextModelEconomics }>
  openrouterModelsError?: string | null
  openrouterAudioModels: Array<{ id: string; name: string; inputPerMillionUsd: number; outputPerMillionUsd: number; contextLength: number }>
  openrouterAudioModelsError?: string | null
  usage: { periodDays: number; totals: { successful: number; failed: number; fallbacks: number; cost_usd: number; cost_rub: number; energy_wh: number; energy_cost_rub: number }; recent: Array<{ createdAt: string; ok: boolean; route?: string; provider?: string; model?: string; mode?: string; latencyMs?: number; fallbackUsed?: boolean; costUsd?: number; costRub?: number; energyWh?: number; energyCostRub?: number }> }
  chatUsage?: { answers?: number; priced?: number; missingActual?: number; costUsd?: number; averageCostUsd?: number | null; settledTokens?: number; revenueRub?: number; profitRub?: number; marginPercent?: number | null; perModel?: Record<string, TextModelUsage> }
}
type AssistantTestResult = { ok?: boolean; provider?: string; model?: string; improvedPrompt?: string; latencyMs?: number; costUsd?: number; costRub?: number; energyWh?: number; detail?: string }

const ASSISTANT_MODE_LABELS: Record<string, string> = {
  text: 'По тексту', i2i: 'По фото', edit: 'Сборка', sketch: 'Эскиз', mask: 'Маска', outpaint: 'Расширение', remove_bg: 'Удалить фон',
  text_to_video: 'Видео по тексту', image_to_video: 'Видео по изображению', first_last_frame: 'Видео: начало и конец', reference_to_video: 'Видео по референсам',
}

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
const modelReleaseLabel = (created?: number) => typeof created === 'number' && created > 0
  ? new Date(created * 1000).toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric', timeZone: 'UTC' })
  : 'не указана поставщиком'
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
.amv2 .page-tabs{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:6px;margin-bottom:10px;padding:6px;border:1px solid var(--line);border-radius:10px;background:rgba(9,12,9,.72)}
.amv2 .page-tabs>button[role="tab"]{min-height:38px;border:1px solid transparent;border-radius:7px;padding:0 12px;background:transparent;color:var(--muted);font-weight:650;white-space:nowrap}
.amv2 .page-tabs button.active{background:var(--lime);border-color:var(--lime);color:#080a07}
.amv2 .openrouter-page-nav{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));margin:0 0 12px;border-top:1px solid var(--line);border-bottom:1px solid var(--line)}
.amv2 .openrouter-page-nav button{min-height:42px;border:0;border-left:1px solid var(--line);border-radius:0;background:transparent;color:var(--muted);font-weight:750}
.amv2 .openrouter-page-nav button:first-child{border-left:0}.amv2 .openrouter-page-nav button.active{background:rgba(234,255,16,.08);box-shadow:inset 0 -2px var(--lime);color:#fff}
.amv2 .openrouter-page-title{display:flex;align-items:flex-start;justify-content:space-between;gap:14px;margin:0 0 12px;padding:0 0 10px;border-bottom:1px solid var(--line)}
.amv2 .openrouter-page-title h2{margin:0;color:#fff;font-size:18px}.amv2 .openrouter-page-title p{margin:4px 0 0;color:var(--muted);font-size:12px}
.amv2 .tab-status{grid-column:1/-1;display:flex;align-items:center;justify-content:flex-end;gap:8px;padding:4px 4px 0;border-top:1px solid var(--line);white-space:nowrap}
.amv2 .models-page-head{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;margin-bottom:12px;padding:11px 13px;border-left:3px solid var(--lime);background:linear-gradient(90deg,rgba(234,255,16,.07),transparent 55%)}
.amv2 .models-page-head h1{margin:0;font-size:18px;line-height:1.2}.amv2 .models-page-head p{margin:4px 0 0;color:var(--muted);font-size:12px;line-height:1.4}
.amv2 .models-page-head-status{margin-left:auto}.amv2 .models-page-head-status .tab-status{grid-column:auto;width:auto;padding:0;border:0;justify-content:flex-end}
.amv2 .models-page-embedded-status{display:flex;justify-content:flex-end;margin-bottom:8px}.amv2 .models-page-embedded-status .tab-status{grid-column:auto;width:auto;padding:6px 8px;border:1px solid var(--line);border-radius:7px;justify-content:flex-end}
.amv2 .models-page-loading{min-height:220px;display:grid;place-content:center;justify-items:center;gap:10px;padding:24px;border:1px solid var(--line);border-radius:var(--radius);background:var(--panel);text-align:center}
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
.amv2 .api-table.format-table{min-width:1760px}
.amv2 .api-table td,.amv2 .api-table th{vertical-align:middle}
.amv2 .api-table th{padding:6px 8px}
.amv2 .api-table td{padding:2px 8px;height:26px;line-height:1.15}
.amv2 .api-table tr.api-model-row{cursor:pointer}
.amv2 .api-table tr.api-model-row:hover td{background:rgba(234,255,16,.035)}
.amv2 .api-table tr.api-model-row.expanded td{background:rgba(234,255,16,.05)}
.amv2 .api-table tr.api-model-row.unpublished td{background:rgba(255,255,255,.012);color:var(--dim)}
.amv2 .api-table tr.api-model-row.unpublished:hover td{background:rgba(255,255,255,.025)}
.amv2 .video-catalog-head{width:100%;display:flex;align-items:center;justify-content:space-between;gap:16px;padding:14px;border:0;background:transparent;color:var(--text);text-align:left;cursor:pointer}
.amv2 .video-catalog-head:hover{background:rgba(234,255,16,.035)}
.amv2 .video-catalog-title{display:flex;align-items:center;gap:10px;min-width:0}.amv2 .video-catalog-title>span{color:var(--lime);flex:none}
.amv2 .video-catalog-meta{display:flex;align-items:center;gap:8px;flex-wrap:wrap;justify-content:flex-end}
.amv2 .video-mode-list{display:grid;gap:8px;padding:0 12px 12px}
.amv2 .video-economy-note{display:flex;align-items:center;gap:10px 18px;flex-wrap:wrap;padding:10px 12px;border:1px solid rgba(234,255,16,.22);border-radius:var(--radius);background:rgba(234,255,16,.045);font-size:11px}.amv2 .video-economy-note strong{color:var(--lime)}.amv2 .video-economy-note span{color:var(--muted)}
.amv2 .video-mode{border:1px solid var(--line);border-radius:var(--radius);overflow:hidden;background:rgba(255,255,255,.018)}
.amv2 .video-mode-toggle{width:100%;display:grid;gap:14px;align-items:center;padding:11px 12px;border:0;background:transparent;color:var(--text);text-align:left;cursor:pointer}
.amv2 .video-mode-toggle:hover{background:rgba(234,255,16,.035)}.amv2 .video-mode-toggle span{display:block;color:var(--muted);font-size:10px;font-weight:500}.amv2 .video-mode-toggle strong{font-size:12px}
.amv2 .video-mode-finance-head{grid-template-columns:minmax(260px,1.5fr) repeat(3,minmax(120px,.7fr)) auto}.amv2 .video-mode-finance-head>div{display:grid;gap:3px}.amv2 .video-mode-count{display:flex!important;grid-auto-flow:column;gap:7px!important}.amv2 .video-mode-count b{padding:3px 7px;border:1px solid var(--line);border-radius:999px;color:var(--muted);font-size:10px;white-space:nowrap}
.amv2 .video-finance-wrap{border-top:1px solid var(--line)}.amv2 .video-finance-table{min-width:1500px}.amv2 .video-finance-table th>span{display:block;margin-top:3px;color:var(--muted);font-size:9px;font-weight:500;text-transform:none;letter-spacing:0}.amv2 .video-finance-table td{height:42px}.amv2 .video-scenario,.amv2 .video-summary-econ{display:grid;gap:3px;white-space:nowrap}.amv2 .video-scenario strong,.amv2 .video-summary-econ strong{font-size:12px}.amv2 .video-scenario span,.amv2 .video-summary-econ span{color:var(--muted);font-size:10px}
.amv2 .video-expand{width:28px;height:28px;padding:0;border:1px solid var(--line);border-radius:var(--radius);background:rgba(255,255,255,.035);color:var(--text);font-size:16px}.amv2 .video-tier-checks{justify-content:flex-start}
.amv2 .video-model-detail{padding:10px 0 2px;display:grid;gap:9px;color:var(--muted);font-size:12px;line-height:1.45}.amv2 .video-model-detail b{color:var(--text)}.amv2 .video-capabilities{display:flex;gap:8px 18px;flex-wrap:wrap}.amv2 .video-model-detail details{margin:0}.amv2 .video-model-detail details p{padding:0 12px 12px;margin:0}
.amv2 .video-economics-wrap{overflow-x:auto;border:1px solid var(--line);border-radius:var(--radius)}.amv2 .video-economics-table{min-width:max-content}.amv2 .video-economics-table th,.amv2 .video-economics-table td{padding:7px 9px;vertical-align:middle}.amv2 .video-economics-table thead th{position:sticky;top:0}.amv2 .video-economics-table tbody th{position:sticky;left:0;z-index:1;min-width:235px;background:#151815}.amv2 .video-economics-table tbody th small{display:block;color:var(--muted);font-weight:500;margin-top:3px}.amv2 .video-economics-cell{display:grid;gap:2px;min-width:175px;white-space:nowrap}.amv2 .video-economics-cell strong{color:var(--lime);font-size:12px}.amv2 .video-economics-cell span{font-size:10px;color:var(--muted)}
.amv2 .video-evidence{color:var(--yellow)}
.amv2 .sort-head{appearance:none;border:0;background:transparent;color:var(--muted);font:inherit;font-size:11px;font-weight:650;text-transform:uppercase;letter-spacing:.04em;padding:0;display:inline-flex;align-items:center;gap:6px}
.amv2 .sort-head.active{color:var(--lime)}
.amv2 .detail-cell{padding:0 10px 9px 10px!important;background:rgba(255,255,255,.018)}
.amv2 .detail-box{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:6px 14px;color:var(--muted);line-height:1.35;font-size:11px}
.amv2 .detail-box span{overflow-wrap:anywhere}
.amv2 .api-table .model-name{white-space:nowrap;font-size:12px;font-weight:700}
.amv2 .api-table .model-release{display:block;margin-top:3px;color:var(--muted);font-size:9px;white-space:nowrap}
.amv2 .api-enabled{width:28px;text-align:center}
.amv2 .api-column-label{display:block;margin-bottom:3px;color:var(--muted);font-size:8px;font-weight:700;text-transform:none;letter-spacing:0}
.amv2 .api-enabled input{width:16px;height:16px;min-width:16px;min-height:16px;padding:0;margin:0;vertical-align:middle}
.amv2 .format-table th:nth-child(1),.amv2 .format-table tr.api-model-row>td:nth-child(1),.amv2 .video-finance-table th:nth-child(1),.amv2 .video-finance-table tr.api-model-row>td:nth-child(1){position:sticky;left:0;z-index:2;min-width:90px;background:#151815}
.amv2 .format-table th:nth-child(2),.amv2 .format-table tr.api-model-row>td:nth-child(2),.amv2 .video-finance-table th:nth-child(2),.amv2 .video-finance-table tr.api-model-row>td:nth-child(2){position:sticky;left:90px;z-index:2;min-width:56px;background:#151815}
.amv2 .format-table th:nth-child(3),.amv2 .format-table tr.api-model-row>td:nth-child(3),.amv2 .video-finance-table th:nth-child(3),.amv2 .video-finance-table tr.api-model-row>td:nth-child(3){position:sticky;left:146px;z-index:2;min-width:56px;background:#151815}
.amv2 .format-table th:nth-child(4),.amv2 .format-table tr.api-model-row>td:nth-child(4),.amv2 .video-finance-table th:nth-child(4),.amv2 .video-finance-table tr.api-model-row>td:nth-child(4){position:sticky;left:202px;z-index:2;min-width:240px;background:#151815;box-shadow:1px 0 var(--line)}
.amv2 .format-table thead th:nth-child(-n+4),.amv2 .video-finance-table thead th:nth-child(-n+4){z-index:4}
.amv2 .tier-checks{display:flex;align-items:center;gap:5px;white-space:nowrap}
.amv2 .tier-checks label{display:inline-flex;align-items:center;gap:3px;color:var(--muted);font-size:10px;font-weight:800}
.amv2 .tier-checks input{width:14px;height:14px;min-width:14px;min-height:14px;padding:0;margin:0}
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
.amv2 .assistant-config{display:grid;grid-template-columns:minmax(0,1.25fr) minmax(300px,.75fr);gap:12px}
.amv2 .assistant-form{padding:14px;display:grid;gap:12px}
.amv2 .assistant-form textarea,.amv2 .assistant-test textarea{font-size:13px;font-weight:400;letter-spacing:0;line-height:1.45}
.amv2 .assistant-form textarea{min-height:108px;resize:vertical}
.amv2 .assistant-form .mode-prompt{min-height:86px}
.amv2 .assistant-test{padding:14px;display:grid;gap:10px;align-content:start}
.amv2 .assistant-test-result{padding:12px;border:1px solid var(--line);border-radius:var(--radius);background:rgba(255,255,255,.03);display:grid;gap:6px}
.amv2 .request-preview{display:grid;gap:10px;padding:14px;border-top:1px solid var(--line)}
.amv2 .request-preview pre{margin:0;max-height:260px;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere;padding:12px;border:1px solid var(--line);border-radius:var(--radius);background:#0b0d0b;color:#dfe5dc;font:400 12px/1.5 ui-monospace,SFMono-Regular,Consolas,monospace}
.amv2 .request-preview label{color:var(--muted);font-size:10px;text-transform:uppercase}
.amv2 .assistant-test-result small{color:var(--muted)}
.amv2 .ollama-list{display:grid;gap:7px}
.amv2 .ollama-row{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:10px;padding:9px;border:1px solid var(--line);border-radius:var(--radius)}
.amv2 .ollama-row small{color:var(--muted)}
.amv2 .assistant-economy{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:8px;margin:0 0 12px}
.amv2 .assistant-economy>div{padding:10px;border:1px solid var(--line);border-radius:var(--radius);background:rgba(255,255,255,.025);display:grid;gap:3px}
.amv2 .assistant-economy small{color:var(--muted);font-size:10px;text-transform:uppercase}.amv2 .assistant-economy strong{font-size:13px;color:var(--lime)}
.amv2 .assistant-history{grid-column:1/-1;display:grid;gap:5px;max-height:210px;overflow:auto}
.amv2 .assistant-history-row{display:grid;grid-template-columns:150px 90px minmax(120px,1fr) 110px 110px;gap:8px;padding:7px 9px;border-bottom:1px solid var(--line);font-size:11px;align-items:center}
.amv2 .assistant-history-row .bad{color:#ff7777}.amv2 .assistant-history-row .ok{color:var(--lime)}
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
@media (max-width:880px){.amv2 .route-row,.amv2 .toolbar,.amv2 .ops-row,.amv2 .job-row,.amv2 .api-key-panel,.amv2 .or-stats,.amv2 .assistant-config{grid-template-columns:1fr}.amv2 .assistant-economy{grid-template-columns:repeat(2,minmax(0,1fr))}.amv2 .assistant-history-row{grid-template-columns:1fr 70px}.amv2 .assistant-history-row span:nth-child(n+3){grid-column:1/-1}.amv2 .server-command{align-items:stretch;flex-wrap:wrap}.amv2 .server-command .server-title{width:100%}.amv2 .profile-switch{flex:1}.amv2 .lora-columns,.amv2 .config-profiles{grid-template-columns:1fr}.amv2 .lora-row{grid-template-columns:28px 1fr 80px}.amv2 .lora-row>div:nth-child(3),.amv2 .lora-row>div:nth-child(4){grid-column:2 / -1}.amv2 .tab-status{width:100%;justify-content:flex-start;flex-wrap:wrap}.amv2 .models-page-head{display:grid}.amv2 .models-page-head-status{margin-left:0}.amv2 .models-page-head-status .tab-status{justify-content:flex-start}.amv2 .page-tabs{grid-template-columns:repeat(2,minmax(0,1fr))}.amv2 .openrouter-page-nav{display:flex;overflow-x:auto}.amv2 .openrouter-page-nav button{flex:0 0 auto;min-width:112px}.amv2 .matrix-wrap{overflow-x:auto}.amv2 .matrix-wrap table{min-width:980px}.amv2 .matrix-wrap .api-table{min-width:760px}.amv2 .api-section-head{grid-template-columns:minmax(0,1fr) auto}.amv2 .api-section-head .section-cell:not(:first-child){display:none}.amv2 .api-section-head .api-count{justify-content:flex-end;flex-wrap:wrap;white-space:normal}.amv2 .matrix-wrap .api-table.format-table{min-width:0;width:100%;table-layout:fixed}.amv2 .format-table th:nth-child(5),.amv2 .format-table td:nth-child(5),.amv2 .format-table th:nth-child(n+7),.amv2 .format-table td:nth-child(n+7){display:none}.amv2 .format-table th:nth-child(2),.amv2 .format-table td:nth-child(2),.amv2 .format-table th:nth-child(3),.amv2 .format-table td:nth-child(3){width:42px;padding-left:4px;padding-right:4px}.amv2 .format-table th:nth-child(1),.amv2 .format-table td:nth-child(1){width:86px}.amv2 .format-table th:nth-child(4),.amv2 .format-table td:nth-child(4){width:132px}.amv2 .format-table .tier-checks{flex-wrap:wrap;white-space:normal;gap:5px 8px}.amv2 .format-table .detail-cell{display:table-cell!important}.amv2 .detail-box{grid-template-columns:1fr}.amv2 .mobile-models{display:grid}}
@media (max-width:580px){.amv2 .metric-grid,.amv2 .two-col,.amv2 .price-row,.amv2 .lora-grid,.amv2 .advanced-grid,.amv2 .status-grid,.amv2 .mode-board,.amv2 .or-stats,.amv2 .server-overview,.amv2 .assistant-summary,.amv2 .assistant-economy{grid-template-columns:1fr}.amv2 .profile-switch{width:100%}.amv2 .server-restart{width:100%}}
@media (max-width:880px){.amv2 .video-catalog-card{width:calc(100vw - 40px);max-width:calc(100vw - 40px)}.amv2 .video-mode-finance-head{grid-template-columns:1fr 1fr}.amv2 .video-mode-finance-head>div:first-child,.amv2 .video-mode-count{grid-column:1 / -1}.amv2 .video-catalog-head{align-items:flex-start;flex-direction:column}.amv2 .video-catalog-meta{width:100%;justify-content:flex-start}.amv2 .video-model-detail{overflow-wrap:anywhere}.amv2 .video-economy-note{display:grid;gap:5px}}
`

export default function AdminModelsV2({ embeddedInSidebar = false }: { embeddedInSidebar?: boolean }) {
  const [data, setData] = useState<PageData | null>(null)
  const [pageTab, setPageTab] = useState<AdminModelsPage>(() => adminModelsPageFromPath(window.location.pathname))
  const [openrouterPage, setOpenrouterPage] = useState<AdminOpenRouterPage>(() => adminOpenRouterPageFromPath(window.location.pathname))
  const [configSection, setConfigSection] = useState<'image' | 'video' | 'text'>('image')
  const [configRuntime, setConfigRuntime] = useState({ imageEnabled: true, videoEnabled: true, videoProfile: 'local/ltx-2.3-fast-q3' })
  const [configStatus, setConfigStatus] = useState<ConfigStatus | null>(null)
  const [routes, setRoutes] = useState<Route[]>([])
  const [query, setQuery] = useState('')
  const [marginDraft, setMarginDraft] = useState('40')
  const [tokenRubDraft, setTokenRubDraft] = useState('5')
  const [apiSorts, setApiSorts] = useState<Record<string, ApiSortState>>({})
  const [apiSectionsOpen, setApiSectionsOpen] = useState<Record<string, boolean>>({})
  const [apiExpandedRows, setApiExpandedRows] = useState<Record<string, boolean>>({})
  const [videoSectionsOpen, setVideoSectionsOpen] = useState<Record<string, boolean>>({})
  const [videoExpandedRows, setVideoExpandedRows] = useState<Record<string, boolean>>({})
  const [videoConfigBusy, setVideoConfigBusy] = useState(false)
  const [openrouterKeyInput, setOpenrouterKeyInput] = useState('')
  const [openrouterBusy, setOpenrouterBusy] = useState(false)
  const [openrouterCatalogBusy, setOpenrouterCatalogBusy] = useState(false)
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

  const navigateModelsPage = useCallback((next: AdminModelsPage) => {
    const path = adminModelsPath(next)
    setPageTab(next)
    setMsg('')
    if (window.location.pathname !== path) {
      window.history.pushState({}, '', path)
      window.dispatchEvent(new PopStateEvent('popstate'))
    }
  }, [])

  const navigateOpenRouterPage = useCallback((next: AdminOpenRouterPage) => {
    const path = adminOpenRouterPath(next)
    setOpenrouterPage(next)
    setMsg('')
    if (window.location.pathname !== path) {
      window.history.pushState({}, '', path)
      window.dispatchEvent(new PopStateEvent('popstate'))
    }
  }, [])

  useEffect(() => {
    const syncFromLocation = () => {
      if (['/admin/models', '/admin/models/openrouter'].includes(window.location.pathname.replace(/\/+$/, ''))) {
        window.history.replaceState({}, '', adminModelsPath('api'))
      }
      setPageTab(adminModelsPageFromPath(window.location.pathname))
      setOpenrouterPage(adminOpenRouterPageFromPath(window.location.pathname))
    }
    syncFromLocation()
    window.addEventListener('popstate', syncFromLocation)
    return () => window.removeEventListener('popstate', syncFromLocation)
  }, [])

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
  useEffect(() => {
    if ((pageTab === 'api' || pageTab === 'config' || pageTab === 'improve') && !data) {
      queueMicrotask(() => { void load() })
    }
  }, [data, load, pageTab])

  const loadLocalModelData = useCallback(async () => {
    const d = await amvFetch('/admin/models-page?local=1').then((r) => (r.ok ? r.json() : null)).catch(() => null) as PageData | null
    if (!d) return
    setData((current) => current ? { ...current, routes: d.routes, catalog: d.catalog, loras: d.loras, loraSettings: d.loraSettings, serverModelProfiles: d.serverModelProfiles, comfyuiAvailable: d.comfyuiAvailable, comfyFiles: d.comfyFiles, profiles: d.profiles, economy: d.economy } : d)
    setLoraAccess(d.loraSettings?.enabled || {})
    setServerProfiles(d.serverModelProfiles?.profiles || {})
    setRoutes(d.routes || [])
  }, [])

  const loadTariffs = useCallback(async () => {
    const result = await amvFetch('/admin/settings').then((r) => r.ok ? r.json() : null).catch(() => null) as { tariffs?: unknown; config_ui_resolution_access?: unknown; config_ui_runtime?: { imageEnabled?: boolean; videoEnabled?: boolean; videoProfile?: string } } | null
    if (result?.tariffs) setTariffs(applyConfigUiResolutionAccess(normalizeTariffs(result.tariffs), result.config_ui_resolution_access))
    if (result?.config_ui_runtime) setConfigRuntime({
      imageEnabled: result.config_ui_runtime.imageEnabled !== false,
      videoEnabled: result.config_ui_runtime.videoEnabled !== false,
      videoProfile: result.config_ui_runtime.videoProfile || 'local/ltx-2.3-fast-q3',
    })
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
    if (result?.config) setAssistantData({
      ...result,
      openrouterModels: Array.isArray(result.openrouterModels) ? result.openrouterModels : [],
      openrouterAudioModels: Array.isArray(result.openrouterAudioModels) ? result.openrouterAudioModels : [],
    })
    else setMsg('Не удалось загрузить настройки голосового ввода и улучшения')
  }, [])

  useEffect(() => {
    if ((pageTab === 'improve' || pageTab === 'api' || pageTab === 'config') && !assistantData) queueMicrotask(() => { void loadAssistants() })
  }, [assistantData, loadAssistants, pageTab])

  const updateAssistantConfig = (next: AssistantConfig) => setAssistantData((current) => current ? { ...current, config: next } : current)
  const saveAssistantConfig = async () => {
    if (!assistantData) return
    setAssistantBusy(true)
    const publishedApiModels = assistantData.config.chat.publishedApiModels || assistantData.config.chat.enabledApiModels
    const normalizedConfig = {
      ...assistantData.config,
      chat: {
        ...assistantData.config.chat,
        publishedApiModels,
        enabledApiModels: [...publishedApiModels],
      },
    }
    await saveSetting('assistant_models', normalizedConfig, 'Настройки помощников')
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
  const saveConfigRuntime = async (next: { imageEnabled: boolean; videoEnabled: boolean; videoProfile: string }) => {
    setConfigRuntime(next)
    const saved = await saveSetting('config_ui_runtime', next, 'Настройки локальных сервисов')
    if (saved) {
      setConfigRuntime({
        imageEnabled: (saved as { imageEnabled?: boolean }).imageEnabled !== false,
        videoEnabled: (saved as { videoEnabled?: boolean }).videoEnabled !== false,
        videoProfile: (saved as { videoProfile?: string }).videoProfile || 'local/ltx-2.3-fast-q3',
      })
      await loadConfigStatus()
    }
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
    const resolutionAccess = { plans: Object.fromEntries(tariffKeys.map((plan) => [plan, tariffs[plan].allowed_resolutions.filter((id) => CONFIG_UI_RUNTIME_RESOLUTION_IDS.has(id))])) }
    const accessSaved = await saveSetting('config_ui_resolution_access', resolutionAccess, 'Доступность разрешений по тарифам')
    if (!accessSaved) return
    const verified = await amvFetch('/admin/settings').then((r) => r.ok ? r.json() : null).catch(() => null) as { tariffs?: unknown; config_ui_resolution_access?: unknown } | null
    if (!verified?.tariffs || !verified.config_ui_resolution_access) { setMsg('Настройки сохранены, но контрольная проверка не выполнена'); return }
    const normalized = applyConfigUiResolutionAccess(normalizeTariffs(verified.tariffs), verified.config_ui_resolution_access)
    setTariffs(normalized)
    const expected = tariffKeys.every((plan) => tariffs[plan].allowed_resolutions.filter((id) => CONFIG_UI_RUNTIME_RESOLUTION_IDS.has(id)).sort().join('|') === [...normalized[plan].allowed_resolutions].sort().join('|'))
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

  const refreshOpenrouterCatalog = async () => {
    if (openrouterCatalogBusy) return
    setOpenrouterCatalogBusy(true)
    setMsg('Каталог OpenRouter обновляется в фоне…')
    const started = await amvFetch('/admin/openrouter/catalog/refresh-v2', { method: 'POST' })
      .then((response) => response.ok ? response.json() : null)
      .catch(() => null) as { ok?: boolean } | null
    if (!started?.ok) {
      setOpenrouterCatalogBusy(false)
      setMsg('Не удалось запустить обновление каталога')
      return
    }
    for (let attempt = 0; attempt < 12; attempt += 1) {
      await new Promise((resolve) => window.setTimeout(resolve, 1000))
      const status = await amvFetch('/admin/openrouter/catalog/status-v2')
        .then((response) => response.ok ? response.json() : null)
        .catch(() => null) as { catalog?: { refreshing?: boolean; lastError?: string | null } } | null
      if (status?.catalog && !status.catalog.refreshing) {
        await load()
        setOpenrouterCatalogBusy(false)
        setMsg(status.catalog.lastError ? 'Показан последний сохранённый каталог: живое обновление временно недоступно' : 'Каталог OpenRouter обновлён')
        return
      }
    }
    await load()
    setOpenrouterCatalogBusy(false)
    setMsg('Обновление продолжается в фоне; последний каталог остаётся доступен')
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

  const saveVideoConfig = async (config: OpenRouterVideoConfig) => {
    setVideoConfigBusy(true)
    const saved = await saveSetting('openrouter_video_models', config, 'Доступность видеомоделей') as OpenRouterVideoConfig | null
    setVideoConfigBusy(false)
    if (saved) setData((current) => current ? { ...current, openrouter: { ...current.openrouter, videoConfig: saved } } : current)
  }

  const toggleVideoPublished = (modelId: string, checked: boolean) => {
    if (!data) return
    void saveVideoConfig(setVideoPublication(data.openrouter.videoConfig || {}, [modelId], checked))
  }

  const toggleVideoPublicationSection = (modelIds: string[], checked: boolean) => {
    if (!data) return
    void saveVideoConfig(setVideoPublication(data.openrouter.videoConfig || {}, modelIds, checked))
  }

  const toggleVideoModel = (mode: OpenRouterVideoMode, modelId: string, checked: boolean) => {
    if (!data) return
    const current = data.openrouter.videoConfig || {}
    const enabled = JSON.parse(JSON.stringify(current.enabled || {})) as NonNullable<OpenRouterVideoConfig['enabled']>
    const access = JSON.parse(JSON.stringify(current.access || {})) as NonNullable<OpenRouterVideoConfig['access']>
    const values = new Set(enabled[mode] || [])
    if (checked) values.add(modelId)
    else {
      values.delete(modelId)
      for (const tier of OPENROUTER_TIERS) {
        const tierValues = new Set(access[mode]?.[tier.id] || [])
        tierValues.delete(modelId)
        if (access[mode]) {
          if (tierValues.size) access[mode]![tier.id] = Array.from(tierValues).sort()
          else delete access[mode]![tier.id]
        }
      }
    }
    if (values.size) enabled[mode] = Array.from(values).sort()
    else delete enabled[mode]
    if (access[mode] && !Object.keys(access[mode]!).length) delete access[mode]
    void saveVideoConfig({ published: current.published || [], enabled, access })
  }

  const toggleVideoTier = (mode: OpenRouterVideoMode, tier: OpenRouterTier, modelId: string, checked: boolean) => {
    if (!data) return
    const current = data.openrouter.videoConfig || {}
    const enabled = JSON.parse(JSON.stringify(current.enabled || {})) as NonNullable<OpenRouterVideoConfig['enabled']>
    const access = JSON.parse(JSON.stringify(current.access || {})) as NonNullable<OpenRouterVideoConfig['access']>
    access[mode] = access[mode] || {}
    const tierValues = new Set(access[mode]?.[tier] || [])
    if (checked) tierValues.add(modelId)
    else tierValues.delete(modelId)
    if (tierValues.size) access[mode]![tier] = Array.from(tierValues).sort()
    else delete access[mode]![tier]
    if (!Object.keys(access[mode]!).length) delete access[mode]
    if (checked) enabled[mode] = Array.from(new Set([...(enabled[mode] || []), modelId])).sort()
    void saveVideoConfig({ published: current.published || [], enabled, access })
  }

  const toggleVideoSection = (mode: OpenRouterVideoMode, modelIds: string[], checked: boolean) => {
    if (!data) return
    const current = data.openrouter.videoConfig || {}
    const enabled = JSON.parse(JSON.stringify(current.enabled || {})) as NonNullable<OpenRouterVideoConfig['enabled']>
    const access = JSON.parse(JSON.stringify(current.access || {})) as NonNullable<OpenRouterVideoConfig['access']>
    const ids = Array.from(new Set(modelIds)).sort()
    if (checked) enabled[mode] = ids
    else {
      delete enabled[mode]
      delete access[mode]
    }
    void saveVideoConfig({ published: current.published || [], enabled, access })
  }

  const toggleVideoTierColumn = (mode: OpenRouterVideoMode, tier: OpenRouterTier, modelIds: string[], checked: boolean) => {
    if (!data) return
    const current = data.openrouter.videoConfig || {}
    const enabled = JSON.parse(JSON.stringify(current.enabled || {})) as NonNullable<OpenRouterVideoConfig['enabled']>
    const access = JSON.parse(JSON.stringify(current.access || {})) as NonNullable<OpenRouterVideoConfig['access']>
    access[mode] = access[mode] || {}
    if (checked) access[mode]![tier] = Array.from(new Set(modelIds)).sort()
    else delete access[mode]![tier]
    if (!Object.keys(access[mode]!).length) delete access[mode]
    void saveVideoConfig({ published: current.published || [], enabled, access })
  }

  const toggleOpenrouterModel = (mode: string, modelId: string, checked: boolean) => {
    if (!data) return
    void saveOpenrouterConfig(setImageModelOperation(data.openrouter.config || {}, mode, modelId, checked))
  }

  const toggleOpenrouterPublished = (modelId: string, checked: boolean) => {
    if (!data) return
    void saveOpenrouterConfig(setImageModelPublished(data.openrouter.config || {}, modelId, checked))
  }

  const toggleOpenrouterSection = (mode: string, modelIds: string[], checked: boolean) => {
    if (!data) return
    void saveOpenrouterConfig(setImageModelSection(data.openrouter.config || {}, mode, modelIds, checked))
  }

  const toggleOpenrouterTier = (mode: string, tier: OpenRouterTier, modelId: string, checked: boolean) => {
    if (!data) return
    void saveOpenrouterConfig(setImageModelTier(data.openrouter.config || {}, mode, tier, modelId, checked))
  }

  const toggleOpenrouterTierColumn = (mode: string, tier: OpenRouterTier, modelIds: string[], checked: boolean) => {
    if (!data) return
    void saveOpenrouterConfig(setImageModelTierColumn(data.openrouter.config || {}, mode, tier, modelIds, checked))
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

  if (pageTab === 'energy') return <div className="amv2">
    <style>{CSS}</style>
    <AdminModelsNavigation active={pageTab} onNavigate={navigateModelsPage} showTabs={!embeddedInSidebar} showHeader={!embeddedInSidebar} />
    <Suspense fallback={<div className="models-page-loading">Загружаем энергопотребление…</div>}><AdminEnergy /></Suspense>
  </div>

  if (pageTab === 'voice') return <div className="amv2">
    <style>{CSS}</style>
    <AdminModelsNavigation active={pageTab} onNavigate={navigateModelsPage} showTabs={!embeddedInSidebar} showHeader={!embeddedInSidebar} />
    <Suspense fallback={<div className="models-page-loading">Загружаем голосовой ввод…</div>}><AdminVoice embedded={embeddedInSidebar} /></Suspense>
  </div>

  if (!data) return <div className="amv2">
    <style>{CSS}</style>
    <AdminModelsNavigation active={pageTab} onNavigate={navigateModelsPage} showTabs={!embeddedInSidebar} showHeader={!embeddedInSidebar} />
    <div className="models-page-loading">
      <p style={{ color: err ? 'var(--red)' : 'var(--muted)' }}>{err || 'Загружаем данные раздела…'}</p>
      {err && <button className="ghost" style={{ width: 'max-content' }} onClick={() => void load()}>Повторить</button>}
    </div>
  </div>

  const orStatus = data.openrouter.status || {}
  const orData = orStatus.data || {}
  const orCredits = orStatus.credits || {}
  const orCreditsData = orCredits.data && typeof orCredits.data === 'object' ? orCredits.data as Record<string, unknown> : {}
  const orAvailability = orStatus.availability || {}
  const minMarginPercent = clampMargin(data.openrouter.economy?.minMarginPercent)
  const tokenRub = clampTokenRub(data.openrouter.economy?.tokenRub)
  const usdRubBase = exchangeRate(data.openrouter.exchange)
  const usdRubEffective = effectiveUsdRub(data.openrouter.exchange)
  const generationReady = orStatus.ready
  const generationStatusClass = generationReady === true ? 'key-ok' : generationReady === false ? 'key-bad' : 'key-warn'
  const generationStatusText = orAvailability.state === 'billing_blocked'
    ? 'оплата провайдера заблокировала генерацию'
    : orAvailability.state === 'authorization_blocked'
      ? 'доступ провайдера заблокирован'
      : orAvailability.state === 'service_error'
        ? 'последняя генерация завершилась сбоем'
        : generationReady === true
          ? 'реальная генерация подтверждена'
          : 'ещё не подтверждено реальной генерацией'
  const orStatusClass = orStatus.ok ? 'key-ok' : orStatus.configured ? 'key-bad' : 'key-warn'
  const orStatusText = orStatus.ok ? 'ключ отвечает' : orStatus.configured ? 'ключ есть, проверка не прошла' : 'ключ не сохранён'
  const orLimit = orData.limit === null || orData.limit === undefined ? 'без лимита / не задан' : moneyUsdText(orData.limit)
  const orRemaining = orData.limit_remaining === null || orData.limit_remaining === undefined ? '—' : moneyUsdText(orData.limit_remaining)
  const orUsageModels = usageModelMap(data.openrouter.usage?.models)
  const orUsageModes = usageModeMap(data.openrouter.usage?.modes)
  const videoUsageModels = usageModelMap(data.openrouter.videoUsage?.models)
  const videoUsageModes = usageModeMap(data.openrouter.videoUsage?.modes)
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
      created: model.created,
    }
  }) : OPENROUTER_IMAGE_MODELS.map(fallbackCapabilityModel)
  const publishedModelIds = new Set(publishedImageModelIds(data.openrouter.config || {}))
  const backendPricedCount = backendPricingMap.size
  const totalSpentPair = typeof data.openrouter.usage?.totalCostUsd === 'number' ? moneyPair(data.openrouter.usage.totalCostUsd, usdRubEffective) : '—'
  const avgImagePair = typeof data.openrouter.usage?.avgCostUsd === 'number' ? moneyPair(data.openrouter.usage.avgCostUsd, usdRubEffective) : '—'
  const avgMpPair = typeof data.openrouter.usage?.avgCostPerMpUsd === 'number' ? moneyPair(data.openrouter.usage.avgCostPerMpUsd, usdRubEffective) : '—'
  const favoriteOverall = (data.openrouter.usage?.models || [])[0]
  const favoriteOverallName = modelLabelById(favoriteOverall?.model)
  const calculatedCreditsBalance = typeof orCredits.calculated_balance === 'number' ? orCredits.calculated_balance : null
  const effectiveRateText = usdRubBase === null || usdRubEffective === null
    ? 'курс ЦБ не загрузился'
    : `$1 ${usdRubBase.toFixed(2)} ₽ + ${Math.round(USD_FEE_RATE * 100)}% = ${usdRubEffective.toFixed(2)} ₽`
  const spentTokensText = tokensText(data.openrouter.usage?.totalCostUsd, usdRubEffective, tokenRub)
  const exchangeCache = data.openrouter.exchange?.cache || ''
  const exchangeStateClass = usdRubBase === null ? 'rate-bad' : exchangeCache === 'stale' ? 'rate-stale' : 'rate-ok'
  const exchangeStateText = usdRubBase === null ? 'курс не загружен' : exchangeCache === 'stale' ? 'курс из последнего кэша' : 'курс загружен'
  const selectedAssistantApiModel = assistantData?.openrouterModels.find((model) => model.id === assistantData.config.improve.apiModel)
  const normalizedModelQuery = query.trim().toLowerCase()
  const filteredOpenrouterTextModels = (assistantData?.openrouterModels || []).filter((model) =>
    !normalizedModelQuery || `${model.id} ${model.name}`.toLowerCase().includes(normalizedModelQuery),
  )
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
    <AdminModelsNavigation active={pageTab} onNavigate={navigateModelsPage} showTabs={!embeddedInSidebar} showHeader={!embeddedInSidebar} status={pageTab === 'api' ? <div className="tab-status">
        <span className={`status-dot ${orStatus.ok ? 'ok' : data.openrouter.keyConfigured ? 'warn' : ''}`} aria-hidden="true" />
        <span className={`state ${orStatus.ok ? 'ok' : data.openrouter.keyConfigured ? 'warn' : 'bad'}`}>{orStatus.ok ? 'ключ работает' : data.openrouter.keyConfigured ? 'проверить ключ' : 'нет ключа'}</span>
        <span className="state ok">billing: {backendPricedCount} моделей</span>
        <button className={`state ${exchangeStateClass}`} disabled={exchangeBusy} onClick={refreshExchange}>{exchangeBusy ? 'обновляю курс…' : `${exchangeStateText}: ${effectiveRateText}`}</button>
      </div> : undefined} />

    {pageTab === 'improve' && !assistantData && <div className="models-page-loading">Загружаем настройки улучшения промпта…</div>}

    {pageTab === 'improve' && assistantData && <>
      <section className="assistant-summary">
        <div><span>Текущий маршрут</span><strong>{assistantData.config.improve.route === 'api' ? 'OpenRouter API' : assistantData.config.improve.route === 'local' ? 'Локальная Ollama' : 'Авто: local → API'}</strong><small>Изменение применяется ко всем вкладкам студии.</small></div>
        <div><span>Ollama</span><strong>{assistantData.ollama.ok ? (assistantData.ollamaResidency.models.some((m) => (m.name || m.model) === assistantData.config.improve.localModel) ? 'Модель в памяти' : 'В сети, модель выгружена') : 'Не отвечает'}</strong><small>{assistantData.ollama.baseUrl}</small></div>
        <div><span>OpenRouter</span><strong>{assistantData.openrouterConfigured ? 'Ключ настроен' : 'Нет ключа'}</strong><small>Ключ управляется в существующей вкладке OpenRouter.</small></div>
      </section>
      <section className="assistant-economy">
        <div><small>Успешно · 30 дней</small><strong>{assistantData.usage.totals.successful}</strong></div>
        <div><small>Ошибки</small><strong>{assistantData.usage.totals.failed}</strong></div>
        <div><small>Переключения</small><strong>{assistantData.usage.totals.fallbacks}</strong></div>
        <div><small>OpenRouter</small><strong>{assistantData.usage.totals.cost_rub.toFixed(4)} ₽ · ${assistantData.usage.totals.cost_usd.toFixed(6)}</strong></div>
        <div><small>Локальная энергия</small><strong>{assistantData.usage.totals.energy_wh.toFixed(4)} Wh</strong></div>
        <div><small>Стоимость энергии</small><strong>{assistantData.usage.totals.energy_cost_rub.toFixed(4)} ₽</strong></div>
        <details className="assistant-history"><summary>Последние вызовы и переключения</summary>{assistantData.usage.recent.map((item, index) => <div className="assistant-history-row" key={`${item.createdAt}-${index}`}><span>{new Date(item.createdAt).toLocaleString('ru-RU')}</span><b className={item.ok ? 'ok' : 'bad'}>{item.ok ? 'готово' : 'ошибка'}</b><span>{item.route || '—'} → {item.provider || '—'}{item.fallbackUsed ? ' · резерв' : ''}<br />{item.model || item.mode || '—'}</span><span>{Number(item.costRub || 0).toFixed(4)} ₽<br />${Number(item.costUsd || 0).toFixed(6)}</span><span>{Number(item.energyWh || 0).toFixed(4)} Wh<br />{Number(item.latencyMs || 0)} мс</span></div>)}</details>
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
          <div className="request-preview">
            <div className="field"><label>Режим для предпросмотра запроса</label><select value={assistantPreviewMode} onChange={(e) => setAssistantPreviewMode(e.target.value)}>{Object.keys(assistantData.config.improve.modePrompts).map((mode) => <option key={mode} value={mode}>{ASSISTANT_MODE_LABELS[mode] || mode}</option>)}</select></div>
            <label>Сообщение system — итог после объединения всех инструкций</label>
            <pre>{assistantPreviewSystem}</pre>
            <label>Сообщение user — данные пользователя и технический контекст</label>
            <pre>{assistantPreviewUser}</pre>
            <small>Эти два сообщения в таком составе отправляются выбранной модели. Значение user берётся из поля «Проверка моделей» справа.</small>
          </div>
        </article>
        <aside className="card">
          <div className="card-head"><div><h2 className="card-title">Проверка моделей</h2><p className="card-note">Тест не меняет пользовательские промпты.</p></div></div>
          <div className="assistant-test">
            <textarea value={assistantTestPrompt} onChange={(e) => setAssistantTestPrompt(e.target.value)} />
            <div className="actions"><button className="ghost" disabled={assistantBusy} onClick={() => void testPromptAssistant('local')}>Тест Ollama</button><button className="ghost" disabled={assistantBusy} onClick={() => void testPromptAssistant('api')}>Тест OpenRouter</button></div>
            {assistantTestResult && <div className="assistant-test-result"><strong>{assistantTestResult.detail || assistantTestResult.improvedPrompt}</strong>{assistantTestResult.model && <small>{assistantTestResult.provider} · {assistantTestResult.model} · {assistantTestResult.latencyMs} мс · {Number(assistantTestResult.costRub || 0).toFixed(4)} ₽ · ${Number(assistantTestResult.costUsd || 0).toFixed(6)}{assistantTestResult.energyWh ? ` · ${assistantTestResult.energyWh.toFixed(4)} Wh` : ''}</small>}</div>}
            <div className="ollama-list">{assistantData.ollama.models.filter((m) => m.name).map((m) => <div className="ollama-row" key={m.name}><div><strong>{m.name}</strong><small>{m.name?.endsWith(':cloud') ? 'Ollama Cloud' : `${m.details?.parameter_size || '—'} · ${m.details?.quantization_level || '—'}`}</small></div><small>{m.name?.endsWith(':cloud') ? 'облако' : m.size ? `${(m.size / 1024 ** 3).toFixed(1)} ГБ` : '—'}</small></div>)}</div>
          </div>
        </aside>
      </section>
    </>}

    {pageTab === 'config' && <>
    <div className="page-tabs" aria-label="Разделы Config UI" style={{ marginBottom: 12 }}>
      <button className={configSection === 'image' ? 'active' : ''} onClick={() => setConfigSection('image')}>Изображения</button>
      <button className={configSection === 'video' ? 'active' : ''} onClick={() => setConfigSection('video')}>Видео</button>
      <button className={configSection === 'text' ? 'active' : ''} onClick={() => setConfigSection('text')}>Текст</button>
    </div>

    {configSection === 'text' && <section className="server-layout">
      <article className="card">
        <div className="card-head"><div><h2 className="card-title">Локальная текстовая модель</h2><p className="card-note">Пользователь видит название «ИЗО Чат», техническая модель работает через Ollama на RTX 4070.</p></div></div>
        {!assistantData ? <p className="hint">Загружаем состояние Ollama…</p> : <div className="assistant-form">
          <div className="assistant-summary">
            <div><span>Ollama</span><strong>{assistantData.ollama.ok ? 'работает' : 'не отвечает'}</strong><small>{assistantData.ollama.baseUrl}</small></div>
            <div><span>Модель в памяти</span><strong>{assistantData.ollamaResidency.models.some((m) => (m.name || m.model) === assistantData.config.chat.localModel) ? 'да' : 'нет'}</strong><small>{assistantData.config.chat.localModel}</small></div>
            <div><span>Тариф</span><strong>Бесплатно</strong><small>Базовый локальный чат не расходует дневные и основные токены.</small></div>
          </div>
          <div className="two-col">
            <div className="field"><label>Название для пользователя</label><input value={assistantData.config.chat.localLabel} onChange={(e) => updateAssistantConfig({ ...assistantData.config, chat: { ...assistantData.config.chat, localLabel: e.target.value } })} /></div>
            <div className="field"><label>Техническая модель Ollama</label><select value={assistantData.config.chat.localModel} onChange={(e) => updateAssistantConfig({ ...assistantData.config, chat: { ...assistantData.config.chat, localModel: e.target.value } })}>{assistantData.ollama.models.filter((m) => m.name && !(m.name || '').endsWith(':cloud')).map((m) => <option key={m.name} value={m.name}>{m.name}</option>)}</select></div>
            <div className="field"><label>Цена базового ответа</label><input type="text" value="Бесплатно" disabled /></div>
            <div className="field"><label>Таймаут, секунд</label><input type="number" min="10" max="180" value={assistantData.config.chat.localTimeoutSeconds} onChange={(e) => updateAssistantConfig({ ...assistantData.config, chat: { ...assistantData.config.chat, localTimeoutSeconds: Number(e.target.value) } })} /></div>
            <div className="field"><label>История диалога, символов</label><input type="number" min="4000" max="240000" step="1000" value={assistantData.config.chat.contextChars} onChange={(e) => updateAssistantConfig({ ...assistantData.config, chat: { ...assistantData.config.chat, contextChars: Number(e.target.value) } })} /><small>60 000 символов — примерно 15 000 токенов текста.</small></div>
            <div className="field"><label>Контекст Ollama, токенов</label><input type="number" min="4096" max="65536" step="1024" value={assistantData.config.chat.localNumCtx} onChange={(e) => updateAssistantConfig({ ...assistantData.config, chat: { ...assistantData.config.chat, localNumCtx: Number(e.target.value) } })} /><small>Используйте общий контекст. Требуется запас памяти.</small></div>
          </div>
          <label className="resolution-plan"><input type="checkbox" checked={assistantData.config.chat.enabled && assistantData.config.chat.localEnabled} onChange={(e) => updateAssistantConfig({ ...assistantData.config, chat: { ...assistantData.config.chat, enabled: e.target.checked, localEnabled: e.target.checked } })} /><span>Доступна пользователям в чате</span></label>
          <button className="primary" disabled={assistantBusy} onClick={() => void saveAssistantConfig()}>{assistantBusy ? 'Сохраняю…' : 'Сохранить текстовую модель'}</button>
        </div>}
      </article>
    </section>}

    {configSection === 'video' && <section className="server-layout">
      <article className="card">
        <div className="card-head">
          <div><h2 className="card-title">Локальная видеогенерация</h2><p className="card-note">Отдельный ComfyUI на RTX 4070; RTX 3090 остаётся только для изображений.</p></div>
          <label className="resolution-plan">
            <input type="checkbox" checked={configRuntime.videoEnabled} onChange={(e) => void saveConfigRuntime({ ...configRuntime, videoEnabled: e.target.checked })} />
            <span>{configRuntime.videoEnabled ? 'включена' : 'отключена'}</span>
          </label>
        </div>
        <div className="server-overview">
          <div className="server-metric"><span>Видеосервис</span><strong style={{ color: statusColor(configStatus?.video?.ready) }}>{configStatus?.video?.ready ? 'Готов' : 'Недоступен'}</strong><small>{configStatus?.video?.base_url || '127.0.0.1:8190'}</small></div>
          <div className="server-metric"><span>Видеокарта</span><strong>{configStatus?.video?.gpu || 'проверка'}</strong><small>выделенная RTX 4070</small></div>
          <div className="server-metric"><span>Форматы</span><strong>{(configStatus?.video?.aspect_ratios || ['16:9', '9:16', '1:1']).join(' · ')}</strong><small>{configStatus?.video?.resolution || '480p'}</small></div>
          <div className="server-metric"><span>Активные видео</span><strong>{configStatus?.video?.active_jobs?.length ?? 0}</strong><small>одна последовательная очередь</small></div>
        </div>
        <div className="profile-switch" aria-label="Технический профиль локальной видеомодели">
          {(configStatus?.video?.profiles || [
            { id: 'local/ltx-2.3-fast-q3', label: 'Q3 — быстрее' },
            { id: 'local/ltx-2.3-standard-q4', label: 'Q4 — качественнее' },
          ]).map((profile) => <button
            key={profile.id}
            disabled={opsBusy || Boolean(configStatus?.video?.active_jobs?.length)}
            className={configRuntime.videoProfile === profile.id ? 'active' : ''}
            onClick={() => void saveConfigRuntime({ ...configRuntime, videoProfile: profile.id })}
          >{profile.label}</button>)}
        </div>
        {(configStatus?.video?.active_jobs || []).map((job) => <div className="job-row" key={job.id}><strong>{job.id}</strong><span>{job.status}</span><span>{job.progress ?? 0}%</span><small>{job.created_at}</small></div>)}
        <div className="dependency-note">
          <div><strong>ИЗО База</strong><span>Пользователь видит одну базовую модель. Здесь администратор выбирает её технический профиль Q3 или Q4 для следующих заданий.</span></div>
          <div><strong>Память</strong><span>RTX 4070 работает в low-VRAM режиме и при необходимости переносит веса в оперативную память.</span></div>
        </div>
      </article>
    </section>}

    {configSection === 'image' && <>
    <section className="server-command">
      <div className="server-title">
        <h2>Config UI</h2>
        <p>Управление локальным генератором, глобальной моделью и LoRA</p>
      </div>
      <label className="resolution-plan">
        <input type="checkbox" checked={configRuntime.imageEnabled} onChange={(e) => void saveConfigRuntime({ ...configRuntime, imageEnabled: e.target.checked })} />
        <span>{configRuntime.imageEnabled ? 'изображения включены' : 'изображения отключены'}</span>
      </label>
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
      <div className="card-head"><div><h2 className="card-title">Разрешения и настройки Config UI</h2><p className="card-note">SD, HD и Full HD доступны для Klein 9B/4B. Галочки определяют доступность разрешений по тарифам.</p></div><button className="primary" onClick={() => void saveConfigUiSettings()}>Сохранить параметры</button></div>
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
    </>}

    {pageTab === 'api' && <>
      {!embeddedInSidebar && <>
        <nav className="openrouter-page-nav" aria-label="Разделы OpenRouter">
          {ADMIN_OPENROUTER_PAGES.map((page) => <button key={page.id} type="button" className={openrouterPage === page.id ? 'active' : ''} onClick={() => navigateOpenRouterPage(page.id)}>{page.label}</button>)}
        </nav>
        {(() => { const page = ADMIN_OPENROUTER_PAGES.find((item) => item.id === openrouterPage) || ADMIN_OPENROUTER_PAGES[0]; return <header className="openrouter-page-title"><div><h2>{page.title}</h2><p>{page.description}</p></div></header> })()}
      </>}
      {openrouterPage === 'settings' && <div className="or-stats">
        <div className={`or-stat ${generationStatusClass}`}><span>Доступность генерации</span><strong>{generationStatusText}</strong></div>
        <div className="or-stat"><span>Сгенерировано картинок</span><strong>{data.openrouter.usage?.pricedImages || 0}</strong></div>
        <div className="or-stat"><span>Потрачено всего</span><strong>{totalSpentPair}</strong></div>
        <div className="or-stat"><span>Списано токенов</span><strong>{spentTokensText}</strong></div>
        <div className="or-stat"><span>Средняя за картинку</span><strong>{avgImagePair}</strong></div>
        <div className="or-stat"><span>Справка 1MP</span><strong>{avgMpPair}</strong></div>
        <div className="or-stat"><span>Фаворит по генерациям</span><strong>{favoriteOverallName}</strong></div>
        <div className={`or-stat ${data.openrouter.usage?.shadowEconomics?.alert ? 'risk-high' : ''}`}><span>Теневая экономика картинок</span><strong>{data.openrouter.usage?.shadowEconomics?.priced || 0} с фактом · {data.openrouter.usage?.shadowEconomics?.underquoted || 0} недооценено</strong></div>
        <div className={`or-stat ${data.openrouter.videoUsage?.shadowEconomics?.alert ? 'risk-high' : ''}`}><span>Теневая экономика видео</span><strong>{data.openrouter.videoUsage?.shadowEconomics?.priced || 0} с фактом · {data.openrouter.videoUsage?.shadowEconomics?.belowMinimumMargin || 0} ниже маржи</strong></div>
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
      </div>}

      {(['text', 'images', 'video'] as AdminOpenRouterPage[]).includes(openrouterPage) && <><div className="toolbar">
        <input
          type="search"
          name="openrouter-model-catalog-filter"
          autoComplete="off"
          data-lpignore="true"
          data-1p-ignore="true"
          spellCheck={false}
          placeholder="Поиск модели или провайдера"
          value={query}
          onChange={(e) => setQuery(e.target.value.includes('@') ? '' : e.target.value)}
        />
        <button className="ghost" onClick={() => setQuery('')}>Сбросить</button>
        <button className="ghost" disabled={openrouterCatalogBusy || data.openrouter.catalogState?.refreshing} onClick={() => { void refreshOpenrouterCatalog() }}>
          {openrouterCatalogBusy || data.openrouter.catalogState?.refreshing ? 'Обновляем каталог…' : 'Обновить каталог'}
        </button>
      </div>
      <p className="hint">
        Каталог: {data.openrouter.catalogState?.modelCount ?? liveCapabilityCatalog.length} моделей
        {' · '}источник {data.openrouter.catalogState?.source || 'резервный каталог'}
        {data.openrouter.catalogState?.lastSuccessAt ? ` · обновлён ${new Date(data.openrouter.catalogState.lastSuccessAt).toLocaleString('ru-RU')}` : ''}
        {typeof data.openrouter.catalogState?.cacheAgeSeconds === 'number' ? ` · возраст ${data.openrouter.catalogState.cacheAgeSeconds} сек.` : ''}
      </p>
      {!liveCapabilityCatalog.length ? <p className="hint" style={{ color: 'var(--yellow)' }}>Живой каталог возможностей пока не получен. Модели, цены и управление показаны из проверенного резервного каталога; перезапустите backend для автоматического обновления.</p> : null}
      {data.openrouter.capabilityError ? <p className="hint" style={{ color: 'var(--yellow)' }}>Каталог возможностей OpenRouter не загрузился: {data.openrouter.capabilityError}</p> : null}
      </>}
      {openrouterPage === 'text' && <article className="card video-catalog-card">
        <div className="video-catalog-head">
          <div className="video-catalog-title"><div><h2 className="card-title">Каталог текстовых моделей</h2><p className="card-note">Техническая цена провайдера за 1 млн токенов. Пользователь платит по фактическому объёму: сервер заранее резервирует максимум и возвращает неиспользованное. Ориентиры «около 1000 слов» и «1 млн русских символов» приблизительны и зависят от модели.</p></div></div>
          <div className="video-catalog-meta"><span className="state ok">{assistantData?.openrouterModels.length || 0} моделей</span><span className="state">{assistantData?.chatUsage?.priced || 0} ответов с фактом · среднее ${Number(assistantData?.chatUsage?.averageCostUsd || 0).toFixed(6)} · маржа {assistantData?.chatUsage?.marginPercent === null || assistantData?.chatUsage?.marginPercent === undefined ? '—' : `${assistantData.chatUsage.marginPercent.toFixed(1)}%`}</span></div>
        </div>
        {!assistantData ? <p className="hint">Загружаем текстовый каталог…</p> : <AdminTextModelCatalog
          models={filteredOpenrouterTextModels}
          publishedIds={assistantData.config.chat.publishedApiModels || assistantData.config.chat.enabledApiModels}
          tierAccess={assistantData.config.chat.apiTierAccess}
          defaultModel={assistantData.config.chat.defaultModel}
          usageByModel={assistantData.chatUsage?.perModel}
          busy={assistantBusy}
          onPublicationChange={(modelId, published) => {
            const currentPublished = assistantData.config.chat.publishedApiModels || assistantData.config.chat.enabledApiModels
            const publishedApiModels = published ? [...new Set([...currentPublished, modelId])] : currentPublished.filter((id) => id !== modelId)
            const enabledApiModels = [...publishedApiModels]
            const apiTierAccess = Object.fromEntries((['mini', 'plus', 'pro', 'business'] as TextTariff[]).map((plan) => [plan, published ? assistantData.config.chat.apiTierAccess?.[plan] || [] : (assistantData.config.chat.apiTierAccess?.[plan] || []).filter((id) => id !== modelId)]))
            const defaultModel = !published && assistantData.config.chat.defaultModel === modelId ? 'local:izo-chat' : assistantData.config.chat.defaultModel
            updateAssistantConfig({ ...assistantData.config, chat: { ...assistantData.config.chat, publishedApiModels, enabledApiModels, apiTierAccess, defaultModel } })
          }}
          onTierChange={(modelId, plan, checked) => {
            const current = assistantData.config.chat.apiTierAccess?.[plan] || []
            const next = checked ? [...new Set([...current, modelId])] : current.filter((id) => id !== modelId)
            updateAssistantConfig({ ...assistantData.config, chat: { ...assistantData.config.chat, apiTierAccess: { ...assistantData.config.chat.apiTierAccess, [plan]: next } } })
          }}
          onDefaultChange={(modelId) => updateAssistantConfig({ ...assistantData.config, chat: { ...assistantData.config.chat, defaultModel: modelId } })}
          onLocalDefault={() => updateAssistantConfig({ ...assistantData.config, chat: { ...assistantData.config.chat, defaultModel: 'local:izo-chat' } })}
          onSave={() => void saveAssistantConfig()}
        />}
      </article>}

      {openrouterPage === 'video' && <article className="card video-catalog-card">
        <div className="video-catalog-head">
          <div className="video-catalog-title">
            <span aria-hidden="true">▶</span>
            <div><h2 className="card-title">Видео OpenRouter</h2><p className="card-note">Модели, тарифный доступ и полная экономика каждого поддерживаемого варианта.</p></div>
          </div>
          <div className="video-catalog-meta"><span className="state ok">{data.openrouter.videoCatalog?.length || 0} моделей</span></div>
        </div>
        <div className="video-mode-list">
          <div className="video-economy-note">
            <strong>Формула продажи</strong>
            <span>Курс: {usdRubBase === null ? 'не загружен' : `${usdRubBase.toFixed(2)} ₽/$`} + {Math.round(USD_FEE_RATE * 100)}% резерв = {usdRubEffective === null ? '—' : `${usdRubEffective.toFixed(2)} ₽/$`}</span>
            <span>1 токен = {tokenRub.toFixed(2)} ₽ · минимальная маржа {minMarginPercent.toFixed(0)}%</span>
            <span>Токены округляются вверх так, чтобы фактическая маржа не опускалась ниже заданной.</span>
            <span>Теневой расчёт: {data.openrouter.videoUsage?.shadowEconomics?.priced || 0} операций с фактической ценой, {data.openrouter.videoUsage?.shadowEconomics?.missingActual || 0} ещё без факта{data.openrouter.videoUsage?.shadowEconomics?.alert ? ' · ВНИМАНИЕ: повторяется маржа ниже минимальной' : ''}.</span>
          </div>
          {data.openrouter.videoCatalogError ? <p className="hint" style={{ color: 'var(--yellow)' }}>Каталог видео не загрузился: {data.openrouter.videoCatalogError}</p> : null}
          {!data.openrouter.videoCatalogError && !data.openrouter.videoCatalog?.length ? <p className="hint">OpenRouter не вернул видеомодели. Обновите backend или проверьте доступ к API.</p> : null}
          {VIDEO_MODE_SECTIONS.map((section) => {
            const open = videoSectionsOpen[section.id] ?? false
            const mode = section.id as OpenRouterVideoMode
            const rows = (data.openrouter.videoCatalog || []).filter((model) => model.modes.includes(section.id)).filter((model) => {
              const hay = `${model.id} ${model.name} ${model.description} ${Object.keys(model.pricingSkus).join(' ')}`.toLowerCase()
              return !query || hay.includes(query.toLowerCase())
            })
            const publishedVideoIds = new Set(data.openrouter.videoConfig?.published || [])
            const rowIds = rows.map((model) => model.id)
            const allPublished = rowIds.length > 0 && rowIds.every((id) => publishedVideoIds.has(id))
            const billableIds = rows.filter((model) => publishedVideoIds.has(model.id) && videoPricingProfiles(model, mode).length > 0).map((model) => model.id)
            const enabledIds = billableIds.filter((id) => data.openrouter.videoConfig?.enabled?.[mode]?.includes(id))
            const allModelsEnabled = billableIds.length > 0 && enabledIds.length === billableIds.length
            const allTierChecked = (tier: OpenRouterTier) => enabledIds.length > 0 && enabledIds.every((id) => data.openrouter.videoConfig?.access?.[mode]?.[tier]?.includes(id))
            const modeStats = videoUsageModes.get(mode)
            const modeCount = typeof modeStats?.count === 'number' ? modeStats.count : 0
            const modeSpent = typeof modeStats?.costUsd === 'number' && Number(modeStats.costUsd) > 0 ? moneyPair(modeStats.costUsd, usdRubEffective) : '—'
            const modeAverage = typeof modeStats?.avgCostUsd === 'number' ? moneyPair(modeStats.avgCostUsd, usdRubEffective) : '—'
            return <section className="video-mode" key={section.id}>
              <button className="video-mode-toggle video-mode-finance-head" onClick={() => setVideoSectionsOpen((current) => ({ ...current, [section.id]: !open }))} aria-expanded={open}>
                <div><strong>{section.title}</strong><span>{section.note}</span></div>
                <div><span>Сген.</span><strong>{modeCount}</strong></div>
                <div><span>Среднее видео</span><strong>{modeAverage}</strong></div>
                <div><span>Потрачено</span><strong>{modeSpent}</strong></div>
                <div className="video-mode-count"><b>{rows.length} моделей</b><b>{enabledIds.length} включено</b></div>
              </button>
              {open && <div className="matrix-wrap video-finance-wrap">
                {!rows.length ? <p className="hint">Подходящих моделей в текущем каталоге нет.</p> : <table className="api-table video-finance-table">
                  <thead><tr>
                    <th>Дата выпуска</th>
                    <th className="api-enabled"><span className="api-column-label">Показ</span><input type="checkbox" checked={allPublished} disabled={!rowIds.length || videoConfigBusy} aria-label={`Показывать все модели ${section.title}`} onChange={(event) => toggleVideoPublicationSection(rowIds, event.target.checked)} /></th>
                    <th className="api-enabled"><span className="api-column-label">Режим</span><input type="checkbox" checked={allModelsEnabled} disabled={!billableIds.length || videoConfigBusy} aria-label={`Включить режим ${section.title} для всех моделей`} onChange={(event) => toggleVideoSection(mode, billableIds, event.target.checked)} /></th>
                    <th>Модель</th>
                    <th>Производитель</th>
                    <th><div className="tier-checks tier-head">{OPENROUTER_TIERS.map((tier) => <label key={tier.id} title={`Весь столбец ${tier.label}`}><input type="checkbox" checked={allTierChecked(tier.id)} disabled={!enabledIds.length || videoConfigBusy} onChange={(event) => toggleVideoTierColumn(mode, tier.id, enabledIds, event.target.checked)} /><span>{tier.label}</span></label>)}</div></th>
                    <th>Контрольный вариант<span>5 сек. · 1080p или ближайший</span></th>
                    <th>Себестоимость<span>рубли · доллары</span></th>
                    <th>Продажа<span>токены · выручка</span></th>
                    <th>Результат<span>прибыль · маржа</span></th>
                    <th>Сген.</th>
                    <th>Потрачено</th>
                    <th aria-label="Раскрыть"></th>
                  </tr></thead>
                  <tbody>{rows.map((model) => {
                  const rowKey = `${section.id}:${model.id}`
                  const expanded = videoExpandedRows[rowKey] || false
                  const profiles = videoPricingProfiles(model, mode)
                  const published = publishedVideoIds.has(model.id)
                  const enabled = published && (data.openrouter.videoConfig?.enabled?.[mode]?.includes(model.id) || false)
                  const scenario = videoRepresentativeScenario(model, mode)
                  const economics = scenario.seconds && scenario.profile ? videoEconomics(scenario.profile, scenario.seconds, usdRubEffective, minMarginPercent, tokenRub) : null
                  const stats = videoUsageModels.get(model.id)
                  const generated = typeof stats?.count === 'number' ? stats.count : 0
                  const spent = typeof stats?.costUsd === 'number' && Number(stats.costUsd) > 0 ? moneyPair(stats.costUsd, usdRubEffective) : '—'
                  const provider = model.id.split('/')[0] || 'OpenRouter'
                  return <Fragment key={rowKey}>
                    <tr className={`api-model-row ${expanded ? 'expanded' : ''} ${published ? '' : 'unpublished'}`} onClick={() => setVideoExpandedRows((current) => ({ ...current, [rowKey]: !expanded }))}>
                      <td data-label="Дата выпуска"><strong className="model-release">{model.created ? new Date(model.created * 1000).toLocaleDateString('ru-RU') : 'дата не указана'}</strong></td>
                      <td className="api-enabled" data-label="Показывать"><input type="checkbox" checked={published} disabled={videoConfigBusy} aria-label={`Публиковать ${model.name}`} onClick={(event) => event.stopPropagation()} onChange={(event) => toggleVideoPublished(model.id, event.target.checked)} /></td>
                      <td className="api-enabled" data-label="Режим"><input type="checkbox" checked={enabled} disabled={videoConfigBusy || !published || (!profiles.length && !enabled)} aria-label={`Включить ${model.name}`} onClick={(event) => event.stopPropagation()} onChange={(event) => toggleVideoModel(mode, model.id, event.target.checked)} /></td>
                      <td data-label="Модель"><strong className="model-name">{model.name}</strong><small className="model-id">{model.id}</small>{!profiles.length ? <span className="mini risk-high" style={{ marginLeft: 8 }}>нет цены</span> : null}</td>
                      <td data-label="Производитель"><span className="provider openrouter">{provider}</span></td>
                      <td data-label="Тарифы"><div className="tier-checks">{OPENROUTER_TIERS.map((tier) => <label key={tier.id}><input type="checkbox" disabled={videoConfigBusy || !enabled} checked={data.openrouter.videoConfig?.access?.[mode]?.[tier.id]?.includes(model.id) || false} onClick={(event) => event.stopPropagation()} onChange={(event) => toggleVideoTier(mode, tier.id, model.id, event.target.checked)} /><span>{tier.label}</span></label>)}</div></td>
                      <td data-label="Контрольный вариант"><div className="video-scenario"><strong>{scenario.seconds ? `${scenario.seconds} сек.` : '—'} · {scenario.resolution}</strong><span>{scenario.profile?.aspectRatio || model.supportedAspectRatios[0] || 'формат не указан'}</span></div></td>
                      <td data-label="Себестоимость"><div className="video-summary-econ"><strong>{economics?.costRub === null || economics?.costRub === undefined ? '—' : `${economics.costRub.toFixed(2)} ₽`}</strong><span>{economics ? `$${economics.costUsd.toFixed(4)}` : 'нет расчёта'}</span></div></td>
                      <td data-label="Продажа"><div className="video-summary-econ"><strong>{economics?.tokens ? `${economics.tokens} ток.` : '—'}</strong><span>{economics?.revenueRub === null || economics?.revenueRub === undefined ? '—' : `выручка ${economics.revenueRub.toFixed(2)} ₽`}</span></div></td>
                      <td data-label="Результат"><div className="video-summary-econ"><strong>{economics?.profitRub === null || economics?.profitRub === undefined ? '—' : `${economics.profitRub.toFixed(2)} ₽`}</strong><span className={economics?.marginPercent !== null && economics?.marginPercent !== undefined && economics.marginPercent < minMarginPercent ? 'risk-high' : 'risk-low'}>{economics?.marginPercent === null || economics?.marginPercent === undefined ? '—' : `маржа ${economics.marginPercent.toFixed(1)}%`}</span></div></td>
                      <td data-label="Сгенерировано">{generated}</td>
                      <td data-label="Потрачено"><span className="money">{spent}</span></td>
                      <td className="video-expand-cell"><button className="video-expand" onClick={(event) => { event.stopPropagation(); setVideoExpandedRows((current) => ({ ...current, [rowKey]: !expanded })) }} aria-label={expanded ? 'Свернуть модель' : 'Раскрыть модель'}>{expanded ? '−' : '+'}</button></td>
                    </tr>
                    {expanded && <tr><td className="detail-cell" colSpan={13}><div className="video-model-detail">
                      <div className="video-capabilities">
                        <span><b>OpenRouter id:</b> {model.id}</span>
                        <span><b>Соотношения:</b> {model.supportedAspectRatios.join(', ') || 'не опубликованы'}</span>
                        <span><b>Длительности:</b> {model.supportedDurations.join(', ') || 'не опубликованы'} сек.</span>
                        <span><b>Разрешения:</b> {model.supportedResolutions.join(', ') || 'не опубликованы'}</span>
                        <span><b>Кадры:</b> {model.supportedFrameImages.join(', ') || 'не принимает'}</span>
                        <span><b>Аудио:</b> {model.generateAudio === true ? 'генерирует' : model.generateAudio === false ? 'не генерирует' : 'OpenRouter не указал'}</span>
                        <span><b>Seed:</b> {model.seed === true ? 'поддерживается' : model.seed === false ? 'не поддерживается' : 'не указан'}</span>
                        <span><b>Сырые ставки:</b> {videoPriceLabel(model.pricingSkus)}</span>
                        <span><b>Факт по проекту:</b> {generated} видео · {spent}</span>
                      </div>
                      {profiles.length ? <div className="video-economics-wrap"><table className="video-economics-table">
                        <thead><tr><th>Разрешение и расчет</th>{model.supportedDurations.map((seconds) => <th key={seconds}>{seconds} сек.</th>)}</tr></thead>
                        <tbody>{profiles.map((profile) => <tr key={profile.id}>
                          <th><strong>{profile.label}</strong><small>{profile.unit === 'second' ? `$${profile.rateUsd.toFixed(4)}/сек.` : `$${profile.rateUsd.toFixed(7)}/видеотокен`}{profile.inputFeeUsd ? ` + $${profile.inputFeeUsd.toFixed(3)} вход` : ''}</small></th>
                          {model.supportedDurations.map((seconds) => {
                            const cell = videoEconomics(profile, seconds, usdRubEffective, minMarginPercent, tokenRub)
                            return <td key={seconds}>{cell ? <div className="video-economics-cell">
                              <strong>{cell.tokens === null ? '—' : `${cell.tokens} ток.`}</strong>
                              <span>себест. {cell.costRub === null ? '—' : `${cell.costRub.toFixed(2)} ₽`} · ${cell.costUsd.toFixed(4)}</span>
                              <span>выручка {cell.revenueRub === null ? '—' : `${cell.revenueRub.toFixed(2)} ₽`}</span>
                              <span>прибыль {cell.profitRub === null ? '—' : `${cell.profitRub.toFixed(2)} ₽`} · {cell.marginPercent === null ? '—' : `${cell.marginPercent.toFixed(1)}%`}</span>
                            </div> : '—'}</td>
                          })}
                        </tr>)}</tbody>
                      </table></div> : <p className="hint">OpenRouter не опубликовал достаточно данных для предварительного расчета. Включать модель в тариф до живого платного теста нельзя.</p>}
                      {section.id === 'reference_to_video' ? <span className="video-evidence"><b>Достоверность:</b> режим определен по описанию модели, до подключения нужен живой тест запроса.</span> : null}
                      {model.description ? <details><summary>Описание OpenRouter</summary><p>{model.description}</p></details> : null}
                    </div></td></tr>}
                  </Fragment>
                })}</tbody></table>}
              </div>}
            </section>
          })}
          <p className="hint">Источник: {data.openrouter.videoCatalogSource || 'OpenRouter video models API'}. Список обновляется вместе с кешем каталога моделей.</p>
        </div>
      </article>}

      {openrouterPage === 'images' && <article className="card video-catalog-card">
        <div className="video-catalog-head">
          <div className="video-catalog-title"><div><h2 className="card-title">Каталог моделей изображений</h2><p className="card-note">Публикация управляет показом пользователям; операция и тарифы задаются отдельно.</p></div></div>
          <div className="video-catalog-meta"><span className="state ok">{capabilityModels.length} моделей</span><span className="state ok">{publishedModelIds.size} опубликовано</span></div>
        </div>
      </article>}

      {openrouterPage === 'images' && API_MODE_SECTIONS.map((section) => {
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
        const billableIds = rows.filter((m) => backendPricingMap.has(m.id) && publishedModelIds.has(m.id)).map((m) => m.id)
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
                <th>Дата выпуска</th>
                <th className="api-enabled" title="Глобальная публикация: выключенная модель нигде не видна пользователям">Показ</th>
                <th className="api-enabled">
                  <span className="api-column-label" title="Разрешение модели для этой операции">Режим</span>
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
                const published = publishedModelIds.has(m.id)
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
                  <tr className={`api-model-row ${expanded ? 'expanded' : ''}${published ? '' : ' unpublished'}`} onClick={() => setApiExpandedRows((prev) => ({ ...prev, [rowKey]: !expanded }))}>
                    <td><strong className="model-release">{modelReleaseLabel(m.created)}</strong></td>
                    <td className="api-enabled">
                      <input
                        type="checkbox"
                        checked={published}
                        disabled={!canBill && !published}
                        aria-label={`Опубликовать ${modelShortName(m)} для пользователей`}
                        onClick={(e) => e.stopPropagation()}
                        onChange={(e) => toggleOpenrouterPublished(m.id, e.target.checked)}
                      />
                    </td>
                    <td className="api-enabled">
                      <input
                        type="checkbox"
                        checked={enabled}
                        disabled={!published || (!canBill && !enabled)}
                        aria-label={`Включить ${modelShortName(m)} для ${section.title}`}
                        onClick={(e) => e.stopPropagation()}
                        onChange={(e) => toggleOpenrouterModel(section.id, m.id, e.target.checked)}
                      />
                    </td>
                    <td><strong className="model-name">{modelShortName(m)}</strong><small className="model-id">{m.id}</small>{defaultForSection === m.id ? <span className="mini" style={{ marginLeft: 8 }}>по умолчанию</span> : null}{!published ? <span className="mini" style={{ marginLeft: 8 }}>скрыта</span> : null}{!canBill ? <span className="mini risk-high" style={{ marginLeft: 8 }}>нет backend цены</span> : null}<span className="mobile-image-economics">{tokenCount === null ? 'цена требует замера' : `${tokenCount} наших ток. · себестоимость ${rubText(costRub)} · выручка ${rubText(revenue)} · прибыль ${rubText(profit)} · маржа ${percentText(margin)}`}</span></td>
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
                    <td className="detail-cell" colSpan={12}>
                      <div className="detail-box">
                        <span><b>Полное имя:</b> {m.name}</span>
                        <span><b>Дата выпуска:</b> {modelReleaseLabel(m.created)}</span>
                        <span><b>Публикация:</b> {published ? 'видна пользователям в разрешённых операциях' : 'полностью скрыта от пользователей'}</span>
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

      {openrouterPage === 'audio' && (assistantData ? <OpenRouterAudioPage models={assistantData.openrouterAudioModels} error={assistantData.openrouterAudioModelsError} selectedModel={assistantData.config.voice.apiModel} usdRub={usdRubEffective} /> : <div className="models-page-loading">Загружаем каталог звуковых моделей…</div>)}
      {openrouterPage === '3d' && <OpenRouterThreeDPage />}

      {openrouterPage === 'settings' && <article className="card">
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
                <div className={`key-status-row ${generationStatusClass}`}><span>Фактическая доступность</span><strong>{generationStatusText}</strong></div>
                <div className="key-status-row"><span>Последний код генерации</span><strong>{valueText(orAvailability.lastStatusCode)}</strong></div>
                <div className="key-status-row"><span>Последний успешный запрос</span><strong>{valueText(orAvailability.lastSuccessAt)}</strong></div>
                <div className="key-status-row"><span>Последний сбой</span><strong>{valueText(orAvailability.lastFailureAt)}</strong></div>
                <div className="key-status-row key-warn"><span>Расчёт Credits API</span><strong>{calculatedCreditsBalance !== null ? moneyPair(calculatedCreditsBalance, usdRubEffective) : '—'} · не является подтверждением доступных средств</strong></div>
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
      </article>}
    </>}
  </div>
}
