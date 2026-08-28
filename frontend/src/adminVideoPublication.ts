export type AdminVideoMode = 'text_to_video' | 'image_to_video' | 'first_last_frame' | 'reference_to_video'
export type AdminVideoTier = 'mini' | 'pro' | 'max'
export type AdminVideoConfig = {
  published?: string[]
  enabled?: Partial<Record<AdminVideoMode, string[]>>
  access?: Partial<Record<AdminVideoMode, Partial<Record<AdminVideoTier, string[]>>>>
}

const MODES: AdminVideoMode[] = ['text_to_video', 'image_to_video', 'first_last_frame', 'reference_to_video']
const TIERS: AdminVideoTier[] = ['mini', 'pro', 'max']

export function setVideoPublication(current: AdminVideoConfig, modelIds: string[], checked: boolean): AdminVideoConfig {
  const published = new Set(current.published || [])
  const enabled = structuredClone(current.enabled || {})
  const access = structuredClone(current.access || {})
  for (const modelId of modelIds) {
    if (checked) published.add(modelId)
    else published.delete(modelId)
  }
  if (!checked) for (const mode of MODES) {
    const allowed = (enabled[mode] || []).filter((id) => published.has(id))
    if (allowed.length) enabled[mode] = allowed
    else delete enabled[mode]
    for (const tier of TIERS) {
      const tierAllowed = (access[mode]?.[tier] || []).filter((id) => published.has(id))
      if (access[mode]) {
        if (tierAllowed.length) access[mode]![tier] = tierAllowed
        else delete access[mode]![tier]
      }
    }
    if (access[mode] && !Object.keys(access[mode]!).length) delete access[mode]
  }
  return { published: Array.from(published).sort(), enabled, access }
}
