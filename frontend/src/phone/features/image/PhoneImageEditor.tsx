import { useEffect, useRef, useState } from 'react'
import { Brush, Eraser, Expand, ScanFace, Scissors, Trash2, Undo2 } from 'lucide-react'

export type PhoneEditorTool = 'compose' | 'face' | 'mask' | 'outpaint' | 'remove_background'
export type PhoneOutpaint = { left: number; right: number; top: number; bottom: number }

function MaskCanvas({ source, onChange }: { source: string; onChange: (mask: string) => void }) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const maskRef = useRef<HTMLCanvasElement | null>(null)
  const [eraser, setEraser] = useState(false)
  const [size, setSize] = useState(42)
  const [ready, setReady] = useState(0)
  const history = useRef<string[]>([])

  const render = () => {
    const visible = canvasRef.current
    const mask = maskRef.current
    if (!visible || !mask) return
    const context = visible.getContext('2d')
    const maskContext = mask.getContext('2d')
    if (!context || !maskContext) return
    context.clearRect(0, 0, visible.width, visible.height)
    context.drawImage(mask, 0, 0)
    onChange(mask.toDataURL('image/png'))
  }

  useEffect(() => {
    const visible = canvasRef.current
    if (!visible) return
    const image = new Image()
    image.onload = () => {
      const width = Math.max(1, image.naturalWidth || image.width)
      const height = Math.max(1, image.naturalHeight || image.height)
      visible.width = width; visible.height = height
      const mask = document.createElement('canvas')
      mask.width = width; mask.height = height
      const context = mask.getContext('2d')
      if (!context) return
      context.fillStyle = '#000'; context.fillRect(0, 0, width, height)
      maskRef.current = mask; history.current = []; render(); setReady((value) => value + 1)
    }
    image.src = source
  // render intentionally follows source initialization only.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [source])

  useEffect(() => {
    const canvas = canvasRef.current
    const mask = maskRef.current
    const context = mask?.getContext('2d')
    if (!canvas || !mask || !context) return
    let drawing = false
    const point = (event: PointerEvent) => { const rect = canvas.getBoundingClientRect(); return [(event.clientX - rect.left) * mask.width / rect.width, (event.clientY - rect.top) * mask.height / rect.height] }
    const down = (event: PointerEvent) => {
      event.preventDefault(); drawing = true; history.current.push(mask.toDataURL('image/png')); if (history.current.length > 20) history.current.shift(); canvas.setPointerCapture(event.pointerId)
      context.strokeStyle = eraser ? '#000' : '#fff'; context.lineWidth = size; context.lineCap = 'round'; context.lineJoin = 'round'
      const [x, y] = point(event); context.beginPath(); context.moveTo(x, y); context.lineTo(x + .1, y + .1); context.stroke(); render()
    }
    const move = (event: PointerEvent) => { if (!drawing) return; const [x, y] = point(event); context.lineTo(x, y); context.stroke(); render() }
    const up = () => { drawing = false }
    canvas.addEventListener('pointerdown', down); canvas.addEventListener('pointermove', move); canvas.addEventListener('pointerup', up); canvas.addEventListener('pointercancel', up)
    return () => { canvas.removeEventListener('pointerdown', down); canvas.removeEventListener('pointermove', move); canvas.removeEventListener('pointerup', up); canvas.removeEventListener('pointercancel', up) }
  // render writes the current mask and is stable for this mounted canvas.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [eraser, ready, size, source])

  const restore = (value: string) => { const image = new Image(); image.onload = () => { const mask = maskRef.current; const context = mask?.getContext('2d'); if (!mask || !context) return; context.clearRect(0, 0, mask.width, mask.height); context.drawImage(image, 0, 0); render() }; image.src = value }
  return <div className="phone-mask-canvas" style={{ backgroundImage: `url(${source})` }}><canvas ref={canvasRef} aria-label="Закрасьте область, которую нужно изменить" /><div><button type="button" className={!eraser ? 'active' : ''} aria-label="Кисть маски" onClick={() => setEraser(false)}><Brush /></button><button type="button" className={eraser ? 'active' : ''} aria-label="Ластик маски" onClick={() => setEraser(true)}><Eraser /></button><input aria-label="Размер кисти" type="range" min="12" max="120" value={size} onChange={(event) => setSize(Number(event.target.value))} /><button type="button" aria-label="Отменить маску" onClick={() => { const value = history.current.pop(); if (value) restore(value) }}><Undo2 /></button><button type="button" aria-label="Очистить маску" onClick={() => { const mask = maskRef.current; const context = mask?.getContext('2d'); if (!mask || !context) return; context.fillStyle = '#000'; context.fillRect(0, 0, mask.width, mask.height); render() }}><Trash2 /></button></div></div>
}

export default function PhoneImageEditor({ tool, setTool, source, faceStrength, setFaceStrength, mask, setMask, outpaint, setOutpaint }: { tool: PhoneEditorTool; setTool: (tool: PhoneEditorTool) => void; source?: string; faceStrength: number; setFaceStrength: (value: number) => void; mask: string; setMask: (value: string) => void; outpaint: PhoneOutpaint; setOutpaint: (value: PhoneOutpaint) => void }) {
  const tools: Array<[PhoneEditorTool, string, typeof ScanFace]> = [['compose', 'Совместить', ScanFace], ['face', 'Лицо', ScanFace], ['mask', 'Маска', Brush], ['outpaint', 'Расширить', Expand], ['remove_background', 'Убрать фон', Scissors]]
  return <div className="phone-editor-controls"><div className="phone-editor-tools">{tools.map(([id, label, Icon]) => <button type="button" className={tool === id ? 'active' : ''} key={id} onClick={() => setTool(id)}><Icon /><span>{label}</span></button>)}</div>
    {tool === 'face' && <label className="phone-face-strength"><span>Сходство лица</span><input type="range" min="25" max="100" step="5" value={faceStrength} onChange={(event) => setFaceStrength(Number(event.target.value))} /><output>{faceStrength}%</output></label>}
    {tool === 'mask' && source && <MaskCanvas source={source} onChange={setMask} key={source} />}
    {tool === 'outpaint' && source && <div className="phone-outpaint"><img src={source} alt="Исходное изображение для расширения" /><div>{(['top', 'right', 'bottom', 'left'] as const).map((side) => <label key={side}><span>{{ top: 'Сверху', right: 'Справа', bottom: 'Снизу', left: 'Слева' }[side]}</span><input type="number" min="0" max="1024" step="16" value={outpaint[side]} onChange={(event) => setOutpaint({ ...outpaint, [side]: Math.max(0, Math.min(1024, Number(event.target.value) || 0)) })} /></label>)}</div></div>}
    {tool === 'remove_background' && source && <div className="phone-editor-hint"><Scissors /><span>Фон станет прозрачным. Предмет и его края сохранятся.</span></div>}
    {tool === 'mask' && !mask && source && <small>Белым закрасьте только область, которую нужно изменить.</small>}
  </div>
}
