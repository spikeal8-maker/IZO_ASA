import { Fragment, lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ChangeEvent, Dispatch, MutableRefObject, ReactNode, PointerEvent as ReactPointerEvent, SetStateAction, WheelEvent as ReactWheelEvent } from 'react'
import {
  AuthV2Modal,
  ensureSessionRefreshedV2,
  initAuthV2,
  updateProfileV2,
  updateProfileV2Detailed,
  logoutV2,
  getAuthCapabilitiesV2,
  pollBotLoginStatusV2,
  refreshAuthStateV2,
  requestEmailLinkCodeV2,
  startBotLinkV2,
  useAuthV2,
  verifyEmailLinkCodeV2,
  type MeV2,
} from './authV2'
import { DiagPanel } from './diag'
import { isDiagMode } from './diagMeta'
import {
  EDIT_SLOT_COUNT, DEFAULT_EDIT_STRENGTH, EDIT_DISABLED_REFERENCE_ROLES, EDIT_SELECTABLE_REFERENCE_ROLES, EDIT_REFERENCE_ROLE_LABELS,
  EDIT_TEMPLATES, editComposerStatus,
  type EditReferenceRole, type EditSlot, type EditTemplate,
} from './editPrompt'
import TopBarV3 from './TopBarV3'
import { accountInfo } from './topbarUtils'
import './newStudioV3.css'
import { Stage, Layer, Line, Rect, Text, Circle } from 'react-konva'
import type { Stage as KonvaStage } from 'konva/lib/Stage'
import {
  Brush,
  Download,
  Eraser,
  GalleryHorizontalEnd,
  Heart,
  Image as ImageIcon,
  Languages,
  Lock,
  Play,
  Plus,
  RotateCcw,
  Settings,
  Shield,
  SlidersHorizontal,
  Sparkles,
  Trash2,
  Upload,
  WandSparkles,
  X,
  Zap,
} from 'lucide-react'
import './index.css'

const NewStudio = lazy(() => import('./newUi'))
const AdminAnalyticsV2 = lazy(() => import('./adminAnalytics').then((module) => ({ default: module.AdminAnalyticsV2 })))
const AdminModelsV2 = lazy(() => import('./adminModels'))

type Mode = 'text_to_image' | 'image_to_image' | 'edit' | 'paint' | 'inpaint' | 'outpaint' | 'faceswap' | 'remove_background' | 'try_on' | 'texture_transfer'
type Tab = 'studio' | 'gallery' | 'presets' | 'settings'
type PaintTool = 'sketch' | 'inpaint' | 'outpaint'
type PaintEditor = null | 'sketch' | 'mask'
type Lang = 'ru' | 'en'

type Job = {
  id: string
  mode: Mode
  provider: string
  status: string
  progress: number
  message: string
  resultImageId?: string
  resultUrl?: string
  error?: string
  gallerySaveStatus?: 'saved' | 'quota_full'
  galleryQuota?: GalleryQuota
}

type TariffKey = 'free' | 'mini' | 'plus' | 'pro' | 'business'
type TariffRule = { daily_tokens: number; gallery_slots: number }
type TariffConfig = Record<TariffKey, TariffRule>
type GalleryQuota = {
  plan: TariffKey
  daily_tokens: number
  gallery_slots: number
  gallery_used: number
  gallery_free: number
  gallery_full: boolean
}

const tariffKeys: TariffKey[] = ['free', 'mini', 'plus', 'pro', 'business']
const DEFAULT_TARIFFS: TariffConfig = {
  free: { daily_tokens: 10, gallery_slots: 1 },
  mini: { daily_tokens: 50, gallery_slots: 10 },
  plus: { daily_tokens: 100, gallery_slots: 50 },
  pro: { daily_tokens: 200, gallery_slots: 100 },
  business: { daily_tokens: 500, gallery_slots: 500 },
}

function normalizeTariffs(raw?: Partial<Record<string, Partial<TariffRule>>> | null): TariffConfig {
  return tariffKeys.reduce((acc, key) => {
    const source = raw?.[key] || {}
    acc[key] = {
      daily_tokens: Number.isFinite(Number(source.daily_tokens)) ? Math.max(0, Number(source.daily_tokens)) : DEFAULT_TARIFFS[key].daily_tokens,
      gallery_slots: Number.isFinite(Number(source.gallery_slots)) ? Math.max(0, Number(source.gallery_slots)) : DEFAULT_TARIFFS[key].gallery_slots,
    }
    return acc
  }, {} as TariffConfig)
}

type GalleryImage = {
  id: string
  userId?: string
  url: string
  thumbnailUrl: string
  mode: Mode
  provider: string
  promptOriginal: string
  promptTranslated?: string
  seed: number
  width: number
  height: number
  modelProfile: string
  loras: string[]
  preset?: string
  generationTimeMs: number
  isFavorite: boolean
  createdAt: string
  comfyuiPromptId?: string
}

type PromoCode = {
  code: string
  tokens: number
  activation_limit: number
  activation_count: number
  enabled: number
  created_at?: string
  updated_at?: string
}

type TimelinePoint = { date: string; value: number }
type AdminTimeline = Record<string, TimelinePoint[]>
type DashboardRange = 1 | 6 | 12 | 24 | 7 | 30 | 90
const HOURLY_DASHBOARD_RANGES = new Set<DashboardRange>([1, 6, 12, 24])

type PaintLine = {
  tool: 'brush' | 'eraser'
  points: number[]
  kind?: 'line' | 'rect' | 'circle'
  fill?: boolean
  color?: string
  strokeWidth?: number
}

type Copy = typeof t.ru
type Preset = {
  id: string
  ru: string
  en: string
  mode: Mode
  prompt: string
  category?: string
  dual?: boolean
  preview?: {
    female: string
    male: string
    alt: string
  }
}
type FluxConfig = {
  autofill_prompts?: Record<string, string>
  t2i_templates?: Array<{ name: string; prompt: string }>
  discover_prompts?: Record<string, { categories?: Array<{ cat: string; items: Array<{ label: string; prompt: string; dual?: boolean }> }> }>
}
type ModelsPayload = {
  diffusion_models?: string[]
  text_encoders?: string[]
  vaes?: string[]
  loras?: string[]
  selected?: { model?: string; textEncoder?: string; vae?: string }
}
type LoraOption = { id: string; label: string; triggerWord: string; strength: number }

const API = import.meta.env.VITE_API_BASE_URL || '/api'
const DEFAULT_NEG_PROMPT = 'low quality, deformed, blurry, watermark, ugly, bad anatomy, disfigured, mutated, extra limbs, poorly drawn face, bad proportions, gross proportions, jpeg artifacts, overexposed, underexposed'

// Edit-режим: до 4 изображений (1 основа + 3 референса с ролью). Prompt Composer и
// семантика ролей вынесены в чистый модуль editPrompt.ts (с unit-тестами).
const EMPTY_EDIT_SLOTS: EditSlot[] = Array.from({ length: EDIT_SLOT_COUNT }, () => ({ image: undefined, role: '', takeNote: '' }))

const resolutionPresets = [
  { label: '1024 × 1024', width: 1024, height: 1024 },
  { label: '1536 × 1024', width: 1536, height: 1024 },
  { label: '1024 × 1536', width: 1024, height: 1536 },
  { label: '1920 × 1088', width: 1920, height: 1088 },
  { label: '1088 × 1920', width: 1088, height: 1920 },
  { label: '1280 × 720', width: 1280, height: 720 },
  { label: '720 × 1280', width: 720, height: 1280 },
]
const AVATAR_PRESET_COUNT = 71
const avatarPresets = Array.from({ length: AVATAR_PRESET_COUNT }, (_, index) => {
  const number = String(index + 1).padStart(3, '0')
  const id = `avatar-${number}`
  return { id, url: `/avatars/${id}.webp`, label: `Аватар ${index + 1}` }
})
// Старые статичные каталоги (openRouterImageModels / localFluxProfiles) удалены:
// их заменил provider-aware экран «Админ → Модели v2» (adminModels.tsx + /api/admin/models-page).
async function apiFetch(path: string, init: RequestInit = {}) {
  const headers = new Headers(init.headers)
  const request = () => fetch(`${API}${path}`, { ...init, headers, credentials: 'include' })
  let response = await request()
  if (response.status === 401 && !path.includes('/auth/session/refresh-v2') && !path.includes('/auth/session/logout-v2')) {
    const refreshed = await ensureSessionRefreshedV2()
    if (refreshed) {
      await refreshAuthStateV2().catch(() => null)
      response = await request()
    }
  }
  return response
}

// Лента-эндпоинты — только trusted cookie session, без legacy-заголовка
// (feed backend не доверяет X-OneNode-User). Используется публикацией из галереи.
function feedFetch(path: string, init: RequestInit = {}) {
  return fetch(`${API}${path}`, { ...init, credentials: 'include' })
}

const modes: Array<{ id: Mode; ru: string; en: string; shortRu: string; shortEn: string }> = [
  { id: 'text_to_image', ru: 'Изображение по тексту', en: 'Image by text', shortRu: 'По тексту', shortEn: 'By text' },
  { id: 'image_to_image', ru: 'Изменить изображение по фото', en: 'Edit image by photo', shortRu: 'По фото', shortEn: 'By photo' },
  { id: 'edit', ru: 'Собрать изображение из нескольких фото', en: 'Assemble image from several photos', shortRu: 'Сборка', shortEn: 'Assembly' },
  { id: 'paint', ru: 'Правки изображения', en: 'Image edits', shortRu: 'Редактор', shortEn: 'Editor' },
  { id: 'faceswap', ru: 'Замена лица', en: 'Face swap', shortRu: 'Лицо', shortEn: 'Face' },
]

const t = {
  ru: {
    title: 'ИЗО_АСА',
    hint: 'Выберите режим, загрузите изображение или напишите prompt, затем нажмите “Сгенерировать”.',
    generate: 'Сгенерировать',
    cancel: 'Остановить',
    prompt: 'Запрос',
    negative: 'Негативный запрос',
    translate: 'Перевести запрос',
    upload: 'Загрузить изображение',
    clear: 'Очистить',
    backToStudio: 'К генерации',
    advanced: 'Расширенные настройки',
    gallery: 'Галерея',
    feed: 'Лента',
    publishToFeed: 'Опубликовать в ленту',
    publishTitleLabel: 'Название',
    promptVisibilityLabel: 'Видимость промпта',
    visOpen: 'Открытый',
    visPartial: 'Частично',
    visHidden: 'Скрыт',
    allowRecreate: 'Разрешить «Повторить»',
    publishAction: 'Опубликовать',
    published: 'Опубликовано в ленту',
    goToFeed: 'Перейти в ленту',
    presets: 'Пресеты',
    settings: 'Настройки',
    admin: 'Админ',
    studio: 'Генерация',
    provider: 'Провайдер',
    model: 'Профиль модели',
    size: 'Размер',
    image1Size: 'Как у основы',
    image2Size: 'Размер Изо 2',
    customSize: 'Свой размер',
    seed: 'Зерно',
    randomSeed: 'Случайный seed',
    steps: 'Шаги',
    cfg: 'CFG',
    guidance: 'Направление',
    strength: 'Сила изменения',
    faceStrength: 'Сила замены лица',
    faceLora: 'FaceSwap LoRA',
    lora: 'LoRA',
    useAs: 'Использовать как...',
    useAsImageToImage: 'По фото',
    useAsEditOne: 'Сборка: основа',
    useAsEditTwo: 'Сборка: референс',
    useAsPaint: 'Редактор',
    useAsInpaint: 'Маска',
    useAsOutpaint: 'Расширение',
    useAsFaceTarget: 'Цель лица',
    useAsFaceSource: 'Источник лица',
    useAsRemoveBackground: 'Удалить фон',
    useAsTryOn: 'Примерка',
    useAsTextureTransfer: 'Текстура',
    download: 'Скачать',
    favorite: 'Избранное',
    delete: 'Удалить',
    sendTg: 'Поделиться',
    sendMax: 'Отправить в MAX',
    sent: 'Отправлено',
    grid: 'Сетка',
    list: 'Список',
    original: 'Оригинальный prompt',
    translated: 'Переведённый prompt',
    generationTime: 'Время генерации',
    providerSettings: 'Настройки провайдеров',
    limits: 'Лимиты',
    save: 'Сохранить',
    loginCode: 'Код входа',
    login: 'Войти',
    fileTooLarge: 'Изображение слишком большое. Максимум: 25 MB.',
    resolutionTooLarge: 'Изображение слишком большое. Максимум: 4096×4096.',
    triggerWord: 'Триггер-слово',
    preview: 'Предпросмотр',
    useLast: 'Использовать последнее изображение',
    brushSize: 'Толщина кисти',
    undo: 'Отмена',
    redo: 'Повтор',
    blankLayer: 'Пустой слой',
    imageLayer: 'Слой с изображением',
    duplicateLayer: 'Дублировать',
    moveUp: 'Выше',
    moveDown: 'Ниже',
    opacity: 'Прозрачность',
    removeBg: 'Удалить фон',
    showMask: 'Показать / скрыть маску',
    invertMask: 'Инвертировать маску',
    maskBlur: 'Размытие маски',
    confirmExpansion: 'Подтвердить расширение',
    resetExpansion: 'Сбросить расширение',
    finalSize: 'Итоговый размер',
    sampler: 'Сэмплер',
    count: 'Количество изображений',
    before: 'Выберите режим и заполните поля.',
    ready: 'Готово',
    running: 'Генерация',
    errors: 'Ошибки',
    users: 'Пользователи',
    jobs: 'Задачи',
    models: 'Модели',
    statistics: 'Статистика',
    brush: 'Кисть',
    eraser: 'Ластик',
    mask: 'Маска',
    layers: 'Слои',
    expand: 'Расширение',
    sourceFace: 'Источник лица',
    targetImage: 'Целевое изображение',
    referenceImage: 'Референс',
  openRouterNotice: 'Часть функций скрыта: OpenRouter не поддерживает LoRA, inpaint, outpaint и face swap в этом прототипе.',
    platformReady: 'Платформы',
    databaseReady: 'База данных',
    help: 'Помощь',
    addLora: '+ Добавить LoRA',
    expandPrompt: 'Расширить запрос',
    generatedPlaceholder: 'Сгенерированное изображение появится здесь',
    language: 'Язык',
    comfyUrl: 'Адрес ComfyUI',
    rateLimit: 'Лимит запросов',
    readyValue: 'готово',
    pendingValue: 'ожидает',
    sqliteReady: 'SQLite готова',
  },
  en: {
    title: 'ИЗО_АСА',
    hint: 'Choose a mode, upload an image or write a prompt, then press Generate.',
    generate: 'Generate',
    cancel: 'Cancel',
    prompt: 'Prompt',
    negative: 'Negative prompt',
    translate: 'Translate prompt',
    upload: 'Upload image',
    clear: 'Clear',
    backToStudio: 'Back to Studio',
    advanced: 'Advanced controls',
    gallery: 'Gallery',
    feed: 'Feed',
    publishToFeed: 'Publish to feed',
    publishTitleLabel: 'Title',
    promptVisibilityLabel: 'Prompt visibility',
    visOpen: 'Open',
    visPartial: 'Partial',
    visHidden: 'Hidden',
    allowRecreate: 'Allow "Recreate"',
    publishAction: 'Publish',
    published: 'Published to feed',
    goToFeed: 'Open feed',
    presets: 'Presets',
    settings: 'Settings',
    admin: 'Admin',
    studio: 'Studio',
    provider: 'Provider',
    model: 'Model profile',
    size: 'Size',
    image1Size: 'As base',
    image2Size: 'Image 2 size',
    customSize: 'Custom size',
    seed: 'Seed',
    randomSeed: 'Random seed',
    steps: 'Steps',
    cfg: 'CFG',
    guidance: 'Guidance',
    strength: 'Strength',
    faceStrength: 'Face swap strength',
    faceLora: 'FaceSwap LoRA',
    lora: 'LoRA',
    useAs: 'Use as...',
    useAsImageToImage: 'By photo',
    useAsEditOne: 'Assembly: base',
    useAsEditTwo: 'Assembly: reference',
    useAsPaint: 'Editor',
    useAsInpaint: 'Inpaint',
    useAsOutpaint: 'Outpaint',
    useAsFaceTarget: 'Face target',
    useAsFaceSource: 'Face source',
    useAsRemoveBackground: 'Remove background',
    useAsTryOn: 'Try On',
    useAsTextureTransfer: 'Texture transfer',
    download: 'Download',
    favorite: 'Favorite',
    delete: 'Delete',
    sendTg: 'Share',
    sendMax: 'Send to MAX',
    sent: 'Sent',
    grid: 'Grid',
    list: 'List',
    original: 'Original prompt',
    translated: 'Translated prompt',
    generationTime: 'Generation time',
    providerSettings: 'Provider settings',
    limits: 'Limits',
    save: 'Save',
    loginCode: 'Login code',
    login: 'Login',
    fileTooLarge: 'Image is too large. Maximum: 25 MB.',
    resolutionTooLarge: 'Image is too large. Maximum: 4096×4096.',
    triggerWord: 'Trigger word',
    preview: 'Preview',
    useLast: 'Use last image',
    brushSize: 'Brush size',
    undo: 'Undo',
    redo: 'Redo',
    blankLayer: 'Blank Layer',
    imageLayer: 'Image Layer',
    duplicateLayer: 'Duplicate Layer',
    moveUp: 'Move Up',
    moveDown: 'Move Down',
    opacity: 'Opacity',
    removeBg: 'Remove Background',
    showMask: 'Show / hide mask',
    invertMask: 'Invert mask',
    maskBlur: 'Mask blur',
    confirmExpansion: 'Confirm expansion',
    resetExpansion: 'Reset expansion',
    finalSize: 'Final size',
    sampler: 'Sampler',
    count: 'Image count',
    before: 'Choose a mode and fill in the fields.',
    ready: 'Ready',
    running: 'Generating',
    errors: 'Errors',
    users: 'Users',
    jobs: 'Jobs',
    models: 'Models',
    statistics: 'Statistics',
    brush: 'Brush',
    eraser: 'Eraser',
    mask: 'Mask',
    layers: 'Layers',
    expand: 'Expansion',
    sourceFace: 'Source face',
    targetImage: 'Target image',
    referenceImage: 'Reference image',
    openRouterNotice: 'Some controls are hidden: OpenRouter does not support LoRA, inpaint, outpaint, or face swap in this prototype.',
    platformReady: 'Platforms',
    databaseReady: 'Database',
    help: 'Help',
    addLora: '+ Add LoRA',
    expandPrompt: 'Expand prompt',
    generatedPlaceholder: 'Generated image will appear here',
    language: 'Language',
    comfyUrl: 'ComfyUI URL',
    rateLimit: 'Rate limit',
    readyValue: 'ready',
    pendingValue: 'pending',
    sqliteReady: 'SQLite ready',
  },
}

const workflowPresets: Preset[] = [
  ...presetsFromRows(textToImageTemplateRows(), 'text_to_image', 'По тексту · идеи', 't2i-template'),
  ...presetsFromRows(imageToImageTransformRows(), 'image_to_image', 'По фото · преобразование', 'i2i-transform', true),
  { id: 't2i-01', ru: 'Кот на крыше под огромной луной', en: 'Cat under giant moon', mode: 'text_to_image', category: 'По тексту', prompt: 'Пушистый кот сидит на краю старой крыши ночью и смотрит на огромную светящуюся луну над тихим городом. Мягкий сине-серебристый лунный свет, лёгкий ветер двигает шерсть, внизу тёплые огни окон, спокойная мечтательная атмосфера, реалистичные детали, малая глубина резкости, эмоциональный кинематографичный кадр. Все видимые поверхности содержат только абстрактные узоры и световые формы.' },
  { id: 't2i-02', ru: 'Биолюминесцентное море', en: 'Bioluminescent ocean', mode: 'text_to_image', category: 'По тексту', prompt: 'Ночной берег океана с биолюминесцентными волнами, которые светятся голубым светом на тёмном песке. Одинокий человек стоит у воды и смотрит на горизонт. В небе яркие звёзды, вдалеке скалы и мягкий туман. Широкий кинематографичный кадр, реалистичная вода, красивые отражения, магическая спокойная атмосфера. Все видимые детали полностью визуальные, только абстрактные формы и узоры.' },
  { id: 't2i-03', ru: 'Космический корабль над древним городом', en: 'Spaceship over ancient city', mode: 'text_to_image', category: 'По тексту', prompt: 'Гигантский футуристический космический корабль медленно зависает над древним пустынным городом с каменными храмами, факелами и золотой пылью в воздухе. Сцена соединяет древнюю цивилизацию и технологии будущего: светящиеся двигатели, резные башни, парящие дроны, драматичный закат. Эпичная кинематографичная композиция, реалистичный масштаб, дорогой sci-fi fantasy стиль. Все символы и панели выглядят как абстрактные декоративные узоры.' },
  { id: 't2i-04', ru: 'Фараон будущего', en: 'Future pharaoh', mode: 'text_to_image', category: 'По тексту', prompt: 'Футуристический фараон стоит внутри монументального золотого храма с чёрным камнем, парящими голографическими кольцами, голубой энергией и древними геометрическими орнаментами. На персонаже элегантная техно-королевская броня из золота и обсидиана. Симметричная композиция, драматичный свет, роскошная атмосфера древнего будущего. Все орнаменты декоративные и нечитаемые.' },
  { id: 't2i-05', ru: 'Инопланетный рынок', en: 'Alien marketplace', mode: 'text_to_image', category: 'По тексту', prompt: 'Яркий инопланетный рынок на далёкой планете: дружелюбные странные существа, парящие фонари, экзотические растения, светящиеся кристаллы, летающие торговые платформы и мягкий пыльный солнечный свет. Богатое кинематографичное окружение, живые цвета, фантастическая атмосфера, много деталей, широкий ракурс. Все панели и вывески заменены абстрактными световыми формами и декоративными символами.' },
  { id: 't2i-06', ru: 'Дракон над замком', en: 'Dragon over castle', mode: 'text_to_image', category: 'По тексту', prompt: 'Величественный дракон летит над тёмным фэнтези-замком на горной скале во время золотого заката. Внизу водопады, в окнах замка тёплый свет, вокруг облака и птицы. Реалистичные крылья дракона, огромный масштаб, эпичная сказочная атмосфера, кинематографичный широкий кадр. Все архитектурные детали содержат только декоративные нечитаемые узоры.' },
  { id: 't2i-07', ru: 'Киберпанк-персонаж у мотоцикла', en: 'Cyberpunk character with bike', mode: 'text_to_image', category: 'По тексту', prompt: 'Стильный оригинальный киберпанк-персонаж стоит рядом с футуристическим мотоциклом на мокрой неоновой улице ночью. На асфальте отражаются огни, в воздухе дождь, вокруг мягкое свечение мегаполиса. Выразительная поза, модная куртка, реалистичные материалы, дорогой fashion-sci-fi стиль. Все городские панели и световые поверхности содержат только абстрактные формы.' },
  { id: 't2i-08', ru: 'Вилла над океаном', en: 'Villa over ocean', mode: 'text_to_image', category: 'По тексту', prompt: 'Роскошная современная вилла встроена в скалу над спокойным океаном на закате. Огромные стеклянные окна, бесконечный бассейн, тёплый свет внутри, пальмовые тени, мягкое золотое небо. Архитектурная фотография премиального уровня, реалистичные отражения, атмосфера дорогой жизни и мечты. Никаких читаемых элементов, только чистая архитектура и природные формы.' },
  { id: 't2i-09', ru: 'Космический кот-астронавт', en: 'Space cat astronaut', mode: 'text_to_image', category: 'По тексту', prompt: 'Милый пушистый кот в маленьком элегантном космическом шлеме парит внутри уютной кабины космического корабля и смотрит на Землю через круглое окно. Мягкий свет, звёзды за окном, маленькие предметы в невесомости, реалистичная шерсть, очаровательное выражение. Все экраны показывают абстрактные световые формы и декоративные линии.' },
  { id: 't2i-10', ru: 'Город внутри стеклянной сферы', en: 'City in glass sphere', mode: 'text_to_image', category: 'По тексту', prompt: 'Сюрреалистический город находится внутри огромной прозрачной стеклянной сферы, парящей над спокойным океаном. Внутри видны маленькие башни, мосты, сады, светящиеся улицы и облака. На воде мягкие отражения, вокруг драматичное небо. Кинематографичный магический реализм, невозможная архитектура, чистая композиция. Все детали полностью визуальные.' },
  { id: 't2i-11', ru: 'Самурай будущего', en: 'Future samurai', mode: 'text_to_image', category: 'По тексту', prompt: 'Футуристический самурай стоит в туманном бамбуковом лесу. На его броне мягко светятся голубые линии, силуэт меча виден в руке, вокруг падает дождь и стелется туман. Спокойная мощная поза, реалистичные материалы, кинематографичный портрет, древность соединена с технологиями будущего. Все узоры на броне абстрактные и нечитаемые.' },
  { id: 't2i-12', ru: 'Летающий остров', en: 'Flying island', mode: 'text_to_image', category: 'По тексту', prompt: 'Летающий остров высоко в небе: маленький замок, светящиеся деревья, водопады, падающие в облака, птицы и тёплый закат. Эпический фэнтези-пейзаж, широкий кинематографичный кадр, детальные скалы и растения, мягкие облака, атмосфера сказочного путешествия. Все элементы декоративные, без читаемых символов.' },
  { id: 't2i-13', ru: 'Футуристический гиперкар', en: 'Futuristic hypercar', mode: 'text_to_image', category: 'По тексту', prompt: 'Роскошный футуристический гиперкар стоит на мокрой ночной улице мегаполиса. Низкий ракурс камеры, аэродинамический корпус, отражения на дороге, мягкие неоновые огни, кинематографичная автомобильная реклама. Все городские панели и световые поверхности содержат только абстрактные световые блоки и узоры.' },
  { id: 't2i-14', ru: 'Магическая библиотека', en: 'Magic library', mode: 'text_to_image', category: 'По тексту', prompt: 'Огромная магическая библиотека с парящими книгами, светящимися лестницами, тёплым свечным светом, древними деревянными полками и чёрным котом на столе. Уютная фэнтези-атмосфера, золотые лучи, пыль в воздухе, высокая детализация, кинематографичный интерьер. Все книги и страницы содержат только декоративные нечитаемые узоры.' },
  { id: 't2i-15', ru: 'Две луны над океаном', en: 'Two moons over ocean', mode: 'text_to_image', category: 'По тексту', prompt: 'Оригинальный персонаж в длинном плаще стоит на высокой скале над океаном под небом с двумя огромными лунами. Ветер двигает ткань, волны разбиваются о скалы внизу, серебристо-синий свет, эмоциональная фантастическая атмосфера. Реалистичный масштаб, кинематографичный пейзаж. Все детали полностью визуальные.' },
  { id: 't2i-16', ru: 'Маленький робот-питомец', en: 'Tiny robot pet', mode: 'text_to_image', category: 'По тексту', prompt: 'Крошечный милый робот-питомец сидит на мягком пледе возле большого окна с дождём. В комнате тёплый свет лампы, на стекле капли, в глазах робота мягкое свечение. Уютная домашняя sci-fi атмосфера, реалистичные материалы, эмоциональная композиция. Все панели и индикаторы выглядят как абстрактные световые точки.' },
  { id: 't2i-17', ru: 'Портал в древнем лесу', en: 'Portal in ancient forest', mode: 'text_to_image', category: 'По тексту', prompt: 'Светящийся магический портал открывается между древними деревьями в туманном лесу на закате. Голубая и золотая энергия, мох, камни, корни, светлячки, мягкий туман, таинственная атмосфера. Кинематографичная фэнтези-композиция, реалистичная природа. Все символы вокруг портала декоративные и нечитаемые.' },
  { id: 't2i-18', ru: 'Дом у биолюминесцентного леса', en: 'House by glowing forest', mode: 'text_to_image', category: 'По тексту', prompt: 'Современный стеклянный дом стоит на краю светящегося биолюминесцентного леса ночью. Голубые растения, тёплый свет внутри, отражающая вода, лёгкий туман, чистая архитектура, атмосфера уюта и роскоши. Широкоугольная кинематографичная фотография. Все декоративные элементы полностью визуальные.' },
  { id: 't2i-19', ru: 'Дружелюбный инопланетянин', en: 'Friendly alien', mode: 'text_to_image', category: 'По тексту', prompt: 'Дружелюбное элегантное инопланетное существо стоит в спокойной светящейся пустыне под огромной планетой в небе. Плавный органический дизайн, выразительные глаза, мягкий тёплый свет, доброжелательная поза, реалистичная sci-fi атмосфера первого контакта. Все детали декоративные и нечитаемые.' },
  { id: 't2i-20', ru: 'Кафе в облаках', en: 'Cloud cafe', mode: 'text_to_image', category: 'По тексту', prompt: 'Уютное фэнтези-кафе парит среди облаков. Внутри тёплый свет, круглые окна, растения, маленькие дракончики спят рядом с чашками, снаружи золотой рассвет. Магический реализм, мягкая атмосфера, дерево, латунь, уют и сказочность. Все меню, таблички и декоративные поверхности содержат только абстрактные узоры.' },
  { id: 'i2i-01', ru: 'Сделать кинематографично', en: 'Make cinematic', mode: 'image_to_image', category: 'По фото', prompt: 'Преобразуй исходное изображение в дорогой кинематографичный кадр. Сохрани главный объект, позу, композицию, масштаб и основную идею. Улучши свет: добавь мягкие тени, глубину, объём, атмосферу, красивую цветокоррекцию и реалистичные материалы. Все экраны, вывески, панели и поверхности должны содержать только абстрактные формы, световые линии и декоративные нечитаемые узоры.' },
  { id: 'i2i-02', ru: 'Сделать киберпанк', en: 'Make cyberpunk', mode: 'image_to_image', category: 'По фото', prompt: 'Преобразуй исходное изображение в ночную киберпанк-сцену. Сохрани главный объект и композицию. Добавь мокрые отражающие поверхности, неоновое свечение, дождь, городские огни, футуристические панели и драматичную атмосферу ночного мегаполиса. Все световые панели и вывески должны быть абстрактными, без читаемых символов.' },
  { id: 'i2i-03', ru: 'Сделать фэнтези', en: 'Make fantasy', mode: 'image_to_image', category: 'По фото', prompt: 'Преобразуй исходное изображение в магическую фэнтези-сцену. Сохрани главный объект, силуэт и композицию. Добавь мягкое свечение, туман, древние камни, волшебные растения, светящиеся частицы и сказочную глубину. Все символы и декоративные элементы должны быть абстрактными и нечитаемыми.' },
  { id: 'i2i-04', ru: 'Сделать древность + будущее', en: 'Ancient + future', mode: 'image_to_image', category: 'По фото', prompt: 'Преобразуй исходное изображение в мир, где древняя цивилизация соединена с технологиями будущего. Сохрани главный объект, силуэт и композицию. Добавь каменную архитектуру, золото, обсидиан, парящие энергетические кольца, мягкое голубое свечение и кинематографичную атмосферу древних технологий. Все орнаменты и панели должны быть декоративными, без читаемых символов.' },
  { id: 'i2i-05', ru: 'Сделать luxury-рекламу', en: 'Make luxury ad', mode: 'image_to_image', category: 'По фото', prompt: 'Преобразуй исходное изображение в премиальный рекламный кадр. Сохрани главный объект и важные детали. Добавь элегантное студийное освещение, чистый фон, полированные отражения, мягкие тени, дорогие материалы и коммерческую композицию. Все этикетки, упаковки и поверхности должны быть заполнены только абстрактными декоративными узорами.' },
  { id: 'i2i-06', ru: 'Сделать космическую версию', en: 'Make space version', mode: 'image_to_image', category: 'По фото', prompt: 'Преобразуй исходное изображение в sci-fi космическую сцену. Сохрани главный объект, позу и композицию. Добавь далёкие планеты, звёзды, мягкое космическое свечение, футуристические материалы, парящие частицы и кинематографичную атмосферу космоса. Все экраны и панели должны показывать только абстрактные световые формы.' },
  { id: 'i2i-07', ru: 'Сделать лунный свет', en: 'Make moonlight', mode: 'image_to_image', category: 'По фото', prompt: 'Преобразуй исходное изображение в спокойную сцену под лунным светом. Сохрани главный объект и композицию. Добавь холодный серебристо-синий свет, мягкие тени, лёгкий туман, спокойные отражения и эмоциональную кинематографичную атмосферу. Все видимые поверхности должны быть полностью визуальными, без читаемых символов.' },
  { id: 'i2i-08', ru: 'Сделать сюрреалистический сон', en: 'Make surreal dream', mode: 'image_to_image', category: 'По фото', prompt: 'Преобразуй исходное изображение в красивую сюрреалистическую сцену сна. Сохрани главный объект, но помести его в невозможное окружение: парящие острова, мягкие облака, светящаяся вода, необычный масштаб, магический реализм и кинематографичная глубина. Все детали должны быть визуальными и декоративными.' },
  { id: 'edit-01', ru: 'Универсальное изменение', en: 'Universal edit', mode: 'edit', category: 'Edit', prompt: 'Сделай нужное изменение в изображении, сохранив главный объект, свет, перспективу и общий стиль.' },
  { id: 'edit-02', ru: 'Заменить фон', en: 'Replace background', mode: 'edit', category: 'Edit', prompt: 'Замени фон на красивый лунный пейзаж у моря.' },
  { id: 'edit-03', ru: 'Добавить объект', en: 'Add object', mode: 'edit', category: 'Edit', prompt: 'Добавь в сцену светящийся магический портал.' },
  { id: 'edit-04', ru: 'Сделать дороже', en: 'Make premium', mode: 'edit', category: 'Edit', prompt: 'Сделай изображение более дорогим и премиальным.' },
  { id: 'edit-05', ru: 'Добавить магический эффект', en: 'Add magic effect', mode: 'edit', category: 'Edit', prompt: 'Преобразуй сцену в фэнтези-мир с мягким магическим светом.' },
  { id: 'edit-06', ru: 'Добавить футуристический эффект', en: 'Add sci-fi effect', mode: 'edit', category: 'Edit', prompt: 'Сделай сцену футуристичной, с мягким неоновым светом.' },
  { id: 'edit-07', ru: 'Кинематографичный вид', en: 'Cinematic look', mode: 'edit', category: 'Edit', prompt: 'Сделай изображение более кинематографичным и выразительным.' },
  { id: 'edit-08', ru: 'Сделать интерьер мечты', en: 'Make dream interior', mode: 'edit', category: 'Edit', prompt: 'Сделай интерьер уютным и роскошным.' },
  { id: 'sketch-01', ru: 'Эскиз в сцену', en: 'Sketch to scene', mode: 'paint', category: 'Эскиз', prompt: 'Преобразуй исходный эскиз в реалистичную кинематографичную сцену. Сохрани расположение объектов из эскиза. Добавь красивый свет, атмосферу, тени, глубину, реалистичные материалы и чистую композицию.' },
  { id: 'mask-01', ru: 'Заменить выделенную область', en: 'Replace masked area', mode: 'inpaint', category: 'Маска', prompt: 'Измени только область, отмеченную маской: «напишите, что должно появиться внутри маски». Всё вне маски сохрани без изменений: главный объект, фон, освещение, перспектива, цветовая атмосфера, тени, резкость и стиль. Новая область должна естественно соединяться с исходным изображением. Все поверхности должны содержать только абстрактные формы, световые линии и декоративные узоры.' },
  { id: 'mask-02', ru: 'Добавить объект в маску', en: 'Add object in mask', mode: 'inpaint', category: 'Маска', prompt: 'Внутри области маски добавь: «напишите объект». Объект должен иметь правильный масштаб, контактную тень, реалистичную перспективу, совпадающее освещение и подходящую резкость. Всё вне маски сохрани без изменений. Все этикетки, панели и декоративные поверхности должны быть абстрактными и нечитаемыми.' },
  { id: 'mask-03', ru: 'Исправить область', en: 'Fix area', mode: 'inpaint', category: 'Маска', prompt: 'Восстанови и улучши только область, отмеченную маской. Сделай форму, текстуру, свет, цвет и резкость естественными. Всё вне маски сохрани без изменений. Исправленная область должна выглядеть как нормальная часть исходного изображения, без заметного перехода.' },
  { id: 'outpaint-01', ru: 'Расширить до широкого кадра', en: 'Expand to widescreen', mode: 'outpaint', category: 'Расширение', prompt: 'Расширь исходное изображение до широкого кинематографичного формата 16:9. Сохрани главный объект, стиль, освещение, перспективу и цветовую атмосферу. В новых областях естественно продолжи окружение: «напишите, что должно появиться по краям». Итог должен выглядеть как единая цельная сцена без заметного шва. Все детали должны быть визуальными, без читаемых символов.' },
  { id: 'outpaint-02', ru: 'Сделать вертикальный кадр', en: 'Make vertical frame', mode: 'outpaint', category: 'Расширение', prompt: 'Расширь исходное изображение до вертикального формата 9:16. Сохрани главный объект в центре, его масштаб, свет и стиль. В верхней и нижней части естественно продолжи фон: «напишите, что добавить сверху и снизу». Композиция должна подходить для красивой вертикальной картинки. Все панели, экраны и декоративные элементы должны быть абстрактными и нечитаемыми.' },
  { id: 'outpaint-03', ru: 'Добавить вокруг красивый мир', en: 'Add beautiful world around', mode: 'outpaint', category: 'Расширение', prompt: 'Расширь изображение и добавь вокруг главного объекта красивое окружение: «опишите мир: лунное море, киберпанк-город, фэнтези-лес, космос, древний храм, luxury-интерьер». Сохрани главный объект, перспективу, освещение и стиль. Новые области должны выглядеть как естественное продолжение исходной сцены.' },
  { id: 'face-01', ru: 'Естественная замена лица', en: 'Natural face swap', mode: 'faceswap', category: 'Лицо', prompt: 'Используй изображение 1 как целевую сцену: сохранить тело, позу, одежду, фон, стиль, ракурс и освещение. Используй изображение 2 только как референс лица: сохранить основные черты, возраст, форму лица, глаза, нос, губы и выражение. Замени лицо в исходной сцене на лицо из референса так, чтобы оно совпадало с поворотом головы, направлением взгляда, светом, цветом кожи, тенями и резкостью. Все элементы одежды, фона и декоративных поверхностей должны быть без читаемых символов.' },
  { id: 'face-02', ru: 'Лицо в новом образе', en: 'Face in new style', mode: 'faceswap', category: 'Лицо', prompt: 'Используй изображение 1 как лицо-референс. Используй изображение 2 как образ, стиль или сцену. Создай портрет: «опишите образ: фэнтези, киберпанк, luxury, космос, древний храм, кинематографичный персонаж». Сохрани узнаваемые черты лица, естественный возраст, выражение и пропорции. Все декоративные элементы должны быть абстрактными и нечитаемыми.' },
]

