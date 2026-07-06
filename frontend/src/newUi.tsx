// ============================================================================
// UI 2.0 — страница /new. Самодостаточный модуль: собственный layout по новым
// макетам, реальный функционал через те же API, что и основной интерфейс
// (/api/generate, /api/jobs, /api/gallery, auth v2). Работает параллельно с
// текущим интерфейсом и не зависит от него (общие только stylePresets/authV2).
//
// Логика стилей (Текст → Изо): клик по стилю дописывает текст стиля в конец
// промпта; выбор другого стиля заменяет предыдущую приписку. В Изо → Изо стиль
// задаёт transform-prompt преобразования (как шаблоны текущей версии).
// ============================================================================
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ReactElement } from 'react'
import { AuthV2Modal, refreshAuthStateV2, useAuthV2 } from './authV2'
import { I2I_STYLES, T2I_TEMPLATES } from './stylePresets'
import type { StylePreset } from './stylePresets'
import TopBarV3 from './TopBarV3'
import type { V3Section } from './TopBarV3'
import './newUi.css'
import './newStudioV3.css'

const API = import.meta.env.VITE_API_BASE_URL || '/api'
// Origin API-сервера для относительных media-URL из ответов backend
// (в проде API='/api' → origin пуст и URL остаются относительными).
const API_ORIGIN = API.endsWith('/api') ? API.slice(0, -'/api'.length) : ''

function apiUrl(path: string): string {
  return path.startsWith('/') ? `${API_ORIGIN}${path}` : path
}

// Auth: только trusted cookie session (credentials: include). Никаких legacy
// заголовков, кук или клиентских идентификаторов — см. docs/new-ui-v2-plan.md.
function apiFetch(path: string, init: RequestInit = {}) {
  return fetch(`${API}${path}`, { ...init, credentials: 'include' })
}

type N2Tab = 'feed' | 'text' | 'i2i' | 'edit' | 'paint' | 'face'
// tabs — генератор/лента; gallery и profile — отдельные канонические страницы.
type N2View = 'tabs' | 'gallery' | 'profile'

