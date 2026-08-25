import { useEffect, useRef, useState } from 'react'
import {
  AlertCircle, CheckCircle2, Cloud, Cpu, FileAudio, Mic2, RefreshCw,
  Save, Server, Settings2, Square, Upload, WandSparkles,
} from 'lucide-react'
import { ensureSessionRefreshedV2 } from './authV2'

const API = (import.meta as ImportMeta & { env?: { VITE_API_BASE_URL?: string } }).env?.VITE_API_BASE_URL || '/api'
const MAX_RECORDING_SECONDS = 30

async function adminFetch(path: string, init: RequestInit = {}) {
  const request = () => fetch(`${API}${path}`, { ...init, credentials: 'include' })
  let response = await request()
  if (response.status === 401 && await ensureSessionRefreshedV2()) response = await request()
  return response
}

type VoiceRoute = 'local' | 'qwen' | 'api' | 'auto'
type TestProvider = VoiceRoute
type VoiceConfig = {
  localModel: string
  qwenModel: string
  qwenBaseUrl: string
  apiModel: string
  route: VoiceRoute
  queueTimeoutSeconds: number
  requestTimeoutSeconds: number
  minRecordingSeconds: number
}
type AssistantConfig = { voice: VoiceConfig; improve: Record<string, unknown> }
type RuntimeStatus = { ok: boolean; baseUrl: string; error?: string; models: Array<{ name?: string; id?: string }> }
type OpenRouterModel = {
  id: string
  name: string
  inputPerMillionUsd: number
  outputPerMillionUsd: number
}
type VoiceData = {
  config: AssistantConfig
  ollama: RuntimeStatus
  qwen: RuntimeStatus
  openrouterConfigured: boolean
  openrouterAudioModels: OpenRouterModel[]
  openrouterAudioModelsError?: string | null
}
type TestResult = { ok?: boolean; text?: string; provider?: string; model?: string; latencyMs?: number; detail?: unknown }

const LABELS: Record<VoiceRoute, string> = {
  local: 'Ollama', qwen: 'Qwen ASR', api: 'OpenRouter', auto: 'Автоматически',
}
const PROVIDER_LABELS: Record<TestProvider, string> = LABELS

function errorText(detail: unknown, fallback: string) {
  if (typeof detail === 'string' && detail.trim()) return detail
  if (detail && typeof detail === 'object' && 'message' in detail && typeof detail.message === 'string') return detail.message
  return fallback
}

function formatPrice(model: OpenRouterModel) {
  return `$${model.inputPerMillionUsd}/M вход · $${model.outputPerMillionUsd}/M выход`
}

