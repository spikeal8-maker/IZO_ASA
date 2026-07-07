import { forwardRef, useImperativeHandle, useLayoutEffect, useRef } from 'react'
import type { CSSProperties, Dispatch, RefObject, SetStateAction } from 'react'
import { Brush, Circle as CircleIcon, Eraser, Palette, Slash, Square as SquareIcon } from 'lucide-react'
import { Circle, Layer, Line, Rect, Stage, Text } from 'react-konva'
import type { Stage as KonvaStage } from 'konva/lib/Stage'
import type { PaintDrawMode, PaintLine, PaintSubMode, PaintTool } from './paintTypes'

export type PaintWorkbenchHandle = {
  toDataURL: () => string | undefined
}

type PaintModeMeta = Record<PaintSubMode, { label: string; hint: string }>

type Props = {
  apiUrl: (path: string) => string
  workbenchRef: RefObject<HTMLDivElement | null>
  paintMode: PaintSubMode
  paintModeMeta: PaintModeMeta
  paintImage?: string
  paintSketchImage?: string
  paintOutpaintPreview?: string
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
  paintFillShape: boolean
  paintCanvasBg: 'white' | 'gray'
  onReady?: () => void
}

function paintPoint(stage: KonvaStage | null) {
  const pos = stage?.getPointerPosition()
  return [pos?.x || 0, pos?.y || 0]
}

