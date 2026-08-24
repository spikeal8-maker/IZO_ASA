import { useEffect, useMemo, useRef, useState } from 'react'
import { Brush, Check, Download, Eraser, ImagePlus, Layers3, Pencil, Share2, Sparkles, Trash2, Undo2, Video, X } from 'lucide-react'

import { I2I_STYLES, T2I_TEMPLATES, styleShortLabel } from '../../../stylePresets.ts'
import { phoneTokenClass } from '../../core/billing.ts'
import { fileToPhoneImage, loadImageModels, loadPhoneGallery, startPhoneImage, type PhoneGalleryImage, type PhoneImageMode, type PhoneImageModel } from './api.ts'
import './phoneImage.css'


type Ratio = '1:1' | '9:16' | '16:9' | '3:2'
type Tier = 'SD' | 'HD' | 'Full HD' | '4K'

const sizes: Record<Ratio, Record<Tier, [string, number, number]>> = {
  '1:1': { SD: ['sq-sd', 704, 704], HD: ['sq-hd', 1024, 1024], 'Full HD': ['sq-fhd', 1408, 1408], '4K': ['sq-4k', 4096, 4096] },
  '16:9': { SD: ['h-sd', 1024, 576], HD: ['h-hd', 1280, 720], 'Full HD': ['h-fhd', 1792, 1008], '4K': ['h-4k', 3840, 2160] },
  '9:16': { SD: ['v-sd', 576, 1024], HD: ['v-hd', 720, 1280], 'Full HD': ['v-fhd', 1008, 1792], '4K': ['v-4k', 2160, 3840] },
  '3:2': { SD: ['p-sd', 960, 640], HD: ['p-hd', 1152, 768], 'Full HD': ['p-fhd', 1728, 1152], '4K': ['p-4k', 4096, 2736] },
}

function SketchCanvas({ ratio, onChange }: { ratio: Ratio; onChange: (value: string) => void }) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [tool, setTool] = useState<'brush' | 'eraser'>('brush')
  const [color, setColor] = useState('#181818')
  const [fullscreen, setFullscreen] = useState(false)
  const history = useRef<string[]>([])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const [rw, rh] = ratio.split(':').map(Number)
    canvas.width = Math.round(800 * rw / Math.max(rw, rh))
    canvas.height = Math.round(800 * rh / Math.max(rw, rh))
    const context = canvas.getContext('2d')
    if (!context) return
    context.fillStyle = '#fff'; context.fillRect(0, 0, canvas.width, canvas.height)
    onChange(canvas.toDataURL('image/png'))
  }, [ratio, onChange])

  useEffect(() => {
    const canvas = canvasRef.current
    const context = canvas?.getContext('2d')
    if (!canvas || !context) return
    let drawing = false
    const point = (event: PointerEvent) => { const rect = canvas.getBoundingClientRect(); return [(event.clientX - rect.left) * canvas.width / rect.width, (event.clientY - rect.top) * canvas.height / rect.height] }
    const down = (event: PointerEvent) => {
      event.preventDefault(); drawing = true; history.current.push(canvas.toDataURL('image/png')); if (history.current.length > 20) history.current.shift()
      canvas.setPointerCapture(event.pointerId); context.lineCap = 'round'; context.lineJoin = 'round'; context.strokeStyle = tool === 'eraser' ? '#fff' : color; context.lineWidth = tool === 'eraser' ? 28 : 10
      const [x, y] = point(event); context.beginPath(); context.moveTo(x, y); context.lineTo(x + .1, y + .1); context.stroke()
    }
    const move = (event: PointerEvent) => { if (!drawing) return; const [x, y] = point(event); context.lineTo(x, y); context.stroke() }
    const up = () => { if (!drawing) return; drawing = false; onChange(canvas.toDataURL('image/png')) }
    canvas.addEventListener('pointerdown', down); canvas.addEventListener('pointermove', move); canvas.addEventListener('pointerup', up); canvas.addEventListener('pointercancel', up)
    return () => { canvas.removeEventListener('pointerdown', down); canvas.removeEventListener('pointermove', move); canvas.removeEventListener('pointerup', up); canvas.removeEventListener('pointercancel', up) }
  }, [color, onChange, tool])

  const restore = (value: string) => { const image = new Image(); image.onload = () => { const canvas = canvasRef.current; const context = canvas?.getContext('2d'); if (!canvas || !context) return; context.clearRect(0, 0, canvas.width, canvas.height); context.drawImage(image, 0, 0, canvas.width, canvas.height); onChange(canvas.toDataURL('image/png')) }; image.src = value }
  return <div className={fullscreen ? 'phone-sketch fullscreen' : 'phone-sketch'}>
    <div className="phone-sketch-tools"><button type="button" className={tool === 'brush' ? 'active' : ''} aria-label="Кисть" onClick={() => setTool('brush')}><Brush /></button><button type="button" className={tool === 'eraser' ? 'active' : ''} aria-label="Ластик" onClick={() => setTool('eraser')}><Eraser /></button><label aria-label="Цвет"><input type="color" value={color} onChange={(event) => setColor(event.target.value)} /></label><button type="button" aria-label="Отменить" onClick={() => { const value = history.current.pop(); if (value) restore(value) }}><Undo2 /></button><button type="button" aria-label="Очистить" onClick={() => { const canvas = canvasRef.current; const context = canvas?.getContext('2d'); if (!canvas || !context) return; history.current.push(canvas.toDataURL()); context.fillStyle = '#fff'; context.fillRect(0, 0, canvas.width, canvas.height); onChange(canvas.toDataURL('image/png')) }}><Trash2 /></button>{fullscreen && <button type="button" aria-label="Закрыть полноэкранное рисование" onClick={() => setFullscreen(false)}><X /></button>}</div>
    <canvas ref={canvasRef} style={{ aspectRatio: ratio.replace(':', '/') }} onDoubleClick={() => setFullscreen(true)} aria-label="Холст. Дважды нажмите для полноэкранного режима" />
  </div>
}