const CSS = `
.voice-admin{--va-panel:#121612;--va-soft:#171c17;--va-line:rgba(255,255,255,.11);--va-muted:#aab2a7;--va-lime:#d8ef55;display:grid;gap:12px;color:#f4f6ef}
.voice-admin *{box-sizing:border-box}.voice-admin h2,.voice-admin h3,.voice-admin p{margin:0}.voice-admin button,.voice-admin input,.voice-admin select{font:inherit}
.voice-hero{display:flex;align-items:center;justify-content:space-between;gap:18px;padding:17px 18px;border:1px solid var(--va-line);border-radius:8px;background:linear-gradient(110deg,rgba(216,239,85,.07),transparent 46%),#101310}
.voice-title{display:flex;gap:13px;align-items:center}.voice-title-icon{width:42px;height:42px;display:grid;place-items:center;flex:0 0 auto;border:1px solid rgba(216,239,85,.42);border-radius:8px;color:var(--va-lime);background:rgba(216,239,85,.08)}
.voice-title h2{font-size:20px}.voice-title p{margin-top:5px;max-width:720px;color:var(--va-muted);font-size:12px;line-height:1.45}.voice-current{text-align:right}.voice-current span{display:block;color:var(--va-muted);font-size:10px;text-transform:uppercase}.voice-current strong{display:block;margin-top:4px;color:var(--va-lime);font-size:15px}
.voice-inline-loading,.voice-embedded-current{display:flex;align-items:center;gap:9px;padding:9px 11px;border:1px solid var(--va-line);border-radius:7px;background:var(--va-panel);color:var(--va-muted);font-size:11px}.voice-embedded-current{justify-content:flex-end}.voice-embedded-current strong{color:var(--va-lime)}
.voice-section-title h3{font-size:15px}.voice-section-title p{margin-top:4px;color:var(--va-muted);font-size:11px;line-height:1.45}
.voice-route-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:9px}.voice-route-card{min-width:0;min-height:108px;padding:13px;border:1px solid var(--va-line);border-radius:8px;background:var(--va-panel);color:#f4f6ef;text-align:left;cursor:pointer;box-shadow:inset 0 1px rgba(255,255,255,.035),0 2px 5px rgba(0,0,0,.18);transition:transform .15s,border-color .15s,background .15s}.voice-route-card:hover:not(:disabled){transform:translateY(-2px);border-color:rgba(216,239,85,.42)}.voice-route-card.active{border-color:var(--va-lime);background:linear-gradient(145deg,rgba(216,239,85,.11),rgba(216,239,85,.025)),var(--va-panel);box-shadow:inset 0 1px rgba(255,255,255,.08),0 3px 8px rgba(0,0,0,.28)}.voice-route-card:disabled{opacity:.5;cursor:not-allowed}
.voice-route-head{display:flex;align-items:center;justify-content:space-between;gap:8px}.voice-route-name{display:flex;align-items:center;gap:7px;font-weight:750}.voice-route-card p{margin-top:9px;color:var(--va-muted);font-size:10px;line-height:1.4}.voice-route-card code{display:block;margin-top:7px;color:#e5eadf;font-size:10px;overflow-wrap:anywhere}.voice-status{display:inline-flex;align-items:center;gap:4px;padding:3px 6px;border:1px solid rgba(255,116,121,.3);border-radius:999px;color:#ff8e92;font-size:9px;white-space:nowrap}.voice-status.ok{color:#77df83;border-color:rgba(119,223,131,.32)}
.voice-workspace{display:grid;grid-template-columns:minmax(330px,.8fr) minmax(460px,1.2fr);gap:12px}.voice-panel{min-width:0;border:1px solid var(--va-line);border-radius:8px;background:var(--va-panel)}.voice-panel-head{padding:14px;border-bottom:1px solid var(--va-line)}
.voice-test-body{display:grid;gap:12px;padding:14px}.voice-recorder{display:grid;place-items:center;gap:8px;min-height:188px;padding:18px;border:1px solid rgba(216,239,85,.26);border-radius:8px;background:radial-gradient(circle at 50% 48%,rgba(216,239,85,.09),transparent 42%),#0d110d;text-align:center}.voice-record-button{position:relative;width:72px;height:72px;display:grid;place-items:center;border:1px solid rgba(216,239,85,.72);border-radius:50%;background:linear-gradient(145deg,#e5f86d,#aeca00);color:#101308;cursor:pointer;box-shadow:inset 0 2px rgba(255,255,255,.6),0 7px 18px rgba(174,202,0,.18)}.voice-record-button.recording{border-color:#ff8589;background:#e75c62;color:#fff}.voice-record-button.recording:before,.voice-record-button.recording:after{content:'';position:absolute;inset:-8px;border:1px solid rgba(255,103,109,.55);border-radius:50%;animation:voice-pulse 1.4s infinite}.voice-record-button.recording:after{animation-delay:.7s}.voice-recorder strong{font-size:15px}.voice-recorder p{max-width:360px;color:var(--va-muted);font-size:11px;line-height:1.45}.voice-timer{font-variant-numeric:tabular-nums;color:var(--va-lime);font-size:22px;font-weight:750}@keyframes voice-pulse{to{inset:-24px;opacity:0}}
.voice-test-options{display:grid;grid-template-columns:1fr auto;gap:9px;align-items:end}.voice-field{display:grid;gap:6px}.voice-field label{color:var(--va-muted);font-size:9px;font-weight:750;text-transform:uppercase}.voice-field small{color:var(--va-muted);font-size:9px;line-height:1.35}.voice-field input,.voice-field select{width:100%;min-height:39px;border:1px solid rgba(255,255,255,.16);border-radius:7px;padding:0 10px;background:#181c18;color:#f5f7ef;color-scheme:dark}.voice-field option{background:#181c18;color:#f5f7ef}.voice-field input:focus,.voice-field select:focus{outline:1px solid rgba(216,239,85,.65);border-color:transparent}
.voice-upload{position:relative;min-height:39px;display:inline-flex;align-items:center;justify-content:center;gap:7px;padding:0 12px;border:1px solid var(--va-line);border-radius:7px;background:#181c18;color:#e4e8df;cursor:pointer;white-space:nowrap}.voice-upload:hover{border-color:rgba(216,239,85,.45)}.voice-upload input{position:absolute;inset:0;opacity:0;cursor:pointer}.voice-file-name{padding:9px 10px;border:1px solid var(--va-line);border-radius:7px;background:#0c0f0c;color:var(--va-muted);font-size:10px;overflow-wrap:anywhere}.voice-run{min-height:39px;display:flex;align-items:center;justify-content:center;gap:7px;border:1px solid var(--va-lime);border-radius:7px;background:var(--va-lime);color:#0a0c08;font-weight:750;cursor:pointer;box-shadow:inset 0 1px rgba(255,255,255,.75),0 2px 5px rgba(0,0,0,.3)}.voice-run:disabled{opacity:.45;cursor:not-allowed}
.voice-result{padding:12px;border:1px solid rgba(119,223,131,.28);border-radius:7px;background:#0c0f0c}.voice-result strong{display:block;font-size:13px;line-height:1.5}.voice-result small{display:block;margin-top:7px;color:var(--va-muted);font-size:10px;overflow-wrap:anywhere}.voice-result.error{border-color:rgba(255,116,121,.3);color:#ffb4b7}
.voice-settings-body{display:grid;gap:13px;padding:14px}.voice-selected{display:flex;gap:10px;align-items:flex-start;padding:11px;border:1px solid rgba(216,239,85,.2);border-radius:7px;background:rgba(216,239,85,.035)}.voice-selected svg{flex:0 0 auto;color:var(--va-lime)}.voice-selected strong{display:block;font-size:12px}.voice-selected span{display:block;margin-top:3px;color:var(--va-muted);font-size:10px;line-height:1.4}.voice-price{color:var(--va-lime)!important}.voice-auto-order{display:grid;gap:7px}.voice-auto-step{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:10px;border:1px solid var(--va-line);border-radius:7px;background:#0e120e;font-size:11px}.voice-auto-step span{color:var(--va-muted)}
.voice-technical{border:1px solid var(--va-line);border-radius:7px;background:#0e120e}.voice-technical summary{display:flex;align-items:center;gap:7px;padding:11px;cursor:pointer;font-size:11px;font-weight:700}.voice-tech-fields{display:grid;grid-template-columns:1fr 1fr;gap:10px;padding:0 11px 11px}.voice-tech-fields .full{grid-column:1/-1}.voice-save{min-height:40px;display:flex;align-items:center;justify-content:center;gap:7px;border:1px solid var(--va-lime);border-radius:7px;background:var(--va-lime);color:#090b08;font-weight:750;cursor:pointer;box-shadow:inset 0 1px rgba(255,255,255,.8),0 2px 5px rgba(0,0,0,.35)}.voice-save:disabled{opacity:.55;cursor:wait}
.voice-catalog{border:1px solid var(--va-line);border-radius:8px;background:var(--va-panel)}.voice-catalog summary{cursor:pointer;padding:13px 14px;color:#f4f6ef;font-size:12px;font-weight:700}.voice-catalog-body{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;padding:0 14px 14px}.voice-candidate{padding:10px;border-top:1px solid var(--va-line)}.voice-candidate strong{display:block;font-size:11px}.voice-candidate span{display:block;margin-top:4px;color:var(--va-muted);font-size:9px;line-height:1.4}
@media(max-width:1050px){.voice-route-grid{grid-template-columns:1fr 1fr}.voice-workspace{grid-template-columns:1fr}.voice-catalog-body{grid-template-columns:1fr 1fr}}
@media(max-width:560px){.voice-hero{align-items:flex-start;padding:14px}.voice-current{display:none}.voice-title h2{font-size:17px}.voice-route-grid{grid-template-columns:1fr}.voice-route-card{min-height:92px}.voice-test-options,.voice-tech-fields,.voice-catalog-body{grid-template-columns:1fr}.voice-tech-fields .full{grid-column:auto}.voice-upload{width:100%}.voice-recorder{min-height:170px}}
`

