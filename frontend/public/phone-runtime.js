/* Real project adapter for the standalone /phone interface.
   The visual template stays in phone-prototype.html; this file only replaces
   demo data and timers with the existing IZO_ASA API contracts. */
(() => {
  const state = {
    ready: false,
    me: null,
    feed: [],
    feedKey: '',
    gallery: [],
    modelAccess: null,
    videoConfig: null,
    imageModelByMode: {},
    videoModelByMode: {},
    imageResults: [],
    imageRefs: [],
    sketchData: '',
    imageJob: null,
    imagePhase: 'idle',
    videoJob: null,
    videoSources: [],
    videoResultUrl: '',
    videoEstimate: null,
    videoDuration: null,
    videoResolution: null,
    videoAspect: null,
    videoAudio: false,
    lastError: '',
  }
  window.__IZO_PHONE_RUNTIME__ = state

  const styleNode = document.createElement('style')
  styleNode.textContent = `
    .live-empty{min-height:220px;border-radius:22px;background:var(--s1);box-shadow:inset 0 0 0 1px var(--edge);display:grid;place-items:center;text-align:center;padding:26px;color:var(--tx2);font:650 12px/1.5 inherit}
    .live-empty b{display:block;color:var(--tx);font:760 15px/1.25 inherit;margin-bottom:5px}
    .live-badge{position:absolute;left:8px;top:8px;border-radius:9px;padding:5px 7px;background:rgba(6,7,10,.66);color:#fff;font:750 9px/1 inherit;backdrop-filter:blur(10px)}
    .live-preview{width:100%;max-height:58vh;border-radius:18px;object-fit:contain;background:#050509;display:block}
    .live-meta{display:grid;gap:5px;padding:10px 2px 2px;color:var(--tx2);font:650 12px/1.4 inherit}.live-meta b{color:var(--tx);font-size:14px}
    .live-source-grid{width:100%;height:100%;display:grid;grid-template-columns:repeat(2,1fr);gap:7px;padding:8px}
    .live-source-grid img{width:100%;height:100%;min-height:90px;max-height:180px;object-fit:cover;border-radius:14px}
    .phone-sketch-canvas{width:100%;height:100%;touch-action:none;background:#fff;display:block}
    .live-status{position:absolute;left:10px;right:10px;bottom:10px;border-radius:12px;padding:8px 10px;background:rgba(6,7,10,.72);color:#fff;font:700 10px/1.3 inherit;backdrop-filter:blur(10px)}
    .pick.disabled{opacity:.38;pointer-events:none}.pick .live-price{margin-left:auto;color:var(--quiet);font:750 11px/1 inherit}
    .card video{width:100%;display:block}.gal span{position:relative}.gal video{width:100%;aspect-ratio:1;object-fit:cover;display:block}
  `
  document.head.appendChild(styleNode)

  const imageMode = () => ['text_to_image', 'image_to_image', 'paint', 'edit'][idx] || 'text_to_image'
  const videoMode = () => ['text_to_video', 'image_to_video', 'first_last_frame', 'reference_to_video'][idx] || 'text_to_video'
  const feedTypes = ['top', 'fresh', 'remix', 'challenge', 'following']
  const resolutionTable = {
    '1:1': { SD: ['sq-sd', 704, 704], HD: ['sq-hd', 1024, 1024], 'Full HD': ['sq-fhd', 1408, 1408], '4K': ['sq-4k', 4096, 4096] },
    '16:9': { SD: ['h-sd', 1024, 576], HD: ['h-hd', 1280, 720], 'Full HD': ['h-fhd', 1792, 1008], '4K': ['h-4k', 3840, 2160] },
    '9:16': { SD: ['v-sd', 576, 1024], HD: ['v-hd', 720, 1280], 'Full HD': ['v-fhd', 1008, 1792], '4K': ['v-4k', 2160, 3840] },
    '3:2': { SD: ['p-sd', 960, 640], HD: ['p-hd', 1152, 768], 'Full HD': ['p-fhd', 1728, 1152], '4K': ['p-4k', 4096, 2736] },
  }
  const planTiers = { free: 0, mini: 1, plus: 2, pro: 2, business: 3 }

  const absoluteUrl = (value) => {
    if (!value) return ''
    try { return new URL(value, location.origin).toString() } catch { return String(value) }
  }
  const html = (value) => String(value ?? '').replace(/[&<>'"]/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' })[char])
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

  async function api(path, init = {}, retry = true) {
    let response = await fetch(`/api${path}`, { ...init, credentials: 'include' })
    if (response.status === 401 && retry) {
      const refreshed = await fetch('/api/auth/session/refresh-v2', {
        method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: '{}',
      }).catch(() => null)
      if (refreshed?.ok) response = await fetch(`/api${path}`, { ...init, credentials: 'include' })
    }
    return response
  }

  async function responseMessage(response, fallback) {
    let detail = ''
    try { detail = String((await response.json())?.detail || '') } catch { /* non-json */ }
    if (response.status === 401) return 'Войдите в аккаунт, чтобы продолжить.'
    if (response.status === 402 || response.status >= 500) return 'Генерация временно недоступна. Повторите позже или обратитесь в поддержку.'
    if (response.status === 403) return detail || 'Эта функция недоступна на вашем тарифе.'
    if (response.status === 429) return 'Слишком много запросов. Подождите немного и повторите.'
    return detail || fallback
  }

  function normalizeFeed(payload) {
    const rows = Array.isArray(payload) ? payload : (payload?.items || payload?.publications || [])
    return rows.map((item, index) => {
      const mediaType = String(item.media_type || item.mediaType || 'image').toLowerCase() === 'video' ? 'video' : 'image'
      const thumb = item.thumbnail_url || item.thumbnailUrl || item.image_url || item.display_url || item.displayUrl
      const media = mediaType === 'video' ? (item.video_url || item.videoUrl || item.video_preview_url) : (item.image_url || item.display_url || item.displayUrl)
      return {
        id: String(item.id || `feed-${index}`), mediaType, thumb: absoluteUrl(thumb), media: absoluteUrl(media || thumb),
        title: String(item.title || item.prompt || 'Работа из ленты'),
        author: String(item.author_name || item.author?.displayName || 'Автор ИЗО АСА'),
        feedUrl: String(item.feed_url || `/feed?tab=new#work-${item.id || ''}`),
      }
    }).filter((item) => item.thumb)
  }

  function normalizeGallery(payload) {
    const rows = Array.isArray(payload) ? payload : (payload?.items || [])
    return rows.map((item, index) => {
      const url = item.videoUrl || item.viewerSrc || item.downloadUrl || item.url || item.src || item.thumbnailUrl
      const thumb = item.thumbnailUrl || item.src || item.viewerSrc || item.url || item.videoUrl
      const explicit = String(item.mediaType || item.media_type || '').toLowerCase()
      const mediaType = explicit === 'video' || /\.(mp4|webm|mov|m4v)(?:[?#]|$)/i.test(String(url || '')) ? 'video' : 'image'
      return {
        id: String(item.id || item.imageId || `gallery-${index}`), mediaType,
        media: absoluteUrl(url), thumb: absoluteUrl(thumb || url),
        title: String(item.promptOriginal || item.prompt || (mediaType === 'video' ? 'Видео' : 'Изображение')),
        width: Number(item.width || 0), height: Number(item.height || 0),
      }
    }).filter((item) => item.media && item.thumb)
  }

  function generation(value) {
    return {
      id: String(value?.id || value?.jobId || ''), status: String(value?.status || ''),
      progress: Number(value?.progress || 0), resultUrl: absoluteUrl(value?.resultUrl || value?.result_url),
      error: String(value?.error || value?.error_message || ''),
    }
  }

  function getImageModels(modeKey = imageMode()) {
    const row = state.modelAccess?.modes?.[modeKey]
    const models = Array.isArray(row?.models) ? row.models : []
    return models.length ? models : [{ id: 'server:local_flux_klein', label: 'ИЗО Base', provider: 'comfyui', modelProfile: 'local_flux_klein', tokenHint: 1, supportedResolutionIds: Object.values(resolutionTable).flatMap((tiers) => Object.values(tiers).slice(0, 3).map((entry) => entry[0])) }]
  }

  function selectedImageModel() {
    const modeKey = imageMode()
    const models = getImageModels(modeKey)
    const configured = state.imageModelByMode[modeKey] || state.modelAccess?.modes?.[modeKey]?.presets?.fast
    const selected = models.find((item) => item.id === configured) || models[0]
    state.imageModelByMode[modeKey] = selected.id
    return selected
  }

  function selectedResolution() {
    const aspect = RATIOS[ratio]?.[0] || '1:1'
    const tier = QUAL[qual]?.[0] || 'HD'
    return resolutionTable[aspect]?.[tier] || resolutionTable['1:1'].HD
  }

  function qualityAllowed(index) {
    const selected = selectedImageModel()
    const aspect = RATIOS[ratio]?.[0] || '1:1'
    const entry = resolutionTable[aspect]?.[QUAL[index]?.[0]]
    if (!entry) return false
    const planLimit = planTiers[String(state.me?.account?.plan || 'mini').toLowerCase()] ?? 1
    if (index > planLimit) return false
    const supported = Array.isArray(selected.supportedResolutionIds) ? selected.supportedResolutionIds : []
    return supported.length === 0 || supported.includes(entry[0])
  }

  function getVideoModels(modeKey = videoMode()) {
    const rows = state.videoConfig?.modes?.[modeKey]
    return Array.isArray(rows) ? rows : []
  }

  function selectedVideoModel() {
    const modeKey = videoMode()
    const models = getVideoModels(modeKey)
    const selected = models.find((item) => item.id === state.videoModelByMode[modeKey]) || models[0] || null
    if (selected) state.videoModelByMode[modeKey] = selected.id
    return selected
  }

  function videoModelDescription(item) {
    if (!item) return 'Выберите модель вашего тарифа'
    const durations = Array.isArray(item.supportedDurations) && item.supportedDurations.length
      ? `${Math.min(...item.supportedDurations)}–${Math.max(...item.supportedDurations)} с`
      : 'короткие ролики'
    const resolutions = Array.isArray(item.supportedResolutions) && item.supportedResolutions.length
      ? item.supportedResolutions.join(', ')
      : 'доступное качество'
    return `Видео по описанию или исходным кадрам · ${durations} · ${resolutions}`
  }

  function syncVideoOptions() {
    const item = selectedVideoModel()
    if (!item) return
    const durations = item.supportedDurations || []
    const resolutions = item.supportedResolutions || []
    const aspects = item.supportedAspectRatios || []
    if (!durations.includes(state.videoDuration)) state.videoDuration = durations.includes(4) ? 4 : durations[0]
    if (!resolutions.includes(state.videoResolution)) state.videoResolution = resolutions.includes('720p') ? '720p' : resolutions[0]
    if (!aspects.includes(state.videoAspect)) state.videoAspect = aspects.includes('16:9') ? '16:9' : aspects[0]
    if (item.generateAudio === false) state.videoAudio = false
  }

  function openMedia(item) {
    shPick.classList.add('tall')
    const media = item.mediaType === 'video'
      ? `<video class="live-preview" src="${html(item.media)}" poster="${html(item.thumb)}" controls playsinline></video>`
      : `<img class="live-preview" src="${html(item.media)}" alt="">`
    shPick.innerHTML = `<div class="grab"></div><div class="shead"><h4>${item.mediaType === 'video' ? 'Видео' : 'Изображение'}</h4>${X}</div>${media}<div class="live-meta"><b>${html(item.title)}</b>${item.author ? `<span>${html(item.author)}</span>` : ''}</div>`
    openSheet('pick')
  }

  function renderFeed() {
    if (!state.feed.length) {
      scr.innerHTML = '<div class="live-empty"><span><b>Лента загружается</b>Здесь появятся реальные публикации ИЗО АСА.</span></div>'
      return
    }
    scr.innerHTML = `<div class="mas">${state.feed.map((item) => `<div class="card" data-live-feed="${html(item.id)}"><img alt="" src="${html(item.thumb)}"><span class="live-badge">${item.mediaType === 'video' ? 'Видео' : 'Изображение'}</span><button class="rp" type="button">Открыть</button><span class="ov">${html(item.title)} · ${html(item.author)}</span></div>`).join('')}</div>`
    scr.querySelectorAll('[data-live-feed]').forEach((node) => node.addEventListener('click', () => openMedia(state.feed.find((item) => item.id === node.dataset.liveFeed))))
  }

  function renderGallery() {
    if (!state.me) {
      scr.innerHTML = '<div class="live-empty"><span><b>Войдите в аккаунт</b>После входа здесь будут ваши реальные изображения и видео.</span></div>'
      return
    }
    if (idx > 2) {
      scr.innerHTML = '<div class="live-empty"><span><b>Раздел пока не подключён</b>В основной галерее проекта сейчас хранятся изображения и видео.</span></div>'
      return
    }
    const items = state.gallery.filter((item) => idx === 0 || (idx === 1 ? item.mediaType === 'image' : item.mediaType === 'video'))
    if (!items.length) {
      scr.innerHTML = '<div class="live-empty"><span><b>Пока пусто</b>Создайте работу — она появится здесь автоматически.</span></div>'
      return
    }
    scr.innerHTML = `<div class="gal">${items.map((item) => `<span data-live-gallery="${html(item.id)}">${item.mediaType === 'video' ? `<video src="${html(item.media)}" poster="${html(item.thumb)}" muted playsinline preload="metadata"></video><i class="live-badge">Видео</i>` : `<img alt="" src="${html(item.thumb)}">`}</span>`).join('')}</div>`
    scr.querySelectorAll('[data-live-gallery]').forEach((node) => node.addEventListener('click', () => openMedia(items.find((item) => item.id === node.dataset.liveGallery))))
  }

  async function ensureFeed() {
    if (view !== 'feed') return
    const key = feedTypes[idx] || 'fresh'
    if (state.feedKey === key && state.feed.length) return
    state.feedKey = key
    try {
      const response = await api(`/feed?type=${encodeURIComponent(key)}&limit=20`)
      if (response.ok) state.feed = normalizeFeed(await response.json())
    } catch { state.feed = [] }
    if (view === 'feed' && state.feedKey === key) renderFeed()
  }

  async function loadGallery() {
    if (!state.me) { state.gallery = []; return }
    try {
      const response = await api('/gallery/items?limit=60')
      state.gallery = response.ok ? normalizeGallery(await response.json()) : []
    } catch { state.gallery = [] }
  }

  function updateProfile() {
    const profile = state.me?.profile || {}
    const account = state.me?.account || {}
    const name = profile.display_name || profile.first_name || 'Пользователь'
    const avatar = absoluteUrl(profile.avatar_url || (profile.avatar_preset ? `/avatars/${profile.avatar_preset}.webp` : '')) || I.a9
    av.src = avatar
    day = Number(account.daily_tokens_remaining ?? account.daily_tokens ?? 0)
    mon = Number(account.token_balance ?? 0)
    credits()
    const title = shYou.querySelector('div[style*="align-items"] span b')
    const note = shYou.querySelector('div[style*="align-items"] span span')
    const image = shYou.querySelector('div[style*="align-items"] img')
    if (title) title.textContent = name
    if (note) note.textContent = `${String(account.plan || 'mini').toUpperCase()} · профиль ИЗО АСА`
    if (image) image.src = avatar
    if (document.getElementById('dayB')) document.getElementById('dayB').textContent = String(day)
    if (document.getElementById('monB')) document.getElementById('monB').textContent = String(mon)
  }

  let fileAction = null
  const fileInput = document.createElement('input')
  fileInput.type = 'file'; fileInput.accept = 'image/*'; fileInput.hidden = true
  document.body.appendChild(fileInput)
  fileInput.addEventListener('change', async () => {
    const files = Array.from(fileInput.files || [])
    fileInput.value = ''
    if (!fileAction || !files.length) return
    const action = fileAction; fileAction = null
    const values = []
    for (const file of files) values.push(await preparedImage(file))
    action(values)
  })

  function chooseImages(multiple, action) {
    fileAction = action
    fileInput.multiple = multiple
    fileInput.click()
  }

  function preparedImage(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader()
      reader.onerror = () => reject(new Error('Не удалось прочитать изображение.'))
      reader.onload = () => {
        const image = new Image()
        image.onerror = () => reject(new Error('Не удалось открыть изображение.'))
        image.onload = () => {
          const maxSide = 1792
          const scale = Math.min(1, maxSide / Math.max(image.naturalWidth, image.naturalHeight))
          const width = Math.max(1, Math.round(image.naturalWidth * scale))
          const height = Math.max(1, Math.round(image.naturalHeight * scale))
          const canvas = document.createElement('canvas'); canvas.width = width; canvas.height = height
          canvas.getContext('2d').drawImage(image, 0, 0, width, height)
          resolve(canvas.toDataURL('image/jpeg', .92))
        }
        image.src = String(reader.result)
      }
      reader.readAsDataURL(file)
    })
  }

  function setupSketch(canvas) {
    const ratioValue = RATIOS[ratio]?.[0] || '1:1'
    const [rw, rh] = ratioValue.split(':').map(Number)
    canvas.width = Math.round(720 * rw / Math.max(rw, rh)); canvas.height = Math.round(720 * rh / Math.max(rw, rh))
    const ctx = canvas.getContext('2d'); ctx.lineWidth = Math.max(5, canvas.width / 90); ctx.lineCap = 'round'; ctx.strokeStyle = '#111'
    const reset = () => { ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, canvas.width, canvas.height) }
    if (state.sketchData) {
      const image = new Image(); image.onload = () => { reset(); ctx.drawImage(image, 0, 0, canvas.width, canvas.height) }; image.src = state.sketchData
    } else reset()
    let drawing = false
    const point = (event) => { const rect = canvas.getBoundingClientRect(); return [(event.clientX - rect.left) * canvas.width / rect.width, (event.clientY - rect.top) * canvas.height / rect.height] }
    canvas.addEventListener('pointerdown', (event) => { drawing = true; canvas.setPointerCapture(event.pointerId); const [x, y] = point(event); ctx.beginPath(); ctx.moveTo(x, y) })
    canvas.addEventListener('pointermove', (event) => { if (!drawing) return; const [x, y] = point(event); ctx.lineTo(x, y); ctx.stroke() })
    canvas.addEventListener('pointerup', () => { drawing = false; state.sketchData = canvas.toDataURL('image/png') })
  }

  function enhanceImage() {
    const selected = selectedImageModel()
    const modelRow = scr.querySelector('.modelrow .mt')
    if (modelRow) modelRow.innerHTML = `<span class="k">Модель</span><span class="v">${html(selected.label || 'ИЗО Base')}</span><span class="d2">реальная модель вашего тарифа</span>`
    const controls = scr.querySelectorAll('.ctrl')
    if (controls[1]) controls[1].querySelector('.v').textContent = `${QUAL[qual][0]} · ${selectedResolution()[1]}×${selectedResolution()[2]}`
    if (controls[2]) { controls[2].querySelector('.v').textContent = '1'; controls[2].setAttribute('aria-disabled', 'true') }
    const cost = Number(selected.tokenHint || 1)
    document.getElementById('cost').textContent = `${cost} кр.`

    const attach = scr.querySelector('[data-attach]')
    if (attach) {
      const clean = attach.cloneNode(true); attach.replaceWith(clean)
      clean.addEventListener('click', () => {
        if (idx === 2) return
        chooseImages(idx === 3, (values) => {
          if (idx === 3) { state.imageRefs = values.slice(0, 4); photo = values[0] || null } else { photo = values[0] || null }
          paintGen()
        })
      })
    }
    const clear = scr.querySelector('[data-clear]')
    if (clear) {
      const clean = clear.cloneNode(true); clear.replaceWith(clean)
      clean.addEventListener('click', () => { photo = null; state.imageRefs = []; paintGen() })
    }
    if (idx === 2 && gstate !== 'done') {
      const canvasHost = scr.querySelector('.canvas')
      if (canvasHost) { canvasHost.innerHTML = '<canvas class="phone-sketch-canvas" aria-label="Холст для наброска"></canvas>'; setupSketch(canvasHost.querySelector('canvas')) }
    }
    if (idx === 3 && state.imageRefs.length && gstate !== 'done') {
      const canvasHost = scr.querySelector('.canvas')
      if (canvasHost) canvasHost.innerHTML = `<div class="live-source-grid">${state.imageRefs.map((src) => `<img alt="" src="${html(src)}">`).join('')}</div>`
    }
    if (gstate === 'done' && state.imageResults.length) {
      const results = scr.querySelector('.four')
      if (results) results.innerHTML = state.imageResults.map((src) => `<div class="g sel"><img alt="Результат генерации" src="${html(src)}"></div>`).join('')
    }
    if (gstate === 'busy' && state.imageJob) {
      const progress = Math.max(1, Math.min(99, Number(state.imageJob.progress || 1)))
      const bar = document.getElementById('bar'); const label = document.getElementById('pct')
      if (bar) bar.style.width = `${progress}%`; if (label) label.textContent = `ГОТОВО НА ${Math.round(progress)}%`
    }
  }

  async function runImage() {
    if (!state.me) { toast('Войдите в аккаунт, чтобы создать изображение'); openSheet('you'); return }
    const prompt = gp.value.trim()
    if (!prompt) { toast('Опишите, что нужно создать'); gp.focus(); return }
    const modeKey = imageMode()
    if (modeKey === 'image_to_image' && !photo) { toast('Сначала выберите исходное фото'); return }
    if (modeKey === 'paint' && !state.sketchData) {
      const canvas = scr.querySelector('.phone-sketch-canvas'); if (canvas) state.sketchData = canvas.toDataURL('image/png')
    }
    if (modeKey === 'edit' && state.imageRefs.length < 2) { toast('Для сборки добавьте минимум два изображения'); return }
    const selected = selectedImageModel(); const [resolutionId, width, height] = selectedResolution()
    const stylePrompt = style >= 0 ? `. Стиль: ${STYLES[style]?.[1] || ''}.` : ''
    const body = {
      mode: modeKey, provider: selected.provider || 'comfyui', prompt: `${prompt}${stylePrompt}`,
      negativePrompt: '', seed: Math.floor(Math.random() * 2147483646) + 1,
      width, height, resolutionId, steps: selected.provider === 'comfyui' ? 4 : 4, cfg: 1, guidance: 3.5,
      strength: .75, modelProfile: selected.modelProfile || 'local_flux_klein', loras: [],
    }
    if (modeKey === 'image_to_image') body.inputImage1 = photo
    if (modeKey === 'paint') body.canvas = state.sketchData
    if (modeKey === 'edit') body.inputImages = state.imageRefs.map((image, index) => ({ index: index + 1, role: index === 0 ? 'base' : 'reference', image }))
    gJobTab = idx; gstate = 'busy'; state.imagePhase = 'busy'; state.imageResults = []; state.lastError = ''; paintGen()
    try {
      const response = await api('/generate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
      if (!response.ok) throw new Error(await responseMessage(response, 'Не удалось запустить генерацию.'))
      state.imageJob = generation(await response.json())
      while (state.imageJob.id && !['completed', 'failed', 'cancelled', 'expired'].includes(state.imageJob.status)) {
        await sleep(1400)
        const jobResponse = await api(`/jobs/${encodeURIComponent(state.imageJob.id)}`)
        if (!jobResponse.ok) throw new Error(await responseMessage(jobResponse, 'Не удалось получить состояние генерации.'))
        state.imageJob = generation(await jobResponse.json()); if (view === 'img') paintGen()
      }
      if (state.imageJob.status !== 'completed' || !state.imageJob.resultUrl) throw new Error(state.imageJob.error || 'Изображение не создано.')
      state.imageResults = [state.imageJob.resultUrl]; gstate = 'done'; state.imagePhase = 'done'; paintGen(); toast('Изображение готово и добавлено в галерею')
      await Promise.all([loadGallery(), loadMe()]); if (view === 'img') paintGen()
    } catch (error) {
      state.lastError = error.message || 'Генерация временно недоступна.'; gstate = 'idle'; state.imagePhase = 'error'; paintGen(); toast(state.lastError)
    }
  }

  function videoSourceHtml() {
    const need = idx === 1 ? 1 : idx === 2 ? 2 : 4
    if (!state.videoSources.length) return `<div class="mid"><div class="t">${idx === 1 ? 'Добавьте исходное изображение' : idx === 2 ? 'Добавьте начальный и конечный кадры' : 'Добавьте изображения-референсы'}</div><button class="big" data-live-video-upload><svg viewBox="0 0 24 24"><path d="M12 5v14M5 12h14" stroke="#fff" stroke-width="2" fill="none"/></svg></button></div>`
    return `<div class="live-source-grid">${state.videoSources.slice(0, need).map((src) => `<img alt="" src="${html(src)}">`).join('')}</div><div class="live-status">Нажмите на кадры, чтобы заменить их</div>`
  }

  function enhanceVideo() {
    syncVideoOptions()
    const selected = selectedVideoModel()
    const player = scr.querySelector('.player')
    if (player && state.videoAspect) player.style.aspectRatio = state.videoAspect.replace(':', '/')
    if (player && vstate === 'done' && state.videoResultUrl) player.innerHTML = `<video class="live-preview" src="${html(state.videoResultUrl)}" controls autoplay playsinline></video>`
    else if (player && idx > 0 && vstate !== 'busy') {
      player.innerHTML = videoSourceHtml()
      const upload = player.querySelector('[data-live-video-upload]') || player
      upload.addEventListener('click', () => chooseImages(idx !== 1, (values) => { state.videoSources = values.slice(0, idx === 3 ? 4 : idx === 2 ? 2 : 1); paintVid(); estimateVideo() }))
    }
    const controls = scr.querySelectorAll('.ctrl')
    if (controls[0]) controls[0].querySelector('.v').textContent = state.videoAspect || '—'
    if (controls[1]) controls[1].querySelector('.v').textContent = state.videoDuration ? `${state.videoDuration} с` : '—'
    if (controls[2]) controls[2].querySelector('.v').textContent = state.videoResolution || '—'
    const rows = scr.querySelectorAll('.modelrow')
    const modelRow = rows[1]?.querySelector('.mt')
    if (modelRow) modelRow.innerHTML = `<span class="k">Модель</span><span class="v">${html(selected?.name || 'Нет доступной модели')}</span><span class="d2">${html(videoModelDescription(selected))}</span>`
    const audioRow = rows[2]?.querySelector('.mt')
    if (audioRow) audioRow.innerHTML = `<span class="k">Звук</span><span class="v">${state.videoAudio ? 'Включён' : 'Выключен'}</span><span class="d2">${selected?.generateAudio === false ? 'эта модель создаёт видео без звука' : 'генерировать звук вместе с роликом'}</span>`
    document.getElementById('cost').textContent = state.videoEstimate?.chargedTokens ? `${state.videoEstimate.chargedTokens} кр.` : `${Number(selected?.publicPricing?.fromTokens || 0) || '—'} кр.`
    document.getElementById('run').disabled = vstate === 'busy' || !selected
    if (vstate === 'busy' && state.videoJob) {
      vstage = Math.min(3, Math.floor(Number(state.videoJob.progress || 0) / 25))
      const stage = scr.querySelector('.stagebox p'); if (stage) stage.textContent = `Сервер обрабатывает видео · ${Math.round(Number(state.videoJob.progress || 0))}%`
    }
  }

  async function estimateVideo() {
    syncVideoOptions(); const selected = selectedVideoModel()
    if (!state.me || !selected || !state.videoDuration || !state.videoResolution || !state.videoAspect) return
    const body = { mode: videoMode(), model: selected.id, prompt: gp.value.trim() || 'preview', duration: state.videoDuration, resolution: state.videoResolution, aspectRatio: state.videoAspect, generateAudio: selected.generateAudio !== false && state.videoAudio, firstFrame: state.videoSources[0] || null, lastFrame: state.videoSources[1] || null, references: videoMode() === 'reference_to_video' ? state.videoSources : [] }
    try {
      const response = await api('/video/estimate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
      state.videoEstimate = response.ok ? await response.json() : null
    } catch { state.videoEstimate = null }
    if (view === 'vid') enhanceVideo()
  }

  async function runVideo() {
    if (!state.me) { toast('Войдите в аккаунт, чтобы создать видео'); openSheet('you'); return }
    const selected = selectedVideoModel(); const prompt = gp.value.trim(); const modeKey = videoMode()
    if (!selected) { toast('Для этого режима нет доступной видеомодели'); return }
    if (!prompt) { toast('Опишите сцену и движение'); gp.focus(); return }
    if (modeKey === 'image_to_video' && !state.videoSources[0]) { toast('Добавьте исходное изображение'); return }
    if (modeKey === 'first_last_frame' && state.videoSources.length < 2) { toast('Добавьте начальный и конечный кадры'); return }
    if (modeKey === 'reference_to_video' && !state.videoSources.length) { toast('Добавьте хотя бы один референс'); return }
    syncVideoOptions()
    const body = { mode: modeKey, model: selected.id, prompt, duration: state.videoDuration, resolution: state.videoResolution, aspectRatio: state.videoAspect, generateAudio: selected.generateAudio !== false && state.videoAudio, firstFrame: state.videoSources[0] || null, lastFrame: state.videoSources[1] || null, references: modeKey === 'reference_to_video' ? state.videoSources : [] }
    vJobTab = idx; vstate = 'busy'; vstage = 0; state.videoResultUrl = ''; state.lastError = ''; paintVid()
    try {
      const response = await api('/video/generate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
      if (!response.ok) throw new Error(await responseMessage(response, 'Не удалось запустить видео.'))
      state.videoJob = await response.json()
      while (!['completed', 'failed', 'cancelled', 'expired'].includes(String(state.videoJob.status || ''))) {
        await sleep(2500)
        const historyResponse = await api('/video/history?limit=40')
        if (!historyResponse.ok) throw new Error(await responseMessage(historyResponse, 'Не удалось получить состояние видео.'))
        const rows = (await historyResponse.json())?.items || []
        state.videoJob = rows.find((item) => item.id === state.videoJob.id) || state.videoJob
        if (view === 'vid') paintVid()
      }
      if (state.videoJob.status !== 'completed' || !state.videoJob.videoUrl) throw new Error(state.videoJob.error || 'Видео не создано.')
      state.videoResultUrl = absoluteUrl(state.videoJob.videoUrl); vstate = 'done'; await Promise.all([loadGallery(), loadMe()]); paintVid(); toast('Видео готово и добавлено в галерею')
    } catch (error) {
      state.lastError = error.message || 'Генерация временно недоступна.'; vstate = 'idle'; paintVid(); toast(state.lastError)
    }
  }

  function realPick(title, items, current, choose) {
    shPick.innerHTML = `<div class="grab"></div><div class="shead"><h4>${html(title)}</h4>${X}</div>${items.map((item, index) => `<div class="pick ${item.disabled ? 'disabled' : ''} ${index === current ? 'on' : ''}" data-live-pick="${index}"><span class="fig">${item.icon || IC.cube}</span><span><b>${html(item.label)}</b><span class="ds">${html(item.description || '')}</span></span>${item.price ? `<span class="live-price">${html(item.price)}</span>` : ''}</div>`).join('')}`
    shPick.querySelectorAll('[data-live-pick]').forEach((node) => node.addEventListener('click', () => { const item = items[Number(node.dataset.livePick)]; if (!item || item.disabled) return; choose(item, Number(node.dataset.livePick)); closeSheets() }))
    openSheet('pick')
  }

  const demoOpenPick = openPick
  openPick = function phoneOpenPick(kind) {
    if (view === 'img' && kind === 'model') {
      const models = getImageModels(); const selected = selectedImageModel()
      return realPick('Модель', models.map((item) => ({ label: item.label || item.id, description: item.id === 'server:local_flux_klein' ? 'Базовая модель ИЗО АСА' : 'Модель API вашего тарифа', price: `${Number(item.tokenHint || 1)} кр.` })), models.findIndex((item) => item.id === selected.id), (_item, index) => { state.imageModelByMode[imageMode()] = models[index].id; model = index; if (!qualityAllowed(qual)) qual = Math.max(0, [0, 1, 2, 3].filter(qualityAllowed).pop() || 0); paintGen() })
    }
    if (view === 'img' && kind === 'qual') {
      return realPick('Качество', QUAL.map((item, index) => { const entry = resolutionTable[RATIOS[ratio][0]][item[0]]; return { label: item[0], description: `${entry[1]} × ${entry[2]}`, disabled: !qualityAllowed(index), icon: item[0] } }), qual, (_item, index) => { qual = index; paintGen() })
    }
    if (view === 'img' && kind === 'cnt') return realPick('Количество', [{ label: '1 вариант', description: 'Одна реальная задача генерации', icon: '1' }], 0, () => { cnt = 0; paintGen() })
    if (view === 'vid' && ['model', 'vf', 'vd', 'vq'].includes(kind)) {
      syncVideoOptions(); const selected = selectedVideoModel()
      if (kind === 'model') {
        const models = getVideoModels(); return realPick('Видеомодель', models.map((item) => ({ label: item.name || item.id, description: videoModelDescription(item), price: item.publicPricing?.fromTokens ? `от ${item.publicPricing.fromTokens} кр.` : '' })), models.findIndex((item) => item.id === selected?.id), (_item, index) => { state.videoModelByMode[videoMode()] = models[index].id; syncVideoOptions(); state.videoEstimate = null; paintVid(); estimateVideo() })
      }
      const source = kind === 'vf' ? (selected?.supportedAspectRatios || []) : kind === 'vd' ? (selected?.supportedDurations || []) : (selected?.supportedResolutions || [])
      const current = kind === 'vf' ? state.videoAspect : kind === 'vd' ? state.videoDuration : state.videoResolution
      return realPick(kind === 'vf' ? 'Формат кадра' : kind === 'vd' ? 'Длительность' : 'Качество', source.map((value) => ({ label: kind === 'vd' ? `${value} с` : String(value), description: 'поддерживается выбранной моделью', icon: kind === 'vd' ? String(value) : String(value) })), source.indexOf(current), (_item, index) => { if (kind === 'vf') state.videoAspect = source[index]; else if (kind === 'vd') state.videoDuration = source[index]; else state.videoResolution = source[index]; state.videoEstimate = null; paintVid(); estimateVideo() })
    }
    return demoOpenPick(kind)
  }

  const demoOpenVid = openVid
  openVid = function phoneOpenVid(kind) {
    if (kind === 'vsnd') {
      const selected = selectedVideoModel()
      if (selected?.generateAudio === false) { toast('Выбранная модель создаёт видео без звука'); return }
      state.videoAudio = !state.videoAudio; vsnd = state.videoAudio; paintVid(); estimateVideo(); return
    }
    if (kind === 'vcam') return demoOpenVid(kind)
    return openPick(kind)
  }

  const demoPaintGen = paintGen
  paintGen = function phonePaintGen() { demoPaintGen(); enhanceImage() }
  const demoPaintVid = paintVid
  paintVid = function phonePaintVid() { demoPaintVid(); enhanceVideo() }
  const demoPaintSnd = paintSnd
  paintSnd = function phonePaintSnd() {
    demoPaintSnd()
    scr.innerHTML = '<div class="live-empty"><span><b>Звук пока не подключён</b>В проекте нет пользовательского API озвучки и музыки, поэтому этот экран не имитирует готовый результат.</span></div>'
    document.getElementById('run').disabled = true; document.getElementById('cost').textContent = '—'
  }
  const demoPaintChat = paintChat
  paintChat = function phonePaintChat() {
    demoPaintChat()
    scr.innerHTML = '<div class="live-empty"><span><b>Чат пока не подключён</b>Публичного API чата в проекте сейчас нет. Демонстрационные ответы отключены.</span></div>'
    chatgp.disabled = true; chatSend.disabled = true
  }

  const demoPaint = paint
  paint = function phonePaint() {
    demoPaint()
    if (view !== 'chat') { chatgp.disabled = false; chatSend.disabled = false }
    if (view === 'feed') { renderFeed(); ensureFeed() }
    if (view === 'gal') renderGallery()
    if (view === 'vid') { syncVideoOptions(); estimateVideo() }
  }
  run = runImage
  runVid = runVideo
  runSnd = () => toast('Раздел звука пока не подключён к серверу')

  async function loadMe() {
    try {
      const response = await api('/me-v2')
      state.me = response.ok ? await response.json() : null
    } catch { state.me = null }
    updateProfile()
  }

  async function loadInitial() {
    await Promise.all([
      loadMe(),
      api('/feed?type=top&limit=20').then(async (response) => { if (response.ok) { state.feed = normalizeFeed(await response.json()); state.feedKey = 'top' } }).catch(() => undefined),
      api('/video/config').then(async (response) => { if (response.ok) state.videoConfig = await response.json() }).catch(() => undefined),
    ])
    if (state.me) {
      await Promise.all([
        loadGallery(),
        api('/model-access').then(async (response) => { if (response.ok) state.modelAccess = await response.json() }).catch(() => undefined),
      ])
    }
    syncVideoOptions(); state.ready = true; paint()
    document.dispatchEvent(new CustomEvent('izo-phone-ready', { detail: { authenticated: Boolean(state.me) } }))
  }

  loadInitial()
})()
