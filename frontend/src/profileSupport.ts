export type TariffKey = 'free' | 'mini' | 'plus' | 'pro' | 'business'
export type QualityPreset = 'fast' | 'standard' | 'max'
export type ModelProvider = 'comfyui' | 'openrouter'
export type TariffModelDefaults = Record<QualityPreset, string>
export type ModelModeKey = 'text_to_image' | 'image_to_image' | 'edit' | 'paint' | 'inpaint' | 'outpaint' | 'faceswap' | 'remove_background'
export type UserModelMode = {
  id: ModelModeKey
  label: string
  models: ModelOption[]
  presets: TariffModelDefaults
}
export type UserModelAccess = {
  plan: TariffKey
  modes: Partial<Record<ModelModeKey, UserModelMode>>
}
export type TariffRule = {
  title: string
  note: string
  price_rub_month: number
  daily_tokens: number
  openrouter_monthly_tokens: number
  gallery_slots: number
  quality_label: string
  model_defaults: TariffModelDefaults
  queue_label: string
  pro_mode_enabled: boolean
  allowed_resolutions: string[]
  video_enabled: boolean
  video_slots: number
}
export type TariffConfig = Record<TariffKey, TariffRule>
export type ModelOption = { id: string; label: string; provider: ModelProvider; modelProfile: string; tokenHint: number }

