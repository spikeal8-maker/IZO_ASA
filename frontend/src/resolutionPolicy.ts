export type ResolutionTier = 'sd' | 'hd' | 'full_hd' | 'four_k'
export type ResolutionFormat = 'square' | 'portrait' | 'wide' | 'photo'

export type ImageResolution = {
  id: string
  format: ResolutionFormat
  aspect: '1:1' | '9:16' | '16:9' | '3:2'
  formatLabel: string
  tier: ResolutionTier
  tierLabel: 'SD' | 'HD' | 'Full HD' | '4K'
  width: number
  height: number
  megapixels: number
}

const resolution = (
  id: string,
  format: ResolutionFormat,
  aspect: ImageResolution['aspect'],
  formatLabel: string,
  tier: ResolutionTier,
  tierLabel: ImageResolution['tierLabel'],
  width: number,
  height: number,
): ImageResolution => ({ id, format, aspect, formatLabel, tier, tierLabel, width, height, megapixels: Number(((width * height) / 1_000_000).toFixed(2)) })

export const IMAGE_RESOLUTIONS: ImageResolution[] = [
  resolution('sq-sd', 'square', '1:1', 'Квадрат', 'sd', 'SD', 704, 704),
  resolution('sq-hd', 'square', '1:1', 'Квадрат', 'hd', 'HD', 1024, 1024),
  resolution('sq-fhd', 'square', '1:1', 'Квадрат', 'full_hd', 'Full HD', 1408, 1408),
  resolution('sq-4k', 'square', '1:1', 'Квадрат', 'four_k', '4K', 4096, 4096),
  resolution('v-sd', 'portrait', '9:16', 'Вертикальное', 'sd', 'SD', 576, 1024),
  resolution('v-hd', 'portrait', '9:16', 'Вертикальное', 'hd', 'HD', 720, 1280),
  resolution('v-fhd', 'portrait', '9:16', 'Вертикальное', 'full_hd', 'Full HD', 1008, 1792),
  resolution('v-4k', 'portrait', '9:16', 'Вертикальное', 'four_k', '4K', 2160, 3840),
  resolution('h-sd', 'wide', '16:9', 'Широкое', 'sd', 'SD', 1024, 576),
  resolution('h-hd', 'wide', '16:9', 'Широкое', 'hd', 'HD', 1280, 720),
  resolution('h-fhd', 'wide', '16:9', 'Широкое', 'full_hd', 'Full HD', 1792, 1008),
  resolution('h-4k', 'wide', '16:9', 'Широкое', 'four_k', '4K', 3840, 2160),
  resolution('p-sd', 'photo', '3:2', 'Фото', 'sd', 'SD', 960, 640),
  resolution('p-hd', 'photo', '3:2', 'Фото', 'hd', 'HD', 1152, 768),
  resolution('p-fhd', 'photo', '3:2', 'Фото', 'full_hd', 'Full HD', 1728, 1152),
  resolution('p-4k', 'photo', '3:2', 'Фото', 'four_k', '4K', 4096, 2736),
]

export const RESOLUTION_BY_ID = Object.fromEntries(IMAGE_RESOLUTIONS.map((item) => [item.id, item])) as Record<string, ImageResolution>

const LEGACY_RESOLUTION_IDS: Record<string, string> = {
  'sq-1024': 'sq-hd',
  'h-1280': 'h-hd',
  'v-720': 'v-hd',
  'h-1536': 'p-hd',
  'v-1024': 'v-fhd',
  'h-1920': 'h-fhd',
  'v-1088': 'v-fhd',
}

export const normalizeResolutionId = (id: string) => LEGACY_RESOLUTION_IDS[id] || id

export function normalizeResolutionIds(value: unknown, fallback: string[] = []): string[] {
  const source = Array.isArray(value) ? value : fallback
  return Array.from(new Set(source.map((item) => normalizeResolutionId(String(item))).filter((id) => Boolean(RESOLUTION_BY_ID[id]))))
}

export const resolutionLabel = (item: ImageResolution) => `${item.tierLabel} · ${item.formatLabel} ${item.aspect} · ${item.width}×${item.height}`

export function closestResolution(format: ResolutionFormat, preferredTier: ResolutionTier = 'hd', allowedIds?: string[]): ImageResolution {
  const allowed = allowedIds?.length ? new Set(normalizeResolutionIds(allowedIds)) : null
  const candidates = IMAGE_RESOLUTIONS.filter((item) => item.format === format && (!allowed || allowed.has(item.id)))
  return candidates.find((item) => item.tier === preferredTier) || candidates[0] || RESOLUTION_BY_ID['sq-hd']
}

export const FORMAT_TO_PRICING_ID: Record<ResolutionFormat, 'square' | 'portrait' | 'wide' | 'soft_wide'> = {
  square: 'square',
  portrait: 'portrait',
  wide: 'wide',
  photo: 'soft_wide',
}
