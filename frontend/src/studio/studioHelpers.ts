// ARCH-FE-STUDIO-001A: shared data/presentation helpers, independent constants
// and localisation tables extracted from newUi.tsx. This module also owns the
// small random seed/request-id helpers; it does not access the DOM or import
// newUi.tsx.
import { EDIT_SLOT_COUNT, type EditSlot } from '../editPrompt'
import type { ModelModeKey, ModelOption } from '../profileSupport'
import type { PaintSubMode } from '../paintTypes'
import { FORMAT_TO_PRICING_ID, IMAGE_RESOLUTIONS } from '../resolutionPolicy'
import type {
  CoreStudioMode,
  FeedLang,
  LoraOption,
  N2GalleryImage,
  N2Tab,
  PreviewShape,
  PublicModelPricing,
  PublicOpenRouterPricing,
  ResolutionPreset,
  StudioMode,
  StudioPreviewState,
} from './studioTypes'

export function coreModeFromTab(tab: N2Tab): CoreStudioMode | null {
  if (tab === 'text' || tab === 'i2i' || tab === 'edit') return tab
  return null
}

export function modelModeFromStudio(mode: StudioMode, paintMode: PaintSubMode): ModelModeKey {
  if (mode === 'text') return 'text_to_image'
  if (mode === 'i2i') return 'image_to_image'
  if (mode === 'edit') return 'edit'
  if (paintMode === 'mask') return 'inpaint'
  if (paintMode === 'outpaint') return 'outpaint'
  if (paintMode === 'remove_bg') return 'remove_background'
  return 'paint'
}

export function emptyPreview(): StudioPreviewState {
  return { kind: 'empty' }
}

export function shapeFromSize(width?: number, height?: number): PreviewShape {
  if (!width || !height) return 'square'
  const ratio = width / height
  if (ratio > 1.18) return 'wide'
  if (ratio < 0.82) return 'tall'
  return 'square'
}

export function pricingMapFromPayload(payload: unknown): Record<string, PublicModelPricing> {
  const source = payload && typeof payload === 'object' ? payload as PublicOpenRouterPricing : {}
  const models = Array.isArray(source.models) ? source.models : []
  return models.reduce((acc, model) => {
    if (model?.id) acc[model.id] = { ...model, formats: Array.isArray(model.formats) ? model.formats : [] }
    return acc
  }, {} as Record<string, PublicModelPricing>)
}

export function formatPricingId(resolution: ResolutionPreset) {
  return FORMAT_TO_PRICING_ID[resolution.format]
}

export function formatName(formatId: string) {
  if (formatId === 'portrait') return '9:16'
  if (formatId === 'wide') return '16:9'
  if (formatId === 'soft_wide') return '3:2'
  return '1:1'
}

export function isRasterOpenRouterModel(model: ModelOption) {
  if (model.provider !== 'openrouter') return true
  return !/vector/i.test(model.id)
}

export const EMPTY_EDIT_SLOTS: EditSlot[] = Array.from({ length: EDIT_SLOT_COUNT }, () => ({ image: undefined, role: '', takeNote: '' }))

// Форма миниатюры истории по реальным размерам/соотношению; квадрат — фолбэк.
export function historyShape(item: N2GalleryImage): 'square' | 'tall' | 'wide' {
  if (item.width && item.height) {
    if (item.width === item.height) return 'square'
    return item.width > item.height ? 'wide' : 'tall'
  }
  if (item.aspectRatio) return feedShape(item.aspectRatio)
  return 'square'
}

export function historyAspectRatio(item: N2GalleryImage): string | undefined {
  if (item.width && item.height) return `${item.width} / ${item.height}`
  if (item.aspectRatio) {
    const parts = item.aspectRatio.split(':').map((x) => Number(x))
    if (parts.length === 2 && parts[0] > 0 && parts[1] > 0) return `${parts[0]} / ${parts[1]}`
  }
  return undefined
}

export const QUALITY: Array<{ id: string; label: string; steps: number }> = [
  { id: 'fast', label: 'Быстро', steps: 4 },
  { id: 'standard', label: 'Стандарт', steps: 6 },
  { id: 'max', label: 'Максимум', steps: 10 },
]

export const RESOLUTION_PRESETS: ResolutionPreset[] = IMAGE_RESOLUTIONS.map((item) => ({
  ...item,
  name: item.formatLabel,
  quality: item.tierLabel,
  kind: item.format === 'square' ? 'square' : item.format === 'portrait' ? 'vertical' : 'horizontal',
}))

export const DEFAULT_FACE_STRENGTH = 75
export const FALLBACK_LORA_OPTIONS: LoraOption[] = [
  { id: 'none', label: 'None', triggerWord: '', strength: 0 },
  { id: 'lora_arcane', label: 'arcane style · 0.8', triggerWord: 'arcane style', strength: 0.8 },
  { id: 'product_photo', label: 'product photo · 0.6', triggerWord: 'product photo', strength: 0.6 },
]

export function faceStrengthPrompt(value: number): string {
  if (value >= 85) return 'Face transfer strength: very strong. Prioritize the face identity from Image 2 clearly and recognizably while preserving the target scene from Image 1.'
  if (value >= 60) return 'Face transfer strength: strong. Transfer the face identity from Image 2, but keep lighting, pose, clothing, and background from Image 1 natural.'
  if (value >= 35) return 'Face transfer strength: balanced. Blend the face identity from Image 2 naturally with the head angle, lighting, and style of Image 1.'
  return 'Face transfer strength: subtle. Keep most of the original target face structure from Image 1 and add only a light resemblance from Image 2.'
}

