import type { ModelOption } from './profileSupport'

export type TokenVisualKind = 'daily' | 'main'

export function imageTokenVisualKind(model: Pick<ModelOption, 'id' | 'provider'>): TokenVisualKind {
  return model.provider === 'comfyui' || model.id.startsWith('server:') ? 'daily' : 'main'
}

export function videoTokenVisualKind(model: { id?: string | null; provider?: string | null } | null | undefined): TokenVisualKind {
  return model?.provider === 'local_ltx' || String(model?.id || '').startsWith('local/ltx-') ? 'daily' : 'main'
}

export function tokenVisualClass(kind: TokenVisualKind): string {
  return `token-cost token-cost--${kind}`
}

export function tokenVisualLabel(kind: TokenVisualKind): string {
  return kind === 'daily' ? 'Дневные токены' : 'Основные токены'
}
