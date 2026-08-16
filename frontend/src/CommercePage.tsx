import { Check, ChevronLeft, CircleAlert, CreditCard, Mail, ShieldCheck } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import IzoTopBar from './studio/IzoTopBar'
import { formatModelCount } from './profileSupport'

const API = (import.meta as ImportMeta & { env?: { VITE_API_BASE_URL?: string } }).env?.VITE_API_BASE_URL || '/api'

type Tariff = {
  title?: string; note?: string; price_rub_month?: number; daily_tokens?: number
  monthly_tokens?: number; gallery_slots?: number; quality_label?: string
  pro_mode_enabled?: boolean; video_enabled?: boolean; video_slots?: number; queue_label?: string
  image_model_count?: number; video_model_count?: number
}
type TermOffer = {
  code: string; months: number; monthly_price_rub: number; discount_percent: number
  base_total_rub: number; price_total_rub: number; savings_rub: number
  included_tokens: number; effective_token_price_rub?: number | null
}
type BillingPackage = {
  code?: string; name?: string; price_amount?: number; token_amount?: number
  kind?: 'tariff' | 'tokens'; plan?: string; term_months?: number
}
type Legal = {
  brand_name?: string; seller_name?: string; seller_status?: string; inn?: string; ogrn?: string
  legal_address?: string; support_email?: string; support_phone?: string; support_hours?: string
  site_url?: string; service_description?: string; offer_version?: string
}
type CommerceData = {
  tariffs?: Record<string, Tariff>; packages?: BillingPackage[]
  termOffers?: Record<string, TermOffer[]>; tariffTerms?: Record<string, number>
  legal?: Legal; legal_readiness?: { ready?: boolean; missing?: string[] }; payments_available?: boolean
}

const planOrder = ['free', 'mini', 'plus', 'pro', 'business']
const legalLinks = [
  ['/legal/offer', 'Публичная оферта'], ['/legal/privacy', 'Политика конфиденциальности'],
  ['/legal/consent', 'Согласие на обработку данных'], ['/legal/terms', 'Пользовательское соглашение'],
  ['/legal/payment', 'Оплата и чеки'], ['/legal/refunds', 'Возвраты'], ['/legal/contacts', 'Реквизиты и контакты'],
  ['/legal/cookies', 'Файлы cookie'],
]
const shortLegalRoutes: Record<string, string> = {
  '/offer': 'offer', '/privacy': 'privacy', '/consent': 'consent', '/terms': 'terms',
  '/payment': 'payment', '/refunds': 'refunds', '/contacts': 'contacts', '/cookies': 'cookies',
}

function PublicHeader({ path }: { path: string }) {
  return <IzoTopBar
    sections={[
      { id: 'tariffs', label: 'Тарифы', href: '/tariffs', active: path === '/tariffs' },
      { id: 'contacts', label: 'Контакты', href: '/legal/contacts', active: path.startsWith('/legal') },
    ]}
    actions={[{ id: 'login', label: 'Войти', href: '/profile/tariffs', cta: true }]}
  />
}

function PublicFooter({ legal }: { legal: Legal }) {
  return <footer className="commerce-footer"><div><strong>{legal.brand_name || 'ИЗО АСА'}</strong><span>{legal.service_description || 'Сервис генерации и редактирования изображений.'}</span></div><nav>{legalLinks.map(([href, label]) => <a href={href} key={href}>{label}</a>)}</nav><small>© 2026 {legal.seller_name || legal.brand_name || 'ИЗО АСА'}. Информация на сайте не ограничивает права потребителя, установленные законодательством РФ.</small></footer>
}

function SellerDetails({ legal }: { legal: Legal }) {
  const rows = [
    ['Исполнитель', legal.seller_name], ['Статус', legal.seller_status], ['ИНН', legal.inn],
    ['ОГРН / ОГРНИП', legal.ogrn], ['Адрес', legal.legal_address], ['Email', legal.support_email],
    ['Телефон', legal.support_phone], ['Поддержка', legal.support_hours], ['Сайт', legal.site_url],
  ].filter(([, value]) => value)
  return <dl className="legal-details">{rows.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{label === 'Email' ? <a href={`mailto:${value}`}>{value}</a> : value}</dd></div>)}</dl>
}

