import { useCallback, useEffect, useState } from 'react'
import {
  Bot,
  CheckCircle2,
  CircleAlert,
  ExternalLink,
  KeyRound,
  Link2,
  RefreshCw,
  Save,
  ShieldAlert,
  Trash2,
} from 'lucide-react'
import { adminFetch, adminGet, type AdminRecord } from './adminApi'

type BotMode = 'disabled' | 'polling' | 'webhook'
type BotConfig = {
  telegram: {
    mode: BotMode
    pollingEnabled: boolean
    botUsername: string
    deepLinkBase: string
  }
  max: {
    mode: BotMode
    pollingEnabled: boolean
    apiBaseUrl: string
    deepLinkBase: string
    webhookUrl: string
    updateTypes: string[]
  }
  public: {
    siteUrl: string
    backendUrl: string
  }
}

const EMPTY_CONFIG: BotConfig = {
  telegram: { mode: 'disabled', pollingEnabled: false, botUsername: '', deepLinkBase: '' },
  max: {
    mode: 'disabled',
    pollingEnabled: false,
    apiBaseUrl: 'https://platform-api2.max.ru',
    deepLinkBase: '',
    webhookUrl: '',
    updateTypes: ['bot_started', 'message_callback', 'message_created'],
  },
  public: { siteUrl: 'https://izo.alikinas.ru', backendUrl: 'https://izo.alikinas.ru' },
}

type Provider = 'telegram' | 'max'

function statusLabel(value: unknown) {
  if (value === 'ok') return 'Подключение проверено'
  if (value === 'not_configured') return 'Токен не настроен'
  if (value === 'unauthorized') return 'Неверный токен'
  if (value === 'unavailable') return 'Сервис недоступен'
  if (value === 'invalid_response') return 'Некорректный ответ сервиса'
  return 'Проверка ещё не выполнялась'
}

function fmtDate(value: unknown) {
  if (!value) return '—'
  const date = new Date(String(value))
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString('ru-RU')
}

async function request(path: string, init: RequestInit = {}) {
  const response = await adminFetch(path, init)
  const payload = await response.json().catch(() => ({})) as AdminRecord
  if (!response.ok) throw new Error(String(payload.detail || 'Операция не выполнена'))
  return payload
}

