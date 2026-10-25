import { useEffect, useMemo, useRef, useState } from 'react'
import { Download, Film, ImagePlus, Play, Send, Share2, Sparkles, Volume2, VolumeX, X } from 'lucide-react'

import { phoneTokenClass } from '../../core/billing.ts'
import { waitForPhoneJob } from '../../core/jobs.ts'
import { readPhoneDraft, writePhoneDraft } from '../../core/accountDraft.ts'
import { estimatePhoneVideo, fileToPhoneVideoFrame, loadPhoneVideoConfig, loadPhoneVideoGalleryFrames, loadPhoneVideoHistory, publishPhoneVideo, startPhoneVideo, type PhoneVideoConfig, type PhoneVideoGalleryFrame, type PhoneVideoHistoryItem, type PhoneVideoMode, type PhoneVideoModel, type PhoneVideoRequest } from './api.ts'
import './phoneVideo.css'

const modes: Array<{ id: PhoneVideoMode; label: string; note: string }> = [
  { id: 'text_to_video', label: 'Текст → видео', note: 'Сцена по описанию' },
  { id: 'image_to_video', label: 'Изображение → видео', note: 'Оживить кадр' },
  { id: 'first_last_frame', label: 'Начало и конец', note: 'Плавный переход' },
  { id: 'reference_to_video', label: 'По референсам', note: 'Собрать ролик' },
]
const aspectOptions = ['16:9', '9:16', '1:1', '4:3', '3:2']
const resolutionOptions = ['480p', '720p', '1080p', '4K']
const terminal = new Set(['completed', 'failed', 'cancelled', 'expired'])

function elapsedLabel(started: number, ended?: string | null) {
  const seconds = Math.max(0, Math.round(((ended ? Date.parse(ended) : Date.now()) - started) / 1000))
  const minutes = Math.floor(seconds / 60)
  return minutes ? `${minutes} мин. ${seconds % 60} сек.` : `${seconds} сек.`
}

function modelDescription(model: PhoneVideoModel | undefined) {
  if (!model) return 'Выберите доступную модель.'
  if (/[А-Яа-яЁё]/.test(model.description || '')) return model.description
  const key = `${model.id} ${model.name}`.toLowerCase()
  if (key.includes('seedance')) return 'Быстро создаёт плавные ролики из текста и изображений.'
  if (key.includes('sora')) return 'Подходит для сложного движения и кинематографичных сцен.'
  if (key.includes('veo')) return 'Реалистичные сцены и звук, если он доступен в режиме.'
  if (key.includes('ltx') || key.includes('local')) return 'Локальная модель для коротких черновых роликов.'
  return 'Создаёт видео по описанию и выбранным исходным кадрам.'
}

function SourcePicker({ label, value, onPick, onClear }: { label: string; value?: string; onPick: () => void; onClear: () => void }) {
  return <div className="phone-video-source">{value ? <><img src={value} alt={label} /><button type="button" onClick={onClear} aria-label={`Убрать: ${label}`}><X /></button></> : <button type="button" onClick={onPick}><ImagePlus /><b>{label}</b></button>}</div>
}

