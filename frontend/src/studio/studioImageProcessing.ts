// ARCH-FE-STUDIO-001A: browser-side image sizing, canvas transforms and paint
// prompt composition. Off-screen canvases are the only DOM objects created.
import type { PaintLine, PaintOutpaintPlacement } from '../paintTypes'
import { apiUrl } from './studioApi'
import { shapeFromSize } from './studioHelpers'
import type { PreviewShape } from './studioTypes'

export const DEFAULT_PAINT_SKETCH_PROMPT = 'Transform this sketch into a hyper-realistic cinematic scene. Interpret the lines as real-world objects with high-quality textures, cinematic lighting, natural shadows, depth, realistic materials and clean composition. Preserve the exact composition, silhouettes, poses, proportions and spatial relationships from the sketch. Scene description:'
export const DEFAULT_PAINT_MASK_PROMPT = 'Edit only the masked area and follow the user instruction literally for that selected region. Seamlessly blend the change with the surrounding scene while preserving lighting, shadows, perspective, depth of field and photo grain. Do not change unmasked areas.'
export const DEFAULT_PAINT_OUTPAINT_PROMPT = 'Extend the composition of this image. Replace black or empty spaces with a logical continuation of the background and foreground. Match perspective, lighting, color palette and texture so the transition is invisible. Scene description:'
export const DEFAULT_I2I_EDIT_PROMPT = 'Edit Image 1 according to the user request. Apply the requested change clearly and literally. Preserve the subject, composition, geometry, lighting, background and every attribute that the user did not ask to change. User request:'

export function loadImageShape(url: string): Promise<PreviewShape> {
  return new Promise((resolve) => {
    const img = new Image()
    img.onload = () => resolve(shapeFromSize(img.naturalWidth, img.naturalHeight))
    img.onerror = () => resolve('square')
    img.src = apiUrl(url)
  })
}

export function fitGenerationDimension(value: number) {
  return Math.max(512, Math.min(1536, Math.round(value / 16) * 16))
}

export function comfySafeGenerationSize(size: { width: number; height: number }) {
  const width = Math.max(512, size.width)
  const height = Math.max(512, size.height)
  const maxPixels = 2_050_000
  const maxSide = 1792
  const scale = Math.min(1, maxSide / Math.max(width, height), Math.sqrt(maxPixels / Math.max(1, width * height)))
  return {
    width: Math.max(512, Math.round((width * scale) / 16) * 16),
    height: Math.max(512, Math.round((height * scale) / 16) * 16),
  }
}

export function sameGenerationSize(a: { width: number; height: number }, b: { width: number; height: number }) {
  return a.width === b.width && a.height === b.height
}

export function meaningfulPaintLines(lines: PaintLine[]) {
  return lines.some((line) => {
    if (line.kind === 'bitmap' && line.image) return true
    if (line.fill && line.points.length >= 4) {
      return Math.abs((line.points[2] || 0) - (line.points[0] || 0))
        * Math.abs((line.points[3] || 0) - (line.points[1] || 0)) >= 64
    }
    let length = 0
    for (let index = 2; index < line.points.length; index += 2) {
      length += Math.hypot(
        (line.points[index] || 0) - (line.points[index - 2] || 0),
        (line.points[index + 1] || 0) - (line.points[index - 1] || 0),
      )
    }
    return length >= Math.max(8, line.strokeWidth)
  })
}

export function outpaintPaddingOnly(placement: PaintOutpaintPlacement): PaintOutpaintPlacement {
  return {
    left: Math.max(0, Math.round(placement.left || 0)),
    right: Math.max(0, Math.round(placement.right || 0)),
    top: Math.max(0, Math.round(placement.top || 0)),
    bottom: Math.max(0, Math.round(placement.bottom || 0)),
  }
}

export async function outpaintRequestSizeFromSource(
  inputImage: string | undefined,
  placement: PaintOutpaintPlacement,
  base: { width: number; height: number },
) {
  if (!inputImage) return base
  const image = await new Promise<HTMLImageElement>((resolve, reject) => {
    const img = new Image()
    img.onload = () => resolve(img)
    img.onerror = reject
    img.src = apiUrl(inputImage)
  }).catch(() => undefined)
  if (!image) return base
  const sourceWidth = Math.max(1, image.naturalWidth || image.width)
  const sourceHeight = Math.max(1, image.naturalHeight || image.height)
  const padding = outpaintPaddingOnly(placement)
  const sourceScale = Math.min(base.width / sourceWidth, base.height / sourceHeight)
  return {
    width: Math.max(512, Math.round(((sourceWidth + padding.left + padding.right) * sourceScale) / 16) * 16),
    height: Math.max(512, Math.round(((sourceHeight + padding.top + padding.bottom) * sourceScale) / 16) * 16),
  }
}

