export type AdminModelsPage = 'api' | 'config' | 'energy' | 'voice' | 'improve'
export type AdminOpenRouterPage = 'text' | 'images' | 'video' | 'audio' | '3d' | 'settings'

export const ADMIN_OPENROUTER_PAGES: Array<{
  id: AdminOpenRouterPage
  label: string
  path: string
  title: string
  description: string
}> = [
  { id: 'text', label: 'Текст', path: '/admin/models/openrouter/text', title: 'Текстовые модели OpenRouter', description: 'Модели чата, контекст, цена за миллион токенов и экономика ответа.' },
  { id: 'images', label: 'Изображения', path: '/admin/models/openrouter/images', title: 'Модели изображений OpenRouter', description: 'Генерация и редактирование изображений, тарифные доступы и экономика форматов.' },
  { id: 'video', label: 'Видео', path: '/admin/models/openrouter/video', title: 'Видеомодели OpenRouter', description: 'Режимы видео, длительности, разрешения, звук и расчёт себестоимости.' },
  { id: 'audio', label: 'Звук', path: '/admin/models/openrouter/audio', title: 'Звуковые модели OpenRouter', description: 'Модели с аудиовходом, стоимость обработки и готовность маршрута.' },
  { id: '3d', label: '3D', path: '/admin/models/openrouter/3d', title: '3D-модели OpenRouter', description: 'Отдельный каталог и экономика будущей генерации 3D-моделей.' },
  { id: 'settings', label: 'Настройки', path: '/admin/models/openrouter/settings', title: 'Настройки OpenRouter', description: 'Ключ, проверка соединения, курс, маржа и общая экономика провайдера.' },
]

export const ADMIN_MODELS_PAGES: Array<{
  id: AdminModelsPage
  label: string
  path: string
  title: string
  description: string
}> = [
  {
    id: 'api',
    label: 'OpenRouter',
    path: '/admin/models/openrouter/text',
    title: 'Модели OpenRouter',
    description: 'Каталог облачных моделей, доступность по тарифам, цены и проверка API.',
  },
  {
    id: 'config',
    label: 'Config UI',
    path: '/admin/models/config-ui',
    title: 'Локальные модели Config UI',
    description: 'Изображения, видео, текстовые модели, профили, LoRA и состояние локального сервера.',
  },
  {
    id: 'energy',
    label: 'Энергопотребление',
    path: '/admin/models/energy',
    title: 'Энергопотребление',
    description: 'Мощность сервера, стоимость электричества и себестоимость локальных генераций.',
  },
  {
    id: 'voice',
    label: 'Голосовой ввод',
    path: '/admin/models/voice-input',
    title: 'Голосовой ввод',
    description: 'Модели распознавания речи, маршрутизация и проверка голосового ввода.',
  },
  {
    id: 'improve',
    label: 'Улучшение промпта',
    path: '/admin/models/prompt-improvement',
    title: 'Улучшение промпта',
    description: 'Локальная и облачная модели, системные инструкции, резервный маршрут и экономика.',
  },
]

const PAGE_BY_ID = new Map(ADMIN_MODELS_PAGES.map((page) => [page.id, page]))
const PAGE_BY_PATH = new Map(ADMIN_MODELS_PAGES.map((page) => [page.path, page]))

export function adminModelsPageFromPath(pathname: string): AdminModelsPage {
  const normalized = pathname.replace(/\/+$/, '') || '/admin/models'
  if (normalized === '/admin/models/openrouter' || normalized.startsWith('/admin/models/openrouter/')) return 'api'
  return PAGE_BY_PATH.get(normalized)?.id || 'api'
}

export function adminModelsPath(page: AdminModelsPage): string {
  return PAGE_BY_ID.get(page)?.path || ADMIN_MODELS_PAGES[0].path
}

export function adminModelsPageDefinition(page: AdminModelsPage) {
  return PAGE_BY_ID.get(page) || ADMIN_MODELS_PAGES[0]
}

export function adminOpenRouterPageFromPath(pathname: string): AdminOpenRouterPage {
  const normalized = pathname.replace(/\/+$/, '')
  return ADMIN_OPENROUTER_PAGES.find((page) => page.path === normalized)?.id || 'text'
}

export function adminOpenRouterPath(page: AdminOpenRouterPage): string {
  return ADMIN_OPENROUTER_PAGES.find((item) => item.id === page)?.path || ADMIN_OPENROUTER_PAGES[0].path
}

export function adminModelsRouteDefinition(pathname: string) {
  const normalized = pathname.replace(/\/+$/, '')
  if (normalized === '/admin/models/openrouter' || normalized.startsWith('/admin/models/openrouter/')) {
    return ADMIN_OPENROUTER_PAGES.find((page) => page.path === normalized) || ADMIN_OPENROUTER_PAGES[0]
  }
  return PAGE_BY_PATH.get(normalized) || ADMIN_MODELS_PAGES[0]
}
