// COMFYUI-BRIDGE-D2R2-001: candidate-only informational leaf.
// Uses existing CSS/classes. Never exposes the host bridge token or controls.
type NativeStatus = {
  enabled?: boolean
  available?: boolean
  model?: string
  encoder?: string
  vae?: string
  nineBAvailable?: boolean
  queue?: { running?: number; pending?: number }
  gpu?: { name?: string; vramTotal?: number; vramFree?: number }
}
type Status = {
  checked_at?: string
  comfyui?: { available?: boolean; base_url?: string }
  config_api?: { ok?: boolean; error?: string; native4b?: NativeStatus }
  models_api?: { ok?: boolean; error?: string }
  active_jobs?: Array<{ id?: string }>
}
export default function Comfy214StatusOverview({
  status, error, fmtState, statusColor, fmtTime,
}: {
  status: Status | null
  error: string
  fmtState: (value?: boolean) => string
  statusColor: (value?: boolean) => string
  fmtTime: (value?: string) => string
}) {
  const native = status?.config_api?.native4b
  const vramGb = native?.gpu?.vramTotal ? (native.gpu.vramTotal / 1073741824).toFixed(1) : '—'
  return (
    <div className="server-overview">
      <div className="server-metric"><span>ComfyUI</span><strong style={{ color: statusColor(status?.comfyui?.available) }}>{error ? '—' : status?.comfyui?.available ? 'В сети' : 'Не отвечает'}</strong><small>{status?.comfyui?.base_url || 'адрес не получен'}</small></div>
      <div className="server-metric"><span>Config API</span><strong style={{ color: statusColor(status?.config_api?.ok) }}>{fmtState(status?.config_api?.ok)}</strong><small>{status?.config_api?.error || 'конфигурация workflow'}</small></div>
      <div className="server-metric"><span>Models API</span><strong style={{ color: statusColor(status?.models_api?.ok) }}>{fmtState(status?.models_api?.ok)}</strong><small>{status?.models_api?.error || 'модели и LoRA'}</small></div>
      <div className="server-metric"><span>Активные задачи</span><strong>{status?.active_jobs?.length ?? '—'}</strong><small>проверено {fmtTime(status?.checked_at)}</small></div>
      {native?.enabled && <>
        <div className="server-metric"><span>Локальная модель</span><strong style={{ color: statusColor(native.available) }}>{native.available ? 'FLUX.2 Klein 4B готова' : 'Недоступна'}</strong><small>{native.model || '4B FP8 не обнаружена'}</small></div>
        <div className="server-metric"><span>Text encoder / VAE</span><strong>{native.encoder || '—'}</strong><small>{native.vae || '—'}</small></div>
        <div className="server-metric"><span>Очередь GPU</span><strong>{native.queue?.running ?? '—'} / {native.queue?.pending ?? '—'}</strong><small>выполняется / ожидает</small></div>
        <div className="server-metric"><span>GPU</span><strong>{native.gpu?.name || 'Не обнаружен'}</strong><small>{vramGb} ГиБ VRAM · 9B по лицензии недоступна</small></div>
      </>}
    </div>
  )
}