export const tariffKeys: TariffKey[] = ['free', 'mini', 'plus', 'pro', 'business']
export const qualityPresets: QualityPreset[] = ['fast', 'standard', 'max']
export const qualityPresetLabels: Record<QualityPreset, string> = {
  fast: 'Быстро',
  standard: 'Стандарт',
  max: 'Максимум',
}
export const modelModeOrder: ModelModeKey[] = ['text_to_image', 'image_to_image', 'edit', 'paint', 'inpaint', 'outpaint', 'faceswap', 'remove_background']
export const modelModeLabels: Record<ModelModeKey, string> = {
  text_to_image: 'Текст -> изображение',
  image_to_image: 'Изображение -> изображение',
  edit: 'Сборка / multi-reference',
  paint: 'Рисунок / sketch',
  inpaint: 'Редактор - маска / inpaint',
  outpaint: 'Редактор - расширение / outpaint',
  faceswap: 'Лицо / reference identity',
  remove_background: 'Удаление фона',
}
export const SERVER_MODEL_OPTION: ModelOption = { id: 'server:local_flux_klein', label: 'Серверная модель ИЗО', provider: 'comfyui', modelProfile: 'local_flux_klein', tokenHint: 1 }
export const modelOptions: ModelOption[] = [
  SERVER_MODEL_OPTION,
  { id: 'black-forest-labs/flux.2-klein-4b', label: 'FLUX.2 Klein 4B', provider: 'openrouter', modelProfile: 'black-forest-labs/flux.2-klein-4b', tokenHint: 1 },
  { id: 'black-forest-labs/flux.2-pro', label: 'FLUX.2 Pro', provider: 'openrouter', modelProfile: 'black-forest-labs/flux.2-pro', tokenHint: 2 },
  { id: 'black-forest-labs/flux.2-max', label: 'FLUX.2 Max', provider: 'openrouter', modelProfile: 'black-forest-labs/flux.2-max', tokenHint: 3 },
  { id: 'black-forest-labs/flux.2-flex', label: 'FLUX.2 Flex', provider: 'openrouter', modelProfile: 'black-forest-labs/flux.2-flex', tokenHint: 4 },
  { id: 'openai/gpt-image-1-mini', label: 'GPT Image Mini', provider: 'openrouter', modelProfile: 'openai/gpt-image-1-mini', tokenHint: 1 },
  { id: 'openai/gpt-5-image-mini', label: 'GPT-5 Image Mini', provider: 'openrouter', modelProfile: 'openai/gpt-5-image-mini', tokenHint: 1 },
  { id: 'openai/gpt-image-1', label: 'GPT Image', provider: 'openrouter', modelProfile: 'openai/gpt-image-1', tokenHint: 2 },
  { id: 'openai/gpt-5-image', label: 'GPT-5 Image', provider: 'openrouter', modelProfile: 'openai/gpt-5-image', tokenHint: 2 },
  { id: 'openai/gpt-image-2', label: 'GPT Image 2', provider: 'openrouter', modelProfile: 'openai/gpt-image-2', tokenHint: 1 },
  { id: 'openai/gpt-5.4-image-2', label: 'GPT-5.4 Image 2', provider: 'openrouter', modelProfile: 'openai/gpt-5.4-image-2', tokenHint: 1 },
  { id: 'google/gemini-3.1-flash-lite-image', label: 'Nano Banana 2 Lite', provider: 'openrouter', modelProfile: 'google/gemini-3.1-flash-lite-image', tokenHint: 1 },
  { id: 'google/gemini-3.1-flash-image', label: 'Nano Banana 2', provider: 'openrouter', modelProfile: 'google/gemini-3.1-flash-image', tokenHint: 2 },
  { id: 'google/gemini-3.1-flash-image-preview', label: 'Nano Banana 2 Preview', provider: 'openrouter', modelProfile: 'google/gemini-3.1-flash-image-preview', tokenHint: 2 },
  { id: 'google/gemini-3-pro-image', label: 'Nano Banana Pro', provider: 'openrouter', modelProfile: 'google/gemini-3-pro-image', tokenHint: 4 },
  { id: 'google/gemini-3-pro-image-preview', label: 'Nano Banana Pro Preview', provider: 'openrouter', modelProfile: 'google/gemini-3-pro-image-preview', tokenHint: 4 },
  { id: 'google/gemini-2.5-flash-image', label: 'Gemini 2.5 Flash Image', provider: 'openrouter', modelProfile: 'google/gemini-2.5-flash-image', tokenHint: 2 },
  { id: 'google/gemini-2.5-flash-image-preview', label: 'Gemini 2.5 Flash Image Preview', provider: 'openrouter', modelProfile: 'google/gemini-2.5-flash-image-preview', tokenHint: 2 },
  { id: 'microsoft/mai-image-2.5', label: 'MAI-Image-2.5', provider: 'openrouter', modelProfile: 'microsoft/mai-image-2.5', tokenHint: 2 },
  { id: 'x-ai/grok-imagine-image-quality', label: 'Grok Imagine Image Quality', provider: 'openrouter', modelProfile: 'x-ai/grok-imagine-image-quality', tokenHint: 3 },
  { id: 'recraft/recraft-v4.1', label: 'Recraft V4.1', provider: 'openrouter', modelProfile: 'recraft/recraft-v4.1', tokenHint: 1 },
  { id: 'recraft/recraft-v4.1-utility', label: 'Recraft V4.1 Utility', provider: 'openrouter', modelProfile: 'recraft/recraft-v4.1-utility', tokenHint: 1 },
  { id: 'recraft/recraft-v4.1-pro', label: 'Recraft V4.1 Pro', provider: 'openrouter', modelProfile: 'recraft/recraft-v4.1-pro', tokenHint: 6 },
  { id: 'recraft/recraft-v4.1-utility-pro', label: 'Recraft V4.1 Utility Pro', provider: 'openrouter', modelProfile: 'recraft/recraft-v4.1-utility-pro', tokenHint: 6 },
  { id: 'recraft/recraft-v4.1-vector', label: 'Recraft V4.1 Vector', provider: 'openrouter', modelProfile: 'recraft/recraft-v4.1-vector', tokenHint: 3 },
  { id: 'recraft/recraft-v4.1-pro-vector', label: 'Recraft V4.1 Pro Vector', provider: 'openrouter', modelProfile: 'recraft/recraft-v4.1-pro-vector', tokenHint: 8 },
  { id: 'recraft/recraft-v4', label: 'Recraft V4', provider: 'openrouter', modelProfile: 'recraft/recraft-v4', tokenHint: 1 },
  { id: 'recraft/recraft-v4-pro', label: 'Recraft V4 Pro', provider: 'openrouter', modelProfile: 'recraft/recraft-v4-pro', tokenHint: 7 },
  { id: 'recraft/recraft-v4-vector', label: 'Recraft V4 Vector', provider: 'openrouter', modelProfile: 'recraft/recraft-v4-vector', tokenHint: 3 },
  { id: 'recraft/recraft-v4-pro-vector', label: 'Recraft V4 Pro Vector', provider: 'openrouter', modelProfile: 'recraft/recraft-v4-pro-vector', tokenHint: 8 },
  { id: 'recraft/recraft-v3', label: 'Recraft V3', provider: 'openrouter', modelProfile: 'recraft/recraft-v3', tokenHint: 1 },
  { id: 'sourceful/riverflow-v2-fast', label: 'Riverflow V2 Fast', provider: 'openrouter', modelProfile: 'sourceful/riverflow-v2-fast', tokenHint: 1 },
  { id: 'sourceful/riverflow-v2-pro', label: 'Riverflow V2 Pro', provider: 'openrouter', modelProfile: 'sourceful/riverflow-v2-pro', tokenHint: 3 },
  { id: 'sourceful/riverflow-v2.5-fast', label: 'Riverflow V2.5 Fast', provider: 'openrouter', modelProfile: 'sourceful/riverflow-v2.5-fast', tokenHint: 1 },
  { id: 'sourceful/riverflow-v2.5-pro', label: 'Riverflow V2.5 Pro', provider: 'openrouter', modelProfile: 'sourceful/riverflow-v2.5-pro', tokenHint: 3 },
  { id: 'sourceful/riverflow-v2-fast-preview', label: 'Riverflow V2 Fast Preview', provider: 'openrouter', modelProfile: 'sourceful/riverflow-v2-fast-preview', tokenHint: 1 },
  { id: 'sourceful/riverflow-v2-standard-preview', label: 'Riverflow V2 Standard Preview', provider: 'openrouter', modelProfile: 'sourceful/riverflow-v2-standard-preview', tokenHint: 2 },
  { id: 'sourceful/riverflow-v2-max-preview', label: 'Riverflow V2 Max Preview', provider: 'openrouter', modelProfile: 'sourceful/riverflow-v2-max-preview', tokenHint: 3 },
  { id: 'bytedance-seed/seedream-4.5', label: 'Seedream 4.5', provider: 'openrouter', modelProfile: 'bytedance-seed/seedream-4.5', tokenHint: 1 },
  { id: 'openrouter/auto', label: 'Auto Router', provider: 'openrouter', modelProfile: 'openrouter/auto', tokenHint: 4 },
]
export const resolutionOptions = [
  { id: 'sq-1024', label: '1024×1024' },
  { id: 'h-1280', label: '1280×720' },
  { id: 'v-720', label: '720×1280' },
  { id: 'h-1536', label: '1536×1024' },
  { id: 'v-1024', label: '1024×1536' },
  { id: 'h-1920', label: '1920×1088' },
  { id: 'v-1088', label: '1088×1920' },
] as const