// RU/EN тексты ленты. Главная кнопка по ТЗ: «Повторить» / "Recreate"
// (не Remix); в detail — «Сделать похожее» / "Make similar".
export const FEED_I18N: Record<FeedLang, Record<string, string>> = {
  ru: {
    feed: 'Лента',
    forYou: 'Для вас',
    fresh: 'Новое',
    top: 'Популярное',
    challenges: 'Челленджи',
    follows: 'Подписки',
    recreate: 'Ремикс',
    makeSimilar: 'Сделать ремикс',
    remixHint: 'Создать свою версию на основе этой работы',
    save: 'Сохранить',
    saved: 'Сохранено',
    useStyle: 'Взять стиль',
    publish: 'Опубликовать в ленту',
    like: 'Нравится',
    follow: 'Подписаться',
    followed: 'Вы подписаны',
    promptOpen: 'Промпт (открыт)',
    promptPartial: 'Промпт частично',
    promptHidden: 'Промпт скрыт автором',
    showFull: 'Показать полностью',
    collapse: 'Свернуть',
    emptyTitle: 'Лента пока пустая',
    emptyText: 'Публикации появятся здесь сразу после первого поста из Галереи.',
    notAuthTitle: 'Публикация доступна после входа',
    notAuthText: 'Смотреть ленту можно без аккаунта.',
    login: 'Войти',
    createImage: 'Создать изображение',
    errorTitle: 'Не удалось загрузить ленту',
    retry: 'Повторить попытку',
    generate: 'Сгенерировать',
    openGallery: 'Открыть галерею',
    soonTitle: 'Скоро',
    gallery: 'Галерея',
    profile: 'Профиль',
    myGallery: 'Моя галерея',
    myWorks: 'Мои публикации',
    useAsSource: 'Использовать как основу',
    download: 'Скачать',
    del: 'Удалить',
    signOut: 'Выйти',
    tokens: 'Тарифы',
    plan: 'Тариф',
    account: 'Аккаунт',
    language: 'Язык',
    galleryHint: 'Ваши генерации: открыть, использовать как основу или опубликовать в ленту.',
    galleryGuest: 'Лента открыта всем, личная галерея — после входа.',
    profileGuest: 'Войдите, чтобы увидеть профиль, баланс и свои работы.',
    deleteConfirm: 'Удалить изображение из галереи?',
    open: 'Открыть',
    role: 'Статус',
  },
  en: {
    feed: 'Feed',
    forYou: 'For you',
    fresh: 'New',
    top: 'Top',
    challenges: 'Challenges',
    follows: 'Following',
    recreate: 'Remix',
    makeSimilar: 'Remix this',
    remixHint: 'Create your own version from this image',
    save: 'Save',
    saved: 'Saved',
    useStyle: 'Use style',
    publish: 'Publish to feed',
    like: 'Like',
    follow: 'Follow',
    followed: 'Following',
    promptOpen: 'Prompt (open)',
    promptPartial: 'Prompt partially open',
    promptHidden: 'Prompt hidden by author',
    showFull: 'Show full',
    collapse: 'Collapse',
    emptyTitle: 'The feed is empty for now',
    emptyText: 'Posts will appear here after the first Gallery publication.',
    notAuthTitle: 'Sign in to publish',
    notAuthText: 'You can browse the feed without an account.',
    login: 'Sign in',
    createImage: 'Create image',
    errorTitle: 'Failed to load the feed',
    retry: 'Retry',
    generate: 'Generate',
    openGallery: 'Open gallery',
    soonTitle: 'Soon',
    gallery: 'Gallery',
    profile: 'Profile',
    myGallery: 'My gallery',
    myWorks: 'My posts',
    useAsSource: 'Use as source',
    download: 'Download',
    del: 'Delete',
    signOut: 'Sign out',
    tokens: 'Tariffs',
    plan: 'Plan',
    account: 'Account',
    language: 'Language',
    galleryHint: 'Your generations: open, use as a source or publish to the feed.',
    galleryGuest: 'The feed is public; your personal gallery needs sign-in.',
    profileGuest: 'Sign in to see your profile, balance and works.',
    deleteConfirm: 'Delete this image from the gallery?',
    open: 'Open',
    role: 'Status',
  },
}

// Форма карточки по соотношению сторон публикации.
export function feedShape(ratio: string): 'tall' | 'wide' | 'square' {
  const parts = ratio.split(':').map(Number)
  const w = parts[0]
  const h = parts[1]
  if (!w || !h || w === h) return 'square'
  return w > h ? 'wide' : 'tall'
}

export const JOB_ACTIVE = ['queued', 'running', 'uploading', 'sent_to_comfyui', 'sent_to_openrouter']

// Приписка стиля в промпте (По тексту). Через маркер её можно заменить при
// выборе другого стиля, не трогая пользовательский текст.
export const STYLE_PREFIX = '\n\nСтиль: '
export const I2I_STYLE_PREFIX = '\n\nСтиль преобразования: '
export const PROMPT_APPEND_PREFIX = '\n\n'

// Вне компонента: react-hooks/purity запрещает impure-вызовы в теле компонента.
export function randomOf<T>(items: T[]): T {
  return items[Math.floor(Math.random() * items.length)]
}

export function randomSeed(): number {
  return Math.floor(Math.random() * 999999999)
}

export function newClientRequestId(): string {
  return typeof crypto !== 'undefined' && crypto.randomUUID
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(36).slice(2)}`
}
