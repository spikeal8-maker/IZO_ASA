import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react'
import type { CSSProperties, Dispatch, PointerEvent as ReactPointerEvent, RefObject, SetStateAction } from 'react'
import { Brush, Eraser, History, Images, PaintBucket, Palette, Slash, Trash2, Undo2, Upload } from 'lucide-react'
import { Circle, Image as KonvaImage, Layer, Line, Rect, Stage, Text } from 'react-konva'
import type { Stage as KonvaStage } from 'konva/lib/Stage'
import type { PaintDrawMode, PaintLine, PaintLineKind, PaintOutpaintPlacement, PaintSubMode, PaintTool } from './paintTypes'

export type PaintWorkbenchHandle = {
  toDataURL: () => string | undefined
}

type Props = {
  apiUrl: (path: string) => string
  workbenchRef: RefObject<HTMLDivElement | null>
  paintMode: PaintSubMode
  paintImage?: string
  paintSketchImage?: string
  paintOutpaintPreview?: string
  paintOutpaint: PaintOutpaintPlacement
  setPaintOutpaint: Dispatch<SetStateAction<PaintOutpaintPlacement>>
  paintStageSize: { width: number; height: number }
  paintLines: PaintLine[]
  setPaintLines: Dispatch<SetStateAction<PaintLine[]>>
  paintTool: PaintTool
  setPaintTool: Dispatch<SetStateAction<PaintTool>>
  paintDrawMode: PaintDrawMode
  setPaintDrawMode: Dispatch<SetStateAction<PaintDrawMode>>
  paintBrushSize: number
  paintColor: string
  setPaintColor: Dispatch<SetStateAction<string>>
  paintCanvasBg: 'white' | 'gray'
  onUploadImage: () => void
  onPickGallery: () => void
  onUseLastImage: () => void
  onRemoveImage: () => void
}

function paintPoint(stage: KonvaStage | null) {
  const pos = stage?.getPointerPosition()
  return [pos?.x || 0, pos?.y || 0]
}

function paintLineKind(mode: PaintDrawMode): PaintLineKind {
  switch (mode) {
    case 'rect-fill':
    case 'rect-outline':
      return 'rect'
    case 'circle-fill':
    case 'circle-outline':
      return 'circle'
    case 'bucket':
      return 'free'
    default:
      return mode
  }
}

function shapeBounds(line: PaintLine) {
  const [x1 = 0, y1 = 0, x2 = x1, y2 = y1] = line.points
  const x = Math.min(x1, x2)
  const y = Math.min(y1, y2)
  const w = Math.abs(x2 - x1)
  const h = Math.abs(y2 - y1)
  return { x, y, w, h, cx: x + w / 2, cy: y + h / 2 }
}

function pointInShape(line: PaintLine, x: number, y: number) {
  if (line.tool !== 'brush' || line.fill || (line.kind !== 'rect' && line.kind !== 'circle')) return false
  const bounds = shapeBounds(line)
  if (line.kind === 'rect') return x >= bounds.x && x <= bounds.x + bounds.w && y >= bounds.y && y <= bounds.y + bounds.h
  const radius = Math.max(bounds.w, bounds.h) / 2
  const dx = x - bounds.cx
  const dy = y - bounds.cy
  return Math.sqrt(dx * dx + dy * dy) <= radius
}

function hexToRgba(hex: string) {
  const normalized = hex.replace('#', '')
  const full = normalized.length === 3
    ? normalized.split('').map((x) => `${x}${x}`).join('')
    : normalized.padEnd(6, '0').slice(0, 6)
  return {
    r: parseInt(full.slice(0, 2), 16),
    g: parseInt(full.slice(2, 4), 16),
    b: parseInt(full.slice(4, 6), 16),
    a: 255,
  }
}

function colorDistance(data: Uint8ClampedArray, index: number, target: { r: number; g: number; b: number; a: number }) {
  return Math.abs(data[index] - target.r) + Math.abs(data[index + 1] - target.g) + Math.abs(data[index + 2] - target.b) + Math.abs(data[index + 3] - target.a)
}

function touchDistance(touches: TouchList) {
  if (touches.length < 2) return 0
  const a = touches[0]
  const b = touches[1]
  return Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY)
}

