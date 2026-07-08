export type TariffKey = 'free' | 'mini' | 'plus' | 'pro'
export type TariffConfig = Record<TariffKey, { daily_tokens: number; gallery_slots: number }>

export const tariffKeys: TariffKey[] = ['free', 'mini', 'plus', 'pro']

export const DEFAULT_TARIFFS: TariffConfig = {
  free: { daily_tokens: 10, gallery_slots: 20 },
  mini: { daily_tokens: 50, gallery_slots: 80 },
  plus: { daily_tokens: 100, gallery_slots: 200 },
  pro: { daily_tokens: 200, gallery_slots: 500 },
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
      daily_tokens: Number(source[key]?.daily_tokens ?? DEFAULT_TARIFFS[key].daily_tokens),
      gallery_slots: Number(source[key]?.gallery_slots ?? DEFAULT_TARIFFS[key].gallery_slots),
    }
    return acc
  }, { ...DEFAULT_TARIFFS } as TariffConfig)
}
