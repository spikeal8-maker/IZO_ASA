import { useState, type ChangeEvent, type Dispatch, type SetStateAction } from 'react'
import { Copy, Link as LinkIcon, Lock, Plus, SlidersHorizontal, Sparkles, Trash2, Upload, WandSparkles } from 'lucide-react'
import type { AuthStatusV2, MeV2 } from './authV2'
import { DEFAULT_TARIFFS, avatarPresets, modelAccessOption, modelModeOrder, qualityPresetLabels, qualityPresets, tariffKeys, type ModelModeKey, type QualityPreset, type TariffConfig, type TariffKey, type TariffModelDefaults, type UserModelAccess } from './profileSupport'

type ProfileTab = 'profile' | 'tariffs' | 'earn' | 'models'
type UserModelChoices = Partial<Record<ModelModeKey, Partial<TariffModelDefaults>>>
export type PublicProfileLink = { label: string; url: string }

type ProfilePageProps = {
  authStatus: AuthStatusV2
  me: MeV2 | null
  galleryCount: number
  profileTab: ProfileTab
  setProfileTab: Dispatch<SetStateAction<ProfileTab>>
  tariffs: TariffConfig
  tariffsState: 'loading' | 'ready' | 'fallback'
  tokenRub: number
  authCapsState: 'loading' | 'ready' | 'fallback'
  authCaps: { telegram_bot_login_available: boolean; max_bot_login_available: boolean }
  quality: string
  setQuality: Dispatch<SetStateAction<string>>
  modelAccess: UserModelAccess
  userModelChoices: UserModelChoices
  setUserModelChoices: Dispatch<SetStateAction<UserModelChoices>>
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
  authCaps,
  quality,
  setQuality,
  modelAccess,
  userModelChoices,
  setUserModelChoices,
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
  const gallerySlots = Number(account?.gallery_slots ?? currentTariff.gallery_slots)
  const galleryUsed = Number(account?.gallery_used ?? galleryCount)
  const galleryFree = Math.max(0, Number(account?.gallery_free ?? gallerySlots - galleryUsed))
  const videoEnabled = Boolean(account?.video_enabled ?? currentTariff.video_enabled)
  const videoSlots = Number(account?.video_slots ?? currentTariff.video_slots)
  const videoUsed = Math.max(0, Number(account?.video_used ?? 0))
  const videoFree = Math.max(0, Number(account?.video_free ?? videoSlots - videoUsed))
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
  const setModeModelChoice = (mode: ModelModeKey, preset: QualityPreset, modelId: string) => {
    setUserModelChoices((current) => ({ ...current, [mode]: { ...(current[mode] || {}), [preset]: modelId } }))
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
    return {
      id,
      title: tariff.title,
      note: tariff.note,
      price: tariff.price_rub_month,
      daily: tariff.daily_tokens,
      premium: tariff.openrouter_monthly_tokens,
      premiumValue: tariff.openrouter_monthly_tokens * safeTokenRub,
      benefit: Math.max(0, tariff.openrouter_monthly_tokens * safeTokenRub - tariff.price_rub_month),
      slots: tariff.gallery_slots,
      quality: tariff.quality_label,
      features,
    }
  })

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
                <div><span>Видео</span><strong>{videoEnabled ? `${videoUsed}/${videoSlots}` : 'Закрыто'}</strong><small>{videoEnabled ? `свободно ${videoFree}` : 'доступно с Pro'}</small></div>
                <button type="button" className="profile-primary" disabled>Управление тарифом скоро</button>
              </div>
              <div className="profile-plans">
                {planCards.map((item) => (
                  <article className={`${item.id === activePlan ? 'profile-card profile-plan active current' : 'profile-card profile-plan'}`} key={item.id}>
                    {item.id === activePlan && <span className="profile-chip current">Текущий</span>}
                    <h4>{item.title}</h4><p>{item.note}</p><strong>{item.price ? `${item.price.toLocaleString('ru-RU')} ₽/мес` : 'Бесплатно'}</strong><span>{item.daily} серверных токенов/день · {item.quality}</span>
                    {item.premium > 0 ? <em>{item.premium} токенов/мес на премиум-модели</em> : null}
                    {item.benefit > 0 ? <small>Выгода по токенам: {item.benefit.toLocaleString('ru-RU')} ₽</small> : null}
                    {item.features.length ? <ul>{item.features.map((feature) => <li key={feature}>{feature}</li>)}</ul> : null}
                    <button type="button" disabled>{item.id === activePlan ? 'Текущий тариф' : 'Смена тарифа скоро'}</button>
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
                <div className="profile-token-packs" aria-label="Примеры пакетов токенов">
                  {[50, 100, 250].map((count) => <span key={count}>{count} ток. · {(count * safeTokenRub).toLocaleString('ru-RU')} ₽</span>)}
                </div>
                <button type="button" className="profile-primary" disabled>Купить токены скоро</button>
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
              <div className="profile-model-summary"><article className="profile-card profile-stat-card"><span>Баланс токенов</span><strong>{tokenBalance}</strong><small>токенов</small></article><article className="profile-card profile-stat-card"><span>Дневной лимит</span><strong>{dailyAvailable} / {dailyLimit}</strong><small>потрачено {dailyUsed}</small></article><article className="profile-card profile-stat-card"><span>Выбрано качество</span><strong>{qualityPresetLabels[selectedQuality]}</strong><small>{selectedModel.label}</small></article><article className="profile-card profile-stat-card"><span>Стоимость</span><strong>{tokenPrice}</strong><small>{tokenPrice === 1 ? 'токен' : 'токена'}</small></article></div>
              <div className="profile-section-head"><h3>Модели и стоимость</h3><span>Стоимость будет показана перед генерацией</span></div>
              <div className="profile-models">
                {qualityPresets.map((preset) => {
                  const option = modelAccessOption(modelAccess, 'text_to_image', preset, userModelChoices)
                  const Icon = preset === 'fast' ? Sparkles : preset === 'standard' ? WandSparkles : SlidersHorizontal
                  return <button type="button" key={preset} className={selectedQuality === preset ? 'profile-card profile-model active' : 'profile-card profile-model'} onClick={() => setQuality(preset)}><Icon size={26} /><b>{qualityPresetLabels[preset]}</b><span>{option.tokenHint} {option.tokenHint === 1 ? 'токен' : 'токена'}</span><small>{option.label}</small></button>
                })}
              </div>
              <div className="profile-estimate"><span>Выбрано: <strong>{qualityPresetLabels[selectedQuality]}</strong></span><span>Модель: <strong>{selectedModel.label}</strong></span><span>Примерная стоимость: <strong>{tokenPrice} {tokenPrice === 1 ? 'токен' : 'токена'}</strong></span></div>
              <div className="profile-section-head"><h3>Доступные модели по вкладкам</h3><span>Можно выбрать модель для каждого качества</span></div>
              <div className="profile-mode-models">
                {modelModeOrder.map((mode) => {
                  const access = modelAccess.modes[mode]
                  if (!access) return null
                  return <article className="profile-card profile-mode-card" key={mode}>
                    <div className="profile-mode-head">
                      <strong>{access.label}</strong>
                      <span>{access.models.length} моделей</span>
                    </div>
                    <div className="profile-mode-presets">
                      {qualityPresets.map((preset) => {
                        const selected = modelAccessOption(modelAccess, mode, preset, userModelChoices)
                        return <label key={preset}>
                          <span>{qualityPresetLabels[preset]}</span>
                          <select value={selected.id} onChange={(e) => setModeModelChoice(mode, preset, e.target.value)}>
                            {access.models.map((item) => <option key={item.id} value={item.id}>{item.label} · {item.tokenHint} ток.</option>)}
                          </select>
                        </label>
                      })}
                    </div>
                    <div className="profile-mode-list">
                      {access.models.map((item) => <span key={item.id}>{item.label}</span>)}
                    </div>
                  </article>
                })}
              </div>
            </section>
          </>}
        </>
      )}
    </section>
  )
}
