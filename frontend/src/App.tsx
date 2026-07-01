import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ChangeEvent, Dispatch, MutableRefObject, SetStateAction } from 'react'
import {
  AuthV2Modal,
  initAuthV2,
  updateProfileV2,
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
  EDIT_SLOT_COUNT, DEFAULT_EDIT_STRENGTH, EDIT_REFERENCE_ROLES, EDIT_REFERENCE_ROLE_LABELS,
  EDIT_TEMPLATES, editComposerStatus,
  type EditReferenceRole, type EditSlot, type EditTemplate,
} from './editPrompt'
import { AdminAnalyticsV2 } from './adminAnalytics'
import AdminModelsV2 from './adminModels'
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

type TariffKey = 'free' | 'mini' | 'plus' | 'pro'
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

const tariffKeys: TariffKey[] = ['free', 'mini', 'plus', 'pro']
const DEFAULT_TARIFFS: TariffConfig = {
  free: { daily_tokens: 10, gallery_slots: 1 },
  mini: { daily_tokens: 50, gallery_slots: 10 },
  plus: { daily_tokens: 100, gallery_slots: 50 },
  pro: { daily_tokens: 200, gallery_slots: 100 },
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
  { label: '1920 × 1088', width: 1920, height: 1088 },
  { label: '1088 × 1920', width: 1088, height: 1920 },
  { label: '1280 × 720', width: 1280, height: 720 },
  { label: '720 × 1280', width: 720, height: 1280 },
]
const avatarPresets = Array.from({ length: 10 }, (_, index) => {
  const id = `preset-${index + 1}`
  return { id, url: `/avatars/${id}.svg`, label: `Аватар ${index + 1}` }
})
// Старые статичные каталоги (openRouterImageModels / localFluxProfiles) удалены:
// их заменил provider-aware экран «Админ → Модели v2» (adminModels.tsx + /api/admin/models-page).
const sessionParams = new URLSearchParams(window.location.search)
const SESSION_USER_ID = sessionParams.get('userId') || window.localStorage.getItem('onenode_user') || 'demo_user'
window.localStorage.setItem('onenode_user', SESSION_USER_ID)

function apiFetch(path: string, init: RequestInit = {}) {
  const headers = new Headers(init.headers)
  headers.set('X-OneNode-User', window.localStorage.getItem('onenode_user') || SESSION_USER_ID)
  return fetch(`${API}${path}`, { ...init, headers, credentials: 'include' })
}