export default function AdminVoice({ embedded = false }: { embedded?: boolean }) {
  const [data, setData] = useState<VoiceData | null>(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [testFile, setTestFile] = useState<File | null>(null)
  const [testProvider, setTestProvider] = useState<TestProvider>('api')
  const [testResult, setTestResult] = useState<TestResult | null>(null)
  const [recording, setRecording] = useState(false)
  const [recordingSeconds, setRecordingSeconds] = useState(0)
  const recorderRef = useRef<MediaRecorder | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const startedAtRef = useRef(0)
  const timerRef = useRef<number | null>(null)

  const load = async () => {
    const response = await adminFetch('/admin/assistants').catch(() => null)
    const body = response ? await response.json().catch(() => null) as VoiceData | null : null
    if (!response?.ok || !body?.config) {
      setMessage('Не удалось загрузить голосовую конфигурацию.')
      return
    }
    const currentVoice = body.config.voice
    setTestProvider(currentVoice.route)
    setData({
      ...body,
      openrouterAudioModels: body.openrouterAudioModels || [],
      qwen: body.qwen || { ok: false, baseUrl: 'http://127.0.0.1:8001', models: [], error: 'BackendNotUpdated' },
      config: {
        ...body.config,
        voice: {
          ...currentVoice,
          localModel: currentVoice.localModel === 'qwen3-asr:1.7b' ? 'gemma4:12b' : currentVoice.localModel || 'gemma4:12b',
          qwenModel: currentVoice.qwenModel || 'Qwen/Qwen3-ASR-1.7B',
          qwenBaseUrl: currentVoice.qwenBaseUrl || 'http://127.0.0.1:8001',
        },
      },
    })
  }

  useEffect(() => { queueMicrotask(() => { void load() }) }, [])
  useEffect(() => () => {
    if (timerRef.current !== null) window.clearInterval(timerRef.current)
    if (recorderRef.current?.state === 'recording') recorderRef.current.stop()
    streamRef.current?.getTracks().forEach((track) => track.stop())
  }, [])

  const updateVoice = (patch: Partial<VoiceConfig>) => setData((current) => current ? {
    ...current, config: { ...current.config, voice: { ...current.config.voice, ...patch } },
  } : current)

  const save = async () => {
    if (!data) return
    setBusy(true); setMessage('')
    const response = await adminFetch('/admin/settings/assistant_models', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ settings: data.config }),
    }).catch(() => null)
    const body = response ? await response.json().catch(() => ({})) as { detail?: unknown } : {}
    setBusy(false)
    setMessage(response?.ok ? 'Настройки голосового ввода сохранены.' : errorText(body.detail, 'Настройки не сохранены.'))
    if (response?.ok) await load()
  }

  const test = async (file = testFile) => {
    if (!file) return
    setBusy(true); setTestResult(null); setMessage('')
    const form = new FormData(); form.append('file', file)
    const response = await adminFetch(`/admin/assistants/voice-test?provider=${testProvider}&language=ru`, { method: 'POST', body: form }).catch(() => null)
    const body = response ? await response.json().catch(() => ({})) as TestResult : { detail: 'Сервер не ответил.' }
    setBusy(false)
    setTestResult(response?.ok ? body : { ...body, ok: false, detail: errorText(body.detail, `Ошибка сервера ${response?.status || ''}`) })
  }

  const stopRecording = () => {
    if (recorderRef.current?.state === 'recording') recorderRef.current.stop()
  }

  const startRecording = async () => {
    if (recording) { stopRecording(); return }
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
      setTestResult({ ok: false, detail: 'Этот браузер не поддерживает запись с микрофона.' })
      return
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const mimeType = ['audio/webm;codecs=opus', 'audio/ogg;codecs=opus', 'audio/webm'].find((type) => MediaRecorder.isTypeSupported(type)) || ''
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined)
      const chunks: BlobPart[] = []
      recorder.ondataavailable = (event) => { if (event.data.size) chunks.push(event.data) }
      recorder.onerror = () => setTestResult({ ok: false, detail: 'Не удалось записать голос.' })
      recorder.onstop = () => {
        if (timerRef.current !== null) window.clearInterval(timerRef.current)
        timerRef.current = null
        setRecording(false)
        stream.getTracks().forEach((track) => track.stop())
        streamRef.current = null
        recorderRef.current = null
        const duration = (Date.now() - startedAtRef.current) / 1000
        if (duration < (data?.config.voice.minRecordingSeconds || 1)) {
          setTestResult({ ok: false, detail: `Запишите не меньше ${data?.config.voice.minRecordingSeconds || 1} сек.` })
          return
        }
        const type = recorder.mimeType || 'audio/webm'
        const extension = type.includes('ogg') ? 'ogg' : 'webm'
        const file = new File([new Blob(chunks, { type })], `voice-test.${extension}`, { type })
        setTestFile(file)
        void test(file)
      }
      recorderRef.current = recorder
      streamRef.current = stream
      startedAtRef.current = Date.now()
      setRecordingSeconds(0); setRecording(true); setTestResult(null)
      recorder.start(250)
      timerRef.current = window.setInterval(() => {
        const seconds = Math.floor((Date.now() - startedAtRef.current) / 1000)
        setRecordingSeconds(seconds)
        if (seconds >= MAX_RECORDING_SECONDS) stopRecording()
      }, 250)
    } catch {
      setTestResult({ ok: false, detail: 'Разрешите этой странице доступ к микрофону.' })
    }
  }

  if (!data) return <div className="voice-admin"><style>{CSS}</style>{embedded
    ? <div className="voice-inline-loading"><RefreshCw size={18} /><span>{message || 'Загружаю статусы моделей...'}</span></div>
    : <div className="voice-hero"><div className="voice-title"><RefreshCw size={20} /><div><h2>Голосовой ввод</h2><p>{message || 'Загружаю статусы моделей...'}</p></div></div></div>}</div>

  const voice = data.config.voice
  const ollamaModels = data.ollama.models.map((model) => model.name).filter(Boolean) as string[]
  const selectedApiModel = data.openrouterAudioModels.find((model) => model.id === voice.apiModel)
  const routeCards: Array<{ route: VoiceRoute; icon: typeof Cpu; ok: boolean; status: string; description: string; detail: string }> = [
    { route: 'local', icon: Cpu, ok: data.ollama.ok, status: data.ollama.ok ? 'готова' : 'нет связи', description: 'Локальная модель Ollama. Без оплаты за вызов.', detail: voice.localModel },
    { route: 'qwen', icon: Server, ok: data.qwen.ok, status: data.qwen.ok ? 'готова' : 'не запущена', description: 'Отдельный специализированный сервис распознавания.', detail: voice.qwenModel },
    { route: 'api', icon: Cloud, ok: data.openrouterConfigured, status: data.openrouterConfigured ? 'ключ готов' : 'нет ключа', description: 'Облачная модель. Платный резерв и быстрый старт.', detail: voice.apiModel },
    { route: 'auto', icon: WandSparkles, ok: data.qwen.ok || data.ollama.ok || data.openrouterConfigured, status: 'резерв', description: 'Если первый способ недоступен, система пробует следующий.', detail: 'Qwen -> Ollama -> OpenRouter' },
  ]

  return <div className="voice-admin">
    <style>{CSS}</style>
    {!embedded && <section className="voice-hero">
      <div className="voice-title"><div className="voice-title-icon"><Mic2 size={21} /></div><div><h2>Голосовой ввод</h2><p>Выберите основной способ, запишите тестовую фразу и сразу увидите реальный результат.</p></div></div>
      <div className="voice-current"><span>Сейчас используется</span><strong>{LABELS[voice.route]}</strong></div>
    </section>}
    {embedded && <div className="voice-embedded-current"><span>Сейчас используется:</span><strong>{LABELS[voice.route]}</strong></div>}

    <div className="voice-section-title"><h3>1. Способ распознавания</h3><p>Недоступные сервисы нельзя выбрать. Автоматический режим переключается на резерв только при ошибке.</p></div>
    <section className="voice-route-grid">
      {routeCards.map(({ route, icon: Icon, ok, status, description, detail }) => <button
        key={route}
        type="button"
        className={`voice-route-card${voice.route === route ? ' active' : ''}`}
        disabled={!ok}
        onClick={() => { updateVoice({ route }); setTestProvider(route); setMessage('') }}
      >
        <span className="voice-route-head"><span className="voice-route-name"><Icon size={17} />{LABELS[route]}</span><span className={`voice-status${ok ? ' ok' : ''}`}>{ok ? <CheckCircle2 size={11} /> : <AlertCircle size={11} />}{status}</span></span>
        <p>{description}</p><code>{detail}</code>
      </button>)}
    </section>

    <section className="voice-workspace">
      <div className="voice-panel">
        <header className="voice-panel-head voice-section-title"><h3>2. Проверка голосом</h3><p>Нажмите «Начать запись», произнесите фразу и нажмите «Стоп». Результат появится ниже.</p></header>
        <div className="voice-test-body">
          <div className="voice-recorder">
            <button className={`voice-record-button${recording ? ' recording' : ''}`} type="button" disabled={busy} onClick={() => void startRecording()} aria-label={recording ? 'Стоп' : 'Начать запись'}>{recording ? <Square size={25} fill="currentColor" /> : <Mic2 size={30} />}</button>
            {recording ? <><span className="voice-timer">00:{String(recordingSeconds).padStart(2, '0')}</span><strong>Идёт запись</strong><p>Говорите. Максимальная длительность {MAX_RECORDING_SECONDS} секунд.</p></> : <><strong>{busy ? 'Распознаю запись...' : 'Начать запись'}</strong><p>Браузер запросит доступ к микрофону. После остановки тест запустится автоматически.</p></>}
          </div>
          <div className="voice-test-options">
            <div className="voice-field"><label>Проверить через</label><select value={testProvider} onChange={(event) => setTestProvider(event.target.value as TestProvider)} disabled={recording || busy}><option value="local" disabled={!data.ollama.ok}>Ollama{data.ollama.ok ? '' : ' — недоступна'}</option><option value="qwen" disabled={!data.qwen.ok}>Qwen ASR{data.qwen.ok ? '' : ' — не запущена'}</option><option value="api" disabled={!data.openrouterConfigured}>OpenRouter{data.openrouterConfigured ? '' : ' — нет ключа'}</option><option value="auto">Автоматически: Qwen → Ollama → OpenRouter</option></select><small>Тестируется именно этот выбор, даже до сохранения настроек.</small></div>
            <label className="voice-upload"><Upload size={15} /><span>Загрузить файл</span><input type="file" accept="audio/wav,audio/webm,audio/ogg,audio/mpeg,audio/mp4" onChange={(event) => { setTestFile(event.target.files?.[0] || null); setTestResult(null) }} /></label>
          </div>
          {testFile && !recording && <><div className="voice-file-name"><FileAudio size={13} /> {testFile.name}</div><button className="voice-run" type="button" disabled={busy} onClick={() => void test()}><Mic2 size={15} />{busy ? 'Распознаю...' : 'Распознать выбранный файл'}</button></>}
          {testResult && <div className={`voice-result${testResult.ok ? '' : ' error'}`}><strong>{testResult.text || errorText(testResult.detail, 'Тест не выполнен.')}</strong>{testResult.ok && <small>{PROVIDER_LABELS[testResult.provider as TestProvider] || testResult.provider} · {testResult.model} · {testResult.latencyMs} мс</small>}</div>}
        </div>
      </div>

      <div className="voice-panel">
        <header className="voice-panel-head voice-section-title"><h3>3. Модель и настройки</h3><p>Здесь показаны только параметры выбранного способа распознавания.</p></header>
        <div className="voice-settings-body">
          {voice.route === 'local' && <>
            <div className="voice-selected"><Cpu size={18} /><div><strong>Ollama работает локально</strong><span>Выберите одну из моделей, реально установленных на сервере.</span></div></div>
            <div className="voice-field"><label>Модель Ollama</label><select value={voice.localModel} onChange={(event) => updateVoice({ localModel: event.target.value })}>{!ollamaModels.includes(voice.localModel) && <option value={voice.localModel}>{voice.localModel} — не установлена</option>}{ollamaModels.map((name) => <option key={name} value={name}>{name}</option>)}</select></div>
          </>}
          {voice.route === 'qwen' && <>
            <div className="voice-selected"><Server size={18} /><div><strong>Qwen ASR — отдельный сервис</strong><span>Он не является моделью Ollama. Выбор станет доступен после запуска сервиса.</span></div></div>
            <div className="voice-field"><label>Модель Qwen ASR</label><select value={voice.qwenModel} onChange={(event) => updateVoice({ qwenModel: event.target.value })}><option value="Qwen/Qwen3-ASR-1.7B">Qwen3-ASR 1.7B — основная</option><option value="Qwen/Qwen3-ASR-0.6B">Qwen3-ASR 0.6B — облегчённая</option></select></div>
          </>}
          {voice.route === 'api' && <>
            <div className="voice-selected"><Cloud size={18} /><div><strong>OpenRouter использует API-ключ</strong><span>В списке только модели, заявившие поддержку аудиовхода.</span>{selectedApiModel && <span className="voice-price">{formatPrice(selectedApiModel)}</span>}</div></div>
            <div className="voice-field"><label>Аудиомодель OpenRouter</label><select value={voice.apiModel} onChange={(event) => updateVoice({ apiModel: event.target.value })}>{!data.openrouterAudioModels.some((model) => model.id === voice.apiModel) && <option value={voice.apiModel}>{voice.apiModel} — сохранённая модель</option>}{data.openrouterAudioModels.map((model) => <option key={model.id} value={model.id}>{model.name} · {formatPrice(model)}</option>)}</select><small>{data.openrouterAudioModelsError ? `Каталог временно недоступен: ${data.openrouterAudioModelsError}` : `${data.openrouterAudioModels.length} аудиосовместимых моделей`}</small></div>
          </>}
          {voice.route === 'auto' && <>
            <div className="voice-selected"><WandSparkles size={18} /><div><strong>Автоматическое резервирование</strong><span>Каждый следующий сервис вызывается только если предыдущий завершился ошибкой.</span></div></div>
            <div className="voice-auto-order"><div className="voice-auto-step"><strong>1. Qwen ASR</strong><span>{data.qwen.ok ? 'готов' : 'будет пропущен'}</span></div><div className="voice-auto-step"><strong>2. Ollama</strong><span>{data.ollama.ok ? 'готова' : 'будет пропущена'}</span></div><div className="voice-auto-step"><strong>3. OpenRouter</strong><span>{data.openrouterConfigured ? 'готов' : 'будет пропущен'}</span></div></div>
          </>}

          <details className="voice-technical"><summary><Settings2 size={15} />Технические настройки</summary><div className="voice-tech-fields">
            <div className="voice-field full"><label>URL сервиса Qwen ASR</label><input value={voice.qwenBaseUrl} onChange={(event) => updateVoice({ qwenBaseUrl: event.target.value })} /></div>
            <div className="voice-field"><label>Таймаут ответа, сек.</label><input type="number" min="10" max="180" value={voice.requestTimeoutSeconds} onChange={(event) => updateVoice({ requestTimeoutSeconds: Number(event.target.value) })} /></div>
            <div className="voice-field"><label>Минимальная запись, сек.</label><input type="number" min="0.5" max="10" step="0.5" value={voice.minRecordingSeconds} onChange={(event) => updateVoice({ minRecordingSeconds: Number(event.target.value) })} /></div>
          </div></details>
          <button className="voice-save" type="button" disabled={busy || recording} onClick={() => void save()}><Save size={15} />{busy ? 'Обрабатываю...' : 'Сохранить настройки'}</button>
          {message && <div className="voice-result"><strong>{message}</strong></div>}
        </div>
      </div>
    </section>

    <details className="voice-catalog"><summary>Модели для будущих сравнительных тестов</summary><div className="voice-catalog-body"><div className="voice-candidate"><strong>Qwen3-ASR 1.7B</strong><span>Основной специализированный локальный кандидат.</span></div><div className="voice-candidate"><strong>Qwen3-ASR 0.6B</strong><span>Облегчённая модель для сравнения скорости и русского языка.</span></div><div className="voice-candidate"><strong>Faster Whisper Large V3 Turbo</strong><span>Зрелый резервный локальный маршрут с VAD.</span></div></div></details>
  </div>
}
