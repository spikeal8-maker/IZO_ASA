// Раздел «Чат» на десктопе. В отличие от Звука и 3D это рабочий раздел:
// запрос идёт в тот же /api/phone/chat, что и телефонный интерфейс, поэтому
// поведение и модель у них совпадают.

import { useEffect, useRef, useState } from 'react'
import './studioChatPanel.css'

const API = (import.meta as ImportMeta & { env?: { VITE_API_BASE_URL?: string } }).env?.VITE_API_BASE_URL || '/api'

type Turn = { role: 'user' | 'assistant'; content: string }

const SUGGESTIONS = [
  'Придумай идею для постера кофейни',
  'Опиши кадр в стиле неонуара',
  'Помоги описать персонажа для иллюстрации',
]

export default function StudioChatPanel({ authed }: { authed: boolean }) {
  const [turns, setTurns] = useState<Turn[]>([])
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const endRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => { endRef.current?.scrollIntoView({ block: 'end' }) }, [turns, busy])

  async function send(text: string) {
    const message = text.trim()
    if (!message || busy) return
    const next: Turn[] = [...turns, { role: 'user', content: message }]
    setTurns(next)
    setDraft('')
    setBusy(true)
    setError('')
    try {
      const response = await fetch(`${API}/phone/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ messages: next.slice(-20), route: 'auto', images: [] }),
      })
      if (!response.ok) {
        const detail = await response.json().catch(() => null)
        throw new Error(detail?.detail || 'Чат временно недоступен.')
      }
      const data = await response.json()
      setTurns((current) => [...current, { role: 'assistant', content: String(data.reply || '') }])
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : 'Чат временно недоступен.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="chat-panel">
      <div className="chat-log">
        {turns.length === 0 && (
          <div className="chat-empty">
            <h2>Помощник ИЗО АСА</h2>
            <p>Поможет сформулировать идею для изображения, видео или публикации.</p>
            <div className="chat-suggestions">
              {SUGGESTIONS.map((s) => (
                <button key={s} type="button" onClick={() => send(s)} disabled={!authed || busy}>{s}</button>
              ))}
            </div>
          </div>
        )}

        {turns.map((turn, i) => (
          <div key={i} className={`chat-turn is-${turn.role}`}>
            <span>{turn.content}</span>
          </div>
        ))}

        {busy && <div className="chat-turn is-assistant is-typing"><i /><i /><i /></div>}
        {error && <p className="chat-error" role="alert">{error}</p>}
        <div ref={endRef} />
      </div>

      <form
        className="chat-composer"
        onSubmit={(e) => { e.preventDefault(); void send(draft) }}
      >
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); void send(draft) } }}
          placeholder={authed ? 'Напишите сообщение…' : 'Войдите в аккаунт, чтобы открыть чат'}
          disabled={!authed || busy}
          rows={1}
        />
        <button type="submit" disabled={!authed || busy || !draft.trim()}>Отправить</button>
      </form>
    </div>
  )
}
