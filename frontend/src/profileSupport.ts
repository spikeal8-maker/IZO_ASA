export type TariffKey = 'free' | 'mini' | 'plus' | 'pro' | 'business'
export type QualityPreset = 'fast' | 'standard' | 'max'
export type ModelProvider = 'comfyui' | 'openrouter'
export type TariffModelDefaults = Record<QualityPreset, string>
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

export const tariffKeys: TariffKey[] = ['free', 'mini', 'plus', 'pro', 'business']
export const qualityPresets: QualityPreset[] = ['fast', 'standard', 'max']
export const qualityPresetLabels: Record<QualityPreset, string> = {
  fast: 'Быстро',
  standard: 'Стандарт',
  max: 'Максимум',
}
export const modelOptions: Array<{ id: string; label: string; provider: ModelProvider; modelProfile: string; tokenHint: number }> = [
  { id: 'server:local_flux_klein', label: 'Серверная модель ИЗО', provider: 'comfyui', modelProfile: 'local_flux_klein', tokenHint: 1 },
  { id: 'black-forest-labs/flux.2-klein-4b', label: 'FLUX.2 Klein 4B', provider: 'openrouter', modelProfile: 'black-forest-labs/flux.2-klein-4b', tokenHint: 1 },
  { id: 'black-forest-labs/flux.2-pro', label: 'FLUX.2 Pro', provider: 'openrouter', modelProfile: 'black-forest-labs/flux.2-pro', tokenHint: 2 },
  { id: 'black-forest-labs/flux.2-max', label: 'FLUX.2 Max', provider: 'openrouter', modelProfile: 'black-forest-labs/flux.2-max', tokenHint: 3 },
  { id: 'openai/gpt-image-1-mini', label: 'GPT Image Mini', provider: 'openrouter', modelProfile: 'openai/gpt-image-1-mini', tokenHint: 1 },
  { id: 'openai/gpt-image-1', label: 'GPT Image', provider: 'openrouter', modelProfile: 'openai/gpt-image-1', tokenHint: 2 },
  { id: 'recraft/recraft-v4.1', label: 'Recraft V4.1', provider: 'openrouter', modelProfile: 'recraft/recraft-v4.1', tokenHint: 1 },
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
  return modelOptions.find((item) => item.id === id) || modelOptions[0]
}
