export type AdminModelsPage = 'api' | 'config' | 'energy' | 'voice' | 'improve'

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
    path: '/admin/models/openrouter',
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
  return PAGE_BY_PATH.get(normalized)?.id || 'api'
}

export function adminModelsPath(page: AdminModelsPage): string {
  return PAGE_BY_ID.get(page)?.path || ADMIN_MODELS_PAGES[0].path
}

export function adminModelsPageDefinition(page: AdminModelsPage) {
  return PAGE_BY_ID.get(page) || ADMIN_MODELS_PAGES[0]
}
