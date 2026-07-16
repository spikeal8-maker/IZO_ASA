import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ChangeEvent, DragEvent, ReactElement } from 'react'
import {
  ChevronDown, Copy, Download, Film, ImagePlus, Images,
  Lightbulb, LoaderCircle, MoreVertical, Play, RotateCcw, Settings2,
  Share2, Sparkles, Trash2, Upload, Volume2, VolumeX, X,
} from 'lucide-react'
import { ensureSessionRefreshedV2 } from './authV2'
import './videoStudio.css'

type VideoMode = 'text_to_video' | 'image_to_video' | 'first_last_frame' | 'reference_to_video'
type VideoQuality = 'fast' | 'standard' | 'max'
type FrameKey = 'first' | 'last' | 'reference'

type VideoPriceExample = { duration: number; resolution: string; aspectRatio: string; tokens: number }
type VideoModel = {
  id: string
  name: string
  description: string
  supportedResolutions: string[]
  supportedAspectRatios: string[]
  supportedDurations: number[]
  supportedFrameImages: string[]
  generateAudio: boolean | null
  publicPricing?: { fromTokens?: number | null; examples?: VideoPriceExample[] }
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
  galleryVideoId?: string | null
  galleryDeleted?: boolean
  generateAudio?: boolean
}
type GalleryImage = { id: string; url?: string; src?: string; viewerSrc?: string; thumbnailUrl?: string; width?: number; height?: number; promptOriginal?: string }

const MODE_META: Array<{ id: VideoMode; label: string; note: string; empty: string }> = [
  { id: 'text_to_video', label: 'Текст → видео', note: 'Создать сцену', empty: 'Опишите сцену, движение камеры и настроение ролика' },
  { id: 'image_to_video', label: 'Изображение → видео', note: 'Оживить кадр', empty: 'Загрузите исходный кадр и опишите движение' },
  { id: 'first_last_frame', label: 'Начало и конец', note: 'Переход кадров', empty: 'Добавьте начальный и конечный кадры' },
  { id: 'reference_to_video', label: 'По референсам', note: 'Собрать ролик', empty: 'Добавьте изображения героя, предмета или стиля' },
]
const QUALITY_META: Array<{ id: VideoQuality; label: string }> = [
  { id: 'fast', label: 'Быстро' },
  { id: 'standard', label: 'Стандарт' },
  { id: 'max', label: 'Максимум' },
]
const DRAFT_KEY = 'izo-video-draft-v2'
const VISIBILITY_KEY = 'izo:video-model-visibility'
const QUALITY_MODELS_KEY = 'izo:video-quality-models'

