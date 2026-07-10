// ============================================================================
// UI 2.0 — страница /new. Самодостаточный модуль: собственный layout по новым
// макетам, реальный функционал через те же API, что и основной интерфейс
// (/api/generate, /api/jobs, /api/gallery, auth v2). Работает параллельно с
// текущим интерфейсом и не зависит от него (общие только stylePresets/authV2).
//
// Логика стилей (По тексту): клик по стилю дописывает текст стиля в конец
// промпта; выбор другого стиля заменяет предыдущую приписку. В По фото стиль
// задаёт transform-prompt преобразования (как шаблоны текущей версии).
// ============================================================================
import { lazy, Suspense, useCallback, useEffect, useRef, useState } from 'react'
import type { ChangeEvent } from 'react'
import type { CSSProperties, PointerEvent as ReactPointerEvent, ReactElement, TouchEvent as ReactTouchEvent, WheelEvent as ReactWheelEvent } from 'react'
import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp, Brush, ChevronDown, Eraser, Moon, PaintBucket, Palette, SlidersHorizontal, Slash, Sun, Trash2, Undo2 } from 'lucide-react'
import {
  AuthV2Modal,
  getAuthCapabilitiesV2,
  initAuthV2,
  logoutV2,
  pollBotLoginStatusV2,
  refreshAuthStateV2,
  startBotLinkV2,
  updateProfileV2,
  updateProfileV2Detailed,
  useAuthV2,
} from './authV2'
import {
  DEFAULT_EDIT_STRENGTH,
  EDIT_DISABLED_REFERENCE_ROLES,
  EDIT_REFERENCE_ROLE_LABELS,
  EDIT_SELECTABLE_REFERENCE_ROLES,
  EDIT_SLOT_COUNT,
  editComposerStatus,
  type EditReferenceRole,
  type EditSlot,
} from './editPrompt'
import { I2I_STYLES, T2I_TEMPLATES, styleShortLabel } from './stylePresets'
import type { StylePreset } from './stylePresets'
import TopBarV3 from './TopBarV3'
import type { V3Mode, V3Section } from './TopBarV3'
import { accountInfo } from './topbarUtils'
import ProfilePage, { type PublicProfileLink } from './ProfilePage'
import { DEFAULT_TARIFFS, avatarPresets, normalizeTariffs, type TariffConfig } from './profileSupport'
import type { PaintDrawMode, PaintLine, PaintOutpaintPlacement, PaintSubMode, PaintTool } from './paintTypes'
import type { PaintWorkbenchHandle } from './PaintWorkbench'
import { applyClientSeo, currentSeoLocale, type SeoMeta } from './seo'
import './newUi.css'
import './newStudioV3.css'
import previewPlaceholderUrl from './assets/preview-placeholder.jpg'

const PaintWorkbench = lazy(() => import('./PaintWorkbench'))

const API = import.meta.env.VITE_API_BASE_URL || '/api'
// Origin API-сервера для относительных media-URL из ответов backend
// (в проде API='/api' → origin пуст и URL остаются относительными).
const API_ORIGIN = API.endsWith('/api') ? API.slice(0, -'/api'.length) : ''

function apiUrl(path: string): string {
  return path.startsWith('/') ? `${API_ORIGIN}${path}` : path
}

function userMediaUrl(path: string | null | undefined): string | null {
  if (!path) return null
  return path.startsWith('/media/') ? apiUrl(path) : path
}

// Auth: только trusted cookie session (credentials: include). Никаких legacy
// заголовков, кук или клиентских идентификаторов — см. docs/new-ui-v2-plan.md.
function apiFetch(path: string, init: RequestInit = {}) {
  return fetch(`${API}${path}`, { ...init, credentials: 'include' })
}

type N2Tab = 'feed' | 'text' | 'i2i' | 'edit' | 'paint' | 'face' | 'video'
// tabs — генератор/лента; gallery и profile — отдельные канонические страницы.
type N2View = 'tabs' | 'profile'
type StudioMode = 'text' | 'i2i' | 'edit' | 'face' | 'paint'
type CoreStudioMode = Exclude<StudioMode, 'paint'>
type UploadTarget = { kind: 'i2i' } | { kind: 'edit'; index: number } | { kind: 'face'; index: number } | { kind: 'paint' } | { kind: 'paintSketch' }
type InspectPreview = { url: string; title: string }
type PreviewShape = 'square' | 'wide' | 'tall'
type StudioPreviewState = {
  kind: 'empty' | 'inspect' | 'result' | 'history'
  url?: string
  sourceUrl?: string
  shape?: PreviewShape
  title?: string
  galleryId?: string
  promptOriginal?: string
  resultImageId?: string
  error?: boolean
}
type ModelsPayload = { loras?: string[] }
type LoraOption = { id: string; label: string; triggerWord: string; strength: number }

function coreModeFromTab(tab: N2Tab): CoreStudioMode | null {
  if (tab === 'text' || tab === 'i2i' || tab === 'edit' || tab === 'face') return tab
  return null
}

function emptyPreview(): StudioPreviewState {
  return { kind: 'empty' }
}

function shapeFromSize(width?: number, height?: number): PreviewShape {
  if (!width || !height) return 'square'
  const ratio = width / height
  if (ratio > 1.18) return 'wide'
  if (ratio < 0.82) return 'tall'
  return 'square'
}

function loadImageShape(url: string): Promise<PreviewShape> {
  return new Promise((resolve) => {
    const img = new Image()
    img.onload = () => resolve(shapeFromSize(img.naturalWidth, img.naturalHeight))
    img.onerror = () => resolve('square')
    img.src = apiUrl(url)
  })
}

const EMPTY_EDIT_SLOTS: EditSlot[] = Array.from({ length: EDIT_SLOT_COUNT }, () => ({ image: undefined, role: '', takeNote: '' }))
const EMPTY_FACE_SLOTS: EditSlot[] = [
  { image: undefined, role: '', takeNote: '' },
  { image: undefined, role: 'face', takeNote: '' },
]
const DEFAULT_PAINT_SKETCH_PROMPT = 'Transform this sketch into a hyper-realistic cinematic scene. Interpret the lines as real-world objects with high-quality textures, cinematic lighting, natural shadows, depth, realistic materials and clean composition. Preserve the exact composition, silhouettes, poses, proportions and spatial relationships from the sketch. Scene description:'
const DEFAULT_PAINT_MASK_PROMPT = 'Edit only the masked area and follow the user instruction literally for that selected region. Seamlessly blend the change with the surrounding scene while preserving lighting, shadows, perspective, depth of field and photo grain. Do not change unmasked areas.'
const DEFAULT_PAINT_OUTPAINT_PROMPT = 'Extend the composition of this image. Replace black or empty spaces with a logical continuation of the background and foreground. Match perspective, lighting, color palette and texture so the transition is invisible. Scene description:'

// Начальное состояние из URL. Статические /feed и /gallery отдаются backend,
// а hash-ссылки из этих страниц возвращают пользователя в нужный режим UI 2.0.
function initialViewFromPath(): { view: N2View; tab: N2Tab } {
  const p = typeof window !== 'undefined' ? window.location.pathname : '/feed'
  const h = typeof window !== 'undefined' ? window.location.hash : ''
  if (p === '/gallery' || p.startsWith('/gallery') || p.startsWith('/new/gallery')) return { view: 'tabs', tab: 'text' }
  if (p === '/profile' || p.startsWith('/profile') || p.startsWith('/new/profile')) return { view: 'profile', tab: 'feed' }
  if (h === '#image-to-image') return { view: 'tabs', tab: 'i2i' }
  if (h === '#editor') return { view: 'tabs', tab: 'edit' }
  if (h === '#face' || h === '#face-to-image') return { view: 'tabs', tab: 'face' }
  if (h === '#draw' || h === '#drawing' || h === '#paint') return { view: 'tabs', tab: 'paint' }
  if (h === '#text-to-image') return { view: 'tabs', tab: 'text' }
  if (p === '/paint' || p.startsWith('/paint/') || p === '/new/paint' || p.startsWith('/new/paint/')) return { view: 'tabs', tab: 'paint' }
  // /feed is owned by backend/static/feed/index.html. If the SPA is ever served
  // for that path by a stale build or broken proxy, do not revive the old React feed.
  return { view: 'tabs', tab: 'text' }
}

interface N2Job {
  id: string
  status: string
  progress?: number
  message?: string
  resultUrl?: string
  resultImageId?: string
  error?: string
}

interface N2GalleryImage {
  id: string
  url: string
  thumbnailUrl: string
  mode: string
  promptOriginal: string
  createdAt: string
  // Для формы миниатюр истории: у галереи есть width/height, у ленты — aspectRatio.
  width?: number
  height?: number
  aspectRatio?: string
}

// Форма миниатюры истории по реальным размерам/соотношению; квадрат — фолбэк.
function historyShape(item: N2GalleryImage): 'square' | 'tall' | 'wide' {
  if (item.width && item.height) {
    if (item.width === item.height) return 'square'
    return item.width > item.height ? 'wide' : 'tall'
  }
  if (item.aspectRatio) return feedShape(item.aspectRatio)
  return 'square'
}

function historyAspectRatio(item: N2GalleryImage): string | undefined {
  if (item.width && item.height) return `${item.width} / ${item.height}`
  if (item.aspectRatio) {
    const parts = item.aspectRatio.split(':').map((x) => Number(x))
    if (parts.length === 2 && parts[0] > 0 && parts[1] > 0) return `${parts[0]} / ${parts[1]}`
  }
  return undefined
}

const QUALITY: Array<{ id: string; label: string; steps: number }> = [
  { id: 'fast', label: 'Быстро', steps: 4 },
  { id: 'standard', label: 'Стандарт', steps: 6 },
  { id: 'max', label: 'Максимум', steps: 10 },
]

// Заготовленные разрешения системы. Источник данных — resolutionPresets
// основного интерфейса (App.tsx) + средний размер 1536 (максимум генерации,
// см. fitGenerationDimension). Перенесены данные, не вёрстка.
type FormatId = 'square' | 'vertical' | 'horizontal'

interface ResolutionPreset {
  id: string
  name: string
  width: number
  height: number
  kind: FormatId
}

const RESOLUTION_PRESETS: ResolutionPreset[] = [
  { id: 'sq-1024', name: 'Квадратное', width: 1024, height: 1024, kind: 'square' },
  { id: 'h-1280', name: 'Горизонтальное HD', width: 1280, height: 720, kind: 'horizontal' },
  { id: 'v-720', name: 'Вертикальное HD', width: 720, height: 1280, kind: 'vertical' },
  { id: 'h-1536', name: 'Горизонтальное среднее', width: 1536, height: 1024, kind: 'horizontal' },
  { id: 'v-1024', name: 'Вертикальное среднее', width: 1024, height: 1536, kind: 'vertical' },
  { id: 'h-1920', name: 'Горизонтальное Full HD', width: 1920, height: 1088, kind: 'horizontal' },
  { id: 'v-1088', name: 'Вертикальное Full HD', width: 1088, height: 1920, kind: 'vertical' },
]

const DEFAULT_FACE_STRENGTH = 75
const FALLBACK_LORA_OPTIONS: LoraOption[] = [
  { id: 'none', label: 'None', triggerWord: '', strength: 0 },
  { id: 'lora_arcane', label: 'arcane style · 0.8', triggerWord: 'arcane style', strength: 0.8 },
  { id: 'product_photo', label: 'product photo · 0.6', triggerWord: 'product photo', strength: 0.6 },
]

function faceStrengthPrompt(value: number): string {
  if (value >= 85) return 'Face transfer strength: very strong. Prioritize the face identity from Image 2 clearly and recognizably while preserving the target scene from Image 1.'
  if (value >= 60) return 'Face transfer strength: strong. Transfer the face identity from Image 2, but keep lighting, pose, clothing, and background from Image 1 natural.'
  if (value >= 35) return 'Face transfer strength: balanced. Blend the face identity from Image 2 naturally with the head angle, lighting, and style of Image 1.'
  return 'Face transfer strength: subtle. Keep most of the original target face structure from Image 1 and add only a light resemblance from Image 2.'
}

function fitGenerationDimension(value: number) {
  return Math.max(512, Math.min(1536, Math.round(value / 16) * 16))
}

