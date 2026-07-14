import { useEffect, useRef, useState } from 'react'
import { AlertCircle, CheckCircle2, Cloud, Cpu, FileAudio, Mic2, RefreshCw, Server, Upload } from 'lucide-react'
import { ensureSessionRefreshedV2 } from './authV2'

const API = (import.meta as ImportMeta & { env?: { VITE_API_BASE_URL?: string } }).env?.VITE_API_BASE_URL || '/api'
async function adminFetch(path: string, init: RequestInit = {}) {
  const request = () => fetch(`${API}${path}`, { ...init, credentials: 'include' })
  let response = await request()
  if (response.status === 401 && await ensureSessionRefreshedV2()) response = await request()
  return response
}

type VoiceRoute = 'local' | 'qwen' | 'api' | 'auto'
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
type VoiceData = {
  config: AssistantConfig
  ollama: RuntimeStatus
  qwen: RuntimeStatus
  openrouterConfigured: boolean
}
type TestResult = { ok?: boolean; text?: string; provider?: string; model?: string; latencyMs?: number; detail?: string }

const LABELS: Record<VoiceRoute, string> = {
  local: 'Ollama', qwen: 'Qwen ASR', api: 'OpenRouter', auto: 'Авторезерв',
}

const CSS = `
.voice-admin{--va-panel:#121612;--va-line:rgba(255,255,255,.11);--va-muted:#aab2a7;--va-lime:#d8ef55;display:grid;gap:12px;color:#f4f6ef}
.voice-admin *{box-sizing:border-box}.voice-admin h2,.voice-admin h3,.voice-admin p{margin:0}.voice-admin button{font:inherit}
.voice-hero{display:grid;grid-template-columns:minmax(0,1.35fr) minmax(320px,.65fr);gap:12px;padding:18px;border:1px solid var(--va-line);border-radius:8px;background:linear-gradient(110deg,rgba(216,239,85,.07),transparent 46%),#101310}
.voice-title{display:flex;gap:13px;align-items:flex-start}.voice-title-icon{width:42px;height:42px;display:grid;place-items:center;border:1px solid rgba(216,239,85,.42);border-radius:8px;color:var(--va-lime);background:rgba(216,239,85,.08)}
.voice-title h2{font-size:20px}.voice-title p{margin-top:5px;max-width:720px;color:var(--va-muted);font-size:13px;line-height:1.45}
.voice-current{display:flex;align-items:center;justify-content:space-between;gap:12px;padding-left:16px;border-left:1px solid var(--va-line)}.voice-current span{display:block;color:var(--va-muted);font-size:10px;text-transform:uppercase}.voice-current strong{display:block;margin-top:4px;color:var(--va-lime);font-size:15px}
.voice-provider-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}.voice-provider{min-width:0;padding:14px;border:1px solid var(--va-line);border-radius:8px;background:var(--va-panel)}
.voice-provider-head{display:flex;align-items:center;justify-content:space-between;gap:10px}.voice-provider-name{display:flex;align-items:center;gap:8px}.voice-provider h3{font-size:14px}.voice-provider p{margin-top:10px;color:var(--va-muted);font-size:12px;line-height:1.45}.voice-provider code{display:block;margin-top:8px;color:#dce5da;font-size:11px;overflow-wrap:anywhere}
.voice-status{display:inline-flex;align-items:center;gap:5px;padding:3px 7px;border:1px solid rgba(255,116,121,.3);border-radius:999px;color:#ff8e92;font-size:10px;white-space:nowrap}.voice-status.ok{color:#77df83;border-color:rgba(119,223,131,.32)}
.voice-route{display:grid;grid-template-columns:repeat(4,1fr);padding:3px;border:1px solid var(--va-line);border-radius:8px;background:#0b0e0b}.voice-route button{min-height:38px;border:0;border-radius:6px;background:transparent;color:var(--va-muted);cursor:pointer}.voice-route button.active{background:var(--va-lime);color:#0a0c08;box-shadow:inset 0 1px rgba(255,255,255,.7),0 2px 5px rgba(0,0,0,.35)}.voice-route button:disabled{opacity:.42;cursor:not-allowed}
.voice-workspace{display:grid;grid-template-columns:minmax(0,1.35fr) minmax(320px,.65fr);gap:12px}.voice-config,.voice-test{border:1px solid var(--va-line);border-radius:8px;background:var(--va-panel)}
.voice-section-head{padding:13px 14px;border-bottom:1px solid var(--va-line)}.voice-section-head h3{font-size:15px}.voice-section-head p{margin-top:4px;color:var(--va-muted);font-size:11px}
.voice-fields{display:grid;grid-template-columns:1fr 1fr;gap:11px;padding:14px}.voice-field{display:grid;gap:6px}.voice-field.full{grid-column:1/-1}.voice-field label{color:var(--va-muted);font-size:10px;font-weight:750;text-transform:uppercase}.voice-field small{color:var(--va-muted);font-size:10px;line-height:1.4}
.voice-field input,.voice-field select{width:100%;min-height:38px;border:1px solid rgba(255,255,255,.17);border-radius:7px;padding:0 10px;background:#181c18;color:#f5f7ef;color-scheme:dark}.voice-field input:focus,.voice-field select:focus{outline:1px solid rgba(216,239,85,.65);border-color:transparent}.voice-field option{background:#181c18;color:#f5f7ef}
.voice-save{margin:0 14px 14px;min-height:38px;border:1px solid #d8ef55;border-radius:7px;background:#d8ef55;color:#090b08;font-weight:750;cursor:pointer;box-shadow:inset 0 1px rgba(255,255,255,.8),0 2px 5px rgba(0,0,0,.35)}.voice-save:disabled{opacity:.55;cursor:wait}
.voice-test-body{display:grid;gap:11px;padding:14px}.voice-file{position:relative;display:grid;place-items:center;gap:7px;min-height:112px;border:1px dashed rgba(216,239,85,.35);border-radius:7px;background:rgba(216,239,85,.035);color:var(--va-muted);text-align:center;cursor:pointer}.voice-file input{position:absolute;inset:0;opacity:0;cursor:pointer}.voice-file strong{color:#f4f6ef;font-size:12px}.voice-file small{font-size:10px}
.voice-test-actions{display:grid;grid-template-columns:1fr auto;gap:8px}.voice-test-actions select{min-width:0;height:38px;border:1px solid var(--va-line);border-radius:7px;padding:0 9px;background:#181c18;color:#f5f7ef;color-scheme:dark}.voice-test-actions button{width:42px;height:38px;display:grid;place-items:center;border:1px solid rgba(216,239,85,.5);border-radius:7px;background:rgba(216,239,85,.08);color:var(--va-lime);cursor:pointer}.voice-test-actions button:disabled{opacity:.45;cursor:not-allowed}
.voice-result{padding:11px;border:1px solid var(--va-line);border-radius:7px;background:#0c0f0c}.voice-result strong{display:block;font-size:13px;line-height:1.45}.voice-result small{display:block;margin-top:7px;color:var(--va-muted);font-size:10px;overflow-wrap:anywhere}.voice-result.error{border-color:rgba(255,116,121,.3);color:#ffb4b7}
.voice-catalog{border:1px solid var(--va-line);border-radius:8px;background:var(--va-panel)}.voice-catalog summary{cursor:pointer;padding:13px 14px;color:#f4f6ef;font-size:13px;font-weight:700}.voice-catalog-body{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;padding:0 14px 14px}.voice-candidate{padding:10px;border-top:1px solid var(--va-line)}.voice-candidate strong{display:block;font-size:12px}.voice-candidate span{display:block;margin-top:4px;color:var(--va-muted);font-size:10px;line-height:1.4}
@media(max-width:900px){.voice-hero,.voice-workspace{grid-template-columns:1fr}.voice-current{padding:12px 0 0;border-left:0;border-top:1px solid var(--va-line)}.voice-provider-grid{grid-template-columns:1fr}.voice-catalog-body{grid-template-columns:1fr 1fr}}
@media(max-width:560px){.voice-route{grid-template-columns:1fr 1fr}.voice-fields,.voice-catalog-body{grid-template-columns:1fr}.voice-field.full{grid-column:auto}.voice-hero{padding:14px}.voice-title h2{font-size:17px}}
`

