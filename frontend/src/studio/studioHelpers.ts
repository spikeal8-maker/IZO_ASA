// ARCH-FE-STUDIO-001A: pure data-transformation helpers, independent constants
// and localisation tables extracted from newUi.tsx. No app DOM structure is
// touched (off-screen canvases used for image processing only). This module
// must not import newUi.tsx.
import { EDIT_SLOT_COUNT, type EditSlot } from '../editPrompt'
import type { ModelModeKey, ModelOption } from '../profileSupport'
import type { PaintLine, PaintOutpaintPlacement, PaintSubMode } from '../paintTypes'
import { FORMAT_TO_PRICING_ID, IMAGE_RESOLUTIONS } from '../resolutionPolicy'
import { currentSeoLocale, type SeoMeta } from '../seo'
import { apiUrl } from './studioApi'
import type {
  CoreStudioMode,
  FeedLang,
  LoraOption,
  N2GalleryImage,
  N2Tab,
  N2View,
  PreviewShape,
  PublicModelPricing,
  PublicOpenRouterPricing,
  ResolutionPreset,
  StudioDraft,
  StudioMode,
  StudioPreviewState,
} from './studioTypes'

export const STUDIO_DRAFT_KEY = 'izo:studio-draft-v1'

export function readStudioDraft(): StudioDraft {
  try {
    const value = window.sessionStorage.getItem(STUDIO_DRAFT_KEY)
    return value ? JSON.parse(value) as StudioDraft : {}
  } catch {
    return {}
  }
}

export function writeStudioDraft(draft: StudioDraft): void {
  try {
    window.sessionStorage.setItem(STUDIO_DRAFT_KEY, JSON.stringify(draft))
  } catch {
    const lightweight = {
      ...draft,
      sourceImage: draft.sourceImage?.startsWith('data:') ? undefined : draft.sourceImage,
      editSlots: draft.editSlots?.map((slot) => ({
        ...slot,
        image: slot.image?.startsWith('data:') ? undefined : slot.image,
      })),
    }
    try {
      window.sessionStorage.setItem(STUDIO_DRAFT_KEY, JSON.stringify(lightweight))
    } catch {
      // Storage may be disabled; generation remains usable without recovery.
    }
  }
}

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

export function loadImageShape(url: string): Promise<PreviewShape> {
  return new Promise((resolve) => {
    const img = new Image()
    img.onload = () => resolve(shapeFromSize(img.naturalWidth, img.naturalHeight))
    img.onerror = () => resolve('square')
    img.src = apiUrl(url)
  })
}

export const EMPTY_EDIT_SLOTS: EditSlot[] = Array.from({ length: EDIT_SLOT_COUNT }, () => ({ image: undefined, role: '', takeNote: '' }))
export const DEFAULT_PAINT_SKETCH_PROMPT = 'Transform this sketch into a hyper-realistic cinematic scene. Interpret the lines as real-world objects with high-quality textures, cinematic lighting, natural shadows, depth, realistic materials and clean composition. Preserve the exact composition, silhouettes, poses, proportions and spatial relationships from the sketch. Scene description:'
export const DEFAULT_PAINT_MASK_PROMPT = 'Edit only the masked area and follow the user instruction literally for that selected region. Seamlessly blend the change with the surrounding scene while preserving lighting, shadows, perspective, depth of field and photo grain. Do not change unmasked areas.'
export const DEFAULT_PAINT_OUTPAINT_PROMPT = 'Extend the composition of this image. Replace black or empty spaces with a logical continuation of the background and foreground. Match perspective, lighting, color palette and texture so the transition is invisible. Scene description:'

// Начальное состояние из URL. Статические /feed и /gallery отдаются backend,
// а hash-ссылки из этих страниц возвращают пользователя в нужный режим UI 2.0.
export function initialViewFromPath(): { view: N2View; tab: N2Tab } {
  const p = typeof window !== 'undefined' ? window.location.pathname : '/feed'
  const h = typeof window !== 'undefined' ? window.location.hash : ''
  if (p === '/gallery' || p.startsWith('/gallery') || p.startsWith('/new/gallery')) return { view: 'tabs', tab: 'text' }
  if (p === '/profile' || p.startsWith('/profile') || p.startsWith('/new/profile')) return { view: 'profile', tab: 'feed' }
  if (h === '#image-to-image') return { view: 'tabs', tab: 'i2i' }
  if (h === '#editor') return { view: 'tabs', tab: 'edit' }
  if (h === '#face' || h === '#face-to-image') return { view: 'tabs', tab: 'edit' }
  if (h === '#draw' || h === '#drawing' || h === '#paint') return { view: 'tabs', tab: 'paint' }
  if (h === '#video') return { view: 'tabs', tab: 'video' }
  if (h === '#text-to-image') return { view: 'tabs', tab: 'text' }
  if (p === '/paint' || p.startsWith('/paint/') || p === '/new/paint' || p.startsWith('/new/paint/')) return { view: 'tabs', tab: 'paint' }
  if (p === '/video' || p.startsWith('/video/') || p === '/new/video' || p.startsWith('/new/video/')) return { view: 'tabs', tab: 'video' }
  // /feed is owned by backend/static/feed/index.html. If the SPA is ever served
  // for that path by a stale build or broken proxy, do not revive the old React feed.
  return { view: 'tabs', tab: 'text' }
}