const modes: Array<{ id: Mode; ru: string; en: string; shortRu: string; shortEn: string }> = [
  { id: 'text_to_image', ru: 'Текст стрелка вправо Изо', en: 'Text arrow right Image', shortRu: 'Текст → Изо', shortEn: 'Text → Img' },
  { id: 'image_to_image', ru: 'Изо стрелка вправо Изо', en: 'Image arrow right Image', shortRu: 'Изо → Изо', shortEn: 'Img → Img' },
  { id: 'edit', ru: 'Редактирование Изо', en: 'Edit Image', shortRu: 'Редактор', shortEn: 'Edit' },
  { id: 'paint', ru: 'Рисование Изо', en: 'Paint Image', shortRu: 'Рисовать', shortEn: 'Paint' },
  { id: 'faceswap', ru: 'Лицо стрелка вправо Изо', en: 'Face arrow right Image', shortRu: 'Лицо → Изо', shortEn: 'Face → Img' },
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
    useAsImageToImage: 'Изо → Изо',
    useAsEditOne: 'Редактор: основа',
    useAsEditTwo: 'Редактор: референс',
    useAsPaint: 'Рисование',
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
    useAsImageToImage: 'Image to Image',
    useAsEditOne: 'Edit: base',
    useAsEditTwo: 'Edit: reference',
    useAsPaint: 'Paint',
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
  { id: 't2i-01', ru: 'Кот на крыше под огромной луной', en: 'Cat under giant moon', mode: 'text_to_image', category: 'Текст → Изо', prompt: 'Пушистый кот сидит на краю старой крыши ночью и смотрит на огромную светящуюся луну над тихим городом. Мягкий сине-серебристый лунный свет, лёгкий ветер двигает шерсть, внизу тёплые огни окон, спокойная мечтательная атмосфера, реалистичные детали, малая глубина резкости, эмоциональный кинематографичный кадр. Все видимые поверхности содержат только абстрактные узоры и световые формы.' },
  { id: 't2i-02', ru: 'Биолюминесцентное море', en: 'Bioluminescent ocean', mode: 'text_to_image', category: 'Текст → Изо', prompt: 'Ночной берег океана с биолюминесцентными волнами, которые светятся голубым светом на тёмном песке. Одинокий человек стоит у воды и смотрит на горизонт. В небе яркие звёзды, вдалеке скалы и мягкий туман. Широкий кинематографичный кадр, реалистичная вода, красивые отражения, магическая спокойная атмосфера. Все видимые детали полностью визуальные, только абстрактные формы и узоры.' },
  { id: 't2i-03', ru: 'Космический корабль над древним городом', en: 'Spaceship over ancient city', mode: 'text_to_image', category: 'Текст → Изо', prompt: 'Гигантский футуристический космический корабль медленно зависает над древним пустынным городом с каменными храмами, факелами и золотой пылью в воздухе. Сцена соединяет древнюю цивилизацию и технологии будущего: светящиеся двигатели, резные башни, парящие дроны, драматичный закат. Эпичная кинематографичная композиция, реалистичный масштаб, дорогой sci-fi fantasy стиль. Все символы и панели выглядят как абстрактные декоративные узоры.' },
  { id: 't2i-04', ru: 'Фараон будущего', en: 'Future pharaoh', mode: 'text_to_image', category: 'Текст → Изо', prompt: 'Футуристический фараон стоит внутри монументального золотого храма с чёрным камнем, парящими голографическими кольцами, голубой энергией и древними геометрическими орнаментами. На персонаже элегантная техно-королевская броня из золота и обсидиана. Симметричная композиция, драматичный свет, роскошная атмосфера древнего будущего. Все орнаменты декоративные и нечитаемые.' },
  { id: 't2i-05', ru: 'Инопланетный рынок', en: 'Alien marketplace', mode: 'text_to_image', category: 'Текст → Изо', prompt: 'Яркий инопланетный рынок на далёкой планете: дружелюбные странные существа, парящие фонари, экзотические растения, светящиеся кристаллы, летающие торговые платформы и мягкий пыльный солнечный свет. Богатое кинематографичное окружение, живые цвета, фантастическая атмосфера, много деталей, широкий ракурс. Все панели и вывески заменены абстрактными световыми формами и декоративными символами.' },
  { id: 't2i-06', ru: 'Дракон над замком', en: 'Dragon over castle', mode: 'text_to_image', category: 'Текст → Изо', prompt: 'Величественный дракон летит над тёмным фэнтези-замком на горной скале во время золотого заката. Внизу водопады, в окнах замка тёплый свет, вокруг облака и птицы. Реалистичные крылья дракона, огромный масштаб, эпичная сказочная атмосфера, кинематографичный широкий кадр. Все архитектурные детали содержат только декоративные нечитаемые узоры.' },
  { id: 't2i-07', ru: 'Киберпанк-персонаж у мотоцикла', en: 'Cyberpunk character with bike', mode: 'text_to_image', category: 'Текст → Изо', prompt: 'Стильный оригинальный киберпанк-персонаж стоит рядом с футуристическим мотоциклом на мокрой неоновой улице ночью. На асфальте отражаются огни, в воздухе дождь, вокруг мягкое свечение мегаполиса. Выразительная поза, модная куртка, реалистичные материалы, дорогой fashion-sci-fi стиль. Все городские панели и световые поверхности содержат только абстрактные формы.' },
  { id: 't2i-08', ru: 'Вилла над океаном', en: 'Villa over ocean', mode: 'text_to_image', category: 'Текст → Изо', prompt: 'Роскошная современная вилла встроена в скалу над спокойным океаном на закате. Огромные стеклянные окна, бесконечный бассейн, тёплый свет внутри, пальмовые тени, мягкое золотое небо. Архитектурная фотография премиального уровня, реалистичные отражения, атмосфера дорогой жизни и мечты. Никаких читаемых элементов, только чистая архитектура и природные формы.' },
  { id: 't2i-09', ru: 'Космический кот-астронавт', en: 'Space cat astronaut', mode: 'text_to_image', category: 'Текст → Изо', prompt: 'Милый пушистый кот в маленьком элегантном космическом шлеме парит внутри уютной кабины космического корабля и смотрит на Землю через круглое окно. Мягкий свет, звёзды за окном, маленькие предметы в невесомости, реалистичная шерсть, очаровательное выражение. Все экраны показывают абстрактные световые формы и декоративные линии.' },
  { id: 't2i-10', ru: 'Город внутри стеклянной сферы', en: 'City in glass sphere', mode: 'text_to_image', category: 'Текст → Изо', prompt: 'Сюрреалистический город находится внутри огромной прозрачной стеклянной сферы, парящей над спокойным океаном. Внутри видны маленькие башни, мосты, сады, светящиеся улицы и облака. На воде мягкие отражения, вокруг драматичное небо. Кинематографичный магический реализм, невозможная архитектура, чистая композиция. Все детали полностью визуальные.' },
  { id: 't2i-11', ru: 'Самурай будущего', en: 'Future samurai', mode: 'text_to_image', category: 'Текст → Изо', prompt: 'Футуристический самурай стоит в туманном бамбуковом лесу. На его броне мягко светятся голубые линии, силуэт меча виден в руке, вокруг падает дождь и стелется туман. Спокойная мощная поза, реалистичные материалы, кинематографичный портрет, древность соединена с технологиями будущего. Все узоры на броне абстрактные и нечитаемые.' },
  { id: 't2i-12', ru: 'Летающий остров', en: 'Flying island', mode: 'text_to_image', category: 'Текст → Изо', prompt: 'Летающий остров высоко в небе: маленький замок, светящиеся деревья, водопады, падающие в облака, птицы и тёплый закат. Эпический фэнтези-пейзаж, широкий кинематографичный кадр, детальные скалы и растения, мягкие облака, атмосфера сказочного путешествия. Все элементы декоративные, без читаемых символов.' },
  { id: 't2i-13', ru: 'Футуристический гиперкар', en: 'Futuristic hypercar', mode: 'text_to_image', category: 'Текст → Изо', prompt: 'Роскошный футуристический гиперкар стоит на мокрой ночной улице мегаполиса. Низкий ракурс камеры, аэродинамический корпус, отражения на дороге, мягкие неоновые огни, кинематографичная автомобильная реклама. Все городские панели и световые поверхности содержат только абстрактные световые блоки и узоры.' },
  { id: 't2i-14', ru: 'Магическая библиотека', en: 'Magic library', mode: 'text_to_image', category: 'Текст → Изо', prompt: 'Огромная магическая библиотека с парящими книгами, светящимися лестницами, тёплым свечным светом, древними деревянными полками и чёрным котом на столе. Уютная фэнтези-атмосфера, золотые лучи, пыль в воздухе, высокая детализация, кинематографичный интерьер. Все книги и страницы содержат только декоративные нечитаемые узоры.' },
  { id: 't2i-15', ru: 'Две луны над океаном', en: 'Two moons over ocean', mode: 'text_to_image', category: 'Текст → Изо', prompt: 'Оригинальный персонаж в длинном плаще стоит на высокой скале над океаном под небом с двумя огромными лунами. Ветер двигает ткань, волны разбиваются о скалы внизу, серебристо-синий свет, эмоциональная фантастическая атмосфера. Реалистичный масштаб, кинематографичный пейзаж. Все детали полностью визуальные.' },
  { id: 't2i-16', ru: 'Маленький робот-питомец', en: 'Tiny robot pet', mode: 'text_to_image', category: 'Текст → Изо', prompt: 'Крошечный милый робот-питомец сидит на мягком пледе возле большого окна с дождём. В комнате тёплый свет лампы, на стекле капли, в глазах робота мягкое свечение. Уютная домашняя sci-fi атмосфера, реалистичные материалы, эмоциональная композиция. Все панели и индикаторы выглядят как абстрактные световые точки.' },
  { id: 't2i-17', ru: 'Портал в древнем лесу', en: 'Portal in ancient forest', mode: 'text_to_image', category: 'Текст → Изо', prompt: 'Светящийся магический портал открывается между древними деревьями в туманном лесу на закате. Голубая и золотая энергия, мох, камни, корни, светлячки, мягкий туман, таинственная атмосфера. Кинематографичная фэнтези-композиция, реалистичная природа. Все символы вокруг портала декоративные и нечитаемые.' },
  { id: 't2i-18', ru: 'Дом у биолюминесцентного леса', en: 'House by glowing forest', mode: 'text_to_image', category: 'Текст → Изо', prompt: 'Современный стеклянный дом стоит на краю светящегося биолюминесцентного леса ночью. Голубые растения, тёплый свет внутри, отражающая вода, лёгкий туман, чистая архитектура, атмосфера уюта и роскоши. Широкоугольная кинематографичная фотография. Все декоративные элементы полностью визуальные.' },
  { id: 't2i-19', ru: 'Дружелюбный инопланетянин', en: 'Friendly alien', mode: 'text_to_image', category: 'Текст → Изо', prompt: 'Дружелюбное элегантное инопланетное существо стоит в спокойной светящейся пустыне под огромной планетой в небе. Плавный органический дизайн, выразительные глаза, мягкий тёплый свет, доброжелательная поза, реалистичная sci-fi атмосфера первого контакта. Все детали декоративные и нечитаемые.' },
  { id: 't2i-20', ru: 'Кафе в облаках', en: 'Cloud cafe', mode: 'text_to_image', category: 'Текст → Изо', prompt: 'Уютное фэнтези-кафе парит среди облаков. Внутри тёплый свет, круглые окна, растения, маленькие дракончики спят рядом с чашками, снаружи золотой рассвет. Магический реализм, мягкая атмосфера, дерево, латунь, уют и сказочность. Все меню, таблички и декоративные поверхности содержат только абстрактные узоры.' },
  { id: 'i2i-01', ru: 'Сделать кинематографично', en: 'Make cinematic', mode: 'image_to_image', category: 'Изо → Изо', prompt: 'Преобразуй исходное изображение в дорогой кинематографичный кадр. Сохрани главный объект, позу, композицию, масштаб и основную идею. Улучши свет: добавь мягкие тени, глубину, объём, атмосферу, красивую цветокоррекцию и реалистичные материалы. Все экраны, вывески, панели и поверхности должны содержать только абстрактные формы, световые линии и декоративные нечитаемые узоры.' },
  { id: 'i2i-02', ru: 'Сделать киберпанк', en: 'Make cyberpunk', mode: 'image_to_image', category: 'Изо → Изо', prompt: 'Преобразуй исходное изображение в ночную киберпанк-сцену. Сохрани главный объект и композицию. Добавь мокрые отражающие поверхности, неоновое свечение, дождь, городские огни, футуристические панели и драматичную атмосферу ночного мегаполиса. Все световые панели и вывески должны быть абстрактными, без читаемых символов.' },
  { id: 'i2i-03', ru: 'Сделать фэнтези', en: 'Make fantasy', mode: 'image_to_image', category: 'Изо → Изо', prompt: 'Преобразуй исходное изображение в магическую фэнтези-сцену. Сохрани главный объект, силуэт и композицию. Добавь мягкое свечение, туман, древние камни, волшебные растения, светящиеся частицы и сказочную глубину. Все символы и декоративные элементы должны быть абстрактными и нечитаемыми.' },
  { id: 'i2i-04', ru: 'Сделать древность + будущее', en: 'Ancient + future', mode: 'image_to_image', category: 'Изо → Изо', prompt: 'Преобразуй исходное изображение в мир, где древняя цивилизация соединена с технологиями будущего. Сохрани главный объект, силуэт и композицию. Добавь каменную архитектуру, золото, обсидиан, парящие энергетические кольца, мягкое голубое свечение и кинематографичную атмосферу древних технологий. Все орнаменты и панели должны быть декоративными, без читаемых символов.' },
  { id: 'i2i-05', ru: 'Сделать luxury-рекламу', en: 'Make luxury ad', mode: 'image_to_image', category: 'Изо → Изо', prompt: 'Преобразуй исходное изображение в премиальный рекламный кадр. Сохрани главный объект и важные детали. Добавь элегантное студийное освещение, чистый фон, полированные отражения, мягкие тени, дорогие материалы и коммерческую композицию. Все этикетки, упаковки и поверхности должны быть заполнены только абстрактными декоративными узорами.' },
  { id: 'i2i-06', ru: 'Сделать космическую версию', en: 'Make space version', mode: 'image_to_image', category: 'Изо → Изо', prompt: 'Преобразуй исходное изображение в sci-fi космическую сцену. Сохрани главный объект, позу и композицию. Добавь далёкие планеты, звёзды, мягкое космическое свечение, футуристические материалы, парящие частицы и кинематографичную атмосферу космоса. Все экраны и панели должны показывать только абстрактные световые формы.' },
  { id: 'i2i-07', ru: 'Сделать лунный свет', en: 'Make moonlight', mode: 'image_to_image', category: 'Изо → Изо', prompt: 'Преобразуй исходное изображение в спокойную сцену под лунным светом. Сохрани главный объект и композицию. Добавь холодный серебристо-синий свет, мягкие тени, лёгкий туман, спокойные отражения и эмоциональную кинематографичную атмосферу. Все видимые поверхности должны быть полностью визуальными, без читаемых символов.' },
  { id: 'i2i-08', ru: 'Сделать сюрреалистический сон', en: 'Make surreal dream', mode: 'image_to_image', category: 'Изо → Изо', prompt: 'Преобразуй исходное изображение в красивую сюрреалистическую сцену сна. Сохрани главный объект, но помести его в невозможное окружение: парящие острова, мягкие облака, светящаяся вода, необычный масштаб, магический реализм и кинематографичная глубина. Все детали должны быть визуальными и декоративными.' },
  { id: 'edit-01', ru: 'Универсальное изменение', en: 'Universal edit', mode: 'edit', category: 'Edit', prompt: 'Сделай нужное изменение в изображении, сохранив главный объект, свет, перспективу и общий стиль.' },
  { id: 'edit-02', ru: 'Заменить фон', en: 'Replace background', mode: 'edit', category: 'Edit', prompt: 'Замени фон на красивый лунный пейзаж у моря.' },
  { id: 'edit-03', ru: 'Добавить объект', en: 'Add object', mode: 'edit', category: 'Edit', prompt: 'Добавь в сцену светящийся магический портал.' },
  { id: 'edit-04', ru: 'Сделать дороже', en: 'Make premium', mode: 'edit', category: 'Edit', prompt: 'Сделай изображение более дорогим и премиальным.' },
  { id: 'edit-05', ru: 'Добавить магический эффект', en: 'Add magic effect', mode: 'edit', category: 'Edit', prompt: 'Преобразуй сцену в фэнтези-мир с мягким магическим светом.' },
  { id: 'edit-06', ru: 'Добавить футуристический эффект', en: 'Add sci-fi effect', mode: 'edit', category: 'Edit', prompt: 'Сделай сцену футуристичной, с мягким неоновым светом.' },
  { id: 'edit-07', ru: 'Кинематографичный вид', en: 'Cinematic look', mode: 'edit', category: 'Edit', prompt: 'Сделай изображение более кинематографичным и выразительным.' },
  { id: 'edit-08', ru: 'Сделать интерьер мечты', en: 'Make dream interior', mode: 'edit', category: 'Edit', prompt: 'Сделай интерьер уютным и роскошным.' },
  { id: 'sketch-01', ru: 'Эскиз в сцену', en: 'Sketch to scene', mode: 'paint', category: 'Эскиз', prompt: 'Преобразуй исходный эскиз в реалистичную кинематографичную сцену. Сохрани расположение объектов из эскиза. Добавь красивый свет, атмосферу, тени, глубину, реалистичные материалы и чистую композицию. Все видимые поверхности и декоративные элементы должны содержать только абстрактные формы и узоры.' },
  { id: 'mask-01', ru: 'Заменить выделенную область', en: 'Replace masked area', mode: 'inpaint', category: 'Маска', prompt: 'Измени только область, отмеченную маской: «напишите, что должно появиться внутри маски». Всё вне маски сохрани без изменений: главный объект, фон, освещение, перспектива, цветовая атмосфера, тени, резкость и стиль. Новая область должна естественно соединяться с исходным изображением. Все поверхности должны содержать только абстрактные формы, световые линии и декоративные узоры.' },
  { id: 'mask-02', ru: 'Добавить объект в маску', en: 'Add object in mask', mode: 'inpaint', category: 'Маска', prompt: 'Внутри области маски добавь: «напишите объект». Объект должен иметь правильный масштаб, контактную тень, реалистичную перспективу, совпадающее освещение и подходящую резкость. Всё вне маски сохрани без изменений. Все этикетки, панели и декоративные поверхности должны быть абстрактными и нечитаемыми.' },
  { id: 'mask-03', ru: 'Исправить область', en: 'Fix area', mode: 'inpaint', category: 'Маска', prompt: 'Восстанови и улучши только область, отмеченную маской. Сделай форму, текстуру, свет, цвет и резкость естественными. Всё вне маски сохрани без изменений. Исправленная область должна выглядеть как нормальная часть исходного изображения, без заметного перехода.' },
  { id: 'outpaint-01', ru: 'Расширить до широкого кадра', en: 'Expand to widescreen', mode: 'outpaint', category: 'Расширение', prompt: 'Расширь исходное изображение до широкого кинематографичного формата 16:9. Сохрани главный объект, стиль, освещение, перспективу и цветовую атмосферу. В новых областях естественно продолжи окружение: «напишите, что должно появиться по краям». Итог должен выглядеть как единая цельная сцена без заметного шва. Все детали должны быть визуальными, без читаемых символов.' },
  { id: 'outpaint-02', ru: 'Сделать вертикальный кадр', en: 'Make vertical frame', mode: 'outpaint', category: 'Расширение', prompt: 'Расширь исходное изображение до вертикального формата 9:16. Сохрани главный объект в центре, его масштаб, свет и стиль. В верхней и нижней части естественно продолжи фон: «напишите, что добавить сверху и снизу». Композиция должна подходить для красивой вертикальной картинки. Все панели, экраны и декоративные элементы должны быть абстрактными и нечитаемыми.' },
  { id: 'outpaint-03', ru: 'Добавить вокруг красивый мир', en: 'Add beautiful world around', mode: 'outpaint', category: 'Расширение', prompt: 'Расширь изображение и добавь вокруг главного объекта красивое окружение: «опишите мир: лунное море, киберпанк-город, фэнтези-лес, космос, древний храм, luxury-интерьер». Сохрани главный объект, перспективу, освещение и стиль. Новые области должны выглядеть как естественное продолжение исходной сцены.' },
  { id: 'face-01', ru: 'Естественная замена лица', en: 'Natural face swap', mode: 'faceswap', category: 'Лицо → Изо', prompt: 'Используй изображение 1 как целевую сцену: сохранить тело, позу, одежду, фон, стиль, ракурс и освещение. Используй изображение 2 только как референс лица: сохранить основные черты, возраст, форму лица, глаза, нос, губы и выражение. Замени лицо в исходной сцене на лицо из референса так, чтобы оно совпадало с поворотом головы, направлением взгляда, светом, цветом кожи, тенями и резкостью. Все элементы одежды, фона и декоративных поверхностей должны быть без читаемых символов.' },
  { id: 'face-02', ru: 'Лицо в новом образе', en: 'Face in new style', mode: 'faceswap', category: 'Лицо → Изо', prompt: 'Используй изображение 1 как лицо-референс. Используй изображение 2 как образ, стиль или сцену. Создай портрет: «опишите образ: фэнтези, киберпанк, luxury, космос, древний храм, кинематографичный персонаж». Сохрани узнаваемые черты лица, естественный возраст, выражение и пропорции. Все декоративные элементы должны быть абстрактными и нечитаемыми.' },
]

