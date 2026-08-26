import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import { Check, ChevronDown, Copy, Download, ImagePlus, Mic, PanelLeftClose, PanelLeftOpen, Plus, Search, Send, Trash2, X } from 'lucide-react'

import {
  createChatThread,
  deleteChatThread,
  listChatThreads,
  loadChatMessages,
  loadChatModels,
  runChatImageTool,
  saveChatTools,
  sendChatMessage,
  transcribePhoneVoice,
  updateChatThread,
  type PhoneChatMessage,
  type PhoneChatModel,
  type PhoneChatThread,
  type PhoneChatTool,
} from '../phone/features/chat/api.ts'
import { cleanAssistantText } from '../phone/features/chat/format.ts'
import './desktopChat.css'

type Props = { authed: boolean; onRequireAuth: () => void; onNavigate: (path: '/video' | '/audio' | '/3d') => void }

const suggestions = [
  { icon: Search, label: 'Найти информацию', prompt: 'Найди в интернете актуальную информацию о ' },
  { icon: ImagePlus, label: 'Создать изображение', prompt: 'Создай изображение: ' },
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
  if (model.tokenKind === 'free' || model.tokenCost <= 0) return <em className="dc-free">Базовая</em>
  return <em className="dc-main-token">{model.tokenCost} ток.</em>
}

function InlineText({ value }: { value: string }) {
  const parts = value.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).filter(Boolean)
  return <>{parts.map((part, index) => part.startsWith('**') && part.endsWith('**')
    ? <strong key={index}>{part.slice(2, -2)}</strong>
    : part.startsWith('`') && part.endsWith('`')
      ? <code key={index}>{part.slice(1, -1)}</code>
      : <span key={index}>{part}</span>)}</>
}

function FormattedText({ value }: { value: string }) {
  const blocks = value.replace(/\r/g, '').split(/\n{2,}/).filter((block) => block.trim())
  return <div className="dc-rich-text">{blocks.map((block, blockIndex) => {
    const lines = block.split('\n')
    const list = lines.length > 0 && lines.every((line) => /^\s*[-*]\s+/.test(line))
    if (list) return <ul key={blockIndex}>{lines.map((line, lineIndex) => <li key={lineIndex}><InlineText value={line.replace(/^\s*[-*]\s+/, '')} /></li>)}</ul>
    return <p key={blockIndex}>{lines.map((line, lineIndex) => <span key={lineIndex}><InlineText value={line} />{lineIndex < lines.length - 1 && <br />}</span>)}</p>
  })}</div>
}

