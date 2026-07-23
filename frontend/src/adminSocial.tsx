import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { Camera, Send, Share2 } from 'lucide-react'
import { adminGet, adminPut } from './adminApi'

type Network = 'telegram' | 'vk' | 'instagram' | 'ok'
type SocialSettings = {
  masterEnabled: boolean
  autoPublish: boolean
  networks: Record<Network, { enabled: boolean }>
}
const defaults: SocialSettings = {
  masterEnabled: false,
  autoPublish: false,
  networks: {
    telegram: { enabled: false }, vk: { enabled: false },
    instagram: { enabled: false }, ok: { enabled: false },
  },
}

export default function AdminSocial() {
  const [settings, setSettings] = useState(defaults)
  const [queue, setQueue] = useState<Array<{ network: string; status: string; count: number }>>([])
  const [message, setMessage] = useState('')
  const load = useCallback(async () => {
    const result = await adminGet<{ settings: SocialSettings; queue: typeof queue; message: string }>('/admin/social-v2')
    if (result?.settings) setSettings(result.settings)
    setQueue(result?.queue || [])
    setMessage(result?.message || '')
  }, [])
  useEffect(() => { queueMicrotask(() => { void load() }) }, [load])
  const toggle = (network: Network) => setSettings({
    ...settings, networks: { ...settings.networks, [network]: { enabled: !settings.networks[network].enabled } },
  })
  const save = async () => {
    const result = await adminPut<{ message: string }>('/admin/social-v2', { settings })
    setMessage(result?.message || 'Не удалось сохранить настройки.')
  }
  return <div className="admin-social-page">
    <div className="admin-section-headline"><div><h3><Share2 size={18} /> Социальные сети</h3><p>Будущее дублирование публичных работ из ленты.</p></div></div>
    <div className="admin-social-warning">Внешняя отправка пока безопасно выключена. Выбор сетей сохраняется как подготовительная конфигурация.</div>
    <label className="admin-social-auto"><input type="checkbox" checked={settings.autoPublish} onChange={(e) => setSettings({ ...settings, autoPublish: e.target.checked })} /> Автоматически ставить публикации ленты в очередь соцсетей</label>
    <div className="admin-social-grid">
      {([
        ['telegram', 'Telegram', <Send size={20} />],
        ['vk', 'ВКонтакте', <Share2 size={20} />],
        ['instagram', 'Instagram', <Camera size={20} />],
        ['ok', 'Одноклассники', <Share2 size={20} />],
      ] as Array<[Network, string, ReactNode]>).map(([id, label, icon]) => <article key={id}>
        {icon}<b>{label}</b><small>Ключ и получатель ещё не подключены</small>
        <label><input type="checkbox" checked={settings.networks[id].enabled} onChange={() => toggle(id)} /> Подготовить канал</label>
      </article>)}
    </div>
    <button onClick={() => void save()}>Сохранить подготовительные настройки</button>
    {message && <p className="admin-social-note">{message}</p>}
    <section><h4>Очередь доставки</h4>{queue.length ? queue.map((row) => <p key={`${row.network}-${row.status}`}>{row.network}: {row.status} — {row.count}</p>) : <p>Заданий пока нет.</p>}</section>
  </div>
}
