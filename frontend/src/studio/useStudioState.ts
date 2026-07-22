// ARCH-FE-STUDIO-001A: bounded studio state hooks extracted from newUi.tsx.
// These own isolated backend-data loads and client-side persistence only; they
// render nothing and never touch the app DOM structure — the component consumes
// the returned values exactly as before. This module must not import newUi.tsx.
import { useEffect, useState } from 'react'
import type { MeV2 } from '../authV2'
import {
  DEFAULT_TARIFFS,
  normalizeModelAccess,
  normalizeTariffs,
  type ModelModeKey,
  type TariffConfig,
  type TariffKey,
  type UserModelAccess,
} from '../profileSupport'
import { normalizeModels } from '../runtimeContracts'
import { apiFetch } from './studioApi'
import { writeStudioDraft } from './studioDraft'
import { pricingMapFromPayload } from './studioHelpers'
import type { ModelsPayload, PublicModelPricing, StudioDraft, UserModelChoices } from './studioTypes'

export interface StudioBackendData {
  modelsPayload: ModelsPayload | undefined
  tariffs: TariffConfig
  tariffsState: 'loading' | 'ready' | 'fallback'
  tokenRub: number
  modelAccess: UserModelAccess
  openrouterPricing: Record<string, PublicModelPricing>
}

// Public config and catalogue loads. Each piece of state is written only by its
// own fetch effect; callers read the values. Behaviour and endpoints unchanged.
export function useStudioBackendData(me: MeV2 | null): StudioBackendData {
  const [modelsPayload, setModelsPayload] = useState<ModelsPayload>()
  const [tariffs, setTariffs] = useState<TariffConfig>(DEFAULT_TARIFFS)
  const [tariffsState, setTariffsState] = useState<'loading' | 'ready' | 'fallback'>('loading')
  const [tokenRub, setTokenRub] = useState(5)
  const [modelAccess, setModelAccess] = useState<UserModelAccess>(() => normalizeModelAccess(null))
  const [openrouterPricing, setOpenrouterPricing] = useState<Record<string, PublicModelPricing>>({})

  useEffect(() => {
    let cancelled = false
    apiFetch('/models')
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (!cancelled && data && data?.ok !== false) setModelsPayload(normalizeModels(data))
      })
      .catch(() => undefined)
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    let cancelled = false
    apiFetch('/tariffs')
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (cancelled) return
        if (data?.tariffs) {
          setTariffs(normalizeTariffs(data.tariffs))
          if (data.openrouterPricing) setOpenrouterPricing(pricingMapFromPayload(data.openrouterPricing))
          if (typeof data.economy?.tokenRub === 'number' && data.economy.tokenRub > 0) setTokenRub(data.economy.tokenRub)
          setTariffsState('ready')
        } else {
          setTariffsState('fallback')
        }
      })
      .catch(() => {
        if (!cancelled) setTariffsState('fallback')
      })
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    let cancelled = false
    apiFetch('/model-access')
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (!cancelled && data?.ok) {
          setModelAccess(normalizeModelAccess(data, (me?.account?.plan || 'mini') as TariffKey))
          if (data.openrouterPricing) setOpenrouterPricing(pricingMapFromPayload(data.openrouterPricing))
        }
      })
      .catch(() => undefined)
    return () => { cancelled = true }
  }, [me?.account?.plan])

  return { modelsPayload, tariffs, tariffsState, tokenRub, modelAccess, openrouterPricing }
}

export type ModelVisibility = Partial<Record<ModelModeKey, Record<string, boolean>>>

export interface ModelPreferences {
  userModelChoices: UserModelChoices
  setUserModelChoices: React.Dispatch<React.SetStateAction<UserModelChoices>>
  userModelVisibility: ModelVisibility
  setUserModelVisibility: React.Dispatch<React.SetStateAction<ModelVisibility>>
}

// Per-browser model choices/visibility, mirrored to localStorage. Server-side
// access rules still apply; storage is best-effort.
export function useModelPreferences(): ModelPreferences {
  const [userModelChoices, setUserModelChoices] = useState<UserModelChoices>(() => {
    try {
      const raw = window.localStorage.getItem('izo:user-model-choices')
      return raw ? JSON.parse(raw) as UserModelChoices : {}
    } catch {
      return {}
    }
  })
  const [userModelVisibility, setUserModelVisibility] = useState<ModelVisibility>(() => {
    try {
      const raw = window.localStorage.getItem('izo:user-model-visibility')
      return raw ? JSON.parse(raw) as ModelVisibility : {}
    } catch {
      return {}
    }
  })

  useEffect(() => {
    try {
      window.localStorage.setItem('izo:user-model-choices', JSON.stringify(userModelChoices))
    } catch {
      // localStorage can be blocked; server-side access rules still apply.
    }
  }, [userModelChoices])

  useEffect(() => {
    try {
      window.localStorage.setItem('izo:user-model-visibility', JSON.stringify(userModelVisibility))
    } catch {
      // localStorage can be blocked; tariff access rules still apply.
    }
  }, [userModelVisibility])

  return { userModelChoices, setUserModelChoices, userModelVisibility, setUserModelVisibility }
}

// Debounced persistence of the in-progress studio draft to sessionStorage.
export function useStudioDraftAutosave(draft: StudioDraft): void {
  useEffect(() => {
    const timer = window.setTimeout(() => {
      writeStudioDraft(draft)
    }, 120)
    return () => window.clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft.editFaceStrengthPct, draft.editSlots, draft.prompts, draft.quality, draft.resolutionId, draft.seed, draft.sourceImage, draft.strengthPct, draft.styleId])
}