export default function AdminVoice() {
  const [data, setData] = useState<VoiceData | null>(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [testFile, setTestFile] = useState<File | null>(null)
  const [testProvider, setTestProvider] = useState<'configured' | 'local' | 'qwen' | 'api'>('configured')
  const [testResult, setTestResult] = useState<TestResult | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  const load = async () => {
    const response = await adminFetch('/admin/assistants').catch(() => null)
    const body = response ? await response.json().catch(() => null) as VoiceData | null : null
    if (response?.ok && body?.config) {
      const currentVoice = body.config.voice
      setData({
        ...body,
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
    else setMessage('Не удалось загрузить голосовую конфигурацию.')
  }
  useEffect(() => { queueMicrotask(() => { void load() }) }, [])

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
    const body = response ? await response.json().catch(() => ({})) as { detail?: string } : {}
    setBusy(false)
    setMessage(response?.ok ? 'Голосовой маршрут сохранён.' : body.detail || 'Настройки не сохранены.')
    if (response?.ok) await load()
  }

  const test = async () => {
    if (!testFile) return
    setBusy(true); setTestResult(null)
    const form = new FormData(); form.append('file', testFile)
    const response = await adminFetch(`/admin/assistants/voice-test?provider=${testProvider}&language=ru`, { method: 'POST', body: form }).catch(() => null)
    const body = response ? await response.json().catch(() => ({})) as TestResult : { detail: 'Сервер не ответил.' }
    setBusy(false); setTestResult(body)
  }

  if (!data) return <div className="voice-admin"><style>{CSS}</style><div className="voice-hero"><div className="voice-title"><RefreshCw size={20} /><div><h2>Голосовой ввод</h2><p>{message || 'Загружаю статусы моделей…'}</p></div></div></div></div>

  const voice = data.config.voice
  const ollamaModels = data.ollama.models.map((model) => model.name).filter(Boolean) as string[]
  return <div className="voice-admin">
    <style>{CSS}</style>
    <section className="voice-hero">
      <div className="voice-title"><div className="voice-title-icon"><Mic2 size={21} /></div><div><h2>Голосовой ввод</h2><p>Три независимых маршрута распознавания. Qwen работает через свой ASR-сервис и не выдаётся за модель Ollama.</p></div></div>
      <div className="voice-current"><div><span>Текущий маршрут</span><strong>{LABELS[voice.route]}</strong></div>{voice.route === 'auto' && <small>Qwen → Ollama → OpenRouter</small>}</div>
    </section>

    <section className="voice-provider-grid">
      <article className="voice-provider"><div className="voice-provider-head"><div className="voice-provider-name"><Cpu size={17} /><h3>Ollama</h3></div><span className={`voice-status${data.ollama.ok ? ' ok' : ''}`}>{data.ollama.ok ? <CheckCircle2 size={12} /> : <AlertCircle size={12} />}{data.ollama.ok ? 'в сети' : 'нет связи'}</span></div><p>Локальная Gemma без цены за вызов.</p><code>{voice.localModel}</code></article>
      <article className="voice-provider"><div className="voice-provider-head"><div className="voice-provider-name"><Server size={17} /><h3>Qwen ASR</h3></div><span className={`voice-status${data.qwen.ok ? ' ok' : ''}`}>{data.qwen.ok ? <CheckCircle2 size={12} /> : <AlertCircle size={12} />}{data.qwen.ok ? 'готов' : 'не запущен'}</span></div><p>Отдельный OpenAI-совместимый ASR runtime.</p><code>{voice.qwenBaseUrl}</code></article>
      <article className="voice-provider"><div className="voice-provider-head"><div className="voice-provider-name"><Cloud size={17} /><h3>OpenRouter</h3></div><span className={`voice-status${data.openrouterConfigured ? ' ok' : ''}`}>{data.openrouterConfigured ? <CheckCircle2 size={12} /> : <AlertCircle size={12} />}{data.openrouterConfigured ? 'ключ готов' : 'нет ключа'}</span></div><p>Платный облачный резерв.</p><code>{voice.apiModel}</code></article>
    </section>

    <div className="voice-route" aria-label="Маршрут транскрибации">{(['local', 'qwen', 'api', 'auto'] as VoiceRoute[]).map((route) => <button key={route} type="button" disabled={route === 'qwen' && !data.qwen.ok} title={route === 'qwen' && !data.qwen.ok ? 'Сначала запустите Qwen ASR и дождитесь зелёного статуса' : undefined} className={voice.route === route ? 'active' : ''} onClick={() => updateVoice({ route })}>{LABELS[route]}</button>)}</div>

    <section className="voice-workspace">
      <div className="voice-config"><header className="voice-section-head"><h3>Настройки маршрута</h3><p>Авторезерв переходит дальше только после ошибки текущего провайдера.</p></header><div className="voice-fields">
        <div className="voice-field"><label>Модель Ollama</label><select value={voice.localModel} onChange={(event) => updateVoice({ localModel: event.target.value })}>{!ollamaModels.includes(voice.localModel) && <option value={voice.localModel}>{voice.localModel} · не установлена</option>}{ollamaModels.map((name) => <option key={name} value={name}>{name}</option>)}</select></div>
        <div className="voice-field"><label>Модель Qwen ASR</label><input value={voice.qwenModel} onChange={(event) => updateVoice({ qwenModel: event.target.value })} /><small>Официальный ID Hugging Face/vLLM.</small></div>
        <div className="voice-field full"><label>URL сервиса Qwen ASR</label><input value={voice.qwenBaseUrl} onChange={(event) => updateVoice({ qwenBaseUrl: event.target.value })} /><small>Ожидается OpenAI-совместимый endpoint `/v1/chat/completions`.</small></div>
        <div className="voice-field"><label>Модель OpenRouter</label><input value={voice.apiModel} onChange={(event) => updateVoice({ apiModel: event.target.value })} /></div>
        <div className="voice-field"><label>Timeout, секунд</label><input type="number" min="10" max="180" value={voice.requestTimeoutSeconds} onChange={(event) => updateVoice({ requestTimeoutSeconds: Number(event.target.value) })} /></div>
        <div className="voice-field"><label>Минимальная запись, секунд</label><input type="number" min="0.5" max="10" step="0.5" value={voice.minRecordingSeconds} onChange={(event) => updateVoice({ minRecordingSeconds: Number(event.target.value) })} /></div>
      </div><button className="voice-save" type="button" disabled={busy} onClick={() => void save()}>{busy ? 'Обрабатываю…' : 'Сохранить маршрут'}</button></div>

      <aside className="voice-test"><header className="voice-section-head"><h3>Проверка распознавания</h3><p>Тест не меняет пользовательский промпт.</p></header><div className="voice-test-body">
        <label className="voice-file"><input ref={fileRef} type="file" accept="audio/wav,audio/webm,audio/ogg,audio/mpeg,audio/mp4" onChange={(event) => { setTestFile(event.target.files?.[0] || null); setTestResult(null) }} />{testFile ? <FileAudio size={22} /> : <Upload size={22} />}<strong>{testFile?.name || 'Выбрать аудиофайл'}</strong><small>WAV, WebM, OGG, MP3 или M4A · до 8 МБ</small></label>
        <div className="voice-test-actions"><select value={testProvider} onChange={(event) => setTestProvider(event.target.value as typeof testProvider)}><option value="configured">По текущему маршруту</option><option value="local">Ollama</option><option value="qwen">Qwen ASR</option><option value="api">OpenRouter</option></select><button type="button" title="Запустить тест" disabled={!testFile || busy} onClick={() => void test()}><Mic2 size={17} /></button></div>
        {testResult && <div className={`voice-result${testResult.ok ? '' : ' error'}`}><strong>{testResult.text || testResult.detail || 'Тест не выполнен.'}</strong>{testResult.ok && <small>{testResult.provider} · {testResult.model} · {testResult.latencyMs} мс</small>}</div>}
        {message && <div className="voice-result"><strong>{message}</strong></div>}
      </div></aside>
    </section>

    <details className="voice-catalog"><summary>Кандидаты для сравнительных тестов</summary><div className="voice-catalog-body">
      <div className="voice-candidate"><strong>Qwen3-ASR 1.7B</strong><span>Отдельный qwen-asr/vLLM runtime. Не Ollama.</span></div>
      <div className="voice-candidate"><strong>Qwen3-ASR 0.6B</strong><span>Более лёгкий кандидат; нужен русский benchmark.</span></div>
      <div className="voice-candidate"><strong>Faster Whisper Large V3 Turbo</strong><span>Зрелый аварийный локальный маршрут с VAD.</span></div>
    </div></details>
  </div>
}
