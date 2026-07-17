import { useCallback, useEffect, useState } from 'react'
import { adminFetch, adminGet, type AdminRecord } from './adminApi'

type RequestState = 'idle' | 'working' | 'ok' | 'error'

export default function AdminMail() {
  const [data, setData] = useState<AdminRecord | null>(null)
  const [host, setHost] = useState('smtp.mail.ru')
  const [port, setPort] = useState('465')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [senderName, setSenderName] = useState('ИЗО АСА')
  const [senderEmail, setSenderEmail] = useState('')
  const [testEmail, setTestEmail] = useState('')
  const [connectionState, setConnectionState] = useState<RequestState>('idle')
  const [connectionMessage, setConnectionMessage] = useState('')
  const [testState, setTestState] = useState<RequestState>('idle')
  const [testMessage, setTestMessage] = useState('')

  const load = useCallback(async () => {
    const next = await adminGet<AdminRecord>('/admin/mail/status-v2')
    const config = (next?.config || {}) as AdminRecord
    setData(next)
    setHost(String(config.host || 'smtp.mail.ru'))
    setPort(String(config.port || 465))
    setUsername(String(config.username || ''))
    setSenderName(String(config.sender_name || 'ИЗО АСА'))
    setSenderEmail(String(config.sender_email || ''))
    if (!next?.service_ready && config.last_error) {
      setConnectionState('error')
      setConnectionMessage(String(config.last_error))
    } else if (next?.service_ready) {
      setConnectionState('ok')
      setConnectionMessage('Почта подключена и готова к отправке.')
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
    if (!response.ok) throw new Error(String(result.detail || 'Почтовый сервер не ответил'))
    return result
  }

  const saveAndVerify = async () => {
    setConnectionState('working')
    setConnectionMessage('Проверяем соединение с почтовым сервером…')
    try {
      await request('/admin/mail/verify-v2', {
        host: host.trim(), port: Number(port), username: username.trim(),
        password: password.trim() || null, sender_name: senderName.trim(),
        sender_email: senderEmail.trim(), use_ssl: true, save: true,
      })
      setPassword('')
      setConnectionState('ok')
      setConnectionMessage('Почта подключена. Пароль сохранён и больше не показывается в админке.')
      await load()
    } catch (cause) {
      setConnectionState('error')
      setConnectionMessage(cause instanceof Error ? cause.message : 'Не удалось подключить почту')
      await load().catch(() => undefined)
    }
  }

  const sendTest = async () => {
    setTestState('working')
    setTestMessage('Отправляем тестовое письмо…')
    try {
      const result = await request('/admin/mail/test-v2', { email: testEmail.trim(), template: 'verify_email' })
      setTestState('ok')
      setTestMessage(`Письмо отправлено на ${String(result.email || testEmail)}`)
      await load()
    } catch (cause) {
      setTestState('error')
      setTestMessage(cause instanceof Error ? cause.message : 'Не удалось отправить письмо')
    }
  }

  const summary = (data?.summary || {}) as AdminRecord
  const config = (data?.config || {}) as AdminRecord
  const ready = Boolean(data?.service_ready)
  const configured = Boolean(config.configured)
  const canConnect = Boolean(host.trim() && port && username.trim() && senderName.trim() && senderEmail.trim() && (password.trim() || config.password))

  return (
    <div className="admin-section admin-mail-page">
      <div className="admin-mail-heading">
        <div><h3>Почта ИЗО АСА</h3><p>Системные письма и коды подтверждения отправляются через настроенный SMTP-сервер.</p></div>
        <span className={`admin-mail-status ${ready ? 'ok' : 'warn'}`}>{ready ? 'Почта работает' : configured ? 'Сохранено · нужна проверка' : 'Почта не подключена'}</span>
      </div>
      <div className="admin-mail-grid">
        <article className="admin-mail-card admin-mail-connect">
          <h4>Подключение ящика</h4>
          <div className="admin-mail-server-row">
            <label>SMTP-сервер<input value={host} onChange={(event) => setHost(event.target.value)} /></label>
            <label>Порт<input inputMode="numeric" value={port} onChange={(event) => setPort(event.target.value)} /></label>
          </div>
          <label>Почтовый ящик<input type="email" value={username} onChange={(event) => { setUsername(event.target.value); if (!senderEmail) setSenderEmail(event.target.value) }} placeholder="mail@alikinas.ru" /></label>
          <label>
            Пароль приложения Mail.ru
            <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} placeholder={config.password ? 'Пароль сохранён · введите новый только для замены' : 'Введите пароль приложения'} />
            <small>
              Обычный пароль от почты не подходит. В VK WorkSpace создайте пароль для внешнего приложения с доступом SMTP. Настройки сохранятся даже при неудачной проверке.
            </small>
          </label>
          <div className="admin-mail-server-row sender">
            <label>Имя отправителя<input value={senderName} onChange={(event) => setSenderName(event.target.value)} /></label>
            <label>Email отправителя<input type="email" value={senderEmail} onChange={(event) => setSenderEmail(event.target.value)} placeholder="mail@alikinas.ru" /></label>
          </div>
          <button className="secondary" disabled={!canConnect || connectionState === 'working'} onClick={saveAndVerify}>{connectionState === 'working' ? 'Проверяем…' : configured ? 'Проверить настройки' : 'Сохранить и проверить'}</button>
          {connectionMessage && <small className={`admin-mail-message ${connectionState}`}>{connectionMessage}</small>}
        </article>
        <article className="admin-mail-card">
          <h4>Тестовое письмо</h4>
          <p>После подключения отправьте письмо на свой адрес и проверьте папку «Входящие».</p>
          <label>Email получателя<input type="email" value={testEmail} onChange={(event) => setTestEmail(event.target.value)} placeholder="Ваш email для проверки" /></label>
          <button className="secondary" disabled={!ready || !testEmail.trim() || testState === 'working'} onClick={sendTest}>{testState === 'working' ? 'Отправляем…' : 'Отправить тест'}</button>
          {testMessage && <small className={`admin-mail-message ${testState}`}>{testMessage}</small>}
        </article>
        <article className="admin-mail-card">
          <h4>Работа почты</h4>
          <p>Всего кодов подтверждения <b>{String(summary.otp_total || 0)}</b></p>
          <p>Запрошено за 24 часа <b>{String(summary.otp_24h || 0)}</b></p>
          <p>Ожидают ввода <b>{String(summary.otp_active || 0)}</b></p>
          <p>Подтверждено за 24 часа <b>{String(summary.otp_consumed_24h || 0)}</b></p>
        </article>
      </div>
    </div>
  )
}
