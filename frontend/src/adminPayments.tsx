import { CheckCircle2, CircleAlert, ClipboardCopy, ExternalLink, UserRoundCheck } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { adminGet, adminPost, adminPut, type AdminRecord } from './adminApi'

type PaymentStatus = AdminRecord & {
  configured?: boolean
  webhook_url?: string
  config?: AdminRecord
  summary?: AdminRecord
  packages?: AdminRecord[]
  tariff_products?: AdminRecord[]
  payments?: AdminRecord[]
  events?: AdminRecord[]
  legal?: AdminRecord
  legal_readiness?: { ready?: boolean; missing?: string[] }
}

const legalFields = [
  ['seller_name', 'Полное имя / наименование'], ['seller_status', 'Правовой статус'],
  ['inn', 'ИНН'], ['ogrn', 'ОГРН / ОГРНИП (если есть)'], ['legal_address', 'Адрес исполнителя'],
  ['support_email', 'Email поддержки'], ['support_phone', 'Телефон поддержки'],
  ['support_hours', 'Время работы поддержки'], ['service_description', 'Описание услуги'],
] as const

export default function AdminPayments() {
  const [data, setData] = useState<PaymentStatus | null>(null)
  const [shopId, setShopId] = useState('')
  const [secretKey, setSecretKey] = useState('')
  const [testMode, setTestMode] = useState(true)
  const [receiptVatCode, setReceiptVatCode] = useState('1')
  const [paymentSubject, setPaymentSubject] = useState('service')
  const [message, setMessage] = useState('')
  const [reviewMessage, setReviewMessage] = useState('')
  const [legal, setLegal] = useState<AdminRecord>({})
  const load = useCallback(async () => {
    const next = await adminGet<PaymentStatus>('/admin/payments/status-v2')
    const config = next?.config || {}
    setData(next)
    setShopId(String(config.shop_id || ''))
    setTestMode(Boolean(config.test_mode ?? true))
    setReceiptVatCode(String(config.receipt_vat_code || '1'))
    setPaymentSubject(String(config.payment_subject || 'service'))
    setLegal(next?.legal || {})
  }, [])

  useEffect(() => { queueMicrotask(() => { void load() }) }, [load])

  const save = async () => {
    const result = await adminPut<AdminRecord>('/admin/payments/config-v2', {
      shop_id: shopId.trim(),
      secret_key: secretKey.trim() || null,
      test_mode: testMode,
      receipt_vat_code: Number(receiptVatCode),
      payment_subject: paymentSubject,
    })
    setMessage(result?.ok ? 'Настройки ЮKassa сохранены' : 'Не удалось сохранить настройки')
    if (result?.ok) setSecretKey('')
    await load()
  }
  const saveLegal = async () => {
    const result = await adminPost<AdminRecord>('/admin/settings/legal', { settings: legal })
    setMessage(result?.ok ? 'Публичные реквизиты сохранены' : 'Не удалось сохранить реквизиты')
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
  const shopReady = Boolean(shopId.trim())
  const secretReady = Boolean(secretKey.trim() || config.secret_key)
  const receiptReady = Number(receiptVatCode) >= 1 && Number(receiptVatCode) <= 12 && Boolean(paymentSubject)
  const webhookReady = Boolean(data?.webhook_url)
  const publicSiteUrl = String(legal.site_url || 'https://izo.alikinas.ru').replace(/\/+$/, '')
  const reviewTemplate = useMemo(() => [
    'Здравствуйте!',
    '',
    'Доступ к личному кабинету покупателя:',
    `Адрес: ${publicSiteUrl}/profile/tariffs`,
    'Логин: [укажите email проверочного покупателя]',
    'Пароль: [укажите временный пароль]',
    '',
    `Публичная витрина: ${publicSiteUrl}/tariffs`,
    `Оферта: ${publicSiteUrl}/legal/offer`,
    `Условия оплаты: ${publicSiteUrl}/legal/payment`,
    `Возвраты: ${publicSiteUrl}/legal/refunds`,
    `Реквизиты и контакты: ${publicSiteUrl}/legal/contacts`,
    '',
    'Аккаунт является обычным покупательским аккаунтом без административных прав.',
  ].join('\n'), [publicSiteUrl])

  const copyReviewTemplate = async () => {
    try {
      await navigator.clipboard.writeText(reviewTemplate)
      setReviewMessage('Шаблон ответа скопирован. Вставьте логин и временный пароль.')
    } catch {
      setReviewMessage('Не удалось скопировать автоматически. Используйте инструкцию в docs.')
    }
  }

  return (
    <div className="admin-section admin-payments-page">
      <div className="admin-section-head">
        <div><h3>Платежи и пополнения</h3><p>Подключение ЮKassa, разовые пакеты токенов и реальные операции.</p></div>
        <span className={data?.configured ? 'status ok' : 'status warn'}>{data?.configured ? 'настроено' : 'нужны реквизиты магазина'}</span>
      </div>
      <div className="admin-owner-note"><strong>Тарифные цены берутся из «Тарифов»</strong><span>Здесь они показаны только для контроля синхронизации и не имеют второго набора настроек.</span><button className="secondary" onClick={() => { window.location.assign('/admin/tariffs') }}>Открыть тарифы</button></div>
      <div className="admin-payment-tariffs">
        {(data?.tariff_products || []).map((item) => <span key={String(item.code)}><b>{String(item.title)}</b>{Number(item.price_amount || 0).toLocaleString('ru-RU')} ₽/мес</span>)}
      </div>
      <article className={`admin-mail-card admin-yookassa-review ${data?.legal_readiness?.ready ? 'ready' : 'blocked'}`}>
        <div className="admin-section-head">
          <div>
            <h4><UserRoundCheck size={18} /> Проверка личного кабинета ЮKassa</h4>
            <p>Менеджеру передаётся отдельный обычный аккаунт покупателя. Админский логин и основной пароль владельца передавать нельзя.</p>
          </div>
          <span className={data?.legal_readiness?.ready ? 'status ok' : 'status warn'}>{data?.legal_readiness?.ready ? 'можно готовить доступ' : 'сначала заполните реквизиты'}</span>
        </div>
        <div className="admin-review-checks">
          <div className={data?.legal_readiness?.ready ? 'ok' : 'error'}>
            {data?.legal_readiness?.ready ? <CheckCircle2 /> : <CircleAlert />}
            <span><b>Публичные реквизиты</b><small>{data?.legal_readiness?.ready ? 'обязательные поля заполнены' : (data?.legal_readiness?.missing || []).join(', ')}</small></span>
          </div>
          <div className="ok"><CheckCircle2 /><span><b>Вход покупателя</b><small>регистрация и вход по email доступны</small></span></div>
          <div className="ok"><CheckCircle2 /><span><b>Маршрут проверки</b><small>кабинет открывается сразу на вкладке тарифов</small></span></div>
        </div>
        <div className="admin-review-links">
          <a href={`${publicSiteUrl}/profile/tariffs`} target="_blank" rel="noreferrer">Кабинет покупателя <ExternalLink /></a>
          <a href={`${publicSiteUrl}/tariffs`} target="_blank" rel="noreferrer">Витрина <ExternalLink /></a>
          <a href={`${publicSiteUrl}/legal/contacts`} target="_blank" rel="noreferrer">Реквизиты <ExternalLink /></a>
          <button className="secondary" type="button" onClick={() => { void copyReviewTemplate() }} disabled={!data?.legal_readiness?.ready}><ClipboardCopy /> Скопировать ответ менеджеру</button>
        </div>
        <p className="admin-review-note">Создайте через обычную регистрацию отдельный email-аккаунт, проверьте вход в приватном окне и только затем отправьте менеджеру временный пароль. После проверки пароль нужно заменить.</p>
        {reviewMessage && <small className="admin-mail-message ok">{reviewMessage}</small>}
      </article>
      <article className="admin-mail-card admin-legal-settings">
        <div className="admin-section-head"><div><h4>Публичные реквизиты и документы</h4><p>Эти сведения отображаются на витрине, в оферте, правилах оплаты и возврата.</p></div><span className={data?.legal_readiness?.ready ? 'status ok' : 'status warn'}>{data?.legal_readiness?.ready ? 'готово к публикации' : `не заполнено: ${(data?.legal_readiness?.missing || []).join(', ')}`}</span></div>
        <div className="admin-legal-grid">
          {legalFields.map(([key, label]) => <label key={key} className={key === 'service_description' || key === 'legal_address' ? 'wide' : ''}>{label}{key === 'service_description' ? <textarea value={String(legal[key] || '')} onChange={(event) => setLegal((current) => ({ ...current, [key]: event.target.value }))} /> : <input value={String(legal[key] || '')} onChange={(event) => setLegal((current) => ({ ...current, [key]: event.target.value }))} />}</label>)}
        </div>
        <div className="admin-legal-actions"><button className="secondary" onClick={() => { void saveLegal() }}>Сохранить реквизиты</button><a href="/tariffs" target="_blank" rel="noreferrer">Открыть публичную витрину</a></div>
      </article>
      <div className="admin-mail-grid">
        <article className="admin-mail-card">
          <h4>Подключение ЮKassa</h4>
          <label>shopId<input value={shopId} onChange={(event) => setShopId(event.target.value)} placeholder="Идентификатор магазина" /></label>
          <label>Секретный ключ<input type="password" value={secretKey} onChange={(event) => setSecretKey(event.target.value)} placeholder={config.secret_key ? 'Ключ сохранен, можно заменить' : 'Секретный ключ API'} /></label>
          <label>НДС в чеке
            <select value={receiptVatCode} onChange={(event) => setReceiptVatCode(event.target.value)}>
              <option value="1">Без НДС (код 1)</option>
              <option value="2">НДС 0% (код 2)</option>
              <option value="3">НДС 10% (код 3)</option>
              <option value="4">НДС 20% (код 4)</option>
              <option value="5">НДС 10/110 (код 5)</option>
              <option value="6">НДС 20/120 (код 6)</option>
              <option value="7">НДС 5% (код 7)</option>
              <option value="8">НДС 7% (код 8)</option>
              <option value="9">НДС 5/105 (код 9)</option>
              <option value="10">НДС 7/107 (код 10)</option>
              <option value="11">НДС 22% (код 11)</option>
              <option value="12">НДС 22/122 (код 12)</option>
            </select>
            <small>Для самозанятого обычно используется «Без НДС». Значение должно совпадать с настройками магазина ЮKassa.</small>
          </label>
          <label>Предмет расчета
            <select value={paymentSubject} onChange={(event) => setPaymentSubject(event.target.value)}>
              <option value="service">Услуга</option>
              <option value="payment">Платеж</option>
              <option value="another">Иной предмет расчета</option>
            </select>
          </label>
          <label className="admin-check"><input type="checkbox" checked={testMode} onChange={(event) => setTestMode(event.target.checked)} /> Тестовый магазин</label>
          <button className="secondary" disabled={!shopReady || !secretReady || !receiptReady} onClick={save}>Сохранить настройки</button>
          {message && <small>{message}</small>}
        </article>
        <article className="admin-mail-card admin-payment-readiness">
          <h4>Готовность приема оплаты</h4>
          <p className={shopReady ? 'ok' : 'error'}>{shopReady ? <CheckCircle2 /> : <CircleAlert />}<span><b>Магазин</b><small>{shopReady ? 'shopId заполнен' : 'нужен shopId'}</small></span></p>
          <p className={secretReady ? 'ok' : 'error'}>{secretReady ? <CheckCircle2 /> : <CircleAlert />}<span><b>Секрет API</b><small>{secretReady ? 'ключ сохранен или введен' : 'нужен секретный ключ'}</small></span></p>
          <p className={receiptReady ? 'ok' : 'error'}>{receiptReady ? <CheckCircle2 /> : <CircleAlert />}<span><b>Электронный чек</b><small>{receiptReady ? 'НДС и предмет расчета выбраны' : 'выберите параметры чека'}</small></span></p>
          <p className={webhookReady ? 'ok' : 'error'}>{webhookReady ? <CheckCircle2 /> : <CircleAlert />}<span><b>Webhook</b><small>{webhookReady ? 'адрес сформирован; его нужно добавить в ЮKassa' : 'адрес не сформирован'}</small></span></p>
          <small>Статус «настроено» появится только после сохранения shopId, секрета и параметров чека. После этого всё равно обязательна тестовая оплата.</small>
        </article>
        <article className="admin-mail-card">
          <h4>Реальные операции</h4>
          <p>Успешных оплат: <b>{String(summary.paid || 0)}</b></p>
          <p>Ожидают подтверждения: <b>{String(summary.pending || 0)}</b></p>
          <p>Получено по успешным платежам: <b>{Number(summary.revenue_rub || 0).toLocaleString('ru-RU')} ₽</b></p>
          <p>Создано попыток оплаты: <b>{String(summary.total || 0)}</b></p>
        </article>
        <article className="admin-mail-card">
          <h4>Webhook</h4>
          <p>Укажите этот адрес в кабинете ЮKassa для события <b>payment.succeeded</b>.</p>
          <input readOnly value={String(data?.webhook_url || '')} onFocus={(event) => event.currentTarget.select()} />
        </article>
      </div>
      <div className="admin-mail-tables">
        <article><h4>Разовые пакеты токенов</h4><p className="admin-table-note">Эти пакеты пользователь покупает отдельно сверх тарифа.</p><table><thead><tr><th>Название</th><th>Токенов</th><th>Цена, ₽</th><th>Продаётся</th><th></th></tr></thead><tbody>{(data?.packages || []).map((item) => <tr key={String(item.code)}><td><input value={String(item.name)} onChange={(event) => updatePackage(String(item.code), { name: event.target.value })} /><small>{String(item.code)}</small></td><td><input type="number" min="1" value={Number(item.token_amount || 0)} onChange={(event) => updatePackage(String(item.code), { token_amount: Number(event.target.value) })} /></td><td><input type="number" min="1" value={Number(item.price_amount || 0)} onChange={(event) => updatePackage(String(item.code), { price_amount: Number(event.target.value) })} /></td><td><input type="checkbox" checked={Boolean(item.is_active)} onChange={(event) => updatePackage(String(item.code), { is_active: event.target.checked })} aria-label={`Продавать ${String(item.name)}`} /></td><td><button className="secondary" onClick={() => { void savePackage(item) }}>Сохранить</button></td></tr>)}</tbody></table></article>
        <article><h4>Последние платежи</h4><table><tbody>{(data?.payments || []).map((item) => <tr key={String(item.id)}><td><b>{String(item.status)}</b><small>{String(item.created_at || '')}</small></td><td>{Number(item.amount || 0).toLocaleString('ru-RU')} ₽</td><td>{String(item.provider)}</td></tr>)}</tbody></table></article>
      </div>
      <div className="admin-mail-tables"><article><h4>События ЮKassa</h4><table><tbody>{(data?.events || []).map((item, index) => <tr key={`${String(item.provider_payment_id)}-${index}`}><td><b>{String(item.event_type)}</b><small>{String(item.received_at || '')}</small></td><td>{String(item.status)}</td><td>{String(item.error || '')}</td></tr>)}</tbody></table></article></div>
    </div>
  )
}
