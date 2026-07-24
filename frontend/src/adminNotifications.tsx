import { useCallback, useEffect, useState } from 'react'
import { Bell, CheckCheck, CircleAlert, Info, TriangleAlert } from 'lucide-react'
import { adminGet, adminPost, adminPut } from './adminApi'

type Notice = {
  id: string
  category: string
  severity: 'info' | 'warning' | 'critical'
  title: string
  message: string
  action_url?: string | null
  created_at: string
  read_at?: string | null
}
type Settings = {
  inAppEnabled: boolean
  telegramEnabled: boolean
  telegramChatId: string
  emailEnabled: boolean
  emailAddress: string
  minimumSeverity: 'info' | 'warning' | 'critical'
  digestMode: 'immediate' | 'daily'
}
type DeliveryStatus = {
  channel: 'telegram' | 'email'
  status: 'pending' | 'processing' | 'retry' | 'sent' | 'failed'
  count: number
  last_sent_at?: string | null
}
type WorkerStatus = {
  running: boolean
  lastSuccessAt?: string | null
  lastErrorAt?: string | null
  lastError?: string | null
}

export default function AdminNotifications() {
  const [items, setItems] = useState<Notice[]>([])
  const [unread, setUnread] = useState(0)
  const [settings, setSettings] = useState<Settings>({
    inAppEnabled: true, telegramEnabled: false, telegramChatId: '',
    emailEnabled: false, emailAddress: '',
    minimumSeverity: 'info', digestMode: 'immediate',
  })
  const [message, setMessage] = useState('')
  const [delivery, setDelivery] = useState<DeliveryStatus[]>([])
  const [worker, setWorker] = useState<WorkerStatus>({ running: false })

  const load = useCallback(async () => {
    const [feed, config] = await Promise.all([
      adminGet<{ items: Notice[]; unread: number }>('/admin/notifications-v2?limit=100'),
      adminGet<{ settings: Settings; delivery: DeliveryStatus[]; worker: WorkerStatus }>('/admin/notifications/settings-v2'),
    ])
    setItems(feed?.items || [])
    setUnread(Number(feed?.unread || 0))
    if (config?.settings) setSettings(config.settings)
    setDelivery(config?.delivery || [])
    setWorker(config?.worker || { running: false })
  }, [])
  useEffect(() => { queueMicrotask(() => { void load() }) }, [load])

  const markAllRead = async () => {
    await adminPost('/admin/notifications/read-v2', { ids: [] })
    await load()
  }
  const save = async () => {
    const result = await adminPut('/admin/notifications/settings-v2', { settings })
    setMessage(result ? 'Настройки сохранены.' : 'Не удалось сохранить настройки.')
  }
  const icon = (severity: Notice['severity']) => severity === 'critical'
    ? <CircleAlert size={18} /> : severity === 'warning' ? <TriangleAlert size={18} /> : <Info size={18} />

  return <div className="admin-notifications-page">
    <div className="admin-section-headline">
      <div><h3><Bell size={18} /> Центр уведомлений</h3><p>Системные события, провайдеры, каталог моделей и внешние доставки.</p></div>
      <button className="secondary" disabled={!unread} onClick={() => void markAllRead()}><CheckCheck size={16} /> Прочитать все ({unread})</button>
    </div>
    <section className="admin-notification-settings">
      <label><input type="checkbox" checked={settings.inAppEnabled} onChange={(e) => setSettings({ ...settings, inAppEnabled: e.target.checked })} /> В админке</label>
      <label><input type="checkbox" checked={settings.telegramEnabled} onChange={(e) => setSettings({ ...settings, telegramEnabled: e.target.checked })} /> Telegram администратора</label>
      <label>Telegram chat ID<input value={settings.telegramChatId} onChange={(e) => setSettings({ ...settings, telegramChatId: e.target.value })} placeholder="-100… или ID пользователя" /></label>
      <label><input type="checkbox" checked={settings.emailEnabled} onChange={(e) => setSettings({ ...settings, emailEnabled: e.target.checked })} /> Email</label>
      <label>Email администратора<input type="email" value={settings.emailAddress} onChange={(e) => setSettings({ ...settings, emailAddress: e.target.value })} placeholder="admin@example.ru" /></label>
      <label>Важность<select value={settings.minimumSeverity} onChange={(e) => setSettings({ ...settings, minimumSeverity: e.target.value as Settings['minimumSeverity'] })}><option value="info">Все</option><option value="warning">Предупреждения</option><option value="critical">Только критические</option></select></label>
      <label>Доставка<select value={settings.digestMode} onChange={(e) => setSettings({ ...settings, digestMode: e.target.value as Settings['digestMode'] })}><option value="immediate">Сразу</option><option value="daily">Суточная сводка</option></select></label>
      <button onClick={() => void save()}>Сохранить</button>
      {message && <small>{message}</small>}
    </section>
    <section className="admin-notification-delivery-status">
      <b>Доставка: {worker.running ? 'worker работает' : 'worker остановлен'}</b>
      {!delivery.length && <small> Очередь пуста.</small>}
      {delivery.map((item) => <small key={`${item.channel}-${item.status}`}>
        {item.channel}: {item.status} — {item.count}
      </small>)}
      {worker.lastError && <small>Последняя ошибка: {worker.lastError}</small>}
    </section>
    <div className="admin-notification-list">
      {!items.length && <div className="preview-empty">Событий пока нет.</div>}
      {items.map((item) => <article key={item.id} className={`admin-notification ${item.severity} ${item.read_at ? 'read' : 'unread'}`}>
        <span>{icon(item.severity)}</span>
        <div><b>{item.title}</b><p>{item.message}</p><small>{new Date(item.created_at).toLocaleString('ru-RU')} · {item.category}</small></div>
        {item.action_url && <button className="secondary" onClick={() => { window.location.href = item.action_url || '/admin' }}>Открыть</button>}
      </article>)}
    </div>
  </div>
}
