// STUDIO-DRAFT-OPT-001: restore/save Studio draft after trusted auth settles.
// Owns only form state and composer behavior; never sends a generation request.
import { useCallback, useEffect, useLayoutEffect, useMemo, useState } from 'react'
import type { Dispatch, SetStateAction } from 'react'
import type { AuthStatusV2 } from '../authV2'
import { EDIT_SLOT_COUNT, type EditSlot } from '../editPrompt'
import type { PaintSubMode } from '../paintTypes'
import { normalizeResolutionId } from '../resolutionPolicy'
import { DEFAULT_FACE_STRENGTH, EMPTY_EDIT_SLOTS } from './studioHelpers'
import { clearStudioDraft, readStudioDraft, studioDraftScope, writeStudioDraft } from './studioDraft'
import type { StudioDraft, StudioMode } from './studioTypes'

const EMPTY_PROMPTS: Record<StudioMode, string> = { text: '', i2i: '', edit: '', paint: '' }
const blankSlots = () => EMPTY_EDIT_SLOTS.map((slot) => ({ ...slot }))

function fromPersistedPrompts(draft: StudioDraft): Record<StudioMode, string> {
  return {
    text: draft.prompts?.text || '',
    i2i: draft.prompts?.i2i || '',
    edit: draft.prompts?.edit || '',
    paint: draft.prompts?.paint || '',
  }
}

export function useStudioDraftState(authStatus: AuthStatusV2, internalUserId?: string | null) {
  const scope = studioDraftScope(authStatus, internalUserId)
  const [restoredScope, setRestoredScope] = useState<typeof scope>(null)
  const [prompts, setPrompts] = useState<Record<StudioMode, string>>({ ...EMPTY_PROMPTS })
  const [styleId, setStyleId] = useState('')
  const [resolutionId, setResolutionId] = useState('sq-hd')
  const [quality, setQuality] = useState('fast')
  const [seed, setSeed] = useState(0)
  const [strengthPct, setStrengthPct] = useState(75)
  const [sourceImage, setSourceImage] = useState<string>()
  const [editSlots, setEditSlots] = useState<EditSlot[]>(blankSlots)
  const [editFaceStrengthPct, setEditFaceStrengthPct] = useState(DEFAULT_FACE_STRENGTH)

  useEffect(() => {
    let cancelled = false
    // Defer state updates outside effect body to satisfy React effect rules.
    queueMicrotask(() => {
      if (cancelled) return
      const draft = scope ? readStudioDraft(scope) : {}
      setPrompts(fromPersistedPrompts(draft))
      setStyleId(draft.styleId || '')
      setResolutionId(normalizeResolutionId(draft.resolutionId || 'sq-hd'))
      setQuality(draft.quality || 'fast')
      setSeed(draft.seed || 0)
      setStrengthPct(draft.strengthPct ?? 75)
      setSourceImage(draft.sourceImage)
      setEditSlots(Array.isArray(draft.editSlots) && draft.editSlots.length === EDIT_SLOT_COUNT
        ? draft.editSlots.map((slot) => ({ ...slot }))
        : blankSlots())
      setEditFaceStrengthPct(draft.editFaceStrengthPct ?? DEFAULT_FACE_STRENGTH)
      setRestoredScope(scope)
    })
    return () => { cancelled = true }
  }, [scope])

  // Never write the previous user's state during auth loading/account switches.
  const ready = scope !== null && scope === restoredScope
  const draft = useMemo<StudioDraft>(() => ({
    prompts, styleId, resolutionId, quality, seed, strengthPct, sourceImage, editSlots, editFaceStrengthPct,
  }), [prompts, styleId, resolutionId, quality, seed, strengthPct, sourceImage, editSlots, editFaceStrengthPct])
  useLayoutEffect(() => {
    // Synchronous after React commits: pressing F5 immediately after typing is safe.
    if (scope && ready) writeStudioDraft(scope, draft)
  }, [scope, ready, draft])

  useEffect(() => {
    if (!scope || !ready) return
    const flush = () => writeStudioDraft(scope, draft)
    window.addEventListener('pagehide', flush)
    return () => window.removeEventListener('pagehide', flush)
  }, [scope, ready, draft])

  const clearSubmittedPrompt = useCallback((mode: StudioMode, submitted: string) => {
    setPrompts((current) => current[mode].trim() === submitted
      ? { ...current, [mode]: '' }
      : current)
  }, [])

  const forgetCurrentDraft = useCallback(() => {
    if (scope) clearStudioDraft(scope)
  }, [scope])

  // When identity is unresolved, never render the previous account's text/media.
  return {
    prompts: ready ? prompts : EMPTY_PROMPTS, setPrompts,
    styleId: ready ? styleId : '', setStyleId,
    resolutionId: ready ? resolutionId : 'sq-hd', setResolutionId,
    quality: ready ? quality : 'fast', setQuality,
    seed: ready ? seed : 0, setSeed,
    strengthPct: ready ? strengthPct : 75, setStrengthPct,
    sourceImage: ready ? sourceImage : undefined, setSourceImage,
    editSlots: ready ? editSlots : EMPTY_EDIT_SLOTS, setEditSlots,
    editFaceStrengthPct: ready ? editFaceStrengthPct : DEFAULT_FACE_STRENGTH, setEditFaceStrengthPct,
    clearSubmittedPrompt, forgetCurrentDraft,
  }
}

