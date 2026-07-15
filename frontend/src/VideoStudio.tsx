import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ChangeEvent, DragEvent, ReactElement } from 'react'
import {
  ArrowRight, Check, Clock3, Film, ImagePlus, Images, LoaderCircle,
  Pause, Play, RotateCcw, Sparkles, Upload, Volume2, VolumeX, X,
} from 'lucide-react'
import { ensureSessionRefreshedV2 } from './authV2'
import './videoStudio.css'

type VideoMode = 'text_to_video' | 'image_to_video' | 'first_last_frame' | 'reference_to_video'

type VideoModel = {
  id: string
  name: string
  description: string
  supportedResolutions: string[]
  supportedAspectRatios: string[]
  supportedDurations: number[]
  supportedFrameImages: string[]
  generateAudio: boolean | null
}

type VideoConfig = {
  modes: Record<VideoMode, VideoModel[]>
  plan: string
  videoSlots: number
  economy: { tokenRub: number; minMarginPercent: number }
}

type VideoJob = {
  id: string
  mode: VideoMode
  status: string
  progress: number
  prompt: string
  error?: string | null
  createdAt: string
  completedAt?: string | null
  model?: string
  duration?: number
  resolution?: string
  aspectRatio?: string
  tokenCost?: number
  videoUrl?: string | null
}

type GalleryImage = { id: string; url: string; thumbnailUrl?: string; width?: number; height?: number; promptOriginal?: string }
type FrameKey = 'first' | 'last' | 'reference'

const MODE_META: Array<{ id: VideoMode; label: string; short: string; empty: string }> = [
  { id: 'text_to_video', label: 'По тексту', short: 'Текст', empty: 'Опишите сцену, движение и настроение будущего ролика' },
  { id: 'image_to_video', label: 'По изображению', short: 'Кадр', empty: 'Добавьте кадр, который нужно оживить' },
  { id: 'first_last_frame', label: 'Начало и конец', short: '2 кадра', empty: 'Добавьте первый и последний кадр, чтобы построить переход' },
  { id: 'reference_to_video', label: 'По референсам', short: 'Референсы', empty: 'Добавьте изображения, которые зададут героя, предмет или стиль' },
]

const DRAFT_KEY = 'izo-video-draft-v1'
const apiUrl = (value: string) => value.startsWith('http') || value.startsWith('data:') || value.startsWith('blob:') ? value : value

async function apiFetch(path: string, init?: RequestInit) {
  let response = await fetch(`/api${path}`, { ...init, credentials: 'include' })
  if (response.status === 401 && await ensureSessionRefreshedV2()) {
    response = await fetch(`/api${path}`, { ...init, credentials: 'include' })
  }
  return response
}

async function responseError(response: Response, fallback: string) {
  try {
    const data = await response.json()
    return String(data.detail || data.error || fallback)
  } catch {
    return fallback
  }
}

function fileAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    if (!file.type.startsWith('image/')) return reject(new Error('Выберите изображение.'))
    if (file.size > 12 * 1024 * 1024) return reject(new Error('Изображение должно быть меньше 12 МБ.'))
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result || ''))
    reader.onerror = () => reject(new Error('Не удалось прочитать изображение.'))
    reader.readAsDataURL(file)
  })
}

function statusLabel(status: string) {
  if (status === 'completed') return 'Готово'
  if (status === 'failed' || status === 'cancelled' || status === 'expired') return 'Не завершено'
  if (status === 'in_progress') return 'Создаём видео'
  return 'В очереди'
}

