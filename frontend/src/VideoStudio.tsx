import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ChangeEvent, DragEvent, ReactElement } from 'react'
import {
  ChevronDown, CircleHelp, Clock3, Copy, Download, Film, ImagePlus, Images,
  LoaderCircle, Mic2, MoreVertical, Play, RotateCcw, Settings2,
  Share2, Sparkles, Trash2, Upload, Volume2, VolumeX, WandSparkles, X,
} from 'lucide-react'
import { ensureSessionRefreshedV2 } from './authV2'
import './videoStudio.css'

type VideoMode = 'text_to_video' | 'image_to_video' | 'first_last_frame' | 'reference_to_video'
type VideoQuality = 'fast' | 'standard' | 'max'
type FrameKey = 'first' | 'last' | 'reference'

type VideoPriceExample = { duration: number; resolution: string; aspectRatio: string; tokens: number }
type VideoEstimate = {
  chargedTokens: number
  estimatedCostRub?: number
  profitRub?: number
  rateUsd?: number
  pricingKey?: string | null
}
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
  feedPublicationEnabled?: boolean
  videoStorage?: { used: number; limit: number; free: number; full: boolean; storedBytes: number }
  economy: { tokenRub: number; minMarginPercent: number }
  availability?: Record<VideoMode, { enabled: number; tariff: number; reason?: string }>
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
  published?: boolean
  publicationId?: string | null
  publicationStatus?: 'preparing' | 'published' | 'failed' | 'hidden' | null
  publicationError?: string | null
}
type GalleryImage = { id: string; url?: string; src?: string; viewerSrc?: string; thumbnailUrl?: string; width?: number; height?: number; promptOriginal?: string }

