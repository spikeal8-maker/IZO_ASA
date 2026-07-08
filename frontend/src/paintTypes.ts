export type PaintSubMode = 'sketch' | 'mask' | 'outpaint' | 'remove_bg'
export type PaintTool = 'brush' | 'eraser'
export type PaintDrawMode = 'free' | 'line' | 'rect-outline' | 'rect-fill' | 'circle-outline' | 'circle-fill' | 'bucket'
export type PaintLineKind = 'free' | 'line' | 'rect' | 'circle' | 'bitmap'

export type PaintLine = {
  tool: PaintTool
  kind?: PaintLineKind
  color?: string
  fill?: boolean
  image?: string
  strokeWidth: number
  points: number[]
}

