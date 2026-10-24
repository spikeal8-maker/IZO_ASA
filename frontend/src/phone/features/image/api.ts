import { phoneFetch, PhoneTransportError } from '../../core/http.ts'
import { beginImageGenerationCommand, acknowledgeImageGenerationCommand, completeImageGenerationCommand, rejectImageGenerationCommand } from '../../../studio/imageGenerationCommand.ts'
import { waitForPhoneJob, type PhoneJob } from '../../core/jobs.ts'


export type PhoneImageModel = {
  id: string
  label: string
  provider: 'comfyui' | 'openrouter'
  modelProfile: string
  tokenHint: number
  supportedResolutionIds: string[]
}

export type PhoneImageMode = 'text_to_image' | 'image_to_image' | 'edit' | 'paint' | 'inpaint' | 'outpaint' | 'remove_background'

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
  mask?: string
  inputRoles?: string[]
  faceLora?: { id: string; triggerWord?: string }
  faceStrength?: number
  outpaint?: { left: number; right: number; top: number; bottom: number }
}, onChange?: (job: PhoneJob) => void, signal?: AbortSignal): Promise<PhoneJob> {
  signal?.throwIfAborted()
  const body: Record<string, unknown> = {
    mode: input.mode, provider: input.model.provider, prompt: input.prompt, negativePrompt: '',
    width: input.width, height: input.height,
    resolutionId: input.resolutionId, steps: 4, cfg: 1, guidance: 3.5, strength: .75,
    modelProfile: input.model.modelProfile,
    loras: input.faceLora ? [{ id: input.faceLora.id, strength: Math.max(.25, Math.min(1, (input.faceStrength || 75) / 100)), triggerWord: input.faceLora.triggerWord || '' }] : [],
  }
  if (['image_to_image', 'inpaint', 'outpaint', 'remove_background'].includes(input.mode)) body.inputImage1 = input.inputImages[0]
  if (input.mode === 'edit') body.inputImages = input.inputImages.map((image, index) => ({ index: index + 1, role: index === 0 ? 'base' : input.inputRoles?.[index] || 'reference', image }))
  if (input.mode === 'paint') body.canvas = input.canvas
  if (input.mode === 'inpaint') body.maskImage = input.mask
  if (input.mode === 'outpaint') body.outpaint = input.outpaint
  const command = await beginImageGenerationCommand('phone', body)
  let jobId = command.acceptedJobId || ''
  if (!jobId) {
    let started: { id?: string; jobId?: string }
    try {
      started = await phoneFetch<{ id?: string; jobId?: string }>('/api/generate', {
        method: 'POST', signal,
        headers: { 'Content-Type': 'application/json', 'Idempotency-Key': command.key },
        body: command.body,
      })
    } catch (error) {
      if (error instanceof PhoneTransportError) rejectImageGenerationCommand('phone', command.ownerId, command.key, error.status)
      throw error
    }
    signal?.throwIfAborted()
    jobId = String(started.id || started.jobId || '')
    if (!jobId) throw new Error('Сервер не вернул номер генерации.')
    acknowledgeImageGenerationCommand('phone', command.ownerId, command.key, jobId)
  }
  const completed = await waitForPhoneJob(jobId, { onChange, signal })
  if (completed.terminal) await completeImageGenerationCommand('phone', jobId).catch(() => undefined)
  return completed
}

export async function loadFaceLora(signal?: AbortSignal): Promise<{ id: string; triggerWord?: string } | null> {
  const payload = await phoneFetch<{ loras?: string[] }>('/api/models', { signal })
  const values = (payload.loras || []).filter((item) => item && item !== 'none')
  const id = values.find((item) => /bfs|face|head/i.test(item)) || values[0]
  return id ? { id } : null
}

export async function publishPhoneImage(imageId: string, title: string): Promise<{ publication?: { id?: string }; moderation?: string }> {
  return phoneFetch('/api/feed/publications', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ imageId, title: title.trim().slice(0, 120) || 'Новая работа', promptVisibility: 'open', allowRecreate: true }),
  })
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
