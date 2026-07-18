import { useCallback, useEffect, useState } from 'react'
import { adminFetch, adminGet, type AdminRecord } from './adminApi'

type RequestState = 'idle' | 'working' | 'ok' | 'error'

export default function AdminMail() {
  const [data, setData] = useState<AdminRecord | null>(null)
  const [apiKey, setApiKey] = useState('')
  const [senderName, setSenderName] = useState('ИЗО АСА')
  const [senderEmail, setSenderEmail] = useState('mail@alikinas.ru')
  const [listId, setListId] = useState(0)
  const [connectionState, setConnectionState] = useState<RequestState>('idle')
  const [connectionMessage, setConnectionMessage] = useState('')
  const [testEmail, setTestEmail] = useState('')
  const [testState, setTestState] = useState<RequestState>('idle')
  const [testMessage, setTestMessage] = useState('')

  const [smtpHost, setSmtpHost] = useState('smtp.mail.ru')
  const [smtpPort, setSmtpPort] = useState('465')
  const [smtpUsername, setSmtpUsername] = useState('')
  const [smtpPassword, setSmtpPassword] = useState('')
  const [smtpSenderName, setSmtpSenderName] = useState('ИЗО АСА')
  const [smtpSenderEmail, setSmtpSenderEmail] = useState('')
  const [smtpState, setSmtpState] = useState<RequestState>('idle')
  const [smtpMessage, setSmtpMessage] = useState('')

  const load = useCallback(async () => {
    const next = await adminGet<AdminRecord>('/admin/mail/status-v2')
    const providers = (next?.providers || {}) as AdminRecord
    const unisender = (providers.unisender || {}) as AdminRecord
    const smtp = (providers.smtp || next?.config || {}) as AdminRecord
    setData(next)
    setSenderName(String(unisender.sender_name || 'ИЗО АСА'))
    setSenderEmail(String(unisender.sender_email || 'mail@alikinas.ru'))
    setListId(Number(unisender.list_id || 0))
    setSmtpHost(String(smtp.host || 'smtp.mail.ru'))
    setSmtpPort(String(smtp.port || 465))
    setSmtpUsername(String(smtp.username || ''))
    setSmtpSenderName(String(smtp.sender_name || 'ИЗО АСА'))
    setSmtpSenderEmail(String(smtp.sender_email || ''))
    if (unisender.verified) {
      setConnectionState('ok')
      setConnectionMessage('UniSender подключён и принимает письма от ИЗО АСА.')
    } else if (unisender.last_error) {
      setConnectionState('error')
      setConnectionMessage(String(unisender.last_error))
    }
  }, [])

  useEffect(() => {
    queueMicrotask(() => { void load() })
  }, [load])

  const request = async (path: string, body: AdminRecord) => {
    const response = await adminFetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    const result = await response.json().catch(() => ({})) as AdminRecord
    if (!response.ok) throw new Error(String(result.detail || 'Почтовый сервис не ответил'))
    return result
  }

  const connectUniSender = async () => {
    setConnectionState('working')
    setConnectionMessage('Проверяем ключ, список контактов и адрес отправителя…')
    try {
      const result = await request('/admin/mail/unisender/verify-v2', {
        api_key: apiKey.trim() || null,
        sender_name: senderName.trim(),
        sender_email: senderEmail.trim(),
        list_id: listId || null,
        create_list_if_missing: true,
      })
      setApiKey('')
      setListId(Number(result.list_id || 0))
      setConnectionState('ok')
      setConnectionMessage(`Почта подключена. Проверочное письмо принято к отправке, список #${String(result.list_id || '')}.`)
      await load()
    } catch (cause) {
      setConnectionState('error')
      setConnectionMessage(cause instanceof Error ? cause.message : 'Не удалось подключить UniSender')
      await load().catch(() => undefined)
    }
  }

  const connectSmtp = async () => {
    setSmtpState('working')
    setSmtpMessage('Проверяем резервный SMTP…')
    try {
      await request('/admin/mail/verify-v2', {
        host: smtpHost.trim(), port: Number(smtpPort), username: smtpUsername.trim(),
        password: smtpPassword.trim() || null, sender_name: smtpSenderName.trim(),
        sender_email: smtpSenderEmail.trim(), use_ssl: true, save: true,
      })
      setSmtpPassword('')
      setSmtpState('ok')
      setSmtpMessage('Резервный SMTP подключён.')
      await load()
    } catch (cause) {
      setSmtpState('error')
      setSmtpMessage(cause instanceof Error ? cause.message : 'Не удалось подключить SMTP')
      await load().catch(() => undefined)
    }
  }

  const sendTest = async () => {
    setTestState('working')
    setTestMessage('Отправляем тестовое письмо…')
    try {
      const result = await request('/admin/mail/test-v2', { email: testEmail.trim(), template: 'verify_email' })
      setTestState('ok')
      setTestMessage(`Письмо принято к отправке на ${String(result.email || testEmail)}`)
      await load()
    } catch (cause) {
      setTestState('error')
      setTestMessage(cause instanceof Error ? cause.message : 'Не удалось отправить письмо')
    }
  }

  const providers = (data?.providers || {}) as AdminRecord
  const unisender = (providers.unisender || {}) as AdminRecord
  const smtp = (providers.smtp || data?.config || {}) as AdminRecord
  const summary = (data?.summary || {}) as AdminRecord
  const ready = Boolean(data?.service_ready)
  const canConnect = Boolean(senderName.trim() && senderEmail.trim() && (apiKey.trim() || unisender.api_key))
  const canConnectSmtp = Boolean(smtpHost.trim() && smtpPort && smtpUsername.trim() && smtpSenderName.trim() && smtpSenderEmail.trim() && (smtpPassword.trim() || smtp.password))

  return (
    <div className="admin-section admin-mail-page">
      <div className="admin-mail-heading">
        <div><h3>Почта ИЗО АСА</h3><p>Коды входа, чеки и системные уведомления.</p></div>
        <span className={`admin-mail-status ${ready ? 'ok' : 'warn'}`}>{ready ? `Работает · ${String(data?.provider || '')}` : 'Не подключена'}</span>
      </div>

      <div className="admin-mail-grid">
        <article className="admin-mail-card admin-mail-connect">
          <h4>UniSender</h4>
          <label>
            API-ключ
            <input type="password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder={unisender.api_key ? 'Ключ сохранён · введите только для замены' : 'Вставьте ключ UniSender'} />
          </label>
          <div className="admin-mail-server-row sender">
            <label>Имя отправителя<input value={senderName} onChange={(event) => setSenderName(event.target.value)} /></label>
            <label>Email отправителя<input type="email" value={senderEmail} onChange={(event) => setSenderEmail(event.target.value)} /></label>
          </div>
          <button className="secondary" disabled={!canConnect || connectionState === 'working'} onClick={connectUniSender}>{connectionState === 'working' ? 'Проверяем…' : unisender.api_key ? 'Проверить подключение' : 'Подключить и проверить'}</button>
          {connectionMessage && <small className={`admin-mail-message ${connectionState}`}>{connectionMessage}</small>}
          <small>Адрес должен быть подтверждён в UniSender: <a href="https://cp.unisender.com/ru/v5/cp/user/info/sender" target="_blank" rel="noreferrer">Подтверждённые email</a>.</small>
        </article>

        <article className="admin-mail-card">
          <h4>Тестовое письмо</h4>
          <p>Проверяет тот же маршрут, которым пользователи получают коды и уведомления.</p>
          <label>Email получателя<input type="email" value={testEmail} onChange={(event) => setTestEmail(event.target.value)} placeholder="Ваш email для проверки" /></label>
          <button className="secondary" disabled={!ready || !testEmail.trim() || testState === 'working'} onClick={sendTest}>{testState === 'working' ? 'Отправляем…' : 'Отправить тест'}</button>
          {testMessage && <small className={`admin-mail-message ${testState}`}>{testMessage}</small>}
        </article>

        <article className="admin-mail-card">
          <h4>Работа почты</h4>
          <p>Кодов подтверждения <b>{String(summary.otp_total || 0)}</b></p>
          <p>Запрошено за 24 часа <b>{String(summary.otp_24h || 0)}</b></p>
          <p>Ожидают ввода <b>{String(summary.otp_active || 0)}</b></p>
          <p>Подтверждено за 24 часа <b>{String(summary.otp_consumed_24h || 0)}</b></p>
        </article>
      </div>

      <details className="admin-mail-backup">
        <summary>Резервный SMTP</summary>
        <div className="admin-mail-card">
          <div className="admin-mail-server-row">
            <label>SMTP-сервер<input value={smtpHost} onChange={(event) => setSmtpHost(event.target.value)} /></label>
            <label>Порт<input inputMode="numeric" value={smtpPort} onChange={(event) => setSmtpPort(event.target.value)} /></label>
          </div>
          <label>Почтовый ящик<input type="email" value={smtpUsername} onChange={(event) => { setSmtpUsername(event.target.value); if (!smtpSenderEmail) setSmtpSenderEmail(event.target.value) }} /></label>
          <label>Пароль приложения<input type="password" value={smtpPassword} onChange={(event) => setSmtpPassword(event.target.value)} placeholder={smtp.password ? 'Пароль сохранён · введите только для замены' : 'Пароль приложения'} /></label>
          <div className="admin-mail-server-row sender">
            <label>Имя отправителя<input value={smtpSenderName} onChange={(event) => setSmtpSenderName(event.target.value)} /></label>
            <label>Email отправителя<input type="email" value={smtpSenderEmail} onChange={(event) => setSmtpSenderEmail(event.target.value)} /></label>
          </div>
          <button className="secondary" disabled={!canConnectSmtp || smtpState === 'working'} onClick={connectSmtp}>{smtpState === 'working' ? 'Проверяем…' : 'Сохранить и проверить SMTP'}</button>
          {smtpMessage && <small className={`admin-mail-message ${smtpState}`}>{smtpMessage}</small>}
        </div>
      </details>
    </div>
  )
}
