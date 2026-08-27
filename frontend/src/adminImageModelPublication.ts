export type ImageModelTier = 'mini' | 'plus' | 'pro' | 'business'
export type ImageModelQuality = 'fast' | 'standard' | 'max'
export type ImageModelAccess = Record<string, Partial<Record<ImageModelTier, string[]>>>
export type ImageModelQualityDefaults = Record<string, Partial<Record<ImageModelQuality, string>>>
export type ImageModelPublicationConfig = {
  published?: string[]
  enabled?: Record<string, string[]>
  defaults?: Record<string, string>
  access?: ImageModelAccess
  qualityDefaults?: ImageModelQualityDefaults
}

const TIERS: ImageModelTier[] = ['mini', 'plus', 'pro', 'business']
const QUALITIES: ImageModelQuality[] = ['fast', 'standard', 'max']

export const publishedImageModelIds = (config: ImageModelPublicationConfig) => Array.isArray(config.published)
  ? config.published
  : Array.from(new Set(Object.values(config.enabled || {}).flat()))

function copyConfig(config: ImageModelPublicationConfig) {
  return {
    published: [...publishedImageModelIds(config)],
    enabled: JSON.parse(JSON.stringify(config.enabled || {})) as Record<string, string[]>,
    defaults: { ...(config.defaults || {}) },
    access: JSON.parse(JSON.stringify(config.access || {})) as ImageModelAccess,
    qualityDefaults: JSON.parse(JSON.stringify(config.qualityDefaults || {})) as ImageModelQualityDefaults,
  }
}

function removeModelFromMode(config: ReturnType<typeof copyConfig>, mode: string, modelId: string) {
  const next = (config.enabled[mode] || []).filter((id) => id !== modelId)
  if (next.length) config.enabled[mode] = next
  else delete config.enabled[mode]
  if (config.defaults[mode] === modelId) {
    if (next.length) config.defaults[mode] = next[0]
    else delete config.defaults[mode]
  }
  for (const tier of TIERS) {
    const tierValues = config.access[mode]?.[tier]?.filter((id) => id !== modelId) || []
    if (config.access[mode]) {
      if (tierValues.length) config.access[mode][tier] = tierValues
      else delete config.access[mode][tier]
    }
  }
  if (config.access[mode] && !Object.keys(config.access[mode]).length) delete config.access[mode]
  for (const quality of QUALITIES) {
    if (config.qualityDefaults[mode]?.[quality] === modelId) delete config.qualityDefaults[mode][quality]
  }
  if (config.qualityDefaults[mode] && !Object.keys(config.qualityDefaults[mode]).length) delete config.qualityDefaults[mode]
}

export function setImageModelPublished(config: ImageModelPublicationConfig, modelId: string, checked: boolean) {
  const next = copyConfig(config)
  const published = new Set(next.published)
  if (checked) published.add(modelId)
  else {
    published.delete(modelId)
    for (const mode of Object.keys(next.enabled)) removeModelFromMode(next, mode, modelId)
  }
  next.published = Array.from(published).sort()
  return next
}

export function setImageModelOperation(config: ImageModelPublicationConfig, mode: string, modelId: string, checked: boolean) {
  const next = copyConfig(config)
  const values = new Set(next.enabled[mode] || [])
  if (checked) values.add(modelId)
  else values.delete(modelId)
  const list = Array.from(values).sort()
  if (list.length) next.enabled[mode] = list
  else delete next.enabled[mode]
  if (!checked) removeModelFromMode(next, mode, modelId)
  if (checked && !next.defaults[mode]) next.defaults[mode] = modelId
  if (!checked && next.defaults[mode] === modelId) {
    if (list.length) next.defaults[mode] = list[0]
    else delete next.defaults[mode]
  }
  return next
}

export function setImageModelSection(config: ImageModelPublicationConfig, mode: string, modelIds: string[], checked: boolean) {
  const next = copyConfig(config)
  const ids = Array.from(new Set(modelIds)).sort()
  if (checked) {
    next.enabled[mode] = ids
    next.defaults[mode] = next.defaults[mode] && ids.includes(next.defaults[mode]) ? next.defaults[mode] : ids[0]
    next.access[mode] = { ...(next.access[mode] || {}) }
  } else {
    delete next.enabled[mode]
    delete next.defaults[mode]
    delete next.access[mode]
    delete next.qualityDefaults[mode]
  }
  return next
}

export function setImageModelTier(config: ImageModelPublicationConfig, mode: string, tier: ImageModelTier, modelId: string, checked: boolean) {
  const next = copyConfig(config)
  next.access[mode] = next.access[mode] || {}
  const values = new Set(next.access[mode][tier] || [])
  if (checked) values.add(modelId)
  else values.delete(modelId)
  if (values.size) next.access[mode][tier] = Array.from(values).sort()
  else delete next.access[mode][tier]
  if (!Object.keys(next.access[mode]).length) delete next.access[mode]
  return next
}

export function setImageModelTierColumn(config: ImageModelPublicationConfig, mode: string, tier: ImageModelTier, modelIds: string[], checked: boolean) {
  const next = copyConfig(config)
  next.access[mode] = next.access[mode] || {}
  if (checked) next.access[mode][tier] = Array.from(new Set(modelIds)).sort()
  else delete next.access[mode][tier]
  if (!Object.keys(next.access[mode]).length) delete next.access[mode]
  return next
}
