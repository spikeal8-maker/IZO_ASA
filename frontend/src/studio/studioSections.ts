// Данные разделов студии. Вынесено из StudioSectionBar.tsx отдельным модулем,
// потому что react-refresh требует, чтобы файл компонентов экспортировал
// только компоненты.

import type { N2Tab } from './studioTypes'

export type ImageMode = 'text' | 'i2i' | 'edit' | 'paint'

export const IMAGE_MODES: Array<{ id: ImageMode; label: string; hint: string }> = [
  { id: 'text', label: 'По тексту', hint: 'Изображение по текстовому описанию' },
  { id: 'i2i', label: 'По фото', hint: 'Изменить готовое изображение' },
  { id: 'edit', label: 'Сборка', hint: 'Собрать изображение из нескольких фото' },
  { id: 'paint', label: 'Редактор', hint: 'Правки и дорисовка' },
]

const IMAGE_TABS: N2Tab[] = ['text', 'i2i', 'edit', 'paint']

export function isImageTab(tab: N2Tab): boolean {
  return IMAGE_TABS.includes(tab)
}

export type StudioSection = {
  id: string
  label: string
  icon: string
  tab: N2Tab
  /** Раздел без серверного API: помечается и открывает экран-заглушку. */
  preview?: boolean
  /** Показывать только на десктопе. */
  desktopOnly?: boolean
}

export const STUDIO_SECTIONS: StudioSection[] = [
  { id: 'image', label: 'Картинки', icon: 'image', tab: 'text' },
  { id: 'video', label: 'Видео', icon: 'video', tab: 'video' },
  { id: 'sound', label: 'Звук', icon: 'sound', tab: 'sound', preview: true },
  { id: 'chat', label: 'Чат', icon: 'chat', tab: 'chat' },
  { id: 'model3d', label: '3D', icon: 'model3d', tab: 'model3d', preview: true, desktopOnly: true },
]
