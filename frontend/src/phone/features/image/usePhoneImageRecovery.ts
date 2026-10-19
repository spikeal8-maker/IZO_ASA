import { useEffect, useState, type RefObject } from 'react'

import { loadPhoneJobs, waitForPhoneJob, type PhoneJob } from '../../core/jobs.ts'

type RecoveryState = { offline: boolean; phase: 'checking' | 'failed' | 'ready' }
type RecoveryOptions = {
  offline: boolean
  jobObserver: RefObject<AbortController | null>
  completeImage: (job: PhoneJob, signal: AbortSignal) => void
  setBusy: (value: boolean) => void
  setProgress: (value: number) => void
  setError: (value: string) => void
  setResult: (value: string) => void
  setResultId: (value: string) => void
}

export function usePhoneImageRecovery({ offline, jobObserver: jobObserverRef, completeImage, setBusy,
  setProgress, setError, setResult, setResultId }: RecoveryOptions) {
  const [recovery, setRecovery] = useState<RecoveryState>({ offline, phase: 'checking' })
  const [attempt, setAttempt] = useState(0)
  if (recovery.offline !== offline) setRecovery({ offline, phase: 'checking' })
  const recovering = recovery.offline !== offline || recovery.phase !== 'ready'
  const retryAllowed = !offline && recovery.offline === offline && recovery.phase === 'failed'

  useEffect(() => {
    const controller = new AbortController()
    let terminalObserved = false
    jobObserverRef.current = controller
    if (!offline) {
      void loadPhoneJobs(true, controller.signal).then(async (items) => {
        controller.signal.throwIfAborted()
        setRecovery({ offline, phase: 'ready' })
        const active = items.find((item) => item.modality === 'image' && !item.terminal)
        if (!active) return
        setBusy(true); setProgress(active.progress); setError(''); setResult(''); setResultId('')
        const job = await waitForPhoneJob(active.id, { signal: controller.signal,
          onChange: (value) => setProgress(value.progress) })
        terminalObserved = job.terminal
        completeImage(job, controller.signal)
      }).catch((caught) => {
        if (controller.signal.aborted) return
        if (!terminalObserved) setRecovery({ offline, phase: 'failed' })
        setError(caught instanceof Error ? caught.message : 'Не удалось восстановить задание.')
      }).finally(() => { if (!controller.signal.aborted) setBusy(false) })
    }
    return () => { controller.abort(); jobObserverRef.current?.abort(); jobObserverRef.current = null }
  }, [attempt, completeImage, jobObserverRef, offline, setBusy, setError, setProgress, setResult, setResultId])

  const retryRecovery = () => {
    if (!retryAllowed) return
    setRecovery({ offline, phase: 'checking' })
    setError('')
    setAttempt((value) => value + 1)
  }

  const requireRecheck = () => setRecovery({ offline, phase: 'failed' })

  return { recovering, retryAllowed, retryRecovery, requireRecheck }
}