function TariffsPage({ data, loading }: { data: CommerceData; loading: boolean }) {
  const tariffs = data.tariffs || {}
  const legalReady = Boolean(data.legal_readiness?.ready)
  const canPay = Boolean(data.payments_available && legalReady)
  const [termMonths, setTermMonths] = useState(1)
  const tokenPackages = (data.packages || []).filter((item) => item.kind === 'tokens' || String(item.code || '').startsWith('tokens_'))
  return <>
    <section className="commerce-intro"><span className="commerce-kicker">Тарифы ИЗО АСА</span><h1>Генерация изображений и видео с понятным списанием токенов</h1><p>В аккаунте два счёта: дневной лимит тарифа и основной баланс. Серверная модель сначала использует дневной лимит, затем основной баланс; API-модели используют основной баланс.</p></section>
    {!loading && !canPay && <div className="commerce-notice"><CircleAlert aria-hidden="true" /><div><strong>Онлайн-оплата временно недоступна</strong><span>Тарифы можно изучить сейчас. Кнопка покупки включится после завершения регистрации магазина и публикации реквизитов.</span></div></div>}
    <div className="commerce-term-selector" aria-label="Срок тарифа">
      <span>Срок подписки</span>
      <div>{[1, 3, 6, 12].map((months) => <button type="button" key={months} className={termMonths === months ? 'active' : ''} onClick={() => setTermMonths(months)}>{months === 1 ? '1 месяц' : `${months} мес.`}{Number(data.tariffTerms?.[String(months)] || 0) > 0 && <small>−{Number(data.tariffTerms?.[String(months)])}%</small>}</button>)}</div>
    </div>
    <section className="commerce-plans" aria-label="Тарифные планы">{planOrder.map((id) => {
      const tariff = tariffs[id] || {}
      const offer = (data.termOffers?.[id] || []).find((item) => Number(item.months) === termMonths)
      const baseTotal = offer?.base_total_rub ?? Number(tariff.price_rub_month || 0) * termMonths
      const priceTotal = offer?.price_total_rub ?? baseTotal
      const features = [
        `${Number(tariff.daily_tokens || 0)} серверных токенов в день`,
        Number(tariff.monthly_tokens || 0) ? `${Number(tariff.monthly_tokens)} токенов ежемесячно в основной баланс` : 'Серверная модель ИЗО',
        formatModelCount(Number(tariff.image_model_count || 0), 'для изображений'),
        formatModelCount(Number(tariff.video_model_count || 0), 'для видео'),
        `${Number(tariff.gallery_slots || 0)} изображений в галерее`,
        Number(tariff.video_slots || 0) > 0 ? `Хранение до ${Number(tariff.video_slots)} видео в галерее` : 'Хранение видео не входит',
        'Скачивание своих файлов без ограничений',
        `Качество до ${tariff.quality_label || 'SD'}`,
        tariff.pro_mode_enabled ? 'Режим профи и выбор моделей' : '',
      ].filter(Boolean)
      return <article className={`commerce-plan ${id === 'pro' ? 'featured' : ''}`} key={id}>
        {id === 'pro' && <span className="commerce-plan-badge">Популярный</span>}
        <div><h2>{tariff.title || id.toUpperCase()}</h2><p>{tariff.note || ''}</p></div>
        <div className="commerce-plan-price">
          {baseTotal > priceTotal && <del>{baseTotal.toLocaleString('ru-RU')} ₽</del>}
          <strong className="commerce-price">{priceTotal ? <>{priceTotal.toLocaleString('ru-RU')} ₽<small>/ {termMonths === 1 ? '30 дней' : `${termMonths} мес.`}</small></> : 'Бесплатно'}</strong>
          {offer && offer.savings_rub > 0 && <span>Экономия {offer.savings_rub.toLocaleString('ru-RU')} ₽</span>}
          {offer?.effective_token_price_rub != null && <small>Включённый токен: {Number(offer.effective_token_price_rub).toLocaleString('ru-RU', { maximumFractionDigits: 2 })} ₽</small>}
        </div>
        <ul>{features.map((feature) => <li key={feature}><Check aria-hidden="true" />{feature}</li>)}</ul>
        {id === 'free' ? <a href="/profile">Начать бесплатно</a> : <a className={!canPay ? 'disabled' : ''} href={canPay ? `/profile/tariffs?term=${termMonths}` : '/legal/payment'} aria-disabled={!canPay}>{canPay ? 'Выбрать тариф' : 'Скоро доступно'}</a>}
      </article>
    })}</section>
    {!!tokenPackages.length && <section className="commerce-token-section"><div><span className="commerce-kicker">Разовое пополнение</span><h2>Дополнительные токены</h2><p>Покупка пополняет основной баланс, не меняет тариф и не сгорает при его понижении.</p></div><div className="commerce-token-list">{tokenPackages.map((item) => <span key={item.code}><b>{Number(item.token_amount || 0)} ток.</b>{Number(item.price_amount || 0).toLocaleString('ru-RU')} ₽</span>)}</div></section>}
    <section className="commerce-facts"><article><CreditCard /><h3>Оплата</h3><p>Банковской картой и другими способами, доступными на защищённой странице ЮKassa. Итоговая сумма показывается до подтверждения.</p><a href="/legal/payment">Условия оплаты</a></article><article><ShieldCheck /><h3>Документы</h3><p>Покупка означает принятие публичной оферты. Версия документа фиксируется вместе с платежом.</p><a href="/legal/offer">Открыть оферту</a></article><article><Mail /><h3>Поддержка</h3><p>Вопросы по оплате, начислению токенов и возвратам принимаются по указанным контактам.</p><a href="/legal/contacts">Контакты</a></article></section>
  </>
}

