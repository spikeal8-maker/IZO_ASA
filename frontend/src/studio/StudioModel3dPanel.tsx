// Раздел «3D». По продуктовому решению показывается только на десктопе.
// Генерации 3D в бэкенде нет, поэтому экран настраивается и реагирует на
// выбор, но результат не имитирует.

import { useState } from 'react'
import './studioPreviewPanels.css'

const KINDS = [
  { id: 'object', label: 'Предмет' },
  { id: 'character', label: 'Персонаж' },
  { id: 'scene', label: 'Сцена' },
]

const FORMATS = ['GLB', 'OBJ', 'STL']

export default function StudioModel3dPanel() {
  const [kind, setKind] = useState(KINDS[0])
  const [format, setFormat] = useState(FORMATS[0])
  const [detail, setDetail] = useState(60)
  const [prompt, setPrompt] = useState('')
  const [notice, setNotice] = useState(false)

  // Плотность каркаса и скорость вращения отзываются на слайдер детализации.
  const rings = Math.max(2, Math.round(detail / 20))
  const spin = `${Math.round(22 - detail / 8)}s`

  return (
    <div className="pv-panel">
      <div className="pv-head">
        <span className="pv-badge">Готовим раздел</span>
        <h2>3D-модели</h2>
        <p>Генерация объёмных моделей по описанию. Интерфейс собран — генерация подключается.</p>
      </div>

      <div className="pv-stage">
        <svg className="pv-cube" viewBox="0 0 120 120" style={{ ['--pv-spin' as string]: spin }} aria-hidden="true">
          <path d="M60 14 106 40v40L60 106 14 80V40Z" />
          <path d="M60 60 106 40M60 60 14 40M60 60v46" className="pv-cube-soft" />
          {Array.from({ length: rings }, (_, i) => {
            const s = 1 - (i + 1) / (rings + 1.6)
            return <path key={i} className="pv-cube-soft" d={`M60 ${60 - 46 * s} ${60 + 46 * s} ${60 - 20 * s}v${40 * s}L60 ${60 + 46 * s} ${60 - 46 * s} ${60 + 20 * s}v${-40 * s}Z`} />
          })}
        </svg>
      </div>

      <div className="pv-card">
        <label className="pv-row">
          <span>Что моделируем</span>
          <div className="pv-chips">
            {KINDS.map((k) => (
              <button key={k.id} type="button" className={`pv-chip${k.id === kind.id ? ' is-active' : ''}`} onClick={() => setKind(k)}>{k.label}</button>
            ))}
          </div>
        </label>

        <label className="pv-row">
          <span>Описание</span>
          <textarea
            className="pv-input"
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="Керамическая кружка с гранёной ручкой, матовая глазурь…"
          />
        </label>

        <label className="pv-row">
          <span>Детализация</span>
          <div className="pv-slider">
            <input type="range" min={20} max={100} step={10} value={detail} onChange={(e) => setDetail(Number(e.target.value))} />
            <b>{detail}%</b>
          </div>
        </label>

        <label className="pv-row">
          <span>Формат файла</span>
          <div className="pv-chips">
            {FORMATS.map((f) => (
              <button key={f} type="button" className={`pv-chip${f === format ? ' is-active' : ''}`} onClick={() => setFormat(f)}>{f}</button>
            ))}
          </div>
        </label>

        <button type="button" className="pv-run" onClick={() => setNotice(true)}>Собрать модель</button>

        {notice && (
          <p className="pv-note" role="status">
            <b>Генерация 3D пока не подключена.</b> Провайдера объёмных моделей в проекте ещё
            нет, поэтому мы не выдаём выдуманный результат. Раздел доступен только на
            десктопе — так решено на этом этапе.
          </p>
        )}
      </div>
    </div>
  )
}
