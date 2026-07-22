export const VIDEO_SOURCE_HANDOFF_KEY = 'izo:video-source-v1'
export const VIDEO_SOURCE_HANDOFF_VERSION = 1 as const
export const VIDEO_SOURCE_HANDOFF_TTL_MS = 10 * 60 * 1000
export const VIDEO_SOURCE_DEFAULT_PROMPT = 'Плавно оживи изображение. Сохрани внешность, форму объектов и композицию. Добавь естественное движение камеры, света и деталей окружения.'
export const VIDEO_SOURCE_UNAVAILABLE_MESSAGE = 'Исходное изображение больше недоступно. Выберите другое изображение.'

type HandoffStorage = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>

export type VideoSourceHandoffInput = {
  galleryImageId?: string
  mediaUrl: string
  thumbnailUrl?: string
  width?: number
  height?: number
  imagePrompt?: string
}

export type VideoSourceHandoff = {
  version: typeof VIDEO_SOURCE_HANDOFF_VERSION
  createdAt: number
  galleryImageId?: string
  mediaUrl: string
  thumbnailUrl?: string
  width?: number
  height?: number
  imagePrompt?: string
}

type VerifiedVideoSource =
  | { ok: true; source: VideoSourceHandoff }
  | { ok: false; message: typeof VIDEO_SOURCE_UNAVAILABLE_MESSAGE }

function browserStorage(storage?: HandoffStorage): HandoffStorage | null {
  if (storage) return storage
  if (typeof window === 'undefined') return null
  try { return window.sessionStorage } catch { return null }
}

export function normalizePrivateMediaPath(value: unknown): string | null {
  if (typeof value !== 'string') return null
  const candidate = value.trim()
  if (!candidate.startsWith('/') || candidate.startsWith('//')) return null
  try {
    const parsed = new URL(candidate, 'https://izo-internal.invalid')
    const privatePath = parsed.pathname.startsWith('/api/media/')
      || (parsed.pathname.startsWith('/media/') && !parsed.pathname.startsWith('/media/avatars/'))
    return privatePath ? parsed.pathname : null
  } catch {
    return null
  }
}

function positiveDimension(value: unknown): number | undefined {
  const numeric = Number(value)
  return Number.isFinite(numeric) && numeric > 0 ? Math.round(numeric) : undefined
}

export function createVideoSourceHandoff(input: VideoSourceHandoffInput, now = Date.now()): VideoSourceHandoff {
  const mediaUrl = normalizePrivateMediaPath(input.mediaUrl)
  if (!mediaUrl) throw new Error('Video source must use an internal private-media path.')
  const thumbnailUrl = normalizePrivateMediaPath(input.thumbnailUrl)
  const galleryImageId = String(input.galleryImageId || '').trim().slice(0, 256) || undefined
  const imagePrompt = String(input.imagePrompt || '').trim().slice(0, 4000) || undefined
  return {
    version: VIDEO_SOURCE_HANDOFF_VERSION,
    createdAt: now,
    galleryImageId,
    mediaUrl,
    thumbnailUrl: thumbnailUrl || undefined,
    width: positiveDimension(input.width),
    height: positiveDimension(input.height),
    imagePrompt,
  }
}

export function writeVideoSourceHandoff(input: VideoSourceHandoffInput, storage?: HandoffStorage, now = Date.now()): VideoSourceHandoff {
  const target = browserStorage(storage)
  if (!target) throw new Error('Session storage is unavailable.')
  const handoff = createVideoSourceHandoff(input, now)
  target.setItem(VIDEO_SOURCE_HANDOFF_KEY, JSON.stringify(handoff))
  return handoff
}

export function clearVideoSourceHandoff(storage?: HandoffStorage): void {
  try { browserStorage(storage)?.removeItem(VIDEO_SOURCE_HANDOFF_KEY) } catch { /* best effort */ }
}

export function readVideoSourceHandoff(storage?: HandoffStorage, now = Date.now()): VideoSourceHandoff | null {
  const target = browserStorage(storage)
  if (!target) return null
  try {
    const raw = target.getItem(VIDEO_SOURCE_HANDOFF_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as Partial<VideoSourceHandoff>
    const createdAt = Number(parsed.createdAt)
    const expired = !Number.isFinite(createdAt) || createdAt > now + 60_000 || now - createdAt > VIDEO_SOURCE_HANDOFF_TTL_MS
    if (parsed.version !== VIDEO_SOURCE_HANDOFF_VERSION || expired) throw new Error('Invalid or expired video source handoff.')
    return createVideoSourceHandoff({
      galleryImageId: parsed.galleryImageId,
      mediaUrl: String(parsed.mediaUrl || ''),
      thumbnailUrl: parsed.thumbnailUrl,
      width: parsed.width,
      height: parsed.height,
      imagePrompt: parsed.imagePrompt,
    }, createdAt)
  } catch {
    clearVideoSourceHandoff(target)
    return null
  }
}

export async function resolveVerifiedVideoSource(handoff: VideoSourceHandoff, verify: (path: string) => Promise<void>): Promise<VerifiedVideoSource> {
  try {
    await verify(handoff.mediaUrl)
    return { ok: true, source: handoff }
  } catch {
    return { ok: false, message: VIDEO_SOURCE_UNAVAILABLE_MESSAGE }
  }
}

export function closestVideoAspectRatio(handoff: VideoSourceHandoff, supported: string[]): string | null {
  if (!handoff.width || !handoff.height || !supported.length) return null
  const sourceRatio = handoff.width / handoff.height
  const candidates = supported.map((value) => {
    const [width, height] = value.split(':').map(Number)
    return { value, ratio: width > 0 && height > 0 ? width / height : Number.NaN }
  }).filter((item) => Number.isFinite(item.ratio))
  return candidates.sort((a, b) => Math.abs(Math.log(sourceRatio / a.ratio)) - Math.abs(Math.log(sourceRatio / b.ratio)))[0]?.value || null
}
