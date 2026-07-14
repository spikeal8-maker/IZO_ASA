import { useCallback, useEffect, useState } from 'react'
import { adminGet, adminPost, type AdminRecord } from './adminApi'

export default function AdminMail() {
  const [data, setData] = useState<AdminRecord | null>(null)
  const [email, setEmail] = useState('')
  const [msg, setMsg] = useState('')
  const load = useCallback(async () => setData(await adminGet<AdminRecord>('/admin/mail/status-v2')), [])

  useEffect(() => {
    queueMicrotask(() => { void load() })
  }, [load])

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
          <h4>Статус почты</h4>
          <p>{data?.service_ready ? 'Готово к отправке' : 'Провайдер не настроен или адаптер недоступен'}</p>
          <div className="admin-mail-flags">
            {Object.entries(config).map(([key, value]) => <span key={key} className={value ? 'ok' : 'warn'}>{key}: {value ? 'yes' : 'no'}</span>)}
          </div>
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
