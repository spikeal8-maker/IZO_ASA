export type PublicFeedVideoHistoryItem = {
  id: string
  mode: 'text_to_video'
  status: 'completed'
  progress: 100
  prompt: string
  createdAt: string
  model: string
  publicModelLabel: string
  duration: number
  resolution: string
  aspectRatio: string
  generateAudio: boolean
  videoUrl: string
  publicFeedItem: true
}

export type PublicFeedImageHistoryItem = {
  id: string
  mediaType: 'image'
  url: string
  thumbnailUrl: string
  width: number
  height: number
  promptOriginal: string
  createdAt: string
  aspectRatio: string
  modelProfile: string
}

export type PublicFeedHistory = {
  videos: PublicFeedVideoHistoryItem[]
  images: PublicFeedImageHistoryItem[]
}

function feedDimensions(value: unknown): { width: number; height: number } {
  const match = String(value || '').match(/(\d+)\s*[×x]\s*(\d+)/i)
  if (!match) return { width: 0, height: 0 }
  return { width: Number(match[1]) || 0, height: Number(match[2]) || 0 }
}

export function normalizeVideoFeedHistory(value: unknown): PublicFeedHistory {
  const payload = value && typeof value === 'object' ? value as { items?: unknown[] } : {}
  const rows = Array.isArray(payload.items) ? payload.items : []
  const videos: PublicFeedVideoHistoryItem[] = []
  const images: PublicFeedImageHistoryItem[] = []
  rows.forEach((raw, index) => {
    if (!raw || typeof raw !== 'object') return
    const item = raw as Record<string, unknown>
    const id = String(item.id || `public-${index}`)
    const mediaType = String(item.media_type || 'image').toLowerCase()
    const createdAt = String(item.created_at || '')
    const prompt = String(item.prompt || item.title || '')
    const aspectRatio = String(item.aspect_ratio || item.native_aspect_ratio || '1:1')
    const thumbnailUrl = String(item.thumbnail_url || item.image_url || '')
    if (mediaType === 'video') {
      const videoUrl = String(item.video_url || item.video_preview_url || '')
      if (!videoUrl) return
      videos.push({
        id: `feed-video-${id}`,
        mode: 'text_to_video',
        status: 'completed',
        progress: 100,
        prompt,
        createdAt,
        model: String(item.model || ''),
        publicModelLabel: String(item.model || 'Видео из ленты'),
        duration: Math.max(0, Math.round(Number(item.duration_ms || 0) / 1000)),
        resolution: String(item.resolution || ''),
        aspectRatio,
        generateAudio: Boolean(item.has_audio),
        videoUrl,
        publicFeedItem: true,
      })
      return
    }
    const source = String(item.image_url || item.display_url || thumbnailUrl)
    if (!source) return
    const dimensions = feedDimensions(item.resolution)
    images.push({
      id: `feed-image-${id}`,
      mediaType: 'image',
      url: source,
      thumbnailUrl: thumbnailUrl || source,
      width: dimensions.width,
      height: dimensions.height,
      promptOriginal: prompt,
      createdAt,
      aspectRatio,
      modelProfile: String(item.model || ''),
    })
  })
  return { videos, images }
}
