import { useCallback, useEffect, useState } from 'react'
import { adminFetch } from './adminApi'
import './adminOpenAISettings.css'

type OpenAIModel = { id: string; label: string }
type OpenAIStatus = {
  ok: boolean
  enabled: boolean
  model: string
  keyConfigured: boolean
  secretStoreReady: boolean
  models: OpenAIModel[]
  liveVerified: boolean
}
type OpenAIResult = { ok?: boolean; model?: string; detail?: string }

const REASON = 'Ручная операция администратора: подключение OpenAI'

async function responseError(response: Response): Promise<string> {
  const parsed = await response.json().catch(() => null) as { detail?: unknown } | null
  return typeof parsed?.detail === 'string' ? parsed.detail.slice(0, 220) : `Ошибка запроса (HTTP ${response.status}).`
}

export default function AdminOpenAISettings() {
  const [status, setStatus] = useState<OpenAIStatus | null>(null)
  const [key, setKey] = useState('')
  const [selectedModel, setSelectedModel] = useState('')
  const [enabled, setEnabled] = useState(false)
  const [busy, setBusy] = useState(false)
  const [checking, setChecking] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  const refresh = useCallback(async () => {
    const response = await adminFetch('/admin/openai')
    if (!response.ok) throw new Error(await responseError(response))
    const data = await response.json() as OpenAIStatus
    setStatus(data)
    setSelectedModel(data.model)
    setEnabled(data.enabled)
    return data
  }, [])

  useEffect(() => {
    let alive = true
    void (async () => {
      try {
        if (alive) await refresh()
      } catch (failure) {
        if (alive) setError(failure instanceof Error ? failure.message : 'Настройки OpenAI недоступны.')
      }
    })()
    return () => { alive = false }
  }, [refresh])

  const operation = async (path: string, method: 'PUT' | 'POST' | 'DELETE', data: Record<string, unknown>, success: string) => {
    setBusy(true)
    setMessage('')
    setError('')
    try {
      const response = await adminFetch(path, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...data, reason: REASON }),
        cache: 'no-store',
      })
      if (!response.ok) throw new Error(await responseError(response))
      setKey('')
      await refresh()
      setMessage(success)
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'Не удалось выполнить операцию.')
    } finally {
      setBusy(false)
    }
  }

  const verify = async () => {
    setChecking(true)
    setMessage('')
    setError('')
    try {
      const response = await adminFetch('/admin/openai/verify', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason: REASON }), cache: 'no-store',
      })
      if (!response.ok) throw new Error(await responseError(response))
      const data = await response.json() as OpenAIResult
      setMessage(data.ok ? `OpenAI подтвердил доступ к модели ${data.model}. Проверка не генерировала текст.` : 'OpenAI не подтвердил доступ.')
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'Проверка соединения не выполнена.')
    } finally {
      setChecking(false)
    }
  }

  return (
    <section className="openai-admin" aria-label="Подключение OpenAI API">
      <header className="openai-admin-heading">
        <div>
          <h2>OpenAI API</h2>
          <p>Прямое подключение к OpenAI Responses API, независимо от OpenRouter. Модель выбирается для тестового текстового чата.</p>
        </div>
        <span className={`openai-admin-state ${status?.enabled ? 'is-on' : ''}`} role="status">
          {status?.enabled ? 'Провайдер включён' : 'Провайдер отключён'}
        </span>
      </header>

      {!status && !error && <p role="status">Загрузка параметров...</p>}
      {status && <>
        <div className="openai-admin-grid">
          <article className="openai-admin-card">
            <h3>API-ключ</h3>
            <p>Состояние: <strong>{status.keyConfigured ? 'Ключ сохранён на сервере' : 'Ключ не сохранён'}</strong></p>
            {!status.secretStoreReady && <p className="openai-admin-warning" role="alert">Защищённое серверное хранилище не подготовлено. Операции с ключом недоступны.</p>}
            <label htmlFor="openai-project-key">Проектный ключ OpenAI</label>
            <input
              id="openai-project-key"
              type="password"
              autoComplete="off"
              spellCheck={false}
              value={key}
              onChange={(event) => setKey(event.target.value)}
              placeholder="Вставьте проектный ключ"
              disabled={busy || !status.secretStoreReady}
            />
            <small>После сохранения поле очищается. Ключ нельзя посмотреть, скачать или извлечь через интерфейс.</small>
            <div className="openai-admin-buttons">
              <button type="button" onClick={() => void operation('/admin/openai/key', 'PUT', { key }, 'Ключ сохранён в защищённом хранилище.')} disabled={busy || !status.secretStoreReady || key.trim().length < 12}>Сохранить ключ</button>
              <button type="button" className="secondary" onClick={() => void verify()} disabled={busy || checking || !status.keyConfigured}>{checking ? 'Проверка…' : 'Проверить доступ'}</button>
              <button type="button" className="danger" onClick={() => {
                if (window.confirm('Удалить сохранённый ключ OpenAI и отключить этот провайдер?')) {
                  void operation('/admin/openai/key', 'DELETE', {}, 'Ключ удалён, OpenAI отключён.')
                }
              }} disabled={busy || !status.keyConfigured}>Удалить ключ</button>
            </div>
          </article>
          <article className="openai-admin-card">
            <h3>Модель и доступность</h3>
            <label htmlFor="openai-model">Текстовая модель OpenAI</label>
            <select id="openai-model" value={selectedModel} onChange={(event) => setSelectedModel(event.target.value)} disabled={busy}>
              {status.models.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
            </select>
            <label className="openai-admin-switch">
              <input type="checkbox" checked={enabled} onChange={(event) => setEnabled(event.target.checked)} disabled={busy || !status.keyConfigured} />
              Включить OpenAI для администратора
            </label>
            <p>Работает только по явному выбору модели в чате. Автоматического переключения на платные модели нет.</p>
            <button type="button" onClick={() => void operation('/admin/openai/settings', 'PUT', { enabled, model: selectedModel }, 'Настройки OpenAI сохранены.')} disabled={busy || !status.keyConfigured}>Сохранить настройки</button>
            <small>Проверка подключения не является платной генерацией текста. Настоящий чат доступен после настройки защищённого сетевого выхода.</small>
          </article>
        </div>
      </>}
      {message && <p className="openai-admin-success" role="status">{message}</p>}
      {error && <p className="openai-admin-error" role="alert">{error}</p>}
    </section>
  )
}