export default function VideoStudio(): ReactElement {
  const initialDraft = useMemo(() => {
    try { return JSON.parse(localStorage.getItem(DRAFT_KEY) || '{}') as Record<string, unknown> } catch { return {} }
  }, [])
  const initialMode = (initialDraft.mode as VideoMode) || 'text_to_video'
  const initialModelId = String(initialDraft.modelId || '')
  const [mode, setMode] = useState<VideoMode>(initialMode)
  const [prompt, setPrompt] = useState(String(initialDraft.prompt || ''))
  const [config, setConfig] = useState<VideoConfig | null>(null)
  const [modelId, setModelId] = useState(initialModelId)
  const [duration, setDuration] = useState(Number(initialDraft.duration || 0))
  const [resolution, setResolution] = useState(String(initialDraft.resolution || ''))
  const [aspectRatio, setAspectRatio] = useState(String(initialDraft.aspectRatio || '16:9'))
  const [generateAudio, setGenerateAudio] = useState(Boolean(initialDraft.generateAudio))
  const [firstFrame, setFirstFrame] = useState('')
  const [lastFrame, setLastFrame] = useState('')
  const [references, setReferences] = useState<string[]>([])
  const [history, setHistory] = useState<VideoJob[]>([])
  const [activeJob, setActiveJob] = useState<VideoJob | null>(null)
  const [selectedJob, setSelectedJob] = useState<VideoJob | null>(null)
  const [estimate, setEstimate] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [galleryOpen, setGalleryOpen] = useState<FrameKey | null>(null)
  const [gallery, setGallery] = useState<GalleryImage[]>([])
  const [galleryLoading, setGalleryLoading] = useState(false)
  const [uploadTarget, setUploadTarget] = useState<FrameKey>('first')
  const fileRef = useRef<HTMLInputElement>(null)

  const models = config?.modes[mode] || []
  const selectedModel = models.find((item) => item.id === modelId) || models[0]

  const syncModelDefaults = useCallback((model: VideoModel | undefined) => {
    if (!model) return
    setModelId(model.id)
    setDuration((value) => model.supportedDurations.includes(value) ? value : (model.supportedDurations[0] || 5))
    setResolution((value) => model.supportedResolutions.includes(value) ? value : (model.supportedResolutions[0] || '720p'))
    setAspectRatio((value) => model.supportedAspectRatios.includes(value) ? value : (model.supportedAspectRatios[0] || '16:9'))
    if (model.generateAudio === false) setGenerateAudio(false)
  }, [])

  const loadHistory = useCallback(async () => {
    const response = await apiFetch('/video/history?limit=30')
    if (!response.ok) return
    const data = await response.json() as { items?: VideoJob[] }
    const items = Array.isArray(data.items) ? data.items : []
    setHistory(items)
    const running = items.find((item) => !['completed', 'failed', 'cancelled', 'expired'].includes(item.status)) || null
    setActiveJob(running)
    setSelectedJob((current) => current ? items.find((item) => item.id === current.id) || current : items.find((item) => item.status === 'completed') || running || null)
  }, [])

  useEffect(() => {
    Promise.all([apiFetch('/video/config'), apiFetch('/video/history?limit=30')])
      .then(async ([configResponse, historyResponse]) => {
        if (!configResponse.ok) throw new Error(await responseError(configResponse, 'Видео сейчас недоступно.'))
        const nextConfig = await configResponse.json() as VideoConfig
        setConfig(nextConfig)
        const initialModels = nextConfig.modes[initialMode] || []
        syncModelDefaults(initialModels.find((item) => item.id === initialModelId) || initialModels[0])
        if (historyResponse.ok) {
          const data = await historyResponse.json() as { items?: VideoJob[] }
          const items = Array.isArray(data.items) ? data.items : []
          setHistory(items)
          const running = items.find((item) => !['completed', 'failed', 'cancelled', 'expired'].includes(item.status)) || null
          setActiveJob(running)
          setSelectedJob(items.find((item) => item.status === 'completed') || running || null)
        }
      })
      .catch((reason: Error) => setError(reason.message))
      .finally(() => setLoading(false))
  }, [initialMode, initialModelId, syncModelDefaults])

  const selectMode = (nextMode: VideoMode) => {
    setMode(nextMode)
    const nextModels = config?.modes[nextMode] || []
    syncModelDefaults(nextModels.find((item) => item.id === modelId) || nextModels[0])
  }

  useEffect(() => {
    localStorage.setItem(DRAFT_KEY, JSON.stringify({ mode, prompt, modelId, duration, resolution, aspectRatio, generateAudio }))
  }, [mode, prompt, modelId, duration, resolution, aspectRatio, generateAudio])

  useEffect(() => {
    if (!activeJob) return
    const timer = window.setInterval(() => void loadHistory(), 8000)
    return () => window.clearInterval(timer)
  }, [activeJob, loadHistory])

  const requestBody = useMemo(() => selectedModel ? {
    mode, model: selectedModel.id, prompt: prompt.trim() || 'preview', duration,
    resolution, aspectRatio, generateAudio, firstFrame: firstFrame || null,
    lastFrame: lastFrame || null, references,
  } : null, [mode, selectedModel, prompt, duration, resolution, aspectRatio, generateAudio, firstFrame, lastFrame, references])

  useEffect(() => {
    if (!requestBody) return
    const timer = window.setTimeout(async () => {
      const response = await apiFetch('/video/estimate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(requestBody) })
      if (response.ok) {
        const data = await response.json() as { chargedTokens?: number }
        setEstimate(Number(data.chargedTokens || 0) || null)
      } else setEstimate(null)
    }, 350)
    return () => window.clearTimeout(timer)
  }, [requestBody])

  const assignImage = (target: FrameKey, value: string) => {
    if (target === 'first') setFirstFrame(value)
    else if (target === 'last') setLastFrame(value)
    else setReferences((current) => current.length < 4 ? [...current, value] : current)
  }

  const openUpload = (target: FrameKey) => {
    setUploadTarget(target)
    fileRef.current?.click()
  }

  const handleFile = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    try { assignImage(uploadTarget, await fileAsDataUrl(file)); setError('') } catch (reason) { setError((reason as Error).message) }
  }

  const handleDrop = async (target: FrameKey, event: DragEvent) => {
    event.preventDefault()
    const file = event.dataTransfer.files?.[0]
    if (!file) return
    try { assignImage(target, await fileAsDataUrl(file)); setError('') } catch (reason) { setError((reason as Error).message) }
  }

  const openGallery = async (target: FrameKey) => {
    setGalleryOpen(target)
    setGalleryLoading(true)
    const response = await apiFetch('/gallery/items?limit=60')
    if (response.ok) {
      const data = await response.json() as { items?: GalleryImage[] } | GalleryImage[]
      setGallery(Array.isArray(data) ? data : (data.items || []))
    }
    setGalleryLoading(false)
  }

  const canSubmit = Boolean(prompt.trim() && selectedModel && !submitting && !activeJob && (
    mode === 'text_to_video' ||
    (mode === 'image_to_video' && firstFrame) ||
    (mode === 'first_last_frame' && firstFrame && lastFrame) ||
    (mode === 'reference_to_video' && references.length)
  ))

  const submit = async () => {
    if (!requestBody || !canSubmit) return
    setSubmitting(true)
    setError('')
    try {
      const response = await apiFetch('/video/generate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(requestBody) })
      if (!response.ok) throw new Error(await responseError(response, 'Не удалось запустить видео.'))
      const data = await response.json() as VideoJob
      setActiveJob({ ...data, mode, prompt, createdAt: new Date().toISOString(), model: modelId, duration, resolution, aspectRatio })
      setSelectedJob({ ...data, mode, prompt, createdAt: new Date().toISOString(), model: modelId, duration, resolution, aspectRatio })
      await loadHistory()
    } catch (reason) {
      setError((reason as Error).message)
    } finally {
      setSubmitting(false)
    }
  }

  const frameSurface = (target: FrameKey, value: string, title: string, note: string) => (
    <div className={`video-frame${value ? ' has-image' : ''}`} onDragOver={(event) => event.preventDefault()} onDrop={(event) => void handleDrop(target, event)}>
      {value ? <img src={apiUrl(value)} alt={title} /> : <ImagePlus size={28} aria-hidden="true" />}
      <div className="video-frame-copy"><strong>{title}</strong><span>{value ? 'Кадр добавлен' : note}</span></div>
      <div className="video-frame-actions">
        <button type="button" title="Загрузить" onClick={() => openUpload(target)}><Upload size={16} /><span>Загрузить</span></button>
        <button type="button" title="Галерея" onClick={() => void openGallery(target)}><Images size={16} /><span>Галерея</span></button>
        {value && <button type="button" title="Убрать" onClick={() => target === 'first' ? setFirstFrame('') : setLastFrame('')}><X size={16} /></button>}
      </div>
    </div>
  )

  const shownJob = selectedJob || activeJob
  const modeMeta = MODE_META.find((item) => item.id === mode) || MODE_META[0]

  return (
    <main className="video-studio">
      <input ref={fileRef} type="file" accept="image/png,image/jpeg,image/webp" hidden onChange={(event) => void handleFile(event)} />
      <section className="video-workspace">
        <aside className="video-controls" aria-label="Настройки видеогенерации">
          <div className="video-controls-title"><div><span>Видео</span><h1>Создать ролик</h1></div><Film size={22} /></div>
          <div className="video-mode-tabs" role="tablist" aria-label="Режим видео">
            {MODE_META.map((item) => <button key={item.id} type="button" role="tab" aria-selected={mode === item.id} className={mode === item.id ? 'active' : ''} onClick={() => selectMode(item.id)}><span>{item.label}</span><small>{item.short}</small></button>)}
          </div>

          {loading ? <div className="video-loading"><LoaderCircle className="spin" /> Загружаем модели</div> : models.length ? <>
            <label className="video-field video-prompt"><span>Что происходит в кадре?</span><textarea value={prompt} maxLength={3000} placeholder="Например: камера медленно приближается, свет меняется от холодного к тёплому…" onChange={(event) => setPrompt(event.target.value)} /><small>{prompt.length} / 3000</small></label>
            <div className="video-options-row">
              <label className="video-field"><span>Модель</span><select value={selectedModel?.id || ''} onChange={(event) => syncModelDefaults(models.find((item) => item.id === event.target.value))}>{models.map((model) => <option key={model.id} value={model.id}>{model.name}</option>)}</select></label>
              <label className="video-field compact"><span>Длительность</span><select value={duration} onChange={(event) => setDuration(Number(event.target.value))}>{selectedModel?.supportedDurations.map((value) => <option key={value} value={value}>{value} сек.</option>)}</select></label>
            </div>
            <div className="video-choice-group"><span>Формат</span><div>{selectedModel?.supportedAspectRatios.map((value) => <button key={value} type="button" className={aspectRatio === value ? 'active' : ''} onClick={() => setAspectRatio(value)}>{value}</button>)}</div></div>
            <div className="video-choice-group"><span>Качество</span><div>{selectedModel?.supportedResolutions.map((value) => <button key={value} type="button" className={resolution === value ? 'active' : ''} onClick={() => setResolution(value)}>{value}</button>)}</div></div>
            {selectedModel?.generateAudio !== false && <label className="video-audio-toggle"><input type="checkbox" checked={generateAudio} onChange={(event) => setGenerateAudio(event.target.checked)} /><span>{generateAudio ? <Volume2 size={17} /> : <VolumeX size={17} />} Звук в ролике</span></label>}
            {error && <div className="video-error">{error}</div>}
            <button className="video-generate" type="button" disabled={!canSubmit} onClick={() => void submit()}>{submitting || activeJob ? <LoaderCircle className="spin" /> : <Sparkles />}<span>{activeJob ? 'Генерация идёт' : 'Создать видео'}</span>{estimate ? <b>{estimate} ток.</b> : <ArrowRight />}</button>
          </> : <div className="video-empty-models">{error || 'Для этого режима пока не включены модели вашего тарифа.'}</div>}
        </aside>

        <div className="video-stage-column">
          <header className="video-stage-header"><div><strong>{modeMeta.label}</strong><span>{shownJob ? statusLabel(shownJob.status) : 'Новый ролик'}</span></div>{shownJob?.status === 'completed' && <a href={shownJob.videoUrl || '#'} download><Film size={16} /> Скачать</a>}</header>
          <section className={`video-stage ratio-${aspectRatio.replace(':', '-')}`}>
            {shownJob?.status === 'completed' && shownJob.videoUrl ? (
              <video key={shownJob.videoUrl} src={shownJob.videoUrl} controls playsInline preload="metadata" />
            ) : shownJob && !['failed', 'cancelled', 'expired'].includes(shownJob.status) ? (
              <div className="video-progress"><div className="video-progress-visual"><span></span><Film /><span></span></div><strong>{statusLabel(shownJob.status)}</strong><p>Можно перейти в другой раздел. Задание останется в истории.</p><div className="video-progress-line"><i style={{ width: `${Math.max(8, shownJob.progress || 10)}%` }} /></div><small>{shownJob.progress || 10}%</small></div>
            ) : shownJob?.error ? (
              <div className="video-stage-message error"><Pause /><strong>Видео не создано</strong><p>{shownJob.error}</p><button type="button" onClick={() => setSelectedJob(null)}><RotateCcw /> Попробовать снова</button></div>
            ) : mode === 'text_to_video' ? (
              <div className="video-stage-message"><Play /><strong>Ваш ролик появится здесь</strong><p>{modeMeta.empty}</p></div>
            ) : mode === 'image_to_video' ? frameSurface('first', firstFrame, 'Исходный кадр', 'Перетащите изображение или выберите источник')
            : mode === 'first_last_frame' ? <div className="video-frame-pair">{frameSurface('first', firstFrame, 'Начальный кадр', 'С него начнётся ролик')}{frameSurface('last', lastFrame, 'Конечный кадр', 'К нему придёт движение')}</div>
            : <div className="video-references"><div className="video-reference-grid">{references.map((value, index) => <div key={`${value.slice(-30)}-${index}`} className="video-reference"><img src={apiUrl(value)} alt={`Референс ${index + 1}`} /><button type="button" title="Убрать" onClick={() => setReferences((current) => current.filter((_, itemIndex) => itemIndex !== index))}><X /></button></div>)}{references.length < 4 && <button type="button" className="video-add-reference" onClick={() => openUpload('reference')}><ImagePlus /><strong>Добавить референс</strong><span>До четырёх изображений</span></button>}</div><button type="button" className="video-gallery-link" onClick={() => void openGallery('reference')}><Images /> Выбрать из галереи</button></div>}
          </section>
        </div>
      </section>

      <section className="video-history" aria-label="История генераций">
        <header><div><Clock3 /><h2>История генераций</h2></div><span>{history.length ? `${history.length} роликов` : 'Пока пусто'}</span></header>
        {history.length ? <div className="video-history-list">{history.map((job) => <button key={job.id} type="button" className={selectedJob?.id === job.id ? 'active' : ''} onClick={() => setSelectedJob(job)}><span className="video-history-thumb">{job.status === 'completed' ? <Play /> : job.status === 'failed' ? <X /> : <LoaderCircle className="spin" />}</span><span className="video-history-copy"><strong>{job.prompt || 'Видео без названия'}</strong><small>{job.duration} сек. · {job.resolution} · {statusLabel(job.status)}</small></span>{job.status === 'completed' && <Check />}</button>)}</div> : <p>Первое созданное видео сохранится здесь.</p>}
      </section>

      {galleryOpen && <div className="video-gallery-overlay" role="dialog" aria-modal="true" aria-label="Выбор изображения" onClick={() => setGalleryOpen(null)}><div className="video-gallery-dialog" onClick={(event) => event.stopPropagation()}><header><div><Images /><h2>Выберите изображение</h2></div><button type="button" aria-label="Закрыть" onClick={() => setGalleryOpen(null)}><X /></button></header>{galleryLoading ? <div className="video-loading"><LoaderCircle className="spin" /> Загружаем галерею</div> : gallery.length ? <div className="video-gallery-grid">{gallery.map((item) => <button key={item.id} type="button" onClick={() => { assignImage(galleryOpen, item.url); setGalleryOpen(null) }}><img src={item.thumbnailUrl || item.url} alt={item.promptOriginal || 'Изображение из галереи'} loading="lazy" /><span>{item.width && item.height ? `${item.width}×${item.height}` : 'Из галереи'}</span></button>)}</div> : <p>В галерее пока нет изображений.</p>}</div></div>}
    </main>
  )
}
