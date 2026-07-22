import { StrictMode, Component, cloneElement, isValidElement } from 'react'
import type { ErrorInfo, ReactElement, ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { installGlobalRuntimeTelemetry, reportRuntimeError } from './runtimeTelemetry'

const STALE_CHUNK_RELOAD_KEY = 'izo_stale_chunk_reload_at'
const STALE_CHUNK_RELOAD_GUARD_MS = 30_000

// A tab can remain open while an immutable frontend release is switched. If
// that old tab later requests a lazy chunk which no longer belongs to the
// active release, refresh once so the no-store HTML loads the current graph.
// A short session guard prevents a broken deployment from creating a reload
// loop; the normal error boundary handles any repeated failure.
window.addEventListener('vite:preloadError', (event: Event) => {
  const now = Date.now()
  let shouldReload = true
  try {
    const previous = Number(window.sessionStorage.getItem(STALE_CHUNK_RELOAD_KEY) || '0')
    shouldReload = !Number.isFinite(previous) || now - previous > STALE_CHUNK_RELOAD_GUARD_MS
    if (shouldReload) window.sessionStorage.setItem(STALE_CHUNK_RELOAD_KEY, String(now))
  } catch {
    // Storage may be unavailable in a restricted WebView; one reload is still
    // the safest recovery for an obsolete module graph.
  }
  if (!shouldReload) return
  event.preventDefault()
  window.location.reload()
})

class ErrorBoundary extends Component<{ children: ReactNode }, { hasError: boolean; incidentId: string; revision: number }> {
  constructor(props: { children: ReactNode }) {
    super(props)
    this.state = { hasError: false, incidentId: '', revision: 0 }
  }
  static getDerivedStateFromError() {
    return { hasError: true }
  }
  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('ErrorBoundary caught:', error, info)
    this.setState({ incidentId: reportRuntimeError('root', error) })
  }
  render() {
    if (this.state.hasError) {
      return (
        <div style={{ padding: 40, textAlign: 'center', fontFamily: 'sans-serif' }}>
          <h2>Студия временно остановлена</h2>
          <p style={{ color: '#aaa', fontSize: 14 }}>Настройки сохранены. Восстановите студию и продолжите работу.</p>
          {this.state.incidentId && <p style={{ color: '#777', fontSize: 12 }}>Код инцидента: {this.state.incidentId}</p>}
          <button
            onClick={() => this.setState((state) => ({ hasError: false, incidentId: '', revision: state.revision + 1 }))}
            style={{ marginTop: 16, padding: '8px 24px', cursor: 'pointer' }}
          >
            Восстановить студию
          </button>
        </div>
      )
    }
    return isValidElement(this.props.children)
      ? cloneElement(this.props.children as ReactElement, { key: this.state.revision })
      : this.props.children
  }
}

installGlobalRuntimeTelemetry()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </StrictMode>,
)