export function initialProfileTabFromPath(): 'profile' | 'tariffs' | 'earn' | 'models' {
  const path = typeof window !== 'undefined' ? window.location.pathname.replace(/\/+$/, '') : '/profile'
  const segment = path.split('/').filter(Boolean).at(-1)
  if (segment === 'tariffs' || segment === 'earn' || segment === 'models') return segment
  return 'profile'
}

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

export function fitGenerationDimension(value: number) {
  return Math.max(512, Math.min(1536, Math.round(value / 16) * 16))
}

export function comfySafeGenerationSize(size: { width: number; height: number }) {
  const width = Math.max(512, size.width)
  const height = Math.max(512, size.height)
  const maxPixels = 2_050_000
  const maxSide = 1792
  const scale = Math.min(1, maxSide / Math.max(width, height), Math.sqrt(maxPixels / Math.max(1, width * height)))
  return {
    width: Math.max(512, Math.round((width * scale) / 16) * 16),
    height: Math.max(512, Math.round((height * scale) / 16) * 16),
  }
}

export function sameGenerationSize(a: { width: number; height: number }, b: { width: number; height: number }) {
  return a.width === b.width && a.height === b.height
}

export async function resizeUploadImage(file: File): Promise<string> {
  const sourceUrl = URL.createObjectURL(file)
  try {
    const image = await new Promise<HTMLImageElement>((resolve, reject) => {
      const img = new Image()
      img.onload = () => resolve(img)
      img.onerror = reject
      img.src = sourceUrl
    })
    const maxSide = Math.max(image.naturalWidth || image.width, image.naturalHeight || image.height)
    const scale = Math.min(1, 1536 / Math.max(1, maxSide))
    const width = Math.max(16, Math.round(((image.naturalWidth || image.width) * scale) / 16) * 16)
    const height = Math.max(16, Math.round(((image.naturalHeight || image.height) * scale) / 16) * 16)
    const canvas = document.createElement('canvas')
    canvas.width = width
    canvas.height = height
    const ctx = canvas.getContext('2d')
    if (!ctx) throw new Error('canvas_unavailable')
    ctx.drawImage(image, 0, 0, width, height)
    return canvas.toDataURL('image/jpeg', 0.9)
  } finally {
    URL.revokeObjectURL(sourceUrl)
  }
}

export async function imageRequestSizeFromSource(source: string | undefined, fallback: { width: number; height: number }) {
  if (!source) return fallback
  const image = await new Promise<HTMLImageElement>((resolve, reject) => {
    const img = new Image()
    img.onload = () => resolve(img)
    img.onerror = reject
    img.src = source
  }).catch(() => undefined)
  const sourceWidth = image?.naturalWidth || fallback.width
  const sourceHeight = image?.naturalHeight || fallback.height
  const maxSide = 1536
  const scale = Math.min(1, maxSide / Math.max(sourceWidth, sourceHeight))
  return {
    width: fitGenerationDimension(sourceWidth * scale),
    height: fitGenerationDimension(sourceHeight * scale),
  }
}

export async function loadHtmlImage(source: string): Promise<HTMLImageElement | undefined> {
  return new Promise<HTMLImageElement>((resolve, reject) => {
    const img = new Image()
    img.onload = () => resolve(img)
    img.onerror = reject
    img.src = source
  }).catch(() => undefined)
}

