import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { Camera, CheckCircle2, MessageCircle, Send, Share2 } from 'lucide-react'
import { adminFetch, adminGet, adminPut } from './adminApi'

type Network = 'telegram' | 'max' | 'vk' | 'instagram' | 'ok'
type NetworkSettings = {
  enabled: boolean; storyEnabled?: boolean; configured?: boolean; mediaConfigured?: boolean; targetId?: string; applicationKey?: string
  verified?: boolean; lastCheckedAt?: string | null; lastError?: string | null
}
type SocialSettings = {
  masterEnabled: boolean; autoPublish: boolean
  networks: Record<Network, NetworkSettings>
}
type CheckResult = { identity?: string; target?: { id?: string | number; title?: string; username?: string } }
type ApiPayload = { detail?: string; message?: string; result?: CheckResult; messageId?: number }

const defaults: SocialSettings = {
  masterEnabled: false, autoPublish: false,
  networks: {
    telegram: { enabled: false }, max: { enabled: false }, vk: { enabled: false },
    instagram: { enabled: false }, ok: { enabled: false },
  },
}
const providers: Array<[Network, string, ReactNode, string]> = [
  ['telegram', 'Telegram', <Send size={19} />, 'Публикация и проверка доставки'],
  ['max', 'MAX', <MessageCircle size={19} />, 'Публикация в канал MAX'],
  ['vk', 'ВКонтакте', <Share2 size={19} />, 'Проверка доступа к группе'],
  ['instagram', 'Instagram', <Camera size={19} />, 'Проверка бизнес-аккаунта'],
  ['ok', 'Одноклассники', <Share2 size={19} />, 'Подключение API группы'],
]

