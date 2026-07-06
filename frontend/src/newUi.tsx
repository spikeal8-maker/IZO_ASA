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
import './newUi.css'

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
type N2View = 'tabs' | 'gallery'

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

const TABS: Array<{ id: N2Tab; label: string; feed?: boolean }> = [
  { id: 'feed', label: '✦ Лента', feed: true },
  { id: 'text', label: 'Текст → Изо' },
  { id: 'i2i', label: 'Изо → Изо' },
  { id: 'edit', label: 'Редактор' },
  { id: 'paint', label: 'Рисунок' },
  { id: 'face', label: 'Лицо' },
]

const QUALITY: Array<{ id: string; label: string; steps: number }> = [
  { id: 'fast', label: 'Быстро', steps: 4 },
  { id: 'standard', label: 'Стандарт', steps: 6 },
  { id: 'max', label: 'Максимум', steps: 10 },
]

// Заготовленные разрешения системы. Источник данных — resolutionPresets
// основного интерфейса (App.tsx) + средний размер 1536 (максимум генерации,
// см. fitGenerationDimension). Перенесены данные, не вёрстка.
type FormatId = 'square' | 'vertical' | 'horizontal'

const FORMATS: Array<{ id: FormatId; label: string; icon: string }> = [
  { id: 'square', label: 'Квадрат 1:1', icon: 'square' },
  { id: 'vertical', label: 'Вертикально 9:16', icon: 'vertical' },
  { id: 'horizontal', label: 'Горизонтально 16:9', icon: 'horizontal' },
]

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

const FORMAT_KIND_MARK: Record<FormatId, string> = { square: '◼', vertical: '▯', horizontal: '▭' }

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
    recreate: 'Повторить',
    makeSimilar: 'Сделать похожее',
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
  },
  en: {
    feed: 'Feed',
    forYou: 'For you',
    fresh: 'New',
    top: 'Top',
    challenges: 'Challenges',
    follows: 'Following',
    recreate: 'Recreate',
    makeSimilar: 'Make similar',
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
  },
}

// Модель публикации = ответ GET /api/feed (snake_case backend-контракта).
interface FeedPublication {
  id: string
  image_url: string
  thumbnail_url: string
  user_id: string
  author_name: string
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
  is_liked_by_me: boolean
  is_saved_by_me: boolean
  is_mine: boolean
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
  const [tab, setTabState] = useState<N2Tab>('feed')
  const [view, setView] = useState<N2View>('tabs')

