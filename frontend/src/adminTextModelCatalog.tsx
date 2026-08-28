import './adminTextModelCatalog.css'

export type TextTariff = 'mini' | 'plus' | 'pro' | 'business'

type EconomicsQuote = {
  quotedCostUsd?: number | null
  quotedCostRub?: number | null
  reservedTokens?: number | null
  revenueRub?: number | null
  profitRub?: number | null
  marginPercent?: number | null
}

export type TextModelEconomics = {
  priceStatus?: 'priced' | 'free' | 'missing_rate' | string
  priceSource?: string
  priceObservedAt?: string | null
  exchangeRate?: number | null
  fundingReservePercent?: number
  minimumMarginPercent?: number
  tokenRub?: number
  inputPerMillion?: EconomicsQuote | null
  outputPerMillion?: EconomicsQuote | null
  millionRussianChars?: {
    assumedProviderTokens?: number
    charsPerProviderToken?: number
    input?: EconomicsQuote | null
    output?: EconomicsQuote | null
    approximate?: boolean
  }
  sample1000Input500Output?: EconomicsQuote | null
}

export type AdminTextModel = {
  id: string
  name: string
  provider?: string
  created?: number | null
  inputPerMillionUsd: number
  outputPerMillionUsd: number
  contextLength: number
  economics?: TextModelEconomics
}

export type TextModelUsage = {
  answers?: number
  priced?: number
  averageCostUsd?: number | null
  settledTokens?: number
  revenueRub?: number
  profitRub?: number
  marginPercent?: number | null
}

const TARIFFS: Array<{ id: TextTariff; label: string }> = [
  { id: 'mini', label: 'MINI' },
  { id: 'plus', label: 'PLUS' },
  { id: 'pro', label: 'PRO' },
  { id: 'business', label: 'BUSINESS' },
]

const number = (value: unknown, digits = 3) => typeof value === 'number' && Number.isFinite(value)
  ? value.toLocaleString('ru-RU', { maximumFractionDigits: digits })
  : '—'

const rub = (value: unknown) => typeof value === 'number' && Number.isFinite(value)
  ? `${value.toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 4 })} ₽`
  : '—'

const usd = (value: unknown, digits = 6) => typeof value === 'number' && Number.isFinite(value)
  ? `$${value.toFixed(digits)}`
  : '—'

const releaseDate = (created: number | null | undefined) => {
  if (!created || !Number.isFinite(created)) return 'дата не указана'
  return new Date(created * 1000).toLocaleDateString('ru-RU')
}

const observedDate = (value: string | null | undefined) => {
  if (!value) return 'время не указано'
  const parsed = new Date(value)
  return Number.isNaN(parsed.valueOf()) ? value : parsed.toLocaleString('ru-RU')
}

function QuoteLine({ label, providerUsd, quote }: { label: string; providerUsd: number; quote?: EconomicsQuote | null }) {
  return <div className="text-price-line">
    <strong>{label}</strong>
    <span>провайдер {usd(providerUsd, 4)}</span>
    <span>себестоимость {rub(quote?.quotedCostRub)}</span>
    <b>{number(quote?.reservedTokens)} наших ток.</b>
    <span>выручка {rub(quote?.revenueRub)} · прибыль {rub(quote?.profitRub)}</span>
  </div>
}