type PromptKey = Mode | `paint:${PaintTool}`

function promptKeyFor(mode: Mode, paintTool: PaintTool): PromptKey {
  return mode === 'paint' ? `paint:${paintTool}` : mode
}

function randomPromptFromPresets(presets: Preset[], fallback = '') {
  if (!presets.length) return fallback
  return presets[Math.floor(Math.random() * presets.length)]?.prompt || fallback
}

function presetPreviewPair(preset: Preset) {
  if (!preset.preview) return null
  return preset.preview
}

function presetsForPromptKey(presets: Preset[], key: PromptKey) {
  if (key === 'paint:sketch') return presets.filter((item) => item.mode === 'paint')
  if (key === 'paint:inpaint') return presets.filter((item) => item.mode === 'inpaint')
  if (key === 'paint:outpaint') return presets.filter((item) => item.mode === 'outpaint')
  return presets.filter((item) => item.mode === key)
}

function initialPromptByMode(presets: Preset[]): Record<string, string> {
  const keys: PromptKey[] = ['text_to_image', 'image_to_image', 'faceswap', 'paint:sketch', 'paint:inpaint', 'paint:outpaint', 'edit']
  return keys.reduce<Record<string, string>>((acc, key) => {
    acc[key] = key === 'edit' ? '' : randomPromptFromPresets(presetsForPromptKey(presets, key), '')
    return acc
  }, {})
}

const fallbackLoraOptions: LoraOption[] = [
  { id: 'none', label: 'None', triggerWord: '', strength: 0 },
  { id: 'lora_arcane', label: 'arcane style · 0.8', triggerWord: 'arcane style', strength: 0.8 },
  { id: 'product_photo', label: 'product photo · 0.6', triggerWord: 'product photo', strength: 0.6 },
]

function loadUserPresets(): Preset[] {
  try {
    const raw = window.localStorage.getItem('izo_asa_user_presets')
    return raw ? JSON.parse(raw) : []
  } catch {
    return []
  }
}

function categoryTitle(category: string, lang: Lang) {
  const titles: Record<string, { ru: string; en: string }> = {
    POPULAR: { ru: 'Популярное', en: 'Popular' },
    T2I: { ru: 'По тексту', en: 'By text' },
    USER: { ru: 'Мои пресеты', en: 'My presets' },
    ANGLES: { ru: 'Ракурсы', en: 'Angles' },
    RELIGHT: { ru: 'Свет', en: 'Relight' },
    STYLES: { ru: 'Стили', en: 'Styles' },
    OTHER: { ru: 'Другое', en: 'Other' },
    SKETCH: { ru: 'Эскиз', en: 'Sketch' },
    COLLAGE: { ru: 'Коллаж', en: 'Collage' },
    INPAINT: { ru: 'Маска', en: 'Inpaint' },
    OUTPAINT: { ru: 'Расширение', en: 'Outpaint' },
  }
  if (category.startsWith('FACE SWAP')) return lang === 'ru' ? 'Замена лица' : 'Face swap'
  return titles[category]?.[lang] || category
}

function presetsFromRows(rows: string, mode: Mode, category: string, idPrefix: string, transformSourceImage = false): Preset[] {
  return rows.trim().split(/\r?\n/).map((line) => {
    const parts = line.split('\t')
    const number = parts.shift() || '0'
    const name = parts.shift() || `Шаблон ${number}`
    const rawPrompt = parts.join('\t').trim()
    const prompt = transformSourceImage
      ? `Преобразуй исходное изображение в выбранное визуальное направление. Сохрани главный объект, силуэт, читаемую композицию и важные детали исходника. Не добавляй читаемый текст, логотипы и водяные знаки. ${rawPrompt}`
      : rawPrompt
    const id = `${idPrefix}-${number.padStart(2, '0')}`
    return {
      id,
      ru: name.trim(),
      en: name.trim(),
      mode,
      category,
      prompt,
      preview: transformSourceImage ? presetPreview(id, name.trim()) : undefined,
    }
  })
}

function presetPreview(id: string, name: string) {
  return {
    female: `/preset-previews/i2i/female/${id}.webp`,
    male: `/preset-previews/i2i/male/${id}.webp`,
    alt: `Превью стиля: ${name}`,
  }
}

function imageToImageTransformRows() {
  return `
1	Чистый коммерческий фотореализм	Реалистичная коммерческая фотография, естественные материалы, чистая композиция, мягкий дневной свет, реалистичная кожа и фактуры, камера на уровне глаз, объектив 50 мм, f/2.8, умеренная глубина резкости, аккуратный премиальный вид.
2	Лакшери премиум	Дорогая премиальная эстетика: мрамор, тёмное дерево, латунь, кожа, бархат, стекло, мягкие золотистые отражения, дорогой интерьер или окружение высокого класса, журнальная luxury-фотография, объектив 50 мм, f/2.2.
3	Fashion editorial	Глянцевая журнальная съёмка, выразительная поза, чистый фон, дорогой свет, стильная одежда и материалы, editorial composition, мягкие тени, камера 85 мм, f/2.0, ощущение обложки журнала.
4	Космическая станция	Реалистичная космическая среда: большой иллюминатор, вид на планету, звёзды, панели управления, герметичный модуль, холодный бело-синий свет, ощущение настоящей орбитальной станции, объектив 35 мм, f/4.
5	Невесомость	Сцена в состоянии невесомости: волосы, ткань и мелкие предметы мягко парят, жидкость собирается в округлые капли, тела удерживаются ремнями или поручнями, нет ощущения обычного веса, за окном космос или большая планета, объектив 35 мм, f/4.
6	Открытое будущее	Светлое будущее не в коробке: большие окна, вид на город будущего, воздух, панорама, гладкая архитектура, прозрачные интерфейсы, мягкие световые линии, чистые материалы, ощущение просторного технологичного мира, объектив 35 мм, f/3.5.
7	Белая high-tech лаборатория	Стерильная технологичная среда, белые панели, стекло, мягкая холодная подсветка, голографические экраны, аккуратная научная эстетика, чистый фотореализм, большие световые поверхности, объектив 50 мм, f/2.8.
8	Киберпанк неон	Тёмный футуристический мир, сине-розовый неон, дождь, мокрые отражения, городские огни, голограммы, высокая контрастность, технологичная ночная атмосфера, cinematic cyberpunk, объектив 35 мм, f/2.0.
9	Стимпанк	Викторианско-индустриальная эстетика: медь, латунь, шестерёнки, трубы, механические приборы, тёплый янтарный свет, дерево, металл, пар, детальная мастерская или механический мир, объектив 50 мм, f/2.8.
10	Дизельпанк	Грубая индустриальная эстетика первой половины XX века: сталь, заклёпки, тяжёлые механизмы, дым, военная техника, тёпло-серые цвета, суровый ретро-футуризм, драматичный свет, объектив 35 мм, f/4.
11	Ретрофутуризм 60-х	Будущее глазами 1960-х: округлые формы, пастельные панели, винтажные приборы, старые экраны, пластик, хром, мягкая студийная подсветка, рекламная эстетика старого будущего, объектив 50 мм, f/2.8.
12	Соларпанк	Светлая экологичная эстетика: растения, солнечный свет, дерево, стекло, зелёные технологии, солнечные панели, чистый воздух, оптимистичный мир будущего, тёплая натуральная палитра, объектив 35 мм, f/3.5.
13	Биопанк	Органическая научная среда: корни, живые ткани, зелёно-бирюзовое свечение, колбы, влажные поверхности, биологические структуры, странная лаборатория, сочетание природы и технологии, объектив 50 мм, f/2.8.
14	Постапокалипсис	Разрушенный мир после катастрофы: трещины, пыль, ржавчина, сломанные конструкции, грязь, холодный свет, следы выживания, реалистичная разруха, но исходная сцена остаётся читаемой, объектив 35 мм, f/4.
15	Грязный реализм	Жёсткая бытовая фактура: старые стены, потёртый металл, пятна, царапины, пыль, неидеальные поверхности, натуральный грубый свет, документальная реалистичность, объектив 50 мм, f/2.8.
16	Средневековая старина	Камень, дерево, свечи, пергамент, грубые ткани, старинные предметы, тёплый огонь, атмосфера средневекового кабинета, замка или мастерской, реалистичная историческая реконструкция, объектив 50 мм, f/2.8.
17	Античный мир	Светлая древняя эстетика: известковые стены, колонны, керамика, лен, камень, мягкое солнце, тёплая песочная палитра, реалистичный древний интерьер или городская среда, объектив 35 мм, f/4.
18	Тёмное фэнтези	Мрачный магический мир, камень, дым, свечи, холодные тени, загадочные символы, тяжёлая атмосфера, драматичный свет, ощущение древней силы, cinematic dark fantasy, объектив 50 мм, f/2.8.
19	Светлое фэнтези	Волшебный мир с мягким золотистым светом, парящими частицами, невозможным пейзажем, красивой архитектурой, сияющими деталями, сказочная реалистичность, ясная композиция, объектив 35 мм, f/3.5.
20	Другой мир / портал	Окружение выглядит как реальность, переходящая в невозможный мир: световые разломы, парящие предметы, необычная гравитация, странный пейзаж за границей сцены, мягкое магическое свечение, объектив 35 мм, f/3.5.
21	Подводный мир	Сцена погружена в подводную эстетику: голубой свет, мягкие лучи через воду, пузырьки, плавающие ткани и мелкие предметы, приглушённые цвета, ощущение глубины и плавности, объектив 35 мм, f/4.
22	Арктика / ледяной мир	Холодная бело-голубая палитра, лёд, снег, иней, прозрачные замёрзшие поверхности, холодный воздух, мягкие отражения, чистая суровая атмосфера, объектив 35 мм, f/4.
23	Пустынный мир	Песок, тёплый жёлто-оранжевый свет, пыль в воздухе, сухие материалы, выжженная атмосфера, длинные тени, ощущение жары и простора, объектив 35 мм, f/5.6.
24	Аниме реализм	Качественная аниме-иллюстрация, выразительное лицо с прорисованными глазами, носом, ртом и эмоцией, чистые контуры, мягкая cel-shading тень, аккуратные волосы, естественная композиция, не чиби, не карикатура.
25	Манга / тушь	Чёрно-белая манга-эстетика, чёткая тушевая линия, скринтоны, аккуратная штриховка, выразительные лица, ясные силуэты, сильный контраст, композиция как кадр из качественной манги.
26	Цветной графический роман	Премиальный comic book / graphic novel style, чёткие контуры, выразительная штриховка, насыщенные цвета, драматичный свет, читаемые лица, детальные материалы, ощущение дорогой комиксной обложки.
27	3D мульт высокого качества	Стильный 3D cartoon render, мягкие округлые формы, приятные лица, выразительные глаза, аккуратные материалы, мягкий студийный свет, чистая персонажная пластика, виртуальная камера 50 мм.
28	Low-poly 3D	Низкополигональный 3D-стиль, фасеточные формы, упрощённые материалы, геометрические силуэты, мягкие тени, читаемые лица и объекты, стильная game-art эстетика, виртуальная камера 50 мм.
29	Пластилин stop-motion	Всё выглядит как физическая лепка из пластилина: матовая глина, следы пальцев, неровные края, миниатюрный масштаб, мягкий студийный свет, stop-motion эстетика, macro 60 мм, f/5.6.
30	Бумажная диорама	Всё собрано из бумаги и картона: видимые слои, вырезанные края, бумажная фактура, мягкие тени от слоёв, shadowbox-композиция, ручная аппликация, macro 60 мм, f/5.6.
31	Пиксель-арт	Чёткий 16-bit pixel art, крупная пиксельная сетка, ограниченная палитра, читаемые силуэты, аккуратные пиксельные тени, без плавных фотореалистичных текстур, стиль качественной игровой сцены.
32	Вектор с лицом	Чистая векторная иллюстрация, плоские формы, ограниченная палитра, аккуратные контуры, лицо обязательно прорисовано простыми элементами: глаза, брови, нос, рот, выражение, современная editorial vector эстетика.
33	Изометрия	Изометрический визуал, камера сверху под углом, аккуратная геометрия, читаемая сцена как миниатюрная модель, чистые формы, мягкие тени, все объекты расположены ясно, стиль интерфейсной 3D-иллюстрации.
34	Технический чертёж	Сцена превращена в аккуратную техническую схему: тонкие линии, синие или белые чертёжные контуры, размеры, конструктивные детали, полупрозрачные слои, blueprint aesthetic, но главный объект остаётся узнаваемым.
35	Музейный архив	Старинная архивная эстетика: выцветшая бумага, аккуратная экспозиция, подписи как музейные таблички без читаемого текста, мягкий рассеянный свет, ощущение редкого исторического объекта, объектив 50 мм, f/4.
36	Продуктовый каталог	Чистая каталожная подача: ровный свет, нейтральный фон, главный объект идеально читается, материалы выглядят дорого и аккуратно, минимум лишних деталей, commercial product photography, объектив 70 мм, f/5.6.
`
}

function textToImageTemplateRows() {
  return `
1	Миниатюрный город в разбитой чашке	На деревянном столе стоит треснувшая фарфоровая чашка, внутри чашки вырос крошечный ночной город с мостами, окнами, улицами и маленьким поездом по краю блюдца. Из трещины чашки вытекает тонкая светящаяся река. Макрофотография, реалистичный фарфор, уютный тёплый свет, много мелких красивых деталей, но главный объект хорошо читается, без текста, без логотипов, без водяных знаков.
2	Биолаборатория в корнях	Странная живая лаборатория, выросшая внутри огромных древесных корней. Стеклянные сосуды, органические экраны, светящаяся зелёная жидкость и мягкие биолюминесцентные жилы встроены в корни. Учёный изучает живое механическое семя на столе, влажный воздух, кинематографичная биопанк-атмосфера, детальные фактуры, без текста, без логотипов, без водяных знаков.
3	Чемодан с целым миром	Открытый винтажный чемодан на деревянном столе, а внутри него находится целый миниатюрный мир: горы, извилистая река, маленькие дома, мост, облака и тёплый закатный свет. Комната вокруг мягко размыта, миниатюрный ландшафт очень детальный и резкий. Магический реализм, макрофотография, реалистичные ручные материалы, объектив 60 мм, без текста, без логотипов, без водяных знаков.
4	Поезд в книжной полке	Крупный план старой книжной полки вечером, между книгами проходит крошечная железная дорога, по ней едет маленький светящийся поезд. Из тоннеля между книгами выходит пар, на корешках книг мягкие отражения, рядом чашка чая и очки. Макрофотография, уютная атмосфера, реалистичные материалы, сказочная детальность, без читаемого текста, без логотипов, без водяных знаков.
5	Тайная станция под ковром	Обычная гостиная, край ковра приподнят, а под ним видна миниатюрная подземная станция с рельсами, лампами, трубами и маленькими рабочими механизмами. Человек стоит на коленях и светит фонариком под ковёр, удивлённо рассматривая скрытый мир. Фотореализм, макро-детали, тёплый домашний свет, без текста, без логотипов, без водяных знаков.
6	Последний магазин дождя	Уютная маленькая лавка вечером, на полках стоят стеклянные банки с разными видами дождя: летний дождь, гроза, снег с дождём, тёплый грибной дождь. Продавец открывает одну банку, и над прилавком появляется маленькая туча с каплями. Дерево, стекло, тёплые лампы, магический реализм, без читаемого текста, без логотипов, без водяных знаков.
7	Портной шьёт крылья	Старая мастерская портного, на манекене висят большие полупрозрачные крылья из ткани, нитей и света. Портной аккуратно прошивает край крыла на швейной машине, вокруг катушки, ножницы, выкройки и тёплая пыль в воздухе. Фотореализм, ремесленная магия, красивый свет, без текста, без логотипов, без водяных знаков.
8	Космическая станция	Инженер проверяет панель управления внутри реалистичного модуля орбитальной станции, рядом инструменты закреплены на стене, через большой иллюминатор видна огромная планета и звёзды. Холодный бело-синий свет, герметичный модуль, ощущение настоящей станции, объектив 35 мм, f/4, чистый фотореализм, без текста, без логотипов, без водяных знаков.
9	Киберпанк неон	Курьер будущего останавливается у автомата доставки на мокрой ночной улице мегаполиса, рядом футуристический мотоцикл, дождь, сине-розовый неон, отражения на асфальте, голограммы, высокая контрастность. Cinematic cyberpunk, объектив 35 мм, f/2.0, технологичная ночная атмосфера, без текста, без логотипов, без водяных знаков.
10	Стимпанк	Мастер запускает огромный латунный механический телескоп в викторианской мастерской, вокруг шестерёнки, трубы, манометры, медь, дерево, пар и тёплый янтарный свет. Викторианско-индустриальная эстетика, детальная механическая среда, объектив 50 мм, f/2.8, без текста, без логотипов, без водяных знаков.
11	Ретрофутуризм 60-х	Семья рассматривает домашнего робота-помощника в яркой гостиной будущего глазами 1960-х: округлые формы, пастельные панели, хром, пластик, винтажные приборы и мягкая студийная подсветка. Рекламная эстетика старого будущего, объектив 50 мм, f/2.8, без текста, без логотипов, без водяных знаков.
12	Грязный реализм	Механик в старой мастерской ремонтирует потёртый мотоцикл у грязного окна, вокруг старые стены, пятна масла, царапины, пыль, грубый натуральный свет и неидеальные поверхности. Документальная реалистичность, объектив 50 мм, f/2.8, без текста, без логотипов, без водяных знаков.
13	Средневековая старина	Картограф в средневековом кабинете чертит карту морского пути при свете свечей, на столе пергамент, компас, грубые ткани, дерево, камень, старинные инструменты и тёплый огонь. Реалистичная историческая реконструкция. Все руки неместе, пальци реалистичны, объектив 50 мм, f/2.8, без читаемого текста, без логотипов, без водяных знаков.
14	Тёмное фэнтези	Маг-кузнец создаёт чёрный артефакт на каменном алтаре в подземной мастерской, вокруг дым, свечи, холодные тени, древние символы, тяжёлая атмосфера и драматичный свет. Cinematic dark fantasy, объектив 50 мм, f/2.8, без текста, без логотипов, без водяных знаков.
15	Светлое фэнтези	Путешественница идёт по мраморному мосту между сияющими башнями над облаками, вокруг мягкий золотистый свет, парящие частицы, невозможный пейзаж и красивая архитектура. Сказочная реалистичность, ясная композиция, объектив 35 мм, f/3.5, без текста, без логотипов, без водяных знаков.
16	Цветной графический роман	Детектив будущего открывает дверь в подпольную лабораторию, в руке фонарь, на лице напряжение, за дверью синий свет и силуэты механизмов. Премиальный comic book / graphic novel style, чёткие контуры, выразительная штриховка, насыщенные цвета, драматичный свет, читаемые лица, ощущение дорогой комиксной обложки, без текста.
17	3D мульт высокого качества	Маленький инженер-изобретатель запускает смешного домашнего робота на рабочем столе, вокруг аккуратные инструменты, лампа, детали и мягкий студийный свет. Стильный 3D cartoon render, мягкие округлые формы, приятные лица, выразительные глаза, аккуратные материалы, виртуальная камера 50 мм, без текста, без логотипов.
18	Low-poly 3D	Низкополигональный путешественник стоит на краю геометрического каньона перед маленьким футуристическим лагерем, рядом транспорт и костёр. Low-poly 3D-стиль, фасеточные формы, упрощённые материалы, геометрические силуэты, мягкие тени, читаемые объекты, стильная game-art эстетика, виртуальная камера 50 мм, без текста.
19	Пластилин stop-motion	Пластилиновый повар готовит огромный светящийся пирог в маленькой кухне, рядом смешные миниатюрные кастрюли, стол, мука и тёплая лампа. Всё выглядит как физическая лепка из пластилина: матовая глина, следы пальцев, неровные края, миниатюрный масштаб, мягкий студийный свет, stop-motion эстетика, macro 60 мм, f/5.6, без текста.
20	Бумажная диорама	Бумажный город на склоне горы, маленький поезд пересекает мост, облака и деревья сделаны из вырезанной бумаги, дома стоят слоями внутри shadowbox-композиции. Видимые слои, вырезанные края, бумажная фактура, мягкие тени от слоёв, ручная аппликация, macro 60 мм, f/5.6, без текста.
21	Пиксель-арт	Ночной вокзал в стиле 16-bit pixel art: маленький герой стоит на платформе с чемоданом, поезд с тёплыми окнами подъезжает под дождём, отражения в лужах. Чёткая пиксельная сетка, ограниченная палитра, читаемые силуэты, аккуратные пиксельные тени, без плавных фотореалистичных текстур, без текста.
22	Вектор с лицом	Современная векторная иллюстрация: дизайнер сидит за столом у большого окна, рядом растения, планшет, чашка кофе и аккуратная лампа, лицо хорошо читается с глазами, бровями, носом, ртом и спокойным выражением. Плоские формы, ограниченная палитра, аккуратные контуры, editorial vector эстетика, без текста.
23	Изометрия	Изометрическая сцена миниатюрного научного хаба: лаборатория, зона отдыха, серверная, маленькие персонажи работают с устройствами, все объекты ясно расположены. Камера сверху под углом, аккуратная геометрия, чистые формы, мягкие тени, стиль интерфейсной 3D-иллюстрации, без текста, без логотипов.
`
}

function fitGenerationDimension(value: number) {
  return Math.max(512, Math.min(1536, Math.round(value / 16) * 16))
}

const uploadImageMaxSide = 1536

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
    const scale = Math.min(1, uploadImageMaxSide / Math.max(1, maxSide))
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

