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
  emailEnabled: boolean
  minimumSeverity: 'info' | 'warning' | 'critical'
  digestMode: 'immediate' | 'daily'
}

export default function AdminNotifications() {
  const [items, setItems] = useState<Notice[]>([])
  const [unread, setUnread] = useState(0)
  const [settings, setSettings] = useState<Settings>({
    inAppEnabled: true, telegramEnabled: false, emailEnabled: false,
    minimumSeverity: 'info', digestMode: 'immediate',
  })
  const [message, setMessage] = useState('')

  const load = useCallback(async () => {
    const [feed, config] = await Promise.all([
      adminGet<{ items: Notice[]; unread: number }>('/admin/notifications-v2?limit=100'),
      adminGet<{ settings: Settings }>('/admin/notifications/settings-v2'),
    ])
    setItems(feed?.items || [])
    setUnread(Number(feed?.unread || 0))
    if (config?.settings) setSettings(config.settings)
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
      <label><input type="checkbox" checked={settings.emailEnabled} onChange={(e) => setSettings({ ...settings, emailEnabled: e.target.checked })} /> Email</label>
      <label>Важность<select value={settings.minimumSeverity} onChange={(e) => setSettings({ ...settings, minimumSeverity: e.target.value as Settings['minimumSeverity'] })}><option value="info">Все</option><option value="warning">Предупреждения</option><option value="critical">Только критические</option></select></label>
      <label>Доставка<select value={settings.digestMode} onChange={(e) => setSettings({ ...settings, digestMode: e.target.value as Settings['digestMode'] })}><option value="immediate">Сразу</option><option value="daily">Суточная сводка</option></select></label>
      <button onClick={() => void save()}>Сохранить</button>
      {message && <small>{message}</small>}
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
