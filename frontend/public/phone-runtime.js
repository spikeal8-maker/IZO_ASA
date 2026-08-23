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
    imageViewer: { open: false, scale: 1 },
    sketchData: '',
    sketchTool: 'brush',
    sketchColor: '#111111',
    sketchSize: 12,
    sketchHistory: [],
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
    lastImageRequest: null,
    chatThreads: {},
    chatRoute: 'auto',
    chatImages: [],
    chatFiles: [],
    chatBusy: false,
    recording: null,
    lastError: '',
  }
  window.__IZO_PHONE_RUNTIME__ = state

  const styleNode = document.createElement('style')
  styleNode.textContent = `
    .live-empty{min-height:220px;border-radius:22px;background:var(--s1);box-shadow:inset 0 0 0 1px var(--edge);display:grid;place-items:center;text-align:center;padding:26px;color:var(--tx2);font:650 12px/1.5 inherit}
    .live-empty b{display:block;color:var(--tx);font:760 15px/1.25 inherit;margin-bottom:5px}
    .live-badge{position:absolute;left:8px;top:8px;border-radius:9px;padding:5px 7px;background:rgba(6,7,10,.66);color:#fff;font:750 9px/1 inherit;backdrop-filter:blur(10px)}
    .feed-like{position:absolute;right:7px;bottom:7px;min-width:42px;height:28px;border:0;border-radius:999px;padding:0 9px;background:rgba(6,7,10,.48);color:#fff;display:flex;align-items:center;justify-content:center;gap:5px;font:760 10px/1 inherit;backdrop-filter:blur(12px) saturate(130%);box-shadow:inset 0 0 0 1px rgba(255,255,255,.13);cursor:pointer}
    .feed-like .heart{font-size:16px;line-height:1;color:#fff}.feed-like[aria-pressed="true"] .heart{color:#ff5e91;text-shadow:0 0 12px rgba(255,64,130,.75)}.feed-like:disabled{opacity:.65}
    .live-preview{width:100%;max-height:58vh;border-radius:18px;object-fit:contain;background:#050509;display:block}
    .live-meta{display:grid;gap:5px;padding:10px 2px 2px;color:var(--tx2);font:650 12px/1.4 inherit}.live-meta b{color:var(--tx);font-size:14px}
    .live-source-grid{width:100%;height:100%;display:grid;grid-template-columns:repeat(2,1fr);gap:7px;padding:8px}
    .live-source-grid.single{grid-template-columns:1fr}.live-source-item{position:relative;min-height:96px;border-radius:14px;overflow:hidden;background:#08090d;box-shadow:inset 0 0 0 1px var(--edge)}
    .live-source-grid img{width:100%;height:100%;min-height:96px;max-height:180px;object-fit:contain;border-radius:14px}
    .live-source-remove{position:absolute;right:6px;top:6px;width:25px;height:25px;border:0;border-radius:50%;background:rgba(6,7,10,.74);color:#fff;font:700 16px/1 inherit;cursor:pointer;backdrop-filter:blur(8px)}
    .live-source-add{min-height:96px;border:1px dashed var(--edge2);border-radius:14px;background:var(--s2);color:var(--tx2);display:grid;place-items:center;gap:4px;padding:12px;font:700 11px/1.3 inherit;cursor:pointer}.live-source-add b{font-size:22px;color:var(--quiet)}
    .canvas{aspect-ratio:16/9!important;max-height:none!important;min-height:0;background:#050509}
    .canvas.live-result-host{height:auto;max-height:none!important;aspect-ratio:16/9!important;background:#050509}
    .live-result-media{position:absolute;inset:0;display:grid;place-items:center;overflow:hidden}.canvas .live-result-preview{display:block;width:auto!important;height:auto!important;max-width:100%;max-height:100%;object-fit:contain;object-position:center;cursor:zoom-in;touch-action:manipulation;user-select:none;-webkit-user-drag:none}
    .phone-preview-empty{position:absolute;inset:0;display:grid;place-items:center;isolation:isolate;overflow:hidden}
    .phone-preview-empty-bg{position:absolute;inset:0;width:100%!important;height:100%!important;object-fit:cover!important;filter:saturate(.82) brightness(.58);transform:scale(1.015);z-index:-2}
    .phone-preview-empty:after{content:"";position:absolute;inset:0;background:linear-gradient(180deg,rgba(4,5,9,.12),rgba(4,5,9,.68)),radial-gradient(circle at 50% 38%,rgba(141,87,255,.08),transparent 55%);z-index:-1}
    .phone-preview-empty-copy{display:grid;place-items:center;gap:9px;max-width:84%;padding:18px;text-align:center;color:#fff;text-shadow:0 2px 14px rgba(0,0,0,.7)}
    .phone-preview-empty-copy .spark{margin:0;font-size:23px}.phone-preview-empty-copy b{font:760 13px/1.35 inherit}.phone-preview-empty-copy span{font:620 10.5px/1.4 inherit;color:rgba(255,255,255,.74)}
    .phone-preview-empty-copy button{border:0;border-radius:13px;padding:10px 15px;background:linear-gradient(145deg,var(--act),var(--act2));color:#fff;font:740 11px/1 inherit;box-shadow:0 12px 28px -12px var(--glow);cursor:pointer}
    .live-image-actions{position:absolute;left:7px;bottom:7px;display:flex;gap:5px;z-index:3}
    .live-image-action,.live-result-dismiss{width:30px;height:30px;border:0;border-radius:50%;padding:0;background:rgba(8,9,14,.42);color:rgba(255,255,255,.9);display:grid;place-items:center;backdrop-filter:blur(12px) saturate(135%);box-shadow:inset 0 0 0 1px rgba(255,255,255,.12);text-decoration:none;cursor:pointer;opacity:.82}
    .live-image-action:active,.live-result-dismiss:active{opacity:1;transform:scale(.94)}.live-image-action.primary{background:rgba(127,55,224,.48)}.live-image-action svg{width:14px;height:14px;stroke:currentColor;fill:none;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}.live-result-dismiss{position:absolute;right:7px;top:7px;z-index:4;font:400 19px/1 inherit}
    .phone-visually-hidden{position:absolute!important;width:1px!important;height:1px!important;padding:0!important;margin:-1px!important;overflow:hidden!important;clip:rect(0,0,0,0)!important;white-space:nowrap!important;border:0!important}
    .live-image-viewer[hidden]{display:none!important}.live-image-viewer{position:fixed;inset:0;z-index:1000;background:#020307;display:grid;grid-template-rows:auto 1fr;touch-action:none;overscroll-behavior:contain}
    .live-image-viewer-bar{display:flex;align-items:center;gap:8px;padding:max(12px,env(safe-area-inset-top)) 12px 10px;color:#fff;background:linear-gradient(180deg,rgba(2,3,7,.96),rgba(2,3,7,.68));z-index:2}
    .live-image-viewer-bar b{font:760 13px/1 inherit}.live-image-viewer-bar span{font:650 10px/1 inherit;color:#aaa}.live-image-viewer-bar button{border:0;border-radius:11px;padding:9px 11px;background:#171922;color:#fff;font:720 11px/1 inherit;cursor:pointer}.live-image-viewer-bar [data-viewer-close]{margin-left:auto;width:36px;height:36px;padding:0;border-radius:50%;font-size:20px}
    .live-image-viewer-stage{position:relative;min-height:0;overflow:hidden;display:grid;place-items:center;touch-action:none}.live-image-viewer-stage img{width:100%;height:100%;object-fit:contain;transform-origin:center;will-change:transform;user-select:none;-webkit-user-drag:none;touch-action:none}
    .canvas.phone-sketch-host{aspect-ratio:var(--sketch-aspect)!important;background:#fff}.phone-sketch-canvas{width:100%;height:100%;max-width:none;margin:auto;touch-action:none;background:#fff;display:block}
    .phone-sketch-tools{position:relative;z-index:4;display:flex;align-items:center;justify-content:center;gap:5px;padding:6px;border-radius:14px;background:rgba(7,8,12,.76);backdrop-filter:blur(16px);box-shadow:inset 0 0 0 1px rgba(255,255,255,.12)}
    .phone-sketch-tool{width:34px;height:34px;border:0;border-radius:10px;background:rgba(255,255,255,.08);color:#fff;display:grid;place-items:center;cursor:pointer;position:relative}.phone-sketch-tool[aria-pressed="true"]{background:linear-gradient(145deg,var(--act),var(--act2));box-shadow:0 8px 18px -10px var(--glow)}
    .phone-sketch-tool svg{width:17px;height:17px;stroke:currentColor;fill:none;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}.phone-sketch-tool .sketch-dot{width:13px;height:13px;border-radius:50%;background:var(--sketch-color,#111);box-shadow:0 0 0 2px #fff}.phone-sketch-tool input{position:absolute;inset:0;opacity:0;width:100%;height:100%;cursor:pointer}
    .phone-sketch-fullscreen-close{display:none}.canvas.phone-sketch-host.phone-sketch-fullscreen{position:fixed;inset:0;z-index:1100;width:100vw;height:100vh;aspect-ratio:auto!important;border-radius:0;padding:54px 10px 76px;background:#090a0f;box-shadow:none}.phone-sketch-fullscreen .phone-sketch-canvas{width:min(calc(100vw - 20px),calc((100vh - 140px)*var(--sketch-ratio)));height:auto;max-width:calc(100vw - 20px);max-height:calc(100vh - 140px);aspect-ratio:var(--sketch-aspect)}
    .phone-sketch-fullscreen .phone-sketch-fullscreen-close{display:grid;place-items:center;position:fixed;right:12px;top:max(12px,env(safe-area-inset-top));width:34px;height:34px;border:0;border-radius:50%;background:rgba(255,255,255,.1);color:#fff;font:400 22px/1 inherit;z-index:1102}.phone-sketch-open .phone-sketch-tools{position:fixed;left:10px;right:10px;bottom:max(10px,env(safe-area-inset-bottom));z-index:1102}
    .phone-hold-tooltip{position:fixed;left:50%;top:50%;z-index:1200;max-width:min(260px,calc(100vw - 28px));transform:translate(-50%,-50%);padding:9px 12px;border-radius:11px;background:rgba(12,13,19,.96);color:#fff;font:720 11px/1.35 inherit;text-align:center;box-shadow:0 14px 34px rgba(0,0,0,.45),inset 0 0 0 1px rgba(255,255,255,.15);pointer-events:none;opacity:0;transition:opacity .16s}.phone-hold-tooltip.on{opacity:1}
    .sheet.live-dragging{transition:none!important;will-change:transform}.sheet{touch-action:pan-y}
    .live-status{position:absolute;left:10px;right:10px;bottom:10px;border-radius:12px;padding:8px 10px;background:rgba(6,7,10,.72);color:#fff;font:700 10px/1.3 inherit;backdrop-filter:blur(10px)}
    .pick.disabled{opacity:.38;pointer-events:none}.pick .live-price{margin-left:auto;font:750 11px/1 inherit;padding:5px 8px;border:1px solid;border-radius:999px;white-space:nowrap}.token-kind-daily{color:#dff12b!important;border-color:rgba(223,241,43,.5)!important;background:rgba(223,241,43,.1)!important}.token-kind-main{color:#dd9cff!important;border-color:rgba(205,117,255,.58)!important;background:rgba(157,64,225,.16)!important}#cost.token-kind-daily,#cost.token-kind-main{display:inline-flex;align-items:center;padding:3px 7px;border:1px solid;border-radius:999px;opacity:1}.gen-btn #cost.token-kind-daily{color:#fff28a!important;border-color:rgba(255,244,133,.5)!important;background:rgba(56,47,0,.3)!important}.gen-btn #cost.token-kind-main{color:#f3d7ff!important;border-color:rgba(241,210,255,.5)!important;background:rgba(65,18,100,.38)!important}
    .card video{width:100%;display:block}.gal span{position:relative}.gal video{width:100%;aspect-ratio:1;object-fit:cover;display:block}
    .live-recording{position:relative;background:#e34f61!important;color:#fff!important;box-shadow:0 0 0 1px rgba(255,95,113,.8),0 0 20px rgba(255,78,99,.48)!important}
    .live-recording:before,.live-recording:after{content:"";position:absolute;inset:-5px;border:1px solid rgba(255,95,113,.72);border-radius:50%;animation:phoneVoicePulse 1.35s infinite;pointer-events:none}
    .live-recording:after{animation-delay:.66s}.live-transcribing{animation:phoneVoiceGlow 1s ease-in-out infinite alternate}
    @keyframes phoneVoicePulse{to{inset:-18px;opacity:0}}@keyframes phoneVoiceGlow{to{filter:brightness(1.35)}}
    .live-voice-status{display:flex;align-items:center;gap:9px;margin:0 2px 8px;padding:8px 11px;border-radius:13px;background:rgba(225,63,84,.13);box-shadow:inset 0 0 0 1px rgba(255,96,115,.28);color:var(--tx);font:700 11px/1.25 inherit}
    .live-voice-status .dot{width:8px;height:8px;border-radius:50%;background:#ff5067;box-shadow:0 0 12px rgba(255,80,103,.8);animation:phoneVoiceGlow .55s infinite alternate}
    .live-voice-status .wave{height:18px;display:flex;gap:2px;align-items:center;flex:1}.live-voice-status .wave i{width:2px;flex:1;max-width:3px;border-radius:3px;background:#ff7184;animation:phoneWave .75s ease-in-out infinite alternate}.live-voice-status .wave i:nth-child(2n){animation-delay:.18s}.live-voice-status .wave i:nth-child(3n){animation-delay:.34s}
    @keyframes phoneWave{from{height:4px;opacity:.45}to{height:17px;opacity:1}}
    .live-voice-status time{font-variant-numeric:tabular-nums;color:#ff8292}.live-voice-status.transcribing{background:rgba(109,74,255,.13);box-shadow:inset 0 0 0 1px rgba(150,112,255,.28)}
    .live-chat-empty{padding-top:34px}.live-chat-turn{display:flex;flex-direction:column;gap:8px}.live-chat-turn .ai.pending{opacity:.72}.live-chat-turn .ai.error{box-shadow:inset 0 0 0 1px rgba(255,91,107,.42);color:#ff9eaa}
    .live-chat-attachments{display:flex;gap:6px;overflow-x:auto;padding:9px 12px 0}.live-chat-attachments:empty{display:none}.live-chat-attachment{position:relative;flex:0 0 auto;width:54px;height:54px;border-radius:12px;background:var(--s2);overflow:hidden;box-shadow:inset 0 0 0 1px var(--edge)}
    .live-chat-attachment img{width:100%;height:100%;object-fit:cover}.live-chat-attachment.file{width:auto;max-width:140px;padding:8px 28px 8px 10px;height:auto;min-height:40px;color:var(--tx2);font:700 10px/1.25 inherit;display:flex;align-items:center}.live-chat-attachment button{position:absolute;right:3px;top:3px;width:20px;height:20px;border:0;border-radius:50%;background:rgba(5,6,10,.78);color:#fff;cursor:pointer}
    .live-chat-user-images{display:flex;gap:5px;margin-bottom:7px}.live-chat-user-images img{width:56px;height:56px;border-radius:10px;object-fit:cover}.live-chat-actions{display:flex;gap:6px;overflow-x:auto;padding:7px 2px 0}.live-chat-actions button{flex:0 0 auto;border:0;border-radius:10px;padding:8px 10px;background:var(--s2);color:var(--tx2);font:700 10.5px/1 inherit;cursor:pointer;box-shadow:inset 0 0 0 1px var(--edge)}
    .live-spinner{display:inline-block;width:13px;height:13px;border:2px solid var(--edge2);border-top-color:var(--act);border-radius:50%;animation:phoneSpin .8s linear infinite;vertical-align:-2px;margin-right:7px}@keyframes phoneSpin{to{transform:rotate(360deg)}}
  `
  document.head.appendChild(styleNode)

  const imageMode = () => idx === 0 ? 'text_to_image' : idx === 1 ? (state.imageRefs.length > 1 ? 'edit' : 'image_to_image') : idx === 2 ? 'paint' : 'text_to_image'
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

  const actionIcons = {
    download: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 4v11M7.5 11L12 15.5 16.5 11M5 20h14"/></svg>',
    share: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="18" cy="5" r="2.5"/><circle cx="6" cy="12" r="2.5"/><circle cx="18" cy="19" r="2.5"/><path d="M8.2 10.8l7.6-4.5M8.2 13.2l7.6 4.5"/></svg>',
    animate: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="3"/><path d="M9 8.5v7l6-3.5z"/></svg>',
    brush: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14.5 4.5l5 5L9 20H4v-5z"/><path d="M12.5 6.5l5 5"/></svg>',
    eraser: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 18l-3-3 9.5-10 5.5 5.5-7.2 7.5z"/><path d="M9.5 9.2l5.5 5.5M7 18h12"/></svg>',
    undo: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 7L4 12l5 5"/><path d="M5 12h8a6 6 0 016 6"/></svg>',
    clear: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 7h14M9 7V4h6v3M8 10v8M12 10v8M16 10v8M7 7l1 14h8l1-14"/></svg>',
  }

  function imageModelDescription(item) {
    const supplied = String(item?.description || '').trim()
    if (supplied) return supplied.split(/(?<=[.!?])\s/)[0].slice(0, 118)
    const id = `${item?.id || ''} ${item?.label || ''}`.toLowerCase()
    if (/local_flux|izo base|server:local/.test(id)) return 'Фирменная модель: быстрое создание, фото и сборка.'
    if (/klein/.test(id)) return 'Быстрые изображения и недорогие варианты.'
    if (/flux.*flex|flex/.test(id)) return 'Гибкая стилизация и творческие варианты.'
    if (/flux.*max|\bmax\b/.test(id)) return 'Максимум деталей для сложных сцен.'
    if (/flux.*pro|\bpro\b/.test(id)) return 'Высокое качество, свет и композиция.'
    if (/seedream/.test(id)) return 'Яркие сцены, персонажи и быстрые идеи.'
    if (/gemini|nano banana/.test(id)) return 'Точное редактирование и следование описанию.'
    if (/gpt.*image/.test(id)) return 'Сложные инструкции, текст и логичная сцена.'
    if (/recraft.*vector/.test(id)) return 'Логотипы и чистая векторная графика.'
    if (/recraft/.test(id)) return 'Дизайн, постеры и коммерческие визуалы.'
    if (/grok/.test(id)) return 'Выразительные художественные сцены.'
    if (/riverflow/.test(id)) return 'Серийные варианты и быстрые концепты.'
    if (/auto/.test(id)) return 'Сам выберет подходящую модель под запрос.'
    return 'Универсальная модель для создания и редактирования.'
  }

  function emptyPreviewHtml(title, note, action = '') {
    return `<div class="phone-preview-empty"><img class="phone-preview-empty-bg" src="/phone-preview-placeholder.jpg" alt="" aria-hidden="true"><div class="phone-preview-empty-copy"><span class="spark">✦</span><b>${html(title)}</b>${note ? `<span>${html(note)}</span>` : ''}${action}</div></div>`
  }

  async function shareImage(src) {
    try {
      const url = absoluteUrl(src)
      const response = await fetch(url, { credentials: 'include' })
      if (!response.ok) throw new Error('download failed')
      const blob = await response.blob()
      const file = new File([blob], 'izo-asa-image.png', { type: blob.type || 'image/png' })
      if (navigator.share && (!navigator.canShare || navigator.canShare({ files: [file] }))) {
        await navigator.share({ title: 'Изображение ИЗО АСА', text: gp.value.trim() || undefined, files: [file] })
      } else if (navigator.share) {
        await navigator.share({ title: 'Изображение ИЗО АСА', text: gp.value.trim() || undefined, url })
      } else if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(url); toast('Ссылка на изображение скопирована')
      } else {
        window.open(url, '_blank', 'noopener,noreferrer')
      }
    } catch (error) {
      if (error?.name !== 'AbortError') toast('Не удалось открыть меню публикации')
    }
  }

  function animateImage(src) {
    try {
      const parsed = new URL(src, location.origin)
      state.videoSources = [parsed.origin === location.origin ? `${parsed.pathname}${parsed.search}` : parsed.toString()]
      gp.value = 'Плавно оживи изображение. Сохрани внешность, форму объектов и композицию. Добавь естественное движение камеры, света и деталей окружения.'
      gp.dispatchEvent(new Event('input', { bubbles: true }))
      go('vid', 1)
      toast('Изображение перенесено в видео')
    } catch { toast('Не удалось подготовить изображение для видео') }
  }

  const holdTooltip = document.createElement('div')
  holdTooltip.className = 'phone-hold-tooltip'; holdTooltip.setAttribute('role', 'tooltip'); document.body.appendChild(holdTooltip)
  const longPressBound = new WeakSet()
  let holdTooltipTimer = 0; let holdTooltipHideTimer = 0
  function showHoldTooltip(target, text) {
    clearTimeout(holdTooltipHideTimer); holdTooltip.textContent = text; holdTooltip.classList.add('on')
    const rect = target.getBoundingClientRect(); const top = rect.top > 90 ? rect.top - 46 : rect.bottom + 14
    holdTooltip.style.left = `${Math.max(24, Math.min(innerWidth - 24, rect.left + rect.width / 2))}px`; holdTooltip.style.top = `${top}px`; holdTooltip.style.transform = 'translate(-50%,-50%)'
    holdTooltipHideTimer = setTimeout(() => holdTooltip.classList.remove('on'), 1700)
  }
  function installLongPressHints(root = document) {
    root.querySelectorAll('button[aria-label],button[title],a[aria-label],[data-hint]').forEach((target) => {
      if (longPressBound.has(target)) return
      const hint = target.dataset.hint || target.getAttribute('aria-label') || target.getAttribute('title')
      if (!hint) return
      longPressBound.add(target)
      let startX = 0; let startY = 0; let shown = false
      const cancel = () => { clearTimeout(holdTooltipTimer); holdTooltipTimer = 0 }
      target.addEventListener('pointerdown', (event) => {
        if (!['touch', 'pen'].includes(event.pointerType)) return
        startX = event.clientX; startY = event.clientY; shown = false; cancel()
        holdTooltipTimer = setTimeout(() => { shown = true; showHoldTooltip(target, hint) }, 560)
      })
      target.addEventListener('pointermove', (event) => { if (Math.hypot(event.clientX - startX, event.clientY - startY) > 12) cancel() })
      target.addEventListener('pointerup', cancel); target.addEventListener('pointercancel', cancel)
      target.addEventListener('click', (event) => { if (!shown) return; shown = false; event.preventDefault(); event.stopImmediatePropagation() }, true)
    })
  }

  function installSheetSwipe(sheet) {
    if (sheet.dataset.swipeClose === 'true') return
    sheet.dataset.swipeClose = 'true'
    let drag = null
    sheet.addEventListener('pointerdown', (event) => {
      if (event.pointerType !== 'touch' || sheet.scrollTop > 0) return
      drag = { id: event.pointerId, x: event.clientX, y: event.clientY, lastY: event.clientY, at: performance.now(), active: false }
    })
    sheet.addEventListener('pointermove', (event) => {
      if (!drag || drag.id !== event.pointerId) return
      const dx = event.clientX - drag.x; const dy = event.clientY - drag.y
      if (!drag.active && (dy < 9 || Math.abs(dx) > dy * .85)) return
      drag.active = true; drag.lastY = event.clientY; event.preventDefault()
      sheet.classList.add('live-dragging'); sheet.style.transform = `translateY(${Math.max(0, dy)}px)`
    }, { passive: false })
    const finish = (event) => {
      if (!drag || drag.id !== event.pointerId) return
      const distance = Math.max(0, drag.lastY - drag.y); const speed = distance / Math.max(1, performance.now() - drag.at)
      const shouldClose = drag.active && (distance > 72 || speed > .55)
      sheet.classList.remove('live-dragging'); sheet.style.transform = ''; drag = null
      if (shouldClose) closeSheets()
    }
    sheet.addEventListener('pointerup', finish); sheet.addEventListener('pointercancel', finish)
  }

  const imageViewer = document.createElement('div')
  imageViewer.className = 'live-image-viewer'; imageViewer.hidden = true
  imageViewer.setAttribute('role', 'dialog'); imageViewer.setAttribute('aria-modal', 'true'); imageViewer.setAttribute('aria-label', 'Полноэкранный просмотр изображения')
  imageViewer.innerHTML = `<div class="live-image-viewer-bar"><b>Просмотр</b><span data-viewer-scale>100%</span><button type="button" data-viewer-reset>Вписать</button><button type="button" data-viewer-close aria-label="Закрыть">×</button></div><div class="live-image-viewer-stage"><img alt="Результат генерации крупным планом"></div>`
  document.body.appendChild(imageViewer)
  const viewerImage = imageViewer.querySelector('img')
  const viewerStage = imageViewer.querySelector('.live-image-viewer-stage')
  const viewerScale = imageViewer.querySelector('[data-viewer-scale]')
  let viewerTransform = { scale: 1, x: 0, y: 0 }
  const viewerPointers = new Map()
  let viewerPinch = null; let viewerLastTap = 0

  function applyViewerTransform() {
    if (viewerTransform.scale <= 1) viewerTransform = { scale: 1, x: 0, y: 0 }
    viewerImage.style.transform = `translate(${viewerTransform.x}px,${viewerTransform.y}px) scale(${viewerTransform.scale})`
    viewerScale.textContent = `${Math.round(viewerTransform.scale * 100)}%`
    state.imageViewer = { open: !imageViewer.hidden, scale: viewerTransform.scale }
  }
  function resetImageViewer() { viewerTransform = { scale: 1, x: 0, y: 0 }; applyViewerTransform() }
  function toggleImageViewerZoom() { viewerTransform = viewerTransform.scale > 1.05 ? { scale: 1, x: 0, y: 0 } : { scale: 2.5, x: 0, y: 0 }; applyViewerTransform() }
  function openImageViewer(src) {
    if (!src) return
    viewerImage.src = src; imageViewer.hidden = false; document.body.style.overflow = 'hidden'; resetImageViewer()
    imageViewer.querySelector('[data-viewer-close]').focus({ preventScroll: true })
  }
  function closeImageViewer() { imageViewer.hidden = true; document.body.style.overflow = ''; viewerPointers.clear(); viewerPinch = null; resetImageViewer() }
  imageViewer.querySelector('[data-viewer-close]').addEventListener('click', closeImageViewer)
  imageViewer.querySelector('[data-viewer-reset]').addEventListener('click', resetImageViewer)
  viewerStage.addEventListener('dblclick', (event) => { event.preventDefault(); toggleImageViewerZoom() })
  viewerStage.addEventListener('pointerdown', (event) => {
    event.preventDefault(); try { viewerStage.setPointerCapture?.(event.pointerId) } catch {}
    viewerPointers.set(event.pointerId, { x: event.clientX, y: event.clientY, startX: event.clientX, startY: event.clientY, at: Date.now() })
    if (viewerPointers.size === 2) {
      const [a, b] = [...viewerPointers.values()]
      viewerPinch = { distance: Math.hypot(a.x - b.x, a.y - b.y), scale: viewerTransform.scale }
    }
  })
  viewerStage.addEventListener('pointermove', (event) => {
    const point = viewerPointers.get(event.pointerId); if (!point) return
    const previous = { x: point.x, y: point.y }; point.x = event.clientX; point.y = event.clientY
    if (viewerPointers.size >= 2) {
      const [a, b] = [...viewerPointers.values()]
      const distance = Math.hypot(a.x - b.x, a.y - b.y)
      if (!viewerPinch) viewerPinch = { distance, scale: viewerTransform.scale }
      viewerTransform.scale = Math.max(1, Math.min(5, viewerPinch.scale * distance / Math.max(1, viewerPinch.distance)))
    } else if (viewerTransform.scale > 1) {
      viewerTransform.x += point.x - previous.x; viewerTransform.y += point.y - previous.y
    }
    applyViewerTransform()
  })
  const finishViewerPointer = (event) => {
    const point = viewerPointers.get(event.pointerId)
    if (point && event.pointerType === 'touch' && Date.now() - point.at < 280 && Math.hypot(point.x - point.startX, point.y - point.startY) < 10) {
      const now = Date.now(); if (now - viewerLastTap < 330) { toggleImageViewerZoom(); viewerLastTap = 0 } else viewerLastTap = now
    }
    viewerPointers.delete(event.pointerId); viewerPinch = null
  }
  viewerStage.addEventListener('pointerup', finishViewerPointer); viewerStage.addEventListener('pointercancel', finishViewerPointer)
  document.addEventListener('keydown', (event) => { if (event.key === 'Escape' && !imageViewer.hidden) closeImageViewer() })

  function installResultPreview(image) {
    if (!image) return
    image.classList.add('live-result-preview'); image.setAttribute('role', 'button'); image.setAttribute('tabindex', '0'); image.setAttribute('aria-label', 'Результат генерации. Дважды нажмите, чтобы открыть на весь экран')
    image.addEventListener('dblclick', (event) => { event.preventDefault(); openImageViewer(image.currentSrc || image.src) })
    let lastTap = 0
    image.addEventListener('pointerup', (event) => {
      if (event.pointerType !== 'touch') return
      const now = Date.now(); if (now - lastTap < 330) { openImageViewer(image.currentSrc || image.src); lastTap = 0 } else lastTap = now
    })
    image.addEventListener('keydown', (event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); openImageViewer(image.currentSrc || image.src) } })
  }

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
        likeCount: Math.max(0, Number(item.like_count || 0)),
        liked: Boolean(item.is_liked_by_me),
        likeBusy: false,
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

  function imageTokenKind(item) {
    return item?.provider === 'comfyui' || String(item?.id || '').startsWith('server:') ? 'daily' : 'main'
  }

  function videoTokenKind(item) {
    return item?.provider === 'local_ltx' || String(item?.id || '').startsWith('local/ltx-') ? 'daily' : 'main'
  }

  function paintCostTokenKind(kind) {
    const node = document.getElementById('cost')
    if (!node) return
    node.classList.toggle('token-kind-daily', kind === 'daily')
    node.classList.toggle('token-kind-main', kind === 'main')
    node.title = kind === 'daily' ? 'Дневные токены' : 'Основные токены'
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
    scr.innerHTML = `<div class="mas">${state.feed.map((item) => `<div class="card" data-live-feed="${html(item.id)}"><img alt="" src="${html(item.thumb)}"><button class="feed-like" type="button" data-feed-like="${html(item.id)}" aria-pressed="${item.liked}" aria-label="${item.liked ? 'Убрать отметку нравится' : 'Отметить нравится'}, ${item.likeCount}" ${item.likeBusy ? 'disabled' : ''}><span class="heart" aria-hidden="true">${item.liked ? '♥' : '♡'}</span><span>${item.likeCount}</span></button></div>`).join('')}</div>`
    scr.querySelectorAll('[data-live-feed]').forEach((node) => node.addEventListener('click', () => openMedia(state.feed.find((item) => item.id === node.dataset.liveFeed))))
    scr.querySelectorAll('[data-feed-like]').forEach((button) => button.addEventListener('click', (event) => {
      event.preventDefault(); event.stopPropagation()
      const item = state.feed.find((row) => row.id === button.dataset.feedLike)
      if (item) void toggleFeedLike(item)
    }))
  }

  async function toggleFeedLike(item) {
    if (item.likeBusy) return
    if (!state.me) { toast('Войдите в аккаунт, чтобы отметить работу'); openSheet('you'); return }
    const previous = { liked: item.liked, likeCount: item.likeCount }
    item.liked = !item.liked; item.likeCount = Math.max(0, item.likeCount + (item.liked ? 1 : -1)); item.likeBusy = true; renderFeed()
    try {
      const response = await api(`/feed/publications/${encodeURIComponent(item.id)}/like`, { method: item.liked ? 'POST' : 'DELETE' })
      if (!response.ok) throw new Error(await responseMessage(response, 'Не удалось сохранить отметку.'))
      const payload = await response.json().catch(() => ({})); const publication = payload.publication || payload
      if (Number.isFinite(Number(publication.like_count))) item.likeCount = Math.max(0, Number(publication.like_count))
      if (typeof publication.is_liked_by_me === 'boolean') item.liked = publication.is_liked_by_me
    } catch (error) {
      item.liked = previous.liked; item.likeCount = previous.likeCount; toast(error.message || 'Не удалось сохранить отметку.')
    } finally { item.likeBusy = false; if (view === 'feed') renderFeed() }
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

  function acceptImageSources(values, append = false) {
    const current = append ? state.imageRefs : []
    state.imageRefs = [...current, ...values].filter(Boolean).slice(0, 4)
    photo = state.imageRefs[0] || null
    if (idx === 0) idx = 1
    state.imageResults = []; state.imagePhase = 'idle'; gstate = 'idle'
    queueMicrotask(() => { if (view === 'img' && idx === 1) enhanceImage() })
    return state.imageRefs.length
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

  const voiceWave = () => Array.from({ length: 16 }, () => '<i></i>').join('')
  const voiceTime = (milliseconds) => {
    const seconds = Math.max(0, Math.floor(milliseconds / 1000))
    return `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`
  }

  function renderVoiceState() {
    document.querySelectorAll('.live-voice-status').forEach((node) => node.remove())
    document.querySelectorAll('[data-live-mic]').forEach((button) => {
      const active = state.recording?.button === button
      button.classList.toggle('live-recording', Boolean(active && state.recording.phase === 'recording'))
      button.classList.toggle('live-transcribing', Boolean(active && state.recording.phase === 'transcribing'))
      button.setAttribute('aria-pressed', String(Boolean(active)))
      button.setAttribute('aria-label', active && state.recording.phase === 'recording' ? 'Остановить запись голоса' : 'Сказать голосом')
    })
    const recording = state.recording
    if (!recording) return
    const host = recording.target === 'chat' ? document.getElementById('chatbar') : document.getElementById('pbar')
    if (!host) return
    const elapsed = Date.now() - recording.startedAt
    const status = document.createElement('div')
    status.className = `live-voice-status${recording.phase === 'transcribing' ? ' transcribing' : ''}`
    status.innerHTML = recording.phase === 'transcribing'
      ? '<span class="live-spinner"></span><span>Распознаём речь и вставляем текст…</span>'
      : `<span class="dot"></span><span>Идёт запись · нажмите микрофон, чтобы закончить</span><span class="wave">${voiceWave()}</span><time>${voiceTime(elapsed)}</time>`
    host.prepend(status)
  }

  function appendVoiceText(input, text, target) {
    const spacer = input.value.trim() ? ' ' : ''
    input.value = `${input.value.trim()}${spacer}${text.trim()}`
    input.dispatchEvent(new Event('input', { bubbles: true }))
    if (target === 'chat') growChatLive()
    else if (typeof grow === 'function') grow()
    input.focus()
  }

  async function transcribeRecording(recording) {
    recording.phase = 'transcribing'; renderVoiceState()
    const duration = Math.max(1, Date.now() - recording.startedAt)
    if (duration < 850) throw new Error('Говорите не меньше одной секунды.')
    const blob = new Blob(recording.chunks, { type: recording.mimeType || 'audio/webm' })
    if (!blob.size) throw new Error('Запись получилась пустой. Попробуйте ещё раз.')
    const type = String(blob.type || 'audio/webm').split(';')[0]
    const extension = type.includes('ogg') ? 'ogg' : type.includes('mp4') ? 'm4a' : 'webm'
    const form = new FormData(); form.append('file', blob, `voice.${extension}`)
    const response = await api(`/tools/transcribe?duration_ms=${Math.round(duration)}&language=ru`, { method: 'POST', body: form })
    if (!response.ok) throw new Error(await responseMessage(response, 'Не удалось распознать голос.'))
    const result = await response.json()
    if (!String(result.text || '').trim()) throw new Error('Речь не распознана. Попробуйте ещё раз.')
    appendVoiceText(recording.input, String(result.text), recording.target)
    toast('Голос распознан и добавлен в текст')
  }

  function stopRecording() {
    const recording = state.recording
    if (!recording || recording.stopRequested) return
    recording.stopRequested = true
    clearInterval(recording.timer)
    try { recording.recorder.stop() } catch { /* recorder already stopped */ }
  }

  async function toggleVoice(target, button, input) {
    if (state.recording) {
      if (state.recording.button === button && state.recording.phase === 'recording') stopRecording()
      else toast('Сначала завершите текущую запись')
      return
    }
    if (!state.me) { toast('Войдите в аккаунт, чтобы использовать голосовой ввод'); openSheet('you'); return }
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
      toast('На этом устройстве запись голоса не поддерживается браузером')
      return
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const supported = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg'].find((type) => !MediaRecorder.isTypeSupported || MediaRecorder.isTypeSupported(type))
      const recorder = supported ? new MediaRecorder(stream, { mimeType: supported }) : new MediaRecorder(stream)
      const recording = { target, button, input, stream, recorder, chunks: [], mimeType: recorder.mimeType || supported || 'audio/webm', startedAt: Date.now(), phase: 'recording', stopRequested: false, timer: null }
      recorder.addEventListener('dataavailable', (event) => { if (event.data?.size) recording.chunks.push(event.data) })
      recorder.addEventListener('stop', async () => {
        try { await transcribeRecording(recording) } catch (error) { toast(error.message || 'Не удалось распознать голос') }
        finally {
          recording.stream.getTracks().forEach((track) => track.stop())
          if (state.recording === recording) state.recording = null
          renderVoiceState()
        }
      }, { once: true })
      recorder.addEventListener('error', () => {
        clearInterval(recording.timer); recording.stream.getTracks().forEach((track) => track.stop()); state.recording = null; renderVoiceState(); toast('Запись голоса прервана')
      }, { once: true })
      state.recording = recording
      recorder.start(250)
      recording.timer = setInterval(() => {
        if (state.recording === recording) renderVoiceState()
        if (Date.now() - recording.startedAt >= 60_000) stopRecording()
      }, 250)
      renderVoiceState()
    } catch (error) {
      toast(error?.name === 'NotAllowedError' ? 'Разрешите доступ к микрофону в браузере' : 'Не удалось включить микрофон')
    }
  }

  const improveMode = () => imageMode() === 'text_to_image' ? 'text' : imageMode() === 'paint' ? 'sketch' : imageMode() === 'edit' ? 'edit' : 'i2i'

  async function improveInput(input, button, mode = improveMode()) {
    if (!state.me) { toast('Войдите в аккаунт, чтобы улучшить описание'); openSheet('you'); return }
    const prompt = input.value.trim()
    if (!prompt) { toast('Сначала напишите описание'); input.focus(); return }
    button.disabled = true; button.classList.add('live-transcribing')
    try {
      const response = await api('/tools/improve-prompt', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ prompt, mode, language: 'ru' }),
      })
      if (!response.ok) throw new Error(await responseMessage(response, 'Не удалось улучшить описание.'))
      const value = String((await response.json()).improvedPrompt || '').trim()
      if (!value) throw new Error('Сервис не вернул улучшенный текст.')
      input.value = value; input.dispatchEvent(new Event('input', { bubbles: true })); input.focus(); toast('Описание улучшено')
    } catch (error) { toast(error.message || 'Не удалось улучшить описание') }
    finally { button.disabled = false; button.classList.remove('live-transcribing') }
  }

  function installImagePromptTools() {
    const buttons = Object.fromEntries(Array.from(document.querySelectorAll('#pbar .ic[data-t]')).map((button) => {
      const clean = button.cloneNode(true); button.replaceWith(clean); return [clean.dataset.t, clean]
    }))
    if (buttons.mic) {
      buttons.mic.dataset.liveMic = 'image'; buttons.mic.title = 'Сказать голосом'
      buttons.mic.addEventListener('click', () => toggleVoice('image', buttons.mic, gp))
    }
    if (buttons.add) buttons.add.addEventListener('click', () => {
      if (view !== 'img') return
      if (idx === 2) { toast('В этом режиме рисуйте прямо на холсте'); return }
      const append = idx === 1 && state.imageRefs.length > 0
      chooseImages(true, (values) => {
        const count = acceptImageSources(values, append)
        paint(); toast(count > 1 ? `Добавлено изображений: ${count}` : 'Изображение прикреплено')
      })
    })
    if (buttons.fix) buttons.fix.addEventListener('click', () => improveInput(gp, buttons.fix))
    if (buttons.hist) buttons.hist.addEventListener('click', () => {
      const previous = state.lastImageRequest
      if (!previous) { toast('Предыдущего запроса пока нет'); return }
      idx = previous.idx; ratio = previous.ratio; qual = previous.qual; style = previous.style
      photo = previous.photo || null; state.imageRefs = [...(previous.imageRefs || [])]; state.sketchData = previous.sketchData || ''
      gp.value = previous.prompt; gp.dispatchEvent(new Event('input', { bubbles: true })); paint(); toast('Предыдущий запрос и настройки восстановлены')
    })
  }

  function setupSketch(canvas, toolbar) {
    const ratioValue = RATIOS[ratio]?.[0] || '1:1'
    const [rw, rh] = ratioValue.split(':').map(Number)
    canvas.width = Math.round(720 * rw / Math.max(rw, rh)); canvas.height = Math.round(720 * rh / Math.max(rw, rh))
    const ctx = canvas.getContext('2d'); ctx.lineCap = 'round'; ctx.lineJoin = 'round'
    const reset = () => { ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, canvas.width, canvas.height) }
    const drawData = (value) => {
      if (!value) { reset(); state.sketchData = canvas.toDataURL('image/png'); return }
      const image = new Image(); image.onload = () => { reset(); ctx.drawImage(image, 0, 0, canvas.width, canvas.height); state.sketchData = canvas.toDataURL('image/png') }; image.src = value
    }
    drawData(state.sketchData)
    const host = canvas.closest('.phone-sketch-host')
    let drawing = false; let drawingStart = null; let sketchLastTap = 0
    const openFullscreen = () => { if (host?.classList.contains('phone-sketch-fullscreen')) return; host?.classList.add('phone-sketch-fullscreen'); document.body.classList.add('phone-sketch-open'); document.body.style.overflow = 'hidden' }
    const closeFullscreen = () => { host?.classList.remove('phone-sketch-fullscreen'); document.body.classList.remove('phone-sketch-open'); document.body.style.overflow = '' }
    const point = (event) => { const rect = canvas.getBoundingClientRect(); return [(event.clientX - rect.left) * canvas.width / rect.width, (event.clientY - rect.top) * canvas.height / rect.height] }
    const remember = () => { state.sketchHistory.push(canvas.toDataURL('image/png')); if (state.sketchHistory.length > 20) state.sketchHistory.shift() }
    canvas.addEventListener('pointerdown', (event) => {
      event.preventDefault(); remember(); drawing = true; drawingStart = { x: event.clientX, y: event.clientY, at: Date.now(), pointerType: event.pointerType }; try { canvas.setPointerCapture?.(event.pointerId) } catch { /* synthetic pointer */ }
      ctx.globalCompositeOperation = 'source-over'; ctx.strokeStyle = state.sketchTool === 'eraser' ? '#fff' : state.sketchColor
      ctx.lineWidth = Math.max(3, state.sketchSize * canvas.width / 720)
      const [x, y] = point(event); ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x + .01, y + .01); ctx.stroke()
    })
    canvas.addEventListener('pointermove', (event) => { if (!drawing) return; const [x, y] = point(event); ctx.lineTo(x, y); ctx.stroke() })
    const finish = (event) => {
      if (!drawing) return
      drawing = false; state.sketchData = canvas.toDataURL('image/png')
      if (drawingStart?.pointerType === 'touch' && Date.now() - drawingStart.at < 280 && Math.hypot(event.clientX - drawingStart.x, event.clientY - drawingStart.y) < 10) {
        const now = Date.now(); if (now - sketchLastTap < 330) { const recent = state.sketchHistory.pop(); const beforeTaps = state.sketchHistory.pop() || recent; if (beforeTaps) drawData(beforeTaps); openFullscreen(); sketchLastTap = 0 } else sketchLastTap = now
      }
      drawingStart = null
    }
    canvas.addEventListener('pointerup', finish); canvas.addEventListener('pointercancel', finish)
    canvas.addEventListener('dblclick', (event) => { event.preventDefault(); if (host?.classList.contains('phone-sketch-fullscreen')) return; const recent = state.sketchHistory.pop(); const beforeClicks = state.sketchHistory.pop() || recent; if (beforeClicks) drawData(beforeClicks); openFullscreen() })
    host?.querySelector('[data-sketch-fullscreen-close]')?.addEventListener('click', (event) => { event.stopPropagation(); closeFullscreen() })
    toolbar?.querySelectorAll('[data-sketch-tool]').forEach((button) => button.addEventListener('click', () => {
      state.sketchTool = button.dataset.sketchTool
      toolbar.querySelectorAll('[data-sketch-tool]').forEach((item) => item.setAttribute('aria-pressed', String(item.dataset.sketchTool === state.sketchTool)))
    }))
    toolbar?.querySelector('[data-sketch-color]')?.addEventListener('input', (event) => {
      state.sketchColor = event.target.value; toolbar.style.setProperty('--sketch-color', state.sketchColor)
    })
    toolbar?.querySelector('[data-sketch-size]')?.addEventListener('click', (event) => {
      const sizes = [6, 12, 24, 42]; state.sketchSize = sizes[(sizes.indexOf(state.sketchSize) + 1) % sizes.length]
      event.currentTarget.querySelector('span').style.width = `${Math.max(6, Math.round(state.sketchSize / 2))}px`
      event.currentTarget.querySelector('span').style.height = `${Math.max(6, Math.round(state.sketchSize / 2))}px`
      event.currentTarget.setAttribute('aria-label', `Размер кисти: ${state.sketchSize}`); event.currentTarget.dataset.hint = `Размер кисти: ${state.sketchSize}`
    })
    toolbar?.querySelector('[data-sketch-undo]')?.addEventListener('click', () => { const previous = state.sketchHistory.pop(); if (previous) drawData(previous); else toast('Отменять больше нечего') })
    toolbar?.querySelector('[data-sketch-clear]')?.addEventListener('click', () => { remember(); reset(); state.sketchData = canvas.toDataURL('image/png') })
  }

  function enhanceImage() {
    const selected = selectedImageModel()
    const modelRow = scr.querySelector('.modelrow .mt')
    if (modelRow) modelRow.innerHTML = `<span class="k">Модель</span><span class="v">${html(selected.label || 'ИЗО Base')}</span><span class="d2">${html(imageModelDescription(selected))}</span>`
    const controls = scr.querySelectorAll('.ctrl')
    if (controls[1]) controls[1].querySelector('.v').textContent = `${QUAL[qual][0]} · ${selectedResolution()[1]}×${selectedResolution()[2]}`
    if (controls[2]) { controls[2].querySelector('.v').textContent = '1'; controls[2].setAttribute('aria-disabled', 'true') }
    const cost = Number(selected.tokenHint || 1)
    document.getElementById('cost').textContent = `${cost} кр.`
    paintCostTokenKind(imageTokenKind(selected))

    const canvasHost = scr.querySelector('.canvas')
    if (canvasHost && gstate === 'idle' && idx === 0) {
      canvasHost.innerHTML = emptyPreviewHtml('Создайте первое изображение', 'Опишите идею — результат полностью поместится в этом окне.')
    }
    if (canvasHost && gstate === 'idle' && idx === 1 && !state.imageRefs.length) {
      canvasHost.innerHTML = emptyPreviewHtml('Измените или совместите', 'Добавьте от одного до четырёх изображений.', '<button type="button" data-attach>Выбрать изображения</button>')
    }
    const attach = scr.querySelector('[data-attach]')
    if (attach) {
      const clean = attach.cloneNode(true); attach.replaceWith(clean)
      clean.addEventListener('click', () => {
        if (idx === 2) return
        chooseImages(true, (values) => { acceptImageSources(values, state.imageRefs.length > 0); paintGen() })
      })
    }
    const clear = scr.querySelector('[data-clear]')
    if (clear) {
      const clean = clear.cloneNode(true); clear.replaceWith(clean)
      clean.addEventListener('click', () => { photo = null; state.imageRefs = []; paintGen() })
    }
    if (idx === 2 && gstate !== 'done') {
      const canvasHost = scr.querySelector('.canvas')
      if (canvasHost) {
        scr.querySelectorAll('.phone-sketch-tools').forEach((toolbar) => toolbar.remove())
        const ratioValue = RATIOS[ratio]?.[0] || '1:1'; const [rw, rh] = ratioValue.split(':').map(Number)
        canvasHost.classList.add('phone-sketch-host'); canvasHost.style.setProperty('--sketch-aspect', ratioValue.replace(':', '/')); canvasHost.style.setProperty('--sketch-ratio', String(rw / rh))
        canvasHost.innerHTML = `<canvas class="phone-sketch-canvas" aria-label="Холст для наброска. Дважды нажмите, чтобы открыть на весь экран"></canvas><button type="button" class="phone-sketch-fullscreen-close" data-sketch-fullscreen-close aria-label="Закрыть полноэкранное рисование">×</button>`
        canvasHost.insertAdjacentHTML('beforebegin', `<div class="phone-sketch-tools" role="toolbar" aria-label="Инструменты рисования" style="--sketch-color:${html(state.sketchColor)}">
          <button type="button" class="phone-sketch-tool" data-sketch-tool="brush" aria-label="Кисть" data-hint="Кисть" aria-pressed="${state.sketchTool === 'brush'}">${actionIcons.brush}</button>
          <button type="button" class="phone-sketch-tool" data-sketch-tool="eraser" aria-label="Ластик" data-hint="Ластик" aria-pressed="${state.sketchTool === 'eraser'}">${actionIcons.eraser}</button>
          <label class="phone-sketch-tool" aria-label="Цвет кисти" data-hint="Выбрать цвет кисти"><span class="sketch-dot"></span><input type="color" data-sketch-color value="${html(state.sketchColor)}"></label>
          <button type="button" class="phone-sketch-tool" data-sketch-size aria-label="Размер кисти: ${state.sketchSize}" data-hint="Размер кисти: ${state.sketchSize}"><span class="sketch-dot" style="width:${Math.max(6, Math.round(state.sketchSize / 2))}px;height:${Math.max(6, Math.round(state.sketchSize / 2))}px;background:#fff"></span></button>
          <button type="button" class="phone-sketch-tool" data-sketch-undo aria-label="Отменить последнее действие" data-hint="Отменить последнее действие">${actionIcons.undo}</button>
          <button type="button" class="phone-sketch-tool" data-sketch-clear aria-label="Очистить холст" data-hint="Очистить холст">${actionIcons.clear}</button>
        </div>`)
        setupSketch(canvasHost.querySelector('canvas'), scr.querySelector('.phone-sketch-tools'))
      }
    }
    if (idx === 1 && state.imageRefs.length && gstate !== 'done') {
      const canvasHost = scr.querySelector('.canvas')
      if (canvasHost) {
        canvasHost.innerHTML = `<div class="live-source-grid ${state.imageRefs.length === 1 ? 'single' : ''}">${state.imageRefs.map((src, index) => `<span class="live-source-item"><img alt="Исходное изображение ${index + 1}" src="${html(src)}"><button type="button" class="live-source-remove" data-remove-source="${index}" aria-label="Убрать исходное изображение ${index + 1}">×</button></span>`).join('')}${state.imageRefs.length < 4 ? '<button type="button" class="live-source-add" data-live-add-source><b>+</b><span>Добавить ещё</span></button>' : ''}</div>`
        canvasHost.querySelectorAll('[data-remove-source]').forEach((button) => button.addEventListener('click', () => {
          state.imageRefs.splice(Number(button.dataset.removeSource), 1); photo = state.imageRefs[0] || null; paintGen()
        }))
        canvasHost.querySelector('[data-live-add-source]')?.addEventListener('click', () => chooseImages(true, (values) => { acceptImageSources(values, true); paintGen() }))
      }
      const chip = document.getElementById('chip')
      if (chip) chip.querySelector('b').textContent = state.imageRefs.length > 1 ? `${state.imageRefs.length} изображения · совместить` : '1 изображение · изменить'
    }
    if (gstate === 'done' && state.imageResults.length) {
      const resultHost = scr.querySelector('.canvas')
      if (resultHost) {
        const src = state.imageResults[0]
        resultHost.classList.add('live-result-host')
        resultHost.innerHTML = `<span class="live-result-media"><img alt="Результат генерации" src="${html(src)}"></span><button type="button" class="live-result-dismiss" data-image-dismiss aria-label="Освободить предпросмотр" data-hint="Освободить предпросмотр">×</button><div class="live-image-actions" aria-label="Действия с изображением">
          <a class="live-image-action" href="${html(src)}" download="izo-asa-image.png" data-image-download aria-label="Скачать" data-hint="Скачать">${actionIcons.download}<span class="phone-visually-hidden">Скачать</span></a>
          <button type="button" class="live-image-action" data-image-share aria-label="Поделиться" data-hint="Поделиться">${actionIcons.share}<span class="phone-visually-hidden">Поделиться</span></button>
          <button type="button" class="live-image-action primary" data-image-animate aria-label="Оживить" data-hint="Оживить">${actionIcons.animate}<span class="phone-visually-hidden">Оживить</span></button>
        </div>`
        installResultPreview(resultHost.querySelector('img'))
        resultHost.querySelector('[data-image-dismiss]')?.addEventListener('click', (event) => {
          event.stopPropagation(); state.imageResults = []; state.imageJob = null; state.imagePhase = 'idle'; gstate = 'idle'; paintGen()
        })
        resultHost.querySelector('[data-image-download]')?.addEventListener('click', (event) => event.stopPropagation())
        resultHost.querySelector('[data-image-share]')?.addEventListener('click', (event) => { event.stopPropagation(); void shareImage(src) })
        resultHost.querySelector('[data-image-animate]')?.addEventListener('click', (event) => { event.stopPropagation(); animateImage(src) })
      }
    }
    if (gstate === 'busy' && state.imageJob) {
      const progress = Math.max(1, Math.min(99, Number(state.imageJob.progress || 1)))
      const bar = document.getElementById('bar'); const label = document.getElementById('pct')
      if (bar) bar.style.width = `${progress}%`; if (label) label.textContent = `ГОТОВО НА ${Math.round(progress)}%`
    }
    installLongPressHints(scr)
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
    const styleRow = style >= 0 ? STYLES[style] : null
    const styleText = modeKey === 'text_to_image' ? styleRow?.[3] : styleRow?.[4]
    const stylePrompt = styleText ? `. ${styleText}` : ''
    const body = {
      mode: modeKey, provider: selected.provider || 'comfyui', prompt: `${prompt}${stylePrompt}`,
      negativePrompt: '', seed: Math.floor(Math.random() * 2147483646) + 1,
      width, height, resolutionId, steps: selected.provider === 'comfyui' ? 4 : 4, cfg: 1, guidance: 3.5,
      strength: .75, modelProfile: selected.modelProfile || 'local_flux_klein', loras: [],
    }
    if (modeKey === 'image_to_image') body.inputImage1 = photo
    if (modeKey === 'paint') body.canvas = state.sketchData
    if (modeKey === 'edit') body.inputImages = state.imageRefs.map((image, index) => ({ index: index + 1, role: index === 0 ? 'base' : 'reference', image }))
    state.lastImageRequest = {
      prompt, idx, ratio, qual, style, photo,
      imageRefs: [...state.imageRefs], sketchData: state.sketchData,
    }
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
    paintCostTokenKind(videoTokenKind(selected))
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
    shPick.innerHTML = `<div class="grab"></div><div class="shead"><h4>${html(title)}</h4>${X}</div>${items.map((item, index) => `<div class="pick ${item.disabled ? 'disabled' : ''} ${index === current ? 'on' : ''}" data-live-pick="${index}"><span class="fig">${item.icon || IC.cube}</span><span><b>${html(item.label)}</b><span class="ds">${html(item.description || '')}</span></span>${item.price ? `<span class="live-price token-kind-${item.tokenKind || 'main'}">${html(item.price)}</span>` : ''}</div>`).join('')}`
    shPick.querySelectorAll('[data-live-pick]').forEach((node) => node.addEventListener('click', () => { const item = items[Number(node.dataset.livePick)]; if (!item || item.disabled) return; choose(item, Number(node.dataset.livePick)); closeSheets() }))
    openSheet('pick')
  }

  const demoOpenPick = openPick
  openPick = function phoneOpenPick(kind) {
    if (view === 'img' && kind === 'model') {
      const models = getImageModels(); const selected = selectedImageModel()
      return realPick('Модель', models.map((item) => ({ label: item.label || item.id, description: imageModelDescription(item), price: `${Number(item.tokenHint || 1)} кр.`, tokenKind: imageTokenKind(item) })), models.findIndex((item) => item.id === selected.id), (_item, index) => { state.imageModelByMode[imageMode()] = models[index].id; model = index; if (!qualityAllowed(qual)) qual = Math.max(0, [0, 1, 2, 3].filter(qualityAllowed).pop() || 0); paintGen() })
    }
    if (view === 'img' && kind === 'qual') {
      return realPick('Качество', QUAL.map((item, index) => { const entry = resolutionTable[RATIOS[ratio][0]][item[0]]; return { label: item[0], description: `${entry[1]} × ${entry[2]}`, disabled: !qualityAllowed(index), icon: item[0] } }), qual, (_item, index) => { qual = index; paintGen() })
    }
    if (view === 'img' && kind === 'cnt') return realPick('Количество', [{ label: '1 вариант', description: 'Одна реальная задача генерации', icon: '1' }], 0, () => { cnt = 0; paintGen() })
    if (view === 'vid' && ['model', 'vf', 'vd', 'vq'].includes(kind)) {
      syncVideoOptions(); const selected = selectedVideoModel()
      if (kind === 'model') {
        const models = getVideoModels(); return realPick('Видеомодель', models.map((item) => ({ label: item.name || item.id, description: videoModelDescription(item), price: item.publicPricing?.fromTokens ? `от ${item.publicPricing.fromTokens} кр.` : '', tokenKind: videoTokenKind(item) })), models.findIndex((item) => item.id === selected?.id), (_item, index) => { state.videoModelByMode[videoMode()] = models[index].id; syncVideoOptions(); state.videoEstimate = null; paintVid(); estimateVideo() })
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

  const chatText = (value) => html(value).replace(/\r?\n/g, '<br>')
  const currentChat = () => state.chatThreads[chatKey()] || (state.chatThreads[chatKey()] = [])
  const chatScrollEnd = () => requestAnimationFrame(() => { body.scrollTop = body.scrollHeight; lastY = body.scrollTop })

  function growChatLive() {
    const input = document.getElementById('chatgp')
    const send = document.getElementById('chatSend')
    if (!input || !send) return
    input.style.height = 'auto'; input.style.height = `${Math.min(input.scrollHeight, 180)}px`
    const ready = Boolean(input.value.trim() || state.chatImages.length || state.chatFiles.length) && !state.chatBusy
    send.classList.toggle('ready', ready); send.disabled = !ready
    updateDockPadding()
  }

  function renderChatAttachments() {
    const bar = document.getElementById('chatbar')
    if (!bar) return
    bar.querySelector('.live-chat-attachments')?.remove()
    if (!state.chatImages.length && !state.chatFiles.length) { growChatLive(); return }
    const tray = document.createElement('div'); tray.className = 'live-chat-attachments'
    tray.innerHTML = [
      ...state.chatImages.map((src, index) => `<span class="live-chat-attachment"><img alt="Прикреплённое изображение" src="${html(src)}"><button type="button" data-remove-chat-image="${index}" aria-label="Убрать изображение">×</button></span>`),
      ...state.chatFiles.map((file, index) => `<span class="live-chat-attachment file">${html(file.name)}<button type="button" data-remove-chat-file="${index}" aria-label="Убрать файл">×</button></span>`),
    ].join('')
    tray.querySelectorAll('[data-remove-chat-image]').forEach((button) => button.addEventListener('click', () => { state.chatImages.splice(Number(button.dataset.removeChatImage), 1); renderChatAttachments() }))
    tray.querySelectorAll('[data-remove-chat-file]').forEach((button) => button.addEventListener('click', () => { state.chatFiles.splice(Number(button.dataset.removeChatFile), 1); renderChatAttachments() }))
    bar.insertBefore(tray, bar.querySelector('.chatbox'))
    growChatLive()
  }

  function chatTurnHtml(turn, index) {
    if (turn.role === 'user') {
      const images = (turn.images || []).map((src) => `<img alt="Вложение пользователя" src="${html(src)}">`).join('')
      return `<div class="live-chat-turn"><div class="bub">${images ? `<span class="live-chat-user-images">${images}</span>` : ''}${chatText(turn.content)}</div></div>`
    }
    const status = turn.status === 'pending' ? ' pending' : turn.status === 'error' ? ' error' : ''
    const reply = turn.status === 'pending' ? '<span class="live-spinner"></span>Готовлю ответ…' : chatText(turn.content)
    const actions = turn.status === 'done' ? `<div class="live-chat-actions">
      <button type="button" data-chat-action="copy" data-chat-index="${index}">Копировать</button>
      <button type="button" data-chat-action="image" data-chat-index="${index}">В картинку</button>
      <button type="button" data-chat-action="video" data-chat-index="${index}">В видео</button>
    </div>` : ''
    const meta = turn.status === 'done' && turn.provider ? `<div class="meta2"><span>ИЗО Чат</span><span>${turn.provider === 'local' ? 'локально' : 'облако'}</span></div>` : ''
    return `<div class="live-chat-turn"><div class="ai${status}"><div class="txt">${reply}</div>${meta}${actions}</div></div>`
  }

  function renderChatLive() {
    const turns = currentChat()
    const intro = turns.length ? '<div class="sys">Чат помнит контекст этого диалога. Можно уточнять и продолжать мысль.</div>' : `<div class="sys live-chat-empty"><b>С чего начнём?</b>Напишите сообщение, скажите его голосом или добавьте изображение и файл.</div>
      <div class="quick" style="padding:4px 0;justify-content:center;flex-wrap:wrap">
        ${['Придумай идею для изображения', 'Улучши описание сцены', 'Напиши текст публикации'].map((value) => `<button type="button" data-live-chat-quick="${html(value)}">${html(value)}</button>`).join('')}
      </div>`
    scr.innerHTML = `<div class="thread" style="padding-top:${turns.length ? 12 : 34}px">${intro}${turns.map(chatTurnHtml).join('')}</div>`
    scr.querySelectorAll('[data-live-chat-quick]').forEach((button) => button.addEventListener('click', () => { chatgp.value = button.dataset.liveChatQuick; chatgp.dispatchEvent(new Event('input', { bubbles: true })); chatgp.focus() }))
    scr.querySelectorAll('[data-chat-action]').forEach((button) => button.addEventListener('click', async () => {
      const turn = turns[Number(button.dataset.chatIndex)]; if (!turn?.content) return
      if (button.dataset.chatAction === 'copy') {
        try { await navigator.clipboard.writeText(turn.content); toast('Ответ скопирован') } catch { toast('Не удалось скопировать ответ') }
        return
      }
      gp.value = turn.content; gp.dispatchEvent(new Event('input', { bubbles: true }))
      go(button.dataset.chatAction === 'video' ? 'vid' : 'img', 0)
      toast(button.dataset.chatAction === 'video' ? 'Ответ перенесён в описание видео' : 'Ответ перенесён в описание изображения')
    }))
    renderChatAttachments(); growChatLive()
  }

  async function sendChatLive() {
    if (state.chatBusy) return
    if (!state.me) { toast('Войдите в аккаунт, чтобы пользоваться чатом'); openSheet('you'); return }
    const typed = chatgp.value.trim()
    if (!typed && !state.chatImages.length && !state.chatFiles.length) return
    const files = state.chatFiles.map((file) => `Файл «${file.name}»:\n${file.content}`).join('\n\n')
    const content = `${typed || (state.chatImages.length ? 'Опиши прикреплённое изображение.' : 'Проанализируй вложенный файл.')} ${files ? `\n\n${files}` : ''}`.trim().slice(0, 4000)
    let key = chatKey(); let turns = currentChat()
    if (key === 'Новый чат' && turns.length === 0) {
      const base = (typed || state.chatFiles[0]?.name || 'Изображение').replace(/\s+/g, ' ').slice(0, 24)
      let title = base; let suffix = 2
      while (Object.prototype.hasOwnProperty.call(state.chatThreads, title) && title !== key) title = `${base.slice(0, 19)} · ${suffix++}`
      delete state.chatThreads[key]; TABS.chat[idx] = title; key = title; state.chatThreads[key] = turns; paintTabs()
    }
    const images = [...state.chatImages]
    turns.push({ role: 'user', content, images })
    const pending = { role: 'assistant', content: '', status: 'pending' }; turns.push(pending)
    state.chatImages = []; state.chatFiles = []; chatgp.value = ''; state.chatBusy = true
    renderChatLive(); chatScrollEnd()
    const history = turns.filter((turn) => turn.role === 'user' || turn.status === 'done').slice(-20).map((turn) => ({ role: turn.role, content: turn.content }))
    try {
      const response = await api('/phone/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ messages: history, route: state.chatRoute, images }) })
      if (!response.ok) throw new Error(await responseMessage(response, 'Чат временно недоступен.'))
      const result = await response.json(); const reply = String(result.reply || '').trim()
      if (!reply) throw new Error('Чат не вернул ответ.')
      Object.assign(pending, { content: reply, status: 'done', provider: result.provider || '', model: result.model || '' })
    } catch (error) {
      Object.assign(pending, { content: error.message || 'Чат временно недоступен. Повторите позже.', status: 'error' })
    } finally {
      state.chatBusy = false
      if (view === 'chat' && chatKey() === key) { renderChatLive(); chatScrollEnd() }
    }
  }

  function installChatControls() {
    TABS.chat.splice(0, TABS.chat.length, 'Новый чат'); state.chatThreads = { 'Новый чат': [] }
    const replace = (id) => { const old = document.getElementById(id); const clean = old.cloneNode(true); old.replaceWith(clean); return clean }
    const liveSend = replace('chatSend'); const liveMic = replace('chatMic'); const liveTools = replace('chatTools')
    const liveModel = replace('chatModelButton'); const livePlus = replace('chatPlus'); const liveMenu = replace('chatPlusMenu'); const liveNew = replace('newchat')
    liveMic.dataset.liveMic = 'chat'; liveMic.title = 'Сказать голосом'; liveModel.querySelector('#chatModelName').textContent = 'ИЗО Чат'
    const imageInput = document.createElement('input'); imageInput.type = 'file'; imageInput.accept = 'image/jpeg,image/png,image/webp'; imageInput.multiple = true; imageInput.hidden = true
    const cameraInput = imageInput.cloneNode(); cameraInput.multiple = false; cameraInput.setAttribute('capture', 'environment')
    const textInput = document.createElement('input'); textInput.type = 'file'; textInput.accept = '.txt,.md,.json,.csv,text/plain,application/json,text/csv'; textInput.multiple = true; textInput.hidden = true
    document.body.append(imageInput, cameraInput, textInput)
    const takeImages = async (files) => {
      const room = 4 - state.chatImages.length
      if (room <= 0) { toast('Можно прикрепить не больше четырёх изображений'); return }
      try { state.chatImages.push(...await Promise.all(Array.from(files).slice(0, room).map(preparedImage))); renderChatAttachments(); chatgp.focus() }
      catch (error) { toast(error.message || 'Не удалось прикрепить изображение') }
    }
    imageInput.addEventListener('change', async () => { await takeImages(imageInput.files); imageInput.value = '' })
    cameraInput.addEventListener('change', async () => { await takeImages(cameraInput.files); cameraInput.value = '' })
    textInput.addEventListener('change', async () => {
      for (const file of Array.from(textInput.files).slice(0, 2)) {
        if (file.size > 200_000) { toast(`Файл «${file.name}» больше 200 КБ`); continue }
        state.chatFiles.push({ name: file.name, content: (await file.text()).slice(0, 1800) })
      }
      state.chatFiles = state.chatFiles.slice(0, 2); textInput.value = ''; renderChatAttachments(); chatgp.focus()
    })
    chatgp.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); event.stopImmediatePropagation(); sendChatLive() }
    }, true)
    chatgp.addEventListener('input', growChatLive); liveSend.addEventListener('click', sendChatLive)
    liveMic.addEventListener('click', () => toggleVoice('chat', liveMic, chatgp))
    livePlus.addEventListener('click', (event) => { event.stopPropagation(); liveMenu.hidden = !liveMenu.hidden; livePlus.setAttribute('aria-expanded', String(!liveMenu.hidden)) })
    liveMenu.querySelectorAll('[data-chat-add]').forEach((button) => button.addEventListener('click', () => {
      liveMenu.hidden = true; livePlus.setAttribute('aria-expanded', 'false')
      if (button.dataset.chatAdd === 'photo') imageInput.click()
      else if (button.dataset.chatAdd === 'camera') cameraInput.click()
      else textInput.click()
    }))
    liveTools.addEventListener('click', () => realPick('Инструменты чата', [
      { label: 'Улучшить сообщение', description: 'Сделать запрос точнее перед отправкой', icon: IC.edit },
      { label: 'Перенести в картинку', description: 'Использовать текст как описание изображения', icon: IC.img },
      { label: 'Перенести в видео', description: 'Использовать текст как описание ролика', icon: IC.vid },
      { label: 'Очистить диалог', description: 'Начать этот чат заново', icon: IC.trash || IC.edit },
    ], -1, async (_item, choice) => {
      if (choice === 0) await improveInput(chatgp, liveTools, 'text')
      else if (choice === 1 || choice === 2) { gp.value = chatgp.value; gp.dispatchEvent(new Event('input', { bubbles: true })); go(choice === 2 ? 'vid' : 'img', 0) }
      else { state.chatThreads[chatKey()] = []; renderChatLive(); toast('Диалог очищен') }
    }))
    liveModel.addEventListener('click', () => realPick('Модель чата', [{ label: 'ИЗО Чат', description: 'Маршрут и модель выбираются сервером автоматически', icon: IC.cube }], 0, () => { state.chatRoute = 'auto' }))
    liveNew.addEventListener('click', () => {
      if (TABS.chat[0] !== 'Новый чат') TABS.chat.unshift('Новый чат')
      state.chatThreads['Новый чат'] = []; idx = 0; paint(); chatgp.focus(); toast('Новый диалог готов')
    })
    document.addEventListener('click', (event) => { if (!event.target.closest('#chatbar')) { liveMenu.hidden = true; livePlus.setAttribute('aria-expanded', 'false') } })
    growChatLive()
  }

  paintChat = renderChatLive

  const demoPaint = paint
  paint = function phonePaint() {
    demoPaint()
    if (view === 'img') enhanceImage()
    if (view === 'feed') { renderFeed(); ensureFeed() }
    if (view === 'gal') renderGallery()
    if (view === 'vid') { syncVideoOptions(); estimateVideo() }
    installLongPressHints(app)
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

  Object.values(SH).forEach(installSheetSwipe)
  const hintObserver = new MutationObserver(() => installLongPressHints(app))
  hintObserver.observe(app, { childList: true, subtree: true })
  installLongPressHints(app)
  installImagePromptTools()
  installChatControls()
  loadInitial()
})()
