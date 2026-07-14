import { useCallback, useEffect, useState } from 'react'
import { adminFetch, adminGet, adminPost, adminPut, type AdminRecord } from './adminApi'

export default function AdminMail() {
  const [data, setData] = useState<AdminRecord | null>(null)
  const [email, setEmail] = useState('')
  const [configMessage, setConfigMessage] = useState('')
  const [testMessage, setTestMessage] = useState('')
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
    setConfigMessage(result?.ok ? 'Отправитель и список сохранены' : 'Не удалось сохранить настройки')
    if (result?.ok) setApiKey('')
    await load()
  }

  const sendTest = async () => {
    const result = await adminPost<AdminRecord>('/admin/mail/test-v2', { email, template: 'verify_email' })
    setTestMessage(result?.ok ? `Тест отправлен на ${String(result.email || email)}` : 'Не удалось отправить тест')
    await load()
  }
  const providerRequest = async (path: string, body: AdminRecord) => {
    const response = await adminFetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
    const result = await response.json().catch(() => ({})) as AdminRecord
    if (!response.ok) throw new Error(String(result.detail || 'UniSender не ответил'))
    return result
  }
  const checkProvider = async () => {
    setChecking(true)
    try {
      const result = await providerRequest('/admin/mail/verify-v2', { api_key: apiKey.trim() || null })
      const nextLists = Array.isArray(result.lists) ? result.lists as AdminRecord[] : []
      await load()
      setLists(nextLists)
      if (nextLists.length && !nextLists.some((item) => String(item.id) === listId)) setListId(String(nextLists[0].id))
      setApiKey('')
      setConfigMessage(nextLists.length ? `Ключ сохранен · найдено списков: ${nextLists.length}` : 'Ключ сохранен. Теперь создайте рабочий список контактов.')
    } catch (cause) {
      setConfigMessage(cause instanceof Error ? cause.message : 'Не удалось проверить API-ключ UniSender')
    } finally {
      setChecking(false)
    }
  }
  const createList = async () => {
    setChecking(true)
    try {
      const result = await providerRequest('/admin/mail/lists-v2', { title: 'Пользователи ИЗО АСА' })
      const nextLists = Array.isArray(result.lists) ? result.lists as AdminRecord[] : []
      setLists(nextLists)
      const created = result.created as AdminRecord | undefined
      if (created?.id) setListId(String(created.id))
      setConfigMessage('Рабочий список «Пользователи ИЗО АСА» создан')
    } catch (cause) {
      setConfigMessage(cause instanceof Error ? cause.message : 'Не удалось создать список')
    } finally {
      setChecking(false)
    }
  }
  const summary = (data?.summary || {}) as AdminRecord
  const config = (data?.config || {}) as AdminRecord

  return (
    <div className="admin-section admin-mail-page">
      <div className="admin-mail-grid">
        <article className="admin-mail-card">
          <h4>Подключение UniSender</h4>
          <p className={data?.service_ready ? 'admin-provider-state ok' : 'admin-provider-state warn'}>{data?.service_ready ? 'Почта готова к отправке' : 'Нужно заполнить и проверить настройки'}</p>
          <label>API-ключ<input type="password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder={config.api_key ? 'Ключ надежно сохранен · вставьте новый для замены' : 'Вставьте API-ключ'} /></label>
          <button className="secondary" disabled={checking || (!apiKey.trim() && !config.api_key)} onClick={checkProvider}>{checking ? 'Проверяем…' : config.api_key && !apiKey ? 'Проверить сохраненный ключ' : 'Проверить и сохранить ключ'}</button>
          <label>Имя в поле «От кого»<input value={senderName} onChange={(event) => setSenderName(event.target.value)} /><small>Так получатель увидит отправителя письма, например «ИЗО АСА».</small></label>
          <label>Email отправителя<input type="email" value={senderEmail} onChange={(event) => setSenderEmail(event.target.value)} placeholder="Реальный адрес, к которому у вас есть доступ" /><small>Придумать адрес недостаточно: откройте в UniSender создание письма, укажите обратный адрес и подтвердите его по ссылке из полученного письма. <a href="https://www.unisender.com/ru/support/api/messages/sendemail/" target="_blank" rel="noreferrer">Инструкция</a></small></label>
          <label>Список контактов
            {lists.length ? <select value={listId} onChange={(event) => setListId(event.target.value)}>{lists.map((item) => <option key={String(item.id)} value={String(item.id)}>{String(item.title)} · #{String(item.id)}</option>)}</select>
              : <input readOnly value="" placeholder={config.api_key ? 'Списков пока нет' : 'Сначала проверьте API-ключ'} />}
            <small>Это техническая группа для системных писем. Получатель каждого письма передаётся отдельно.</small>
          </label>
          {Boolean(config.api_key) && !lists.length && <button className="secondary" disabled={checking} onClick={createList}>Создать рабочий список</button>}
          <button className="secondary" disabled={!senderEmail || !listId || (!apiKey && !config.api_key)} onClick={saveConfig}>Сохранить отправителя и список</button>
          {configMessage && <small className="admin-mail-message">{configMessage}</small>}
        </article>
        <article className="admin-mail-card">
          <h4>Тест отправки</h4>
          <label>Email<input type="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="admin@example.com" /></label>
          <button className="secondary" disabled={!email.trim() || !data?.service_ready} onClick={sendTest}>Отправить тест</button>
          <small>Кнопка станет доступна после сохранения отправителя и списка.</small>
          {testMessage && <small className="admin-mail-message">{testMessage}</small>}
        </article>
        <article className="admin-mail-card">
          <h4>Работа почты</h4>
          <p>Всего кодов подтверждения: <b>{String(summary.otp_total || 0)}</b></p>
          <p>Отправлено за 24 часа: <b>{String(summary.otp_24h || 0)}</b></p>
          <p>Сейчас ожидают ввода: <b>{String(summary.otp_active || 0)}</b></p>
          <p>Подтверждено за 24 часа: <b>{String(summary.otp_consumed_24h || 0)}</b></p>
        </article>
      </div>
      <article className="admin-mail-plan-note">
        <h4>Какой тариф UniSender нужен</h4>
        <p>Для кодов входа, подтверждений и системных уведомлений активируйте <b>«Базовый» Email API</b>. «Расширенный» пока не нужен: он рассчитан на сложные массовые сценарии и расширенную аналитику.</p>
        <p>Основной тариф «Фри» можно оставить на старте, пока хватает лимитов аккаунта. По текущим условиям это до 1500 писем в месяц и 100 уникальных контактов.</p>
      </article>
    </div>
  )
}