export async function createPaintMask(inputImage: string | undefined, lines: PaintLine[], stageSize: { width: number; height: number }) {
  if (!inputImage) return undefined
  const image = await loadHtmlImage(inputImage)
  if (!image) return undefined
  const canvas = document.createElement('canvas')
  canvas.width = image.naturalWidth || image.width
  canvas.height = image.naturalHeight || image.height
  const ctx = canvas.getContext('2d')
  if (!ctx) return undefined
  ctx.fillStyle = '#000'
  ctx.fillRect(0, 0, canvas.width, canvas.height)
  const scale = Math.min(stageSize.width / canvas.width, stageSize.height / canvas.height)
  const offsetX = (stageSize.width - canvas.width * scale) / 2
  const offsetY = (stageSize.height - canvas.height * scale) / 2
  const map = (x: number, y: number) => [
    Math.max(0, Math.min(canvas.width, (x - offsetX) / scale)),
    Math.max(0, Math.min(canvas.height, (y - offsetY) / scale)),
  ]
  for (const line of lines) {
    ctx.save()
    ctx.strokeStyle = line.tool === 'eraser' ? '#000' : '#fff'
    ctx.fillStyle = line.tool === 'eraser' ? '#000' : '#fff'
    ctx.lineCap = 'round'
    ctx.lineJoin = 'round'
    ctx.lineWidth = Math.max(1, line.strokeWidth / Math.max(0.1, scale))
    if (line.kind === 'rect' || line.kind === 'circle') {
      const [x1 = 0, y1 = 0, x2 = x1, y2 = y1] = line.points
      const [mx1, my1] = map(x1, y1)
      const [mx2, my2] = map(x2, y2)
      const x = Math.min(mx1, mx2)
      const y = Math.min(my1, my2)
      const w = Math.abs(mx2 - mx1)
      const h = Math.abs(my2 - my1)
      if (line.kind === 'circle') {
        ctx.beginPath()
        ctx.ellipse(x + w / 2, y + h / 2, w / 2, h / 2, 0, 0, Math.PI * 2)
        if (line.fill === false) ctx.stroke()
        else ctx.fill()
      } else if (line.fill === false) ctx.strokeRect(x, y, w, h)
      else ctx.fillRect(x, y, w, h)
    } else {
      ctx.beginPath()
      for (let i = 0; i < line.points.length; i += 2) {
        const [x, y] = map(line.points[i] || 0, line.points[i + 1] || 0)
        if (i === 0) ctx.moveTo(x, y)
        else ctx.lineTo(x, y)
      }
      ctx.stroke()
    }
    ctx.restore()
  }
  return canvas.toDataURL('image/png')
}