const baseResolutions = ['sq-1024', 'h-1280', 'v-720']
const fullResolutions = resolutionOptions.map((item) => item.id)
const serverDefaults: TariffModelDefaults = { fast: 'server:local_flux_klein', standard: 'server:local_flux_klein', max: 'server:local_flux_klein' }

export const DEFAULT_TARIFFS: TariffConfig = {
  free: { title: 'Free', note: 'Базовый доступ', price_rub_month: 0, daily_tokens: 10, openrouter_monthly_tokens: 0, gallery_slots: 20, quality_label: 'Базовое качество', model_defaults: serverDefaults, queue_label: 'Обычная', pro_mode_enabled: false, allowed_resolutions: ['sq-1024'], video_enabled: false, video_slots: 0 },
  mini: { title: 'Mini', note: 'Оптимальный старт', price_rub_month: 490, daily_tokens: 50, openrouter_monthly_tokens: 100, gallery_slots: 80, quality_label: 'HD', model_defaults: serverDefaults, queue_label: 'Обычная', pro_mode_enabled: false, allowed_resolutions: baseResolutions, video_enabled: false, video_slots: 0 },
  plus: { title: 'Plus', note: 'Больше возможностей', price_rub_month: 990, daily_tokens: 100, openrouter_monthly_tokens: 250, gallery_slots: 200, quality_label: 'Full HD', model_defaults: { fast: 'server:local_flux_klein', standard: 'black-forest-labs/flux.2-klein-4b', max: 'openai/gpt-image-1-mini' }, queue_label: 'Ускоренная', pro_mode_enabled: true, allowed_resolutions: [...baseResolutions, 'h-1536', 'v-1024'], video_enabled: false, video_slots: 0 },
  pro: { title: 'Pro', note: 'Видео и приоритет', price_rub_month: 1990, daily_tokens: 200, openrouter_monthly_tokens: 500, gallery_slots: 500, quality_label: '4K', model_defaults: { fast: 'server:local_flux_klein', standard: 'black-forest-labs/flux.2-klein-4b', max: 'black-forest-labs/flux.2-pro' }, queue_label: 'Приоритетная', pro_mode_enabled: true, allowed_resolutions: fullResolutions, video_enabled: true, video_slots: 10 },
  business: { title: 'Бизнес', note: 'Для команды и видео', price_rub_month: 4990, daily_tokens: 500, openrouter_monthly_tokens: 1200, gallery_slots: 500, quality_label: '4K', model_defaults: { fast: 'server:local_flux_klein', standard: 'black-forest-labs/flux.2-pro', max: 'openai/gpt-image-1' }, queue_label: 'Бизнес', pro_mode_enabled: true, allowed_resolutions: fullResolutions, video_enabled: true, video_slots: 50 },
}

export const AVATAR_PRESET_COUNT = 71

export const avatarPresets = Array.from({ length: AVATAR_PRESET_COUNT }, (_, index) => {
  const number = String(index + 1).padStart(3, '0')
  const id = `avatar-${number}`
  return { id, url: `/avatars/${id}.webp`, label: `Аватар ${index + 1}` }
})

