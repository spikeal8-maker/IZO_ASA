import { useCallback, useEffect, type Dispatch, type SetStateAction } from 'react'
import { initAuthV2, refreshAuthStateV2, type AuthStatusV2 } from './authV2'
import type { N2Tab, N2View } from './studio/studioTypes'

interface ProfileAuthNavigationOptions {
  authStatus: AuthStatusV2
  view: N2View
  setView: Dispatch<SetStateAction<N2View>>
  setTab: Dispatch<SetStateAction<N2Tab>>
  goProfile: () => void
  setAuthOpen: Dispatch<SetStateAction<boolean>>
}

export function useProfileAuthNavigation({
  authStatus,
  view,
  setView,
  setTab,
  goProfile,
  setAuthOpen,
}: ProfileAuthNavigationOptions): () => void {
  useEffect(() => {
    if (view !== 'profile' || authStatus !== 'anon') return
    setView('tabs')
    setTab('text')
    if (window.location.pathname === '/profile') window.history.replaceState(null, '', '/')
    setAuthOpen(true)
  }, [authStatus, setAuthOpen, setTab, setView, view])

  return useCallback(() => {
    void (async () => {
      if (authStatus === 'authed') {
        goProfile()
        return
      }
      if (authStatus === 'loading') await initAuthV2()
      if (await refreshAuthStateV2()) {
        goProfile()
        return
      }
      setAuthOpen(true)
    })()
  }, [authStatus, goProfile, setAuthOpen])
}