export default function PhoneVideoWorkspace({ offline, ownerId }: { offline: boolean; ownerId: string }) {
  const handoff = readPhoneDraft('video.source', ownerId)
  const [mode, setMode] = useState<PhoneVideoMode>(handoff ? 'image_to_video' : 'text_to_video')
  const [config, setConfig] = useState<PhoneVideoConfig | null>(null)
  const [modelId, setModelId] = useState('')
  const [prompt, setPrompt] = useState(() => readPhoneDraft('video.prompt', ownerId))
  const [duration, setDuration] = useState(4)
  const [resolution, setResolution] = useState('480p')
  const [aspectRatio, setAspectRatio] = useState('16:9')
  const [audio, setAudio] = useState(false)
  const [firstFrame, setFirstFrame] = useState(handoff)
  const [lastFrame, setLastFrame] = useState('')
  const [references, setReferences] = useState<string[]>([])
  const [uploadTarget, setUploadTarget] = useState<'first' | 'last' | 'reference'>('first')
  const [estimate, setEstimate] = useState(0)
  const [history, setHistory] = useState<PhoneVideoHistoryItem[]>([])
  const [galleryFrames, setGalleryFrames] = useState<PhoneVideoGalleryFrame[]>([])
  const [selected, setSelected] = useState<PhoneVideoHistoryItem | null>(null)
  const [busy, setBusy] = useState(false)
  const [progress, setProgress] = useState(0)
  const [startedAt, setStartedAt] = useState(0)
  const [, tick] = useState(0)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)
  const jobObserver = useRef<AbortController | null>(null)

  const models = useMemo(() => config?.modes?.[mode] || [], [config, mode])
  const model = models.find((item) => item.id === modelId) || models.find((item) => item.available !== false) || models[0]
  const buildRequest = (): PhoneVideoRequest | null => model && model.available !== false ? { mode, model: model.id, prompt: prompt.trim() || 'Короткая естественная сцена.', duration, resolution, aspectRatio, generateAudio: model.generateAudio !== false && audio, firstFrame: firstFrame || null, lastFrame: lastFrame || null, references } : null

  const applyModel = (value: PhoneVideoModel | undefined) => {
    if (!value) return
    setModelId(value.id); setDuration(value.supportedDurations.includes(duration) ? duration : value.supportedDurations[0] || 4); setResolution(value.supportedResolutions.includes(resolution) ? resolution : value.supportedResolutions[0] || '480p'); setAspectRatio(value.supportedAspectRatios.includes(aspectRatio) ? aspectRatio : value.supportedAspectRatios[0] || '16:9'); if (value.generateAudio === false) setAudio(false)
  }

  async function startWaiting(jobId: string, signal: AbortSignal) {
    try {
      const job = await waitForPhoneJob(jobId, { signal, intervalMs: 1800, onChange: (value) => setProgress(value.progress) })
      const items = await loadPhoneVideoHistory(signal)
      signal.throwIfAborted()
      setHistory(items); const row = items.find((item) => item.id === job.id) || null; setSelected(row)
      if (job.status !== 'completed') throw new Error(job.message || 'Видео не создано.')
    } catch (caught) { if (!signal.aborted) setError(caught instanceof Error ? caught.message : 'Видео не создано.') }
    finally { if (!signal.aborted) setBusy(false) }
  }

  useEffect(() => {
    const controller = new AbortController()
    jobObserver.current = controller
    void Promise.all([loadPhoneVideoConfig(controller.signal), loadPhoneVideoHistory(controller.signal), loadPhoneVideoGalleryFrames(controller.signal)]).then(([nextConfig, items, frames]) => {
      controller.signal.throwIfAborted()
      setConfig(nextConfig); const firstModel = nextConfig.modes?.[mode]?.find((item) => item.available !== false) || nextConfig.modes?.[mode]?.[0]; applyModel(firstModel); setHistory(items); setGalleryFrames(frames); setSelected(items.find((item) => item.status === 'completed') || null)
      const active = items.find((item) => !terminal.has(item.status))
      if (active) { setBusy(true); setProgress(active.progress); setStartedAt(Date.parse(active.createdAt) || Date.now()); void startWaiting(active.id, controller.signal) }
    }).catch((caught) => { if (!controller.signal.aborted) setError(caught instanceof Error ? caught.message : 'Видео временно недоступно.') })
    return () => { controller.abort(); jobObserver.current?.abort(); jobObserver.current = null }
  // initial recovery is intentionally run once.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => { if (!busy || !startedAt) return; const timer = window.setInterval(() => tick((value) => value + 1), 1000); return () => window.clearInterval(timer) }, [busy, startedAt])
  useEffect(() => {
    const request = buildRequest()
    if (!request) return
    const controller = new AbortController(); const timer = window.setTimeout(() => void estimatePhoneVideo(request, controller.signal).then((value) => setEstimate(value.chargedTokens)).catch(() => setEstimate(0)), 250)
    return () => { window.clearTimeout(timer); controller.abort() }
  // estimation follows only the public request inputs.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, modelId, prompt, duration, resolution, aspectRatio, audio, firstFrame, lastFrame, references])

  const generate = async () => {
    const request = buildRequest()
    if (!request || busy || offline) return
    if (!prompt.trim()) { setError('Опишите движение и сцену.'); return }
    if (mode === 'image_to_video' && !firstFrame) { setError('Добавьте исходное изображение.'); return }
    if (mode === 'first_last_frame' && (!firstFrame || !lastFrame)) { setError('Добавьте начальный и конечный кадры.'); return }
    if (mode === 'reference_to_video' && !references.length) { setError('Добавьте хотя бы один референс.'); return }
    const controller = new AbortController()
    jobObserver.current?.abort(); jobObserver.current = controller
    try {
      setBusy(true); setError(''); setNotice(''); setProgress(5); setStartedAt(Date.now())
      const job = await startPhoneVideo(request, (value) => setProgress(value.progress), controller.signal)
      const items = await loadPhoneVideoHistory(controller.signal)
      controller.signal.throwIfAborted()
      setHistory(items); setSelected(items.find((item) => item.id === job.id) || null)
      if (job.status !== 'completed') throw new Error(job.message || 'Видео не создано.')
    } catch (caught) { if (!controller.signal.aborted) setError(caught instanceof Error ? caught.message : 'Видео временно недоступно.') }
    finally { if (!controller.signal.aborted) setBusy(false) }
  }

  const openUpload = (target: 'first' | 'last' | 'reference') => { setUploadTarget(target); fileRef.current?.click() }
  const chooseGalleryFrame = (url: string) => { if (mode === 'image_to_video') setFirstFrame(url); else if (mode === 'first_last_frame') { if (!firstFrame) setFirstFrame(url); else setLastFrame(url) } else if (mode === 'reference_to_video') setReferences((items) => [...items, url].slice(0, 4)) }
  const videoUrl = selected?.videoUrl || (selected?.status === 'completed' ? `/api/video/media/${encodeURIComponent(selected.id)}` : '')
  return <section className="phone-video" data-phone-workspace="video"><h1>Видео</h1><div className="phone-video-scroll">
    <div className="phone-video-preview">{videoUrl ? <><video key={videoUrl} src={videoUrl} controls playsInline preload="metadata" /><button type="button" className="dismiss" aria-label="Освободить предпросмотр" onClick={() => setSelected(null)}><X /></button><div className="actions"><a href={videoUrl} download aria-label="Скачать видео"><Download /></a><button type="button" aria-label="Поделиться видео" onClick={() => { const url = new URL(videoUrl, location.origin).toString(); if (navigator.share) void navigator.share({ title: 'ИЗО АСА', url }); else void navigator.clipboard?.writeText(url) }}><Share2 /></button><button type="button" aria-label="В ленту" disabled={!selected?.galleryVideoId} onClick={() => { if (!selected?.galleryVideoId) return; void publishPhoneVideo(selected.galleryVideoId, selected.prompt).then(() => setNotice('Видео отправлено в ленту.')).catch((caught) => setError(caught instanceof Error ? caught.message : 'Не удалось опубликовать видео.')) }}><Send /></button></div></> : <><img src="/phone-preview-placeholder.jpg" alt="" /><div><Film /><b>Создайте видео</b><span>Результат полностью поместится здесь</span></div></>}{busy && <div className="phone-video-busy"><Play /><b>Создаём видео</b><span>Прошло {elapsedLabel(startedAt)}</span><i style={{ width: `${Math.max(5, progress)}%` }} /></div>}</div>
    <div className="phone-video-modes">{modes.map((item) => <button type="button" className={mode === item.id ? 'active' : ''} key={item.id} onClick={() => { setMode(item.id); const candidates = config?.modes?.[item.id] || []; const next = candidates.find((candidate) => candidate.available !== false) || candidates[0]; if (next) applyModel(next) }}><b>{item.label}</b><span>{item.note}</span></button>)}</div>
    {mode !== 'text_to_video' && <><div className="phone-video-sources"><input ref={fileRef} hidden type="file" accept="image/jpeg,image/png,image/webp" onChange={async (event) => { const file = event.target.files?.[0]; event.target.value = ''; if (!file) return; try { const value = await fileToPhoneVideoFrame(file); if (uploadTarget === 'first') setFirstFrame(value); else if (uploadTarget === 'last') setLastFrame(value); else setReferences((items) => [...items, value].slice(0, 4)) } catch (caught) { setError(caught instanceof Error ? caught.message : 'Не удалось добавить изображение.') } }} />{mode === 'image_to_video' && <SourcePicker label="Исходный кадр" value={firstFrame} onPick={() => openUpload('first')} onClear={() => setFirstFrame('')} />}{mode === 'first_last_frame' && <><SourcePicker label="Начальный кадр" value={firstFrame} onPick={() => openUpload('first')} onClear={() => setFirstFrame('')} /><SourcePicker label="Конечный кадр" value={lastFrame} onPick={() => openUpload('last')} onClear={() => setLastFrame('')} /></>}{mode === 'reference_to_video' && <>{references.map((value, index) => <SourcePicker key={`${value.slice(-16)}-${index}`} label={`Референс ${index + 1}`} value={value} onPick={() => undefined} onClear={() => setReferences((items) => items.filter((_, itemIndex) => itemIndex !== index))} />)}{references.length < 4 && <SourcePicker label="Добавить референс" onPick={() => openUpload('reference')} onClear={() => undefined} />}</>}</div>{galleryFrames.length > 0 && <section className="phone-video-gallery-frames"><h2>Из галереи</h2><div>{galleryFrames.map((item) => <button type="button" key={item.id} style={{ aspectRatio: item.width > 0 && item.height > 0 ? `${item.width}/${item.height}` : '1' }} onClick={() => chooseGalleryFrame(item.url)}><img src={item.thumbnailUrl} alt="Использовать изображение из галереи" /></button>)}</div></section>}</>}
    <div className="phone-video-prompt"><textarea value={prompt} maxLength={3000} placeholder="Опишите сцену и движение камеры…" onChange={(event) => { setPrompt(event.target.value); writePhoneDraft('video.prompt', ownerId, event.target.value) }} /><button type="button" disabled={busy || offline || !model || model.available === false || !prompt.trim()} onClick={() => void generate()}><Sparkles />{busy ? 'Создаём…' : 'Создать видео'}<em className={phoneTokenClass(model?.provider === 'local_ltx' || model?.id.startsWith('local/ltx-') ? 'daily' : 'main')}>{estimate || model?.publicPricing?.fromTokens || 0} ток.</em></button></div>
    {model?.available === false && <div className="phone-video-message">{model.unavailableReason || 'Эта модель недоступна на вашем тарифе.'}</div>}
    {error && <div className="phone-video-message error">{error}<button type="button" onClick={() => setError('')} aria-label="Закрыть ошибку"><X /></button></div>}{notice && <div className="phone-video-message success">{notice}<button type="button" onClick={() => setNotice('')} aria-label="Закрыть уведомление"><X /></button></div>}
    <section className="phone-video-settings"><h2>Формат</h2><div>{aspectOptions.map((value) => <button type="button" disabled={!model?.supportedAspectRatios.includes(value)} className={aspectRatio === value ? 'active' : ''} key={value} onClick={() => setAspectRatio(value)}>{value}</button>)}</div><h2>Качество</h2><div>{resolutionOptions.map((value) => <button type="button" disabled={!model?.supportedResolutions.includes(value)} className={resolution.toLowerCase() === value.toLowerCase() ? 'active' : ''} key={value} onClick={() => setResolution(model?.supportedResolutions.find((item) => item.toLowerCase() === value.toLowerCase()) || value)}>{value}</button>)}</div><h2>Длительность</h2><div>{(model?.supportedDurations || []).map((value) => <button type="button" className={duration === value ? 'active' : ''} key={value} onClick={() => setDuration(value)}>{value} сек.</button>)}</div><label className="phone-video-audio"><span>{audio ? <Volume2 /> : <VolumeX />}<b>Звук в ролике</b></span><input type="checkbox" disabled={model?.generateAudio !== true} checked={audio} onChange={(event) => setAudio(event.target.checked)} /></label><label className="phone-video-model">Модель<select value={model?.id || ''} onChange={(event) => applyModel(models.find((item) => item.id === event.target.value))}>{models.map((item) => <option value={item.id} key={item.id} disabled={item.available === false}>{item.name}{item.available === false ? ' — недоступна' : ''}</option>)}</select><small>{modelDescription(model)}</small></label></section>
    {history.length > 0 && <section className="phone-video-history"><h2>История</h2><div>{history.map((item) => <button type="button" className={selected?.id === item.id ? 'active' : ''} key={item.id} onClick={() => setSelected(item)}><span style={{ aspectRatio: item.aspectRatio?.replace(':', '/') || '16/9' }}>{item.status === 'completed' ? <Play /> : <i>{Math.round(item.progress || 0)}%</i>}</span><b>{item.status === 'completed' ? 'Видео' : 'В работе'}</b><small>{item.completedAt ? elapsedLabel(Date.parse(item.createdAt), item.completedAt) : item.resolution || ''}</small></button>)}</div></section>}
  </div></section>
}
