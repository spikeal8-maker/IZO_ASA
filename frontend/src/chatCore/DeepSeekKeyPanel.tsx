import { useEffect, useState } from 'react'
import { Check, KeyRound, Trash2, X } from 'lucide-react'

import {
  deleteDeepSeekKey,
  loadDeepSeekStatus,
  saveDeepSeekKey,
  testDeepSeekConnection,
  type DeepSeekProviderStatus,
} from './deepSeekApi.ts'
import './chatCore.css'

type Props = {
  open: boolean
  status: DeepSeekProviderStatus | null
  onClose: () => void
  onStatus: (status: DeepSeekProviderStatus) => void
}

export function DeepSeekKeyPanel({ open, status, onClose, onStatus }: Props) {
  const [key, setKey] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')

  useEffect(() => {
    if (!open) {
      setKey('')
      setMessage('')
    }
  }, [open])

  if (!open) return null

  const refresh = async () => {
    const next = await loadDeepSeekStatus()
    onStatus(next)
    return next
  }

  const save = async (verify: boolean) => {
    const value = key.trim()
    if (!value && !status?.configured) {
      setMessage('Введите DeepSeek API key.')
      return
    }
    setBusy(true)
    setMessage('')
    try {
      if (value) await saveDeepSeekKey(value)
      setKey('')
      if (verify) {
        const checked = await testDeepSeekConnection()
        setMessage(checked.connected ? `Подключение работает · моделей: ${checked.models.length}` : 'Подключение не подтверждено.')
      } else {
        setMessage('API key сохранён безопасно.')
      }
      await refresh()
    } catch (caught) {
      setMessage(caught instanceof Error ? caught.message : 'Не удалось настроить DeepSeek.')
    } finally {
      setBusy(false)
    }
  }

  const remove = async () => {
    setBusy(true)
    setMessage('')
    try {
      await deleteDeepSeekKey()
      await refresh()
      setMessage('DeepSeek API key удалён.')
    } catch (caught) {
      setMessage(caught instanceof Error ? caught.message : 'Не удалось удалить API key.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <button className="portable-provider-backdrop" type="button" aria-label="Закрыть настройки DeepSeek" onClick={onClose} />
      <section className="portable-provider-panel" role="dialog" aria-modal="true" aria-label="DeepSeek API">
        <header>
          <span><KeyRound />DeepSeek API</span>
          <button type="button" aria-label="Закрыть" onClick={onClose}><X /></button>
        </header>
        <p>Ключ хранится только на backend в зашифрованном пользовательском secret store и не сохраняется в браузере.</p>
        <label>
          <span>API key</span>
          <input
            type="password"
            autoComplete="off"
            spellCheck={false}
            value={key}
            placeholder={status?.configured ? 'Ключ уже настроен' : 'Введите DeepSeek API key'}
            onChange={(event) => setKey(event.target.value)}
          />
        </label>
        <div className="portable-provider-status">
          {status?.configured ? <><Check />Ключ настроен</> : 'Ключ не настроен'}
        </div>
        {message && <div className="portable-provider-message" role="status">{message}</div>}
        <footer>
          <button type="button" disabled={busy || (!key.trim() && !status?.configured)} onClick={() => void save(true)}>
            Сохранить и проверить
          </button>
          <button type="button" disabled={busy || !key.trim()} onClick={() => void save(false)}>
            Сохранить
          </button>
          {status?.configured && (
            <button className="is-danger" type="button" disabled={busy} onClick={() => void remove()}>
              <Trash2 />
              Удалить
            </button>
          )}
        </footer>
      </section>
    </>
  )
}
