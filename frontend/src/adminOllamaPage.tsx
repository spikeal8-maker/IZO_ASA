type LocalModel = {
  name?: string
  model?: string
  size?: number
  details?: { parameter_size?: string; quantization_level?: string }
}
type ResidentModel = {
  name?: string
  model?: string
  size_vram?: number
  expires_at?: string
}
type LocalChat = {
  enabled: boolean
  localEnabled: boolean
  localLabel: string
  localModel: string
  localTimeoutSeconds: number
  localNumCtx: number
  contextChars: number
}
type OllamaAdminData = {
  ollama: { ok: boolean; baseUrl: string; error?: string; models: LocalModel[] }
  ollamaResidency: { ok: boolean; models: ResidentModel[] }
  config: { chat: LocalChat }
}
type TestResult = {
  detail?: string
  improvedPrompt?: string
  provider?: string
  model?: string
  latencyMs?: number
}

export function AdminOllamaPage({
  data, busy, testPrompt, testResult, onChangeChat, onChangePrompt,
  onSave, onRefresh, onTest,
}: {
  data: OllamaAdminData | null
  busy: boolean
  testPrompt: string
  testResult: TestResult | null
  onChangeChat: (patch: Partial<LocalChat>) => void
  onChangePrompt: (value: string) => void
  onSave: () => void
  onRefresh: () => void
  onTest: () => void
}) {
  if (!data) return <div className="models-page-loading">Загружаем защищённый статус Ollama…</div>
  const { ollama, ollamaResidency, config } = data
  const chat = config.chat
  const models = (ollama.models || []).filter((item) => item.name && !item.name.endsWith(':cloud'))
  const running = (ollamaResidency.models || []).filter((item) => item.name || item.model)
  const current = running.find((item) => (item.name || item.model) === chat.localModel)
  const installed = models.some((item) => item.name === chat.localModel)
  const vramGiB = (size: number | undefined) =>
    typeof size === 'number' && Number.isFinite(size) ? `${(size / 1024 ** 3).toFixed(2)} ГиБ` : '—'
  return <section className="server-layout" aria-label="Отдельная страница Ollama">
    <article className="card">
      <div className="card-head">
        <div>
          <h2 className="card-title">Локальная Ollama</h2>
          <p className="card-note">Управление моделями чата через защищённый backend IZO_ASA. Браузер не подключается к Ollama напрямую.</p>
        </div>
        <button className="ghost" disabled={busy} onClick={onRefresh}>Обновить состояние</button>
      </div>
      <div className="assistant-summary">
        <div><span>Соединение</span><strong>{ollama.ok ? 'Доступно' : 'Недоступно'}</strong><small>{ollama.ok ? 'Защищённый backend-канал доступен' : 'Отключено до проверки локального соединения'}{ollama.error ? ` · ${ollama.error}` : ''}</small></div>
        <div><span>Основная модель</span><strong>{chat.localModel || 'Не выбрана'}</strong><small>{installed ? 'Установлена на сервере' : 'Не найдена в полученном каталоге'}</small></div>
        <div><span>Загружена в VRAM</span><strong>{current ? vramGiB(current.size_vram) : 'Нет подтверждения'}</strong><small>{current?.expires_at ? `До ${current.expires_at}` : 'Данные /api/ps'}</small></div>
      </div>
      <div className="assistant-form">
        <div className="two-col">
          <div className="field">
            <label htmlFor="ollama-local-label">Название для пользователя</label>
            <input id="ollama-local-label" value={chat.localLabel} onChange={(event) => onChangeChat({ localLabel: event.target.value })} />
          </div>
          <div className="field">
            <label htmlFor="ollama-model">Основная модель Ollama</label>
            <select id="ollama-model" value={chat.localModel} onChange={(event) => onChangeChat({ localModel: event.target.value })}>
              {!installed && chat.localModel && <option value={chat.localModel}>{chat.localModel} · не подтверждена сервером</option>}
              {models.map((model) => <option key={model.name} value={model.name}>{model.name}</option>)}
            </select>
          </div>
          <div className="field">
            <label htmlFor="ollama-timeout">Таймаут, секунд</label>
            <input id="ollama-timeout" type="number" min="10" max="180" value={chat.localTimeoutSeconds} onChange={(event) => onChangeChat({ localTimeoutSeconds: Number(event.target.value) })} />
          </div>
          <div className="field">
            <label htmlFor="ollama-context">Контекст Ollama, токенов</label>
            <input id="ollama-context" type="number" min="4096" max="32768" step="1024" value={chat.localNumCtx} onChange={(event) => onChangeChat({ localNumCtx: Number(event.target.value) })} />
          </div>
          <div className="field">
            <label htmlFor="ollama-history">История чата, символов</label>
            <input id="ollama-history" type="number" min="4000" max="240000" step="1000" value={chat.contextChars} onChange={(event) => onChangeChat({ contextChars: Number(event.target.value) })} />
          </div>
          <div className="field">
            <label>Стоимость локального базового чата</label>
            <input type="text" disabled value="Бесплатно для пользователя" />
          </div>
        </div>
        <label className="ollama-user-toggle" style={{ display: 'flex', alignItems: 'center', gap: 9, fontSize: 12 }}>
          <input type="checkbox" style={{ width: 16, height: 16, accentColor: 'var(--lime)' }} disabled={busy || !ollama.ok || !installed} checked={chat.enabled && chat.localEnabled && ollama.ok && installed} onChange={(event) => onChangeChat({ enabled: event.target.checked, localEnabled: event.target.checked })} />
          <span>Локальный чат доступен пользователям</span>
        </label>
        <div className="actions">
          <button className="primary" disabled={busy} onClick={onSave}>{busy ? 'Сохранение…' : 'Сохранить настройки Ollama'}</button>
        </div>
        {!ollama.ok && <p className="hint">Сервер не отвечает из текущего backend-окружения. Сохранение настроек не разрешает сетевой доступ; включение провайдера требует отдельного защищённого Task.</p>}
        <h3 className="card-title">Установленные модели</h3>
        <div className="ollama-list">
          {models.length ? models.map((item) => {
            const resident = running.find((model) => (model.name || model.model) === item.name)
            return <div className="ollama-row" key={item.name}>
              <div><strong>{item.name}</strong><small style={{ display: 'block' }}>Параметры: {item.details?.parameter_size || 'не указаны'} · {item.details?.quantization_level || 'квантование неизвестно'}</small></div>
              <small>{resident ? `В памяти: ${vramGiB(resident.size_vram)}` : item.size ? `На диске: ${vramGiB(item.size)}` : 'Не загружена'}</small>
            </div>
          }) : <p className="hint">Ollama недоступна либо локальные модели не найдены.</p>}
        </div>
      </div>
    </article>
    <aside className="card">
      <div className="card-head">
        <div><h2 className="card-title">Тест выбранной модели</h2><p className="card-note">Только локальный backend-маршрут. Резервный платный API для теста не используется.</p></div>
      </div>
      <div className="assistant-test">
        <label htmlFor="ollama-test-prompt">Тестовый запрос</label>
        <textarea id="ollama-test-prompt" value={testPrompt} onChange={(event) => onChangePrompt(event.target.value)} />
        <div className="actions"><button className="ghost" disabled={busy || !ollama.ok || !installed || !testPrompt.trim()} onClick={onTest}>Проверить Ollama</button></div>
        {testResult && <div className="assistant-test-result">
          <strong>{testResult.detail || testResult.improvedPrompt || 'Ответ отсутствует'}</strong>
          {testResult.model && <small>{testResult.provider} · {testResult.model} · {testResult.latencyMs ?? '—'} мс</small>}
        </div>}
        <p className="hint">Адрес и сетевые разрешения задаются на сервере в отдельном Task. Смена основной модели сохраняется в существующей backend-настройке помощников.</p>
      </div>
    </aside>
  </section>
}
