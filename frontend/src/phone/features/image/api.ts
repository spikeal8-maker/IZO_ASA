import { phoneFetch } from '../../core/http.ts'
import { waitForPhoneJob, type PhoneJob } from '../../core/jobs.ts'


export type PhoneImageModel = {
  id: string
  label: string
  provider: 'comfyui' | 'openrouter'
  modelProfile: string
  tokenHint: number
  supportedResolutionIds: string[]
}

export type PhoneImageMode = 'text_to_image' | 'image_to_image' | 'edit' | 'paint'

export type PhoneGalleryImage = {
  id: string
  url: string
  thumbnailUrl: string
  width: number
  height: number
}

export async function loadImageModels(signal?: AbortSignal): Promise<{ plan: string; modes: Record<string, { models: PhoneImageModel[]; presets: { fast?: string } }> }> {
  return phoneFetch('/api/model-access', { signal })
}

export async function startPhoneImage(input: {
  mode: PhoneImageMode
  prompt: string
  model: PhoneImageModel
  resolutionId: string
  width: number
  height: number
  inputImages: string[]
  canvas?: string
}, onChange?: (job: PhoneJob) => void): Promise<PhoneJob> {
  const body: Record<string, unknown> = {
    mode: input.mode, provider: input.model.provider, prompt: input.prompt, negativePrompt: '',
    seed: Math.floor(Math.random() * 2147483646) + 1, width: input.width, height: input.height,
    resolutionId: input.resolutionId, steps: 4, cfg: 1, guidance: 3.5, strength: .75,
    modelProfile: input.model.modelProfile, loras: [],
  }
  if (input.mode === 'image_to_image') body.inputImage1 = input.inputImages[0]
  if (input.mode === 'edit') body.inputImages = input.inputImages.map((image, index) => ({ index: index + 1, role: index === 0 ? 'base' : 'reference', image }))
  if (input.mode === 'paint') body.canvas = input.canvas
  const started = await phoneFetch<{ id?: string; jobId?: string }>('/api/generate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
  const jobId = String(started.id || started.jobId || '')
  if (!jobId) throw new Error('Сервер не вернул номер генерации.')
  return waitForPhoneJob(jobId, { onChange })
}

export async function loadPhoneGallery(signal?: AbortSignal): Promise<PhoneGalleryImage[]> {
  const payload = await phoneFetch<{ items?: Array<Record<string, unknown>> }>('/api/gallery/items?limit=20&filter=image', { signal })
  return (payload.items || []).map((item) => ({
    id: String(item.id || ''),
    url: String(item.viewerSrc || item.downloadUrl || item.url || item.image_url || item.display_url || ''),
    thumbnailUrl: String(item.thumbnailUrl || item.src || item.thumbnail_url || item.viewerSrc || item.url || item.image_url || ''),
    width: Number(item.width || 0), height: Number(item.height || 0),
  })).filter((item) => item.id && item.url)
}

export async function fileToPhoneImage(file: File): Promise<string> {
  if (!/^image\/(jpeg|png|webp)$/i.test(file.type)) throw new Error('Можно использовать JPEG, PNG или WebP.')
  if (file.size > 18_000_000) throw new Error('Изображение больше 18 МБ.')
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onerror = () => reject(new Error('Не удалось прочитать изображение.'))
    reader.onload = () => resolve(String(reader.result || ''))
    reader.readAsDataURL(file)
  })
}
