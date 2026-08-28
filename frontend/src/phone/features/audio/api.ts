export type PhoneTranscription = {
  ok: boolean
  text: string
  model?: string
  provider?: string
  usage?: Record<string, unknown>
}

export type PhoneAudioConfig = { transcriptionPublished: boolean; speechPublished: boolean; voices: Array<{ id: 'irina' | 'pavel'; name: string }>; speechMaxChars: number; transcriptionMaxBytes: number }

export async function loadPhoneAudioConfig(signal?: AbortSignal): Promise<PhoneAudioConfig> {
  const response = await fetch('/api/phone/audio/config', { credentials: 'include', signal })
  const payload = await response.json().catch(() => ({})) as PhoneAudioConfig & { detail?: string }
  if (!response.ok) throw new Error(payload.detail || 'Не удалось загрузить настройки звука.')
  return payload
}

export async function synthesizePhoneSpeech(text: string, voice: 'irina' | 'pavel', rate = 0): Promise<Blob> {
  const response = await fetch('/api/phone/audio/speech', {
    method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, voice, rate }),
  })
  if (!response.ok) {
    const payload = await response.json().catch(() => ({})) as { detail?: string }
    throw new Error(payload.detail || 'Не удалось озвучить текст.')
  }
  return response.blob()
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
