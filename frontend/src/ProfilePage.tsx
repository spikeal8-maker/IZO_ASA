import { useEffect, useState, type ChangeEvent, type Dispatch, type SetStateAction } from 'react'
import { Copy, Link as LinkIcon, Lock, Plus, SlidersHorizontal, Sparkles, Trash2, Upload, WandSparkles } from 'lucide-react'
import type { AuthStatusV2, MeV2 } from './authV2'
import { DEFAULT_TARIFFS, SERVER_MODEL_OPTION, avatarPresets, modelAccessOption, modelModeOrder, modelOptions, modelPublicInfo, qualityPresetLabels, qualityPresets, tariffKeys, type ModelModeKey, type ModelOption, type QualityPreset, type TariffConfig, type TariffKey, type TariffModelDefaults, type UserModelAccess } from './profileSupport'

type ProfileTab = 'profile' | 'tariffs' | 'earn' | 'models'
type UserModelChoices = Partial<Record<ModelModeKey, Partial<TariffModelDefaults>>>
type UserModelVisibility = Partial<Record<ModelModeKey, Record<string, boolean>>>
export type PublicProfileLink = { label: string; url: string }
type TokenHistoryItem = {
  id: string
  delta: number
  spentTokens: number
  reason: string
  source: string
  mode?: string | null
  provider?: string | null
  model?: string | null
  createdAt: string
}
type TokenHistory = {
  summary?: { spentTokens?: number; balanceSpentTokens?: number; includedSpentTokens?: number; refundedTokens?: number; balance?: number }
  items?: TokenHistoryItem[]
}
type PublicModelFormatPricing = {
  id: string
  label: string
  short: string
  tokens?: number | null
  supported?: boolean
}
type PublicModelPricing = { id: string; label: string; formats: PublicModelFormatPricing[] }
type BillingPackage = { code: string; name: string; description?: string; price_amount: number; base_price_amount?: number; discount_percent?: number; discount_amount?: number; token_amount: number; currency: string }
type ProfileVideoMode = 'text_to_video' | 'image_to_video' | 'first_last_frame' | 'reference_to_video'
type ProfileVideoModel = { id: string; name: string; description?: string; publicPricing?: { fromTokens?: number | null }; supportedDurations?: number[]; supportedResolutions?: string[]; supportedAspectRatios?: string[]; generateAudio?: boolean | null }
type ProfileVideoConfig = { modes: Record<ProfileVideoMode, ProfileVideoModel[]>; plan?: string }
const videoModeLabels: Record<ProfileVideoMode, string> = { text_to_video: 'Текст → видео', image_to_video: 'Изображение → видео', first_last_frame: 'Начало и конец', reference_to_video: 'По референсам' }
const videoQualityLabels = { fast: 'Быстро', standard: 'Стандарт', max: 'Максимум' } as const

const API = (import.meta as ImportMeta & { env?: { VITE_API_BASE_URL?: string } }).env?.VITE_API_BASE_URL || '/api'

type ProfilePageProps = {
  authStatus: AuthStatusV2
  me: MeV2 | null
  galleryCount: number
  profileTab: ProfileTab
  setProfileTab: Dispatch<SetStateAction<ProfileTab>>
  tariffs: TariffConfig
  tariffsState: 'loading' | 'ready' | 'fallback'
  tokenRub: number
  openrouterPricing: Record<string, PublicModelPricing>
  authCapsState: 'loading' | 'ready' | 'fallback'
  authCaps: { telegram_bot_login_available: boolean; max_bot_login_available: boolean }
  quality: string
  setQuality: Dispatch<SetStateAction<string>>
  modelAccess: UserModelAccess
  userModelChoices: UserModelChoices
  setUserModelChoices: Dispatch<SetStateAction<UserModelChoices>>
  userModelVisibility: UserModelVisibility
  setUserModelVisibility: Dispatch<SetStateAction<UserModelVisibility>>
  displayName: string
  setDisplayName: Dispatch<SetStateAction<string>>
  profileGender: 'female' | 'male'
  setProfileGender: Dispatch<SetStateAction<'female' | 'male'>>
  profileAge: string
  setProfileAge: Dispatch<SetStateAction<string>>
  publicAbout: string
  setPublicAbout: Dispatch<SetStateAction<string>>
  publicWebsite: string
  setPublicWebsite: Dispatch<SetStateAction<string>>
  publicFocus: string
  setPublicFocus: Dispatch<SetStateAction<string>>
  publicPhone: string
  setPublicPhone: Dispatch<SetStateAction<string>>
  publicLinks: PublicProfileLink[]
  setPublicLinks: Dispatch<SetStateAction<PublicProfileLink[]>>
  saveMsg: string
  setSaveMsg: Dispatch<SetStateAction<string>>
  avatarSrc: string | null
  avatarPreset: string
  avatarBusy: boolean
  avatarMsg: string
  uploadAvatar: (event: ChangeEvent<HTMLInputElement>) => void
  selectAvatarPreset: (presetId: string) => Promise<void>
  promoCode: string
  setPromoCode: Dispatch<SetStateAction<string>>
  promoBusy: boolean
  promoResult: string
  setPromoResult: Dispatch<SetStateAction<string>>
  inviteMsg: string
  setInviteMsg: Dispatch<SetStateAction<string>>
  linkBusy: boolean
  linkMsg: string
  onOpenAuth: () => void
  onBackToGeneration: () => void
  onSaveProfile: () => void
  onLogout: () => void
  onApplyPromo: () => void
  onLinkBot: (providerName: 'telegram' | 'max') => void
}