export default function AdminSocial() {
  const [settings, setSettings] = useState(defaults)
  const [queue, setQueue] = useState<Array<{ network: string; status: string; count: number }>>([])
  const [worker, setWorker] = useState<{ running: boolean; lastSuccessAt?: string | null; lastError?: string | null }>({ running: false })
  const [operational, setOperational] = useState(false)
  const [message, setMessage] = useState('')
  const [messageKind, setMessageKind] = useState<'success' | 'error' | 'info'>('info')
  const [tokens, setTokens] = useState<Record<Network, string>>({ telegram: '', max: '', vk: '', instagram: '', ok: '' })
  const [okSessionSecret, setOkSessionSecret] = useState('')
  const [vkMediaToken, setVkMediaToken] = useState('')
  const [busy, setBusy] = useState('')

  const load = useCallback(async () => {
    const result = await adminGet<{ settings: SocialSettings; queue: typeof queue; worker: typeof worker; operational: boolean; message: string }>('/admin/social-v2')
    if (result?.settings) setSettings(result.settings)
    setQueue(result?.queue || [])
    setWorker(result?.worker || { running: false })
    setOperational(Boolean(result?.operational))
  }, [])
  useEffect(() => { queueMicrotask(() => { void load() }) }, [load])

  const patchNetwork = (network: Network, patch: Partial<NetworkSettings>) => setSettings((current) => ({
    ...current, networks: { ...current.networks, [network]: { ...current.networks[network], ...patch } },
  }))
  const request = async (path: string, init: RequestInit): Promise<ApiPayload> => {
    const response = await adminFetch(path, init)
    const payload = await response.json().catch(() => ({})) as ApiPayload
    if (!response.ok) throw new Error(String(payload.detail || payload.message || 'Операция не выполнена'))
    return payload
  }
  const run = async (key: string, action: () => Promise<void>) => {
    setBusy(key)
    try { await action() } catch (error) {
      setMessageKind('error')
      setMessage(error instanceof Error ? error.message : 'Операция не выполнена')
    } finally { setBusy('') }
  }
  const saveCredentials = (network: Network) => run(`${network}:save`, async () => {
    await request(`/admin/social/${network}/credentials-v2`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        token: tokens[network], targetId: settings.networks[network].targetId || '',
        applicationKey: settings.networks[network].applicationKey || '',
        sessionSecret: network === 'ok' ? okSessionSecret : '',
        mediaToken: network === 'vk' ? vkMediaToken : '',
      }),
    })
    setTokens((current) => ({ ...current, [network]: '' }))
    if (network === 'ok') setOkSessionSecret('')
    if (network === 'vk') setVkMediaToken('')
    setMessageKind('success'); setMessage('Доступ сохранён. Нажмите «Проверить», чтобы подтвердить аккаунт и получателя.')
    await load()
  })
  const check = (network: Network) => run(`${network}:check`, async () => {
    const payload = await request(`/admin/social/${network}/check-v2`, { method: 'POST' })
    const identity = payload.result?.identity || 'аккаунт подтверждён'
    const target = payload.result?.target
    const targetName = target?.title || target?.username || target?.id
    setMessageKind('success')
    setMessage(`${providers.find(([id]) => id === network)?.[1]}: ${identity}${targetName ? ` → ${targetName}` : ''}. Проверка пройдена.`)
    await load()
  })
  const testTelegram = () => run('telegram:test', async () => {
    const payload = await request('/admin/social/telegram/test-delivery-v2', { method: 'POST' })
    setMessageKind('success')
    setMessage(`Тестовое сообщение доставлено в Telegram. message_id: ${payload.messageId}.`)
  })
  const testMax = () => run('max:test', async () => {
    const payload = await request('/admin/social/max/test-delivery-v2', { method: 'POST' })
    setMessageKind('success')
    setMessage(`Тестовое сообщение доставлено в MAX. message_id: ${payload.messageId}.`)
  })
  const testVk = () => run('vk:test', async () => {
    const payload = await request('/admin/social/vk/test-delivery-v2', { method: 'POST' })
    setMessageKind('success')
    setMessage(`Тестовая публикация создана во ВКонтакте. post_id: ${payload.messageId}.`)
  })
  const removeCredentials = (network: Network) => {
    if (!window.confirm('Удалить сохранённый доступ к этой социальной сети?')) return
    void run(`${network}:delete`, async () => {
      await request(`/admin/social/${network}/credentials-v2`, { method: 'DELETE' })
      setMessageKind('success'); setMessage('Сохранённый доступ удалён.')
      await load()
    })
  }
  const save = () => run('settings:save', async () => {
    const result = await adminPut<{ message: string }>('/admin/social-v2', { settings })
    setMessageKind('success'); setMessage(result?.message || 'Настройки публикации сохранены.')
    await load()
  })

  return <div className="admin-social-page">
    <div className="admin-section-headline">
      <div><h3><Share2 size={18} /> Социальные сети</h3><p>Подключение каналов, проверка доступа и управление автопубликацией.</p></div>
      <span className={`admin-social-health ${operational ? 'ready' : ''}`}>{operational ? 'Доставка включена' : 'Доставка выключена'}</span>
    </div>
    <div className="admin-social-toolbar">
      <div className="admin-social-trigger"><b>Когда публикуем?</b><span>Сразу после публикации работы в нашей ленте — только в отмеченные ниже форматы.</span></div>
      <Switch checked={settings.masterEnabled && settings.autoPublish} onChange={(checked) => setSettings({ ...settings, masterEnabled: checked, autoPublish: checked })} title="Публиковать вместе с лентой" note="Один понятный запуск для всех выбранных сетей" />
      <button disabled={busy !== ''} onClick={() => void save()}>{busy === 'settings:save' ? 'Сохраняем…' : 'Сохранить настройки'}</button>
    </div>
    <p className="admin-social-security">Ключи хранятся локально в защищённом DPAPI-хранилище и не возвращаются в браузер.</p>

    <div className="admin-social-grid">
      {providers.map(([id, label, icon, subtitle]) => {
        const network = settings.networks[id]
        const status = network.verified ? 'Проверено' : network.configured ? 'Нужна проверка' : 'Не подключено'
        return <article key={id} className={network.verified ? 'verified' : ''}>
          <header className="admin-social-card-head">
            <div className="admin-social-provider-icon">{icon}</div>
            <div><b>{label}</b><small>{subtitle}</small></div>
            <span className={`admin-social-status ${network.verified ? 'ready' : ''}`}>{network.verified && <CheckCircle2 size={13} />}{status}</span>
          </header>
          <div className="admin-social-fields">
            <label><span>Ключ доступа</span><input type="password" value={tokens[id]} onChange={(e) => setTokens({ ...tokens, [id]: e.target.value })} placeholder={network.configured ? 'Оставьте пустым, чтобы не менять' : 'Вставьте ключ'} autoComplete="new-password" /></label>
            {id === 'vk' && <label><span>Пользовательский VK token для фото</span><input type="password" value={vkMediaToken} onChange={(e) => setVkMediaToken(e.target.value)} placeholder={network.mediaConfigured ? 'Сохранён — оставьте пустым, чтобы не менять' : 'Вставьте пользовательский VK token'} autoComplete="new-password" /></label>}
            {id === 'ok' && <label><span>Session secret</span><input type="password" value={okSessionSecret} onChange={(e) => setOkSessionSecret(e.target.value)} autoComplete="new-password" /></label>}
            {id === 'ok' && <label><span>Application key</span><input value={network.applicationKey || ''} onChange={(e) => patchNetwork(id, { applicationKey: e.target.value })} /></label>}
            <label><span>{id === 'telegram' || id === 'max' ? 'Канал / chat ID' : id === 'vk' || id === 'ok' ? 'ID группы' : 'Instagram account ID'}</span><input value={network.targetId || ''} onChange={(e) => patchNetwork(id, { targetId: e.target.value })} placeholder={id === 'telegram' ? '@channel или -100…' : 'ID'} /></label>
          </div>
          {network.lastError && <p className="admin-social-error">{network.lastError}</p>}
          <div className="admin-social-card-footer">
            <div className="admin-social-modes">
              <Switch compact checked={network.enabled} onChange={(checked) => patchNetwork(id, { enabled: checked })} title="Пост" note="" />
              <Switch
                compact
                disabled
                checked={Boolean(network.storyEnabled)}
                onChange={(checked) => patchNetwork(id, { storyEnabled: checked })}
                title="История"
                note={
                  id === 'telegram' ? 'Нужен Business Connection ID'
                    : id === 'vk' ? 'Нужен пользовательский токен Stories'
                      : id === 'max' ? 'В MAX Bot API метода Stories нет'
                        : id === 'ok' ? 'В API OK метода Stories нет'
                          : 'Нужен Instagram Content Publishing доступ'
                }
              />
            </div>
            <div className="admin-social-actions">
              <button disabled={busy !== '' || (!tokens[id] && !network.configured)} onClick={() => void saveCredentials(id)}>{busy === `${id}:save` ? 'Сохраняем…' : 'Сохранить'}</button>
              <button className="secondary" disabled={busy !== '' || !network.configured} onClick={() => void check(id)}>{busy === `${id}:check` ? 'Проверяем…' : 'Проверить'}</button>
              {id === 'telegram' && <button className="secondary" disabled={busy !== '' || !network.verified} onClick={() => void testTelegram()}>{busy === 'telegram:test' ? 'Отправляем…' : 'Тест'}</button>}
              {id === 'max' && <button className="secondary" disabled={busy !== '' || !network.verified} onClick={() => void testMax()}>{busy === 'max:test' ? 'Отправляем…' : 'Тест'}</button>}
              {id === 'vk' && <button className="secondary" disabled={busy !== '' || !network.verified} onClick={() => void testVk()}>{busy === 'vk:test' ? 'Публикуем…' : 'Тест'}</button>}
              <button className="admin-social-delete" title="Удалить доступ" disabled={busy !== '' || !network.configured} onClick={() => removeCredentials(id)}>Удалить</button>
            </div>
          </div>
        </article>
      })}
    </div>
    {message && <p className={`admin-social-note ${messageKind}`}>{message}</p>}
    <div className="admin-social-runtime">
      <div><b>Сервис доставки</b><span>Автопубликация: {operational ? 'готова' : 'выключена'} · worker: {worker.running ? 'работает' : 'остановлен'}</span></div>
      <div><b>Очередь</b><span>{queue.length ? queue.map((row) => `${row.network}: ${row.status} — ${row.count}`).join(' · ') : 'Заданий нет'}</span></div>
      {worker.lastError && <p className="admin-social-error">{worker.lastError}</p>}
    </div>
  </div>
}

function Switch({ checked, onChange, title, note, compact = false, disabled = false }: { checked: boolean; onChange: (checked: boolean) => void; title: string; note: string; compact?: boolean; disabled?: boolean }) {
  return <label className={`admin-social-switch ${compact ? 'compact' : ''} ${disabled ? 'disabled' : ''}`}>
    <input type="checkbox" disabled={disabled} checked={checked} onChange={(event) => onChange(event.target.checked)} />
    <span className="admin-social-switch-track" aria-hidden="true"><span /></span>
    <span><b>{title}</b>{note && <small>{note}</small>}</span>
  </label>
}
