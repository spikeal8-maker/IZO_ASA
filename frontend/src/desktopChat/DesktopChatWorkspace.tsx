import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import { Box, Check, ChevronDown, Copy, Download, FileUp, ImagePlus, MessageCircle, Mic, Moon, PanelLeftClose, PanelLeftOpen, Plus, Search, Send, Share2, Sparkles, Sun, Trash2, Video, Volume2, X } from 'lucide-react'

import { createChatThread, deleteChatThread, listChatThreads, loadChatMessages, loadChatModels, runChatImageTool, saveChatTools, sendChatMessage, transcribePhoneVoice, updateChatThread, type PhoneChatMessage, type PhoneChatModel, type PhoneChatThread, type PhoneChatTool } from '../phone/features/chat/api.ts'
import { cleanAssistantText } from '../phone/features/chat/format.ts'
import { loadImageModels, type PhoneImageModel } from '../phone/features/image/api.ts'
import { loadPhoneVideoConfig, type PhoneVideoModel } from '../phone/features/video/api.ts'
import './desktopChat.css'

type Props = {
  authed: boolean
  onRequireAuth: () => void
  onNavigate: (path: '/image' | '/video' | '/audio' | '/3d') => void
}
type VoicePhase = 'idle' | 'requesting' | 'recording' | 'transcribing' | 'error'
type ChatTheme = 'dark' | 'light'
type ModelCategory = 'chat' | 'image' | 'video' | 'audio' | '3d'
type ForcedTool = 'auto' | 'web_search' | 'generate_image'
type VoiceRecorder = {
  recorder: MediaRecorder
  stream: MediaStream
  chunks: Blob[]
  startedAt: number
  cancelled: boolean
  audioContext?: AudioContext
  animationFrame?: number
}

const suggestions = [
  {
    icon: Search,
    label: 'Найти информацию',
    prompt: 'Найди в интернете актуальную информацию о ',
  },
  {
    icon: ImagePlus,
    label: 'Создать изображение',
    prompt: 'Создай изображение: ',
  },
]