export function composeI2IEditPrompt(userPrompt: string) {
  const user = userPrompt.trim()
  return user ? `${DEFAULT_I2I_EDIT_PROMPT}\n\n${user}` : DEFAULT_I2I_EDIT_PROMPT
}

export async function resizeUploadImage(file: File): Promise<string> {
  const sourceUrl = URL.createObjectURL(file)
  try {
    const image = await new Promise<HTMLImageElement>((resolve, reject) => {
      const img = new Image()
      img.onload = () => resolve(img)
      img.onerror = reject
      img.src = sourceUrl
    })
    const maxSide = Math.max(image.naturalWidth || image.width, image.naturalHeight || image.height)
    const scale = Math.min(1, 1536 / Math.max(1, maxSide))
    const width = Math.max(16, Math.round(((image.naturalWidth || image.width) * scale) / 16) * 16)
    const height = Math.max(16, Math.round(((image.naturalHeight || image.height) * scale) / 16) * 16)
    const canvas = document.createElement('canvas')
    canvas.width = width
    canvas.height = height
    const ctx = canvas.getContext('2d')
    if (!ctx) throw new Error('canvas_unavailable')
    ctx.drawImage(image, 0, 0, width, height)
    return canvas.toDataURL('image/jpeg', 0.9)
  } finally {
    URL.revokeObjectURL(sourceUrl)
  }
}

export async function imageRequestSizeFromSource(source: string | undefined, fallback: { width: number; height: number }) {
  if (!source) return fallback
  const image = await new Promise<HTMLImageElement>((resolve, reject) => {
    const img = new Image()
    img.onload = () => resolve(img)
    img.onerror = reject
    img.src = source
  }).catch(() => undefined)
  const sourceWidth = image?.naturalWidth || fallback.width
  const sourceHeight = image?.naturalHeight || fallback.height
  const maxSide = 1536
  const scale = Math.min(1, maxSide / Math.max(sourceWidth, sourceHeight))
  return {
    width: fitGenerationDimension(sourceWidth * scale),
    height: fitGenerationDimension(sourceHeight * scale),
  }
}

export async function loadHtmlImage(source: string): Promise<HTMLImageElement | undefined> {
  return new Promise<HTMLImageElement>((resolve, reject) => {
    const img = new Image()
    img.onload = () => resolve(img)
    img.onerror = reject
    img.src = source
  }).catch(() => undefined)
}

export async function createPaintMask(inputImage: string | undefined, lines: PaintLine[], stageSize: { width: number; height: number }) {
  if (!inputImage) return undefined
  const image = await loadHtmlImage(inputImage)
  if (!image) return undefined
  const canvas = document.createElement('canvas')
  canvas.width = image.naturalWidth || image.width
  canvas.height = image.naturalHeight || image.height
  const ctx = canvas.getContext('2d')
  if (!ctx) return undefined
  ctx.fillStyle = '#000'
  ctx.fillRect(0, 0, canvas.width, canvas.height)
  const scale = Math.min(stageSize.width / canvas.width, stageSize.height / canvas.height)
  const offsetX = (stageSize.width - canvas.width * scale) / 2
  const offsetY = (stageSize.height - canvas.height * scale) / 2
  const map = (x: number, y: number) => [
    Math.max(0, Math.min(canvas.width, (x - offsetX) / scale)),
    Math.max(0, Math.min(canvas.height, (y - offsetY) / scale)),
  ]
  for (const line of lines) {
    ctx.save()
    ctx.strokeStyle = line.tool === 'eraser' ? '#000' : '#fff'
    ctx.fillStyle = line.tool === 'eraser' ? '#000' : '#fff'
    ctx.lineCap = 'round'
    ctx.lineJoin = 'round'
    ctx.lineWidth = Math.max(1, line.strokeWidth / Math.max(0.1, scale))
    if (line.kind === 'rect' || line.kind === 'circle') {
      const [x1 = 0, y1 = 0, x2 = x1, y2 = y1] = line.points
      const [mx1, my1] = map(x1, y1)
      const [mx2, my2] = map(x2, y2)
      const x = Math.min(mx1, mx2)
      const y = Math.min(my1, my2)
      const w = Math.abs(mx2 - mx1)
      const h = Math.abs(my2 - my1)
      if (line.kind === 'circle') {
        ctx.beginPath()
        ctx.ellipse(x + w / 2, y + h / 2, w / 2, h / 2, 0, 0, Math.PI * 2)
        if (line.fill === false) ctx.stroke()
        else ctx.fill()
      } else if (line.fill === false) ctx.strokeRect(x, y, w, h)
      else ctx.fillRect(x, y, w, h)
    } else {
      ctx.beginPath()
      for (let i = 0; i < line.points.length; i += 2) {
        const [x, y] = map(line.points[i] || 0, line.points[i + 1] || 0)
        if (i === 0) ctx.moveTo(x, y)
        else ctx.lineTo(x, y)
      }
      ctx.stroke()
    }
    ctx.restore()
  }
  return canvas.toDataURL('image/png')
}