function ImageViewer({ src, onClose }: { src: string; onClose: () => void }) {
  const imageRef = useRef<HTMLImageElement>(null)
  const pointers = useRef(new Map<number, { x: number; y: number }>())
  const transform = useRef({ scale: 1, x: 0, y: 0, pinchDistance: 0, pinchScale: 1 })
  const [scaleLabel, setScaleLabel] = useState(100)
  const apply = () => { const image = imageRef.current; if (image) image.style.transform = `translate(${transform.current.x}px,${transform.current.y}px) scale(${transform.current.scale})`; setScaleLabel(Math.round(transform.current.scale * 100)) }
  const toggle = () => { transform.current = transform.current.scale > 1.05 ? { scale: 1, x: 0, y: 0, pinchDistance: 0, pinchScale: 1 } : { scale: 2.5, x: 0, y: 0, pinchDistance: 0, pinchScale: 2.5 }; apply() }
  return <div className="phone-image-viewer" role="dialog" aria-modal="true" aria-label="Просмотр изображения"><button type="button" aria-label="Закрыть" onClick={onClose}><X /></button><span>{scaleLabel}%</span><img ref={imageRef} src={src} alt="Результат крупным планом" draggable={false} onDoubleClick={toggle} onPointerDown={(event) => { event.preventDefault(); event.currentTarget.setPointerCapture(event.pointerId); pointers.current.set(event.pointerId, { x: event.clientX, y: event.clientY }); if (pointers.current.size === 2) { const [a, b] = [...pointers.current.values()]; transform.current.pinchDistance = Math.hypot(a.x - b.x, a.y - b.y); transform.current.pinchScale = transform.current.scale } }} onPointerMove={(event) => { const previous = pointers.current.get(event.pointerId); if (!previous) return; pointers.current.set(event.pointerId, { x: event.clientX, y: event.clientY }); if (pointers.current.size >= 2) { const [a, b] = [...pointers.current.values()]; transform.current.scale = Math.max(1, Math.min(5, transform.current.pinchScale * Math.hypot(a.x - b.x, a.y - b.y) / Math.max(1, transform.current.pinchDistance))) } else if (transform.current.scale > 1) { transform.current.x += event.clientX - previous.x; transform.current.y += event.clientY - previous.y } apply() }} onPointerUp={(event) => pointers.current.delete(event.pointerId)} onPointerCancel={(event) => pointers.current.delete(event.pointerId)} /></div>
}