export default function DesktopChatWorkspace({ authed, onRequireAuth, onNavigate }: Props) {
  const [threads, setThreads] = useState<PhoneChatThread[]>([])
  const [currentId, setCurrentId] = useState('')
  const [messages, setMessages] = useState<PhoneChatMessage[]>([])
  const [models, setModels] = useState<PhoneChatModel[]>([])
  const [modelId, setModelId] = useState('local:izo-chat')
  const [text, setText] = useState('')
  const [images, setImages] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [sidebarOpen, setSidebarOpen] = useState(() => window.innerWidth > 900)
  const [modelOpen, setModelOpen] = useState(false)
  const [recording, setRecording] = useState(false)
  const [artifact, setArtifact] = useState<PhoneChatTool | null>(null)
  const [artifactWidth, setArtifactWidth] = useState(() => Math.round(Math.min(920, Math.max(420, window.innerWidth * .48))))
  const [resizingArtifact, setResizingArtifact] = useState(false)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const messagesRef = useRef<HTMLDivElement>(null)
  const workspaceRef = useRef<HTMLElement>(null)
  const threadLoadSequence = useRef(0)
  const recorderRef = useRef<{ recorder: MediaRecorder; stream: MediaStream; chunks: Blob[]; startedAt: number } | null>(null)

  const current = useMemo(() => threads.find((item) => item.id === currentId) || null, [threads, currentId])
  const selectedModel = models.find((item) => item.id === modelId) || models.find((item) => item.available !== false) || null

  const openThread = useCallback(async (thread: PhoneChatThread, signal?: AbortSignal) => {
    const sequence = ++threadLoadSequence.current
    const loaded = await loadChatMessages(thread.id, signal)
    if (sequence !== threadLoadSequence.current) return
    setCurrentId(thread.id)
    setMessages(loaded.messages)
    setModelId(thread.chatModelId)
    setArtifact([...loaded.messages].reverse().flatMap((message) => message.tools || []).find((tool) => tool.resultUrl) || null)
    setError('')
  }, [])

  useEffect(() => {
    if (!authed) return
    const controller = new AbortController()
    void Promise.all([listChatThreads(controller.signal), loadChatModels(controller.signal)]).then(async ([saved, catalog]) => {
      setThreads(saved)
      setModels(catalog.models)
      setModelId(catalog.defaultModel)
      if (saved[0]) await openThread(saved[0], controller.signal)
    }).catch((caught) => { if (!controller.signal.aborted) setError(caught instanceof Error ? caught.message : 'Не удалось открыть чат.') })
    return () => controller.abort()
  }, [authed, openThread])

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      const node = messagesRef.current
      if (node) node.scrollTop = node.scrollHeight
    })
    return () => window.cancelAnimationFrame(frame)
  }, [messages, busy, currentId])
  useEffect(() => () => recorderRef.current?.stream.getTracks().forEach((track) => track.stop()), [])
  useEffect(() => {
    if (!resizingArtifact) return
    const resize = (event: PointerEvent) => {
      const rect = workspaceRef.current?.getBoundingClientRect()
      if (!rect) return
      const sidebar = sidebarOpen ? 260 : 0
      const maximum = Math.max(360, rect.width - sidebar - 420 - 6)
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
      setCurrentId(thread.id); setMessages([]); setArtifact(null); setError('')
      inputRef.current?.focus()
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Не удалось создать чат.') }
  }

  const removeThread = async (thread: PhoneChatThread) => {
    try {
      await deleteChatThread(thread.id)
      const next = threads.filter((item) => item.id !== thread.id)
      setThreads(next)
      if (currentId === thread.id) {
        if (next[0]) await openThread(next[0])
        else { setCurrentId(''); setMessages([]); setArtifact(null) }
      }
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Не удалось удалить чат.') }
  }

  const chooseModel = async (model: PhoneChatModel) => {
    if (model.available === false) return
    setModelId(model.id); setModelOpen(false)
    if (!current) return
    try {
      const updated = await updateChatThread(current.id, { chatModelId: model.id })
      setThreads((items) => items.map((item) => item.id === updated.id ? updated : item))
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Не удалось сменить модель.') }
  }

  const submit = async () => {
    if (!authed) return onRequireAuth()
    const content = text.trim() || (images.length ? 'Опиши прикреплённое изображение.' : '')
    if (!content || busy || selectedModel?.available === false) return
    let thread = current
    try {
      if (!thread) {
        thread = await createChatThread(modelId)
        setThreads((items) => [thread!, ...items]); setCurrentId(thread.id)
      }
      const user: PhoneChatMessage = { id: `user-${makeId()}`, role: 'user', content, provider: '', model: modelId, tools: [], chargedTokens: 0, tokenKind: '', createdAt: new Date().toISOString(), status: 'done' }
      const pendingId = `pending-${makeId()}`
      const pending: PhoneChatMessage = { ...user, id: pendingId, role: 'assistant', content: '', status: 'pending' }
      setMessages((items) => [...items, user, pending]); setText(''); const attached = [...images]; setImages([]); setBusy(true); setError('')
      const answer = await sendChatMessage({ threadId: thread.id, content, modelId, images: attached, requestId: makeId() })
      const assistantId = answer.messageId || pendingId
      let tools = answer.tools || []
      setMessages((items) => items.map((item) => item.id === pendingId ? { ...item, id: assistantId, content: answer.reply, model: answer.modelId, chargedTokens: answer.chargedTokens, tokenKind: answer.tokenKind, tools, status: 'done' } : item))
      for (let index = 0; index < tools.length; index += 1) {
        if (tools[index].name !== 'generate_image' || tools[index].status !== 'requested') continue
        const replace = (next: PhoneChatTool) => {
          tools = tools.map((tool, toolIndex) => toolIndex === index ? next : tool)
          setMessages((items) => items.map((item) => item.id === assistantId ? { ...item, tools } : item))
          if (next.resultUrl) setArtifact(next)
          if (answer.messageId) void saveChatTools(thread!.id, answer.messageId, tools).catch(() => undefined)
        }
        try { await runChatImageTool(tools[index], replace) }
        catch (caught) { replace({ ...tools[index], status: 'error', error: caught instanceof Error ? caught.message : 'Изображение не создано.' }) }
      }
      setThreads(await listChatThreads())
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : 'Чат временно недоступен.'
      setMessages((items) => items.map((item) => item.status === 'pending' ? { ...item, content: message, status: 'error' } : item)); setError(message)
    } finally { setBusy(false) }
  }

  const startVoice = async () => {
    if (!authed) return onRequireAuth()
    if (recording || !navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') return
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const mime = ['audio/webm;codecs=opus', 'audio/ogg;codecs=opus', 'audio/webm'].find((item) => MediaRecorder.isTypeSupported(item)) || ''
      const recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined)
      const active = { recorder, stream, chunks: [] as Blob[], startedAt: Date.now() }; recorderRef.current = active
      recorder.addEventListener('dataavailable', (event) => { if (event.data.size) active.chunks.push(event.data) })
      recorder.addEventListener('stop', async () => {
        setRecording(false); stream.getTracks().forEach((track) => track.stop()); recorderRef.current = null
        const duration = Date.now() - active.startedAt
        if (duration < 700) return
        try { const value = await transcribePhoneVoice(new Blob(active.chunks, { type: recorder.mimeType || 'audio/webm' }), duration); setText((old) => `${old}${old ? ' ' : ''}${value}`) }
        catch (caught) { setError(caught instanceof Error ? caught.message : 'Не удалось распознать голос.') }
      }, { once: true })
      recorder.start(250); setRecording(true)
    } catch { setError('Разрешите доступ к микрофону в браузере.') }
  }

  const workspaceStyle = artifact?.resultUrl ? { '--dc-artifact-width': `${artifactWidth}px` } as CSSProperties : undefined

  return <section ref={workspaceRef} style={workspaceStyle} className={`desktop-chat${sidebarOpen ? '' : ' sidebar-closed'}${artifact?.resultUrl ? ' artifact-open' : ''}${resizingArtifact ? ' is-resizing' : ''}`}>
    <aside className="dc-sidebar">
      <header><b>Чаты</b><button type="button" onClick={() => void newThread()}><Plus />Новый чат</button></header>
      <div className="dc-thread-list">{threads.map((thread) => <div className={thread.id === currentId ? 'active' : ''} key={thread.id}><button type="button" onClick={() => void openThread(thread)}>{thread.title || 'Новый чат'}</button><button type="button" aria-label="Удалить чат" onClick={() => void removeThread(thread)}><Trash2 /></button></div>)}</div>
    </aside>
    <main className="dc-main">
      <header className="dc-toolbar"><button type="button" aria-label={sidebarOpen ? 'Скрыть историю' : 'Показать историю'} onClick={() => setSidebarOpen((value) => !value)}>{sidebarOpen ? <PanelLeftClose /> : <PanelLeftOpen />}</button><span>{current?.title || 'Новый чат'}</span><button type="button" aria-label="Новый чат" onClick={() => void newThread()}><Plus /></button></header>
      <div ref={messagesRef} className="dc-messages">
        {!authed ? <div className="dc-empty"><h1>Чат ИЗО АСА</h1><p>Войдите, чтобы сохранять диалоги и использовать инструменты.</p><button type="button" onClick={onRequireAuth}>Войти</button></div> : !messages.length ? <div className="dc-empty"><h1>Что хотите сделать?</h1><p>Спросите что угодно, найдите свежую информацию или создайте изображение.</p><div>{suggestions.map(({ icon: Icon, label, prompt }) => <button type="button" key={label} onClick={() => { setText(prompt); inputRef.current?.focus() }}><Icon />{label}</button>)}<button type="button" onClick={() => onNavigate('/video')}>Создать видео</button><button type="button" onClick={() => onNavigate('/audio')}>Создать звук</button><button type="button" onClick={() => onNavigate('/3d')}>Создать 3D</button></div></div> : messages.map((message, index) => {
          const clean = message.role === 'assistant' ? cleanAssistantText(message.content, message.tools || []) : message.content
          return <article className={`dc-message ${message.role} ${message.status}`} key={message.id || index}><div className="dc-message-head"><b>{message.role === 'user' ? 'Вы' : 'ИЗО Чат'}</b><button type="button" aria-label="Копировать" onClick={() => void navigator.clipboard.writeText(clean)}><Copy /></button></div>{message.status === 'pending' ? <span className="dc-thinking"><i /><i /><i /></span> : message.role === 'assistant' ? <FormattedText value={clean} /> : <p>{clean}</p>}{(message.tools || []).filter((tool) => tool.name === 'web_search').map((tool, toolIndex) => <div className="dc-search-result" key={toolIndex}><Search /><span>Поиск в интернете</span>{tool.sources?.map((source) => <a href={source.url} target="_blank" rel="noreferrer" key={source.url}>{source.title}</a>)}</div>)}{(message.tools || []).filter((tool) => tool.name === 'generate_image').map((tool, toolIndex) => <button type="button" className="dc-image-result" key={toolIndex} onClick={() => tool.resultUrl && setArtifact(tool)}>{tool.resultUrl ? <img src={tool.resultUrl} alt="Созданное изображение" /> : <ImagePlus />}<span>{tool.status === 'running' ? 'Создаём изображение…' : tool.error || 'Открыть изображение'}</span></button>)}</article>
        })}<div className="dc-scroll-anchor" /></div>
      {error && <div className="dc-error" role="status">{error}<button type="button" onClick={() => setError('')}><X /></button></div>}
      <footer className="dc-composer">
        {images.length > 0 && <div className="dc-attachments">{images.map((src, index) => <span key={index}><img src={src} alt="Вложение" /><button type="button" onClick={() => setImages((items) => items.filter((_, itemIndex) => itemIndex !== index))}><X /></button></span>)}</div>}
        <textarea ref={inputRef} rows={1} maxLength={4000} value={text} placeholder="Сообщение…" onChange={(event) => setText(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void submit() } }} />
        <div><input ref={fileRef} hidden multiple type="file" accept="image/jpeg,image/png,image/webp" onChange={async (event) => { try { const selected = await Promise.all(Array.from(event.target.files || []).slice(0, Math.max(0, 4 - images.length)).map(readImage)); setImages((items) => [...items, ...selected].slice(0, 4)) } catch (caught) { setError(caught instanceof Error ? caught.message : 'Не удалось добавить изображение.') } event.target.value = '' }} /><button type="button" aria-label="Добавить изображение" onClick={() => fileRef.current?.click()}><Plus /></button><button className="dc-model-button" type="button" onClick={() => setModelOpen((value) => !value)}><span>{selectedModel?.name || 'ИЗО Чат'}</span><ChevronDown /></button><button className={recording ? 'recording' : ''} type="button" aria-label="Удерживайте, чтобы говорить" onPointerDown={(event) => { event.currentTarget.setPointerCapture(event.pointerId); void startVoice() }} onPointerUp={() => recorderRef.current?.recorder.stop()} onPointerCancel={() => recorderRef.current?.recorder.stop()}><Mic /></button><button className="dc-send" type="button" aria-label="Отправить" disabled={busy || (!text.trim() && !images.length)} onClick={() => void submit()}><Send /></button></div>
        {modelOpen && <section className="dc-model-popover"><header><b>Модель чата</b><button type="button" aria-label="Закрыть" onClick={() => setModelOpen(false)}><X /></button></header>{models.map((model) => <button type="button" key={model.id} disabled={model.available === false} className={`${model.id === modelId ? 'active ' : ''}${model.available === false ? 'unavailable' : ''}`} onClick={() => void chooseModel(model)}><span><b>{model.name}</b><small>{model.available === false ? model.unavailableReason : model.description}</small></span><TokenPrice model={model} />{model.id === modelId && <Check />}</button>)}</section>}
      </footer>
    </main>
    {artifact?.resultUrl && <><div className="dc-artifact-resizer" role="separator" aria-label="Изменить ширину предпросмотра" aria-orientation="vertical" tabIndex={0} onPointerDown={(event) => { event.preventDefault(); setResizingArtifact(true) }} onKeyDown={(event) => { if (event.key === 'ArrowLeft') { event.preventDefault(); setArtifactWidth((value) => Math.min(960, value + 24)) } else if (event.key === 'ArrowRight') { event.preventDefault(); setArtifactWidth((value) => Math.max(340, value - 24)) } }}><span /></div><aside className="dc-artifact"><header><div><small>Результат</small><b>Изображение</b></div><button type="button" aria-label="Закрыть предпросмотр" onClick={() => setArtifact(null)}><X /></button></header><div><img src={artifact.resultUrl} alt="Созданное изображение" /></div><footer><a href={artifact.resultUrl} download="izo-asa-image.png"><Download />Скачать</a><button type="button" onClick={() => { sessionStorage.setItem('izo.video.source', artifact.resultUrl || ''); onNavigate('/video') }}>Оживить</button></footer></aside></>}
  </section>
}
