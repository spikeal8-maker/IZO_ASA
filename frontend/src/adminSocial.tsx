import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { Camera, Send, Share2 } from 'lucide-react'
import { adminFetch, adminGet, adminPut } from './adminApi'

type Network = 'telegram' | 'vk' | 'instagram' | 'ok'
type SocialSettings = {
  masterEnabled: boolean
  autoPublish: boolean
  networks: Record<Network, {
    enabled: boolean
    configured?: boolean
    targetId?: string
    applicationKey?: string
    verified?: boolean
    lastCheckedAt?: string | null
    lastError?: string | null
  }>
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
  const [tokens, setTokens] = useState<Record<Network, string>>({ telegram: '', vk: '', instagram: '', ok: '' })
  const [okSessionSecret, setOkSessionSecret] = useState('')
  const [busy, setBusy] = useState('')
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
  const patchNetwork = (network: Network, patch: Partial<SocialSettings['networks'][Network]>) => setSettings({
    ...settings, networks: { ...settings.networks, [network]: { ...settings.networks[network], ...patch } },
  })
  const request = async (path: string, init: RequestInit) => {
    const response = await adminFetch(path, init)
    const payload = await response.json().catch(() => ({})) as { detail?: string; message?: string }
    if (!response.ok) throw new Error(String(payload.detail || payload.message || 'Операция не выполнена'))
    return payload
  }
  const saveCredentials = async (network: Network) => {
    setBusy(`${network}:save`)
    try {
      await request(`/admin/social/${network}/credentials-v2`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          token: tokens[network],
          targetId: settings.networks[network].targetId || '',
          applicationKey: settings.networks[network].applicationKey || '',
          sessionSecret: network === 'ok' ? okSessionSecret : '',
        }),
      })
      setTokens({ ...tokens, [network]: '' })
      if (network === 'ok') setOkSessionSecret('')
      setMessage('Доступ сохранён в защищённом DPAPI-хранилище. Теперь выполните проверку.')
      await load()
    } catch (error) { setMessage(error instanceof Error ? error.message : 'Ошибка сохранения') } finally { setBusy('') }
  }
  const check = async (network: Network) => {
    setBusy(`${network}:check`)
    try {
      await request(`/admin/social/${network}/check-v2`, { method: 'POST' })
      setMessage('Подключение и получатель проверены.')
      await load()
    } catch (error) { setMessage(error instanceof Error ? error.message : 'Проверка не пройдена'); await load() } finally { setBusy('') }
  }
  const removeCredentials = async (network: Network) => {
    if (!window.confirm('Удалить сохранённый доступ к этой социальной сети?')) return
    setBusy(`${network}:delete`)
    try {
      await request(`/admin/social/${network}/credentials-v2`, { method: 'DELETE' })
      setMessage('Доступ удалён.')
      await load()
    } catch (error) { setMessage(error instanceof Error ? error.message : 'Ошибка удаления') } finally { setBusy('') }
  }
  const save = async () => {
    const result = await adminPut<{ message: string }>('/admin/social-v2', { settings })
    setMessage(result?.message || 'Не удалось сохранить настройки.')
  }
  return <div className="admin-social-page">
    <div className="admin-section-headline"><div><h3><Share2 size={18} /> Социальные сети</h3><p>Будущее дублирование публичных работ из ленты.</p></div></div>
    <div className="admin-social-warning">Ключи сохраняются вне Git в DPAPI и никогда не возвращаются в браузер. Автопубликация остаётся выключенной до успешной проверки.</div>
    <label className="admin-social-auto"><input type="checkbox" checked={settings.autoPublish} onChange={(e) => setSettings({ ...settings, autoPublish: e.target.checked })} /> Автоматически ставить публикации ленты в очередь соцсетей</label>
    <div className="admin-social-grid">
      {([
        ['telegram', 'Telegram', <Send size={20} />],
        ['vk', 'ВКонтакте', <Share2 size={20} />],
        ['instagram', 'Instagram', <Camera size={20} />],
        ['ok', 'Одноклассники', <Share2 size={20} />],
      ] as Array<[Network, string, ReactNode]>).map(([id, label, icon]) => <article key={id} className={settings.networks[id].verified ? 'verified' : ''}>
        <div className="admin-social-title">{icon}<b>{label}</b><span>{settings.networks[id].verified ? 'Проверено' : settings.networks[id].configured ? 'Ключ сохранён' : 'Не подключено'}</span></div>
        <label>Ключ доступа<input type="password" value={tokens[id]} onChange={(e) => setTokens({ ...tokens, [id]: e.target.value })} placeholder={settings.networks[id].configured ? 'Оставьте пустым, чтобы не менять' : 'Вставьте ключ'} autoComplete="new-password" /></label>
        {id === 'ok' && <label>Session secret<input type="password" value={okSessionSecret} onChange={(e) => setOkSessionSecret(e.target.value)} autoComplete="new-password" /></label>}
        {id === 'ok' && <label>Application key<input value={settings.networks[id].applicationKey || ''} onChange={(e) => patchNetwork(id, { applicationKey: e.target.value })} /></label>}
        <label>{id === 'telegram' ? 'Канал / chat ID' : id === 'vk' || id === 'ok' ? 'ID группы' : 'Instagram account ID'}<input value={settings.networks[id].targetId || ''} onChange={(e) => patchNetwork(id, { targetId: e.target.value })} placeholder={id === 'telegram' ? '@channel или -100…' : 'ID'} /></label>
        {settings.networks[id].lastError && <small className="error">{settings.networks[id].lastError}</small>}
        <label><input type="checkbox" checked={settings.networks[id].enabled} onChange={() => toggle(id)} /> Использовать после общего включения</label>
        <div className="admin-social-actions">
          <button disabled={busy !== '' || (!tokens[id] && !settings.networks[id].configured)} onClick={() => void saveCredentials(id)}>Сохранить доступ</button>
          <button className="secondary" disabled={busy !== '' || !settings.networks[id].configured} onClick={() => void check(id)}>Проверить</button>
          <button className="secondary" disabled={busy !== '' || !settings.networks[id].configured} onClick={() => void removeCredentials(id)}>Удалить</button>
        </div>
      </article>)}
    </div>
    <button onClick={() => void save()}>Сохранить настройки публикации</button>
    {message && <p className="admin-social-note">{message}</p>}
    <section><h4>Очередь доставки</h4>{queue.length ? queue.map((row) => <p key={`${row.network}-${row.status}`}>{row.network}: {row.status} — {row.count}</p>) : <p>Заданий пока нет.</p>}</section>
  </div>
}