const makeId = () => globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`

function readImage(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    if (!/^image\/(jpeg|png|webp)$/i.test(file.type)) return reject(new Error('Можно добавить JPEG, PNG или WebP.'))
    if (file.size > 12_000_000) return reject(new Error('Изображение больше 12 МБ.'))
    const reader = new FileReader()
    reader.onerror = () => reject(new Error('Не удалось прочитать изображение.'))
    reader.onload = () => resolve(String(reader.result || ''))
    reader.readAsDataURL(file)
  })
}

function TokenPrice({ model }: { model: PhoneChatModel }) {
  if (model.tokenKind === 'free' || model.tokenCost <= 0) return <em className="dc-daily-token">0 дневных</em>
  const input = Number(model.inputPerMillionProductTokens || 0)
  const output = Number(model.outputPerMillionProductTokens || 0)
  const format = (value: number) => (value > 0 && value < 0.01 ? '<0,01' : value.toLocaleString('ru-RU', { maximumFractionDigits: 2 }))
  return (
    <em className="dc-main-token" title="Наши токены за один миллион токенов OpenRouter">
      {input || output ? `вх. ${format(input)} · вых. ${format(output)} / 1 млн` : `${model.tokenCost.toLocaleString('ru-RU')} осн.`}
    </em>
  )
}

function InlineText({ value }: { value: string }) {
  const parts = value.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).filter(Boolean)
  return <>{parts.map((part, index) => (part.startsWith('**') && part.endsWith('**') ? <strong key={index}>{part.slice(2, -2)}</strong> : part.startsWith('`') && part.endsWith('`') ? <code key={index}>{part.slice(1, -1)}</code> : <span key={index}>{part}</span>))}</>
}

function FormattedText({ value }: { value: string }) {
  const blocks = value
    .replace(/\r/g, '')
    .split(/\n{2,}/)
    .filter((block) => block.trim())
  return (
    <div className="dc-rich-text">
      {blocks.map((block, blockIndex) => {
        const lines = block.split('\n')
        const list = lines.length > 0 && lines.every((line) => /^\s*[-*]\s+/.test(line))
        if (list)
          return (
            <ul key={blockIndex}>
              {lines.map((line, lineIndex) => (
                <li key={lineIndex}>
                  <InlineText value={line.replace(/^\s*[-*]\s+/, '')} />
                </li>
              ))}
            </ul>
          )
        return (
          <p key={blockIndex}>
            {lines.map((line, lineIndex) => (
              <span key={lineIndex}>
                <InlineText value={line} />
                {lineIndex < lines.length - 1 && <br />}
              </span>
            ))}
          </p>
        )
      })}
    </div>
  )
}

export default function DesktopChatWorkspace({ authed, onRequireAuth, onNavigate }: Props) {
  const [threads, setThreads] = useState<PhoneChatThread[]>([])
  const [currentId, setCurrentId] = useState('')
  const [messages, setMessages] = useState<PhoneChatMessage[]>([])
  const [models, setModels] = useState<PhoneChatModel[]>([])
  const [modelsLoading, setModelsLoading] = useState(false)
  const [modelId, setModelId] = useState('local:izo-chat')
  const [text, setText] = useState('')
  const [images, setImages] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [threadQuery, setThreadQuery] = useState('')
  const [modelQuery, setModelQuery] = useState('')
  const [theme, setTheme] = useState<ChatTheme>(() => (localStorage.getItem('izo.desktop-chat.theme') === 'light' ? 'light' : 'dark'))
  const [sidebarOpen, setSidebarOpen] = useState(() => window.innerWidth > 900)
  const [modelOpen, setModelOpen] = useState(false)
  const [modelCategory, setModelCategory] = useState<ModelCategory>('chat')
  const [imageModels, setImageModels] = useState<PhoneImageModel[]>([])
  const [videoModels, setVideoModels] = useState<PhoneVideoModel[]>([])
  const [forcedTool, setForcedTool] = useState<ForcedTool>('auto')
  const [attachOpen, setAttachOpen] = useState(false)
  const [voicePhase, setVoicePhase] = useState<VoicePhase>('idle')
  const [voiceSeconds, setVoiceSeconds] = useState(0)
  const [voiceLevels, setVoiceLevels] = useState<number[]>(() => Array.from({ length: 58 }, () => 3))
  const [threadKinds, setThreadKinds] = useState<Record<string, 'chat' | 'image'>>({})
  const [artifact, setArtifact] = useState<PhoneChatTool | null>(null)
  const [artifactWidth, setArtifactWidth] = useState(() => Math.round(Math.min(920, Math.max(420, window.innerWidth * 0.48))))
  const [resizingArtifact, setResizingArtifact] = useState(false)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const attachMenuRef = useRef<HTMLSpanElement>(null)
  const messagesRef = useRef<HTMLDivElement>(null)
  const workspaceRef = useRef<HTMLElement>(null)
  const threadLoadSequence = useRef(0)
  const currentIdRef = useRef('')
  const recorderRef = useRef<VoiceRecorder | null>(null)
  const voiceGestureRef = useRef({
    pressed: false,
    pointerId: -1,
    requestId: 0,
  })
  const scrollPositionsRef = useRef<Record<string, number>>({})
  const restoreScrollRef = useRef<number | null>(null)
  const stickToBottomRef = useRef(true)

  const current = useMemo(() => threads.find((item) => item.id === currentId) || null, [threads, currentId])
  const selectedModel = models.find((item) => item.id === modelId) || models.find((item) => item.available !== false) || null
  const visibleThreads = useMemo(() => {
    const query = threadQuery.trim().toLocaleLowerCase('ru')
    return query ? threads.filter((item) => (item.title || 'Новый чат').toLocaleLowerCase('ru').includes(query)) : threads
  }, [threadQuery, threads])
  const visibleModels = useMemo(() => {
    const query = modelQuery.trim().toLocaleLowerCase('ru')
    const filtered = query ? models.filter((model) => `${model.name} ${model.description || ''}`.toLocaleLowerCase('ru').includes(query)) : models
    return [...filtered].sort((left, right) => Number(left.available === false) - Number(right.available === false))
  }, [modelQuery, models])
  const visibleImageModels = useMemo(() => {
    const query = modelQuery.trim().toLocaleLowerCase('ru')
    return imageModels.filter((model) => !query || `${model.label} ${model.modelProfile}`.toLocaleLowerCase('ru').includes(query))
  }, [imageModels, modelQuery])
  const visibleVideoModels = useMemo(() => {
    const query = modelQuery.trim().toLocaleLowerCase('ru')
    return videoModels.filter((model) => !query || `${model.name} ${model.description}`.toLocaleLowerCase('ru').includes(query))
  }, [videoModels, modelQuery])

  useEffect(() => {
    currentIdRef.current = currentId
  }, [currentId])
  useEffect(() => {
    localStorage.setItem('izo.desktop-chat.theme', theme)
  }, [theme])
  useEffect(() => {
    let mobile = window.innerWidth <= 900
    const syncLayout = () => {
      const nextMobile = window.innerWidth <= 900
      if (nextMobile !== mobile) {
        mobile = nextMobile
        setSidebarOpen(!nextMobile)
      }
    }
    window.addEventListener('resize', syncLayout)
    return () => window.removeEventListener('resize', syncLayout)
  }, [])

  const openThread = useCallback(async (thread: PhoneChatThread, signal?: AbortSignal) => {
    const previousId = currentIdRef.current
    if (previousId && messagesRef.current) scrollPositionsRef.current[previousId] = messagesRef.current.scrollTop
    const sequence = ++threadLoadSequence.current
    const loaded = await loadChatMessages(thread.id, signal)
    if (sequence !== threadLoadSequence.current) return
    restoreScrollRef.current = scrollPositionsRef.current[thread.id] ?? Number.POSITIVE_INFINITY
    stickToBottomRef.current = restoreScrollRef.current === Number.POSITIVE_INFINITY
    setCurrentId(thread.id)
    setMessages(loaded.messages)
    if (loaded.messages.some((message) => (message.tools || []).some((tool) => tool.name === 'generate_image'))) setThreadKinds((items) => ({ ...items, [thread.id]: 'image' }))
    setModelId(thread.chatModelId)
    setArtifact(null)
    setError('')
  }, [])

  useEffect(() => {
    if (!authed) return
    const controller = new AbortController()
    setModels([
      {
        id: 'local:izo-chat',
        name: 'ИЗО Чат',
        provider: 'local',
        tokenCost: 0,
        tokenKind: 'free',
        description: 'Базовая локальная модель',
        contextChars: 60000,
      },
    ])
    setModelsLoading(true)
    void listChatThreads(controller.signal)
      .then(async (saved) => {
        setThreads(saved)
        if (saved[0]) await openThread(saved[0], controller.signal)
      })
      .catch((caught) => {
        if (!controller.signal.aborted) setError(caught instanceof Error ? caught.message : 'Не удалось открыть историю.')
      })
    void loadChatModels(controller.signal)
      .then((catalog) => {
        setModels((existing) => (catalog.models.length ? catalog.models : existing))
        if (catalog.models.length) setModelId((selected) => (catalog.models.some((model) => model.id === selected && model.available !== false) ? selected : catalog.defaultModel))
      })
      .catch((caught) => {
        if (!controller.signal.aborted) setError(caught instanceof Error ? caught.message : 'Не удалось загрузить модели.')
      })
      .finally(() => {
        if (!controller.signal.aborted) setModelsLoading(false)
      })
    void loadImageModels(controller.signal)
      .then((imageCatalog) => {
        if (imageCatalog) {
          const unique = new Map<string, PhoneImageModel>()
          Object.values(imageCatalog.modes || {}).forEach((mode) => (mode.models || []).forEach((model) => unique.set(model.id, model)))
          setImageModels([...unique.values()])
        }
      })
      .catch(() => undefined)
    void loadPhoneVideoConfig(controller.signal)
      .then((videoCatalog) => {
        if (videoCatalog) {
          const unique = new Map<string, PhoneVideoModel>()
          Object.values(videoCatalog.modes || {}).forEach((items) => (items || []).forEach((model) => unique.set(model.id, model)))
          setVideoModels([...unique.values()])
        }
      })
      .catch(() => undefined)
    return () => controller.abort()
  }, [authed, openThread])
  useEffect(() => {
    if (!attachOpen) return
    const close = (event: PointerEvent) => {
      if (!attachMenuRef.current?.contains(event.target as Node)) setAttachOpen(false)
    }
    document.addEventListener('pointerdown', close)
    return () => document.removeEventListener('pointerdown', close)
  }, [attachOpen])
  useLayoutEffect(() => {
    const node = inputRef.current
    if (!node) return
    node.style.height = '0'
    node.style.height = `${Math.min(132, Math.max(40, node.scrollHeight))}px`
  }, [text])

  useLayoutEffect(() => {
    const node = messagesRef.current
    if (!node) return
    if (restoreScrollRef.current !== null) {
      node.scrollTop = restoreScrollRef.current === Number.POSITIVE_INFINITY ? node.scrollHeight : restoreScrollRef.current
      restoreScrollRef.current = null
    } else if (stickToBottomRef.current) node.scrollTop = node.scrollHeight
  }, [messages, busy, currentId])
  useEffect(() => {
    if (voicePhase !== 'recording') {
      setVoiceSeconds(0)
      return
    }
    const tick = () => setVoiceSeconds(Math.max(1, Math.floor((Date.now() - (recorderRef.current?.startedAt || Date.now())) / 1000) + 1))
    tick()
    const timer = window.setInterval(tick, 250)
    return () => window.clearInterval(timer)
  }, [voicePhase])
  useEffect(() => {
    const cancel = () => {
      voiceGestureRef.current.pressed = false
      voiceGestureRef.current.requestId += 1
      const active = recorderRef.current
      if (active) {
        active.cancelled = true
        if (active.recorder.state !== 'inactive') active.recorder.stop()
      }
    }
    const hidden = () => {
      if (document.hidden) cancel()
    }
    window.addEventListener('blur', cancel)
    document.addEventListener('visibilitychange', hidden)
    return () => {
      window.removeEventListener('blur', cancel)
      document.removeEventListener('visibilitychange', hidden)
      cancel()
      recorderRef.current?.stream.getTracks().forEach((track) => track.stop())
    }
  }, [])
  useEffect(() => {
    if (!resizingArtifact) return
    const resize = (event: PointerEvent) => {
      const rect = workspaceRef.current?.getBoundingClientRect()
      if (!rect) return
      const sidebar = sidebarOpen ? workspaceRef.current?.querySelector<HTMLElement>('.dc-sidebar')?.getBoundingClientRect().width || 292 : 72
      const maximum = Math.max(360, rect.width - sidebar - 280 - 6)
      setArtifactWidth(Math.round(Math.min(maximum, Math.max(340, rect.right - event.clientX))))
    }
    const stop = () => setResizingArtifact(false)
    document.body.classList.add('dc-resizing')
    window.addEventListener('pointermove', resize)
    window.addEventListener('pointerup', stop, { once: true })
    window.addEventListener('pointercancel', stop, { once: true })
    return () => {
      document.body.classList.remove('dc-resizing')
      window.removeEventListener('pointermove', resize)
      window.removeEventListener('pointerup', stop)
      window.removeEventListener('pointercancel', stop)
    }
  }, [resizingArtifact, sidebarOpen])

  const newThread = async () => {
    if (!authed) return onRequireAuth()
    const fallback = selectedModel?.available === false ? models.find((item) => item.available !== false)?.id : modelId
    try {
      const thread = await createChatThread(fallback || 'local:izo-chat')
      setThreads((items) => [thread, ...items])
      setCurrentId(thread.id)
      setMessages([])
      setArtifact(null)
      setError('')
      inputRef.current?.focus()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Не удалось создать чат.')
    }
  }

  const appendImages = async (files: File[]) => {
    try {
      const selected = await Promise.all(
        files
          .filter((file) => file.type.startsWith('image/'))
          .slice(0, Math.max(0, 4 - images.length))
          .map(readImage),
      )
      if (!selected.length) throw new Error('Выберите изображение JPEG, PNG или WebP.')
      setImages((items) => [...items, ...selected].slice(0, 4))
      setError('')
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Не удалось добавить изображение.')
    }
  }

  const removeThread = async (thread: PhoneChatThread) => {
    try {
      await deleteChatThread(thread.id)
      const next = threads.filter((item) => item.id !== thread.id)
      setThreads(next)
      if (currentId === thread.id) {
        if (next[0]) await openThread(next[0])
        else {
          setCurrentId('')
          setMessages([])
          setArtifact(null)
        }
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Не удалось удалить чат.')
    }
  }

  const clearCurrentChat = async () => {
    if (!current) {
      setMessages([])
      setArtifact(null)
      return
    }
    try {
      await deleteChatThread(current.id)
      const replacement = await createChatThread(modelId)
      setThreads((items) => [replacement, ...items.filter((item) => item.id !== current.id)])
      setCurrentId(replacement.id)
      setMessages([])
      setArtifact(null)
      setText('')
      setImages([])
      setError('')
      inputRef.current?.focus()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Не удалось очистить чат.')
    }
  }

  const shareArtifact = async (url: string) => {
    try {
      if (navigator.share)
        await navigator.share({
          title: 'Изображение ИЗО АСА',
          url: new URL(url, window.location.href).href,
        })
      else {
        await navigator.clipboard.writeText(new URL(url, window.location.href).href)
        setError('Ссылка скопирована.')
      }
    } catch (caught) {
      if (caught instanceof DOMException && caught.name === 'AbortError') return
      setError('Не удалось открыть меню публикации.')
    }
  }

  const chooseModel = async (model: PhoneChatModel) => {
    if (model.available === false) return
    setModelId(model.id)
    setModelOpen(false)
    if (!current) return
    try {
      const updated = await updateChatThread(current.id, {
        chatModelId: model.id,
      })
      setThreads((items) => items.map((item) => (item.id === updated.id ? updated : item)))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Не удалось сменить модель.')
    }
  }

  const chooseMediaModel = async (category: 'image' | 'video', id: string) => {
    if (!current) {
      setModelOpen(false)
      return
    }
    try {
      const updated = await updateChatThread(current.id, category === 'image' ? { imageModelId: id } : { videoModelId: id })
      setThreads((items) => items.map((item) => (item.id === updated.id ? updated : item)))
      setModelOpen(false)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Не удалось сменить модель.')
    }
  }

  const submit = async () => {
    if (!authed) return onRequireAuth()
    const rawContent = text.trim() || (images.length ? 'Опиши прикреплённое изображение.' : '')
    const content = forcedTool === 'web_search' ? `Обязательно используй инструмент web_search для этого запроса. ${rawContent}` : forcedTool === 'generate_image' ? `Обязательно используй инструмент generate_image для этого запроса. ${rawContent}` : rawContent
    if (!rawContent || busy || selectedModel?.available === false) return
    let thread = current
    try {
      if (!thread) {
        thread = await createChatThread(modelId)
        setThreads((items) => [thread!, ...items])
        setCurrentId(thread.id)
      }
      const user: PhoneChatMessage = {
        id: `user-${makeId()}`,
        role: 'user',
        content: rawContent,
        provider: '',
        model: modelId,
        tools: [],
        chargedTokens: 0,
        tokenKind: '',
        createdAt: new Date().toISOString(),
        status: 'done',
      }
      const pendingId = `pending-${makeId()}`
      const pending: PhoneChatMessage = {
        ...user,
        id: pendingId,
        role: 'assistant',
        content: '',
        status: 'pending',
      }
      setMessages((items) => [...items, user, pending])
      setText('')
      setForcedTool('auto')
      const attached = [...images]
      setImages([])
      setBusy(true)
      setError('')
      const answer = await sendChatMessage({
        threadId: thread.id,
        content,
        modelId,
        images: attached,
        requestId: makeId(),
      })
      const assistantId = answer.messageId || pendingId
      let tools = answer.tools || []
      setMessages((items) =>
        items.map((item) =>
          item.id === pendingId
            ? {
                ...item,
                id: assistantId,
                content: answer.reply,
                model: answer.modelId,
                chargedTokens: answer.chargedTokens,
                tokenKind: answer.tokenKind,
                tools,
                status: 'done',
              }
            : item,
        ),
      )
      for (let index = 0; index < tools.length; index += 1) {
        if (tools[index].name !== 'generate_image' || tools[index].status !== 'requested') continue
        setThreadKinds((items) => ({ ...items, [thread!.id]: 'image' }))
        const replace = (next: PhoneChatTool) => {
          tools = tools.map((tool, toolIndex) => (toolIndex === index ? next : tool))
          setMessages((items) => items.map((item) => (item.id === assistantId ? { ...item, tools } : item)))
          if (answer.messageId) void saveChatTools(thread!.id, answer.messageId, tools).catch(() => undefined)
        }
        try {
          await runChatImageTool(tools[index], replace, thread.imageModelId)
        } catch (caught) {
          replace({
            ...tools[index],
            status: 'error',
            error: caught instanceof Error ? caught.message : 'Изображение не создано.',
          })
        }
      }
      setThreads(await listChatThreads())
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : 'Чат временно недоступен.'
      setMessages((items) => items.map((item) => (item.status === 'pending' ? { ...item, content: message, status: 'error' } : item)))
      setError(message)
    } finally {
      setBusy(false)
    }
  }

  const finishVoice = (cancelled = false) => {
    voiceGestureRef.current.pressed = false
    voiceGestureRef.current.requestId += 1
    const active = recorderRef.current
    if (!active) {
      if (voicePhase === 'requesting') setVoicePhase('idle')
      return
    }
    active.cancelled ||= cancelled
    if (active.recorder.state !== 'inactive') active.recorder.stop()
  }

  const startVoiceMeter = (stream: MediaStream, active: VoiceRecorder) => {
    if (typeof AudioContext === 'undefined') return
    try {
      const audioContext = new AudioContext()
      const analyser = audioContext.createAnalyser()
      analyser.fftSize = 256
      audioContext.createMediaStreamSource(stream).connect(analyser)
      const samples = new Uint8Array(analyser.frequencyBinCount)
      let lastPaint = 0
      const paint = (now: number) => {
        if (recorderRef.current !== active) return
        active.animationFrame = window.requestAnimationFrame(paint)
        if (now - lastPaint < 90) return
        lastPaint = now
        analyser.getByteTimeDomainData(samples)
        let peak = 0
        let energy = 0
        for (let sample = 0; sample < samples.length; sample += 1) {
          const amplitude = Math.abs(samples[sample] - 128) / 128
          peak = Math.max(peak, amplitude)
          energy += amplitude * amplitude
        }
        const rms = Math.sqrt(energy / samples.length)
        const height = Math.max(3, Math.min(25, Math.round(3 + Math.max(peak * 0.68, rms * 1.8) * 31)))
        setVoiceLevels((levels) => [...levels.slice(1), height])
      }
      active.audioContext = audioContext
      active.animationFrame = window.requestAnimationFrame(paint)
    } catch {
      void active.audioContext?.close().catch(() => undefined)
    }
  }

  const startVoice = async (pointerId: number) => {
    if (!authed) return onRequireAuth()
    if (voicePhase !== 'idle' || !navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
      if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
        setVoicePhase('error')
        setError('Этот браузер не поддерживает запись голоса.')
      }
      return
    }
    const requestId = voiceGestureRef.current.requestId + 1
    voiceGestureRef.current = { pressed: true, pointerId, requestId }
    setVoicePhase('requesting')
    setError('')
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      if (!voiceGestureRef.current.pressed || voiceGestureRef.current.requestId !== requestId) {
        stream.getTracks().forEach((track) => track.stop())
        setVoicePhase('idle')
        return
      }
      const mime = ['audio/webm;codecs=opus', 'audio/ogg;codecs=opus', 'audio/webm'].find((item) => MediaRecorder.isTypeSupported(item)) || ''
      const recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined)
      const active: VoiceRecorder = {
        recorder,
        stream,
        chunks: [],
        startedAt: 0,
        cancelled: false,
      }
      recorderRef.current = active
      recorder.addEventListener('dataavailable', (event) => {
        if (event.data.size) active.chunks.push(event.data)
      })
      recorder.addEventListener(
        'stop',
        async () => {
          if (active.animationFrame) window.cancelAnimationFrame(active.animationFrame)
          void active.audioContext?.close().catch(() => undefined)
          stream.getTracks().forEach((track) => track.stop())
          recorderRef.current = null
          setVoiceLevels(Array.from({ length: 58 }, () => 3))
          const duration = Date.now() - active.startedAt
          if (active.cancelled || duration < 700 || !active.chunks.length) {
            setVoicePhase('idle')
            return
          }
          setVoicePhase('transcribing')
          try {
            const value = await transcribePhoneVoice(
              new Blob(active.chunks, {
                type: recorder.mimeType || 'audio/webm',
              }),
              duration,
            )
            if (!value) throw new Error('Речь не распознана. Попробуйте ещё раз.')
            setText((old) => `${old}${old ? ' ' : ''}${value}`)
            setVoicePhase('idle')
            inputRef.current?.focus()
          } catch (caught) {
            setVoicePhase('error')
            setError(caught instanceof Error ? caught.message : 'Не удалось распознать голос.')
            window.setTimeout(() => setVoicePhase((phase) => (phase === 'error' ? 'idle' : phase)), 1800)
          }
        },
        { once: true },
      )
      active.startedAt = Date.now()
      recorder.start(250)
      startVoiceMeter(stream, active)
      setVoicePhase('recording')
    } catch (caught) {
      if (voiceGestureRef.current.requestId === requestId) {
        voiceGestureRef.current.pressed = false
        setVoicePhase('error')
        setError(caught instanceof DOMException && caught.name === 'NotAllowedError' ? 'Разрешите доступ к микрофону в настройках браузера.' : 'Не удалось включить микрофон.')
        window.setTimeout(() => setVoicePhase((phase) => (phase === 'error' ? 'idle' : phase)), 1800)
      }
    }
  }

  const workspaceStyle = artifact?.resultUrl ? ({ '--dc-artifact-width': `${artifactWidth}px` } as CSSProperties) : undefined

  const localPreview = location.hostname === '127.0.0.1' || location.hostname === 'localhost'

  return (
    <section ref={workspaceRef} style={workspaceStyle} className={`desktop-chat theme-${theme}${sidebarOpen ? '' : ' sidebar-closed'}${artifact?.resultUrl ? ' artifact-open' : ''}${resizingArtifact ? ' is-resizing' : ''}`}>
      <aside className="dc-sidebar sidebar">
        <header className="sidebar-head">
          <b>История</b>
          <button type="button" aria-label="Скрыть историю" onClick={() => setSidebarOpen(false)}>
            <PanelLeftClose />
          </button>
        </header>
        <button className="dc-new-chat new-chat" type="button" onClick={() => void newThread()}>
          <Plus />
          <span>Новый чат</span>
        </button>
        <label className="dc-thread-search search-field">
          <Search />
          <input value={threadQuery} onChange={(event) => setThreadQuery(event.target.value)} placeholder="Найти чат" />
        </label>
        <div className="dc-thread-list thread-group">
          <div className="thread-group-title">Недавние</div>
          {visibleThreads.map((thread) => {
            const imageThread = threadKinds[thread.id] === 'image'
            const ThreadIcon = imageThread ? ImagePlus : MessageCircle
            return (
              <div className={`thread-item${thread.id === currentId ? ' active' : ''}${imageThread ? ' kind-image' : ''}`} key={thread.id}>
                <button
                  className="thread-open"
                  type="button"
                  onClick={() => {
                    void openThread(thread)
                    if (window.innerWidth <= 900) setSidebarOpen(false)
                  }}
                >
                  <span className="dc-thread-icon thread-thumb">
                    <ThreadIcon />
                  </span>
                  <span className="thread-copy">
                    <b>{thread.title || 'Новый чат'}</b>
                  </span>
                </button>
                <button className="thread-delete" type="button" aria-label="Удалить чат" onClick={() => void removeThread(thread)}>
                  <Trash2 />
                </button>
              </div>
            )
          })}
          {!visibleThreads.length && <p>Ничего не найдено</p>}
        </div>
      </aside>
      {sidebarOpen && <button className="dc-sidebar-backdrop" type="button" aria-label="Закрыть историю" onClick={() => setSidebarOpen(false)} />}
      <main className={`dc-main chat-main${!messages.length ? ' is-empty' : ''}`}>
        {!sidebarOpen && (
          <button className="dc-floating-sidebar" type="button" aria-label="Показать историю" onClick={() => setSidebarOpen(true)}>
            <PanelLeftOpen />
          </button>
        )}
        <button className="dc-floating-theme" type="button" aria-label={theme === 'dark' ? 'Включить светлую тему' : 'Включить тёмную тему'} title={theme === 'dark' ? 'Светлая тема' : 'Тёмная тема'} onClick={() => setTheme((value) => (value === 'dark' ? 'light' : 'dark'))}>
          {theme === 'dark' ? <Sun /> : <Moon />}
        </button>
        {!!messages.length && (
          <button className="dc-floating-clear" type="button" aria-label="Очистить текущий чат" title="Очистить чат" onClick={() => void clearCurrentChat()}>
            <X />
          </button>
        )}
        <div
          ref={messagesRef}
          className="dc-messages conversation"
          onScroll={(event) => {
            const node = event.currentTarget
            stickToBottomRef.current = node.scrollHeight - node.scrollTop - node.clientHeight < 96
            if (currentId) scrollPositionsRef.current[currentId] = node.scrollTop
          }}
        >
          <div className="conversation-column">
            {!authed ? (
              <div className="dc-empty">
                <span className="dc-empty-mark">
                  <Sparkles />
                </span>
                <h1>Чат ИЗО АСА</h1>
                <p>{localPreview ? 'Локальная страница использует отдельный вход. Авторизуйтесь здесь один раз.' : 'Войдите, чтобы сохранять диалоги и использовать инструменты.'}</p>
                <button type="button" onClick={onRequireAuth}>
                  {localPreview ? 'Войти для проверки' : 'Войти'}
                </button>
              </div>
            ) : !messages.length ? (
              <div className="dc-empty">
                <span className="dc-empty-mark">
                  <Sparkles />
                </span>
                <h1>Что хотите сделать?</h1>
                <p>Задайте вопрос, найдите свежую информацию или создайте новый материал.</p>
                <div>
                  {suggestions.map(({ icon: Icon, label, prompt }) => (
                    <button
                      type="button"
                      key={label}
                      onClick={() => {
                        setText(prompt)
                        inputRef.current?.focus()
                      }}
                    >
                      <Icon />
                      {label}
                    </button>
                  ))}
                  <button type="button" onClick={() => onNavigate('/video')}>
                    Создать видео
                  </button>
                  <button type="button" onClick={() => onNavigate('/audio')}>
                    Создать звук
                  </button>
                  <button type="button" onClick={() => onNavigate('/3d')}>
                    Создать 3D
                  </button>
                </div>
              </div>
            ) : (
              messages.map((message, index) => {
                const clean = message.role === 'assistant' ? cleanAssistantText(message.content, message.tools || []) : message.content
                return (
                  <article className={`dc-message turn turn-${message.role} ${message.role} ${message.status}`} key={message.id || index}>
                    <div className="dc-message-head asa-head">
                      {message.role === 'assistant' && (
                        <span className="asa-icon">
                          <Sparkles />
                        </span>
                      )}
                      <b>{message.role === 'user' ? 'Вы' : 'ИЗО Чат'}</b>
                      <button type="button" aria-label="Копировать" onClick={() => void navigator.clipboard.writeText(clean)}>
                        <Copy />
                      </button>
                    </div>
                    {message.status === 'pending' ? (
                      <span className="dc-thinking status-block">
                        <i />
                        <i />
                        <i />
                      </span>
                    ) : message.role === 'assistant' ? (
                      <div className="assistant-body">
                        <FormattedText value={clean} />
                      </div>
                    ) : (
                      <p>{clean}</p>
                    )}
                    {(message.tools || [])
                      .filter((tool) => tool.name === 'web_search')
                      .map((tool, toolIndex) => (
                        <div className="dc-search-result sources" key={toolIndex}>
                          <Search />
                          <span>Источники</span>
                          {tool.sources?.map((source) => (
                            <a href={source.url} target="_blank" rel="noreferrer" key={source.url}>
                              {source.title}
                            </a>
                          ))}
                        </div>
                      ))}
                    {(message.tools || [])
                      .filter((tool) => tool.name === 'generate_image')
                      .map((tool, toolIndex) => (
                        <div className={`dc-image-result artifact-block is-${tool.status || 'requested'}`} key={toolIndex}>
                          {tool.resultUrl ? (
                            <>
                              <button className="dc-image-open" type="button" aria-label="Открыть изображение в предпросмотре" onClick={() => setArtifact(tool)}>
                                <img src={tool.resultUrl} alt="Созданное изображение" />
                              </button>
                              <div className="dc-image-actions">
                                <button type="button" onClick={() => setArtifact(tool)}>
                                  <ImagePlus />
                                  Предпросмотр
                                </button>
                                <a href={tool.resultUrl} download="izo-asa-image.png">
                                  <Download />
                                  Скачать
                                </a>
                                <button type="button" onClick={() => void shareArtifact(tool.resultUrl!)}>
                                  <Share2 />
                                  Поделиться
                                </button>
                              </div>
                            </>
                          ) : (
                            <span className="dc-image-progress">
                              <ImagePlus />
                              {tool.status === 'running' ? 'Создаём изображение…' : tool.error || 'Подготавливаем генерацию…'}
                            </span>
                          )}
                        </div>
                      ))}
                  </article>
                )
              })
            )}
            <div className="dc-scroll-anchor" />
          </div>
        </div>
        <footer className="dc-composer-area composer-area">
          <div className={`dc-composer composer is-${voicePhase}`}>
            {(voicePhase === 'error' || error) && (
              <div className="dc-composer-status is-error" role="status">
                {error || 'Не удалось записать голос.'}
                <button
                  type="button"
                  aria-label="Закрыть сообщение"
                  onClick={() => {
                    setError('')
                    if (voicePhase === 'error') setVoicePhase('idle')
                  }}
                >
                  <X />
                </button>
              </div>
            )}
            {images.length > 0 && (
              <div className="dc-attachments">
                {images.map((src, index) => (
                  <span key={index}>
                    <img src={src} alt="Вложение" />
                    <button type="button" onClick={() => setImages((items) => items.filter((_, itemIndex) => itemIndex !== index))}>
                      <X />
                    </button>
                  </span>
                ))}
              </div>
            )}
            <textarea
              ref={inputRef}
              rows={1}
              maxLength={4000}
              value={text}
              placeholder="Сообщение…"
              onPaste={(event) => {
                const pasted = Array.from(event.clipboardData.files).filter((file) => file.type.startsWith('image/'))
                if (pasted.length) {
                  event.preventDefault()
                  void appendImages(pasted)
                }
              }}
              onChange={(event) => setText(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && !event.shiftKey) {
                  event.preventDefault()
                  void submit()
                }
              }}
            />
            <div>
              <input
                ref={fileRef}
                hidden
                multiple
                type="file"
                accept="image/jpeg,image/png,image/webp"
                onChange={(event) => {
                  void appendImages(Array.from(event.target.files || []))
                  event.target.value = ''
                }}
              />
              <span ref={attachMenuRef} className="dc-attach-wrap">
                <button type="button" aria-label="Добавить файл или выбрать инструмент" aria-expanded={attachOpen} onClick={() => setAttachOpen((value) => !value)}>
                  <Plus />
                </button>
                {attachOpen && (
                  <span className="dc-attach-menu" role="menu">
                    <button
                      type="button"
                      role="menuitem"
                      onClick={() => {
                        setAttachOpen(false)
                        fileRef.current?.click()
                      }}
                    >
                      <FileUp />
                      <span>
                        <b>Добавить файл</b>
                        <small>Изображение или вставка Ctrl+V</small>
                      </span>
                    </button>
                    <span className="dc-tool-menu-title">Инструменты</span>
                    <button
                      type="button"
                      role="menuitem"
                      onClick={() => {
                        setForcedTool('web_search')
                        setAttachOpen(false)
                        inputRef.current?.focus()
                      }}
                    >
                      <Search />
                      <span>
                        <b>Найти в интернете</b>
                        <small>Обязательный поиск по запросу</small>
                      </span>
                    </button>
                    <button
                      type="button"
                      role="menuitem"
                      onClick={() => {
                        setForcedTool('generate_image')
                        setAttachOpen(false)
                        inputRef.current?.focus()
                      }}
                    >
                      <ImagePlus />
                      <span>
                        <b>Создать изображение</b>
                        <small>Обязательная генерация в чате</small>
                      </span>
                    </button>
                    <button
                      type="button"
                      role="menuitem"
                      onClick={() => {
                        setForcedTool('web_search')
                        setText('Какая сейчас погода в ')
                        setAttachOpen(false)
                        inputRef.current?.focus()
                      }}
                    >
                      <Sun />
                      <span>
                        <b>Погода</b>
                        <small>Актуальные данные из интернета</small>
                      </span>
                    </button>
                    <button type="button" role="menuitem" onClick={() => onNavigate('/video')}>
                      <Video />
                      <span>
                        <b>Создать видео</b>
                        <small>Открыть видеогенератор</small>
                      </span>
                    </button>
                    <button type="button" role="menuitem" onClick={() => onNavigate('/audio')}>
                      <Volume2 />
                      <span>
                        <b>Создать звук</b>
                        <small>Открыть работу со звуком</small>
                      </span>
                    </button>
                    <button type="button" role="menuitem" onClick={() => onNavigate('/3d')}>
                      <Box />
                      <span>
                        <b>Создать 3D</b>
                        <small>Открыть 3D-раздел</small>
                      </span>
                    </button>
                  </span>
                )}
              </span>
              {forcedTool !== 'auto' && voicePhase !== 'recording' && (
                <button className="dc-forced-tool" type="button" aria-label="Убрать обязательный инструмент" title="Убрать обязательный инструмент" onClick={() => setForcedTool('auto')}>
                  {forcedTool === 'web_search' ? <Search /> : <ImagePlus />}
                </button>
              )}
              {voicePhase === 'recording' ? (
                <span className="dc-live-voice" role="status">
                  <button
                    type="button"
                    aria-label="Отменить запись"
                    onPointerDown={(event) => {
                      event.preventDefault()
                      finishVoice(true)
                    }}
                  >
                    <X />
                  </button>
                  <span className="dc-live-wave" aria-hidden="true">
                    {voiceLevels.map((level, index) => (
                      <i key={index} style={{ height: `${level}px` }} />
                    ))}
                  </span>
                  <small>{voiceSeconds} с</small>
                </span>
              ) : (
                <>
                  <span className="dc-model-control">
                    <small>Модель</small>
                    <button
                      className="dc-model-button"
                      type="button"
                      aria-expanded={modelOpen}
                      onClick={() => {
                        setModelQuery('')
                        setModelCategory('chat')
                        setModelOpen(true)
                      }}
                    >
                      <span>{selectedModel?.name || 'ИЗО Чат'}</span>
                      <ChevronDown />
                    </button>
                  </span>
                  {voicePhase !== 'idle' && voicePhase !== 'error' && (
                    <span className={`dc-inline-voice is-${voicePhase}`} role="status">
                      <span className="dc-status-spinner" />
                      <small>{voicePhase === 'requesting' ? 'Микрофон' : 'Текст'}</small>
                    </span>
                  )}
                </>
              )}
              <button
                className={voicePhase === 'recording' || voicePhase === 'requesting' ? 'recording' : ''}
                type="button"
                aria-label="Удерживайте, чтобы говорить"
                onPointerDown={(event) => {
                  event.preventDefault()
                  event.currentTarget.setPointerCapture(event.pointerId)
                  void startVoice(event.pointerId)
                }}
                onPointerUp={() => finishVoice(false)}
                onPointerCancel={() => finishVoice(true)}
                onLostPointerCapture={() => finishVoice(false)}
              >
                <Mic />
              </button>
              <button className="dc-send" type="button" aria-label="Отправить" disabled={busy || (!text.trim() && !images.length)} onClick={() => void submit()}>
                <Send />
              </button>
            </div>
          </div>
        </footer>
        <div className="dc-empty-bottom-spacer" aria-hidden="true" />
      </main>
      {modelOpen && (
        <>
          <button className="dc-model-backdrop" type="button" aria-label="Закрыть выбор модели" onClick={() => setModelOpen(false)} />
          <section className="dc-model-popover model-popover" role="dialog" aria-modal="true" aria-label="Выбор модели">
            <header className="model-popover-head">
              <b>Модели</b>
              <button type="button" aria-label="Закрыть" onClick={() => setModelOpen(false)}>
                <X />
              </button>
            </header>
            <div className="dc-model-controls">
              <nav className="model-filter" aria-label="Тип модели">
                {(
                  [
                    ['chat', 'Чат'],
                    ['image', 'Изображение'],
                    ['video', 'Видео'],
                    ['audio', 'Звук'],
                    ['3d', '3D'],
                  ] as const
                ).map(([id, label]) => (
                  <button
                    type="button"
                    className={modelCategory === id ? 'active' : ''}
                    key={id}
                    onClick={() => {
                      setModelCategory(id)
                      setModelQuery('')
                    }}
                  >
                    {label}
                  </button>
                ))}
              </nav>
              <label className="dc-model-search model-search">
                <Search />
                <input value={modelQuery} onChange={(event) => setModelQuery(event.target.value)} placeholder="Поиск" />
              </label>
            </div>
            <div className="dc-model-list model-list">
              {modelCategory === 'chat' ? (
                visibleModels.length ? (
                  visibleModels.map((model) => (
                    <button type="button" key={model.id} disabled={model.available === false} className={`model-item${model.id === modelId ? ' selected active' : ''}${model.available === false ? ' unavailable' : ''}`} onClick={() => void chooseModel(model)}>
                      <span className="dc-model-icon model-item-icon">
                        <Sparkles />
                      </span>
                      <span className="model-item-copy">
                        <b>{model.name}</b>
                        <small>{model.available === false ? model.unavailableReason : model.description}</small>
                      </span>
                      <TokenPrice model={model} />
                      {model.id === modelId && <Check />}
                    </button>
                  ))
                ) : (
                  <p className="dc-model-empty">{modelsLoading ? 'Загружаем модели…' : 'Модели не найдены.'}</p>
                )
              ) : modelCategory === 'image' ? (
                visibleImageModels.length ? (
                  visibleImageModels.map((model) => (
                    <button type="button" key={model.id} className={`model-item${current?.imageModelId === model.id ? ' selected active' : ''}`} onClick={() => void chooseMediaModel('image', model.id)}>
                      <span className="dc-model-icon model-item-icon">
                        <ImagePlus />
                      </span>
                      <span className="model-item-copy">
                        <b>{model.label}</b>
                        <small>{model.provider === 'comfyui' ? 'Базовая модель изображений' : 'Облачная модель изображений'}</small>
                      </span>
                      <em className={model.provider === 'comfyui' ? 'dc-daily-token' : 'dc-main-token'}>{model.tokenHint} ток.</em>
                      {current?.imageModelId === model.id && <Check />}
                    </button>
                  ))
                ) : (
                  <p className="dc-model-empty">Нет доступных моделей изображений.</p>
                )
              ) : modelCategory === 'video' ? (
                visibleVideoModels.length ? (
                  visibleVideoModels.map((model) => (
                    <button type="button" key={model.id} className={`model-item${current?.videoModelId === model.id ? ' selected active' : ''}`} onClick={() => void chooseMediaModel('video', model.id)}>
                      <span className="dc-model-icon model-item-icon">
                        <Video />
                      </span>
                      <span className="model-item-copy">
                        <b>{model.name}</b>
                        <small>{model.description}</small>
                      </span>
                      <em className={model.provider === 'local_ltx' ? 'dc-daily-token' : 'dc-main-token'}>{model.publicPricing?.fromTokens || 0} ток.</em>
                      {current?.videoModelId === model.id && <Check />}
                    </button>
                  ))
                ) : (
                  <p className="dc-model-empty">Нет доступных видеомоделей.</p>
                )
              ) : (
                <div className="dc-model-empty">
                  <p>{modelCategory === 'audio' ? 'Модели звука выбираются в разделе звука.' : '3D-модели будут доступны после подключения генератора.'}</p>
                  {modelCategory === 'audio' && (
                    <button type="button" onClick={() => onNavigate('/audio')}>
                      Открыть звук
                    </button>
                  )}
                </div>
              )}
            </div>
          </section>
        </>
      )}
      {artifact?.resultUrl && (
        <>
          <div
            className="dc-artifact-resizer"
            role="separator"
            aria-label="Изменить ширину предпросмотра"
            aria-orientation="vertical"
            tabIndex={0}
            onPointerDown={(event) => {
              event.preventDefault()
              setResizingArtifact(true)
            }}
            onKeyDown={(event) => {
              if (event.key === 'ArrowLeft') {
                event.preventDefault()
                setArtifactWidth((value) => Math.min(960, value + 24))
              } else if (event.key === 'ArrowRight') {
                event.preventDefault()
                setArtifactWidth((value) => Math.max(340, value - 24))
              }
            }}
          >
            <span />
          </div>
          <aside className="dc-artifact">
            <header>
              <div>
                <small>Результат</small>
                <b>Изображение</b>
              </div>
              <button type="button" aria-label="Закрыть предпросмотр" onClick={() => setArtifact(null)}>
                <X />
              </button>
            </header>
            <div>
              <img src={artifact.resultUrl} alt="Созданное изображение" />
            </div>
            <footer>
              <a href={artifact.resultUrl} download="izo-asa-image.png">
                <Download />
                Скачать
              </a>
              <button type="button" onClick={() => void shareArtifact(artifact.resultUrl!)}>
                <Share2 />
                Поделиться
              </button>
              <button
                className="dc-artifact-animate"
                type="button"
                onClick={() => {
                  sessionStorage.setItem('izo.video.source', artifact.resultUrl || '')
                  onNavigate('/video')
                }}
              >
                <Video />
                Оживить
              </button>
            </footer>
          </aside>
        </>
      )}
    </section>
  )
}
