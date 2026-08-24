export type PhoneTranscription = {
  ok: boolean
  text: string
  model?: string
  provider?: string
  usage?: Record<string, unknown>
}

export async function transcribePhoneAudio(file: File, durationMs: number, language = 'ru'): Promise<PhoneTranscription> {
  const body = new FormData()
  body.append('file', file)
  const response = await fetch(`/api/tools/transcribe?duration_ms=${Math.max(1000, Math.round(durationMs))}&language=${encodeURIComponent(language)}`, {
    method: 'POST',
    credentials: 'include',
    body,
  })
  const payload = await response.json().catch(() => ({})) as Partial<PhoneTranscription> & { detail?: string }
  if (!response.ok || !payload.ok || !payload.text) throw new Error(payload.detail || 'Не удалось распознать речь.')
  return payload as PhoneTranscription
}
