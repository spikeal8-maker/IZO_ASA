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
  const [lists, setLists] = useState<AdminRecord[]>([])
  const [checking, setChecking] = useState(false)
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
  const checkProvider = async () => {
    setChecking(true)
    const result = await adminGet<AdminRecord>('/admin/mail/provider-options-v2')
    const nextLists = Array.isArray(result?.lists) ? result.lists as AdminRecord[] : []
    setLists(nextLists)
    if (nextLists.length && !nextLists.some((item) => String(item.id) === listId)) setListId(String(nextLists[0].id))
    setMsg(result?.ok ? `UniSender отвечает · найдено списков: ${nextLists.length}` : 'Не удалось проверить UniSender. Сначала сохраните API-ключ.')
    setChecking(false)
  }
  const summary = (data?.summary || {}) as AdminRecord
  const config = (data?.config || {}) as AdminRecord

  return (
    <div className="admin-section admin-mail-page">
      <div className="admin-mail-grid">
        <article className="admin-mail-card">
          <h4>Подключение UniSender</h4>
          <p className={data?.service_ready ? 'admin-provider-state ok' : 'admin-provider-state warn'}>{data?.service_ready ? 'Почта готова к отправке' : 'Нужно заполнить и проверить настройки'}</p>
          <label>API-ключ<input type="password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder={config.api_key ? 'Ключ сохранен, можно заменить' : 'Вставьте API-ключ'} /></label>
          <label>Имя в поле «От кого»<input value={senderName} onChange={(event) => setSenderName(event.target.value)} /></label>
          <label>Email отправителя<input type="email" value={senderEmail} onChange={(event) => setSenderEmail(event.target.value)} /><small>Этот адрес нужно сначала подтвердить в кабинете UniSender.</small></label>
          <label>Список контактов
            {lists.length ? <select value={listId} onChange={(event) => setListId(event.target.value)}>{lists.map((item) => <option key={String(item.id)} value={String(item.id)}>{String(item.title)} · #{String(item.id)}</option>)}</select>
              : <input inputMode="numeric" value={listId} onChange={(event) => setListId(event.target.value.replace(/\D/g, ''))} placeholder="Появится после проверки UniSender" />}
            <small>Список нужен UniSender для разрешения отправки. Получатель письма передаётся отдельно.</small>
          </label>
          <button className="secondary" disabled={checking || (!apiKey && !config.api_key)} onClick={checkProvider}>{checking ? 'Проверяем…' : 'Проверить UniSender и загрузить списки'}</button>
          <button className="secondary" disabled={!senderEmail || !listId || (!apiKey && !config.api_key)} onClick={saveConfig}>Сохранить настройки</button>
        </article>
        <article className="admin-mail-card">
          <h4>Тест отправки</h4>
          <label>Email<input type="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="admin@example.com" /></label>
          <button className="secondary" disabled={!email.trim()} onClick={sendTest}>Отправить тест</button>
          {msg && <small>{msg}</small>}
        </article>
        <article className="admin-mail-card">
          <h4>Работа почты</h4>
          <p>Всего кодов подтверждения: <b>{String(summary.otp_total || 0)}</b></p>
          <p>Отправлено за 24 часа: <b>{String(summary.otp_24h || 0)}</b></p>
          <p>Сейчас ожидают ввода: <b>{String(summary.otp_active || 0)}</b></p>
          <p>Подтверждено за 24 часа: <b>{String(summary.otp_consumed_24h || 0)}</b></p>
        </article>
      </div>
    </div>
  )
}