export function normalizeTariffs(input: unknown): TariffConfig {
  const source = (input && typeof input === 'object' ? input : {}) as Partial<Record<TariffKey, Partial<TariffConfig[TariffKey]>>>
  return tariffKeys.reduce((acc, key) => {
    acc[key] = {
      title: String(source[key]?.title ?? DEFAULT_TARIFFS[key].title),
      note: String(source[key]?.note ?? DEFAULT_TARIFFS[key].note),
      price_rub_month: Number(source[key]?.price_rub_month ?? DEFAULT_TARIFFS[key].price_rub_month),
      daily_tokens: Number(source[key]?.daily_tokens ?? DEFAULT_TARIFFS[key].daily_tokens),
      openrouter_monthly_tokens: Number(source[key]?.openrouter_monthly_tokens ?? DEFAULT_TARIFFS[key].openrouter_monthly_tokens),
      gallery_slots: Number(source[key]?.gallery_slots ?? DEFAULT_TARIFFS[key].gallery_slots),
      quality_label: String(source[key]?.quality_label ?? DEFAULT_TARIFFS[key].quality_label),
      model_defaults: qualityPresets.reduce((defaults, preset) => {
        const raw = source[key]?.model_defaults?.[preset]
        defaults[preset] = modelOptions.some((item) => item.id === raw) ? String(raw) : DEFAULT_TARIFFS[key].model_defaults[preset]
        return defaults
      }, { ...DEFAULT_TARIFFS[key].model_defaults } as TariffModelDefaults),
      queue_label: String(source[key]?.queue_label ?? DEFAULT_TARIFFS[key].queue_label),
      pro_mode_enabled: Boolean(source[key]?.pro_mode_enabled ?? DEFAULT_TARIFFS[key].pro_mode_enabled),
      allowed_resolutions: Array.isArray(source[key]?.allowed_resolutions) && source[key]?.allowed_resolutions?.length
        ? source[key]!.allowed_resolutions!.map(String)
        : DEFAULT_TARIFFS[key].allowed_resolutions,
      video_enabled: Boolean(source[key]?.video_enabled ?? DEFAULT_TARIFFS[key].video_enabled),
      video_slots: Number(source[key]?.video_slots ?? DEFAULT_TARIFFS[key].video_slots),
    }
    return acc
  }, { ...DEFAULT_TARIFFS } as TariffConfig)
}

export function modelOptionById(id: string) {
  const known = modelOptions.find((item) => item.id === id)
  if (known) return known
  if (id.includes('/')) {
    const short = id.split('/').pop() || id
    return { id, label: short.replace(/[-_]/g, ' ').replace(/\b\w/g, (char) => char.toUpperCase()), provider: 'openrouter' as const, modelProfile: id, tokenHint: 1 }
  }
  return SERVER_MODEL_OPTION
}

export function normalizeModelAccess(input: unknown, fallbackPlan: TariffKey = 'mini'): UserModelAccess {
  const source = (input && typeof input === 'object' ? input : {}) as Partial<UserModelAccess>
  const plan = tariffKeys.includes(source.plan as TariffKey) ? source.plan as TariffKey : fallbackPlan
  const modes = modelModeOrder.reduce((acc, mode) => {
    const raw = source.modes?.[mode]
    const rawModels = Array.isArray(raw?.models) ? raw.models : [SERVER_MODEL_OPTION]
    const models = rawModels.map((item) => modelOptionById(String(item.id || item.modelProfile || SERVER_MODEL_OPTION.id)))
    const unique = Array.from(new Map([SERVER_MODEL_OPTION, ...models].map((item) => [item.id, item])).values())
    const rawPresets = (raw?.presets || {}) as Partial<TariffModelDefaults>
    const presets = qualityPresets.reduce((presetAcc, preset) => {
      const value = String(rawPresets[preset] || SERVER_MODEL_OPTION.id)
      presetAcc[preset] = unique.some((item) => item.id === value) ? value : SERVER_MODEL_OPTION.id
      return presetAcc
    }, { ...serverDefaults } as TariffModelDefaults)
    acc[mode] = { id: mode, label: raw?.label || modelModeLabels[mode], models: unique, presets }
    return acc
  }, {} as Record<ModelModeKey, UserModelMode>)
  return { plan, modes }
}

export function modelAccessOption(access: UserModelAccess | null | undefined, mode: ModelModeKey, preset: QualityPreset, userChoices?: Partial<Record<ModelModeKey, Partial<TariffModelDefaults>>>) {
  const modeAccess = access?.modes?.[mode]
  const models = modeAccess?.models?.length ? modeAccess.models : [SERVER_MODEL_OPTION]
  const chosen = userChoices?.[mode]?.[preset]
  const presetId = chosen && models.some((item) => item.id === chosen) ? chosen : modeAccess?.presets?.[preset]
  return models.find((item) => item.id === presetId) || models[0] || SERVER_MODEL_OPTION
}
