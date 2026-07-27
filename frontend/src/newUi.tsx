// ============================================================================
// UI 2.0 — страница /new. Самодостаточный модуль: собственный layout по новым
// макетам, реальный функционал через те же API, что и основной интерфейс
// (/api/generate, /api/jobs, /api/gallery, auth v2). Работает параллельно с
// текущим интерфейсом и не зависит от него (общие только stylePresets/authV2).
//
// Логика стилей (По тексту): клик по стилю дописывает текст стиля в конец
// промпта; выбор другого стиля заменяет предыдущую приписку. В По фото стиль
// задаёт transform-prompt преобразования (как шаблоны текущей версии).
// ============================================================================
import { lazy, Suspense, useCallback, useEffect, useRef, useState } from 'react'
import type { ChangeEvent } from 'react'
import type { CSSProperties, PointerEvent as ReactPointerEvent, ReactElement, TouchEvent as ReactTouchEvent, WheelEvent as ReactWheelEvent } from 'react'
import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp, Brush, ChevronDown, Eraser, Film, Moon, PaintBucket, Palette, SlidersHorizontal, Slash, Sun, Trash2, Undo2, X } from 'lucide-react'
import {
  AuthV2Modal,
  ensureSessionRefreshedV2,
  getAuthCapabilitiesV2,
  initAuthV2,
  logoutV2,
  pollBotLoginStatusV2,
  refreshAuthStateV2,
  startBotLinkV2,
  updateProfileV2,
  updateProfileV2Detailed,
  useAuthV2,
} from './authV2'
import {
  DEFAULT_EDIT_STRENGTH,
  EDIT_DISABLED_REFERENCE_ROLES,
  EDIT_REFERENCE_ROLE_LABELS,
  EDIT_SELECTABLE_REFERENCE_ROLES,
  EDIT_SLOT_COUNT,
  editComposerStatus,
  type EditReferenceRole,
  type EditSlot,
} from './editPrompt'
import { I2I_STYLES, T2I_TEMPLATES, styleShortLabel } from './stylePresets'
import type { StylePreset } from './stylePresets'
import TopBarV3 from './TopBarV3'
import type { V3Mode, V3Section } from './TopBarV3'
import { accountInfo } from './topbarUtils'
import ProfilePage, { type PublicProfileLink } from './ProfilePage'
import { DEFAULT_TARIFFS, avatarPresets, modelAccessOption, modelOptions, modelPublicInfo, type ModelModeKey, type ModelOption, type QualityPreset, type TariffKey } from './profileSupport'
import { normalizeResolutionId } from './resolutionPolicy'
import type { PaintDrawMode, PaintLine, PaintOutpaintPlacement, PaintSubMode, PaintTool } from './paintTypes'
import type { PaintWorkbenchHandle } from './PaintWorkbench'
import { applyClientSeo } from './seo'
import ResilientRegion from './RuntimeBoundary'
import HistoryVideoPreview from './HistoryVideoPreview'
import { useProfileAuthNavigation } from './useProfileAuthNavigation'
import {
  normalizeFeedPayload,
  normalizeGalleryPayload,
  normalizeGeneration,
} from './runtimeContracts'
import './newUi.css'
import './paymentCheckout.css'
import './newStudioV3.css'
import previewPlaceholderUrl from './assets/preview-placeholder.jpg'
import {
  API,
  apiErrorText,
  apiFetch,
  apiUrl,
  userMediaUrl,
  verifyPrivateImage,
} from './studio/studioApi'
import {
  coreModeFromTab,
  DEFAULT_FACE_STRENGTH,
  emptyPreview,
  EMPTY_EDIT_SLOTS,
  FALLBACK_LORA_OPTIONS,
  faceStrengthPrompt,
  FEED_I18N,
  formatName,
  formatPricingId,
  historyAspectRatio,
  historyShape,
  I2I_STYLE_PREFIX,
  isRasterOpenRouterModel,
  JOB_ACTIVE,
  modelModeFromStudio,
  newClientRequestId,
  PROMPT_APPEND_PREFIX,
  QUALITY,
  randomOf,
  randomSeed,
  RESOLUTION_PRESETS,
  shapeFromSize,
  STYLE_PREFIX,
} from './studio/studioHelpers'
import { readStudioDraft } from './studio/studioDraft'
import {
  comfySafeGenerationSize,
  composeI2IEditPrompt,
  composePaintPrompt,
  createOutpaintPreview,
  createPaintMask,
  DEFAULT_PAINT_MASK_PROMPT,
  DEFAULT_PAINT_OUTPAINT_PROMPT,
  DEFAULT_PAINT_SKETCH_PROMPT,
  imageRequestSizeFromSource,
  loadHtmlImage,
  loadImageShape,
  meaningfulPaintLines,
  outpaintPaddingOnly,
  outpaintRequestSizeFromSource,
  paintStageForResolution,
  resizeUploadImage,
  sameGenerationSize,
} from './studio/studioImageProcessing'
import { initialProfileTabFromPath, initialViewFromPath, studioSeoMeta } from './studio/studioNavigation'
import { normalizePrivateMediaPath, writeVideoSourceHandoff } from './studio/videoSourceHandoff'
import type {
  CoreStudioMode,
  FeedLang,
  GalleryPickerTab,
  InspectPreview,
  LastI2ISubmit,
  LastTextSubmit,
  LoraOption,
  N2GalleryImage,
  N2Job,
  N2Tab,
  N2View,
  PreviewShape,
  PublicFormatId,
  StudioDraft,
  StudioMode,
  StudioModelSort,
  StudioPreviewState,
  UploadedSourceImage,
  UploadTarget,
} from './studio/studioTypes'
import { useModelPreferences, useStudioBackendData, useStudioDraftAutosave } from './studio/useStudioState'
const PaintWorkbench = lazy(() => import('./PaintWorkbench'))
const VideoStudio = lazy(() => import('./VideoStudio'))