export function AdminTextModelCatalog({
  models,
  publishedIds,
  tierAccess,
  defaultModel,
  usageByModel,
  busy,
  onPublicationChange,
  onTierChange,
  onDefaultChange,
  onLocalDefault,
  onSave,
}: {
  models: AdminTextModel[]
  publishedIds: string[]
  tierAccess: Partial<Record<TextTariff, string[]>>
  defaultModel: string
  usageByModel?: Record<string, TextModelUsage>
  busy: boolean
  onPublicationChange: (modelId: string, published: boolean) => void
  onTierChange: (modelId: string, tariff: TextTariff, enabled: boolean) => void
  onDefaultChange: (modelId: string) => void
  onLocalDefault: () => void
  onSave: () => void
}) {
  const published = new Set(publishedIds)
  return <div className="text-model-catalog">
    <div className="text-model-legend" role="note">
      <strong>Один главный переключатель</strong>
      <span>Выключен — модель скрыта. Включён — модель видна; тариф определяет возможность запуска.</span>
    </div>
    <div className="text-model-header" aria-hidden="true">
      <span>Дата выпуска</span><span>Показ</span><span>Модель</span><span>Производитель</span>
      <span>Тарифы</span><span>Цена за 1 млн</span><span>Факт</span><span>По умолчанию</span>
    </div>
    <div className="text-model-list">
      {models.map((model) => {
        const isPublished = published.has(model.id)
        const economics = model.economics
        const chars = economics?.millionRussianChars
        const usage = usageByModel?.[model.id]
        const margin = usage?.marginPercent
        return <article className={`text-model-row${isPublished ? '' : ' unpublished'}`} key={model.id}>
          <div className="text-model-cell release" data-label="Дата выпуска">
            <strong>{releaseDate(model.created)}</strong>
          </div>
          <div className="text-model-cell publication" data-label="Показывать пользователям">
            <label className="text-model-publication">
              <input className="text-model-checkbox" type="checkbox" checked={isPublished} disabled={busy}
                onChange={(event) => onPublicationChange(model.id, event.target.checked)} />
              <span>{isPublished ? 'Показывается' : 'Скрыта'}</span>
            </label>
          </div>
          <div className="text-model-cell identity" data-label="Модель">
            <strong>{model.name}</strong><small>{model.id}</small>
            <span className={`text-price-status ${economics?.priceStatus || 'unknown'}`}>
              {economics?.priceStatus === 'priced' ? 'цена рассчитана' : economics?.priceStatus === 'free' ? 'бесплатная' : 'нет проверенной цены'}
            </span>
          </div>
          <div className="text-model-cell provider" data-label="Производитель">
            <strong>{model.provider || model.id.split('/')[0] || 'не указан'}</strong>
            <small>контекст {model.contextLength.toLocaleString('ru-RU')}</small>
          </div>
          <div className="text-model-cell tariffs" data-label="Тарифы">
            {TARIFFS.map((tariff) => <label key={tariff.id}>
              <input className="text-model-checkbox tariff" type="checkbox" disabled={busy || !isPublished}
                checked={isPublished && (tierAccess[tariff.id] || []).includes(model.id)}
                onChange={(event) => onTierChange(model.id, tariff.id, event.target.checked)} />
              <span>{tariff.label}</span>
            </label>)}
          </div>
          <div className="text-model-cell economics" data-label="Цена за 1 млн токенов провайдера">
            <QuoteLine label="Вход" providerUsd={model.inputPerMillionUsd} quote={economics?.inputPerMillion} />
            <QuoteLine label="Выход" providerUsd={model.outputPerMillionUsd} quote={economics?.outputPerMillion} />
            <div className="text-char-estimate">
              <strong>≈ 1 млн русских символов</strong>
              <span>при допущении {chars?.charsPerProviderToken || 4} символа на токен:</span>
              <b>вход {number(chars?.input?.reservedTokens)} · выход {number(chars?.output?.reservedTokens)} наших ток.</b>
            </div>
            <details>
              <summary>Источник и пример</summary>
              <span>Источник: {economics?.priceSource || 'не указан'} · наблюдение: {observedDate(economics?.priceObservedAt)}</span>
              <span>Курс: {number(economics?.exchangeRate, 4)} ₽/$ · резерв {number(economics?.fundingReservePercent, 2)}% · минимум маржи {number(economics?.minimumMarginPercent, 2)}%</span>
              <span>Пример 1000 входных + 500 выходных: {number(economics?.sample1000Input500Output?.reservedTokens)} наших ток.</span>
            </details>
          </div>
          <div className="text-model-cell usage" data-label="Фактическая статистика">
            <strong>{usage?.answers || 0} ответов</strong>
            <span>{usage?.priced || 0} с фактической ценой</span>
            <span>среднее {usd(usage?.averageCostUsd)}</span>
            <b className={typeof margin === 'number' && typeof economics?.minimumMarginPercent === 'number' && margin < economics.minimumMarginPercent ? 'bad' : ''}>
              маржа {typeof margin === 'number' ? `${number(margin, 1)}%` : '—'}
            </b>
          </div>
          <div className="text-model-cell default" data-label="По умолчанию">
            <label>
              <input className="text-model-radio" type="radio" name="chat-default-model" disabled={busy || !isPublished}
                checked={defaultModel === model.id} onChange={() => onDefaultChange(model.id)} />
              <span>{defaultModel === model.id ? 'Выбрана' : 'Выбрать'}</span>
            </label>
          </div>
        </article>
      })}
      {!models.length && <div className="text-model-empty">По выбранному фильтру модели не найдены.</div>}
    </div>
    <div className="text-model-actions">
      <label className="text-model-local-default">
        <input className="text-model-radio" type="radio" name="chat-default-model" checked={defaultModel === 'local:izo-chat'} onChange={onLocalDefault} />
        <span>ИЗО Чат по умолчанию</span>
      </label>
      <button className="primary" disabled={busy} onClick={onSave}>{busy ? 'Сохраняю…' : 'Сохранить текстовые модели'}</button>
    </div>
  </div>
}