export default function ProfilePage({
  authStatus,
  me,
  galleryCount,
  profileTab,
  setProfileTab,
  tariffs,
  tokenRub,
  openrouterPricing,
  authCaps,
  quality,
  setQuality,
  modelAccess,
  userModelChoices,
  setUserModelChoices,
  userModelVisibility,
  setUserModelVisibility,
  displayName,
  setDisplayName,
  profileGender,
  setProfileGender,
  profileAge,
  setProfileAge,
  publicAbout,
  setPublicAbout,
  publicWebsite,
  setPublicWebsite,
  publicFocus,
  setPublicFocus,
  publicPhone,
  setPublicPhone,
  publicLinks,
  setPublicLinks,
  saveMsg,
  setSaveMsg,
  avatarSrc,
  avatarPreset,
  avatarBusy,
  avatarMsg,
  uploadAvatar,
  selectAvatarPreset,
  promoCode,
  setPromoCode,
  promoBusy,
  promoResult,
  setPromoResult,
  inviteMsg,
  setInviteMsg,
  linkBusy,
  linkMsg,
  onOpenAuth,
  onSaveProfile,
  onLogout,
  onApplyPromo,
  onLinkBot,
}: ProfilePageProps) {
  const [avatarChooserOpen, setAvatarChooserOpen] = useState(false)
  const [codeCopied, setCodeCopied] = useState(false)
  const [tokenHistoryDays, setTokenHistoryDays] = useState(30)
  const [tokenHistory, setTokenHistory] = useState<TokenHistory | null>(null)
  const [billingPackages, setBillingPackages] = useState<BillingPackage[]>([])
  const [personalDiscountPercent, setPersonalDiscountPercent] = useState(0)
  const [selectedPackage, setSelectedPackage] = useState('')
  const [checkoutBusy, setCheckoutBusy] = useState(false)
  const [checkoutMessage, setCheckoutMessage] = useState('')
  const [checkoutAccepted, setCheckoutAccepted] = useState(false)
  const [videoConfig, setVideoConfig] = useState<ProfileVideoConfig | null>(null)
  const [videoConfigError, setVideoConfigError] = useState('')
  const [videoVisibility, setVideoVisibility] = useState<Record<string, Record<string, boolean>>>(() => {
    try { return JSON.parse(localStorage.getItem('izo:video-model-visibility') || '{}') as Record<string, Record<string, boolean>> } catch { return {} }
  })
  const [videoQualityModels, setVideoQualityModels] = useState<Record<string, Record<string, string>>>(() => {
    try { return JSON.parse(localStorage.getItem('izo:video-quality-models') || '{}') as Record<string, Record<string, string>> } catch { return {} }
  })
  const [receiptContact, setReceiptContact] = useState(() => me?.identities?.find((identity) => identity.provider_email)?.provider_email || '')
  const account = me?.account
  const activePlan = (tariffKeys.includes(String(account?.plan || 'mini').toLowerCase() as TariffKey) ? String(account?.plan || 'mini').toLowerCase() : 'mini') as TariffKey
  const currentTariff = tariffs[activePlan] || DEFAULT_TARIFFS[activePlan]
  const planLabel = activePlan.toUpperCase()
  const tokenBalance = Number(account?.token_balance ?? 0)
  const dailyLimit = Number(account?.daily_tokens_limit ?? account?.daily_tokens ?? currentTariff.daily_tokens)
  const premiumMonthlyTokens = Number(account?.openrouter_monthly_tokens ?? currentTariff.openrouter_monthly_tokens)
  const safeTokenRub = Number.isFinite(tokenRub) && tokenRub > 0 ? tokenRub : 5
  const dailyUsed = Math.max(0, Number(account?.daily_tokens_used ?? 0))
  const dailyAvailable = Math.max(0, Number(account?.daily_tokens_remaining ?? dailyLimit - dailyUsed))
  const premiumMonthlyUsed = Math.max(0, Number(account?.openrouter_monthly_tokens_used ?? 0))
  const premiumMonthlyRemaining = Math.max(0, Number(account?.openrouter_monthly_tokens_remaining ?? premiumMonthlyTokens - premiumMonthlyUsed))
  const gallerySlots = Number(account?.gallery_slots ?? currentTariff.gallery_slots)
  const galleryUsed = Number(account?.gallery_used ?? galleryCount)
  const galleryFree = Math.max(0, Number(account?.gallery_free ?? gallerySlots - galleryUsed))
  const feedLikes = Number((account as { feed_likes?: number | null; likes_received?: number | null } | undefined)?.feed_likes ?? (account as { likes_received?: number | null } | undefined)?.likes_received ?? 0)
  const displayEmail = me?.identities?.find((i) => i.provider_email)?.provider_email
  const telegramIdentity = me?.identities?.find((i) => i.provider === 'telegram')
  const maxIdentity = me?.identities?.find((i) => i.provider === 'max')
  const displayNameFallback = me?.profile?.display_name
    || [me?.profile?.first_name, me?.profile?.last_name].filter(Boolean).join(' ')
    || displayEmail?.split('@')[0]
    || 'Пользователь'
  const userInitials = displayNameFallback.split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]?.toUpperCase()).join('') || 'AI'
  const publicCode = String(me?.profile?.public_user_code || me?.internal_user_id || '').replace(/^web_/, '').toUpperCase()
  const friendPromoCode = `FRIEND-${String(me?.profile?.public_user_code || me?.internal_user_id || 'GUEST').replace(/^web_/, '').toUpperCase().slice(0, 12)}`
  const referralLink = `${window.location.origin}?ref=${me?.profile?.public_user_code || me?.internal_user_id || 'guest'}`
  const selectedQuality = (['fast', 'standard', 'max'].includes(quality) ? quality : 'fast') as QualityPreset
  const selectedModel = modelAccessOption(modelAccess, 'text_to_image', selectedQuality, userModelChoices)
  const tokenPrice = selectedModel.tokenHint
  const accessRows = modelModeOrder.map((mode) => modelAccess.modes[mode]).filter(Boolean)
  const availableModelIds = (mode: ModelModeKey) => new Set((modelAccess.modes[mode]?.models || []).map((item) => item.id))
  const catalogModelsForMode = (mode: ModelModeKey): ModelOption[] => {
    const accessModels = modelAccess.modes[mode]?.models || []
    const map = new Map([...accessModels, ...modelOptions].map((item) => [item.id, item]))
    const available = availableModelIds(mode)
    return Array.from(map.values()).sort((a, b) => {
      const accessDiff = Number(available.has(b.id)) - Number(available.has(a.id))
      return accessDiff || a.label.localeCompare(b.label, 'ru')
    })
  }
  const isModelAvailable = (mode: ModelModeKey, modelId: string) => availableModelIds(mode).has(modelId)
  const isModelVisible = (mode: ModelModeKey, modelId: string) => userModelVisibility[mode]?.[modelId] !== false
  const visibleModelsForSelect = (mode: ModelModeKey, preset: QualityPreset) => {
    const access = modelAccess.modes[mode]
    if (!access) return []
    const selected = modelAccessOption(modelAccess, mode, preset, userModelChoices)
    const visible = access.models.filter((item) => isModelVisible(mode, item.id))
    return visible.some((item) => item.id === selected.id) ? visible : [selected, ...visible.filter((item) => item.id !== selected.id)]
  }
  const setModeModelChoice = (mode: ModelModeKey, preset: QualityPreset, modelId: string) => {
    setUserModelChoices((current) => ({ ...current, [mode]: { ...(current[mode] || {}), [preset]: modelId } }))
  }
  const toggleModelVisibility = (mode: ModelModeKey, modelId: string, visible: boolean) => {
    setUserModelVisibility((current) => ({ ...current, [mode]: { ...(current[mode] || {}), [modelId]: visible } }))
  }
  const modelFormatChips = (model: ModelOption) => {
    if (model.provider !== 'openrouter') {
      return [
        { id: 'square', short: '1:1', tokens: model.tokenHint, supported: true },
        { id: 'portrait', short: '9:16', tokens: model.tokenHint, supported: true },
        { id: 'wide', short: '16:9', tokens: model.tokenHint, supported: true },
        { id: 'soft_wide', short: '3:2', tokens: model.tokenHint, supported: true },
      ]
    }
    const formats = openrouterPricing[model.id]?.formats || []
    return formats.length ? formats : [{ id: 'default', short: '1:1', tokens: model.tokenHint, supported: true }]
  }
  useEffect(() => {
    if (authStatus !== 'authed') return
    let cancelled = false
    fetch(`${API}/account/token-history-v2?days=${tokenHistoryDays}&limit=80`, { credentials: 'include' })
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (!cancelled) setTokenHistory(data?.ok ? data : null)
      })
      .catch(() => {
        if (!cancelled) setTokenHistory(null)
      })
    return () => { cancelled = true }
  }, [authStatus, tokenHistoryDays])
  useEffect(() => {
    if (authStatus !== 'authed' || profileTab !== 'tariffs') return
    let cancelled = false
    fetch(`${API}/billing/packages-v2`, { credentials: 'include' })
      .then((response) => response.ok ? response.json() : null)
      .then((result) => {
        if (cancelled) return
        const packages = Array.isArray(result?.packages) ? result.packages as BillingPackage[] : []
        setBillingPackages(packages)
        setPersonalDiscountPercent(Math.max(0, Number(result?.personal_discount_percent || 0)))
        setSelectedPackage((current) => current || packages[0]?.code || '')
      })
      .catch(() => { if (!cancelled) { setBillingPackages([]); setPersonalDiscountPercent(0) } })
    return () => { cancelled = true }
  }, [authStatus, profileTab])
  useEffect(() => {
    if (authStatus !== 'authed' || profileTab !== 'models') return
    let cancelled = false
    fetch(`${API}/video/config`, { credentials: 'include' })
      .then(async (response) => {
        if (!response.ok) throw new Error(String((await response.json().catch(() => ({})))?.detail || 'Каталог видео недоступен'))
        return response.json() as Promise<ProfileVideoConfig>
      })
      .then((data) => { if (!cancelled) { setVideoConfig(data); setVideoConfigError('') } })
      .catch((reason: Error) => { if (!cancelled) setVideoConfigError(reason.message) })
    return () => { cancelled = true }
  }, [authStatus, profileTab])
  useEffect(() => { try { localStorage.setItem('izo:video-model-visibility', JSON.stringify(videoVisibility)) } catch { /* browser storage can be blocked */ } }, [videoVisibility])
  useEffect(() => { try { localStorage.setItem('izo:video-quality-models', JSON.stringify(videoQualityModels)) } catch { /* browser storage can be blocked */ } }, [videoQualityModels])
  const visibleVideoModels = (mode: ProfileVideoMode) => (videoConfig?.modes[mode] || []).filter((model) => videoVisibility[mode]?.[model.id] !== false)
  const videoQualityModel = (mode: ProfileVideoMode, qualityId: keyof typeof videoQualityLabels) => {
    const models = [...visibleVideoModels(mode)].sort((a, b) => Number(a.publicPricing?.fromTokens ?? 999999) - Number(b.publicPricing?.fromTokens ?? 999999))
    const stored = videoQualityModels[mode]?.[qualityId]
    return models.find((model) => model.id === stored) || (qualityId === 'fast' ? models[0] : qualityId === 'max' ? models[models.length - 1] : models[Math.floor((models.length - 1) / 2)])
  }
  const toggleVideoModel = (mode: ProfileVideoMode, modelId: string, visible: boolean) => setVideoVisibility((current) => ({ ...current, [mode]: { ...(current[mode] || {}), [modelId]: visible } }))
  const setVideoQualityModel = (mode: ProfileVideoMode, qualityId: string, modelId: string) => setVideoQualityModels((current) => ({ ...current, [mode]: { ...(current[mode] || {}), [qualityId]: modelId } }))
  const startCheckout = async (packageCode = selectedPackage) => {
    if (!packageCode || checkoutBusy) return
    if (!receiptContact.trim()) {
      setCheckoutMessage('Укажите email или телефон для электронного чека.')
      return
    }
    if (!checkoutAccepted) {
      setCheckoutMessage('Подтвердите согласие с офертой и условиями оплаты.')
      return
    }
    setCheckoutBusy(true)
    setCheckoutMessage('')
    try {
      const response = await fetch(`${API}/billing/checkout-v2`, {
        method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          package_code: packageCode,
          idempotency_key: `checkout-${crypto.randomUUID()}`,
          offer_accepted: checkoutAccepted,
          receipt_contact: receiptContact.trim(),
        }),
      })
      const result = await response.json().catch(() => ({}))
      if (!response.ok || !result?.confirmation_url) throw new Error(String(result?.detail || 'Не удалось создать оплату'))
      window.location.assign(String(result.confirmation_url))
    } catch (error) {
      setCheckoutMessage(error instanceof Error ? error.message : 'Не удалось создать оплату')
      setCheckoutBusy(false)
    }
  }
  const copyPublicCode = async () => {
    const value = publicCode || 'GUEST'
    try {
      await navigator.clipboard?.writeText(value)
      setCodeCopied(true)
      window.setTimeout(() => setCodeCopied(false), 1400)
    } catch {
      setCodeCopied(false)
    }
  }
  const updatePublicLink = (index: number, patch: Partial<PublicProfileLink>) => {
    setPublicLinks((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, ...patch } : item))
    setSaveMsg('')
  }
  const addPublicLink = () => {
    setPublicLinks((current) => current.length >= 6 ? current : [...current, { label: '', url: '' }])
    setSaveMsg('')
  }
  const removePublicLink = (index: number) => {
    setPublicLinks((current) => current.filter((_, itemIndex) => itemIndex !== index))
    setSaveMsg('')
  }
  const planCards = tariffKeys.map((id) => {
    const tariff = tariffs[id] || DEFAULT_TARIFFS[id]
    const features = [
      `${tariff.daily_tokens} серверных токенов в день`,
      tariff.openrouter_monthly_tokens > 0 ? `${tariff.openrouter_monthly_tokens} токенов премиум-моделей в месяц` : '',
      `${tariff.gallery_slots} работ в галерее`,
      `Качество: ${tariff.quality_label}`,
      tariff.pro_mode_enabled ? 'Режим профи' : '',
      tariff.queue_label && tariff.queue_label.toLowerCase() !== 'обычная' ? `Очередь: ${tariff.queue_label}` : '',
      tariff.video_enabled ? `${tariff.video_slots} видео-экспортов/мес` : '',
    ].filter(Boolean)
    const basePrice = tariff.price_rub_month
    const discountAmount = Math.round(basePrice * personalDiscountPercent / 100)
    return {
      id,
      title: tariff.title,
      note: tariff.note,
      price: Math.max(0, basePrice - discountAmount),
      basePrice,
      daily: tariff.daily_tokens,
      premium: tariff.openrouter_monthly_tokens,
      premiumValue: tariff.openrouter_monthly_tokens * safeTokenRub,
      benefit: Math.max(0, tariff.openrouter_monthly_tokens * safeTokenRub - Math.max(0, basePrice - discountAmount)),
      slots: tariff.gallery_slots,
      quality: tariff.quality_label,
      features,
    }
  })
  const tokenHistoryItems = tokenHistory?.items || []
  const tokenReasonLabel = (item: TokenHistoryItem) => {
    if (item.reason === 'daily_generation') return 'Серверная генерация'
    if (item.reason === 'openrouter_monthly_generation') return 'Премиум-модель'
    if (item.reason === 'generation') return 'Генерация с баланса'
    if (item.reason.endsWith('_refund')) return 'Возврат токенов'
    if (item.delta > 0) return 'Начисление токенов'
    return item.reason
  }
  const tokenHistoryDate = (value: string) => {
    try {
      return new Intl.DateTimeFormat('ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }).format(new Date(value))
    } catch {
      return value
    }
  }

  return (
    <section className="profile-page">
      {authStatus === 'loading' ? (
        <>
          <header className="profile-title">
            <h2>Настройки аккаунта</h2>
            <p>Проверяем активную сессию и загружаем данные профиля.</p>
          </header>
          <article className="profile-card profile-auth-card">
            <h3>Загружаем профиль</h3>
            <p>Если вы уже входили, страница откроется без повторного входа.</p>
          </article>
        </>
      ) : authStatus !== 'authed' ? (
        <>
          <header className="profile-title">
            <h2>Настройки аккаунта</h2>
            <p>Войдите, чтобы увидеть профиль, тарифы, токены и параметры генерации.</p>
          </header>
          <article className="profile-card profile-auth-card">
            <h3>Аккаунт</h3>
            <p>После входа здесь появятся ваш баланс, тариф, промокоды и реферальная ссылка.</p>
            <button className="profile-primary" type="button" onClick={onOpenAuth}><Lock size={16} />Войти</button>
          </article>
        </>
      ) : (
        <>
          <nav className="profile-tabs" aria-label="Разделы настроек">
            <button type="button" className={profileTab === 'profile' ? 'active' : ''} onClick={() => setProfileTab('profile')}><span className="tabFull">Профиль</span><span className="tabShort">Профиль</span></button>
            <button type="button" className={profileTab === 'tariffs' ? 'active' : ''} onClick={() => setProfileTab('tariffs')}><span className="tabFull">Тарифы</span><span className="tabShort">Тарифы</span></button>
            <button type="button" className={profileTab === 'earn' ? 'active' : ''} onClick={() => setProfileTab('earn')}><span className="tabFull">Заработать токены</span><span className="tabShort">Токены</span></button>
            <button type="button" className={profileTab === 'models' ? 'active' : ''} onClick={() => setProfileTab('models')}><span className="tabFull">Модели</span><span className="tabShort">Модели</span></button>
          </nav>

          {profileTab === 'profile' && <>
            <section className="profile-card profile-hero">
              <div className="profile-avatar-block">
                <div className="profile-avatar" aria-label="Аватар пользователя">
                  {avatarSrc ? <img src={avatarSrc} alt="" /> : <span>{userInitials}</span>}
                </div>
                <button className="profile-avatar-upload" type="button" onClick={() => setAvatarChooserOpen(true)} disabled={avatarBusy}>{avatarBusy ? 'Сохраняем...' : 'Выбрать'}</button>
                {avatarMsg && <small className={avatarMsg.includes('сохран') || avatarMsg.includes('загруж') ? 'profile-save-ok' : 'profile-save-err'}>{avatarMsg}</small>}
              </div>
              <div className="profile-hero-main">
                <div className="profile-hero-top">
                  <div className="profile-identity">
                    <h3>{displayNameFallback}</h3>
                    <div className="profile-identity-meta">
                      <button className="profile-chip current" type="button" onClick={() => setProfileTab('tariffs')} title="Открыть тарифы">{planLabel}</button>
                      <a className="profile-chip green" href="/gallery" title="Открыть галерею"><span className="galleryFull">Галерея {galleryUsed}/{gallerySlots}</span><span className="galleryShort">{galleryUsed}/{gallerySlots}</span></a>
                      <button className={codeCopied ? 'profile-code copied' : 'profile-code'} type="button" onClick={copyPublicCode} title="Скопировать код">
                        <span><span className="codeLabel">Код: </span>{publicCode || 'GUEST'}</span>
                        <Copy size={14} aria-hidden="true" />
                        <em aria-live="polite">{codeCopied ? 'Скопировано' : ''}</em>
                      </button>
                    </div>
                  </div>
                </div>
                <div className="profile-metrics">
                  <div><strong>{dailyAvailable}/{dailyLimit}</strong><span>Токены</span><small>потрачено {dailyUsed}</small></div>
                  <div><strong>{tokenBalance}</strong><span>Баланс</span><small>доступно</small></div>
                  <div><strong>{galleryUsed}/{gallerySlots}</strong><span>Галерея</span><small>свободно {galleryFree}</small></div>
                  <div><strong>{feedLikes}</strong><span>Лайки</span><small>в ленте</small></div>
                  <div><strong>+50</strong><span>Бонусы</span><small>промо</small></div>
                </div>
              </div>
            </section>
            {avatarChooserOpen && (
              <div className="profile-avatar-modal" role="dialog" aria-modal="true" aria-label="Выбор аватара">
                <div className="profile-avatar-dialog">
                  <div className="profile-avatar-dialog-head">
                    <h3>Аватар</h3>
                    <button type="button" onClick={() => setAvatarChooserOpen(false)} aria-label="Закрыть">×</button>
                  </div>
                  <div className="profile-avatar-grid">
                    <label className={avatarBusy ? 'profile-avatar-tile upload disabled' : 'profile-avatar-tile upload'}>
                      <Upload size={18} />
                      <span>Файл</span>
                      <input type="file" accept="image/png,image/jpeg,image/webp" onChange={(event) => { uploadAvatar(event); setAvatarChooserOpen(false) }} disabled={avatarBusy} />
                    </label>
                    {avatarPresets.map((preset) => (
                      <button type="button" className={avatarPreset === preset.id ? 'profile-avatar-tile active' : 'profile-avatar-tile'} onClick={() => { void selectAvatarPreset(preset.id); setAvatarChooserOpen(false) }} disabled={avatarBusy} key={preset.id} title={preset.label}>
                        <img src={preset.url} alt="" />
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            )}
            <section className="profile-card profile-profile">
              <label>Имя<input type="text" value={displayName} onChange={(e) => { setDisplayName(e.target.value); setSaveMsg('') }} placeholder="Ваше имя" maxLength={80} /></label>
              <label>Email<input type="email" value={displayEmail || ''} placeholder="Email не указан" readOnly /></label>
              <div className="profile-auth-inline">
                <div>
                  <strong>Способы входа</strong>
                  <span>Подключения помогают нам точнее видеть активность аккаунта и не терять доступ.</span>
                </div>
                <article>
                  <b>Telegram</b>
                  <p>{telegramIdentity ? `Подключен${telegramIdentity.provider_username ? `: @${telegramIdentity.provider_username}` : ''}` : 'Не подключен'}</p>
                  {!telegramIdentity && authCaps.telegram_bot_login_available && <button className="profile-secondary" type="button" onClick={() => onLinkBot('telegram')} disabled={linkBusy}>Подключить</button>}
                </article>
                <article>
                  <b>MAX</b>
                  <p>{maxIdentity ? `Подключен${maxIdentity.provider_username ? `: ${maxIdentity.provider_username}` : ''}` : 'Не подключен'}</p>
                  {!maxIdentity && authCaps.max_bot_login_available && <button className="profile-secondary" type="button" onClick={() => onLinkBot('max')} disabled={linkBusy}>Подключить</button>}
                </article>
              </div>
              <div className="profile-profile-actions">
                <button className="profile-primary" type="button" onClick={onSaveProfile} disabled={!displayName.trim()}>Сохранить профиль</button>
                <button className="profile-ghost" type="button" onClick={onLogout}><Lock size={14} />Выйти</button>
                {saveMsg && <small className={saveMsg === 'Сохранено' ? 'profile-save-ok' : 'profile-save-err'}>{saveMsg}</small>}
                {linkMsg && <small className={linkMsg.includes('подключ') || linkMsg.includes('отправлен') ? 'profile-save-ok' : 'profile-save-err'}>{linkMsg}</small>}
              </div>
            </section>
            <section className="profile-card profile-public">
              <div className="profile-public-head">
                <div>
                  <h3>Публичные данные</h3>
                  <p>Эта информация нужна только для ленты и публичного профиля автора. Можно оставить пустым, если вы не хотите рассказывать о себе.</p>
                </div>
                <span>для ленты</span>
              </div>
              <div className="profile-public-grid">
                <label className="profile-public-wide profile-about-field">
                  <span>О себе</span>
                  <span className="profile-about-input">
                    <textarea value={publicAbout} onChange={(e) => { setPublicAbout(e.target.value); setSaveMsg('') }} placeholder="Расскажите, чем занимаетесь, что создаёте, чем можете быть полезны аудитории" maxLength={700} rows={4} />
                    <small>{publicAbout.length}/700</small>
                  </span>
                </label>
                <label>Чем занимаетесь<input type="text" value={publicFocus} onChange={(e) => { setPublicFocus(e.target.value); setSaveMsg('') }} placeholder="Дизайнер, фотограф, бренд одежды" maxLength={120} /></label>
                <label>Кто вы
                  <select value={profileGender} onChange={(e) => { setProfileGender(e.target.value === 'male' ? 'male' : 'female'); setSaveMsg('') }}>
                    <option value="female">Женщина</option>
                    <option value="male">Мужчина</option>
                  </select>
                </label>
                <label>Возраст<input type="number" min="13" max="120" value={profileAge} onChange={(e) => { setProfileAge(e.target.value); setSaveMsg('') }} placeholder="Например, 28" /></label>
                <label>Основной сайт<input type="url" value={publicWebsite} onChange={(e) => { setPublicWebsite(e.target.value); setSaveMsg('') }} placeholder="site.ru или https://..." maxLength={240} /></label>
                <label>Телефон для связи<input type="tel" value={publicPhone} onChange={(e) => { setPublicPhone(e.target.value); setSaveMsg('') }} placeholder="+7 900 000-00-00" maxLength={40} /></label>
              </div>
              <div className="profile-public-links">
                <div className="profile-public-links-head">
                  <strong><LinkIcon size={16} />Соцсети и ссылки</strong>
                  <button className="profile-secondary" type="button" onClick={addPublicLink} disabled={publicLinks.length >= 6}><Plus size={15} />Добавить</button>
                </div>
                <div className="profile-public-link-list">
                  {publicLinks.length ? publicLinks.map((item, index) => (
                    <div className="profile-public-link-row" key={index}>
                      <input value={item.label} onChange={(e) => updatePublicLink(index, { label: e.target.value })} placeholder="Название: Telegram, VK, Portfolio" maxLength={40} aria-label="Название публичной ссылки" />
                      <input value={item.url} onChange={(e) => updatePublicLink(index, { url: e.target.value })} placeholder="https://..." maxLength={240} aria-label="URL публичной ссылки" />
                      <button type="button" onClick={() => removePublicLink(index)} aria-label="Удалить ссылку"><Trash2 size={16} /></button>
                    </div>
                  )) : (
                    <div className="profile-public-empty">Добавьте ссылки на соцсети, портфолио или сайт, если хотите показывать их в публичном профиле.</div>
                  )}
                </div>
              </div>
              <div className="profile-profile-actions">
                <button className="profile-primary" type="button" onClick={onSaveProfile} disabled={!displayName.trim()}>Сохранить публичные данные</button>
                {saveMsg && <small className={saveMsg === 'Сохранено' ? 'profile-save-ok' : 'profile-save-err'}>{saveMsg}</small>}
              </div>
            </section>
          </>}

          {profileTab === 'tariffs' && <>
            <section className="profile-section">
              <div className="profile-tariff-summary profile-card">
                <div><span>Текущий тариф</span><strong>{planLabel}</strong></div>
                <div><span>Токены сегодня</span><strong>{dailyAvailable} / {dailyLimit}</strong><small>потрачено {dailyUsed}</small></div>
                <div><span>Премиум-модели</span><strong>{premiumMonthlyTokens}</strong><small>токенов в месяц</small></div>
                <div><span>Галерея</span><strong>{galleryUsed}/{gallerySlots}</strong><small>свободно {galleryFree}</small></div>
                <div><span>Видео</span><strong>Доступно</strong><small>модели зависят от тарифа</small></div>
                <button type="button" className="profile-primary" disabled>Управление тарифом скоро</button>
              </div>
              <div className="profile-checkout-consent profile-card">
                {personalDiscountPercent > 0 && <div className="profile-checkout-discount">Персональная скидка: <strong>{personalDiscountPercent}%</strong>. Она уже учтена в ценах ниже.</div>}
                <label>
                  <span>Email или телефон для электронного чека</span>
                  <input value={receiptContact} onChange={(event) => { setReceiptContact(event.target.value); setCheckoutMessage('') }} placeholder="mail@example.ru или +7 900 000-00-00" autoComplete="email" />
                </label>
                <label className="profile-checkout-checkbox">
                  <input type="checkbox" checked={checkoutAccepted} onChange={(event) => { setCheckoutAccepted(event.target.checked); setCheckoutMessage('') }} />
                  <span>Я принимаю <a href="/legal/offer" target="_blank" rel="noreferrer">публичную оферту</a>, <a href="/legal/payment" target="_blank" rel="noreferrer">условия оплаты</a> и <a href="/legal/privacy" target="_blank" rel="noreferrer">политику конфиденциальности</a>.</span>
                </label>
                <small>Итоговая цена будет показана до перехода в ЮKassa. Данные банковской карты вводятся только на защищённой странице платёжного оператора.</small>
              </div>
              <div className="profile-plans">
                {planCards.map((item) => (
                  <article className={`${item.id === activePlan ? 'profile-card profile-plan active current' : 'profile-card profile-plan'}`} key={item.id}>
                    {item.id === activePlan && <span className="profile-chip current">Текущий</span>}
                    <h4>{item.title}</h4><p>{item.note}</p><strong>{item.price ? `${item.price.toLocaleString('ru-RU')} ₽/мес` : 'Бесплатно'}</strong>{personalDiscountPercent > 0 && item.basePrice > item.price ? <small className="profile-old-price">{item.basePrice.toLocaleString('ru-RU')} ₽ без скидки</small> : null}<span>{item.daily} серверных токенов/день · {item.quality}</span>
                    {item.premium > 0 ? <em>{item.premium} токенов/мес на премиум-модели</em> : null}
                    {item.benefit > 0 ? <small>Выгода по токенам: {item.benefit.toLocaleString('ru-RU')} ₽</small> : null}
                    {item.features.length ? <ul>{item.features.map((feature) => <li key={feature}>{feature}</li>)}</ul> : null}
                    <button type="button" disabled={item.id === activePlan || item.id === 'free' || checkoutBusy || !checkoutAccepted || !receiptContact.trim()} onClick={() => { void startCheckout(`tariff_${item.id}`) }}>{item.id === activePlan ? 'Текущий тариф' : checkoutBusy ? 'Переходим к оплате...' : 'Выбрать тариф'}</button>
                  </article>
                ))}
              </div>
              <article className="profile-card profile-token-buy">
                <div>
                  <h3>Купить токены</h3>
                  <p>Дополнительные токены пригодятся для премиум API-моделей сверх месячного пакета тарифа.</p>
                </div>
                <div className="profile-token-rate">
                  <span>Стоимость</span>
                  <strong>1 токен = {safeTokenRub.toLocaleString('ru-RU')} ₽</strong>
                </div>
                <div className="profile-token-packs" aria-label="Пакеты токенов">
                  {billingPackages.map((item) => <button type="button" className={selectedPackage === item.code ? 'active' : ''} key={item.code} onClick={() => setSelectedPackage(item.code)}>{item.token_amount} ток. · {item.price_amount.toLocaleString('ru-RU')} ₽{item.base_price_amount && item.base_price_amount > item.price_amount ? <del>{item.base_price_amount.toLocaleString('ru-RU')} ₽</del> : null}</button>)}
                </div>
                <button type="button" className="profile-primary" disabled={!selectedPackage || checkoutBusy || !checkoutAccepted || !receiptContact.trim()} onClick={() => { void startCheckout() }}>{checkoutBusy ? 'Переходим к оплате...' : 'Купить токены'}</button>
                {checkoutMessage && <small className="profile-save-err">{checkoutMessage}</small>}
              </article>
            </section>
          </>}

          {profileTab === 'earn' && <>
            <section className="profile-section">
              <div className="profile-earn-hero profile-card"><h3>Получайте токены</h3><div><span>Текущий баланс</span><strong>{tokenBalance}</strong><small>токенов</small></div><div><span>Ожидает начисления</span><strong>+50</strong><small>за друга или промокод</small></div></div>
              <div className="profile-earn">
                <article className="profile-card profile-earn-card"><h4>Промокод</h4><p>Введите промокод и получите награду, если код активен.</p><div className="profile-inline"><input value={promoCode} onChange={(e) => { setPromoCode(e.target.value.toUpperCase()); setPromoResult('') }} placeholder="Например START50" aria-label="Промокод" /><button type="button" disabled={promoBusy || !promoCode.trim()} onClick={onApplyPromo}>{promoBusy ? 'Проверяем...' : 'Применить'}</button></div><div className={promoResult ? 'profile-reward result' : 'profile-reward'}>{promoResult || '+50 токенов за успешный промокод'}</div></article>
                <article className="profile-card profile-earn-card"><h4>Пригласи друга</h4><p>Отправьте другу ссылку. Бонус начислится после регистрации.</p><label>Реферальный код<input readOnly value={friendPromoCode} onFocus={(e) => e.currentTarget.select()} /></label><div className="profile-inline"><input readOnly value={referralLink} onFocus={(e) => e.currentTarget.select()} aria-label="Реферальная ссылка" /><button type="button" onClick={async () => { await navigator.clipboard?.writeText(`${referralLink}\nПромокод: ${friendPromoCode}`); setInviteMsg('Скопировано') }}>Копировать</button></div><div className="profile-reward">{inviteMsg || '+50 токенов за каждого друга'}</div></article>
                <article className="profile-card profile-earn-card"><h4>Баланс</h4><p>Токены списываются при генерации. Стоимость зависит от качества.</p><strong className="profile-token-balance">{tokenBalance} токенов</strong><button type="button" className="profile-primary" disabled>Пополнение скоро</button></article>
              </div>
            </section>
          </>}

          {profileTab === 'models' && <>
            <section className="profile-section">
              <div className="profile-model-summary"><article className="profile-card profile-stat-card"><span>Баланс токенов</span><strong>{tokenBalance}</strong><small>токенов</small></article><article className="profile-card profile-stat-card"><span>Дневной лимит</span><strong>{dailyAvailable} / {dailyLimit}</strong><small>потрачено {dailyUsed}</small></article><article className="profile-card profile-stat-card"><span>Выбрано качество</span><strong>{qualityPresetLabels[selectedQuality]}</strong><small>{selectedModel.label}</small></article><article className="profile-card profile-stat-card"><span>Списание</span><strong>{tokenPrice} ток.</strong><small>за выбранную модель</small></article></div>
              <div className="profile-section-head"><h3>Модели по умолчанию</h3><span>Эти модели подставляются в генератор при выборе качества</span></div>
              <div className="profile-models">
                {qualityPresets.map((preset) => {
                  const option = modelAccessOption(modelAccess, 'text_to_image', preset, userModelChoices)
                  const Icon = preset === 'fast' ? Sparkles : preset === 'standard' ? WandSparkles : SlidersHorizontal
                  return <button type="button" key={preset} className={selectedQuality === preset ? 'profile-card profile-model active' : 'profile-card profile-model'} onClick={() => setQuality(preset)}><Icon size={26} /><b>{qualityPresetLabels[preset]}</b><span>{option.label} · {option.tokenHint} ток.</span><small>будет списано при генерации</small></button>
                })}
              </div>
              <div className="profile-estimate"><span>По умолчанию: <strong>{qualityPresetLabels[selectedQuality]}</strong></span><span><strong>{selectedModel.label}</strong> · {tokenPrice} ток.</span><span>Перед генерацией списание будет показано еще раз</span></div>
              <div className="profile-section-head"><h3>Доступные модели по вкладкам</h3><span>Можно выбрать модель для каждого качества</span></div>
              <div className="profile-mode-models">
                {accessRows.map((access) => {
                  if (!access) return null
                  const visibleAvailableCount = access.models.filter((model) => isModelVisible(access.id, model.id)).length
                  return <article className="profile-card profile-mode-card" key={access.id}>
                    <div className="profile-mode-head">
                      <strong>{access.label}</strong>
                      <span>{visibleAvailableCount} / {access.models.length} доступно</span>
                    </div>
                    <div className="profile-mode-presets">
                      {qualityPresets.map((preset) => {
                        const selected = modelAccessOption(modelAccess, access.id, preset, userModelChoices)
                        return <label key={preset}>
                          <span>{qualityPresetLabels[preset]}</span>
                          <select value={selected.id} onChange={(e) => setModeModelChoice(access.id, preset, e.target.value)}>
                            {visibleModelsForSelect(access.id, preset).map((item) => <option key={item.id} value={item.id}>{item.label} · {item.tokenHint} ток.</option>)}
                          </select>
                        </label>
                      })}
                    </div>
                  </article>
                })}
              </div>
              <article className="profile-card profile-base-note">
                <div>
                  <strong>{SERVER_MODEL_OPTION.label}</strong>
                  <span>базовая модель ИЗО · {SERVER_MODEL_OPTION.tokenHint} ток.</span>
                </div>
                <p>{modelPublicInfo(SERVER_MODEL_OPTION).description}</p>
                <ul>{modelPublicInfo(SERVER_MODEL_OPTION).strengths.map((item) => <li key={item}>{item}</li>)}</ul>
              </article>
              <div className="profile-section-head"><h3>Каталог моделей</h3><span>Откройте вкладку, чтобы посмотреть модели и описание</span></div>
              <div className="profile-model-catalog">
                {accessRows.map((access) => {
                  if (!access) return null
                  const visibleCount = access.models.filter((model) => isModelVisible(access.id, model.id)).length
                  const catalogModels = catalogModelsForMode(access.id)
                  return <details className="profile-model-group" key={`catalog-${access.id}`}>
                    <summary><strong>{access.label}</strong><span>{access.models.length} доступно · {visibleCount} показано</span></summary>
                    <div className="profile-model-info-list">
                      {catalogModels.map((model) => {
                        const info = modelPublicInfo(model)
                        const available = isModelAvailable(access.id, model.id)
                        const visible = isModelVisible(access.id, model.id)
                        return <details className={available && visible ? 'profile-model-info-row' : 'profile-model-info-row muted'} key={`${access.id}-${model.id}`}>
                          <summary>
                            <label className="profile-model-visible" onClick={(event) => event.stopPropagation()}>
                              <input type="checkbox" checked={available && visible} disabled={!available} onChange={(event) => toggleModelVisibility(access.id, model.id, event.currentTarget.checked)} />
                              <span>показывать</span>
                            </label>
                            <strong>{model.label}</strong>
                            <span className="profile-model-token">{model.tokenHint} ток.</span>
                            <span className={available ? 'profile-model-status available' : 'profile-model-status unavailable'}>{available ? 'доступно' : 'недоступно'}</span>
                          </summary>
                          <div className="profile-model-info-body">
                            <p>{info.description}</p>
                            <div className="profile-model-info-meta"><span>Год: <b>{info.year}</b></span><span>Семейство: <b>{info.company}</b></span></div>
                            <div className="profile-model-format-grid" aria-label="Стоимость по форматам">
                              {modelFormatChips(model).map((fmt) => (
                                <span key={`${model.id}-${fmt.id}`} className={fmt.supported === false ? 'disabled' : ''}>
                                  <b>{fmt.short}</b>
                                  <em>{fmt.supported === false ? 'недоступно' : `${fmt.tokens ?? model.tokenHint} ток.`}</em>
                                </span>
                              ))}
                            </div>
                            <ul>{info.strengths.map((item) => <li key={item}>{item}</li>)}</ul>
                          </div>
                        </details>
                      })}
                    </div>
                  </details>
                })}
              </div>
              <div className="profile-section-head"><h3>Видеомодели</h3><span>Выберите модели, которые будут видны в видеогенераторе</span></div>
              {videoConfigError && <p className="profile-save-err">{videoConfigError}</p>}
              {!videoConfig && !videoConfigError && <p className="profile-model-loading">Загружаем каталог видеомоделей...</p>}
              <div className="profile-video-catalog">
                {(Object.keys(videoModeLabels) as ProfileVideoMode[]).map((mode) => {
                  const models = videoConfig?.modes[mode] || []
                  const visibleCount = visibleVideoModels(mode).length
                  return <details className="profile-model-group" key={`video-${mode}`}>
                    <summary><strong>{videoModeLabels[mode]}</strong><span>{visibleCount} / {models.length} показано</span></summary>
                    <div className="profile-video-presets" aria-label={`Модели качества: ${videoModeLabels[mode]}`}>
                      {(Object.keys(videoQualityLabels) as Array<keyof typeof videoQualityLabels>).map((qualityId) => {
                        const selected = videoQualityModel(mode, qualityId)
                        return <label key={`${mode}-${qualityId}`}>
                          <span>{videoQualityLabels[qualityId]}</span>
                          <select value={selected?.id || ''} disabled={!visibleCount} onChange={(event) => setVideoQualityModel(mode, qualityId, event.currentTarget.value)}>
                            {visibleVideoModels(mode).map((model) => <option key={model.id} value={model.id}>{model.name} · от {model.publicPricing?.fromTokens ?? '—'} ток.</option>)}
                          </select>
                        </label>
                      })}
                    </div>
                    <div className="profile-video-model-list">
                      {models.map((model) => {
                        const visible = videoVisibility[mode]?.[model.id] !== false
                        return <div className={visible ? 'profile-video-model-row' : 'profile-video-model-row muted'} key={`${mode}-${model.id}`}>
                          <label className="profile-video-model-toggle" title={visible ? 'Скрыть модель в видеогенераторе' : 'Показывать модель в видеогенераторе'}>
                            <input type="checkbox" checked={visible} onChange={(event) => toggleVideoModel(mode, model.id, event.currentTarget.checked)} />
                            <span className="visually-hidden">{visible ? 'Модель включена' : 'Модель скрыта'}</span>
                          </label>
                          <details className="profile-video-model-details">
                            <summary>
                              <span className="profile-video-model-copy"><strong>{model.name}</strong><small>{(model.supportedResolutions || []).join(', ') || 'разрешение по модели'}</small></span>
                              <span className="profile-video-model-meta"><b>от {model.publicPricing?.fromTokens ?? '—'} ток.</b><small>{(model.supportedDurations || []).map((value) => `${value} с`).join(', ') || 'длительность по модели'} · доступна для {videoConfig?.plan || 'вашего тарифа'}</small></span>
                            </summary>
                            <div className="profile-video-model-description">
                              <p>{model.description || 'Описание модели пока не опубликовано.'}</p>
                              <dl>
                                <div><dt>Форматы</dt><dd>{(model.supportedAspectRatios || []).join(', ') || 'по модели'}</dd></div>
                                <div><dt>Разрешения</dt><dd>{(model.supportedResolutions || []).join(', ') || 'по модели'}</dd></div>
                                <div><dt>Длительность</dt><dd>{(model.supportedDurations || []).map((value) => `${value} сек.`).join(', ') || 'по модели'}</dd></div>
                                <div><dt>Звук</dt><dd>{model.generateAudio === true ? 'поддерживается' : model.generateAudio === false ? 'не поддерживается' : 'зависит от модели'}</dd></div>
                              </dl>
                              <code>{model.id}</code>
                            </div>
                          </details>
                        </div>
                      })}
                      {!models.length && videoConfig && <p className="profile-model-empty">Для этого режима доступных моделей пока нет.</p>}
                    </div>
                  </details>
                })}
              </div>
              <div className="profile-usage-panel profile-card">
                <div className="profile-usage-head">
                  <div><h3>История использования</h3><span>Здесь показываем только токены: сколько списано, возвращено или начислено.</span></div>
                  <div className="profile-usage-filter">{[7, 30, 90].map((days) => <button type="button" key={days} className={tokenHistoryDays === days ? 'active' : ''} onClick={() => setTokenHistoryDays(days)}>{days} дн.</button>)}</div>
                </div>
                <div className="profile-usage-stats">
                  <span>Премиум: <strong>{premiumMonthlyRemaining} / {premiumMonthlyTokens}</strong></span>
                  <span>Потрачено за период: <strong>{tokenHistory?.summary?.spentTokens ?? 0}</strong></span>
                  <span>Из баланса: <strong>{tokenHistory?.summary?.balanceSpentTokens ?? 0}</strong></span>
                  <span>Из пакетов: <strong>{tokenHistory?.summary?.includedSpentTokens ?? 0}</strong></span>
                </div>
                <div className="profile-usage-list">
                  {tokenHistoryItems.length ? tokenHistoryItems.slice(0, 8).map((item) => (
                    <div key={item.id}>
                      <strong>{tokenReasonLabel(item)}</strong>
                      <span>{item.spentTokens ? `${item.spentTokens} ток.` : item.delta > 0 ? `+${item.delta} ток.` : `${item.delta} ток.`}</span>
                      <small>{item.source}{item.model ? ` · ${item.model}` : ''}</small>
                      <time>{tokenHistoryDate(item.createdAt)}</time>
                    </div>
                  )) : <p>За выбранный период списаний пока нет.</p>}
                </div>
              </div>
            </section>
          </>}
        </>
      )}
    </section>
  )
}
