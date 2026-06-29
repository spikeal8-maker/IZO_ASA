import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ChangeEvent, Dispatch, MutableRefObject, RefObject, SetStateAction } from 'react'
import { AuthV2Modal, initAuthV2, updateProfileV2, logoutV2, refreshAuthStateV2, useAuthV2, type MeV2 } from './authV2'
import { DiagPanel, isDiagMode } from './diag'
import {
  EDIT_SLOT_COUNT, DEFAULT_EDIT_STRENGTH, EDIT_REFERENCE_ROLES, EDIT_REFERENCE_ROLE_LABELS,
  EDIT_TEMPLATES, editComposerStatus,
  type EditReferenceRole, type EditSlot, type EditTemplate,
} from './editPrompt'
import { AdminAnalyticsV2 } from './adminAnalytics'
import { Stage, Layer, Line, Rect, Text, Circle } from 'react-konva'
import type { Stage as KonvaStage } from 'konva/lib/Stage'
import {
  Brush,
  Download,
  Eraser,
  Expand,
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
type Tab = 'studio' | 'gallery' | 'presets' | 'settings' | 'admin'
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

type AdminUser = {
  id: string
  telegram_id?: string
  max_id?: string
  username?: string
  first_name?: string
  last_name?: string
  middle_name?: string
  phone?: string
  email?: string
  language?: string
  role: 'user' | 'admin'
  plan: 'free' | 'mini' | 'plus' | 'pro'
  token_balance: number
  gallery_enabled: number
  country?: string
  city?: string
  timezone?: string
  total_time_seconds: number
  generation_count: number
  tokens_used: number
  promo_used_count: number
  referrals_count: number
  banned: number
  last_seen_at?: string
  created_at?: string
  last_login_at?: string
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

type UserHistory = {
  user?: AdminUser
  jobs: Array<Record<string, unknown>>
  images: Array<Record<string, unknown>>
  ledger: Array<Record<string, unknown>>
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
const openRouterImageModels = [
  { id: 'google/gemini-3.1-flash-image', name: 'Nano Banana 2 Flash Image', use: 'быстрая генерация и редактирование', prompt: '$0.50 / 1M', completion: '$3.00 / 1M', image: 'по токенам ответа', tokenCost: 2 },
  { id: 'google/gemini-3-pro-image', name: 'Nano Banana Pro Image', use: 'лучшее качество и сложные правки', prompt: '$2.00 / 1M', completion: '$12.00 / 1M', image: '$2.00 / 1M image input', tokenCost: 6 },
  { id: 'openai/gpt-5-image-mini', name: 'GPT-5 Image Mini', use: 'дешевый запасной маршрут', prompt: '$2.50 / 1M', completion: '$2.00 / 1M', image: 'по токенам ответа', tokenCost: 3 },
  { id: 'openai/gpt-5-image', name: 'GPT-5 Image', use: 'качественный запасной маршрут', prompt: '$10.00 / 1M', completion: '$10.00 / 1M', image: 'по токенам ответа', tokenCost: 7 },
]
const localFluxProfiles = [
  {
    id: 'flux2-4b',
    title: 'Flux 2 Klein 4B',
    modelFile: 'flux-2-klein-4b-fp8.safetensors',
    quality: 'Быстро',
    defaultSteps: 4,
    tokenRules: [
      { steps: '4 шага', tokens: 1 },
      { steps: '5 шагов', tokens: 2 },
      { steps: '6-8 шагов', tokens: 3 },
    ],
  },
  {
    id: 'flux2-9b',
    title: 'Flux 2 Klein 9B',
    modelFile: 'flux-2-klein-9b-fp8.safetensors',
    quality: 'Максимум',
    defaultSteps: 4,
    tokenRules: [
      { steps: '4 шага', tokens: 1 },
      { steps: '5 шагов', tokens: 2 },
      { steps: '6 шагов', tokens: 4 },
      { steps: '7-8 шагов', tokens: 6 },
    ],
  },
]
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
  const [provider, setProvider] = useState('comfyui')
  const [prompt, setPrompt] = useState(workflowPresets.find((item) => item.mode === 'text_to_image')?.prompt || '')
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
  const [galleryView, setGalleryView] = useState<'grid' | 'list'>('grid')
  const [notice, setNotice] = useState('')
  const [discoverOpen, setDiscoverOpen] = useState(false)
  const [instructionOpen, setInstructionOpen] = useState(false)
  const [userPresets, setUserPresets] = useState<Preset[]>(() => loadUserPresets())
  const [, setFluxConfig] = useState<FluxConfig>()
  const [modelsPayload, setModelsPayload] = useState<ModelsPayload>()
  const [bgRemovalModels, setBgRemovalModels] = useState<string[]>([])
  const [loraTriggers, setLoraTriggers] = useState<Record<string, string>>({})
  const loraSelectRef = useRef<HTMLSelectElement>(null)
  // Single-flight guard для Generate: синхронный ref блокирует повторные клики/хоткеи/
  // double-tap до того, как React-state успеет обновиться. isSubmitting — для UI.
  const generateInFlightRef = useRef(false)
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

  useEffect(() => {
    try {
      const saved = sessionStorage.getItem(SESSION_KEY)
      if (!saved) return
      const s = JSON.parse(saved)
      if (s.prompt !== undefined) setPrompt(s.prompt)
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
      if (s.tab) setTab(s.tab)
      if (s.sampler) setSampler(s.sampler)
      if (s.lang) setLang(s.lang)
    } catch { /* ignore */ }
  }, [])

  useEffect(() => {
    sessionStorage.setItem(SESSION_KEY, JSON.stringify({
      prompt, negativePrompt, mode, seed, width, height, steps, cfg, strength,
      selectedLora, modelProfile, provider, paintTool, tab, sampler, lang,
    }))
  }, [prompt, negativePrompt, mode, seed, width, height, steps, cfg, strength, selectedLora, modelProfile, provider, paintTool, tab, sampler, lang])

  // Trusted auth-v2 state (cookie session). The ONLY source for the generation lock.
  const { status: authV2Status, me: authMe } = useAuthV2()
  const isAuthedV2 = authV2Status === 'authed'
  const [authModalOpen, setAuthModalOpen] = useState(false)

  const currentUser = (bootstrap?.user || {}) as { id?: string; role?: string; username?: string; firstName?: string; plan?: string; galleryEnabled?: boolean }
  const adminSummaryReady = Boolean(admin && !('detail' in admin))
  const isAdmin = currentUser.role === 'admin' || authMe?.account?.role === 'admin' || adminSummaryReady
  const galleryLocked = !(isAdmin || authMe?.account?.gallery_access || currentUser.galleryEnabled || ['mini', 'plus', 'pro'].includes(String(currentUser.plan || '')))
  const activeMode = modes.find((item) => item.id === mode)!
  const cloudLimited = provider === 'openrouter'
  const actualMode: Mode = mode === 'paint' && paintTool !== 'sketch' ? paintTool : mode
  const allPresets = [...workflowPresets, ...userPresets]
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

  const fetchGallery = useCallback(async () => {
    // /api/gallery returns 401 (JSON {detail}) when unauthenticated; only ever
    // store an array so gallery.slice/.map/.length never crash the render.
    const images = await apiFetch('/gallery').then((r) => (r.ok ? r.json() : [])).catch(() => [])
    setGallery(Array.isArray(images) ? images : [])
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
      if (next.status === 'completed') fetchGallery()
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
        void generate()
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
    if (preset.mode === 'inpaint' || preset.mode === 'outpaint') {
      setMode('paint')
      setPaintTool(preset.mode)
    } else {
      setMode(preset.mode as Mode)
      if (preset.mode === 'paint') setPaintTool('sketch')
    }
    setPrompt(preset.prompt)
    setDiscoverOpen(false)
    setTab('studio')
  }

  function selectMode(nextMode: Mode) {
    setMode(nextMode)
    setTab('studio')
    setDiscoverOpen(false)
    if (nextMode === 'faceswap' && selectedLora === 'none' && faceLora) setSelectedLora(faceLora.id)
    if (nextMode === 'paint') setPaintTool('sketch')
    // Edit: «Дополнительное пожелание» необязательное — оставляем пустым, чтобы был виден
    // placeholder, а задачу собирает Prompt Composer из ролей.
    if (nextMode === 'edit') { setPrompt(''); return }
    const defaultPreset = allPresets.find((item) => item.mode === (nextMode === 'paint' ? 'paint' : nextMode))
    if (defaultPreset) setPrompt(defaultPreset.prompt)
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
      setPrompt(image.promptOriginal)
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
    ...(isAdmin ? [{ id: 'admin' as Tab, label: copy.admin, icon: Shield }] : []),
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
          {mode === 'paint' && <div className="mobile-paint-actions"><button onClick={() => { setPaintTool('sketch'); setPrompt(workflowPresets.find((item) => item.id === 'sketch-01')?.prompt || ''); setPaintEditor('sketch') }}><strong>Эскиз</strong><span>Рисование на чистом холсте</span></button><button onClick={() => { setPaintTool('inpaint'); setPrompt(workflowPresets.find((item) => item.id === 'mask-01')?.prompt || ''); setPaintEditor('mask') }}><strong>Маска / расширение</strong><span>Закрасить область или расширить изображение</span></button></div>}
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
          <button className="mobile-lang-toggle" onClick={() => setLang(lang === 'ru' ? 'en' : 'ru')} title={copy.language}>
            {lang.toUpperCase()}
          </button>
        </div>
        <button className="admin-link" onClick={() => setTab('admin')}>{copy.admin}</button>
      </aside>

      <main className="workspace">
        <header className="topbar">
          <div>
            <h1>{activeMode[lang]}</h1>
            <p>{copy.hint}</p>
          </div>
          <div className="top-actions">
            <button className="icon-button" onClick={() => setLang(lang === 'ru' ? 'en' : 'ru')} title={copy.language}>
              <Languages size={18} /> {lang.toUpperCase()}
            </button>
            <button className="icon-button lockable" onClick={openGallery} title={galleryLocked ? 'Галерея доступна с подпиской' : copy.gallery}><GalleryHorizontalEnd size={18} />{galleryLocked && <Lock className="lock-badge" size={11} />}{copy.gallery}</button>
            <button className="icon-button" onClick={() => setTab('presets')} title={copy.help}><Sparkles size={18} />{copy.help}</button>
            <button className="icon-button" onClick={() => setTab('settings')} title={copy.settings}><Settings size={18} />{copy.settings}</button>
            {isAdmin && <button className="icon-button" onClick={() => setTab('admin')} title={copy.admin}><Shield size={18} />{copy.admin}</button>}
            <button className="icon-button" title="Fullscreen"><Expand size={18} /></button>
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
            <section className="preview-panel" style={{ aspectRatio: `${previewAspectWidth} / ${previewAspectHeight}` }}>
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
                  {discoverOpen && <DiscoverPanel lang={lang} mode={mode} presets={visiblePresets} applyPreset={applyPreset} addUserPreset={addUserPreset} currentPrompt={prompt} />}
                </>
              )}
            </section>
          </div>
        )}

        {tab === 'gallery' && !galleryLocked && <GalleryView copy={copy} images={gallery} selected={selected} setSelected={setSelected} handleUseImageAs={useImageAs} refreshGallery={fetchGallery} clearSelected={() => setSelected(undefined)} backToStudio={() => setTab('studio')} view={galleryView} setView={setGalleryView} sendImage={sendImage} pickSlot={pendingEditSlot} onPickForSlot={assignGalleryToEditSlot} cancelPick={() => { setPendingEditSlot(null); setTab('studio') }} />}
        {tab === 'gallery' && galleryLocked && <SettingsView copy={copy} bootstrap={bootstrap} setBootstrap={setBootstrap} openAdmin={() => setTab('admin')} openGallery={() => setTab('gallery')} backToStudio={() => setTab('studio')} provider={provider} setProvider={setProvider} width={width} setWidth={setWidth} height={height} setHeight={setHeight} steps={steps} setSteps={setSteps} setCfg={setCfg} isAuthedV2={isAuthedV2} openAuthModal={() => setAuthModalOpen(true)} authMe={authMe} />}
        {tab === 'presets' && <HelpView lang={lang} applyPreset={applyPreset} copy={copy} backToStudio={() => setTab('studio')} />}
        {tab === 'settings' && <SettingsView copy={copy} bootstrap={bootstrap} setBootstrap={setBootstrap} openAdmin={() => setTab('admin')} openGallery={() => setTab('gallery')} backToStudio={() => setTab('studio')} provider={provider} setProvider={setProvider} width={width} setWidth={setWidth} height={height} setHeight={setHeight} steps={steps} setSteps={setSteps} setCfg={setCfg} isAuthedV2={isAuthedV2} openAuthModal={() => setAuthModalOpen(true)} authMe={authMe} />}
        {tab === 'admin' && isAdmin && <AdminView copy={copy} admin={admin} backToStudio={() => setTab('studio')} provider={provider} setProvider={setProvider} modelProfile={modelProfile} setModelProfile={setModelProfile} seed={seed} setSeed={setSeed} width={width} setWidth={setWidth} height={height} setHeight={setHeight} steps={steps} setSteps={setSteps} cfg={cfg} setCfg={setCfg} sampler={sampler} setSampler={setSampler} selectedLora={settingsSelectedLora} setSelectedLora={setSelectedLora} loraOptions={loraOptions} modelsPayload={modelsPayload} bgRemovalModels={bgRemovalModels} loraSelectRef={loraSelectRef} resetDefaults={resetDefaults} />}
        {tab === 'admin' && !isAdmin && <SettingsView copy={copy} bootstrap={bootstrap} setBootstrap={setBootstrap} openAdmin={() => setTab('admin')} openGallery={() => setTab('gallery')} backToStudio={() => setTab('studio')} provider={provider} setProvider={setProvider} width={width} setWidth={setWidth} height={height} setHeight={setHeight} steps={steps} setSteps={setSteps} setCfg={setCfg} isAuthedV2={isAuthedV2} openAuthModal={() => setAuthModalOpen(true)} authMe={authMe} />}

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
  setPaintEditor: (value: PaintEditor) => void
}