export async function createOutpaintPreview(inputImage: string | undefined, placement: PaintOutpaintPlacement, target: { width: number; height: number }) {
  if (!inputImage) return undefined
  const image = await new Promise<HTMLImageElement>((resolve, reject) => {
    const img = new Image()
    img.onload = () => resolve(img)
    img.onerror = reject
    img.src = inputImage
  }).catch(() => undefined)
  if (!image) return undefined
  const sourceWidth = image.naturalWidth || image.width
  const sourceHeight = image.naturalHeight || image.height
  const canvas = document.createElement('canvas')
  canvas.width = Math.max(256, Math.round(target.width || 1024))
  canvas.height = Math.max(256, Math.round(target.height || 1024))
  const ctx = canvas.getContext('2d')
  if (!ctx) return undefined
  ctx.fillStyle = '#030403'
  ctx.fillRect(0, 0, canvas.width, canvas.height)
  ctx.fillStyle = 'rgba(182, 207, 18, .08)'
  for (let x = -canvas.height; x < canvas.width; x += 24) ctx.fillRect(x, 0, 10, canvas.height)
  const hasPlacement = typeof placement.sourceX === 'number'
    && typeof placement.sourceY === 'number'
    && typeof placement.sourceW === 'number'
    && typeof placement.sourceH === 'number'
  const frameW = Math.max(1, placement.frameW || target.width || canvas.width)
  const frameH = Math.max(1, placement.frameH || target.height || canvas.height)
  const scaleX = canvas.width / frameW
  const scaleY = canvas.height / frameH
  const finalWidth = Math.max(1, sourceWidth + Math.max(0, placement.left) + Math.max(0, placement.right))
  const finalHeight = Math.max(1, sourceHeight + Math.max(0, placement.top) + Math.max(0, placement.bottom))
  const x = hasPlacement ? Math.round((placement.sourceX || 0) * scaleX) : Math.round(Math.max(0, placement.left) * canvas.width / finalWidth)
  const y = hasPlacement ? Math.round((placement.sourceY || 0) * scaleY) : Math.round(Math.max(0, placement.top) * canvas.height / finalHeight)
  const w = hasPlacement ? Math.max(1, Math.round((placement.sourceW || frameW) * scaleX)) : Math.max(1, Math.round(sourceWidth * canvas.width / finalWidth))
  const h = hasPlacement ? Math.max(1, Math.round((placement.sourceH || frameH) * scaleY)) : Math.max(1, Math.round(sourceHeight * canvas.height / finalHeight))
  ctx.drawImage(image, x, y, w, h)
  ctx.strokeStyle = '#b6cf12'
  ctx.lineWidth = Math.max(2, Math.round(Math.min(canvas.width, canvas.height) / 240))
  ctx.strokeRect(x + 1, y + 1, Math.max(1, w - 2), Math.max(1, h - 2))
  return canvas.toDataURL('image/jpeg', 0.9)
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

export function paintStageForResolution(resolution: { width: number; height: number }) {
  const maxSide = 1024
  const width = Math.max(1, resolution.width)
  const height = Math.max(1, resolution.height)
  if (width >= height) {
    return { width: maxSide, height: Math.max(256, Math.round((maxSide * height) / width)) }
  }
  return { width: Math.max(256, Math.round((maxSide * width) / height)), height: maxSide }
}

export function composePaintPrompt(basePrompt: string, userPrompt: string) {
  const base = basePrompt.trim()
  const user = userPrompt.trim()
  if (!user) return base
  const normalizedUser = user.toLowerCase()
  const baseLead = base.slice(0, 42).toLowerCase()
  return normalizedUser.includes(baseLead) ? user : `${base}\n\n${user}`
}

export function studioSeoMeta(tab: N2Tab, view: N2View): SeoMeta {
  const locale = currentSeoLocale()
  const path = view === 'profile' ? '/profile' : tab === 'paint' ? '/paint' : tab === 'video' ? '/video' : '/'
  const canonical = `https://izo.alikinas.ru${path}`

  if (view === 'profile') {
    return locale === 'en'
      ? {
        title: 'Profile and settings — IZO ASA',
        description: 'Manage your IZO ASA profile, avatar, accounts, tariffs, bonuses and generation history settings.',
        canonical,
        robots: 'noindex, nofollow',
      }
      : {
        title: 'Профиль и настройки — ИЗО АСА',
        description: 'Управляйте профилем ИЗО АСА: аватаром, аккаунтами, тарифами, бонусами и настройками истории генераций.',
        canonical,
        robots: 'noindex, nofollow',
      }
  }

  const ru: Record<N2Tab, SeoMeta> = {
    feed: {
      title: 'ИЗО АСА — лента AI-изображений',
      description: 'Смотрите публичную ленту изображений, промптов и идей пользователей ИЗО АСА.',
      canonical: 'https://izo.alikinas.ru/feed',
    },
    text: {
      title: 'По тексту — ИЗО АСА',
      description: 'Создавайте изображения нейросетью по текстовому описанию: выбирайте стиль, формат, качество и публикуйте результат в ленту.',
      canonical,
    },
    i2i: {
      title: 'По фото — ИЗО АСА',
      description: 'Преобразуйте исходное изображение по промпту и стилю, управляйте влиянием описания и сохраняйте результат в галерею.',
      canonical,
    },
    edit: {
      title: 'Сборка изображения — ИЗО АСА',
      description: 'Объединяйте несколько изображений, переносите одежду, фон, стиль и детали с референсов через AI-редактор ИЗО АСА.',
      canonical,
    },
    paint: {
      title: 'Редактор изображения — ИЗО АСА',
      description: 'Редактируйте изображения: рисуйте эскиз, работайте с маской, расширением холста и AI-дорисовкой.',
      canonical,
    },
    video: {
      title: 'Видео — ИЗО АСА',
      description: 'Создавайте видео по тексту, изображению, начальному и конечному кадру или набору референсов.',
      canonical,
    },
  }
  const en: Record<N2Tab, SeoMeta> = {
    feed: {
      title: 'AI image feed — IZO ASA',
      description: 'Explore public AI images, prompts, ideas and remixes from IZO ASA users.',
      canonical: 'https://izo.alikinas.ru/feed',
    },
    text: {
      title: 'By text — IZO ASA',
      description: 'Create AI images from text prompts, choose styles, aspect ratios and quality, then publish results to the feed.',
      canonical,
    },
    i2i: {
      title: 'By photo — IZO ASA',
      description: 'Transform a source image with a prompt and style, control prompt influence and save results to your gallery.',
      canonical,
    },
    edit: {
      title: 'Image assembly — IZO ASA',
      description: 'Combine multiple images, transfer clothes, background, style and details from references with the IZO ASA editor.',
      canonical,
    },
    paint: {
      title: 'Image editor — IZO ASA',
      description: 'Edit images with sketches, masks, outpainting and AI-assisted canvas tools.',
      canonical,
    },
    video: {
      title: 'Video — IZO ASA',
      description: 'Create videos from text, images, first and last frames, or visual references.',
      canonical,
    },
  }
  return locale === 'en' ? en[tab] : ru[tab]
}
