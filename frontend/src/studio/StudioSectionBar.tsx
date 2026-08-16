// Шапка студии: разделы по типу контента вместо россыпи режимов.
//
// Взаимодействие повторяет замысел телефонного интерфейса: при выборе
// «Картинок» остальные разделы уезжают влево, а на их место выезжает список
// режимов этого раздела с кнопкой возврата. Обе дорожки лежат в одной полосе,
// поэтому высота шапки не скачет.
//
// Палитра — из /phone (см. studioSectionBar.css), включая светлую тему.

import './studioSectionBar.css'
import type { N2Tab } from './studioTypes'
import { IMAGE_MODES, STUDIO_SECTIONS, isImageTab } from './studioSections'
import type { StudioSection } from './studioSections'

function Icon({ name }: { name: string }) {
  const s = { fill: 'none', stroke: 'currentColor', strokeWidth: 1.8, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const }
  if (name === 'image') return <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3.5" y="5" width="17" height="14" rx="2.5" {...s} /><path d="m6.5 16 3.8-3.8 2.5 2.5 2-2L18 16" {...s} /><circle cx="15.6" cy="9.2" r="1.3" fill="currentColor" /></svg>
  if (name === 'video') return <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="6" width="12.5" height="12" rx="2.5" {...s} /><path d="m16.5 10.5 4-2.2v7.4l-4-2.2z" {...s} /></svg>
  if (name === 'sound') return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 10.5v3M8 7v10M12 4.5v15M16 8v8M20 11v2" {...s} /></svg>
  if (name === 'chat') return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 12.2c0 3.9-3.6 7-8 7-1 0-2-.16-2.9-.46L4 20l1.4-3.3A6.6 6.6 0 0 1 4 12.2c0-3.9 3.6-7 8-7s8 3.1 8 7Z" {...s} /></svg>
  if (name === 'model3d') return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m12 3.6 7.2 4.1v8.6L12 20.4 4.8 16.3V7.7Z" {...s} /><path d="M12 12.1 19.2 8M12 12.1 4.8 8M12 12.1v8.3" {...s} /></svg>
  return <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8" {...s} /></svg>
}

const Caret = () => <svg className="sb-caret" viewBox="0 0 24 24" aria-hidden="true"><path d="m9 6 6 6-6 6" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" /></svg>
const Back = () => <svg className="sb-caret" viewBox="0 0 24 24" aria-hidden="true"><path d="m15 6-6 6 6 6" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" /></svg>

export default function StudioSectionBar({
  tab,
  onSelectTab,
  submodesOpen,
  onToggleSubmodes,
}: {
  tab: N2Tab
  onSelectTab: (tab: N2Tab) => void
  submodesOpen: boolean
  onToggleSubmodes: (open: boolean) => void
}) {
  const imageActive = isImageTab(tab)
  const open = imageActive && submodesOpen

  const activate = (section: StudioSection) => {
    if (section.id === 'image') {
      if (!imageActive) onSelectTab(section.tab)
      onToggleSubmodes(true)
      return
    }
    onToggleSubmodes(false)
    onSelectTab(section.tab)
  }

  return (
    <div className={`sb-rail${open ? ' is-open' : ''}`}>
      <div
        className="sb-track sb-track-sections"
        role="tablist"
        aria-label="Разделы студии"
        aria-hidden={open}
        style={{ transform: open ? 'translateX(-14%)' : 'none', opacity: open ? 0 : 1, pointerEvents: open ? 'none' : 'auto' }}
      >
        {STUDIO_SECTIONS.map((section) => {
          const active = section.id === 'image' ? imageActive : tab === section.tab
          const cls = ['sb-btn', active ? 'is-active' : '', section.preview ? 'is-preview' : '', section.desktopOnly ? 'sb-desktop-only' : ''].filter(Boolean).join(' ')
          return (
            <button key={section.id} type="button" role="tab" aria-selected={active} className={cls} tabIndex={open ? -1 : 0} onClick={() => activate(section)}>
              <Icon name={section.icon} />
              <span className="sb-label">{section.label}</span>
              {section.id === 'image' && <Caret />}
            </button>
          )
        })}
      </div>

      <div
        className="sb-track sb-track-modes"
        role="tablist"
        aria-label="Режимы изображений"
        aria-hidden={!open}
        style={{ transform: open ? 'none' : 'translateX(14%)', opacity: open ? 1 : 0, pointerEvents: open ? 'auto' : 'none' }}
      >
        <button type="button" className="sb-btn sb-back" tabIndex={open ? 0 : -1} onClick={() => onToggleSubmodes(false)} aria-label="Ко всем разделам">
          <Back />
          <span className="sb-label">Картинки</span>
        </button>
        <span className="sb-sep" aria-hidden="true" />
        {IMAGE_MODES.map((mode) => (
          <button
            key={mode.id}
            type="button"
            role="tab"
            aria-selected={tab === mode.id}
            title={mode.hint}
            tabIndex={open ? 0 : -1}
            className={`sb-btn${tab === mode.id ? ' is-active' : ''}`}
            onClick={() => onSelectTab(mode.id)}
          >
            <span className="sb-label">{mode.label}</span>
          </button>
        ))}
      </div>
    </div>
  )
}
