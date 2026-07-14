import { useCallback, useEffect, useState } from 'react'
import { adminGet, adminPost, adminPut, type AdminRecord } from './adminApi'

export default function AdminMail() {
  const [data, setData] = useState<AdminRecord | null>(null)
  const [email, setEmail] = useState('')
  const [msg, setMsg] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [senderName, setSenderName] = useState('ИЗО АСА')
  const [senderEmail, setSenderEmail] = useState('')
  const [listId, setListId] = useState('')
  const load = useCallback(async () => {
    const next = await adminGet<AdminRecord>('/admin/mail/status-v2')
    const config = (next?.config || {}) as AdminRecord
    setData(next)
    setSenderName(String(config.sender_name || 'ИЗО АСА'))
    setSenderEmail(String(config.sender_email || ''))
    setListId(String(config.list_id || ''))
  }, [])

  useEffect(() => {
    queueMicrotask(() => { void load() })
  }, [load])

  const saveConfig = async () => {
    const result = await adminPut<AdminRecord>('/admin/mail/config-v2', {
      api_key: apiKey.trim() || null,
      sender_name: senderName.trim(),
      sender_email: senderEmail.trim(),
      list_id: Number(listId),
    })
    setMsg(result?.ok ? 'Настройки UniSender сохранены' : 'Не удалось сохранить настройки')
    if (result?.ok) setApiKey('')
    await load()
  }

  const sendTest = async () => {
    const result = await adminPost<AdminRecord>('/admin/mail/test-v2', { email, template: 'verify_email' })
    setMsg(result?.ok ? `Тест отправлен на ${String(result.email || email)}` : 'Не удалось отправить тест')
    await load()
  }
  const summary = (data?.summary || {}) as AdminRecord
  const config = (data?.config || {}) as AdminRecord

  return (
    <div className="admin-section admin-mail-page">
      <div className="admin-mail-grid">
        <article className="admin-mail-card">
          <h4>UniSender</h4>
          <p>{data?.service_ready ? 'Готово к отправке' : 'Провайдер не настроен или адаптер недоступен'}</p>
          <label>API-ключ<input type="password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder={config.api_key ? 'Ключ сохранен, можно заменить' : 'Вставьте API-ключ'} /></label>
          <label>Имя отправителя<input value={senderName} onChange={(event) => setSenderName(event.target.value)} /></label>
          <label>Подтвержденный email<input type="email" value={senderEmail} onChange={(event) => setSenderEmail(event.target.value)} /></label>
          <label>ID списка<input inputMode="numeric" value={listId} onChange={(event) => setListId(event.target.value.replace(/\D/g, ''))} /></label>
          <button className="secondary" disabled={!senderEmail || !listId || (!apiKey && !config.api_key)} onClick={saveConfig}>Сохранить настройки</button>
        </article>
        <article className="admin-mail-card">
          <h4>Тест отправки</h4>
          <label>Email<input type="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="admin@example.com" /></label>
          <button className="secondary" disabled={!email.trim()} onClick={sendTest}>Отправить тест</button>
          {msg && <small>{msg}</small>}
        </article>
        <article className="admin-mail-card">
          <h4>Сводка</h4>
          {Object.entries(summary).map(([key, value]) => <p key={key}><b>{key}</b>: {String(value)}</p>)}
        </article>
      </div>
    </div>
  )
}
