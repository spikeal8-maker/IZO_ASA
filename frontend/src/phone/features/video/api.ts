import { phoneFetch } from '../../core/http.ts'
import { waitForPhoneJob, type PhoneJob } from '../../core/jobs.ts'

export type PhoneVideoMode = 'text_to_video' | 'image_to_video' | 'first_last_frame' | 'reference_to_video'
export type PhoneVideoModel = {
  id: string
  provider?: string
  name: string
  description: string
  supportedResolutions: string[]
  supportedAspectRatios: string[]
  supportedDurations: number[]
  generateAudio: boolean | null
  available?: boolean
  unavailableReason?: string
  publicPricing?: { fromTokens?: number | null }
}
export type PhoneVideoConfig = { modes: Record<PhoneVideoMode, PhoneVideoModel[]>; videoSlots: number; feedPublicationEnabled?: boolean }
export type PhoneVideoHistoryItem = {
  id: string; mode: PhoneVideoMode; status: string; progress: number; prompt: string; createdAt: string; completedAt?: string | null
  model?: string; publicModelLabel?: string; duration?: number; resolution?: string; aspectRatio?: string; tokenCost?: number
  videoUrl?: string | null; galleryVideoId?: string | null; generateAudio?: boolean; galleryDeleted?: boolean
}
export type PhoneVideoGalleryFrame = { id: string; url: string; thumbnailUrl: string; width: number; height: number }
export type PhoneVideoRequest = { mode: PhoneVideoMode; model: string; prompt: string; duration: number; resolution: string; aspectRatio: string; generateAudio: boolean; firstFrame?: string | null; lastFrame?: string | null; references?: string[] }

export async function loadPhoneVideoConfig(signal?: AbortSignal): Promise<PhoneVideoConfig> {
  return phoneFetch('/api/video/config', { signal })
}

export async function estimatePhoneVideo(input: PhoneVideoRequest, signal?: AbortSignal): Promise<{ chargedTokens: number }> {
  return phoneFetch('/api/video/estimate', { method: 'POST', signal, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(input) })
}

export async function startPhoneVideo(input: PhoneVideoRequest, onChange?: (job: PhoneJob) => void): Promise<PhoneJob> {
  const started = await phoneFetch<{ id?: string }>('/api/video/generate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(input) })
  if (!started.id) throw new Error('Сервер не вернул номер видеозадания.')
  return waitForPhoneJob(started.id, { onChange, intervalMs: 1800 })
}

export async function loadPhoneVideoHistory(signal?: AbortSignal): Promise<PhoneVideoHistoryItem[]> {
  const payload = await phoneFetch<{ items?: PhoneVideoHistoryItem[] }>('/api/video/history?limit=30', { signal })
  return (payload.items || []).filter((item) => !item.galleryDeleted)
}

export async function loadPhoneVideoGalleryFrames(signal?: AbortSignal): Promise<PhoneVideoGalleryFrame[]> {
  const payload = await phoneFetch<{ items?: Array<Record<string, unknown>> }>('/api/gallery/items?limit=20&filter=image', { signal })
  return (payload.items || []).map((item) => ({ id: String(item.id || ''), url: String(item.viewerSrc || item.downloadUrl || item.url || ''), thumbnailUrl: String(item.thumbnailUrl || item.src || item.viewerSrc || item.url || ''), width: Number(item.width || 0), height: Number(item.height || 0) })).filter((item) => item.id && item.url)
}

export async function publishPhoneVideo(videoId: string, title: string): Promise<{ moderation?: string }> {
  return phoneFetch('/api/feed/publications', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ videoId, title: title.trim().slice(0, 120) || 'Новое видео', promptVisibility: 'open', allowRecreate: false }) })
}

export function fileToPhoneVideoFrame(file: File): Promise<string> {
  if (!/^image\/(jpeg|png|webp)$/i.test(file.type)) return Promise.reject(new Error('Можно использовать JPEG, PNG или WebP.'))
  if (file.size > 12_000_000) return Promise.reject(new Error('Изображение больше 12 МБ.'))
  return new Promise((resolve, reject) => { const reader = new FileReader(); reader.onerror = () => reject(new Error('Не удалось прочитать изображение.')); reader.onload = () => resolve(String(reader.result || '')); reader.readAsDataURL(file) })
}
