type MaxViewportSize = { width?: number | string; height?: number | string }

export type MaxWebAppBridge = {
  initData?: string
  webAppData?: string
  platform?: string
  getViewportSize?: () => Promise<MaxViewportSize> | MaxViewportSize
}

type MaxWindow = Window & {
  WebApp?: MaxWebAppBridge
  MAX?: { WebApp?: MaxWebAppBridge }
  maxWebApp?: MaxWebAppBridge
}

function windowWithMax(): MaxWindow {
  return window as MaxWindow
}

export function maxWebAppBridge(): MaxWebAppBridge | undefined {
  const target = windowWithMax()
  return target.WebApp || target.MAX?.WebApp || target.maxWebApp
}

export function maxInitData(): string {
  const target = windowWithMax()
  return (
    target.WebApp?.initData
    || target.WebApp?.webAppData
    || target.MAX?.WebApp?.webAppData
    || target.MAX?.WebApp?.initData
    || target.maxWebApp?.webAppData
    || target.maxWebApp?.initData
    || ''
  ).trim()
}

export function isMaxMiniApp(): boolean {
  return maxInitData().length > 0
}

function positivePixels(value: number | string | undefined): number | null {
  const parsed = typeof value === 'number' ? value : Number.parseFloat(String(value || ''))
  return Number.isFinite(parsed) && parsed > 0 ? Math.round(parsed) : null
}

function fallbackViewport(): Required<MaxViewportSize> {
  const visual = window.visualViewport
  return {
    width: Math.round(visual?.width || window.innerWidth),
    height: Math.round(visual?.height || window.innerHeight),
  }
}

function applyViewport(size?: MaxViewportSize): void {
  const fallback = fallbackViewport()
  const width = positivePixels(size?.width) || fallback.width
  const height = positivePixels(size?.height) || fallback.height
  const root = document.documentElement
  root.style.setProperty('--max-viewport-width', `${width}px`)
  root.style.setProperty('--max-viewport-height', `${height}px`)
  root.style.setProperty('--app-viewport-height', `${height}px`)
}

export function installMaxBridgeLayout(): () => void {
  if (!isMaxMiniApp()) return () => undefined

  const bridge = maxWebAppBridge()
  const platform = String(bridge?.platform || '').trim().toLowerCase()
  document.documentElement.classList.add('max-mini-app')
  document.body.classList.add('max-mini-app')
  if (platform) document.documentElement.dataset.maxPlatform = platform.slice(0, 32)

  let refreshSequence = 0
  const refresh = () => {
    const sequence = ++refreshSequence
    applyViewport()
    try {
      if (!bridge?.getViewportSize) return
      void Promise.resolve(bridge.getViewportSize())
        .then((size) => {
          if (sequence === refreshSequence) applyViewport(size)
        })
        .catch(() => undefined)
    } catch {
      // The fallback based on VisualViewport/innerHeight is already applied.
    }
  }

  const onVisibility = () => {
    if (!document.hidden) refresh()
  }
  refresh()
  window.addEventListener('resize', refresh)
  window.addEventListener('orientationchange', refresh)
  window.visualViewport?.addEventListener('resize', refresh)
  document.addEventListener('visibilitychange', onVisibility)

  return () => {
    refreshSequence += 1
    window.removeEventListener('resize', refresh)
    window.removeEventListener('orientationchange', refresh)
    window.visualViewport?.removeEventListener('resize', refresh)
    document.removeEventListener('visibilitychange', onVisibility)
  }
}
