import { Download, Volume2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { loadPhoneAudioConfig, synthesizePhoneSpeech, type PhoneAudioConfig } from './phone/features/audio/api'
import './desktopAudioWorkspace.css'

type Props = { authed: boolean; onRequireAuth: () => void }

export default function DesktopAudioWorkspace({ authed, onRequireAuth }: Props) {
  const [config, setConfig] = useState<PhoneAudioConfig | null>(null)
  const [text, setText] = useState('')
  const [voice, setVoice] = useState<'irina' | 'pavel'>('irina')
  const [audioUrl, setAudioUrl] = useState('')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!authed) return
    const controller = new AbortController()
    void loadPhoneAudioConfig(controller.signal)
      .then(setConfig)
      .catch((error: Error) => setMessage(error.message))
    return () => controller.abort()
  }, [authed])

  useEffect(() => () => { if (audioUrl) URL.revokeObjectURL(audioUrl) }, [audioUrl])

  const synthesize = async () => {
    if (!authed) { onRequireAuth(); return }
    if (!text.trim() || busy) return
    setBusy(true)
    setMessage('Озвучиваем текст…')
    try {
      const blob = await synthesizePhoneSpeech(text.trim(), voice)
      if (audioUrl) URL.revokeObjectURL(audioUrl)
      setAudioUrl(URL.createObjectURL(blob))
      setMessage('Аудиофайл готов.')
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Не удалось озвучить текст.')
    } finally {
      setBusy(false)
    }
  }

  if (!authed) return <main className="desktop-audio"><section><Volume2 /><h1>Звук</h1><p>Войдите, чтобы пользоваться локальным озвучиванием.</p><button type="button" onClick={onRequireAuth}>Войти</button></section></main>
  if (config && !config.speechPublished) return <main className="desktop-audio"><section><Volume2 /><h1>Звук</h1><p>Озвучивание сейчас отключено администратором.</p></section></main>

  return <main className="desktop-audio"><section>
    <header><Volume2 /><div><h1>Озвучивание текста</h1><p>Локальные голоса сервера, без внешнего API.</p></div></header>
    <textarea value={text} maxLength={config?.speechMaxChars || 4000} placeholder="Введите текст для озвучивания" onChange={(event) => setText(event.target.value)} />
    <div className="desktop-audio-controls"><label>Голос<select value={voice} onChange={(event) => setVoice(event.target.value as 'irina' | 'pavel')}>{(config?.voices || []).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><button type="button" disabled={busy || !text.trim()} onClick={() => void synthesize()}>{busy ? 'Озвучиваем…' : 'Озвучить'}</button></div>
    {message && <p role="status" className="desktop-audio-message">{message}</p>}
    {audioUrl && <div className="desktop-audio-result"><audio controls src={audioUrl} /><a href={audioUrl} download="izo-asa-voice.wav"><Download /> Скачать WAV</a></div>}
  </section></main>
}
