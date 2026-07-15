import { Component, Fragment } from 'react'
import type { ErrorInfo, ReactNode } from 'react'
import { reportRuntimeError, type RuntimeRegion } from './runtimeTelemetry'

type BoundaryProps = {
  region: RuntimeRegion
  label: string
  fallbackClassName?: string
  children: ReactNode
}

type BoundaryState = { failed: boolean; incidentId: string; revision: number }

function testFailureRegion(): string {
  if (window.location.hostname !== '127.0.0.1' && window.location.hostname !== 'localhost') return ''
  return window.sessionStorage.getItem('izo:e2e:fail-region') || ''
}

class RegionErrorBoundary extends Component<BoundaryProps, BoundaryState> {
  state: BoundaryState = { failed: false, incidentId: '', revision: 0 }

  static getDerivedStateFromError(): Partial<BoundaryState> {
    return { failed: true }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error(`Runtime region failed: ${this.props.region}`, error, info)
    this.setState({ incidentId: reportRuntimeError(this.props.region, error) })
  }

  retry = (): void => {
    if (testFailureRegion() === this.props.region) window.sessionStorage.removeItem('izo:e2e:fail-region')
    this.setState((state) => ({ failed: false, incidentId: '', revision: state.revision + 1 }))
  }

  render(): ReactNode {
    if (!this.state.failed) return <Fragment key={this.state.revision}>{this.props.children}</Fragment>
    return (
      <div className={`runtime-region-fallback ${this.props.fallbackClassName || ''}`.trim()} role="alert" data-runtime-region={this.props.region}>
        <strong>{this.props.label} временно недоступен</strong>
        <span>Остальная студия продолжает работать.</span>
        {this.state.incidentId && <small>Код: {this.state.incidentId}</small>}
        <button type="button" onClick={this.retry}>Повторить</button>
      </div>
    )
  }
}

function RegionRenderer({ region, render }: { region: RuntimeRegion; render: () => ReactNode }): ReactNode {
  if (testFailureRegion() === region) throw new Error(`e2e_region_failure:${region}`)
  return render()
}

export default function ResilientRegion(props: {
  region: RuntimeRegion
  label: string
  fallbackClassName?: string
  render: () => ReactNode
}): ReactNode {
  return (
    <RegionErrorBoundary region={props.region} label={props.label} fallbackClassName={props.fallbackClassName}>
      <RegionRenderer region={props.region} render={props.render} />
    </RegionErrorBoundary>
  )
}
