// Раздел «Звук». Серверного API озвучки и музыки в проекте пока нет, поэтому
// экран настраивается и отзывается на выбор, но результат не имитирует —
// кнопка запуска честно сообщает состояние. Так же ведёт себя телефонный
// прототип, чтобы поведение разделов совпадало.

import { useState } from 'react'
import './studioPreviewPanels.css'

const KINDS = [
  { id: 'speech', label: 'Речь', peak: '58%', speed: 900 },
  { id: 'music', label: 'Музыка', peak: '86%', speed: 1500 },
  { id: 'sfx', label: 'Звуковой эффект', peak: '72%', speed: 620 },
]

const VOICES = ['Тёплый', 'Дикторский', 'Мягкий', 'Энергичный']

const BARS = [0.35, 0.6, 0.85, 0.5, 1, 0.7, 0.45, 0.9, 0.55, 0.75, 0.4, 0.95, 0.6, 0.3, 0.8]

export default function StudioSoundPanel() {
  const [kind, setKind] = useState(KINDS[0])
  const [voice, setVoice] = useState(VOICES[0])
  const [text, setText] = useState('')
  const [notice, setNotice] = useState(false)

  return (
    <div className="pv-panel">
      <div className="pv-head">
        <span className="pv-badge">Готовим раздел</span>
        <h2>Звук</h2>
        <p>Речь, музыка и эффекты. Интерфейс уже собран — осталось подключить генерацию.</p>
      </div>

      <div className="pv-stage">
        <div className="pv-wave" aria-hidden="true">
          {BARS.map((h, i) => (
            <i key={i} style={{
              ['--pv-peak' as string]: `${Math.round(h * parseInt(kind.peak, 10))}%`,
              ['--pv-speed' as string]: `${kind.speed + i * 45}ms`,
            }} />
          ))}
        </div>
      </div>

      <div className="pv-card">
        <label className="pv-row">
          <span>Что озвучиваем</span>
          <div className="pv-chips">
            {KINDS.map((k) => (
              <button key={k.id} type="button" className={`pv-chip${k.id === kind.id ? ' is-active' : ''}`} onClick={() => setKind(k)}>{k.label}</button>
            ))}
          </div>
        </label>

        {kind.id === 'speech' && (
          <label className="pv-row">
            <span>Голос</span>
            <div className="pv-chips">
              {VOICES.map((v) => (
                <button key={v} type="button" className={`pv-chip${v === voice ? ' is-active' : ''}`} onClick={() => setVoice(v)}>{v}</button>
              ))}
            </div>
          </label>
        )}

        <label className="pv-row">
          <span>{kind.id === 'music' ? 'Опишите настроение' : 'Текст'}</span>
          <textarea
            className="pv-input"
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={kind.id === 'music' ? 'Спокойная фоновая тема с мягкими клавишами…' : 'Введите текст, который нужно озвучить…'}
          />
        </label>

        <button type="button" className="pv-run" onClick={() => setNotice(true)}>
          {kind.id === 'music' ? 'Сочинить' : 'Озвучить'}
        </button>

        {notice && (
          <p className="pv-note" role="status">
            <b>Генерация звука пока не подключена.</b> В проекте нет пользовательского API
            озвучки и музыки, поэтому мы не показываем выдуманный результат. Настройки этого
            экрана сохранятся, когда провайдер появится.
          </p>
        )}
      </div>
    </div>
  )
}