const PaintWorkbench = forwardRef<PaintWorkbenchHandle, Props>(function PaintWorkbench({
  apiUrl,
  workbenchRef,
  paintMode,
  paintModeMeta,
  paintImage,
  paintSketchImage,
  paintOutpaintPreview,
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
  paintFillShape,
  paintCanvasBg,
  onReady,
}, ref) {
  const stageRef = useRef<KonvaStage>(null)
  const drawingRef = useRef(false)

  useImperativeHandle(ref, () => ({
    toDataURL: () => stageRef.current?.toDataURL({ pixelRatio: 1 }),
  }), [])

  useLayoutEffect(() => {
    onReady?.()
  }, [onReady])

  function startPaintLine(stage: KonvaStage | null) {
    if (paintMode === 'outpaint' || paintMode === 'remove_bg') return
    drawingRef.current = true
    const point = paintPoint(stage)
    const kind = paintDrawMode
    setPaintLines((lines) => lines.concat({
      tool: paintTool,
      kind,
      color: paintMode === 'mask' ? '#dfff22' : paintColor,
      fill: paintFillShape,
      strokeWidth: paintBrushSize,
      points: point.concat(point),
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

  const renderPaintLine = (line: PaintLine, index: number) => {
    const color = line.tool === 'eraser' ? (paintMode === 'mask' ? 'rgba(0,0,0,.8)' : (paintCanvasBg === 'white' ? '#fff' : '#2b2f2c')) : (line.color || paintColor)
    const width = line.tool === 'eraser' ? line.strokeWidth * 1.7 : line.strokeWidth
    if (line.kind === 'rect' || line.kind === 'circle') {
      const [x1 = 0, y1 = 0, x2 = x1, y2 = y1] = line.points
      const x = Math.min(x1, x2)
      const y = Math.min(y1, y2)
      const w = Math.abs(x2 - x1)
      const h = Math.abs(y2 - y1)
      if (line.kind === 'circle') {
        return <Circle key={index} x={x + w / 2} y={y + h / 2} radius={Math.max(w, h) / 2} stroke={color} strokeWidth={width} fill={line.fill ? color : undefined} opacity={line.tool === 'eraser' ? 1 : .9} />
      }
      return <Rect key={index} x={x} y={y} width={w} height={h} stroke={color} strokeWidth={width} fill={line.fill ? color : undefined} opacity={line.tool === 'eraser' ? 1 : .9} />
    }
    return <Line key={index} points={line.points} stroke={color} strokeWidth={width} tension={0.45} lineCap="round" lineJoin="round" opacity={paintMode === 'mask' && line.tool !== 'eraser' ? .78 : 1} />
  }

  return (
    <div ref={workbenchRef} className={`paint-workbench mode-${paintMode}`}>
      {((paintMode === 'sketch' && paintSketchImage) || (paintMode !== 'sketch' && paintImage)) && (
        <img
          className={`paint-workbench-image${paintMode === 'sketch' ? ' sketch' : ''}`}
          src={apiUrl(paintMode === 'sketch' ? paintSketchImage! : paintImage!)}
          alt=""
          aria-hidden="true"
          style={paintMode === 'sketch' ? {
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
              <button className={paintDrawMode === 'rect' ? 'active' : ''} type="button" title="Прямоугольник" aria-label="Прямоугольник" onClick={() => { setPaintTool('brush'); setPaintDrawMode('rect') }}><SquareIcon size={19} strokeWidth={2.2} /></button>
              <button className={paintDrawMode === 'circle' ? 'active' : ''} type="button" title="Круг" aria-label="Круг" onClick={() => { setPaintTool('brush'); setPaintDrawMode('circle') }}><CircleIcon size={19} strokeWidth={2.2} /></button>
              <label className="paint-color-dot" title="Цвет кисти" aria-label="Цвет кисти" style={{ '--paint-color': paintColor } as CSSProperties}>
                <Palette size={14} strokeWidth={2.2} aria-hidden="true" />
                <input aria-label="Цвет кисти" type="color" value={paintColor} onChange={(e) => setPaintColor(e.target.value)} />
              </label>
            </>
          )}
          {paintMode === 'mask' && (
            <button className={paintDrawMode === 'rect' ? 'active' : ''} type="button" title="Прямоугольная маска" aria-label="Прямоугольная маска" onClick={() => { setPaintTool('brush'); setPaintDrawMode('rect') }}><SquareIcon size={19} strokeWidth={2.2} /></button>
          )}
        </div>
      )}
      {paintMode === 'outpaint' && (
        <div className="paint-outpaint-frame">
          {paintOutpaintPreview ? <img src={paintOutpaintPreview} alt="Предпросмотр расширения" /> : paintImage ? <img src={apiUrl(paintImage)} alt="Исходное изображение" /> : <span>Загрузите изображение для расширения</span>}
        </div>
      )}
      {paintMode === 'remove_bg' && (
        <div className="paint-remove-bg-frame">
          {paintImage ? <img src={apiUrl(paintImage)} alt="Изображение для удаления фона" /> : <span>Загрузите изображение</span>}
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
          onTouchStart={(e) => { e.evt.preventDefault(); startPaintLine(e.target.getStage() || null) }}
          onTouchMove={(e) => { e.evt.preventDefault(); extendPaintLine(e.target.getStage() || null) }}
          onTouchEnd={stopPaintLine}
        >
          <Layer>
            <Rect width={paintStageSize.width} height={paintStageSize.height} fill={paintMode === 'mask' || paintSketchImage ? 'rgba(0,0,0,0)' : paintCanvasBg === 'white' ? '#ffffff' : '#2b2f2c'} />
            {paintMode === 'sketch' && paintLines.length === 0 && !paintSketchImage && <Text text="Нарисуйте эскиз" x={paintStageSize.width / 2 - 94} y={paintStageSize.height / 2 - 13} fill="#74806d" fontSize={22} fontStyle="bold" />}
            {paintMode === 'mask' && paintLines.length === 0 && <Text text="Закрасьте область маской" x={paintStageSize.width / 2 - 142} y={paintStageSize.height / 2 - 13} fill="#dfff22" fontSize={20} fontStyle="bold" opacity={0.72} />}
            {paintLines.map(renderPaintLine)}
          </Layer>
        </Stage>
      )}
      {(paintMode === 'sketch' || paintMode === 'mask') && (
        <div className="paint-workbench-actions">
          <button type="button" onClick={() => setPaintLines((lines) => lines.slice(0, -1))}>Назад</button>
          <button type="button" onClick={() => setPaintLines([])}>Очистить</button>
        </div>
      )}
      <div className="paint-workbench-badge">{paintModeMeta[paintMode].label}</div>
    </div>
  )
})

export default PaintWorkbench
