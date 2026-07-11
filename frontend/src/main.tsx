import { StrictMode, Component, cloneElement, isValidElement } from 'react'
import type { ErrorInfo, ReactElement, ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'

class ErrorBoundary extends Component<{ children: ReactNode }, { hasError: boolean; error: Error | null; revision: number }> {
  constructor(props: { children: ReactNode }) {
    super(props)
    this.state = { hasError: false, error: null, revision: 0 }
  }
  static getDerivedStateFromError(error: Error) {
    return { hasError: true, error }
  }
  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('ErrorBoundary caught:', error, info)
  }
  render() {
    if (this.state.hasError) {
      return (
        <div style={{ padding: 40, textAlign: 'center', fontFamily: 'sans-serif' }}>
          <h2>Студия временно остановлена</h2>
          <p style={{ color: '#aaa', fontSize: 14 }}>Настройки сохранены. Восстановите студию и продолжите работу.</p>
          <p style={{ color: '#777', fontSize: 12 }}>{String(this.state.error?.message || 'Неизвестная ошибка интерфейса')}</p>
          <button
            onClick={() => this.setState((state) => ({ hasError: false, error: null, revision: state.revision + 1 }))}
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

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </StrictMode>,
)