export default function PhoneImageWorkspace({ offline }: { offline: boolean }) {
  const [tab, setTab] = useState<'describe' | 'edit' | 'draw'>('describe')
  const [prompt, setPrompt] = useState(() => sessionStorage.getItem('izo.phone.image.prompt') || '')
  const [ratio, setRatio] = useState<Ratio>('1:1')
  const [tier, setTier] = useState<Tier>('HD')
  const [styleId, setStyleId] = useState('')
  const [sources, setSources] = useState<string[]>([])
  const [sketch, setSketch] = useState('')
  const [models, setModels] = useState<PhoneImageModel[]>([])
  const [modelId, setModelId] = useState('server:local_flux_klein')
  const [result, setResult] = useState('')
  const [progress, setProgress] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [viewer, setViewer] = useState(false)
  const [history, setHistory] = useState<PhoneGalleryImage[]>([])
  const fileRef = useRef<HTMLInputElement>(null)
  const sketchChange = useMemo(() => (value: string) => setSketch(value), [])

  useEffect(() => {
    const controller = new AbortController()
    void loadImageModels(controller.signal).then((access) => {
      const mode = tab === 'describe' ? 'text_to_image' : tab === 'draw' ? 'paint' : sources.length > 1 ? 'edit' : 'image_to_image'
      const row = access.modes?.[mode]
      const values = row?.models || []
      setModels(values)
      if (!values.some((item) => item.id === modelId)) setModelId(row?.presets?.fast || values[0]?.id || 'server:local_flux_klein')
    }).catch((caught) => setError(caught instanceof Error ? caught.message : 'Не удалось загрузить модели.'))
    return () => controller.abort()
  }, [modelId, sources.length, tab])

  useEffect(() => {
    const controller = new AbortController()
    void loadPhoneGallery(controller.signal).then(setHistory).catch(() => undefined)
    return () => controller.abort()
  }, [])

  const model = models.find((item) => item.id === modelId) || models[0] || { id: 'server:local_flux_klein', label: 'ИЗО Base', provider: 'comfyui' as const, modelProfile: 'local_flux_klein', tokenHint: 1, supportedResolutionIds: [] }
  const selectedSize = sizes[ratio][tier]
  const tierAvailable = (value: Tier) => !model.supportedResolutionIds?.length || model.supportedResolutionIds.includes(sizes[ratio][value][0])
  const style = I2I_STYLES.find((item) => item.id === styleId)

  const generate = async () => {
    if (!prompt.trim() || busy || offline) { if (!prompt.trim()) setError('Опишите, что нужно создать.'); return }
    const mode: PhoneImageMode = tab === 'describe' ? 'text_to_image' : tab === 'draw' ? 'paint' : sources.length > 1 ? 'edit' : 'image_to_image'
    if (mode === 'image_to_image' && !sources.length) { setError('Добавьте исходное изображение.'); return }
    if (mode === 'edit' && sources.length < 2) { setError('Для совмещения нужно минимум два изображения.'); return }
    try {
      setBusy(true); setError(''); setResult(''); setProgress(8)
      const suffix = style ? (mode === 'text_to_image' ? style.stylePrompt : style.transformPrompt) : ''
      const job = await startPhoneImage({ mode, prompt: `${prompt.trim()}${suffix ? `. ${suffix}` : ''}`, model, resolutionId: selectedSize[0], width: selectedSize[1], height: selectedSize[2], inputImages: sources, canvas: sketch }, (snapshot) => setProgress(snapshot.progress))
      setProgress(job.progress)
      if (job.status !== 'completed' || !job.result?.url) throw new Error(job.message || 'Изображение не создано.')
      setResult(job.result.url); setProgress(100)
      void loadPhoneGallery().then(setHistory).catch(() => undefined)
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Генерация временно недоступна.') }
    finally { setBusy(false) }
  }

  return <section className="phone-image" data-phone-workspace="image">
    <nav className="phone-image-tabs"><button className={tab === 'describe' ? 'active' : ''} type="button" onClick={() => setTab('describe')}><Sparkles />По описанию</button><button className={tab === 'edit' ? 'active' : ''} type="button" onClick={() => setTab('edit')}><Layers3 />Изменить</button><button className={tab === 'draw' ? 'active' : ''} type="button" onClick={() => setTab('draw')}><Pencil />Нарисовать</button></nav>
    <div className="phone-image-scroll">
      <div className="phone-image-preview">
        {result ? <><img src={result} alt="Результат генерации" onDoubleClick={() => setViewer(true)} /><button className="dismiss" type="button" aria-label="Освободить предпросмотр" onClick={() => setResult('')}><X /></button><div className="actions"><a href={result} download="izo-asa-image.png" aria-label="Скачать"><Download /></a><button type="button" aria-label="Поделиться" onClick={() => { const url = new URL(result, location.origin).toString(); if (navigator.share) void navigator.share({ title: 'ИЗО АСА', url }); else void navigator.clipboard?.writeText(url) }}><Share2 /></button><button type="button" aria-label="Оживить" onClick={() => { sessionStorage.setItem('izo.phone.video.source', result); window.location.assign('/phone/video') }}><Video /></button></div></> : tab === 'draw' ? <SketchCanvas ratio={ratio} onChange={sketchChange} /> : tab === 'edit' && sources.length ? <div className="phone-image-sources">{sources.map((source, index) => <span key={`${source.slice(-20)}-${index}`}><img src={source} alt={`Исходное изображение ${index + 1}`} /><button type="button" aria-label="Убрать изображение" onClick={() => setSources((value) => value.filter((_, itemIndex) => itemIndex !== index))}><X /></button></span>)}{sources.length < 4 && <button type="button" onClick={() => fileRef.current?.click()}><ImagePlus />Добавить</button>}</div> : <><img className="placeholder" src="/phone-preview-placeholder.jpg" alt="" /><div className="empty"><Sparkles /><b>{tab === 'edit' ? 'Измените или совместите' : 'Создайте первое изображение'}</b><span>{tab === 'edit' ? 'Добавьте до четырёх изображений' : 'Результат полностью поместится здесь'}</span>{tab === 'edit' && <button type="button" onClick={() => fileRef.current?.click()}>Выбрать изображения</button>}</div></>}
        {busy && <div className="phone-image-busy"><i style={{ width: `${Math.max(8, progress)}%` }} /><b>Создаём изображение</b><span>{Math.round(progress)}%</span></div>}
      </div>

      <input ref={fileRef} hidden multiple type="file" accept="image/jpeg,image/png,image/webp" onChange={async (event) => { try { const added = await Promise.all(Array.from(event.target.files || []).slice(0, 4 - sources.length).map(fileToPhoneImage)); setSources((value) => [...value, ...added].slice(0, 4)); setTab('edit') } catch (caught) { setError(caught instanceof Error ? caught.message : 'Не удалось добавить изображение.') } event.target.value = '' }} />
      <div className="phone-image-prompt"><textarea value={prompt} maxLength={3000} placeholder="Например: сова в космосе, неоновые звёзды…" onChange={(event) => setPrompt(event.target.value)} /><button type="button" disabled={busy || offline || !prompt.trim()} onClick={() => void generate()}><Sparkles />{busy ? 'Создаём…' : 'Сгенерировать'}<em className={phoneTokenClass(model.provider === 'comfyui' ? 'daily' : 'main')}>{model.tokenHint} ток.</em></button></div>
      {error && <div className="phone-image-error">{error}<button type="button" aria-label="Закрыть" onClick={() => setError('')}><X /></button></div>}

      <section className="phone-image-options"><h2>Формат и качество</h2><div className="phone-image-ratios">{(['1:1', '9:16', '16:9', '3:2'] as Ratio[]).map((value) => <button className={ratio === value ? 'active' : ''} type="button" key={value} onClick={() => setRatio(value)}>{value}</button>)}</div><div className="phone-image-tiers">{(['SD', 'HD', 'Full HD', '4K'] as Tier[]).map((value) => <button className={tier === value ? 'active' : ''} disabled={!tierAvailable(value)} type="button" key={value} onClick={() => setTier(value)}><b>{value === 'Full HD' ? 'FHD' : value}</b><small>{sizes[ratio][value][1]}×{sizes[ratio][value][2]}</small></button>)}</div>
        <label>Модель<select value={model.id} onChange={(event) => setModelId(event.target.value)}>{models.map((item) => <option value={item.id} key={item.id}>{item.label} · {item.tokenHint} ток.</option>)}</select><small>{model.provider === 'comfyui' ? 'Базовая модель ИЗО АСА на этом сервере' : 'Расширенная модель для особых задач'}</small></label>
      </section>

      <section className="phone-image-styles"><h2>Стиль</h2><div><button className={!styleId ? 'active none' : 'none'} type="button" onClick={() => setStyleId('')}><Check /><span>Нет</span></button>{I2I_STYLES.map((item) => <button className={styleId === item.id ? 'active' : ''} type="button" key={item.id} onClick={() => setStyleId(item.id)}><img src={item.preview.female} alt="" /><span>{styleShortLabel(item, 'ru')}</span></button>)}</div></section>
      {tab === 'describe' && <section className="phone-image-templates"><h2>Шаблоны</h2><div>{T2I_TEMPLATES.slice(0, 12).map((item) => <button type="button" key={item.id} onClick={() => setPrompt(item.prompt)}><b>{item.name}</b><span>{item.prompt.slice(0, 90)}…</span></button>)}</div></section>}
      {history.length > 0 && <section className="phone-image-history"><h2>История</h2><div>{history.map((item) => <button type="button" key={item.id} style={{ aspectRatio: item.width > 0 && item.height > 0 ? `${item.width}/${item.height}` : '1' }} onClick={() => { setResult(item.url); setViewer(false); document.querySelector('.phone-image-scroll')?.scrollTo({ top: 0, behavior: 'smooth' }) }}><img src={item.thumbnailUrl} alt="Открыть изображение из истории" /></button>)}</div></section>}
    </div>
    {viewer && result && <ImageViewer src={result} onClose={() => setViewer(false)} />}
  </section>
}