async function resizeUploadImage(file: File): Promise<string> {
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

async function imageRequestSizeFromSource(source: string | undefined, fallback: { width: number; height: number }) {
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

async function loadHtmlImage(source: string): Promise<HTMLImageElement | undefined> {
  return new Promise<HTMLImageElement>((resolve, reject) => {
    const img = new Image()
    img.onload = () => resolve(img)
    img.onerror = reject
    img.src = source
  }).catch(() => undefined)
}

async function createPaintMask(inputImage: string | undefined, lines: PaintLine[], stageSize: { width: number; height: number }) {
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

async function createOutpaintPreview(inputImage: string | undefined, placement: PaintOutpaintPlacement, target: { width: number; height: number }) {
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

type FeedLang = 'ru' | 'en'

// RU/EN тексты ленты. Главная кнопка по ТЗ: «Повторить» / "Recreate"
// (не Remix); в detail — «Сделать похожее» / "Make similar".
const FEED_I18N: Record<FeedLang, Record<string, string>> = {
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

// Модель публикации = ответ GET /api/feed (snake_case backend-контракта).
interface FeedPublication {
  id: string
  image_url: string
  thumbnail_url: string
  display_url?: string
  user_id: string
  author_name: string
  author_handle?: string | null
  author_avatar?: string | null
  author_type?: string
  is_seed?: boolean
  is_current_user?: boolean
  badge?: string | null
  category?: string | null
  title: string
  description: string | null
  prompt: string | null
  prompt_visibility: 'open' | 'partial' | 'hidden'
  allow_recreate: boolean
  style: string | null
  model: string | null
  mode: string | null
  aspect_ratio: string
  resolution: string | null
  seed: number | null
  created_at: string
  remix_count: number
  save_count: number
  like_count: number
  view_count?: number
  is_liked_by_me: boolean
  is_saved_by_me: boolean
  is_mine: boolean
}

// Форма карточки по соотношению сторон публикации.
function feedShape(ratio: string): 'tall' | 'wide' | 'square' {
  const parts = ratio.split(':').map(Number)
  const w = parts[0]
  const h = parts[1]
  if (!w || !h || w === h) return 'square'
  return w > h ? 'wide' : 'tall'
}

const JOB_ACTIVE = ['queued', 'running', 'uploading', 'sent_to_comfyui']

// Приписка стиля в промпте (По тексту). Через маркер её можно заменить при
// выборе другого стиля, не трогая пользовательский текст.
const STYLE_PREFIX = '\n\nСтиль: '
const I2I_STYLE_PREFIX = '\n\nСтиль преобразования: '
const PROMPT_APPEND_PREFIX = '\n\n'

// Вне компонента: react-hooks/purity запрещает impure-вызовы в теле компонента.
function randomOf<T>(items: T[]): T {
  return items[Math.floor(Math.random() * items.length)]
}

function randomSeed(): number {
  return Math.floor(Math.random() * 999999999)
}

function newClientRequestId(): string {
  return typeof crypto !== 'undefined' && crypto.randomUUID
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(36).slice(2)}`
}

function paintStageForResolution(resolution: { width: number; height: number }) {
  const maxSide = 1024
  const width = Math.max(1, resolution.width)
  const height = Math.max(1, resolution.height)
  if (width >= height) {
    return { width: maxSide, height: Math.max(256, Math.round((maxSide * height) / width)) }
  }
  return { width: Math.max(256, Math.round((maxSide * width) / height)), height: maxSide }
}

function composePaintPrompt(basePrompt: string, userPrompt: string) {
  const base = basePrompt.trim()
  const user = userPrompt.trim()
  if (!user) return base
  const normalizedUser = user.toLowerCase()
  const baseLead = base.slice(0, 42).toLowerCase()
  return normalizedUser.includes(baseLead) ? user : `${base}\n\n${user}`
}

function studioSeoMeta(tab: N2Tab, view: N2View): SeoMeta {
  const locale = currentSeoLocale()
  const path = view === 'profile' ? '/profile' : tab === 'paint' ? '/paint' : '/'
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
    face: {
      title: 'Замена лица нейросетью — ИЗО АСА',
      description: 'Переносите лицо с одного изображения на другое, настраивайте силу замены и сохраняйте естественный свет, позу и сцену.',
      canonical,
    },
    paint: {
      title: 'Редактор изображения — ИЗО АСА',
      description: 'Редактируйте изображения: рисуйте эскиз, работайте с маской, расширением холста и AI-дорисовкой.',
      canonical,
    },
    video: {
      title: 'Видео — ИЗО АСА',
      description: 'Раздел генерации видео в ИЗО АСА готовится к запуску.',
      canonical,
      robots: 'noindex, follow',
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
    face: {
      title: 'AI face swap — IZO ASA',
      description: 'Transfer a face from one image to another while preserving the target pose, lighting, clothing and scene.',
      canonical,
    },
    paint: {
      title: 'Image editor — IZO ASA',
      description: 'Edit images with sketches, masks, outpainting and AI-assisted canvas tools.',
      canonical,
    },
    video: {
      title: 'Video — IZO ASA',
      description: 'AI video generation in IZO ASA is being prepared for launch.',
      canonical,
      robots: 'noindex, follow',
    },
  }
  return locale === 'en' ? en[tab] : ru[tab]
}

export default function NewStudio(): ReactElement {
  // Route: /paint — отдельная страница режима «Редактор»; остальные режимы генератора
  // пока живут на /new. Это URL-изоляция, физический split компонента ниже в TODO.
  const initialRoute = initialViewFromPath()
  const [tab, setTabState] = useState<N2Tab>(initialRoute.tab)
  const [view, setView] = useState<N2View>(initialRoute.view)

  // Навигация страниц нового UI с синхронизацией URL. Каноничные маршруты:
  // Лента /feed, Галерея /gallery, Профиль /profile, Редактор /paint,
  // остальные режимы генератора /new.
  const navTo = useCallback((path: string) => {
    if (window.location.pathname !== path) window.history.pushState(null, '', path)
  }, [])
  const setTab = useCallback(
    (next: N2Tab) => {
      if (next === 'feed') {
        window.location.href = '/feed'
        return
      }
      setView('tabs')
      setTabState(next)
      navTo(next === 'paint' ? '/paint' : '/new')
    },
    [navTo],
  )
  const selectStudioMode = useCallback(
    (next: V3Mode) => {
      setTab(next)
    },
    [setTab],
  )
  const goGallery = useCallback(() => {
    window.location.href = '/gallery'
  }, [])
  const goProfile = useCallback(() => {
    setView('profile')
    navTo('/profile')
  }, [navTo])

  useEffect(() => {
    if (view === 'tabs' && tab === 'feed') window.location.href = '/feed'
  }, [view, tab])

  useEffect(() => {
    applyClientSeo(studioSeoMeta(tab, view))
  }, [tab, view])

  // Кнопка «назад» браузера синхронизирует страницу с URL.
  useEffect(() => {
    const onPop = () => {
      const r = initialViewFromPath()
      setView(r.view)
      setTabState(r.tab)
    }
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])
  const { status: authStatus, me } = useAuthV2()
  const videoEnabled = Boolean(me?.account?.video_enabled)
  const isAdmin = authStatus === 'authed' && me?.account?.role === 'admin'
  const [authOpen, setAuthOpen] = useState(false)
  const ensureAuthed = useCallback(async () => {
    if (authStatus === 'authed') return true
    if (authStatus === 'loading') {
      await initAuthV2()
      if (await refreshAuthStateV2()) return true
    }
    const current = await refreshAuthStateV2()
    if (current) return true
    setAuthOpen(true)
    return false
  }, [authStatus])
  const openProfilePage = useCallback(() => {
    goProfile()
    if (authStatus === 'loading') void initAuthV2()
  }, [authStatus, goProfile])
  const onSaveProfile = async () => {
    const trimmed = displayName.trim()
    if (!trimmed) { setSaveMsg('Введите имя'); return }
    const age = profileAge.trim()
    if (age && (Number(age) < 13 || Number(age) > 120)) { setSaveMsg('Возраст должен быть от 13 до 120'); return }
    const normalizedAge = age ? Number(age) : null
    setSaveMsg('')
    const result = await updateProfileV2({
      display_name: trimmed,
      gender: profileGender,
      age: normalizedAge,
      public_about: publicAbout.trim(),
      public_website: publicWebsite.trim(),
      public_focus: publicFocus.trim(),
      public_phone: publicPhone.trim(),
      public_links: publicLinks
        .map((item) => ({ label: item.label.trim(), url: item.url.trim() }))
        .filter((item) => item.url),
    })
    if (result) { await refreshAuthStateV2(); setSaveMsg('Сохранено') }
    else setSaveMsg('Ошибка сохранения')
  }
  const selectAvatarPreset = async (presetId: string) => {
    const preset = avatarPresets.find((item) => item.id === presetId)
    if (!preset) return
    setAvatarBusy(true)
    setAvatarMsg('')
    const result = await updateProfileV2Detailed({ avatar_preset: presetId, avatar_url: preset.url })
    if (result.ok) {
      setAvatarPreset(presetId)
      setAvatarUrl(preset.url)
      await refreshAuthStateV2()
      setAvatarMsg('Аватар сохранён')
    } else setAvatarMsg(result.detail || 'Не удалось сохранить аватар')
    setAvatarBusy(false)
  }
  const uploadAvatar = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    if (!/^image\/(png|jpeg|webp)$/.test(file.type)) { setAvatarMsg('Нужен PNG, JPG или WEBP'); return }
    if (file.size > 8 * 1024 * 1024) { setAvatarMsg('Файл больше 8 МБ'); return }
    setAvatarBusy(true)
    setAvatarMsg('')
    try {
      const form = new FormData()
      form.append('file', file)
      const r = await fetch(`${API}/me/avatar-upload-v2`, { method: 'POST', credentials: 'include', body: form })
      const payload = await r.json().catch(() => ({}))
      if (!r.ok || !payload.avatar_url) { setAvatarMsg(String(payload.detail || 'Не удалось загрузить аватар')); return }
      setAvatarUrl(String(payload.avatar_url))
      setAvatarPreset('')
      await refreshAuthStateV2()
      setAvatarMsg('Аватар загружен')
    } catch {
      setAvatarMsg('Ошибка загрузки аватара')
    } finally {
      setAvatarBusy(false)
    }
  }
  const onLogout = async () => {
    await logoutV2()
    await refreshAuthStateV2()
  }
  const onApplyPromo = async () => {
    const code = promoCode.trim().toUpperCase()
    if (!code) { setPromoResult('Введите промокод'); return }
    setPromoBusy(true)
    setPromoResult('')
    try {
      const r = await apiFetch('/account/apply-promo-v2', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ promo_code: code }),
      })
      const payload = await r.json().catch(() => ({}))
      if (!r.ok) { setPromoResult(String(payload.detail || 'Промокод не применён')); return }
      const bonus = Number(payload.token_bonus || 50)
      setPromoResult(`Промокод применён: +${bonus} токенов`)
      await refreshAuthStateV2()
    } catch {
      setPromoResult('Не удалось проверить промокод')
    } finally {
      setPromoBusy(false)
    }
  }
  const onLinkBot = async (providerName: 'telegram' | 'max') => {
    setLinkBusy(true)
    setLinkMsg('')
    const started = await startBotLinkV2(providerName)
    if (!started.ok) {
      setLinkMsg(providerName === 'telegram' ? 'Telegram-подключение сейчас недоступно' : 'MAX-подключение сейчас недоступно')
      setLinkBusy(false)
      return
    }
    window.open(started.deep_link, '_blank', 'noopener,noreferrer')
    setLinkMsg(`Подтвердите подключение в ${providerName === 'telegram' ? 'Telegram' : 'MAX'}-боте`)
    let attemptsLeft = Math.ceil((10 * 60 * 1000) / (started.poll_interval_ms || 2000))
    const timer = window.setInterval(async () => {
      attemptsLeft -= 1
      const status = await pollBotLoginStatusV2()
      if (status.status === 'authenticated') {
        window.clearInterval(timer)
        await refreshAuthStateV2()
        setLinkBusy(false)
        setLinkMsg(`${providerName === 'telegram' ? 'Telegram' : 'MAX'} подключен`)
      } else if (status.status === 'conflict') {
        window.clearInterval(timer)
        setLinkBusy(false)
        setLinkMsg('Этот способ входа уже привязан к другому аккаунту')
      } else if (status.status === 'expired' || status.status === 'error' || attemptsLeft <= 0) {
        window.clearInterval(timer)
        setLinkBusy(false)
        setLinkMsg('Подключение не завершено. Попробуйте снова')
      }
    }, started.poll_interval_ms || 2000)
  }
  const [helpOpen, setHelpOpen] = useState(false)

  useEffect(() => {
    const syncHelpHash = () => {
      if (window.location.hash === '#help') setHelpOpen(true)
    }
    syncHelpHash()
    window.addEventListener('hashchange', syncHelpHash)
    return () => window.removeEventListener('hashchange', syncHelpHash)
  }, [])

  const [templatesOpen, setTemplatesOpen] = useState(false)
  const [galleryPickTarget, setGalleryPickTarget] = useState<UploadTarget | null>(null)
  const [uploadTarget, setUploadTarget] = useState<UploadTarget | null>(null)
  const [modelsPayload, setModelsPayload] = useState<ModelsPayload>()
  const [loraTriggers] = useState<Record<string, string>>({})

  // Пол из профиля определяет вариант превью стилей (по умолчанию female).
  const previewGender: 'female' | 'male' = me?.profile?.gender === 'male' ? 'male' : 'female'
  const acct = accountInfo(me)

  const [prompts, setPrompts] = useState<Record<StudioMode, string>>({ text: '', i2i: '', edit: '', face: '', paint: '' })
  const [styleId, setStyleId] = useState<string>('')
  // Временный предпросмотр стиля при наведении на карточку (не выбирает стиль).
  const [hoverStyle, setHoverStyle] = useState<StylePreset | null>(null)
  // Разрешение = конкретный системный пресет; формат-кнопки переключают тип.
  const [resolutionId, setResolutionId] = useState('sq-1024')
  const [formatOpen, setFormatOpen] = useState(false)
  const formatRef = useRef<HTMLDivElement>(null)
  const [quality, setQuality] = useState('fast')
  const [provider, setProvider] = useState<'comfyui' | 'openrouter'>('comfyui')
  const [proMode, setProMode] = useState(false)
  const [seed, setSeed] = useState(0)
  const [guidance] = useState(3.5)
  const [strengthPct, setStrengthPct] = useState(75)
  const [sourceImage, setSourceImage] = useState<string>()
  const [editSlots, setEditSlots] = useState<EditSlot[]>(() => EMPTY_EDIT_SLOTS.map((slot) => ({ ...slot })))
  const [editExtraOpen, setEditExtraOpen] = useState(false)
  const [faceSlots, setFaceSlots] = useState<EditSlot[]>(() => EMPTY_FACE_SLOTS.map((slot) => ({ ...slot })))
  const [faceStrengthPct, setFaceStrengthPct] = useState(DEFAULT_FACE_STRENGTH)
  const [profileTab, setProfileTab] = useState<'profile' | 'tariffs' | 'earn' | 'models'>('profile')
  const [tariffs, setTariffs] = useState<TariffConfig>(DEFAULT_TARIFFS)
  const [tariffsState, setTariffsState] = useState<'loading' | 'ready' | 'fallback'>('loading')
  const [tokenRub, setTokenRub] = useState(5)
  const [displayName, setDisplayName] = useState(me?.profile?.display_name || '')
  const [profileGender, setProfileGender] = useState<'female' | 'male'>(me?.profile?.gender === 'male' ? 'male' : 'female')
  const [profileAge, setProfileAge] = useState(me?.profile?.age ? String(me.profile.age) : '')
  const [publicAbout, setPublicAbout] = useState(me?.profile?.public_about || '')
  const [publicWebsite, setPublicWebsite] = useState(me?.profile?.public_website || '')
  const [publicFocus, setPublicFocus] = useState(me?.profile?.public_focus || '')
  const [publicPhone, setPublicPhone] = useState(me?.profile?.public_phone || '')
  const [publicLinks, setPublicLinks] = useState<PublicProfileLink[]>(() => (
    (me?.profile?.public_links || [])
      .map((item) => ({ label: String(item.label || ''), url: String(item.url || '') }))
      .filter((item) => item.url)
      .slice(0, 6)
  ))
  const [saveMsg, setSaveMsg] = useState('')
  const [avatarUrl, setAvatarUrl] = useState(me?.profile?.avatar_url || avatarPresets[0].url)
  const [avatarPreset, setAvatarPreset] = useState(me?.profile?.avatar_preset || '')
  const [avatarMsg, setAvatarMsg] = useState('')
  const [avatarBusy, setAvatarBusy] = useState(false)
  const [promoCode, setPromoCode] = useState('')
  const [promoResult, setPromoResult] = useState('')
  const [promoBusy, setPromoBusy] = useState(false)
  const [inviteMsg, setInviteMsg] = useState('')
  const [authCaps, setAuthCaps] = useState({ telegram_bot_login_available: false, max_bot_login_available: false })
  const [authCapsState, setAuthCapsState] = useState<'loading' | 'ready' | 'fallback'>('loading')
  const [linkMsg, setLinkMsg] = useState('')
  const [linkBusy, setLinkBusy] = useState(false)
  const [paintMode, setPaintMode] = useState<PaintSubMode>('sketch')
  const [paintImage, setPaintImage] = useState<string>()
  const [paintSketchImage, setPaintSketchImage] = useState<string>()
  const [paintSketchLines, setPaintSketchLines] = useState<PaintLine[]>([])
  const [paintMaskLines, setPaintMaskLines] = useState<PaintLine[]>([])
  const [paintTool, setPaintTool] = useState<PaintTool>('brush')
  const [paintDrawMode, setPaintDrawMode] = useState<PaintDrawMode>('free')
  const [paintBrushSize, setPaintBrushSize] = useState(3)
  const [paintTechPrompts, setPaintTechPrompts] = useState<Record<PaintSubMode, string>>({
    sketch: DEFAULT_PAINT_SKETCH_PROMPT,
    mask: DEFAULT_PAINT_MASK_PROMPT,
    outpaint: DEFAULT_PAINT_OUTPAINT_PROMPT,
    remove_bg: 'Аккуратно удали фон, сохрани главный объект и его края.',
  })
  const [paintTechPromptOpen, setPaintTechPromptOpen] = useState(false)
  const [paintColor, setPaintColor] = useState('#111827')
  const [paintCanvasBg, setPaintCanvasBg] = useState<'white' | 'gray'>('white')
  const [paintOutpaint, setPaintOutpaint] = useState<PaintOutpaintPlacement>({ left: 0, right: 0, top: 0, bottom: 0 })
  const [paintOutpaintPreview, setPaintOutpaintPreview] = useState<string>()
  const [paintStageSize, setPaintStageSize] = useState(() => paintStageForResolution(RESOLUTION_PRESETS[0]))
  const [paintWorkbenchVisible, setPaintWorkbenchVisible] = useState(true)
  const [paintToolsOpen, setPaintToolsOpen] = useState(false)
  const [compare, setCompare] = useState(50)
  const [compareEnabled, setCompareEnabled] = useState(true)
  const [compareAuto, setCompareAuto] = useState(false)
  const compareTouchedRef = useRef(false)

  // ---------- Live Feed state ----------
  // Язык ленты из профиля (RU по умолчанию — как весь /new).
  const feedLang: FeedLang = me?.profile?.language_code === 'en' ? 'en' : 'ru'
  const ft = FEED_I18N[feedLang]

  const [toastText, setToastText] = useState('')
  const toastTimerRef = useRef<number>(0)

  // Публикация из галереи: модалка поверх просмотра изображения.
  const [publishFor, setPublishFor] = useState<N2GalleryImage | null>(null)
  const [publishTitle, setPublishTitle] = useState('')
  const [publishVisibility, setPublishVisibility] = useState<'open' | 'partial' | 'hidden'>('open')
  const [publishAllowRecreate, setPublishAllowRecreate] = useState(true)
  const [publishBusy, setPublishBusy] = useState(false)

  const showToast = useCallback((text: string) => {
    setToastText(text)
    window.clearTimeout(toastTimerRef.current)
    toastTimerRef.current = window.setTimeout(() => setToastText(''), 2100)
  }, [])

  // Публикация выбранного изображения галереи.
  const openPublish = async (item: N2GalleryImage) => {
    if (!(await ensureAuthed())) return
    setPublishTitle('')
    setPublishVisibility('open')
    setPublishAllowRecreate(true)
    setPublishFor(item)
  }

  // Удалить изображение из личной галереи (как в старом интерфейсе: DELETE
  // /api/gallery/{id}). Только для своей галереи, требует сессию.
  const deleteGalleryImage = async (item: N2GalleryImage) => {
    if (!(await ensureAuthed())) return
    if (!window.confirm(ft.deleteConfirm)) return
    apiFetch(`/gallery/${item.id}`, { method: 'DELETE' })
      .then((r) => {
        if (!r.ok) throw new Error(String(r.status))
        setGallery((cur) => cur.filter((g) => g.id !== item.id))
        setGalleryItem(undefined)
        void refreshAuthStateV2()
        showToast(feedLang === 'ru' ? 'Удалено из галереи' : 'Deleted from gallery')
      })
      .catch(() => showToast(feedLang === 'ru' ? 'Не удалось удалить' : 'Delete failed'))
  }

  // «Использовать как основу» → По фото с этим изображением-исходником.
  const applyGalleryAsSource = (item: N2GalleryImage) => {
    setSourceImage(apiUrl(item.url))
    setGalleryItem(undefined)
    setTab('i2i')
  }

  // Профиль: язык RU/EN и выход.

  useEffect(() => {
    void initAuthV2()
  }, [])

  const submitPublish = () => {
    if (!publishFor || publishBusy) return
    const title = publishTitle.trim()
    if (!title) {
      showToast(feedLang === 'ru' ? 'Укажите название' : 'Title is required')
      return
    }
    setPublishBusy(true)
    apiFetch('/feed/publications', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        imageId: publishFor.id,
        title,
        promptVisibility: publishVisibility,
        allowRecreate: publishAllowRecreate,
      }),
    })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then(() => {
        setPublishFor(null)
        setGalleryItem(undefined)
        showToast(feedLang === 'ru' ? 'Опубликовано в ленту' : 'Published to feed')
        window.setTimeout(() => {
          window.location.href = '/feed'
        }, 250)
      })
      .catch(() => showToast(feedLang === 'ru' ? 'Не удалось опубликовать' : 'Publish failed'))
      .finally(() => setPublishBusy(false))
  }

  const [job, setJob] = useState<N2Job>()
  const [jobMode, setJobMode] = useState<StudioMode>('text')
  const [resultUrl, setResultUrl] = useState<string>()
  // URL результата не загрузился (битая ссылка/удалённый файл) — error-state.
  const [resultError, setResultError] = useState(false)
  const [resultSource, setResultSource] = useState<string>()
  const [inspectPreview, setInspectPreview] = useState<InspectPreview | null>(null)
  const [previewByMode, setPreviewByMode] = useState<Record<CoreStudioMode, StudioPreviewState>>({
    text: emptyPreview(),
    i2i: emptyPreview(),
    edit: emptyPreview(),
    face: emptyPreview(),
  })
  const [inspectZoom, setInspectZoom] = useState(1)
  const [inspectPan, setInspectPan] = useState({ x: 0, y: 0 })
  const [notice, setNotice] = useState('')
  const [gallery, setGallery] = useState<N2GalleryImage[]>([])
  const [galleryItem, setGalleryItem] = useState<N2GalleryImage>()
  // Изображение, чей промпт показан в доке «Промпт изображения» (v3-студия).
  // Храним только id выбранной миниатюры; сам объект выводим при рендере,
  // с откатом на самую свежую генерацию (без setState-в-эффекте).
  const [dockImageId, setDockImageId] = useState<string>()
  // Фолбэк истории из Ленты, когда у пользователя ещё нет своих генераций.
  const [feedFallback, setFeedFallback] = useState<N2GalleryImage[]>([])
  const [shareOpen, setShareOpen] = useState(false)
  const [copied, setCopied] = useState(false)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const inFlightRef = useRef(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const historyStripRef = useRef<HTMLDivElement>(null)
  const promptTextareaRef = useRef<HTMLTextAreaElement>(null)
  // true, если тянули историю мышью — тогда клик по миниатюре не выбирает её.
  const historyDraggedRef = useRef(false)
  const styleRowRef = useRef<HTMLDivElement>(null)
  const pendingResultSourceRef = useRef<Record<StudioMode, string | undefined>>({ text: undefined, i2i: undefined, edit: undefined, face: undefined, paint: undefined })
  const pendingResultShapeRef = useRef<Record<StudioMode, PreviewShape | undefined>>({ text: undefined, i2i: undefined, edit: undefined, face: undefined, paint: undefined })
  // true, если пользователь тянул ряд стилей — тогда клик по карточке не выбирает.
  const styleDraggedRef = useRef(false)
  // true, пока зажата кнопка над рядом стилей — подавляет hover-preview при drag.
  const stylePointerDownRef = useRef(false)
  const inspectDragRef = useRef<{ active: boolean; startX: number; startY: number; panX: number; panY: number }>({ active: false, startX: 0, startY: 0, panX: 0, panY: 0 })
  const inspectTouchRef = useRef<{ pinching: boolean; distance: number; zoom: number; panX: number; panY: number; startX: number; startY: number; lastTap: number }>({
    pinching: false,
    distance: 0,
    zoom: 1,
    panX: 0,
    panY: 0,
    startX: 0,
    startY: 0,
    lastTap: 0,
  })
  const paintStageRef = useRef<PaintWorkbenchHandle>(null)
  const paintWorkbenchRef = useRef<HTMLDivElement>(null)
  const paintLines = paintMode === 'mask' ? paintMaskLines : paintSketchLines
  const setPaintLines = paintMode === 'mask' ? setPaintMaskLines : setPaintSketchLines
  // Текущая стилевая приписка в text-промпте: {id, text} — чтобы заменять её.
  const appliedStyleRef = useRef<{ id: string; text: string } | null>(null)
  // Текущая стилевая приписка в i2i-промпте — видна прямо в textarea.
  const appliedI2IStyleRef = useRef<{ id: string; text: string } | null>(null)
  const lastSubmittedRef = useRef<{ text?: string; i2i?: { prompt: string; source: string; width: number; height: number } }>({})
  const noticeClearRef = useRef<{ text: string; i2i: string; edit: string; face: string; paint: string; source: string; editSlots: string; faceSlots: string }>({ text: '', i2i: '', edit: '', face: '', paint: '', source: '', editSlots: '', faceSlots: '' })
  const resultSeededRef = useRef(false)

  useEffect(() => {
    document.title = 'ИЗО АСА — новый интерфейс'
  }, [])

  useEffect(() => {
    let cancelled = false
    apiFetch('/models')
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (!cancelled && data?.ok !== false) setModelsPayload(data)
      })
      .catch(() => undefined)
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    let cancelled = false
    apiFetch('/tariffs')
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (cancelled) return
        if (data?.tariffs) {
          setTariffs(normalizeTariffs(data.tariffs))
          if (typeof data.economy?.tokenRub === 'number' && data.economy.tokenRub > 0) setTokenRub(data.economy.tokenRub)
          setTariffsState('ready')
        } else {
          setTariffsState('fallback')
        }
      })
      .catch(() => {
        if (!cancelled) setTariffsState('fallback')
      })
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    queueMicrotask(() => {
      setDisplayName(me?.profile?.display_name || '')
      setProfileGender(me?.profile?.gender === 'male' ? 'male' : 'female')
      setProfileAge(me?.profile?.age === null || me?.profile?.age === undefined ? '' : String(me.profile.age))
      setPublicAbout(me?.profile?.public_about || '')
      setPublicWebsite(me?.profile?.public_website || '')
      setPublicFocus(me?.profile?.public_focus || '')
      setPublicPhone(me?.profile?.public_phone || '')
      setPublicLinks((me?.profile?.public_links || []).map((item) => ({ label: String(item.label || ''), url: String(item.url || '') })).filter((item) => item.url).slice(0, 6))
      setAvatarUrl(me?.profile?.avatar_url || avatarPresets[0].url)
      setAvatarPreset(me?.profile?.avatar_preset || '')
      setSaveMsg('')
      setAvatarMsg('')
    })
  }, [me?.profile?.age, me?.profile?.avatar_preset, me?.profile?.avatar_url, me?.profile?.display_name, me?.profile?.gender, me?.profile?.public_about, me?.profile?.public_focus, me?.profile?.public_links, me?.profile?.public_phone, me?.profile?.public_website])

  useEffect(() => {
    let active = true
    getAuthCapabilitiesV2()
      .then((caps) => {
        if (!active) return
        setAuthCaps({ telegram_bot_login_available: caps.telegram_bot_login_available, max_bot_login_available: caps.max_bot_login_available })
        setAuthCapsState(caps.capabilities_loaded ? 'ready' : 'fallback')
      })
      .catch(() => {
        if (active) setAuthCapsState('fallback')
      })
    return () => { active = false }
  }, [])

  // Стабильная загрузка галереи: как только увидели свои изображения, спуриозный
  // пустой ответ (транзиентный 401 при refresh и т.п.) больше не затирает историю,
  // чтобы лента-фолбэк не «перебивал» уже показанную пользовательскую галерею.
  const ownGallerySeenRef = useRef(false)
  const fetchGallery = useCallback(() => {
    apiFetch('/gallery')
      .then((r) => (r.ok ? r.json() : []))
      .then((data) => {
        const arr: N2GalleryImage[] = Array.isArray(data) ? data : []
        if (arr.length === 0 && ownGallerySeenRef.current) return
        if (arr.length > 0) ownGallerySeenRef.current = true
        setGallery(arr)
      })
      .catch(() => undefined)
  }, [])

  useEffect(() => {
    fetchGallery()
  }, [fetchGallery, authStatus])

  // Если своих генераций ещё нет — подгружаем последние работы из Ленты как
  // наполнение истории (публичный /api/feed). Свои изображения ленту не мешают.
  useEffect(() => {
    // Свои генерации есть — лента не нужна (в рендере historyItems берёт ownHistory).
    if (gallery.length > 0) return
    let cancelled = false
    apiFetch('/feed?type=new&limit=10')
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (cancelled || !data) return
        const rows: FeedPublication[] = Array.isArray(data) ? data : data.items || data.publications || []
        const mapped: N2GalleryImage[] = rows
          .map((p) => {
            // Только ПУБЛИЧНЫЕ деривативы ленты (display_url/thumbnail_url).
            // image_url может указывать на приватный оригинал (/api/media → 401),
            // поэтому его не используем — иначе миниатюра «битая».
            const display = p.display_url || p.thumbnail_url || ''
            const thumb = p.thumbnail_url || p.display_url || ''
            return {
              id: `feed-${p.id}`,
              url: display,
              thumbnailUrl: thumb,
              mode: 'feed',
              promptOriginal: p.prompt || p.title || '',
              createdAt: p.created_at || '',
              aspectRatio: p.aspect_ratio || '1:1',
            }
          })
          // В историю не добавляем элементы без рабочего публичного изображения.
          .filter((x) => x.url && x.thumbnailUrl)
          .slice(0, 10)
        setFeedFallback(mapped)
      })
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [gallery.length])

  // В предпросмотре при загрузке страницы показываем последнюю генерацию.
  useEffect(() => {
    if (resultSeededRef.current || resultUrl || gallery.length === 0) return
    resultSeededRef.current = true
    setPreviewByMode((cur) => cur.text.kind === 'empty'
      ? { ...cur, text: { kind: 'history', url: gallery[0].url, shape: historyShape(gallery[0]), galleryId: gallery[0].id, promptOriginal: gallery[0].promptOriginal, title: 'Последняя генерация' } }
      : cur)
  }, [gallery, resultUrl])

  // Поллинг активной задачи — тот же контракт, что в основном UI (resultUrl).
  useEffect(() => {
    if (!job || !JOB_ACTIVE.includes(job.status)) return
    const timer = window.setInterval(async () => {
      try {
        const next: N2Job = await apiFetch(`/jobs/${job.id}`).then((r) => r.json())
        setJob(next)
        if (next.status === 'completed') {
          if (next.resultUrl) {
            setResultError(false)
            if (jobMode === 'paint') {
              setResultUrl(next.resultUrl)
            } else {
              const coreMode = jobMode as CoreStudioMode
              setPreviewByMode((cur) => ({
                ...cur,
                [coreMode]: {
                  kind: 'result',
                  url: next.resultUrl,
                  sourceUrl: pendingResultSourceRef.current[jobMode],
                  shape: pendingResultShapeRef.current[jobMode],
                  title: 'Результат генерации',
                  resultImageId: next.resultImageId,
                  error: false,
                },
              }))
            }
          }
          fetchGallery()
          void refreshAuthStateV2()
        } else if (next.status === 'failed') {
          setNotice(next.error || 'Генерация не удалась. Попробуйте ещё раз.')
        }
      } catch {
        /* сеть мигнула — следующий тик */
      }
    }, 900)
    return () => window.clearInterval(timer)
  }, [fetchGallery, job, jobMode])

  const promptKey: StudioMode = tab === 'i2i' ? 'i2i' : tab === 'edit' ? 'edit' : tab === 'face' ? 'face' : tab === 'paint' ? 'paint' : 'text'
  const setPrompt = useCallback(
    (value: string) => setPrompts((cur) => ({ ...cur, [promptKey]: value })),
    [promptKey],
  )

  useEffect(() => {
    const prev = noticeClearRef.current
    const source = sourceImage || ''
    const editSlotSignature = editSlots.map((slot) => `${slot.image || ''}:${slot.role}:${slot.takeNote || ''}`).join('|')
    const faceSlotSignature = faceSlots.map((slot) => `${slot.image || ''}:${slot.role}:${slot.takeNote || ''}`).join('|')
    const changed = prev.text !== prompts.text || prev.i2i !== prompts.i2i || prev.edit !== prompts.edit || prev.face !== prompts.face || prev.paint !== prompts.paint || prev.source !== source || prev.editSlots !== editSlotSignature || prev.faceSlots !== faceSlotSignature
    noticeClearRef.current = { text: prompts.text, i2i: prompts.i2i, edit: prompts.edit, face: prompts.face, paint: prompts.paint, source, editSlots: editSlotSignature, faceSlots: faceSlotSignature }
    if (notice && changed) setNotice('')
  }, [editSlots, faceSlots, notice, prompts.edit, prompts.face, prompts.i2i, prompts.paint, prompts.text, sourceImage])

  useEffect(() => {
    if (!notice) return undefined
    const timer = window.setTimeout(() => setNotice(''), 5000)
    return () => window.clearTimeout(timer)
  }, [notice])

  // Стиль в «По тексту»: приписываем текст стиля в промпт (замена предыдущего).
  // Вся строковая математика — вне setState-updater (updater обязан быть чистым:
  // под StrictMode он вызывается дважды, и мутация ref внутри него ломает замену).
  // targetTab передаётся явно: из Ленты стиль применяется к «По тексту»,
  // хотя state `tab` в замыкании ещё старый.
  function applyStyleTo(targetTab: 'text' | 'i2i', next: StylePreset | null) {
    setStyleId(next?.id || '')
    if (targetTab === 'i2i') {
      const applied = appliedI2IStyleRef.current
      let text = prompts.i2i
      if (applied && text.includes(applied.text)) text = text.replace(applied.text, '')
      if (next) {
        const addition = `${I2I_STYLE_PREFIX}${next.transformPrompt}`
        text = `${text.trimEnd()}${addition}`
        appliedI2IStyleRef.current = { id: next.id, text: addition }
      } else {
        appliedI2IStyleRef.current = null
      }
      setPrompts((cur) => ({ ...cur, i2i: text }))
      return
    }
    const applied = appliedStyleRef.current
    let text = prompts.text
    if (applied && text.includes(applied.text)) text = text.replace(applied.text, '')
    if (next) {
      const addition = `${STYLE_PREFIX}${next.stylePrompt}`
      text = `${text.trimEnd()}${addition}`
      appliedStyleRef.current = { id: next.id, text: addition }
    } else {
      appliedStyleRef.current = null
    }
    setPrompts((cur) => ({ ...cur, text }))
  }

  function applyStyle(next: StylePreset | null) {
    applyStyleTo(tab === 'i2i' ? 'i2i' : 'text', next)
  }

  function applyTemplate(templatePrompt: string) {
    appliedStyleRef.current = null
    setStyleId('')
    setPrompt(templatePrompt)
    setTemplatesOpen(false)
  }

  function appendI2ITemplate(templatePrompt: string) {
    setPrompts((cur) => ({
      ...cur,
      i2i: cur.i2i.trim() ? `${cur.i2i.trimEnd()}${PROMPT_APPEND_PREFIX}${templatePrompt}` : templatePrompt,
    }))
    showToast('Шаблон добавлен в промпт')
  }

  function randomPrompt() {
    if (tab === 'i2i') {
      appendI2ITemplate(randomOf(I2I_STYLES).transformPrompt)
    } else {
      applyTemplate(randomOf(T2I_TEMPLATES).prompt)
    }
  }

  function clearEditSlot(index: number) {
    if (inspectPreview && editSlots[index]?.image === inspectPreview.url) setInspectPreview(null)
    if (editSlots[index]?.image) {
      const removed = editSlots[index].image
      setPreviewByMode((cur) => cur.edit.url === removed || cur.edit.sourceUrl === removed ? { ...cur, edit: emptyPreview() } : cur)
    }
    setEditSlots((current) => current.map((slot, i) => (i === index ? { image: undefined, role: '', takeNote: '' } : slot)))
  }

  function clearFaceSlot(index: number) {
    if (inspectPreview && faceSlots[index]?.image === inspectPreview.url) setInspectPreview(null)
    if (faceSlots[index]?.image) {
      const removed = faceSlots[index].image
      setPreviewByMode((cur) => cur.face.url === removed || cur.face.sourceUrl === removed ? { ...cur, face: emptyPreview() } : cur)
    }
    setFaceSlots((current) => current.map((slot, i) => (i === index ? { ...slot, image: undefined } : slot)))
  }

  function setEditSlotRole(index: number, role: EditReferenceRole | '') {
    if (role === 'pose') {
      showToast('Поза временно недоступна')
      setNotice('Смена позы временно отключена: workflow нестабилен.')
      return
    }
    setEditSlots((current) => current.map((slot, i) => (i === index ? { ...slot, role } : slot)))
  }

  function setEditSlotTakeNote(index: number, takeNote: string) {
    setEditSlots((current) => current.map((slot, i) => (i === index ? { ...slot, takeNote } : slot)))
  }

  function openUpload(target: UploadTarget) {
    setUploadTarget(target)
    fileInputRef.current?.click()
  }

  function openGalleryPick(target: UploadTarget) {
    setGalleryPickTarget(target)
  }

  function showInspectPreview(url: string, title: string) {
    const coreMode = coreModeFromTab(tab)
    if (!coreMode) {
      setPaintWorkbenchVisible(false)
      setInspectPreview({ url, title })
    } else {
      setPreviewByMode((cur) => ({ ...cur, [coreMode]: { kind: 'inspect', url, title, shape: cur[coreMode].shape, error: false } }))
      void loadImageShape(url).then((shape) => {
        setPreviewByMode((cur) => {
          const current = cur[coreMode]
          return current.kind === 'inspect' && current.url === url ? { ...cur, [coreMode]: { ...current, shape } } : cur
        })
      })
    }
    setInspectZoom(1)
    setInspectPan({ x: 0, y: 0 })
    setResultError(false)
  }

  function applyImageToTarget(target: UploadTarget | null, image: string) {
    if (!target || target.kind === 'i2i') {
      setSourceImage(image)
      showInspectPreview(image, 'Исходное изображение')
      return
    }
    if (target.kind === 'paintSketch') {
      setPaintSketchImage(image)
      setPaintWorkbenchVisible(true)
      setPaintMode('sketch')
      setInspectPreview(null)
      resetInspectView()
      return
    }
    if (target.kind === 'face') {
      setFaceSlots((current) => current.map((slot, i) => (i === target.index ? { ...slot, image, role: target.index === 1 ? 'face' : slot.role } : slot)))
      showInspectPreview(image, target.index === 0 ? 'Основа' : 'Лицо')
      return
    }
    if (target.kind === 'paint') {
      setPaintImage(image)
      setPaintOutpaintPreview(undefined)
      setPaintWorkbenchVisible(true)
      setInspectPreview(null)
      resetInspectView()
      return
    }
    setEditSlots((current) => current.map((slot, i) => {
      if (i !== target.index) return slot
      return target.index > 0 ? { image, role: '', takeNote: '' } : { ...slot, image }
    }))
    showInspectPreview(image, target.index === 0 ? 'Основа' : `Референс ${target.index}`)
  }

  async function generate(mode: StudioMode) {
    if (inFlightRef.current || isSubmitting || jobActive) return
    const textPrompt = prompts.text.trim()
    const i2iPrompt = prompts.i2i.trim()
    const editPrompt = prompts.edit.trim()
    const facePrompt = prompts.face.trim()
    const i2iSource = sourceImage || ''
    const size = RESOLUTION_PRESETS.find((p) => p.id === resolutionId) || RESOLUTION_PRESETS[0]
    const editComposer = editComposerStatus({ slots: editSlots, userNote: editPrompt, manualMode: false, manualPrompt: '' })
    // Пустой запрос не запускает генерацию — показываем понятную подсказку.
    if (mode === 'text' && !textPrompt) {
      showToast('Опишите идею — что вы хотите увидеть')
      return
    }
    if (mode === 'i2i' && !sourceImage) {
      showToast('Добавьте исходное изображение')
      return
    }
    if (mode === 'i2i' && !(i2iPrompt || styleId)) {
      showToast('Опишите преобразование или выберите стиль')
      return
    }
    if (mode === 'edit' && editComposer.blockReason) {
      showToast(editComposer.blockReason)
      setNotice(editComposer.blockReason)
      return
    }
    if (mode === 'face') {
      const faceBlock = !faceSlots[0]?.image
        ? 'Загрузите изображение, куда вставляем лицо.'
        : !faceSlots[1]?.image
          ? 'Загрузите изображение с лицом.'
          : !faceLora?.id || faceLora.id === 'none'
            ? 'Face LoRA не найдена. Откройте старую версию или проверьте /api/models.'
            : null
      if (faceBlock) {
        showToast(faceBlock)
        setNotice(faceBlock)
        return
      }
    }
    if (mode === 'paint') {
      const paintBlock = paintMode === 'sketch' && paintLines.length === 0
        ? 'Нарисуйте эскиз на холсте.'
        : paintMode !== 'sketch' && !paintImage
          ? 'Загрузите изображение для этого режима.'
          : paintMode === 'mask' && paintLines.length === 0
            ? 'Закрасьте область маской.'
            : null
      if (paintBlock) {
        showToast(paintBlock)
        setNotice(paintBlock)
        return
      }
    }
    if (mode === 'text' && lastSubmittedRef.current.text === textPrompt) {
      showToast('Измените промпт перед новой генерацией')
      setNotice('Измените промпт перед новой генерацией.')
      return
    }
    if (mode === 'i2i') {
      const last = lastSubmittedRef.current.i2i
      if (last && last.prompt === i2iPrompt && last.source === i2iSource && last.width === size.width && last.height === size.height) {
        showToast('Измените промпт, формат или изображение')
        setNotice('Измените промпт, формат или исходное изображение перед новой генерацией.')
        return
      }
    }
    if (!(await ensureAuthed())) return
    inFlightRef.current = true
    setIsSubmitting(true)
    setNotice('')
    try {
      const style = I2I_STYLES.find((s) => s.id === styleId)
      const steps = QUALITY.find((q) => q.id === quality)?.steps || 4
      const effectiveSeed = seed || randomSeed()
      const requestSize = mode === 'face'
        ? await imageRequestSizeFromSource(faceSlots[0]?.image, size)
        : mode === 'paint' && paintMode === 'outpaint'
          ? size
        : mode === 'paint' && paintMode !== 'sketch'
          ? await imageRequestSizeFromSource(paintImage, size)
          : size
      const userText = mode === 'i2i' ? i2iPrompt : textPrompt
      // В обоих режимах пользователь видит финальный prompt в textarea:
      // text/i2i-стиль дописывается туда при выборе и может быть отредактирован.
      const fullPrompt = userText || (mode === 'i2i' ? style?.transformPrompt || '' : '')
      const isEditLikeMode = mode === 'edit' || mode === 'face'
      const activeEditSlots = mode === 'face' ? faceSlots : editSlots
      const paintCanvas = mode === 'paint' && paintMode === 'sketch' ? await createPaintSketchCanvas() : undefined
      const paintMask = mode === 'paint' && paintMode === 'mask' ? await createPaintMask(paintImage, paintLines, paintStageSize) : undefined
      const nextOutpaintPreview = mode === 'paint' && paintMode === 'outpaint' ? await createOutpaintPreview(paintImage, paintOutpaint, requestSize) : undefined
      const nextResultSource = mode === 'i2i' ? sourceImage : isEditLikeMode ? activeEditSlots[0]?.image : mode === 'paint' ? (paintMode === 'sketch' ? paintCanvas : nextOutpaintPreview || paintImage) : undefined
      const nextResultShape = shapeFromSize(requestSize.width, requestSize.height)
      if (mode === 'paint') setPaintOutpaintPreview(nextOutpaintPreview)
      const paintUserPrompt = prompts.paint.trim()
      const paintBasePrompt = paintTechPrompts[paintMode]
      const paintPrompt = composePaintPrompt(paintBasePrompt, paintUserPrompt)
      const faceFinalPrompt = [
        facePrompt,
        'Use Image 1 as the target scene. Use Image 2 only as the source face. Preserve the target body, clothing, pose, background, camera angle, lighting, and style.',
        faceStrengthPrompt(faceStrengthPct),
      ].filter(Boolean).join('\n\n')
      const body = {
        mode: mode === 'i2i'
          ? 'image_to_image'
          : mode === 'face'
            ? 'faceswap'
            : mode === 'edit'
              ? 'edit'
              : mode === 'paint'
                ? paintMode === 'sketch'
                  ? 'paint'
                  : paintMode === 'mask'
                    ? 'inpaint'
                    : paintMode === 'outpaint'
                      ? 'outpaint'
                      : 'remove_background'
                : 'text_to_image',
        provider,
        prompt: mode === 'edit' ? editComposer.finalPrompt : mode === 'face' ? faceFinalPrompt : mode === 'paint' ? paintPrompt : fullPrompt,
        negativePrompt: isEditLikeMode || mode === 'paint' ? '' : '',
        seed: effectiveSeed,
        width: requestSize.width,
        height: requestSize.height,
        steps,
        cfg: 1,
        guidance,
        strength: mode === 'edit' ? DEFAULT_EDIT_STRENGTH : mode === 'face' ? faceStrengthPct / 100 : strengthPct / 100,
        modelProfile: provider === 'comfyui' ? 'local_flux_klein' : 'openrouter_cloud',
        loras: mode === 'face' && faceLora ? [{ id: faceLora.id, strength: faceStrengthPct / 100, triggerWord: faceLora.triggerWord }] : [],
        inputImage1: mode === 'i2i' ? sourceImage : isEditLikeMode ? activeEditSlots[0]?.image : mode === 'paint' && paintMode !== 'sketch' ? paintImage : undefined,
        inputImage2: mode === 'face' ? activeEditSlots[1]?.image : undefined,
        inputImages: mode === 'edit'
          ? activeEditSlots
              .map((slot, index) => ({ slot, index }))
              .filter(({ slot }) => slot.image)
              .map(({ slot, index }) => ({ index: index + 1, role: index === 0 ? 'base' : slot.role, image: slot.image! }))
          : undefined,
        maskImage: mode === 'paint' && paintMode === 'mask' ? paintMask : undefined,
        canvas: mode === 'paint' && paintMode === 'sketch' ? paintCanvas : undefined,
        outpaint: mode === 'paint' && paintMode === 'outpaint' ? paintOutpaint : undefined,
        clientRequestId: newClientRequestId(),
      }
      const response = await apiFetch('/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!response.ok) {
        let detail = ''
        try {
          detail = (await response.json())?.detail || ''
        } catch {
          /* non-JSON */
        }
        if (response.status === 402) setNotice('Закончились токены. Пополните баланс в настройках основной версии.')
        else if (response.status === 401 || response.status === 403) {
          setNotice('Сессия истекла. Войдите снова, чтобы генерировать.')
          setAuthOpen(true)
        } else if (response.status === 429) setNotice(detail || 'Слишком много запросов подряд. Подождите немного.')
        else setNotice(detail || `Сервер вернул ошибку (${response.status}). Попробуйте ещё раз.`)
        return
      }
      const created: N2Job = await response.json()
      if (mode === 'i2i') lastSubmittedRef.current.i2i = { prompt: i2iPrompt, source: i2iSource, width: size.width, height: size.height }
      else lastSubmittedRef.current.text = textPrompt
      if (mode === 'paint') setPaintWorkbenchVisible(false)
      pendingResultSourceRef.current[mode] = nextResultSource
      pendingResultShapeRef.current[mode] = nextResultShape
      setJob(created)
      setJobMode(mode)
      setResultUrl(undefined)
      setInspectPreview(null)
      if (mode !== 'paint') {
        setPreviewByMode((cur) => ({ ...cur, [mode]: { kind: 'empty' } }))
      }
      resetInspectView()
      setResultSource(nextResultSource)
      setCompare(mode === 'i2i' || isEditLikeMode || mode === 'paint' ? 96 : 50)
      if (!seed && mode !== 'face') setSeed(effectiveSeed)
    } catch {
      setNotice('Проблема соединения с сервером. Проверьте, что сервис запущен.')
    } finally {
      inFlightRef.current = false
      setIsSubmitting(false)
    }
  }

  function onSourceFile(file: File | undefined) {
    if (!file) return
    resizeUploadImage(file)
      .then((image) => {
        applyImageToTarget(uploadTarget, image)
        setUploadTarget(null)
      })
      .catch(() => {
    const reader = new FileReader()
    reader.onload = () => {
      if (typeof reader.result !== 'string') return
      applyImageToTarget(uploadTarget, reader.result)
      setUploadTarget(null)
    }
    reader.readAsDataURL(file)
      })
  }

  function setPromptInfluence(value: number) {
    const next = Math.max(0, Math.min(100, Math.round(value)))
    setStrengthPct(Math.abs(next - 75) <= 3 ? 75 : next)
  }

  function setFaceStrength(value: number) {
    const next = Math.max(0, Math.min(100, Math.round(value)))
    setFaceStrengthPct(Math.abs(next - DEFAULT_FACE_STRENGTH) <= 3 ? DEFAULT_FACE_STRENGTH : next)
  }

  function applyLastSourceImage() {
    const last = visibleResultUrl || gallery[0]?.url || dockImage?.url || historyItems[0]?.url
    if (!last) {
      showToast('Последнего изображения пока нет')
      return
    }
    const image = apiUrl(last)
    setSourceImage(image)
    showInspectPreview(image, 'Исходное изображение')
  }

  function applyLastImageToTarget(target: UploadTarget) {
    const last = visibleResultUrl || gallery[0]?.url || dockImage?.url || historyItems[0]?.url
    if (!last) {
      showToast('Последнего изображения пока нет')
      return
    }
    applyImageToTarget(target, apiUrl(last))
  }

  function useCurrentPreviewInPaint() {
    const source = visibleInspectPreview?.url || visibleResultUrl
    if (!source) {
      showToast('Сначала выберите изображение в предпросмотре')
      return
    }
    applyImageToTarget(paintMode === 'sketch' ? { kind: 'paintSketch' } : { kind: 'paint' }, apiUrl(source))
  }

  function resetInspectView() {
    setInspectZoom(1)
    setInspectPan({ x: 0, y: 0 })
  }

  function onInspectWheel(e: ReactWheelEvent<HTMLDivElement>) {
    e.preventDefault()
    const rect = e.currentTarget.getBoundingClientRect()
    const localX = e.clientX - rect.left - rect.width / 2
    const localY = e.clientY - rect.top - rect.height / 2
    setInspectZoom((current) => {
      const next = Math.max(0.46, Math.min(5, current * (e.deltaY < 0 ? 1.16 : 0.86)))
      const ratio = next / current
      setInspectPan((pan) => Math.abs(next - 1) <= 0.02
        ? { x: 0, y: 0 }
        : {
            x: localX - (localX - pan.x) * ratio,
            y: localY - (localY - pan.y) * ratio,
          })
      return next
    })
  }

  function onInspectPointerDown(e: ReactPointerEvent<HTMLDivElement>) {
    if (Math.abs(inspectZoom - 1) <= 0.02) return
    inspectDragRef.current = { active: true, startX: e.clientX, startY: e.clientY, panX: inspectPan.x, panY: inspectPan.y }
    e.currentTarget.setPointerCapture(e.pointerId)
  }

  function onInspectPointerMove(e: ReactPointerEvent<HTMLDivElement>) {
    const drag = inspectDragRef.current
    if (!drag.active) return
    setInspectPan({ x: drag.panX + e.clientX - drag.startX, y: drag.panY + e.clientY - drag.startY })
  }

  function onInspectPointerUp(e: ReactPointerEvent<HTMLDivElement>) {
    inspectDragRef.current.active = false
    if (e.currentTarget.hasPointerCapture(e.pointerId)) e.currentTarget.releasePointerCapture(e.pointerId)
  }

  function touchDistance(touches: ReactTouchEvent<HTMLDivElement>['touches']) {
    if (touches.length < 2) return 0
    const a = touches[0]
    const b = touches[1]
    return Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY)
  }

  function onInspectTouchStart(e: ReactTouchEvent<HTMLDivElement>) {
    const touch = inspectTouchRef.current
    if (e.touches.length === 2) {
      e.preventDefault()
      touch.pinching = true
      touch.distance = touchDistance(e.touches)
      touch.zoom = inspectZoom
      touch.panX = inspectPan.x
      touch.panY = inspectPan.y
      return
    }
    if (e.touches.length !== 1) return
    const now = e.timeStamp
    const first = e.touches[0]
    touch.startX = first.clientX
    touch.startY = first.clientY
    touch.panX = inspectPan.x
    touch.panY = inspectPan.y
    if (now - touch.lastTap < 280) {
      e.preventDefault()
      if (inspectZoom > 1.05) resetInspectView()
      else {
        setInspectZoom(2.2)
        setInspectPan({ x: 0, y: 0 })
      }
      touch.lastTap = 0
    } else {
      touch.lastTap = now
    }
  }

  function onInspectTouchMove(e: ReactTouchEvent<HTMLDivElement>) {
    const touch = inspectTouchRef.current
    if (e.touches.length === 2 && touch.pinching) {
      e.preventDefault()
      const distance = touchDistance(e.touches)
      if (!touch.distance || !distance) return
      setInspectZoom(Math.max(1, Math.min(5, touch.zoom * (distance / touch.distance))))
      return
    }
    if (e.touches.length === 1 && inspectZoom > 1.02) {
      e.preventDefault()
      const first = e.touches[0]
      setInspectPan({
        x: touch.panX + first.clientX - touch.startX,
        y: touch.panY + first.clientY - touch.startY,
      })
    }
  }

  function onInspectTouchEnd(e: ReactTouchEvent<HTMLDivElement>) {
    if (e.touches.length < 2) inspectTouchRef.current.pinching = false
    if (inspectZoom <= 1.02) setInspectPan({ x: 0, y: 0 })
  }

  const jobActive = !!job && JOB_ACTIVE.includes(job.status)
  const jobProgress = Math.max(0, Math.min(100, Math.round(job?.progress || 0)))

  const ownHistory = gallery.slice(0, 12)
  // Своя история приоритетна; при её отсутствии показываем работы из Ленты.
  const historyItems = ownHistory.length > 0 ? ownHistory : feedFallback
  const historyIsFeed = ownHistory.length === 0 && feedFallback.length > 0
  const selectedResolution = RESOLUTION_PRESETS.find((p) => p.id === resolutionId) || RESOLUTION_PRESETS[0]
  const studioMode: StudioMode = tab === 'i2i' ? 'i2i' : tab === 'edit' ? 'edit' : tab === 'face' ? 'face' : tab === 'paint' ? 'paint' : 'text'
  const isI2IStudio = studioMode === 'i2i'
  const isEditStudio = studioMode === 'edit'
  const isFaceStudio = studioMode === 'face'
  const isPaintStudio = studioMode === 'paint'
  const activeCoreMode = coreModeFromTab(tab)
  const activeCorePreview = activeCoreMode ? previewByMode[activeCoreMode] : null
  const visibleInspectPreview = isPaintStudio
    ? inspectPreview
    : activeCorePreview?.kind === 'inspect' && activeCorePreview.url
      ? { url: activeCorePreview.url, title: activeCorePreview.title || 'Предпросмотр' }
      : null
  const visibleResultUrl = isPaintStudio
    ? resultUrl
    : (activeCorePreview?.kind === 'result' || activeCorePreview?.kind === 'history') && activeCorePreview.url
      ? activeCorePreview.url
      : undefined
  const visibleResultSource = isPaintStudio ? resultSource : activeCorePreview?.kind === 'result' ? activeCorePreview.sourceUrl : undefined
  const visibleResultError = isPaintStudio ? resultError : !!activeCorePreview?.error
  const previewJobActive = jobActive && (isPaintStudio ? jobMode === 'paint' : jobMode === studioMode)
  useEffect(() => {
    if (!visibleResultUrl || !visibleResultSource || previewJobActive) return undefined
    compareTouchedRef.current = false
    queueMicrotask(() => {
      setInspectZoom(1)
      setInspectPan({ x: 0, y: 0 })
      setCompareAuto(true)
      setCompare(96)
    })
    const moveTimer = window.setTimeout(() => {
      if (!compareTouchedRef.current) setCompare(4)
    }, 120)
    const stopTimer = window.setTimeout(() => setCompareAuto(false), 2300)
    return () => {
      window.clearTimeout(moveTimer)
      window.clearTimeout(stopTimer)
    }
  }, [previewJobActive, visibleResultSource, visibleResultUrl])
  const studioTitle = isI2IStudio ? 'По фото' : isEditStudio ? 'Сборка' : isFaceStudio ? 'Лицо' : isPaintStudio ? 'Редактор' : 'По тексту'
  const promptTitle = isI2IStudio ? 'Как преобразовать?' : isPaintStudio ? 'Что визуализируем?' : isEditStudio || isFaceStudio ? 'Дополнительные пожелания' : 'Что хотите увидеть?'
  const promptPlaceholder = isI2IStudio
    ? 'Опишите, как преобразовать исходное изображение...'
    : isFaceStudio
      ? 'Например: сохранить прическу и свет основы, взять только лицо...'
    : isPaintStudio
      ? paintMode === 'sketch'
        ? 'Опишите сцену, которую нужно получить из эскиза...'
        : paintMode === 'mask'
          ? 'Опишите, что должно появиться или измениться внутри маски...'
          : paintMode === 'outpaint'
            ? 'Опишите, что дорисовать в пустых краях кадра: фон, свет, детали, продолжение сцены...'
            : 'Опишите, что важно сохранить после удаления фона...'
    : isEditStudio
      ? 'Например: сохранить лицо, заменить одежду, взять фон или цвет из референса...'
    : 'Опишите идею своими словами — получите изображение...'
  const promptLimit = isI2IStudio || isEditStudio || isFaceStudio || isPaintStudio ? 1000 : 2000
  const promptValue = prompts[studioMode]
  const paintPromptDisplayValue = isPaintStudio && paintTechPromptOpen
    ? `${prompts.paint}${prompts.paint.trim() ? '\n\n' : ''}${paintTechPrompts[paintMode]}`
    : promptValue
  const promptTextareaValue = isPaintStudio ? paintPromptDisplayValue : promptValue
  const promptTextareaLimit = isPaintStudio && paintTechPromptOpen ? 2800 : promptLimit
  const promptCounterValue = promptTextareaValue.length

  function updatePromptTextarea(value: string) {
    if (isPaintStudio && paintTechPromptOpen) {
      const currentUserPrompt = prompts.paint
      if (!currentUserPrompt) {
        setPaintTechPrompts((cur) => ({ ...cur, [paintMode]: value }))
        return
      }
      if (value.startsWith(currentUserPrompt)) {
        setPaintTechPrompts((cur) => ({ ...cur, [paintMode]: value.slice(currentUserPrompt.length).replace(/^\n+/, '') }))
        return
      }
      const [nextUserPrompt = '', ...nextTechPrompt] = value.split(/\n{2,}/)
      setPrompt(nextUserPrompt)
      setPaintTechPrompts((cur) => ({ ...cur, [paintMode]: nextTechPrompt.join('\n\n') }))
      return
    }
    setPrompt(value)
  }

  useEffect(() => {
    if (tab !== 'paint' || !paintWorkbenchVisible) return undefined
    let observedNode: HTMLDivElement | null = null
    let frame = 0
    const timers: number[] = []
    const observer = new ResizeObserver(() => update())
    const update = () => {
      const node = paintWorkbenchRef.current
      if (!node) return
      const rect = node.getBoundingClientRect()
      if (rect.width < 160 || rect.height < 160) return
      const maxW = Math.max(256, rect.width - 36)
      const maxH = Math.max(256, rect.height - 36)
      const ratio = Math.max(0.1, selectedResolution.width / Math.max(1, selectedResolution.height))
      let width = maxW
      let height = width / ratio
      if (height > maxH) {
        height = maxH
        width = height * ratio
      }
      const next = { width: Math.max(1, Math.round(width)), height: Math.max(1, Math.round(height)) }
      setPaintStageSize((current) => current.width === next.width && current.height === next.height ? current : next)
    }
    const attach = () => {
      const node = paintWorkbenchRef.current
      if (!node) return
      if (observedNode !== node) {
        observer.disconnect()
        observer.observe(node)
        observedNode = node
      }
      update()
    }
    frame = window.requestAnimationFrame(attach)
    timers.push(window.setTimeout(attach, 80), window.setTimeout(attach, 240), window.setTimeout(attach, 600))
    window.addEventListener('resize', attach)
    return () => {
      window.cancelAnimationFrame(frame)
      timers.forEach((timer) => window.clearTimeout(timer))
      observer.disconnect()
      window.removeEventListener('resize', attach)
    }
  }, [paintMode, paintWorkbenchVisible, selectedResolution, tab])

  const loraOptions: LoraOption[] = (() => {
    const found = (modelsPayload?.loras || []).filter((item) => item && item !== 'none')
    if (!found.length) return FALLBACK_LORA_OPTIONS
    return [
      { id: 'none', label: 'None', triggerWord: '', strength: 0 },
      ...found.map((item) => ({
        id: item,
        label: item,
        triggerWord: loraTriggers[item] || '',
        strength: item.toLowerCase().includes('bfs') || item.toLowerCase().includes('face') || item.toLowerCase().includes('head') ? 1 : 0.8,
      })),
    ]
  })()
  const faceLora = (() => {
    const candidates = loraOptions.filter((item) => item.id !== 'none')
    return candidates.find((item) => /bfs|face|head/i.test(item.id)) || candidates[0]
  })()
  const generateLabel = isI2IStudio ? 'Преобразовать' : isEditStudio ? 'Создать изображение' : isFaceStudio ? 'Заменить лицо' : isPaintStudio ? paintMode === 'remove_bg' ? 'Удалить фон' : paintMode === 'outpaint' ? 'Расширить' : 'Создать по рисунку' : 'Сгенерировать'
  const generatingLabel = isI2IStudio ? 'Преобразуем...' : isEditStudio ? 'Создаём...' : isFaceStudio ? 'Заменяем...' : isPaintStudio ? 'Готовим рисунок...' : 'Генерируем...'
  const influenceStyle = { '--i2i-range-progress': `${strengthPct}%` } as CSSProperties
  const faceStrengthStyle = { '--i2i-range-progress': `${faceStrengthPct}%` } as CSSProperties
  const inspectImageStyle = {
    transform: `translate(${inspectPan.x}px, ${inspectPan.y}px) scale(${inspectZoom})`,
  } as CSSProperties
  const inspectToolsVisible = Math.abs(inspectZoom - 1) > 0.02
  const visibleEditSlots = editExtraOpen ? editSlots : editSlots.slice(0, 2)
  const editFilledCount = editSlots.filter((slot) => slot.image).length
  const faceFilledCount = faceSlots.filter((slot) => slot.image).length

  // Док «Промпт изображения»: если пользователь выбрал миниатюру — берём её из
  // видимой истории (своя или лента), чтобы клик по ленте синхронизировал промпт.
  // Без явного выбора показываем свою последнюю генерацию (но НЕ ленту, чтобы
  // промпт-блок не рассинхронизировался с пустым preview у гостя).
  const dockImage = dockImageId ? historyItems.find((g) => g.id === dockImageId) : gallery[0]
  const dockIsFeed = !!dockImage && dockImage.id.startsWith('feed-')
  const visibleGalleryImage = visibleResultUrl
    ? gallery.find((item) => item.id === activeCorePreview?.galleryId || apiUrl(item.url) === apiUrl(visibleResultUrl) || apiUrl(item.thumbnailUrl) === apiUrl(visibleResultUrl))
    : undefined
  const visiblePreviewShape = isPaintStudio
    ? selectedResolution.kind === 'vertical'
      ? 'tall'
      : selectedResolution.kind === 'horizontal'
        ? 'wide'
        : 'square'
    : activeCorePreview?.shape
      ? activeCorePreview.shape
    : visibleGalleryImage
      ? historyShape(visibleGalleryImage)
      : selectedResolution.kind === 'vertical'
        ? 'tall'
        : selectedResolution.kind === 'horizontal'
          ? 'wide'
          : 'square'
  // Фон preview во время генерации: текущая работа/история/стиль как размытая
  // подложка; если ничего нет — брендовый placeholder (в CSS).
  const loadingBackdropUrl = hoverStyle
    ? hoverStyle.preview[previewGender]
    : dockImage
      ? apiUrl(dockImage.url)
      : gallery[0]
        ? apiUrl(gallery[0].url)
        : undefined

  // v3-студия: выбрать формат (соотношение сторон) — переключает разрешение на
  // первый пресет нужной ориентации.
  const selectRatio = (kind: 'square' | 'vertical' | 'horizontal') => {
    const preset = RESOLUTION_PRESETS.find((p) => p.kind === kind)
    if (preset) setResolutionId(preset.id)
  }

  // Формат-дропдаун: класс shape-иконки и локализованный тип разрешения.
  const ratioIconClass = (kind: 'square' | 'vertical' | 'horizontal') =>
    kind === 'vertical' ? 'tall' : kind === 'horizontal' ? 'wide' : ''

  // Закрытие формат-дропдауна по клику вне него.
  useEffect(() => {
    if (!formatOpen) return
    const onDoc = (e: MouseEvent) => {
      if (formatRef.current && !formatRef.current.contains(e.target as Node)) setFormatOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [formatOpen])

  const copyPrompt = (text: string) => {
    if (!text) return
    void navigator.clipboard?.writeText(text).then(() => {
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1400)
    })
  }

  // Открыть миниатюру истории в предпросмотре + доке промпта.
  const openHistory = (item: N2GalleryImage) => {
    setResultError(false)
    setInspectPreview(null)
    resetInspectView()
    const coreMode = coreModeFromTab(tab)
    if (coreMode) {
      setPreviewByMode((cur) => ({
        ...cur,
        [coreMode]: {
          kind: 'history',
          url: item.url,
          shape: historyShape(item),
          title: 'История',
          galleryId: item.id,
          promptOriginal: item.promptOriginal,
          error: false,
        },
      }))
    } else {
      setResultUrl(item.url)
      setResultSource(undefined)
    }
    setDockImageId(item.id)
    if (isPaintStudio) setPaintWorkbenchVisible(false)
  }

  const scrollHistory = (dir: -1 | 1) => {
    const strip = historyStripRef.current
    if (strip) strip.scrollBy({ left: dir * Math.max(160, strip.clientWidth * 0.7), behavior: 'smooth' })
  }

  // Drag-скролл ленты истории мышью/тачем (как у ряда стилей). Клик после drag
  // не выбирает миниатюру; обычный клик — выбирает.
  useEffect(() => {
    const strip = historyStripRef.current
    if (!strip) return
    const st = { down: false, startX: 0, startScroll: 0 }
    const onWheel = (e: WheelEvent) => {
      if (strip.scrollWidth <= strip.clientWidth) return
      const d = Math.abs(e.deltaY) >= Math.abs(e.deltaX) ? e.deltaY : e.deltaX
      if (!d) return
      strip.scrollLeft += d
      e.preventDefault()
    }
    const onDown = (e: PointerEvent) => {
      st.down = true
      historyDraggedRef.current = false
      st.startX = e.clientX
      st.startScroll = strip.scrollLeft
    }
    const onMove = (e: PointerEvent) => {
      if (!st.down) return
      const dx = e.clientX - st.startX
      if (Math.abs(dx) > 4) {
        historyDraggedRef.current = true
        strip.classList.add('dragging')
      }
      strip.scrollLeft = st.startScroll - dx
    }
    const onUp = () => {
      st.down = false
      strip.classList.remove('dragging')
    }
    strip.addEventListener('wheel', onWheel, { passive: false })
    strip.addEventListener('pointerdown', onDown)
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
    return () => {
      strip.removeEventListener('wheel', onWheel)
      strip.removeEventListener('pointerdown', onDown)
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
    }
  }, [tab, historyItems.length])

  // Auto-grow главного prompt на мобильном: высота по контенту до max-height,
  // затем внутренний скролл. На desktop высоту не трогаем — там resize вручную.
  useEffect(() => {
    const ta = promptTextareaRef.current
    if (!ta) return
    if (!window.matchMedia('(max-width: 820px)').matches) {
      ta.style.height = ''
      return
    }
    ta.style.height = 'auto'
    const max = Math.round(window.innerHeight * 0.34)
    ta.style.height = `${Math.min(ta.scrollHeight, max)}px`
  }, [prompts.text, prompts.i2i, prompts.edit, prompts.face, prompts.paint, tab])

  // Горизонтальный скролл ряда стилей: колесо мыши + drag (мышь/тач).
  // Если пользователь тянул ряд — клик по карточке не выбирает стиль (styleDraggedRef).
  useEffect(() => {
    const row = styleRowRef.current
    if (!row) return
    const st = { down: false, startX: 0, startScroll: 0 }
    const onWheel = (e: WheelEvent) => {
      if (row.scrollWidth <= row.clientWidth) return
      const d = Math.abs(e.deltaY) >= Math.abs(e.deltaX) ? e.deltaY : e.deltaX
      if (!d) return
      row.scrollLeft += d
      e.preventDefault()
    }
    const onDown = (e: PointerEvent) => {
      st.down = true
      stylePointerDownRef.current = true
      styleDraggedRef.current = false
      setHoverStyle(null) // на время взаимодействия убираем hover-preview
      st.startX = e.clientX
      st.startScroll = row.scrollLeft
    }
    const onMove = (e: PointerEvent) => {
      if (!st.down) return
      const dx = e.clientX - st.startX
      if (Math.abs(dx) > 4) {
        styleDraggedRef.current = true
        row.classList.add('dragging')
      }
      row.scrollLeft = st.startScroll - dx
    }
    const onUp = () => {
      st.down = false
      stylePointerDownRef.current = false
      row.classList.remove('dragging')
    }
    row.addEventListener('wheel', onWheel, { passive: false })
    row.addEventListener('pointerdown', onDown)
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
    return () => {
      row.removeEventListener('wheel', onWheel)
      row.removeEventListener('pointerdown', onDown)
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
    }
  }, [tab])

  // /feed is the backend static product page; keep no React feed surface here.


  // ————————————————————————————————————————————————————————————————
  // v3-студия: общий экран для «По тексту» и «По фото».
  // ————————————————————————————————————————————————————————————————
  // Промпт выбранного изображения; у ленты без промпта — честный fallback.
  const dockPromptText = dockImage
    ? dockImage.promptOriginal || (dockIsFeed ? 'Промпт недоступен' : '')
    : prompts.text
  const ratioKind = selectedResolution.kind
  const shareTarget = visibleGalleryImage
  const previewNoticeText = notice || toastText
  const paintModeMeta: Record<PaintSubMode, { label: string; hint: string }> = {
    sketch: { label: 'Эскиз', hint: 'Нарисуйте идею на холсте. Модель превратит рисунок в изображение.' },
    mask: { label: 'Маска', hint: 'Загрузите изображение и закрасьте область, которую нужно изменить.' },
    outpaint: { label: 'Расширение', hint: 'Загрузите изображение и задайте поля для дорисовки.' },
    remove_bg: { label: 'Удалить фон', hint: 'Загрузите изображение. Результат вернётся с прозрачным фоном.' },
  }
  const paintReturnLabel: Record<PaintSubMode, string> = {
    sketch: 'К эскизу',
    mask: 'К маске',
    outpaint: 'К расширению',
    remove_bg: 'К удалению фона',
  }

  function choosePaintMode(id: PaintSubMode) {
    setPaintMode(id)
    setPaintToolsOpen(false)
    if (id === 'sketch') {
      setPaintTool('brush')
      setPaintBrushSize(3)
    } else if (id === 'mask') {
      setPaintTool('brush')
      setPaintDrawMode('free')
      setPaintBrushSize(25)
    }
    setPaintWorkbenchVisible(true)
    setResultError(false)
    setInspectPreview(null)
    resetInspectView()
    setPaintOutpaintPreview(undefined)
  }

  function updateOutpaintPadding(key: 'left' | 'right' | 'top' | 'bottom', value: number) {
    setPaintOutpaint((cur) => {
      const next = { ...cur, [key]: value }
      const frameW = Math.max(1, cur.frameW || paintStageSize.width)
      const frameH = Math.max(1, cur.frameH || paintStageSize.height)
      const aspect = Math.max(0.05, (cur.sourceW && cur.sourceH) ? cur.sourceW / cur.sourceH : frameW / frameH)
      const horizontalEdit = key === 'left' || key === 'right'
      const sourceW = horizontalEdit
        ? Math.max(48, frameW - Math.max(0, next.left) - Math.max(0, next.right))
        : Math.max(48, Math.min(frameW * 4, Math.max(48, frameH - Math.max(0, next.top) - Math.max(0, next.bottom)) * aspect))
      const sourceH = horizontalEdit
        ? Math.max(48, Math.min(frameH * 4, sourceW / aspect))
        : Math.max(48, frameH - Math.max(0, next.top) - Math.max(0, next.bottom))
      return {
        ...next,
        frameW,
        frameH,
        sourceX: horizontalEdit ? Math.max(0, next.left) : Math.round((frameW - sourceW) / 2),
        sourceY: horizontalEdit ? Math.round((frameH - sourceH) / 2) : Math.max(0, next.top),
        sourceW: Math.round(sourceW),
        sourceH: Math.round(sourceH),
      }
    })
  }

  function markVisiblePreviewError() {
    if (isPaintStudio) {
      setResultError(true)
      return
    }
    if (!activeCoreMode) return
    setPreviewByMode((cur) => ({ ...cur, [activeCoreMode]: { ...cur[activeCoreMode], error: true } }))
  }

  async function createPaintSketchCanvas() {
    const stageUrl = paintStageRef.current?.toDataURL()
    if (!paintSketchImage) return stageUrl
    const canvas = document.createElement('canvas')
    canvas.width = paintStageSize.width
    canvas.height = paintStageSize.height
    const ctx = canvas.getContext('2d')
    if (!ctx) return stageUrl || paintSketchImage
    ctx.fillStyle = paintCanvasBg === 'white' ? '#ffffff' : '#2b2f2c'
    ctx.fillRect(0, 0, canvas.width, canvas.height)
    const sketch = await loadHtmlImage(apiUrl(paintSketchImage))
    if (sketch) {
      const scale = Math.min(canvas.width / sketch.naturalWidth, canvas.height / sketch.naturalHeight)
      const width = sketch.naturalWidth * scale
      const height = sketch.naturalHeight * scale
      ctx.drawImage(sketch, (canvas.width - width) / 2, (canvas.height - height) / 2, width, height)
    }
    if (stageUrl) {
      const overlay = await loadHtmlImage(stageUrl)
      if (overlay) ctx.drawImage(overlay, 0, 0, canvas.width, canvas.height)
    }
    return canvas.toDataURL('image/png')
  }

  const paintWorkbench = (
    <Suspense fallback={<div ref={paintWorkbenchRef} className="paint-workbench paint-workbench-loading">Загружаем редактор рисунка...</div>}>
      <PaintWorkbench
        ref={paintStageRef}
        apiUrl={apiUrl}
        workbenchRef={paintWorkbenchRef}
        paintMode={paintMode}
        paintImage={paintImage}
        paintSketchImage={paintSketchImage}
        paintOutpaintPreview={paintOutpaintPreview}
        paintOutpaint={paintOutpaint}
        setPaintOutpaint={setPaintOutpaint}
        paintStageSize={paintStageSize}
        paintLines={paintLines}
        setPaintLines={setPaintLines}
        paintTool={paintTool}
        setPaintTool={setPaintTool}
        paintDrawMode={paintDrawMode}
        setPaintDrawMode={setPaintDrawMode}
        paintBrushSize={paintBrushSize}
        paintColor={paintColor}
        setPaintColor={setPaintColor}
        paintCanvasBg={paintCanvasBg}
        onUploadImage={() => openUpload(paintMode === 'sketch' ? { kind: 'paintSketch' } : { kind: 'paint' })}
        onPickGallery={() => openGalleryPick(paintMode === 'sketch' ? { kind: 'paintSketch' } : { kind: 'paint' })}
        onUseLastImage={() => applyLastImageToTarget(paintMode === 'sketch' ? { kind: 'paintSketch' } : { kind: 'paint' })}
        onRemoveImage={() => {
          if (paintMode === 'sketch') {
            setPaintSketchImage(undefined)
            setPaintSketchLines([])
          } else {
            setPaintImage(undefined)
            setPaintOutpaintPreview(undefined)
            setPaintMaskLines([])
          }
        }}
      />
    </Suspense>
  )

  const renderEditorSlot = (slot: EditSlot, index: number) => {
    const isBase = index === 0
    const target: UploadTarget = { kind: 'edit', index }
    const title = isBase ? 'Основа' : `Референс ${index}`
    const subtitle = isBase ? 'На что применяем изменения' : 'Что берём из изображения'
    return (
      <article className={`editor-slot editor-ref-card${slot.image ? ' is-filled' : ''}`} key={index}>
        <div className="editor-slot-title editor-ref-header">
          <div>
            <strong>{title}</strong>
            <span>{subtitle}</span>
          </div>
        </div>
        <article className={`i2i-upload-card editor-upload-card${slot.image ? ' is-filled' : ''}${isBase ? ' is-required' : ''}`}>
          {isBase && !slot.image && <span className="i2i-required-chip">Обязательно</span>}
          {slot.image && (
            <button className="i2i-remove" type="button" aria-label={`Удалить ${title.toLowerCase()}`} onClick={() => clearEditSlot(index)}>
              ×
            </button>
          )}
          <div className="i2i-preview">
            {slot.image ? (
              <button className="editor-preview-open" type="button" aria-label={`Показать ${title.toLowerCase()} в предпросмотре`} onClick={() => showInspectPreview(slot.image!, title)}>
                <img src={apiUrl(slot.image)} alt={title} />
              </button>
            ) : (
              <div className="i2i-upload-empty">
                <svg className="i2i-upload-icon" width="32" height="32" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                  <path d="M7 18.5h10a4 4 0 0 0 .6-7.96A6 6 0 0 0 6.4 8.7 4.8 4.8 0 0 0 7 18.5Z" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
                  <path d="M12 15V9.5m0 0-2.3 2.3M12 9.5l2.3 2.3" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
                <div className="i2i-upload-actions">
                  <button className="i2i-upload-action primary" type="button" onClick={() => openUpload(target)}>
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                      <path d="M12 16V6m0 0-4 4m4-4 4 4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                      <path d="M5 18.5h14" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                    </svg>
                    Загрузить
                  </button>
                  <button className="i2i-upload-action" type="button" onClick={() => openGalleryPick(target)}>
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                      <path d="M4 5h16v14H4V5Z" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
                      <path d="m7 15 3.2-3.2 2.4 2.4 2.2-2.7L20 17" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
                      <path d="M8.4 8.6h.1" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" />
                    </svg>
                    Галерея
                  </button>
                  <button className="i2i-upload-action" type="button" onClick={() => applyLastImageToTarget(target)}>
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                      <path d="M5 7v5h5" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" />
                      <path d="M5.6 12a6.6 6.6 0 1 0 1.9-4.7L5 9.8" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" />
                      <path d="M12 8.5V12l2.2 1.4" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                    Последнее
                  </button>
                </div>
              </div>
            )}
          </div>
          {!isBase && slot.image && (
            <div className="editor-role-controls">
              <label>
                <span>Что взять из картинки</span>
                <select
                  className="editor-role-select"
                  value={slot.role}
                  aria-label={`Роль для ${title.toLowerCase()}`}
                  onChange={(e) => setEditSlotRole(index, e.target.value as EditReferenceRole | '')}
                >
                  <option value="">Выберите роль</option>
                  {EDIT_SELECTABLE_REFERENCE_ROLES.map((role) => (
                    <option key={role} value={role} disabled={EDIT_DISABLED_REFERENCE_ROLES.includes(role)}>
                      {EDIT_REFERENCE_ROLE_LABELS[role]}
                    </option>
                  ))}
                </select>
              </label>
              {slot.role === 'other' && (
                <input
                  className="editor-role-note"
                  type="text"
                  maxLength={120}
                  placeholder="Например: материал, предмет, настроение..."
                  value={slot.takeNote || ''}
                  onChange={(e) => setEditSlotTakeNote(index, e.target.value)}
                />
              )}
            </div>
          )}
        </article>
      </article>
    )
  }

  const renderFaceSlot = (slot: EditSlot, index: number) => {
    const isBase = index === 0
    const target: UploadTarget = { kind: 'face', index }
    const title = isBase ? 'Основа' : 'Лицо'
    const subtitle = isBase ? 'Куда вставляем лицо' : 'Изображение с лицом'
    return (
      <article className={`editor-slot editor-ref-card face-slot${slot.image ? ' is-filled' : ''}`} key={index}>
        <div className="editor-slot-title editor-ref-header">
          <div>
            <strong>{title}</strong>
            <span>{subtitle}</span>
          </div>
        </div>
        <article className={`i2i-upload-card editor-upload-card face-upload-card${slot.image ? ' is-filled' : ''} is-required`}>
          {!slot.image && <span className="i2i-required-chip">{isBase ? 'Обязательно' : 'Лицо'}</span>}
          {slot.image && (
            <button className="i2i-remove" type="button" aria-label={`Удалить ${title.toLowerCase()}`} onClick={() => clearFaceSlot(index)}>
              ×
            </button>
          )}
          <div className="i2i-preview">
            {slot.image ? (
              <button className="editor-preview-open" type="button" aria-label={`Показать ${title.toLowerCase()} в предпросмотре`} onClick={() => showInspectPreview(slot.image!, title)}>
                <img src={apiUrl(slot.image)} alt={title} />
              </button>
            ) : (
              <div className="i2i-upload-empty">
                <svg className="i2i-upload-icon" width="32" height="32" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                  <path d="M7 18.5h10a4 4 0 0 0 .6-7.96A6 6 0 0 0 6.4 8.7 4.8 4.8 0 0 0 7 18.5Z" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
                  <path d="M12 15V9.5m0 0-2.3 2.3M12 9.5l2.3 2.3" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
                <div className="i2i-upload-actions">
                  <button className="i2i-upload-action primary" type="button" onClick={() => openUpload(target)}>
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                      <path d="M12 16V6m0 0-4 4m4-4 4 4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                      <path d="M5 18.5h14" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                    </svg>
                    Загрузить
                  </button>
                  <button className="i2i-upload-action" type="button" onClick={() => openGalleryPick(target)}>
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                      <path d="M4 5h16v14H4V5Z" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
                      <path d="m7 15 3.2-3.2 2.4 2.4 2.2-2.7L20 17" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
                      <path d="M8.4 8.6h.1" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" />
                    </svg>
                    Галерея
                  </button>
                  <button className="i2i-upload-action" type="button" onClick={() => applyLastImageToTarget(target)}>
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                      <path d="M5 7v5h5" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" />
                      <path d="M5.6 12a6.6 6.6 0 1 0 1.9-4.7L5 9.8" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" />
                      <path d="M12 8.5V12l2.2 1.4" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                    Последнее
                  </button>
                </div>
              </div>
            )}
          </div>
        </article>
      </article>
    )
  }

  const studio = (
    <main className="layout">
      <aside className="sidebar">
        <div className="sidebar-head">
          <h1>{studioTitle}</h1>
          <button className={`pro-button${proMode ? ' active' : ''}`} type="button" onClick={() => setProMode((v) => !v)}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <path d="m4 19 1.4-11 4.4 4.4L12 5l2.2 7.4L18.6 8 20 19H4Z" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
            </svg>
            {proMode ? 'Режим Стандарт' : 'Режим Профи'}
          </button>
        </div>

        {isI2IStudio && (
          <section className="form-section i2i-source-section">
            <div className="section-title">
              <h2>Исходное изображение</h2>
              <span className={`i2i-source-status${sourceImage ? ' filled' : ' required'}`}>
                {sourceImage ? '1 изображение' : 'обязательно'}
              </span>
            </div>
            <div className="i2i-source-grid">
              <article className={`i2i-upload-card${sourceImage ? ' is-filled' : ''}`}>
                {!sourceImage && <span className="i2i-required-chip">Обязательно</span>}
                {sourceImage && (
                  <button className="i2i-remove" type="button" aria-label="Удалить исходное изображение" onClick={() => {
                    const removed = sourceImage
                    setSourceImage(undefined)
                    if (removed) setPreviewByMode((cur) => cur.i2i.url === removed || cur.i2i.sourceUrl === removed ? { ...cur, i2i: emptyPreview() } : cur)
                  }}>
                    ×
                  </button>
                )}
                <div className="i2i-preview">
                  {sourceImage ? (
                    <button
                      className="editor-preview-open i2i-preview-open"
                      type="button"
                      aria-label="Показать исходное изображение в предпросмотре"
                      onClick={() => showInspectPreview(sourceImage, 'Исходное изображение')}
                    >
                      <img src={apiUrl(sourceImage)} alt="Исходное изображение" />
                    </button>
                  ) : (
                    <div className="i2i-upload-empty">
                      <svg className="i2i-upload-icon" width="32" height="32" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                        <path d="M7 18.5h10a4 4 0 0 0 .6-7.96A6 6 0 0 0 6.4 8.7 4.8 4.8 0 0 0 7 18.5Z" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
                        <path d="M12 15V9.5m0 0-2.3 2.3M12 9.5l2.3 2.3" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
                      </svg>
                      <div className="i2i-upload-actions">
                        <button className="i2i-upload-action primary" type="button" onClick={() => openUpload({ kind: 'i2i' })}>
                          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                            <path d="M12 16V6m0 0-4 4m4-4 4 4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                            <path d="M5 18.5h14" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                          </svg>
                          Загрузить
                        </button>
                        <button className="i2i-upload-action" type="button" onClick={() => openGalleryPick({ kind: 'i2i' })}>
                          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                            <path d="M4 5h16v14H4V5Z" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
                            <path d="m7 15 3.2-3.2 2.4 2.4 2.2-2.7L20 17" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
                            <path d="M8.4 8.6h.1" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" />
                          </svg>
                          Галерея
                        </button>
                        <button className="i2i-upload-action" type="button" onClick={applyLastSourceImage}>
                          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                            <path d="M5 7v5h5" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" />
                            <path d="M5.6 12a6.6 6.6 0 1 0 1.9-4.7L5 9.8" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" />
                            <path d="M12 8.5V12l2.2 1.4" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" />
                          </svg>
                          Последнее
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              </article>

              <article className="i2i-influence-card">
                <div className="i2i-influence-head">
                  <h3>Влияние промпта</h3>
                  <label className="i2i-strength-value">
                    <input
                      type="number"
                      min="0"
                      max="100"
                      step="1"
                      value={strengthPct}
                      aria-label="Значение влияния промпта в процентах"
                      onFocus={(e) => e.currentTarget.select()}
                      onChange={(e) => setPromptInfluence(Number(e.target.value))}
                    />
                    <span>%</span>
                  </label>
                </div>
                <div className="i2i-range-wrap" style={influenceStyle}>
                  <div className="i2i-range-scale" aria-hidden="true">
                    <span className="i2i-range-edge start">0</span>
                    <span className="i2i-range-edge end">100</span>
                  </div>
                  <button className="i2i-range-mark" type="button" onClick={() => setPromptInfluence(75)}>
                    75
                  </button>
                  <input
                    className="i2i-range"
                    type="range"
                    min="0"
                    max="100"
                    step="1"
                    value={strengthPct}
                    aria-label="Влияние промпта"
                    aria-valuetext={`${strengthPct}%`}
                    onChange={(e) => setPromptInfluence(Number(e.target.value))}
                  />
                </div>
                <div className="i2i-range-legend">
                  <span><span className="i2i-range-arrow">←</span> ближе к фото</span>
                  <span>больше промпта <span className="i2i-range-arrow">→</span></span>
                </div>
                <p>Рекомендуем 75%. Ниже сохраняет исходник, выше сильнее следует описанию.</p>
              </article>
            </div>
          </section>
        )}

        {isEditStudio && (
          <section className="form-section i2i-source-section editor-source-section">
            <div className="section-title">
              <h2>Изображения</h2>
              <span className={`i2i-source-status${editSlots[0]?.image ? ' filled' : ' required'}`}>
                {editSlots[0]?.image ? `${editFilledCount} из ${EDIT_SLOT_COUNT}` : `${visibleEditSlots.length} из ${EDIT_SLOT_COUNT}`}
              </span>
            </div>
            <div className="editor-source-grid">
              {visibleEditSlots.map(renderEditorSlot)}
            </div>
            <button className="editor-extra-toggle" type="button" onClick={() => setEditExtraOpen((open) => !open)}>
              {editExtraOpen ? 'Скрыть референсы' : 'Еще референсы'}
            </button>
          </section>
        )}

        {isFaceStudio && (
          <section className="form-section i2i-source-section editor-source-section face-source-section">
            <div className="section-title">
              <h2>Изображения</h2>
              <span className={`i2i-source-status${faceFilledCount === 2 ? ' filled' : ' required'}`}>
                {faceFilledCount} из 2
              </span>
            </div>
            <div className="editor-source-grid face-source-grid">
              {faceSlots.map(renderFaceSlot)}
            </div>
            <article className="face-strength-card">
              <div className="i2i-influence-head">
                <h3>Сила замены лица</h3>
                <label className="i2i-strength-value">
                  <input
                    type="number"
                    min="0"
                    max="100"
                    step="1"
                    value={faceStrengthPct}
                    aria-label="Сила замены лица в процентах"
                    onFocus={(e) => e.currentTarget.select()}
                    onChange={(e) => setFaceStrength(Number(e.target.value))}
                  />
                  <span>%</span>
                </label>
              </div>
              <div className="i2i-range-wrap" style={faceStrengthStyle}>
                <div className="i2i-range-scale" aria-hidden="true">
                  <span className="i2i-range-edge start">0</span>
                  <span className="i2i-range-edge end">100</span>
                </div>
                <button className="i2i-range-mark face-range-mark" type="button" onClick={() => setFaceStrength(DEFAULT_FACE_STRENGTH)}>
                  {faceStrengthPct}
                </button>
                <input
                  className="i2i-range"
                  type="range"
                  min="0"
                  max="100"
                  step="1"
                  value={faceStrengthPct}
                  aria-label="Сила замены лица"
                  aria-valuetext={`${faceStrengthPct}%`}
                  onChange={(e) => setFaceStrength(Number(e.target.value))}
                />
              </div>
              <div className="i2i-range-legend">
                <span><span className="i2i-range-arrow">←</span> мягче</span>
                <span>сильнее лицо <span className="i2i-range-arrow">→</span></span>
              </div>
              <p>Рекомендуем 75%. Ниже мягче смешивает лицо, выше сильнее переносит черты.</p>
            </article>
          </section>
        )}

        {isPaintStudio && (
          <section className="form-section paint-panel-section">
            <div className="section-title">
              <h2>Режим рисунка</h2>
              <span>{paintModeMeta[paintMode].label}</span>
            </div>
            <label className="paint-mode-select">
              <span>Режим</span>
              <select value={paintMode} onChange={(e) => choosePaintMode(e.target.value as PaintSubMode)}>
                {(Object.keys(paintModeMeta) as PaintSubMode[]).map((id) => (
                  <option value={id} key={id}>{paintModeMeta[id].label}</option>
                ))}
              </select>
            </label>
            <div className="paint-mode-tabs" role="tablist" aria-label="Режимы рисунка">
              {(Object.keys(paintModeMeta) as PaintSubMode[]).map((id) => (
                <button
                  key={id}
                  className={paintMode === id ? 'active' : ''}
                  type="button"
                  onClick={() => choosePaintMode(id)}
                >
                  <span className="paint-tab-label">{paintModeMeta[id].label}</span>
                  <span className="paint-tab-state">
                    {id === 'sketch'
                      ? paintSketchLines.length ? 'есть эскиз' : 'пусто'
                      : id === 'mask'
                        ? paintMaskLines.length ? 'есть маска' : 'пусто'
                        : id === 'outpaint'
                          ? paintImage ? 'изображение' : 'пусто'
                          : paintImage ? 'готово' : 'пусто'}
                  </span>
                  <span className="paint-tab-indicator" aria-hidden="true"></span>
                </button>
              ))}
            </div>
            <div className={`paint-mode-panel mode-${paintMode}`}>
              <div className="paint-panel-head">
                <strong>{paintModeMeta[paintMode].label}</strong>
                <span>{paintModeMeta[paintMode].hint}</span>
              </div>

              {(paintMode === 'sketch' || paintMode === 'mask') && (
                <div className="paint-toolbox">
                  <button
                    className={`paint-tools-toggle${paintToolsOpen ? ' active' : ''}`}
                    type="button"
                    aria-expanded={paintToolsOpen}
                    onClick={() => setPaintToolsOpen((open) => !open)}
                  >
                    <SlidersHorizontal size={17} strokeWidth={2.2} aria-hidden="true" />
                    <span>{paintMode === 'sketch' ? 'Инструменты эскиза' : 'Инструменты маски'}</span>
                    <ChevronDown size={17} strokeWidth={2.2} aria-hidden="true" />
                  </button>
                  <div className={`paint-tools-body${paintToolsOpen ? ' is-open' : ''}`}>
                    <div className="paint-sidebar-tools" aria-label="Инструменты рисования">
                      <button className={`paint-tool-brush${paintTool === 'brush' && paintDrawMode === 'free' ? ' active' : ''}`} type="button" title="Кисть" aria-label="Кисть" onClick={() => { setPaintTool('brush'); setPaintDrawMode('free') }}><Brush size={18} strokeWidth={2.2} /></button>
                      {paintMode === 'sketch' && (
                        <label className="paint-tool-color paint-mobile-color" title="Цвет кисти" aria-label="Цвет кисти">
                          <span className="paint-color-dot inline" style={{ '--paint-color': paintColor } as CSSProperties}><Palette size={14} strokeWidth={2.2} aria-hidden="true" /><input type="color" value={paintColor} onChange={(e) => setPaintColor(e.target.value)} /></span>
                        </label>
                      )}
                      <button className={`paint-tool-eraser${paintTool === 'eraser' ? ' active' : ''}`} type="button" title="Ластик" aria-label="Ластик" onClick={() => { setPaintTool('eraser'); setPaintDrawMode('free') }}><Eraser size={18} strokeWidth={2.2} /></button>
                      {paintMode === 'sketch' && (
                        <>
                          <button className={`paint-tool-line${paintDrawMode === 'line' ? ' active' : ''}`} type="button" title="Линия" aria-label="Линия" onClick={() => { setPaintTool('brush'); setPaintDrawMode('line') }}><Slash size={19} strokeWidth={2.6} /></button>
                          <button className={`paint-tool-rect-fill${paintDrawMode === 'rect-fill' ? ' active' : ''}`} type="button" title="Залитый прямоугольник" aria-label="Залитый прямоугольник" onClick={() => { setPaintTool('brush'); setPaintDrawMode('rect-fill') }}><span className="paint-shape-icon rect filled" /></button>
                          <button className={`paint-tool-rect-outline${paintDrawMode === 'rect-outline' ? ' active' : ''}`} type="button" title="Контурный прямоугольник" aria-label="Контурный прямоугольник" onClick={() => { setPaintTool('brush'); setPaintDrawMode('rect-outline') }}><span className="paint-shape-icon rect outline" /></button>
                          <button className={`paint-tool-circle-fill${paintDrawMode === 'circle-fill' ? ' active' : ''}`} type="button" title="Залитый круг" aria-label="Залитый круг" onClick={() => { setPaintTool('brush'); setPaintDrawMode('circle-fill') }}><span className="paint-shape-icon circle filled" /></button>
                          <button className={`paint-tool-circle-outline${paintDrawMode === 'circle-outline' ? ' active' : ''}`} type="button" title="Контурный круг" aria-label="Контурный круг" onClick={() => { setPaintTool('brush'); setPaintDrawMode('circle-outline') }}><span className="paint-shape-icon circle outline" /></button>
                          <button className={`paint-tool-bucket${paintDrawMode === 'bucket' ? ' active' : ''}`} type="button" title="Заливка области" aria-label="Заливка области" onClick={() => { setPaintTool('brush'); setPaintDrawMode('bucket') }}><PaintBucket size={18} strokeWidth={2.2} /></button>
                        </>
                      )}
                    </div>
                    <label className="paint-control"><span className="paint-control-label">Размер</span><input type="range" min="1" max="64" value={paintBrushSize} onChange={(e) => setPaintBrushSize(Number(e.target.value))} /><span>{paintBrushSize}</span></label>
                    {paintMode === 'sketch' && (
                      <div className="paint-segment paint-icon-segment">
                        <button className={paintCanvasBg === 'white' ? 'active' : ''} type="button" title="Белый холст" onClick={() => setPaintCanvasBg('white')}><Sun size={16} strokeWidth={2.2} /><span>Белый холст</span></button>
                        <button className={paintCanvasBg === 'gray' ? 'active' : ''} type="button" title="Серый холст" onClick={() => setPaintCanvasBg('gray')}><Moon size={16} strokeWidth={2.2} /><span>Серый холст</span></button>
                      </div>
                    )}
                  </div>
                </div>
              )}

              {paintMode === 'outpaint' && (
                <div className="paint-toolbox">
                  <button
                    className={`paint-tools-toggle${paintToolsOpen ? ' active' : ''}`}
                    type="button"
                    aria-expanded={paintToolsOpen}
                    onClick={() => setPaintToolsOpen((open) => !open)}
                  >
                    <SlidersHorizontal size={17} strokeWidth={2.2} aria-hidden="true" />
                    <span>Поля расширения</span>
                    <ChevronDown size={17} strokeWidth={2.2} aria-hidden="true" />
                  </button>
                  <div className={`paint-tools-body${paintToolsOpen ? ' is-open' : ''}`}>
                    {(['left', 'right', 'top', 'bottom'] as const).map((key) => (
                      <label className="paint-control" key={key}>
                        <span className="paint-control-label">
                          {key === 'left' ? <ArrowLeft size={13} strokeWidth={2.4} /> : key === 'right' ? <ArrowRight size={13} strokeWidth={2.4} /> : key === 'top' ? <ArrowUp size={13} strokeWidth={2.4} /> : <ArrowDown size={13} strokeWidth={2.4} />}
                          {key === 'left' ? 'Слева' : key === 'right' ? 'Справа' : key === 'top' ? 'Сверху' : 'Снизу'}
                        </span>
                        <input type="range" min="0" max="768" step="16" value={paintOutpaint[key]} onChange={(e) => updateOutpaintPadding(key, Number(e.target.value))} />
                        <span>{paintOutpaint[key]}</span>
                      </label>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </section>
        )}

        <section className={`form-section prompt-section${isEditStudio || isFaceStudio || isPaintStudio ? ' editor-prompt-section' : ''}`}>
          <div className="section-title">
            <h2>{promptTitle}</h2>
            {isPaintStudio && (
              <label className="paint-tech-toggle">
                <input type="checkbox" checked={paintTechPromptOpen} onChange={(e) => setPaintTechPromptOpen(e.target.checked)} />
                <span>Технический промпт</span>
              </label>
            )}
            <span className="help-dot" role="button" tabIndex={0} onClick={() => setHelpOpen(true)}>?</span>
          </div>
          <div className={`prompt-card paint-prompt-card${isPaintStudio && paintTechPromptOpen ? ' is-tech-open' : ''}`}>
            <textarea
              ref={promptTextareaRef}
              placeholder={promptPlaceholder}
              maxLength={promptTextareaLimit}
              value={promptTextareaValue}
              onChange={(e) => updatePromptTextarea(e.target.value)}
            />
            <div className="counter">{promptCounterValue} / {promptTextareaLimit}</div>
          </div>
          <div className="action-row">
            <button className="tool-button" type="button" onClick={() => showToast('Голосовой ввод скоро')}>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <path d="M12 14a3 3 0 0 0 3-3V6a3 3 0 0 0-6 0v5a3 3 0 0 0 3 3Z" stroke="currentColor" strokeWidth="2" />
                <path d="M19 11a7 7 0 0 1-14 0M12 18v4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
              </svg>
              Голос
            </button>
            <button className="tool-button primary" type="button" onClick={() => showToast('Улучшение промпта скоро')}>
              <svg width="17" height="17" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <path d="M12 3.5l1.6 4 4 1.6-4 1.6-1.6 4-1.6-4-4-1.6 4-1.6L12 3.5Z" fill="currentColor" />
                <path d="M18.5 14.5l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8.8-2Z" fill="currentColor" opacity=".72" />
              </svg>
              Улучшить
            </button>
            {!isEditStudio && !isFaceStudio && !isPaintStudio && (
              <>
                <button className="tool-button" type="button" onClick={() => setTemplatesOpen(true)}>
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                    <path d="M4 4h6v6H4V4Zm10 0h6v6h-6V4ZM4 14h6v6H4v-6Zm10 0h6v6h-6v-6Z" stroke="currentColor" strokeWidth="1.8" />
                  </svg>
                  Шаблоны
                </button>
                <button className="tool-button" type="button" onClick={randomPrompt}>
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                    <path d="M9 18h6M10 22h4M8.4 14.4A6 6 0 1 1 15.6 14c-.9.7-1.6 1.7-1.8 2.8h-3.6c-.2-1-.8-1.8-1.8-2.4Z" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                  Идея
                </button>
              </>
            )}
          </div>
        </section>

        {!isEditStudio && !isFaceStudio && !isPaintStudio && <section className="form-section style-section">
          <div className="section-title">
            <h2>Стиль</h2>
            <span>{I2I_STYLES.length} стилей</span>
          </div>
          <div className="style-row" ref={styleRowRef}>
            <figure
              className={`style-card no-style${!styleId ? ' active' : ''}`}
              role="button"
              tabIndex={0}
              onClick={() => { if (styleDraggedRef.current) { styleDraggedRef.current = false; return } applyStyle(null) }}
            >
              <span className="no-style-symbol">✓</span>
              <figcaption>Нет</figcaption>
            </figure>
            {I2I_STYLES.map((style) => (
              <figure
                key={style.id}
                className={`style-card${styleId === style.id ? ' active' : ''}`}
                role="button"
                tabIndex={0}
                title={style.name}
                onClick={() => { if (styleDraggedRef.current) { styleDraggedRef.current = false; return } applyStyle(style) }}
                onMouseEnter={() => { if (!stylePointerDownRef.current) setHoverStyle(style) }}
                onMouseLeave={() => setHoverStyle(null)}
              >
                <img src={style.preview[previewGender]} alt={style.preview.alt} loading="lazy" />
                <figcaption>{styleShortLabel(style, feedLang)}</figcaption>
              </figure>
            ))}
          </div>
        </section>}

        <section className="form-section format-section">
          <div className="section-title">
            <h2>Формат</h2>
          </div>
          <div className="control-row">
            <div className={`iv3-format-select${formatOpen ? ' open' : ''}`} ref={formatRef}>
              <button
                type="button"
                className="resolution iv3-format-trigger"
                aria-haspopup="listbox"
                aria-expanded={formatOpen}
                aria-label="Разрешение"
                onClick={() => setFormatOpen((o) => !o)}
              >
                <span className="iv3-format-res">{selectedResolution.width}×{selectedResolution.height}</span>
                <svg className="iv3-format-caret" width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                  <path d="m7 9 5 5 5-5" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </button>
              {formatOpen && (
                <div className="iv3-format-menu" role="listbox">
                  {RESOLUTION_PRESETS.map((p) => (
                    <button
                      key={p.id}
                      type="button"
                      role="option"
                      aria-selected={p.id === resolutionId}
                      className={`iv3-format-option${p.id === resolutionId ? ' active' : ''}`}
                      onClick={() => { setResolutionId(p.id); setFormatOpen(false) }}
                    >
                      <span className={`ratio-icon ${ratioIconClass(p.kind)}`.trim()} aria-hidden="true"></span>
                      <span className="iv3-format-res">{p.width}×{p.height}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>
            <button className={`ratio-button${ratioKind === 'square' ? ' active' : ''}`} type="button" onClick={() => selectRatio('square')}>
              <span className="ratio-icon"></span>1:1
            </button>
            <button className={`ratio-button${ratioKind === 'vertical' ? ' active' : ''}`} type="button" onClick={() => selectRatio('vertical')}>
              <span className="ratio-icon tall"></span>9:16
            </button>
            <button className={`ratio-button${ratioKind === 'horizontal' ? ' active' : ''}`} type="button" onClick={() => selectRatio('horizontal')}>
              <span className="ratio-icon wide"></span>16:9
            </button>
          </div>
        </section>

        <section className="form-section quality-section">
          <div className="section-title">
            <h2>Качество</h2>
          </div>
          <div className="quality-row">
            {QUALITY.map((q) => (
              <button
                key={q.id}
                className={`quality-button${quality === q.id ? ' active' : ''}`}
                type="button"
                onClick={() => setQuality(q.id)}
              >
                {q.label}
              </button>
            ))}
          </div>
        </section>

        {notice && <div className="iv3-notice" role="alert">{notice}</div>}

        <button className={`generate-button${isSubmitting || jobActive ? ' is-generating' : ''}`} type="button" disabled={isSubmitting || jobActive} onClick={() => generate(studioMode)}>
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path d="M12 3.5l1.9 4.8 4.8 1.9-4.8 1.9-1.9 4.9-1.9-4.9-4.8-1.9 4.8-1.9L12 3.5Z" fill="currentColor" />
          </svg>
          {jobActive || isSubmitting ? generatingLabel : generateLabel}
        </button>
      </aside>

      <section className="preview-panel">
        <div className="mobile-title-row">
          <h1>{studioTitle}</h1>
          {isPaintStudio && paintWorkbenchVisible && (paintMode === 'sketch' || paintMode === 'mask') && (
            <div className="paint-mobile-history-actions" aria-label="Действия рисунка">
              <button type="button" onClick={() => setPaintLines((lines) => lines.slice(0, -1))}><Undo2 size={13} strokeWidth={2.2} />Назад</button>
              <button type="button" onClick={() => setPaintLines([])}><Trash2 size={13} strokeWidth={2.2} />Очистить</button>
            </div>
          )}
          {isPaintStudio && !paintWorkbenchVisible && !previewJobActive && (
            <div className="paint-preview-actions">
              <button
                className="paint-return-workbench"
                type="button"
                onClick={() => {
                  setPaintWorkbenchVisible(true)
                  setResultError(false)
                  setInspectPreview(null)
                  resetInspectView()
                }}
              >
                {paintReturnLabel[paintMode]}
              </button>
              {(visibleInspectPreview?.url || visibleResultUrl) && (
                <button className="paint-use-preview" type="button" onClick={useCurrentPreviewInPaint}>
                  Взять это
                </button>
              )}
            </div>
          )}
          <button className={`pro-button${proMode ? ' active' : ''}`} type="button" onClick={() => setProMode((v) => !v)}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <path d="m4 19 1.4-11 4.4 4.4L12 5l2.2 7.4L18.6 8 20 19H4Z" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
            </svg>
            {proMode ? 'Режим Стандарт' : 'Режим Профи'}
          </button>
        </div>
        <div className={`preview-image preview-shape-${visiblePreviewShape}`}>
          {isPaintStudio && paintWorkbenchVisible && !hoverStyle && !previewJobActive ? (
            paintWorkbench
          ) : hoverStyle ? (
            <>
              <img className="iv3-preview-backdrop" src={hoverStyle.preview[previewGender]} alt="" aria-hidden="true" />
              <img className="iv3-preview-main" src={hoverStyle.preview[previewGender]} alt={hoverStyle.preview.alt} />
              <span className="iv3-style-hover-badge">Превью стиля · {styleShortLabel(hoverStyle, feedLang)}</span>
            </>
          ) : previewJobActive ? (
            <div className={`iv3-preview-loading${loadingBackdropUrl ? ' has-bg' : ''}`}>
              {loadingBackdropUrl && <img className="iv3-preview-backdrop" src={loadingBackdropUrl} alt="" aria-hidden="true" />}
              <div className="iv3-loading-shimmer" aria-hidden="true"></div>
              <div className="iv3-loading-inner">
                <span className="iv3-spinner" aria-hidden="true"></span>
                <span className="iv3-loading-text">Генерируем{jobProgress > 0 ? ` · ${jobProgress}%` : '…'}</span>
                <div className="iv3-loading-bar" aria-hidden="true">
                  <div className="iv3-loading-bar-fill" style={jobProgress > 0 ? { width: `${jobProgress}%` } : undefined}></div>
                </div>
              </div>
            </div>
          ) : visibleInspectPreview ? (
            <>
              <img className="iv3-preview-backdrop" src={apiUrl(visibleInspectPreview.url)} alt="" aria-hidden="true" />
              <div
                className={`iv3-inspect-stage${inspectToolsVisible ? ' is-zoomed' : ''}`}
                onWheel={onInspectWheel}
                onPointerDown={onInspectPointerDown}
                onPointerMove={onInspectPointerMove}
                onPointerUp={onInspectPointerUp}
                onPointerCancel={onInspectPointerUp}
                onTouchStart={onInspectTouchStart}
                onTouchMove={onInspectTouchMove}
                onTouchEnd={onInspectTouchEnd}
                onTouchCancel={onInspectTouchEnd}
                onDoubleClick={resetInspectView}
              >
                <img className="iv3-preview-main iv3-inspect-image" src={apiUrl(visibleInspectPreview.url)} alt={visibleInspectPreview.title} style={inspectImageStyle} draggable={false} />
              </div>
              {inspectToolsVisible && <div className="iv3-inspect-tools">
                <span>{visibleInspectPreview.title} · {Math.round(inspectZoom * 100)}%</span>
                <button type="button" onClick={resetInspectView}>Сброс</button>
              </div>}
            </>
          ) : visibleResultUrl && !visibleResultError ? (
            <>
              <img className="iv3-preview-backdrop" src={apiUrl(visibleResultUrl)} alt="" aria-hidden="true" />
              {visibleResultSource && compareEnabled ? (
                <div
                  className={`iv3-compare${compareAuto ? ' is-auto' : ''}${inspectToolsVisible ? ' is-zoomed' : ''}`}
                  style={{ '--compare': `${compare}%`, ...inspectImageStyle } as CSSProperties}
                  onTouchStart={onInspectTouchStart}
                  onTouchMove={onInspectTouchMove}
                  onTouchEnd={onInspectTouchEnd}
                  onTouchCancel={onInspectTouchEnd}
                  onDoubleClick={resetInspectView}
                >
                  <img className="iv3-preview-main iv3-compare-after" src={apiUrl(visibleResultUrl)} alt="Результат генерации" onError={markVisiblePreviewError} />
                  <div className="iv3-compare-before">
                    <img className="iv3-preview-main" src={apiUrl(visibleResultSource)} alt="Исходное изображение" />
                  </div>
                  <div className="iv3-compare-line" aria-hidden="true">
                    <span className="iv3-compare-handle"></span>
                  </div>
                  <span className="iv3-compare-label before">До</span>
                  <span className="iv3-compare-label after">После</span>
                  <input
                    className="iv3-compare-range"
                    type="range"
                    min="0"
                    max="100"
                    value={compare}
                    aria-label="Сравнение до и после"
                    onChange={(e) => {
                      compareTouchedRef.current = true
                      setCompareAuto(false)
                      setCompare(Number(e.target.value))
                    }}
                  />
                </div>
              ) : (
                <div
                  className={`iv3-inspect-stage${inspectToolsVisible ? ' is-zoomed' : ''}`}
                  onWheel={onInspectWheel}
                  onPointerDown={onInspectPointerDown}
                  onPointerMove={onInspectPointerMove}
                  onPointerUp={onInspectPointerUp}
                  onPointerCancel={onInspectPointerUp}
                  onTouchStart={onInspectTouchStart}
                  onTouchMove={onInspectTouchMove}
                  onTouchEnd={onInspectTouchEnd}
                  onTouchCancel={onInspectTouchEnd}
                  onDoubleClick={resetInspectView}
                >
                  <img className="iv3-preview-main iv3-inspect-image" src={apiUrl(visibleResultUrl)} alt="Результат генерации" style={inspectImageStyle} draggable={false} onError={markVisiblePreviewError} />
                </div>
              )}
              {(!visibleResultSource || !compareEnabled) && inspectToolsVisible && (
                <div className="iv3-inspect-tools">
                  <span>Предпросмотр · {Math.round(inspectZoom * 100)}%</span>
                  <button type="button" onClick={resetInspectView}>Сброс</button>
                </div>
              )}
              {visibleResultSource && inspectToolsVisible && (
                <div className="iv3-inspect-tools">
                  <span>Сравнение · {Math.round(inspectZoom * 100)}%</span>
                  <button type="button" onClick={resetInspectView}>Сброс</button>
                </div>
              )}
              <div className="image-actions">
                {visibleResultUrl && (
                  <a className="image-action" href={apiUrl(visibleResultUrl)} download target="_blank" rel="noreferrer">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                      <path d="M12 3v12m0 0 4-4m-4 4-4-4M5 19h14" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                    Скачать
                  </a>
                )}
                {visibleResultSource && (
                  <button className={`image-action compare-toggle${compareEnabled ? ' active' : ''}`} type="button" aria-pressed={compareEnabled} onClick={() => setCompareEnabled((value) => !value)}>
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                      <path d="M12 4v16M5 6h14a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1Z" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
                    </svg>
                    До/После
                  </button>
                )}
                <button className="image-action" type="button" onClick={() => setShareOpen((v) => !v)}>
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                    <path d="M18 8a3 3 0 1 0-2.82-4M6 13a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm12 8a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM8.7 10.7l6.6 3.6M15.3 9.7l-6.6 3.6" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
                  </svg>
                  Поделиться
                </button>
                {shareOpen && (
                  <div className="iv3-share-menu">
                    <button type="button" onClick={() => { setShareOpen(false); if (shareTarget) openPublish(shareTarget); else showToast(visibleResultUrl ? 'Результат ещё сохраняется в галерею. Подождите секунду.' : 'Сначала сгенерируйте изображение') }}>В ленту</button>
                    <button type="button" onClick={() => { setShareOpen(false); if (visibleResultUrl) copyPrompt(apiUrl(visibleResultUrl)) }}>Скопировать ссылку</button>
                  </div>
                )}
              </div>
            </>
          ) : (
            <div className="iv3-preview-empty">
              <img className="iv3-preview-placeholder-bg" src={previewPlaceholderUrl} alt="" aria-hidden="true" />
              <span className="iv3-preview-placeholder-vignette" aria-hidden="true"></span>
              <span className="iv3-preview-empty-mark" aria-hidden="true">✦</span>
              {visibleResultError ? (
                <p>Предыдущий результат не загрузился. Новый появится здесь.</p>
              ) : (
                <p>
                  <span className="iv3-preview-empty-desktop">Опишите идею слева и нажмите «Сгенерировать»</span>
                  <span className="iv3-preview-empty-mobile">Опишите идею и нажмите «Сгенерировать»</span>
                </p>
              )}
            </div>
          )}
          {previewNoticeText && (
            <div className="iv3-preview-notice" role="status" aria-live="polite">
              <span className="iv3-preview-notice-mark" aria-hidden="true">!</span>
              <p>{previewNoticeText}</p>
            </div>
          )}
        </div>
      </section>

      <section className="result-dock">
        <div className="history">
          <div className="history-head">
            <button className="history-prompt-chip" type="button" onClick={() => copyPrompt(dockPromptText)}>
              Промпт изображения ›
            </button>
          </div>
          {historyItems.length === 0 ? (
            <div className="iv3-history-empty">
              <span className="iv3-history-empty-mark" aria-hidden="true">▧</span>
              <span>{authStatus === 'authed' ? 'Здесь появятся ваши генерации' : 'Войдите — и здесь появятся ваши работы'}</span>
            </div>
          ) : (
            <div className="history-carousel" aria-label="Навигация истории">
              <button className="history-arrow history-prev" type="button" aria-label="Назад" onClick={() => scrollHistory(-1)}>
                <svg width="18" height="34" viewBox="0 0 18 34" fill="none" aria-hidden="true">
                  <path d="M12.5 6 3.5 17l9 11" stroke="currentColor" strokeWidth="2.1" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </button>
              <div className="history-strip" ref={historyStripRef}>
                {historyIsFeed && (
                  <div className="history-item square history-placeholder-tile" aria-hidden="true">
                    <span className="history-placeholder-mark">✦</span>
                    <span>Здесь появятся ваши генерации</span>
                  </div>
                )}
                {historyItems.map((item) => (
                  <figure
                    key={item.id}
                    className={`history-item ${historyShape(item)}${dockImage?.id === item.id ? ' active' : ''}`}
                    style={historyAspectRatio(item) ? { aspectRatio: historyAspectRatio(item) } : undefined}
                    role="button"
                    tabIndex={0}
                    onClick={() => { if (historyDraggedRef.current) { historyDraggedRef.current = false; return } openHistory(item) }}
                  >
                    <img
                      src={apiUrl(item.thumbnailUrl || item.url)}
                      alt={item.promptOriginal.slice(0, 40)}
                      loading="lazy"
                      onLoad={(e) => {
                        const img = e.currentTarget
                        const frame = img.closest<HTMLElement>('.history-item')
                        if (!frame || img.naturalWidth <= 0 || img.naturalHeight <= 0) return
                        frame.style.aspectRatio = `${img.naturalWidth} / ${img.naturalHeight}`
                      }}
                    />
                    {historyIsFeed && <span className="history-feed-badge">Лента</span>}
                  </figure>
                ))}
              </div>
              <button className="history-arrow history-next" type="button" aria-label="Вперёд" onClick={() => scrollHistory(1)}>
                <svg width="18" height="34" viewBox="0 0 18 34" fill="none" aria-hidden="true">
                  <path d="m5.5 6 9 11-9 11" stroke="currentColor" strokeWidth="2.1" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </button>
            </div>
          )}
        </div>

        <aside className="image-prompt">
          <div className="prompt-copy">
            <div className="prompt-copy-head">
              <h2>Промпт изображения</h2>
              <button className="prompt-action prompt-copy-button" type="button" onClick={() => copyPrompt(dockPromptText)}>
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                  <path d="M8 8h10v12H8V8Z" stroke="currentColor" strokeWidth="1.7" />
                  <path d="M5 16V4h11" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
                </svg>
                <span className="prompt-action-label">{copied ? 'Скопировано' : 'Копировать'}</span>
              </button>
            </div>
            <div className="prompt-scroll">{dockPromptText || 'Здесь появится промпт выбранного изображения.'}</div>
          </div>
          <div className="prompt-actions">
            <details className="prompt-menu">
              <summary className="prompt-action">
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M4 20h4l10.5-10.5a2.1 2.1 0 0 0-3-3L5 17v3Z" stroke="currentColor" strokeWidth="1.7" strokeLinejoin="round" /><path d="m13.5 8.5 3 3" stroke="currentColor" strokeWidth="1.7" /></svg>
                <span className="prompt-action-label">Изменить в</span>
                <svg className="menu-caret" width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m7 9 5 5 5-5" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" /></svg>
              </summary>
              <div className="prompt-menu-list">
                <button type="button" onClick={() => { if (dockImage) setSourceImage(apiUrl(dockImage.url)); setTab('i2i') }}>По фото</button>
                <button type="button" onClick={() => setTab('edit')}>Сборка</button>
                <button type="button" onClick={() => setTab('face')}>Лицо</button>
                <button type="button" onClick={() => setTab('paint')}>Редактор</button>
              </div>
            </details>
            <button className="prompt-action feed" type="button" onClick={() => (shareTarget ? openPublish(shareTarget) : showToast('Сначала сгенерируйте изображение'))}>
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M12 3.5l1.6 4 4 1.6-4 1.6-1.6 4-1.6-4-4-1.6 4-1.6L12 3.5Z" fill="currentColor" /></svg>
              <span className="prompt-action-label">В ленту</span>
            </button>
            <button className="prompt-action" type="button" onClick={() => { if (dockImage) setPrompt(dockImage.promptOriginal); showToast('Промпт подставлен — измените и сгенерируйте') }}>
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M7 7h10v10H7V7Z" stroke="currentColor" strokeWidth="1.6" /><path d="M4 4h10M10 20h10" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" /></svg>
              <span className="prompt-action-label">Вариации</span>
            </button>
          </div>
        </aside>
      </section>
    </main>
  )

  const placeholderStudio = (title: string, note: string) => (
    <div className="iv3-placeholder">
      <img className="iv3-preview-placeholder-bg" src={previewPlaceholderUrl} alt="" aria-hidden="true" />
      <span className="iv3-preview-placeholder-vignette" aria-hidden="true"></span>
      <div className="iv3-placeholder-card">
        <span className="iv3-preview-empty-mark" aria-hidden="true">✦</span>
        <h2>{title}</h2>
        <p>{note}</p>
        <button className="iv3-placeholder-cta" type="button" onClick={() => setTab('text')}>
          Перейти в «По тексту»
        </button>
      </div>
    </div>
  )

  const topbarAvatarSrc = userMediaUrl(acct.avatarUrl)
  const profileAvatarSrc = userMediaUrl(avatarUrl)
  const profilePage = (
    <ProfilePage
      authStatus={authStatus}
      me={me}
      galleryCount={gallery.length}
      profileTab={profileTab}
      setProfileTab={setProfileTab}
      tariffs={tariffs}
      tariffsState={tariffsState}
      tokenRub={tokenRub}
      authCapsState={authCapsState}
      authCaps={authCaps}
      quality={quality}
      setQuality={setQuality}
      provider={provider}
      setProvider={setProvider}
      displayName={displayName}
      setDisplayName={setDisplayName}
      profileGender={profileGender}
      setProfileGender={setProfileGender}
      profileAge={profileAge}
      setProfileAge={setProfileAge}
      publicAbout={publicAbout}
      setPublicAbout={setPublicAbout}
      publicWebsite={publicWebsite}
      setPublicWebsite={setPublicWebsite}
      publicFocus={publicFocus}
      setPublicFocus={setPublicFocus}
      publicPhone={publicPhone}
      setPublicPhone={setPublicPhone}
      publicLinks={publicLinks}
      setPublicLinks={setPublicLinks}
      saveMsg={saveMsg}
      setSaveMsg={setSaveMsg}
      avatarSrc={profileAvatarSrc}
      avatarPreset={avatarPreset}
      avatarBusy={avatarBusy}
      avatarMsg={avatarMsg}
      uploadAvatar={uploadAvatar}
      selectAvatarPreset={selectAvatarPreset}
      promoCode={promoCode}
      setPromoCode={setPromoCode}
      promoBusy={promoBusy}
      promoResult={promoResult}
      setPromoResult={setPromoResult}
      inviteMsg={inviteMsg}
      setInviteMsg={setInviteMsg}
      linkBusy={linkBusy}
      linkMsg={linkMsg}
      onOpenAuth={() => setAuthOpen(true)}
      onBackToGeneration={() => setTab('text')}
      onSaveProfile={onSaveProfile}
      onLogout={onLogout}
      onApplyPromo={onApplyPromo}
      onLinkBot={(providerName) => void onLinkBot(providerName)}
    />
  )
  const topActive: V3Section = view === 'profile' ? 'profile' : tab === 'feed' ? 'feed' : (tab as V3Section)

  return (
    <div className="n2">
      <AuthV2Modal open={authOpen} onClose={() => setAuthOpen(false)} />
      {toastText && tab === 'feed' && (
        <div className="n2-toast" role="status">
          {toastText}
        </div>
      )}
      <input
        ref={fileInputRef}
        type="file"
        accept="image/png,image/jpeg,image/webp"
        style={{ display: 'none' }}
        onChange={(e) => {
          onSourceFile(e.target.files?.[0])
          e.target.value = ''
        }}
      />

      {helpOpen && (
        <div className="n2-overlay" role="dialog" aria-label="Помощь" onClick={() => setHelpOpen(false)}>
          <div className="n2-overlay-card n2-help-card" onClick={(e) => e.stopPropagation()}>
            <button className="n2-overlay-close" type="button" aria-label="Закрыть" onClick={() => setHelpOpen(false)}>
              ×
            </button>
            <header className="n2-help-hero">
              <span>Справка и правила сервиса</span>
              <h2>ИЗО АСА: генерация и редактирование изображений</h2>
              <p>
                ИЗО АСА — AI-сервис для создания изображений, редактирования фотографий, работы с референсами,
                замены лица, примерки одежды, генерации по эскизу и публикации результата в галерею или ленту.
              </p>
            </header>

            <nav className="n2-help-toc" aria-label="Разделы помощи">
              <a href="#help-modes">Режимы</a>
              <a href="#help-faq">FAQ</a>
              <a href="#help-policy">Правила</a>
              <a href="#help-privacy">Данные</a>
              <a href="#help-contacts">Контакты</a>
            </nav>

            <section className="n2-help-section" id="help-modes">
              <h3>Что умеет сервис</h3>
              <div className="n2-help-grid">
                <article>
                  <strong>По тексту</strong>
                  <p>Создает изображение по описанию: персонаж, сцена, предмет, интерьер, афиша, иллюстрация, обложка, концепт-арт или реалистичная фотография.</p>
                </article>
                <article>
                  <strong>По фото</strong>
                  <p>Преобразует исходное изображение по промпту и стилю. Ползунок влияния промпта регулирует силу изменения; рекомендуемое значение — 75%.</p>
                </article>
                <article>
                  <strong>Сборка</strong>
                  <p>Объединяет изображения и переносит детали с референсов: одежду, фон, объект, стиль, цвет, материал, позу или лицо.</p>
                </article>
                <article>
                  <strong>Лицо</strong>
                  <p>Переносит лицо из одного изображения в другое. Оптимальное значение силы замены по умолчанию — 75%.</p>
                </article>
                <article>
                  <strong>Редактор</strong>
                  <p>Превращает эскиз в сцену, работает с маской, дорисовывает область и расширяет холст вокруг изображения.</p>
                </article>
                <article>
                  <strong>Галерея и лента</strong>
                  <p>Хранит результаты, исходники и промпты. Работы можно скачивать, защищать сердечком, открывать в другом режиме и публиковать в ленту.</p>
                </article>
              </div>
            </section>

            <section className="n2-help-section" id="help-faq">
              <h3>FAQ</h3>
              <details open>
                <summary>Как получить лучший результат?</summary>
                <p>Опишите, что нужно сохранить, что изменить и какой итог нужен: реалистичное фото, аниме, комикс, премиум-стиль, предметная визуализация, портрет или кинематографичная сцена.</p>
              </details>
              <details>
                <summary>Можно ли использовать свои изображения?</summary>
                <p>Да. В режимах По фото, Сборка, Лицо и Редактор можно загрузить изображение, взять работу из галереи или использовать последнее созданное изображение.</p>
              </details>
              <details>
                <summary>Где хранятся результаты?</summary>
                <p>Результаты сохраняются в галерее пользователя вместе с промптом и параметрами генерации. Отдельные работы можно отправить в публичную ленту.</p>
              </details>
              <details>
                <summary>Что публикуется в ленте?</summary>
                <p>В ленту отправляется отдельная публичная копия выбранного изображения. Пользователь управляет публикацией и может удалить ее из ленты.</p>
              </details>
              <details>
                <summary>Почему некоторые функции требуют вход?</summary>
                <p>Авторизация нужна для сохранения галереи, публикаций, профиля, лимитов, избранного и связи работ с конкретным пользователем.</p>
              </details>
            </section>

            <section className="n2-help-section" id="help-policy">
              <h3>Правила использования</h3>
              <ul>
                <li>Не загружайте изображения, на которые у вас нет прав или разрешения.</li>
                <li>Не используйте сервис для обмана, вреда, травли, незаконных действий или выдачи результата за официальный документ.</li>
                <li>При работе с лицами используйте только изображения людей, на использование которых у вас есть согласие.</li>
                <li>Публичные публикации в ленте могут быть скрыты или удалены при нарушении правил сервиса.</li>
              </ul>
            </section>

            <section className="n2-help-section" id="help-privacy">
              <h3>Данные и приватность</h3>
              <p>
                Для работы сервиса используются учетная запись, cookie-сессия, загруженные изображения, промпты,
                параметры генерации, публикации в ленте и технические данные запросов. Эти данные нужны для входа,
                генерации, сохранения галереи, восстановления истории, лимитов и защиты сервиса от злоупотреблений.
              </p>
              <p>
                Не загружайте чувствительные документы, платежные данные, медицинские сведения или материалы,
                которые вы не хотите использовать в AI-обработке. Удаление изображения из галереи удаляет его из
                пользовательского интерфейса; опубликованные копии в ленте управляются отдельно.
              </p>
            </section>

            <section className="n2-help-section" id="help-contacts">
              <h3>Контакты и поддержка</h3>
              <p>
                По вопросам доступа, удаления публикации, обработки данных, ошибок генерации или рекламного
                размещения используйте кнопку «Помощь» в интерфейсе и профиль пользователя. До отдельной страницы
                контактов официальный канал поддержки фиксируется внутри интерфейса ИЗО АСА.
              </p>
            </section>
          </div>
        </div>
      )}

      {templatesOpen && (
        <div className="n2-overlay" role="dialog" aria-label="Шаблоны" onClick={() => setTemplatesOpen(false)}>
          <div className="n2-overlay-card n2-templates" onClick={(e) => e.stopPropagation()}>
            <button className="n2-overlay-close" type="button" aria-label="Закрыть" onClick={() => setTemplatesOpen(false)}>
              ×
            </button>
            <h2>{tab === 'i2i' ? 'Шаблоны преобразования' : 'Шаблоны · идеи'}</h2>
            {tab === 'i2i' ? (
              <div className="n2-templates-styles">
                {I2I_STYLES.map((style) => (
                  <button
                    key={style.id}
                    className="n2-template-style"
                    type="button"
                    title={style.name}
                    onClick={() => {
                      appendI2ITemplate(style.transformPrompt)
                    }}
                  >
                    <img src={style.preview[previewGender]} alt={style.preview.alt} loading="lazy" />
                    <span>{style.name}</span>
                  </button>
                ))}
              </div>
            ) : (
              <div className="n2-templates-list">
                {T2I_TEMPLATES.map((template) => (
                  <button key={template.id} className="n2-template-item" type="button" onClick={() => applyTemplate(template.prompt)}>
                    <strong>{template.name}</strong>
                    <span>{template.prompt.slice(0, 140)}…</span>
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {galleryPickTarget && (
        <div className="n2-overlay" role="dialog" aria-label="Выбор из галереи" onClick={() => setGalleryPickTarget(null)}>
          <div className="n2-overlay-card n2-templates" onClick={(e) => e.stopPropagation()}>
            <button className="n2-overlay-close" type="button" aria-label="Закрыть" onClick={() => setGalleryPickTarget(null)}>
              ×
            </button>
            <h2>{galleryPickTarget.kind === 'edit' ? 'Выберите изображение' : 'Выберите исходник из галереи'}</h2>
            <div className="n2-templates-styles">
              {gallery.map((item) => (
                <button
                  key={item.id}
                  className="n2-template-style"
                  type="button"
                  title={item.promptOriginal}
                  onClick={() => {
                    applyImageToTarget(galleryPickTarget, apiUrl(item.url))
                    setGalleryPickTarget(null)
                  }}
                >
                  <img src={apiUrl(item.thumbnailUrl || item.url)} alt={item.promptOriginal.slice(0, 60)} loading="lazy" />
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

      {galleryItem && (
        <div className="n2-overlay" role="dialog" aria-label="Просмотр изображения" onClick={() => setGalleryItem(undefined)}>
          <div className="n2-overlay-card n2-overlay-image" onClick={(e) => e.stopPropagation()}>
            <button className="n2-overlay-close" type="button" aria-label="Закрыть" onClick={() => setGalleryItem(undefined)}>
              ×
            </button>
            <img src={apiUrl(galleryItem.url)} alt={galleryItem.promptOriginal.slice(0, 80)} />
            <p className="n2-overlay-prompt">{galleryItem.promptOriginal}</p>
            <div className="n2-overlay-actions">
              <a className="n2-ghost" href={apiUrl(galleryItem.url)} download target="_blank" rel="noreferrer">
                ⬇ {ft.download}
              </a>
              <button className="n2-ghost" type="button" onClick={() => applyGalleryAsSource(galleryItem)}>
                → {ft.useAsSource}
              </button>
              <button className="n2-ghost purple" type="button" onClick={() => openPublish(galleryItem)}>
                ✦ {ft.publish}
              </button>
              <button className="n2-ghost danger" type="button" onClick={() => deleteGalleryImage(galleryItem)}>
                🗑 {ft.del}
              </button>
            </div>
          </div>
        </div>
      )}

      {publishFor && (
        <div className="n2-overlay" role="dialog" aria-label={ft.publish} onClick={() => setPublishFor(null)}>
          <div className="n2-overlay-card" onClick={(e) => e.stopPropagation()}>
            <button className="n2-overlay-close" type="button" aria-label="Закрыть" onClick={() => setPublishFor(null)}>
              ×
            </button>
            <h2>{ft.publish}</h2>
            <img className="n2-publish-preview" src={apiUrl(publishFor.thumbnailUrl || publishFor.url)} alt="" />
            <label className="n2-publish-field">
              <span>{feedLang === 'ru' ? 'Название' : 'Title'}</span>
              <input
                type="text"
                maxLength={120}
                value={publishTitle}
                onChange={(e) => setPublishTitle(e.target.value)}
              />
            </label>
            <label className="n2-publish-field">
              <span>{feedLang === 'ru' ? 'Видимость промпта' : 'Prompt visibility'}</span>
              <select value={publishVisibility} onChange={(e) => setPublishVisibility(e.target.value as 'open' | 'partial' | 'hidden')}>
                <option value="open">{feedLang === 'ru' ? 'Открытый' : 'Open'}</option>
                <option value="partial">{feedLang === 'ru' ? 'Частично' : 'Partial'}</option>
                <option value="hidden">{feedLang === 'ru' ? 'Скрыт' : 'Hidden'}</option>
              </select>
            </label>
            <label className="n2-publish-check">
              <input
                type="checkbox"
                checked={publishAllowRecreate}
                onChange={(e) => setPublishAllowRecreate(e.target.checked)}
              />
              <span>{feedLang === 'ru' ? `Разрешить «${ft.recreate}»` : `Allow "${ft.recreate}"`}</span>
            </label>
            <div className="n2-overlay-actions">
              <button className="n2-publish-submit" type="button" disabled={publishBusy} onClick={submitPublish}>
                {publishBusy ? '…' : ft.publish}
              </button>
            </div>
          </div>
        </div>
      )}

      <div className={`iv3 mode-${tab}`}>
        <div className="app-shell">
          <TopBarV3
            active={topActive}
            authed={authStatus === 'authed'}
            avatarUrl={authStatus === 'authed' ? topbarAvatarSrc : null}
            userLabel={authStatus === 'authed' ? acct.userLabel : null}
            initials={authStatus === 'authed' ? acct.initials : null}
            isAdmin={isAdmin}
            videoEnabled={authStatus === 'authed' && videoEnabled}
            onSelectMode={selectStudioMode}
            onOpenFeed={() => setTab('feed')}
            onOpenGallery={goGallery}
            onOpenHelp={() => setHelpOpen(true)}
            onOpenAdmin={() => { window.location.href = '/admin' }}
            onOpenProfile={openProfilePage}
          />
          {view === 'profile' ? (
            <div className="iv3-content">{profilePage}</div>
          ) : tab === 'feed' ? (
            <div className="iv3-content"><div className="preview-empty">Открываем ленту...</div></div>
          ) : tab === 'text' || tab === 'i2i' || tab === 'edit' || tab === 'face' || tab === 'paint' ? (
            studio
          ) : (
            placeholderStudio('Видео', 'Раздел видео открыт для тарифов Pro и Бизнес. Генерация видео будет подключена отдельным модулем.')
          )}
        </div>
        {view === 'tabs' && (tab === 'text' || tab === 'i2i' || tab === 'edit' || tab === 'face' || tab === 'paint') && (
          <button className={`mobile-bottom-cta${isSubmitting || jobActive ? ' is-generating' : ''}`} type="button" disabled={isSubmitting || jobActive} onClick={() => generate(studioMode)}>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <path d="M12 3.5l1.9 4.8 4.8 1.9-4.8 1.9-1.9 4.9-1.9-4.9-4.8-1.9 4.8-1.9L12 3.5Z" fill="currentColor" />
            </svg>
            {jobActive || isSubmitting ? generatingLabel.replace('...', '…') : generateLabel}
          </button>
        )}
      </div>
    </div>
  )
}
