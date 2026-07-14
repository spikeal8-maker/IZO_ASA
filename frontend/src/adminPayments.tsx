import { useCallback, useEffect, useState } from 'react'
import { adminGet, adminPut, type AdminRecord } from './adminApi'

type PaymentStatus = AdminRecord & {
  configured?: boolean
  webhook_url?: string
  config?: AdminRecord
  summary?: AdminRecord
  packages?: AdminRecord[]
  payments?: AdminRecord[]
  events?: AdminRecord[]
}

export default function AdminPayments() {
  const [data, setData] = useState<PaymentStatus | null>(null)
  const [shopId, setShopId] = useState('')
  const [secretKey, setSecretKey] = useState('')
  const [testMode, setTestMode] = useState(true)
  const [message, setMessage] = useState('')
  const load = useCallback(async () => {
    const next = await adminGet<PaymentStatus>('/admin/payments/status-v2')
    const config = next?.config || {}
    setData(next)
    setShopId(String(config.shop_id || ''))
    setTestMode(Boolean(config.test_mode ?? true))
  }, [])

  useEffect(() => { queueMicrotask(() => { void load() }) }, [load])

  const save = async () => {
    const result = await adminPut<AdminRecord>('/admin/payments/config-v2', {
      shop_id: shopId.trim(),
      secret_key: secretKey.trim() || null,
      test_mode: testMode,
    })
    setMessage(result?.ok ? 'Настройки ЮKassa сохранены' : 'Не удалось сохранить настройки')
    if (result?.ok) setSecretKey('')
    await load()
  }

  const updatePackage = (code: string, patch: AdminRecord) => {
    setData((current) => current ? { ...current, packages: (current.packages || []).map((item) => String(item.code) === code ? { ...item, ...patch } : item) } : current)
  }
  const savePackage = async (item: AdminRecord) => {
    const result = await adminPut<AdminRecord>(`/admin/payments/packages/${String(item.code)}-v2`, {
      name: String(item.name || ''), price_amount: Number(item.price_amount || 0),
      token_amount: Number(item.token_amount || 0), is_active: Boolean(item.is_active),
    })
    setMessage(result?.ok ? `Пакет ${String(item.name)} сохранен` : 'Не удалось сохранить пакет')
    await load()
  }

  const summary = data?.summary || {}
  const config = data?.config || {}
  return (
    <div className="admin-section admin-payments-page">
      <div className="admin-section-head">
        <div><h3>Платежи</h3><p>ЮKassa, счета, начисление токенов и контроль webhook.</p></div>
        <span className={data?.configured ? 'status ok' : 'status warn'}>{data?.configured ? 'настроено' : 'нужны реквизиты магазина'}</span>
      </div>
      <div className="admin-mail-grid">
        <article className="admin-mail-card">
          <h4>Подключение ЮKassa</h4>
          <label>shopId<input value={shopId} onChange={(event) => setShopId(event.target.value)} placeholder="Идентификатор магазина" /></label>
          <label>Секретный ключ<input type="password" value={secretKey} onChange={(event) => setSecretKey(event.target.value)} placeholder={config.secret_key ? 'Ключ сохранен, можно заменить' : 'Секретный ключ API'} /></label>
          <label className="admin-check"><input type="checkbox" checked={testMode} onChange={(event) => setTestMode(event.target.checked)} /> Тестовый магазин</label>
          <button className="secondary" disabled={!shopId.trim() || (!secretKey && !config.secret_key)} onClick={save}>Сохранить</button>
          {message && <small>{message}</small>}
        </article>
        <article className="admin-mail-card">
          <h4>Сводка</h4>
          <p>Оплат: <b>{String(summary.paid || 0)}</b></p>
          <p>Ожидают: <b>{String(summary.pending || 0)}</b></p>
          <p>Оборот: <b>{Number(summary.revenue_rub || 0).toLocaleString('ru-RU')} ₽</b></p>
          <p>Всего попыток: <b>{String(summary.total || 0)}</b></p>
        </article>
        <article className="admin-mail-card">
          <h4>Webhook</h4>
          <p>Укажите этот адрес в кабинете ЮKassa для события <b>payment.succeeded</b>.</p>
          <input readOnly value={String(data?.webhook_url || '')} onFocus={(event) => event.currentTarget.select()} />
        </article>
      </div>
      <div className="admin-mail-tables">
        <article><h4>Пакеты</h4><table><tbody>{(data?.packages || []).map((item) => <tr key={String(item.code)}><td><input value={String(item.name)} disabled={!String(item.code).startsWith('tokens_')} onChange={(event) => updatePackage(String(item.code), { name: event.target.value })} /><small>{String(item.code)}</small></td><td><input type="number" min="1" value={Number(item.token_amount || 0)} disabled={!String(item.code).startsWith('tokens_')} onChange={(event) => updatePackage(String(item.code), { token_amount: Number(event.target.value) })} /></td><td><input type="number" min="1" value={Number(item.price_amount || 0)} disabled={!String(item.code).startsWith('tokens_')} onChange={(event) => updatePackage(String(item.code), { price_amount: Number(event.target.value) })} /></td><td>{String(item.code).startsWith('tokens_') && <button className="secondary" onClick={() => { void savePackage(item) }}>Сохранить</button>}</td></tr>)}</tbody></table></article>
        <article><h4>Последние платежи</h4><table><tbody>{(data?.payments || []).map((item) => <tr key={String(item.id)}><td><b>{String(item.status)}</b><small>{String(item.created_at || '')}</small></td><td>{Number(item.amount || 0).toLocaleString('ru-RU')} ₽</td><td>{String(item.provider)}</td></tr>)}</tbody></table></article>
      </div>
      <div className="admin-mail-tables"><article><h4>События ЮKassa</h4><table><tbody>{(data?.events || []).map((item, index) => <tr key={`${String(item.provider_payment_id)}-${index}`}><td><b>{String(item.event_type)}</b><small>{String(item.received_at || '')}</small></td><td>{String(item.status)}</td><td>{String(item.error || '')}</td></tr>)}</tbody></table></article></div>
    </div>
  )
}