const MODE_META: Array<{ id: VideoMode; label: string; note: string; empty: string }> = [
  { id: 'text_to_video', label: 'Текст → видео', note: 'Создать сцену по тексту', empty: 'Опишите сцену, движение камеры и настроение ролика' },
  { id: 'image_to_video', label: 'Изображение → видео', note: 'Оживить изображение', empty: 'Загрузите исходный кадр и опишите движение' },
  { id: 'first_last_frame', label: 'Начало и конец', note: 'Переход кадров', empty: 'Добавьте начальный и конечный кадры' },
  { id: 'reference_to_video', label: 'По референсам', note: 'Собрать ролик', empty: 'Добавьте изображения героя, предмета или стиля' },
]
const QUALITY_META: Array<{ id: VideoQuality; label: string }> = [
  { id: 'fast', label: 'Быстро' },
  { id: 'standard', label: 'Стандарт' },
  { id: 'max', label: 'Максимум' },
]
const EXAMPLE_PROMPTS: Record<VideoMode, string[]> = {
  text_to_video: [
    'На рассвете камера плавно летит над футуристическим городом у моря. На улицах просыпается жизнь, транспорт мягко движется между зданиями, солнечные лучи отражаются в стекле, лёгкий туман растворяется в тёплом свете. Кинематографичная композиция, естественная динамика и реалистичная атмосфера.',
    'Камера медленно движется вдоль вечерней набережной после дождя. Неон отражается в мокром асфальте, прохожие раскрывают зонты, лёгкий пар поднимается от люков, а вдали проходит трамвай. Реалистичная оптика и спокойный кинематографичный ритм.',
    'Макросъёмка капли росы на листе. Камера плавно приближается, в отражении появляется рассветный лес, лист слегка колышется от ветра, мягкий контровой свет подчёркивает фактуру и прозрачность воды.',
    'Широкий кадр пустынной планеты: исследователь идёт к огромной светящейся арке, пыль медленно стелется по земле, камера следует сзади и постепенно поднимается, открывая масштабный пейзаж и далёкие спутники.',
  ],
  image_to_video: [
    'Камера медленно приближается к главному объекту. Волосы, одежда и детали окружения естественно движутся от лёгкого ветра, свет мягко меняется, исходная композиция и внешность сохраняются.',
    'Сохрани исходный кадр и внешность героя. Добавь едва заметное дыхание, естественное моргание, мягкое движение камеры вправо и живые световые блики на фоне без деформации лица.',
    'Оживи сцену лёгким параллаксом: передний план движется быстрее дальнего, камера плавно отъезжает, листья и ткань естественно реагируют на ветер, исходные цвета и композиция сохраняются.',
    'Камера делает медленный полукруг вокруг объекта. Сохрани форму, материалы и все надписи, добавь реалистичные отражения, мягкое изменение света и спокойное движение окружения.',
  ],
  first_last_frame: [
    'Создай плавный кинематографичный переход от первого кадра к последнему. Сохрани объекты и композицию, добавь естественное движение камеры, света и окружающей среды без резких скачков.',
    'Плавно свяжи начальный и конечный кадры через движение камеры вперёд. Все изменения должны происходить последовательно, без внезапного появления объектов, мерцания и деформаций.',
    'Сделай переход через мягкий поворот камеры влево: пространство и персонажи постепенно принимают положение финального кадра, свет меняется естественно, движение остаётся непрерывным.',
    'Соедини кадры как один непрерывный план. Камера медленно поднимается, детали окружения логично трансформируются, а финальная композиция точно совпадает с последним изображением.',
  ],
  reference_to_video: [
    'Собери цельную динамичную сцену по загруженным референсам. Сохрани внешность, предметы и визуальный стиль, добавь естественное движение камеры, реалистичный свет и последовательное действие.',
    'Используй персонажа, одежду и окружение из референсов в одной сцене. Камера плавно следует за героем, пропорции и узнаваемые детали сохраняются, движение выглядит физически правдоподобно.',
    'Объедини референсы в рекламный ролик продукта: чистое движение камеры по дуге, аккуратные световые блики, точные материалы и цвета, без изменения формы предмета и логотипа.',
    'Создай короткую сюжетную сцену на основе всех референсов. Сохрани идентичность персонажей и стиль окружения, добавь последовательное действие, естественную мимику и согласованный свет.',
  ],
}
const PRIMARY_ASPECT_RATIOS = ['16:9', '9:16', '1:1', '4:3']
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
function errorText(detail: unknown, fallback: string) {
  if (typeof detail === 'string' && detail.trim()) return detail.trim()
  if (detail && typeof detail === 'object' && 'message' in detail && typeof detail.message === 'string') return detail.message
  return fallback
}
function shortModelName(model: VideoModel | undefined) {
  if (!model) return 'Нет модели'
  return model.name.replace(/^.*?:\s*/, '').replace(/\s+(Preview|Standard)$/i, ' $1')
}
function publicModelRate(model: VideoModel | undefined) {
  const tokens = Number(model?.publicPricing?.fromTokens || 0)
  const seconds = Math.min(...(model?.supportedDurations || []).filter((value) => value > 0))
  if (!tokens || !Number.isFinite(seconds)) return 'расчёт после выбора'
  const rate = tokens / seconds
  return `от ${formatTokenRate(rate)} ток./с`
}
function aspectPreviewWidth(value: string) {
  const [width, height] = value.split(':').map(Number)
  const ratio = width > 0 && height > 0 ? width / height : 16 / 9
  return `${Math.round(Math.min(40, Math.max(14, 23 * ratio)))}px`
}
function formatTokenRate(value: number) {
  return new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 }).format(value)
}
function formatElapsed(createdAt?: string | null, completedAt?: string | null, now = Date.now()) {
  const started = Date.parse(String(createdAt || ''))
  const finished = completedAt ? Date.parse(completedAt) : now
  if (!Number.isFinite(started) || !Number.isFinite(finished) || finished < started) return ''
  const total = Math.max(0, Math.round((finished - started) / 1000))
  if (total < 60) return `${total} сек.`
  const minutes = Math.floor(total / 60)
  const seconds = total % 60
  return `${minutes} мин. ${seconds} сек.`
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
  const [estimate, setEstimate] = useState<VideoEstimate | null>(null)
  const [estimateKey, setEstimateKey] = useState('')
  const [estimateLoading, setEstimateLoading] = useState(false)
  const [qualityEstimates, setQualityEstimates] = useState<Partial<Record<VideoQuality, VideoEstimate>>>({})
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [galleryOpen, setGalleryOpen] = useState<FrameKey | null>(null)
  const [gallery, setGallery] = useState<GalleryImage[]>([])
  const [galleryLoading, setGalleryLoading] = useState(false)
  const [uploadTarget, setUploadTarget] = useState<FrameKey>('first')
  const [proOpen, setProOpen] = useState(false)
  const [formatExpanded, setFormatExpanded] = useState(false)
  const [mobileModeOpen, setMobileModeOpen] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  const [shareOpen, setShareOpen] = useState(false)
  const [publishJob, setPublishJob] = useState<VideoJob | null>(null)
  const [publishTitle, setPublishTitle] = useState('')
  const [publishDescription, setPublishDescription] = useState('')
  const [publishVisibility, setPublishVisibility] = useState<'open' | 'partial' | 'hidden'>('open')
  const [publishCategory, setPublishCategory] = useState('other')
  const [publishTags, setPublishTags] = useState('')
  const [publishBusy, setPublishBusy] = useState(false)
  const [notice, setNotice] = useState('')
  const [guideOpen, setGuideOpen] = useState(false)
  const [previewCleared, setPreviewCleared] = useState(false)
  const [voiceRecording, setVoiceRecording] = useState(false)
  const [voiceBusy, setVoiceBusy] = useState(false)
  const [improveBusy, setImproveBusy] = useState(false)
  const [lastImprovedPrompt, setLastImprovedPrompt] = useState('')
  const [clockNow, setClockNow] = useState(() => Date.now())
  const fileRef = useRef<HTMLInputElement>(null)
  const promptTextareaRef = useRef<HTMLTextAreaElement>(null)
  const voiceRecorderRef = useRef<MediaRecorder | null>(null)
  const voiceStreamRef = useRef<MediaStream | null>(null)
  const voiceStartedAtRef = useRef(0)

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
  const qualityChoices = useMemo(() => Object.fromEntries(QUALITY_META.map((item) => [item.id, qualityModel(item.id)])) as Record<VideoQuality, VideoModel | undefined>, [qualityModel])

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
  const hasPreparingPublication = history.some((item) => item.publicationStatus === 'preparing')
  useEffect(() => {
    if (!hasPreparingPublication) return
    const timer = window.setInterval(() => void loadHistory(), 2500)
    return () => window.clearInterval(timer)
  }, [hasPreparingPublication, loadHistory])
  useEffect(() => {
    if (!activeJob) return
    const timer = window.setInterval(() => setClockNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [activeJob])

  const selectMode = (nextMode: VideoMode) => {
    setMode(nextMode)
    setMobileModeOpen(false)
    setError('')
    const candidates = (config?.modes[nextMode] || []).filter((item) => visibility[nextMode]?.[item.id] !== false)
    const sorted = [...candidates].sort((a, b) => Number(a.publicPricing?.fromTokens ?? 999999) - Number(b.publicPricing?.fromTokens ?? 999999))
    const stored = qualityModels[nextMode]?.[quality]
    syncModelDefaults(candidates.find((item) => item.id === stored) || (quality === 'max' ? sorted[sorted.length - 1] : quality === 'standard' ? sorted[Math.floor((sorted.length - 1) / 2)] : sorted[0]))
  }
  const selectQuality = (next: VideoQuality) => { setQuality(next); syncModelDefaults(qualityModel(next)) }
  const useNextExample = () => {
    const examples = EXAMPLE_PROMPTS[mode]
    const currentIndex = examples.indexOf(prompt)
    const nextIndex = currentIndex >= 0 ? (currentIndex + 1) % examples.length : Math.floor(Math.random() * examples.length)
    setPrompt(examples[nextIndex])
    setLastImprovedPrompt('')
  }

  const improvePrompt = async () => {
    const original = prompt.trim()
    if (!original || improveBusy) return
    setImproveBusy(true); setError('')
    try {
      const response = await apiFetch('/tools/improve-prompt', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: original, mode, language: 'ru', technicalPrompt: '' }),
      })
      const payload = await response.json().catch(() => ({})) as { improvedPrompt?: string; detail?: unknown }
      if (!response.ok || !payload.improvedPrompt?.trim()) throw new Error(errorText(payload.detail, 'Не удалось улучшить описание.'))
      const improved = payload.improvedPrompt.trim().slice(0, 3000)
      setPrompt(improved); setLastImprovedPrompt(improved)
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Не удалось улучшить описание.') }
    finally { setImproveBusy(false) }
  }

  const toggleVoiceInput = async () => {
    if (voiceRecording) { voiceRecorderRef.current?.stop(); return }
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
      setError('Этот браузер не поддерживает запись голоса.'); return
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const preferredType = ['audio/webm;codecs=opus', 'audio/ogg;codecs=opus', 'audio/webm'].find((value) => MediaRecorder.isTypeSupported(value)) || ''
      const recorder = new MediaRecorder(stream, preferredType ? { mimeType: preferredType } : undefined)
      const chunks: BlobPart[] = []
      recorder.ondataavailable = (event) => { if (event.data.size) chunks.push(event.data) }
      recorder.onerror = () => setError('Не удалось записать голос.')
      recorder.onstop = async () => {
        const durationMs = Math.max(0, Date.now() - voiceStartedAtRef.current)
        setVoiceRecording(false)
        voiceStreamRef.current?.getTracks().forEach((track) => track.stop())
        voiceStreamRef.current = null; voiceRecorderRef.current = null
        if (durationMs < 1000) { setError('Говорите не меньше одной секунды.'); return }
        const blob = new Blob(chunks, { type: recorder.mimeType || 'audio/webm' })
        const form = new FormData()
        form.append('file', blob, `voice.${blob.type.includes('ogg') ? 'ogg' : 'webm'}`)
        setVoiceBusy(true); setError('')
        try {
          const response = await apiFetch(`/tools/transcribe?duration_ms=${durationMs}&language=ru`, { method: 'POST', body: form })
          const payload = await response.json().catch(() => ({})) as { text?: string; detail?: unknown }
          if (!response.ok || !payload.text?.trim()) throw new Error(errorText(payload.detail, 'Не удалось распознать речь.'))
          const spoken = payload.text.trim()
          setPrompt((current) => `${current.trim()}${current.trim() ? ' ' : ''}${spoken}`.slice(0, 3000))
        } catch (reason) { setError(reason instanceof Error ? reason.message : 'Не удалось распознать речь.') }
        finally { setVoiceBusy(false) }
      }
      voiceStreamRef.current = stream; voiceRecorderRef.current = recorder; voiceStartedAtRef.current = Date.now()
      recorder.start(250); setVoiceRecording(true); setError('')
    } catch { setError('Разрешите доступ к микрофону в браузере.') }
  }

  useEffect(() => () => {
    if (voiceRecorderRef.current?.state === 'recording') voiceRecorderRef.current.stop()
    voiceStreamRef.current?.getTracks().forEach((track) => track.stop())
  }, [])

  const requestForModel = useCallback((model: VideoModel | undefined) => {
    if (!model) return null
    const nextDuration = model.supportedDurations.includes(duration) ? duration : (model.supportedDurations[0] || 4)
    const nextResolution = model.supportedResolutions.includes(resolution) ? resolution : (model.supportedResolutions[0] || '720p')
    const nextAspectRatio = model.supportedAspectRatios.includes(aspectRatio) ? aspectRatio : (model.supportedAspectRatios[0] || '16:9')
    return {
      mode,
      model: model.id,
      prompt: 'preview',
      duration: nextDuration,
      resolution: nextResolution,
      aspectRatio: nextAspectRatio,
      generateAudio: model.generateAudio !== false && generateAudio,
      firstFrame: firstFrame || null,
      lastFrame: lastFrame || null,
      references,
    }
  }, [aspectRatio, duration, firstFrame, generateAudio, lastFrame, mode, references, resolution])
  const estimateRequest = useMemo(() => requestForModel(selectedModel), [requestForModel, selectedModel])
  const estimateRequestKey = useMemo(() => estimateRequest ? JSON.stringify(estimateRequest) : '', [estimateRequest])
  const requestBody = useMemo(() => {
    const body = estimateRequest
    return body ? { ...body, prompt: prompt.trim() || 'preview' } : null
  }, [estimateRequest, prompt])
  useEffect(() => {
    if (!estimateRequest) return
    const requestKey = JSON.stringify(estimateRequest)
    const controller = new AbortController()
    const timer = window.setTimeout(async () => {
      setEstimateLoading(true)
      try {
        const response = await apiFetch('/video/estimate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(estimateRequest),
          signal: controller.signal,
        })
        if (!response.ok) {
          setEstimate(null)
          setEstimateKey(requestKey)
          return
        }
        const data = await response.json() as VideoEstimate
        setEstimate(Number(data.chargedTokens || 0) > 0 ? data : null)
        setEstimateKey(requestKey)
      } catch (reason) {
        if (!(reason instanceof DOMException && reason.name === 'AbortError')) {
          setEstimate(null)
          setEstimateKey(requestKey)
        }
      } finally {
        if (!controller.signal.aborted) setEstimateLoading(false)
      }
    }, 250)
    return () => { window.clearTimeout(timer); controller.abort() }
  }, [estimateRequest])
  useEffect(() => {
    const controller = new AbortController()
    const timer = window.setTimeout(async () => {
      const entries = await Promise.all(QUALITY_META.map(async (item) => {
        const body = requestForModel(qualityChoices[item.id])
        if (!body) return [item.id, null] as const
        try {
          const response = await apiFetch('/video/estimate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
            signal: controller.signal,
          })
          if (!response.ok) return [item.id, null] as const
          const data = await response.json() as VideoEstimate
          return [item.id, Number(data.chargedTokens || 0) > 0 ? data : null] as const
        } catch {
          return [item.id, null] as const
        }
      }))
      if (!controller.signal.aborted) setQualityEstimates(Object.fromEntries(entries.filter((entry) => entry[1])) as Partial<Record<VideoQuality, VideoEstimate>>)
    }, 320)
    return () => { window.clearTimeout(timer); controller.abort() }
  }, [qualityChoices, requestForModel])
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
    setSubmitting(true); setError(''); setPreviewCleared(false)
    try {
      const response = await apiFetch('/video/generate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(requestBody) })
      if (!response.ok) throw new Error(await responseError(response, 'Не удалось запустить видео.'))
      const data = await response.json() as VideoJob
      const job = { ...data, mode, prompt, createdAt: new Date().toISOString(), model: modelId, duration, resolution, aspectRatio, generateAudio }
      setActiveJob(job); setSelectedJob(job); await loadHistory()
    } catch (reason) { setError((reason as Error).message) } finally { setSubmitting(false) }
  }
  const deleteVideo = async (job: VideoJob) => {
    if (!job.galleryVideoId || !window.confirm('Удалить видео из галереи и хранилища? Файл будет удалён без восстановления.')) return
    const response = await apiFetch(`/gallery/videos/${encodeURIComponent(job.galleryVideoId)}`, { method: 'DELETE' })
    if (!response.ok) { setError(await responseError(response, 'Не удалось удалить видео.')); return }
    setHistory((items) => items.filter((item) => item.id !== job.id)); setSelectedJob(null); setPreviewCleared(true); setMenuOpen(false)
  }
  const clearPreview = () => { setSelectedJob(null); setPreviewCleared(true); setMenuOpen(false) }
  const copyVideoLink = async (job: VideoJob) => {
    const url = new URL(job.videoUrl || '', window.location.origin).toString()
    await navigator.clipboard.writeText(url)
    setNotice('Ссылка на видео скопирована.')
    setShareOpen(false)
  }
  const shareVideo = async (job: VideoJob) => {
    const url = new URL(job.videoUrl || '', window.location.origin).toString()
    try {
      const response = await fetch(url, { credentials: 'include' })
      if (!response.ok) throw new Error('Не удалось подготовить видео для отправки.')
      const blob = await response.blob()
      const file = new File([blob], `izo-asa-${job.id}.mp4`, { type: blob.type || 'video/mp4' })
      if (navigator.share && (!navigator.canShare || navigator.canShare({ files: [file] }))) {
        await navigator.share({ title: 'Видео ИЗО АСА', text: job.prompt, files: [file] })
      } else if (navigator.share) {
        await navigator.share({ title: 'Видео ИЗО АСА', text: job.prompt, url })
      } else {
        await navigator.clipboard.writeText(url)
        setNotice('Ссылка на видео скопирована.')
      }
    } catch (reason) {
      if (reason instanceof DOMException && reason.name === 'AbortError') return
      setError(reason instanceof Error ? reason.message : 'Не удалось поделиться видео.')
    } finally {
      setShareOpen(false)
    }
  }
  const openVideoPublish = (job: VideoJob) => {
    setShareOpen(false)
    if (job.published && job.publicationId) {
      window.location.href = `/feed#work-${encodeURIComponent(job.publicationId)}`
      return
    }
    if (job.publicationStatus === 'preparing') {
      setNotice('Видео уже готовится к публикации.')
      return
    }
    if (!config?.feedPublicationEnabled || !job.galleryVideoId) {
      setNotice(job.galleryVideoId ? 'Публикация видео временно недоступна.' : 'Дождитесь сохранения видео в галерею.')
      return
    }
    setPublishTitle('')
    setPublishDescription('')
    setPublishVisibility('open')
    setPublishCategory('other')
    setPublishTags('')
    setPublishJob(job)
  }
  const submitVideoPublish = async () => {
    if (!publishJob?.galleryVideoId || publishBusy) return
    const title = publishTitle.trim()
    if (!title) { setNotice('Укажите название публикации.'); return }
    setPublishBusy(true); setError('')
    try {
      const response = await apiFetch('/feed/publications', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          videoId: publishJob.galleryVideoId,
          title,
          description: publishDescription.trim(),
          promptVisibility: publishVisibility,
          allowRecreate: false,
          category: publishCategory,
          tags: publishTags.split(',').map((item) => item.trim()).filter(Boolean).slice(0, 8),
        }),
      })
      if (!response.ok) throw new Error(await responseError(response, 'Не удалось опубликовать видео.'))
      const data = await response.json() as { publication?: { id?: string; status?: VideoJob['publicationStatus'] } }
      const publicationId = data.publication?.id || null
      const publicationStatus = data.publication?.status || 'preparing'
      const applyPublication = (item: VideoJob) => item.id === publishJob.id
        ? { ...item, publicationId, publicationStatus, published: publicationStatus === 'published' }
        : item
      setHistory((items) => items.map(applyPublication))
      setSelectedJob((item) => item ? applyPublication(item) : item)
      setPublishJob(null)
      setNotice(publicationStatus === 'published' ? 'Видео опубликовано в ленту.' : 'Видео готовится к публикации. Можно продолжать работу.')
      await loadHistory()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Не удалось опубликовать видео.')
    } finally {
      setPublishBusy(false)
    }
  }
  const applySettings = (job: VideoJob) => {
    setMode(job.mode); setPrompt(job.prompt || ''); setDuration(Number(job.duration || duration)); setResolution(job.resolution || resolution); setAspectRatio(job.aspectRatio || aspectRatio); setGenerateAudio(Boolean(job.generateAudio));
    setPreviewCleared(false)
    const candidates = config?.modes[job.mode] || []; syncModelDefaults(candidates.find((item) => item.id === job.model) || candidates[0])
    window.setTimeout(() => {
      if (window.matchMedia('(max-width: 820px)').matches) document.querySelector('.video-composer')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
      else promptTextareaRef.current?.focus()
    }, 0)
  }

  const sourceCard = (target: FrameKey, value: string, title: string, note: string, index = -1) => (
    <div key={`${target}-${index}-${title}`} className={`video-source${value ? ' filled' : ' clickable'}`} role={!value ? 'button' : undefined} tabIndex={!value ? 0 : undefined} onClick={!value ? () => openUpload(target) : undefined} onKeyDown={!value ? (event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); openUpload(target) } } : undefined} onDragOver={(event) => event.preventDefault()} onDrop={(event) => void handleDrop(target, event)}>
      {value ? <img src={value} alt={title} /> : <ImagePlus aria-hidden="true" />}
      <div><strong>{title}</strong><span>{value ? 'Кадр добавлен' : note}</span></div>
      <div className="video-source-actions">
        <button type="button" onClick={(event) => { event.stopPropagation(); openUpload(target) }} title="Загрузить с устройства"><Upload /><span>Загрузить</span></button>
        <button type="button" onClick={(event) => { event.stopPropagation(); void openGallery(target) }} title="Выбрать из галереи"><Images /><span>Галерея</span></button>
        {value && <button type="button" onClick={(event) => { event.stopPropagation(); removeImage(target, index) }} title="Убрать"><X /></button>}
      </div>
    </div>
  )

  const sourceInputs = (placement: 'desktop' | 'mobile') => mode !== 'text_to_video' ? <section className={`video-inputs video-${placement}-inputs`}><h2>Исходные материалы</h2>
    {mode === 'image_to_video' && sourceCard('first', firstFrame, 'Исходный кадр', 'Фото, которое нужно оживить')}
    {mode === 'first_last_frame' && <div className="video-input-pair">{sourceCard('first', firstFrame, 'Начало', 'Первый кадр')}{sourceCard('last', lastFrame, 'Конец', 'Последний кадр')}</div>}
    {mode === 'reference_to_video' && <div className="video-reference-inputs">{references.map((value, index) => sourceCard('reference', value, `Референс ${index + 1}`, '', index))}{references.length < 4 && sourceCard('reference', '', 'Добавить референс', 'До четырёх изображений')}</div>}
  </section> : null

  const shownJob = previewCleared ? null : selectedJob || activeJob
  const modeMeta = MODE_META.find((item) => item.id === mode) || MODE_META[0]
  const stageRatio = shownJob?.aspectRatio || aspectRatio
  const orderedAspectRatios = useMemo(() => {
    const ratios = selectedModel?.supportedAspectRatios || []
    return [...ratios].sort((a, b) => {
      const aIndex = PRIMARY_ASPECT_RATIOS.indexOf(a)
      const bIndex = PRIMARY_ASPECT_RATIOS.indexOf(b)
      return (aIndex < 0 ? 99 : aIndex) - (bIndex < 0 ? 99 : bIndex)
    })
  }, [selectedModel])
  const primaryAspectRatios = useMemo(() => {
    const first = orderedAspectRatios.slice(0, 4)
    if (first.includes(aspectRatio) || !orderedAspectRatios.includes(aspectRatio)) return first
    return [...first.slice(0, 3), aspectRatio]
  }, [aspectRatio, orderedAspectRatios])
  const visibleAspectRatios = formatExpanded ? orderedAspectRatios : primaryAspectRatios
  const visibleEstimate = estimateKey === estimateRequestKey ? estimate : null
  const visibleEstimateLoading = Boolean(estimateRequest && (estimateLoading || estimateKey !== estimateRequestKey))
  const currentRate = visibleEstimate && duration > 0 ? visibleEstimate.chargedTokens / duration : null
  const shownElapsed = formatElapsed(shownJob?.createdAt, shownJob?.completedAt, clockNow)
  const findJobModel = (job: VideoJob) => config?.modes[job.mode]?.find((item) => item.id === job.model)

  return <main className="video-studio">
    {publishJob && <div className="video-publish-overlay" role="dialog" aria-modal="true" aria-labelledby="video-publish-title" onClick={() => !publishBusy && setPublishJob(null)}><div className="video-publish-dialog" onClick={(event) => event.stopPropagation()}>
      <header><div><Sparkles /><div><span>Публичная карточка</span><h2 id="video-publish-title">Опубликовать видео в ленту</h2></div></div><button type="button" aria-label="Закрыть" disabled={publishBusy} onClick={() => setPublishJob(null)}><X /></button></header>
      {publishJob.videoUrl && <video src={publishJob.videoUrl} muted playsInline preload="metadata" />}
      <label><span>Название публикации</span><input value={publishTitle} maxLength={120} autoFocus onChange={(event) => setPublishTitle(event.target.value)} /></label>
      <label><span>Описание</span><textarea value={publishDescription} maxLength={700} rows={3} placeholder="Коротко расскажите о работе" onChange={(event) => setPublishDescription(event.target.value)} /></label>
      <div className="video-publish-grid">
        <label><span>Промпт</span><select value={publishVisibility} onChange={(event) => setPublishVisibility(event.target.value as 'open' | 'partial' | 'hidden')}><option value="open">Показывать полностью</option><option value="partial">Показывать частично</option><option value="hidden">Скрыть</option></select></label>
        <label><span>Категория</span><select value={publishCategory} onChange={(event) => setPublishCategory(event.target.value)}><option value="art">Искусство</option><option value="photo">Фото</option><option value="design">Дизайн</option><option value="character">Персонаж</option><option value="product">Продукт</option><option value="architecture">Архитектура</option><option value="other">Другое</option></select></label>
      </div>
      <label><span>Теги</span><input value={publishTags} maxLength={200} placeholder="кино, движение, неон" onChange={(event) => setPublishTags(event.target.value)} /></label>
      <p>Для ленты будет создана отдельная сжатая копия. Приватный оригинал в галерее не изменится.</p>
      <footer><button type="button" disabled={publishBusy} onClick={() => setPublishJob(null)}>Отмена</button><button className="primary" type="button" disabled={publishBusy || !publishTitle.trim()} onClick={() => void submitVideoPublish()}>{publishBusy ? <LoaderCircle className="spin" /> : <Sparkles />} Опубликовать</button></footer>
    </div></div>}
    <input ref={fileRef} type="file" accept="image/png,image/jpeg,image/webp" hidden onChange={(event) => void handleFile(event)} />
    <section className="video-shell">
      <aside className="video-composer" aria-label="Настройки видеогенерации">
        <div className="video-composer-scroll">
          <header className="video-composer-title">
            <h1>Генерация видео</h1>
            {config?.videoStorage && <span title="Одновременно хранимые ролики в вашей галерее">{config.videoStorage.used} / {config.videoStorage.limit} в галерее</span>}
          </header>
          <div className="video-mode-tabs" role="tablist" aria-label="Способ создания">
            {MODE_META.map((item) => <button key={item.id} type="button" role="tab" aria-selected={mode === item.id} className={mode === item.id ? 'active' : ''} onClick={() => selectMode(item.id)}><strong>{item.label}</strong><small>{item.note}</small></button>)}
          </div>

          {loading ? <div className="video-loading"><LoaderCircle className="spin" /> Загружаем модели</div> : models.length ? <>
          {sourceInputs('desktop')}

          <section className="video-prompt">
            <div className="video-prompt-heading">
              <b>Что происходит в кадре?</b>
              <div className="video-prompt-heading-controls">
                <label className="video-duration-control" title="Длительность видео">
                  <Clock3 aria-hidden="true" />
                  <select aria-label="Длительность видео" value={duration} onChange={(event) => setDuration(Number(event.target.value))}>{selectedModel?.supportedDurations.map((value) => <option key={value} value={value}>{value} сек.</option>)}</select>
                </label>
                <button className="video-guide-button" type="button" aria-label="Инструкция по созданию видео" onClick={() => setGuideOpen(true)}><CircleHelp aria-hidden="true" /></button>
              </div>
            </div>
            <div className="video-prompt-field">
              <textarea ref={promptTextareaRef} value={prompt} maxLength={3000} placeholder="Опишите сцену, действия, движение камеры и атмосферу" onChange={(event) => { setPrompt(event.target.value); setLastImprovedPrompt('') }} />
              <small>{prompt.length} / 3000</small>
              {prompt && <button className="video-prompt-clear" type="button" title="Очистить промпт" aria-label="Очистить промпт" onClick={() => { setPrompt(''); setLastImprovedPrompt(''); promptTextareaRef.current?.focus() }}><X /></button>}
            </div>
          </section>
          <div className="video-prompt-actions">
            <button type="button" className={voiceRecording ? 'recording' : ''} disabled={voiceBusy} aria-pressed={voiceRecording} onClick={() => void toggleVoiceInput()}>{voiceRecording && <i aria-hidden="true" />}<Mic2 /> {voiceBusy ? 'Распознаю…' : voiceRecording ? 'Стоп' : 'Голос'}</button>
            <button type="button" disabled={!prompt.trim() || improveBusy || lastImprovedPrompt === prompt} onClick={() => void improvePrompt()}><WandSparkles /> {improveBusy ? 'Улучшаю…' : lastImprovedPrompt === prompt ? 'Улучшено' : 'Улучшить'}</button>
            <button type="button" title="Показать следующий пример сцены" onClick={useNextExample}><Sparkles /> Пример</button>
          </div>
          <section className={`video-audio-row${selectedModel?.generateAudio === false ? ' disabled' : ''}`} aria-label="Звук в ролике">
            <div className="video-audio-summary">
              {generateAudio && selectedModel?.generateAudio !== false ? <Volume2 /> : <VolumeX />}
              <span><b>Звук в ролике</b><small>{selectedModel?.generateAudio === false ? 'Эта модель не поддерживает звук' : `Создаёт ${shortModelName(selectedModel)} вместе с видео`}</small></span>
            </div>
              <label className="video-audio-switch">
                <input type="checkbox" checked={generateAudio && selectedModel?.generateAudio !== false} disabled={selectedModel?.generateAudio === false} onChange={(event) => setGenerateAudio(event.target.checked)} />
                <i />
                <span>{selectedModel?.generateAudio === false ? 'Недоступно' : generateAudio ? 'Включён' : 'Выключен'}</span>
              </label>
            <div className="video-live-price" aria-live="polite">
              <strong>{visibleEstimateLoading ? 'Считаем…' : visibleEstimate ? `${visibleEstimate.chargedTokens} ток. за ${duration} сек.` : '—'}</strong>
              <small>{currentRate ? `≈ ${formatTokenRate(currentRate)} ток./с` : 'текущая цена'}</small>
            </div>
          </section>

          <section className="video-settings-section video-visual-settings">
            <div className="video-setting-label"><span>Формат</span></div>
            <div className="video-format-tabs">{visibleAspectRatios.map((value) => <button key={value} type="button" className={aspectRatio === value ? 'active' : ''} onClick={() => setAspectRatio(value)} title={`Формат ${value} · качество ${resolution}`}><i style={{ aspectRatio: aspectStyle(value), width: aspectPreviewWidth(value) }} /><span>{value}</span></button>)}</div>
            {orderedAspectRatios.length > 4 && <button className="video-format-more" type="button" aria-expanded={formatExpanded} onClick={() => setFormatExpanded((value) => !value)}><span>{formatExpanded ? 'Скрыть дополнительные форматы' : `Ещё форматы (${orderedAspectRatios.length - 4})`}</span><ChevronDown className={formatExpanded ? 'open' : ''} /></button>}
          </section>

          <section className="video-params">
            <div className="video-setting-label"><span>Качество</span></div>
            <div className="video-resolution-tabs">{selectedModel?.supportedResolutions.map((value) => <button key={value} type="button" className={resolution === value ? 'active' : ''} onClick={() => setResolution(value)} title={`Качество ${value} · формат ${aspectRatio}`}>{value}</button>)}</div>
            <h2>Модель</h2>
            <div className="video-quality-tabs">{QUALITY_META.map((item) => {
              const presetModel = qualityChoices[item.id]
              const presetEstimate = qualityEstimates[item.id]
              const presetDuration = presetModel?.supportedDurations.includes(duration) ? duration : (presetModel?.supportedDurations[0] || duration)
              const presetRate = presetEstimate && presetDuration > 0 ? presetEstimate.chargedTokens / presetDuration : null
              return <button type="button" key={item.id} className={quality === item.id && selectedModel?.id === presetModel?.id ? 'active' : ''} onClick={() => selectQuality(item.id)}>
                <span><strong>{item.label}</strong><b>{presetRate ? `≈ ${formatTokenRate(presetRate)} ток./с` : 'Считаем…'}</b></span>
                <small>{shortModelName(presetModel)}</small>
                <em>{presetEstimate ? `${presetEstimate.chargedTokens} ток. за ${presetDuration} сек.` : 'Цена уточняется'}</em>
              </button>
            })}</div>
            <button type="button" className="video-pro" onClick={() => setProOpen((value) => !value)}><Settings2 /><span><b>Выбрать модель</b><small>{shortModelName(selectedModel)} · {publicModelRate(selectedModel)}</small></span><ChevronDown className={proOpen ? 'open' : ''} /></button>
            {proOpen && <div className="video-model-list">{models.map((model) => <button key={model.id} type="button" className={selectedModel?.id === model.id ? 'active' : ''} onClick={() => syncModelDefaults(model)}><span><strong>{model.name}</strong><b>{publicModelRate(model)}</b></span><p>{model.description || 'Описание модели пока не опубликовано.'}</p><small>{model.supportedResolutions.join(', ')} · {model.supportedDurations.join(', ')} сек.</small></button>)}</div>}
          </section>
          {notice && <div className="video-notice">{notice}</div>}
          {error && <div className="video-error">{error}</div>}
        </> : <div className="video-empty-models">{error || config?.availability?.[mode]?.reason || 'Для этого режима пока нет доступных моделей.'}</div>}
        </div>
        {!loading && <button className="video-generate" type="button" disabled={!canSubmit} onClick={() => void submit()}>{submitting || activeJob ? <LoaderCircle className="spin" /> : <Sparkles />}<span>{activeJob ? 'Генерация идёт' : 'Создать видео'}</span><b>{visibleEstimateLoading ? 'Считаем…' : visibleEstimate ? `${visibleEstimate.chargedTokens} ток.` : models.length ? '—' : 'Нет модели'}</b></button>}
      </aside>

      <section className="video-result">
        <section className="video-mobile-mode" aria-label="Способ создания видео">
          <button className="video-mobile-mode-trigger" type="button" aria-expanded={mobileModeOpen} onClick={() => setMobileModeOpen((value) => !value)}>
            <span><b>{modeMeta.label}</b><em>{modeMeta.note}</em></span>
            <ChevronDown className={mobileModeOpen ? 'open' : ''} />
          </button>
          {mobileModeOpen && <div className="video-mobile-mode-menu" role="listbox">{MODE_META.map((item) => <button key={item.id} type="button" role="option" aria-selected={mode === item.id} className={mode === item.id ? 'active' : ''} onClick={() => selectMode(item.id)}><strong>{item.label}</strong><small>{item.note}</small></button>)}</div>}
        </section>
        {sourceInputs('mobile')}
        <div className="video-stage-wrap"><div className="video-stage" style={{ aspectRatio: aspectStyle(stageRatio) }}>
          <div className="video-stage-overlay">
            <div className="video-stage-actions">
              {shownJob?.videoUrl && <a href={shownJob.videoUrl} download title="Скачать"><Download /> <span>Скачать</span></a>}
              {shownJob?.videoUrl && <div className="video-share"><button type="button" aria-expanded={shareOpen} onClick={() => setShareOpen((value) => !value)}><Share2 /> <span>Поделиться</span></button>{shareOpen && <div className="video-share-menu">
                <button type="button" onClick={() => openVideoPublish(shownJob)}><Sparkles /> {shownJob.published ? 'Открыть в ленте' : shownJob.publicationStatus === 'preparing' ? 'Готовим публикацию' : 'В ленту'}</button>
                <button type="button" onClick={() => void shareVideo(shownJob)}><Share2 /> Поделиться через устройство</button>
                <button type="button" onClick={() => void copyVideoLink(shownJob)}><Copy /> Копировать ссылку</button>
              </div>}</div>}
              {shownJob && <div className="video-more"><button type="button" title="Другие действия" onClick={() => setMenuOpen((value) => !value)}><MoreVertical /></button>{menuOpen && <div><button type="button" onClick={clearPreview}><X /> Очистить предпросмотр</button>{shownJob.galleryVideoId && <button className="destructive" type="button" onClick={() => void deleteVideo(shownJob)}><Trash2 /> Удалить из галереи</button>}</div>}</div>}
            </div>
          </div>
          {shownJob?.status === 'completed' && shownJob.videoUrl ? <video key={shownJob.videoUrl} src={shownJob.videoUrl} controls playsInline preload="metadata" />
            : shownJob && !['failed', 'cancelled', 'expired'].includes(shownJob.status) ? <div className="video-progress"><Film /><strong>{statusLabel(shownJob.status)}</strong><p>Прошло {shownElapsed || 'несколько секунд'}. Ролик сохранится в истории и галерее.</p><div><i style={{ width: `${Math.max(8, shownJob.progress || 10)}%` }} /></div><small>{shownJob.progress || 10}%</small></div>
            : shownJob?.error ? <div className="video-stage-message error"><RotateCcw /><strong>Видео не создано</strong><p>{shownJob.error}</p><button type="button" onClick={() => setSelectedJob(null)}>Попробовать снова</button></div>
            : <div className="video-stage-message"><Play /><strong>{modeMeta.empty}</strong><p>Выберите параметры и создайте видео</p></div>}
        </div></div>
      </section>

        <div className="video-result-shelf">
          <section className="video-history" aria-label="Предыдущие видео">
            {history.length ? <div className="video-history-list">{history.map((job) => { const jobModel = findJobModel(job); const elapsed = formatElapsed(job.createdAt, job.completedAt); return <button key={job.id} type="button" className={!previewCleared && selectedJob?.id === job.id ? 'active' : ''} onClick={() => { setSelectedJob(job); setPreviewCleared(false) }} style={{ aspectRatio: aspectStyle(job.aspectRatio) }} title={`${shortModelName(jobModel)} · ${job.duration || 0} сек.${elapsed ? ` · готово за ${elapsed}` : ''}`}>{job.videoUrl ? <video src={job.videoUrl} muted preload="metadata" /> : <span>{job.status === 'completed' ? <Play /> : <LoaderCircle className="spin" />}</span>}<span className="video-history-meta"><small>{job.duration || 0} сек.</small><em>{shortModelName(jobModel)}</em></span></button> })}</div> : <p>Здесь появятся созданные видео.</p>}
          </section>
          <aside className="video-context">{shownJob ? <>
            <div className="video-context-prompt"><div><span>Промпт</span><button type="button" title="Копировать промпт" aria-label="Копировать промпт" onClick={() => void navigator.clipboard.writeText(shownJob.prompt || '')}><Copy /></button></div><p>{shownJob.prompt || 'Промпт не сохранён'}</p></div>
            <div className="video-context-details">
              <div className="video-context-tags"><span>{shortModelName(findJobModel(shownJob))}</span><span>{shownJob.duration} сек.</span><span>{shownJob.aspectRatio}</span><span>{shownJob.resolution}</span>{shownJob.generateAudio && <span><Volume2 /> Звук</span>}{shownElapsed && shownJob.completedAt && <span><Clock3 /> Готово за {shownElapsed}</span>}</div>
              <div className="video-context-actions">
                <button className="feed" type="button" disabled={!shownJob.galleryVideoId || shownJob.publicationStatus === 'preparing'} onClick={() => openVideoPublish(shownJob)}><Sparkles /> <span>{shownJob.published ? 'Открыть в ленте' : shownJob.publicationStatus === 'preparing' ? 'Готовим' : 'В ленту'}</span></button>
                <button className="icon" type="button" title="Повторить с этими настройками" aria-label="Повторить с этими настройками" onClick={() => applySettings(shownJob)}><RotateCcw /></button>
              </div>
            </div>
          </> : <p>Выберите видео, чтобы увидеть его параметры.</p>}</aside>
        </div>
    </section>

    {guideOpen && <div className="video-guide-overlay" role="dialog" aria-modal="true" aria-labelledby="video-guide-title" onClick={() => setGuideOpen(false)}><div className="video-guide-dialog" onClick={(event) => event.stopPropagation()}><header><div><Film /><div><span>Краткая инструкция</span><h2 id="video-guide-title">Как создать первое видео</h2></div></div><button type="button" aria-label="Закрыть инструкцию" onClick={() => setGuideOpen(false)}><X /></button></header><ol><li><b>Выберите способ создания.</b><span>Сцену можно описать текстом, оживить изображение, связать первый и последний кадр или использовать несколько референсов.</span></li><li><b>Добавьте исходники, если они нужны.</b><span>Нажмите на всю область загрузки, выберите файл с устройства или изображение из галереи.</span></li><li><b>Опишите движение.</b><span>Укажите, что делает объект, как движется камера, какой нужен свет, темп и атмосфера. Не перечисляйте лишние изменения.</span></li><li><b>Настройте ролик.</b><span>Выберите длительность, звук, формат, качество и модель. Итоговая цена в токенах пересчитывается сервером.</span></li><li><b>Создайте видео.</b><span>Ход генерации появится в предосмотре. Готовый ролик автоматически сохранится в истории и галерее.</span></li></ol><footer><button type="button" onClick={() => setGuideOpen(false)}>Понятно</button></footer></div></div>}
    {galleryOpen && <div className="video-gallery-overlay" role="dialog" aria-modal="true" aria-label="Выбор изображения" onClick={() => setGalleryOpen(null)}><div className="video-gallery-dialog" onClick={(event) => event.stopPropagation()}><header><div><Images /><h2>Выберите изображение</h2></div><button type="button" aria-label="Закрыть" onClick={() => setGalleryOpen(null)}><X /></button></header>{galleryLoading ? <div className="video-loading"><LoaderCircle className="spin" /> Загружаем галерею</div> : gallery.length ? <div className="video-gallery-grid">{gallery.map((item) => { const source = item.url || item.viewerSrc || item.src || item.thumbnailUrl || ''; return <button key={item.id} type="button" disabled={!source} onClick={() => { assignImage(galleryOpen, source); setGalleryOpen(null) }}><img src={item.thumbnailUrl || item.src || source} alt={item.promptOriginal || 'Изображение из галереи'} loading="lazy" /><span>{item.width && item.height ? `${item.width}×${item.height}` : 'Из галереи'}</span></button> })}</div> : <p>В галерее пока нет изображений.</p>}</div></div>}
  </main>
}
