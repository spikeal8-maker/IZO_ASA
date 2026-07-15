type UnknownRecord = Record<string, unknown>

function record(value: unknown): UnknownRecord | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value) ? value as UnknownRecord : null
}

function text(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

function optionalText(value: unknown): string | undefined {
  const normalized = text(value).trim()
  return normalized || undefined
}

function finiteNumber(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined
}

export interface GalleryContractItem {
  id: string
  url: string
  thumbnailUrl: string
  mode: string
  promptOriginal: string
  createdAt: string
  resultImageId?: string
  modelProfile?: string
  tokenCost?: number | null
  generationTimeMs?: number
  width?: number
  height?: number
  aspectRatio?: string
}

export function normalizeGalleryItem(value: unknown, index = 0): GalleryContractItem | null {
  const item = record(value)
  if (!item) return null
  const url = text(item.viewerSrc || item.downloadUrl || item.url || item.src || item.thumbnailUrl)
  const thumbnailUrl = text(item.thumbnailUrl || item.src || item.viewerSrc || item.downloadUrl || item.url)
  if (!url || !thumbnailUrl) return null
  return {
    id: text(item.id || item.imageId) || `gallery-${index}-${thumbnailUrl}`,
    url,
    thumbnailUrl,
    mode: text(item.mode),
    promptOriginal: text(item.promptOriginal || item.prompt),
    createdAt: text(item.createdAt || item.date),
    resultImageId: optionalText(item.resultImageId),
    modelProfile: optionalText(item.modelProfile),
    tokenCost: finiteNumber(item.tokenCost) ?? null,
    generationTimeMs: finiteNumber(item.generationTimeMs),
    width: finiteNumber(item.width),
    height: finiteNumber(item.height),
    aspectRatio: optionalText(item.aspectRatio),
  }
}

export function normalizeGalleryPayload(value: unknown): GalleryContractItem[] {
  const payload = record(value)
  const items = Array.isArray(payload?.items) ? payload.items : Array.isArray(value) ? value : []
  return items.map(normalizeGalleryItem).filter((item): item is GalleryContractItem => item !== null)
}

export interface FeedContractItem {
  id: string
  displayUrl: string
  thumbnailUrl: string
  prompt: string
  createdAt: string
  aspectRatio: string
}

export function normalizeFeedPayload(value: unknown): FeedContractItem[] {
  const payload = record(value)
  const rows = Array.isArray(value)
    ? value
    : Array.isArray(payload?.items)
      ? payload.items
      : Array.isArray(payload?.publications) ? payload.publications : []
  return rows.flatMap((raw) => {
    const item = record(raw)
    if (!item) return []
    const displayUrl = text(item.display_url || item.thumbnail_url)
    const thumbnailUrl = text(item.thumbnail_url || item.display_url)
    const id = text(item.id)
    if (!id || !displayUrl || !thumbnailUrl) return []
    return [{
      id,
      displayUrl,
      thumbnailUrl,
      prompt: text(item.prompt || item.title),
      createdAt: text(item.created_at),
      aspectRatio: text(item.aspect_ratio) || '1:1',
    }]
  })
}

export interface GenerationContract {
  id: string
  status: string
  progress?: number
  message?: string
  resultUrl?: string
  resultImageId?: string
  width?: number
  height?: number
  error?: string
  createdAt?: string
}

export function normalizeGeneration(value: unknown): GenerationContract | null {
  const item = record(value)
  if (!item) return null
  const id = text(item.id || item.jobId)
  const status = text(item.status)
  if (!id || !status) return null
  return {
    id,
    status,
    progress: finiteNumber(item.progress),
    message: optionalText(item.message),
    resultUrl: optionalText(item.resultUrl || item.result_url),
    resultImageId: optionalText(item.resultImageId || item.result_image_id),
    width: finiteNumber(item.width),
    height: finiteNumber(item.height),
    error: optionalText(item.error),
    createdAt: optionalText(item.createdAt || item.created_at),
  }
}

export interface ModelContract {
  loras: string[]
}

export function normalizeModels(value: unknown): ModelContract {
  const payload = record(value)
  return {
    loras: Array.isArray(payload?.loras) ? payload.loras.filter((item): item is string => typeof item === 'string') : [],
  }
}

export interface AuthSessionContract {
  id: string
  provider?: string | null
  platform?: string | null
  ip_address?: string | null
  device?: string | null
  created_at?: string | null
  last_seen_at?: string | null
  expires_at?: string | null
  revoked_at?: string | null
  active: boolean
  current: boolean
}

export function normalizeAuthSessions(value: unknown): { sessions: AuthSessionContract[]; currentSessionId?: string } {
  const payload = record(value)
  const sessions = Array.isArray(payload?.sessions) ? payload.sessions.flatMap((raw) => {
    const item = record(raw)
    const id = text(item?.id)
    if (!item || !id) return []
    return [{
      id,
      provider: optionalText(item.provider),
      platform: optionalText(item.platform),
      ip_address: optionalText(item.ip_address),
      device: optionalText(item.device),
      created_at: optionalText(item.created_at),
      last_seen_at: optionalText(item.last_seen_at),
      expires_at: optionalText(item.expires_at),
      revoked_at: optionalText(item.revoked_at),
      active: item.active === true,
      current: item.current === true,
    }]
  }) : []
  return { sessions, currentSessionId: optionalText(payload?.current_session_id) }
}

export function safeJsonObject(value: unknown): UnknownRecord {
  return record(value) || {}
}