export default function AdminBots() {
  const [config, setConfig] = useState<BotConfig>(EMPTY_CONFIG)
  const [status, setStatus] = useState<AdminRecord | null>(null)
  const [tokens, setTokens] = useState<Record<Provider, string>>({ telegram: '', max: '' })
  const [busy, setBusy] = useState('')
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setBusy('load')
    setError('')
    const [configPayload, statusPayload] = await Promise.all([
      adminGet<AdminRecord>('/admin/bots/config-v2'),
      adminGet<AdminRecord>('/admin/bots/status-v2'),
    ])
    if (configPayload?.config) setConfig(configPayload.config as unknown as BotConfig)
    if (statusPayload) setStatus(statusPayload)
    if (!configPayload || !statusPayload) setError('Не удалось получить состояние ботов.')
    setBusy('')
  }, [])

  useEffect(() => {
    queueMicrotask(() => { void load() })
  }, [load])

  const providerStatus = (provider: Provider) => (status?.[provider] || {}) as AdminRecord
  const publicStatus = (status?.public || {}) as AdminRecord
  const conflictWarning = String(status?.conflictWarning || 'Убедитесь, что боты отключены на старом сервере перед включением получения обновлений.')

  const run = async (key: string, action: () => Promise<unknown>, success: string) => {
    setBusy(key)
    setError('')
    setMessage('')
    try {
      await action()
      setMessage(success)
      await load()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Операция не выполнена')
      setBusy('')
    }
  }

  const saveConfig = async () => {
    const oldConfig = (status?.config || EMPTY_CONFIG) as unknown as BotConfig
    const changedMode = oldConfig.telegram.mode !== config.telegram.mode || oldConfig.max.mode !== config.max.mode
    if (changedMode && !window.confirm(`${conflictWarning}\n\nСохранить новый режим? Он не запустится автоматически и потребует перезапуска backend.`)) return
    await run(
      'config',
      () => request('/admin/bots/config-v2', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ config, confirmModeChange: changedMode }),
      }),
      changedMode ? 'Настройки сохранены. Для применения режима потребуется контролируемый перезапуск backend.' : 'Настройки ботов сохранены.',
    )
  }

  const saveToken = async (provider: Provider) => {
    const token = tokens[provider].trim()
    if (!token) return
    await run(
      `${provider}-token`,
      () => request(`/admin/bots/${provider}/token-v2`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token, verify: true }),
      }).then((result) => {
        setTokens((current) => ({ ...current, [provider]: '' }))
        return result
      }),
      `${provider === 'telegram' ? 'Telegram' : 'MAX'}: токен сохранён в DPAPI и проверен. Получение обновлений не включалось.`,
    )
  }

  const deleteToken = async (provider: Provider) => {
    if (!window.confirm(`Удалить сохранённый токен ${provider === 'telegram' ? 'Telegram' : 'MAX'} из DPAPI-хранилища?`)) return
    await run(
      `${provider}-delete-token`,
      () => request(`/admin/bots/${provider}/token-v2`, { method: 'DELETE' }),
      'Токен удалён из защищённого хранилища.',
    )
  }

  const verify = (provider: Provider) => run(
    `${provider}-verify`,
    () => request(`/admin/bots/${provider}/verify-v2`, { method: 'POST' }),
    `${provider === 'telegram' ? 'Telegram' : 'MAX'}: подключение проверено.`,
  )

  const generateSecret = (provider: Provider) => run(
    `${provider}-secret`,
    () => request(`/admin/bots/${provider}/webhook-secret-v2`, { method: 'POST' }),
    'Секрет webhook создан и сохранён в DPAPI. Его значение не отображается.',
  )

  const webhookAction = async (provider: Provider, action: 'set' | 'delete') => {
    const verb = action === 'set' ? 'перенести webhook на этот сервер' : 'удалить действующий webhook'
    if (!window.confirm(`${conflictWarning}\n\nВы действительно хотите ${verb}?`)) return
    await run(
      `${provider}-${action}-webhook`,
      () => request(`/admin/bots/${provider}/${action === 'set' ? 'set' : 'delete'}-webhook-v2`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ confirm: true }),
      }),
      action === 'set' ? 'Webhook зарегистрирован на указанный публичный адрес.' : 'Webhook удалён.',
    )
  }

  const summary = (['telegram', 'max'] as Provider[]).map((provider) => {
    const item = providerStatus(provider)
    const probe = (item.probe || {}) as AdminRecord
    return {
      provider,
      title: provider === 'telegram' ? 'Telegram' : 'MAX',
      ok: Boolean(probe.ok),
      configured: Boolean(item.tokenConfigured),
      mode: String(item.mode || 'disabled'),
      lastCheck: ((item.lastCheck || {}) as AdminRecord).checkedAt,
    }
  })

  const renderProvider = (provider: Provider) => {
    const item = providerStatus(provider)
    const probe = (item.probe || {}) as AdminRecord
    const cfg = config[provider]
    const isTelegram = provider === 'telegram'
    const title = isTelegram ? 'Telegram' : 'MAX'
    const identity = isTelegram
      ? [probe.name, probe.username ? `@${String(probe.username).replace(/^@/, '')}` : '', probe.bot_id].filter(Boolean).join(' · ')
      : [probe.name, probe.nickname, probe.bot_id].filter(Boolean).join(' · ')
    const lastCheck = (item.lastCheck || {}) as AdminRecord
    return (
      <article className="admin-bot-card">
        <header>
          <div className="admin-bot-title"><Bot /><div><h4>{title}</h4><p>{statusLabel(probe.status)}</p></div></div>
          <span className={`admin-bot-state ${probe.ok ? 'ok' : item.tokenConfigured ? 'warn' : 'off'}`}>
            {probe.ok ? 'готов' : item.tokenConfigured ? 'нужна проверка' : 'не настроен'}
          </span>
        </header>

        <div className="admin-bot-facts">
          <span><small>Токен</small><b>{item.tokenConfigured ? 'сохранён' : 'отсутствует'}</b></span>
          <span><small>Источник</small><b>{item.tokenSource === 'dpapi' ? 'защищённое хранилище' : item.tokenSource === 'environment' ? 'переменная службы' : '—'}</b></span>
          <span><small>Режим</small><b>{String(item.mode || 'disabled')}</b></span>
          <span><small>Polling</small><b>{item.pollingActive ? 'активен' : 'выключен'}</b></span>
          <span><small>Webhook</small><b>{item.webhookReady ? 'готов' : 'не готов'}</b></span>
          <span><small>Последняя проверка</small><b>{fmtDate(lastCheck.checkedAt)}</b></span>
          <span><small>Бот</small><b>{identity || '—'}</b></span>
          <span><small>Последняя ошибка</small><b>{String(lastCheck.error || probe.error_type || 'нет')}</b></span>
        </div>

        <section className="admin-bot-secret">
          <label>
            {item.tokenConfigured ? `Заменить токен ${title}` : `Токен ${title}`}
            <input
              type="password"
              autoComplete="new-password"
              value={tokens[provider]}
              onChange={(event) => setTokens((current) => ({ ...current, [provider]: event.target.value }))}
              placeholder={item.tokenConfigured ? 'Введите новый токен только для замены' : 'Введите токен'}
            />
          </label>
          <div className="admin-bot-actions">
            <button className="secondary" disabled={!tokens[provider].trim() || busy === `${provider}-token`} onClick={() => { void saveToken(provider) }}><Save /> Сохранить и проверить</button>
            <button className="secondary" disabled={!item.tokenConfigured || busy === `${provider}-verify`} onClick={() => { void verify(provider) }}><RefreshCw /> Проверить</button>
            <button className="danger" disabled={!item.tokenConfigured || busy === `${provider}-delete-token`} onClick={() => { void deleteToken(provider) }}><Trash2 /> Удалить токен</button>
          </div>
          <small><KeyRound /> Значение не возвращается из API и после сохранения не показывается.</small>
        </section>

        <div className="admin-bot-fields">
          <label>Режим
            <select value={cfg.mode} onChange={(event) => setConfig((current) => ({ ...current, [provider]: { ...current[provider], mode: event.target.value as BotMode } }))}>
              <option value="disabled">disabled</option>
              <option value="polling">polling</option>
              <option value="webhook">webhook</option>
            </select>
          </label>
          <label className="admin-check"><input type="checkbox" checked={cfg.pollingEnabled} onChange={(event) => setConfig((current) => ({ ...current, [provider]: { ...current[provider], pollingEnabled: event.target.checked } }))} /> Разрешить polling после перезапуска</label>
          {isTelegram ? <>
            <label>Username бота<input value={config.telegram.botUsername} onChange={(event) => setConfig((current) => ({ ...current, telegram: { ...current.telegram, botUsername: event.target.value } }))} placeholder="@izo_bot" /></label>
            <label>Deep link<input value={config.telegram.deepLinkBase} onChange={(event) => setConfig((current) => ({ ...current, telegram: { ...current.telegram, deepLinkBase: event.target.value } }))} placeholder="https://t.me/..." /></label>
          </> : <>
            <label>MAX API<input value={config.max.apiBaseUrl} onChange={(event) => setConfig((current) => ({ ...current, max: { ...current.max, apiBaseUrl: event.target.value } }))} /></label>
            <label>Deep link<input value={config.max.deepLinkBase} onChange={(event) => setConfig((current) => ({ ...current, max: { ...current.max, deepLinkBase: event.target.value } }))} placeholder="https://max.ru/..." /></label>
            <label>Webhook URL<input value={config.max.webhookUrl} onChange={(event) => setConfig((current) => ({ ...current, max: { ...current.max, webhookUrl: event.target.value } }))} placeholder="Оставьте пустым для вычисляемого адреса" /></label>
            <label>События подписки<input value={config.max.updateTypes.join(', ')} onChange={(event) => setConfig((current) => ({ ...current, max: { ...current.max, updateTypes: event.target.value.split(',').map((value) => value.trim()).filter(Boolean) } }))} /></label>
          </>}
        </div>

        <section className="admin-bot-webhook">
          <div><Link2 /><span><b>{String(item.webhookUrl || 'URL не сформирован')}</b><small>Секрет: {item.webhookSecretConfigured ? 'сохранён в DPAPI' : 'не создан'}</small></span></div>
          {isTelegram && Boolean((probe.webhook as AdminRecord | undefined)?.configured) && <p className="admin-bot-restart"><ShieldAlert /> У Telegram уже установлен webhook: {String((probe.webhook as AdminRecord).url || 'адрес скрыт')}.</p>}
          {!isTelegram && Array.isArray(probe.subscriptions) && probe.subscriptions.length > 0 && <p className="admin-bot-restart"><ShieldAlert /> В MAX уже есть активные подписки: {probe.subscriptions.length}.</p>}
          <div className="admin-bot-actions">
            <button className="secondary" onClick={() => { void generateSecret(provider) }}>Сгенерировать секрет</button>
            <button className="secondary" disabled={!item.webhookReady} onClick={() => { void webhookAction(provider, 'set') }}>Зарегистрировать webhook</button>
            <button className="danger" disabled={!item.tokenConfigured} onClick={() => { void webhookAction(provider, 'delete') }}>Удалить webhook</button>
            {isTelegram && <button className="secondary" disabled={!item.tokenConfigured} onClick={() => { void run('telegram-configure', () => request('/admin/bots/telegram/configure-v2', { method: 'POST' }), 'Команды Telegram настроены.') }}>Настроить команды</button>}
          </div>
        </section>

        {Boolean(item.restartRequired) && <p className="admin-bot-restart"><CircleAlert /> Сохранённая конфигурация отличается от запущенного backend. Нужен контролируемый перезапуск службы.</p>}
      </article>
    )
  }

  return (
    <div className="admin-section admin-bots-page">
      <div className="admin-section-head">
        <div><h3>Боты ИЗО АСА</h3><p>Безопасная настройка Telegram и MAX без автоматического переключения действующего сервера.</p></div>
        <button className="secondary" disabled={busy === 'load'} onClick={() => { void load() }}><RefreshCw /> Обновить</button>
      </div>

      <div className="admin-bot-warning"><ShieldAlert /><div><strong>Защита от двойного сервера</strong><p>{conflictWarning}</p></div></div>

      <div className="admin-bot-summary">
        {summary.map((item) => <span key={item.provider} className={item.ok ? 'ok' : item.configured ? 'warn' : 'off'}>{item.ok ? <CheckCircle2 /> : <CircleAlert />}<b>{item.title}</b><small>{item.mode} · {fmtDate(item.lastCheck)}</small></span>)}
        <span className={publicStatus.ok ? 'ok' : 'warn'}>{publicStatus.ok ? <CheckCircle2 /> : <CircleAlert />}<b>Публичный HTTPS</b><small>{String(publicStatus.url || 'не настроен')} · {String(publicStatus.source || 'источник не определён')}</small></span>
      </div>

      <section className="admin-bot-public">
        <div><h4>Публичные адреса</h4><p>Туннель определяется только проверкой URL. Админка не запускает и не перенастраивает FRP.</p></div>
        <label>Адрес сайта<input value={config.public.siteUrl} onChange={(event) => setConfig((current) => ({ ...current, public: { ...current.public, siteUrl: event.target.value } }))} /></label>
        <label>Адрес backend<input value={config.public.backendUrl} onChange={(event) => setConfig((current) => ({ ...current, public: { ...current.public, backendUrl: event.target.value } }))} /></label>
        <a href={config.public.backendUrl} target="_blank" rel="noreferrer">Открыть адрес <ExternalLink /></a>
      </section>

      <div className="admin-bot-grid">{renderProvider('telegram')}{renderProvider('max')}</div>

      <div className="admin-bot-savebar">
        <span>{message || error || 'Сохранение настроек не включает polling и не регистрирует webhook.'}</span>
        <button className="secondary" disabled={busy === 'config'} onClick={() => { void saveConfig() }}><Save /> Сохранить настройки</button>
      </div>
      {error && <p className="admin-mail-message error">{error}</p>}
    </div>
  )
}