// Начальное состояние из URL: /gallery, /profile, /feed, /new/*.
function initialViewFromPath(): { view: N2View; tab: N2Tab } {
  const p = typeof window !== 'undefined' ? window.location.pathname : '/feed'
  if (p === '/gallery' || p.startsWith('/gallery') || p.startsWith('/new/gallery')) return { view: 'gallery', tab: 'feed' }
  if (p === '/profile' || p.startsWith('/profile') || p.startsWith('/new/profile')) return { view: 'profile', tab: 'feed' }
  // Лента: /feed, /lenta. Генератор /new открывается на «Текст → Изо».
  if (p === '/feed' || p.startsWith('/feed') || p === '/lenta' || p.startsWith('/lenta')) return { view: 'tabs', tab: 'feed' }
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

// Дефолтный пресет для каждой формат-кнопки.
const DEFAULT_PRESET_BY_KIND: Record<FormatId, string> = {
  square: 'sq-1024',
  vertical: 'v-720',
  horizontal: 'h-1280',
}

// ============================================================================
// Live Feed. Данные — реальный backend: GET /api/feed, публикации из галереи
// (POST /api/feed/publications), реакции like/save/recreate. Референсы:
// izo_feed_visual_spec.md, лента_izo_feed_documentation.md, Лента.html.
// Челленджи/Подписки — честные placeholder-вкладки (backend будущей фазы).
// ============================================================================
type FeedTabId = 'all' | 'new' | 'top' | 'challenge' | 'follow'

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
    tokens: 'Токены',
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
    tokens: 'Tokens',
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

// Ключ бейджа с backend → RU/EN подпись. Терминология по ТЗ.
const FEED_BADGE_LABELS: Record<string, { ru: string; en: string }> = {
  trend: { ru: 'Тренд', en: 'Trending' },
  editor_pick: { ru: 'Выбор редакции', en: "Editor's pick" },
  face_template: { ru: 'Шаблон лица', en: 'Face template' },
  open_prompt: { ru: 'Открытый промпт', en: 'Open prompt' },
}

function feedTimeAgo(iso: string, lang: FeedLang): string {
  const then = Date.parse(iso)
  if (Number.isNaN(then)) return ''
  const minutes = Math.max(1, Math.round((Date.now() - then) / 60000))
  if (minutes < 60) return lang === 'ru' ? `${minutes} мин назад` : `${minutes}m ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return lang === 'ru' ? `${hours} ч назад` : `${hours}h ago`
  const days = Math.round(hours / 24)
  return lang === 'ru' ? `${days} дн назад` : `${days}d ago`
}

function feedCount(n: number): string {
  return n >= 1000 ? `${(n / 1000).toFixed(1)}K` : String(n)
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

// Приписка стиля в промпте (Текст → Изо). Через маркер её можно заменить при
// выборе другого стиля, не трогая пользовательский текст.
const STYLE_PREFIX = '\n\nСтиль: '

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

export default function NewStudio(): ReactElement {
  // Route: /new/feed — Лента (она же вкладка по умолчанию на /new);
  // остальные вкладки живут на /new.
  const initialRoute = initialViewFromPath()
  const [tab, setTabState] = useState<N2Tab>(initialRoute.tab)
  // view: студия (tabs). Галерея/Профиль вынесены на App-level маршруты, но
  // setView сохраняем для синхронизации при popstate/навигации по вкладкам.
  const [, setView] = useState<N2View>(initialRoute.view)

  // Навигация страниц нового UI с синхронизацией URL. Каноничные маршруты:
  // Лента /feed, Галерея /gallery, Профиль /profile, генератор /new.
  const navTo = useCallback((path: string) => {
    if (window.location.pathname !== path) window.history.pushState(null, '', path)
  }, [])
  const setTab = useCallback(
    (next: N2Tab) => {
      setView('tabs')
      setTabState(next)
      navTo(next === 'feed' ? '/feed' : '/new')
    },
    [navTo],
  )
  // Галерея и Профиль вынесены в отдельные страницы (App-level: перенесённые
  // рабочие экраны старого UI). Переходим полной навигацией, чтобы App заново
  // разобрал маршрут и отрисовал нужный экран.
  const goGallery = useCallback(() => { window.location.href = '/gallery' }, [])
  const goProfile = useCallback(() => { window.location.href = '/profile' }, [])

  // Кнопка «назад» браузера синхронизирует страницу с URL.
  useEffect(() => {
    const onPop = () => {
      const r = initialViewFromPath()
      setView(r.view)
      if (window.location.pathname === '/feed' || window.location.pathname === '/lenta') setTabState('feed')
    }
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])
  const { status: authStatus, me } = useAuthV2()
  const [authOpen, setAuthOpen] = useState(false)
  const [helpOpen, setHelpOpen] = useState(false)
  const [templatesOpen, setTemplatesOpen] = useState(false)
  const [galleryPickOpen, setGalleryPickOpen] = useState(false)

  // Пол из профиля определяет вариант превью стилей (по умолчанию female).
  const previewGender: 'female' | 'male' = me?.profile?.gender === 'male' ? 'male' : 'female'

  const [prompts, setPrompts] = useState<Record<'text' | 'i2i', string>>({ text: '', i2i: '' })
  const [styleId, setStyleId] = useState<string>('')
  // Разрешение = конкретный системный пресет; формат-кнопки переключают тип.
  const [resolutionId, setResolutionId] = useState('sq-1024')
  const [quality, setQuality] = useState('fast')
  const [proMode, setProMode] = useState(false)
  const [seed, setSeed] = useState(0)
  const [guidance] = useState(3.5)
  const [strengthPct] = useState(75)
  const [sourceImage, setSourceImage] = useState<string>()
  const [, setCompare] = useState(50)

  // ---------- Live Feed state ----------
  // Язык ленты из профиля (RU по умолчанию — как весь /new).
  const feedLang: FeedLang = me?.profile?.language_code === 'en' ? 'en' : 'ru'
  const ft = FEED_I18N[feedLang]

  const feedTabs: Array<{ id: FeedTabId; label: string }> = [
    { id: 'all', label: ft.forYou },
    { id: 'new', label: ft.fresh },
    { id: 'top', label: ft.top },
    { id: 'challenge', label: ft.challenges },
    { id: 'follow', label: ft.follows },
  ]

  const [feedTab, setFeedTab] = useState<FeedTabId>('all')
  const [feedItems, setFeedItems] = useState<FeedPublication[]>([])
  const [feedLoading, setFeedLoading] = useState(true)
  const [feedError, setFeedError] = useState(false)
  const [feedSelectedId, setFeedSelectedId] = useState<string>('')
  const [feedDetailOpen, setFeedDetailOpen] = useState(false) // mobile overlay
  const [feedPromptExpanded, setFeedPromptExpanded] = useState(false)
  const [feedReload, setFeedReload] = useState(0)
  // id публикаций с недоступным файлом — показываем error-state, не чёрный блок.
  const [feedBroken, setFeedBroken] = useState<Set<string>>(() => new Set())
  const markFeedBroken = useCallback((id: string) => {
    setFeedBroken((cur) => (cur.has(id) ? cur : new Set(cur).add(id)))
  }, [])
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

  // «Открыть галерею» → каноническая страница нового UI /gallery.
  const openRealGallery = goGallery

  // Живая загрузка ленты. Вкладки: Для вас → top (персонализации пока нет),
  // Новое → new, Популярное → top. Челленджи/Подписки — placeholder, не грузим.
  useEffect(() => {
    if (tab !== 'feed') return
    if (feedTab === 'challenge' || feedTab === 'follow') return
    let cancelled = false
    // queueMicrotask — проектный паттерн против react-hooks/set-state-in-effect.
    queueMicrotask(() => {
      if (!cancelled) {
        setFeedLoading(true)
        setFeedError(false)
      }
    })
    // Для вас → foryou (живая выдача), Новое → new, Популярное → top.
    const apiType = feedTab === 'new' ? 'new' : feedTab === 'top' ? 'top' : 'foryou'
    apiFetch(`/feed?type=${apiType}&limit=50`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((data) => {
        if (cancelled) return
        const items: FeedPublication[] = Array.isArray(data?.items) ? data.items : []
        setFeedItems(items)
        setFeedSelectedId((cur) => (items.some((i) => i.id === cur) ? cur : items[0]?.id || ''))
        setFeedLoading(false)
      })
      .catch(() => {
        if (cancelled) return
        setFeedError(true)
        setFeedLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [tab, feedTab, feedReload])

  const feedSelected = feedItems.find((p) => p.id === feedSelectedId) || feedItems[0]

  const patchFeedItem = useCallback((updated: FeedPublication) => {
    setFeedItems((cur) => cur.map((item) => (item.id === updated.id ? updated : item)))
  }, [])

  // Реальные реакции like/save: POST/DELETE, ответ содержит свежую публикацию.
  const toggleFeedReaction = (post: FeedPublication, kind: 'like' | 'save') => {
    if (authStatus !== 'authed') {
      setAuthOpen(true)
      return
    }
    const active = kind === 'like' ? post.is_liked_by_me : post.is_saved_by_me
    apiFetch(`/feed/publications/${post.id}/${kind}`, { method: active ? 'DELETE' : 'POST' })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((data) => {
        if (data?.publication) patchFeedItem(data.publication)
      })
      .catch(() => showToast(feedLang === 'ru' ? 'Не удалось сохранить реакцию' : 'Reaction failed'))
  }

  // «Повторить»/«Сделать похожее»: prompt/format в генератор + счётчик recreate.
  const startFeedRecreate = (post: FeedPublication) => {
    if (authStatus !== 'authed') {
      setAuthOpen(true)
      return
    }
    if (!post.allow_recreate) {
      showToast(feedLang === 'ru' ? 'Автор запретил повторение этой работы' : 'Author disabled recreate')
      return
    }
    // Счётчик — fire-and-forget; сама генерация идёт обычным /api/generate.
    void apiFetch(`/feed/publications/${post.id}/recreate`, { method: 'POST' })
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (data?.publication) patchFeedItem(data.publication)
      })
      .catch(() => undefined)
    appliedStyleRef.current = null
    setStyleId('')
    // Формат из соотношения работы.
    const shape = feedShape(post.aspect_ratio)
    setResolutionId(DEFAULT_PRESET_BY_KIND[shape === 'square' ? 'square' : shape === 'wide' ? 'horizontal' : 'vertical'])
    // Открытый промпт → в ту вкладку, где сделана работа (i2i→Изо→Изо, иначе Текст),
    // с подстановкой промпта. Скрытый промпт → НЕ подставляем текст, а используем
    // само изображение как референс (Изо → Изо).
    const hasPrompt = !!post.prompt
    const targetTab: 'text' | 'i2i' = !hasPrompt ? 'i2i' : post.mode === 'image_to_image' ? 'i2i' : 'text'
    const promptSlot = targetTab === 'i2i' ? 'i2i' : 'text'
    setPrompts((cur) => ({ ...cur, [promptSlot]: post.prompt || '' }))
    if (targetTab === 'i2i') {
      // Референс — сжатая display-версия опубликованной работы.
      setSourceImage(apiUrl(post.display_url || post.image_url))
    }
    if (hasPrompt) {
      showToast(feedLang === 'ru' ? 'Промпт подставлен — генерируйте свою версию' : 'Prompt prefilled — generate your version')
    } else {
      showToast(
        feedLang === 'ru'
          ? 'Промпт скрыт автором, используем изображение как референс'
          : 'Prompt hidden by author — using the image as reference',
      )
    }
    setFeedDetailOpen(false)
    setTab(targetTab)
  }

  // «Взять стиль»: style публикации мапится на реальный стиль stylePresets по
  // имени; у старых генераций поле пустое — кнопка тогда не показывается.
  const applyFeedStyle = (post: FeedPublication) => {
    const style = post.style ? I2I_STYLES.find((s) => s.name === post.style || s.id === post.style) : undefined
    if (!style) {
      showToast(feedLang === 'ru' ? 'У этой работы стиль не размечен' : 'This work has no tagged style')
      return
    }
    setFeedDetailOpen(false)
    setTab('text')
    applyStyleTo('text', style)
    showToast(feedLang === 'ru' ? `Стиль «${style.name}» применён` : `Style "${style.name}" applied`)
  }

  // Публикация выбранного изображения галереи.
  const openPublish = (item: N2GalleryImage) => {
    if (authStatus !== 'authed') {
      setAuthOpen(true)
      return
    }
    setPublishTitle(item.promptOriginal.slice(0, 60) || (feedLang === 'ru' ? 'Моя работа' : 'My work'))
    setPublishVisibility('open')
    setPublishAllowRecreate(true)
    setPublishFor(item)
  }

  // Удалить изображение из личной галереи (как в старом интерфейсе: DELETE
  // /api/gallery/{id}). Только для своей галереи, требует сессию.
  const deleteGalleryImage = (item: N2GalleryImage) => {
    if (authStatus !== 'authed') {
      setAuthOpen(true)
      return
    }
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

  // «Использовать как основу» → Изо → Изо с этим изображением-исходником.
  const applyGalleryAsSource = (item: N2GalleryImage) => {
    setSourceImage(apiUrl(item.url))
    setGalleryItem(undefined)
    setTab('i2i')
  }

  // Профиль: язык RU/EN и выход.

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
        setFeedReload((n) => n + 1)
        setView('tabs')
        setTab('feed')
        setFeedTab('new')
        showToast(feedLang === 'ru' ? 'Опубликовано в ленту' : 'Published to feed')
      })
      .catch(() => showToast(feedLang === 'ru' ? 'Не удалось опубликовать' : 'Publish failed'))
      .finally(() => setPublishBusy(false))
  }

  const [job, setJob] = useState<N2Job>()
  const [, setJobMode] = useState<'text' | 'i2i'>('text')
  const [resultUrl, setResultUrl] = useState<string>()
  // URL результата не загрузился (битая ссылка/удалённый файл) — error-state.
  const [resultError, setResultError] = useState(false)
  const [, setResultSource] = useState<string>()
  const [notice, setNotice] = useState('')
  const [gallery, setGallery] = useState<N2GalleryImage[]>([])
  const [galleryItem, setGalleryItem] = useState<N2GalleryImage>()
  // Изображение, чей промпт показан в доке «Промпт изображения» (v3-студия).
  // Храним только id выбранной миниатюры; сам объект выводим при рендере,
  // с откатом на самую свежую генерацию (без setState-в-эффекте).
  const [dockImageId, setDockImageId] = useState<string>()
  const [shareOpen, setShareOpen] = useState(false)
  const [copied, setCopied] = useState(false)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const inFlightRef = useRef(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  // Текущая стилевая приписка в text-промпте: {id, text} — чтобы заменять её.
  const appliedStyleRef = useRef<{ id: string; text: string } | null>(null)
  const resultSeededRef = useRef(false)

  useEffect(() => {
    document.title = 'ИЗО ACA — новый интерфейс'
  }, [])

  const fetchGallery = useCallback(() => {
    apiFetch('/gallery')
      .then((r) => (r.ok ? r.json() : []))
      .then((data) => setGallery(Array.isArray(data) ? data : []))
      .catch(() => undefined)
  }, [])

  useEffect(() => {
    fetchGallery()
  }, [fetchGallery, authStatus])

  // В предпросмотре при загрузке страницы показываем последнюю генерацию.
  useEffect(() => {
    if (resultSeededRef.current || resultUrl || gallery.length === 0) return
    resultSeededRef.current = true
    setResultUrl(gallery[0].url)
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
            setResultUrl(next.resultUrl)
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
  }, [fetchGallery, job])

  const promptKey: 'text' | 'i2i' = tab === 'i2i' ? 'i2i' : 'text'
  const setPrompt = useCallback(
    (value: string) => setPrompts((cur) => ({ ...cur, [promptKey]: value })),
    [promptKey],
  )

  // Стиль в Текст → Изо: приписываем текст стиля в промпт (замена предыдущего).
  // Вся строковая математика — вне setState-updater (updater обязан быть чистым:
  // под StrictMode он вызывается дважды, и мутация ref внутри него ломает замену).
  // targetTab передаётся явно: из Ленты стиль применяется к «Текст → Изо»,
  // хотя state `tab` в замыкании ещё старый.
  function applyStyleTo(targetTab: 'text' | 'i2i', next: StylePreset | null) {
    setStyleId(next?.id || '')
    if (targetTab !== 'text') return
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

  function randomPrompt() {
    if (tab === 'i2i') {
      applyStyle(randomOf(I2I_STYLES))
    } else {
      applyTemplate(randomOf(T2I_TEMPLATES).prompt)
    }
  }

  const canGenerate = useMemo(() => {
    if (isSubmitting || (job && JOB_ACTIVE.includes(job.status))) return false
    if (tab === 'i2i') return !!sourceImage && (prompts.i2i.trim().length > 0 || !!styleId)
    return prompts.text.trim().length > 0
  }, [isSubmitting, job, prompts, sourceImage, styleId, tab])

  async function generate(mode: 'text' | 'i2i') {
    if (inFlightRef.current || !canGenerate) return
    if (authStatus !== 'authed') {
      setAuthOpen(true)
      return
    }
    inFlightRef.current = true
    setIsSubmitting(true)
    setNotice('')
    try {
      const style = I2I_STYLES.find((s) => s.id === styleId)
      const size = RESOLUTION_PRESETS.find((p) => p.id === resolutionId) || RESOLUTION_PRESETS[0]
      const steps = QUALITY.find((q) => q.id === quality)?.steps || 4
      const effectiveSeed = seed || randomSeed()
      const userText = (mode === 'i2i' ? prompts.i2i : prompts.text).trim()
      // text: стиль уже вписан в промпт (applyStyle). i2i: transform-prompt стиля
      // + пользовательское уточнение.
      const fullPrompt =
        mode === 'i2i'
          ? [style?.transformPrompt, userText ? `Дополнительно: ${userText}` : ''].filter(Boolean).join(' ') || userText
          : userText
      const body = {
        mode: mode === 'i2i' ? 'image_to_image' : 'text_to_image',
        provider: 'comfyui',
        prompt: fullPrompt,
        negativePrompt: '',
        seed: effectiveSeed,
        width: size.width,
        height: size.height,
        steps,
        cfg: 1,
        guidance,
        strength: strengthPct / 100,
        modelProfile: 'local_flux_klein',
        loras: [],
        inputImage1: mode === 'i2i' ? sourceImage : undefined,
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
      setJob(created)
      setJobMode(mode)
      setResultUrl(undefined)
      setResultSource(mode === 'i2i' ? sourceImage : undefined)
      setCompare(50)
      if (!seed) setSeed(effectiveSeed)
    } catch {
      setNotice('Проблема соединения с сервером. Проверьте, что сервис запущен.')
    } finally {
      inFlightRef.current = false
      setIsSubmitting(false)
    }
  }

  function onSourceFile(file: File | undefined) {
    if (!file) return
    const reader = new FileReader()
    reader.onload = () => setSourceImage(typeof reader.result === 'string' ? reader.result : undefined)
    reader.readAsDataURL(file)
  }

  const jobActive = !!job && JOB_ACTIVE.includes(job.status)
  const jobProgress = Math.max(0, Math.min(100, Math.round(job?.progress || 0)))
  const history = gallery.slice(0, 6)
  const selectedResolution = RESOLUTION_PRESETS.find((p) => p.id === resolutionId) || RESOLUTION_PRESETS[0]

  // Док «Промпт изображения»: выбранная миниатюра либо самая свежая генерация.
  const dockImage = gallery.find((g) => g.id === dockImageId) || gallery[0]

  // v3-студия: выбрать формат (соотношение сторон) — переключает разрешение на
  // первый пресет нужной ориентации.
  const selectRatio = (kind: 'square' | 'vertical' | 'horizontal') => {
    const preset = RESOLUTION_PRESETS.find((p) => p.kind === kind)
    if (preset) setResolutionId(preset.id)
  }

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
    setResultUrl(item.url)
    setResultSource(undefined)
    setDockImageId(item.id)
  }

  // ---------- Live Feed: карточка публикации ----------
  const feedCard = (post: FeedPublication) => (
    <article
      key={post.id}
      className={`nf-card ${feedShape(post.aspect_ratio)}${feedSelected?.id === post.id ? ' selected' : ''}`}
      onClick={() => {
        setFeedSelectedId(post.id)
        setFeedPromptExpanded(false)
        setFeedDetailOpen(true)
      }}
    >
      <div className="nf-card-image">
        {feedBroken.has(post.id) ? (
          <div className="nf-img-error" aria-label={feedLang === 'ru' ? 'Изображение недоступно' : 'Image unavailable'}>
            <span>⚠</span>
            {feedLang === 'ru' ? 'Изображение недоступно' : 'Image unavailable'}
          </div>
        ) : (
          // Сетка грузит СЖАТЫЙ thumbnail (не оригинал). Без loading="lazy":
          // в CSS multicolumn (masonry) нативный lazy ненадёжно триггерится и
          // карточки могут не прогрузиться; thumbnails малы (~56KB), грузим eager.
          <img
            src={apiUrl(post.thumbnail_url)}
            alt={post.title}
            decoding="async"
            onError={() => markFeedBroken(post.id)}
          />
        )}
        {post.badge && FEED_BADGE_LABELS[post.badge] && (
          <span className={`nf-tag badge-${post.badge}`}>{FEED_BADGE_LABELS[post.badge][feedLang]}</span>
        )}
        {post.is_current_user && <span className="nf-tag mine">{feedLang === 'ru' ? 'Ваша работа' : 'Yours'}</span>}
      </div>
      <div className="nf-card-body">
        <div className="nf-author">
          {post.author_avatar ? (
            <img className="nf-avatar-img" src={apiUrl(post.author_avatar)} alt="" decoding="async" />
          ) : (
            <span className="nf-avatar" aria-hidden="true">{(post.author_name[0] || 'A').toUpperCase()}</span>
          )}
          <span className="nf-author-text">
            <strong>{post.author_name}</strong>
            <span>{feedTimeAgo(post.created_at, feedLang)}</span>
          </span>
        </div>
        <h3>{post.title}</h3>
        <div className="nf-stats">
          <span>⟳ {feedCount(post.remix_count)}</span>
          <span>▣ {feedCount(post.save_count)}</span>
        </div>
        <div className="nf-card-actions">
          <button
            className="nf-remix"
            type="button"
            title={ft.remixHint}
            aria-label={ft.remixHint}
            onClick={(e) => {
              e.stopPropagation()
              startFeedRecreate(post)
            }}
          >
            ⟳ {ft.recreate}
          </button>
          <button
            className={`nf-save${post.is_liked_by_me ? ' active' : ''}`}
            type="button"
            aria-label={ft.like}
            title={ft.like}
            onClick={(e) => {
              e.stopPropagation()
              toggleFeedReaction(post, 'like')
            }}
          >
            {post.is_liked_by_me ? '♥' : '♡'}{post.like_count > 0 ? ` ${feedCount(post.like_count)}` : ''}
          </button>
          <button
            className={`nf-save${post.is_saved_by_me ? ' active' : ''}`}
            type="button"
            aria-label={ft.save}
            title={ft.save}
            onClick={(e) => {
              e.stopPropagation()
              toggleFeedReaction(post, 'save')
            }}
          >
            {post.is_saved_by_me ? '▣' : '▢'}
          </button>
        </div>
      </div>
    </article>
  )

  // ---------- Live Feed: панель подробностей ----------
  const feedDetail = feedSelected && (
    <div className="nf-detail-scroll">
      <div className="nf-detail-image">
        {feedBroken.has(feedSelected.id) ? (
          <div className="nf-img-error detail" aria-label={feedLang === 'ru' ? 'Изображение недоступно' : 'Image unavailable'}>
            <span>⚠</span>
            {feedLang === 'ru' ? 'Изображение недоступно' : 'Image unavailable'}
          </div>
        ) : (
          // Detail грузит СЖАТУЮ display-версию (large), не оригинал.
          <img src={apiUrl(feedSelected.display_url || feedSelected.image_url)} alt={feedSelected.title} onError={() => markFeedBroken(feedSelected.id)} />
        )}
        <span className="nf-ai-label">{feedLang === 'ru' ? 'Сгенерировано ИИ' : 'AI-generated'}</span>
      </div>
      <div className="nf-detail-author">
        <div className="nf-author">
          {feedSelected.author_avatar ? (
            <img className="nf-avatar-img big" src={apiUrl(feedSelected.author_avatar)} alt="" loading="lazy" />
          ) : (
            <span className="nf-avatar big" aria-hidden="true">{(feedSelected.author_name[0] || 'A').toUpperCase()}</span>
          )}
          <span className="nf-author-text">
            <strong>{feedSelected.author_name}</strong>
            <span>{feedTimeAgo(feedSelected.created_at, feedLang)}</span>
          </span>
        </div>
        {/* Подписки — backend будущей фазы: honest placeholder-кнопка. */}
        <button
          className="nf-follow"
          type="button"
          onClick={() => showToast(feedLang === 'ru' ? 'Подписки скоро появятся' : 'Follows are coming soon')}
        >
          {ft.follow}
        </button>
      </div>
      <h2 className="nf-detail-title">{feedSelected.title}</h2>
      <div className="nf-stats">
        <span>⟳ {feedCount(feedSelected.remix_count)} {ft.recreate.toLowerCase()}</span>
        <span>♥ {feedCount(feedSelected.like_count)}</span>
        <span>▣ {feedCount(feedSelected.save_count)}</span>
      </div>
      <div className="nf-prompt">
        <strong>
          {feedSelected.prompt_visibility === 'open'
            ? ft.promptOpen
            : feedSelected.prompt_visibility === 'partial'
              ? ft.promptPartial
              : ft.promptHidden}
        </strong>
        {feedSelected.prompt && (
          <>
            <span className={feedPromptExpanded ? '' : 'clamped'}>{feedSelected.prompt}</span>
            <button className="nf-more" type="button" onClick={() => setFeedPromptExpanded((v) => !v)}>
              {feedPromptExpanded ? ft.collapse : ft.showFull}
            </button>
          </>
        )}
      </div>
      <div className="nf-params">
        <div className="nf-param"><span>{feedLang === 'ru' ? 'Модель' : 'Model'}</span><strong>{feedSelected.model || '—'}</strong></div>
        <div className="nf-param"><span>{feedLang === 'ru' ? 'Стиль' : 'Style'}</span><strong>{feedSelected.style || '—'}</strong></div>
        <div className="nf-param"><span>{feedLang === 'ru' ? 'Соотношение' : 'Ratio'}</span><strong>{feedSelected.aspect_ratio}</strong></div>
        <div className="nf-param"><span>{feedLang === 'ru' ? 'Разрешение' : 'Resolution'}</span><strong>{feedSelected.resolution || '—'}</strong></div>
        <div className="nf-param"><span>Seed</span><strong>{feedSelected.seed ?? '—'}</strong></div>
        <div className="nf-param"><span>{feedLang === 'ru' ? 'Режим' : 'Mode'}</span><strong>{feedSelected.mode || '—'}</strong></div>
      </div>
      <div className="nf-detail-actions">
        <button
          className="nf-remix"
          type="button"
          title={ft.remixHint}
          aria-label={ft.remixHint}
          onClick={() => startFeedRecreate(feedSelected)}
        >
          ⟳ {ft.makeSimilar}
        </button>
        <button
          className={`nf-secondary${feedSelected.is_saved_by_me ? ' saved' : ''}`}
          type="button"
          onClick={() => toggleFeedReaction(feedSelected, 'save')}
        >
          {feedSelected.is_saved_by_me ? `▣ ${ft.saved}` : `▢ ${ft.save}`}
        </button>
        {feedSelected.style && I2I_STYLES.some((s) => s.name === feedSelected.style || s.id === feedSelected.style) && (
          <button className="nf-purple" type="button" onClick={() => applyFeedStyle(feedSelected)}>
            ✦ {ft.useStyle}
          </button>
        )}
      </div>
    </div>
  )

  // ---------- Live Feed: страница ----------
  const feedPlaceholderTab = feedTab === 'challenge' || feedTab === 'follow'

  const feed = (
    <section className="nf-page" aria-label={ft.feed}>
      <div className="nf-main n2-panel">
        <div className="nf-head">
          <nav className="nf-tabs" aria-label={ft.feed}>
            {feedTabs.map((tabDef) => (
              <button
                key={tabDef.id}
                className={`nf-tab${feedTab === tabDef.id ? ' active' : ''}`}
                type="button"
                onClick={() => setFeedTab(tabDef.id)}
              >
                {tabDef.label}
              </button>
            ))}
          </nav>
          {authStatus !== 'authed' && !feedPlaceholderTab && (
            <button className="nf-login-pill" type="button" onClick={() => setAuthOpen(true)}>
              {feedLang === 'ru' ? 'Войти для публикации' : 'Sign in to publish'}
            </button>
          )}
        </div>
        <div className="nf-grid-scroll">
          {feedPlaceholderTab ? (
            <div className="nf-empty">
              <span className="icon">✦</span>
              <h3>{ft.soonTitle}</h3>
              <p>
                {feedTab === 'challenge'
                  ? feedLang === 'ru'
                    ? 'Челленджи с призовым фондом появятся в следующей фазе.'
                    : 'Challenges with prize pools arrive in the next phase.'
                  : feedLang === 'ru'
                    ? 'Подписки на авторов появятся в следующей фазе.'
                    : 'Author follows arrive in the next phase.'}
              </p>
            </div>
          ) : feedLoading ? (
            <div className="nf-grid" aria-hidden="true">
              {Array.from({ length: 8 }).map((_, i) => (
                <div key={i} className={`nf-card nf-skeleton ${i % 3 === 0 ? 'tall' : i % 3 === 1 ? 'wide' : 'square'}`}>
                  <div className="nf-card-image" />
                  <div className="nf-skeleton-lines">
                    <span />
                    <span />
                  </div>
                </div>
              ))}
            </div>
          ) : feedError ? (
            <div className="nf-empty">
              <span className="icon error">!</span>
              <h3>{ft.errorTitle}</h3>
              <div className="nf-empty-actions">
                <button className="nf-remix" type="button" onClick={() => setFeedReload((n) => n + 1)}>
                  {ft.retry}
                </button>
              </div>
            </div>
          ) : feedItems.length === 0 ? (
            <div className="nf-empty">
              <span className="icon">▧</span>
              <h3>{ft.emptyTitle}</h3>
              <p>{ft.emptyText}</p>
              <div className="nf-empty-actions">
                {authStatus === 'authed' ? (
                  <>
                    <button className="nf-remix" type="button" onClick={openRealGallery}>
                      {ft.openGallery}
                    </button>
                    <button className="nf-secondary" type="button" onClick={() => setTab('text')}>
                      {ft.createImage}
                    </button>
                  </>
                ) : (
                  <>
                    <button className="nf-remix" type="button" onClick={() => setTab('text')}>
                      {ft.createImage}
                    </button>
                    <button className="nf-secondary" type="button" onClick={() => setAuthOpen(true)}>
                      {ft.login}
                    </button>
                  </>
                )}
              </div>
            </div>
          ) : (
            <div className="nf-grid">{feedItems.map(feedCard)}</div>
          )}
        </div>
      </div>

      <aside className={`nf-detail n2-panel${feedDetailOpen ? ' open' : ''}`} aria-label={ft.feed}>
        <button className="nf-detail-close" type="button" aria-label="Close" onClick={() => setFeedDetailOpen(false)}>
          ‹ {feedLang === 'ru' ? 'Назад к ленте' : 'Back to feed'}
        </button>
        {feedDetail || (
          <div className="nf-empty">
            <span className="icon">▧</span>
            <h3>{ft.emptyTitle}</h3>
          </div>
        )}
      </aside>

      <nav className="nf-mobile-nav" aria-label={feedLang === 'ru' ? 'Мобильная навигация' : 'Mobile navigation'}>
        <button type="button" onClick={() => setTab('text')}>
          <i>⌂</i>ИЗО
        </button>
        <button className="active" type="button" onClick={() => setFeedDetailOpen(false)}>
          <i>▦</i>{ft.feed}
        </button>
        <button type="button" onClick={openRealGallery}>
          <i>▧</i>{feedLang === 'ru' ? 'Галерея' : 'Gallery'}
        </button>
        <button
          type="button"
          onClick={() => {
            setFeedTab('challenge')
            setFeedDetailOpen(false)
          }}
        >
          <i>✦</i>{ft.challenges}
        </button>
        <button type="button" onClick={authStatus === 'authed' ? goProfile : () => setAuthOpen(true)}>
          <i>○</i>{ft.profile}
        </button>
      </nav>
    </section>
  )


  // ————————————————————————————————————————————————————————————————
  // v3-студия «Текст в изображение» (визуальный источник: прототип 14).
  // Функционально подключена только эта вкладка; остальные — честные заглушки.
  // ————————————————————————————————————————————————————————————————
  const dockPromptText = dockImage?.promptOriginal || prompts.text
  const ratioKind = selectedResolution.kind
  const shareTarget = dockImage || gallery[0]

  const textStudio = (
    <main className="layout">
      <aside className="sidebar">
        <div className="sidebar-head">
          <h1>Текст в изображение</h1>
          <button className={`pro-button${proMode ? ' active' : ''}`} type="button" onClick={() => setProMode((v) => !v)}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <path d="m4 19 1.4-11 4.4 4.4L12 5l2.2 7.4L18.6 8 20 19H4Z" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
            </svg>
            {proMode ? 'Режим Стандарт' : 'Режим Профи'}
          </button>
        </div>

        <section className="form-section prompt-section">
          <div className="section-title">
            <h2>Что хотите увидеть?</h2>
            <span className="help-dot" role="button" tabIndex={0} onClick={() => setHelpOpen(true)}>?</span>
          </div>
          <div className="prompt-card">
            <textarea
              placeholder="Опишите идею своими словами — получите изображение..."
              maxLength={2000}
              value={prompts.text}
              onChange={(e) => setPrompt(e.target.value)}
            />
            <div className="counter">{prompts.text.length} / 2000</div>
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
          </div>
        </section>

        <section className="form-section style-section">
          <div className="section-title">
            <h2>Стиль</h2>
            <span>{I2I_STYLES.length} стилей</span>
          </div>
          <div className="style-row">
            <figure
              className={`style-card no-style${!styleId ? ' active' : ''}`}
              role="button"
              tabIndex={0}
              onClick={() => applyStyle(null)}
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
                onClick={() => applyStyle(style)}
              >
                <img src={style.preview[previewGender]} alt={style.preview.alt} loading="lazy" />
                <figcaption>{style.name}</figcaption>
              </figure>
            ))}
          </div>
        </section>

        <section className="form-section format-section">
          <div className="section-title">
            <h2>Формат</h2>
          </div>
          <div className="control-row">
            <select
              className="resolution"
              aria-label="Разрешение"
              value={resolutionId}
              onChange={(e) => setResolutionId(e.target.value)}
            >
              {RESOLUTION_PRESETS.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.width}×{p.height}
                </option>
              ))}
            </select>
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

        <button className="generate-button" type="button" disabled={!canGenerate} onClick={() => generate('text')}>
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path d="M12 3.5l1.9 4.8 4.8 1.9-4.8 1.9-1.9 4.9-1.9-4.9-4.8-1.9 4.8-1.9L12 3.5Z" fill="currentColor" />
          </svg>
          {jobActive || isSubmitting ? 'Генерируем...' : 'Сгенерировать'}
        </button>
      </aside>

      <section className="preview-panel">
        <div className="mobile-title-row">
          <h1>Текст в изображение</h1>
          <button className={`pro-button${proMode ? ' active' : ''}`} type="button" onClick={() => setProMode((v) => !v)}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <path d="m4 19 1.4-11 4.4 4.4L12 5l2.2 7.4L18.6 8 20 19H4Z" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
            </svg>
            {proMode ? 'Режим Стандарт' : 'Режим Профи'}
          </button>
        </div>
        <div className="preview-image">
          {jobActive ? (
            <div className="iv3-preview-loading">
              <span className="iv3-spinner" aria-hidden="true"></span>
              <span>Генерируем{jobProgress > 0 ? ` · ${jobProgress}%` : '...'}</span>
            </div>
          ) : resultUrl && !resultError ? (
            <>
              <img src={resultUrl} alt="Результат генерации" onError={() => setResultError(true)} />
              <div className="image-actions">
                {resultUrl && (
                  <a className="image-action" href={resultUrl} download target="_blank" rel="noreferrer">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                      <path d="M12 3v12m0 0 4-4m-4 4-4-4M5 19h14" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                    Скачать
                  </a>
                )}
                <button className="image-action" type="button" onClick={() => setShareOpen((v) => !v)}>
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                    <path d="M18 8a3 3 0 1 0-2.82-4M6 13a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm12 8a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM8.7 10.7l6.6 3.6M15.3 9.7l-6.6 3.6" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
                  </svg>
                  Поделиться
                </button>
                {shareOpen && (
                  <div className="iv3-share-menu">
                    <button type="button" onClick={() => { setShareOpen(false); if (shareTarget) openPublish(shareTarget); else showToast('Сначала сгенерируйте изображение') }}>В ленту</button>
                    <button type="button" onClick={() => { setShareOpen(false); if (resultUrl) copyPrompt(apiUrl(resultUrl)) }}>Скопировать ссылку</button>
                  </div>
                )}
              </div>
            </>
          ) : (
            <div className="iv3-preview-empty">
              <span className="iv3-preview-empty-mark" aria-hidden="true">✦</span>
              <p>{resultError ? 'Изображение недоступно. Сгенерируйте заново.' : 'Опишите идею слева и нажмите «Сгенерировать»'}</p>
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
          <div className="history-carousel" aria-label="Навигация истории">
            <div className="history-strip">
              {history.length === 0 ? (
                <span className="iv3-history-empty">История пуста</span>
              ) : (
                history.map((item) => (
                  <figure
                    key={item.id}
                    className={`history-item${dockImage?.id === item.id ? ' active' : ''}`}
                    role="button"
                    tabIndex={0}
                    onClick={() => openHistory(item)}
                  >
                    <img src={apiUrl(item.thumbnailUrl || item.url)} alt={item.promptOriginal.slice(0, 40)} loading="lazy" />
                  </figure>
                ))
              )}
            </div>
          </div>
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
                <button type="button" onClick={() => { if (dockImage) setSourceImage(apiUrl(dockImage.url)); setTab('i2i') }}>Изо</button>
                <button type="button" onClick={() => setTab('edit')}>Редактор</button>
                <button type="button" onClick={() => setTab('paint')}>Рисунок</button>
                <button type="button" onClick={() => setTab('face')}>Лицо</button>
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
      <div className="iv3-placeholder-card">
        <span className="iv3-preview-empty-mark" aria-hidden="true">✦</span>
        <h2>{title}</h2>
        <p>{note}</p>
        <button className="iv3-placeholder-cta" type="button" onClick={() => setTab('text')}>
          Перейти в «Текст → Изо»
        </button>
      </div>
    </div>
  )

  const topActive: V3Section = tab === 'feed' ? 'feed' : (tab as V3Section)

  return (
    <div className="n2">
      <AuthV2Modal open={authOpen} onClose={() => setAuthOpen(false)} />
      {toastText && (
        <div className="nf-toast" role="status">
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
          <div className="n2-overlay-card" onClick={(e) => e.stopPropagation()}>
            <button className="n2-overlay-close" type="button" aria-label="Закрыть" onClick={() => setHelpOpen(false)}>
              ×
            </button>
            <h2>Как это работает</h2>
            <p>
              <strong>Текст → Изо</strong>: опишите идею словами, выберите стиль (он допишется в запрос) и формат,
              нажмите «Сгенерировать».
            </p>
            <p>
              <strong>Изо → Изо</strong>: загрузите исходник, выберите стиль преобразования, при желании уточните
              текстом. Ползунок «Влияние промпта» решает, насколько сильно менять фото; рекомендуем 75%.
            </p>
            <p>
              <strong>Шаблоны</strong> — готовые идеи для каждой вкладки, <strong>Случайно</strong> подставляет
              случайный шаблон.
            </p>
            <p>
              <strong>Лента</strong> — будущая соцсеть: публикуйте лучшие работы, собирайте лайки и комментарии.
            </p>
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
                    className={`n2-template-style${styleId === style.id ? ' active' : ''}`}
                    type="button"
                    onClick={() => {
                      applyStyle(style)
                      setTemplatesOpen(false)
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

      {galleryPickOpen && (
        <div className="n2-overlay" role="dialog" aria-label="Выбор из галереи" onClick={() => setGalleryPickOpen(false)}>
          <div className="n2-overlay-card n2-templates" onClick={(e) => e.stopPropagation()}>
            <button className="n2-overlay-close" type="button" aria-label="Закрыть" onClick={() => setGalleryPickOpen(false)}>
              ×
            </button>
            <h2>Выберите исходник из галереи</h2>
            <div className="n2-templates-styles">
              {gallery.map((item) => (
                <button
                  key={item.id}
                  className="n2-template-style"
                  type="button"
                  title={item.promptOriginal}
                  onClick={() => {
                    setSourceImage(item.url)
                    setGalleryPickOpen(false)
                  }}
                >
                  <img src={item.thumbnailUrl || item.url} alt={item.promptOriginal.slice(0, 60)} loading="lazy" />
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
            <img className="nf-publish-preview" src={apiUrl(publishFor.thumbnailUrl || publishFor.url)} alt="" />
            <label className="nf-publish-field">
              <span>{feedLang === 'ru' ? 'Название' : 'Title'}</span>
              <input
                type="text"
                maxLength={120}
                value={publishTitle}
                onChange={(e) => setPublishTitle(e.target.value)}
              />
            </label>
            <label className="nf-publish-field">
              <span>{feedLang === 'ru' ? 'Видимость промпта' : 'Prompt visibility'}</span>
              <select value={publishVisibility} onChange={(e) => setPublishVisibility(e.target.value as 'open' | 'partial' | 'hidden')}>
                <option value="open">{feedLang === 'ru' ? 'Открытый' : 'Open'}</option>
                <option value="partial">{feedLang === 'ru' ? 'Частично' : 'Partial'}</option>
                <option value="hidden">{feedLang === 'ru' ? 'Скрыт' : 'Hidden'}</option>
              </select>
            </label>
            <label className="nf-publish-check">
              <input
                type="checkbox"
                checked={publishAllowRecreate}
                onChange={(e) => setPublishAllowRecreate(e.target.checked)}
              />
              <span>{feedLang === 'ru' ? `Разрешить «${ft.recreate}»` : `Allow "${ft.recreate}"`}</span>
            </label>
            <div className="n2-overlay-actions">
              <button className="nf-remix" type="button" disabled={publishBusy} onClick={submitPublish}>
                {publishBusy ? '…' : ft.publish}
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="iv3">
        <div className="app-shell">
          <TopBarV3
            active={topActive}
            authed={authStatus === 'authed'}
            onSelectMode={(m) => { if (m !== 'video') setTab(m) }}
            onOpenFeed={() => setTab('feed')}
            onOpenGallery={goGallery}
            onOpenHelp={() => setHelpOpen(true)}
            onOpenProfile={authStatus === 'authed' ? goProfile : () => setAuthOpen(true)}
          />
          {tab === 'feed' ? (
            <div className="iv3-content iv3-feed">{feed}</div>
          ) : tab === 'text' ? (
            textStudio
          ) : tab === 'i2i' ? (
            placeholderStudio('Изо → Изо', 'Загрузка исходника и преобразование по стилю появятся здесь в новом дизайне. Функционал уже работает в текущей версии.')
          ) : tab === 'edit' ? (
            placeholderStudio('Редактор', 'Основа и референсы с ролями (лицо, одежда, стиль, фон) переносятся в новый интерфейс следующим этапом.')
          ) : tab === 'paint' ? (
            placeholderStudio('Рисунок', 'Эскиз, маска и расширение появятся здесь в новом дизайне. Функционал уже работает в текущей версии.')
          ) : tab === 'face' ? (
            placeholderStudio('Лицо', 'Замена лица (FaceSwap) появится здесь в новом дизайне. Функционал уже работает в текущей версии.')
          ) : (
            placeholderStudio('Скоро', 'Раздел в разработке.')
          )}
        </div>
      </div>
    </div>
  )
}