async function apiFetch(path: string, init?: RequestInit) {
  let response = await fetch(`/api${path}`, { ...init, credentials: 'include' })
  if (response.status === 401 && await ensureSessionRefreshedV2()) response = await fetch(`/api${path}`, { ...init, credentials: 'include' })
  return response
}
async function responseError(response: Response, fallback: string) {
  try { const data = await response.json(); return String(data.detail || data.error || fallback) } catch { return fallback }
}
function readStorage<T>(key: string, fallback: T): T {
  try { const value = localStorage.getItem(key); return value ? JSON.parse(value) as T : fallback } catch { return fallback }
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
  if (['failed', 'cancelled', 'expired'].includes(status)) return 'Не завершено'
  if (status === 'in_progress') return 'Создаём видео'
  return 'В очереди'
}
function aspectStyle(value: string | undefined) {
  const [width, height] = String(value || '16:9').split(':').map(Number)
  return `${width || 16} / ${height || 9}`
}
export default function VideoStudio(): ReactElement {
  const initialDraft = useMemo(() => readStorage<Record<string, unknown>>(DRAFT_KEY, {}), [])
  const initialMode = (initialDraft.mode as VideoMode) || 'text_to_video'
  const [mode, setMode] = useState<VideoMode>(initialMode)
  const [quality, setQuality] = useState<VideoQuality>((initialDraft.quality as VideoQuality) || 'fast')
  const [prompt, setPrompt] = useState(String(initialDraft.prompt || ''))
  const [config, setConfig] = useState<VideoConfig | null>(null)
  const [modelId, setModelId] = useState(String(initialDraft.modelId || ''))
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
  const [proOpen, setProOpen] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  const visibility = useMemo(() => readStorage<Record<VideoMode, Record<string, boolean>>>(VISIBILITY_KEY, {} as Record<VideoMode, Record<string, boolean>>), [])
  const qualityModels = useMemo(() => readStorage<Record<VideoMode, Partial<Record<VideoQuality, string>>>>(QUALITY_MODELS_KEY, {} as Record<VideoMode, Partial<Record<VideoQuality, string>>>), [])
  const models = useMemo(() => (config?.modes[mode] || []).filter((item) => visibility[mode]?.[item.id] !== false), [config, visibility, mode])
  const sortedModels = useMemo(() => [...models].sort((a, b) => Number(a.publicPricing?.fromTokens ?? 999999) - Number(b.publicPricing?.fromTokens ?? 999999)), [models])
  const qualityModel = useCallback((nextQuality: VideoQuality, candidates = sortedModels) => {
    const stored = qualityModels[mode]?.[nextQuality]
    if (stored && candidates.some((item) => item.id === stored)) return candidates.find((item) => item.id === stored)
    if (nextQuality === 'fast') return candidates[0]
    if (nextQuality === 'max') return candidates[candidates.length - 1]
    return candidates[Math.floor((candidates.length - 1) / 2)] || candidates[0]
  }, [mode, qualityModels, sortedModels])
  const selectedModel = models.find((item) => item.id === modelId) || qualityModel(quality) || models[0]

  const syncModelDefaults = useCallback((model: VideoModel | undefined) => {
    if (!model) return
    setModelId(model.id)
    setDuration((value) => model.supportedDurations.includes(value) ? value : (model.supportedDurations[0] || 5))
    setResolution((value) => model.supportedResolutions.includes(value) ? value : (model.supportedResolutions[0] || '720p'))
    setAspectRatio((value) => model.supportedAspectRatios.includes(value) ? value : (model.supportedAspectRatios[0] || '16:9'))
    if (model.generateAudio === false) setGenerateAudio(false)
  }, [])

  const loadHistory = useCallback(async () => {
    const response = await apiFetch('/video/history?limit=40')
    if (!response.ok) return
    const data = await response.json() as { items?: VideoJob[] }
    const items = (Array.isArray(data.items) ? data.items : []).filter((item) => !item.galleryDeleted)
    setHistory(items)
    const running = items.find((item) => !['completed', 'failed', 'cancelled', 'expired'].includes(item.status)) || null
    setActiveJob(running)
    setSelectedJob((current) => current ? items.find((item) => item.id === current.id) || items.find((item) => item.status === 'completed') || running || null : items.find((item) => item.status === 'completed') || running || null)
  }, [])

  useEffect(() => {
    Promise.all([apiFetch('/video/config'), apiFetch('/video/history?limit=40')]).then(async ([configResponse, historyResponse]) => {
      if (!configResponse.ok) throw new Error(await responseError(configResponse, 'Видео сейчас недоступно.'))
      const nextConfig = await configResponse.json() as VideoConfig
      setConfig(nextConfig)
      const candidates = (nextConfig.modes[initialMode] || []).filter((item) => visibility[initialMode]?.[item.id] !== false)
      const storedModel = candidates.find((item) => item.id === String(initialDraft.modelId || ''))
      const ranked = [...candidates].sort((a, b) => Number(a.publicPricing?.fromTokens ?? 999999) - Number(b.publicPricing?.fromTokens ?? 999999))
      const preferred = storedModel || (initialDraft.quality === 'max' ? ranked[ranked.length - 1] : initialDraft.quality === 'standard' ? ranked[Math.floor((ranked.length - 1) / 2)] : ranked[0])
      syncModelDefaults(preferred)
      if (historyResponse.ok) {
        const data = await historyResponse.json() as { items?: VideoJob[] }
        const items = (data.items || []).filter((item) => !item.galleryDeleted)
        setHistory(items)
        const running = items.find((item) => !['completed', 'failed', 'cancelled', 'expired'].includes(item.status)) || null
        setActiveJob(running)
        setSelectedJob(items.find((item) => item.status === 'completed') || running || null)
      }
    }).catch((reason: Error) => setError(reason.message)).finally(() => setLoading(false))
  }, [initialDraft.modelId, initialDraft.quality, initialMode, syncModelDefaults, visibility])

  useEffect(() => { localStorage.setItem(DRAFT_KEY, JSON.stringify({ mode, quality, prompt, modelId, duration, resolution, aspectRatio, generateAudio })) }, [mode, quality, prompt, modelId, duration, resolution, aspectRatio, generateAudio])
  useEffect(() => { if (!activeJob) return; const timer = window.setInterval(() => void loadHistory(), 8000); return () => window.clearInterval(timer) }, [activeJob, loadHistory])

  const selectMode = (nextMode: VideoMode) => {
    setMode(nextMode)
    setError('')
    const candidates = (config?.modes[nextMode] || []).filter((item) => visibility[nextMode]?.[item.id] !== false)
    const sorted = [...candidates].sort((a, b) => Number(a.publicPricing?.fromTokens ?? 999999) - Number(b.publicPricing?.fromTokens ?? 999999))
    const stored = qualityModels[nextMode]?.[quality]
    syncModelDefaults(candidates.find((item) => item.id === stored) || (quality === 'max' ? sorted[sorted.length - 1] : quality === 'standard' ? sorted[Math.floor((sorted.length - 1) / 2)] : sorted[0]))
  }
  const selectQuality = (next: VideoQuality) => { setQuality(next); syncModelDefaults(qualityModel(next)) }

  const requestBody = useMemo(() => selectedModel ? {
    mode, model: selectedModel.id, prompt: prompt.trim() || 'preview', duration, resolution,
    aspectRatio, generateAudio, firstFrame: firstFrame || null, lastFrame: lastFrame || null, references,
  } : null, [mode, selectedModel, prompt, duration, resolution, aspectRatio, generateAudio, firstFrame, lastFrame, references])
  useEffect(() => {
    if (!requestBody) return
    const timer = window.setTimeout(async () => {
      const response = await apiFetch('/video/estimate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(requestBody) })
      if (response.ok) { const data = await response.json() as { chargedTokens?: number }; setEstimate(Number(data.chargedTokens || 0) || null) } else setEstimate(null)
    }, 350)
    return () => window.clearTimeout(timer)
  }, [requestBody])

  const assignImage = (target: FrameKey, value: string) => {
    if (target === 'first') setFirstFrame(value)
    else if (target === 'last') setLastFrame(value)
    else setReferences((current) => current.length < 4 ? [...current, value] : current)
  }
  const removeImage = (target: FrameKey, index = -1) => {
    if (target === 'first') setFirstFrame('')
    else if (target === 'last') setLastFrame('')
    else setReferences((current) => current.filter((_, itemIndex) => itemIndex !== index))
  }
  const openUpload = (target: FrameKey) => { setUploadTarget(target); fileRef.current?.click() }
  const handleFile = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]; event.target.value = ''; if (!file) return
    try { assignImage(uploadTarget, await fileAsDataUrl(file)); setError('') } catch (reason) { setError((reason as Error).message) }
  }
  const handleDrop = async (target: FrameKey, event: DragEvent) => {
    event.preventDefault(); const file = event.dataTransfer.files?.[0]; if (!file) return
    try { assignImage(target, await fileAsDataUrl(file)); setError('') } catch (reason) { setError((reason as Error).message) }
  }
  const openGallery = async (target: FrameKey) => {
    setGalleryOpen(target); setGalleryLoading(true)
    const response = await apiFetch('/gallery/items?limit=60&filter=image')
    if (response.ok) { const data = await response.json() as { items?: GalleryImage[] }; setGallery(data.items || []) }
    setGalleryLoading(false)
  }

  const canSubmit = Boolean(prompt.trim() && selectedModel && !submitting && !activeJob && (mode === 'text_to_video' || (mode === 'image_to_video' && firstFrame) || (mode === 'first_last_frame' && firstFrame && lastFrame) || (mode === 'reference_to_video' && references.length)))
  const submit = async () => {
    if (!requestBody || !canSubmit) return
    setSubmitting(true); setError('')
    try {
      const response = await apiFetch('/video/generate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(requestBody) })
      if (!response.ok) throw new Error(await responseError(response, 'Не удалось запустить видео.'))
      const data = await response.json() as VideoJob
      const job = { ...data, mode, prompt, createdAt: new Date().toISOString(), model: modelId, duration, resolution, aspectRatio, generateAudio }
      setActiveJob(job); setSelectedJob(job); await loadHistory()
    } catch (reason) { setError((reason as Error).message) } finally { setSubmitting(false) }
  }
  const deleteVideo = async (job: VideoJob) => {
    if (!job.galleryVideoId || !window.confirm('Удалить видео из галереи? Файл будет удалён без восстановления.')) return
    const response = await apiFetch(`/gallery/videos/${encodeURIComponent(job.galleryVideoId)}`, { method: 'DELETE' })
    if (!response.ok) { setError(await responseError(response, 'Не удалось удалить видео.')); return }
    setHistory((items) => items.filter((item) => item.id !== job.id)); setSelectedJob(null); setMenuOpen(false)
  }
  const shareVideo = async (job: VideoJob) => {
    const url = new URL(job.videoUrl || '', window.location.origin).toString()
    if (navigator.share) await navigator.share({ title: 'Видео ИЗО АСА', text: job.prompt, url })
    else { await navigator.clipboard.writeText(url); setError('Ссылка на видео скопирована.') }
  }
  const applySettings = (job: VideoJob) => {
    setMode(job.mode); setPrompt(job.prompt || ''); setDuration(Number(job.duration || duration)); setResolution(job.resolution || resolution); setAspectRatio(job.aspectRatio || aspectRatio); setGenerateAudio(Boolean(job.generateAudio));
    const candidates = config?.modes[job.mode] || []; syncModelDefaults(candidates.find((item) => item.id === job.model) || candidates[0]); window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  const sourceCard = (target: FrameKey, value: string, title: string, note: string, index = -1) => (
    <div className={`video-source${value ? ' filled' : ''}`} onDragOver={(event) => event.preventDefault()} onDrop={(event) => void handleDrop(target, event)}>
      {value ? <img src={value} alt={title} /> : <ImagePlus aria-hidden="true" />}
      <div><strong>{title}</strong><span>{value ? 'Кадр добавлен' : note}</span></div>
      <div className="video-source-actions">
        <button type="button" onClick={() => openUpload(target)} title="Загрузить с устройства"><Upload /><span>Загрузить</span></button>
        <button type="button" onClick={() => void openGallery(target)} title="Выбрать из галереи"><Images /><span>Галерея</span></button>
        {value && <button type="button" onClick={() => removeImage(target, index)} title="Убрать"><X /></button>}
      </div>
    </div>
  )

  const shownJob = selectedJob || activeJob
  const modeMeta = MODE_META.find((item) => item.id === mode) || MODE_META[0]
  const stageRatio = shownJob?.aspectRatio || aspectRatio
  const selectedModelPrice = selectedModel?.publicPricing?.fromTokens

  return <main className="video-studio">
    <input ref={fileRef} type="file" accept="image/png,image/jpeg,image/webp" hidden onChange={(event) => void handleFile(event)} />
    <section className="video-shell">
      <aside className="video-composer" aria-label="Настройки видеогенерации">
        <header className="video-composer-title"><span>Видео</span><h1>Создать ролик</h1></header>
        <div className="video-mode-tabs" role="tablist" aria-label="Способ создания">
          {MODE_META.map((item) => <button key={item.id} type="button" role="tab" aria-selected={mode === item.id} className={mode === item.id ? 'active' : ''} onClick={() => selectMode(item.id)}><strong>{item.label}</strong><small>{item.note}</small></button>)}
        </div>

        {loading ? <div className="video-loading"><LoaderCircle className="spin" /> Загружаем модели</div> : models.length ? <>
          {mode !== 'text_to_video' && <section className="video-inputs"><h2>Исходные материалы</h2>
            {mode === 'image_to_video' && sourceCard('first', firstFrame, 'Исходный кадр', 'Фото, которое нужно оживить')}
            {mode === 'first_last_frame' && <div className="video-input-pair">{sourceCard('first', firstFrame, 'Начало', 'Первый кадр')}{sourceCard('last', lastFrame, 'Конец', 'Последний кадр')}</div>}
            {mode === 'reference_to_video' && <div className="video-reference-inputs">{references.map((value, index) => sourceCard('reference', value, `Референс ${index + 1}`, '', index))}{references.length < 4 && sourceCard('reference', '', 'Добавить референс', 'До четырёх изображений')}</div>}
          </section>}

          <label className="video-prompt"><span><b>Что происходит в кадре?</b><button type="button" title="Подсказки"><Lightbulb /> Подсказки</button></span><textarea value={prompt} maxLength={3000} placeholder="Опишите сцену, движение камеры, действия и атмосферу..." onChange={(event) => setPrompt(event.target.value)} /><small>{prompt.length} / 3000</small></label>
          <div className="video-prompt-actions"><button type="button" disabled><Sparkles /> Голос</button><button type="button" disabled><Sparkles /> Улучшить</button><button type="button" onClick={() => setPrompt('Камера плавно приближается, естественное движение объектов, кинематографичный свет и реалистичная атмосфера.')}>Пример</button></div>

          <section className="video-params"><h2>Основные параметры</h2>
            <div className="video-quality-tabs">{QUALITY_META.map((item) => <button type="button" key={item.id} className={quality === item.id ? 'active' : ''} onClick={() => selectQuality(item.id)}>{item.label}</button>)}</div>
            <div className="video-options-row">
              <label><span>Модель</span><select value={selectedModel?.id || ''} onChange={(event) => syncModelDefaults(models.find((item) => item.id === event.target.value))}>{models.map((model) => <option key={model.id} value={model.id}>{model.name}{model.publicPricing?.fromTokens ? ` · от ${model.publicPricing.fromTokens} ток.` : ''}</option>)}</select><small>{selectedModelPrice ? `Стоимость модели: от ${selectedModelPrice} ток.` : 'Цена рассчитывается по параметрам'}</small></label>
              <label><span>Длительность</span><select value={duration} onChange={(event) => setDuration(Number(event.target.value))}>{selectedModel?.supportedDurations.map((value) => <option key={value} value={value}>{value} секунд</option>)}</select></label>
            </div>
            <div className="video-setting-label">Формат</div>
            <div className="video-format-tabs">{selectedModel?.supportedAspectRatios.map((value) => <button key={value} type="button" className={aspectRatio === value ? 'active' : ''} onClick={() => setAspectRatio(value)}><i style={{ aspectRatio: aspectStyle(value) }} /><span>{value}</span></button>)}</div>
            <div className="video-setting-label">Качество</div>
            <div className="video-resolution-tabs">{selectedModel?.supportedResolutions.map((value) => <button key={value} type="button" className={resolution === value ? 'active' : ''} onClick={() => setResolution(value)}>{value}</button>)}</div>
            {selectedModel?.generateAudio !== false && <label className="video-audio"><span>{generateAudio ? <Volume2 /> : <VolumeX />}<b>Звук в ролике</b><small>Сгенерировать звук и атмосферу</small></span><input type="checkbox" checked={generateAudio} onChange={(event) => setGenerateAudio(event.target.checked)} /><i /></label>}
            <button type="button" className="video-pro" onClick={() => setProOpen((value) => !value)}><Settings2 /> Профессиональные настройки <ChevronDown className={proOpen ? 'open' : ''} /></button>
            {proOpen && <div className="video-pro-body">Модель, длительность, формат и звук уже передаются провайдеру напрямую. Дополнительные технические параметры появятся только после проверки их поддержки.</div>}
          </section>
          {error && <div className="video-error">{error}</div>}
          <button className="video-generate" type="button" disabled={!canSubmit} onClick={() => void submit()}>{submitting || activeJob ? <LoaderCircle className="spin" /> : <Sparkles />}<span>{activeJob ? 'Генерация идёт' : 'Создать видео'}</span><b>{estimate ? `${estimate} ток.` : 'Рассчитаем'}</b></button>
        </> : <div className="video-empty-models">{error || 'Для этого режима пока не включены модели вашего тарифа.'}</div>}
      </aside>

      <section className="video-result">
        <header className="video-stage-head"><div><h2>Предпросмотр</h2>{shownJob && <span className={`status ${shownJob.status}`}>{statusLabel(shownJob.status)}</span>}</div><div className="video-stage-actions">
          {shownJob?.videoUrl && <a href={shownJob.videoUrl} download title="Скачать"><Download /> <span>Скачать</span></a>}
          {shownJob?.videoUrl && <button type="button" onClick={() => void shareVideo(shownJob)}><Share2 /> <span>Поделиться</span></button>}
          {shownJob?.galleryVideoId && <div className="video-more"><button type="button" title="Другие действия" onClick={() => setMenuOpen((value) => !value)}><MoreVertical /></button>{menuOpen && <div><button type="button" onClick={() => void deleteVideo(shownJob)}><Trash2 /> Удалить видео</button></div>}</div>}
        </div></header>
        <div className="video-stage-wrap"><div className="video-stage" style={{ aspectRatio: aspectStyle(stageRatio) }}>
          {shownJob?.status === 'completed' && shownJob.videoUrl ? <video key={shownJob.videoUrl} src={shownJob.videoUrl} controls playsInline preload="metadata" />
            : shownJob && !['failed', 'cancelled', 'expired'].includes(shownJob.status) ? <div className="video-progress"><Film /><strong>{statusLabel(shownJob.status)}</strong><p>Можно закрыть страницу. Ролик сохранится в истории и галерее.</p><div><i style={{ width: `${Math.max(8, shownJob.progress || 10)}%` }} /></div><small>{shownJob.progress || 10}%</small></div>
            : shownJob?.error ? <div className="video-stage-message error"><RotateCcw /><strong>Видео не создано</strong><p>{shownJob.error}</p><button type="button" onClick={() => setSelectedJob(null)}>Попробовать снова</button></div>
            : <div className="video-stage-message"><Play /><strong>{modeMeta.empty}</strong><p>Выберите параметры и создайте видео</p></div>}
        </div></div>

        <div className="video-result-shelf">
          <section className="video-history" aria-label="История генераций"><header><h2>История генераций</h2><span>{history.length ? `${history.length} роликов` : 'Пока пусто'}</span></header>
            {history.length ? <div className="video-history-list">{history.map((job) => <button key={job.id} type="button" className={selectedJob?.id === job.id ? 'active' : ''} onClick={() => setSelectedJob(job)} style={{ aspectRatio: aspectStyle(job.aspectRatio) }}>{job.videoUrl ? <video src={job.videoUrl} muted preload="metadata" /> : <span>{job.status === 'completed' ? <Play /> : <LoaderCircle className="spin" />}</span>}<small>{job.duration || 0} сек.</small></button>)}</div> : <p>Первое созданное видео появится здесь и в общей галерее.</p>}
          </section>
          <aside className="video-context"><header><h2>Промпт и параметры</h2></header>{shownJob ? <><p>{shownJob.prompt || 'Промпт не сохранён'}</p><div className="video-context-tags"><span>{models.find((item) => item.id === shownJob.model)?.name || shownJob.model}</span><span>{shownJob.duration} сек.</span><span>{shownJob.aspectRatio}</span><span>{shownJob.resolution}</span>{shownJob.generateAudio && <span><Volume2 /> Звук</span>}</div><div className="video-context-actions"><button type="button" onClick={() => void navigator.clipboard.writeText(shownJob.prompt || '')}><Copy /> Копировать</button><button type="button" onClick={() => applySettings(shownJob)}><Settings2 /> Использовать настройки</button></div></> : <p>Выберите работу в истории, чтобы увидеть ее промпт и настройки.</p>}</aside>
        </div>
      </section>
    </section>

    {galleryOpen && <div className="video-gallery-overlay" role="dialog" aria-modal="true" aria-label="Выбор изображения" onClick={() => setGalleryOpen(null)}><div className="video-gallery-dialog" onClick={(event) => event.stopPropagation()}><header><div><Images /><h2>Выберите изображение</h2></div><button type="button" aria-label="Закрыть" onClick={() => setGalleryOpen(null)}><X /></button></header>{galleryLoading ? <div className="video-loading"><LoaderCircle className="spin" /> Загружаем галерею</div> : gallery.length ? <div className="video-gallery-grid">{gallery.map((item) => { const source = item.url || item.viewerSrc || item.src || item.thumbnailUrl || ''; return <button key={item.id} type="button" disabled={!source} onClick={() => { assignImage(galleryOpen, source); setGalleryOpen(null) }}><img src={item.thumbnailUrl || item.src || source} alt={item.promptOriginal || 'Изображение из галереи'} loading="lazy" /><span>{item.width && item.height ? `${item.width}×${item.height}` : 'Из галереи'}</span></button> })}</div> : <p>В галерее пока нет изображений.</p>}</div></div>}
  </main>
}
