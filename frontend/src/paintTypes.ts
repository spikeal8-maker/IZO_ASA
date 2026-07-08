export type PaintSubMode = 'sketch' | 'mask' | 'outpaint' | 'remove_bg'
export type PaintTool = 'brush' | 'eraser'
export type PaintDrawMode = 'free' | 'line' | 'rect' | 'circle'

export type PaintLine = {
  tool: PaintTool
  kind?: PaintDrawMode
  color?: string
  fill?: boolean
  strokeWidth: number
  points: number[]
}

