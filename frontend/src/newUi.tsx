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

// Реальные разрешения из текущего интерфейса (resolutionPresets в App.tsx):
// 1024×1024, 1280×720 / 720×1280, 1920×1088 / 1088×1920.
type FormatId = 'square' | 'vertical' | 'horizontal'

const FORMATS: Array<{ id: FormatId; label: string; icon: string }> = [
  { id: 'square', label: 'Квадрат 1:1', icon: 'square' },
  { id: 'vertical', label: 'Вертикально 9:16', icon: 'vertical' },
  { id: 'horizontal', label: 'Горизонтально 16:9', icon: 'horizontal' },
]

const SIZE_TABLE: Record<string, Record<FormatId, { width: number; height: number }>> = {
  standard: {
    square: { width: 1024, height: 1024 },
    vertical: { width: 720, height: 1280 },
    horizontal: { width: 1280, height: 720 },
  },
  medium: {
    square: { width: 1024, height: 1024 },
    vertical: { width: 1024, height: 1536 },
    horizontal: { width: 1536, height: 1024 },
  },
  high: {
    square: { width: 1024, height: 1024 },
    vertical: { width: 1088, height: 1920 },
    horizontal: { width: 1920, height: 1088 },
  },
}

const RESOLUTION_TIERS: Array<{ id: string; label: string }> = [
  { id: 'standard', label: 'Стандарт' },
  { id: 'medium', label: 'Среднее' },
  { id: 'high', label: 'Высокое' },
]

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
  const [tab, setTab] = useState<N2Tab>('feed')
  const [view, setView] = useState<N2View>('tabs')
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
  const [formatId, setFormatId] = useState<FormatId>('square')
  const [resolutionTier, setResolutionTier] = useState('standard')
  const [quality, setQuality] = useState('fast')
  const [proMode, setProMode] = useState(false)
  const [seed, setSeed] = useState(0)
  const [guidance, setGuidance] = useState(3.5)
  const [strengthPct, setStrengthPct] = useState(75)
  const [sourceImage, setSourceImage] = useState<string>()
  const [compare, setCompare] = useState(50)

  const [job, setJob] = useState<N2Job>()
  const [jobMode, setJobMode] = useState<'text' | 'i2i'>('text')
  const [resultUrl, setResultUrl] = useState<string>()
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
          if (next.resultUrl) setResultUrl(next.resultUrl)
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
  function applyStyle(next: StylePreset | null) {
    setStyleId(next?.id || '')
    if (tab !== 'text') return
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
      const size = SIZE_TABLE[resolutionTier]?.[formatId] || SIZE_TABLE.standard.square
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
      ) : resultUrl ? (
        <img className="n2-mobile-preview-img" src={resultUrl} alt="Результат генерации" />
      ) : (
        <div className="n2-mobile-preview-empty">
          <span className="n2-mobile-preview-icon">▧</span>
          <span>Здесь появится сгенерированное изображение</span>
        </div>
      )}
    </div>
  )

  const stylesStrip = (
    <div className="n2-block">
      <div className="n2-label-row">
        <strong>Стиль</strong>
        <span>{I2I_STYLES.length} стилей</span>
      </div>
      <div className="n2-style-scroll" aria-label="Выбор стиля" onMouseLeave={() => setHoverStyle(null)}>
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
      {hoverStyle && (
        <div className="n2-style-hover" aria-hidden="true">
          <img src={hoverStyle.preview[previewGender]} alt="" />
          <span>{hoverStyle.name}</span>
        </div>
      )}
    </div>
  )

  const controls = (mode: 'text' | 'i2i') => (
    <section className="n2-panel n2-controls" aria-label="Панель генерации">
      <div className="n2-controls-scroll">
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
            <span>Главный шаг</span>
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
              <select
                value={resolutionTier}
                aria-label="Разрешение изображения"
                onChange={(e) => setResolutionTier(e.target.value)}
              >
                {RESOLUTION_TIERS.map((tier) => {
                  const size = SIZE_TABLE[tier.id][formatId]
                  return (
                    <option key={tier.id} value={tier.id}>
                      {tier.label} · {size.width}×{size.height}
                    </option>
                  )
                })}
              </select>
            </label>
            {FORMATS.map((format) => (
              <button
                key={format.id}
                className={`n2-format-button${formatId === format.id ? ' active' : ''}`}
                type="button"
                onClick={() => setFormatId(format.id)}
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

  const resultPanel = (
    <section className="n2-panel n2-result" aria-label="Предпросмотр результата">
      <div className="n2-canvas">
        {jobActive ? (
          progressCard
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
          <img className="n2-result-image" src={resultUrl} alt="Результат генерации" />
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
                onClick={() => {
                  setResultUrl(item.url)
                  setResultSource(undefined)
                }}
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

  const feed = (
    <section className="n2-panel n2-feed" aria-label="Лента сообщества">
      <div className="n2-feed-hero">
        <span className="n2-feed-badge">✦ Скоро</span>
        <h2>Лента сообщества ИЗО ACA</h2>
        <p>
          Лента — это соцсеть внутри ИЗО ACA. Пользователи сами решают, какие свои генерации опубликовать: в ленту
          попадает только то, чем автор захотел поделиться. Публикации собирают лайки и комментарии. Раздел в
          разработке — ниже макет того, как это будет выглядеть.
        </p>
      </div>
      <div className="n2-feed-grid">
        {gallery.slice(0, 12).map((item) => (
          <div key={item.id} className="n2-feed-card">
            <img src={item.thumbnailUrl || item.url} alt={item.promptOriginal.slice(0, 60)} loading="lazy" />
            <div className="n2-feed-card-meta">
              <span>Вы</span>
              <span>♥ · 💬</span>
            </div>
          </div>
        ))}
        {gallery.length === 0 &&
          I2I_STYLES.slice(0, 8).map((style) => (
            <div key={style.id} className="n2-feed-card">
              <img src={style.preview[previewGender]} alt={style.preview.alt} loading="lazy" />
              <div className="n2-feed-card-meta">
                <span>{style.name}</span>
                <span>♥ · 💬</span>
              </div>
            </div>
          ))}
      </div>
    </section>
  )

  const galleryView = (
    <section className="n2-panel n2-gallery" aria-label="Галерея">
      <div className="n2-gallery-head">
        <h2>Галерея</h2>
        <button className="n2-ghost" type="button" onClick={() => setView('tabs')}>
          ← Назад
        </button>
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
            <button key={item.id} className="n2-gallery-card" type="button" title={item.promptOriginal} onClick={() => setGalleryItem(item)}>
              <img src={item.thumbnailUrl || item.url} alt={item.promptOriginal.slice(0, 60)} loading="lazy" />
            </button>
          ))}
        </div>
      )}
    </section>
  )

  const placeholder = (title: string, text: string) => (
    <section className="n2-panel n2-placeholder">
      <div className="n2-placeholder-card">
        <span className="icon">▧</span>
        <h2>{title}</h2>
        <p>{text}</p>
        <button className="n2-ghost" type="button" onClick={() => (window.location.href = '/')}>
          Открыть в текущей версии
        </button>
      </div>
    </section>
  )

  const wideTab = tab === 'feed' || tab === 'edit' || tab === 'paint' || tab === 'face'

  return (
    <div className="n2">
      <AuthV2Modal open={authOpen} onClose={() => setAuthOpen(false)} />
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
            <img src={galleryItem.url} alt={galleryItem.promptOriginal.slice(0, 80)} />
            <p className="n2-overlay-prompt">{galleryItem.promptOriginal}</p>
            <div className="n2-overlay-actions">
              <a className="n2-ghost" href={galleryItem.url} download target="_blank" rel="noreferrer">
                ⬇ Скачать
              </a>
              <button
                className="n2-ghost"
                type="button"
                onClick={() => {
                  setSourceImage(galleryItem.url)
                  setGalleryItem(undefined)
                  setView('tabs')
                  setTab('i2i')
                }}
              >
                → В Изо → Изо
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
                placeholder(
                  'Редактор',
                  'Редактор с основой и референсами переезжает в новый интерфейс следующим этапом. Функционал уже работает в текущей версии.',
                )}
              {tab === 'paint' &&
                placeholder(
                  'Рисунок',
                  'Холст для рисования и масок появится здесь в новом дизайне. Пока функционал доступен в текущей версии.',
                )}
              {tab === 'face' &&
                placeholder(
                  'Лицо',
                  'Замена лица (FaceSwap) появится здесь в новом дизайне. Пока функционал доступен в текущей версии.',
                )}
            </>
          )}
        </main>
      </div>
    </div>
  )
}
