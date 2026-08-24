import { useEffect, useRef, useState } from 'react'
import { Check, Copy, Download, FileAudio, Mic, Pause, Play, RotateCcw, Trash2, Upload } from 'lucide-react'

import { transcribePhoneAudio } from './api.ts'
import './phoneAudio.css'

type AudioEntry = {
  id: string
  name: string
  createdAt: string
  durationMs: number
  text: string
  url: string
}

function recordingType() {
  return ['audio/webm;codecs=opus', 'audio/ogg;codecs=opus', 'audio/webm'].find((value) => MediaRecorder.isTypeSupported(value)) || ''
}

function extensionFor(type: string) {
  return type.includes('ogg') ? 'ogg' : 'webm'
}

function formatTime(milliseconds: number) {
  const seconds = Math.max(0, Math.round(milliseconds / 1000))
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
}

async function mediaDuration(file: File): Promise<number> {
  const url = URL.createObjectURL(file)
  try {
    return await new Promise((resolve) => {
      const audio = new Audio()
      const done = () => resolve(Number.isFinite(audio.duration) ? Math.max(1000, audio.duration * 1000) : 1000)
      audio.onloadedmetadata = done
      audio.onerror = () => resolve(1000)
      audio.src = url
    })
  } finally {
    URL.revokeObjectURL(url)
  }
}