function ModeWorkspace(props: ModeWorkspaceProps) {
  const { mode, paintTool, setPaintTool, copy, inputOne, inputTwo, setInputOne, setInputTwo, upload, applyLastImage, setPrompt, setPaintEditor } = props
  if (mode === 'paint') {
    const sketchPrompt = workflowPresets.find((item) => item.id === 'sketch-01')?.prompt || ''
    const maskPrompt = workflowPresets.find((item) => item.id === 'mask-01')?.prompt || ''
    function openSketch() {
      setPaintTool('sketch')
      setPrompt(sketchPrompt)
      setPaintEditor('sketch')
    }
    function openMask() {
      setPaintTool('inpaint')
      setPrompt(maskPrompt)
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
  setCanvasSnapshot: (value?: string) => void
}) {
  const { editor, paintTool, setPaintTool, onClose, copy, inputOne, setInputOne, upload, paintLines, setPaintLines, maskLines, setMaskLines, tool, setTool, brushSize, setBrushSize, paintColor, setPaintColor, layerOpacity, setLayerOpacity, outpaint, setOutpaint, drawingRef, canvasRef, setPrompt, setCanvasSnapshot } = props
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
      setPrompt(workflowPresets.find((item) => item.id === 'sketch-01')?.prompt || '')
    } else if (paintTool === 'outpaint') {
      setCanvasSnapshot(await createImageMask(inputOne, activeLines, stageSize))
      setPrompt(workflowPresets.find((item) => item.id === 'outpaint-01')?.prompt || '')
    } else {
      setCanvasSnapshot(await createImageMask(inputOne, activeLines, stageSize))
      setPrompt(workflowPresets.find((item) => item.id === 'mask-01')?.prompt || '')
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
    {isSketch ? <div className="paint-editor-top"><div className="canvas-size-bar"><strong>ХОЛСТ</strong><input type="number" value={canvasDraft.width} onChange={(e) => setCanvasDraft({ ...canvasDraft, width: Number(e.target.value) })} /><span>⇆</span><input type="number" value={canvasDraft.height} onChange={(e) => setCanvasDraft({ ...canvasDraft, height: Number(e.target.value) })} /><button onClick={applyCanvasTarget}>Применить</button><button className="editor-close" onClick={onClose} aria-label="Закрыть"><X size={18} /></button></div><div className="editor-zoom"><button>-</button><button>Вписать</button><button>+</button></div><button className="secondary" onClick={() => setActiveLines((lines) => lines.slice(0, -1))}><RotateCcw size={16} />Назад</button><button className="secondary" onClick={() => setActiveLines([])}>Очистить</button><button className="save-sketch" onClick={applyEditor}>Сохранить</button></div> : <div className="paint-editor-top mask-top"><button className={paintTool === 'inpaint' ? 'active' : ''} onClick={() => { setPaintTool('inpaint'); setPrompt(workflowPresets.find((item) => item.id === 'mask-01')?.prompt || '') }}>Закрасить область</button><button className={paintTool === 'outpaint' ? 'active' : ''} onClick={() => { setPaintTool('outpaint'); setPrompt(workflowPresets.find((item) => item.id === 'outpaint-01')?.prompt || '') }}>Расширить изображение</button><button onClick={() => upload(setInputOne)}>Загрузить</button><button className={tool === 'brush' ? 'active' : ''} onClick={() => setTool('brush')}>● Кисть</button><button className={tool === 'eraser' ? 'active' : ''} onClick={() => setTool('eraser')}>○ Ластик</button><label>Размер<input type="range" min="2" max="60" value={brushSize} onChange={(e) => setBrushSize(Number(e.target.value))} /></label><output>{brushSize}</output><label>Жест.<input type="range" min="0" max="100" value="100" readOnly /></label><output>100</output><button onClick={() => setActiveLines((lines) => lines.slice(0, -1))}>↩ Назад</button><button onClick={() => setActiveLines([])}>× Сбросить маску</button><button className="save-sketch" onClick={applyEditor}>Применить</button><button className="secondary" onClick={onClose}>Отмена</button></div>}
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
  const actions = job.resultUrl ? <div className="result-actions"><a className="secondary" href={job.resultUrl} download><Download size={16} />{copy.download}</a><button className="secondary" onClick={() => sendImage('telegram', job.resultImageId)}>{copy.sendTg}</button></div> : null
  return <div className={`job-card ${job.status}`}>{canCompare ? <div className="compare-frame"><img className="compare-before" src={beforeImage} /><div className="compare-after" style={{ clipPath: `inset(0 0 0 ${compare}%)` }}><img src={job.resultUrl} /></div><i className="compare-line" style={{ left: `${compare}%` }}><span>↔</span></i><input aria-label="До после" type="range" min="0" max="100" value={compare} onChange={(e) => setCompare(Number(e.target.value))} />{actions}</div> : job.resultUrl ? <div className="result-frame"><img src={job.resultUrl} />{actions}</div> : null}</div>
}

function GalleryView({ copy, images, selected, setSelected, handleUseImageAs, refreshGallery, clearSelected, backToStudio, view, setView, sendImage, pickSlot = null, onPickForSlot, cancelPick }: { copy: Copy; images: GalleryImage[]; selected?: GalleryImage; setSelected: (image: GalleryImage) => void; handleUseImageAs: (image: GalleryImage, target: Mode, slot?: number) => void; refreshGallery: () => Promise<void>; clearSelected: () => void; backToStudio: () => void; view: 'grid' | 'list'; setView: (view: 'grid' | 'list') => void; sendImage: (platform: 'telegram' | 'max', imageId?: string) => void; pickSlot?: number | null; onPickForSlot?: (image: GalleryImage) => void; cancelPick?: () => void }) {
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

function DiscoverPanel({ lang, presets: panelPresets, applyPreset, addUserPreset, currentPrompt }: { lang: Lang; mode: Mode; presets: Preset[]; applyPreset: (preset: Preset) => void; addUserPreset: (name: string, presetPrompt: string) => void; currentPrompt: string }) {
  const [name, setName] = useState('')
  const [presetPrompt, setPresetPrompt] = useState(currentPrompt)
  const groups = panelPresets.reduce<Record<string, Preset[]>>((acc, preset) => {
    const key = preset.category || 'USER'
    acc[key] = [...(acc[key] || []), preset]
    return acc
  }, {})
  return <div className="discover-panel"><div className="discover-head"><strong>Шаблоны</strong><span>Выберите готовый запрос или сохраните свой</span></div><div className="preset-create"><strong>Добавить свой шаблон</strong><input placeholder="Название" value={name} onChange={(e) => setName(e.target.value)} /><textarea placeholder="Текст запроса" value={presetPrompt} onChange={(e) => setPresetPrompt(e.target.value)} /><button onClick={() => { if (name.trim() && presetPrompt.trim()) { addUserPreset(name.trim(), presetPrompt.trim()); setName(''); setPresetPrompt('') } }}>Сохранить</button></div><div className="discover-groups">{Object.entries(groups).map(([category, items]) => <section className="discover-category" key={category}><h3>{categoryTitle(category, lang)}</h3><div className="discover-cards">{items.map((preset) => <button key={preset.id} onClick={() => applyPreset(preset)}><Sparkles size={16} /><span>{preset[lang]}{preset.dual ? ' · 2 IMG' : ''}</span><small>{preset.prompt.slice(0, 120)}</small></button>)}</div></section>)}</div></div>
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

function SettingsView({ copy, bootstrap, setBootstrap, openAdmin, openGallery, backToStudio, provider, setProvider, width, setWidth, height, setHeight, steps, setSteps, setCfg, isAuthedV2 = false, openAuthModal, authMe }: { copy: Copy; bootstrap?: Record<string, unknown>; setBootstrap: Dispatch<SetStateAction<Record<string, unknown> | undefined>>; openAdmin: () => void; openGallery?: () => void; backToStudio: () => void; provider: string; setProvider: (value: string) => void; width: number; setWidth: (value: number) => void; height: number; setHeight: (value: number) => void; steps: number; setSteps: (value: number) => void; setCfg: (value: number) => void; isAuthedV2?: boolean; openAuthModal?: () => void; authMe?: MeV2 | null }) {
  const user = (bootstrap?.user || {}) as { id?: string; role?: string; username?: string; firstName?: string; email?: string; plan?: string; galleryEnabled?: boolean; tokenBalance?: number }
  const account = authMe?.account
  const quality = steps <= 4 ? 'fast' : steps <= 8 ? 'standard' : 'max'
  const tokenPrice = (quality === 'fast' ? 1 : quality === 'standard' ? 2 : 4) * (provider === 'openrouter' ? 2 : 1)
  const referralLink = `${window.location.origin}?ref=${authMe?.profile?.public_user_code || user.id || 'guest'}`
  const plan = String(account?.plan || user.plan || 'mini').toLowerCase()
  const galleryOpen = Boolean(account?.gallery_access ?? (account?.role === 'admin' || user.role === 'admin' || ['mini', 'plus', 'pro'].includes(plan)))
  const planLabel = plan.toUpperCase()
  const tokenBalance = Number(account?.token_balance ?? user.tokenBalance ?? 0)
  const planDaily: Record<string, number> = { free: 10, mini: 50, plus: 100, pro: 200 }
  const dailyTokens = planDaily[plan] ?? 50
  const publicCode = String(authMe?.profile?.public_user_code || user.id || '').replace(/^web_/, '').toUpperCase()
  const planCards = [
    { id: 'free', title: 'Free', note: 'Базовый доступ', daily: 10, features: ['Базовые модели', 'Стандартная скорость', 'Промокоды доступны'], disabled: ['Галерея закрыта'] },
    { id: 'mini', title: 'Mini', note: 'Оптимальный старт', daily: 50, features: ['Стандартные модели', 'Галерея открыта', 'Реферальные бонусы'], disabled: [] },
    { id: 'plus', title: 'Plus', note: 'Больше возможностей', daily: 100, features: ['HD-модели', 'Ускоренная генерация', 'Расширенная галерея'], disabled: [] },
    { id: 'pro', title: 'Pro', note: 'Максимум мощности', daily: 200, features: ['Продвинутые модели', 'Приоритетная очередь', 'Полный доступ к галерее'], disabled: [] },
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
  const friendPromoCode = `FRIEND-${String(authMe?.profile?.public_user_code || user.id || 'GUEST').replace(/^web_/, '').toUpperCase().slice(0, 12)}`
  void openAdmin // prop accepted for call-site compatibility
  useEffect(() => { setDisplayName(authMe?.profile?.display_name || '') }, [authMe?.profile?.display_name])
  useEffect(() => { setViewedPlan(plan) }, [plan])
  useEffect(() => {
    setAvatarUrl(authMe?.profile?.avatar_url || avatarPresets[0].url)
    setAvatarPreset(authMe?.profile?.avatar_preset || '')
    setAvatarMsg('')
  }, [authMe?.profile?.avatar_url, authMe?.profile?.avatar_preset])
  const displayEmail = authMe?.identities?.find((i) => i.provider_email)?.provider_email
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
            <span className={galleryOpen ? 'usr-chip green' : 'usr-chip'}>{galleryOpen ? 'Галерея открыта' : 'Галерея закрыта'}</span>
          </div>
          <div className="usr-code"><span>Публичный код: {publicCode || 'GUEST'}</span></div>
          <div className="usr-metrics">
            <div><span>Токенов в сутки</span><strong>{dailyTokens} / {dailyTokens}</strong><small>по текущему тарифу</small></div>
            <div><span>Баланс токенов</span><strong>{tokenBalance}</strong><small>доступно сейчас</small></div>
            <div><span>Галерея</span><strong>{galleryOpen ? 'Открыта' : 'Закрыта'}</strong><small>доступ зависит от тарифа</small></div>
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
      <section className="usr-profile-dashboard">
        <article className="usr-card usr-stat-card"><span>Сегодня доступно</span><strong>{dailyTokens}</strong><small>токенов</small></article>
        <article className="usr-card usr-stat-card"><span>Баланс</span><strong>{tokenBalance}</strong><small>токенов</small></article>
        <article className="usr-card usr-stat-card"><span>Галерея</span><strong>{galleryOpen ? 'Открыта' : 'Закрыта'}</strong><small>{galleryOpen ? 'без ограничений' : 'по тарифу'}</small></article>
        <article className="usr-card usr-stat-card"><span>Промокод друга</span><strong>{friendPromoCode}</strong><small>+50 токенов</small></article>
      </section>
      </>}

      {settingsTab === 'tariffs' && <>
      <section className="usr-section">
        <div className="usr-tariff-summary usr-card">
          <div><span>Текущий тариф</span><strong>{planLabel}</strong></div>
          <div><span>Токены в сутки</span><strong>{dailyTokens}</strong></div>
          <div><span>Галерея</span><strong>{galleryOpen ? 'открыта' : 'закрыта'}</strong></div>
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
              <span>токенов в сутки</span>
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
          <article className="usr-card usr-stat-card"><span>Дневной лимит</span><strong>{dailyTokens} / {dailyTokens}</strong><small>использовано сегодня</small></article>
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
            <p>Ваш текущий доступ: <strong>{galleryOpen ? 'открыт' : 'закрыт'}</strong>. Загружайте, просматривайте и сохраняйте работы.</p>
            <button type="button" className="usr-ghost" disabled={!galleryOpen || !openGallery} onClick={() => openGallery?.()}>{galleryOpen ? 'Перейти в галерею' : 'Галерея закрыта'}</button>
          </article>
        </div>
      </section>
      </>}
    </section>
  )
}

function AdminView({ copy, admin, backToStudio, provider, setProvider, modelProfile, setModelProfile, seed, setSeed, width, setWidth, height, setHeight, steps, setSteps, cfg, setCfg, sampler, setSampler, selectedLora, setSelectedLora, loraOptions, modelsPayload, bgRemovalModels, loraSelectRef, resetDefaults }: { copy: Copy; admin?: Record<string, unknown>; backToStudio: () => void; provider: string; setProvider: (value: string) => void; modelProfile: string; setModelProfile: (value: string) => void; seed: number; setSeed: (value: number) => void; width: number; setWidth: (value: number) => void; height: number; setHeight: (value: number) => void; steps: number; setSteps: (value: number) => void; cfg: number; setCfg: (value: number) => void; sampler: string; setSampler: (value: string) => void; selectedLora: string; setSelectedLora: (value: string) => void; loraOptions: LoraOption[]; modelsPayload?: ModelsPayload; bgRemovalModels: string[]; loraSelectRef: RefObject<HTMLSelectElement | null>; resetDefaults: () => void }) {
  const [tab, setTab] = useState<'dashboard' | 'models' | 'tokens' | 'users' | 'queue' | 'errors'>('dashboard')
  const [showLegacyUsers, setShowLegacyUsers] = useState(false)
  const [limits, setLimits] = useState({ hourly: 10, daily: 50 })
  const [saved, setSaved] = useState('')
  const [promoDraft, setPromoDraft] = useState({ code: 'START50', tokens: 50, activations: 100 })
  const [finance, setFinance] = useState({ tokenRevenue: 12450, tokenCost: 2380, electricity: 740, promoBudget: 1500 })
  const [adminUsers, setAdminUsers] = useState<AdminUser[]>([])
  const [promoCodes, setPromoCodes] = useState<PromoCode[]>([])
  const [modelStatus, setModelStatus] = useState<any>(null)
  const [modelSel, setModelSel] = useState({ editModelProfile: 'flux_klein_9b', poseModelProfile: '' })
  const [userDraft, setUserDraft] = useState({ userId: 'telegram_123456789', username: '', firstName: '', lastName: '', middleName: '', phone: '', email: '', country: '', city: '', role: 'user', plan: 'mini', tokenBalance: 50, galleryEnabled: true })
  const [userFormOpen, setUserFormOpen] = useState(false)
  const [editingUserId, setEditingUserId] = useState<string | null>(null)
  const [userHistory, setUserHistory] = useState<UserHistory | null>(null)
  const [adminMessage, setAdminMessage] = useState('')
  const diffusionModels = modelsPayload?.diffusion_models?.length ? modelsPayload.diffusion_models : [modelProfile]
  const textEncoders = modelsPayload?.text_encoders || []
  const vaes = modelsPayload?.vaes || []
  const fluxLoras = useMemo(() => {
    const is4b = /4b/i.test(modelProfile)
    return loraOptions.filter((item) => {
      if (item.id === 'none') return false
      if (!/bfs|flux|head|face/i.test(item.id)) return false
      return is4b ? /4b/i.test(item.id) : /9b/i.test(item.id)
    })
  }, [loraOptions, modelProfile])
  const queue = Array.isArray(admin?.queue) ? admin.queue : []
  const recentErrors = Array.isArray(admin?.recentErrors) ? admin.recentErrors : []
  const health = Number(admin?.errors ?? 0) === 0 ? 'Стабильно' : 'Есть ошибки'
  const netProfit = finance.tokenRevenue - finance.tokenCost - finance.electricity - finance.promoBudget
  async function saveLimits() {
    const result = await apiFetch('/admin/limits', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(limits) }).then((r) => r.json())
    setSaved(JSON.stringify(result.rateLimits))
  }
  const refreshAdminData = useCallback(async () => {
    const [users, promos, settings, mstatus] = await Promise.all([
      apiFetch('/admin/users').then((r) => r.json()).catch(() => []),
      apiFetch('/admin/promos').then((r) => r.json()).catch(() => []),
      apiFetch('/admin/settings').then((r) => r.json()).catch(() => ({})),
      apiFetch('/admin/model-status').then((r) => r.json()).catch(() => null),
    ])
    setAdminUsers(users)
    setPromoCodes(promos)
    if (settings.finance) setFinance((current) => ({ ...current, ...settings.finance }))
    if (settings.models) setModelSel((current) => ({ ...current, ...settings.models }))
    if (mstatus) setModelStatus(mstatus)
  }, [])
  async function saveModelSettings(next: { editModelProfile: string; poseModelProfile: string }) {
    setModelSel(next)
    const result = await apiFetch('/admin/settings/models', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ settings: next }) }).then((r) => r.json()).catch(() => null)
    setAdminMessage(result?.ok ? 'Настройки моделей сохранены' : 'Ошибка сохранения моделей')
    const mstatus = await apiFetch('/admin/model-status').then((r) => r.json()).catch(() => null)
    if (mstatus) setModelStatus(mstatus)
  }
  useEffect(() => { refreshAdminData() }, [refreshAdminData])
  async function saveFinance() {
    const result = await apiFetch('/admin/settings/finance', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ settings: finance }) }).then((r) => r.json())
    setAdminMessage(result.ok ? 'Финансы сохранены' : 'Ошибка сохранения')
  }
  async function registerUser() {
    const payload = { ...userDraft, tokenBalance: Number(userDraft.tokenBalance) }
    const result = editingUserId
      ? await apiFetch(`/admin/users/${encodeURIComponent(editingUserId)}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) }).then((r) => r.json())
      : await apiFetch('/admin/users', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) }).then((r) => r.json())
    setAdminMessage(result.ok ? `Пользователь ${result.user.id} сохранен` : 'Ошибка регистрации')
    if (result.ok) { setUserFormOpen(false); setEditingUserId(null); setUserHistory(null) }
    await refreshAdminData()
  }
  async function updateUser(userId: string, patch: Partial<{ role: string; plan: string; tokenBalance: number; galleryEnabled: boolean; banned: boolean; phone: string; email: string; country: string; city: string }>) {
    const result = await apiFetch(`/admin/users/${encodeURIComponent(userId)}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(patch) }).then((r) => r.json())
    setAdminMessage(result.ok ? `Пользователь ${result.user.id} обновлен` : 'Ошибка обновления')
    await refreshAdminData()
  }
  async function editUser(item: AdminUser) {
    setEditingUserId(item.id)
    setUserHistory(null)
    setUserDraft({
      userId: item.id,
      username: item.username || '',
      firstName: item.first_name || '',
      lastName: item.last_name || '',
      middleName: item.middle_name || '',
      phone: item.phone || '',
      email: item.email || '',
      country: item.country || '',
      city: item.city || '',
      role: item.role,
      plan: item.plan,
      tokenBalance: item.token_balance,
      galleryEnabled: Boolean(item.gallery_enabled),
    })
    setUserFormOpen(true)
    const history = await apiFetch(`/admin/users/${encodeURIComponent(item.id)}/history`).then((r) => r.json()).catch(() => null)
    if (history?.ok) setUserHistory(history)
  }
  function closeUserEditor() {
    setUserFormOpen(false)
    setEditingUserId(null)
    setUserHistory(null)
  }
  async function deleteUser(userId: string) {
    if (!window.confirm(`Удалить пользователя ${userId}?`)) return
    const result = await apiFetch(`/admin/users/${encodeURIComponent(userId)}`, { method: 'DELETE' }).then((r) => r.json())
    setAdminMessage(result.ok ? `Пользователь ${userId} удален` : 'Ошибка удаления')
    await refreshAdminData()
  }
  function downloadUsersExcel() {
    const columns = ['ID', 'Фамилия', 'Имя', 'Отчество', 'Username', 'Телефон', 'Почта', 'Страна', 'Город', 'Роль', 'Тариф', 'Токены', 'Использовано токенов', 'Генерации', 'Минуты в приложении', 'Промокоды', 'Рефералы', 'Бан', 'Последний вход']
    const rows = adminUsers.map((item) => [
      item.id,
      item.last_name || '',
      item.first_name || '',
      item.middle_name || '',
      item.username || '',
      item.phone || '',
      item.email || '',
      item.country || '',
      item.city || '',
      item.role,
      item.plan,
      item.token_balance,
      item.tokens_used || 0,
      item.generation_count || 0,
      Math.round((item.total_time_seconds || 0) / 60),
      item.promo_used_count || 0,
      item.referrals_count || 0,
      item.banned ? 'да' : 'нет',
      item.last_login_at || '',
    ])
    const csv = [columns, ...rows].map((row) => row.map((value) => `"${String(value).replaceAll('"', '""')}"`).join(';')).join('\n')
    const blob = new Blob([`\uFEFF${csv}`], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `users-${new Date().toISOString().slice(0, 10)}.csv`
    link.click()
    URL.revokeObjectURL(url)
  }
  async function createPromo() {
    const result = await apiFetch('/admin/promos', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ code: promoDraft.code, tokens: Number(promoDraft.tokens), activationLimit: Number(promoDraft.activations) }) }).then((r) => r.json())
    setAdminMessage(result.ok ? `Промокод ${result.promo.code} сохранен` : 'Ошибка промокода')
    await refreshAdminData()
  }
  return <section className="admin-page">
    <div className="view-actions in-panel"><button className="secondary" onClick={backToStudio}><WandSparkles size={16} />{copy.backToStudio}</button><button className="secondary" onClick={resetDefaults}>По умолчанию</button></div>
    <div className="admin-head"><div><h2>{copy.admin}</h2><p>Управление генерациями, токенами, моделями, тарифами и доступами.</p>{adminMessage && <small>{adminMessage}</small>}</div><strong>{health}</strong></div>
    <div className="admin-tabbar">{[['dashboard', 'Дашборд'], ['models', 'Модели'], ['tokens', 'Токены'], ['users', 'Пользователи'], ['queue', 'Очередь'], ['errors', 'Ошибки']].map(([id, label]) => <button key={id} className={tab === id ? 'active' : ''} onClick={() => setTab(id as typeof tab)}>{label}</button>)}</div>
    {tab === 'dashboard' && <div className="admin-section">
      <div className="admin-grid"><div><strong>{copy.users}</strong><span>{String(admin?.users ?? 1)}</span><small>аккаунтов всего</small></div><div><strong>{copy.jobs}</strong><span>{String(admin?.jobs ?? 0)}</span><small>задач в системе</small></div><div><strong>Доход</strong><span>{finance.tokenRevenue.toLocaleString('ru-RU')} ₽</span><small>продажа токенов</small></div><div><strong>Прибыль</strong><span>{netProfit.toLocaleString('ru-RU')} ₽</span><small>после токенов, света и акций</small></div></div>
      <div className="admin-grid"><div><strong>Себестоимость</strong><span>{finance.tokenCost.toLocaleString('ru-RU')} ₽</span><small>затраты на внешние токены/API</small></div><div><strong>Свет</strong><span>{finance.electricity.toLocaleString('ru-RU')} ₽</span><small>электричество локальной GPU</small></div><div><strong>Акции</strong><span>{finance.promoBudget.toLocaleString('ru-RU')} ₽</span><small>промокоды и рефералы</small></div><div><strong>{copy.errors}</strong><span>{String(admin?.errors ?? 0)}</span><small>ошибок сейчас</small></div></div>
      <div className="admin-two-col"><article><h3>Состояние генератора</h3><p>Провайдер: {provider === 'openrouter' ? 'OpenRouter Cloud' : 'ComfyUI локально'}</p><p>Модель: {modelProfile}</p><p>Очередь: {queue.length}</p><p>LoRA для лица: {selectedLora}</p></article><article><h3>Быстрые действия</h3><button className="secondary" onClick={() => setTab('models')}>Настроить модели</button><button className="secondary" onClick={() => setTab('tokens')}>Тарифы и финансы</button><button className="secondary" onClick={() => setTab('users')}>Админы и пользователи</button></article></div>
    </div>}
    {tab === 'models' && <div className="admin-section">
      <h3>Модель редактора (FLUX.2 [klein])</h3>
      <div className="settings-grid">
        <label>Default edit model<select value={modelSel.editModelProfile} onChange={(e) => void saveModelSettings({ ...modelSel, editModelProfile: e.target.value })}>{(modelStatus?.profiles || []).map((p: any) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
        <label>Pose model/profile<select value={modelSel.poseModelProfile} onChange={(e) => void saveModelSettings({ ...modelSel, poseModelProfile: e.target.value })}><option value="">как edit-модель</option>{(modelStatus?.profiles || []).map((p: any) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
        <small>ComfyUI: {modelStatus?.comfyuiAvailable ? 'доступен' : 'недоступен'}</small>
      </div>
      <div className="admin-table">{(modelStatus?.profiles || []).map((p: any) => <article key={p.id}>
        <strong>{p.name}{modelSel.editModelProfile === p.id ? ' · default edit' : ''}</strong>
        <span>{p.modelName}</span>
        <small>установлена: {p.installed ? 'да' : 'нет'} · нода: {p.requiredNode}</small>
        <p>base edit: <b>{p.baseEdit === 'available' ? 'available' : 'missing'}</b> · faceswap: <b>{p.faceswapLora}</b></p>
        <p>pose workflow: <b>{!p.supportsPose ? 'не поддерживается этой моделью' : p.pose === 'available' ? 'available' : 'missing'}</b></p>
        {p.missingFiles?.length ? <small>missing files: {p.missingFiles.join(', ')}</small> : null}
        {p.poseMissing?.length ? <small>pose требует: {p.poseMissing.join(', ')}</small> : null}
      </article>)}</div>
      <h3>OpenRouter: облачный маршрут</h3>
      <div className="admin-table">{openRouterImageModels.map((item) => <article key={item.id}><strong>{item.name}</strong><span>{item.id}</span><small>{item.use}</small><p>Вход: {item.prompt} · Выход: {item.completion} · Image: {item.image}</p><button className={provider === 'openrouter' && modelProfile === item.id ? 'secondary active' : 'secondary'} onClick={() => { setProvider('openrouter'); setModelProfile(item.id) }}>Использовать · {item.tokenCost} токенов</button></article>)}</div>
      <h3>ComfyUI: локальные Flux 2</h3>
      <div className="admin-table">{localFluxProfiles.map((profile) => <article key={profile.id}><strong>{profile.title}</strong><span>{profile.modelFile}</span><small>Качество: {profile.quality} · По умолчанию: {profile.defaultSteps} шага</small><div className="token-rules">{profile.tokenRules.map((rule) => <p key={rule.steps}>{rule.steps}: <b>{rule.tokens}</b> ток.</p>)}</div><button className={modelProfile === profile.modelFile ? 'secondary active' : 'secondary'} onClick={() => { setProvider('comfyui'); setModelProfile(profile.modelFile); setSteps(profile.defaultSteps) }}>Выбрать</button></article>)}</div>
      <h3>Файлы ComfyUI</h3>
      <div className="settings-grid"><label>{copy.model}<select value={modelProfile} onChange={(e) => setModelProfile(e.target.value)}>{diffusionModels.map((item) => <option key={item} value={item}>{item}</option>)}</select></label><label>Text encoder<input value={textEncoders.join(', ') || modelsPayload?.selected?.textEncoder || 'not found'} readOnly /></label><label>VAE<input value={vaes.join(', ') || modelsPayload?.selected?.vae || 'not found'} readOnly /></label><label>Remove Background<input value={bgRemovalModels.join(', ') || 'not found'} readOnly /></label><label>{copy.seed}<input type="number" value={seed} onChange={(e) => setSeed(Number(e.target.value))} /></label><button className="secondary" onClick={() => setSeed(Math.floor(Math.random() * 999999999))}><RotateCcw size={16} />{copy.randomSeed}</button><label>Width<input type="number" value={width} onChange={(e) => setWidth(Number(e.target.value))} /></label><label>Height<input type="number" value={height} onChange={(e) => setHeight(Number(e.target.value))} /></label><label>{copy.steps}<input type="number" value={steps} onChange={(e) => setSteps(Number(e.target.value))} /></label><label>{copy.cfg}<input type="number" step="0.1" value={cfg} onChange={(e) => setCfg(Number(e.target.value))} /></label><label>{copy.sampler}<select value={sampler} onChange={(e) => setSampler(e.target.value)}><option value="er_sde">er_sde</option><option value="euler">euler</option><option value="dpmpp_2m">dpmpp_2m</option></select></label><label>Face LoRA<select ref={loraSelectRef} value={selectedLora} onChange={(e) => setSelectedLora(e.target.value)}>{fluxLoras.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label></div>
    </div>}
    {tab === 'tokens' && <div className="admin-section"><h3>Токены, тарифы, финансы и акции</h3><div className="admin-two-col"><article><h3>{copy.limits}</h3><label>hourly<input type="number" value={limits.hourly} onChange={(e) => setLimits({ ...limits, hourly: Number(e.target.value) })} /></label><label>daily<input type="number" value={limits.daily} onChange={(e) => setLimits({ ...limits, daily: Number(e.target.value) })} /></label><button className="secondary" onClick={saveLimits}>{copy.save}</button><small>{saved}</small></article><article><h3>Финансы</h3><label>Доход от токенов<input type="number" value={finance.tokenRevenue} onChange={(e) => setFinance({ ...finance, tokenRevenue: Number(e.target.value) })} /></label><label>Себестоимость API<input type="number" value={finance.tokenCost} onChange={(e) => setFinance({ ...finance, tokenCost: Number(e.target.value) })} /></label><label>Свет<input type="number" value={finance.electricity} onChange={(e) => setFinance({ ...finance, electricity: Number(e.target.value) })} /></label><label>Акции<input type="number" value={finance.promoBudget} onChange={(e) => setFinance({ ...finance, promoBudget: Number(e.target.value) })} /></label><button className="secondary" onClick={saveFinance}>Сохранить финансы</button></article><article><h3>Промокод</h3><label>Код<input value={promoDraft.code} onChange={(e) => setPromoDraft({ ...promoDraft, code: e.target.value.toUpperCase() })} /></label><label>Токены<input type="number" value={promoDraft.tokens} onChange={(e) => setPromoDraft({ ...promoDraft, tokens: Number(e.target.value) })} /></label><label>Активации<input type="number" value={promoDraft.activations} onChange={(e) => setPromoDraft({ ...promoDraft, activations: Number(e.target.value) })} /></label><button className="secondary" onClick={createPromo}>Создать промокод</button></article><article><h3>Промокоды в базе</h3>{promoCodes.length ? promoCodes.map((item) => <p key={item.code}><b>{item.code}</b>: {item.tokens} ток. · {item.activation_count}/{item.activation_limit}</p>) : <p>Промокодов пока нет.</p>}</article></div><div className="admin-grid"><div><strong>Free</strong><span>0 ₽</span><small>галерея закрыта, базовые токены</small></div><div><strong>Mini</strong><span>калибровка</span><small>все функции включены для тестов</small></div><div><strong>Plus</strong><span>личная галерея</span><small>больше токенов и история</small></div><div><strong>Pro</strong><span>мегаскорость</span><small>приоритет и расширенные лимиты</small></div></div></div>}
    {tab === 'users' && <div className="admin-section"><AdminAnalyticsV2 /><div className="legacy-admin-toggle"><button className="secondary" onClick={() => setShowLegacyUsers((v) => !v)}>{showLegacyUsers ? 'Скрыть старую таблицу действий' : 'Открыть старую таблицу действий'}</button><small className="legacy-admin-warn">Эти действия устаревают. Используйте карточку пользователя (Карточка → Админ-действия). Показывать только для экстренных случаев.</small></div>{showLegacyUsers && <div className="legacy-admin-table"><div className="admin-section-head"><h3>Старые действия — временно</h3><div className="admin-row-actions"><button className="secondary" onClick={downloadUsersExcel}>Скачать Excel</button><button className="secondary" onClick={() => { setEditingUserId(null); setUserHistory(null); setUserDraft({ userId: 'telegram_123456789', username: '', firstName: '', lastName: '', middleName: '', phone: '', email: '', country: '', city: '', role: 'user', plan: 'mini', tokenBalance: 50, galleryEnabled: true }); setUserFormOpen(true) }}>Добавить пользователя</button></div></div><div className="admin-grid"><div><strong>Всего</strong><span>{adminUsers.length || String(admin?.users ?? 1)}</span><small>зарегистрировано</small></div><div><strong>Админы</strong><span>{adminUsers.filter((item) => item.role === 'admin').length}</span><small>role=admin</small></div><div><strong>Токены</strong><span>{adminUsers.reduce((sum, item) => sum + (item.token_balance || 0), 0)}</span><small>на балансах</small></div><div><strong>Использовано</strong><span>{adminUsers.reduce((sum, item) => sum + (item.tokens_used || 0), 0)}</span><small>списано токенов</small></div><div><strong>Генерации</strong><span>{adminUsers.reduce((sum, item) => sum + (item.generation_count || 0), 0)}</span><small>всего</small></div><div><strong>Время</strong><span>{Math.round(adminUsers.reduce((sum, item) => sum + (item.total_time_seconds || 0), 0) / 60)} м</span><small>в приложении</small></div><div><strong>Промокоды</strong><span>{adminUsers.reduce((sum, item) => sum + (item.promo_used_count || 0), 0)}</span><small>использовано</small></div><div><strong>Рефералы</strong><span>{adminUsers.reduce((sum, item) => sum + (item.referrals_count || 0), 0)}</span><small>по ссылкам/кодам</small></div></div><div className="admin-user-table"><div className="admin-user-head"><span>Ред.</span><span>ID</span><span>ФИО и контакты</span><span>Гео</span><span>Роль</span><span>Баланс</span><span>Активность</span><span>Промо</span><span>Статус</span><span>Действия</span><span>Удалить</span></div>{adminUsers.map((item) => <div className="admin-user-row" key={item.id}><button className="edit-user-button" title="Редактировать" onClick={() => void editUser(item)}>Ред.</button><strong>{item.id}</strong><span>{[item.last_name, item.first_name, item.middle_name].filter(Boolean).join(' ') || item.username || 'без имени'}<br />@{item.username || '-'} · {item.phone || 'тел. -'} · {item.email || 'почта -'}</span><span>{item.country || '-'} / {item.city || '-'}<br />{item.timezone || '-'}</span><span>{item.role}<br />{item.plan}</span><span>{item.token_balance}<br />used {item.tokens_used || 0}</span><span>{item.generation_count || 0} ген.<br />{Math.round((item.total_time_seconds || 0) / 60)} мин.</span><span>{item.promo_used_count || 0} промо<br />{item.referrals_count || 0} реф.</span><button className={item.banned ? 'ban-state banned' : 'ban-state'} onClick={() => updateUser(item.id, { banned: !item.banned })}>{item.banned ? 'Забанен' : 'Активен'}</button><div className="admin-row-actions"><button className="secondary" onClick={() => updateUser(item.id, { role: item.role === 'admin' ? 'user' : 'admin' })}>{item.role === 'admin' ? 'Снять' : 'Админ'}</button><button className="secondary" onClick={() => { const nextPlan = item.plan === 'mini' ? 'plus' : item.plan === 'plus' ? 'pro' : item.plan === 'pro' ? 'free' : 'mini'; updateUser(item.id, { plan: nextPlan, galleryEnabled: nextPlan !== 'free' }) }}>Тариф</button><button className="secondary" onClick={() => updateUser(item.id, { tokenBalance: item.token_balance + 50 })}>+50</button><button className="secondary" onClick={() => updateUser(item.id, { tokenBalance: Math.max(0, item.token_balance - 50) })}>-50</button></div><button className="delete-user-button" title="Удалить" onClick={() => deleteUser(item.id)}><Trash2 size={16} /></button></div>)}</div></div>}</div>}
    {tab === 'queue' && <div className="admin-section"><h3>Очередь генераций</h3><div className="admin-grid"><div><strong>В очереди</strong><span>{queue.length}</span><small>ожидают запуска</small></div><div><strong>Провайдер</strong><span>{provider}</span><small>текущий маршрут</small></div><div><strong>Сегодня</strong><span>{String(admin?.completedToday ?? 0)}</span><small>выполнено</small></div></div><pre>{JSON.stringify(queue, null, 2)}</pre></div>}
    {tab === 'errors' && <div className="admin-section"><h3>Ошибки и диагностика</h3><div className="admin-grid"><div><strong>Ошибки</strong><span>{String(admin?.errors ?? 0)}</span><small>в сводке</small></div><div><strong>ComfyUI</strong><span>{provider === 'comfyui' ? 'активен' : 'резерв'}</span><small>локальный маршрут</small></div><div><strong>OpenRouter</strong><span>{provider === 'openrouter' ? 'активен' : 'резерв'}</span><small>облачный маршрут</small></div></div><pre>{recentErrors.length ? recentErrors.join('\n') : 'Ошибок нет'}</pre><details><summary>Сырой admin summary</summary><pre>{JSON.stringify(admin, null, 2)}</pre></details></div>}
    {userFormOpen && <div className="modal-backdrop"><section className="user-edit-modal"><button className="floating-clear" onClick={closeUserEditor}><X size={16} /></button><h2>{editingUserId ? 'Редактировать пользователя' : 'Добавить пользователя'}</h2><div className="user-edit-grid"><label>User ID<input value={userDraft.userId} disabled={Boolean(editingUserId)} onChange={(e) => setUserDraft({ ...userDraft, userId: e.target.value })} /></label><label>Фамилия<input value={userDraft.lastName} onChange={(e) => setUserDraft({ ...userDraft, lastName: e.target.value })} /></label><label>Имя<input value={userDraft.firstName} onChange={(e) => setUserDraft({ ...userDraft, firstName: e.target.value })} /></label><label>Отчество<input value={userDraft.middleName} onChange={(e) => setUserDraft({ ...userDraft, middleName: e.target.value })} /></label><label>Username<input value={userDraft.username} onChange={(e) => setUserDraft({ ...userDraft, username: e.target.value })} /></label><label>Телефон<input value={userDraft.phone} onChange={(e) => setUserDraft({ ...userDraft, phone: e.target.value })} /></label><label>Почта<input value={userDraft.email} onChange={(e) => setUserDraft({ ...userDraft, email: e.target.value })} /></label><label>Страна<input value={userDraft.country} onChange={(e) => setUserDraft({ ...userDraft, country: e.target.value })} /></label><label>Город<input value={userDraft.city} onChange={(e) => setUserDraft({ ...userDraft, city: e.target.value })} /></label><label>Роль<select value={userDraft.role} onChange={(e) => setUserDraft({ ...userDraft, role: e.target.value })}><option value="user">user</option><option value="admin">admin</option></select></label><label>Тариф<select value={userDraft.plan} onChange={(e) => setUserDraft({ ...userDraft, plan: e.target.value, galleryEnabled: e.target.value !== 'free' })}><option value="free">free</option><option value="mini">mini</option><option value="plus">plus</option><option value="pro">pro</option></select></label><label>Баланс токенов<input type="number" value={userDraft.tokenBalance} onChange={(e) => setUserDraft({ ...userDraft, tokenBalance: Number(e.target.value) })} /></label><label className="checkbox-row"><input type="checkbox" checked={userDraft.galleryEnabled} onChange={(e) => setUserDraft({ ...userDraft, galleryEnabled: e.target.checked })} />Галерея доступна</label></div>{editingUserId && <div className="user-history-panel"><div className="admin-grid"><div><strong>Генерации</strong><span>{userHistory?.jobs?.length ?? '...'}</span><small>последние задачи</small></div><div><strong>Галерея</strong><span>{userHistory?.images?.length ?? '...'}</span><small>личные изображения</small></div><div><strong>Токены</strong><span>{userHistory?.ledger?.reduce((sum, item) => sum + Number(item.delta || 0), 0) ?? '...'}</span><small>движение по счету</small></div></div><div className="user-history-lists"><article><h3>История генераций</h3>{userHistory?.jobs?.length ? userHistory.jobs.slice(0, 8).map((job) => <p key={String(job.id)}><b>{String(job.status)}</b> · {String(job.mode)} · {String(job.created_at || '')}<br /><span>{String(job.prompt_original || '').slice(0, 140)}</span></p>) : <p>Истории генераций пока нет.</p>}</article><article><h3>Галерея клиента</h3>{userHistory?.images?.length ? userHistory.images.slice(0, 8).map((image) => <p key={String(image.id)}><b>{String(image.mode)}</b> · {String(image.created_at || '')}<br /><span>{String(image.prompt_original || '').slice(0, 140)}</span></p>) : <p>Изображений пока нет.</p>}</article><article><h3>Списание токенов</h3>{userHistory?.ledger?.length ? userHistory.ledger.slice(0, 8).map((entry) => <p key={String(entry.id)}><b>{Number(entry.delta || 0) > 0 ? '+' : ''}{String(entry.delta)}</b> · {String(entry.reason)}<br /><span>{String(entry.created_at || '')}</span></p>) : <p>Движений по токенам пока нет.</p>}</article></div></div>}<div className="user-edit-actions"><button className="secondary" onClick={closeUserEditor}>Отмена</button><button className="generate small-action" onClick={registerUser}>Сохранить</button></div></section></div>}
  </section>
}

export default App