function App() {
  const [lang, setLang] = useState<Lang>('ru')
  const [mode, setMode] = useState<Mode>('text_to_image')
  const [paintTool, setPaintTool] = useState<PaintTool>('sketch')
  const [paintEditor, setPaintEditor] = useState<PaintEditor>(null)
  const [tab, setTab] = useState<Tab>('studio')
  const [pathName, setPathName] = useState(() => window.location.pathname)
  const [provider, setProvider] = useState('comfyui')
  const [promptByMode, setPromptByMode] = useState<Record<string, string>>(() => initialPromptByMode(workflowPresets))
  const [negativePrompt, setNegativePrompt] = useState(DEFAULT_NEG_PROMPT)
  const [seed, setSeed] = useState(0)
  const [width, setWidth] = useState(1024)
  const [height, setHeight] = useState(1024)
  const [steps, setSteps] = useState(4)
  const [cfg, setCfg] = useState(1)
  const [strength, setStrength] = useState(0.75)
  const [selectedLora, setSelectedLora] = useState('none')
  const [modelProfile, setModelProfile] = useState('local_flux_klein')
  const [sampler, setSampler] = useState('er_sde')
  const [sizeSource, setSizeSource] = useState<'image1' | 'image2' | 'custom'>('image1')
  const [inputOne, setInputOne] = useState<string>()
  const [inputTwo, setInputTwo] = useState<string>()
  const [editSlots, setEditSlots] = useState<EditSlot[]>(() => EMPTY_EDIT_SLOTS.map((s) => ({ ...s })))
  const [pendingEditSlot, setPendingEditSlot] = useState<number | null>(null)
  const [editManualMode, setEditManualMode] = useState(false)
  const [editManualPrompt, setEditManualPrompt] = useState('')
  const [editAdvancedOpen, setEditAdvancedOpen] = useState(false)
  const [editTemplatesOpen, setEditTemplatesOpen] = useState(false)
  const [job, setJob] = useState<Job>()
  const [gallery, setGallery] = useState<GalleryImage[]>([])
  const [selected, setSelected] = useState<GalleryImage>()
  const [admin, setAdmin] = useState<Record<string, unknown>>()
  const [bootstrap, setBootstrap] = useState<Record<string, unknown>>()
  const [tariffs, setTariffs] = useState<TariffConfig>(DEFAULT_TARIFFS)
  const [galleryView, setGalleryView] = useState<'grid' | 'list'>('grid')
  const [notice, setNotice] = useState('')
  const [discoverOpen, setDiscoverOpen] = useState(false)
  const [instructionOpen, setInstructionOpen] = useState(false)
  const [userPresets, setUserPresets] = useState<Preset[]>(() => loadUserPresets())
  const [, setFluxConfig] = useState<FluxConfig>()
  const [modelsPayload, setModelsPayload] = useState<ModelsPayload>()
  const [, setBgRemovalModels] = useState<string[]>([])
  const [loraTriggers, setLoraTriggers] = useState<Record<string, string>>({})
  // Single-flight guard для Generate: синхронный ref блокирует повторные клики/хоткеи/
  // double-tap до того, как React-state успеет обновиться. isSubmitting — для UI.
  const generateInFlightRef = useRef(false)
  const generateRef = useRef<(() => Promise<void>) | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)

  useEffect(() => {
    document.title = 'ИЗО_АСА'
  }, [])
  // Из Ленты «Открыть галерею» ведёт на /?open=gallery — уводим на
  // каноничную статическую галерею, чтобы не оживлять старый React-экран.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    if (params.get('open') === 'gallery') {
      window.location.replace('/gallery')
    }
  }, [])
  const [paintLines, setPaintLines] = useState<PaintLine[]>([])
  const [maskLines, setMaskLines] = useState<PaintLine[]>([])
  const [canvasSnapshot, setCanvasSnapshot] = useState<string>()
  const [outpaintPreview, setOutpaintPreview] = useState<string>()
  const [tool, setTool] = useState<'brush' | 'eraser'>('brush')
  const [brushSize, setBrushSize] = useState(10)
  const [paintColor, setPaintColor] = useState('#111827')
  const [layerOpacity, setLayerOpacity] = useState(1)
  const [outpaint, setOutpaint] = useState({ left: 0, right: 256, top: 0, bottom: 0, scaleDown: true })
  const drawingRef = useRef(false)
  const canvasRef = useRef<KonvaStage>(null)
  const copy = t[lang]
  const SESSION_KEY = 'izo_asa_session'
  const sessionRestoredRef = useRef(false)
  const [profileLanguageLoaded, setProfileLanguageLoaded] = useState(false)

  useEffect(() => {
    const saved = sessionStorage.getItem(SESSION_KEY)
    queueMicrotask(() => {
      try {
        if (!saved) return
        const s = JSON.parse(saved)
        if (s.promptByMode && typeof s.promptByMode === 'object') setPromptByMode(s.promptByMode)
        else if (s.prompt !== undefined) setPromptByMode((current) => ({ ...current, text_to_image: s.prompt }))
        if (s.negativePrompt !== undefined) setNegativePrompt(s.negativePrompt)
        if (s.mode) setMode(s.mode)
        if (s.seed !== undefined) setSeed(s.seed)
        if (s.width) setWidth(s.width)
        if (s.height) setHeight(s.height)
        if (s.steps) setSteps(s.steps)
        if (s.cfg !== undefined) setCfg(s.cfg)
        if (s.strength !== undefined) setStrength(s.strength)
        if (s.selectedLora !== undefined) setSelectedLora(s.selectedLora)
        if (s.modelProfile) setModelProfile(s.modelProfile)
        if (s.provider) setProvider(s.provider)
        if (s.paintTool) setPaintTool(s.paintTool)
        if (['studio', 'gallery', 'presets', 'settings'].includes(s.tab)) setTab(s.tab)
        if (s.sampler) setSampler(s.sampler)
        if (s.lang) setLang(s.lang)
      } catch { /* ignore */ }
      finally {
        sessionRestoredRef.current = true
      }
    })
  }, [])

  useEffect(() => {
    if (!sessionRestoredRef.current) return
    sessionStorage.setItem(SESSION_KEY, JSON.stringify({
      promptByMode, negativePrompt, mode, seed, width, height, steps, cfg, strength,
      selectedLora, modelProfile, provider, paintTool, tab, sampler, lang,
    }))
  }, [promptByMode, negativePrompt, mode, seed, width, height, steps, cfg, strength, selectedLora, modelProfile, provider, paintTool, tab, sampler, lang])

  // Trusted auth-v2 state (cookie session). The ONLY source for the generation lock.
  const { status: authV2Status, me: authMe } = useAuthV2()
  const isAuthedV2 = authV2Status === 'authed'
  const [authModalOpen, setAuthModalOpen] = useState(false)
  const adminRoute = pathName === '/admin' || pathName.startsWith('/admin/')
  // UI 2.0: experimental /new route (docs/new-ui-v2-plan.md). Minimal hook only.
  const newUiRoute = pathName === '/new' || pathName.startsWith('/new/')
  // Редактор — отдельный канонический маршрут нового UI. Пока использует общий
  // shell NewStudio; физическое code-splitting вынесено отдельным слоем.
  const paintRoute = pathName === '/paint' || pathName.startsWith('/paint/')
  // /feed is a backend static page. Keep a guard here so a stale frontend
  // fallback cannot revive the old React feed implementation.
  const staticFeedRoute = pathName === '/feed' || pathName.startsWith('/feed/')
  // Профиль остаётся React-страницей. Галерея больше не рендерится здесь:
  // канонический /gallery отдаётся backend/static/gallery.
  const profileRoute =
    pathName === '/profile' || pathName.startsWith('/profile/') || pathName === '/new/profile'

  useEffect(() => {
    const onPopState = () => setPathName(window.location.pathname)
    window.addEventListener('popstate', onPopState)
    return () => window.removeEventListener('popstate', onPopState)
  }, [])

  const openAdminPage = useCallback(() => {
    window.location.href = '/admin'
  }, [])

  useEffect(() => {
    const profileLang = authMe?.profile?.language_code
    if (!profileLanguageLoaded && (profileLang === 'ru' || profileLang === 'en')) {
      queueMicrotask(() => {
        setLang(profileLang)
        setProfileLanguageLoaded(true)
      })
    }
  }, [authMe?.profile?.language_code, profileLanguageLoaded])

  const changeLanguage = useCallback((value: Lang) => {
    setLang(value)
    setProfileLanguageLoaded(true)
    if (authV2Status === 'authed') {
      void updateProfileV2({
        language_code: value,
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || '',
      }).then((updated) => { if (updated) void refreshAuthStateV2() })
    }
  }, [authV2Status])

  useEffect(() => { if (tab === 'settings') { void refreshAuthStateV2() } }, [tab])

  const currentUser = (bootstrap?.user || {}) as { id?: string; role?: string; username?: string; firstName?: string; plan?: string; galleryEnabled?: boolean; dailyTokens?: number; gallerySlots?: number; galleryUsed?: number; galleryFree?: number; galleryFull?: boolean }
  const isAdmin = authV2Status === 'authed' && authMe?.account?.role === 'admin'
  const galleryLocked = false
  const currentPlanKey = (tariffKeys.includes(String(authMe?.account?.plan || currentUser.plan || 'mini').toLowerCase() as TariffKey)
    ? String(authMe?.account?.plan || currentUser.plan || 'mini').toLowerCase()
    : 'mini') as TariffKey
  const activeTariff = tariffs[currentPlanKey] || DEFAULT_TARIFFS[currentPlanKey]
  const galleryUsed = Number(authMe?.account?.gallery_used ?? currentUser.galleryUsed ?? gallery.length)
  const galleryQuota: GalleryQuota = {
    plan: currentPlanKey,
    daily_tokens: Number(authMe?.account?.daily_tokens ?? currentUser.dailyTokens ?? activeTariff.daily_tokens),
    gallery_slots: Number(authMe?.account?.gallery_slots ?? currentUser.gallerySlots ?? activeTariff.gallery_slots),
    gallery_used: galleryUsed,
    gallery_free: Math.max(0, Number(authMe?.account?.gallery_slots ?? currentUser.gallerySlots ?? activeTariff.gallery_slots) - galleryUsed),
    gallery_full: Boolean(authMe?.account?.gallery_full ?? currentUser.galleryFull ?? galleryUsed >= Number(authMe?.account?.gallery_slots ?? currentUser.gallerySlots ?? activeTariff.gallery_slots)),
  }
  const activeMode = modes.find((item) => item.id === mode)!
  const cloudLimited = provider === 'openrouter'
  const actualMode: Mode = mode === 'paint' && paintTool !== 'sketch' ? paintTool : mode
  useEffect(() => {
    if (actualMode !== 'outpaint') queueMicrotask(() => setOutpaintPreview(undefined))
  }, [actualMode])
  const allPresets = useMemo(() => [...workflowPresets, ...userPresets], [userPresets])
  const promptKey = promptKeyFor(mode, paintTool)
  const prompt = promptByMode[promptKey] ?? ''
  const setPrompt = useCallback((value: string) => {
    setPromptByMode((current) => ({ ...current, [promptKey]: value }))
  }, [promptKey])
  const setPromptForKey = useCallback((key: PromptKey, value: string) => {
    setPromptByMode((current) => ({ ...current, [key]: value }))
  }, [])
  const loraOptions = useMemo<LoraOption[]>(() => {
    const found = (modelsPayload?.loras || []).filter((item) => item && item !== 'none')
    if (!found.length) return fallbackLoraOptions
    return [{ id: 'none', label: 'None', triggerWord: '', strength: 0 }, ...found.map((item) => ({ id: item, label: item, triggerWord: loraTriggers[item] || '', strength: item.toLowerCase().includes('bfs') || item.toLowerCase().includes('face') ? 1 : 0.8 }))]
  }, [loraTriggers, modelsPayload])
  const faceLora = useMemo(() => {
    const candidates = loraOptions.filter((item) => item.id !== 'none')
    return candidates.find((item) => /bfs|face|head/i.test(item.id)) || candidates[0]
  }, [loraOptions])
  const activeSelectedLora = actualMode === 'faceswap' && selectedLora === 'none' && faceLora ? faceLora.id : selectedLora
  const visiblePresets = allPresets.filter((item) => {
    if (mode === 'paint') {
      const toolMode: Mode = paintTool === 'sketch' ? 'paint' : paintTool
      return item.mode === toolMode
    }
    return item.mode === mode
  })

  useEffect(() => {
    if (promptByMode[promptKey] !== undefined) return
    queueMicrotask(() => {
      setPromptByMode((current) => {
        if (current[promptKey] !== undefined) return current
        return { ...current, [promptKey]: '' }
      })
    })
  }, [promptByMode, promptKey])

  const fetchGallery = useCallback(async () => {
    // /api/gallery returns 401 (JSON {detail}) when unauthenticated; only ever
    // store an array so gallery.slice/.map/.length never crash the render.
    const images = await apiFetch('/gallery').then((r) => (r.ok ? r.json() : [])).catch(() => [])
    setGallery(Array.isArray(images) ? images : [])
  }, [])

  useEffect(() => {
    if (authV2Status !== 'authed') return undefined
    let cancelled = false
    window.setTimeout(() => {
      if (!cancelled) void fetchGallery()
    }, 0)
    return () => { cancelled = true }
  }, [authV2Status, authMe?.internal_user_id, fetchGallery])

  useEffect(() => {
    apiFetch('/tariffs')
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => setTariffs(normalizeTariffs(data?.tariffs)))
      .catch(() => setTariffs(DEFAULT_TARIFFS))
  }, [])

  useEffect(() => {
    // Identity/Auth v2: bootstrap + restore the cookie session at startup.
    void initAuthV2()
    const tg = (window as Window & { Telegram?: { WebApp?: { ready?: () => void; expand?: () => void; initData?: string; initDataUnsafe?: { user?: { id?: number; username?: string; first_name?: string; last_name?: string; language_code?: string } } } } }).Telegram?.WebApp
    tg?.ready?.()
    tg?.expand?.()
    const params = new URLSearchParams(window.location.search)
    const platform = tg?.initData ? 'telegram' : 'web'
    const tgUser = tg?.initDataUnsafe?.user
    const effectiveUserId = platform === 'telegram' && tgUser?.id ? String(tgUser.id) : ''
    const screenInfo = `${window.screen.width}x${window.screen.height}@${window.devicePixelRatio || 1}`
    apiFetch('/app/bootstrap', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        platform,
        language: navigator.language?.slice(0, 2) || 'ru',
        userId: effectiveUserId,
        username: tgUser?.username,
        firstName: tgUser?.first_name,
        lastName: tgUser?.last_name,
        initData: tg?.initData,
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
        ref: params.get('ref'),
        screen: screenInfo,
        userAgent: navigator.userAgent,
      }),
    }).then((r) => r.json()).then((data) => {
      setBootstrap(data)
      apiFetch('/gallery').then((r) => (r.ok ? r.json() : [])).then((data) => setGallery(Array.isArray(data) ? data : [])).catch(() => undefined)
      if (data?.fluxKleinConfig?.ok !== false) setFluxConfig(data.fluxKleinConfig)
      if (data?.models?.ok !== false) setModelsPayload(data.models)
      if (Array.isArray(data?.bgRemovalModels?.models)) setBgRemovalModels(data.bgRemovalModels.models)
    }).catch(() => undefined)
    apiFetch('/flux-klein/config').then((r) => r.json()).then((data) => {
      if (data?.ok !== false) setFluxConfig((current) => current || data)
    }).catch(() => undefined)
    apiFetch('/models').then((r) => r.json()).then((data) => setModelsPayload((current) => current || data)).catch(() => undefined)
    apiFetch('/flux-klein/bgremoval-models').then((r) => r.json()).then((data) => {
      setBgRemovalModels((current) => current.length ? current : Array.isArray(data?.models) ? data.models : [])
    }).catch(() => undefined)
  }, [])

  useEffect(() => {
    if (authV2Status !== 'authed' || !authMe?.legacy_user_id) return undefined
    const heartbeatUserId = authMe.legacy_user_id
    const rawId = heartbeatUserId.replace(/^(web_|telegram_|max_)/, '')
    const heartbeatPlatform = heartbeatUserId.startsWith('telegram_') ? 'telegram' : heartbeatUserId.startsWith('max_') ? 'max' : 'web'
    const heartbeat = window.setInterval(() => {
      apiFetch('/app/heartbeat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ platform: heartbeatPlatform, userId: rawId, seconds: 60 }),
      }).catch(() => undefined)
    }, 60000)
    return () => window.clearInterval(heartbeat)
  }, [authV2Status, authMe?.legacy_user_id])

  useEffect(() => {
    if (!job || ['completed', 'failed', 'cancelled'].includes(job.status)) return
    const timer = window.setInterval(async () => {
      const next = await apiFetch(`/jobs/${job.id}`).then((r) => r.json())
      setJob(next)
      if (next.status === 'completed') {
        fetchGallery()
        void refreshAuthStateV2()
      }
    }, 900)
    return () => window.clearInterval(timer)
  }, [fetchGallery, job])

  useEffect(() => {
    if (!activeSelectedLora || activeSelectedLora === 'none' || loraTriggers[activeSelectedLora] !== undefined) return
    apiFetch(`/flux-klein/lora-triggers?name=${encodeURIComponent(activeSelectedLora)}`).then((r) => r.json()).then((data) => {
      const trigger = Array.isArray(data?.triggers) ? data.triggers.join(', ') : ''
      setLoraTriggers((current) => ({ ...current, [activeSelectedLora]: trigger }))
    }).catch(() => setLoraTriggers((current) => ({ ...current, [activeSelectedLora]: '' })))
  }, [activeSelectedLora, loraTriggers])

  // Edit Prompt Composer: единый источник для собранного prompt + блокировки Generate.
  // userNote = текстовое поле «Дополнительное пожелание» (state `prompt`).
  const editComposer = useMemo(
    () => editComposerStatus({ slots: editSlots, userNote: prompt, manualMode: editManualMode, manualPrompt: editManualPrompt }),
    [editSlots, prompt, editManualMode, editManualPrompt],
  )
  const editBlockReason = actualMode === 'edit' ? editComposer.blockReason : null

  const canGenerate = useMemo(() => {
    if (cloudLimited && ['inpaint', 'outpaint', 'faceswap', 'remove_background', 'try_on', 'texture_transfer'].includes(actualMode)) return false
    if (actualMode === 'edit') return editBlockReason === null
    if (actualMode !== 'text_to_image' && actualMode !== 'paint' && !inputOne) return false
    if (['faceswap', 'try_on', 'texture_transfer'].includes(actualMode) && !inputTwo) return false
    if (actualMode === 'faceswap' && activeSelectedLora === 'none') return false
    return prompt.trim().length > 0 || actualMode === 'faceswap'
  }, [actualMode, activeSelectedLora, cloudLimited, editBlockReason, inputOne, inputTwo, prompt])

  async function imageRequestSize() {
    const baseImage = actualMode === 'edit' ? editSlots[0].image : inputOne
    if (!baseImage || actualMode === 'text_to_image' || actualMode === 'outpaint' || sizeSource === 'custom') return { width, height }
    const sourceImage = baseImage
    const image = await new Promise<HTMLImageElement>((resolve, reject) => {
      const img = new Image()
      img.onload = () => resolve(img)
      img.onerror = reject
      img.src = sourceImage
    }).catch(() => undefined)
    const sourceWidth = image?.naturalWidth || width
    const sourceHeight = image?.naturalHeight || height
    const maxSide = 1536
    const scale = Math.min(1, maxSide / Math.max(sourceWidth, sourceHeight))
    return {
      width: fitGenerationDimension(sourceWidth * scale),
      height: fitGenerationDimension(sourceHeight * scale),
    }
  }

  const jobIsActive = (status?: string) => !!status && ['queued', 'running', 'uploading', 'sent_to_comfyui'].includes(status)

  async function generate() {
    // СИНХРОННЫЙ guard ДО любого await — гарантирует ровно 1 POST на серию быстрых кликов.
    if (generateInFlightRef.current) return
    if (!canGenerate) return
    if (jobIsActive(job?.status)) return
    generateInFlightRef.current = true
    setIsSubmitting(true)
    try {
    const canvasData = actualMode === 'outpaint'
      ? undefined
      : (actualMode === 'paint' || actualMode === 'inpaint') ? (canvasRef.current?.toDataURL({ pixelRatio: 1 }) || canvasSnapshot) : undefined
    const lora = loraOptions.find((item) => item.id === activeSelectedLora)
    const effectiveSeed = seed || Math.floor(Math.random() * 999999999)
    const requestSize = await imageRequestSize()
    if (actualMode === 'outpaint') {
      setOutpaintPreview(await createOutpaintPreview(inputOne, outpaint, requestSize))
    } else {
      setOutpaintPreview(undefined)
    }
    const isEdit = actualMode === 'edit'
    // Edit: финальный prompt собирает Prompt Composer (auto) или ручной prompt (manual).
    // negativePrompt для edit не уходит; все заполненные слоты идут в inputImages.
    const filledEditSlots = editSlots.map((slot, index) => ({ ...slot, index })).filter((slot) => slot.image)
    const editFinalPrompt = isEdit ? editComposer.finalPrompt : prompt
    const editInputImages = isEdit
      ? filledEditSlots.map((slot) => ({ index: slot.index + 1, role: slot.index === 0 ? 'base' : slot.role, image: slot.image! }))
      : undefined
    if (isEdit) console.info('[edit] payload images', editInputImages?.map((item) => ({ index: item.index, role: item.role })))
    const body = {
      mode: actualMode,
      provider,
      prompt: editFinalPrompt,
      negativePrompt: isEdit ? '' : negativePrompt,
      seed: effectiveSeed,
      width: requestSize.width,
      height: requestSize.height,
      steps,
      cfg,
      guidance: 3.5,
      strength: isEdit ? DEFAULT_EDIT_STRENGTH : strength,
      modelProfile: provider === 'comfyui' ? modelProfile : 'openrouter_cloud',
      loras: cloudLimited || !lora || lora.id === 'none' ? [] : [{ id: lora.id, strength: actualMode === 'faceswap' ? strength : lora.strength, triggerWord: lora.triggerWord }],
      inputImage1: isEdit ? editSlots[0].image : inputOne,
      inputImage2: isEdit ? null : inputTwo,
      inputImages: editInputImages,
      maskImage: actualMode === 'inpaint' ? canvasData : undefined,
      canvas: actualMode === 'paint' ? canvasData : undefined,
      outpaintMask: undefined,
      outpaint: actualMode === 'outpaint' ? outpaint : undefined,
      // Трассировка серии (backend игнорирует неизвестные поля) — для отладки дублей.
      clientRequestId: (typeof crypto !== 'undefined' && crypto.randomUUID) ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`,
    }
    const response = await apiFetch('/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (!response.ok) {
      // Понятное сообщение по статусу + тексту backend (а не общий «не удалось»).
      let detail = ''
      try { detail = (await response.json())?.detail || '' } catch { /* non-JSON */ }
      if (response.status === 402) setNotice('Закончились токены. Пополните баланс в «Настройках», чтобы продолжить.')
      else if (response.status === 401 || response.status === 403) { setNotice('Сессия истекла. Войдите снова, чтобы генерировать.'); setAuthModalOpen(true) }
      else if (response.status === 429) setNotice(detail || 'Слишком много запросов подряд. Подождите немного и попробуйте снова.')
      else if (response.status === 422 || response.status === 400) setNotice(detail || 'Проверьте входные данные: основа и роли референсов.')
      else setNotice(detail || `Сервер вернул ошибку (${response.status}). Попробуйте ещё раз.`)
      return
    }
    const created = await response.json()
    setJob(created)
    void refreshAuthStateV2()
    if (!seed) setSeed(effectiveSeed)
    setNotice('')
    setTab('studio')
    window.setTimeout(() => {
      if (window.innerWidth <= 980) document.querySelector('.preview-panel')?.scrollIntoView({ block: 'center' })
    }, 0)
    } catch {
      // Сюда попадаем при сетевой ошибке (сервер недоступен), а не при ответе с кодом.
      setNotice('Проблема соединения с сервером. Проверьте, что сервис запущен, и попробуйте снова.')
    } finally {
      generateInFlightRef.current = false
      setIsSubmitting(false)
    }
  }
  useEffect(() => {
    generateRef.current = generate
  })

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      const tag = document.activeElement?.tagName.toLowerCase()
      const typing = tag === 'textarea' || tag === 'input' || tag === 'select'
      if (event.key === 'Escape') {
        if (typing && document.activeElement instanceof HTMLElement) document.activeElement.blur()
        else {
          setDiscoverOpen(false)
          setInstructionOpen(false)
          if (tab !== 'studio') setTab('studio')
        }
        return
      }
      if (typing) return
      if (event.key.toLowerCase() === 'd') {
        event.preventDefault()
        setTab('studio')
        setDiscoverOpen((open) => !open)
      }
      if (event.key.toLowerCase() === 'g') {
        event.preventDefault()
        setTab((current) => current === 'gallery' ? 'studio' : 'gallery')
      }
      if (event.key.toLowerCase() === 'f') {
        event.preventDefault()
        document.querySelector('.preview-panel')?.scrollIntoView({ block: 'center' })
      }
      if (event.code === 'Space' && canGenerate && !isSubmitting && !generateInFlightRef.current && !jobIsActive(job?.status)) {
        event.preventDefault()
        if (event.repeat) return
        void generateRef.current?.()
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [canGenerate, isSubmitting, job?.status, tab])

  function randomPrompt() {
    const pool = visiblePresets.length ? visiblePresets : allPresets
    const next = pool[Math.floor(Math.random() * pool.length)]
    if (next) setPrompt(next.prompt)
  }

  function applyPreset(preset: Preset) {
    const nextMode = (preset.mode === 'inpaint' || preset.mode === 'outpaint') ? 'paint' : preset.mode as Mode
    const nextPaintTool = preset.mode === 'inpaint' || preset.mode === 'outpaint' ? preset.mode : preset.mode === 'paint' ? 'sketch' : paintTool
    if (preset.mode === 'inpaint' || preset.mode === 'outpaint') {
      setMode('paint')
      setPaintTool(preset.mode)
    } else {
      setMode(preset.mode as Mode)
      if (preset.mode === 'paint') setPaintTool('sketch')
    }
    setPromptForKey(promptKeyFor(nextMode, nextPaintTool), preset.prompt)
    setDiscoverOpen(false)
    setTab('studio')
  }

  function selectMode(nextMode: Mode) {
    setMode(nextMode)
    setTab('studio')
    setDiscoverOpen(false)
    if (nextMode === 'faceswap' && selectedLora === 'none' && faceLora) setSelectedLora(faceLora.id)
    if (nextMode === 'paint') setPaintTool('sketch')
    const nextKey = promptKeyFor(nextMode, nextMode === 'paint' ? 'sketch' : paintTool)
    setPromptByMode((current) => {
      if (current[nextKey] !== undefined) return current
      return { ...current, [nextKey]: '' }
    })
  }

  function addUserPreset(name: string, presetPrompt: string) {
    const nextPreset = {
      id: `user-${Date.now()}`,
      ru: name,
      en: name,
      mode,
      prompt: presetPrompt,
    } as Preset
    const next = [...userPresets, nextPreset]
    setUserPresets(next)
    try {
      window.localStorage.setItem('izo_asa_user_presets', JSON.stringify(next))
    } catch {
      // Saving locally is optional; the preset still appears for the current session.
    }
  }

  async function cancelJob() {
    if (!job) return
    const cancelled = await apiFetch(`/jobs/${job.id}/cancel`, { method: 'POST' }).then((r) => r.json())
    setJob(cancelled)
  }

  async function sendImage(platform: 'telegram' | 'max', imageId?: string) {
    if (!imageId) return
    await apiFetch(`/gallery/${imageId}/send`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ platform }),
    }).then((r) => r.json()).catch(() => undefined)
  }

  async function translatePrompt() {
    const result = await apiFetch('/translate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: prompt, target: 'en' }),
    }).then((r) => r.json())
    setPrompt(result.translated)
  }

  function upload(setter: (url: string) => void) {
    const input = document.createElement('input')
    input.type = 'file'
    input.accept = 'image/png,image/jpeg,image/webp,image/heic'
    input.onchange = async () => {
      const file = input.files?.[0]
      if (!file) return
      if (file.size > 25 * 1024 * 1024) {
        setNotice(copy.fileTooLarge)
        return
      }
      try {
        setter(await resizeUploadImage(file))
      } catch {
        setNotice(copy.fileTooLarge)
      }
    }
    input.click()
  }

  // Edit slot helpers (0-индексация: slot 0 = основа, 1..3 = референсы).
  function setEditSlotImage(index: number, url?: string) {
    setEditSlots((current) => current.map((slot, i) => (i === index ? { ...slot, image: url } : slot)))
  }
  function setEditSlotRole(index: number, role: EditReferenceRole | '') {
    if (role === 'pose') {
      setNotice('Смена позы временно отключена: режим нестабилен и может надолго занять видеокарту.')
      return
    }
    setEditSlots((current) => current.map((slot, i) => (i === index ? { ...slot, role } : slot)))
  }
  function setEditSlotTakeNote(index: number, takeNote: string) {
    setEditSlots((current) => current.map((slot, i) => (i === index ? { ...slot, takeNote } : slot)))
  }
  function clearEditSlot(index: number) {
    // При удалении референса его роль и заметка обязательно сбрасываются.
    setEditSlots((current) => current.map((slot, i) => (i === index ? { image: undefined, role: '', takeNote: '' } : slot)))
  }
  // Применить шаблон: назначает роли референсам + ставит userNote. Не перетирает уже
  // выбранные роли без подтверждения. Возвращает в auto-режим, чтобы prompt пересобрался.
  function applyEditTemplate(tpl: EditTemplate) {
    if (tpl.assign.some(({ role }) => role === 'pose')) {
      setNotice('Шаблон со сменой позы временно недоступен.')
      return
    }
    const conflict = tpl.assign.some(({ refIndex, role }) => {
      const s = editSlots[refIndex]
      return s && s.role && s.role !== role
    })
    const replaceRoles = !conflict || window.confirm('Применить шаблон и заменить уже выбранные роли референсов?')
    setEditSlots((current) => current.map((slot, i) => {
      const a = tpl.assign.find((x) => x.refIndex === i)
      return a && replaceRoles ? { ...slot, role: a.role } : slot
    }))
    setPrompt(tpl.userNote)
    setEditManualMode(false)
    setEditTemplatesOpen(false)
  }

  async function useImageAs(image: GalleryImage, target: Mode, slot = 1) {
    const normalizedTarget: Mode = target === 'try_on' || target === 'texture_transfer' ? 'edit' : target === 'remove_background' || target === 'inpaint' || target === 'outpaint' ? 'paint' : target
    await apiFetch(`/gallery/${image.id}/use-as`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ target: slot === 2 ? `${normalizedTarget}:2` : normalizedTarget }),
    }).catch(() => undefined)
    setMode(normalizedTarget)
    if (target === 'inpaint') setPaintTool('inpaint')
    if (target === 'outpaint') setPaintTool('outpaint')
    setTab('studio')
    if (normalizedTarget === 'edit') {
      // Любой из 4 слотов (slot 1 = основа, 2..4 = референсы). Роль сбрасывается при замене.
      const index = Math.min(Math.max(slot - 1, 0), EDIT_SLOT_COUNT - 1)
      setEditSlots((current) => current.map((s, i) => (i === index ? { image: image.url, role: '', takeNote: '' } : s)))
    } else {
      if (slot === 1) setInputOne(image.url)
      if (slot === 2) setInputTwo(image.url)
      setPromptForKey(promptKeyFor(normalizedTarget, target === 'inpaint' || target === 'outpaint' ? target : paintTool), image.promptOriginal)
    }
  }

  // Назначить изображение из галереи в заранее выбранный edit-слот (кнопка «Галерея» у слота).
  function assignGalleryToEditSlot(image: GalleryImage) {
    if (pendingEditSlot === null) return
    setEditSlotImage(pendingEditSlot, image.url)
    if (pendingEditSlot >= 1) setEditSlotRole(pendingEditSlot, '')
    setPendingEditSlot(null)
    setTab('studio')
  }

  function applyLastImage(slot = 1) {
    const latest = gallery[0]
    if (!latest) return
    if (mode === 'edit') {
      const index = Math.min(Math.max(slot - 1, 0), EDIT_SLOT_COUNT - 1)
      setEditSlots((current) => current.map((s, i) => (i === index ? { image: latest.url, role: '', takeNote: '' } : s)))
      return
    }
    if (slot === 1) setInputOne(latest.url)
    if (slot === 2) setInputTwo(latest.url)
    setPrompt(latest.promptOriginal)
  }

  const nav = [
    { id: 'studio', label: copy.studio, icon: WandSparkles },
    { id: 'gallery', label: copy.gallery, icon: GalleryHorizontalEnd },
    { id: 'presets', label: copy.help, icon: Sparkles },
    { id: 'settings', label: copy.settings, icon: Settings },
  ] as Array<{ id: Tab; label: string; icon: typeof WandSparkles }>
  const openGalleryPicker = () => {
    if (galleryLocked) {
      setTab('settings')
      return
    }
    setTab('gallery')
  }
  const openGallery = () => {
    window.location.href = '/gallery'
  }
  const editBaseImage = editSlots[0].image
  const previewSource = job?.status === 'completed' && job.resultUrl ? job.resultUrl : (mode === 'edit' ? editBaseImage : actualMode === 'outpaint' ? outpaintPreview || inputOne : inputOne)
  const canUsePreviewAsInput = Boolean(job?.status === 'completed' && job.resultUrl)
  // Preview panel aspect ratio. Restored after a Phase 12.1 cleanup removed these
  // (and the previewImageSize state) while a usage remained at the preview-panel
  // style below — that caused a runtime ReferenceError. Safe definition uses the
  // generation width/height (always valid); no generation business logic changed.
  const previewAspectWidth = width
  const previewAspectHeight = height
  const mobileEditSlots = (
    <div className="mobile-preview-inputs edit-mobile">
      <EditCards
        editSlots={editSlots}
        onUpload={(i) => upload((url) => setEditSlotImage(i, url))}
        onPickGallery={(i) => { setPendingEditSlot(i); openGalleryPicker() }}
        onClear={clearEditSlot}
        onRole={setEditSlotRole}
        onTakeNote={setEditSlotTakeNote}
      />
    </div>
  )
  const mobilePreviewInputs = mode === 'text_to_image' ? null : mode === 'edit' ? mobileEditSlots : (
    <div className={`mobile-preview-inputs ${mode === 'faceswap' || mode === 'try_on' || mode === 'texture_transfer' ? 'two' : ''} ${mode === 'paint' ? 'paint-mobile-tools' : ''}`}>
      <div className="mobile-input-row primary">
        <button className="mobile-thumb" onClick={() => upload(setInputOne)}>{inputOne ? <img src={inputOne} /> : <><ImageIcon size={22} /><span>Добавить</span></>}</button>
        <div className="mobile-input-actions">
          {mode === 'paint' && <div className="mobile-paint-actions"><button onClick={() => { setPaintTool('sketch'); setPromptForKey('paint:sketch', workflowPresets.find((item) => item.id === 'sketch-01')?.prompt || ''); setPaintEditor('sketch') }}><strong>Эскиз</strong><span>Рисование на чистом холсте</span></button><button onClick={() => { setPaintTool('inpaint'); setPromptForKey('paint:inpaint', workflowPresets.find((item) => item.id === 'mask-01')?.prompt || ''); setPaintEditor('mask') }}><strong>Маска</strong><span>Закрасить область внутри изображения</span></button><button onClick={() => { setPaintTool('outpaint'); setPromptForKey('paint:outpaint', workflowPresets.find((item) => item.id === 'outpaint-01')?.prompt || ''); setPaintEditor('mask') }}><strong>Расширение</strong><span>Дорисовать пространство вокруг</span></button></div>}
          <button onClick={() => upload(setInputOne)}>Файл</button>
          <button onClick={openGallery}>Галерея</button>
          <button className="take-this-button" disabled={!canUsePreviewAsInput && gallery.length === 0} onClick={() => job?.resultUrl ? setInputOne(job.resultUrl) : applyLastImage(1)}><span>Взять это</span><span>↓</span></button>
        </div>
      </div>
      {(mode === 'faceswap' || mode === 'try_on' || mode === 'texture_transfer') && <div className="mobile-input-row secondary">
        <button className="mobile-thumb" onClick={() => upload(setInputTwo)}>{inputTwo ? <img src={inputTwo} /> : <><ImageIcon size={22} /><span>{mode === 'faceswap' ? 'Лицо' : 'Добавить'}</span></>}</button>
        <div className="mobile-input-actions">
          <button onClick={() => upload(setInputTwo)}>Файл</button>
          <button onClick={openGallery}>Галерея</button>
          {mode === 'faceswap' ? <span className="mobile-face-inline-hint">Добавь фото лица для замены</span> : <button disabled={gallery.length === 0} onClick={() => applyLastImage(2)}>Взять это</button>}
        </div>
      </div>}
    </div>
  )

  if (profileRoute) {
    return (
      <div className="iv3">
        <div className="app-shell">
          {isDiagMode() && <DiagPanel />}
          <AuthV2Modal open={authModalOpen} onClose={() => setAuthModalOpen(false)} />
          <TopBarV3
            active="profile"
            authed={isAuthedV2}
            avatarUrl={isAuthedV2 ? accountInfo(authMe).avatarUrl : null}
            userLabel={isAuthedV2 ? accountInfo(authMe).userLabel : null}
            initials={isAuthedV2 ? accountInfo(authMe).initials : null}
            dailyTokensRemaining={isAuthedV2 ? authMe?.account?.daily_tokens_remaining : null}
            dailyTokensLimit={isAuthedV2 ? (authMe?.account?.daily_tokens_limit ?? authMe?.account?.daily_tokens) : null}
            tokenBalance={isAuthedV2 ? authMe?.account?.token_balance : null}
            onOpenGallery={() => { window.location.href = '/gallery' }}
            onOpenHelp={() => { window.location.href = '/' }}
          />
          <main className="new-sub-main">
            <SettingsView copy={copy} lang={lang} onLanguageChange={changeLanguage} tariffs={tariffs} bootstrap={bootstrap} setBootstrap={setBootstrap} openAdmin={openAdminPage} openGallery={() => { window.location.href = '/gallery' }} provider={provider} setProvider={setProvider} width={width} setWidth={setWidth} height={height} setHeight={setHeight} steps={steps} setSteps={setSteps} setCfg={setCfg} isAuthedV2={isAuthedV2} openAuthModal={() => setAuthModalOpen(true)} authMe={authMe} />
          </main>
        </div>
      </div>
    )
  }

  if (staticFeedRoute) {
    return <div className="app-loading">Загружаем ленту...</div>
  }

  if (newUiRoute || paintRoute) {
    return (
      <Suspense fallback={<div className="iv3"><div className="app-shell"><main className="new-sub-main"><div className="preview-empty">Загружаем интерфейс...</div></main></div></div>}>
        <NewStudio />
      </Suspense>
    )
  }

  if (adminRoute) {
    const backToNewStudio = () => { window.location.href = '/' }
    return (
      <div className="app-shell admin-route-shell">
        {isDiagMode() && <DiagPanel />}
        <AuthV2Modal open={authModalOpen} onClose={() => setAuthModalOpen(false)} />
        <main className="workspace admin-workspace">
          {authV2Status === 'loading' ? (
            <section className="admin-page admin-access-page">
              <div className="view-actions in-panel"><button className="secondary" onClick={backToNewStudio}><WandSparkles size={16} />{copy.backToStudio}</button></div>
              <div className="admin-head"><div><h2>{copy.admin}</h2><p>Проверяем trusted admin-сессию.</p></div><strong>loading</strong></div>
            </section>
          ) : isAdmin ? (
            <AdminView copy={copy} admin={admin} setAdmin={setAdmin} tariffs={tariffs} setTariffs={setTariffs} backToStudio={backToNewStudio} provider={provider} />
          ) : (
            <section className="admin-page admin-access-page">
              <div className="view-actions in-panel"><button className="secondary" onClick={backToNewStudio}><WandSparkles size={16} />{copy.backToStudio}</button></div>
              <div className="admin-head"><div><h2>{copy.admin}</h2><p>Админка вынесена на отдельную страницу и доступна только для trusted admin-сессии.</p></div><strong>403</strong></div>
              <div className="admin-note">
                <strong>Доступ закрыт</strong>
                <p>Войдите под аккаунтом администратора. Кнопки в интерфейсе скрываются для обычных пользователей, а все admin API дополнительно проверяются на backend.</p>
                <button className="generate small-action" onClick={() => setAuthModalOpen(true)}><Lock size={16} />Войти</button>
              </div>
            </section>
          )}
        </main>
      </div>
    )
  }

  return (
    <div className="app-shell">
      {isDiagMode() && <DiagPanel />}
      <AuthV2Modal open={authModalOpen} onClose={() => setAuthModalOpen(false)} />
      <aside className="rail">
        <div className="brand"><Sparkles size={22} /><span>{copy.title}</span></div>
        <div className="mode-list">
          {modes.map((item) => (
            <button aria-label={item[lang]} className={item.id === mode ? 'mode active' : 'mode'} key={item.id} onClick={() => selectMode(item.id)}>
              {lang === 'ru' ? item.shortRu : item.shortEn}
            </button>
          ))}
        </div>
        {isAdmin && <button className="admin-link" onClick={openAdminPage}>{copy.admin}</button>}
      </aside>

      <main className="workspace">
        <header className="topbar">
          <div>
            <h1>{activeMode[lang]}</h1>
            <p>{copy.hint}</p>
          </div>
          <div className="top-actions">
            <button className="icon-button lockable" onClick={openGallery} title={copy.gallery}><GalleryHorizontalEnd size={18} />{copy.gallery}</button>
            <button
              className="icon-button feed-link"
              onClick={() => { window.location.href = '/feed' }}
              title={copy.feed}
            ><Sparkles size={18} />{copy.feed}</button>
            <button className="icon-button" onClick={() => setTab('presets')} title={copy.help}><Sparkles size={18} />{copy.help}</button>
            <button className="icon-button" onClick={() => setTab('settings')} title={copy.settings}><Settings size={18} />{copy.settings}</button>
            {isAdmin && <button className="icon-button" onClick={openAdminPage} title={copy.admin}><Shield size={18} />{copy.admin}</button>}
          </div>
        </header>

        <section className="mobile-modes">
          {modes.map((item) => <button aria-label={item[lang]} key={item.id} className={item.id === mode ? 'chip active' : 'chip'} onClick={() => selectMode(item.id)}>{lang === 'ru' ? item.shortRu : item.shortEn}</button>)}
        </section>

        {tab === 'studio' && (
          <div className="studio-grid">
            <section className="control-panel">
              {mode === 'edit' ? (
                <EditCards
                  editSlots={editSlots}
                  onUpload={(i) => upload((url) => setEditSlotImage(i, url))}
                  onPickGallery={(i) => { setPendingEditSlot(i); openGalleryPicker() }}
                  onClear={clearEditSlot}
                  onRole={setEditSlotRole}
                  onTakeNote={setEditSlotTakeNote}
                />
              ) : (
              <ModeWorkspace
                mode={mode}
                paintTool={paintTool}
                setPaintTool={setPaintTool}
                copy={copy}
                inputOne={inputOne}
                inputTwo={inputTwo}
                setInputOne={setInputOne}
                setInputTwo={setInputTwo}
                upload={upload}
                paintLines={paintLines}
                setPaintLines={setPaintLines}
                maskLines={maskLines}
                setMaskLines={setMaskLines}
                tool={tool}
                setTool={setTool}
                brushSize={brushSize}
                setBrushSize={setBrushSize}
                paintColor={paintColor}
                setPaintColor={setPaintColor}
                layerOpacity={layerOpacity}
                setLayerOpacity={setLayerOpacity}
                outpaint={outpaint}
                setOutpaint={setOutpaint}
                applyLastImage={applyLastImage}
                drawingRef={drawingRef}
                canvasRef={canvasRef}
                setPrompt={setPrompt}
                setPromptForKey={setPromptForKey}
                setPaintEditor={setPaintEditor}
              />
              )}
              <div className="control-stack">
              {mode === 'edit' && (
                <div className="size-section">
                  <span className="size-section-label">{copy.size}</span>
                  <div className="size-source">
                    <button className={sizeSource === 'image1' ? 'active' : ''} onClick={() => setSizeSource('image1')}>{copy.image1Size}</button>
                    <button className={sizeSource === 'custom' ? 'active' : ''} onClick={() => setSizeSource('custom')}>{copy.customSize}</button>
                  </div>
                  {sizeSource === 'custom' && <label className="size-control"><select value={`${width}x${height}`} onChange={(e) => { const [nextWidth, nextHeight] = e.target.value.split('x').map(Number); setWidth(nextWidth); setHeight(nextHeight) }}>{resolutionPresets.map((item) => <option key={item.label} value={`${item.width}x${item.height}`}>{item.label}</option>)}</select></label>}
                </div>
              )}
              {mode !== 'edit' && mode !== 'image_to_image' && mode !== 'faceswap' && <label className="size-control">{copy.size}<select value={`${width}x${height}`} onChange={(e) => { const [nextWidth, nextHeight] = e.target.value.split('x').map(Number); setWidth(nextWidth); setHeight(nextHeight) }}>{resolutionPresets.map((item) => <option key={item.label} value={`${item.width}x${item.height}`}>{item.label}</option>)}</select></label>}
              {mode === 'image_to_image' && <label className="strength-control">{copy.strength}<input type="range" min="0" max="1" step="0.01" value={strength} onChange={(e) => setStrength(Number(e.target.value))} /><span>{Math.round(strength * 100)}%</span></label>}
              {mode === 'faceswap' && <div className="face-controls"><label className="strength-control">{copy.faceStrength}<input type="range" min="0.2" max="1" step="0.01" value={strength} onChange={(e) => setStrength(Number(e.target.value))} /><span>{Math.round(strength * 100)}%</span></label></div>}
              <button className="secondary instruction-button" onClick={() => setInstructionOpen(true)}>Инструкция</button>
              {isAuthedV2
                ? <button className="generate" disabled={!canGenerate || isSubmitting || jobIsActive(job?.status)} onClick={generate}>{(isSubmitting || jobIsActive(job?.status)) ? <span className="gen-spinner" /> : <Play size={18} />}{isSubmitting ? 'Отправляем…' : jobIsActive(job?.status) ? 'Генерация…' : copy.generate}</button>
                : <button className="generate generate-locked" title="Войдите, чтобы генерировать" onClick={() => setAuthModalOpen(true)}><Lock size={16} /><span className="lock-cta-full">Войдите, чтобы генерировать</span><span className="lock-cta-short">Войти</span></button>}
              {isAuthedV2 && editBlockReason && <div className="notice edit-block-reason">{editBlockReason}</div>}
              {notice && <div className="notice">{notice}</div>}
              </div>
            </section>
            {mobilePreviewInputs}
            <section className={`preview-panel ${!job && !previewSource ? 'empty-preview' : 'has-preview'}`} style={{ aspectRatio: `${previewAspectWidth} / ${previewAspectHeight}` }}>
              {job && ['queued', 'running', 'uploading', 'sent_to_comfyui'].includes(job.status) ? <JobCard job={job} copy={copy} cancelJob={cancelJob} sendImage={sendImage} mode={mode} beforeImage={mode === 'edit' ? editBaseImage : actualMode === 'outpaint' ? outpaintPreview || inputOne : inputOne} loadingBackdrop={(actualMode === 'outpaint' ? outpaintPreview || inputOne : mode === 'edit' ? editBaseImage : undefined) || gallery[0]?.url} /> : job?.status === 'completed' && job.resultUrl ? <JobCard job={job} copy={copy} cancelJob={cancelJob} sendImage={sendImage} mode={mode} beforeImage={mode === 'edit' ? editBaseImage : actualMode === 'outpaint' ? outpaintPreview || inputOne : inputOne} /> : previewSource && mode !== 'text_to_image' ? <div className={`result-frame mobile-source-preview ${actualMode === 'outpaint' ? 'outpaint-preview-frame' : ''}`}><img src={previewSource} />{mode === 'edit' && !job && <span className="preview-caption">Предпросмотр основы</span>}</div> : <div className="preview-empty">{mode !== 'text_to_image' ? <><span className="preview-empty-hint">{mode === 'edit' ? 'Добавьте основу для редактирования' : 'Добавьте изображение'}</span><button className="preview-add-button" onClick={() => upload((url) => mode === 'edit' ? setEditSlotImage(0, url) : setInputOne(url))}><Upload size={22} />{mode === 'edit' ? 'Выбрать изображение' : 'Добавить изображение'}</button></> : <><ImageIcon size={64} /><span>{copy.generatedPlaceholder}</span></>}</div>}
            </section>
            <section className="prompt-dock">
              {mode === 'edit' ? (
                <EditPromptDock
                  prompt={prompt}
                  setPrompt={setPrompt}
                  onTemplates={() => setEditTemplatesOpen(true)}
                  onAdvanced={() => setEditAdvancedOpen(true)}
                />
              ) : (
                <>
                  <PromptBlock
                    copy={copy}
                    prompt={prompt}
                    setPrompt={setPrompt}
                    negativePrompt={negativePrompt}
                    setNegativePrompt={setNegativePrompt}
                    translatePrompt={translatePrompt}
                    onDiscover={() => setDiscoverOpen(!discoverOpen)}
                    randomPrompt={randomPrompt}
                  />
                  {discoverOpen && <DiscoverPanel lang={lang} mode={mode} presets={visiblePresets} applyPreset={applyPreset} addUserPreset={addUserPreset} currentPrompt={prompt} onClose={() => setDiscoverOpen(false)} />}
                </>
              )}
              <a className="creator-credit" href="https://vk.com/spikeal.site" target="_blank" rel="noreferrer">ИЗО АСА — ИИ генератор реализовал Аликин АС.</a>
            </section>
          </div>
        )}

        {tab === 'gallery' && !galleryLocked && <GalleryView copy={copy} images={gallery} quota={galleryQuota} selected={selected} setSelected={setSelected} handleUseImageAs={useImageAs} refreshGallery={fetchGallery} clearSelected={() => setSelected(undefined)} backToStudio={() => setTab('studio')} view={galleryView} setView={setGalleryView} sendImage={sendImage} pickSlot={pendingEditSlot} onPickForSlot={assignGalleryToEditSlot} cancelPick={() => { setPendingEditSlot(null); setTab('studio') }} />}
        {tab === 'gallery' && galleryLocked && <SettingsView copy={copy} lang={lang} onLanguageChange={changeLanguage} tariffs={tariffs} bootstrap={bootstrap} setBootstrap={setBootstrap} openAdmin={openAdminPage} openGallery={openGallery} provider={provider} setProvider={setProvider} width={width} setWidth={setWidth} height={height} setHeight={setHeight} steps={steps} setSteps={setSteps} setCfg={setCfg} isAuthedV2={isAuthedV2} openAuthModal={() => setAuthModalOpen(true)} authMe={authMe} />}
        {tab === 'presets' && <HelpView lang={lang} applyPreset={applyPreset} copy={copy} backToStudio={() => setTab('studio')} />}
        {tab === 'settings' && <SettingsView copy={copy} lang={lang} onLanguageChange={changeLanguage} tariffs={tariffs} bootstrap={bootstrap} setBootstrap={setBootstrap} openAdmin={openAdminPage} openGallery={openGallery} provider={provider} setProvider={setProvider} width={width} setWidth={setWidth} height={height} setHeight={setHeight} steps={steps} setSteps={setSteps} setCfg={setCfg} isAuthedV2={isAuthedV2} openAuthModal={() => setAuthModalOpen(true)} authMe={authMe} />}

        {instructionOpen && <InstructionModal mode={mode} paintTool={paintTool} onClose={() => setInstructionOpen(false)} />}
        {editTemplatesOpen && <EditTemplatesModal templates={EDIT_TEMPLATES} applyTemplate={applyEditTemplate} onClose={() => setEditTemplatesOpen(false)} />}
        {editAdvancedOpen && (
          <EditAdvancedModal
            editSlots={editSlots}
            onTakeNote={setEditSlotTakeNote}
            composedPrompt={editComposer.composedPrompt}
            manualMode={editManualMode}
            manualPrompt={editManualPrompt}
            onEnterManual={() => { setEditManualPrompt(editComposer.composedPrompt); setEditManualMode(true) }}
            onBackToAuto={() => setEditManualMode(false)}
            setManualPrompt={setEditManualPrompt}
            onClose={() => setEditAdvancedOpen(false)}
          />
        )}
        {paintEditor && (
          <PaintEditorModal
            editor={paintEditor}
            paintTool={paintTool}
            setPaintTool={setPaintTool}
            onClose={() => setPaintEditor(null)}
            copy={copy}
            inputOne={inputOne}
            setInputOne={setInputOne}
            upload={upload}
            paintLines={paintLines}
            setPaintLines={setPaintLines}
            maskLines={maskLines}
            setMaskLines={setMaskLines}
            tool={tool}
            setTool={setTool}
            brushSize={brushSize}
            setBrushSize={setBrushSize}
            paintColor={paintColor}
            setPaintColor={setPaintColor}
            layerOpacity={layerOpacity}
            setLayerOpacity={setLayerOpacity}
            outpaint={outpaint}
            setOutpaint={setOutpaint}
            drawingRef={drawingRef}
            canvasRef={canvasRef}
            setPrompt={setPrompt}
            setPromptForKey={setPromptForKey}
            setCanvasSnapshot={setCanvasSnapshot}
            setOutpaintPreview={setOutpaintPreview}
            targetWidth={width}
            targetHeight={height}
          />
        )}

        {!galleryLocked && <section className="bottom-strip">
          {gallery.slice(0, 6).map((image) => <button key={image.id} onClick={() => { setSelected(image); openGalleryPicker() }}><img src={image.thumbnailUrl} alt="" /></button>)}
        </section>}
      </main>

      <nav className="bottom-nav" style={{ gridTemplateColumns: `repeat(${nav.length + 1}, 1fr)` }}>
        {nav.map(({ id, label, icon: Icon }) => (
          <Fragment key={id}>
            <button className={tab === id ? 'active' : ''} onClick={() => id === 'gallery' ? openGallery() : setTab(id)}><span className="nav-icon-wrap"><Icon size={19} />{id === 'gallery' && galleryLocked && <Lock className="lock-badge" size={10} />}</span><span>{label}</span></button>
            {id === 'gallery' && (
              <label className="mobile-size-nav">
                <span className="size-value"><b>{width}</b><b>× {height}</b></span>
                <span>Размер</span>
                <select value={`${width}x${height}`} onChange={(e) => { const [nextWidth, nextHeight] = e.target.value.split('x').map(Number); setWidth(nextWidth); setHeight(nextHeight) }}>{resolutionPresets.map((item) => <option key={item.label} value={`${item.width}x${item.height}`}>{item.label}</option>)}</select>
              </label>
            )}
          </Fragment>
        ))}
      </nav>
    </div>
  )
}

type ModeWorkspaceProps = {
  mode: Mode
  paintTool: PaintTool
  setPaintTool: Dispatch<SetStateAction<PaintTool>>
  copy: Copy
  inputOne?: string
  inputTwo?: string
  setInputOne: (value?: string) => void
  setInputTwo: (value?: string) => void
  upload: (setter: (url: string) => void) => void
  paintLines: PaintLine[]
  setPaintLines: Dispatch<SetStateAction<PaintLine[]>>
  maskLines: PaintLine[]
  setMaskLines: Dispatch<SetStateAction<PaintLine[]>>
  tool: 'brush' | 'eraser'
  setTool: (tool: 'brush' | 'eraser') => void
  brushSize: number
  setBrushSize: (value: number) => void
  paintColor: string
  setPaintColor: (value: string) => void
  layerOpacity: number
  setLayerOpacity: (value: number) => void
  outpaint: { left: number; right: number; top: number; bottom: number; scaleDown: boolean }
  setOutpaint: (value: { left: number; right: number; top: number; bottom: number; scaleDown: boolean }) => void
  applyLastImage: (slot?: number) => void
  drawingRef: MutableRefObject<boolean>
  canvasRef: MutableRefObject<KonvaStage | null>
  setPrompt: (value: string) => void
  setPromptForKey: (key: PromptKey, value: string) => void
  setPaintEditor: (value: PaintEditor) => void
}

function ModeWorkspace(props: ModeWorkspaceProps) {
  const { mode, paintTool, setPaintTool, copy, inputOne, inputTwo, setInputOne, setInputTwo, upload, applyLastImage, setPromptForKey, setPaintEditor } = props
  if (mode === 'paint') {
    const sketchPrompt = workflowPresets.find((item) => item.id === 'sketch-01')?.prompt || ''
    const maskPrompt = workflowPresets.find((item) => item.id === 'mask-01')?.prompt || ''
    const outpaintPrompt = workflowPresets.find((item) => item.id === 'outpaint-01')?.prompt || ''
    function openSketch() {
      setPaintTool('sketch')
      setPromptForKey('paint:sketch', sketchPrompt)
      setPaintEditor('sketch')
    }
    function openMask() {
      setPaintTool('inpaint')
      setPromptForKey('paint:inpaint', maskPrompt)
      setPaintEditor('mask')
    }
    function openOutpaint() {
      setPaintTool('outpaint')
      setPromptForKey('paint:outpaint', outpaintPrompt)
      setPaintEditor('mask')
    }
    return <div className="paint-compact"><ImageBox title="ИЗО" image={inputOne} onUpload={() => upload(setInputOne)} onClear={() => setInputOne(undefined)} onUseLast={() => applyLastImage(1)} copy={copy} /><div className="paint-choice-stack"><button className={paintTool === 'sketch' ? 'paint-choice active' : 'paint-choice'} onClick={openSketch}><strong>Эскиз</strong><span>Нарисовать объект на холсте</span></button><button className={paintTool === 'inpaint' ? 'paint-choice active' : 'paint-choice'} onClick={openMask}><strong>Маска</strong><span>Закрасить область внутри изображения</span></button><button className={paintTool === 'outpaint' ? 'paint-choice active' : 'paint-choice'} onClick={openOutpaint}><strong>Расширение</strong><span>Добавить пространство вокруг изображения</span></button></div></div>
  }

  if (mode === 'faceswap') {
    return <div className="image-inputs"><ImageBox title={copy.targetImage} image={inputOne} onUpload={() => upload(setInputOne)} onClear={() => setInputOne(undefined)} onUseLast={() => applyLastImage(1)} copy={copy} /><ImageBox title={copy.sourceFace} image={inputTwo} onUpload={() => upload(setInputTwo)} onClear={() => setInputTwo(undefined)} onUseLast={() => applyLastImage(2)} copy={copy} /></div>
  }

  if (mode === 'try_on') {
    return <div className="image-inputs"><ImageBox title="Человек" image={inputOne} onUpload={() => upload(setInputOne)} onClear={() => setInputOne(undefined)} onUseLast={() => applyLastImage(1)} copy={copy} /><ImageBox title="Одежда" image={inputTwo} onUpload={() => upload(setInputTwo)} onClear={() => setInputTwo(undefined)} onUseLast={() => applyLastImage(2)} copy={copy} /></div>
  }

  if (mode === 'texture_transfer') {
    return <div className="image-inputs"><ImageBox title="Цель" image={inputOne} onUpload={() => upload(setInputOne)} onClear={() => setInputOne(undefined)} onUseLast={() => applyLastImage(1)} copy={copy} /><ImageBox title={copy.referenceImage} image={inputTwo} onUpload={() => upload(setInputTwo)} onClear={() => setInputTwo(undefined)} onUseLast={() => applyLastImage(2)} copy={copy} /></div>
  }

  if (mode === 'remove_background') {
    return <div className="image-inputs one"><ImageBox title={copy.removeBg} image={inputOne} onUpload={() => upload(setInputOne)} onClear={() => setInputOne(undefined)} onUseLast={() => applyLastImage(1)} copy={copy} /></div>
  }


  if (mode === 'image_to_image') {
    return <div className="image-inputs one"><ImageBox title="Изображение 1" image={inputOne} onUpload={() => upload(setInputOne)} onClear={() => setInputOne(undefined)} onUseLast={() => applyLastImage(1)} copy={copy} /></div>
  }

  return <div className="empty-state"><Sparkles size={34} /><span>{copy.before}</span></div>
}

// Одна карточка изображения. Пустая → «+ фото» с мини-меню (Загрузить / Галерея).
// Основа → кнопка «Выбрать». Референс → select роли под карточкой.
function EditCard({ index, slot, onUpload, onPickGallery, onClear, onRole, onTakeNote }: {
  index: number
  slot: EditSlot
  onUpload: (index: number) => void
  onPickGallery: (index: number) => void
  onClear: (index: number) => void
  onRole: (index: number, role: EditReferenceRole | '') => void
  onTakeNote: (index: number, value: string) => void
}) {
  const [menuOpen, setMenuOpen] = useState(false)
  const isBase = index === 0
  const needsRole = !isBase && Boolean(slot.image) && !slot.role
  const pick = (fn: () => void) => { fn(); setMenuOpen(false) }
  return (
    <div className={`edit-card ${isBase ? 'base' : 'ref'} ${needsRole ? 'needs-role' : ''}`}>
      <div className="edit-card-head"><span>{isBase ? 'Основа' : `Референс ${index}`}</span>{isBase && <small>обязательно</small>}</div>
      <div className="edit-card-box">
        {slot.image
          ? <><img src={slot.image} alt="" /><button className="card-clear" aria-label="Удалить" onClick={() => onClear(index)}><X size={15} /></button></>
          : <button className="card-add" onClick={() => setMenuOpen((v) => !v)}><Plus size={26} /><span>+ фото</span></button>}
        {menuOpen && (
          <div className="card-menu" onMouseLeave={() => setMenuOpen(false)}>
            <button onClick={() => pick(() => onUpload(index))}><Upload size={14} />Загрузить</button>
            <button onClick={() => pick(() => onPickGallery(index))}><GalleryHorizontalEnd size={14} />Галерея</button>
          </div>
        )}
      </div>
      <div className="edit-card-foot">
        {isBase ? (
          <button className="card-choose" onClick={() => setMenuOpen((v) => !v)}>Выбрать</button>
        ) : slot.image ? (
          <select className={`card-role ${needsRole ? 'needs-role' : ''}`} value={slot.role} onChange={(e) => onRole(index, e.target.value as EditReferenceRole | '')}>
            <option value="">Выберите роль…</option>
            {EDIT_SELECTABLE_REFERENCE_ROLES.map((role) => <option key={role} value={role}>{EDIT_REFERENCE_ROLE_LABELS[role]}</option>)}
            {EDIT_DISABLED_REFERENCE_ROLES.map((role) => <option key={role} value={role} disabled>🔒 {EDIT_REFERENCE_ROLE_LABELS[role]} · скоро</option>)}
          </select>
        ) : (
          <div className="card-role-hint">роль после фото</div>
        )}
      </div>
      {!isBase && slot.image && slot.role === 'other' && (
        <input
          className={`card-custom-note ${!slot.takeNote.trim() ? 'needs-role' : ''}`}
          value={slot.takeNote}
          placeholder="Что взять из референса?"
          onChange={(e) => onTakeNote(index, e.target.value)}
        />
      )}
      {!isBase && slot.image && slot.role === 'object' && (
        <div className="card-advisory">Лучше используйте референс, где нужный предмет виден отдельно. Если предметов несколько, обрежьте изображение до нужного предмета.</div>
      )}
      {!isBase && slot.image && slot.role === 'pose' && (
        <div className="card-advisory disabled"><Lock size={12} />Смена позы временно закрыта. Выберите другую роль.</div>
      )}
    </div>
  )
}

// Сетка 4 карточек (основа + 3 референса). Используется и на desktop, и на mobile.
function EditCards({ editSlots, onUpload, onPickGallery, onClear, onRole, onTakeNote }: {
  editSlots: EditSlot[]
  onUpload: (index: number) => void
  onPickGallery: (index: number) => void
  onClear: (index: number) => void
  onRole: (index: number, role: EditReferenceRole | '') => void
  onTakeNote: (index: number, value: string) => void
}) {
  return <div className="edit-grid">
    {editSlots.map((slot, i) => (
      <EditCard key={i} index={i} slot={slot} onUpload={onUpload} onPickGallery={onPickGallery} onClear={onClear} onRole={onRole} onTakeNote={onTakeNote} />
    ))}
  </div>
}

async function createImageMask(inputImage: string | undefined, lines: PaintLine[], stageSize: { width: number; height: number }) {
  if (!inputImage) return undefined
  const image = await new Promise<HTMLImageElement>((resolve, reject) => {
    const img = new Image()
    img.onload = () => resolve(img)
    img.onerror = reject
    img.src = inputImage
  })
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
  const mapPoint = (x: number, y: number) => [
    Math.max(0, Math.min(canvas.width, (x - offsetX) / scale)),
    Math.max(0, Math.min(canvas.height, (y - offsetY) / scale)),
  ]

  for (const line of lines) {
    ctx.save()
    ctx.strokeStyle = line.tool === 'eraser' ? '#000' : '#fff'
    ctx.fillStyle = line.tool === 'eraser' ? '#000' : '#fff'
    ctx.lineCap = 'round'
    ctx.lineJoin = 'round'
    ctx.lineWidth = Math.max(1, (line.strokeWidth || 10) / scale)
    if (line.kind === 'rect' || line.kind === 'circle') {
      const [x1 = 0, y1 = 0, x2 = x1, y2 = y1] = line.points
      const [mx1, my1] = mapPoint(x1, y1)
      const [mx2, my2] = mapPoint(x2, y2)
      const x = Math.min(mx1, mx2)
      const y = Math.min(my1, my2)
      const w = Math.abs(mx2 - mx1)
      const h = Math.abs(my2 - my1)
      if (line.kind === 'circle') {
        ctx.beginPath()
        ctx.ellipse(x + w / 2, y + h / 2, w / 2, h / 2, 0, 0, Math.PI * 2)
        if (line.fill === false) ctx.stroke()
        else ctx.fill()
      } else {
        if (line.fill === false) ctx.strokeRect(x, y, w, h)
        else ctx.fillRect(x, y, w, h)
      }
      ctx.restore()
      continue
    }
    ctx.beginPath()
    for (let index = 0; index < line.points.length; index += 2) {
      const [x, y] = mapPoint(line.points[index] || 0, line.points[index + 1] || 0)
      if (index === 0) ctx.moveTo(x, y)
      else ctx.lineTo(x, y)
    }
    ctx.stroke()
    ctx.restore()
  }
  return canvas.toDataURL('image/png')
}

async function createOutpaintPreview(inputImage: string | undefined, padding: { left: number; right: number; top: number; bottom: number }, target: { width: number; height: number }) {
  if (!inputImage) return undefined
  const image = await new Promise<HTMLImageElement>((resolve, reject) => {
    const img = new Image()
    img.onload = () => resolve(img)
    img.onerror = reject
    img.src = inputImage
  })
  const sourceWidth = image.naturalWidth || image.width
  const sourceHeight = image.naturalHeight || image.height
  const finalWidth = Math.max(1, sourceWidth + Math.max(0, padding.left) + Math.max(0, padding.right))
  const finalHeight = Math.max(1, sourceHeight + Math.max(0, padding.top) + Math.max(0, padding.bottom))
  const canvas = document.createElement('canvas')
  canvas.width = Math.max(256, Math.round(target.width || 1024))
  canvas.height = Math.max(256, Math.round(target.height || 1024))
  const ctx = canvas.getContext('2d')
  if (!ctx) return undefined
  ctx.fillStyle = '#030303'
  ctx.fillRect(0, 0, canvas.width, canvas.height)
  ctx.fillStyle = 'rgba(236,255,47,0.08)'
  for (let x = -canvas.height; x < canvas.width; x += 24) {
    ctx.fillRect(x, 0, 10, canvas.height)
  }
  const scaleX = canvas.width / finalWidth
  const scaleY = canvas.height / finalHeight
  const x = Math.round(Math.max(0, padding.left) * scaleX)
  const y = Math.round(Math.max(0, padding.top) * scaleY)
  const w = Math.max(1, Math.round(sourceWidth * scaleX))
  const h = Math.max(1, Math.round(sourceHeight * scaleY))
  ctx.drawImage(image, x, y, w, h)
  ctx.strokeStyle = '#dfff22'
  ctx.lineWidth = Math.max(2, Math.round(Math.min(canvas.width, canvas.height) / 256))
  ctx.strokeRect(x + 1, y + 1, Math.max(1, w - 2), Math.max(1, h - 2))
  return canvas.toDataURL('image/jpeg', 0.9)
}

function PaintEditorModal(props: {
  editor: Exclude<PaintEditor, null>
  paintTool: PaintTool
  setPaintTool: Dispatch<SetStateAction<PaintTool>>
  onClose: () => void
  copy: Copy
  inputOne?: string
  setInputOne: (value?: string) => void
  upload: (setter: (url: string) => void) => void
  paintLines: PaintLine[]
  setPaintLines: Dispatch<SetStateAction<PaintLine[]>>
  maskLines: PaintLine[]
  setMaskLines: Dispatch<SetStateAction<PaintLine[]>>
  tool: 'brush' | 'eraser'
  setTool: (tool: 'brush' | 'eraser') => void
  brushSize: number
  setBrushSize: (value: number) => void
  paintColor: string
  setPaintColor: (value: string) => void
  layerOpacity: number
  setLayerOpacity: (value: number) => void
  outpaint: { left: number; right: number; top: number; bottom: number; scaleDown: boolean }
  setOutpaint: (value: { left: number; right: number; top: number; bottom: number; scaleDown: boolean }) => void
  drawingRef: MutableRefObject<boolean>
  canvasRef: MutableRefObject<KonvaStage | null>
  setPrompt: (value: string) => void
  setPromptForKey: (key: PromptKey, value: string) => void
  setCanvasSnapshot: (value?: string) => void
  setOutpaintPreview: (value?: string) => void
  targetWidth: number
  targetHeight: number
}) {
  const { editor, paintTool, setPaintTool, onClose, copy, inputOne, setInputOne, upload, paintLines, setPaintLines, maskLines, setMaskLines, tool, setTool, brushSize, setBrushSize, paintColor, setPaintColor, layerOpacity, setLayerOpacity, outpaint, setOutpaint, drawingRef, canvasRef, setPromptForKey, setCanvasSnapshot, setOutpaintPreview, targetWidth, targetHeight } = props
  const isSketch = editor === 'sketch'
  const isOutpaint = paintTool === 'outpaint'
  const activeLines = isSketch ? paintLines : maskLines
  const setActiveLines = isSketch ? setPaintLines : setMaskLines
  const strokeColor = isSketch ? paintColor : '#dfff22'
  const stageWrapRef = useRef<HTMLDivElement | null>(null)
  const [stageSize, setStageSize] = useState({ width: isSketch ? 1024 : 1220, height: 620 })
  const [canvasTarget, setCanvasTarget] = useState({ width: 1024, height: 1024 })
  const [canvasDraft, setCanvasDraft] = useState({ width: 1024, height: 1024 })
  const [drawMode, setDrawMode] = useState<'free' | 'circle' | 'rect' | 'move'>('free')
  const [fillShape, setFillShape] = useState(true)
  const moveStartRef = useRef<{ x: number; y: number } | null>(null)
  const dragRef = useRef<{ x: number; y: number; panX: number; panY: number } | null>(null)
  const [sourceSize, setSourceSize] = useState<{ width: number; height: number } | null>(null)
  const [outpaintScale, setOutpaintScale] = useState(70)
  const [outpaintPan, setOutpaintPan] = useState({ x: 50, y: 50 })
  const updateOutpaint = (key: keyof typeof outpaint, value: number | boolean) => setOutpaint({ ...outpaint, [key]: value })
  const outpaintTarget = useMemo(() => {
    const sourceWidth = Math.max(1, sourceSize?.width || targetWidth)
    const sourceHeight = Math.max(1, sourceSize?.height || targetHeight)
    const targetAspect = Math.max(0.1, targetWidth / Math.max(1, targetHeight))
    const sourceAspect = sourceWidth / sourceHeight
    const scale = Math.max(0.35, Math.min(1, outpaintScale / 100))
    if (sourceAspect > targetAspect) {
      const baseHeight = Math.max(sourceHeight, Math.ceil(sourceWidth / targetAspect))
      const finalHeight = Math.ceil(baseHeight / scale)
      const finalWidth = Math.ceil(finalHeight * targetAspect)
      return { sourceWidth, sourceHeight, extraX: Math.max(0, finalWidth - sourceWidth), extraY: Math.max(0, finalHeight - sourceHeight) }
    }
    const baseWidth = Math.max(sourceWidth, Math.ceil(sourceHeight * targetAspect))
    const finalWidth = Math.ceil(baseWidth / scale)
    const finalHeight = Math.ceil(finalWidth / targetAspect)
    return { sourceWidth, sourceHeight, extraX: Math.max(0, finalWidth - sourceWidth), extraY: Math.max(0, finalHeight - sourceHeight) }
  }, [outpaintScale, sourceSize, targetHeight, targetWidth])
  const outpaintFinalWidth = outpaintTarget.sourceWidth + outpaint.left + outpaint.right
  const outpaintFinalHeight = outpaintTarget.sourceHeight + outpaint.top + outpaint.bottom
  const outpaintHorizontalValue = outpaintTarget.extraX > 0 ? Math.round((outpaint.left / Math.max(1, outpaintTarget.extraX)) * 100) : 50
  const outpaintVerticalValue = outpaintTarget.extraY > 0 ? Math.round((outpaint.top / Math.max(1, outpaintTarget.extraY)) * 100) : 50
  const applyOutpaintPan = useCallback((x: number, y: number, target = outpaintTarget) => {
    const next = { x: Math.max(0, Math.min(100, Math.round(x))), y: Math.max(0, Math.min(100, Math.round(y))) }
    const left = Math.round(target.extraX * next.x / 100)
    const top = Math.round(target.extraY * next.y / 100)
    setOutpaintPan(next)
    setOutpaint({ left, right: target.extraX - left, top, bottom: target.extraY - top, scaleDown: true })
  }, [outpaintTarget, setOutpaint])
  const updateOutpaintAxis = (axis: 'x' | 'y', value: number) => {
    const clamped = Math.max(0, Math.min(100, value))
    if (axis === 'x') applyOutpaintPan(clamped, outpaintPan.y)
    else applyOutpaintPan(outpaintPan.x, clamped)
  }
  const updateOutpaintScale = (value: number) => setOutpaintScale(Math.max(35, Math.min(100, Math.round(value || 100))))
  const startOutpaintDrag = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!isOutpaint || !inputOne) return
    event.currentTarget.setPointerCapture(event.pointerId)
    dragRef.current = { x: event.clientX, y: event.clientY, panX: outpaintPan.x, panY: outpaintPan.y }
  }
  const moveOutpaintDrag = (event: ReactPointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current
    if (!drag) return
    const rect = event.currentTarget.getBoundingClientRect()
    const dx = ((event.clientX - drag.x) / Math.max(1, rect.width)) * 140
    const dy = ((event.clientY - drag.y) / Math.max(1, rect.height)) * 140
    applyOutpaintPan(drag.panX + dx, drag.panY + dy)
  }
  const stopOutpaintDrag = (event: ReactPointerEvent<HTMLDivElement>) => {
    dragRef.current = null
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId)
  }
  const wheelOutpaintScale = (event: ReactWheelEvent<HTMLDivElement>) => {
    event.preventDefault()
    updateOutpaintScale(outpaintScale + (event.deltaY > 0 ? -5 : 5))
  }
  useEffect(() => {
    if (!inputOne || isSketch) {
      queueMicrotask(() => setSourceSize(null))
      return
    }
    let cancelled = false
    const img = new Image()
    img.onload = () => { if (!cancelled) setSourceSize({ width: img.naturalWidth || targetWidth, height: img.naturalHeight || targetHeight }) }
    img.onerror = () => { if (!cancelled) setSourceSize(null) }
    img.src = inputOne
    return () => { cancelled = true }
  }, [inputOne, isSketch, targetHeight, targetWidth])
  useEffect(() => {
    if (!isOutpaint || !sourceSize) return
    queueMicrotask(() => applyOutpaintPan(outpaintPan.x, outpaintPan.y))
  }, [applyOutpaintPan, isOutpaint, outpaintPan.x, outpaintPan.y, sourceSize])
  useEffect(() => {
    const node = stageWrapRef.current
    if (!node) return
    const update = () => {
      const rect = node.getBoundingClientRect()
      if (isSketch) {
        const ratio = Math.max(0.2, canvasTarget.width / Math.max(1, canvasTarget.height))
        let nextWidth = Math.max(1, Math.floor(rect.width))
        let nextHeight = Math.max(1, Math.floor(nextWidth / ratio))
        if (nextHeight > rect.height) {
          nextHeight = Math.max(1, Math.floor(rect.height))
          nextWidth = Math.max(1, Math.floor(nextHeight * ratio))
        }
        setStageSize({ width: nextWidth, height: nextHeight })
        return
      }
      setStageSize({ width: Math.max(1, Math.floor(rect.width)), height: Math.max(1, Math.floor(rect.height)) })
    }
    update()
    const observer = new ResizeObserver(update)
    observer.observe(node)
    return () => observer.disconnect()
  }, [canvasTarget.height, canvasTarget.width, isSketch])
  const applyCanvasTarget = () => {
    setCanvasTarget({
      width: Math.max(256, Math.min(2048, Math.round(canvasDraft.width || 1024))),
      height: Math.max(256, Math.min(2048, Math.round(canvasDraft.height || 1024))),
    })
  }
  const startLine = (stage: KonvaStage | null) => {
    drawingRef.current = true
    const pos = stage?.getPointerPosition()
    if (isSketch && drawMode === 'move') {
      moveStartRef.current = { x: pos?.x || 0, y: pos?.y || 0 }
      return
    }
    const point = [pos?.x || 0, pos?.y || 0]
    const kind = isSketch && (drawMode === 'circle' || drawMode === 'rect') ? drawMode : 'line'
    setActiveLines((lines) => lines.concat({ tool, kind, fill: fillShape, color: strokeColor, strokeWidth: brushSize, points: point.concat(point) }))
  }
  const extendLine = (stage: KonvaStage | null) => {
    if (!drawingRef.current) return
    const point = stage?.getPointerPosition()
    if (isSketch && drawMode === 'move') {
      const previous = moveStartRef.current
      if (!previous) return
      const next = { x: point?.x || 0, y: point?.y || 0 }
      const dx = next.x - previous.x
      const dy = next.y - previous.y
      moveStartRef.current = next
      setActiveLines((lines) => {
        const last = lines[lines.length - 1]
        if (!last) return lines
        const shifted = last.points.map((value, index) => value + (index % 2 === 0 ? dx : dy))
        return lines.slice(0, -1).concat({ ...last, points: shifted })
      })
      return
    }
    setActiveLines((lines) => {
      const last = lines[lines.length - 1]
      if (!last) return lines
      const nextPoint = [point?.x || 0, point?.y || 0]
      const points = last.kind && last.kind !== 'line' ? last.points.slice(0, 2).concat(nextPoint) : last.points.concat(nextPoint)
      return lines.slice(0, -1).concat({ ...last, points })
    })
  }
  const stopLine = () => { drawingRef.current = false; moveStartRef.current = null }
  const applyEditor = async () => {
    if (isSketch) {
      const dataUrl = canvasRef.current?.toDataURL({ pixelRatio: 1 })
      setCanvasSnapshot(dataUrl)
      if (dataUrl) setInputOne(dataUrl)
      setPaintTool('sketch')
      setPromptForKey('paint:sketch', workflowPresets.find((item) => item.id === 'sketch-01')?.prompt || '')
    } else if (paintTool === 'outpaint') {
      setCanvasSnapshot(undefined)
      setOutpaintPreview(await createOutpaintPreview(inputOne, outpaint, { width: targetWidth, height: targetHeight }))
      setPromptForKey('paint:outpaint', workflowPresets.find((item) => item.id === 'outpaint-01')?.prompt || '')
    } else {
      setCanvasSnapshot(await createImageMask(inputOne, activeLines, stageSize))
      setPromptForKey('paint:inpaint', workflowPresets.find((item) => item.id === 'mask-01')?.prompt || '')
    }
    onClose()
  }
  const renderPaintItem = (line: PaintLine, i: number) => {
    const color = line.tool === 'eraser' ? (isSketch ? '#fff' : '#000') : (line.color || strokeColor)
    const width = line.strokeWidth || brushSize
    if (line.kind === 'rect' || line.kind === 'circle') {
      const [x1 = 0, y1 = 0, x2 = x1, y2 = y1] = line.points
      const x = Math.min(x1, x2)
      const y = Math.min(y1, y2)
      const w = Math.abs(x2 - x1)
      const h = Math.abs(y2 - y1)
      if (line.kind === 'circle') {
        return <Circle key={i} x={x + w / 2} y={y + h / 2} radius={Math.max(w, h) / 2} stroke={color} strokeWidth={width} fill={line.fill ? color : undefined} opacity={line.tool === 'eraser' ? 1 : 0.85} />
      }
      return <Rect key={i} x={x} y={y} width={w} height={h} stroke={color} strokeWidth={width} fill={line.fill ? color : undefined} opacity={line.tool === 'eraser' ? 1 : 0.85} />
    }
    return <Line key={i} points={line.points} stroke={color} strokeWidth={line.tool === 'eraser' ? width * 2 : width} tension={0.5} lineCap="round" lineJoin="round" opacity={isSketch ? 1 : 0.75} />
  }
  const moveLastItem = () => {
    setTool('brush')
    setDrawMode('move')
    setActiveLines((lines) => {
      const last = lines[lines.length - 1]
      if (!last) return lines
      const shifted = last.points.map((value, index) => value + (index % 2 === 0 ? 18 : 10))
      return lines.slice(0, -1).concat({ ...last, points: shifted })
    })
  }
  if (!isSketch && isOutpaint) {
    return <div className="paint-editor-backdrop"><section className="paint-editor mask-editor outpaint-editor">
      <div className="paint-editor-top outpaint-top">
        <strong>Расширение изображения</strong>
        <span>{targetWidth} × {targetHeight}</span>
        <button className="secondary" onClick={() => upload(setInputOne)}>Загрузить другое</button>
        <span className="outpaint-info" title="Уменьшите или сдвиньте исходник внутри рамки. Пустые области будут дорисованы моделью.">?</span>
        <button className="save-sketch" onClick={applyEditor}>Применить</button>
        <button className="editor-close" onClick={onClose} aria-label="Закрыть"><X size={18} /></button>
      </div>
      <div className="mask-body outpaint-body">
        {inputOne ? <div className="outpaint-workbench">
          <div className="outpaint-frame" onPointerDown={startOutpaintDrag} onPointerMove={moveOutpaintDrag} onPointerUp={stopOutpaintDrag} onPointerCancel={stopOutpaintDrag} onWheel={wheelOutpaintScale} style={{ aspectRatio: `${targetWidth} / ${targetHeight}` }}>
            <div className="outpaint-image" style={{ backgroundImage: `url(${inputOne})`, left: `${(outpaint.left / Math.max(1, outpaintFinalWidth)) * 100}%`, top: `${(outpaint.top / Math.max(1, outpaintFinalHeight)) * 100}%`, width: `${(outpaintTarget.sourceWidth / Math.max(1, outpaintFinalWidth)) * 100}%`, height: `${(outpaintTarget.sourceHeight / Math.max(1, outpaintFinalHeight)) * 100}%` }} />
          </div>
          <div className="outpaint-controls">
            <strong>Итоговый кадр: {targetWidth} × {targetHeight}</strong>
            <span>Колесо мыши меняет масштаб. Исходник можно перетащить внутри рамки.</span>
            <label>Масштаб исходника<input type="range" min="35" max="100" value={outpaintScale} onChange={(e) => updateOutpaintScale(Number(e.target.value))} /></label>
            <label>Сдвиг влево / вправо<input type="range" min="0" max="100" value={outpaintHorizontalValue} disabled={outpaintTarget.extraX === 0} onChange={(e) => updateOutpaintAxis('x', Number(e.target.value))} /></label>
            <label>Сдвиг вверх / вниз<input type="range" min="0" max="100" value={outpaintVerticalValue} disabled={outpaintTarget.extraY === 0} onChange={(e) => updateOutpaintAxis('y', Number(e.target.value))} /></label>
            <small>Масштаб {outpaintScale}% · поля: слева {outpaint.left}, справа {outpaint.right}, сверху {outpaint.top}, снизу {outpaint.bottom}</small>
          </div>
        </div> : <button className="mask-upload" onClick={() => upload(setInputOne)}><span>↥</span><strong>Перетащите изображение или нажмите для загрузки</strong></button>}
      </div>
    </section></div>
  }
  return <div className="paint-editor-backdrop"><section className={isSketch ? 'paint-editor sketch-editor' : 'paint-editor mask-editor'}>
    {isSketch ? <div className="paint-editor-top"><div className="canvas-size-bar"><strong>ХОЛСТ</strong><input type="number" value={canvasDraft.width} onChange={(e) => setCanvasDraft({ ...canvasDraft, width: Number(e.target.value) })} /><span>⇆</span><input type="number" value={canvasDraft.height} onChange={(e) => setCanvasDraft({ ...canvasDraft, height: Number(e.target.value) })} /><button onClick={applyCanvasTarget}>Применить</button><button className="editor-close" onClick={onClose} aria-label="Закрыть"><X size={18} /></button></div><div className="editor-zoom"><button>-</button><button>Вписать</button><button>+</button></div><button className="secondary" onClick={() => setActiveLines((lines) => lines.slice(0, -1))}><RotateCcw size={16} />Назад</button><button className="secondary" onClick={() => setActiveLines([])}>Очистить</button><button className="save-sketch" onClick={applyEditor}>Сохранить</button></div> : <div className="paint-editor-top mask-top"><button className={paintTool === 'inpaint' ? 'active' : ''} onClick={() => { setPaintTool('inpaint'); setPromptForKey('paint:inpaint', workflowPresets.find((item) => item.id === 'mask-01')?.prompt || '') }}>Закрасить область</button><button className={paintTool === 'outpaint' ? 'active' : ''} onClick={() => { setPaintTool('outpaint'); setPromptForKey('paint:outpaint', workflowPresets.find((item) => item.id === 'outpaint-01')?.prompt || '') }}>Расширить изображение</button><button onClick={() => upload(setInputOne)}>Загрузить</button><button className={tool === 'brush' ? 'active' : ''} onClick={() => setTool('brush')}>● Кисть</button><button className={tool === 'eraser' ? 'active' : ''} onClick={() => setTool('eraser')}>○ Ластик</button><label>Размер<input type="range" min="2" max="60" value={brushSize} onChange={(e) => setBrushSize(Number(e.target.value))} /></label><output>{brushSize}</output><label>Жест.<input type="range" min="0" max="100" value="100" readOnly /></label><output>100</output><button onClick={() => setActiveLines((lines) => lines.slice(0, -1))}>↩ Назад</button><button onClick={() => setActiveLines([])}>× Сбросить маску</button><button className="save-sketch" onClick={applyEditor}>Применить</button><button className="secondary" onClick={onClose}>Отмена</button></div>}
    {isSketch ? <div className="sketch-body"><aside className="sketch-tools"><strong>РИСОВАНИЕ</strong><div className="tool-pair"><button className={tool === 'brush' && drawMode === 'free' ? 'active' : ''} onClick={() => { setTool('brush'); setDrawMode('free') }}><Brush size={16} />КИСТЬ</button><button className={tool === 'eraser' ? 'active' : ''} onClick={() => { setTool('eraser'); setDrawMode('free') }}><Eraser size={16} />ЛАСТИК</button></div><strong>КИСТЬ</strong><label>РАЗМЕР<input type="range" min="2" max="48" value={brushSize} onChange={(e) => setBrushSize(Number(e.target.value))} /></label><label>ЖЕСТКОСТЬ<input type="range" min="0" max="100" value="100" readOnly /></label><strong>ЦВЕТ</strong><input type="color" value={paintColor} onChange={(e) => setPaintColor(e.target.value)} /><strong>ФИГУРЫ</strong><div className="shape-grid"><button className={drawMode === 'circle' ? 'active' : ''} onClick={() => { setTool('brush'); setDrawMode('circle') }}>○ КРУГ</button><button className={drawMode === 'rect' ? 'active' : ''} onClick={() => { setTool('brush'); setDrawMode('rect') }}>□ ПРЯМ.</button><button className={!fillShape ? 'active' : ''} onClick={() => setFillShape(false)}>Контур</button><button className={fillShape ? 'active' : ''} onClick={() => setFillShape(true)}>Заливка</button></div><button className={drawMode === 'move' ? 'transform-button active' : 'transform-button'} onClick={moveLastItem}>✣ ПЕРЕМЕСТИТЬ</button></aside><div ref={stageWrapRef} className="editor-stage-wrap"><Stage ref={canvasRef} width={stageSize.width} height={stageSize.height} className="konva-stage editor-stage" onMouseDown={(e) => startLine(e.target.getStage() || null)} onMouseMove={(e) => extendLine(e.target.getStage() || null)} onMouseUp={stopLine} onMouseLeave={stopLine} onTouchStart={(e) => { e.evt.preventDefault(); startLine(e.target.getStage() || null) }} onTouchMove={(e) => { e.evt.preventDefault(); extendLine(e.target.getStage() || null) }} onTouchEnd={stopLine}><Layer opacity={layerOpacity}><Rect x={0} y={0} width={stageSize.width} height={stageSize.height} fill="#fff" />{activeLines.length === 0 && <Text text="Рисуйте на холсте" x={Math.max(18, stageSize.width / 2 - 92)} y={Math.max(80, stageSize.height / 2 - 12)} fill="#777" fontSize={Math.min(20, Math.max(14, stageSize.width / 24))} fontStyle="bold" />}{activeLines.map(renderPaintItem)}</Layer></Stage></div><aside className="editor-layers"><strong>СЛОИ</strong><button>＋</button><label>{copy.opacity}<input type="range" min="0.2" max="1" step="0.05" value={layerOpacity} onChange={(e) => setLayerOpacity(Number(e.target.value))} /></label></aside></div> : <div className="mask-body">{inputOne ? <div className="mask-upload mask-image-layer"><div className="mask-image-bg" style={{ backgroundImage: `url(${inputOne})` }} /></div> : <button className="mask-upload" onClick={() => upload(setInputOne)}><span>↥</span><strong>Перетащите изображение или нажмите для загрузки</strong></button>}{isOutpaint && <div className="outpaint-inline"><strong>{copy.finalSize}: {stageSize.width + outpaint.left + outpaint.right} × {stageSize.height + outpaint.top + outpaint.bottom}</strong><label>Слева<input value={outpaint.left} onChange={(e) => updateOutpaint('left', Number(e.target.value))} /></label><label>Справа<input value={outpaint.right} onChange={(e) => updateOutpaint('right', Number(e.target.value))} /></label><label>Сверху<input value={outpaint.top} onChange={(e) => updateOutpaint('top', Number(e.target.value))} /></label><label>Снизу<input value={outpaint.bottom} onChange={(e) => updateOutpaint('bottom', Number(e.target.value))} /></label></div>}<div ref={stageWrapRef} className="mask-stage-wrap"><Stage ref={canvasRef} width={stageSize.width} height={stageSize.height} className="konva-stage mask-stage" onMouseDown={(e) => startLine(e.target.getStage() || null)} onMouseMove={(e) => extendLine(e.target.getStage() || null)} onMouseUp={stopLine} onMouseLeave={stopLine} onTouchStart={(e) => { e.evt.preventDefault(); startLine(e.target.getStage() || null) }} onTouchMove={(e) => { e.evt.preventDefault(); extendLine(e.target.getStage() || null) }} onTouchEnd={stopLine}><Layer><Rect x={0} y={0} width={stageSize.width} height={stageSize.height} fill="rgba(0,0,0,0)" />{activeLines.map(renderPaintItem)}</Layer></Stage></div></div>}
  </section></div>
}

function ImageBox({ title, image, onUpload, onClear, onUseLast, copy }: { title: string; image?: string; onUpload: () => void; onClear: () => void; onUseLast?: () => void; copy: Copy }) {
  return <div className="image-box"><div className="box-title">{title}</div>{image ? <img src={image} /> : <div className="image-box-actions"><button onClick={onUpload}><Upload />{copy.upload}</button>{onUseLast && <button onClick={onUseLast}><GalleryHorizontalEnd />{copy.useLast}</button>}</div>}{image && <button className="floating-clear" onClick={onClear}><X size={16} /></button>}</div>
}

function PromptBlock({ copy, prompt, setPrompt, negativePrompt, setNegativePrompt, translatePrompt, onDiscover, randomPrompt, hideNegative = false, label, placeholder, hideTemplates = false }: { copy: Copy; prompt: string; setPrompt: (value: string) => void; negativePrompt: string; setNegativePrompt: (value: string) => void; translatePrompt: () => void; onDiscover: () => void; randomPrompt: () => void; hideNegative?: boolean; label?: string; placeholder?: string; hideTemplates?: boolean }) {
  const promptRef = useRef<HTMLTextAreaElement | null>(null)
  useEffect(() => {
    const field = promptRef.current
    if (!field) return
    field.style.height = 'auto'
    field.style.height = `${field.scrollHeight}px`
  }, [prompt])
  const promptLabel = label || copy.prompt
  const promptPlaceholder = placeholder || 'Напиши, что сгенерировать'
  return (
    <div className="prompt-block">
      <div className="prompt-head">
        <span className="prompt-label-text">{promptLabel}</span>
        {!hideTemplates && <button type="button" className="discover-button" onClick={onDiscover}>Шаблоны</button>}
        {!hideTemplates && <button type="button" className="expand-button" onClick={randomPrompt}>Случайный</button>}
      </div>
      <textarea ref={promptRef} aria-label={promptLabel} placeholder={promptPlaceholder} value={prompt} onChange={(e) => setPrompt(e.target.value)} />
      {!hideNegative && <label>{copy.negative}<input value={negativePrompt} onChange={(e) => setNegativePrompt(e.target.value)} /></label>}
      <button className="secondary" onClick={translatePrompt}><Languages size={16} />{copy.translate}</button>
    </div>
  )
}

// Нижний док edit: только «Дополнительное пожелание» + две кнопки (Шаблоны / Расширенные).
function EditPromptDock({ prompt, setPrompt, onTemplates, onAdvanced }: {
  prompt: string
  setPrompt: (value: string) => void
  onTemplates: () => void
  onAdvanced: () => void
}) {
  const promptRef = useRef<HTMLTextAreaElement | null>(null)
  useEffect(() => {
    const field = promptRef.current
    if (!field) return
    field.style.height = 'auto'
    field.style.height = `${field.scrollHeight}px`
  }, [prompt])
  return (
    <div className="prompt-block edit-dock">
      <div className="prompt-head">
        <span className="prompt-label-text">Дополнительное пожелание</span>
        <button type="button" className="discover-button" onClick={onTemplates}><Sparkles size={15} />Шаблоны</button>
        <button type="button" className="expand-button" onClick={onAdvanced}><SlidersHorizontal size={15} />Расширенные</button>
      </div>
      <textarea ref={promptRef} aria-label="Дополнительное пожелание" placeholder="Например: сделать свет мягче, добавить кинематографичность (необязательно)" value={prompt} onChange={(e) => setPrompt(e.target.value)} />
    </div>
  )
}

// Модалка шаблонов: настраивает роли + userNote (не просто текст).
function EditTemplatesModal({ templates, applyTemplate, onClose }: {
  templates: EditTemplate[]
  applyTemplate: (tpl: EditTemplate) => void
  onClose: () => void
}) {
  const roleNames = (tpl: EditTemplate) => tpl.assign.map((a) => `реф ${a.refIndex} — ${EDIT_REFERENCE_ROLE_LABELS[a.role]}`).join(', ')
  const isDisabled = (tpl: EditTemplate) => tpl.assign.some((a) => EDIT_DISABLED_REFERENCE_ROLES.includes(a.role))
  return <div className="modal-backdrop" onClick={onClose}><section className="instruction-modal edit-templates-modal" onClick={(e) => e.stopPropagation()}>
    <button className="floating-clear" onClick={onClose}><X size={16} /></button>
    <h2>Шаблоны</h2>
    <p className="modal-sub">Шаблон сам расставит роли референсам. Загрузите изображения в нужные слоты.</p>
    <div className="templates-list">
      {templates.map((tpl) => (
        <button key={tpl.id} className={`template-card ${isDisabled(tpl) ? 'disabled' : ''}`} disabled={isDisabled(tpl)} onClick={() => applyTemplate(tpl)}>
          <strong>{tpl.title}</strong>
          <small>{roleNames(tpl)}</small>
          {isDisabled(tpl) && <em>Режим временно закрыт</em>}
        </button>
      ))}
    </div>
  </section></div>
}

// Модалка «Расширенные»: уточнения «что взять», собранная инструкция, ручной режим.
function EditAdvancedModal({ editSlots, onTakeNote, composedPrompt, manualMode, manualPrompt, onEnterManual, onBackToAuto, setManualPrompt, onClose }: {
  editSlots: EditSlot[]
  onTakeNote: (index: number, value: string) => void
  composedPrompt: string
  manualMode: boolean
  manualPrompt: string
  onEnterManual: () => void
  onBackToAuto: () => void
  setManualPrompt: (value: string) => void
  onClose: () => void
}) {
  const refsWithRole = editSlots.map((slot, i) => ({ slot, i })).filter((x) => x.i >= 1 && x.slot.image && x.slot.role)
  return <div className="modal-backdrop" onClick={onClose}><section className="instruction-modal edit-advanced-modal" onClick={(e) => e.stopPropagation()}>
    <button className="floating-clear" onClick={onClose}><X size={16} /></button>
    <h2>Расширенные</h2>
    {refsWithRole.length > 0 && <div className="advanced-takenotes">
      {refsWithRole.map(({ slot, i }) => (
        <label key={i} className={`edit-take-note-row ${slot.role === 'other' && !slot.takeNote.trim() ? 'needs-role' : ''}`}>
          <span>Референс {i} ({EDIT_REFERENCE_ROLE_LABELS[slot.role as EditReferenceRole]}) — что взять</span>
          <input value={slot.takeNote} placeholder="напр.: позу сидя, белую рубашку, фон комнаты" onChange={(e) => onTakeNote(i, e.target.value)} />
        </label>
      ))}
    </div>}
    <div className="composer-head">
      <span>Инструкция для модели{manualMode ? ' · ручной режим' : ' · авто'}</span>
      <button type="button" className="composer-toggle" onClick={() => manualMode ? onBackToAuto() : onEnterManual()}>{manualMode ? 'Вернуться к авто' : 'Редактировать вручную'}</button>
    </div>
    {manualMode
      ? <textarea className="composer-manual" value={manualPrompt} onChange={(e) => setManualPrompt(e.target.value)} placeholder="Финальная инструкция для генерации" />
      : <pre className="composer-preview">{composedPrompt}</pre>}
  </section></div>
}

function JobCard({ job, copy, cancelJob, sendImage, mode, beforeImage, loadingBackdrop }: { job: Job; copy: Copy; cancelJob: () => void; sendImage: (platform: 'telegram' | 'max', imageId?: string) => void; mode: Mode; beforeImage?: string; loadingBackdrop?: string }) {
  const [compare, setCompare] = useState(50)
  const canCompare = mode !== 'text_to_image' && job.status === 'completed' && job.resultUrl && beforeImage
  const isLoading = job.status !== 'completed'
  const statusLabel = job.status === 'queued' ? 'В очереди' : job.status === 'uploading' ? 'Загружаем изображения' : job.status === 'sent_to_comfyui' ? 'Отправлено в обработку' : copy.running
  if (isLoading) {
    return <div className={`job-card ${job.status} loading`}>
      <div className="loading-backdrop">{loadingBackdrop ? <img src={loadingBackdrop} /> : <ImageIcon size={64} />}</div>
      <div className="loading-overlay">
        <div className="loading-ring"><span className="loading-pct">{job.progress}%</span></div>
        <div className="loading-status">{statusLabel}…</div>
        <div className="progress"><i style={{ width: `${Math.max(6, job.progress)}%` }} /></div>
        {job.error && <p className="loading-error">{job.error}</p>}
        {['queued', 'running', 'uploading', 'sent_to_comfyui'].includes(job.status) && <button className="secondary danger" onClick={cancelJob}>{copy.cancel}</button>}
      </div>
    </div>
  }
  const actions = job.resultUrl ? <div className="result-actions"><a className="secondary" href={job.resultUrl} download><Download size={16} />{copy.download}</a><button className="secondary" disabled={!job.resultImageId} onClick={() => sendImage('telegram', job.resultImageId)}>{copy.sendTg}</button></div> : null
  const quotaNote = job.gallerySaveStatus === 'quota_full'
    ? <div className="notice quota-full-note">Галерея заполнена: результат готов, но не сохранён в галерею. Освободите слот или смените тариф.</div>
    : null
  return <div className={`job-card ${job.status}`}>{canCompare ? <div className="compare-frame"><img className="compare-before" src={beforeImage} /><div className="compare-after" style={{ clipPath: `inset(0 0 0 ${compare}%)` }}><img src={job.resultUrl} /></div><i className="compare-line" style={{ left: `${compare}%` }}><span>↔</span></i><input aria-label="До после" type="range" min="0" max="100" value={compare} onChange={(e) => setCompare(Number(e.target.value))} />{actions}{quotaNote}</div> : job.resultUrl ? <div className="result-frame"><img src={job.resultUrl} />{actions}{quotaNote}</div> : null}</div>
}

function GalleryView({ copy, images, quota, selected, setSelected, handleUseImageAs, refreshGallery, clearSelected, backToStudio, view, setView, sendImage, pickSlot = null, onPickForSlot, cancelPick }: { copy: Copy; images: GalleryImage[]; quota?: GalleryQuota; selected?: GalleryImage; setSelected: (image: GalleryImage) => void; handleUseImageAs: (image: GalleryImage, target: Mode, slot?: number) => void; refreshGallery: () => Promise<void>; clearSelected: () => void; backToStudio: () => void; view: 'grid' | 'list'; setView: (view: 'grid' | 'list') => void; sendImage: (platform: 'telegram' | 'max', imageId?: string) => void; pickSlot?: number | null; onPickForSlot?: (image: GalleryImage) => void; cancelPick?: () => void }) {
  const picking = pickSlot !== null
  const [galleryMsg, setGalleryMsg] = useState('')
  // Публикация выбранного изображения в Ленту (feed backend, cookie-сессия).
  const [publishOpen, setPublishOpen] = useState(false)
  const [publishTitle, setPublishTitle] = useState('')
  const [publishVisibility, setPublishVisibility] = useState<'open' | 'hidden'>('open')
  const [publishAllow, setPublishAllow] = useState(true)
  const [publishBusy, setPublishBusy] = useState(false)
  const [publishDone, setPublishDone] = useState(false)
  const [imageZoom, setImageZoom] = useState(1)
  const [imagePan, setImagePan] = useState({ x: 0, y: 0 })
  const imageDragRef = useRef({ active: false, startX: 0, startY: 0, panX: 0, panY: 0 })

  function openPublish(image: GalleryImage) {
    void image
    setPublishTitle('')
    setPublishVisibility('open')
    setPublishAllow(true)
    setPublishDone(false)
    setPublishOpen(true)
  }

  async function submitPublish(image: GalleryImage) {
    const title = publishTitle.trim()
    if (!title || publishBusy) return
    setPublishBusy(true)
    try {
      const response = await feedFetch('/feed/publications', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          imageId: image.id,
          title,
          promptVisibility: publishVisibility,
          allowRecreate: publishAllow,
        }),
      })
      if (response.status === 401 || response.status === 403) {
        setGalleryMsg('Войдите, чтобы публиковать работы.')
        setPublishOpen(false)
        return
      }
      if (!response.ok) {
        setGalleryMsg('Не удалось опубликовать. Попробуйте ещё раз.')
        return
      }
      setPublishDone(true)
    } catch {
      setGalleryMsg('Проблема соединения. Попробуйте ещё раз.')
    } finally {
      setPublishBusy(false)
    }
  }
  const useOptions: Array<{ label: string; target: Mode; slot?: number }> = [
    { label: copy.useAsImageToImage, target: 'image_to_image' },
    { label: copy.useAsEditOne, target: 'edit', slot: 1 },
    { label: copy.useAsEditTwo, target: 'edit', slot: 2 },
    { label: copy.useAsPaint, target: 'paint' },
    { label: copy.useAsInpaint, target: 'inpaint' },
    { label: copy.useAsOutpaint, target: 'outpaint' },
    { label: copy.useAsFaceTarget, target: 'faceswap', slot: 1 },
    { label: copy.useAsFaceSource, target: 'faceswap', slot: 2 },
    { label: copy.useAsRemoveBackground, target: 'remove_background' },
    { label: copy.useAsTryOn, target: 'try_on', slot: 1 },
    { label: `${copy.referenceImage} · примерка`, target: 'try_on', slot: 2 },
    { label: copy.useAsTextureTransfer, target: 'texture_transfer', slot: 1 },
    { label: `${copy.referenceImage} · текстура`, target: 'texture_transfer', slot: 2 },
  ]
  async function toggleFavorite(image: GalleryImage) {
    setGalleryMsg('')
    const updated = await apiFetch(`/gallery/${image.id}/favorite`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ isFavorite: !image.isFavorite }),
    }).then((response) => response.json())
    setSelected(updated)
    await refreshGallery()
  }
  async function deleteImage(image: GalleryImage) {
    if (!window.confirm('Удалить изображение из галереи?')) return
    await apiFetch(`/gallery/${image.id}`, { method: 'DELETE' })
    clearSelected()
    await refreshGallery()
    await refreshAuthStateV2()
  }
  const onUseSelected = (value: string) => {
    if (!selected || !value) return
    const option = useOptions[Number(value)]
    if (!option) return
    handleUseImageAs(selected, option.target, option.slot)
  }
  const shareSelected = async (image: GalleryImage) => {
    setGalleryMsg('')
    if (navigator.share) {
      try {
        await navigator.share({ title: 'Изображение из галереи', text: image.promptOriginal.slice(0, 180), url: image.url })
        return
      } catch {
        return
      }
    }
    await navigator.clipboard?.writeText(image.url)
    setGalleryMsg('Ссылка скопирована')
  }
  const favoriteLimit = Math.max(0, Math.floor((quota?.gallery_slots || 0) * 0.8))
  const favoriteUsed = images.filter((image) => image.isFavorite).length
  const imageZoomStyle = {
    transform: `translate3d(${imagePan.x}px, ${imagePan.y}px, 0) scale(${imageZoom})`,
  }
  const resetImageView = () => {
    setImageZoom(1)
    setImagePan({ x: 0, y: 0 })
  }
  const changeImageZoom = (next: number) => {
    const clamped = Math.max(0.5, Math.min(5, next))
    setImageZoom(clamped)
    if (Math.abs(clamped - 1) < 0.02) setImagePan({ x: 0, y: 0 })
  }
  const onImageWheel = (event: ReactWheelEvent<HTMLDivElement>) => {
    event.preventDefault()
    changeImageZoom(imageZoom * (event.deltaY < 0 ? 1.14 : 0.88))
  }
  const onImagePointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (imageZoom <= 1.02) return
    imageDragRef.current = { active: true, startX: event.clientX, startY: event.clientY, panX: imagePan.x, panY: imagePan.y }
    event.currentTarget.setPointerCapture(event.pointerId)
  }
  const onImagePointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    const drag = imageDragRef.current
    if (!drag.active) return
    setImagePan({ x: drag.panX + event.clientX - drag.startX, y: drag.panY + event.clientY - drag.startY })
  }
  const onImagePointerUp = (event: ReactPointerEvent<HTMLDivElement>) => {
    imageDragRef.current.active = false
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId)
  }
  void sendImage
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && selected) clearSelected()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [selected, clearSelected])
  useEffect(() => {
    const timer = window.setTimeout(() => {
      resetImageView()
      setGalleryMsg('')
    }, 0)
    return () => window.clearTimeout(timer)
  }, [selected?.id])
  return (
    <section className="gallery-page">
      {picking && <div className="gallery-pick-banner"><span>Выберите изображение для слота {pickSlot === 0 ? 'Основа' : `Референс ${pickSlot}`}</span><button className="secondary" onClick={() => cancelPick?.()}>Отмена</button></div>}
      {quota && (
        <div className="gallery-pick-banner gallery-quota-banner">
          <span>Галерея</span>
          <span>Оригиналы {quota.gallery_used}/{quota.gallery_slots}</span>
          <span>Сердечки {favoriteUsed}/{favoriteLimit}</span>
        </div>
      )}
      <div className="view-actions gallery-toolbar">
        <button className="secondary" onClick={backToStudio}><WandSparkles size={16} />{copy.backToStudio}</button>
        <button className={view === 'grid' ? 'secondary active' : 'secondary'} onClick={() => setView('grid')}>{copy.grid}</button>
        <button className={view === 'list' ? 'secondary active' : 'secondary'} onClick={() => setView('list')}>{copy.list}</button>
      </div>
      <div className="gallery-view">
        <div className={view === 'grid' ? 'gallery-grid' : 'gallery-list'}>
          {images.length === 0 && <div className="gallery-empty">Галерея пока пуста</div>}
          {images.map((image) => (
            <article className="image-card" key={image.id}>
              <button className="gallery-thumb" type="button" onClick={() => picking ? onPickForSlot?.(image) : setSelected(image)}>
                <img src={image.thumbnailUrl || image.url} alt="" loading="lazy" />
              </button>
              <div className="gallery-card-body">
                <span>{image.mode.replaceAll('_', ' ')}</span>
                <small>{new Date(image.createdAt).toLocaleString()}</small>
                <p>{image.promptOriginal}</p>
              </div>
              <div className="gallery-card-actions">
                <button type="button" title={copy.favorite} onClick={() => void toggleFavorite(image)}><Heart className={image.isFavorite ? 'fav' : ''} size={16} /></button>
                <button type="button" title={copy.publishToFeed} onClick={() => openPublish(image)}><Sparkles size={16} /></button>
                <button className="danger" type="button" title={copy.delete} onClick={() => void deleteImage(image)}><Trash2 size={16} /></button>
              </div>
            </article>
          ))}
        </div>
      </div>
      {selected && (
        <div className="gallery-modal-backdrop" onClick={clearSelected}>
          <section className="gallery-modal" role="dialog" aria-label="Предпросмотр изображения" onClick={(e) => e.stopPropagation()}>
            <div className="gallery-modal-topbar">
              <button className="gallery-icon-button" aria-label="Закрыть" onClick={clearSelected}><X size={17} /></button>
              <div className="gallery-zoom-controls">
                <button className="gallery-icon-button" type="button" aria-label="Уменьшить" onClick={() => changeImageZoom(imageZoom - 0.25)}>−</button>
                <button className="gallery-zoom-value" type="button" onClick={resetImageView}>{Math.round(imageZoom * 100)}%</button>
                <button className="gallery-icon-button" type="button" aria-label="Увеличить" onClick={() => changeImageZoom(imageZoom + 0.25)}>+</button>
              </div>
              <div className="gallery-modal-top-actions">
                <a className="gallery-icon-button" href={selected.url} download title={copy.download} aria-label={copy.download}><Download size={17} /></a>
                <button className="gallery-icon-button" type="button" title={copy.favorite} aria-label={copy.favorite} onClick={() => void toggleFavorite(selected)}><Heart className={selected.isFavorite ? 'fav' : ''} size={17} /></button>
                <button className="gallery-icon-button publish-to-feed" type="button" title={copy.publishToFeed} aria-label={copy.publishToFeed} onClick={() => openPublish(selected)}><Sparkles size={17} /></button>
                <button className="gallery-icon-button danger" type="button" title={copy.delete} aria-label={copy.delete} onClick={() => void deleteImage(selected)}><Trash2 size={17} /></button>
              </div>
            </div>
            <div
              className={`gallery-modal-media${imageZoom > 1.02 ? ' is-zoomed' : ''}`}
              onWheel={onImageWheel}
              onPointerDown={onImagePointerDown}
              onPointerMove={onImagePointerMove}
              onPointerUp={onImagePointerUp}
              onPointerCancel={onImagePointerUp}
            >
              <img
                src={selected.url || selected.thumbnailUrl}
                alt=""
                style={imageZoomStyle}
                draggable={false}
                onDoubleClick={() => changeImageZoom(imageZoom > 1.02 ? 1 : 2)}
                onError={(event) => { if (selected.thumbnailUrl && event.currentTarget.src !== selected.thumbnailUrl) event.currentTarget.src = selected.thumbnailUrl }}
              />
            </div>
            <div className="gallery-modal-panel">
              <header>
                <strong>{copy.preview}</strong>
                <span>{selected.mode.replaceAll('_', ' ')} · {new Date(selected.createdAt).toLocaleString()}</span>
              </header>
              <p className="gallery-meta">{selected.width}×{selected.height} · {selected.provider} · seed {selected.seed}</p>
              <details className="gallery-prompt-box">
                <summary>Prompt</summary>
                <p>{selected.promptOriginal}</p>
                {selected.promptTranslated && <p className="translated">{selected.promptTranslated}</p>}
              </details>
              <div className="gallery-use-select">
                <label>Использовать изображение<select value="" onChange={(e) => onUseSelected(e.target.value)}><option value="">Выбрать действие…</option>{useOptions.map((option, index) => <option value={index} key={`${option.target}-${option.slot || 0}`}>{option.label}</option>)}</select></label>
              </div>
              <details className="gallery-tech">
                <summary>Техническая информация</summary>
                <dl>
                  <dt>Model profile</dt><dd>{selected.modelProfile || '—'}</dd>
                  <dt>LoRA</dt><dd>{selected.loras?.join(', ') || '—'}</dd>
                  <dt>Preset</dt><dd>{selected.preset || '—'}</dd>
                  <dt>{copy.generationTime}</dt><dd>{selected.generationTimeMs} ms</dd>
                  <dt>ComfyUI prompt</dt><dd>{selected.comfyuiPromptId || '—'}</dd>
                </dl>
              </details>
              <div className="gallery-modal-actions">
                <button className="secondary" onClick={() => void toggleFavorite(selected)}><Heart className={selected.isFavorite ? 'fav' : ''} size={16} />{copy.favorite}</button>
                <a className="secondary" href={selected.url} download><Download size={16} />{copy.download}</a>
                <button className="secondary publish-to-feed" onClick={() => openPublish(selected)}><Sparkles size={16} />{copy.publishToFeed}</button>
                <button className="secondary" onClick={() => void shareSelected(selected)}>Скопировать ссылку</button>
                <button className="secondary danger" onClick={() => void deleteImage(selected)}><Trash2 size={16} />{copy.delete}</button>
              </div>
              {galleryMsg && <p className="gallery-msg">{galleryMsg}</p>}
              {publishOpen && (
                <div className="publish-modal-backdrop" onClick={() => setPublishOpen(false)}>
                  <div className="publish-modal" role="dialog" aria-label={copy.publishToFeed} onClick={(e) => e.stopPropagation()}>
                    <button className="floating-clear" aria-label="Закрыть" onClick={() => setPublishOpen(false)}><X size={16} /></button>
                    <strong>{copy.publishToFeed}</strong>
                    {publishDone ? (
                      <div className="publish-done">
                        <p>{copy.published}</p>
                        <button className="generate small-action" onClick={() => { window.location.href = '/feed' }}>{copy.goToFeed}</button>
                      </div>
                    ) : (
                      <>
                        <label className="publish-field">
                          <span>{copy.publishTitleLabel}</span>
                          <input type="text" maxLength={120} value={publishTitle} onChange={(e) => setPublishTitle(e.target.value)} />
                        </label>
                        <label className="publish-field">
                          <span>{copy.promptVisibilityLabel}</span>
                          <label className="publish-check inline">
                            <input
                              type="checkbox"
                              checked={publishVisibility === 'open'}
                              onChange={(e) => setPublishVisibility(e.target.checked ? 'open' : 'hidden')}
                            />
                            <span>{publishVisibility === 'open' ? copy.visOpen : copy.visHidden}</span>
                          </label>
                        </label>
                        <button className="generate small-action" disabled={publishBusy || !publishTitle.trim()} onClick={() => void submitPublish(selected)}>
                          {publishBusy ? '…' : copy.publishAction}
                        </button>
                      </>
                    )}
                  </div>
                </div>
              )}
            </div>
          </section>
        </div>
      )}
    </section>
  )
}

function DiscoverPanel({ lang, presets: panelPresets, applyPreset, addUserPreset, currentPrompt, onClose }: { lang: Lang; mode: Mode; presets: Preset[]; applyPreset: (preset: Preset) => void; addUserPreset: (name: string, presetPrompt: string) => void; currentPrompt: string; onClose: () => void }) {
  const [name, setName] = useState('')
  const [presetPrompt, setPresetPrompt] = useState(currentPrompt)
  const groups = panelPresets.reduce<Record<string, Preset[]>>((acc, preset) => {
    const key = preset.category || 'USER'
    acc[key] = [...(acc[key] || []), preset]
    return acc
  }, {})
  return <div className="discover-panel"><div className="discover-head"><strong>Шаблоны</strong><span>Выберите готовый запрос или сохраните свой</span><button type="button" className="discover-close" onClick={onClose} aria-label="Закрыть шаблоны"><X size={18} /></button></div><div className="preset-create"><strong>Добавить свой шаблон</strong><input placeholder="Название" value={name} onChange={(e) => setName(e.target.value)} /><textarea placeholder="Текст запроса" value={presetPrompt} onChange={(e) => setPresetPrompt(e.target.value)} /><button onClick={() => { if (name.trim() && presetPrompt.trim()) { addUserPreset(name.trim(), presetPrompt.trim()); setName(''); setPresetPrompt('') } }}>Сохранить</button></div><div className="discover-groups">{Object.entries(groups).map(([category, items]) => <section className="discover-category" key={category}><h3>{categoryTitle(category, lang)}</h3><div className="discover-cards">{items.map((preset) => {
    const preview = presetPreviewPair(preset)
    return <button key={preset.id} className={preview ? 'has-preview has-preview-pair' : ''} onClick={() => applyPreset(preset)}>{preview ? <span className="preset-preview-pair"><img className="preset-preview" src={preview.female} alt={`${preview.alt}: женская сцена`} loading="lazy" /><img className="preset-preview" src={preview.male} alt={`${preview.alt}: мужская сцена`} loading="lazy" /></span> : <Sparkles size={16} />}<span>{preset[lang]}{preset.dual ? ' · 2 IMG' : ''}</span><small>{preset.prompt.slice(0, 120)}</small></button>
  })}</div></section>)}</div></div>
}

function HelpView({ lang, applyPreset, copy, backToStudio }: { lang: Lang; applyPreset: (preset: Preset) => void; copy: Copy; backToStudio: () => void }) {
  return <section className="help-page"><div className="view-actions"><button className="secondary" onClick={backToStudio}><WandSparkles size={16} />{copy.backToStudio}</button></div><h2>Помощь</h2><div className="help-grid"><article><h3>Как пользоваться ИЗО_АСА</h3><p>Выберите режим в верхней панели: По тексту, По фото, Сборка или Редактор. Заполните prompt, добавьте изображения там, где режим этого требует, и нажмите «Сгенерировать».</p><p>Кнопка «Шаблоны» открывает готовые русские запросы для текущей вкладки. Кнопка «Случайный» подставляет случайный запрос только из набора активной вкладки или активного инструмента рисования.</p></article><article><h3>Настройки по умолчанию исходника</h3><p>Размер: 1024 × 1024. Seed: 0 с рандомизацией. Steps: 4. CFG: 1. Sampler: er_sde. Negative prompt уже заполнен исходным списком ограничений качества.</p><p>Перенос лица выполняется референсом «Лицо» в режиме «Сборка». Для локальной генерации используется ComfyUI и workflow Flux 2 Klein.</p></article><article><h3>Режимы</h3><p><strong>По тексту</strong>: генерация картинки по prompt. <strong>По фото</strong>: изменение загруженного изображения с силой изменения. <strong>Сборка</strong>: собрать изображение из нескольких фото, включая перенос лица. <strong>Редактор</strong>: эскиз, маска, правки и расширение изображения.</p></article></div><h3>Шаблоны</h3><div className="preset-grid">{workflowPresets.map((preset) => <button key={preset.id} onClick={() => applyPreset(preset)}><Sparkles /><strong>{preset[lang]}</strong><span>{preset.prompt.slice(0, 130)}</span></button>)}</div></section>
}

function InstructionModal({ mode, paintTool, onClose }: { mode: Mode; paintTool: PaintTool; onClose: () => void }) {
  const text: Record<string, { title: string; steps: string[] }> = {
    text_to_image: { title: 'Инструкция: По тексту', steps: ['Нажмите «Пресеты» или «Случайный prompt», чтобы быстро заполнить запрос.', 'Выберите размер изображения слева.', 'При необходимости откройте «Настройки» и измените seed, steps, CFG, sampler или LoRA.', 'Нажмите «Сгенерировать» и дождитесь результата справа.'] },
    image_to_image: { title: 'Инструкция: По фото', steps: ['Загрузите исходное изображение в левую область.', 'Настройте «Силу изменения»: 0.10 меняет мало, 0.75 ближе к исходнику One Node, 0.80 меняет сильно.', 'Введите prompt с описанием того, как нужно изменить изображение.', 'Нажмите «Сгенерировать».'] },
    edit: { title: 'Инструкция: Сборка', steps: ['Загрузите «Основу» — это главное изображение, которое нужно сохранить и изменить. Без основы сборка не запускается.', 'Добавьте до трёх референсов. Каждый референс должен иметь одну роль: «Лицо», «Одежда», «Стиль / цвет», «Предмет», «Фон» или «Другое».', '«Лицо» переносит только узнаваемые черты лица. «Одежда» переносит фасон, ткань, цвет и посадку одежды. «Предмет» добавляет конкретный объект; лучше использовать референс, где предмет виден отдельно.', '«Стиль / цвет» объединяет старые роли «Стиль» и «Цвет/материал»: берет свет, атмосферу, цветовую палитру, фактуру и визуальную обработку, но не переносит людей, композицию и лишние объекты.', '«Фон» берет окружение, помещение, архитектуру, глубину и настроение сцены. Главный объект из основы должен остаться главным.', '«Другое» используйте только если нужно явно описать, что взять из референса. После выбора этой роли появится обязательное поле уточнения.', '«Поза» сейчас заблокирована серым замком. Этот workflow нестабилен, сильно грузит видеокарту и временно недоступен до отдельной стабилизации.', 'В поле «Дополнительное пожелание» пишите короткую правку результата: например, «сделай свет мягче», «добавь кинематографичность», «сохрани реализм». Это поле не заменяет роли референсов.', 'Кнопка «Шаблоны» расставляет роли автоматически. Кнопка «Расширенные» показывает собранную инструкцию и позволяет уточнить каждый референс или перейти в ручной prompt.', 'Нажмите «Сгенерировать». Во время обработки повторные нажатия блокируются. Для результата сборки жёлтая вертикальная линия в предпросмотре — это сравнение до/после.'] },
    paint: { title: `Инструкция: ${paintTool === 'sketch' ? 'Эскиз' : paintTool === 'inpaint' ? 'Маска' : 'Расширение'}`, steps: paintTool === 'sketch' ? ['Выберите «Эскиз», рисуйте на чистом холсте кистью/ластиком.', 'Prompt должен объяснять, во что превратить рисунок.', 'Сгенерируйте сцену по вашему рисунку.'] : paintTool === 'inpaint' ? ['Выберите «Маска». Это понятный режим замены области изображения.', 'Загрузите изображение и закрасьте область, которую нужно изменить.', 'В prompt опишите, что должно появиться в закрашенной зоне.', 'Сгенерируйте результат.'] : ['Выберите «Расширение».', 'Загрузите изображение и задайте, сколько пикселей добавить слева/справа/сверху/снизу.', 'Prompt должен описывать, чем заполнить новые области.', 'Сгенерируйте расширенную композицию.'] },
    faceswap: { title: 'Инструкция: Лицо', steps: ['Загрузите Target: изображение, куда нужно перенести лицо.', 'Загрузите Source: изображение, откуда берется лицо.', 'В «Настройки» выберите Faceswap LoRA, если он доступен локально.', 'Prompt по умолчанию описывает замену головы с сохранением света и стиля.'] },
    remove_background: { title: 'Инструкция: Удалить фон', steps: ['Загрузите изображение с объектом.', 'Оставьте стандартный prompt или уточните, что нужно изолировать.', 'Нажмите «Сгенерировать».'] },
    try_on: { title: 'Инструкция: Примерка', steps: ['Загрузите человека в первый слот.', 'Загрузите одежду или референс образа во второй слот.', 'Prompt по умолчанию переносит только одежду, сохраняя лицо, позу и фон.', 'Нажмите «Сгенерировать».'] },
    texture_transfer: { title: 'Инструкция: Перенос текстуры', steps: ['Загрузите целевой объект в первый слот.', 'Загрузите материал, текстуру или стиль во второй слот.', 'Prompt по умолчанию переносит поверхность, сохраняя форму и перспективу.', 'Нажмите «Сгенерировать».'] },
  }
  const current = text[mode] || text.text_to_image
  return <div className="modal-backdrop"><section className="instruction-modal"><button className="floating-clear" onClick={onClose}><X size={16} /></button><h2>{current.title}</h2>{current.steps.map((step, index) => <p key={step}><strong>{index + 1}.</strong> {step}</p>)}</section></div>
}

function SettingsView({ copy, lang, onLanguageChange, tariffs, bootstrap, setBootstrap, openAdmin, openGallery, provider, setProvider, width, setWidth, height, setHeight, steps, setSteps, setCfg, isAuthedV2 = false, openAuthModal, authMe }: { copy: Copy; lang: Lang; onLanguageChange: (value: Lang) => void; tariffs: TariffConfig; bootstrap?: Record<string, unknown>; setBootstrap: Dispatch<SetStateAction<Record<string, unknown> | undefined>>; openAdmin: () => void; openGallery?: () => void; provider: string; setProvider: (value: string) => void; width: number; setWidth: (value: number) => void; height: number; setHeight: (value: number) => void; steps: number; setSteps: (value: number) => void; setCfg: (value: number) => void; isAuthedV2?: boolean; openAuthModal?: () => void; authMe?: MeV2 | null }) {
  const user = (bootstrap?.user || {}) as { id?: string; role?: string; username?: string; firstName?: string; email?: string; plan?: string; galleryEnabled?: boolean; tokenBalance?: number; dailyTokens?: number; gallerySlots?: number; galleryUsed?: number; galleryFree?: number; galleryFull?: boolean }
  const account = authMe?.account
  const quality = steps <= 4 ? 'fast' : steps <= 8 ? 'standard' : 'max'
  const tokenPrice = (quality === 'fast' ? 1 : quality === 'standard' ? 2 : 4) * (provider === 'openrouter' ? 2 : 1)
  const referralLink = `${window.location.origin}?ref=${authMe?.profile?.public_user_code || user.id || 'guest'}`
  const plan = (tariffKeys.includes(String(account?.plan || user.plan || 'mini').toLowerCase() as TariffKey) ? String(account?.plan || user.plan || 'mini').toLowerCase() : 'mini') as TariffKey
  const planLabel = plan.toUpperCase()
  const tokenBalance = Number(account?.token_balance ?? user.tokenBalance ?? 0)
  const currentTariff = tariffs[plan] || DEFAULT_TARIFFS[plan]
  const dailyLimit = Number(account?.daily_tokens_limit ?? account?.daily_tokens ?? user.dailyTokens ?? currentTariff.daily_tokens)
  const dailyUsed = Math.max(0, Number(account?.daily_tokens_used ?? 0))
  const dailyRemaining = Math.max(0, Number(account?.daily_tokens_remaining ?? dailyLimit - dailyUsed))
  const gallerySlots = Number(account?.gallery_slots ?? user.gallerySlots ?? currentTariff.gallery_slots)
  const galleryUsed = Number(account?.gallery_used ?? user.galleryUsed ?? 0)
  const galleryFree = Math.max(0, Number(account?.gallery_free ?? user.galleryFree ?? gallerySlots - galleryUsed))
  const publicCode = String(authMe?.profile?.public_user_code || user.id || '').replace(/^web_/, '').toUpperCase()
  const planCards = [
    { id: 'free' as TariffKey, title: 'Free', note: 'Базовый доступ', daily: tariffs.free.daily_tokens, slots: tariffs.free.gallery_slots, features: ['Базовые модели', 'Галерея открыта', `${tariffs.free.gallery_slots} слот(ов) галереи`], disabled: [] },
    { id: 'mini' as TariffKey, title: 'Mini', note: 'Оптимальный старт', daily: tariffs.mini.daily_tokens, slots: tariffs.mini.gallery_slots, features: ['Стандартные модели', 'Галерея открыта', `${tariffs.mini.gallery_slots} слот(ов) галереи`], disabled: [] },
    { id: 'plus' as TariffKey, title: 'Plus', note: 'Больше возможностей', daily: tariffs.plus.daily_tokens, slots: tariffs.plus.gallery_slots, features: ['HD-модели', 'Ускоренная генерация', `${tariffs.plus.gallery_slots} слот(ов) галереи`], disabled: [] },
    { id: 'pro' as TariffKey, title: 'Pro', note: 'Максимум мощности', daily: tariffs.pro.daily_tokens, slots: tariffs.pro.gallery_slots, features: ['Продвинутые модели', 'Приоритетная очередь', `${tariffs.pro.gallery_slots} слот(ов) галереи`], disabled: [] },
    { id: 'business' as TariffKey, title: 'Business', note: 'Команда и максимальные лимиты', daily: tariffs.business.daily_tokens, slots: tariffs.business.gallery_slots, features: ['Бизнес-модели', 'Приоритетная очередь', `${tariffs.business.gallery_slots} слот(ов) галереи`], disabled: [] },
  ]
  const setQuality = (value: string) => {
    if (value === 'fast') { setSteps(4); setCfg(1) }
    if (value === 'standard') { setSteps(8); setCfg(1.5) }
    if (value === 'max') { setSteps(16); setCfg(2) }
  }
  const [promoCode, setPromoCode] = useState('')
  const [promoResult, setPromoResult] = useState('')
  const [promoBusy, setPromoBusy] = useState(false)
  const [inviteMsg, setInviteMsg] = useState('')
  const [displayName, setDisplayName] = useState(authMe?.profile?.display_name || '')
  const [profileGender, setProfileGender] = useState<'female' | 'male'>(authMe?.profile?.gender === 'male' ? 'male' : 'female')
  const [profileAge, setProfileAge] = useState(authMe?.profile?.age ? String(authMe.profile.age) : '')
  const [saveMsg, setSaveMsg] = useState('')
  const [techOpen, setTechOpen] = useState(false)
  const [viewedPlan, setViewedPlan] = useState(plan)
  const [avatarUrl, setAvatarUrl] = useState(authMe?.profile?.avatar_url || avatarPresets[0].url)
  const [avatarPreset, setAvatarPreset] = useState(authMe?.profile?.avatar_preset || '')
  const [avatarMsg, setAvatarMsg] = useState('')
  const [avatarBusy, setAvatarBusy] = useState(false)
  const [settingsTab, setSettingsTab] = useState<'profile' | 'tariffs' | 'earn' | 'models'>('profile')
  const [authCaps, setAuthCaps] = useState({ telegram_bot_login_available: false, max_bot_login_available: false })
  const [linkEmail, setLinkEmail] = useState('')
  const [linkEmailChallenge, setLinkEmailChallenge] = useState('')
  const [linkEmailCode, setLinkEmailCode] = useState('')
  const [linkMsg, setLinkMsg] = useState('')
  const [linkBusy, setLinkBusy] = useState(false)
  const friendPromoCode = `FRIEND-${String(authMe?.profile?.public_user_code || user.id || 'GUEST').replace(/^web_/, '').toUpperCase().slice(0, 12)}`
  void openAdmin // prop accepted for call-site compatibility
  useEffect(() => { queueMicrotask(() => setDisplayName(authMe?.profile?.display_name || '')) }, [authMe?.profile?.display_name])
  useEffect(() => { queueMicrotask(() => setProfileGender(authMe?.profile?.gender === 'male' ? 'male' : 'female')) }, [authMe?.profile?.gender])
  useEffect(() => { queueMicrotask(() => setProfileAge(authMe?.profile?.age ? String(authMe.profile.age) : '')) }, [authMe?.profile?.age])
  useEffect(() => { queueMicrotask(() => setViewedPlan(plan)) }, [plan])
  useEffect(() => {
    queueMicrotask(() => {
      setAvatarUrl(authMe?.profile?.avatar_url || avatarPresets[0].url)
      setAvatarPreset(authMe?.profile?.avatar_preset || '')
      setAvatarMsg('')
    })
  }, [authMe?.profile?.avatar_url, authMe?.profile?.avatar_preset])
  useEffect(() => {
    let active = true
    getAuthCapabilitiesV2().then((caps) => {
      if (active) setAuthCaps({ telegram_bot_login_available: caps.telegram_bot_login_available, max_bot_login_available: caps.max_bot_login_available })
    }).catch(() => undefined)
    return () => { active = false }
  }, [])
  const displayEmail = authMe?.identities?.find((i) => i.provider_email)?.provider_email
  const telegramIdentity = authMe?.identities?.find((i) => i.provider === 'telegram')
  const maxIdentity = authMe?.identities?.find((i) => i.provider === 'max')
  const emailIdentity = authMe?.identities?.find((i) => i.provider === 'web_email')
  const emailStatus = emailIdentity ? (emailIdentity.verified_at || authMe?.profile?.email_verified_at ? 'Подтвержден' : 'Ожидает подтверждения') : 'Не указан'
  const displayNameFallback = authMe?.profile?.display_name
    || [authMe?.profile?.first_name, authMe?.profile?.last_name].filter(Boolean).join(' ')
    || displayEmail?.split('@')[0]
    || 'Пользователь'
  const userInitials = displayNameFallback.split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]?.toUpperCase()).join('') || 'AI'
  const onSaveProfile = async () => {
    const trimmed = displayName.trim()
    if (!trimmed) { setSaveMsg('Введите имя'); return }
    const age = profileAge.trim()
    if (age && (Number(age) < 13 || Number(age) > 120)) { setSaveMsg('Возраст должен быть от 13 до 120'); return }
    setSaveMsg('')
    const result = await updateProfileV2({ display_name: trimmed, gender: profileGender, age })
    if (result) { await refreshAuthStateV2(); setSaveMsg('Сохранено') }
    else setSaveMsg('Ошибка сохранения')
  }
  const selectAvatarPreset = async (presetId: string) => {
    const preset = avatarPresets.find((item) => item.id === presetId)
    if (!preset) return
    setAvatarBusy(true); setAvatarMsg('')
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
    setAvatarBusy(true); setAvatarMsg('')
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
  const onLogout = async () => { await logoutV2(); await refreshAuthStateV2() }
  const onApplyPromo = async () => {
    const code = promoCode.trim().toUpperCase()
    if (!code) { setPromoResult('Введите промокод'); return }
    setPromoBusy(true); setPromoResult('')
    try {
      const r = await fetch(`${API}/account/apply-promo-v2`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ promo_code: code }),
      })
      const payload = await r.json().catch(() => ({}))
      if (!r.ok) {
        setPromoResult(String(payload.detail || 'Промокод не применён'))
        return
      }
      const bonus = Number(payload.token_bonus || 50)
      setPromoResult(`Промокод применён: +${bonus} токенов`)
      setBootstrap((current) => {
        const currentUser = ((current || {}).user || {}) as Record<string, unknown>
        return { ...(current || {}), user: { ...currentUser, tokenBalance: Number(payload.new_token_balance ?? tokenBalance + bonus) } }
      })
    } catch {
      setPromoResult('Не удалось проверить промокод')
    } finally {
      setPromoBusy(false)
    }
  }
  const copyInvite = async () => {
    await navigator.clipboard?.writeText(`${referralLink}\nПромокод: ${friendPromoCode}`)
    setInviteMsg('Скопировано')
  }
  const onRequestLinkEmail = async () => {
    const email = linkEmail.trim()
    if (!email) { setLinkMsg('Введите email'); return }
    setLinkBusy(true); setLinkMsg('')
    const result = await requestEmailLinkCodeV2(email)
    if (!result) setLinkMsg('Не удалось отправить код')
    else if ('error' in result) setLinkMsg(result.error === 'email_already_linked' ? 'Этот email уже привязан к другому аккаунту' : 'Email-подтверждение сейчас недоступно')
    else { setLinkEmailChallenge(result.challenge_id); setLinkMsg('Код отправлен на email') }
    setLinkBusy(false)
  }
  const onVerifyLinkEmail = async () => {
    if (!linkEmailChallenge || !linkEmailCode.trim()) return
    setLinkBusy(true); setLinkMsg('')
    const result = await verifyEmailLinkCodeV2(linkEmailChallenge, linkEmailCode.trim())
    if (!result.ok) setLinkMsg(result.error === 'email_already_linked' ? 'Этот email уже привязан к другому аккаунту' : 'Неверный или просроченный код')
    else {
      setLinkEmailChallenge(''); setLinkEmailCode(''); setLinkEmail('')
      await refreshAuthStateV2()
      setLinkMsg(result.reward_tokens ? `Email подключен: +${result.reward_tokens} токенов` : 'Email уже подключен')
    }
    setLinkBusy(false)
  }
  const onLinkBot = async (providerName: 'telegram' | 'max') => {
    setLinkBusy(true); setLinkMsg('')
    const started = await startBotLinkV2(providerName)
    if (!started.ok) {
      setLinkMsg(providerName === 'telegram' ? 'Telegram-подключение сейчас недоступно' : 'MAX-подключение сейчас недоступно')
      setLinkBusy(false)
      return
    }
    window.open(started.deep_link, '_blank', 'noopener,noreferrer')
    setLinkMsg(`Подтвердите подключение в ${providerName === 'telegram' ? 'Telegram' : 'MAX'}-боте`)
    const deadline = Date.now() + 10 * 60 * 1000
    const timer = window.setInterval(async () => {
      const status = await pollBotLoginStatusV2()
      if (status.status === 'authenticated') {
        window.clearInterval(timer)
        await refreshAuthStateV2()
        setLinkBusy(false)
        setLinkMsg(`${providerName === 'telegram' ? 'Telegram' : 'MAX'} подключен: +10 токенов, если бонус ещё не выдавался`)
      } else if (status.status === 'conflict') {
        window.clearInterval(timer)
        setLinkBusy(false)
        setLinkMsg('Этот способ входа уже привязан к другому аккаунту')
      } else if (status.status === 'expired' || status.status === 'error' || Date.now() > deadline) {
        window.clearInterval(timer)
        setLinkBusy(false)
        setLinkMsg('Подключение не завершено. Попробуйте снова')
      }
    }, started.poll_interval_ms || 2000)
  }

  if (!isAuthedV2) {
    return (
      <section className="settings-page user-settings usr-page">
        <header className="usr-title">
          <h2>Настройки аккаунта</h2>
          <p>Войдите, чтобы увидеть профиль, тарифы, токены и параметры генерации.</p>
        </header>
        <article className="usr-card usr-auth-card">
          <h3>Аккаунт</h3>
          <p>После входа здесь появятся ваш баланс, тариф, промокоды и реферальная ссылка.</p>
          <button className="usr-primary" onClick={() => openAuthModal?.()}><Lock size={16} />Войти</button>
        </article>
        <article className="usr-card usr-profile">
          <label>{copy.language}
            <select value={lang} onChange={(e) => onLanguageChange(e.target.value as Lang)}>
              <option value="ru">Русский</option>
              <option value="en">English</option>
            </select>
          </label>
        </article>
      </section>
    )
  }
  return (
    <section className="settings-page user-settings usr-page">
      <nav className="usr-tabs" aria-label="Разделы настроек">
        <button type="button" className={settingsTab === 'profile' ? 'active' : ''} onClick={() => setSettingsTab('profile')}>Профиль</button>
        <button type="button" className={settingsTab === 'tariffs' ? 'active' : ''} onClick={() => setSettingsTab('tariffs')}>Тарифы</button>
        <button type="button" className={settingsTab === 'earn' ? 'active' : ''} onClick={() => setSettingsTab('earn')}>Заработать токены</button>
        <button type="button" className={settingsTab === 'models' ? 'active' : ''} onClick={() => setSettingsTab('models')}>Модели</button>
      </nav>

      {settingsTab === 'profile' && <>
      <section className="usr-card usr-hero">
        <div className="usr-avatar-block">
          <div className="usr-avatar" aria-label="Аватар пользователя">
            {avatarUrl ? <img src={avatarUrl} alt="" /> : <span>{userInitials}</span>}
          </div>
          <label className={avatarBusy ? 'usr-avatar-upload disabled' : 'usr-avatar-upload'}>
            <Upload size={16} />
            <span>{avatarBusy ? 'Сохраняем...' : 'Загрузить файл'}</span>
            <input type="file" accept="image/png,image/jpeg,image/webp" onChange={uploadAvatar} disabled={avatarBusy} />
          </label>
          {avatarMsg && <small className={avatarMsg.includes('сохран') || avatarMsg.includes('загруж') ? 'save-ok' : 'save-err'}>{avatarMsg}</small>}
        </div>
        <div className="usr-hero-main">
          <div className="usr-identity">
            <h3>{displayNameFallback}</h3>
            <span className="usr-chip current">{planLabel}</span>
            <span className="usr-chip green">Галерея {galleryUsed}/{gallerySlots}</span>
          </div>
          <div className="usr-code"><span>Публичный код: {publicCode || 'GUEST'}</span></div>
          <div className="usr-metrics">
            <div><span>Токенов сегодня</span><strong>{dailyUsed} / {dailyLimit}</strong><small>осталось {dailyRemaining}</small></div>
            <div><span>Баланс токенов</span><strong>{tokenBalance}</strong><small>доступно сейчас</small></div>
            <div><span>Галерея</span><strong>{galleryUsed}/{gallerySlots}</strong><small>свободно {galleryFree}</small></div>
            <div><span>Промо и друзья</span><strong>+50</strong><small>за промокод или друга</small></div>
          </div>
          <div className="usr-avatar-picker" aria-label="Выбор аватара">
            {avatarPresets.map((preset) => (
              <button type="button" className={avatarPreset === preset.id ? 'active' : ''} onClick={() => void selectAvatarPreset(preset.id)} disabled={avatarBusy} key={preset.id} title={preset.label}>
                <img src={preset.url} alt="" />
              </button>
            ))}
          </div>
        </div>
      </section>

      <section className="usr-card usr-profile">
        <label>Имя<input type="text" value={displayName} onChange={(e) => { setDisplayName(e.target.value); setSaveMsg('') }} placeholder="Ваше имя" maxLength={80} /></label>
        <label>Email<input type="email" value={displayEmail || ''} placeholder="Email не указан" readOnly disabled /></label>
        <label>{copy.language}
          <select value={lang} onChange={(e) => onLanguageChange(e.target.value as Lang)}>
            <option value="ru">Русский</option>
            <option value="en">English</option>
          </select>
        </label>
        <label>Превью шаблонов
          <select value={profileGender} onChange={(e) => { setProfileGender(e.target.value === 'male' ? 'male' : 'female'); setSaveMsg('') }}>
            <option value="female">Женский набор</option>
            <option value="male">Мужской набор</option>
          </select>
        </label>
        <label>Возраст<input type="number" min="13" max="120" value={profileAge} onChange={(e) => { setProfileAge(e.target.value); setSaveMsg('') }} placeholder="Например, 28" /></label>
        <div className="usr-profile-actions">
          <button className="usr-primary" onClick={onSaveProfile} disabled={!displayName.trim()}>Сохранить профиль</button>
          <button className="usr-ghost" onClick={onLogout}><Lock size={14} />Выйти</button>
          {saveMsg && <small className={saveMsg === 'Сохранено' ? 'save-ok' : 'save-err'}>{saveMsg}</small>}
        </div>
        <div className="tech-info">
          <button className="tech-toggle" onClick={() => setTechOpen(!techOpen)}>{techOpen ? '\u25BE' : '\u25B8'} Техническая информация</button>
          {techOpen && (
            <div className="tech-body">
              <small>ID: {authMe?.internal_user_id?.slice(0, 8) || '\u2014'}\u2026</small>
              {authMe?.identities?.map((id, i) => (<small key={i}>{id.provider}: {id.provider_username || id.provider_email || '\u2014'}</small>))}
            </div>
          )}
        </div>
      </section>
      <section className="usr-card usr-login-methods">
        <div className="usr-section-head"><h3>Способы входа</h3><span>+10 токенов за новое подтвержденное подключение</span></div>
        <div className="usr-login-grid">
          <article>
            <strong>Telegram</strong>
            <p>{telegramIdentity ? `Подключен: ${telegramIdentity.provider_username ? `@${telegramIdentity.provider_username}` : `ID ${telegramIdentity.provider_user_id || '—'}`}` : 'Не подключен'}</p>
            {!telegramIdentity && authCaps.telegram_bot_login_available && <button className="secondary" onClick={() => void onLinkBot('telegram')} disabled={linkBusy}>Подключить Telegram</button>}
          </article>
          <article>
            <strong>Email</strong>
            <p>{emailIdentity?.provider_email ? `${emailStatus}: ${emailIdentity.provider_email}` : emailStatus}</p>
            {!emailIdentity && <div className="usr-link-email">
              <input type="email" value={linkEmail} onChange={(e) => setLinkEmail(e.target.value)} placeholder="email@example.com" disabled={linkBusy || Boolean(linkEmailChallenge)} />
              {!linkEmailChallenge ? <button className="secondary" onClick={() => void onRequestLinkEmail()} disabled={linkBusy || !linkEmail.trim()}>Получить код</button> : <>
                <input value={linkEmailCode} onChange={(e) => setLinkEmailCode(e.target.value)} placeholder="Код из письма" disabled={linkBusy} />
                <button className="secondary" onClick={() => void onVerifyLinkEmail()} disabled={linkBusy || !linkEmailCode.trim()}>Подтвердить</button>
              </>}
            </div>}
          </article>
          <article>
            <strong>MAX</strong>
            <p>{maxIdentity ? `Подключен: ${maxIdentity.provider_username || `ID ${maxIdentity.provider_user_id || '—'}`}` : 'Не подключен'}</p>
            {!maxIdentity && authCaps.max_bot_login_available && <button className="secondary" onClick={() => void onLinkBot('max')} disabled={linkBusy}>Подключить MAX</button>}
          </article>
          <article>
            <strong>Телефон</strong>
            <p>Будет доступно позже</p>
          </article>
        </div>
        {linkMsg && <small className={linkMsg.includes('подключ') || linkMsg.includes('отправлен') ? 'save-ok' : 'save-err'}>{linkMsg}</small>}
      </section>
      <section className="usr-profile-dashboard">
        <article className="usr-card usr-stat-card"><span>Сегодня осталось</span><strong>{dailyRemaining}</strong><small>из {dailyLimit} токенов</small></article>
        <article className="usr-card usr-stat-card"><span>Баланс</span><strong>{tokenBalance}</strong><small>токенов</small></article>
        <article className="usr-card usr-stat-card"><span>Галерея</span><strong>{galleryUsed}/{gallerySlots}</strong><small>свободно {galleryFree}</small></article>
        <article className="usr-card usr-stat-card"><span>Промокод друга</span><strong>{friendPromoCode}</strong><small>+50 токенов</small></article>
      </section>
      </>}

      {settingsTab === 'tariffs' && <>
      <section className="usr-section">
        <div className="usr-tariff-summary usr-card">
          <div><span>Текущий тариф</span><strong>{planLabel}</strong></div>
          <div><span>Токены сегодня</span><strong>{dailyUsed} / {dailyLimit}</strong></div>
          <div><span>Галерея</span><strong>{galleryUsed}/{gallerySlots}</strong><small>свободно {galleryFree}</small></div>
          <button type="button" className="usr-primary" disabled>Управление тарифом скоро</button>
        </div>
        <div className="usr-section-head"><h3>Тарифы</h3><span>Текущий тариф: {planLabel}</span></div>
        <div className="usr-plan-tabs" aria-label="Тарифы">
          {planCards.map((item) => <button type="button" className={item.id === viewedPlan ? 'active' : ''} onClick={() => setViewedPlan(item.id)} key={item.id}>{item.title}</button>)}
        </div>
        <div className="usr-plans">
          {planCards.map((item) => (
            <article className={`${item.id === viewedPlan ? 'usr-card usr-plan active' : 'usr-card usr-plan'} ${item.id === plan ? 'current' : ''}`} key={item.id}>
              {item.id === plan && <span className="usr-chip current">Текущий</span>}
              <h4>{item.title}</h4>
              <p>{item.note}</p>
              <strong>{item.daily}</strong>
              <span>токенов в сутки · {item.slots} слот(ов)</span>
              <ul>
                {item.features.map((feature) => <li key={feature}>{feature}</li>)}
                {item.disabled.map((feature) => <li className="no" key={feature}>{feature}</li>)}
              </ul>
              <button type="button" disabled>{item.id === plan ? 'Текущий тариф' : 'Смена тарифа скоро'}</button>
            </article>
          ))}
        </div>
      </section>
      <section className="usr-card usr-compare">
        <div>Функции</div>{tariffKeys.map((key) => <div key={key}>{key.toUpperCase()}</div>)}
        <span>Токены в сутки</span>{tariffKeys.map((key) => <b key={key}>{tariffs[key].daily_tokens}</b>)}
        <span>Галерея</span>{tariffKeys.map((key) => <b key={key}>{tariffs[key].gallery_slots} слот.</b>)}
        <span>Модели</span><b>Базовые</b><b>Стандартные</b><b>HD</b><b>Продвинутые</b><b>Бизнес</b>
        <span>Очередь</span><b>Обычная</b><b>Обычная</b><b>Ускоренная</b><b>Приоритетная</b><b>Бизнес</b>
      </section>
      </>}

      {settingsTab === 'earn' && <>
      <section className="usr-section">
        <div className="usr-earn-hero usr-card">
          <h3>Получайте токены</h3>
          <div><span>Текущий баланс</span><strong>{tokenBalance}</strong><small>токенов</small></div>
          <div><span>Ожидает начисления</span><strong>+50</strong><small>за друга или промокод</small></div>
        </div>
        <div className="usr-earn">
          <article className="usr-card usr-earn-card">
            <h4>Промокод</h4>
            <p>Введите промокод и получите награду, если код активен.</p>
            <div className="usr-inline">
              <input value={promoCode} onChange={(e) => { setPromoCode(e.target.value.toUpperCase()); setPromoResult('') }} placeholder="Например START50" aria-label="Промокод" />
              <button type="button" disabled={promoBusy || !promoCode.trim()} onClick={onApplyPromo}>{promoBusy ? 'Проверяем...' : 'Применить'}</button>
            </div>
            <div className={promoResult ? 'usr-reward result' : 'usr-reward'}>{promoResult || '+50 токенов за успешный промокод'}</div>
          </article>

          <article className="usr-card usr-earn-card">
            <h4>Пригласи друга</h4>
            <p>Отправьте другу ссылку. Бонус начислится после регистрации.</p>
            <label>Реферальный код<input readOnly value={friendPromoCode} onFocus={(e) => e.currentTarget.select()} /></label>
            <div className="usr-inline">
              <input readOnly value={referralLink} onFocus={(e) => e.currentTarget.select()} aria-label="Реферальная ссылка" />
              <button type="button" onClick={copyInvite}>Копировать</button>
            </div>
            <div className="usr-reward">{inviteMsg || '+50 токенов за каждого друга'}</div>
          </article>

          <article className="usr-card usr-earn-card">
            <h4>Баланс</h4>
            <p>Токены списываются при генерации. Стоимость зависит от качества и мегаскорости.</p>
            <strong className="usr-token-balance">{tokenBalance} токенов</strong>
            <button type="button" className="usr-primary" disabled>Пополнение скоро</button>
          </article>
        </div>
      </section>
      <section className="usr-card usr-bonus-history">
        <h4>История бонусов</h4>
        <div><span>Сегодня</span><b>Промокод или приглашение</b><strong>+50</strong><em>Начисляется после успешной активации</em></div>
        <div><span>Сейчас</span><b>Реферальный код</b><strong>{friendPromoCode}</strong><em>Скопируйте и отправьте другу</em></div>
      </section>
      </>}

      {settingsTab === 'models' && <>
      <section className="usr-section">
        <div className="usr-model-summary">
          <article className="usr-card usr-stat-card"><span>Баланс токенов</span><strong>{tokenBalance}</strong><small>токенов</small></article>
          <article className="usr-card usr-stat-card"><span>Дневной лимит</span><strong>{dailyUsed} / {dailyLimit}</strong><small>осталось {dailyRemaining}</small></article>
          <article className="usr-card usr-stat-card"><span>Модель по умолчанию</span><strong>{quality === 'fast' ? 'Быстрая' : quality === 'standard' ? 'Стандарт' : 'Максимум'}</strong><small>рекомендуется</small></article>
          <article className="usr-card usr-stat-card"><span>Стоимость</span><strong>{tokenPrice}</strong><small>{tokenPrice === 1 ? 'токен' : 'токена'}</small></article>
        </div>
        <div className="usr-section-head"><h3>Модели и стоимость</h3><span>Стоимость будет показана перед генерацией</span></div>
        <div className="usr-models">
          <button type="button" className={quality === 'fast' ? 'usr-card usr-model active' : 'usr-card usr-model'} onClick={() => setQuality('fast')}><Sparkles size={26} /><b>Быстрая</b><span>1 токен</span></button>
          <button type="button" className={quality === 'standard' ? 'usr-card usr-model active' : 'usr-card usr-model'} onClick={() => setQuality('standard')}><WandSparkles size={26} /><b>Стандарт</b><span>2 токена</span></button>
          <button type="button" className={quality === 'max' ? 'usr-card usr-model active' : 'usr-card usr-model'} onClick={() => setQuality('max')}><SlidersHorizontal size={26} /><b>Максимум</b><span>4 токена</span></button>
          <button type="button" className={provider === 'openrouter' ? 'usr-card usr-model active' : 'usr-card usr-model'} onClick={() => setProvider(provider === 'openrouter' ? 'comfyui' : 'openrouter')}><Zap size={26} /><b>Мегаскорость</b><span>{provider === 'openrouter' ? 'Включена' : 'Выключена'}</span></button>
        </div>
        <div className="usr-estimate"><span>Выбрано: <strong>{quality === 'fast' ? 'Быстрая' : quality === 'standard' ? 'Стандарт' : 'Максимум'}</strong></span><span>Примерная стоимость: <strong>{tokenPrice} {tokenPrice === 1 ? 'токен' : 'токена'}</strong></span></div>
      </section>

      <section className="usr-section">
        <h3>Параметры генерации</h3>
        <div className="usr-generation">
          <article className="usr-card usr-small-card">
            <h4>Размер по умолчанию</h4>
            <p>Формат можно менять перед каждой генерацией.</p>
            <div className="usr-size-options">
              {resolutionPresets.map((item) => {
                const selectedSize = width === item.width && height === item.height
                return <button type="button" className={selectedSize ? 'active' : ''} key={item.label} onClick={() => { setWidth(item.width); setHeight(item.height) }}>{item.label}</button>
              })}
            </div>
          </article>
          <article className="usr-card usr-small-card">
            <h4>Доступ к галерее</h4>
            <p>Ваш текущий доступ: <strong>{galleryUsed}/{gallerySlots}</strong>. Свободно слотов: <strong>{galleryFree}</strong>.</p>
            <button type="button" className="usr-ghost" disabled={!openGallery} onClick={() => openGallery?.()}>Перейти в галерею</button>
          </article>
        </div>
      </section>
      </>}
    </section>
  )
}

function AdminLogsView({ data, provider, admin }: { data: Record<string, unknown> | null; provider: string; admin?: Record<string, unknown> }) {
  const [logTab, setLogTab] = useState<'overview' | 'backend' | 'models' | 'tasks' | 'auth' | 'audit' | 'config'>('overview')
  const summary = (data?.summary || {}) as Record<string, unknown>
  const comfy = (data?.comfyui || {}) as Record<string, unknown>
  const backend = (data?.backend || {}) as Record<string, unknown>
  const profiles = Array.isArray(comfy.profiles) ? comfy.profiles as Record<string, unknown>[] : []
  const activeJobs = Array.isArray(data?.active_jobs) ? data.active_jobs as Record<string, unknown>[] : []
  const generationErrors = Array.isArray(data?.generation_errors) ? data.generation_errors as Record<string, unknown>[] : []
  const eventLogs = Array.isArray(data?.event_logs) ? data.event_logs as Record<string, unknown>[] : []
  const securityEvents = Array.isArray(data?.security_events) ? data.security_events as Record<string, unknown>[] : []
  const auditLogs = Array.isArray(data?.audit_logs) ? data.audit_logs as Record<string, unknown>[] : []
  const formatTime = (value: unknown) => {
    if (!value) return '—'
    const date = new Date(String(value))
    if (Number.isNaN(date.getTime())) return String(value)
    return date.toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' })
  }
  const severityClass = (value: unknown) => {
    const normalized = String(value || '').toLowerCase()
    if (['error', 'critical', 'fatal', 'failed'].some((item) => normalized.includes(item))) return 'danger'
    if (['warning', 'warn', 'spoof', 'failed_login'].some((item) => normalized.includes(item))) return 'warning'
    if (['approved', 'success', 'online', 'ok'].some((item) => normalized.includes(item))) return 'success'
    return 'info'
  }
  const logItem = (item: {
    key: string
    time?: unknown
    source?: unknown
    title: unknown
    meta?: unknown
    extra?: unknown
    level?: unknown
  }) => (
    <div className={`admin-log-item ${severityClass(item.level || item.title || item.meta)}`} key={item.key}>
      <time>{formatTime(item.time)}</time>
      <em>{String(item.source || 'system')}</em>
      <div>
        <strong>{String(item.title || '—')}</strong>
        {item.meta ? <span>{String(item.meta)}</span> : null}
        {item.extra ? <small>{String(item.extra)}</small> : null}
      </div>
    </div>
  )
  const modelRows = profiles.map((p) => {
    const missing = Array.isArray(p.missingFiles) ? p.missingFiles.map(String) : []
    return logItem({ key: String(p.id || p.name), source: 'model', title: p.name || p.id, meta: `${p.baseEdit || '—'} · pose ${p.pose || '—'}`, extra: missing.length ? `missing: ${missing.join(', ')}` : undefined, level: missing.length ? 'warning' : 'ok' })
  })
  const taskRows = activeJobs.map((j, index) => logItem({ key: `${String(j.id || 'job')}-${index}`, time: j.createdAt, source: 'queue', title: j.id, meta: `${j.status || '—'} · ${j.mode || '—'} · ${j.provider || '—'}`, extra: j.message, level: j.status }))
  const generationRows = generationErrors.map((e, index) => logItem({ key: `${String(e.id || 'error')}-${index}`, time: e.completed_at || e.created_at, source: 'generation', title: e.id, meta: `${e.mode || '—'} · ${e.provider || '—'}`, extra: e.error, level: 'error' }))
  const securityRows = securityEvents.slice(0, 30).map((e, index) => logItem({ key: `${String(e.event_type || 'security')}-${index}`, time: e.created_at, source: 'security', title: e.event_type, meta: e.severity, extra: e.ip_address, level: e.severity || e.event_type }))
  const eventRows = eventLogs.slice(0, 30).map((e, index) => logItem({ key: `${String(e.event_name || 'event')}-${index}`, time: e.created_at, source: e.platform || 'auth', title: e.event_name, meta: e.platform, extra: e.ip_address, level: e.event_name }))
  const auditRows = auditLogs.slice(0, 30).map((e, index) => logItem({ key: `${String(e.action || 'audit')}-${index}`, time: e.created_at, source: 'audit', title: e.action, meta: e.entity_type, extra: e.target ? `target ${e.target}` : undefined, level: e.action }))
  const showRows = (rows: ReactNode[], empty: string) => <div className="admin-log-table">{rows.length ? rows : <p className="admin-empty-line">{empty}</p>}</div>
  return (
    <div className="admin-section">
      <div className="admin-section-head compact">
        <h3>Контроль систем</h3>
        <small>{String(summary.active_jobs ?? activeJobs.length)} задач · {String(summary.generation_errors_db ?? admin?.errors ?? 0)} ошибок генерации · {String(summary.failed_logins_24h ?? admin?.errors24h ?? 0)} ошибок входа</small>
      </div>
      <div className="admin-healthline">
        <span className={comfy.available ? 'ok' : 'danger'}>ComfyUI: {comfy.available ? 'online' : 'offline'}</span>
        <span>Backend: {String(backend.build || 'unknown')}</span>
        <span>Старт: {formatTime(backend.started_at)}</span>
        <span>Обновлено: {formatTime(data?.generated_at)}</span>
      </div>
      <div className="admin-grid admin-grid-compact">
        <div><strong>ComfyUI</strong><span>{comfy.available ? 'online' : 'offline'}</span><small>локальный генератор</small></div>
        <div><strong>Активные задачи</strong><span>{String(summary.active_jobs ?? activeJobs.length)}</span><small>queue/running/uploading</small></div>
        <div><strong>Ошибки генерации</strong><span>{String(summary.generation_errors_db ?? admin?.errors ?? 0)}</span><small>failed jobs в базе</small></div>
        <div><strong>Ошибки входа 24ч</strong><span>{String(summary.failed_logins_24h ?? admin?.errors24h ?? 0)}</span><small>password/auth attempts</small></div>
      </div>
      <div className="admin-log-tabs">
        {[
          ['overview', 'Все'],
          ['backend', 'Backend'],
          ['models', 'Модели'],
          ['tasks', 'Задачи'],
          ['auth', 'Входы'],
          ['audit', 'Аудит'],
          ['config', 'Config'],
        ].map(([id, label]) => <button key={id} className={logTab === id ? 'active' : ''} onClick={() => setLogTab(id as typeof logTab)}>{label}</button>)}
      </div>
      {logTab === 'overview' && showRows([...generationRows.slice(0, 8), ...securityRows.slice(0, 8), ...eventRows.slice(0, 8)], 'Событий пока нет.')}
      {logTab === 'backend' && showRows([
        logItem({ key: 'backend-build', source: 'backend', title: 'build', meta: backend.build || 'unknown', extra: `started ${formatTime(backend.started_at)}`, level: 'ok' }),
        logItem({ key: 'backend-route', source: 'backend', title: 'route', meta: provider === 'openrouter' ? 'OpenRouter Cloud' : 'ComfyUI локально', extra: `updated ${formatTime(data?.generated_at)}`, level: comfy.available ? 'ok' : 'warning' }),
      ], 'Backend-данные не загружены.')}
      {logTab === 'models' && showRows(modelRows, 'Профили моделей не загружены.')}
      {logTab === 'tasks' && showRows([...taskRows, ...generationRows], 'Очередь пуста, ошибок генерации нет.')}
      {logTab === 'auth' && showRows([...securityRows, ...eventRows], 'Событий входа нет.')}
      {logTab === 'audit' && showRows(auditRows, 'Audit logs нет.')}
      {logTab === 'config' && <details open className="admin-config-details"><summary>Сводка конфигурации</summary><pre>{JSON.stringify({ backend, summary, admin }, null, 2)}</pre></details>}
    </div>
  )
}

type AdminMailStatus = {
  ok?: boolean
  generated_at?: string
  service_ready?: boolean
  status?: string
  provider?: string | null
  environment?: string
  otp_available?: boolean
  delivery_implemented?: boolean
  debug_return_code?: boolean
  config?: Record<string, boolean>
  summary?: Record<string, number>
  templates?: Array<Record<string, unknown>>
  recent_challenges?: Array<Record<string, unknown>>
  recent_attempts?: Array<Record<string, unknown>>
  mock_outbox?: Array<Record<string, unknown>>
}

function AdminMailView() {
  const [data, setData] = useState<AdminMailStatus | null>(null)
  const [loading, setLoading] = useState(false)
  const [testEmail, setTestEmail] = useState('')
  const [msg, setMsg] = useState('')
  const load = useCallback(async () => {
    setLoading(true)
    try {
      const result = await apiFetch('/admin/mail/status-v2').then((r) => (r.ok ? r.json() : null)).catch(() => null)
      setData(result)
    } finally {
      setLoading(false)
    }
  }, [])
  useEffect(() => { queueMicrotask(() => { void load() }) }, [load])
  const sendTest = async () => {
    setMsg('')
    const res = await apiFetch('/admin/mail/test-v2', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: testEmail, template: 'verify_email' }),
    }).then(async (r) => ({ ok: r.ok, status: r.status, body: await r.json().catch(() => ({})) })).catch(() => ({ ok: false, status: 0, body: {} }))
    setMsg(res.ok ? `Тест отправлен на ${String(res.body.email || '')}` : `Не отправлено: ${String(res.body.detail || res.status || 'network_error')}`)
    await load()
  }
  const summary = data?.summary || {}
  const config = data?.config || {}
  const statusText = data?.service_ready ? 'Готово к отправке' : data?.status === 'provider_adapter_missing' ? 'Нужен адаптер провайдера' : 'Провайдер не настроен'
  const row = (item: Record<string, unknown>, index: number) => <tr key={index}>{Object.entries(item).slice(0, 6).map(([k, v]) => <td key={k}><small>{k}</small><span>{String(v ?? '—')}</span></td>)}</tr>
  return <div className="admin-section admin-mail-page">
    <div className="admin-section-headline">
      <div>
        <h3>Почта</h3>
        <p>Доменная почта, подтверждение email, поддержка и журнал отправок.</p>
      </div>
      <button className="secondary" onClick={() => void load()} disabled={loading}>{loading ? 'Обновляю…' : 'Обновить'}</button>
    </div>
    <div className="admin-grid admin-grid-compact">
      <div><strong>Сервис</strong><span>{statusText}</span><small>{data?.provider || 'EMAIL_PROVIDER не задан'}</small></div>
      <div><strong>OTP</strong><span>{String(summary.otp_24h ?? 0)}</span><small>кодов за 24 часа</small></div>
      <div><strong>Активные</strong><span>{String(summary.otp_active ?? 0)}</span><small>ожидают подтверждения</small></div>
      <div><strong>Подтверждено</strong><span>{String(summary.otp_consumed_24h ?? 0)}</span><small>за 24 часа</small></div>
    </div>
    <div className="admin-mail-grid">
      <article className="admin-mail-card">
        <h4>Конфигурация</h4>
        <div className="admin-mail-flags">
          {['EMAIL_PROVIDER', 'EMAIL_FROM', 'SMTP_HOST', 'SMTP_PORT', 'SUPPORT_EMAIL'].map((key) => <span key={key} className={config[key] ? 'ok' : 'warn'}>{key}: {config[key] ? 'yes' : 'no'}</span>)}
          <span className={data?.delivery_implemented ? 'ok' : 'warn'}>delivery adapter: {data?.delivery_implemented ? 'yes' : 'no'}</span>
          <span className={data?.debug_return_code ? 'warn' : 'ok'}>debug code: {data?.debug_return_code ? 'on' : 'off'}</span>
        </div>
        <p>Для доменной отправки нужно настроить реальный провайдер и `EMAIL_FROM` на вашем домене. Секреты в админку не выводятся.</p>
      </article>
      <article className="admin-mail-card">
        <h4>Тест письма</h4>
        <label>Email<input type="email" value={testEmail} onChange={(e) => setTestEmail(e.target.value)} placeholder="test@example.com" /></label>
        <button className="secondary" onClick={() => void sendTest()} disabled={!testEmail.trim()}>Отправить тест OTP</button>
        {msg && <p className={msg.startsWith('Тест') ? 'crm-action-ok' : 'crm-err'}>{msg}</p>}
      </article>
      <article className="admin-mail-card">
        <h4>Шаблоны</h4>
        {(data?.templates || []).map((tpl) => <div className="admin-mail-template" key={String(tpl.id)}><strong>{String(tpl.title)}</strong><span>{String(tpl.subject)}</span><small>{String(tpl.status)}</small></div>)}
      </article>
    </div>
    <div className="admin-mail-tables">
      <article><h4>Последние коды</h4><table><tbody>{(data?.recent_challenges || []).map(row)}</tbody></table>{!data?.recent_challenges?.length && <p>Событий нет.</p>}</article>
      <article><h4>Попытки email-входа</h4><table><tbody>{(data?.recent_attempts || []).map(row)}</tbody></table>{!data?.recent_attempts?.length && <p>Попыток нет.</p>}</article>
    </div>
  </div>
}

function AdminView({ copy, admin, setAdmin, tariffs, setTariffs, backToStudio, provider }: { copy: Copy; admin?: Record<string, unknown>; setAdmin: Dispatch<SetStateAction<Record<string, unknown> | undefined>>; tariffs: TariffConfig; setTariffs: Dispatch<SetStateAction<TariffConfig>>; backToStudio: () => void; provider: string }) {
  const [tab, setTab] = useState<'dashboard' | 'mail' | 'models' | 'tariffs' | 'users' | 'queue' | 'logs'>('dashboard')
  const [limits, setLimits] = useState({ hourly: 0, daily: 0 })
  const [saved, setSaved] = useState('')
  const [promoDraft, setPromoDraft] = useState({ code: 'START50', tokens: 50, activations: 100 })
  const [finance, setFinance] = useState({ tokenRevenue: 0, tokenCost: 0, electricity: 0, promoBudget: 0 })
  const [tariffConfig, setTariffConfig] = useState<TariffConfig>(tariffs)
  const [promoCodes, setPromoCodes] = useState<PromoCode[]>([])
  const [logsData, setLogsData] = useState<Record<string, unknown> | null>(null)
  const [adminMessage, setAdminMessage] = useState('')
  const [dashboardRange, setDashboardRange] = useState<DashboardRange>(24)
  const queue = Array.isArray(admin?.queue) ? admin.queue : []
  const generationErrors = Number(admin?.errors ?? 0)
  const health = generationErrors === 0 ? 'Стабильно' : `Ошибки генерации: ${generationErrors}`
  const adminFinance = (admin?.finance || {}) as Record<string, number>
  useEffect(() => { queueMicrotask(() => setTariffConfig(tariffs)) }, [tariffs])
  async function saveLimits() {
    const result = await apiFetch('/admin/limits', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(limits) }).then((r) => r.json())
    setSaved(JSON.stringify(result.rateLimits))
  }
  const refreshTokenAdminData = useCallback(async () => {
    const [promos, settings] = await Promise.all([
      apiFetch('/admin/promos').then((r) => r.json()).catch(() => []),
      apiFetch('/admin/settings').then((r) => r.json()).catch(() => ({})),
    ])
    setPromoCodes(promos)
    if (settings.finance) setFinance((current) => ({ ...current, ...settings.finance }))
    if (settings.tariffs) {
      const normalized = normalizeTariffs(settings.tariffs)
      setTariffConfig(normalized)
      setTariffs(normalized)
    }
  }, [setTariffs])
  useEffect(() => { if (tab === 'tariffs') queueMicrotask(() => { void refreshTokenAdminData() }) }, [tab, refreshTokenAdminData])
  useEffect(() => {
    if (tab !== 'dashboard') return undefined
    let cancelled = false
    const refreshDashboard = async () => {
      const data = await apiFetch('/admin/summary').then((r) => (r.ok ? r.json() : null)).catch(() => null)
      if (!cancelled && data) setAdmin(data)
    }
    void refreshDashboard()
    const timer = window.setInterval(() => { void refreshDashboard() }, 30000)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [tab, dashboardRange, setAdmin])
  useEffect(() => {
    if (tab !== 'logs') return
    void apiFetch('/admin/logs-v2').then((r) => (r.ok ? r.json() : null)).then(setLogsData).catch(() => setLogsData(null))
  }, [tab])
  async function saveFinance() {
    const result = await apiFetch('/admin/settings/finance', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ settings: finance }) }).then((r) => r.json())
    setAdminMessage(result.ok ? 'Финансы сохранены' : 'Ошибка сохранения')
  }
  async function saveTariffs() {
    const result = await apiFetch('/admin/settings/tariffs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ settings: tariffConfig }) }).then((r) => r.json())
    if (result.ok) {
      const normalized = normalizeTariffs(result.settings)
      setTariffConfig(normalized)
      setTariffs(normalized)
      setAdminMessage('Тарифы сохранены')
    } else {
      setAdminMessage(String(result.detail || 'Ошибка сохранения тарифов'))
    }
  }
  async function createPromo() {
    const result = await apiFetch('/admin/promos', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ code: promoDraft.code, tokens: Number(promoDraft.tokens), activationLimit: Number(promoDraft.activations) }) }).then((r) => r.json())
    setAdminMessage(result.ok ? `Промокод ${result.promo.code} сохранен` : 'Ошибка промокода')
    await refreshTokenAdminData()
  }
  const kpi = (title: string, value: unknown, note: string) => <div><strong>{title}</strong><span>{String(value ?? '—')}</span><small>{note}</small></div>
  const timeline = (admin?.timeline || {}) as AdminTimeline
  const isHourlyDashboardRange = HOURLY_DASHBOARD_RANGES.has(dashboardRange)
  const sliceSeries = (key: string): TimelinePoint[] => {
    const sourceKey = isHourlyDashboardRange ? `${key}_${dashboardRange}h` : key
    const source = Array.isArray(timeline[sourceKey]) ? timeline[sourceKey] : []
    return isHourlyDashboardRange ? source : source.slice(-dashboardRange)
  }
  const shortDate = (date: string) => {
    if (date.includes('T')) {
      const parsedHour = new Date(date)
      return Number.isNaN(parsedHour.getTime()) ? date.slice(11, 16) : parsedHour.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
    }
    const parsed = new Date(`${date}T00:00:00`)
    return Number.isNaN(parsed.getTime()) ? date.slice(5) : parsed.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit' })
  }
  const lineChart = (title: string, key: string, note: string, color = '#dfff22') => {
    const rows = sliceSeries(key)
    const max = Math.max(1, ...rows.map((p) => Number(p.value) || 0))
    const width = 460
    const height = 176
    const padLeft = 40
    const padRight = 14
    const padTop = 18
    const padBottom = 30
    const plotWidth = width - padLeft - padRight
    const plotHeight = height - padTop - padBottom
    const points = rows.map((p, index) => {
      const x = padLeft + (rows.length <= 1 ? 0 : (index / (rows.length - 1)) * plotWidth)
      const y = padTop + plotHeight - ((Number(p.value) || 0) / max) * plotHeight
      return `${x.toFixed(1)},${y.toFixed(1)}`
    }).join(' ')
    const total = rows.reduce((sum, p) => sum + (Number(p.value) || 0), 0)
    const last = rows.at(-1)?.value ?? 0
    const average = rows.length ? Math.round(total / rows.length) : 0
    const peak = rows.reduce((best, point) => (Number(point.value) > Number(best.value) ? point : best), rows[0] || { date: '', value: 0 })
    const tickStep = rows.length <= 12 ? 3 : rows.length <= 24 ? 6 : dashboardRange === 7 ? 2 : dashboardRange === 30 ? 10 : 30
    const dateTicks = rows.filter((_, index) => index === 0 || index === rows.length - 1 || index % tickStep === 0)
    const valueTicks = Array.from(new Set([max, Math.round(max * 0.75), Math.round(max * 0.5), Math.round(max * 0.25), 0])).sort((a, b) => b - a)
    const verticalTicks = rows.filter((_, index) => index === 0 || index === rows.length - 1 || index % tickStep === 0)
    const valueLabels = rows.filter((point, index) => Number(point.value || 0) > 0 && (index === rows.length - 1 || Number(point.value) === Number(peak.value)))
    return (
      <article className="admin-line-chart">
        <header><h3>{title}</h3><p className="admin-line-meta">Сумма {total.toLocaleString('ru-RU')} · пик {Number(peak.value || 0).toLocaleString('ru-RU')} {shortDate(peak.date)} · среднее {average.toLocaleString('ru-RU')} · сейчас {Number(last || 0).toLocaleString('ru-RU')}</p></header>
        <svg viewBox={`0 0 ${width} ${height}`} aria-label={title}>
          {valueTicks.map((value) => {
            const y = padTop + plotHeight - (value / max) * plotHeight
            return <g key={`y-${value}-${y}`}><line className="grid horizontal" x1={padLeft} x2={width - padRight} y1={y} y2={y} /><text className="axis value" x={8} y={y + 5}>{value.toLocaleString('ru-RU')}</text></g>
          })}
          {verticalTicks.map((point, index) => {
            const rowIndex = rows.indexOf(point)
            const x = padLeft + (rows.length <= 1 ? 0 : (rowIndex / (rows.length - 1)) * plotWidth)
            return <line className="grid vertical" key={`v-${point.date}-${index}`} x1={x} x2={x} y1={padTop} y2={padTop + plotHeight} />
          })}
          {dateTicks.map((point, index) => {
            const rowIndex = rows.indexOf(point)
            const x = padLeft + (rows.length <= 1 ? 0 : (rowIndex / (rows.length - 1)) * plotWidth)
            return <text className="axis date" key={`${point.date}-${index}`} x={x} y={height - 10}>{shortDate(point.date)}</text>
          })}
          <polyline points={points} style={{ stroke: color }} />
          {rows.map((point, index) => {
            const rowIndex = rows.indexOf(point)
            const x = padLeft + (rows.length <= 1 ? 0 : (rowIndex / (rows.length - 1)) * plotWidth)
            const y = padTop + plotHeight - ((Number(point.value) || 0) / max) * plotHeight
            return <circle key={`${point.date}-${index}`} cx={x} cy={y} r={Number(point.value || 0) > 0 ? 4 : 2.2} style={{ fill: color }}><title>{shortDate(point.date)}: {Number(point.value || 0).toLocaleString('ru-RU')}</title></circle>
          })}
          {valueLabels.map((point, index) => {
            const rowIndex = rows.indexOf(point)
            const x = padLeft + (rows.length <= 1 ? 0 : (rowIndex / (rows.length - 1)) * plotWidth)
            const y = padTop + plotHeight - ((Number(point.value) || 0) / max) * plotHeight
            const labelY = Math.max(14, y - 9)
            return <text className="axis point-value" key={`label-${point.date}-${index}`} x={x} y={labelY}>{Number(point.value || 0).toLocaleString('ru-RU')}</text>
          })}
        </svg>
        <footer><small>{note}</small><b>{rows[0]?.date ? `${shortDate(rows[0].date)} - ${shortDate(rows.at(-1)?.date || rows[0].date)}` : `${dashboardRange} ${isHourlyDashboardRange ? 'ч' : 'дней'}`}</b></footer>
      </article>
    )
  }
  return <section className="admin-page">
    <div className="admin-topline">
      <button className="secondary" onClick={backToStudio}><WandSparkles size={16} />{copy.backToStudio}</button>
      <span className={generationErrors === 0 ? 'admin-live-ok' : 'admin-live-warn'}>{health}</span>
      {adminMessage && <small>{adminMessage}</small>}
    </div>
    <div className="admin-kpi-strip">
      <span><b>{String(admin?.users ?? '—')}</b> пользователей</span>
      <span><b>{String(admin?.activeToday ?? '—')}</b> сегодня</span>
      <span><b>{String(admin?.generationsToday ?? '—')}</b> генераций</span>
      <span><b>{String(admin?.errors24h ?? '—')}</b> ошибок входа 24ч</span>
      <span><b>{String(admin?.errors ?? '—')}</b> ошибок генерации</span>
    </div>
    <div className="admin-tabbar">{[['dashboard', 'Дашборд'], ['mail', 'Почта'], ['models', 'Модели'], ['tariffs', 'Тарифы'], ['users', 'Пользователи'], ['queue', 'Очередь'], ['logs', 'Логи']].map(([id, label]) => <button key={id} className={tab === id ? 'active' : ''} onClick={() => setTab(id as typeof tab)}>{label}</button>)}</div>
    {tab === 'dashboard' && <div className="admin-section admin-dashboard-v2">
      <div className="admin-grid admin-grid-compact">
        {kpi(copy.users, admin?.users, 'аккаунтов в базе')}
        {kpi('Сегодня', admin?.activeToday, 'активных пользователей')}
        {kpi('Генерации', admin?.generationsToday, 'создано сегодня')}
        {kpi('Сессии', admin?.activeSessions, 'активны сейчас')}
        {kpi('Ошибки входа', admin?.errors24h, 'за 24 часа')}
        {kpi('Ошибки генерации', admin?.errors, 'failed jobs')}
      </div>
      <div className="admin-dashboard-toolbar">
        <strong>Графики по времени</strong>
        {[
          [1, '1 час'],
          [6, '6 часов'],
          [12, '12 часов'],
          [24, 'сутки'],
          [7, '7 дней'],
          [30, '30 дней'],
          [90, '90 дней'],
        ].map(([range, label]) => <button key={range} className={dashboardRange === range ? 'active' : ''} onClick={() => setDashboardRange(range as DashboardRange)}>{label}</button>)}
      </div>
      <div className="admin-chart-grid">
        {lineChart('Активность пользователей', 'active_users', 'last_seen по дням')}
        {lineChart('Новые пользователи', 'registrations', 'созданные аккаунты', '#72ff69')}
        {lineChart('Успешные входы', 'logins', 'login/register события', '#64b5ff')}
        {lineChart('Ошибки входа', 'login_errors', 'неудачные auth попытки', '#ffd45c')}
        {lineChart('Генерации', 'generations', 'старты генераций', '#dfff22')}
        {lineChart('Ошибки генерации', 'generation_errors', 'failed jobs', '#ff6b6b')}
      </div>
      {Boolean(admin?.finance) && <div className="admin-grid admin-grid-compact">
        {kpi('Доход', `${Number(adminFinance.tokenRevenue ?? 0).toLocaleString('ru-RU')} ₽`, 'оценка')}
        {kpi('Себестоимость', `${Number(adminFinance.tokenCost ?? 0).toLocaleString('ru-RU')} ₽`, 'оценка')}
        {kpi('Свет', `${Number(adminFinance.electricity ?? 0).toLocaleString('ru-RU')} ₽`, 'оценка')}
        {kpi('Акции', `${Number(adminFinance.promoBudget ?? 0).toLocaleString('ru-RU')} ₽`, 'оценка')}
      </div>}
    </div>}
    {tab === 'mail' && <AdminMailView />}
    {tab === 'models' && <div className="admin-section"><Suspense fallback={<div className="preview-empty">Загружаем модели...</div>}><AdminModelsV2 /></Suspense></div>}
    {tab === 'tariffs' && <div className="admin-section"><h3>Тарифы, токены, финансы и акции</h3><div className="admin-two-col"><article><h3>{copy.limits}</h3><label>hourly<input type="number" value={limits.hourly} onChange={(e) => setLimits({ ...limits, hourly: Number(e.target.value) })} /></label><label>daily<input type="number" value={limits.daily} onChange={(e) => setLimits({ ...limits, daily: Number(e.target.value) })} /></label><button className="secondary" onClick={saveLimits}>{copy.save}</button><small>{saved}</small></article><article><h3>Финансы</h3><label>Доход от токенов<input type="number" value={finance.tokenRevenue} onChange={(e) => setFinance({ ...finance, tokenRevenue: Number(e.target.value) })} /></label><label>Себестоимость API<input type="number" value={finance.tokenCost} onChange={(e) => setFinance({ ...finance, tokenCost: Number(e.target.value) })} /></label><label>Свет<input type="number" value={finance.electricity} onChange={(e) => setFinance({ ...finance, electricity: Number(e.target.value) })} /></label><label>Акции<input type="number" value={finance.promoBudget} onChange={(e) => setFinance({ ...finance, promoBudget: Number(e.target.value) })} /></label><button className="secondary" onClick={saveFinance}>Сохранить финансы</button></article><article><h3>Промокод</h3><label>Код<input value={promoDraft.code} onChange={(e) => setPromoDraft({ ...promoDraft, code: e.target.value.toUpperCase() })} /></label><label>Токены<input type="number" value={promoDraft.tokens} onChange={(e) => setPromoDraft({ ...promoDraft, tokens: Number(e.target.value) })} /></label><label>Активации<input type="number" value={promoDraft.activations} onChange={(e) => setPromoDraft({ ...promoDraft, activations: Number(e.target.value) })} /></label><button className="secondary" onClick={createPromo}>Создать промокод</button></article><article><h3>Промокоды в базе</h3>{promoCodes.length ? promoCodes.map((item) => <p key={item.code}><b>{item.code}</b>: {item.tokens} ток. · {item.activation_count}/{item.activation_limit}</p>) : <p>Промокодов пока нет.</p>}</article></div><div className="admin-grid">{tariffKeys.map((planKey) => <div key={planKey}><strong>{planKey.toUpperCase()}</strong><span>{tariffConfig[planKey].daily_tokens} ток.</span><small>{tariffConfig[planKey].gallery_slots} слот(ов) галереи</small></div>)}</div></div>}
    {tab === 'tariffs' && <div className="admin-section"><h3>Настройки тарифов</h3><p>Единый источник для Settings, Gallery и CRM: токены в сутки и слоты галереи.</p><div className="admin-grid">{tariffKeys.map((planKey) => <div key={planKey}><strong>{planKey.toUpperCase()}</strong><label>Токенов/день<input type="number" min="0" value={tariffConfig[planKey].daily_tokens} onChange={(e) => setTariffConfig((current) => ({ ...current, [planKey]: { ...current[planKey], daily_tokens: Number(e.target.value) } }))} /></label><label>Слоты галереи<input type="number" min="0" value={tariffConfig[planKey].gallery_slots} onChange={(e) => setTariffConfig((current) => ({ ...current, [planKey]: { ...current[planKey], gallery_slots: Number(e.target.value) } }))} /></label><small>{tariffConfig[planKey].daily_tokens} ток./день · {tariffConfig[planKey].gallery_slots} слот(ов)</small></div>)}</div><button className="secondary" onClick={() => void saveTariffs()}>Сохранить тарифы</button></div>}
    {tab === 'users' && <div className="admin-section"><Suspense fallback={<div className="preview-empty">Загружаем аналитику...</div>}><AdminAnalyticsV2 /></Suspense></div>}
    {tab === 'queue' && <div className="admin-section"><h3>Очередь генераций</h3><div className="admin-grid"><div><strong>В очереди</strong><span>{queue.length}</span><small>ожидают запуска</small></div><div><strong>Провайдер</strong><span>{provider}</span><small>текущий маршрут</small></div><div><strong>Сегодня</strong><span>{String(admin?.completedToday ?? 0)}</span><small>выполнено</small></div></div><pre>{JSON.stringify(queue, null, 2)}</pre></div>}
    {tab === 'logs' && <AdminLogsView data={logsData} provider={provider} admin={admin} />}

  </section>
}

export default App