  // Канонический маршрут Ленты — /feed (короткий, из старого интерфейса);
  // /new/feed остаётся рабочим синонимом.
  const setTab = useCallback((next: N2Tab) => {
    setTabState(next)
    const target = next === 'feed' ? '/feed' : '/new'
    if (window.location.pathname !== target) window.history.pushState(null, '', target)
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
  const [hoverStyle, setHoverStyle] = useState<StylePreset | null>(null)
  // Разрешение = конкретный системный пресет; формат-кнопки переключают тип.
  const [resolutionId, setResolutionId] = useState('sq-1024')
  const [quality, setQuality] = useState('fast')
  const [proMode, setProMode] = useState(false)
  const [seed, setSeed] = useState(0)
  const [guidance, setGuidance] = useState(3.5)
  const [strengthPct, setStrengthPct] = useState(75)
  const [sourceImage, setSourceImage] = useState<string>()
  const [compare, setCompare] = useState(50)

  // Вкладка «Рисунок»: выбор режима (UX-структура; сам холст — отдельная фаза).
  const [paintMode, setPaintMode] = useState<'sketch' | 'mask' | 'expand'>('sketch')

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

  // «Открыть галерею» из Ленты → РЕАЛЬНАЯ рабочая галерея старого интерфейса
  // (не сырая /new-галерея), где есть «Опубликовать в ленту».
  const openRealGallery = useCallback(() => {
    window.location.href = '/?open=gallery'
  }, [])

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
    const apiType = feedTab === 'new' ? 'new' : 'top'
    apiFetch(`/feed?type=${apiType}&limit=40`)
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
    if (post.prompt) {
      setPrompts((cur) => ({ ...cur, text: post.prompt || '' }))
      showToast(feedLang === 'ru' ? 'Промпт подставлен — генерируйте свою версию' : 'Prompt prefilled — generate your version')
    } else {
      setPrompts((cur) => ({ ...cur, text: '' }))
      showToast(
        feedLang === 'ru'
          ? 'Промпт скрыт автором — опишите идею своими словами'
          : 'Prompt is hidden — describe the idea in your own words',
      )
    }
    setFeedDetailOpen(false)
    setTab('text')
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
  const [jobMode, setJobMode] = useState<'text' | 'i2i'>('text')
  const [resultUrl, setResultUrl] = useState<string>()
  // URL результата не загрузился (битая ссылка/удалённый файл) — error-state.
  const [resultError, setResultError] = useState(false)
  const [resultSource, setResultSource] = useState<string>()
  const [notice, setNotice] = useState('')
  const [gallery, setGallery] = useState<N2GalleryImage[]>([])
  const [galleryItem, setGalleryItem] = useState<N2GalleryImage>()
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
  const prompt = prompts[promptKey]
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

  function uploadSource() {
    fileInputRef.current?.click()
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
  const loadingBackdrop = resultSource || gallery[0]?.url
  const selectedResolution = RESOLUTION_PRESETS.find((p) => p.id === resolutionId) || RESOLUTION_PRESETS[0]
  const selectedStyle = styleId ? I2I_STYLES.find((s) => s.id === styleId) || null : null

  const showResult = useCallback((url: string | undefined, source?: string) => {
    setResultError(false)
    setResultUrl(url)
    setResultSource(source)
  }, [])

  const progressCard = (
    <div className="n2-progress">
      {loadingBackdrop && <img className="n2-progress-backdrop" src={loadingBackdrop} alt="" aria-hidden="true" />}
      <div className="n2-progress-inner">
        <span className="n2-progress-title">Генерация…</span>
        <div className="n2-progress-track">
          <div
            className={`n2-progress-fill${jobProgress === 0 ? ' indeterminate' : ''}`}
            style={jobProgress > 0 ? { width: `${jobProgress}%` } : undefined}
          />
        </div>
        <span className="n2-progress-note">{jobProgress > 0 ? `${jobProgress}%` : job?.message || job?.status}</span>
      </div>
    </div>
  )

  // Мобильный предпросмотр: живёт между промптом и стилями (на десктопе скрыт).
  const mobilePreview = (
    <div className="n2-mobile-preview" aria-label="Предпросмотр результата">
      {jobActive ? (
        progressCard
      ) : resultUrl && !resultError ? (
        <img
          className="n2-mobile-preview-img"
          src={resultUrl}
          alt="Результат генерации"
          onError={() => setResultError(true)}
        />
      ) : (
        <div className="n2-mobile-preview-empty">
          <span className="n2-mobile-preview-icon">▧</span>
          <span>Здесь появится сгенерированное изображение</span>
        </div>
      )}
    </div>
  )

  // Drag-scroll ленты стилей мышью (touch остаётся нативным). Клик после
  // перетаскивания подавляется, чтобы случайно не выбрать стиль.
  const styleScrollRef = useRef<HTMLDivElement | null>(null)
  const styleDragRef = useRef({ active: false, moved: false, startX: 0, startScroll: 0 })

  const onStyleScrollPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    if (e.pointerType !== 'mouse' || e.button !== 0) return
    const el = styleScrollRef.current
    if (!el) return
    styleDragRef.current = { active: true, moved: false, startX: e.clientX, startScroll: el.scrollLeft }
    el.classList.add('dragging')
    el.setPointerCapture(e.pointerId)
  }

  const onStyleScrollPointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    const drag = styleDragRef.current
    const el = styleScrollRef.current
    if (!drag.active || !el) return
    const delta = e.clientX - drag.startX
    if (Math.abs(delta) > 5) drag.moved = true
    el.scrollLeft = drag.startScroll - delta
  }

  const onStyleScrollPointerEnd = (e: React.PointerEvent<HTMLDivElement>) => {
    const el = styleScrollRef.current
    if (!styleDragRef.current.active || !el) return
    styleDragRef.current.active = false
    el.classList.remove('dragging')
    if (el.hasPointerCapture(e.pointerId)) el.releasePointerCapture(e.pointerId)
  }

  const onStyleScrollClickCapture = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!styleDragRef.current.moved) return
    styleDragRef.current.moved = false
    e.preventDefault()
    e.stopPropagation()
  }

  // Вертикальное колесо/трекпад скроллит ленту горизонтально. Нативный
  // listener c passive:false — React-обработчик wheel не даёт preventDefault.
  useEffect(() => {
    const el = styleScrollRef.current
    if (!el) return
    const onWheel = (event: WheelEvent) => {
      if (Math.abs(event.deltaY) > Math.abs(event.deltaX)) {
        event.preventDefault()
        el.scrollLeft += event.deltaY
      }
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [tab])

  const stylesStrip = (
    <div className="n2-block">
      <div className="n2-label-row">
        <strong>Стиль</strong>
        <span>{I2I_STYLES.length} стилей</span>
      </div>
      <div
        ref={styleScrollRef}
        className="n2-style-scroll"
        aria-label="Выбор стиля"
        onMouseLeave={() => setHoverStyle(null)}
        onPointerDown={onStyleScrollPointerDown}
        onPointerMove={onStyleScrollPointerMove}
        onPointerUp={onStyleScrollPointerEnd}
        onPointerCancel={onStyleScrollPointerEnd}
        onClickCapture={onStyleScrollClickCapture}
      >
        <button
          className={`n2-style-card${styleId === '' ? ' active' : ''}`}
          type="button"
          onClick={() => applyStyle(null)}
          onMouseEnter={() => setHoverStyle(null)}
        >
          <span className="n2-style-art none">∅</span>
          <span className="n2-style-name">Без стиля</span>
        </button>
        {I2I_STYLES.map((style) => (
          <button
            key={style.id}
            className={`n2-style-card${styleId === style.id ? ' active' : ''}`}
            type="button"
            title={style.name}
            onClick={() => applyStyle(style)}
            onMouseEnter={() => setHoverStyle(style)}
          >
            <img className="n2-style-art" src={style.preview[previewGender]} alt={style.preview.alt} loading="lazy" />
            <span className="n2-style-name">{style.name}</span>
          </button>
        ))}
      </div>
    </div>
  )

  // Единый каркас вкладки: заголовок + короткое описание над рабочей областью.
  const viewHead = (title: string, description: string) => (
    <div className="n2-view-head">
      <h2>{title}</h2>
      <p>{description}</p>
    </div>
  )

  const controls = (mode: 'text' | 'i2i') => (
    <section className="n2-panel n2-controls" aria-label="Панель генерации">
      <div className="n2-controls-scroll">
        {mode === 'i2i'
          ? viewHead('Изо → Изо', 'Загрузите фото и преобразуйте его в выбранный стиль.')
          : viewHead('Текст → Изо', 'Опишите идею словами — получите изображение.')}
        {mode === 'i2i' && (
          <div className="n2-block n2-source-card">
            <div className="n2-label-row">
              <strong>Источник</strong>
              <span>{sourceImage ? '1 изображение' : 'не выбран'}</span>
            </div>
            <div className="n2-source-layout">
              <div className={`n2-source-preview${sourceImage ? ' selected' : ''}`}>
                {sourceImage ? (
                  <>
                    <img src={sourceImage} alt="Исходное изображение" />
                    <button
                      className="n2-source-remove"
                      type="button"
                      aria-label="Убрать изображение"
                      onClick={() => setSourceImage(undefined)}
                    >
                      ×
                    </button>
                  </>
                ) : (
                  <div className="n2-source-state">
                    <strong>Выберите исходник</strong>
                    <span>PNG, JPG до 20 МБ</span>
                    <div className="n2-source-buttons">
                      <button className="n2-source-button" type="button" onClick={uploadSource}>
                        ＋ Загрузить
                      </button>
                      <button
                        className="n2-source-button"
                        type="button"
                        disabled={gallery.length === 0}
                        onClick={() => setGalleryPickOpen(true)}
                      >
                        ▧ Галерея
                      </button>
                      <button
                        className="n2-source-button"
                        type="button"
                        disabled={gallery.length === 0}
                        onClick={() => setSourceImage(gallery[0]?.url)}
                      >
                        ↺ Последнее
                      </button>
                    </div>
                  </div>
                )}
              </div>
              <div className="n2-influence">
                <div className="n2-slider-head">
                  <span>Влияние промпта</span>
                  <span className="n2-slider-value">{strengthPct}%</span>
                </div>
                <div className="n2-range-wrap">
                  <input
                    type="range"
                    min={0}
                    max={100}
                    value={strengthPct}
                    aria-label="Влияние промпта"
                    onChange={(e) => setStrengthPct(Number(e.target.value))}
                  />
                </div>
                <div className="n2-slider-labels">
                  <span>0: ближе к фото</span>
                  <span>100: больше промпта</span>
                </div>
                <p className="n2-recommend-note">Рекомендуем 75%. Выше 80% исходник почти не сохраняется.</p>
              </div>
            </div>
          </div>
        )}

        <div className="n2-block n2-prompt-block">
          <div className="n2-label-row">
            <strong>{mode === 'i2i' ? 'Что изменить?' : 'Что хотите увидеть?'}</strong>
            {/* i2i: стиль применяется как transform-prompt под капотом — показываем
                его пользователю явным чипом (крестик снимает стиль). */}
            {mode === 'i2i' && selectedStyle ? (
              <button
                className="n2-style-chip"
                type="button"
                title={`Стиль применяется к генерации: ${selectedStyle.stylePrompt.slice(0, 120)}…`}
                onClick={() => applyStyle(null)}
              >
                Стиль: {selectedStyle.name} <span aria-hidden="true">×</span>
              </button>
            ) : (
              <span>Главный шаг</span>
            )}
          </div>
          <div className="n2-prompt-card">
            <textarea
              maxLength={2000}
              value={prompt}
              placeholder={mode === 'i2i' ? 'Опишите, что изменить в изображении…' : 'Опишите идею обычными словами…'}
              aria-label="Запрос для генерации"
              onChange={(e) => setPrompt(e.target.value)}
            />
            <div className="n2-counter">{prompt.length} / 2000</div>
          </div>
          <div className="n2-quick-actions">
            <button className="n2-mini" type="button" disabled title="Скоро">
              ✦ Улучшить
            </button>
            <button className="n2-mini" type="button" onClick={() => setTemplatesOpen(true)}>
              ▦ Шаблоны
            </button>
            <button className="n2-mini" type="button" onClick={randomPrompt}>
              ◈ Случайно
            </button>
          </div>
        </div>

        {mobilePreview}

        {stylesStrip}

        <div className="n2-block">
          <div className="n2-label-row">
            <strong>Формат</strong>
          </div>
          <div className="n2-format-row" aria-label="Формат и разрешение">
            <label className="n2-resolution-cell">
              <span>Разрешение</span>
              {/* Закрытый вид показывает только W×H; полный список — в option. */}
              <span className="n2-resolution-display">
                <span className="n2-resolution-value">
                  {selectedResolution.width}×{selectedResolution.height}
                </span>
                <select
                  value={resolutionId}
                  aria-label="Разрешение изображения"
                  onChange={(e) => setResolutionId(e.target.value)}
                >
                  {RESOLUTION_PRESETS.map((preset) => (
                    <option key={preset.id} value={preset.id}>
                      {FORMAT_KIND_MARK[preset.kind]} {preset.name} · {preset.width}×{preset.height}
                    </option>
                  ))}
                </select>
              </span>
            </label>
            {FORMATS.map((format) => (
              <button
                key={format.id}
                className={`n2-format-button${selectedResolution.kind === format.id ? ' active' : ''}`}
                type="button"
                onClick={() => {
                  if (selectedResolution.kind !== format.id) setResolutionId(DEFAULT_PRESET_BY_KIND[format.id])
                }}
              >
                <span className={`n2-format-icon ${format.icon}`} />
                {format.label}
              </button>
            ))}
          </div>
        </div>

        <div className="n2-segmented-wrap" aria-label="Сложность интерфейса">
          <div className="n2-segmented">
            <button className={proMode ? '' : 'active'} type="button" onClick={() => setProMode(false)}>
              Простой
            </button>
            <button className={proMode ? 'active' : ''} type="button" onClick={() => setProMode(true)}>
              Pro
            </button>
          </div>
          <div className="n2-quality-inline" aria-label="Качество генерации">
            {QUALITY.map((item) => (
              <button
                key={item.id}
                className={`n2-quality-button${quality === item.id ? ' active' : ''}`}
                type="button"
                onClick={() => setQuality(item.id)}
              >
                {item.label}
              </button>
            ))}
          </div>
        </div>

        {proMode && (
          <div className="n2-pro-panel" aria-label="Pro настройки">
            <div className="n2-pro-field">
              <span>Seed (0 — случайный)</span>
              <input
                type="number"
                min={0}
                value={seed}
                aria-label="Seed"
                onChange={(e) => setSeed(Math.max(0, Number(e.target.value) || 0))}
              />
            </div>
            <div className="n2-pro-field">
              <span>Guidance</span>
              <select value={guidance} aria-label="Guidance" onChange={(e) => setGuidance(Number(e.target.value))}>
                <option value={2.5}>Мягко (2.5)</option>
                <option value={3.5}>Стандарт (3.5)</option>
                <option value={5}>Точно (5.0)</option>
              </select>
            </div>
          </div>
        )}
      </div>

      {/* Док: кнопка генерации всегда привязана к низу панели и видна во всех состояниях. */}
      <div className="n2-dock">
        {notice && <div className="n2-notice">{notice}</div>}
        <button className="n2-generate" type="button" disabled={!canGenerate} onClick={() => void generate(mode)}>
          {jobActive ? 'Генерация…' : mode === 'i2i' ? '✦ Преобразовать' : '✦ Сгенерировать'}
        </button>
      </div>
    </section>
  )

  // Статус предпросмотра — единое состояние empty/loading/error/result
  // (+ временный режим «Предпросмотр стиля» при наведении на карточку стиля).
  const resultStatus = hoverStyle
    ? { label: 'Предпросмотр стиля', tone: 'busy' }
    : jobActive
      ? { label: 'Генерация…', tone: 'busy' }
      : resultError || job?.status === 'failed'
        ? { label: 'Ошибка', tone: 'error' }
        : resultUrl
          ? { label: 'Готово', tone: 'done' }
          : { label: 'Пусто', tone: 'idle' }

  const resultPanel = (
    <section className="n2-panel n2-result" aria-label="Предпросмотр результата">
      <div className="n2-result-head">
        <h3>Предпросмотр</h3>
        <span className={`n2-status-chip ${resultStatus.tone}`}>{resultStatus.label}</span>
      </div>
      <div className="n2-canvas">
        {hoverStyle ? (
          <div className="n2-style-preview" aria-label={`Предпросмотр стиля: ${hoverStyle.name}`}>
            <img src={hoverStyle.preview[previewGender]} alt={hoverStyle.preview.alt} />
            <div className="n2-style-preview-caption">
              <strong>{hoverStyle.name}</strong>
              <span>Нажмите на карточку, чтобы применить стиль</span>
            </div>
          </div>
        ) : jobActive ? (
          progressCard
        ) : resultError ? (
          <div className="n2-empty">
            <div className="n2-empty-icon error">!</div>
            <div>
              <h2>Изображение недоступно</h2>
              <p>Файл результата не загрузился — возможно, он был удалён. Попробуйте сгенерировать заново.</p>
            </div>
          </div>
        ) : resultUrl && jobMode === 'i2i' && resultSource ? (
          <div className="n2-compare" style={{ ['--compare' as string]: `${compare}%` }} aria-label="Сравнение до и после">
            <div className="n2-compare-layer">
              <img src={resultSource} alt="До" />
            </div>
            <div className="n2-compare-layer after">
              <img src={resultUrl} alt="После" />
            </div>
            <span className="n2-compare-label before">До</span>
            <span className="n2-compare-label after-label">После</span>
            <div className="n2-compare-handle" />
            <input
              className="n2-compare-range"
              type="range"
              min={0}
              max={100}
              value={compare}
              aria-label="Ползунок сравнения до и после"
              onChange={(e) => setCompare(Number(e.target.value))}
            />
          </div>
        ) : resultUrl ? (
          <img
            className="n2-result-image"
            src={resultUrl}
            alt="Результат генерации"
            onError={() => setResultError(true)}
          />
        ) : (
          <div className="n2-empty">
            <div className="n2-empty-icon">▧</div>
            <div>
              <h2>Результат появится здесь</h2>
              <p>Ваше изображение будет сгенерировано на основе указанного описания.</p>
            </div>
          </div>
        )}
      </div>
      <div className="n2-result-bottom">
        <div className="n2-history">
          <h3>История</h3>
          {history.length === 0 && <p className="n2-history-empty">Пока пусто — создайте первое изображение.</p>}
          <div className="n2-thumb-row" aria-label="Последние изображения">
            {history.map((item) => (
              <button
                key={item.id}
                className={`n2-thumb${resultUrl === item.url ? ' active' : ''}`}
                type="button"
                title={item.promptOriginal}
                onClick={() => showResult(item.url)}
              >
                <img src={item.thumbnailUrl || item.url} alt={item.promptOriginal.slice(0, 60)} loading="lazy" />
              </button>
            ))}
          </div>
        </div>
        <div className="n2-tip">
          <h3>Совет</h3>
          <p>Укажите объект, стиль, свет и ракурс — так результат обычно получается точнее.</p>
        </div>
      </div>
    </section>
  )

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
          <img
            src={apiUrl(post.thumbnail_url || post.image_url)}
            alt={post.title}
            loading="lazy"
            decoding="async"
            onError={() => markFeedBroken(post.id)}
          />
        )}
        {post.prompt_visibility === 'open' && (
          <span className="nf-tag">{feedLang === 'ru' ? 'Открытый промпт' : 'Open prompt'}</span>
        )}
        {post.is_mine && <span className="nf-tag mine">{feedLang === 'ru' ? 'Ваша работа' : 'Yours'}</span>}
      </div>
      <div className="nf-card-body">
        <div className="nf-author">
          <span className="nf-avatar" aria-hidden="true">{(post.author_name[0] || 'A').toUpperCase()}</span>
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
          <img
            src={apiUrl(feedSelected.image_url)}
            alt={feedSelected.title}
            decoding="async"
            onError={() => markFeedBroken(feedSelected.id)}
          />
        )}
        <span className="nf-ai-label">{feedLang === 'ru' ? 'Сгенерировано ИИ' : 'AI-generated'}</span>
      </div>
      <div className="nf-detail-author">
        <div className="nf-author">
          <span className="nf-avatar big" aria-hidden="true">{(feedSelected.author_name[0] || 'A').toUpperCase()}</span>
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
        <button className="nf-remix" type="button" onClick={() => startFeedRecreate(feedSelected)}>
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
        <button type="button" onClick={() => setAuthOpen(true)}>
          <i>○</i>{feedLang === 'ru' ? 'Профиль' : 'Profile'}
        </button>
      </nav>
    </section>
  )

  const galleryView = (
    <section className="n2-panel n2-gallery" aria-label="Галерея">
      <div className="n2-gallery-head">
        <div>
          <h2>Галерея</h2>
          <p>{authStatus === 'authed' ? 'Ваши генерации: открыть, скачать или опубликовать в ленту.' : 'Лента открыта всем, личная галерея доступна после входа.'}</p>
        </div>
        <div className="n2-gallery-head-actions">
          {authStatus !== 'authed' && (
            <button className="n2-ghost purple" type="button" onClick={() => setAuthOpen(true)}>
              Войти
            </button>
          )}
          <button className="n2-ghost" type="button" onClick={() => setView('tabs')}>
            ← Назад
          </button>
        </div>
      </div>
      {gallery.length === 0 ? (
        <div className="n2-placeholder-card">
          <span className="icon">▧</span>
          <h2>Здесь будут ваши изображения</h2>
          <p>{authStatus === 'authed' ? 'Сгенерируйте первое изображение — оно появится в галерее.' : 'Войдите, чтобы увидеть свои генерации.'}</p>
          {authStatus !== 'authed' && (
            <button className="n2-ghost" type="button" onClick={() => setAuthOpen(true)}>
              Войти
            </button>
          )}
        </div>
      ) : (
        <div className="n2-gallery-grid">
          {gallery.map((item) => (
            <article key={item.id} className="n2-gallery-card">
              <button className="n2-gallery-thumb" type="button" title={item.promptOriginal} onClick={() => setGalleryItem(item)}>
                <img src={apiUrl(item.thumbnailUrl || item.url)} alt={item.promptOriginal.slice(0, 60)} loading="lazy" />
              </button>
              <div className="n2-gallery-card-body">
                <strong>{item.mode || 'image'}</strong>
                <small>{feedTimeAgo(item.createdAt, feedLang)}</small>
                <p>{item.promptOriginal || '—'}</p>
                <div className="n2-gallery-card-actions">
                  <button className="n2-gallery-mini" type="button" onClick={() => setGalleryItem(item)}>
                    Открыть
                  </button>
                  <button className="n2-gallery-mini publish" type="button" onClick={() => openPublish(item)}>
                    ✦ В ленту
                  </button>
                </div>
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  )

  // «Рисунок»: структура режимов Эскиз/Маска/Расширение. Холст и генерация для
  // этих режимов — placeholder (честно подписан), функционал живёт в текущей версии.
  const paintSize = RESOLUTION_PRESETS.find((p) => p.id === resolutionId) || RESOLUTION_PRESETS[0]
  const paintModes: Array<{ id: 'sketch' | 'mask' | 'expand'; icon: string; title: string; hint: string; meta?: string }> = [
    {
      id: 'sketch',
      icon: '✎',
      title: 'Эскиз',
      hint: 'Нарисуйте набросок — он станет основой изображения',
      meta: `${paintSize.width}×${paintSize.height}`,
    },
    {
      id: 'mask',
      icon: '◧',
      title: 'Маска',
      hint: 'Изменить выделенную область изображения',
    },
    {
      id: 'expand',
      icon: '⇱',
      title: 'Расширение',
      hint: 'Дорисовать края изображения под выбранный формат',
    },
  ]

  const paintView = (
    <section className="n2-panel n2-paint" aria-label="Рисунок">
      <div className="n2-paint-head">
        <h2>Рисунок</h2>
        <span className="n2-paint-badge">Placeholder — холст в разработке</span>
      </div>
      <div className="n2-paint-modes" role="radiogroup" aria-label="Режим рисования">
        {paintModes.map((mode) => (
          <button
            key={mode.id}
            className={`n2-paint-mode${paintMode === mode.id ? ' active' : ''}`}
            type="button"
            role="radio"
            aria-checked={paintMode === mode.id}
            onClick={() => setPaintMode(mode.id)}
          >
            <span className="n2-paint-mode-icon" aria-hidden="true">{mode.icon}</span>
            <span className="n2-paint-mode-body">
              <strong>
                {mode.title}
                {mode.meta && <em className="n2-paint-mode-meta">{mode.meta}</em>}
              </strong>
              <span>{mode.hint}</span>
            </span>
          </button>
        ))}
      </div>
      <div className="n2-paint-stage">
        <div className="n2-placeholder-card">
          <span className="icon">▧</span>
          <h2>
            {paintMode === 'sketch' ? 'Холст эскиза' : paintMode === 'mask' ? 'Холст маски' : 'Холст расширения'}
          </h2>
          <p>
            Этот режим — placeholder: холст и генерация появятся здесь следующим этапом.
            Сейчас функционал полностью работает в текущей версии.
          </p>
          <button className="n2-ghost" type="button" onClick={() => (window.location.href = '/')}>
            Открыть в текущей версии
          </button>
        </div>
      </div>
    </section>
  )

  // Единый каркас будущих вкладок (Редактор/Лицо): заголовок + honest badge +
  // placeholder-карточка. Тот же стандарт, что у «Рисунка».
  const futureView = (title: string, description: string, cardTitle: string, cardText: string) => (
    <section className="n2-panel n2-paint" aria-label={title}>
      <div className="n2-paint-head">
        <div className="n2-view-head bare">
          <h2>{title}</h2>
          <p>{description}</p>
        </div>
        <span className="n2-paint-badge">Placeholder — в разработке</span>
      </div>
      <div className="n2-paint-stage">
        <div className="n2-placeholder-card">
          <span className="icon">▧</span>
          <h2>{cardTitle}</h2>
          <p>{cardText}</p>
          <button className="n2-ghost" type="button" onClick={() => (window.location.href = '/')}>
            Открыть в текущей версии
          </button>
        </div>
      </div>
    </section>
  )

  const wideTab = tab === 'feed' || tab === 'edit' || tab === 'paint' || tab === 'face'

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
                ⬇ Скачать
              </a>
              <button
                className="n2-ghost"
                type="button"
                onClick={() => {
                  setSourceImage(apiUrl(galleryItem.url))
                  setGalleryItem(undefined)
                  setView('tabs')
                  setTab('i2i')
                }}
              >
                → В Изо → Изо
              </button>
              <button className="n2-ghost purple" type="button" onClick={() => openPublish(galleryItem)}>
                ✦ {ft.publish}
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

      <div className="n2-shell">
        <header className="n2-topbar">
          <button
            className="n2-brand"
            type="button"
            aria-label="ИЗО ACA"
            onClick={() => {
              setView('tabs')
              setTab('feed')
            }}
          >
            <span className="n2-brand-mark">▧</span>
            <span>
              ИЗО <span className="n2-brand-accent">ACA</span>
            </span>
          </button>
          <nav className="n2-tabs" aria-label="Режимы">
            {TABS.map((item) => (
              <button
                key={item.id}
                className={`n2-tab${item.feed ? ' feed-tab' : ''}${view === 'tabs' && tab === item.id ? ' active' : ''}`}
                type="button"
                onClick={() => {
                  setView('tabs')
                  setTab(item.id)
                }}
              >
                {item.label}
              </button>
            ))}
          </nav>
          <div className="n2-top-actions">
            <button
              className={`n2-ghost purple${view === 'gallery' ? ' active-view' : ''}`}
              type="button"
              onClick={() => setView('gallery')}
            >
              ▧ <span>Галерея</span>
            </button>
            <button className="n2-ghost" type="button" onClick={() => setHelpOpen(true)}>
              ? <span>Помощь</span>
            </button>
            <button
              className="n2-icon-button"
              type="button"
              aria-label="Настройки"
              title="Настройки (пока в текущей версии)"
              onClick={() => (window.location.href = '/')}
            >
              ⚙
            </button>
            <button
              className="n2-icon-button"
              type="button"
              aria-label={authStatus === 'authed' ? 'Профиль' : 'Войти'}
              title={authStatus === 'authed' ? 'Вы вошли' : 'Войти'}
              onClick={() => setAuthOpen(true)}
            >
              {authStatus === 'authed' ? '☺' : '⏻'}
            </button>
          </div>
        </header>

        <main className={`n2-main${wideTab || view === 'gallery' ? ' single' : ''}`}>
          {view === 'gallery' ? (
            galleryView
          ) : (
            <>
              {tab === 'feed' && feed}
              {tab === 'text' && (
                <>
                  {controls('text')}
                  {resultPanel}
                </>
              )}
              {tab === 'i2i' && (
                <>
                  {controls('i2i')}
                  {resultPanel}
                </>
              )}
              {tab === 'edit' &&
                futureView(
                  'Редактор',
                  'Основа + референсы с ролями: лицо, одежда, стиль, фон.',
                  'Рабочая область редактора',
                  'Редактор с основой и референсами переезжает в новый интерфейс следующим этапом. Функционал уже работает в текущей версии.',
                )}
              {tab === 'paint' && paintView}
              {tab === 'face' &&
                futureView(
                  'Лицо',
                  'Перенос лица с одного изображения на другое.',
                  'Рабочая область замены лица',
                  'Замена лица (FaceSwap) появится здесь в новом дизайне. Пока функционал доступен в текущей версии.',
                )}
            </>
          )}
        </main>
      </div>
    </div>
  )
}
