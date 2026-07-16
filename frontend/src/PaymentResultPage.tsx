import { CheckCircle2, Clock3, RefreshCw, XCircle } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import './paymentResult.css'

const API = (import.meta as ImportMeta & { env?: { VITE_API_BASE_URL?: string } }).env?.VITE_API_BASE_URL || '/api'

type PaymentData = {
  ok?: boolean
  payment?: { id?: string; status?: string; amount?: number; title?: string; package_code?: string; tokens?: number; invoice_code?: string }
  account?: { plan?: string; plan_expires_at?: string; token_balance?: number }
  verification_error?: string | null
  detail?: string
}

export default function PaymentResultPage() {
  const paymentId = new URLSearchParams(window.location.search).get('payment_id') || ''
  const [data, setData] = useState<PaymentData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    if (!paymentId) {
      setError('В ссылке нет номера платежа.')
      setLoading(false)
      return
    }
    try {
      const response = await fetch(`${API}/billing/payments/${encodeURIComponent(paymentId)}/status-v2`, { credentials: 'include' })
      const result = await response.json().catch(() => ({})) as PaymentData
      if (!response.ok) throw new Error(result.detail || 'Не удалось проверить платеж.')
      setData(result)
      setError('')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Не удалось проверить платеж.')
    } finally {
      setLoading(false)
    }
  }, [paymentId])

  useEffect(() => { queueMicrotask(() => { void load() }) }, [load])
  useEffect(() => {
    if (data?.payment?.status !== 'pending') return
    const timer = window.setInterval(() => { void load() }, 2500)
    return () => window.clearInterval(timer)
  }, [data?.payment?.status, load])

  const status = data?.payment?.status || (loading ? 'pending' : 'error')
  const succeeded = status === 'paid'
  const pending = status === 'pending'
  const Icon = succeeded ? CheckCircle2 : pending ? Clock3 : XCircle
  const title = succeeded ? 'Оплата прошла' : pending ? 'Проверяем оплату' : 'Оплата не завершена'

  return (
    <main className="payment-result-page">
      <section className={`payment-result-panel ${succeeded ? 'success' : pending ? 'pending' : 'failed'}`}>
        <Icon aria-hidden="true" />
        <h1>{title}</h1>
        {loading ? <p>Получаем подтверждение от ЮKassa…</p> : error ? <p>{error}</p> : <>
          <strong>{data?.payment?.title}</strong>
          <p>{Number(data?.payment?.amount || 0).toLocaleString('ru-RU')} ₽ · счет {data?.payment?.invoice_code}</p>
          {succeeded && Number(data?.payment?.tokens || 0) > 0 && <p>Начислено: <b>{data?.payment?.tokens} ток.</b> · баланс: <b>{data?.account?.token_balance} ток.</b></p>}
          {succeeded && String(data?.payment?.package_code || '').startsWith('tariff_') && <p>Тариф активирован: <b>{String(data?.account?.plan || '').toUpperCase()}</b></p>}
          {succeeded && <p className="payment-result-note">Доступы уже обновлены. Можно вернуться в студию и продолжить работу.</p>}
          {pending && <p>Страницу можно оставить открытой: статус обновится автоматически.</p>}
          {data?.verification_error && <small>ЮKassa временно не ответила. Повторная проверка выполнится автоматически.</small>}
        </>}
        <div className="payment-result-actions">
          {(pending || error) && <button type="button" onClick={() => { setLoading(true); void load() }}><RefreshCw aria-hidden="true" />Проверить снова</button>}
          <a href="/profile/tariffs">Тариф и баланс</a>
          <a href="/">К генератору</a>
        </div>
        <div className="payment-result-legal"><a href="/legal/payment">Условия оплаты</a><a href="/legal/refunds">Возвраты</a><a href="/legal/contacts">Реквизиты</a></div>
      </section>
    </main>
  )
}
