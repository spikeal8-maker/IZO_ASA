export type TariffKey = 'free' | 'mini' | 'plus' | 'pro' | 'business'
export type TariffRule = {
  title: string
  note: string
  daily_tokens: number
  gallery_slots: number
  queue_label: string
  pro_mode_enabled: boolean
  allowed_resolutions: string[]
  video_enabled: boolean
  video_slots: number
}
export type TariffConfig = Record<TariffKey, TariffRule>

export const tariffKeys: TariffKey[] = ['free', 'mini', 'plus', 'pro', 'business']
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

export const DEFAULT_TARIFFS: TariffConfig = {
  free: { title: 'Free', note: 'Базовый доступ', daily_tokens: 10, gallery_slots: 20, queue_label: 'Обычная', pro_mode_enabled: false, allowed_resolutions: ['sq-1024'], video_enabled: false, video_slots: 0 },
  mini: { title: 'Mini', note: 'Оптимальный старт', daily_tokens: 50, gallery_slots: 80, queue_label: 'Обычная', pro_mode_enabled: false, allowed_resolutions: baseResolutions, video_enabled: false, video_slots: 0 },
  plus: { title: 'Plus', note: 'Больше возможностей', daily_tokens: 100, gallery_slots: 200, queue_label: 'Ускоренная', pro_mode_enabled: true, allowed_resolutions: [...baseResolutions, 'h-1536', 'v-1024'], video_enabled: false, video_slots: 0 },
  pro: { title: 'Pro', note: 'Видео и приоритет', daily_tokens: 200, gallery_slots: 500, queue_label: 'Приоритетная', pro_mode_enabled: true, allowed_resolutions: fullResolutions, video_enabled: true, video_slots: 10 },
  business: { title: 'Бизнес', note: 'Для команды и видео', daily_tokens: 500, gallery_slots: 500, queue_label: 'Бизнес', pro_mode_enabled: true, allowed_resolutions: fullResolutions, video_enabled: true, video_slots: 50 },
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
      daily_tokens: Number(source[key]?.daily_tokens ?? DEFAULT_TARIFFS[key].daily_tokens),
      gallery_slots: Number(source[key]?.gallery_slots ?? DEFAULT_TARIFFS[key].gallery_slots),
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
