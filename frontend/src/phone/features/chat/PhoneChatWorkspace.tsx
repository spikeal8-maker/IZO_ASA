import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Check, ChevronDown, Copy, ImagePlus, Mic, MoreHorizontal, Plus, RotateCcw, Send, Settings2, X } from 'lucide-react'

import { phoneTokenClass } from '../../core/billing.ts'
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
} from './api.ts'
import { cleanAssistantText } from './format.ts'
import './phoneChat.css'


const quickPrompts = ['Придумай идею для изображения', 'Найди свежую информацию', 'Напиши текст публикации']

function requestId() {
  return globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`
}

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

function ChatTools({ tools }: { tools: PhoneChatTool[] }) {
  const visible = tools.filter((tool) => tool.name === 'generate_image')
  if (!visible.length) return null
  return <div className="phone-chat-tools">{visible.map((tool, index) => tool.resultUrl ? (
    <figure key={`${tool.name}-${index}`}><img src={tool.resultUrl} alt="Изображение, созданное из чата" /><figcaption><a href={tool.resultUrl} download="izo-asa-image.png">Скачать</a><button type="button" onClick={() => { sessionStorage.setItem('izo.phone.video.source', tool.resultUrl || ''); window.location.assign('/phone/video') }}>Оживить</button></figcaption></figure>
  ) : (
    <button key={`${tool.name}-${index}`} type="button" disabled={tool.status === 'running'} onClick={() => {
      if (tool.prompt) sessionStorage.setItem('izo.phone.image.prompt', tool.prompt)
      window.location.assign('/phone/image')
    }}>
      <ImagePlus />
      <span><b>{tool.status === 'running' ? 'Создаём изображение…' : tool.status === 'error' ? 'Изображение не создано' : 'Создать изображение'}</b><small>{tool.error || (tool.status === 'running' ? 'Можно продолжать диалог — результат появится здесь' : 'Описание готово')}</small></span>
    </button>
  ))}</div>
}

function MessageActions({ message, onRepeat }: { message: PhoneChatMessage; onRepeat: () => void }) {
  const [open, setOpen] = useState(false)
  const [copied, setCopied] = useState(false)
  return <div className="phone-chat-message-actions">
    <button type="button" aria-label="Действия с сообщением" onClick={() => setOpen((value) => !value)}><MoreHorizontal /></button>
    {open && <div className="phone-chat-message-menu">
      <button type="button" onClick={async () => { await navigator.clipboard.writeText(message.content); setCopied(true); setOpen(false); window.setTimeout(() => setCopied(false), 1300) }}>{copied ? <Check /> : <Copy />}Копировать</button>
      <button type="button" onClick={() => { onRepeat(); setOpen(false) }}><RotateCcw />{message.role === 'user' ? 'Изменить' : 'Повторить запрос'}</button>
    </div>}
  </div>
}

function ChatMessage({ message, onRepeat }: { message: PhoneChatMessage; onRepeat: () => void }) {
  const text = message.role === 'assistant' ? cleanAssistantText(message.content, message.tools || []) : message.content
  return <article className={`phone-chat-message ${message.role} ${message.status}`}>
    <MessageActions message={message} onRepeat={onRepeat} />
    {message.status === 'pending' ? <span className="phone-chat-thinking"><i /><i /><i /></span> : <p>{text || (message.tools?.length ? '' : 'Ответ не получен.')}</p>}
    <ChatTools tools={message.tools || []} />
    {message.role === 'assistant' && message.status === 'done' && message.chargedTokens > 0 && <small className={phoneTokenClass(message.tokenKind || 'main')}>{message.chargedTokens} ток.</small>}
  </article>
}

export default function PhoneChatWorkspace({ offline }: { offline: boolean }) {
  const [threads, setThreads] = useState<PhoneChatThread[]>([])
  const [currentId, setCurrentId] = useState('')
  const [messages, setMessages] = useState<PhoneChatMessage[]>([])
  const [models, setModels] = useState<PhoneChatModel[]>([])
  const [modelId, setModelId] = useState('local:izo-chat')
  const [text, setText] = useState('')
  const [images, setImages] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [modelOpen, setModelOpen] = useState(false)
  const [recording, setRecording] = useState(false)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const endRef = useRef<HTMLDivElement>(null)
  const recorderRef = useRef<{ recorder: MediaRecorder; stream: MediaStream; chunks: Blob[]; startedAt: number } | null>(null)
  const voiceHeldRef = useRef(false)

  const current = useMemo(() => threads.find((thread) => thread.id === currentId) || null, [threads, currentId])
  const selectedModel = models.find((model) => model.id === modelId) || null

  const openThread = useCallback(async (thread: PhoneChatThread, signal?: AbortSignal) => {
    setCurrentId(thread.id)
    setModelId(thread.chatModelId)
    setError('')
    const loaded = await loadChatMessages(thread.id, signal)
    setMessages(loaded.messages)
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    void Promise.all([listChatThreads(controller.signal), loadChatModels(controller.signal)]).then(async ([saved, catalog]) => {
      setModels(catalog.models)
      setModelId(catalog.defaultModel)
      if (saved.length) {
        setThreads(saved)
        await openThread(saved[0], controller.signal)
      }
    }).catch((caught) => { if (!controller.signal.aborted) setError(caught instanceof Error ? caught.message : 'Не удалось открыть чаты.') })
    return () => controller.abort()
  }, [openThread])

  useEffect(() => { endRef.current?.scrollIntoView({ block: 'end' }) }, [messages, busy])
  useEffect(() => () => {
    voiceHeldRef.current = false
    const active = recorderRef.current
    if (active) {
      active.stream.getTracks().forEach((track) => track.stop())
      recorderRef.current = null
    }
  }, [])

  const newThread = async () => {
    try {
      const thread = await createChatThread(modelId)
      setThreads((value) => [thread, ...value])
      setCurrentId(thread.id)
      setMessages([])
      setError('')
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
        else { setCurrentId(''); setMessages([]) }
      }
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Не удалось удалить чат.') }
  }

  const selectModel = async (model: PhoneChatModel) => {
    if (model.available === false) return
    setModelId(model.id)
    setModelOpen(false)
    if (!current) return
    try {
      const updated = await updateChatThread(current.id, { chatModelId: model.id })
      setThreads((value) => value.map((item) => item.id === updated.id ? updated : item))
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Не удалось сменить модель.') }
  }

  const submit = async () => {
    const content = text.trim() || (images.length ? 'Опиши прикреплённое изображение.' : '')
    if (!content || busy || offline) return
    let thread = current
    try {
      if (!thread) {
        thread = await createChatThread(modelId)
        setThreads((value) => [thread!, ...value])
        setCurrentId(thread.id)
      }
      const optimisticUser: PhoneChatMessage = { id: `user-${requestId()}`, role: 'user', content, provider: '', model: '', tools: [], chargedTokens: 0, tokenKind: '', createdAt: new Date().toISOString(), status: 'done' }
      const pendingId = `pending-${requestId()}`
      const pending: PhoneChatMessage = { ...optimisticUser, id: pendingId, role: 'assistant', content: '', status: 'pending' }
      setMessages((value) => [...value, optimisticUser, pending])
      const attached = [...images]
      setText(''); setImages([]); setBusy(true); setError('')
      const answer = await sendChatMessage({ threadId: thread.id, content, modelId, images: attached, requestId: requestId() })
      const assistantId = answer.messageId || pendingId
      let activeTools = answer.tools || []
      setMessages((value) => value.map((item) => item.id === pendingId ? { ...item, id: assistantId, content: answer.reply, model: answer.modelId, chargedTokens: answer.chargedTokens, tokenKind: answer.tokenKind, tools: activeTools, status: 'done' } : item))
      for (let index = 0; index < activeTools.length; index += 1) {
        if (activeTools[index].name !== 'generate_image' || activeTools[index].status !== 'requested') continue
        const replaceTool = (next: PhoneChatTool) => {
          activeTools = activeTools.map((item, itemIndex) => itemIndex === index ? next : item)
          setMessages((value) => value.map((item) => item.id === assistantId ? { ...item, tools: activeTools } : item))
          if (answer.messageId) void saveChatTools(thread!.id, answer.messageId, activeTools).catch(() => undefined)
        }
        try { await runChatImageTool(activeTools[index], replaceTool) }
        catch (toolError) { replaceTool({ ...activeTools[index], status: 'error', error: toolError instanceof Error ? toolError.message : 'Изображение не создано.' }) }
      }
      const refreshed = await listChatThreads()
      setThreads(refreshed)
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : 'Чат временно недоступен.'
      setMessages((value) => value.map((item) => item.status === 'pending' ? { ...item, content: message, status: 'error' } : item))
      setError(message)
    } finally { setBusy(false) }
  }

  const stopVoice = useCallback(() => {
    const active = recorderRef.current
    if (active?.recorder.state === 'recording') active.recorder.stop()
  }, [])

  const startVoice = async () => {
    if (recording || !navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') return
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      if (!voiceHeldRef.current) { stream.getTracks().forEach((track) => track.stop()); return }
      const mime = ['audio/webm;codecs=opus', 'audio/ogg;codecs=opus', 'audio/webm'].find((item) => MediaRecorder.isTypeSupported(item)) || ''
      const recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined)
      const active = { recorder, stream, chunks: [] as Blob[], startedAt: Date.now() }
      recorderRef.current = active
      recorder.addEventListener('dataavailable', (event) => { if (event.data.size) active.chunks.push(event.data) })
      recorder.addEventListener('stop', async () => {
        setRecording(false)
        active.stream.getTracks().forEach((track) => track.stop())
        recorderRef.current = null
        const duration = Date.now() - active.startedAt
        if (duration < 850) { setError('Удерживайте кнопку и говорите не меньше секунды.'); return }
        try {
          const value = await transcribePhoneVoice(new Blob(active.chunks, { type: recorder.mimeType || 'audio/webm' }), duration)
          if (!value) throw new Error('Речь не распознана.')
          setText((currentText) => `${currentText.trim()}${currentText.trim() ? ' ' : ''}${value}`)
        } catch (caught) { setError(caught instanceof Error ? caught.message : 'Не удалось распознать голос.') }
      }, { once: true })
      recorder.start(250)
      setRecording(true)
    } catch { setError('Разрешите доступ к микрофону в браузере.') }
  }

  return <section className="phone-chat" data-phone-workspace="chat">
    <header className="phone-chat-tabs">
      <div>{threads.map((thread) => <span key={thread.id} className={thread.id === currentId ? 'active' : ''}><button type="button" onClick={() => void openThread(thread)}>{thread.title}</button><button type="button" onClick={() => void removeThread(thread)} aria-label={`Удалить ${thread.title}`}><X /></button></span>)}</div>
      <button type="button" aria-label="Новый чат" onClick={() => void newThread()}><Plus /></button>
    </header>

    <div className="phone-chat-thread">
      {!messages.length && <div className="phone-chat-empty"><b>С чего начнём?</b><span>Напишите сообщение или удерживайте микрофон.</span><div>{quickPrompts.map((prompt) => <button key={prompt} type="button" onClick={() => { setText(prompt); inputRef.current?.focus() }}>{prompt}</button>)}</div></div>}
      {messages.map((message, index) => <ChatMessage key={message.id || index} message={message} onRepeat={() => {
        const source = message.role === 'user' ? message : [...messages.slice(0, index)].reverse().find((item) => item.role === 'user')
        if (source) { setText(source.content); inputRef.current?.focus() }
      }} />)}
      <div ref={endRef} />
    </div>

    {error && <div className="phone-chat-error" role="status">{error}<button type="button" aria-label="Закрыть сообщение" onClick={() => setError('')}><X /></button></div>}
    <footer className="phone-chat-composer">
      {images.length > 0 && <div className="phone-chat-attachments">{images.map((src, index) => <span key={`${src.slice(-20)}-${index}`}><img src={src} alt="Вложение" /><button type="button" aria-label="Убрать изображение" onClick={() => setImages((value) => value.filter((_, itemIndex) => itemIndex !== index))}><X /></button></span>)}</div>}
      <textarea ref={inputRef} value={text} rows={1} maxLength={4000} placeholder="Сообщение…" onChange={(event) => setText(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void submit() } }} />
      <div className="phone-chat-composer-row">
        <input ref={fileRef} hidden multiple type="file" accept="image/jpeg,image/png,image/webp" onChange={async (event) => {
          try {
            const selected = await Promise.all(Array.from(event.target.files || []).slice(0, Math.max(0, 4 - images.length)).map(readImage))
            setImages((value) => [...value, ...selected].slice(0, 4))
          }
          catch (caught) { setError(caught instanceof Error ? caught.message : 'Не удалось добавить изображение.') }
          event.target.value = ''
        }} />
        <button type="button" aria-label="Добавить изображение" onClick={() => fileRef.current?.click()}><Plus /></button>
        <button className={selectedModel?.tokenKind === 'main' ? 'phone-chat-model main' : 'phone-chat-model daily'} type="button" onClick={() => setModelOpen(true)}><Settings2 /><span>{selectedModel?.name || 'ИЗО Чат'}</span><ChevronDown /></button>
        <button className={recording ? 'phone-chat-mic recording' : 'phone-chat-mic'} type="button" aria-label="Удерживайте, чтобы сказать голосом" onPointerDown={(event) => { event.preventDefault(); voiceHeldRef.current = true; event.currentTarget.setPointerCapture(event.pointerId); void startVoice() }} onPointerUp={(event) => { event.preventDefault(); voiceHeldRef.current = false; stopVoice() }} onPointerCancel={() => { voiceHeldRef.current = false; stopVoice() }} onLostPointerCapture={() => { voiceHeldRef.current = false; stopVoice() }}><Mic /></button>
        <button className="phone-chat-send" type="button" aria-label="Отправить" disabled={busy || offline || (!text.trim() && !images.length)} onClick={() => void submit()}><Send /></button>
      </div>
    </footer>

    {modelOpen && <div className="phone-chat-sheet-backdrop" onPointerDown={(event) => { if (event.target === event.currentTarget) setModelOpen(false) }}><section className="phone-chat-model-sheet" role="dialog" aria-modal="true" aria-label="Модель чата"><header><div><small>Ответы и стоимость</small><b>Модель чата</b></div><button type="button" aria-label="Закрыть" onClick={() => setModelOpen(false)}><X /></button></header>{models.map((model) => <button className={`${model.id === modelId ? 'active ' : ''}${model.available === false ? 'unavailable' : ''}`.trim()} type="button" key={model.id} disabled={model.available === false} onClick={() => void selectModel(model)}><span><b>{model.name}</b><small>{model.available === false ? model.unavailableReason : model.description} · контекст {Math.round(model.contextChars / 1000)} тыс.</small></span><em className={phoneTokenClass(model.tokenKind === 'main' ? 'main' : 'daily')}>{model.tokenCost > 0 ? `${model.tokenCost} ток.` : 'Базовая'}</em>{model.id === modelId && <Check />}</button>)}</section></div>}
  </section>
}