function touchCenter(touches: TouchList) {
  const a = touches[0]
  const b = touches[1]
  return { x: (a.clientX + b.clientX) / 2, y: (a.clientY + b.clientY) / 2 }
}

function loadImage(source: string) {
  return new Promise<HTMLImageElement>((resolve, reject) => {
    const image = new Image()
    image.onload = () => resolve(image)
    image.onerror = reject
    image.src = source
  })
}

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value))
}

function PaintBitmapImage({ line, width, height }: { line: PaintLine; width: number; height: number }) {
  const [image, setImage] = useState<HTMLImageElement | null>(null)
  useEffect(() => {
    if (!line.image) return undefined
    let cancelled = false
    void loadImage(line.image).then((loaded) => {
      if (!cancelled) setImage(loaded)
    }).catch(() => {
      if (!cancelled) setImage(null)
    })
    return () => { cancelled = true }
  }, [line.image])
  return image ? <KonvaImage image={image} x={0} y={0} width={width} height={height} listening={false} /> : null
}

const PaintWorkbench = forwardRef<PaintWorkbenchHandle, Props>(function PaintWorkbench({
  apiUrl,
  workbenchRef,
  paintMode,
  paintImage,
  paintSketchImage,
  paintOutpaintPreview,
  paintOutpaint,
  setPaintOutpaint,
  paintStageSize,
  paintLines,
  setPaintLines,
  paintTool,
  setPaintTool,
  paintDrawMode,
  setPaintDrawMode,
  paintBrushSize,
  paintColor,
  setPaintColor,
  paintCanvasBg,
  onUploadImage,
  onPickGallery,
  onUseLastImage,
  onRemoveImage,
}, ref) {
  const stageRef = useRef<KonvaStage>(null)
  const drawingRef = useRef(false)
  const outpaintFrameRef = useRef<HTMLDivElement | null>(null)
  const outpaintFitKeyRef = useRef('')
  const outpaintDragRef = useRef<null | {
    kind: 'image' | 'left' | 'right' | 'top' | 'bottom'
    x: number
    y: number
    rect: { x: number; y: number; w: number; h: number }
  }>(null)
  const [view, setView] = useState({ scale: 1, x: 0, y: 0 })
  const [outpaintFrameSize, setOutpaintFrameSize] = useState(paintStageSize)
  const [outpaintSourceSize, setOutpaintSourceSize] = useState({ width: paintStageSize.width, height: paintStageSize.height })
  const touchViewRef = useRef({ pinching: false, distance: 0, centerX: 0, centerY: 0, scale: 1, x: 0, y: 0 })

  useImperativeHandle(ref, () => ({
    toDataURL: () => stageRef.current?.toDataURL({ pixelRatio: 1 }),
  }), [])

  useEffect(() => {
    if (!paintImage) {
      outpaintFitKeyRef.current = ''
      return undefined
    }
    let cancelled = false
    void loadImage(apiUrl(paintImage)).then((image) => {
      if (!cancelled) {
        setOutpaintSourceSize({ width: image.naturalWidth || image.width || paintStageSize.width, height: image.naturalHeight || image.height || paintStageSize.height })
      }
    }).catch(() => {
      if (!cancelled) setOutpaintSourceSize({ width: paintStageSize.width, height: paintStageSize.height })
    })
    return () => { cancelled = true }
  }, [apiUrl, paintImage, paintStageSize.height, paintStageSize.width])

  useEffect(() => {
    if (paintMode !== 'outpaint') return undefined
    const update = () => {
      const box = workbenchRef.current?.getBoundingClientRect()
      const maxW = Math.max(240, (box?.width || paintStageSize.width) - 36)
      const maxH = Math.max(240, (box?.height || paintStageSize.height) - 36)
      const scale = Math.min(maxW / Math.max(1, paintStageSize.width), maxH / Math.max(1, paintStageSize.height))
      setOutpaintFrameSize({
        width: Math.max(1, Math.round(paintStageSize.width * scale)),
        height: Math.max(1, Math.round(paintStageSize.height * scale)),
      })
    }
    update()
    const observer = typeof ResizeObserver === 'undefined' ? undefined : new ResizeObserver(update)
    if (workbenchRef.current && observer) observer.observe(workbenchRef.current)
    window.addEventListener('resize', update)
    return () => {
      observer?.disconnect()
      window.removeEventListener('resize', update)
    }
  }, [paintMode, paintStageSize.height, paintStageSize.width, workbenchRef])

  useEffect(() => {
    if (paintMode !== 'outpaint' || !paintImage) return
    const sourceW = Math.max(1, outpaintSourceSize.width)
    const sourceH = Math.max(1, outpaintSourceSize.height)
    const frameW = Math.max(1, paintStageSize.width)
    const frameH = Math.max(1, paintStageSize.height)
    const fitKey = `${paintImage}|${sourceW}x${sourceH}|${frameW}x${frameH}`
    if (outpaintFitKeyRef.current === fitKey) return
    outpaintFitKeyRef.current = fitKey
    const scale = Math.min(frameW / sourceW, frameH / sourceH)
    const rectW = Math.round(sourceW * scale)
    const rectH = Math.round(sourceH * scale)
    const rectX = Math.round((frameW - rectW) / 2)
    const rectY = Math.round((frameH - rectH) / 2)
    const finalW = frameW / Math.max(0.0001, scale)
    const finalH = frameH / Math.max(0.0001, scale)
    const extraX = Math.max(0, Math.round(finalW - sourceW))
    const extraY = Math.max(0, Math.round(finalH - sourceH))
    setPaintOutpaint({
      left: Math.floor(extraX / 2),
      right: Math.ceil(extraX / 2),
      top: Math.floor(extraY / 2),
      bottom: Math.ceil(extraY / 2),
      frameW,
      frameH,
      sourceX: rectX,
      sourceY: rectY,
      sourceW: rectW,
      sourceH: rectH,
    })
  }, [outpaintSourceSize.height, outpaintSourceSize.width, paintImage, paintMode, paintStageSize.height, paintStageSize.width, setPaintOutpaint])

  function startPaintLine(stage: KonvaStage | null) {
    if (paintMode === 'outpaint' || paintMode === 'remove_bg') return
    const point = paintPoint(stage)
    if (paintMode === 'sketch' && paintDrawMode === 'bucket') {
      void bucketFill(stage, point)
      drawingRef.current = false
      return
    }
    drawingRef.current = true
    const kind = paintLineKind(paintDrawMode)
    const fill = paintDrawMode === 'rect-fill' || paintDrawMode === 'circle-fill'
    setPaintLines((lines) => lines.concat({
      tool: paintTool,
      kind,
      color: paintMode === 'mask' ? '#dfff22' : paintColor,
      fill,
      strokeWidth: paintBrushSize,
      points: point.concat(point),
    }))
  }

  async function bucketFill(stage: KonvaStage | null, point: number[]) {
    if (!stage) return
    const [x, y] = point.map((value) => Math.round(value))
    const width = paintStageSize.width
    const height = paintStageSize.height
    if (x < 0 || y < 0 || x >= width || y >= height) return
    const stageImage = await loadImage(stage.toDataURL({ pixelRatio: 1 })).catch(() => undefined)
    if (!stageImage) return
    const canvas = document.createElement('canvas')
    canvas.width = width
    canvas.height = height
    const ctx = canvas.getContext('2d', { willReadFrequently: true })
    if (!ctx) return
    ctx.drawImage(stageImage, 0, 0, width, height)
    const source = ctx.getImageData(0, 0, width, height)
    const sourceData = source.data
    const startIndex = (y * width + x) * 4
    const target = {
      r: sourceData[startIndex],
      g: sourceData[startIndex + 1],
      b: sourceData[startIndex + 2],
      a: sourceData[startIndex + 3],
    }
    const fill = hexToRgba(paintColor)
    if (Math.abs(target.r - fill.r) + Math.abs(target.g - fill.g) + Math.abs(target.b - fill.b) < 12) return
    const tolerance = 54
    const visited = new Uint8Array(width * height)
    const output = ctx.createImageData(width, height)
    const outputData = output.data
    const stack = [[x, y]]
    let painted = 0
    const maxPixels = width * height
    while (stack.length) {
      const next = stack.pop()
      if (!next) break
      const [px, py] = next
      if (px < 0 || py < 0 || px >= width || py >= height) continue
      const pixelIndex = py * width + px
      if (visited[pixelIndex]) continue
      visited[pixelIndex] = 1
      const dataIndex = pixelIndex * 4
      if (colorDistance(sourceData, dataIndex, target) > tolerance) continue
      outputData[dataIndex] = fill.r
      outputData[dataIndex + 1] = fill.g
      outputData[dataIndex + 2] = fill.b
      outputData[dataIndex + 3] = fill.a
      painted += 1
      if (painted > maxPixels * 0.92) break
      stack.push([px + 1, py], [px - 1, py], [px, py + 1], [px, py - 1])
    }
    if (painted < 2) {
      setPaintLines((lines) => {
        const targetIndex = [...lines].reverse().findIndex((line) => pointInShape(line, x, y))
        if (targetIndex < 0) return lines
        const source = lines[lines.length - 1 - targetIndex]
        return lines.concat({ ...source, fill: true, color: paintColor, strokeWidth: 0 })
      })
      return
    }
    const out = document.createElement('canvas')
    out.width = width
    out.height = height
    const outCtx = out.getContext('2d')
    if (!outCtx) return
    outCtx.putImageData(output, 0, 0)
    const image = out.toDataURL('image/png')
    setPaintLines((lines) => lines.concat({
      tool: paintTool,
      kind: 'bitmap',
      color: paintColor,
      fill: true,
      image,
      strokeWidth: 0,
      points: [0, 0],
    }))
  }

  function extendPaintLine(stage: KonvaStage | null) {
    if (!drawingRef.current) return
    const point = paintPoint(stage)
    setPaintLines((lines) => {
      const last = lines[lines.length - 1]
      if (!last) return lines
      const points = last.kind && last.kind !== 'free' ? last.points.slice(0, 2).concat(point) : last.points.concat(point)
      return lines.slice(0, -1).concat({ ...last, points })
    })
  }

  function stopPaintLine() {
    drawingRef.current = false
  }

  function startTouch(e: { evt: TouchEvent; target: { getStage: () => KonvaStage | null } }) {
    if (e.evt.touches.length === 2) {
      e.evt.preventDefault()
      const distance = touchDistance(e.evt.touches)
      const center = touchCenter(e.evt.touches)
      touchViewRef.current = { pinching: true, distance, centerX: center.x, centerY: center.y, scale: view.scale, x: view.x, y: view.y }
      stopPaintLine()
      return
    }
    e.evt.preventDefault()
    startPaintLine(e.target.getStage() || null)
  }

  function moveTouch(e: { evt: TouchEvent; target: { getStage: () => KonvaStage | null } }) {
    const touch = touchViewRef.current
    if (e.evt.touches.length === 2 && touch.pinching) {
      e.evt.preventDefault()
      const distance = touchDistance(e.evt.touches)
      if (!touch.distance || !distance) return
      const center = touchCenter(e.evt.touches)
      setView({
        scale: Math.max(1, Math.min(4, touch.scale * (distance / touch.distance))),
        x: Math.max(-260, Math.min(260, touch.x + center.x - touch.centerX)),
        y: Math.max(-260, Math.min(260, touch.y + center.y - touch.centerY)),
      })
      return
    }
    e.evt.preventDefault()
    extendPaintLine(e.target.getStage() || null)
  }

  function endTouch(e: { evt: TouchEvent }) {
    if (e.evt.touches.length < 2) touchViewRef.current.pinching = false
    if (e.evt.touches.length === 0) stopPaintLine()
  }

  function outpaintUnits(dx: number, dy: number) {
    const box = outpaintFrameRef.current?.getBoundingClientRect()
    return {
      x: box?.width ? dx * paintStageSize.width / box.width : 0,
      y: box?.height ? dy * paintStageSize.height / box.height : 0,
    }
  }

  function clampOutpaintRect(rect: { x: number; y: number; w: number; h: number }) {
    const frameW = Math.max(1, paintStageSize.width)
    const frameH = Math.max(1, paintStageSize.height)
    const minVisible = Math.min(48, frameW / 3, frameH / 3)
    const w = clamp(rect.w, minVisible, frameW * 4)
    const h = clamp(rect.h, minVisible, frameH * 4)
    const x = clamp(rect.x, minVisible - w, frameW - minVisible)
    const y = clamp(rect.y, minVisible - h, frameH - minVisible)
    return { x: Math.round(x), y: Math.round(y), w: Math.round(w), h: Math.round(h) }
  }

  function outpaintPaddingFromRect(rect: { x: number; y: number; w: number; h: number }) {
    const frameW = Math.max(1, paintStageSize.width)
    const frameH = Math.max(1, paintStageSize.height)
    const naturalW = Math.max(1, outpaintSourceSize.width)
    const naturalH = Math.max(1, outpaintSourceSize.height)
    const scaleX = rect.w / naturalW
    const scaleY = rect.h / naturalH
    return {
      left: Math.max(0, Math.round(rect.x / Math.max(0.0001, scaleX))),
      right: Math.max(0, Math.round((frameW - rect.x - rect.w) / Math.max(0.0001, scaleX))),
      top: Math.max(0, Math.round(rect.y / Math.max(0.0001, scaleY))),
      bottom: Math.max(0, Math.round((frameH - rect.y - rect.h) / Math.max(0.0001, scaleY))),
    }
  }

  function currentOutpaintRect() {
    const frameW = Math.max(1, paintStageSize.width)
    const frameH = Math.max(1, paintStageSize.height)
    if (
      typeof paintOutpaint.sourceX === 'number'
      && typeof paintOutpaint.sourceY === 'number'
      && typeof paintOutpaint.sourceW === 'number'
      && typeof paintOutpaint.sourceH === 'number'
    ) {
      return clampOutpaintRect({ x: paintOutpaint.sourceX, y: paintOutpaint.sourceY, w: paintOutpaint.sourceW, h: paintOutpaint.sourceH })
    }
    const sourceSize = paintImage ? outpaintSourceSize : paintStageSize
    const finalWidth = Math.max(1, sourceSize.width + paintOutpaint.left + paintOutpaint.right)
    const finalHeight = Math.max(1, sourceSize.height + paintOutpaint.top + paintOutpaint.bottom)
    return {
      x: Math.round(paintOutpaint.left / finalWidth * frameW),
      y: Math.round(paintOutpaint.top / finalHeight * frameH),
      w: Math.round(sourceSize.width / finalWidth * frameW),
      h: Math.round(sourceSize.height / finalHeight * frameH),
    }
  }

  function updateOutpaintRect(rect: { x: number; y: number; w: number; h: number }) {
    const next = clampOutpaintRect(rect)
    const padding = outpaintPaddingFromRect(next)
    setPaintOutpaint({
      ...padding,
      frameW: paintStageSize.width,
      frameH: paintStageSize.height,
      sourceX: next.x,
      sourceY: next.y,
      sourceW: next.w,
      sourceH: next.h,
    })
  }

  function startOutpaintDrag(kind: NonNullable<typeof outpaintDragRef.current>['kind'], event: ReactPointerEvent) {
    if (!paintImage) return
    event.preventDefault()
    event.stopPropagation()
    outpaintDragRef.current = { kind, x: event.clientX, y: event.clientY, rect: currentOutpaintRect() }
    event.currentTarget.setPointerCapture?.(event.pointerId)
  }

  function moveOutpaintDrag(event: ReactPointerEvent) {
    const drag = outpaintDragRef.current
    if (!drag) return
    event.preventDefault()
    const delta = outpaintUnits(event.clientX - drag.x, event.clientY - drag.y)
    const minSize = 48
    if (drag.kind === 'image') {
      updateOutpaintRect({ ...drag.rect, x: drag.rect.x + delta.x, y: drag.rect.y + delta.y })
    } else if (drag.kind === 'left') {
      const nextX = drag.rect.x + delta.x
      updateOutpaintRect({ x: nextX, y: drag.rect.y, w: Math.max(minSize, drag.rect.w - delta.x), h: drag.rect.h })
    } else if (drag.kind === 'right') {
      updateOutpaintRect({ ...drag.rect, w: Math.max(minSize, drag.rect.w + delta.x) })
    } else if (drag.kind === 'top') {
      const nextY = drag.rect.y + delta.y
      updateOutpaintRect({ x: drag.rect.x, y: nextY, w: drag.rect.w, h: Math.max(minSize, drag.rect.h - delta.y) })
    } else {
      updateOutpaintRect({ ...drag.rect, h: Math.max(minSize, drag.rect.h + delta.y) })
    }
  }

  function stopOutpaintDrag() {
    outpaintDragRef.current = null
  }

  const renderPaintLine = (line: PaintLine, index: number | string) => {
    if (line.kind === 'bitmap') return <PaintBitmapImage key={index} line={line} width={paintStageSize.width} height={paintStageSize.height} />
    const color = line.tool === 'eraser' ? (paintMode === 'mask' ? 'rgba(0,0,0,.8)' : (paintCanvasBg === 'white' ? '#fff' : '#2b2f2c')) : (line.color || paintColor)
    const width = line.tool === 'eraser' ? line.strokeWidth * 1.7 : line.strokeWidth
    if (line.kind === 'rect' || line.kind === 'circle') {
      const { x, y, w, h } = shapeBounds(line)
      if (line.kind === 'circle') {
        return <Circle key={index} x={x + w / 2} y={y + h / 2} radius={Math.max(w, h) / 2} stroke={color} strokeWidth={width} fill={line.fill ? color : undefined} opacity={line.tool === 'eraser' ? 1 : .9} />
      }
      return <Rect key={index} x={x} y={y} width={w} height={h} stroke={color} strokeWidth={width} fill={line.fill ? color : undefined} opacity={line.tool === 'eraser' ? 1 : .9} />
    }
    return <Line key={index} points={line.points} stroke={color} strokeWidth={width} tension={0.45} lineCap="round" lineJoin="round" opacity={paintMode === 'mask' && line.tool !== 'eraser' ? .78 : 1} />
  }

  const needsPaintImage = paintMode !== 'sketch'
  const hasPaintImage = !!paintImage
  const uploadTitle = paintMode === 'sketch'
    ? 'Нарисуйте эскиз'
    : paintMode === 'mask'
      ? 'Загрузить изображение для маски'
      : paintMode === 'outpaint'
        ? 'Загрузить изображение для расширения'
        : 'Загрузить изображение для удаления фона'
  const uploadHint = paintMode === 'sketch'
    ? 'Нарисуйте эскиз и получите реалистичное изображение.'
    : paintMode === 'mask'
      ? 'Загрузите изображение и выделите, что нужно изменить.'
      : paintMode === 'outpaint'
        ? 'Загрузите изображение, затем потяните исходник или его края в нужную сторону.'
        : 'Загрузите изображение, результат появится после генерации.'
  const outpaintRect = currentOutpaintRect()
  const sketchPlaceholderText = paintStageSize.width < 520
    ? 'Нарисуйте эскиз'
    : 'Нарисуйте эскиз и получите реалистичное изображение'
  const outpaintImageStyle = {
    left: `${outpaintRect.x / Math.max(1, paintStageSize.width) * 100}%`,
    top: `${outpaintRect.y / Math.max(1, paintStageSize.height) * 100}%`,
    width: `${outpaintRect.w / Math.max(1, paintStageSize.width) * 100}%`,
    height: `${outpaintRect.h / Math.max(1, paintStageSize.height) * 100}%`,
  } as CSSProperties

  return (
    <div
      ref={workbenchRef}
      className={`paint-workbench mode-${paintMode}`}
      style={{
        '--paint-view-scale': view.scale,
        '--paint-view-x': `${view.x}px`,
        '--paint-view-y': `${view.y}px`,
      } as CSSProperties}
    >
      {((paintMode === 'sketch' && paintSketchImage) || (paintMode === 'mask' && paintImage)) && (
        <img
          className={`paint-workbench-image${paintMode === 'sketch' ? ' sketch' : paintMode === 'mask' ? ' mask' : ''}`}
          src={apiUrl(paintMode === 'sketch' ? paintSketchImage! : paintImage!)}
          alt=""
          aria-hidden="true"
          style={paintMode === 'sketch' || paintMode === 'mask' ? {
            '--paint-stage-w': `${paintStageSize.width}px`,
            '--paint-stage-h': `${paintStageSize.height}px`,
          } as CSSProperties : undefined}
        />
      )}
      {(paintMode === 'sketch' || paintMode === 'mask') && (
        <div className="paint-canvas-toolbar" aria-label="Быстрые инструменты холста">
          <button className={paintTool === 'brush' && paintDrawMode === 'free' ? 'active' : ''} type="button" title="Кисть" aria-label="Кисть" onClick={() => { setPaintTool('brush'); setPaintDrawMode('free') }}><Brush size={19} strokeWidth={2.2} /></button>
          <button className={paintTool === 'eraser' ? 'active' : ''} type="button" title="Ластик" aria-label="Ластик" onClick={() => { setPaintTool('eraser'); setPaintDrawMode('free') }}><Eraser size={19} strokeWidth={2.2} /></button>
          {paintMode === 'sketch' && (
            <>
              <button className={paintDrawMode === 'line' ? 'active' : ''} type="button" title="Линия" aria-label="Линия" onClick={() => { setPaintTool('brush'); setPaintDrawMode('line') }}><Slash size={20} strokeWidth={2.6} /></button>
              <button className={paintDrawMode === 'rect-fill' ? 'active' : ''} type="button" title="Залитый прямоугольник" aria-label="Залитый прямоугольник" onClick={() => { setPaintTool('brush'); setPaintDrawMode('rect-fill') }}><span className="paint-shape-icon rect filled" /></button>
              <button className={paintDrawMode === 'rect-outline' ? 'active' : ''} type="button" title="Контурный прямоугольник" aria-label="Контурный прямоугольник" onClick={() => { setPaintTool('brush'); setPaintDrawMode('rect-outline') }}><span className="paint-shape-icon rect outline" /></button>
              <button className={paintDrawMode === 'circle-fill' ? 'active' : ''} type="button" title="Залитый круг" aria-label="Залитый круг" onClick={() => { setPaintTool('brush'); setPaintDrawMode('circle-fill') }}><span className="paint-shape-icon circle filled" /></button>
              <button className={paintDrawMode === 'circle-outline' ? 'active' : ''} type="button" title="Контурный круг" aria-label="Контурный круг" onClick={() => { setPaintTool('brush'); setPaintDrawMode('circle-outline') }}><span className="paint-shape-icon circle outline" /></button>
              <button className={paintDrawMode === 'bucket' ? 'active' : ''} type="button" title="Заливка области" aria-label="Заливка области" onClick={() => { setPaintTool('brush'); setPaintDrawMode('bucket') }}><PaintBucket size={19} strokeWidth={2.2} /></button>
              <label className="paint-color-dot" title="Цвет кисти" aria-label="Цвет кисти" style={{ '--paint-color': paintColor } as CSSProperties}>
                <Palette size={14} strokeWidth={2.2} aria-hidden="true" />
                <input aria-label="Цвет кисти" type="color" value={paintColor} onChange={(e) => setPaintColor(e.target.value)} />
              </label>
            </>
          )}
        </div>
      )}
      {paintMode === 'outpaint' && (
        <div
          ref={outpaintFrameRef}
          className={`paint-outpaint-frame${paintImage ? ' is-filled' : ''}`}
          style={{
            '--paint-stage-ratio': `${paintStageSize.width} / ${paintStageSize.height}`,
            width: `${outpaintFrameSize.width}px`,
            height: `${outpaintFrameSize.height}px`,
          } as CSSProperties}
          onPointerMove={moveOutpaintDrag}
          onPointerUp={stopOutpaintDrag}
          onPointerCancel={stopOutpaintDrag}
          onPointerLeave={stopOutpaintDrag}
        >
          {paintImage ? (
            <>
              <div className="paint-outpaint-guidance">Потяните изображение или его края, чтобы задать пустые области для дорисовки</div>
              <div className="paint-outpaint-empty-area" aria-hidden="true" />
              <div className="paint-outpaint-source" style={outpaintImageStyle} onPointerDown={(event) => startOutpaintDrag('image', event)}>
                <img src={apiUrl(paintImage)} alt="Исходное изображение" draggable={false} />
                <button className="paint-outpaint-handle left" type="button" aria-label="Изменить левое поле" onPointerDown={(event) => startOutpaintDrag('left', event)} />
                <button className="paint-outpaint-handle right" type="button" aria-label="Изменить правое поле" onPointerDown={(event) => startOutpaintDrag('right', event)} />
                <button className="paint-outpaint-handle top" type="button" aria-label="Изменить верхнее поле" onPointerDown={(event) => startOutpaintDrag('top', event)} />
                <button className="paint-outpaint-handle bottom" type="button" aria-label="Изменить нижнее поле" onPointerDown={(event) => startOutpaintDrag('bottom', event)} />
              </div>
              {paintOutpaintPreview && <img className="paint-outpaint-preview-ghost" src={paintOutpaintPreview} alt="Последний предпросмотр расширения" />}
            </>
          ) : null}
        </div>
      )}
      {paintMode === 'remove_bg' && (
        <div className={`paint-remove-bg-frame${paintImage ? ' is-filled' : ''}`}>
          {paintImage ? (
            <>
              <img src={apiUrl(paintImage)} alt="Изображение для удаления фона" />
              <span className="paint-remove-bg-note">Фон станет прозрачным, объект сохранится</span>
            </>
          ) : null}
        </div>
      )}
      {(paintMode === 'sketch' || paintMode === 'mask') && (
        <Stage
          ref={stageRef}
          width={paintStageSize.width}
          height={paintStageSize.height}
          className="paint-stage"
          style={{
            '--paint-stage-w': `${paintStageSize.width}px`,
            '--paint-stage-h': `${paintStageSize.height}px`,
            '--paint-stage-ratio': `${paintStageSize.width} / ${paintStageSize.height}`,
          } as CSSProperties}
          onMouseDown={(e) => startPaintLine(e.target.getStage() || null)}
          onMouseMove={(e) => extendPaintLine(e.target.getStage() || null)}
          onMouseUp={stopPaintLine}
          onMouseLeave={stopPaintLine}
          onTouchStart={startTouch}
          onTouchMove={moveTouch}
          onTouchEnd={endTouch}
        >
          <Layer>
            <Rect width={paintStageSize.width} height={paintStageSize.height} fill={paintMode === 'mask' || paintSketchImage ? 'rgba(0,0,0,0)' : paintCanvasBg === 'white' ? '#ffffff' : '#2b2f2c'} />
            {paintMode === 'sketch' && paintLines.length === 0 && !paintSketchImage && <Text text={sketchPlaceholderText} x={20} y={paintStageSize.height / 2 - 13} width={Math.max(1, paintStageSize.width - 40)} align="center" fill="#74806d" fontSize={Math.min(22, Math.max(13, paintStageSize.width / 38))} fontStyle="bold" />}
            {paintMode === 'mask' && paintLines.length === 0 && <Text text="Выделите область, которую нужно изменить" x={Math.max(20, paintStageSize.width / 2 - 210)} y={paintStageSize.height / 2 - 13} fill="#dfff22" fontSize={Math.min(20, Math.max(14, paintStageSize.width / 46))} fontStyle="bold" opacity={0.72} />}
            {paintLines.map((line, index) => line.fill ? renderPaintLine(line, `${index}-fill`) : null)}
            {paintLines.map((line, index) => line.fill ? null : renderPaintLine(line, `${index}-stroke`))}
          </Layer>
        </Stage>
      )}
      {(paintMode === 'sketch' || paintMode === 'mask') && (
        <div className="paint-workbench-actions">
          <button type="button" onClick={() => setPaintLines((lines) => lines.slice(0, -1))}><Undo2 size={14} strokeWidth={2.2} />Назад</button>
          <button type="button" onClick={() => setPaintLines([])}><Trash2 size={14} strokeWidth={2.2} />Очистить</button>
        </div>
      )}
      {paintMode === 'sketch' && (
        <div className="paint-workbench-import-actions" aria-label="Дополнительная загрузка эскиза">
          <button type="button" title="Загрузить эскиз" onClick={onUploadImage}><Upload size={14} strokeWidth={2.1} />Загрузить</button>
          <button type="button" title="Выбрать из галереи" onClick={onPickGallery}><Images size={14} strokeWidth={2.1} />Галерея</button>
          <button type="button" title="Взять последнее изображение" onClick={onUseLastImage}><History size={14} strokeWidth={2.1} />Последнее</button>
        </div>
      )}
      {needsPaintImage && !hasPaintImage && (
        <div className="paint-workbench-upload">
          <strong>{uploadTitle}</strong>
          <span>{uploadHint}</span>
          <div>
            <button type="button" onClick={onUploadImage}><Upload size={15} strokeWidth={2.1} />Загрузить</button>
            <button type="button" onClick={onPickGallery}><Images size={15} strokeWidth={2.1} />Галерея</button>
            <button type="button" onClick={onUseLastImage}><History size={15} strokeWidth={2.1} />Последнее</button>
          </div>
        </div>
      )}
      {needsPaintImage && hasPaintImage && (
        <button className="paint-workbench-remove" type="button" onClick={onRemoveImage}>Убрать изображение</button>
      )}
    </div>
  )
})

export default PaintWorkbench