export default function NewStudio(): ReactElement {
  // Route: /paint — отдельная страница режима «Редактор»; остальные режимы генератора
  // пока живут на /new. Это URL-изоляция, физический split компонента ниже в TODO.
  const initialRoute = initialViewFromPath()
  const [tab, setTabState] = useState<N2Tab>(initialRoute.tab)
  const [view, setView] = useState<N2View>(initialRoute.view)

  // Навигация страниц нового UI с синхронизацией URL. Каноничные маршруты:
  // Лента /feed, Галерея /gallery, Профиль /profile, Редактор /paint,
  // остальные режимы генератора живут на главной странице.
  const navTo = useCallback((path: string) => {
    if (window.location.pathname !== path) window.history.pushState(null, '', path)
  }, [])
  const setTab = useCallback(
    (next: N2Tab) => {
      if (next === 'feed') {
        window.location.href = '/feed'
        return
      }
      setView('tabs')
      setTabState(next)
      navTo(next === 'paint' ? '/paint' : next === 'video' ? '/video' : '/')
    },
    [navTo],
  )
  const selectStudioMode = useCallback(
    (next: V3Mode) => {
      setTab(next)
    },
    [setTab],
  )
  const goGallery = useCallback(() => {
    window.location.href = '/gallery'
  }, [])
  const goProfile = useCallback(() => {
    setView('profile')
    navTo('/profile')
  }, [navTo])

  useEffect(() => {
    if (view === 'tabs' && tab === 'feed') window.location.href = '/feed'
  }, [view, tab])

  useEffect(() => {
    applyClientSeo(studioSeoMeta(tab, view))
  }, [tab, view])

  // Кнопка «назад» браузера синхронизирует страницу с URL.
  useEffect(() => {
    const onPop = () => {
      const r = initialViewFromPath()
      setView(r.view)
      setTabState(r.tab)
    }
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])
  const { status: authStatus, me } = useAuthV2()
  const isAdmin = authStatus === 'authed' && me?.account?.role === 'admin'
  const [authOpen, setAuthOpen] = useState(false)
  const ensureAuthed = useCallback(async () => {
    if (authStatus === 'authed') return true
    if (authStatus === 'loading') {
      await initAuthV2()
      if (await refreshAuthStateV2()) return true
    }
    const current = await refreshAuthStateV2()
    if (current) return true
    setAuthOpen(true)
    return false
  }, [authStatus])
  const openProfilePage = useProfileAuthNavigation({ authStatus, view, setView, setTab: setTabState, goProfile, setAuthOpen })
  const onSaveProfile = async () => {
    const trimmed = displayName.trim()
    if (!trimmed) { setSaveMsg('Введите имя'); return }
    const age = profileAge.trim()
    if (age && (Number(age) < 13 || Number(age) > 120)) { setSaveMsg('Возраст должен быть от 13 до 120'); return }
    const normalizedAge = age ? Number(age) : null
    setSaveMsg('')
    const result = await updateProfileV2({
      display_name: trimmed,
      gender: profileGender,
      age: normalizedAge,
      public_about: publicAbout.trim(),
      public_website: publicWebsite.trim(),
      public_focus: publicFocus.trim(),
      public_phone: publicPhone.trim(),
      public_links: publicLinks
        .map((item) => ({ label: item.label.trim(), url: item.url.trim() }))
        .filter((item) => item.url),
    })
    if (result) { await refreshAuthStateV2(); setSaveMsg('Сохранено') }
    else setSaveMsg('Ошибка сохранения')
  }
  const selectAvatarPreset = async (presetId: string) => {
    const preset = avatarPresets.find((item) => item.id === presetId)
    if (!preset) return
    setAvatarBusy(true)
    setAvatarMsg('')
    const result = await updateProfileV2Detailed({ avatar_preset: presetId, avatar_url: preset.url })
    if (result.ok) {
      setAvatarPreset(presetId)
      setAvatarUrl(preset.url)
      await refreshAuthStateV2()
      setAvatarMsg('Аватар сохранён')
    } else setAvatarMsg(result.detail || 'Не удалось сохранить аватар')
    setAvatarBusy(false)
  }
  const uploadAvatar = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    if (!/^image\/(png|jpeg|webp)$/.test(file.type)) { setAvatarMsg('Нужен PNG, JPG или WEBP'); return }
    if (file.size > 8 * 1024 * 1024) { setAvatarMsg('Файл больше 8 МБ'); return }
    setAvatarBusy(true)
    setAvatarMsg('')
    try {
      const form = new FormData()
      form.append('file', file)
      const r = await fetch(`${API}/me/avatar-upload-v2`, { method: 'POST', credentials: 'include', body: form })
      const payload = await r.json().catch(() => ({}))
      if (!r.ok || !payload.avatar_url) { setAvatarMsg(String(payload.detail || 'Не удалось загрузить аватар')); return }
      setAvatarUrl(String(payload.avatar_url))
      setAvatarPreset('')
      await refreshAuthStateV2()
      setAvatarMsg('Аватар загружен')
    } catch {
      setAvatarMsg('Ошибка загрузки аватара')
    } finally {
      setAvatarBusy(false)
    }
  }
  const onLogout = async () => {
    await logoutV2()
    await refreshAuthStateV2()
  }
  const onApplyPromo = async () => {
    const code = promoCode.trim().toUpperCase()
    if (!code) { setPromoResult('Введите промокод'); return }
    setPromoBusy(true)
    setPromoResult('')
    try {
      const r = await apiFetch('/account/apply-promo-v2', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ promo_code: code }),
      })
      const payload = await r.json().catch(() => ({}))
      if (!r.ok) { setPromoResult(String(payload.detail || 'Промокод не применён')); return }
      const bonus = Number(payload.token_bonus || 50)
      setPromoResult(`Промокод применён: +${bonus} токенов`)
      await refreshAuthStateV2()
    } catch {
      setPromoResult('Не удалось проверить промокод')
    } finally {
      setPromoBusy(false)
    }
  }
  const onLinkBot = async (providerName: 'telegram' | 'max') => {
    setLinkBusy(true)
    setLinkMsg('')
    const started = await startBotLinkV2(providerName)
    if (!started.ok) {
      setLinkMsg(providerName === 'telegram' ? 'Telegram-подключение сейчас недоступно' : 'MAX-подключение сейчас недоступно')
      setLinkBusy(false)
      return
    }
    window.open(started.deep_link, '_blank', 'noopener,noreferrer')
    setLinkMsg(`Подтвердите подключение в ${providerName === 'telegram' ? 'Telegram' : 'MAX'}-боте`)
    let attemptsLeft = Math.ceil((10 * 60 * 1000) / (started.poll_interval_ms || 2000))
    const timer = window.setInterval(async () => {
      attemptsLeft -= 1
      const status = await pollBotLoginStatusV2()
      if (status.status === 'authenticated') {
        window.clearInterval(timer)
        await refreshAuthStateV2()
        setLinkBusy(false)
        setLinkMsg(`${providerName === 'telegram' ? 'Telegram' : 'MAX'} подключен`)
      } else if (status.status === 'conflict') {
        window.clearInterval(timer)
        setLinkBusy(false)
        setLinkMsg('Этот способ входа уже привязан к другому аккаунту')
      } else if (status.status === 'expired' || status.status === 'error' || attemptsLeft <= 0) {
        window.clearInterval(timer)
        setLinkBusy(false)
        setLinkMsg('Подключение не завершено. Попробуйте снова')
      }
    }, started.poll_interval_ms || 2000)
  }
  const [helpOpen, setHelpOpen] = useState(false)

  useEffect(() => {
    const syncHelpHash = () => {
      if (window.location.hash === '#help') setHelpOpen(true)
    }
    syncHelpHash()
    window.addEventListener('hashchange', syncHelpHash)
    return () => window.removeEventListener('hashchange', syncHelpHash)
  }, [])

  const [templatesOpen, setTemplatesOpen] = useState(false)
  const [galleryPickTarget, setGalleryPickTarget] = useState<UploadTarget | null>(null)
  const [galleryPickerTab, setGalleryPickerTab] = useState<GalleryPickerTab>('generated')
  const [galleryPickerImages, setGalleryPickerImages] = useState<N2GalleryImage[]>([])
  const [uploadedSources, setUploadedSources] = useState<UploadedSourceImage[]>([])
  const [galleryPickerLoading, setGalleryPickerLoading] = useState(false)
  const [galleryPickerError, setGalleryPickerError] = useState('')
  const [uploadTarget, setUploadTarget] = useState<UploadTarget | null>(null)
  const [loraTriggers] = useState<Record<string, string>>({})

  // Пол из профиля определяет вариант превью стилей (по умолчанию female).
  const previewGender: 'female' | 'male' = me?.profile?.gender === 'male' ? 'male' : 'female'
  const acct = accountInfo(me)
  const topbarDailyLimit = Math.max(0, Number(me?.account?.daily_tokens_limit ?? me?.account?.daily_tokens ?? 0))
  const topbarDailyRemaining = Math.max(0, Number(me?.account?.daily_tokens_remaining ?? topbarDailyLimit - Number(me?.account?.daily_tokens_used ?? 0)))
  const topbarTokenBalance = Math.max(0, Number(me?.account?.token_balance ?? 0))

  const [initialStudioDraft] = useState<StudioDraft>(readStudioDraft)
  const [prompts, setPrompts] = useState<Record<StudioMode, string>>({
    text: initialStudioDraft.prompts?.text || '',
    i2i: initialStudioDraft.prompts?.i2i || '',
    edit: initialStudioDraft.prompts?.edit || '',
    paint: initialStudioDraft.prompts?.paint || '',
  })
  const [styleId, setStyleId] = useState<string>(initialStudioDraft.styleId || '')
  // Временный предпросмотр стиля при наведении на карточку (не выбирает стиль).
  const [hoverStyle, setHoverStyle] = useState<StylePreset | null>(null)
  // Разрешение = конкретный системный пресет; формат-кнопки переключают тип.
  const [resolutionId, setResolutionId] = useState(() => normalizeResolutionId(initialStudioDraft.resolutionId || 'sq-hd'))
  const [formatAutoNotice, setFormatAutoNotice] = useState('')
  const [formatOpen, setFormatOpen] = useState(false)
  const formatRef = useRef<HTMLDivElement>(null)
  const [quality, setQuality] = useState(initialStudioDraft.quality || 'fast')
  const [proMode, setProMode] = useState(false)
  const [proModelChoices, setProModelChoices] = useState<Partial<Record<ModelModeKey, string>>>({})
  const [proModelDetails, setProModelDetails] = useState<Partial<Record<ModelModeKey, string>>>({})
  const [studioModelSort, setStudioModelSort] = useState<StudioModelSort>('tokens-asc')
  const [seed, setSeed] = useState(initialStudioDraft.seed || 0)
  const [guidance] = useState(3.5)
  const [strengthPct, setStrengthPct] = useState(initialStudioDraft.strengthPct ?? 75)
  const [sourceImage, setSourceImage] = useState<string | undefined>(initialStudioDraft.sourceImage)
  const [editSlots, setEditSlots] = useState<EditSlot[]>(() => (
    Array.isArray(initialStudioDraft.editSlots) && initialStudioDraft.editSlots.length === EDIT_SLOT_COUNT
      ? initialStudioDraft.editSlots.map((slot) => ({ ...slot }))
      : EMPTY_EDIT_SLOTS.map((slot) => ({ ...slot }))
  ))
  const [editExtraOpen, setEditExtraOpen] = useState(false)
  const [editFaceStrengthPct, setEditFaceStrengthPct] = useState(initialStudioDraft.editFaceStrengthPct ?? DEFAULT_FACE_STRENGTH)
  const [profileTab, setProfileTab] = useState<'profile' | 'tariffs' | 'earn' | 'models'>(initialProfileTabFromPath)
  const { modelsPayload, tariffs, tariffsState, tokenRub, modelAccess, openrouterPricing } = useStudioBackendData(me)
  const activeTariffKey = (String(me?.account?.plan || 'mini').toLowerCase() in tariffs ? String(me?.account?.plan || 'mini').toLowerCase() : 'mini') as TariffKey
  const activeTariff = tariffs[activeTariffKey] || DEFAULT_TARIFFS[activeTariffKey] || DEFAULT_TARIFFS.mini
  const effectiveProMode = proMode
  const { userModelChoices, setUserModelChoices, userModelVisibility, setUserModelVisibility } = useModelPreferences()
  const [displayName, setDisplayName] = useState(me?.profile?.display_name || '')
  const [profileGender, setProfileGender] = useState<'female' | 'male'>(me?.profile?.gender === 'male' ? 'male' : 'female')
  const [profileAge, setProfileAge] = useState(me?.profile?.age ? String(me.profile.age) : '')
  const [publicAbout, setPublicAbout] = useState(me?.profile?.public_about || '')
  const [publicWebsite, setPublicWebsite] = useState(me?.profile?.public_website || '')
  const [publicFocus, setPublicFocus] = useState(me?.profile?.public_focus || '')
  const [publicPhone, setPublicPhone] = useState(me?.profile?.public_phone || '')
  const [publicLinks, setPublicLinks] = useState<PublicProfileLink[]>(() => (
    (me?.profile?.public_links || [])
      .map((item) => ({ label: String(item.label || ''), url: String(item.url || '') }))
      .filter((item) => item.url)
      .slice(0, 6)
  ))
  const [saveMsg, setSaveMsg] = useState('')
  const [avatarUrl, setAvatarUrl] = useState(me?.profile?.avatar_url || avatarPresets[0].url)
  const [avatarPreset, setAvatarPreset] = useState(me?.profile?.avatar_preset || '')
  const [avatarMsg, setAvatarMsg] = useState('')
  const [avatarBusy, setAvatarBusy] = useState(false)
  const [promoCode, setPromoCode] = useState('')
  const [promoResult, setPromoResult] = useState('')
  const [promoBusy, setPromoBusy] = useState(false)
  const [inviteMsg, setInviteMsg] = useState('')
  const [authCaps, setAuthCaps] = useState({ telegram_bot_login_available: false, max_bot_login_available: false })
  const [authCapsState, setAuthCapsState] = useState<'loading' | 'ready' | 'fallback'>('loading')
  const [linkMsg, setLinkMsg] = useState('')
  const [linkBusy, setLinkBusy] = useState(false)
  const [paintMode, setPaintMode] = useState<PaintSubMode>('sketch')
  const [paintImage, setPaintImage] = useState<string>()
  const [paintSketchImage, setPaintSketchImage] = useState<string>()
  const [paintSketchLines, setPaintSketchLines] = useState<PaintLine[]>([])
  const [paintMaskLines, setPaintMaskLines] = useState<PaintLine[]>([])
  const [paintTool, setPaintTool] = useState<PaintTool>('brush')
  const [paintDrawMode, setPaintDrawMode] = useState<PaintDrawMode>('free')
  const [paintBrushSize, setPaintBrushSize] = useState(3)
  const [paintTechPrompts, setPaintTechPrompts] = useState<Record<PaintSubMode, string>>({
    sketch: DEFAULT_PAINT_SKETCH_PROMPT,
    mask: DEFAULT_PAINT_MASK_PROMPT,
    outpaint: DEFAULT_PAINT_OUTPAINT_PROMPT,
    remove_bg: 'Аккуратно удали фон, сохрани главный объект и его края.',
  })
  const [paintTechPromptOpen, setPaintTechPromptOpen] = useState(false)
  const [paintColor, setPaintColor] = useState('#111827')
  const [paintCanvasBg, setPaintCanvasBg] = useState<'white' | 'gray'>('white')
  const [paintOutpaint, setPaintOutpaint] = useState<PaintOutpaintPlacement>({ left: 0, right: 0, top: 0, bottom: 0 })
  const [paintOutpaintPreview, setPaintOutpaintPreview] = useState<string>()
  const [paintStageSize, setPaintStageSize] = useState(() => paintStageForResolution(RESOLUTION_PRESETS[0]))
  const [paintWorkbenchVisible, setPaintWorkbenchVisible] = useState(true)
  const [promptImproveBusy, setPromptImproveBusy] = useState(false)
  const [lastImprovedPrompt, setLastImprovedPrompt] = useState<{ mode: StudioMode; text: string } | null>(null)
  const [voiceRecording, setVoiceRecording] = useState(false)
  const [voiceBusy, setVoiceBusy] = useState(false)
  const voiceRecorderRef = useRef<MediaRecorder | null>(null)
  const voiceStreamRef = useRef<MediaStream | null>(null)
  const voiceStartedAtRef = useRef(0)

  const [paintToolsOpen, setPaintToolsOpen] = useState(false)
  const [compare, setCompare] = useState(50)
  const [compareEnabled, setCompareEnabled] = useState(true)
  const [compareAuto, setCompareAuto] = useState(false)
  const compareTouchedRef = useRef(false)

  // ---------- Live Feed state ----------
  // Язык ленты из профиля (RU по умолчанию — как весь /new).
  const feedLang: FeedLang = me?.profile?.language_code === 'en' ? 'en' : 'ru'
  const ft = FEED_I18N[feedLang]

  const [toastText, setToastText] = useState('')
  const toastTimerRef = useRef<number>(0)

  // Публикация из галереи: модалка поверх просмотра изображения.
  const [publishFor, setPublishFor] = useState<N2GalleryImage | null>(null)
  const [publishTitle, setPublishTitle] = useState('')
  const [publishVisibility, setPublishVisibility] = useState<'open' | 'partial' | 'hidden'>('open')
  const [publishAllowRecreate, setPublishAllowRecreate] = useState(true)
  const [publishBusy, setPublishBusy] = useState(false)

  const showToast = useCallback((text: string) => {
    setToastText(text)
    window.clearTimeout(toastTimerRef.current)
    toastTimerRef.current = window.setTimeout(() => setToastText(''), 2100)
  }, [])

  // Публикация выбранного изображения галереи.
  const openPublish = async (item: N2GalleryImage) => {
    if (!(await ensureAuthed())) return
    setPublishTitle('')
    setPublishVisibility('open')
    setPublishAllowRecreate(true)
    setPublishFor(item)
  }

  // Удалить изображение из личной галереи (как в старом интерфейсе: DELETE
  // /api/gallery/{id}). Только для своей галереи, требует сессию.
  const deleteGalleryImage = async (item: N2GalleryImage) => {
    if (!(await ensureAuthed())) return
    if (!window.confirm(ft.deleteConfirm)) return
    apiFetch(`/gallery/${item.id}`, { method: 'DELETE' })
      .then((r) => {
        if (!r.ok) throw new Error(String(r.status))
        setGallery((cur) => cur.filter((g) => g.id !== item.id))
        setGalleryItem(undefined)
        void refreshAuthStateV2()
        showToast(feedLang === 'ru' ? 'Удалено из галереи' : 'Deleted from gallery')
      })
      .catch(() => showToast(feedLang === 'ru' ? 'Не удалось удалить' : 'Delete failed'))
  }

  // «Использовать как основу» → По фото с этим изображением-исходником.
  const applyGalleryAsSource = (item: N2GalleryImage) => {
    setSourceImage(apiUrl(item.url))
    setGalleryItem(undefined)
    setTab('i2i')
  }

  // Профиль: язык RU/EN и выход.

  useEffect(() => {
    void initAuthV2()
  }, [])

  const submitPublish = () => {
    if (!publishFor || publishBusy) return
    const title = publishTitle.trim()
    if (!title) {
      showToast(feedLang === 'ru' ? 'Укажите название' : 'Title is required')
      return
    }
    setPublishBusy(true)
    apiFetch('/feed/publications', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        imageId: publishFor.id,
        title,
        promptVisibility: publishVisibility,
        allowRecreate: publishAllowRecreate,
      }),
    })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((data) => {
        setPublishFor(null)
        setGalleryItem(undefined)
        const pendingReview = data?.moderation === 'pending_review'
        showToast(pendingReview
          ? (feedLang === 'ru' ? 'Отправлено на проверку' : 'Sent for review')
          : (feedLang === 'ru' ? 'Опубликовано в ленту' : 'Published to feed'))
        if (pendingReview) return
        const publicationId = String(data?.publication?.id || '').trim()
        window.setTimeout(() => {
          window.location.href = publicationId
            ? `/feed?tab=new#work-${encodeURIComponent(publicationId)}`
            : '/feed?tab=new'
        }, 250)
      })
      .catch(() => showToast(feedLang === 'ru' ? 'Не удалось опубликовать' : 'Publish failed'))
      .finally(() => setPublishBusy(false))
  }

  const [job, setJob] = useState<N2Job>()
  const [jobMode, setJobMode] = useState<StudioMode>('text')
  const [progressNow, setProgressNow] = useState(() => Date.now())
  const [resultUrl, setResultUrl] = useState<string>()
  // URL результата не загрузился (битая ссылка/удалённый файл) — error-state.
  const [resultError, setResultError] = useState(false)
  const [resultSource, setResultSource] = useState<string>()
  const [inspectPreview, setInspectPreview] = useState<InspectPreview | null>(null)
  const [previewByMode, setPreviewByMode] = useState<Record<CoreStudioMode, StudioPreviewState>>({
    text: emptyPreview(),
    i2i: emptyPreview(),
    edit: emptyPreview(),
  })
  const [inspectZoom, setInspectZoom] = useState(1)
  const [inspectPan, setInspectPan] = useState({ x: 0, y: 0 })
  const [notice, setNotice] = useState('')
  useEffect(() => {
    let cancelled = false
    const raw = window.sessionStorage.getItem('izoUseAsDraft')
    if (!raw) return undefined

    const applyDraft = async () => {
      try {
        const draft = JSON.parse(raw) as { target?: string; inputImage?: string; prompt?: string }
        const target = draft.target || 'image'
        if (target !== 'prompt' && !draft.inputImage) throw new Error('Missing draft image')
        const image = draft.inputImage ? apiUrl(draft.inputImage) : ''
        if (image) await verifyPrivateImage(image)
        if (cancelled) return

        if (target === 'prompt') {
          setTab('text')
          if (draft.prompt) setPrompts((current) => ({ ...current, text: draft.prompt || '' }))
        } else if (target === 'editor' || target === 'face_target') {
          setTab('edit')
          setEditSlots((current) => current.map((slot, index) => index === 0 ? { ...slot, image } : slot))
          if (draft.prompt) setPrompts((current) => ({ ...current, edit: draft.prompt || '' }))
        } else if (target === 'face_source') {
          setTab('edit')
          setEditSlots((current) => current.map((slot, index) => (
            index === 1 ? { ...slot, image, role: 'face', takeNote: '' } : slot
          )))
        } else if (target === 'draw') {
          setTab('paint')
          setPaintImage(image)
          setPaintWorkbenchVisible(true)
          if (draft.prompt) setPrompts((current) => ({ ...current, paint: draft.prompt || '' }))
        } else {
          setTab('i2i')
          setSourceImage(image)
          if (draft.prompt) setPrompts((current) => ({ ...current, i2i: draft.prompt || '' }))
        }
        window.sessionStorage.removeItem('izoUseAsDraft')
      } catch {
        if (!cancelled) setNotice('Не удалось загрузить выбранное изображение. Черновик сохранён — повторите переход из галереи.')
      }
    }
    void applyDraft()
    return () => { cancelled = true }
  }, [setTab])
  const [gallery, setGallery] = useState<N2GalleryImage[]>([])
  const [galleryItem, setGalleryItem] = useState<N2GalleryImage>()
  const [historyVideoPreview, setHistoryVideoPreview] = useState<N2GalleryImage | null>(null)
  // Изображение, чей промпт показан в доке «Промпт изображения» (v3-студия).
  // Храним только id выбранной миниатюры; сам объект выводим при рендере,
  // с откатом на самую свежую генерацию (без setState-в-эффекте).
  const [dockImageId, setDockImageId] = useState<string>()
  // Фолбэк истории из Ленты, когда у пользователя ещё нет своих генераций.
  const [feedFallback, setFeedFallback] = useState<N2GalleryImage[]>([])
  const [shareOpen, setShareOpen] = useState(false)
  const [copied, setCopied] = useState(false)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const inFlightRef = useRef(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const historyStripRef = useRef<HTMLDivElement>(null)
  const promptTextareaRef = useRef<HTMLTextAreaElement>(null)
  // true, если тянули историю мышью — тогда клик по миниатюре не выбирает её.
  const historyDraggedRef = useRef(false)
  const styleRowRef = useRef<HTMLDivElement>(null)
  const pendingResultSourceRef = useRef<Record<StudioMode, string | undefined>>({ text: undefined, i2i: undefined, edit: undefined, paint: undefined })
  const pendingResultShapeRef = useRef<Record<StudioMode, PreviewShape | undefined>>({ text: undefined, i2i: undefined, edit: undefined, paint: undefined })
  // true, если пользователь тянул ряд стилей — тогда клик по карточке не выбирает.
  const styleDraggedRef = useRef(false)
  // true, пока зажата кнопка над рядом стилей — подавляет hover-preview при drag.
  const stylePointerDownRef = useRef(false)
  const inspectDragRef = useRef<{ active: boolean; startX: number; startY: number; panX: number; panY: number }>({ active: false, startX: 0, startY: 0, panX: 0, panY: 0 })
  const inspectTouchRef = useRef<{ pinching: boolean; distance: number; zoom: number; panX: number; panY: number; startX: number; startY: number; lastTap: number }>({
    pinching: false,
    distance: 0,
    zoom: 1,
    panX: 0,
    panY: 0,
    startX: 0,
    startY: 0,
    lastTap: 0,
  })
  const paintStageRef = useRef<PaintWorkbenchHandle>(null)
  const paintWorkbenchRef = useRef<HTMLDivElement>(null)
  const paintLines = paintMode === 'mask' ? paintMaskLines : paintSketchLines
  const setPaintLines = paintMode === 'mask' ? setPaintMaskLines : setPaintSketchLines
  // Текущая стилевая приписка в text-промпте: {id, text} — чтобы заменять её.
  const appliedStyleRef = useRef<{ id: string; text: string } | null>(null)
  // Текущая стилевая приписка в i2i-промпте — видна прямо в textarea.
  const appliedI2IStyleRef = useRef<{ id: string; text: string } | null>(null)
  const lastTextSubmittedRef = useRef<LastTextSubmit | undefined>(undefined)
  const lastI2ISubmittedRef = useRef<LastI2ISubmit | undefined>(undefined)
  const noticeClearRef = useRef<{ text: string; i2i: string; edit: string; paint: string; source: string; editSlots: string }>({ text: '', i2i: '', edit: '', paint: '', source: '', editSlots: '' })
  const resultSeededRef = useRef(false)

  useEffect(() => {
    document.title = 'ИЗО АСА — новый интерфейс'
  }, [])

  useStudioDraftAutosave({ prompts, styleId, resolutionId, quality, seed, strengthPct, sourceImage, editSlots, editFaceStrengthPct })

  useEffect(() => {
    queueMicrotask(() => {
      setDisplayName(me?.profile?.display_name || '')
      setProfileGender(me?.profile?.gender === 'male' ? 'male' : 'female')
      setProfileAge(me?.profile?.age === null || me?.profile?.age === undefined ? '' : String(me.profile.age))
      setPublicAbout(me?.profile?.public_about || '')
      setPublicWebsite(me?.profile?.public_website || '')
      setPublicFocus(me?.profile?.public_focus || '')
      setPublicPhone(me?.profile?.public_phone || '')
      setPublicLinks((me?.profile?.public_links || []).map((item) => ({ label: String(item.label || ''), url: String(item.url || '') })).filter((item) => item.url).slice(0, 6))
      setAvatarUrl(me?.profile?.avatar_url || avatarPresets[0].url)
      setAvatarPreset(me?.profile?.avatar_preset || '')
      setSaveMsg('')
      setAvatarMsg('')
    })
  }, [me?.profile?.age, me?.profile?.avatar_preset, me?.profile?.avatar_url, me?.profile?.display_name, me?.profile?.gender, me?.profile?.public_about, me?.profile?.public_focus, me?.profile?.public_links, me?.profile?.public_phone, me?.profile?.public_website])

  useEffect(() => {
    let active = true
    getAuthCapabilitiesV2()
      .then((caps) => {
        if (!active) return
        setAuthCaps({ telegram_bot_login_available: caps.telegram_bot_login_available, max_bot_login_available: caps.max_bot_login_available })
        setAuthCapsState(caps.capabilities_loaded ? 'ready' : 'fallback')
      })
      .catch(() => {
        if (active) setAuthCapsState('fallback')
      })
    return () => { active = false }
  }, [])

  // Стабильная загрузка галереи: как только увидели свои изображения, спуриозный
  // пустой ответ (транзиентный 401 при refresh и т.п.) больше не затирает историю,
  // чтобы лента-фолбэк не «перебивал» уже показанную пользовательскую галерею.
  const ownGallerySeenRef = useRef(false)
  const fetchGallery = useCallback(async () => {
    try {
      const data = await apiFetch('/gallery/items?limit=24').then((r) => (r.ok ? r.json() : null))
      const arr = normalizeGalleryPayload(data)
      if (arr.length === 0 && ownGallerySeenRef.current) return []
      if (arr.length > 0) ownGallerySeenRef.current = true
      setGallery(arr)
      return arr
    } catch {
      return []
    }
  }, [])

  useEffect(() => {
    fetchGallery()
  }, [fetchGallery, authStatus])

  // Если своих генераций ещё нет — подгружаем последние работы из Ленты как
  // наполнение истории (публичный /api/feed). Свои изображения ленту не мешают.
  useEffect(() => {
    // Свои генерации есть — лента не нужна (в рендере historyItems берёт ownHistory).
    if (gallery.length > 0) return
    let cancelled = false
    apiFetch('/feed?type=new&limit=10')
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (cancelled || !data) return
        const mapped: N2GalleryImage[] = normalizeFeedPayload(data).map((item) => ({
          id: `feed-${item.id}`,
          mediaType: 'image' as const,
          url: item.displayUrl,
          thumbnailUrl: item.thumbnailUrl,
          mode: 'feed',
          promptOriginal: item.prompt,
          createdAt: item.createdAt,
          aspectRatio: item.aspectRatio,
          tokenCost: null,
        })).slice(0, 10)
        setFeedFallback(mapped)
      })
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [gallery.length])

  // В предпросмотре при загрузке страницы показываем последнюю генерацию.
  useEffect(() => {
    if (resultSeededRef.current || resultUrl || gallery.length === 0) return
    resultSeededRef.current = true
    setPreviewByMode((cur) => cur.text.kind === 'empty'
      ? { ...cur, text: { kind: 'history', url: gallery[0].url, shape: historyShape(gallery[0]), galleryId: gallery[0].id, promptOriginal: gallery[0].promptOriginal, title: 'Последняя генерация' } }
      : cur)
  }, [gallery, resultUrl])

  // Поллинг активной задачи — тот же контракт, что в основном UI (resultUrl).
  useEffect(() => {
    if (!job || !JOB_ACTIVE.includes(job.status)) return
    const timer = window.setInterval(async () => {
      try {
        const response = await apiFetch(`/jobs/${job.id}`)
        if (!response.ok) {
          if (response.status === 404) setNotice('Задача не найдена. Обновите историю, если результат уже сохранился.')
          return
        }
        const next = normalizeGeneration(await response.json())
        if (!next) {
          setNotice('Сервер вернул неполные данные задачи. Повторите проверку истории.')
          return
        }
        setJob(next)
        if (next.status === 'completed') {
          const completedUrl = next.resultUrl
          const completedImageId = next.resultImageId
          if (completedUrl) {
            setResultError(false)
            if (jobMode === 'paint') {
              setResultUrl(completedUrl)
            } else {
              const coreMode = jobMode as CoreStudioMode
              setPreviewByMode((cur) => ({
                ...cur,
                [coreMode]: {
                  kind: 'result',
                  url: completedUrl,
                  sourceUrl: pendingResultSourceRef.current[jobMode],
                  shape: next.width && next.height ? shapeFromSize(next.width, next.height) : pendingResultShapeRef.current[jobMode],
                  title: 'Результат генерации',
                  resultImageId: completedImageId,
                  galleryId: completedImageId,
                  width: next.width,
                  height: next.height,
                  error: false,
                },
              }))
            }
          }
          if (completedImageId) setDockImageId(completedImageId)
          const freshGallery = await fetchGallery()
          const fallbackImage = freshGallery.find((item) => item.resultImageId === next.resultImageId || item.id === next.resultImageId) || freshGallery[0]
          if (!completedUrl && fallbackImage?.url) {
            const fallbackImageId = next.resultImageId || fallbackImage.id
            setResultError(false)
            if (jobMode === 'paint') {
              setResultUrl(fallbackImage.url)
            } else {
              const coreMode = jobMode as CoreStudioMode
              setPreviewByMode((cur) => ({
                ...cur,
                [coreMode]: {
                  kind: 'result',
                  url: fallbackImage.url,
                  sourceUrl: pendingResultSourceRef.current[jobMode],
                  shape: fallbackImage.width && fallbackImage.height ? shapeFromSize(fallbackImage.width, fallbackImage.height) : pendingResultShapeRef.current[jobMode],
                  title: 'Результат генерации',
                  resultImageId: fallbackImageId,
                  galleryId: fallbackImageId,
                  promptOriginal: fallbackImage.promptOriginal,
                  width: fallbackImage.width,
                  height: fallbackImage.height,
                  error: false,
                },
              }))
            }
            setDockImageId(fallbackImageId)
          } else if (!completedUrl) {
            setNotice('Генерация завершилась, но результат ещё сохраняется. Обновляю историю...')
          } else if (fallbackImage?.promptOriginal && completedImageId) {
            setPreviewByMode((cur) => {
              const coreMode = jobMode as CoreStudioMode
              if (jobMode === 'paint' || cur[coreMode]?.resultImageId !== completedImageId) return cur
              return { ...cur, [coreMode]: { ...cur[coreMode], promptOriginal: fallbackImage.promptOriginal } }
            })
          }
          void refreshAuthStateV2()
        } else if (next.status === 'failed') {
          setNotice(apiErrorText(next.error, 'Сервер временно недоступен. Попробуйте ещё раз позже.'))
          if (jobMode === 'paint') {
            setResultError(true)
          } else {
            const coreMode = jobMode as CoreStudioMode
            setPreviewByMode((cur) => ({ ...cur, [coreMode]: { ...cur[coreMode], error: true } }))
          }
        }
      } catch {
        /* сеть мигнула — следующий тик */
      }
    }, 900)
    return () => window.clearInterval(timer)
  }, [fetchGallery, job, jobMode])

  const promptKey: StudioMode = tab === 'i2i' ? 'i2i' : tab === 'edit' ? 'edit' : tab === 'paint' ? 'paint' : 'text'
  const setPrompt = useCallback(
    (value: string) => setPrompts((cur) => ({ ...cur, [promptKey]: value })),
    [promptKey],
  )

  useEffect(() => {
    const prev = noticeClearRef.current
    const source = sourceImage || ''
    const editSlotSignature = editSlots.map((slot) => `${slot.image || ''}:${slot.role}:${slot.takeNote || ''}`).join('|')
    const changed = prev.text !== prompts.text || prev.i2i !== prompts.i2i || prev.edit !== prompts.edit || prev.paint !== prompts.paint || prev.source !== source || prev.editSlots !== editSlotSignature
    noticeClearRef.current = { text: prompts.text, i2i: prompts.i2i, edit: prompts.edit, paint: prompts.paint, source, editSlots: editSlotSignature }
    if (notice && changed) setNotice('')
  }, [editSlots, notice, prompts.edit, prompts.i2i, prompts.paint, prompts.text, sourceImage])

  useEffect(() => {
    if (!notice) return undefined
    const timer = window.setTimeout(() => setNotice(''), 5000)
    return () => window.clearTimeout(timer)
  }, [notice])

  // Стиль в «По тексту»: приписываем текст стиля в промпт (замена предыдущего).
  // Вся строковая математика — вне setState-updater (updater обязан быть чистым:
  // под StrictMode он вызывается дважды, и мутация ref внутри него ломает замену).
  // targetTab передаётся явно: из Ленты стиль применяется к «По тексту»,
  // хотя state `tab` в замыкании ещё старый.
  function applyStyleTo(targetTab: 'text' | 'i2i', next: StylePreset | null) {
    setStyleId(next?.id || '')
    if (targetTab === 'i2i') {
      const applied = appliedI2IStyleRef.current
      let text = prompts.i2i
      if (applied && text.includes(applied.text)) text = text.replace(applied.text, '')
      if (next) {
        const addition = `${I2I_STYLE_PREFIX}${next.transformPrompt}`
        text = `${text.trimEnd()}${addition}`
        appliedI2IStyleRef.current = { id: next.id, text: addition }
      } else {
        appliedI2IStyleRef.current = null
      }
      setPrompts((cur) => ({ ...cur, i2i: text }))
      return
    }
    const applied = appliedStyleRef.current
    let text = prompts.text
    if (applied && text.includes(applied.text)) text = text.replace(applied.text, '')
    if (next) {
      const addition = `${STYLE_PREFIX}${next.stylePrompt}`
      text = `${text.trimEnd()}${addition}`
      appliedStyleRef.current = { id: next.id, text: addition }
    } else {
      appliedStyleRef.current = null
    }
    setPrompts((cur) => ({ ...cur, text }))
  }

  function applyStyle(next: StylePreset | null) {
    applyStyleTo(tab === 'i2i' ? 'i2i' : 'text', next)
  }

  function applyTemplate(templatePrompt: string) {
    appliedStyleRef.current = null
    setStyleId('')
    setPrompt(templatePrompt)
    setTemplatesOpen(false)
  }

  function appendI2ITemplate(templatePrompt: string) {
    setPrompts((cur) => ({
      ...cur,
      i2i: cur.i2i.trim() ? `${cur.i2i.trimEnd()}${PROMPT_APPEND_PREFIX}${templatePrompt}` : templatePrompt,
    }))
    showToast('Шаблон добавлен в промпт')
  }

  function randomPrompt() {
    if (tab === 'i2i') {
      appendI2ITemplate(randomOf(I2I_STYLES).transformPrompt)
    } else {
      applyTemplate(randomOf(T2I_TEMPLATES).prompt)
    }
  }

  function clearEditSlot(index: number) {
    if (inspectPreview && editSlots[index]?.image === inspectPreview.url) setInspectPreview(null)
    if (editSlots[index]?.image) {
      const removed = editSlots[index].image
      setPreviewByMode((cur) => cur.edit.url === removed || cur.edit.sourceUrl === removed ? { ...cur, edit: emptyPreview() } : cur)
    }
    setEditSlots((current) => current.map((slot, i) => (i === index ? { image: undefined, role: '', takeNote: '' } : slot)))
  }

  function setEditSlotRole(index: number, role: EditReferenceRole | '') {
    if (role === 'pose') {
      showToast('Поза временно недоступна')
      setNotice('Смена позы временно отключена: workflow нестабилен.')
      return
    }
    setEditSlots((current) => current.map((slot, i) => (i === index ? { ...slot, role } : slot)))
  }

  function setEditSlotTakeNote(index: number, takeNote: string) {
    setEditSlots((current) => current.map((slot, i) => (i === index ? { ...slot, takeNote } : slot)))
  }

  function openUpload(target: UploadTarget) {
    setUploadTarget(target)
    fileInputRef.current?.click()
  }

  function openGalleryPick(target: UploadTarget) {
    setGalleryPickTarget(target)
    setGalleryPickerTab('generated')
    setGalleryPickerLoading(true)
    setGalleryPickerError('')
    Promise.all([
      apiFetch('/gallery/items?limit=60'),
      apiFetch('/gallery/secondary?limit=60'),
    ])
      .then(async ([primaryResponse, secondaryResponse]) => {
        if (!primaryResponse.ok || !secondaryResponse.ok) throw new Error('gallery picker unavailable')
        return Promise.all([primaryResponse.json(), secondaryResponse.json()])
      })
      .then(([primary, secondary]) => {
        setGalleryPickerImages(normalizeGalleryPayload(primary))
        setUploadedSources(Array.isArray(secondary?.uploadedItems) ? secondary.uploadedItems : [])
      })
      .catch(() => setGalleryPickerError('Не удалось загрузить ранее загруженные изображения.'))
      .finally(() => setGalleryPickerLoading(false))
  }

  async function retryImageOnce(image: HTMLImageElement, onFailure: () => void) {
    if (image.dataset.retryAttempted === '1') {
      onFailure()
      return
    }
    image.dataset.retryAttempted = '1'
    await ensureSessionRefreshedV2().catch(() => false)
    const url = new URL(image.currentSrc || image.src, window.location.href)
    url.searchParams.set('_retry', String(Date.now()))
    image.src = url.toString()
  }

  function markPickerImageError(event: ChangeEvent<HTMLImageElement>) {
    const image = event.currentTarget
    void retryImageOnce(image, () => {
      image.hidden = true
      image.closest('.n2-template-style')?.classList.add('is-broken')
    })
  }

  function showInspectPreview(url: string, title: string) {
    const coreMode = coreModeFromTab(tab)
    if (!coreMode) {
      setPaintWorkbenchVisible(false)
      setInspectPreview({ url, title })
    } else {
      setPreviewByMode((cur) => ({ ...cur, [coreMode]: { kind: 'inspect', url, title, shape: cur[coreMode].shape, error: false } }))
      void loadImageShape(url).then((shape) => {
        setPreviewByMode((cur) => {
          const current = cur[coreMode]
          return current.kind === 'inspect' && current.url === url ? { ...cur, [coreMode]: { ...current, shape } } : cur
        })
      })
    }
    setInspectZoom(1)
    setInspectPan({ x: 0, y: 0 })
    setResultError(false)
  }

  function applyImageToTarget(target: UploadTarget | null, image: string) {
    if (!target || target.kind === 'i2i') {
      setSourceImage(image)
      showInspectPreview(image, 'Исходное изображение')
      return
    }
    if (target.kind === 'paintSketch') {
      setPaintSketchImage(image)
      setPaintWorkbenchVisible(true)
      setPaintMode('sketch')
      setInspectPreview(null)
      resetInspectView()
      return
    }
    if (target.kind === 'paint') {
      setPaintImage(image)
      setPaintOutpaintPreview(undefined)
      setPaintWorkbenchVisible(true)
      setInspectPreview(null)
      resetInspectView()
      return
    }
    setEditSlots((current) => current.map((slot, i) => {
      if (i !== target.index) return slot
      return target.index > 0 ? { image, role: '', takeNote: '' } : { ...slot, image }
    }))
    showInspectPreview(image, target.index === 0 ? 'Основа' : `Референс ${target.index}`)
  }

  async function generate(mode: StudioMode) {
    if (inFlightRef.current || isSubmitting || jobActive) return
    const textPrompt = prompts.text.trim()
    const i2iPrompt = prompts.i2i.trim()
    const editPrompt = prompts.edit.trim()
    const i2iSource = sourceImage || ''
    const size = RESOLUTION_PRESETS.find((p) => p.id === resolutionId) || RESOLUTION_PRESETS[0]
    const selectedQuality = (['fast', 'standard', 'max'].includes(quality) ? quality : 'fast') as QualityPreset
    const selectedModelMode = modelModeFromStudio(mode, paintMode)
    const selectedModel = effectiveProMode ? studioProSelectedModel(selectedModelMode, selectedQuality) : studioSelectedModel(selectedModelMode, selectedQuality)
    const requestEditReferenceLimit = selectedModel.provider === 'openrouter'
      ? Math.max(2, Math.min(EDIT_SLOT_COUNT, selectedModel.generation?.maxInputReferences || 2))
      : EDIT_SLOT_COUNT
    const requestEditSlots = editSlots.slice(0, requestEditReferenceLimit)
    const editComposer = editComposerStatus({ slots: requestEditSlots, userNote: editPrompt, manualMode: false, manualPrompt: '' })
    // Пустой запрос не запускает генерацию — показываем понятную подсказку.
    if (mode === 'text' && !textPrompt) {
      showToast('Опишите идею — что вы хотите увидеть')
      return
    }
    if (mode === 'i2i' && !sourceImage) {
      showToast('Добавьте исходное изображение')
      return
    }
    if (mode === 'i2i' && !(i2iPrompt || styleId)) {
      showToast('Опишите преобразование или выберите стиль')
      return
    }
    if (mode === 'edit' && editComposer.blockReason) {
      showToast(editComposer.blockReason)
      setNotice(editComposer.blockReason)
      return
    }
    if (mode === 'paint') {
      const paintBlock = paintMode === 'sketch' && !paintSketchImage && !meaningfulPaintLines(paintLines)
        ? 'Нарисуйте эскиз на холсте.'
        : paintMode !== 'sketch' && !paintImage
          ? 'Загрузите изображение для этого режима.'
          : paintMode === 'mask' && !meaningfulPaintLines(paintLines)
            ? 'Закрасьте область маской.'
            : paintMode === 'outpaint' && !Object.values(outpaintPaddingOnly(paintOutpaint)).some((value) => Number(value) > 0)
              ? 'Задайте поле расширения слева, справа, сверху или снизу.'
            : null
      if (paintBlock) {
        showToast(paintBlock)
        setNotice(paintBlock)
        return
      }
    }
    const presetRequestSize = selectedModel.provider === 'comfyui' ? comfySafeGenerationSize(size) : size
    const lastText = lastTextSubmittedRef.current
    const allowsExactRepeat = selectedModel.generation?.allowsExactRepeat ?? selectedModel.provider === 'openrouter'
    if (mode === 'text' && !allowsExactRepeat && lastText && lastText.prompt === textPrompt && lastText.model === selectedModel.id && lastText.width === presetRequestSize.width && lastText.height === presetRequestSize.height) {
      showToast('Измените промпт перед новой локальной генерацией')
      setNotice('Для повторного запуска ИЗО Base измените промпт, модель или формат.')
      return
    }
    const lastI2I = lastI2ISubmittedRef.current
    if (mode === 'i2i' && lastI2I && lastI2I.prompt === i2iPrompt && lastI2I.source === i2iSource && lastI2I.width === size.width && lastI2I.height === size.height && lastI2I.model === selectedModel.id) {
      showToast('Измените промпт, модель, формат или изображение')
      setNotice('Измените промпт, модель, формат или исходное изображение перед новой генерацией.')
      return
    }
    if (!(await ensureAuthed())) return
    inFlightRef.current = true
    setIsSubmitting(true)
    setNotice('')
    try {
      const style = I2I_STYLES.find((s) => s.id === styleId)
      const steps = mode === 'text' && typeof selectedModel.generation?.fixedSteps === 'number'
        ? selectedModel.generation.fixedSteps
        : mode === 'text' && selectedModel.provider === 'comfyui'
          ? 4
        : QUALITY.find((q) => q.id === quality)?.steps || 4
      const effectiveSeed = seed || randomSeed()
      const rawRequestSize = mode === 'paint' && paintMode === 'outpaint'
          ? await outpaintRequestSizeFromSource(paintImage, paintOutpaint, size)
        : mode === 'paint' && paintMode !== 'sketch'
          ? await imageRequestSizeFromSource(paintImage, size)
          : size
      const requestSize = selectedModel.provider === 'comfyui' ? comfySafeGenerationSize(rawRequestSize) : rawRequestSize
      if (selectedModel.provider === 'comfyui' && !sameGenerationSize(rawRequestSize, requestSize)) {
        showToast(`ИЗО Base использует безопасный размер ${requestSize.width}×${requestSize.height}`)
      }
      const userText = mode === 'i2i' ? i2iPrompt : textPrompt
      // В обоих режимах пользователь видит финальный prompt в textarea:
      // text/i2i-стиль дописывается туда при выборе и может быть отредактирован.
      const rawFullPrompt = userText || (mode === 'i2i' ? style?.transformPrompt || '' : '')
      const fullPrompt = mode === 'i2i' && selectedModel.provider === 'comfyui'
        ? composeI2IEditPrompt(rawFullPrompt)
        : rawFullPrompt
      const isEditLikeMode = mode === 'edit'
      const activeEditSlots = requestEditSlots
      const paintCanvas = mode === 'paint' && paintMode === 'sketch' ? await createPaintSketchCanvas() : undefined
      const paintMask = mode === 'paint' && paintMode === 'mask' ? await createPaintMask(paintImage, paintLines, paintStageSize) : undefined
      const nextOutpaintPreview = mode === 'paint' && paintMode === 'outpaint' ? await createOutpaintPreview(paintImage, paintOutpaint, requestSize) : undefined
      const nextResultSource = mode === 'i2i' ? sourceImage : isEditLikeMode ? activeEditSlots[0]?.image : mode === 'paint' ? (paintMode === 'sketch' ? paintCanvas : nextOutpaintPreview || paintImage) : undefined
      const nextResultShape = shapeFromSize(requestSize.width, requestSize.height)
      if (mode === 'paint') setPaintOutpaintPreview(nextOutpaintPreview)
      const paintUserPrompt = prompts.paint.trim()
      const paintBasePrompt = paintTechPrompts[paintMode]
      const paintPrompt = composePaintPrompt(paintBasePrompt, paintUserPrompt)
      const editHasFaceReference = requestEditSlots.some((slot, index) => index > 0 && slot.image && slot.role === 'face')
      const editFaceStrengthInstruction = editHasFaceReference
        ? `\n\nFace reference control for Edit mode:\n${faceStrengthPrompt(editFaceStrengthPct)}\nUse this strength only for references whose role is FACE. Do not let the face reference change clothing, pose, body, background, style, or objects.`
        : ''
      const body = {
        mode: mode === 'i2i'
          ? 'image_to_image'
          : mode === 'edit'
              ? 'edit'
              : mode === 'paint'
                ? paintMode === 'sketch'
                  ? 'paint'
                  : paintMode === 'mask'
                    ? 'inpaint'
                    : paintMode === 'outpaint'
                      ? 'outpaint'
                      : 'remove_background'
                : 'text_to_image',
        provider: selectedModel.provider,
        prompt: mode === 'edit' ? `${editComposer.finalPrompt}${editFaceStrengthInstruction}` : mode === 'paint' ? paintPrompt : fullPrompt,
        negativePrompt: isEditLikeMode || mode === 'paint' ? '' : '',
        seed: effectiveSeed,
        width: requestSize.width,
        height: requestSize.height,
        resolutionId,
        steps,
        cfg: 1,
        guidance,
        strength: mode === 'edit' ? DEFAULT_EDIT_STRENGTH : strengthPct / 100,
        modelProfile: selectedModel.modelProfile,
        loras: mode === 'edit' && editHasFaceReference && faceLora
            ? [{ id: faceLora.id, strength: editFaceStrengthPct / 100, triggerWord: faceLora.triggerWord }]
            : [],
        inputImage1: mode === 'i2i' ? sourceImage : isEditLikeMode ? activeEditSlots[0]?.image : mode === 'paint' && paintMode !== 'sketch' ? paintImage : undefined,
        inputImages: mode === 'edit'
          ? activeEditSlots
              .map((slot, index) => ({ slot, index }))
              .filter(({ slot }) => slot.image)
              .map(({ slot, index }) => ({ index: index + 1, role: index === 0 ? 'base' : slot.role, image: slot.image! }))
          : undefined,
        maskImage: mode === 'paint' && paintMode === 'mask' ? paintMask : undefined,
        canvas: mode === 'paint' && paintMode === 'sketch' ? paintCanvas : undefined,
        outpaint: mode === 'paint' && paintMode === 'outpaint' ? outpaintPaddingOnly(paintOutpaint) : undefined,
        clientRequestId: newClientRequestId(),
      }
      const response = await apiFetch('/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!response.ok) {
        let detail: unknown = ''
        try {
          detail = (await response.json())?.detail || ''
        } catch {
          /* non-JSON */
        }
        if (response.status === 402) setNotice('Закончились токены. Пополните баланс в настройках основной версии.')
        else if (response.status === 401 || response.status === 403) {
          setNotice('Сессия истекла. Войдите снова, чтобы генерировать.')
          setAuthOpen(true)
        } else if (response.status === 429) setNotice(apiErrorText(detail, 'Слишком много запросов подряд. Подождите немного.'))
        else setNotice(apiErrorText(detail, `Сервер вернул ошибку (${response.status}). Попробуйте ещё раз.`))
        return
      }
      const created = normalizeGeneration(await response.json())
      if (!created) {
        setNotice('Сервер не подтвердил создание задачи. Токены не списываются без подтверждённой задачи.')
        return
      }
      if (mode === 'text') {
        lastTextSubmittedRef.current = { prompt: textPrompt, model: selectedModel.id, width: requestSize.width, height: requestSize.height }
      } else if (mode === 'i2i') {
        lastI2ISubmittedRef.current = { prompt: i2iPrompt, source: i2iSource, model: selectedModel.id, width: requestSize.width, height: requestSize.height }
      }
      if (mode === 'paint') setPaintWorkbenchVisible(false)
      pendingResultSourceRef.current[mode] = nextResultSource
      pendingResultShapeRef.current[mode] = nextResultShape
      setJob(created)
      setJobMode(mode)
      setHistoryVideoPreview(null)
      setResultUrl(undefined)
      setInspectPreview(null)
      if (mode !== 'paint') {
        setPreviewByMode((cur) => ({ ...cur, [mode]: { kind: 'empty' } }))
      }
      resetInspectView()
      setResultSource(nextResultSource)
      setCompare(mode === 'i2i' || isEditLikeMode || mode === 'paint' ? 96 : 50)
      if (!seed) setSeed(effectiveSeed)
    } catch {
      setNotice('Проблема соединения с сервером. Проверьте, что сервис запущен.')
    } finally {
      inFlightRef.current = false
      setIsSubmitting(false)
    }
  }

  function onSourceFile(file: File | undefined) {
    if (!file) return
    resizeUploadImage(file)
      .then((image) => {
        applyImageToTarget(uploadTarget, image)
        setUploadTarget(null)
      })
      .catch(() => {
    const reader = new FileReader()
    reader.onload = () => {
      if (typeof reader.result !== 'string') return
      applyImageToTarget(uploadTarget, reader.result)
      setUploadTarget(null)
    }
    reader.readAsDataURL(file)
      })
  }

  function setPromptInfluence(value: number) {
    const next = Math.max(0, Math.min(100, Math.round(value)))
    setStrengthPct(Math.abs(next - 75) <= 3 ? 75 : next)
  }

  function setEditFaceStrength(value: number) {
    const next = Math.max(0, Math.min(100, Math.round(value)))
    setEditFaceStrengthPct(Math.abs(next - DEFAULT_FACE_STRENGTH) <= 3 ? DEFAULT_FACE_STRENGTH : next)
  }

  function applyLastSourceImage() {
    const lastGalleryImage = gallery.find((item) => item.mediaType === 'image')
    const lastDockImage = dockImage?.mediaType === 'image' ? dockImage : undefined
    const lastHistoryImage = historyItems.find((item) => item.mediaType === 'image')
    const last = visibleResultUrl || lastGalleryImage?.url || lastDockImage?.url || lastHistoryImage?.url
    if (!last) {
      showToast('Последнего изображения пока нет')
      return
    }
    const image = apiUrl(last)
    setSourceImage(image)
    showInspectPreview(image, 'Исходное изображение')
  }

  function applyLastImageToTarget(target: UploadTarget) {
    const lastGalleryImage = gallery.find((item) => item.mediaType === 'image')
    const lastDockImage = dockImage?.mediaType === 'image' ? dockImage : undefined
    const lastHistoryImage = historyItems.find((item) => item.mediaType === 'image')
    const last = visibleResultUrl || lastGalleryImage?.url || lastDockImage?.url || lastHistoryImage?.url
    if (!last) {
      showToast('Последнего изображения пока нет')
      return
    }
    applyImageToTarget(target, apiUrl(last))
  }

  function useCurrentPreviewInPaint() {
    const source = visibleInspectPreview?.url || visibleResultUrl
    if (!source) {
      showToast('Сначала выберите изображение в предпросмотре')
      return
    }
    applyImageToTarget(paintMode === 'sketch' ? { kind: 'paintSketch' } : { kind: 'paint' }, apiUrl(source))
  }

  function resetInspectView() {
    setInspectZoom(1)
    setInspectPan({ x: 0, y: 0 })
  }

  function onInspectWheel(e: ReactWheelEvent<HTMLDivElement>) {
    e.preventDefault()
    const rect = e.currentTarget.getBoundingClientRect()
    const localX = e.clientX - rect.left - rect.width / 2
    const localY = e.clientY - rect.top - rect.height / 2
    setInspectZoom((current) => {
      const next = Math.max(0.46, Math.min(5, current * (e.deltaY < 0 ? 1.16 : 0.86)))
      const ratio = next / current
      setInspectPan((pan) => Math.abs(next - 1) <= 0.02
        ? { x: 0, y: 0 }
        : {
            x: localX - (localX - pan.x) * ratio,
            y: localY - (localY - pan.y) * ratio,
          })
      return next
    })
  }

  function onInspectPointerDown(e: ReactPointerEvent<HTMLDivElement>) {
    if (Math.abs(inspectZoom - 1) <= 0.02) return
    inspectDragRef.current = { active: true, startX: e.clientX, startY: e.clientY, panX: inspectPan.x, panY: inspectPan.y }
    e.currentTarget.setPointerCapture(e.pointerId)
  }

  function onInspectPointerMove(e: ReactPointerEvent<HTMLDivElement>) {
    const drag = inspectDragRef.current
    if (!drag.active) return
    setInspectPan({ x: drag.panX + e.clientX - drag.startX, y: drag.panY + e.clientY - drag.startY })
  }

  function onInspectPointerUp(e: ReactPointerEvent<HTMLDivElement>) {
    inspectDragRef.current.active = false
    if (e.currentTarget.hasPointerCapture(e.pointerId)) e.currentTarget.releasePointerCapture(e.pointerId)
  }

  function touchDistance(touches: ReactTouchEvent<HTMLDivElement>['touches']) {
    if (touches.length < 2) return 0
    const a = touches[0]
    const b = touches[1]
    return Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY)
  }

  function onInspectTouchStart(e: ReactTouchEvent<HTMLDivElement>) {
    const touch = inspectTouchRef.current
    if (e.touches.length === 2) {
      e.preventDefault()
      touch.pinching = true
      touch.distance = touchDistance(e.touches)
      touch.zoom = inspectZoom
      touch.panX = inspectPan.x
      touch.panY = inspectPan.y
      return
    }
    if (e.touches.length !== 1) return
    const now = e.timeStamp
    const first = e.touches[0]
    touch.startX = first.clientX
    touch.startY = first.clientY
    touch.panX = inspectPan.x
    touch.panY = inspectPan.y
    if (now - touch.lastTap < 280) {
      e.preventDefault()
      if (inspectZoom > 1.05) resetInspectView()
      else {
        setInspectZoom(2.2)
        setInspectPan({ x: 0, y: 0 })
      }
      touch.lastTap = 0
    } else {
      touch.lastTap = now
    }
  }

  function onInspectTouchMove(e: ReactTouchEvent<HTMLDivElement>) {
    const touch = inspectTouchRef.current
    if (e.touches.length === 2 && touch.pinching) {
      e.preventDefault()
      const distance = touchDistance(e.touches)
      if (!touch.distance || !distance) return
      setInspectZoom(Math.max(1, Math.min(5, touch.zoom * (distance / touch.distance))))
      return
    }
    if (e.touches.length === 1 && inspectZoom > 1.02) {
      e.preventDefault()
      const first = e.touches[0]
      setInspectPan({
        x: touch.panX + first.clientX - touch.startX,
        y: touch.panY + first.clientY - touch.startY,
      })
    }
  }

  function onInspectTouchEnd(e: ReactTouchEvent<HTMLDivElement>) {
    if (e.touches.length < 2) inspectTouchRef.current.pinching = false
    if (inspectZoom <= 1.02) setInspectPan({ x: 0, y: 0 })
  }

  const jobActive = !!job && JOB_ACTIVE.includes(job.status)
  useEffect(() => {
    if (!jobActive) return undefined
    const timer = window.setInterval(() => setProgressNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [jobActive])
  const rawJobProgress = Math.max(0, Math.min(100, Math.round(job?.progress || 0)))
  const jobStartedAt = job?.createdAt ? Date.parse(job.createdAt) : 0
  const jobElapsedSeconds = jobStartedAt ? Math.max(0, Math.floor((progressNow - jobStartedAt) / 1000)) : 0
  const estimatedOpenRouterProgress = job?.status === 'sent_to_openrouter'
    ? Math.min(92, Math.max(rawJobProgress, 24 + Math.floor(Math.min(68, Math.log1p(jobElapsedSeconds) * 18))))
    : rawJobProgress
  const jobProgress = Math.max(rawJobProgress, estimatedOpenRouterProgress)
  const jobProgressText = job?.status === 'sent_to_openrouter'
    ? `Ожидаем модель · ${jobProgress}%`
    : jobProgress > 0
      ? `Генерируем · ${jobProgress}%`
      : 'Генерируем…'

  const ownHistory = gallery.slice(0, 12)
  // Своя история приоритетна; при её отсутствии показываем работы из Ленты.
  const historyItems = ownHistory.length > 0 ? ownHistory : feedFallback
  const historyIsFeed = ownHistory.length === 0 && feedFallback.length > 0
  const selectedResolution = RESOLUTION_PRESETS.find((p) => p.id === resolutionId) || RESOLUTION_PRESETS[0]
  const studioMode: StudioMode = tab === 'i2i' ? 'i2i' : tab === 'edit' ? 'edit' : tab === 'paint' ? 'paint' : 'text'
  const isI2IStudio = studioMode === 'i2i'
  const isEditStudio = studioMode === 'edit'
  const isPaintStudio = studioMode === 'paint'
  const activeCoreMode = coreModeFromTab(tab)
  const activeCorePreview = activeCoreMode ? previewByMode[activeCoreMode] : null
  const visibleInspectPreview = isPaintStudio
    ? inspectPreview
    : activeCorePreview?.kind === 'inspect' && activeCorePreview.url
      ? { url: activeCorePreview.url, title: activeCorePreview.title || 'Предпросмотр' }
      : null
  const visibleResultUrl = isPaintStudio
    ? resultUrl
    : (activeCorePreview?.kind === 'result' || activeCorePreview?.kind === 'history') && activeCorePreview.url
      ? activeCorePreview.url
      : undefined
  const visibleResultSource = isPaintStudio ? resultSource : activeCorePreview?.kind === 'result' ? activeCorePreview.sourceUrl : undefined
  const visibleResultError = isPaintStudio ? resultError : !!activeCorePreview?.error
  const previewJobActive = jobActive && (isPaintStudio ? jobMode === 'paint' : jobMode === studioMode)
  useEffect(() => {
    if (!visibleResultUrl || !visibleResultSource || previewJobActive) return undefined
    compareTouchedRef.current = false
    queueMicrotask(() => {
      setInspectZoom(1)
      setInspectPan({ x: 0, y: 0 })
      setCompareAuto(true)
      setCompare(96)
    })
    const moveTimer = window.setTimeout(() => {
      if (!compareTouchedRef.current) setCompare(4)
    }, 120)
    const stopTimer = window.setTimeout(() => setCompareAuto(false), 2300)
    return () => {
      window.clearTimeout(moveTimer)
      window.clearTimeout(stopTimer)
    }
  }, [previewJobActive, visibleResultSource, visibleResultUrl])
  const studioTitle = isI2IStudio ? 'По фото' : isEditStudio ? 'Сборка' : isPaintStudio ? 'Редактор' : 'По тексту'
  const promptTitle = isI2IStudio ? 'Как преобразовать?' : isPaintStudio ? 'Что визуализируем?' : isEditStudio ? 'Дополнительные пожелания' : 'Что хотите увидеть?'
  const promptPlaceholder = isI2IStudio
    ? 'Опишите, как преобразовать исходное изображение...'
    : isPaintStudio
      ? paintMode === 'sketch'
        ? 'Опишите сцену, которую нужно получить из эскиза...'
        : paintMode === 'mask'
          ? 'Опишите, что должно появиться или измениться внутри маски...'
          : paintMode === 'outpaint'
            ? 'Опишите, что дорисовать в пустых краях кадра: фон, свет, детали, продолжение сцены...'
            : 'Опишите, что важно сохранить после удаления фона...'
    : isEditStudio
      ? 'Например: сохранить лицо, заменить одежду, взять фон или цвет из референса...'
    : 'Опишите идею своими словами — получите изображение...'
  const promptLimit = isI2IStudio || isEditStudio || isPaintStudio ? 1000 : 2000
  const promptValue = prompts[studioMode]
  const paintPromptDisplayValue = isPaintStudio && paintTechPromptOpen
    ? `${prompts.paint}${prompts.paint.trim() ? '\n\n' : ''}${paintTechPrompts[paintMode]}`
    : promptValue
  const promptTextareaValue = isPaintStudio ? paintPromptDisplayValue : promptValue
  const promptTextareaLimit = isPaintStudio && paintTechPromptOpen ? 2800 : promptLimit
  const promptCounterValue = promptTextareaValue.length

  function updatePromptTextarea(value: string) {
    if (isPaintStudio && paintTechPromptOpen) {
      const currentUserPrompt = prompts.paint
      if (!currentUserPrompt) {
        setPaintTechPrompts((cur) => ({ ...cur, [paintMode]: value }))
        return
      }
      if (value.startsWith(currentUserPrompt)) {
        setPaintTechPrompts((cur) => ({ ...cur, [paintMode]: value.slice(currentUserPrompt.length).replace(/^\n+/, '') }))
        return
      }
      const [nextUserPrompt = '', ...nextTechPrompt] = value.split(/\n{2,}/)
      setPrompt(nextUserPrompt)
      setPaintTechPrompts((cur) => ({ ...cur, [paintMode]: nextTechPrompt.join('\n\n') }))
      return
    }
    setPrompt(value)
  }

  async function improveCurrentPrompt() {
    const original = promptValue.trim()
    if (!original) {
      showToast('Сначала напишите, что нужно изобразить или изменить')
      return
    }
    if (!(await ensureAuthed())) return
    const improveMode = isPaintStudio ? paintMode : studioMode
    setPromptImproveBusy(true)
    try {
      const response = await apiFetch('/tools/improve-prompt', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          prompt: original,
          mode: improveMode,
          language: feedLang,
          technicalPrompt: isPaintStudio ? paintTechPrompts[paintMode] : '',
        }),
      })
      const payload = await response.json().catch(() => ({})) as { improvedPrompt?: string; detail?: unknown }
      if (!response.ok || !payload.improvedPrompt?.trim()) {
        throw new Error(apiErrorText(payload.detail, 'Не удалось улучшить промпт'))
      }
      const improved = payload.improvedPrompt.trim().slice(0, promptLimit)
      setPrompt(improved)
      setLastImprovedPrompt({ mode: studioMode, text: improved })
      showToast('Промпт улучшен')
    } catch (error) {
      showToast(error instanceof Error ? error.message : 'Не удалось улучшить промпт')
    } finally {
      setPromptImproveBusy(false)
    }
  }

  async function toggleVoiceInput() {
    if (voiceRecording) {
      voiceRecorderRef.current?.stop()
      return
    }
    if (!(await ensureAuthed())) return
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
      showToast('Этот браузер не поддерживает запись голоса')
      return
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const preferredType = ['audio/webm;codecs=opus', 'audio/ogg;codecs=opus', 'audio/webm'].find((type) => MediaRecorder.isTypeSupported(type)) || ''
      const recorder = new MediaRecorder(stream, preferredType ? { mimeType: preferredType } : undefined)
      const chunks: BlobPart[] = []
      recorder.ondataavailable = (event) => { if (event.data.size) chunks.push(event.data) }
      recorder.onerror = () => showToast('Не удалось записать голос')
      recorder.onstop = async () => {
        const durationMs = Math.max(0, Date.now() - voiceStartedAtRef.current)
        setVoiceRecording(false)
        voiceStreamRef.current?.getTracks().forEach((track) => track.stop())
        voiceStreamRef.current = null
        voiceRecorderRef.current = null
        if (durationMs < 1000) {
          showToast('Говорите не меньше 1 секунды')
          return
        }
        const blob = new Blob(chunks, { type: recorder.mimeType || 'audio/webm' })
        const form = new FormData()
        form.append('file', blob, `voice.${blob.type.includes('ogg') ? 'ogg' : 'webm'}`)
        setVoiceBusy(true)
        try {
          const response = await apiFetch(`/tools/transcribe?duration_ms=${durationMs}&language=${encodeURIComponent(feedLang)}`, { method: 'POST', body: form })
          const payload = await response.json().catch(() => ({})) as { text?: string; detail?: unknown }
          if (!response.ok || !payload.text?.trim()) throw new Error(apiErrorText(payload.detail, 'Не удалось распознать речь'))
          const spoken = payload.text.trim()
          setPrompt(`${promptValue.trim()}${promptValue.trim() ? ' ' : ''}${spoken}`.slice(0, promptLimit))
          showToast('Голос добавлен в промпт')
        } catch (error) {
          showToast(error instanceof Error ? error.message : 'Не удалось распознать речь')
        } finally {
          setVoiceBusy(false)
        }
      }
      voiceStreamRef.current = stream
      voiceRecorderRef.current = recorder
      voiceStartedAtRef.current = Date.now()
      recorder.start(250)
      setVoiceRecording(true)
      showToast('Говорите. Нажмите ещё раз, чтобы закончить')
    } catch {
      showToast('Разрешите доступ к микрофону в браузере')
    }
  }

  useEffect(() => () => {
    voiceRecorderRef.current?.stop()
    voiceStreamRef.current?.getTracks().forEach((track) => track.stop())
  }, [])

  useEffect(() => {
    if (tab !== 'paint' || !paintWorkbenchVisible) return undefined
    let observedNode: HTMLDivElement | null = null
    let frame = 0
    const timers: number[] = []
    const observer = new ResizeObserver(() => update())
    const update = () => {
      const node = paintWorkbenchRef.current
      if (!node) return
      const rect = node.getBoundingClientRect()
      if (rect.width < 160 || rect.height < 160) return
      const maxW = Math.max(256, rect.width - 36)
      const maxH = Math.max(256, rect.height - 36)
      const ratio = Math.max(0.1, selectedResolution.width / Math.max(1, selectedResolution.height))
      let width = maxW
      let height = width / ratio
      if (height > maxH) {
        height = maxH
        width = height * ratio
      }
      const next = { width: Math.max(1, Math.round(width)), height: Math.max(1, Math.round(height)) }
      setPaintStageSize((current) => current.width === next.width && current.height === next.height ? current : next)
    }
    const attach = () => {
      const node = paintWorkbenchRef.current
      if (!node) return
      if (observedNode !== node) {
        observer.disconnect()
        observer.observe(node)
        observedNode = node
      }
      update()
    }
    frame = window.requestAnimationFrame(attach)
    timers.push(window.setTimeout(attach, 80), window.setTimeout(attach, 240), window.setTimeout(attach, 600))
    window.addEventListener('resize', attach)
    return () => {
      window.cancelAnimationFrame(frame)
      timers.forEach((timer) => window.clearTimeout(timer))
      observer.disconnect()
      window.removeEventListener('resize', attach)
    }
  }, [paintMode, paintWorkbenchVisible, selectedResolution, tab])

  const loraOptions: LoraOption[] = (() => {
    const found = (modelsPayload?.loras || []).filter((item) => item && item !== 'none')
    if (!found.length) return FALLBACK_LORA_OPTIONS
    return [
      { id: 'none', label: 'None', triggerWord: '', strength: 0 },
      ...found.map((item) => ({
        id: item,
        label: item,
        triggerWord: loraTriggers[item] || '',
        strength: item.toLowerCase().includes('bfs') || item.toLowerCase().includes('face') || item.toLowerCase().includes('head') ? 1 : 0.8,
      })),
    ]
  })()
  const faceLora = (() => {
    const candidates = loraOptions.filter((item) => item.id !== 'none')
    return candidates.find((item) => /bfs|face|head/i.test(item.id)) || candidates[0]
  })()
  const currentModelMode = modelModeFromStudio(studioMode, paintMode)
  const currentModeAccess = modelAccess.modes[currentModelMode]
  const selectedQuality = (['fast', 'standard', 'max'].includes(quality) ? quality : 'fast') as QualityPreset
  const currentFormatPricingId = formatPricingId(selectedResolution)
  const modelFormats = (model: ModelOption) => {
    if (model.provider !== 'openrouter') return []
    return (openrouterPricing[model.id]?.formats || []).filter((fmt) => fmt.supported !== false)
  }
  const supportedFormatIdsForModel = (model: ModelOption) => {
    if (model.provider !== 'openrouter') return ['square', 'portrait', 'wide', 'soft_wide'] as PublicFormatId[]
    const supportedIds = new Set(model.supportedResolutionIds || [])
    const ids = RESOLUTION_PRESETS
      .filter((resolution) => supportedIds.has(resolution.id))
      .map((resolution) => formatPricingId(resolution))
    return Array.from(new Set(ids.length ? ids : ['square'])) as PublicFormatId[]
  }
  const pricingForModel = (model: ModelOption) => {
    if (model.provider !== 'openrouter') return undefined
    const resolutionPricing = openrouterPricing[model.id]?.resolutions?.find((item) => item.id === resolutionId)
    if (resolutionPricing) return resolutionPricing
    const formats = modelFormats(model)
    return formats.find((fmt) => fmt.id === currentFormatPricingId) || formats[0]
  }
  const tokenCostForModel = (model: ModelOption) => {
    const priced = pricingForModel(model)
    return typeof priced?.tokens === 'number' && priced.tokens > 0 ? priced.tokens : model.tokenHint
  }
  const formatSummaryForModel = (model: ModelOption) => {
    if (model.provider !== 'openrouter') return '1:1 · 9:16 · 16:9 · 3:2'
    const formats = openrouterPricing[model.id]?.formats || []
    const available = formats.filter((fmt) => fmt.supported !== false).map((fmt) => `${fmt.short} ${fmt.tokens ?? model.tokenHint}т`)
    return available.length ? available.join(' · ') : 'форматы уточняются'
  }
  const tariffResolutionIds = new Set(activeTariff.allowed_resolutions)
  const supportedResolutionIdsForModel = (model: ModelOption) => {
    const modelIds = new Set(model.supportedResolutionIds?.length ? model.supportedResolutionIds : RESOLUTION_PRESETS.map((item) => item.id))
    return RESOLUTION_PRESETS.filter((item) => modelIds.has(item.id) && (model.provider === 'openrouter' || tariffResolutionIds.has(item.id))).map((item) => item.id)
  }
  const preferredResolutionForModel = (model: ModelOption, formatId?: string) => {
    const allowed = supportedResolutionIdsForModel(model)
    const sameFormat = allowed.filter((id) => {
      const preset = RESOLUTION_PRESETS.find((item) => item.id === id)
      return preset && (!formatId || formatPricingId(preset) === formatId)
    })
    return sameFormat.includes(resolutionId) ? resolutionId : sameFormat[0] || allowed[0] || 'sq-sd'
  }
  const studioModelEnabled = (model: ModelOption, mode: ModelModeKey = currentModelMode) => isRasterOpenRouterModel(model) && (model.provider !== 'openrouter' || mode === 'text_to_image' || mode === 'image_to_image' || mode === 'edit')
  const accessibleStudioModelIds = new Set((currentModeAccess?.models || []).map((model) => model.id))
  const studioModelCatalog = Array.from(new Map(
    [...(currentModeAccess?.models || []), ...modelOptions].map((model) => [model.id, model]),
  ).values())
  const selectableStudioModels = studioModelCatalog
    .filter((model) => studioModelEnabled(model))
    .sort((a, b) => {
      if (studioModelSort === 'name-asc') return a.label.localeCompare(b.label, 'ru')
      if (studioModelSort === 'name-desc') return b.label.localeCompare(a.label, 'ru')
      if (studioModelSort === 'tokens-desc') return tokenCostForModel(b) - tokenCostForModel(a) || a.label.localeCompare(b.label, 'ru')
      return tokenCostForModel(a) - tokenCostForModel(b) || a.label.localeCompare(b.label, 'ru')
    })
  function selectStudioModel(model: ModelOption) {
    setProModelDetails((current) => ({ ...current, [currentModelMode]: model.id }))
    if (!accessibleStudioModelIds.has(model.id)) return
    const supported = supportedFormatIdsForModel(model)
    const supportedResolutions = supportedResolutionIdsForModel(model)
    if (!supported.includes(currentFormatPricingId) || !supportedResolutions.includes(resolutionId)) {
      const nextFormat = supported[0] || 'square'
      setResolutionId(preferredResolutionForModel(model, supported.includes(currentFormatPricingId) ? currentFormatPricingId : nextFormat))
      setFormatAutoNotice(`Формат изменен: ${formatName(nextFormat)}`)
    } else {
      setFormatAutoNotice('')
    }
    setProModelChoices((current) => ({
      ...current,
      [currentModelMode]: model.id,
    }))
  }
  function selectQualityPreset(nextQuality: QualityPreset) {
    const nextModel = studioSelectedModel(currentModelMode, nextQuality)
    const supported = supportedFormatIdsForModel(nextModel)
    const supportedResolutions = supportedResolutionIdsForModel(nextModel)
    if (!supported.includes(currentFormatPricingId) || !supportedResolutions.includes(resolutionId)) {
      const nextFormat = supported[0] || 'square'
      setResolutionId(preferredResolutionForModel(nextModel, supported.includes(currentFormatPricingId) ? currentFormatPricingId : nextFormat))
      setFormatAutoNotice(`Формат изменен: ${formatName(nextFormat)}`)
    } else {
      setFormatAutoNotice('')
    }
    setQuality(nextQuality)
  }
  function studioSelectedModel(mode: ModelModeKey, preset: QualityPreset) {
    const access = modelAccess.modes[mode]
    const models = (access?.models || []).filter((model) => userModelVisibility[mode]?.[model.id] !== false)
    const allowed = models.filter((model) => studioModelEnabled(model, mode))
    const chosen = userModelChoices[mode]?.[preset]
    const presetId = chosen && allowed.some((model) => model.id === chosen) ? chosen : access?.presets?.[preset]
    return allowed.find((model) => model.id === presetId) || allowed[0] || models[0] || modelAccessOption(modelAccess, mode, preset, userModelChoices)
  }
  function studioProSelectedModel(mode: ModelModeKey, preset: QualityPreset) {
    const access = modelAccess.modes[mode]
    const models = (access?.models || []).filter((model) => userModelVisibility[mode]?.[model.id] !== false)
    const allowed = models.filter((model) => studioModelEnabled(model, mode))
    const chosen = proModelChoices[mode]
    return (chosen ? allowed.find((model) => model.id === chosen) : undefined) || studioSelectedModel(mode, preset)
  }
  const currentStudioModel = effectiveProMode ? studioProSelectedModel(currentModelMode, selectedQuality) : studioSelectedModel(currentModelMode, selectedQuality)
  const inspectedStudioModel = selectableStudioModels.find((model) => model.id === proModelDetails[currentModelMode]) || currentStudioModel
  const inspectedStudioModelAvailable = accessibleStudioModelIds.has(inspectedStudioModel.id)
  const editReferenceLimit = currentStudioModel.provider === 'openrouter'
    ? Math.max(2, Math.min(EDIT_SLOT_COUNT, currentStudioModel.generation?.maxInputReferences || 2))
    : EDIT_SLOT_COUNT
  const currentStudioTokenCost = tokenCostForModel(currentStudioModel)
  const currentSupportedFormatIds = supportedFormatIdsForModel(currentStudioModel)
  const currentSupportedResolutionIds = supportedResolutionIdsForModel(currentStudioModel)
  const resolutionFormatAvailable = (formatId: PublicFormatId) => currentSupportedResolutionIds.some((id) => {
    const preset = RESOLUTION_PRESETS.find((item) => item.id === id)
    return preset && formatPricingId(preset) === formatId
  })
  const currentSupportedFormatsKey = currentSupportedFormatIds.join('|')
  const currentSupportedResolutionsKey = currentSupportedResolutionIds.join('|')
  useEffect(() => {
    const supported = currentSupportedFormatsKey.split('|').filter(Boolean) as PublicFormatId[]
    const supportedResolutions = currentSupportedResolutionsKey.split('|').filter(Boolean)
    if (supported.includes(currentFormatPricingId) && supportedResolutions.includes(resolutionId)) return
    const nextFormat = supported.includes(currentFormatPricingId) ? currentFormatPricingId : supported[0] || 'square'
    const matchingResolutions = supportedResolutions.filter((id) => {
      const preset = RESOLUTION_PRESETS.find((item) => item.id === id)
      return preset && formatPricingId(preset) === nextFormat
    })
    const nextResolutionId = matchingResolutions.includes(resolutionId)
      ? resolutionId
      : matchingResolutions[0] || supportedResolutions[0] || 'sq-sd'
    let cancelled = false
    queueMicrotask(() => {
      if (cancelled) return
      setResolutionId((current) => current === nextResolutionId ? current : nextResolutionId)
      setFormatAutoNotice(`Формат изменен: ${formatName(nextFormat)}`)
    })
    return () => { cancelled = true }
  }, [currentFormatPricingId, currentSupportedFormatsKey, currentSupportedResolutionsKey, resolutionId])
  const generateLabel = isI2IStudio ? 'Преобразовать' : isEditStudio ? 'Создать изображение' : isPaintStudio ? paintMode === 'remove_bg' ? 'Удалить фон' : paintMode === 'outpaint' ? 'Расширить' : 'Создать по рисунку' : 'Сгенерировать'
  const generatingLabel = isI2IStudio ? 'Преобразуем...' : isEditStudio ? 'Создаём...' : isPaintStudio ? 'Готовим рисунок...' : 'Генерируем...'
  const influenceStyle = { '--i2i-range-progress': `${strengthPct}%` } as CSSProperties
  const inspectImageStyle = {
    transform: `translate(${inspectPan.x}px, ${inspectPan.y}px) scale(${inspectZoom})`,
  } as CSSProperties
  const inspectToolsVisible = Math.abs(inspectZoom - 1) > 0.02
  const availableEditSlots = editSlots.slice(0, editReferenceLimit)
  const visibleEditSlots = editExtraOpen ? availableEditSlots : availableEditSlots.slice(0, 2)
  const editFilledCount = availableEditSlots.filter((slot) => slot.image).length
  const dockImage = dockImageId ? historyItems.find((g) => g.id === dockImageId) : gallery[0]
  const dockIsVideo = dockImage?.mediaType === 'video'
  const dockIsFeed = typeof dockImage?.id === 'string' && dockImage.id.startsWith('feed-')
  const visibleGalleryImage = visibleResultUrl
    ? gallery.find((item) => item.id === activeCorePreview?.galleryId || apiUrl(item.url) === apiUrl(visibleResultUrl) || apiUrl(item.thumbnailUrl) === apiUrl(visibleResultUrl))
    : undefined
  const visibleResultHasTransparency = visibleGalleryImage?.mode === 'remove_background'
  const visibleResultWidth = activeCorePreview?.width || visibleGalleryImage?.width
  const visibleResultHeight = activeCorePreview?.height || visibleGalleryImage?.height
  const visiblePreviewShape = isPaintStudio
    ? selectedResolution.kind === 'vertical'
      ? 'tall'
      : selectedResolution.kind === 'horizontal'
        ? 'wide'
        : 'square'
    : activeCorePreview?.shape
      ? activeCorePreview.shape
    : visibleGalleryImage
      ? historyShape(visibleGalleryImage)
      : selectedResolution.kind === 'vertical'
        ? 'tall'
        : selectedResolution.kind === 'horizontal'
          ? 'wide'
          : 'square'
  // Фон preview во время генерации: текущая работа/история/стиль как размытая
  // подложка; если ничего нет — брендовый placeholder (в CSS).
  const loadingBackdropUrl = hoverStyle
    ? hoverStyle.preview[previewGender]
    : dockImage && dockImage.mediaType !== 'video'
      ? apiUrl(dockImage.url)
      : gallery[0]
        ? apiUrl(gallery[0].url)
        : undefined

  // v3-студия: выбрать формат (соотношение сторон) — переключает на конкретный
  // базовый пресет, чтобы 16:9 и 3:2 не смешивались в один horizontal.
  const selectRatio = (format: 'square' | 'portrait' | 'wide' | 'soft_wide') => {
    if (!currentSupportedFormatIds.includes(format)) {
      setFormatAutoNotice(`${formatName(format)} не поддерживается выбранной моделью`)
      return
    }
    const presetId = preferredResolutionForModel(currentStudioModel, format)
    const preset = RESOLUTION_PRESETS.find((p) => p.id === presetId)
    if (preset) {
      setResolutionId(preset.id)
      setFormatAutoNotice('')
    }
  }

  // Формат-дропдаун: класс shape-иконки и локализованный тип разрешения.
  const ratioIconClass = (kind: 'square' | 'vertical' | 'horizontal', formatId?: string) =>
    kind === 'vertical' ? 'tall' : formatId === 'soft_wide' ? 'soft-wide' : kind === 'horizontal' ? 'wide' : ''

  // Закрытие формат-дропдауна по клику вне него.
  useEffect(() => {
    if (!formatOpen) return
    const onDoc = (e: MouseEvent) => {
      if (formatRef.current && !formatRef.current.contains(e.target as Node)) setFormatOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [formatOpen])

  const copyPrompt = (text: string) => {
    if (!text) return
    void navigator.clipboard?.writeText(text).then(() => {
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1400)
    })
  }

  const shareCurrentResult = async () => {
    if (!visibleResultUrl) {
      showToast('Сначала сгенерируйте изображение')
      return
    }
    const url = apiUrl(visibleResultUrl)
    try {
      const response = await fetch(url, { credentials: 'include' })
      if (!response.ok) throw new Error('Не удалось подготовить изображение')
      const blob = await response.blob()
      const extension = blob.type.includes('png') ? 'png' : blob.type.includes('webp') ? 'webp' : 'jpg'
      const file = new File([blob], `izo-asa-result.${extension}`, { type: blob.type || 'image/jpeg' })
      if (navigator.share && (!navigator.canShare || navigator.canShare({ files: [file] }))) {
        await navigator.share({ title: 'Изображение ИЗО АСА', text: promptValue.trim() || undefined, files: [file] })
      } else if (navigator.share) {
        await navigator.share({ title: 'Изображение ИЗО АСА', text: promptValue.trim() || undefined, url: new URL(url, window.location.origin).toString() })
      } else {
        await navigator.clipboard.writeText(new URL(url, window.location.origin).toString())
        showToast('Ссылка скопирована')
      }
    } catch (reason) {
      if (reason instanceof DOMException && reason.name === 'AbortError') return
      showToast('Не удалось поделиться изображением')
    } finally {
      setShareOpen(false)
    }
  }

  // Открыть миниатюру истории в предпросмотре + доке промпта.
  const openHistory = (item: N2GalleryImage) => {
    setResultError(false)
    setInspectPreview(null)
    resetInspectView()
    setDockImageId(item.id)
    if (item.mediaType === 'video') {
      setHistoryVideoPreview(item)
      if (isPaintStudio) setPaintWorkbenchVisible(false)
      return
    }
    setHistoryVideoPreview(null)
    const coreMode = coreModeFromTab(tab)
    if (coreMode) {
      setPreviewByMode((cur) => ({
        ...cur,
        [coreMode]: {
          kind: 'history',
          url: item.url,
          shape: historyShape(item),
          title: 'История',
          galleryId: item.id,
          promptOriginal: item.promptOriginal,
          error: false,
        },
      }))
    } else {
      setResultUrl(item.url)
      setResultSource(undefined)
    }
    if (isPaintStudio) setPaintWorkbenchVisible(false)
  }

  const scrollHistory = (dir: -1 | 1) => {
    const strip = historyStripRef.current
    if (strip) strip.scrollBy({ left: dir * Math.max(160, strip.clientWidth * 0.7), behavior: 'smooth' })
  }

  // Drag-скролл ленты истории мышью/тачем (как у ряда стилей). Клик после drag
  // не выбирает миниатюру; обычный клик — выбирает.
  useEffect(() => {
    const strip = historyStripRef.current
    if (!strip) return
    const st = { down: false, startX: 0, startScroll: 0 }
    const onWheel = (e: WheelEvent) => {
      if (strip.scrollWidth <= strip.clientWidth) return
      const d = Math.abs(e.deltaY) >= Math.abs(e.deltaX) ? e.deltaY : e.deltaX
      if (!d) return
      strip.scrollLeft += d
      e.preventDefault()
    }
    const onDown = (e: PointerEvent) => {
      st.down = true
      historyDraggedRef.current = false
      st.startX = e.clientX
      st.startScroll = strip.scrollLeft
    }
    const onMove = (e: PointerEvent) => {
      if (!st.down) return
      const dx = e.clientX - st.startX
      if (Math.abs(dx) > 4) {
        historyDraggedRef.current = true
        strip.classList.add('dragging')
      }
      strip.scrollLeft = st.startScroll - dx
    }
    const onUp = () => {
      st.down = false
      strip.classList.remove('dragging')
    }
    strip.addEventListener('wheel', onWheel, { passive: false })
    strip.addEventListener('pointerdown', onDown)
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
    return () => {
      strip.removeEventListener('wheel', onWheel)
      strip.removeEventListener('pointerdown', onDown)
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
    }
  }, [tab, historyItems.length])

  // Keep the prompt readable on every viewport, then fall back to inner scrolling.
  useEffect(() => {
    const ta = promptTextareaRef.current
    if (!ta) return
    ta.style.height = 'auto'
    const mobile = window.matchMedia('(max-width: 820px)').matches
    const max = Math.round(window.innerHeight * (mobile ? 0.34 : 0.45))
    ta.style.height = `${Math.min(ta.scrollHeight, max)}px`
  }, [prompts.text, prompts.i2i, prompts.edit, prompts.paint, tab])

  // Горизонтальный скролл ряда стилей: колесо мыши + drag (мышь/тач).
  // Если пользователь тянул ряд — клик по карточке не выбирает стиль (styleDraggedRef).
  useEffect(() => {
    const row = styleRowRef.current
    if (!row) return
    const st = { down: false, startX: 0, startScroll: 0 }
    const onWheel = (e: WheelEvent) => {
      if (row.scrollWidth <= row.clientWidth) return
      const d = Math.abs(e.deltaY) >= Math.abs(e.deltaX) ? e.deltaY : e.deltaX
      if (!d) return
      row.scrollLeft += d
      e.preventDefault()
    }
    const onDown = (e: PointerEvent) => {
      st.down = true
      stylePointerDownRef.current = true
      styleDraggedRef.current = false
      setHoverStyle(null) // на время взаимодействия убираем hover-preview
      st.startX = e.clientX
      st.startScroll = row.scrollLeft
    }
    const onMove = (e: PointerEvent) => {
      if (!st.down) return
      const dx = e.clientX - st.startX
      if (Math.abs(dx) > 4) {
        styleDraggedRef.current = true
        row.classList.add('dragging')
      }
      row.scrollLeft = st.startScroll - dx
    }
    const onUp = () => {
      st.down = false
      stylePointerDownRef.current = false
      row.classList.remove('dragging')
    }
    row.addEventListener('wheel', onWheel, { passive: false })
    row.addEventListener('pointerdown', onDown)
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
    return () => {
      row.removeEventListener('wheel', onWheel)
      row.removeEventListener('pointerdown', onDown)
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
    }
  }, [tab])

  // ————————————————————————————————————————————————————————————————
  // v3-студия: общий экран для «По тексту» и «По фото».
  // ————————————————————————————————————————————————————————————————
  // Промпт выбранного изображения; у ленты без промпта — честный fallback.
  const dockPromptText = dockImage
    ? dockImage.promptOriginal || (dockIsFeed ? 'Промпт недоступен' : '')
    : ''
  const shareTarget = visibleGalleryImage
  const previewNoticeText = notice || toastText
  const paintModeMeta: Record<PaintSubMode, { label: string; hint: string }> = {
    sketch: { label: 'Эскиз', hint: 'Нарисуйте идею на холсте. Модель превратит рисунок в изображение.' },
    mask: { label: 'Маска', hint: 'Загрузите изображение и закрасьте область, которую нужно изменить.' },
    outpaint: { label: 'Расширение', hint: 'Загрузите изображение и задайте поля для дорисовки.' },
    remove_bg: { label: 'Удалить фон', hint: 'Загрузите изображение. Результат вернётся с прозрачным фоном.' },
  }
  const paintReturnLabel: Record<PaintSubMode, string> = {
    sketch: 'К эскизу',
    mask: 'К маске',
    outpaint: 'К расширению',
    remove_bg: 'К удалению фона',
  }

  function choosePaintMode(id: PaintSubMode) {
    setPaintMode(id)
    setPaintToolsOpen(false)
    if (id === 'sketch') {
      setPaintTool('brush')
      setPaintBrushSize(3)
    } else if (id === 'mask') {
      setPaintTool('brush')
      setPaintDrawMode('free')
      setPaintBrushSize(25)
    }
    setPaintWorkbenchVisible(true)
    setResultError(false)
    setInspectPreview(null)
    resetInspectView()
    setPaintOutpaintPreview(undefined)
  }

  function updateOutpaintPadding(key: 'left' | 'right' | 'top' | 'bottom', value: number) {
    setPaintOutpaint((cur) => ({ ...outpaintPaddingOnly(cur), [key]: Math.max(0, value) }))
  }

  function markVisiblePreviewError(event: ChangeEvent<HTMLImageElement>) {
    void retryImageOnce(event.currentTarget, () => {
      if (isPaintStudio) {
        setResultError(true)
        return
      }
      if (!activeCoreMode) return
      setPreviewByMode((cur) => ({ ...cur, [activeCoreMode]: { ...cur[activeCoreMode], error: true } }))
    })
  }

  async function createPaintSketchCanvas() {
    const stageUrl = paintStageRef.current?.toDataURL()
    if (!paintSketchImage) return stageUrl
    const canvas = document.createElement('canvas')
    canvas.width = paintStageSize.width
    canvas.height = paintStageSize.height
    const ctx = canvas.getContext('2d')
    if (!ctx) return stageUrl || paintSketchImage
    ctx.fillStyle = paintCanvasBg === 'white' ? '#ffffff' : '#2b2f2c'
    ctx.fillRect(0, 0, canvas.width, canvas.height)
    const sketch = await loadHtmlImage(apiUrl(paintSketchImage))
    if (sketch) {
      const scale = Math.min(canvas.width / sketch.naturalWidth, canvas.height / sketch.naturalHeight)
      const width = sketch.naturalWidth * scale
      const height = sketch.naturalHeight * scale
      ctx.drawImage(sketch, (canvas.width - width) / 2, (canvas.height - height) / 2, width, height)
    }
    if (stageUrl) {
      const overlay = await loadHtmlImage(stageUrl)
      if (overlay) ctx.drawImage(overlay, 0, 0, canvas.width, canvas.height)
    }
    return canvas.toDataURL('image/png')
  }

  const paintWorkbench = (
    <Suspense fallback={<div ref={paintWorkbenchRef} className="paint-workbench paint-workbench-loading">Загружаем редактор рисунка...</div>}>
      <PaintWorkbench
        ref={paintStageRef}
        apiUrl={apiUrl}
        workbenchRef={paintWorkbenchRef}
        paintMode={paintMode}
        paintImage={paintImage}
        paintSketchImage={paintSketchImage}
        paintOutpaintPreview={paintOutpaintPreview}
        paintOutpaint={paintOutpaint}
        setPaintOutpaint={setPaintOutpaint}
        paintStageSize={paintStageSize}
        paintLines={paintLines}
        setPaintLines={setPaintLines}
        paintTool={paintTool}
        setPaintTool={setPaintTool}
        paintDrawMode={paintDrawMode}
        setPaintDrawMode={setPaintDrawMode}
        paintBrushSize={paintBrushSize}
        paintColor={paintColor}
        setPaintColor={setPaintColor}
        paintCanvasBg={paintCanvasBg}
        onUploadImage={() => openUpload(paintMode === 'sketch' ? { kind: 'paintSketch' } : { kind: 'paint' })}
        onPickGallery={() => openGalleryPick(paintMode === 'sketch' ? { kind: 'paintSketch' } : { kind: 'paint' })}
        onUseLastImage={() => applyLastImageToTarget(paintMode === 'sketch' ? { kind: 'paintSketch' } : { kind: 'paint' })}
        onRemoveImage={() => {
          if (paintMode === 'sketch') {
            setPaintSketchImage(undefined)
            setPaintSketchLines([])
          } else {
            setPaintImage(undefined)
            setPaintOutpaintPreview(undefined)
            setPaintMaskLines([])
          }
        }}
      />
    </Suspense>
  )

  const renderEditorSlot = (slot: EditSlot, index: number) => {
    const isBase = index === 0
    const target: UploadTarget = { kind: 'edit', index }
    const title = isBase ? 'Основа' : `Референс ${index}`
    const subtitle = isBase ? 'На что применяем изменения' : 'Что берём из изображения'
    return (
      <article className={`editor-slot editor-ref-card${slot.image ? ' is-filled' : ''}`} key={index}>
        <div className="editor-slot-title editor-ref-header">
          <div>
            <strong>{title}</strong>
            <span>{subtitle}</span>
          </div>
        </div>
        <article className={`i2i-upload-card editor-upload-card${slot.image ? ' is-filled' : ''}${isBase ? ' is-required' : ''}`}>
          {isBase && !slot.image && <span className="i2i-required-chip">Обязательно</span>}
          {slot.image && (
            <button className="i2i-remove" type="button" aria-label={`Удалить ${title.toLowerCase()}`} onClick={() => clearEditSlot(index)}>
              ×
            </button>
          )}
          <div className="i2i-preview">
            {slot.image ? (
              <button className="editor-preview-open" type="button" aria-label={`Показать ${title.toLowerCase()} в предпросмотре`} onClick={() => showInspectPreview(slot.image!, title)}>
                <img src={apiUrl(slot.image)} alt={title} />
              </button>
            ) : (
              <div className="i2i-upload-empty">
                <svg className="i2i-upload-icon" width="32" height="32" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                  <path d="M7 18.5h10a4 4 0 0 0 .6-7.96A6 6 0 0 0 6.4 8.7 4.8 4.8 0 0 0 7 18.5Z" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
                  <path d="M12 15V9.5m0 0-2.3 2.3M12 9.5l2.3 2.3" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
                <div className="i2i-upload-actions">
                  <button className="i2i-upload-action primary" type="button" onClick={() => openUpload(target)}>
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                      <path d="M12 16V6m0 0-4 4m4-4 4 4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                      <path d="M5 18.5h14" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                    </svg>
                    Загрузить
                  </button>
                  <button className="i2i-upload-action" type="button" onClick={() => openGalleryPick(target)}>
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                      <path d="M4 5h16v14H4V5Z" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
                      <path d="m7 15 3.2-3.2 2.4 2.4 2.2-2.7L20 17" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
                      <path d="M8.4 8.6h.1" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" />
                    </svg>
                    Галерея
                  </button>
                  <button className="i2i-upload-action" type="button" onClick={() => applyLastImageToTarget(target)}>
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                      <path d="M5 7v5h5" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" />
                      <path d="M5.6 12a6.6 6.6 0 1 0 1.9-4.7L5 9.8" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" />
                      <path d="M12 8.5V12l2.2 1.4" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                    Последнее
                  </button>
                </div>
              </div>
            )}
          </div>
          {!isBase && slot.image && (
            <div className={`editor-role-controls${slot.role === 'face' ? ' is-face-strength' : ''}`}>
              <label>
                <span>Что взять из картинки</span>
                <select
                  className="editor-role-select"
                  value={slot.role}
                  aria-label={`Роль для ${title.toLowerCase()}`}
                  onChange={(e) => setEditSlotRole(index, e.target.value as EditReferenceRole | '')}
                >
                  <option value="">Выберите роль</option>
                  {EDIT_SELECTABLE_REFERENCE_ROLES.map((role) => (
                    <option key={role} value={role} disabled={EDIT_DISABLED_REFERENCE_ROLES.includes(role)}>
                      {EDIT_REFERENCE_ROLE_LABELS[role]}
                    </option>
                  ))}
                </select>
              </label>
              {slot.role === 'other' && (
                <input
                  className="editor-role-note"
                  type="text"
                  maxLength={120}
                  placeholder="Например: материал, предмет, настроение..."
                  value={slot.takeNote || ''}
                  onChange={(e) => setEditSlotTakeNote(index, e.target.value)}
                />
              )}
              {slot.role === 'face' && (
                <div className="editor-face-strength" style={{ '--i2i-range-progress': `${editFaceStrengthPct}%` } as CSSProperties}>
                  <input
                    className="editor-face-range"
                    type="range"
                    min="0"
                    max="100"
                    step="1"
                    value={editFaceStrengthPct}
                    aria-label={`Сила переноса лица для ${title.toLowerCase()}`}
                    aria-valuetext={`${editFaceStrengthPct}%`}
                    onChange={(e) => setEditFaceStrength(Number(e.target.value))}
                  />
                  <button
                    className="editor-face-value"
                    type="button"
                    aria-label={`Сбросить силу лица до ${DEFAULT_FACE_STRENGTH}%`}
                    onClick={() => setEditFaceStrength(DEFAULT_FACE_STRENGTH)}
                  >
                    {editFaceStrengthPct}%
                  </button>
                </div>
              )}
            </div>
          )}
        </article>
      </article>
    )
  }

  const studio = (
    <main className="layout">
      <ResilientRegion region="studio-form" label="Панель настроек" fallbackClassName="sidebar" render={() => (
      <aside className="sidebar" data-studio-region="studio-form">
        <div className="sidebar-head">
          <h1>{studioTitle}</h1>
        </div>

        {isI2IStudio && (
          <section className="form-section i2i-source-section">
            <div className="section-title">
              <h2>Исходное изображение</h2>
              <span className={`i2i-source-status${sourceImage ? ' filled' : ' required'}`}>
                {sourceImage ? '1 изображение' : 'обязательно'}
              </span>
            </div>
            <div className="i2i-source-grid">
              <article className={`i2i-upload-card${sourceImage ? ' is-filled' : ''}`}>
                {!sourceImage && <span className="i2i-required-chip">Обязательно</span>}
                {sourceImage && (
                  <button className="i2i-remove" type="button" aria-label="Удалить исходное изображение" onClick={() => {
                    const removed = sourceImage
                    setSourceImage(undefined)
                    if (removed) setPreviewByMode((cur) => cur.i2i.url === removed || cur.i2i.sourceUrl === removed ? { ...cur, i2i: emptyPreview() } : cur)
                  }}>
                    ×
                  </button>
                )}
                <div className="i2i-preview">
                  {sourceImage ? (
                    <button
                      className="editor-preview-open i2i-preview-open"
                      type="button"
                      aria-label="Показать исходное изображение в предпросмотре"
                      onClick={() => showInspectPreview(sourceImage, 'Исходное изображение')}
                    >
                      <img src={apiUrl(sourceImage)} alt="Исходное изображение" />
                    </button>
                  ) : (
                    <div className="i2i-upload-empty">
                      <svg className="i2i-upload-icon" width="32" height="32" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                        <path d="M7 18.5h10a4 4 0 0 0 .6-7.96A6 6 0 0 0 6.4 8.7 4.8 4.8 0 0 0 7 18.5Z" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
                        <path d="M12 15V9.5m0 0-2.3 2.3M12 9.5l2.3 2.3" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
                      </svg>
                      <div className="i2i-upload-actions">
                        <button className="i2i-upload-action primary" type="button" onClick={() => openUpload({ kind: 'i2i' })}>
                          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                            <path d="M12 16V6m0 0-4 4m4-4 4 4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                            <path d="M5 18.5h14" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                          </svg>
                          Загрузить
                        </button>
                        <button className="i2i-upload-action" type="button" onClick={() => openGalleryPick({ kind: 'i2i' })}>
                          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                            <path d="M4 5h16v14H4V5Z" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
                            <path d="m7 15 3.2-3.2 2.4 2.4 2.2-2.7L20 17" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
                            <path d="M8.4 8.6h.1" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" />
                          </svg>
                          Галерея
                        </button>
                        <button className="i2i-upload-action" type="button" onClick={applyLastSourceImage}>
                          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                            <path d="M5 7v5h5" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" />
                            <path d="M5.6 12a6.6 6.6 0 1 0 1.9-4.7L5 9.8" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" />
                            <path d="M12 8.5V12l2.2 1.4" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" />
                          </svg>
                          Последнее
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              </article>

              <article className="i2i-influence-card">
                <div className="i2i-influence-head">
                  <h3>{currentStudioModel.provider === 'openrouter' ? 'Степень изменений' : 'Влияние промпта'}</h3>
                  <label className="i2i-strength-value">
                    <input
                      type="number"
                      min="0"
                      max="100"
                      step="1"
                      value={strengthPct}
                      aria-label="Значение влияния промпта в процентах"
                      onFocus={(e) => e.currentTarget.select()}
                      onChange={(e) => setPromptInfluence(Number(e.target.value))}
                    />
                    <span>%</span>
                  </label>
                </div>
                <div className="i2i-range-wrap" style={influenceStyle}>
                  <div className="i2i-range-scale" aria-hidden="true">
                    <span className="i2i-range-edge start">0</span>
                    <span className="i2i-range-edge end">100</span>
                  </div>
                  <button className="i2i-range-mark" type="button" onClick={() => setPromptInfluence(75)}>
                    75
                  </button>
                  <input
                    className="i2i-range"
                    type="range"
                    min="0"
                    max="100"
                    step="1"
                    value={strengthPct}
                    aria-label="Влияние промпта"
                    aria-valuetext={`${strengthPct}%`}
                    onChange={(e) => setPromptInfluence(Number(e.target.value))}
                  />
                </div>
                <div className="i2i-range-legend">
                  <span><span className="i2i-range-arrow">←</span> ближе к фото</span>
                  <span>больше промпта <span className="i2i-range-arrow">→</span></span>
                </div>
                <p>{currentStudioModel.provider === 'openrouter'
                  ? 'Рекомендуем 75%. Для API-модели это смысловая инструкция: ниже точнее сохраняет фото, выше свободнее следует описанию.'
                  : 'Рекомендуем 75%. Ниже сохраняет исходник, выше сильнее следует описанию.'}</p>
              </article>
            </div>
          </section>
        )}

        {isEditStudio && (
          <section className="form-section i2i-source-section editor-source-section">
            <div className="section-title">
              <h2>Изображения</h2>
              <span className={`i2i-source-status${editSlots[0]?.image ? ' filled' : ' required'}`}>
                {editFilledCount} из {editReferenceLimit}
              </span>
            </div>
            <div className="editor-source-grid">
              {visibleEditSlots.map(renderEditorSlot)}
            </div>
            {editReferenceLimit > 2 && (
              <button className="editor-extra-toggle" type="button" onClick={() => setEditExtraOpen((open) => !open)}>
                {editExtraOpen ? 'Скрыть референсы' : `Еще референсы · до ${editReferenceLimit}`}
              </button>
            )}
          </section>
        )}

        {isPaintStudio && (
          <section className="form-section paint-panel-section">
            <div className="section-title">
              <h2>Режим рисунка</h2>
              <span>{paintModeMeta[paintMode].label}</span>
            </div>
            <label className="paint-mode-select">
              <span>Режим</span>
              <select value={paintMode} onChange={(e) => choosePaintMode(e.target.value as PaintSubMode)}>
                {(Object.keys(paintModeMeta) as PaintSubMode[]).map((id) => (
                  <option value={id} key={id}>{paintModeMeta[id].label}</option>
                ))}
              </select>
            </label>
            <div className="paint-mode-tabs" role="tablist" aria-label="Режимы рисунка">
              {(Object.keys(paintModeMeta) as PaintSubMode[]).map((id) => (
                <button
                  key={id}
                  className={paintMode === id ? 'active' : ''}
                  type="button"
                  onClick={() => choosePaintMode(id)}
                >
                  <span className="paint-tab-label">{paintModeMeta[id].label}</span>
                  <span className="paint-tab-state">
                    {id === 'sketch'
                      ? paintSketchLines.length ? 'есть эскиз' : 'пусто'
                      : id === 'mask'
                        ? paintMaskLines.length ? 'есть маска' : 'пусто'
                        : id === 'outpaint'
                          ? paintImage ? 'изображение' : 'пусто'
                          : paintImage ? 'готово' : 'пусто'}
                  </span>
                  <span className="paint-tab-indicator" aria-hidden="true"></span>
                </button>
              ))}
            </div>
            <div className={`paint-mode-panel mode-${paintMode}`}>
              <div className="paint-panel-head">
                <strong>{paintModeMeta[paintMode].label}</strong>
                <span>{paintModeMeta[paintMode].hint}</span>
              </div>

              {(paintMode === 'sketch' || paintMode === 'mask') && (
                <div className="paint-toolbox">
                  <button
                    className={`paint-tools-toggle${paintToolsOpen ? ' active' : ''}`}
                    type="button"
                    aria-expanded={paintToolsOpen}
                    onClick={() => setPaintToolsOpen((open) => !open)}
                  >
                    <SlidersHorizontal size={17} strokeWidth={2.2} aria-hidden="true" />
                    <span>{paintMode === 'sketch' ? 'Инструменты эскиза' : 'Инструменты маски'}</span>
                    <ChevronDown size={17} strokeWidth={2.2} aria-hidden="true" />
                  </button>
                  <div className={`paint-tools-body${paintToolsOpen ? ' is-open' : ''}`}>
                    <div className="paint-sidebar-tools" aria-label="Инструменты рисования">
                      <button className={`paint-tool-brush${paintTool === 'brush' && paintDrawMode === 'free' ? ' active' : ''}`} type="button" title="Кисть" aria-label="Кисть" onClick={() => { setPaintTool('brush'); setPaintDrawMode('free') }}><Brush size={18} strokeWidth={2.2} /></button>
                      {paintMode === 'sketch' && (
                        <label className="paint-tool-color paint-mobile-color" title="Цвет кисти" aria-label="Цвет кисти">
                          <span className="paint-color-dot inline" style={{ '--paint-color': paintColor } as CSSProperties}><Palette size={14} strokeWidth={2.2} aria-hidden="true" /><input type="color" value={paintColor} onChange={(e) => setPaintColor(e.target.value)} /></span>
                        </label>
                      )}
                      <button className={`paint-tool-eraser${paintTool === 'eraser' ? ' active' : ''}`} type="button" title="Ластик" aria-label="Ластик" onClick={() => { setPaintTool('eraser'); setPaintDrawMode('free') }}><Eraser size={18} strokeWidth={2.2} /></button>
                      {paintMode === 'sketch' && (
                        <>
                          <button className={`paint-tool-line${paintDrawMode === 'line' ? ' active' : ''}`} type="button" title="Линия" aria-label="Линия" onClick={() => { setPaintTool('brush'); setPaintDrawMode('line') }}><Slash size={19} strokeWidth={2.6} /></button>
                          <button className={`paint-tool-rect-fill${paintDrawMode === 'rect-fill' ? ' active' : ''}`} type="button" title="Залитый прямоугольник" aria-label="Залитый прямоугольник" onClick={() => { setPaintTool('brush'); setPaintDrawMode('rect-fill') }}><span className="paint-shape-icon rect filled" /></button>
                          <button className={`paint-tool-rect-outline${paintDrawMode === 'rect-outline' ? ' active' : ''}`} type="button" title="Контурный прямоугольник" aria-label="Контурный прямоугольник" onClick={() => { setPaintTool('brush'); setPaintDrawMode('rect-outline') }}><span className="paint-shape-icon rect outline" /></button>
                          <button className={`paint-tool-circle-fill${paintDrawMode === 'circle-fill' ? ' active' : ''}`} type="button" title="Залитый круг" aria-label="Залитый круг" onClick={() => { setPaintTool('brush'); setPaintDrawMode('circle-fill') }}><span className="paint-shape-icon circle filled" /></button>
                          <button className={`paint-tool-circle-outline${paintDrawMode === 'circle-outline' ? ' active' : ''}`} type="button" title="Контурный круг" aria-label="Контурный круг" onClick={() => { setPaintTool('brush'); setPaintDrawMode('circle-outline') }}><span className="paint-shape-icon circle outline" /></button>
                          <button className={`paint-tool-bucket${paintDrawMode === 'bucket' ? ' active' : ''}`} type="button" title="Заливка области" aria-label="Заливка области" onClick={() => { setPaintTool('brush'); setPaintDrawMode('bucket') }}><PaintBucket size={18} strokeWidth={2.2} /></button>
                        </>
                      )}
                    </div>
                    <label className="paint-control"><span className="paint-control-label">Размер</span><input type="range" min="1" max="64" value={paintBrushSize} onChange={(e) => setPaintBrushSize(Number(e.target.value))} /><span>{paintBrushSize}</span></label>
                    {paintMode === 'sketch' && (
                      <div className="paint-segment paint-icon-segment">
                        <button className={paintCanvasBg === 'white' ? 'active' : ''} type="button" title="Белый холст" onClick={() => setPaintCanvasBg('white')}><Sun size={16} strokeWidth={2.2} /><span>Белый холст</span></button>
                        <button className={paintCanvasBg === 'gray' ? 'active' : ''} type="button" title="Серый холст" onClick={() => setPaintCanvasBg('gray')}><Moon size={16} strokeWidth={2.2} /><span>Серый холст</span></button>
                      </div>
                    )}
                  </div>
                </div>
              )}

              {paintMode === 'outpaint' && (
                <div className="paint-toolbox">
                  <button
                    className={`paint-tools-toggle${paintToolsOpen ? ' active' : ''}`}
                    type="button"
                    aria-expanded={paintToolsOpen}
                    onClick={() => setPaintToolsOpen((open) => !open)}
                  >
                    <SlidersHorizontal size={17} strokeWidth={2.2} aria-hidden="true" />
                    <span>Поля расширения</span>
                    <ChevronDown size={17} strokeWidth={2.2} aria-hidden="true" />
                  </button>
                  <div className={`paint-tools-body${paintToolsOpen ? ' is-open' : ''}`}>
                    {(['left', 'right', 'top', 'bottom'] as const).map((key) => (
                      <label className="paint-control" key={key}>
                        <span className="paint-control-label">
                          {key === 'left' ? <ArrowLeft size={13} strokeWidth={2.4} /> : key === 'right' ? <ArrowRight size={13} strokeWidth={2.4} /> : key === 'top' ? <ArrowUp size={13} strokeWidth={2.4} /> : <ArrowDown size={13} strokeWidth={2.4} />}
                          {key === 'left' ? 'Слева' : key === 'right' ? 'Справа' : key === 'top' ? 'Сверху' : 'Снизу'}
                        </span>
                        <input type="range" min="0" max="768" step="16" value={paintOutpaint[key]} onChange={(e) => updateOutpaintPadding(key, Number(e.target.value))} />
                        <span>{paintOutpaint[key]}</span>
                      </label>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </section>
        )}

        <section className={`form-section prompt-section${isEditStudio || isPaintStudio ? ' editor-prompt-section' : ''}`}>
          <div className="section-title">
            <h2>{promptTitle}</h2>
            <div className="prompt-title-meta">
              {isPaintStudio && (
                <label className="paint-tech-toggle">
                  <input type="checkbox" checked={paintTechPromptOpen} onChange={(e) => setPaintTechPromptOpen(e.target.checked)} />
                  <span>Технический промпт</span>
                </label>
              )}
              <span className="help-dot" role="button" tabIndex={0} onClick={() => setHelpOpen(true)}>?</span>
            </div>
          </div>
          <div className={`prompt-card paint-prompt-card${isPaintStudio && paintTechPromptOpen ? ' is-tech-open' : ''}`}>
            <textarea
              ref={promptTextareaRef}
              placeholder={promptPlaceholder}
              maxLength={promptTextareaLimit}
              value={promptTextareaValue}
              onChange={(e) => updatePromptTextarea(e.target.value)}
            />
            <span className="prompt-inline-counter" aria-hidden="true">
              {promptCounterValue} / {promptTextareaLimit}
            </span>
            {promptTextareaValue.length > 0 && (
              <>
                <span className="prompt-clear-mark" aria-hidden="true">
                  <X size={14} strokeWidth={2.2} />
                </span>
                <button
                  className="prompt-clear-button"
                  type="button"
                  title="Очистить промпт"
                  aria-label="Очистить промпт"
                  onClick={() => {
                    updatePromptTextarea('')
                    promptTextareaRef.current?.focus()
                  }}
                />
              </>
            )}
          </div>
          <div className="action-row">
            <button className={`tool-button${voiceRecording ? ' voice-recording' : ''}`} type="button" disabled={voiceBusy} aria-pressed={voiceRecording} onClick={() => void toggleVoiceInput()}>
              {voiceRecording && <span className="voice-recording-dot" aria-hidden="true" />}
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <path d="M12 14a3 3 0 0 0 3-3V6a3 3 0 0 0-6 0v5a3 3 0 0 0 3 3Z" stroke="currentColor" strokeWidth="2" />
                <path d="M19 11a7 7 0 0 1-14 0M12 18v4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
              </svg>
              {voiceBusy ? 'Распознаю…' : voiceRecording ? 'Стоп' : 'Голос'}
            </button>
            <button className="tool-button primary" type="button" disabled={promptImproveBusy || (lastImprovedPrompt?.mode === studioMode && lastImprovedPrompt.text === promptValue)} onClick={() => void improveCurrentPrompt()}>
              <svg width="17" height="17" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <path d="M12 3.5l1.6 4 4 1.6-4 1.6-1.6 4-1.6-4-4-1.6 4-1.6L12 3.5Z" fill="currentColor" />
                <path d="M18.5 14.5l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8.8-2Z" fill="currentColor" opacity=".72" />
              </svg>
              {promptImproveBusy ? 'Улучшаю…' : lastImprovedPrompt?.mode === studioMode && lastImprovedPrompt.text === promptValue ? 'Улучшено' : 'Улучшить'}
            </button>
            {!isEditStudio && !isPaintStudio && (
              <>
                <button className="tool-button" type="button" onClick={() => setTemplatesOpen(true)}>
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                    <path d="M4 4h6v6H4V4Zm10 0h6v6h-6V4ZM4 14h6v6H4v-6Zm10 0h6v6h-6v-6Z" stroke="currentColor" strokeWidth="1.8" />
                  </svg>
                  Шаблоны
                </button>
                <button className="tool-button" type="button" onClick={randomPrompt}>
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                    <path d="M9 18h6M10 22h4M8.4 14.4A6 6 0 1 1 15.6 14c-.9.7-1.6 1.7-1.8 2.8h-3.6c-.2-1-.8-1.8-1.8-2.4Z" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                  Идея
                </button>
              </>
            )}
          </div>
        </section>

        {!isEditStudio && !isPaintStudio && <section className="form-section style-section">
          <div className="section-title">
            <h2>Стиль</h2>
            <span>{I2I_STYLES.length} стилей</span>
          </div>
          <div className="style-row" ref={styleRowRef}>
            <figure
              className={`style-card no-style${!styleId ? ' active' : ''}`}
              role="button"
              tabIndex={0}
              onClick={() => { if (styleDraggedRef.current) { styleDraggedRef.current = false; return } applyStyle(null) }}
            >
              <span className="no-style-symbol">✓</span>
              <figcaption>Нет</figcaption>
            </figure>
            {I2I_STYLES.map((style) => (
              <figure
                key={style.id}
                className={`style-card${styleId === style.id ? ' active' : ''}`}
                role="button"
                tabIndex={0}
                title={style.name}
                onClick={() => { if (styleDraggedRef.current) { styleDraggedRef.current = false; return } applyStyle(style) }}
                onMouseEnter={() => { if (!stylePointerDownRef.current) setHoverStyle(style) }}
                onMouseLeave={() => setHoverStyle(null)}
              >
                <img src={style.preview[previewGender]} alt={style.preview.alt} loading="lazy" />
                <figcaption>{styleShortLabel(style, feedLang)}</figcaption>
              </figure>
            ))}
          </div>
        </section>}

        <section className="form-section format-section">
          <div className="section-title">
            <h2>Формат</h2>
          </div>
          <div className="control-row">
            <div className={`iv3-format-select${formatOpen ? ' open' : ''}`} ref={formatRef}>
              <button
                type="button"
                className="resolution iv3-format-trigger"
                aria-haspopup="listbox"
                aria-expanded={formatOpen}
                aria-label="Разрешение"
                onClick={() => setFormatOpen((o) => !o)}
              >
                <span className="iv3-format-res">{selectedResolution.width}×{selectedResolution.height}</span>
                <svg className="iv3-format-caret" width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                  <path d="m7 9 5 5 5-5" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </button>
              {formatOpen && (
                <div className="iv3-format-menu" role="listbox">
                  {RESOLUTION_PRESETS.map((p) => (
                    <button
                      key={p.id}
                      type="button"
                      role="option"
                      aria-selected={p.id === resolutionId}
                      disabled={!currentSupportedFormatIds.includes(formatPricingId(p)) || !currentSupportedResolutionIds.includes(p.id)}
                      className={`iv3-format-option${p.id === resolutionId ? ' active' : ''}`}
                      onClick={() => { setResolutionId(p.id); setFormatAutoNotice(''); setFormatOpen(false) }}
                    >
                      <span className={`ratio-icon ${ratioIconClass(p.kind, formatPricingId(p))}`.trim()} aria-hidden="true"></span>
                      <span className="iv3-format-res">{p.width}×{p.height}</span>
                      <span className="iv3-format-type">{p.quality}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>
            <button className={`ratio-button${currentFormatPricingId === 'square' ? ' active' : ''}`} type="button" disabled={!currentSupportedFormatIds.includes('square') || !resolutionFormatAvailable('square')} onClick={() => selectRatio('square')}>
              <span className="ratio-icon"></span>1:1
            </button>
            <button className={`ratio-button${currentFormatPricingId === 'portrait' ? ' active' : ''}`} type="button" disabled={!currentSupportedFormatIds.includes('portrait') || !resolutionFormatAvailable('portrait')} onClick={() => selectRatio('portrait')}>
              <span className="ratio-icon tall"></span>9:16
            </button>
            <button className={`ratio-button${currentFormatPricingId === 'wide' ? ' active' : ''}`} type="button" disabled={!currentSupportedFormatIds.includes('wide') || !resolutionFormatAvailable('wide')} onClick={() => selectRatio('wide')}>
              <span className="ratio-icon wide"></span>16:9
            </button>
            <button className={`ratio-button${currentFormatPricingId === 'soft_wide' ? ' active' : ''}`} type="button" disabled={!currentSupportedFormatIds.includes('soft_wide') || !resolutionFormatAvailable('soft_wide')} onClick={() => selectRatio('soft_wide')}>
              <span className="ratio-icon soft-wide"></span>3:2
            </button>
          </div>
          {formatAutoNotice && <div className="format-auto-note">{formatAutoNotice}</div>}
        </section>

        <section className="form-section quality-section">
          <div className="section-title studio-model-title">
            <div className="studio-model-heading">
              <h2>Качество</h2>
              {effectiveProMode && <span>{currentModeAccess?.label || studioTitle}</span>}
            </div>
            <button
              className={`pro-button quality-pro-toggle${effectiveProMode ? ' active' : ''}`}
              type="button"
              aria-pressed={effectiveProMode}
              onClick={() => setProMode((value) => !value)}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <path d="m4 19 1.4-11 4.4 4.4L12 5l2.2 7.4L18.6 8 20 19H4Z" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
              </svg>
              {effectiveProMode ? 'Простой режим' : 'Режим Профи'}
            </button>
          </div>
          {!effectiveProMode ? (
            <div className="quality-row">
              {QUALITY.map((q) => {
                const qualityId = q.id as QualityPreset
                const qualityModel = studioSelectedModel(currentModelMode, qualityId)
                const qualityTokens = tokenCostForModel(qualityModel)
                return (
                  <button
                    key={q.id}
                    className={`quality-button${quality === q.id ? ' active' : ''}`}
                    type="button"
                    onClick={() => selectQualityPreset(qualityId)}
                  >
                    <span className="quality-label">{q.label}</span>
                    <span className="quality-model-name">{qualityModel.label}</span>
                    <span className="quality-token-cost">{qualityTokens} ток.</span>
                  </button>
                )
              })}
            </div>
          ) : (
            <>
            <div className="studio-selected-model">
              <div className="studio-selected-head">
                <strong>{inspectedStudioModel.label}</strong>
                <span className="studio-selected-specs">
                  <b>{modelPublicInfo(inspectedStudioModel).company}</b>
                  <em>{modelPublicInfo(inspectedStudioModel).year}</em>
                  <em>{pricingForModel(inspectedStudioModel)?.requestSize || `${selectedResolution.width}×${selectedResolution.height}`}</em>
                  {isEditStudio && <em>до {editReferenceLimit} изображений</em>}
                  {!inspectedStudioModelAvailable && <em className="studio-model-unavailable">Недоступна на вашем тарифе</em>}
                </span>
              </div>
              <p>{modelPublicInfo(inspectedStudioModel).description}</p>
              <div className="studio-model-formats" aria-label="Стоимость по форматам">
                {inspectedStudioModel.provider === 'openrouter'
                  ? (openrouterPricing[inspectedStudioModel.id]?.formats || []).map((fmt) => (
                    <span key={fmt.id} className={`${fmt.id === currentFormatPricingId ? 'active' : ''}${fmt.supported === false ? ' disabled' : ''}`.trim()}>{fmt.short}: {fmt.supported === false ? 'нет' : `${fmt.tokens ?? inspectedStudioModel.tokenHint}т`}</span>
                  ))
                  : ['1:1', '9:16', '16:9', '3:2'].map((fmt) => <span key={fmt} className={fmt === formatName(currentFormatPricingId) ? 'active' : ''}>{fmt}: {inspectedStudioModel.tokenHint}т</span>)}
              </div>
            </div>
            <div className="studio-model-sort" aria-label="Сортировка моделей">
              <span>Сортировка</span>
              <button type="button" className={studioModelSort.startsWith('name') ? 'active' : ''} onClick={() => setStudioModelSort((cur) => cur === 'name-asc' ? 'name-desc' : 'name-asc')}>Имя {studioModelSort === 'name-desc' ? '↓' : '↑'}</button>
              <button type="button" className={studioModelSort.startsWith('tokens') ? 'active' : ''} onClick={() => setStudioModelSort((cur) => cur === 'tokens-asc' ? 'tokens-desc' : 'tokens-asc')}>Токены {studioModelSort === 'tokens-desc' ? '↓' : '↑'}</button>
            </div>
            <div className="studio-model-list" role="listbox" aria-label={`Модели для ${currentModeAccess?.label || studioTitle}`}>
              {selectableStudioModels.map((model) => {
                const active = currentStudioModel.id === model.id
                const available = accessibleStudioModelIds.has(model.id)
                const info = modelPublicInfo(model)
                return (
                  <button
                    type="button"
                    key={`${currentModelMode}-${model.id}`}
                    className={`studio-model-row${active ? ' active' : ''}${available ? '' : ' unavailable'}`}
                    onClick={() => selectStudioModel(model)}
                    aria-selected={active}
                    title={available ? 'Выбрать модель' : 'Посмотреть описание модели'}
                    role="option"
                  >
                    <span className="studio-model-main"><strong>{model.label}</strong><small>{info.strengths.slice(0, 2).join(' · ')}</small></span>
                    <span className="studio-model-cost"><b>{available ? `${tokenCostForModel(model)} ток.` : 'Недоступна'}</b><small>{formatSummaryForModel(model)}</small></span>
                  </button>
                )
              })}
            </div>
            </>
          )}
        </section>

        {notice && <div className="iv3-notice" role="alert">{notice}</div>}

        <button className={`generate-button${isSubmitting || jobActive ? ' is-generating' : ''}`} type="button" disabled={isSubmitting || jobActive} onClick={() => generate(studioMode)}>
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path d="M12 3.5l1.9 4.8 4.8 1.9-4.8 1.9-1.9 4.9-1.9-4.9-4.8-1.9 4.8-1.9L12 3.5Z" fill="currentColor" />
          </svg>
          {jobActive || isSubmitting ? generatingLabel : <>{generateLabel}<span className="generate-token-cost">{currentStudioTokenCost} ток.</span></>}
        </button>
      </aside>
      )} />

      <section className="preview-panel">
        <div className="mobile-title-row">
          <h1>{studioTitle}</h1>
          {isPaintStudio && paintWorkbenchVisible && (paintMode === 'sketch' || paintMode === 'mask') && (
            <div className="paint-mobile-history-actions" aria-label="Действия рисунка">
              <button type="button" onClick={() => setPaintLines((lines) => lines.slice(0, -1))}><Undo2 size={13} strokeWidth={2.2} />Назад</button>
              <button type="button" onClick={() => setPaintLines([])}><Trash2 size={13} strokeWidth={2.2} />Очистить</button>
            </div>
          )}
          {isPaintStudio && !paintWorkbenchVisible && !previewJobActive && (
            <div className="paint-preview-actions">
              <button
                className="paint-return-workbench"
                type="button"
                onClick={() => {
                  setPaintWorkbenchVisible(true)
                  setResultError(false)
                  setInspectPreview(null)
                  resetInspectView()
                }}
              >
                {paintReturnLabel[paintMode]}
              </button>
              {(visibleInspectPreview?.url || visibleResultUrl) && (
                <button className="paint-use-preview" type="button" onClick={useCurrentPreviewInPaint}>
                  Взять это
                </button>
              )}
            </div>
          )}
        </div>
        <ResilientRegion region="preview" label="Предпросмотр" fallbackClassName={`preview-image preview-shape-${visiblePreviewShape}`} render={() => (
        <div className={`preview-image preview-shape-${visiblePreviewShape}`} data-studio-region="preview">
          {isPaintStudio && paintWorkbenchVisible && !hoverStyle && !previewJobActive ? (
            paintWorkbench
          ) : hoverStyle ? (
            <>
              <img className="iv3-preview-backdrop" src={hoverStyle.preview[previewGender]} alt="" aria-hidden="true" />
              <img className="iv3-preview-main" src={hoverStyle.preview[previewGender]} alt={hoverStyle.preview.alt} />
              <span className="iv3-style-hover-badge">Превью стиля · {styleShortLabel(hoverStyle, feedLang)}</span>
            </>
          ) : previewJobActive ? (
            <div className={`iv3-preview-loading${loadingBackdropUrl ? ' has-bg' : ''}`}>
              {loadingBackdropUrl && <img className="iv3-preview-backdrop" src={loadingBackdropUrl} alt="" aria-hidden="true" />}
              <div className="iv3-loading-shimmer" aria-hidden="true"></div>
              <div className="iv3-loading-inner">
                <span className="iv3-spinner" aria-hidden="true"></span>
                <span className="iv3-loading-text">{jobProgressText}</span>
                <div className="iv3-loading-bar" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={jobProgress}>
                  <div className="iv3-loading-bar-fill" style={jobProgress > 0 ? { width: `${jobProgress}%` } : undefined}></div>
                </div>
              </div>
            </div>
          ) : historyVideoPreview ? (
            <HistoryVideoPreview id={historyVideoPreview.id} src={apiUrl(historyVideoPreview.videoUrl || historyVideoPreview.url)} prompt={historyVideoPreview.promptOriginal} onOpenVideo={() => setTab('video')} />
          ) : visibleInspectPreview ? (
            <>
              <img className="iv3-preview-backdrop" src={apiUrl(visibleInspectPreview.url)} alt="" aria-hidden="true" />
              <div
                className={`iv3-inspect-stage${inspectToolsVisible ? ' is-zoomed' : ''}`}
                onWheel={onInspectWheel}
                onPointerDown={onInspectPointerDown}
                onPointerMove={onInspectPointerMove}
                onPointerUp={onInspectPointerUp}
                onPointerCancel={onInspectPointerUp}
                onTouchStart={onInspectTouchStart}
                onTouchMove={onInspectTouchMove}
                onTouchEnd={onInspectTouchEnd}
                onTouchCancel={onInspectTouchEnd}
                onDoubleClick={resetInspectView}
              >
                <img className="iv3-preview-main iv3-inspect-image" src={apiUrl(visibleInspectPreview.url)} alt={visibleInspectPreview.title} style={inspectImageStyle} draggable={false} />
              </div>
              {inspectToolsVisible && <div className="iv3-inspect-tools">
                <span>{visibleInspectPreview.title} · {Math.round(inspectZoom * 100)}%</span>
                <button type="button" onClick={resetInspectView}>Сброс</button>
              </div>}
            </>
          ) : visibleResultUrl && !visibleResultError ? (
            <>
              {!visibleResultHasTransparency && <img className="iv3-preview-backdrop" src={apiUrl(visibleResultUrl)} alt="" aria-hidden="true" />}
              {visibleResultWidth && visibleResultHeight && (
                <span className="iv3-result-resolution" title="Фактическое разрешение результата">
                  {visibleResultWidth}×{visibleResultHeight}
                </span>
              )}
              {visibleResultSource && compareEnabled ? (
                <div
                  className={`iv3-compare${compareAuto ? ' is-auto' : ''}${inspectToolsVisible ? ' is-zoomed' : ''}`}
                  style={{ '--compare': `${compare}%`, ...inspectImageStyle } as CSSProperties}
                  onTouchStart={onInspectTouchStart}
                  onTouchMove={onInspectTouchMove}
                  onTouchEnd={onInspectTouchEnd}
                  onTouchCancel={onInspectTouchEnd}
                  onDoubleClick={resetInspectView}
                >
                  <img className={`iv3-preview-main iv3-compare-after${visibleResultHasTransparency ? ' transparent-grid' : ''}`} src={apiUrl(visibleResultUrl)} alt="Результат генерации" onError={markVisiblePreviewError} />
                  <div className="iv3-compare-before">
                    <img className="iv3-preview-main" src={apiUrl(visibleResultSource)} alt="Исходное изображение" />
                  </div>
                  <div className="iv3-compare-line" aria-hidden="true">
                    <span className="iv3-compare-handle"></span>
                  </div>
                  <span className="iv3-compare-label before">До</span>
                  <span className="iv3-compare-label after">После</span>
                  <input
                    className="iv3-compare-range"
                    type="range"
                    min="0"
                    max="100"
                    value={compare}
                    aria-label="Сравнение до и после"
                    onChange={(e) => {
                      compareTouchedRef.current = true
                      setCompareAuto(false)
                      setCompare(Number(e.target.value))
                    }}
                  />
                </div>
              ) : (
                <div
                  className={`iv3-inspect-stage${inspectToolsVisible ? ' is-zoomed' : ''}`}
                  onWheel={onInspectWheel}
                  onPointerDown={onInspectPointerDown}
                  onPointerMove={onInspectPointerMove}
                  onPointerUp={onInspectPointerUp}
                  onPointerCancel={onInspectPointerUp}
                  onTouchStart={onInspectTouchStart}
                  onTouchMove={onInspectTouchMove}
                  onTouchEnd={onInspectTouchEnd}
                  onTouchCancel={onInspectTouchEnd}
                  onDoubleClick={resetInspectView}
                >
                  <img className={`iv3-preview-main iv3-inspect-image${visibleResultHasTransparency ? ' transparent-grid' : ''}`} src={apiUrl(visibleResultUrl)} alt="Результат генерации" style={inspectImageStyle} draggable={false} onError={markVisiblePreviewError} />
                </div>
              )}
              {(!visibleResultSource || !compareEnabled) && inspectToolsVisible && (
                <div className="iv3-inspect-tools">
                  <span>Предпросмотр · {Math.round(inspectZoom * 100)}%</span>
                  <button type="button" onClick={resetInspectView}>Сброс</button>
                </div>
              )}
              {visibleResultSource && inspectToolsVisible && (
                <div className="iv3-inspect-tools">
                  <span>Сравнение · {Math.round(inspectZoom * 100)}%</span>
                  <button type="button" onClick={resetInspectView}>Сброс</button>
                </div>
              )}
              <div className="image-actions">
                {visibleResultUrl && (
                  <a className="image-action" href={apiUrl(visibleResultUrl)} download target="_blank" rel="noreferrer">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                      <path d="M12 3v12m0 0 4-4m-4 4-4-4M5 19h14" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                    Скачать
                  </a>
                )}
                {normalizePrivateMediaPath(visibleResultUrl) && <button className="image-action animate-image-action" type="button" onClick={() => { try { writeVideoSourceHandoff({ galleryImageId: activeCorePreview?.galleryId || activeCorePreview?.resultImageId || visibleGalleryImage?.id, mediaUrl: visibleResultUrl, thumbnailUrl: visibleGalleryImage?.thumbnailUrl, width: visibleResultWidth, height: visibleResultHeight, imagePrompt: activeCorePreview?.promptOriginal || visibleGalleryImage?.promptOriginal }); setTab('video') } catch { showToast('Не удалось подготовить изображение для видео') } }}><Film aria-hidden="true" />Оживить</button>}
                {visibleResultSource && (
                  <button className={`image-action compare-toggle${compareEnabled ? ' active' : ''}`} type="button" aria-pressed={compareEnabled} onClick={() => setCompareEnabled((value) => !value)}>
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                      <path d="M12 4v16M5 6h14a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1Z" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
                    </svg>
                    До/После
                  </button>
                )}
                <button className="image-action" type="button" onClick={() => setShareOpen((v) => !v)}>
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                    <path d="M18 8a3 3 0 1 0-2.82-4M6 13a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm12 8a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM8.7 10.7l6.6 3.6M15.3 9.7l-6.6 3.6" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
                  </svg>
                  Поделиться
                </button>
                {shareOpen && (
                  <div className="iv3-share-menu">
                    <button type="button" onClick={() => { setShareOpen(false); if (shareTarget) openPublish(shareTarget); else showToast(visibleResultUrl ? 'Результат ещё сохраняется в галерею. Подождите секунду.' : 'Сначала сгенерируйте изображение') }}>В ленту</button>
                    <button type="button" onClick={() => void shareCurrentResult()}>Поделиться через устройство</button>
                    <button type="button" onClick={() => { setShareOpen(false); if (visibleResultUrl) copyPrompt(apiUrl(visibleResultUrl)) }}>Скопировать ссылку</button>
                  </div>
                )}
              </div>
            </>
          ) : (
            <div className="iv3-preview-empty">
              <img className="iv3-preview-placeholder-bg" src={previewPlaceholderUrl} alt="" aria-hidden="true" />
              <span className="iv3-preview-placeholder-vignette" aria-hidden="true"></span>
              <span className="iv3-preview-empty-mark" aria-hidden="true">✦</span>
              {visibleResultError ? (
                <p>Предыдущий результат не загрузился. Новый появится здесь.</p>
              ) : previewJobActive ? (
                <div className="iv3-loading-inline" role="status">
                  <span>{jobProgressText}</span>
                  <div className="iv3-loading-bar" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={jobProgress}>
                    <div className="iv3-loading-bar-fill" style={jobProgress > 0 ? { width: `${jobProgress}%` } : undefined}></div>
                  </div>
                </div>
              ) : (
                <p>
                  <span className="iv3-preview-empty-desktop">Опишите идею слева и нажмите «Сгенерировать»</span>
                  <span className="iv3-preview-empty-mobile">Опишите идею и нажмите «Сгенерировать»</span>
                </p>
              )}
            </div>
          )}
          {previewNoticeText && (
            <div className="iv3-preview-notice" role="status" aria-live="polite">
              <span className="iv3-preview-notice-mark" aria-hidden="true">!</span>
              <p>{previewNoticeText}</p>
            </div>
          )}
        </div>
        )} />
      </section>

      <section className="result-dock">
        <ResilientRegion region="history" label="История" fallbackClassName="history" render={() => (
        <div className="history" data-studio-region="history">
          <div className="history-head">
            <button className="history-prompt-chip" type="button" disabled={!dockImage} onClick={() => copyPrompt(dockPromptText)}>
              {dockIsVideo ? 'Промпт видео ›' : 'Промпт изображения ›'}
            </button>
          </div>
          {historyItems.length === 0 ? (
            <div className="iv3-history-empty">
              <span className="iv3-history-empty-mark" aria-hidden="true">▧</span>
              <span>{authStatus === 'authed' ? 'Здесь появятся ваши генерации' : 'Войдите — и здесь появятся ваши работы'}</span>
            </div>
          ) : (
            <div className="history-carousel" aria-label="Навигация истории">
              <button className="history-arrow history-prev" type="button" aria-label="Назад" onClick={() => scrollHistory(-1)}>
                <svg width="18" height="34" viewBox="0 0 18 34" fill="none" aria-hidden="true">
                  <path d="M12.5 6 3.5 17l9 11" stroke="currentColor" strokeWidth="2.1" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </button>
              <div className="history-strip" ref={historyStripRef}>
                {historyIsFeed && (
                  <div className="history-item square history-placeholder-tile" aria-hidden="true">
                    <span className="history-placeholder-mark">✦</span>
                    <span>Здесь появятся ваши генерации</span>
                  </div>
                )}
                {historyItems.map((item) => (
                  <figure
                    key={item.id}
                    className={`history-item ${historyShape(item)}${item.mediaType === 'video' ? ' video' : ''}${dockImage?.id === item.id ? ' active' : ''}`}
                    style={historyAspectRatio(item) ? { aspectRatio: historyAspectRatio(item) } : undefined}
                    role="button"
                    tabIndex={0}
                    onClick={() => {
                      if (historyDraggedRef.current) { historyDraggedRef.current = false; return }
                      openHistory(item)
                    }}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault()
                        openHistory(item)
                      }
                    }}
                  >
                    {item.mediaType === 'video' ? (
                      <video
                        src={apiUrl(item.videoUrl || item.url)}
                        muted
                        playsInline
                        preload="metadata"
                        aria-label={item.promptOriginal.slice(0, 40) || 'Видео из истории'}
                        onLoadedMetadata={(e) => {
                          const video = e.currentTarget
                          const frame = video.closest<HTMLElement>('.history-item')
                          if (!frame || video.videoWidth <= 0 || video.videoHeight <= 0) return
                          frame.style.aspectRatio = `${video.videoWidth} / ${video.videoHeight}`
                        }}
                      />
                    ) : (
                      <img
                        src={apiUrl(item.thumbnailUrl || item.url)}
                        alt={item.promptOriginal.slice(0, 40)}
                        loading="lazy"
                        onLoad={(e) => {
                          const img = e.currentTarget
                          const frame = img.closest<HTMLElement>('.history-item')
                          if (!frame || img.naturalWidth <= 0 || img.naturalHeight <= 0) return
                          frame.style.aspectRatio = `${img.naturalWidth} / ${img.naturalHeight}`
                        }}
                      />
                    )}
                    {item.mediaType === 'video' && <span className="history-video-badge">Видео</span>}
                    {historyIsFeed && <span className="history-feed-badge">Лента</span>}
                  </figure>
                ))}
              </div>
              <button className="history-arrow history-next" type="button" aria-label="Вперёд" onClick={() => scrollHistory(1)}>
                <svg width="18" height="34" viewBox="0 0 18 34" fill="none" aria-hidden="true">
                  <path d="m5.5 6 9 11-9 11" stroke="currentColor" strokeWidth="2.1" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </button>
            </div>
          )}
        </div>
        )} />

        <aside className="image-prompt">
          <div className="prompt-copy">
            <div className="prompt-copy-head">
              <h2>{dockIsVideo ? 'Промпт видео' : 'Промпт изображения'}</h2>
              <button className="prompt-action prompt-copy-button" type="button" disabled={!dockImage} onClick={() => copyPrompt(dockPromptText)}>
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                  <path d="M8 8h10v12H8V8Z" stroke="currentColor" strokeWidth="1.7" />
                  <path d="M5 16V4h11" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
                </svg>
                <span className="prompt-action-label">{copied ? 'Скопировано' : 'Копировать'}</span>
              </button>
            </div>
            <div className="prompt-scroll">{dockPromptText || `Здесь появится промпт выбранного ${dockIsVideo ? 'видео' : 'изображения'}.`}</div>
          </div>
          <div className="prompt-actions">
            <details className={`prompt-menu${!dockImage || dockIsVideo ? ' is-disabled' : ''}`}>
              <summary className="prompt-action" aria-disabled={!dockImage || dockIsVideo} onClick={(event) => { if (!dockImage || dockIsVideo) event.preventDefault() }}>
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M4 20h4l10.5-10.5a2.1 2.1 0 0 0-3-3L5 17v3Z" stroke="currentColor" strokeWidth="1.7" strokeLinejoin="round" /><path d="m13.5 8.5 3 3" stroke="currentColor" strokeWidth="1.7" /></svg>
                <span className="prompt-action-label">Изменить в</span>
                <svg className="menu-caret" width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m7 9 5 5 5-5" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" /></svg>
              </summary>
              <div className="prompt-menu-list">
                <button type="button" onClick={() => { if (dockImage) setSourceImage(apiUrl(dockImage.url)); setTab('i2i') }}>По фото</button>
                <button type="button" onClick={() => setTab('edit')}>Сборка</button>
                <button type="button" onClick={() => setTab('paint')}>Редактор</button>
              </div>
            </details>
            <button className="prompt-action feed" type="button" disabled={!shareTarget || dockIsVideo} onClick={() => { if (shareTarget && !dockIsVideo) openPublish(shareTarget) }}>
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M12 3.5l1.6 4 4 1.6-4 1.6-1.6 4-1.6-4-4-1.6 4-1.6L12 3.5Z" fill="currentColor" /></svg>
              <span className="prompt-action-label">В ленту</span>
            </button>
            <button className="prompt-action" type="button" disabled={!dockImage || dockIsVideo} onClick={() => { if (!dockImage || dockIsVideo) return; setPrompt(dockImage.promptOriginal); showToast('Промпт подставлен — измените и сгенерируйте') }}>
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M7 7h10v10H7V7Z" stroke="currentColor" strokeWidth="1.6" /><path d="M4 4h10M10 20h10" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" /></svg>
              <span className="prompt-action-label">Вариации</span>
            </button>
          </div>
        </aside>
      </section>
    </main>
  )

  const placeholderStudio = (title: string, note: string) => (
    <div className="iv3-placeholder">
      <img className="iv3-preview-placeholder-bg" src={previewPlaceholderUrl} alt="" aria-hidden="true" />
      <span className="iv3-preview-placeholder-vignette" aria-hidden="true"></span>
      <div className="iv3-placeholder-card">
        <span className="iv3-preview-empty-mark" aria-hidden="true">✦</span>
        <h2>{title}</h2>
        <p>{note}</p>
        <button className="iv3-placeholder-cta" type="button" onClick={() => setTab('text')}>
          Перейти в «По тексту»
        </button>
      </div>
    </div>
  )

  const topbarAvatarSrc = userMediaUrl(acct.avatarUrl)
  const profileAvatarSrc = userMediaUrl(avatarUrl)
  const profilePage = (
    <ProfilePage
      authStatus={authStatus}
      me={me}
      galleryCount={gallery.length}
      profileTab={profileTab}
      setProfileTab={setProfileTab}
      tariffs={tariffs}
      tariffsState={tariffsState}
      tokenRub={tokenRub}
      openrouterPricing={openrouterPricing}
      authCapsState={authCapsState}
      authCaps={authCaps}
      quality={quality}
      setQuality={setQuality}
      modelAccess={modelAccess}
      userModelChoices={userModelChoices}
      setUserModelChoices={setUserModelChoices}
      userModelVisibility={userModelVisibility}
      setUserModelVisibility={setUserModelVisibility}
      displayName={displayName}
      setDisplayName={setDisplayName}
      profileGender={profileGender}
      setProfileGender={setProfileGender}
      profileAge={profileAge}
      setProfileAge={setProfileAge}
      publicAbout={publicAbout}
      setPublicAbout={setPublicAbout}
      publicWebsite={publicWebsite}
      setPublicWebsite={setPublicWebsite}
      publicFocus={publicFocus}
      setPublicFocus={setPublicFocus}
      publicPhone={publicPhone}
      setPublicPhone={setPublicPhone}
      publicLinks={publicLinks}
      setPublicLinks={setPublicLinks}
      saveMsg={saveMsg}
      setSaveMsg={setSaveMsg}
      avatarSrc={profileAvatarSrc}
      avatarPreset={avatarPreset}
      avatarBusy={avatarBusy}
      avatarMsg={avatarMsg}
      uploadAvatar={uploadAvatar}
      selectAvatarPreset={selectAvatarPreset}
      promoCode={promoCode}
      setPromoCode={setPromoCode}
      promoBusy={promoBusy}
      promoResult={promoResult}
      setPromoResult={setPromoResult}
      inviteMsg={inviteMsg}
      setInviteMsg={setInviteMsg}
      linkBusy={linkBusy}
      linkMsg={linkMsg}
      onOpenAuth={() => setAuthOpen(true)}
      onBackToGeneration={() => setTab('text')}
      onSaveProfile={onSaveProfile}
      onLogout={onLogout}
      onApplyPromo={onApplyPromo}
      onLinkBot={(providerName) => void onLinkBot(providerName)}
    />
  )
  const topActive: V3Section = view === 'profile' ? 'profile' : tab === 'feed' ? 'feed' : (tab as V3Section)

  return (
    <div className="n2">
      <AuthV2Modal open={authOpen} onClose={() => setAuthOpen(false)} />
      {toastText && tab === 'feed' && (
        <div className="n2-toast" role="status">
          {toastText}
        </div>
      )}
      <input
        ref={fileInputRef}
        type="file"
        accept="image/png,image/jpeg,image/webp"
        style={{ display: 'none' }}
        onChange={(e) => {
          onSourceFile(e.target.files?.[0])
          e.target.value = ''
        }}
      />

      {helpOpen && (
        <div className="n2-overlay" role="dialog" aria-label="Помощь" onClick={() => setHelpOpen(false)}>
          <div className="n2-overlay-card n2-help-card" onClick={(e) => e.stopPropagation()}>
            <button className="n2-overlay-close" type="button" aria-label="Закрыть" onClick={() => setHelpOpen(false)}>
              ×
            </button>
            <header className="n2-help-hero">
              <span>Справка и правила сервиса</span>
              <h2>ИЗО АСА: генерация и редактирование изображений</h2>
              <p>
                ИЗО АСА — AI-сервис для создания изображений, редактирования фотографий, работы с референсами,
                замены лица, примерки одежды, генерации по эскизу и публикации результата в галерею или ленту.
              </p>
            </header>

            <nav className="n2-help-toc" aria-label="Разделы помощи">
              <a href="#help-modes">Режимы</a>
              <a href="#help-faq">FAQ</a>
              <a href="#help-policy">Правила</a>
              <a href="#help-privacy">Данные</a>
              <a href="#help-billing">Тарифы и оплата</a>
              <a href="#help-contacts">Контакты</a>
            </nav>

            <section className="n2-help-section" id="help-modes">
              <h3>Что умеет сервис</h3>
              <div className="n2-help-grid">
                <article>
                  <strong>По тексту</strong>
                  <p>Создает изображение по описанию: персонаж, сцена, предмет, интерьер, афиша, иллюстрация, обложка, концепт-арт или реалистичная фотография.</p>
                </article>
                <article>
                  <strong>По фото</strong>
                  <p>Преобразует исходное изображение по промпту и стилю. Ползунок влияния промпта регулирует силу изменения; рекомендуемое значение — 75%.</p>
                </article>
                <article>
                  <strong>Сборка</strong>
                  <p>Объединяет изображения и переносит детали с референсов: одежду, фон, объект, стиль, цвет, материал, позу или лицо.</p>
                </article>
                <article>
                  <strong>Редактор</strong>
                  <p>Превращает эскиз в сцену, работает с маской, дорисовывает область и расширяет холст вокруг изображения.</p>
                </article>
                <article>
                  <strong>Галерея и лента</strong>
                  <p>Хранит результаты, исходники и промпты. Работы можно скачивать, защищать сердечком, открывать в другом режиме и публиковать в ленту.</p>
                </article>
              </div>
            </section>

            <section className="n2-help-section" id="help-faq">
              <h3>FAQ</h3>
              <details open>
                <summary>Как получить лучший результат?</summary>
                <p>Опишите, что нужно сохранить, что изменить и какой итог нужен: реалистичное фото, аниме, комикс, премиум-стиль, предметная визуализация, портрет или кинематографичная сцена.</p>
              </details>
              <details>
                <summary>Можно ли использовать свои изображения?</summary>
                <p>Да. В режимах По фото, Сборка и Редактор можно загрузить изображение, взять работу из галереи или использовать последнее созданное изображение.</p>
              </details>
              <details>
                <summary>Где хранятся результаты?</summary>
                <p>Результаты сохраняются в галерее пользователя вместе с промптом и параметрами генерации. Отдельные работы можно отправить в публичную ленту.</p>
              </details>
              <details>
                <summary>Что публикуется в ленте?</summary>
                <p>В ленту отправляется отдельная публичная копия выбранного изображения. Пользователь управляет публикацией и может удалить ее из ленты.</p>
              </details>
              <details>
                <summary>Почему некоторые функции требуют вход?</summary>
                <p>Авторизация нужна для сохранения галереи, публикаций, профиля, лимитов, избранного и связи работ с конкретным пользователем.</p>
              </details>
            </section>

            <section className="n2-help-section" id="help-policy">
              <h3>Правила использования</h3>
              <ul>
                <li>Не загружайте изображения, на которые у вас нет прав или разрешения.</li>
                <li>Не используйте сервис для обмана, вреда, травли, незаконных действий или выдачи результата за официальный документ.</li>
                <li>При работе с лицами используйте только изображения людей, на использование которых у вас есть согласие.</li>
                <li>Публичные публикации в ленте могут быть скрыты или удалены при нарушении правил сервиса.</li>
              </ul>
            </section>

            <section className="n2-help-section" id="help-privacy">
              <h3>Данные и приватность</h3>
              <p>
                Для работы сервиса используются учетная запись, cookie-сессия, загруженные изображения, промпты,
                параметры генерации, публикации в ленте и технические данные запросов. Эти данные нужны для входа,
                генерации, сохранения галереи, восстановления истории, лимитов и защиты сервиса от злоупотреблений.
              </p>
              <p>
                Не загружайте чувствительные документы, платежные данные, медицинские сведения или материалы,
                которые вы не хотите использовать в AI-обработке. Удаление изображения из галереи удаляет его из
                пользовательского интерфейса; опубликованные копии в ленте управляются отдельно.
              </p>
            </section>

            <section className="n2-help-section n2-help-billing" id="help-billing">
              <h3>Тарифы, токены и оплата</h3>
              <div className="n2-help-grid">
                <article>
                  <strong>Что входит в тариф</strong>
                  <p>У каждого тарифа свой дневной пакет серверных генераций, месячный пакет токенов для премиум-моделей, объём галереи, доступные разрешения и дополнительные режимы.</p>
                </article>
                <article>
                  <strong>Как списываются токены</strong>
                  <p>Стоимость выбранной модели и формата показывается до запуска. Серверные и премиум-токены учитываются раздельно; актуальный остаток и история доступны в профиле.</p>
                </article>
                <article>
                  <strong>Как проходит оплата</strong>
                  <p>Перед переходом в ЮKassa пользователь видит состав услуги и итоговую цену, принимает оферту и указывает email или телефон для электронного чека. Тариф или пакет активируется после подтверждения платежа.</p>
                </article>
                <article>
                  <strong>Возвраты и обращения</strong>
                  <p>Условия отказа и возврата опубликованы отдельно. В обращении укажите аккаунт, номер платежа, сумму и причину; это ускорит проверку операции.</p>
                </article>
              </div>
              <div className="n2-help-links" aria-label="Тарифы и правовые документы">
                <a href="/tariffs">Тарифы и цены</a>
                <a href="/legal/offer">Публичная оферта</a>
                <a href="/legal/payment">Условия оплаты</a>
                <a href="/legal/refunds">Возвраты</a>
                <a href="/legal/privacy">Политика конфиденциальности</a>
                <a href="/legal/contacts">Реквизиты и контакты</a>
              </div>
            </section>

            <section className="n2-help-section" id="help-contacts">
              <h3>Контакты и поддержка</h3>
              <p>
                По вопросам доступа, удаления публикации, обработки данных, ошибок генерации или рекламного
                размещения используйте профиль пользователя и официальные контакты ИЗО АСА. Для вопросов по оплате
                указывайте номер платежа или счёта.
              </p>
              <a className="n2-help-contact-link" href="/legal/contacts">Открыть контакты и реквизиты</a>
            </section>
          </div>
        </div>
      )}

      {templatesOpen && (
        <div className="n2-overlay" role="dialog" aria-label="Шаблоны" onClick={() => setTemplatesOpen(false)}>
          <div className="n2-overlay-card n2-templates" onClick={(e) => e.stopPropagation()}>
            <button className="n2-overlay-close" type="button" aria-label="Закрыть" onClick={() => setTemplatesOpen(false)}>
              ×
            </button>
            <h2>{tab === 'i2i' ? 'Шаблоны преобразования' : 'Шаблоны · идеи'}</h2>
            {tab === 'i2i' ? (
              <div className="n2-templates-styles">
                {I2I_STYLES.map((style) => (
                  <button
                    key={style.id}
                    className="n2-template-style"
                    type="button"
                    title={style.name}
                    onClick={() => {
                      appendI2ITemplate(style.transformPrompt)
                    }}
                  >
                    <img src={style.preview[previewGender]} alt={style.preview.alt} loading="lazy" />
                    <span>{style.name}</span>
                  </button>
                ))}
              </div>
            ) : (
              <div className="n2-templates-list">
                {T2I_TEMPLATES.map((template) => (
                  <button key={template.id} className="n2-template-item" type="button" onClick={() => applyTemplate(template.prompt)}>
                    <strong>{template.name}</strong>
                    <span>{template.prompt.slice(0, 140)}…</span>
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {galleryPickTarget && (
        <div className="n2-overlay" role="dialog" aria-label="Выбор из галереи" onClick={() => setGalleryPickTarget(null)}>
          <ResilientRegion region="gallery-picker" label="Выбор изображения" fallbackClassName="n2-overlay-card n2-templates" render={() => (
          <div className="n2-overlay-card n2-templates" data-studio-region="gallery-picker" onClick={(e) => e.stopPropagation()}>
            <button className="n2-overlay-close" type="button" aria-label="Закрыть" onClick={() => setGalleryPickTarget(null)}>
              ×
            </button>
            <h2>{galleryPickTarget.kind === 'edit' ? 'Выберите изображение' : 'Выберите исходник из галереи'}</h2>
            <div className="n2-gallery-picker-tabs" role="tablist" aria-label="Источник изображения">
              <button className={galleryPickerTab === 'generated' ? 'active' : ''} type="button" role="tab" aria-selected={galleryPickerTab === 'generated'} onClick={() => setGalleryPickerTab('generated')}>
                Сгенерированные <span>{galleryPickerImages.length}</span>
              </button>
              <button className={galleryPickerTab === 'uploaded' ? 'active' : ''} type="button" role="tab" aria-selected={galleryPickerTab === 'uploaded'} onClick={() => setGalleryPickerTab('uploaded')}>
                Загруженные <span>{uploadedSources.length}</span>
              </button>
            </div>
            {galleryPickerError && <p className="n2-gallery-picker-message error">{galleryPickerError}</p>}
            {galleryPickerLoading ? (
              <p className="n2-gallery-picker-message">Загружаем изображения…</p>
            ) : galleryPickerTab === 'generated' ? (
              galleryPickerImages.length ? (
                <div className="n2-templates-styles n2-gallery-picker-grid">
                  {galleryPickerImages.map((item) => (
                    <button
                      key={item.id}
                      className="n2-template-style"
                      type="button"
                      title={item.promptOriginal}
                      onClick={() => {
                        applyImageToTarget(galleryPickTarget, apiUrl(item.url))
                        setGalleryPickTarget(null)
                      }}
                    >
                      <img
                        src={apiUrl(item.thumbnailUrl || item.url)}
                        alt={item.promptOriginal.slice(0, 60)}
                        loading="lazy"
                        onError={markPickerImageError}
                        style={item.width && item.height ? { aspectRatio: `${item.width} / ${item.height}` } : undefined}
                      />
                      {item.width && item.height && <span>{item.width}×{item.height}</span>}
                    </button>
                  ))}
                </div>
              ) : <p className="n2-gallery-picker-message">Сгенерированных изображений пока нет.</p>
            ) : uploadedSources.length ? (
              <div className="n2-templates-styles n2-gallery-picker-grid">
                {uploadedSources.map((item) => (
                  <button
                    key={item.id}
                    className="n2-template-style"
                    type="button"
                    title={item.roleLabel || 'Ранее загруженное изображение'}
                    onClick={() => {
                      applyImageToTarget(galleryPickTarget, apiUrl(item.thumbnailUrl))
                      setGalleryPickTarget(null)
                    }}
                  >
                    <img
                      src={apiUrl(item.thumbnailUrl)}
                      alt={item.roleLabel || 'Ранее загруженное изображение'}
                      loading="lazy"
                      onError={markPickerImageError}
                      style={item.width && item.height ? { aspectRatio: `${item.width} / ${item.height}` } : undefined}
                    />
                    <span>{item.width && item.height ? `${item.width}×${item.height}` : item.roleLabel || 'Загруженное'}</span>
                  </button>
                ))}
              </div>
            ) : <p className="n2-gallery-picker-message">Ранее загруженных изображений пока нет.</p>}
          </div>
          )} />
        </div>
      )}

      {galleryItem && (
        <div className="n2-overlay" role="dialog" aria-label="Просмотр изображения" onClick={() => setGalleryItem(undefined)}>
          <div className="n2-overlay-card n2-overlay-image" onClick={(e) => e.stopPropagation()}>
            <button className="n2-overlay-close" type="button" aria-label="Закрыть" onClick={() => setGalleryItem(undefined)}>
              ×
            </button>
            <img src={apiUrl(galleryItem.url)} alt={galleryItem.promptOriginal.slice(0, 80)} />
            <p className="n2-overlay-prompt">{galleryItem.promptOriginal}</p>
            <div className="n2-overlay-actions">
              <a className="n2-ghost" href={apiUrl(galleryItem.url)} download target="_blank" rel="noreferrer">
                ⬇ {ft.download}
              </a>
              <button className="n2-ghost" type="button" onClick={() => applyGalleryAsSource(galleryItem)}>
                → {ft.useAsSource}
              </button>
              <button className="n2-ghost purple" type="button" onClick={() => openPublish(galleryItem)}>
                ✦ {ft.publish}
              </button>
              <button className="n2-ghost danger" type="button" onClick={() => deleteGalleryImage(galleryItem)}>
                🗑 {ft.del}
              </button>
            </div>
          </div>
        </div>
      )}

      {publishFor && (
        <div className="n2-overlay" role="dialog" aria-label={ft.publish} onClick={() => setPublishFor(null)}>
          <div className="n2-overlay-card" onClick={(e) => e.stopPropagation()}>
            <button className="n2-overlay-close" type="button" aria-label="Закрыть" onClick={() => setPublishFor(null)}>
              ×
            </button>
            <h2>{ft.publish}</h2>
            <img className="n2-publish-preview" src={apiUrl(publishFor.thumbnailUrl || publishFor.url)} alt="" />
            <label className="n2-publish-field">
              <span>{feedLang === 'ru' ? 'Название' : 'Title'}</span>
              <input
                type="text"
                maxLength={120}
                value={publishTitle}
                onChange={(e) => setPublishTitle(e.target.value)}
              />
            </label>
            <label className="n2-publish-field">
              <span>{feedLang === 'ru' ? 'Видимость промпта' : 'Prompt visibility'}</span>
              <select value={publishVisibility} onChange={(e) => setPublishVisibility(e.target.value as 'open' | 'partial' | 'hidden')}>
                <option value="open">{feedLang === 'ru' ? 'Открытый' : 'Open'}</option>
                <option value="partial">{feedLang === 'ru' ? 'Частично' : 'Partial'}</option>
                <option value="hidden">{feedLang === 'ru' ? 'Скрыт' : 'Hidden'}</option>
              </select>
            </label>
            <label className="n2-publish-check">
              <input
                type="checkbox"
                checked={publishAllowRecreate}
                onChange={(e) => setPublishAllowRecreate(e.target.checked)}
              />
              <span>{feedLang === 'ru' ? `Разрешить «${ft.recreate}»` : `Allow "${ft.recreate}"`}</span>
            </label>
            <div className="n2-overlay-actions">
              <button className="n2-publish-submit" type="button" disabled={publishBusy} onClick={submitPublish}>
                {publishBusy ? '…' : ft.publish}
              </button>
            </div>
          </div>
        </div>
      )}

      <div className={`iv3 mode-${tab}`}>
        <div className="app-shell">
          <TopBarV3
            active={topActive}
            authed={authStatus === 'authed'}
            avatarUrl={authStatus === 'authed' ? topbarAvatarSrc : null}
            userLabel={authStatus === 'authed' ? acct.userLabel : null}
            initials={authStatus === 'authed' ? acct.initials : null}
            dailyTokensRemaining={authStatus === 'authed' ? topbarDailyRemaining : null}
            dailyTokensLimit={authStatus === 'authed' ? topbarDailyLimit : null}
            tokenBalance={authStatus === 'authed' ? topbarTokenBalance : null}
            isAdmin={isAdmin}
            onSelectMode={selectStudioMode}
            onOpenFeed={() => setTab('feed')}
            onOpenGallery={goGallery}
            onOpenHelp={() => setHelpOpen(true)}
            onOpenAdmin={() => { window.location.href = '/admin' }}
            onOpenProfile={openProfilePage}
          />
          {view === 'profile' ? (
            <div className="iv3-content">{profilePage}</div>
          ) : tab === 'feed' ? (
            <div className="iv3-content"><div className="preview-empty">Открываем ленту...</div></div>
          ) : tab === 'text' || tab === 'i2i' || tab === 'edit' || tab === 'paint' ? (
            studio
          ) : tab === 'video' ? (
            <Suspense fallback={<div className="iv3-content"><div className="preview-empty">Загружаем видеостудию…</div></div>}><VideoStudio onTokenBalanceChange={() => { void refreshAuthStateV2() }} /></Suspense>
          ) : (
            placeholderStudio('Видео', 'Выберите режим и доступную вашему тарифу видеомодель.')
          )}
        </div>
        {view === 'tabs' && (tab === 'text' || tab === 'i2i' || tab === 'edit' || tab === 'paint') && (
          <button className={`mobile-bottom-cta${isSubmitting || jobActive ? ' is-generating' : ''}`} type="button" disabled={isSubmitting || jobActive} onClick={() => generate(studioMode)}>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <path d="M12 3.5l1.9 4.8 4.8 1.9-4.8 1.9-1.9 4.9-1.9-4.9-4.8-1.9 4.8-1.9L12 3.5Z" fill="currentColor" />
            </svg>
            {jobActive || isSubmitting ? generatingLabel.replace('...', '…') : generateLabel}
          </button>
        )}
      </div>
    </div>
  )
}