export default function PhoneAudioWorkspace({ offline }: { offline: boolean }) {
  const [entries, setEntries] = useState<AudioEntry[]>([])
  const [selected, setSelected] = useState<AudioEntry | null>(null)
  const [recording, setRecording] = useState(false)
  const [busy, setBusy] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [message, setMessage] = useState('')
  const [copied, setCopied] = useState(false)
  const recorderRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const startedRef = useRef(0)
  const heldRef = useRef(false)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const fileRef = useRef<HTMLInputElement | null>(null)
  const entriesRef = useRef<AudioEntry[]>([])

  useEffect(() => {
    if (!recording) return
    const timer = window.setInterval(() => setElapsed(Date.now() - startedRef.current), 100)
    return () => window.clearInterval(timer)
  }, [recording])

  useEffect(() => { entriesRef.current = entries }, [entries])

  useEffect(() => () => {
    recorderRef.current?.stream.getTracks().forEach((track) => track.stop())
    entriesRef.current.forEach((entry) => URL.revokeObjectURL(entry.url))
  }, [])

  async function recognize(file: File, durationMs: number) {
    if (offline) { setMessage('Нет связи с сервером. Запись сохранена в этом сеансе.'); return '' }
    setBusy(true)
    setMessage('Распознаём речь…')
    try {
      const result = await transcribePhoneAudio(file, durationMs)
      setMessage('Речь распознана.')
      return result.text.trim()
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Не удалось распознать речь.')
      return ''
    } finally {
      setBusy(false)
    }
  }

  async function addFile(file: File, durationMs?: number) {
    if (!/^audio\/(webm|ogg|mpeg|mp4|wav|x-wav)$/i.test(file.type) && !/\.(webm|ogg|mp3|m4a|wav)$/i.test(file.name)) {
      setMessage('Поддерживаются WebM, OGG, MP3, M4A и WAV.')
      return
    }
    if (file.size > 8_000_000) { setMessage('Файл больше 8 МБ.'); return }
    const measured = durationMs || await mediaDuration(file)
    const url = URL.createObjectURL(file)
    const item: AudioEntry = { id: crypto.randomUUID(), name: file.name || 'Запись', createdAt: new Date().toISOString(), durationMs: measured, text: '', url }
    setEntries((current) => [item, ...current].slice(0, 12))
    setSelected(item)
    const text = await recognize(file, measured)
    if (text) {
      const next = { ...item, text }
      setEntries((current) => current.map((entry) => entry.id === item.id ? next : entry))
      setSelected(next)
    }
  }

  async function beginRecording() {
    if (recording || busy) return
    heldRef.current = true
    setMessage('')
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      if (!heldRef.current) { stream.getTracks().forEach((track) => track.stop()); return }
      const mimeType = recordingType()
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined)
      chunksRef.current = []
      recorder.ondataavailable = (event) => { if (event.data.size) chunksRef.current.push(event.data) }
      recorder.onstop = () => {
        const durationMs = Date.now() - startedRef.current
        const type = recorder.mimeType || 'audio/webm'
        stream.getTracks().forEach((track) => track.stop())
        setRecording(false)
        setElapsed(durationMs)
        if (durationMs < 900) { setMessage('Удерживайте кнопку не меньше секунды.'); return }
        const file = new File([new Blob(chunksRef.current, { type })], `Запись-${new Date().toLocaleTimeString('ru-RU').replaceAll(':', '-')}.${extensionFor(type)}`, { type })
        void addFile(file, durationMs)
      }
      recorderRef.current = recorder
      startedRef.current = Date.now()
      setElapsed(0)
      setRecording(true)
      recorder.start(200)
    } catch {
      heldRef.current = false
      setMessage('Разрешите доступ к микрофону в браузере.')
    }
  }

  function endRecording() {
    heldRef.current = false
    if (recorderRef.current?.state === 'recording') recorderRef.current.stop()
  }

  function togglePlayback() {
    const audio = audioRef.current
    if (!audio) return
    if (audio.paused) void audio.play()
    else audio.pause()
  }

  function removeEntry(entry: AudioEntry) {
    URL.revokeObjectURL(entry.url)
    setEntries((current) => current.filter((item) => item.id !== entry.id))
    if (selected?.id === entry.id) { setSelected(null); setPlaying(false) }
  }

  return <main className="phone-audio-workspace">
    <section className={`phone-audio-recorder ${recording ? 'recording' : ''}`}>
      <div className="phone-audio-orbit"><i /><i /><i /><Mic /></div>
      <h1>{recording ? 'Говорите…' : 'Запишите голос'}</h1>
      <p>{recording ? 'Отпустите кнопку, чтобы закончить и распознать речь.' : 'Нажмите и удерживайте. Запись идёт только пока кнопка зажата.'}</p>
      <strong>{formatTime(recording ? elapsed : selected?.durationMs || 0)}</strong>
      <button type="button" className="phone-audio-hold" disabled={busy} onPointerDown={(event) => { event.currentTarget.setPointerCapture(event.pointerId); void beginRecording() }} onPointerUp={endRecording} onPointerCancel={endRecording} onPointerLeave={() => { if (recording) endRecording() }}>
        <Mic /> {recording ? 'Отпустите' : 'Удерживайте'}
      </button>
      <button type="button" className="phone-audio-upload" onClick={() => fileRef.current?.click()} disabled={busy}><Upload /> Загрузить аудио</button>
      <input ref={fileRef} hidden type="file" accept="audio/webm,audio/ogg,audio/mpeg,audio/mp4,audio/wav,.m4a" onChange={(event) => { const file = event.target.files?.[0]; if (file) void addFile(file); event.target.value = '' }} />
    </section>

    {message && <div className={`phone-audio-message ${message.includes('распознана') ? 'ok' : ''}`} role="status">{message}</div>}

    {selected && <section className="phone-audio-result">
      <header><div><small>Текущая запись</small><b>{selected.name}</b></div><button type="button" aria-label="Удалить запись" onClick={() => removeEntry(selected)}><Trash2 /></button></header>
      <audio ref={audioRef} src={selected.url} onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)} onEnded={() => setPlaying(false)} />
      <div className="phone-audio-player">
        <button type="button" aria-label={playing ? 'Пауза' : 'Воспроизвести'} onClick={togglePlayback}>{playing ? <Pause /> : <Play />}</button>
        <span><i className={playing ? 'active' : ''} /></span>
        <small>{formatTime(selected.durationMs)}</small>
        <a href={selected.url} download={selected.name} aria-label="Скачать запись"><Download /></a>
      </div>
      <div className="phone-audio-transcript">
        <header><b>Текст</b>{selected.text && <button type="button" onClick={async () => { await navigator.clipboard.writeText(selected.text); setCopied(true); window.setTimeout(() => setCopied(false), 1200) }}>{copied ? <Check /> : <Copy />}{copied ? 'Скопировано' : 'Копировать'}</button>}</header>
        <p>{selected.text || (busy ? 'Распознаём…' : 'Речь не распознана. Повторите запись.')}</p>
      </div>
      <button type="button" className="phone-audio-repeat" onClick={() => { setSelected(null); setMessage('') }}><RotateCcw /> Новая запись</button>
    </section>}

    <section className="phone-audio-history">
      <header><div><h2>Записи</h2><small>Текущий сеанс · до 12 файлов</small></div><FileAudio /></header>
      {entries.length ? <div>{entries.map((entry) => <button type="button" key={entry.id} className={selected?.id === entry.id ? 'active' : ''} onClick={() => setSelected(entry)}><Play /><span><b>{entry.name}</b><small>{entry.text || 'Без расшифровки'}</small></span><time>{formatTime(entry.durationMs)}</time></button>)}</div> : <p>Здесь появятся записанные и загруженные файлы.</p>}
    </section>

    <section className="phone-audio-soon"><b>Озвучивание текста</b><span>Серверный синтез речи и выбор голосов подключаются следующим пакетом. Кнопка не показывается, пока операция недоступна.</span></section>
  </main>
}