function LegalPage({ kind, legal }: { kind: string; legal: Legal }) {
  const seller = legal.seller_name || 'исполнитель, указанный в разделе «Реквизиты и контакты»'
  const email = legal.support_email || 'mail@alikinas.ru'
  const documents: Record<string, { title: string; lead: string; sections: Array<[string, string[]]> }> = {
    offer: { title: 'Публичная оферта', lead: `Предложение ${seller} заключить договор возмездного оказания услуг ИЗО АСА. Версия: ${legal.offer_version || '2026-07-15'}.`, sections: [
      ['1. Термины и предмет договора', ['Исполнитель предоставляет доступ к онлайн-сервису генерации и редактирования изображений, а пользователь оплачивает выбранный тариф или пакет токенов.', 'Токены являются внутренней расчётной единицей объёма услуг, не являются денежными средствами, ценной бумагой или электронным средством платежа и не подлежат передаче между пользователями.']],
      ['2. Заключение договора', ['Оферта содержит существенные условия договора. Полным и безоговорочным акцептом является установка отметки о согласии и оплата выбранной услуги.', 'До оплаты пользователь видит наименование услуги, срок, количество токенов и итоговую цену в рублях.']],
      ['3. Порядок оказания услуг', ['Тариф активируется после подтверждения успешного платежа платёжным оператором. Срок платного тарифа — 30 календарных дней, если на витрине прямо не указано иное.', 'Результат генерации зависит от запроса, выбранной модели и вероятностной природы ИИ. Исполнитель не гарантирует совпадение результата с субъективными ожиданиями пользователя.']],
      ['4. Оплата и токены', ['Оплата проводится через ЮKassa. Сервис не получает и не хранит полные реквизиты банковской карты.', 'Стоимость генерации в токенах показывается пользователю до запуска. Списание производится за успешно принятую в обработку платную генерацию; при технической ошибке применяются правила возврата токенов сервиса.']],
      ['5. Права и обязанности пользователя', ['Пользователь обязан иметь права на загружаемые материалы и не использовать сервис для нарушения закона, прав третьих лиц, создания запрещённого или вводящего в заблуждение контента.', 'Пользователь самостоятельно проверяет допустимость дальнейшего использования созданного результата, включая права на изображения людей, товарные знаки и иные охраняемые объекты.']],
      ['6. Отказ и возврат', ['Порядок отказа от услуги и возврата денежных средств приведён на странице «Возвраты». Условия оферты не ограничивают права потребителя, предусмотренные законодательством РФ.', `Заявление направляется на ${email} с указанием аккаунта, номера платежа, суммы и причины обращения.`]],
      ['7. Ответственность и споры', ['Стороны отвечают в пределах, установленных законодательством РФ. Ограничения ответственности не применяются в случаях, когда это запрещено законом.', 'До обращения в суд пользователь вправе направить претензию. Исполнитель рассматривает требования в сроки, установленные законом.']],
      ['8. Реквизиты исполнителя', ['Актуальные реквизиты являются частью оферты и опубликованы на отдельной странице.']],
    ]},
    privacy: { title: 'Политика обработки персональных данных', lead: `Политика описывает обработку персональных данных пользователей сайта ${legal.site_url || 'https://izo.alikinas.ru'}.`, sections: [
      ['1. Оператор и область действия', [`Оператором является ${seller}. Контакт по вопросам персональных данных: ${email}.`, 'Политика применяется к сайту, личному кабинету, генератору, галерее, платежам и обращениям в поддержку.']],
      ['2. Какие данные обрабатываются', ['Данные аккаунта и входа: имя, email, телефон или идентификаторы подключённых мессенджеров; технические данные: IP-адрес, cookies, сведения об устройстве, сессии и события безопасности; сведения об оплате без полных данных банковской карты; загружаемые изображения, запросы и результаты генерации.', 'Не следует загружать специальные категории персональных данных и сведения, для обработки которых у пользователя нет законного основания.']],
      ['3. Цели и основания', ['Регистрация и исполнение договора, предоставление сервиса, проведение и подтверждение платежей, поддержка, безопасность, предотвращение злоупотреблений, выполнение требований закона.', 'Обработка проводится на основании договора, согласия пользователя и обязанностей, возложенных на оператора законом.']],
      ['4. Передача и обработчики', ['В необходимом объёме данные могут передаваться платёжному оператору, провайдерам авторизации и сообщений, инфраструктурным и модельным провайдерам. Банковские реквизиты вводятся на стороне платёжного оператора.', 'Запросы и изображения могут передаваться выбранному провайдеру модели для выполнения генерации. Пользователь получает информацию о выбранной модели в интерфейсе без раскрытия внутренних коммерческих маршрутов.']],
      ['5. Сроки, защита и удаление', ['Данные хранятся не дольше, чем этого требуют цели обработки, договор и законодательство. Сроки финансовых и бухгалтерских документов определяются обязательными требованиями закона.', `Для доступа, исправления, отзыва согласия или удаления данных направьте обращение на ${email}. Отзыв не затрагивает обработку, необходимую для исполнения закона или уже заключённого договора.`]],
    ]},
    consent: { title: 'Согласие на обработку персональных данных', lead: 'Отдельное согласие пользователя на обработку данных, предоставляемых через сайт.', sections: [
      ['Содержание согласия', [`Пользователь свободно, своей волей и в своём интересе предоставляет ${seller} согласие на сбор, запись, систематизацию, накопление, хранение, уточнение, извлечение, использование, передачу необходимым обработчикам, блокирование, удаление и уничтожение данных.`, 'Перечень данных, цели, категории получателей и права пользователя раскрыты в Политике обработки персональных данных.']],
      ['Срок и отзыв', [`Согласие действует до достижения целей обработки или его отзыва, если продолжение обработки не требуется по закону или договору. Отзыв направляется на ${email}.`]],
    ]},
    terms: { title: 'Пользовательское соглашение', lead: 'Правила использования сайта, генератора, редактора, галереи и пользовательского контента.', sections: [
      ['Аккаунт и безопасность', ['Пользователь отвечает за сохранность доступа к аккаунту и достоверность предоставленных данных. Действия из авторизованной сессии считаются действиями пользователя до сообщения о компрометации.']],
      ['Допустимое использование', ['Запрещены незаконный контент, нарушения прав третьих лиц, обход ограничений, вмешательство в работу сервиса, автоматизированная нагрузка без разрешения и попытки получить чужие данные.']],
      ['Контент и результаты', ['Пользователь сохраняет права на законно загруженные материалы. Он предоставляет сервису ограниченное право технически обрабатывать их для выполнения запроса.', 'Правовой режим результата зависит от закона, вклада пользователя и условий применённой модели. Сервис не передаёт пользователю права, которых у исполнителя нет.']],
      ['Изменение сервиса', ['Функции и модели могут обновляться. Существенные изменения оплаченного объёма услуг применяются с учётом закона и условий, действовавших при оплате.']],
    ]},
    payment: { title: 'Условия оплаты и чеки', lead: 'Порядок формирования заказа, перехода к оплате и подтверждения платежа.', sections: [
      ['Как проходит оплата', ['Пользователь выбирает тариф или пакет токенов в личном кабинете, проверяет цену и состав услуги, принимает оферту и переходит на защищённую страницу ЮKassa.', 'После оплаты пользователь возвращается на страницу статуса. Начисление выполняется после подтверждения события payment.succeeded.']],
      ['Цена и валюта', ['Все цены указаны в российских рублях за полный объём выбранной услуги. Скрытые комиссии со стороны сервиса отсутствуют. Возможные комиссии банка пользователя показываются его банком.']],
      ['Чек самозанятого', ['Исполнитель применяет налог на профессиональный доход. После подтверждения оплаты исполнитель регистрирует доход в приложении «Мой налог», формирует чек и передаёт его покупателю по email, указанному при оформлении покупки.', 'Квитанция ЮKassa и страница результата платежа не заменяют чек из приложения «Мой налог». Если чек не получен, покупатель может обратиться в поддержку.']],
      ['Безопасность', ['Полные данные банковской карты обрабатываются ЮKassa и не поступают в ИЗО АСА. Не передавайте коды подтверждения сотрудникам поддержки.']],
    ]},
    refunds: { title: 'Правила отказа и возврата', lead: 'Порядок обращений по неоказанным, ошибочно оплаченным или ненадлежащим услугам.', sections: [
      ['Право на обращение', ['Потребитель вправе отказаться от договора оказания услуг с учётом фактически оказанных услуг и документально подтверждённых расходов исполнителя. Положения этой страницы не уменьшают права, предоставленные законом.', 'При техническом сбое неоказанная часть услуги восстанавливается токенами либо возвращается денежными средствами в зависимости от обстоятельств и требования пользователя.']],
      ['Как подать заявление', [`Направьте письмо на ${email}: email или идентификатор аккаунта, номер и дату платежа, сумму, причину и требование. Не отправляйте полные данные банковской карты.`, 'Исполнитель может запросить сведения, необходимые для идентификации платежа и предотвращения мошенничества.']],
      ['Срок и способ возврата', ['Обращение рассматривается в срок, установленный законодательством РФ. При одобрении деньги возвращаются через ЮKassa на то же средство платежа; банковский срок зачисления зависит от платёжной системы и банка.', 'Если услуга оказана частично, расчёт возврата учитывает фактически предоставленный объём. Спорные случаи рассматриваются индивидуально с сохранением прав потребителя.']],
    ]},
    contacts: { title: 'Реквизиты и контакты', lead: 'Официальные сведения об исполнителе и каналы связи.', sections: [
      ['Поддержка', [`Email: ${email}`, `Время работы: ${legal.support_hours || 'ежедневно, 10:00–20:00 по московскому времени'}`, 'Для платежных обращений укажите номер платежа или счёта.']],
      ['Назначение сервиса', [legal.service_description || 'Онлайн-сервис генерации и редактирования изображений с использованием моделей искусственного интеллекта.']],
    ]},
    cookies: { title: 'Правила использования файлов cookie', lead: 'Какие локальные данные использует сайт и как пользователь может ими управлять.', sections: [
      ['Обязательные cookie', ['Сайт использует технические cookie и локальное хранилище для авторизации, безопасности сессии, сохранения выбранных настроек и работы платежного возврата. Без них отдельные функции личного кабинета могут быть недоступны.']],
      ['Аналитика', ['Необязательные аналитические инструменты могут применяться только в пределах опубликованной политики конфиденциальности и настроек согласия. Они не должны использоваться для принятия решений, порождающих юридические последствия для пользователя.']],
      ['Управление', ['Пользователь может удалить или заблокировать cookie в настройках браузера. После удаления потребуется повторная авторизация, а сохранённые настройки интерфейса могут сброситься.']],
    ]},
  }
  const document = documents[kind] || documents.offer
  return <article className="legal-document"><a className="legal-back" href="/tariffs"><ChevronLeft />К тарифам</a><header><span className="commerce-kicker">Документы ИЗО АСА</span><h1>{document.title}</h1><p>{document.lead}</p></header>{kind === 'contacts' && <SellerDetails legal={legal} />}{document.sections.map(([title, paragraphs]) => <section key={title}><h2>{title}</h2>{paragraphs.map((paragraph) => <p key={paragraph}>{paragraph}</p>)}</section>)}</article>
}

export default function CommercePage() {
  const [data, setData] = useState<CommerceData>({})
  const [loading, setLoading] = useState(true)
  useEffect(() => { fetch(`${API}/public/commerce-v2`).then((response) => response.ok ? response.json() : Promise.reject()).then(setData).catch(() => setData({})).finally(() => setLoading(false)) }, [])
  const path = window.location.pathname.replace(/\/+$/, '') || '/'
  const kind = useMemo(() => {
    if (path === '/legal') return 'offer'
    if (path.startsWith('/legal/')) return path.split('/')[2] || 'offer'
    return shortLegalRoutes[path] || ''
  }, [path])
  const legal = data.legal || {}
  return <div className="commerce-page"><PublicHeader path={path} /><main>{path === '/tariffs' ? <TariffsPage data={data} loading={loading} /> : <LegalPage kind={kind} legal={legal} />}</main><PublicFooter legal={legal} /></div>
}