export async function createOutpaintPreview(inputImage: string | undefined, placement: PaintOutpaintPlacement, target: { width: number; height: number }) {
  if (!inputImage) return undefined
  const image = await new Promise<HTMLImageElement>((resolve, reject) => {
    const img = new Image()
    img.onload = () => resolve(img)
    img.onerror = reject
    img.src = inputImage
  }).catch(() => undefined)
  if (!image) return undefined
  const sourceWidth = image.naturalWidth || image.width
  const sourceHeight = image.naturalHeight || image.height
  const canvas = document.createElement('canvas')
  canvas.width = Math.max(256, Math.round(target.width || 1024))
  canvas.height = Math.max(256, Math.round(target.height || 1024))
  const ctx = canvas.getContext('2d')
  if (!ctx) return undefined
  ctx.fillStyle = '#030403'
  ctx.fillRect(0, 0, canvas.width, canvas.height)
  ctx.fillStyle = 'rgba(182, 207, 18, .08)'
  for (let x = -canvas.height; x < canvas.width; x += 24) ctx.fillRect(x, 0, 10, canvas.height)
  const hasPlacement = typeof placement.sourceX === 'number'
    && typeof placement.sourceY === 'number'
    && typeof placement.sourceW === 'number'
    && typeof placement.sourceH === 'number'
  const frameW = Math.max(1, placement.frameW || target.width || canvas.width)
  const frameH = Math.max(1, placement.frameH || target.height || canvas.height)
  const scaleX = canvas.width / frameW
  const scaleY = canvas.height / frameH
  const finalWidth = Math.max(1, sourceWidth + Math.max(0, placement.left) + Math.max(0, placement.right))
  const finalHeight = Math.max(1, sourceHeight + Math.max(0, placement.top) + Math.max(0, placement.bottom))
  const x = hasPlacement ? Math.round((placement.sourceX || 0) * scaleX) : Math.round(Math.max(0, placement.left) * canvas.width / finalWidth)
  const y = hasPlacement ? Math.round((placement.sourceY || 0) * scaleY) : Math.round(Math.max(0, placement.top) * canvas.height / finalHeight)
  const w = hasPlacement ? Math.max(1, Math.round((placement.sourceW || frameW) * scaleX)) : Math.max(1, Math.round(sourceWidth * canvas.width / finalWidth))
  const h = hasPlacement ? Math.max(1, Math.round((placement.sourceH || frameH) * scaleY)) : Math.max(1, Math.round(sourceHeight * canvas.height / finalHeight))
  ctx.drawImage(image, x, y, w, h)
  ctx.strokeStyle = '#b6cf12'
  ctx.lineWidth = Math.max(2, Math.round(Math.min(canvas.width, canvas.height) / 240))
  ctx.strokeRect(x + 1, y + 1, Math.max(1, w - 2), Math.max(1, h - 2))
  return canvas.toDataURL('image/jpeg', 0.9)
}

export function paintStageForResolution(resolution: { width: number; height: number }) {
  const maxSide = 1024
  const width = Math.max(1, resolution.width)
  const height = Math.max(1, resolution.height)
  if (width >= height) {
    return { width: maxSide, height: Math.max(256, Math.round((maxSide * height) / width)) }
  }
  return { width: Math.max(256, Math.round((maxSide * width) / height)), height: maxSide }
}

export function composePaintPrompt(basePrompt: string, userPrompt: string) {
  const base = basePrompt.trim()
  const user = userPrompt.trim()
  if (!user) return base
  const normalizedUser = user.toLowerCase()
  const baseLead = base.slice(0, 42).toLowerCase()
  return normalizedUser.includes(baseLead) ? user : `${base}\n\n${user}`
}
