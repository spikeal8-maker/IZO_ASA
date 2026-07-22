// ARCH-FE-STUDIO-001A: TypeScript types/interfaces extracted from newUi.tsx.
// Pure type declarations only — no runtime code, no DOM. This module must not
// import newUi.tsx.
import type { EditSlot } from '../editPrompt'
import type { ModelModeKey, TariffModelDefaults } from '../profileSupport'
import type { ImageResolution } from '../resolutionPolicy'
import type { GalleryContractItem, GenerationContract } from '../runtimeContracts'

export type N2Tab = 'feed' | 'text' | 'i2i' | 'edit' | 'paint' | 'video'
// tabs — генератор/лента; gallery и profile — отдельные канонические страницы.
export type N2View = 'tabs' | 'profile'
export type StudioMode = 'text' | 'i2i' | 'edit' | 'paint'
export type CoreStudioMode = Exclude<StudioMode, 'paint'>
export type UploadTarget = { kind: 'i2i' } | { kind: 'edit'; index: number } | { kind: 'paint' } | { kind: 'paintSketch' }
export type InspectPreview = { url: string; title: string }
export type PreviewShape = 'square' | 'wide' | 'tall'
export type StudioPreviewState = {
  kind: 'empty' | 'inspect' | 'result' | 'history'
  url?: string
  sourceUrl?: string
  shape?: PreviewShape
  title?: string
  galleryId?: string
  promptOriginal?: string
  resultImageId?: string
  width?: number
  height?: number
  error?: boolean
}
export type ModelsPayload = { loras?: string[] }
export type LoraOption = { id: string; label: string; triggerWord: string; strength: number }
export type UserModelChoices = Partial<Record<ModelModeKey, Partial<TariffModelDefaults>>>
export type StudioModelSort = 'name-asc' | 'name-desc' | 'tokens-asc' | 'tokens-desc'
export type LastTextSubmit = { prompt: string; model: string; width: number; height: number }
export type LastI2ISubmit = LastTextSubmit & { source: string }
export type StudioDraft = {
  prompts?: Partial<Record<StudioMode, string>>
  styleId?: string
  resolutionId?: string
  quality?: string
  seed?: number
  strengthPct?: number
  sourceImage?: string
  editSlots?: EditSlot[]
  editFaceStrengthPct?: number
}

export type PublicModelFormatPricing = {
  id: string
  label: string
  short: string
  tokens?: number | null
  requestSize?: string
  billingWidth?: number
  billingHeight?: number
  supported?: boolean
}
export type PublicModelPricing = { id: string; label: string; formats: PublicModelFormatPricing[]; resolutions?: PublicModelFormatPricing[] }
export type PublicOpenRouterPricing = { models?: PublicModelPricing[] }
export type PublicFormatId = 'square' | 'portrait' | 'wide' | 'soft_wide'

export type N2Job = GenerationContract
export type N2GalleryImage = GalleryContractItem

export type UploadedSourceImage = {
  id: string
  thumbnailUrl: string
  width: number
  height: number
  roleLabel?: string
  createdAt?: string
}

export type GalleryPickerTab = 'generated' | 'uploaded'

export type FormatId = 'square' | 'vertical' | 'horizontal'

export interface ResolutionPreset extends ImageResolution {
  name: string
  quality: string
  kind: FormatId
}

export type FeedLang = 'ru' | 'en'