export function studioPromptComposer({
  studioMode, paintMode, paintTechPromptOpen, paintTechPrompts,
  setPaintTechPrompts, prompts, setPrompt,
}: {
  studioMode: StudioMode
  paintMode: PaintSubMode
  paintTechPromptOpen: boolean
  paintTechPrompts: Record<PaintSubMode, string>
  setPaintTechPrompts: Dispatch<SetStateAction<Record<PaintSubMode, string>>>
  prompts: Record<StudioMode, string>
  setPrompt: (value: string) => void
}) {
  const isI2I = studioMode === 'i2i'
  const isEdit = studioMode === 'edit'
  const isPaint = studioMode === 'paint'
  const promptTitle = isI2I ? 'Как преобразовать?' : isPaint ? 'Что визуализируем?' : isEdit ? 'Дополнительные пожелания' : 'Что хотите увидеть?'
  const promptPlaceholder = isI2I
    ? 'Опишите, как преобразовать исходное изображение...'
    : isPaint
      ? paintMode === 'sketch'
        ? 'Опишите сцену, которую нужно получить из эскиза...'
        : paintMode === 'mask'
          ? 'Опишите, что должно появиться или измениться внутри маски...'
          : paintMode === 'outpaint'
            ? 'Опишите, что дорисовать в пустых краях кадра: фон, свет, детали, продолжение сцены...'
            : 'Опишите, что важно сохранить после удаления фона...'
      : isEdit ? 'Например: сохранить лицо, заменить одежду, взять фон или цвет из референса...'
        : 'Опишите идею своими словами — получите изображение...'
  const promptLimit = isI2I || isEdit || isPaint ? 1000 : 2000
  const promptValue = prompts[studioMode]
  const paintPromptDisplayValue = isPaint && paintTechPromptOpen
    ? `${prompts.paint}${prompts.paint.trim() ? '\n\n' : ''}${paintTechPrompts[paintMode]}`
    : promptValue
  const promptTextareaValue = isPaint ? paintPromptDisplayValue : promptValue
  const promptTextareaLimit = isPaint && paintTechPromptOpen ? 2800 : promptLimit
  const promptCounterValue = promptTextareaValue.length

  function updatePromptTextarea(value: string) {
    if (isPaint && paintTechPromptOpen) {
      const currentUserPrompt = prompts.paint
      if (!currentUserPrompt) {
        setPaintTechPrompts((cur) => ({ ...cur, [paintMode]: value }))
        return
      }
      if (value.startsWith(currentUserPrompt)) {
        setPaintTechPrompts((cur) => ({ ...cur, [paintMode]: value.slice(currentUserPrompt.length).replace(/^\n+/, '') }))
        return
      }
      const [nextUserPrompt = '', ...nextTechPrompt] = value.split(/\n{2,}/)
      setPrompt(nextUserPrompt)
      setPaintTechPrompts((cur) => ({ ...cur, [paintMode]: nextTechPrompt.join('\n\n') }))
      return
    }
    setPrompt(value)
  }

  return { promptTitle, promptPlaceholder, promptLimit, promptValue, promptTextareaValue, promptTextareaLimit, promptCounterValue, updatePromptTextarea }
}