type PromptKey = Mode | `paint:${PaintTool}`

function promptKeyFor(mode: Mode, paintTool: PaintTool): PromptKey {
  return mode === 'paint' ? `paint:${paintTool}` : mode
}

function randomPromptFromPresets(presets: Preset[], fallback = '') {
  if (!presets.length) return fallback
  return presets[Math.floor(Math.random() * presets.length)]?.prompt || fallback
}

function presetsForPromptKey(presets: Preset[], key: PromptKey) {
  if (key === 'paint:sketch') return presets.filter((item) => item.mode === 'paint')
  if (key === 'paint:inpaint') return presets.filter((item) => item.mode === 'inpaint')
  if (key === 'paint:outpaint') return presets.filter((item) => item.mode === 'outpaint')
  return presets.filter((item) => item.mode === key)
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
    T2I: { ru: 'Текст в изображение', en: 'Text to image' },
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

function fitGenerationDimension(value: number) {
  return Math.max(512, Math.min(1536, Math.round(value / 16) * 16))
}

function App() {
  const [lang, setLang] = useState<Lang>('ru')
  const [mode, setMode] = useState<Mode>('text_to_image')
  const [paintTool, setPaintTool] = useState<PaintTool>('sketch')
  const [paintEditor, setPaintEditor] = useState<PaintEditor>(null)
  const [tab, setTab] = useState<Tab>('studio')
  const [pathName, setPathName] = useState(() => window.location.pathname)
  const [provider, setProvider] = useState('comfyui')
  const [promptByMode, setPromptByMode] = useState<Record<string, string>>(() => ({
    text_to_image: randomPromptFromPresets(workflowPresets.filter((item) => item.mode === 'text_to_image'), workflowPresets.find((item) => item.mode === 'text_to_image')?.prompt || ''),
  }))
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
  const [paintLines, setPaintLines] = useState<PaintLine[]>([])
  const [maskLines, setMaskLines] = useState<PaintLine[]>([])
  const [canvasSnapshot, setCanvasSnapshot] = useState<string>()
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

  useEffect(() => {
    const onPopState = () => setPathName(window.location.pathname)
    window.addEventListener('popstate', onPopState)
    return () => window.removeEventListener('popstate', onPopState)
  }, [])

  const navigateApp = useCallback((nextTab: Tab = 'studio') => {
    if (window.location.pathname !== '/') window.history.pushState(null, '', '/')
    setPathName(window.location.pathname)
    setTab(nextTab)
  }, [])

  const openAdminPage = useCallback(() => {
    if (window.location.pathname !== '/admin') window.history.pushState(null, '', '/admin')
    setPathName(window.location.pathname)
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
  const isAdmin = currentUser.role === 'admin' || authMe?.account?.role === 'admin'
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
  const settingsSelectedLora = selectedLora === 'none' && faceLora ? faceLora.id : selectedLora
  const visiblePresets = allPresets.filter((item) => {
    if (mode === 'paint') {
      const toolMode: Mode = paintTool === 'sketch' ? 'paint' : paintTool
      return item.mode === toolMode
    }
    return item.mode === mode
  })

  useEffect(() => {
    if (promptByMode[promptKey] !== undefined) return
    const fallbackPresets = presetsForPromptKey(allPresets, promptKey)
    queueMicrotask(() => {
      setPromptByMode((current) => {
        if (current[promptKey] !== undefined) return current
        return {
          ...current,
          [promptKey]: promptKey === 'edit' ? '' : randomPromptFromPresets(fallbackPresets, ''),
        }
      })
    })
  }, [allPresets, promptByMode, promptKey])

  const fetchGallery = useCallback(async () => {
    // /api/gallery returns 401 (JSON {detail}) when unauthenticated; only ever
    // store an array so gallery.slice/.map/.length never crash the render.
    const images = await apiFetch('/gallery').then((r) => (r.ok ? r.json() : [])).catch(() => [])
    setGallery(Array.isArray(images) ? images : [])
  }, [])

  useEffect(() => {
    apiFetch('/tariffs')
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => setTariffs(normalizeTariffs(data?.tariffs)))
      .catch(() => setTariffs(DEFAULT_TARIFFS))
  }, [])

  useEffect(() => {
    // Identity/Auth v2: bootstrap + restore the cookie session at startup.
    void initAuthV2()
    apiFetch('/admin/summary').then((r) => r.json()).then(setAdmin).catch(() => undefined)
    const tg = (window as Window & { Telegram?: { WebApp?: { ready?: () => void; expand?: () => void; initData?: string; initDataUnsafe?: { user?: { id?: number; username?: string; first_name?: string; last_name?: string; language_code?: string } } } } }).Telegram?.WebApp
    tg?.ready?.()
    tg?.expand?.()
    const params = new URLSearchParams(window.location.search)
    const platform = tg?.initData ? 'telegram' : 'web'
    const tgUser = tg?.initDataUnsafe?.user
    const effectiveUserId = platform === 'telegram' && tgUser?.id ? String(tgUser.id) : SESSION_USER_ID
    window.localStorage.setItem('onenode_user', effectiveUserId)
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
      if (data?.user?.id) window.localStorage.setItem('onenode_user', data.user.id)
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
    const heartbeat = window.setInterval(() => {
      const currentUserId = window.localStorage.getItem('onenode_user') || effectiveUserId
      const rawId = (currentUserId || '').replace(/^(web_|telegram_|max_)/, '')
      const currentPlatform = rawId === currentUserId ? platform : (currentUserId.startsWith('telegram_') ? 'telegram' : currentUserId.startsWith('max_') ? 'max' : 'web')
      apiFetch('/app/heartbeat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ platform: currentPlatform, userId: rawId, seconds: 60 }),
      }).catch(() => undefined)
    }, 60000)
    return () => window.clearInterval(heartbeat)
  }, [])

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
    if (!baseImage || actualMode === 'text_to_image' || sizeSource === 'custom') return { width, height }
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
    const canvasData = (actualMode === 'paint' || actualMode === 'inpaint' || actualMode === 'outpaint') ? (canvasRef.current?.toDataURL({ pixelRatio: 1 }) || canvasSnapshot) : undefined
    const lora = loraOptions.find((item) => item.id === activeSelectedLora)
    const effectiveSeed = seed || Math.floor(Math.random() * 999999999)
    const requestSize = await imageRequestSize()
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
      outpaintMask: actualMode === 'outpaint' ? canvasData : undefined,
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
      const fallbackPresets = presetsForPromptKey(allPresets, nextKey)
      return { ...current, [nextKey]: nextKey === 'edit' ? '' : randomPromptFromPresets(fallbackPresets, '') }
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

  function resetDefaults() {
    setProvider('comfyui')
    setModelProfile('local_flux_klein')
    setSampler('er_sde')
    setSeed(0)
    setWidth(1024)
    setHeight(1024)
    setSteps(4)
    setCfg(1)
    setStrength(0.75)
    setSelectedLora('none')
    setNegativePrompt(DEFAULT_NEG_PROMPT)
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
    input.onchange = () => {
      const file = input.files?.[0]
      if (!file) return
      if (file.size > 25 * 1024 * 1024) {
        setNotice(copy.fileTooLarge)
        return
      }
      const reader = new FileReader()
      reader.onload = () => {
        const dataUrl = String(reader.result)
        const image = new Image()
        image.onload = () => {
          if (image.width > 4096 || image.height > 4096) {
            setNotice(copy.resolutionTooLarge)
            return
          }
          setter(dataUrl)
        }
        image.src = dataUrl
      }
      reader.readAsDataURL(file)
    }
    input.click()
  }

  // Edit slot helpers (0-индексация: slot 0 = основа, 1..3 = референсы).
  function setEditSlotImage(index: number, url?: string) {
    setEditSlots((current) => current.map((slot, i) => (i === index ? { ...slot, image: url } : slot)))
  }
  function setEditSlotRole(index: number, role: EditReferenceRole | '') {
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
  const openGallery = () => {
    if (galleryLocked) {
      setTab('settings')
      return
    }
    setTab('gallery')
  }
  const editBaseImage = editSlots[0].image
  const previewSource = job?.status === 'completed' && job.resultUrl ? job.resultUrl : (mode === 'edit' ? editBaseImage : inputOne)
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
        onPickGallery={(i) => { setPendingEditSlot(i); openGallery() }}
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
          {mode === 'paint' && <div className="mobile-paint-actions"><button onClick={() => { setPaintTool('sketch'); setPromptForKey('paint:sketch', workflowPresets.find((item) => item.id === 'sketch-01')?.prompt || ''); setPaintEditor('sketch') }}><strong>Эскиз</strong><span>Рисование на чистом холсте</span></button><button onClick={() => { setPaintTool('inpaint'); setPromptForKey('paint:inpaint', workflowPresets.find((item) => item.id === 'mask-01')?.prompt || ''); setPaintEditor('mask') }}><strong>Маска / расширение</strong><span>Закрасить область или расширить изображение</span></button></div>}
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

  if (adminRoute) {
    return (
      <div className="app-shell admin-route-shell">
        {isDiagMode() && <DiagPanel />}
        <AuthV2Modal open={authModalOpen} onClose={() => setAuthModalOpen(false)} />
        <main className="workspace admin-workspace">
          {authV2Status === 'loading' ? (
            <section className="admin-page admin-access-page">
              <div className="view-actions in-panel"><button className="secondary" onClick={() => navigateApp('studio')}><WandSparkles size={16} />{copy.backToStudio}</button></div>
              <div className="admin-head"><div><h2>{copy.admin}</h2><p>Проверяем trusted admin-сессию.</p></div><strong>loading</strong></div>
            </section>
          ) : isAdmin ? (
            <AdminView copy={copy} admin={admin} tariffs={tariffs} setTariffs={setTariffs} backToStudio={() => navigateApp('studio')} provider={provider} modelProfile={modelProfile} selectedLora={settingsSelectedLora} resetDefaults={resetDefaults} />
          ) : (
            <section className="admin-page admin-access-page">
              <div className="view-actions in-panel"><button className="secondary" onClick={() => navigateApp('studio')}><WandSparkles size={16} />{copy.backToStudio}</button></div>
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
                  onPickGallery={(i) => { setPendingEditSlot(i); openGallery() }}
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
              {job && ['queued', 'running', 'uploading', 'sent_to_comfyui'].includes(job.status) ? <JobCard job={job} copy={copy} cancelJob={cancelJob} sendImage={sendImage} mode={mode} beforeImage={mode === 'edit' ? editBaseImage : inputOne} loadingBackdrop={(mode === 'edit' ? editBaseImage : undefined) || gallery[0]?.url} /> : job?.status === 'completed' && job.resultUrl ? <JobCard job={job} copy={copy} cancelJob={cancelJob} sendImage={sendImage} mode={mode} beforeImage={mode === 'edit' ? editBaseImage : inputOne} /> : previewSource && mode !== 'text_to_image' ? <div className="result-frame mobile-source-preview"><img src={previewSource} />{mode === 'edit' && !job && <span className="preview-caption">Предпросмотр основы</span>}</div> : <div className="preview-empty">{mode !== 'text_to_image' ? <><span className="preview-empty-hint">{mode === 'edit' ? 'Добавьте основу для редактирования' : 'Добавьте изображение'}</span><button className="preview-add-button" onClick={() => upload((url) => mode === 'edit' ? setEditSlotImage(0, url) : setInputOne(url))}><Upload size={22} />{mode === 'edit' ? 'Выбрать изображение' : 'Добавить изображение'}</button></> : <><ImageIcon size={64} /><span>{copy.generatedPlaceholder}</span></>}</div>}
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
        {tab === 'gallery' && galleryLocked && <SettingsView copy={copy} lang={lang} onLanguageChange={changeLanguage} tariffs={tariffs} bootstrap={bootstrap} setBootstrap={setBootstrap} openAdmin={openAdminPage} openGallery={() => setTab('gallery')} backToStudio={() => setTab('studio')} provider={provider} setProvider={setProvider} width={width} setWidth={setWidth} height={height} setHeight={setHeight} steps={steps} setSteps={setSteps} setCfg={setCfg} isAuthedV2={isAuthedV2} openAuthModal={() => setAuthModalOpen(true)} authMe={authMe} />}
        {tab === 'presets' && <HelpView lang={lang} applyPreset={applyPreset} copy={copy} backToStudio={() => setTab('studio')} />}
        {tab === 'settings' && <SettingsView copy={copy} lang={lang} onLanguageChange={changeLanguage} tariffs={tariffs} bootstrap={bootstrap} setBootstrap={setBootstrap} openAdmin={openAdminPage} openGallery={() => setTab('gallery')} backToStudio={() => setTab('studio')} provider={provider} setProvider={setProvider} width={width} setWidth={setWidth} height={height} setHeight={setHeight} steps={steps} setSteps={setSteps} setCfg={setCfg} isAuthedV2={isAuthedV2} openAuthModal={() => setAuthModalOpen(true)} authMe={authMe} />}

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
          />
        )}

        {!galleryLocked && <section className="bottom-strip">
          {gallery.slice(0, 6).map((image) => <button key={image.id} onClick={() => { setSelected(image); setTab('gallery') }}><img src={image.thumbnailUrl} alt="" /></button>)}
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
    return <div className="paint-compact"><ImageBox title="ИЗО" image={inputOne} onUpload={() => upload(setInputOne)} onClear={() => setInputOne(undefined)} onUseLast={() => applyLastImage(1)} copy={copy} /><div className="paint-choice-stack"><button className={paintTool === 'sketch' ? 'paint-choice active' : 'paint-choice'} onClick={openSketch}><strong>Эскиз</strong><span>Рисование на чистом холсте</span></button><button className={paintTool !== 'sketch' ? 'paint-choice active' : 'paint-choice'} onClick={openMask}><strong>Маска / Расширение</strong><span>Закрасить область или расширить изображение</span></button></div></div>
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
            {EDIT_REFERENCE_ROLES.map((role) => <option key={role} value={role}>{EDIT_REFERENCE_ROLE_LABELS[role]}</option>)}
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
}) {
  const { editor, paintTool, setPaintTool, onClose, copy, inputOne, setInputOne, upload, paintLines, setPaintLines, maskLines, setMaskLines, tool, setTool, brushSize, setBrushSize, paintColor, setPaintColor, layerOpacity, setLayerOpacity, outpaint, setOutpaint, drawingRef, canvasRef, setPromptForKey, setCanvasSnapshot } = props
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
  const updateOutpaint = (key: keyof typeof outpaint, value: number | boolean) => setOutpaint({ ...outpaint, [key]: value })
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
      setCanvasSnapshot(await createImageMask(inputOne, activeLines, stageSize))
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
  return <div className="modal-backdrop" onClick={onClose}><section className="instruction-modal edit-templates-modal" onClick={(e) => e.stopPropagation()}>
    <button className="floating-clear" onClick={onClose}><X size={16} /></button>
    <h2>Шаблоны</h2>
    <p className="modal-sub">Шаблон сам расставит роли референсам. Загрузите изображения в нужные слоты.</p>
    <div className="templates-list">
      {templates.map((tpl) => (
        <button key={tpl.id} className="template-card" onClick={() => applyTemplate(tpl)}>
          <strong>{tpl.title}</strong>
          <small>{roleNames(tpl)}</small>
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
  void sendImage
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && selected) clearSelected()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [selected, clearSelected])
  return (
    <section className="gallery-page">
      {picking && <div className="gallery-pick-banner"><span>Выберите изображение для слота {pickSlot === 0 ? 'Основа' : `Референс ${pickSlot}`}</span><button className="secondary" onClick={() => cancelPick?.()}>Отмена</button></div>}
      {quota && <div className="gallery-pick-banner gallery-quota-banner"><span>Галерея: занято {quota.gallery_used} из {quota.gallery_slots} · свободно {quota.gallery_free} · тариф {quota.plan.toUpperCase()}</span></div>}
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
                <a title={copy.download} href={image.url} download onClick={(e) => e.stopPropagation()}><Download size={16} /></a>
                <button type="button" title={copy.delete} onClick={() => void deleteImage(image)}><Trash2 size={16} /></button>
              </div>
            </article>
          ))}
        </div>
      </div>
      {selected && (
        <div className="gallery-modal-backdrop" onClick={clearSelected}>
          <section className="gallery-modal" role="dialog" aria-label="Предпросмотр изображения" onClick={(e) => e.stopPropagation()}>
            <button className="floating-clear" aria-label="Закрыть" onClick={clearSelected}><X size={16} /></button>
            <div className="gallery-modal-media"><img src={selected.url || selected.thumbnailUrl} alt="" onError={(event) => { if (selected.thumbnailUrl && event.currentTarget.src !== selected.thumbnailUrl) event.currentTarget.src = selected.thumbnailUrl }} /></div>
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
                <button className="secondary" onClick={() => void shareSelected(selected)}>Скопировать ссылку</button>
                <button className="secondary" disabled title="Отправка в Telegram требует привязанный чат">Telegram</button>
                <button className="secondary" disabled title="MAX отправка требует привязанный чат">MAX</button>
                <button className="secondary danger" onClick={() => void deleteImage(selected)}><Trash2 size={16} />{copy.delete}</button>
              </div>
              {galleryMsg && <p className="gallery-msg">{galleryMsg}</p>}
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
  return <div className="discover-panel"><div className="discover-head"><strong>Шаблоны</strong><span>Выберите готовый запрос или сохраните свой</span><button type="button" className="discover-close" onClick={onClose} aria-label="Закрыть шаблоны"><X size={18} /></button></div><div className="preset-create"><strong>Добавить свой шаблон</strong><input placeholder="Название" value={name} onChange={(e) => setName(e.target.value)} /><textarea placeholder="Текст запроса" value={presetPrompt} onChange={(e) => setPresetPrompt(e.target.value)} /><button onClick={() => { if (name.trim() && presetPrompt.trim()) { addUserPreset(name.trim(), presetPrompt.trim()); setName(''); setPresetPrompt('') } }}>Сохранить</button></div><div className="discover-groups">{Object.entries(groups).map(([category, items]) => <section className="discover-category" key={category}><h3>{categoryTitle(category, lang)}</h3><div className="discover-cards">{items.map((preset) => <button key={preset.id} onClick={() => applyPreset(preset)}><Sparkles size={16} /><span>{preset[lang]}{preset.dual ? ' · 2 IMG' : ''}</span><small>{preset.prompt.slice(0, 120)}</small></button>)}</div></section>)}</div></div>
}

function HelpView({ lang, applyPreset, copy, backToStudio }: { lang: Lang; applyPreset: (preset: Preset) => void; copy: Copy; backToStudio: () => void }) {
  return <section className="help-page"><div className="view-actions"><button className="secondary" onClick={backToStudio}><WandSparkles size={16} />{copy.backToStudio}</button></div><h2>Помощь</h2><div className="help-grid"><article><h3>Как пользоваться ИЗО_АСА</h3><p>Выберите режим в верхней панели: текст в изображение, изображение в изображение, редактирование, рисование, закрашивание области, расширение изображения или замена лица. Заполните prompt, добавьте изображения там, где режим этого требует, и нажмите «Сгенерировать».</p><p>Кнопка «Шаблоны» открывает готовые русские запросы для текущей вкладки. Кнопка «Случайный» подставляет случайный запрос только из набора активной вкладки или активного инструмента рисования.</p></article><article><h3>Настройки по умолчанию исходника</h3><p>Размер: 1024 × 1024. Seed: 0 с рандомизацией. Steps: 4. CFG: 1. Sampler: er_sde. Negative prompt уже заполнен исходным списком ограничений качества.</p><p>Для FaceSwap нужен Faceswap LoRA. Для локальной генерации используется ComfyUI и workflow Flux 2 Klein.</p></article><article><h3>Режимы</h3><p><strong>Текст → Изо</strong>: генерация картинки по prompt. <strong>Изо → Изо</strong>: изменение загруженного изображения с силой изменения. <strong>Редактор</strong>: правки и примерка объектов. <strong>Рисовать</strong>: эскиз, маска и расширение. <strong>Лицо → Изо</strong>: перенос лица из source в target.</p></article></div><h3>Шаблоны</h3><div className="preset-grid">{workflowPresets.map((preset) => <button key={preset.id} onClick={() => applyPreset(preset)}><Sparkles /><strong>{preset[lang]}</strong><span>{preset.prompt.slice(0, 130)}</span></button>)}</div></section>
}

function InstructionModal({ mode, paintTool, onClose }: { mode: Mode; paintTool: PaintTool; onClose: () => void }) {
  const text: Record<string, { title: string; steps: string[] }> = {
    text_to_image: { title: 'Инструкция: Текст → Изо', steps: ['Нажмите «Пресеты» или «Случайный prompt», чтобы быстро заполнить запрос.', 'Выберите размер изображения слева.', 'При необходимости откройте «Настройки» и измените seed, steps, CFG, sampler или LoRA.', 'Нажмите «Сгенерировать» и дождитесь результата справа.'] },
    image_to_image: { title: 'Инструкция: Изо → Изо', steps: ['Загрузите исходное изображение в левую область.', 'Настройте «Силу изменения»: 0.10 меняет мало, 0.75 ближе к исходнику One Node, 0.80 меняет сильно.', 'Введите prompt с описанием того, как нужно изменить изображение.', 'Нажмите «Сгенерировать».'] },
    edit: { title: 'Инструкция: Редактор', steps: ['Загрузите «Основу» — это изображение, которое нужно изменить. Этот слот обязателен.', 'Добавьте до трёх референсов. Для каждого загруженного референса выберите роль: лицо, одежда, стиль, объект, поза, фон, цвет/материал или другое.', 'Роль определяет, что именно система возьмёт из референса. Например: «Одежда» берёт одежду, «Поза» берёт положение тела, «Фон» берёт окружение.', 'Писать большой prompt не нужно. Система сама собирает инструкцию по выбранным изображениям и ролям.', 'В поле «Дополнительное пожелание» можно коротко уточнить результат, например: «сделай свет мягче» или «сделай изображение более кинематографичным». Это поле необязательное.', 'Если нужна тонкая настройка, откройте «Расширенные». Там можно уточнить, что взять из каждого референса, посмотреть собранную инструкцию или отредактировать её вручную.', 'Нажмите «Сгенерировать». Пока задача отправляется или выполняется, повторные нажатия блокируются.', 'Жёлтая вертикальная линия в предпросмотре — это сравнение «до/после». Это не ошибка.'] },
    paint: { title: `Инструкция: ${paintTool === 'sketch' ? 'Эскиз' : paintTool === 'inpaint' ? 'Маска' : 'Расширение'}`, steps: paintTool === 'sketch' ? ['Выберите «Эскиз», рисуйте на чистом холсте кистью/ластиком.', 'Prompt должен объяснять, во что превратить рисунок.', 'Сгенерируйте сцену по вашему рисунку.'] : paintTool === 'inpaint' ? ['Выберите «Маска». Это понятный режим замены области изображения.', 'Загрузите изображение и закрасьте область, которую нужно изменить.', 'В prompt опишите, что должно появиться в закрашенной зоне.', 'Сгенерируйте результат.'] : ['Выберите «Расширение».', 'Загрузите изображение и задайте, сколько пикселей добавить слева/справа/сверху/снизу.', 'Prompt должен описывать, чем заполнить новые области.', 'Сгенерируйте расширенную композицию.'] },
    faceswap: { title: 'Инструкция: Лицо → Изо', steps: ['Загрузите Target: изображение, куда нужно перенести лицо.', 'Загрузите Source: изображение, откуда берется лицо.', 'В «Настройки» выберите Faceswap LoRA, если он доступен локально.', 'Prompt по умолчанию описывает замену головы с сохранением света и стиля.'] },
    remove_background: { title: 'Инструкция: Удалить фон', steps: ['Загрузите изображение с объектом.', 'Оставьте стандартный prompt или уточните, что нужно изолировать.', 'Нажмите «Сгенерировать».'] },
    try_on: { title: 'Инструкция: Примерка', steps: ['Загрузите человека в первый слот.', 'Загрузите одежду или референс образа во второй слот.', 'Prompt по умолчанию переносит только одежду, сохраняя лицо, позу и фон.', 'Нажмите «Сгенерировать».'] },
    texture_transfer: { title: 'Инструкция: Перенос текстуры', steps: ['Загрузите целевой объект в первый слот.', 'Загрузите материал, текстуру или стиль во второй слот.', 'Prompt по умолчанию переносит поверхность, сохраняя форму и перспективу.', 'Нажмите «Сгенерировать».'] },
  }
  const current = text[mode] || text.text_to_image
  return <div className="modal-backdrop"><section className="instruction-modal"><button className="floating-clear" onClick={onClose}><X size={16} /></button><h2>{current.title}</h2>{current.steps.map((step, index) => <p key={step}><strong>{index + 1}.</strong> {step}</p>)}</section></div>
}

function SettingsView({ copy, lang, onLanguageChange, tariffs, bootstrap, setBootstrap, openAdmin, openGallery, backToStudio, provider, setProvider, width, setWidth, height, setHeight, steps, setSteps, setCfg, isAuthedV2 = false, openAuthModal, authMe }: { copy: Copy; lang: Lang; onLanguageChange: (value: Lang) => void; tariffs: TariffConfig; bootstrap?: Record<string, unknown>; setBootstrap: Dispatch<SetStateAction<Record<string, unknown> | undefined>>; openAdmin: () => void; openGallery?: () => void; backToStudio: () => void; provider: string; setProvider: (value: string) => void; width: number; setWidth: (value: number) => void; height: number; setHeight: (value: number) => void; steps: number; setSteps: (value: number) => void; setCfg: (value: number) => void; isAuthedV2?: boolean; openAuthModal?: () => void; authMe?: MeV2 | null }) {
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
    setSaveMsg('')
    const result = await updateProfileV2({ display_name: trimmed })
    if (result) { await refreshAuthStateV2(); setSaveMsg('Сохранено') }
    else setSaveMsg('Ошибка сохранения')
  }
  const selectAvatarPreset = async (presetId: string) => {
    const preset = avatarPresets.find((item) => item.id === presetId)
    if (!preset) return
    setAvatarBusy(true); setAvatarMsg('')
    const result = await updateProfileV2({ avatar_preset: presetId })
    if (result) {
      setAvatarPreset(presetId)
      setAvatarUrl(preset.url)
      await refreshAuthStateV2()
      setAvatarMsg('Аватар сохранён')
    } else setAvatarMsg('Не удалось сохранить аватар')
    setAvatarBusy(false)
  }
  const uploadAvatar = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    if (!/^image\/(png|jpeg|webp)$/.test(file.type)) { setAvatarMsg('Нужен PNG, JPG или WEBP'); return }
    if (file.size > 2 * 1024 * 1024) { setAvatarMsg('Файл больше 2 МБ'); return }
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
        <div className="usr-head"><button className="secondary" onClick={backToStudio}><WandSparkles size={16} />{copy.backToStudio}</button></div>
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
      <div className="usr-head">
        <button className="secondary" onClick={backToStudio}><WandSparkles size={16} />{copy.backToStudio}</button>
        <span className="usr-status"><i />Сессия активна</span>
      </div>

      <header className="usr-title">
        <h2>Настройки аккаунта</h2>
        <p>Профиль, тарифы, токены, промокоды и параметры генерации.</p>
      </header>

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
        <div>Функции</div><div>FREE</div><div>MINI</div><div>PLUS</div><div>PRO</div>
        <span>Токены в сутки</span><b>10</b><b>50</b><b>100</b><b>200</b>
        <span>Галерея</span><b>Закрыта</b><b>Открыта</b><b>Расширенная</b><b>Расширенная</b>
        <span>Модели</span><b>Базовые</b><b>Стандартные</b><b>HD</b><b>Продвинутые</b>
        <span>Очередь</span><b>Обычная</b><b>Обычная</b><b>Ускоренная</b><b>Приоритетная</b>
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
  const summary = (data?.summary || {}) as Record<string, unknown>
  const comfy = (data?.comfyui || {}) as Record<string, unknown>
  const profiles = Array.isArray(comfy.profiles) ? comfy.profiles as Record<string, unknown>[] : []
  const activeJobs = Array.isArray(data?.active_jobs) ? data.active_jobs as Record<string, unknown>[] : []
  const generationErrors = Array.isArray(data?.generation_errors) ? data.generation_errors as Record<string, unknown>[] : []
  const eventLogs = Array.isArray(data?.event_logs) ? data.event_logs as Record<string, unknown>[] : []
  const securityEvents = Array.isArray(data?.security_events) ? data.security_events as Record<string, unknown>[] : []
  const auditLogs = Array.isArray(data?.audit_logs) ? data.audit_logs as Record<string, unknown>[] : []
  const line = (left: unknown, right?: unknown, extra?: unknown) => <p><b>{String(left || '—')}</b>{right ? ` · ${String(right)}` : ''}{extra ? <small>{String(extra)}</small> : null}</p>
  return (
    <div className="admin-section">
      <h3>Логи и состояние систем</h3>
      <div className="admin-grid">
        <div><strong>ComfyUI</strong><span>{comfy.available ? 'online' : 'offline'}</span><small>локальный генератор</small></div>
        <div><strong>Активные задачи</strong><span>{String(summary.active_jobs ?? activeJobs.length)}</span><small>queue/running/uploading</small></div>
        <div><strong>Ошибки генерации</strong><span>{String(summary.generation_errors_memory ?? admin?.errors ?? 0)}</span><small>runtime failed jobs</small></div>
        <div><strong>Ошибки входа 24ч</strong><span>{String(summary.failed_logins_24h ?? admin?.errors24h ?? 0)}</span><small>password/auth attempts</small></div>
      </div>
      <div className="admin-two-col">
        <article>
          <h3>ComfyUI / модели</h3>
          <p>Маршрут сейчас: {provider === 'openrouter' ? 'OpenRouter Cloud' : 'ComfyUI локально'}</p>
          {profiles.length ? profiles.map((p) => {
            const missing = Array.isArray(p.missingFiles) ? p.missingFiles.map(String) : []
            return line(p.name || p.id, `${p.baseEdit || '—'} · pose ${p.pose || '—'}`, missing.length ? `missing: ${missing.join(', ')}` : undefined)
          }) : <p>Профили не загружены.</p>}
          {Boolean(comfy.error) && <p><b>Ошибка проверки</b> · {String(comfy.error)}</p>}
        </article>
        <article>
          <h3>Активные задачи</h3>
          {activeJobs.length ? activeJobs.map((j) => line(j.id, `${j.status || '—'} · ${j.mode || '—'} · ${j.provider || '—'}`, j.message)) : <p>Очередь пуста.</p>}
        </article>
      </div>
      <div className="admin-two-col">
        <article>
          <h3>Ошибки генерации</h3>
          {generationErrors.length ? generationErrors.map((e) => line(e.id, `${e.mode || '—'} · ${e.provider || '—'}`, e.error)) : <p>Ошибок генерации в runtime нет.</p>}
        </article>
        <article>
          <h3>Security events</h3>
          {securityEvents.length ? securityEvents.slice(0, 14).map((e) => line(e.event_type, `${e.severity || '—'} · ${e.created_at || '—'}`, e.ip_address)) : <p>Security events нет.</p>}
        </article>
      </div>
      <div className="admin-two-col">
        <article>
          <h3>Product / auth logs</h3>
          {eventLogs.length ? eventLogs.slice(0, 14).map((e) => line(e.event_name, `${e.platform || '—'} · ${e.created_at || '—'}`, e.ip_address)) : <p>Event logs нет.</p>}
        </article>
        <article>
          <h3>Audit logs</h3>
          {auditLogs.length ? auditLogs.slice(0, 14).map((e) => line(e.action, `${e.entity_type || '—'} · ${e.created_at || '—'}`, e.target ? `target ${e.target}` : undefined)) : <p>Audit logs нет.</p>}
        </article>
      </div>
      <details><summary>Сырой admin summary</summary><pre>{JSON.stringify(admin, null, 2)}</pre></details>
    </div>
  )
}

function AdminView({ copy, admin, tariffs, setTariffs, backToStudio, provider, modelProfile, selectedLora, resetDefaults }: { copy: Copy; admin?: Record<string, unknown>; tariffs: TariffConfig; setTariffs: Dispatch<SetStateAction<TariffConfig>>; backToStudio: () => void; provider: string; modelProfile: string; selectedLora: string; resetDefaults: () => void }) {
  const [tab, setTab] = useState<'dashboard' | 'models' | 'tokens' | 'users' | 'queue' | 'logs'>('dashboard')
  const [limits, setLimits] = useState({ hourly: 0, daily: 0 })
  const [saved, setSaved] = useState('')
  const [promoDraft, setPromoDraft] = useState({ code: 'START50', tokens: 50, activations: 100 })
  const [finance, setFinance] = useState({ tokenRevenue: 0, tokenCost: 0, electricity: 0, promoBudget: 0 })
  const [tariffConfig, setTariffConfig] = useState<TariffConfig>(tariffs)
  const [promoCodes, setPromoCodes] = useState<PromoCode[]>([])
  const [logsData, setLogsData] = useState<Record<string, unknown> | null>(null)
  const [adminMessage, setAdminMessage] = useState('')
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
  useEffect(() => { if (tab === 'tokens') queueMicrotask(() => { void refreshTokenAdminData() }) }, [tab, refreshTokenAdminData])
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
  return <section className="admin-page">
    <div className="view-actions in-panel"><button className="secondary" onClick={backToStudio}><WandSparkles size={16} />{copy.backToStudio}</button><button className="secondary" onClick={resetDefaults}>По умолчанию</button></div>
    <div className="admin-head"><div><h2>{copy.admin}</h2><p>Управление генерациями, токенами, моделями, тарифами и доступами.</p>{adminMessage && <small>{adminMessage}</small>}</div><strong>{health}</strong></div>
    <div className="admin-tabbar">{[['dashboard', 'Дашборд'], ['models', 'Модели'], ['tokens', 'Токены'], ['users', 'Пользователи'], ['queue', 'Очередь'], ['logs', 'Логи']].map(([id, label]) => <button key={id} className={tab === id ? 'active' : ''} onClick={() => setTab(id as typeof tab)}>{label}</button>)}</div>
    {tab === 'dashboard' && <div className="admin-section">
      <div className="admin-grid"><div><strong>{copy.users}</strong><span>{String(admin?.users ?? 1)}</span><small>аккаунтов всего</small></div><div><strong>Активных сегодня</strong><span>{String(admin?.activeToday ?? 0)}</span><small>за последние 24ч</small></div><div><strong>Генераций сегодня</strong><span>{String(admin?.generationsToday ?? 0)}</span><small>задач создано</small></div><div><strong>Токенов списано</strong><span>{Number(admin?.tokensSpentTotal ?? 0).toLocaleString('ru-RU')}</span><small>всего</small></div></div>
      <div className="admin-grid"><div><strong>Активных сессий</strong><span>{String(admin?.activeSessions ?? 0)}</span><small>прямо сейчас</small></div><div><strong>Ошибок входа (24ч)</strong><span>{String(admin?.errors24h ?? 0)}</span><small>неудачных попыток</small></div><div><strong>Изображений</strong><span>{String(admin?.images ?? 0)}</span><small>в галереях</small></div><div><strong>{copy.errors}</strong><span>{String(admin?.errors ?? 0)}</span><small>ошибок генерации</small></div></div>
      {Boolean(admin?.finance) && <div className="admin-grid"><div><strong>Доход</strong><span>{Number(adminFinance.tokenRevenue ?? 0).toLocaleString('ru-RU')} ₽</span><small>оценка</small></div><div><strong>Себестоимость</strong><span>{Number(adminFinance.tokenCost ?? 0).toLocaleString('ru-RU')} ₽</span><small>оценка</small></div><div><strong>Свет</strong><span>{Number(adminFinance.electricity ?? 0).toLocaleString('ru-RU')} ₽</span><small>оценка</small></div><div><strong>Акции</strong><span>{Number(adminFinance.promoBudget ?? 0).toLocaleString('ru-RU')} ₽</span><small>оценка</small></div></div>}
      <div className="admin-two-col"><article><h3>Состояние генератора</h3><p>Провайдер: {provider === 'openrouter' ? 'OpenRouter Cloud' : 'ComfyUI локально'}</p><p>Модель: {modelProfile}</p><p>В очереди: {String(Array.isArray(admin?.queue) ? admin.queue.length : 0)}</p><p>LoRA для лица: {selectedLora}</p></article><article><h3>Быстрые действия</h3><button className="secondary" onClick={() => setTab('models')}>Настроить модели</button><button className="secondary" onClick={() => setTab('tokens')}>Тарифы и финансы</button><button className="secondary" onClick={() => setTab('users')}>Админы и пользователи</button></article></div>
    </div>}
    {tab === 'models' && <div className="admin-section"><AdminModelsV2 /></div>}
    {tab === 'tokens' && <div className="admin-section"><h3>Токены, тарифы, финансы и акции</h3><div className="admin-two-col"><article><h3>{copy.limits}</h3><label>hourly<input type="number" value={limits.hourly} onChange={(e) => setLimits({ ...limits, hourly: Number(e.target.value) })} /></label><label>daily<input type="number" value={limits.daily} onChange={(e) => setLimits({ ...limits, daily: Number(e.target.value) })} /></label><button className="secondary" onClick={saveLimits}>{copy.save}</button><small>{saved}</small></article><article><h3>Финансы</h3><label>Доход от токенов<input type="number" value={finance.tokenRevenue} onChange={(e) => setFinance({ ...finance, tokenRevenue: Number(e.target.value) })} /></label><label>Себестоимость API<input type="number" value={finance.tokenCost} onChange={(e) => setFinance({ ...finance, tokenCost: Number(e.target.value) })} /></label><label>Свет<input type="number" value={finance.electricity} onChange={(e) => setFinance({ ...finance, electricity: Number(e.target.value) })} /></label><label>Акции<input type="number" value={finance.promoBudget} onChange={(e) => setFinance({ ...finance, promoBudget: Number(e.target.value) })} /></label><button className="secondary" onClick={saveFinance}>Сохранить финансы</button></article><article><h3>Промокод</h3><label>Код<input value={promoDraft.code} onChange={(e) => setPromoDraft({ ...promoDraft, code: e.target.value.toUpperCase() })} /></label><label>Токены<input type="number" value={promoDraft.tokens} onChange={(e) => setPromoDraft({ ...promoDraft, tokens: Number(e.target.value) })} /></label><label>Активации<input type="number" value={promoDraft.activations} onChange={(e) => setPromoDraft({ ...promoDraft, activations: Number(e.target.value) })} /></label><button className="secondary" onClick={createPromo}>Создать промокод</button></article><article><h3>Промокоды в базе</h3>{promoCodes.length ? promoCodes.map((item) => <p key={item.code}><b>{item.code}</b>: {item.tokens} ток. · {item.activation_count}/{item.activation_limit}</p>) : <p>Промокодов пока нет.</p>}</article></div><div className="admin-grid"><div><strong>Free</strong><span>{tariffConfig.free.daily_tokens} ток.</span><small>{tariffConfig.free.gallery_slots} слот(ов) галереи</small></div><div><strong>Mini</strong><span>{tariffConfig.mini.daily_tokens} ток.</span><small>{tariffConfig.mini.gallery_slots} слот(ов) галереи</small></div><div><strong>Plus</strong><span>{tariffConfig.plus.daily_tokens} ток.</span><small>{tariffConfig.plus.gallery_slots} слот(ов) галереи</small></div><div><strong>Pro</strong><span>{tariffConfig.pro.daily_tokens} ток.</span><small>{tariffConfig.pro.gallery_slots} слот(ов) галереи</small></div></div></div>}
    {tab === 'tokens' && <div className="admin-section"><h3>Настройки тарифов</h3><p>Единый источник для Settings, Gallery и CRM: токены в сутки и слоты галереи.</p><div className="admin-grid">{tariffKeys.map((planKey) => <div key={planKey}><strong>{planKey.toUpperCase()}</strong><label>Токенов/день<input type="number" min="0" value={tariffConfig[planKey].daily_tokens} onChange={(e) => setTariffConfig((current) => ({ ...current, [planKey]: { ...current[planKey], daily_tokens: Number(e.target.value) } }))} /></label><label>Слоты галереи<input type="number" min="0" value={tariffConfig[planKey].gallery_slots} onChange={(e) => setTariffConfig((current) => ({ ...current, [planKey]: { ...current[planKey], gallery_slots: Number(e.target.value) } }))} /></label><small>{tariffConfig[planKey].daily_tokens} ток./день · {tariffConfig[planKey].gallery_slots} слот(ов)</small></div>)}</div><button className="secondary" onClick={() => void saveTariffs()}>Сохранить тарифы</button></div>}
    {tab === 'users' && <div className="admin-section"><AdminAnalyticsV2 /></div>}
    {tab === 'queue' && <div className="admin-section"><h3>Очередь генераций</h3><div className="admin-grid"><div><strong>В очереди</strong><span>{queue.length}</span><small>ожидают запуска</small></div><div><strong>Провайдер</strong><span>{provider}</span><small>текущий маршрут</small></div><div><strong>Сегодня</strong><span>{String(admin?.completedToday ?? 0)}</span><small>выполнено</small></div></div><pre>{JSON.stringify(queue, null, 2)}</pre></div>}
    {tab === 'logs' && <AdminLogsView data={logsData} provider={provider} admin={admin} />}

  </section>
}

export default App
