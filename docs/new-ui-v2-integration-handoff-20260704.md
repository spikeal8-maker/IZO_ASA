# New UI v2 integration handoff - 2026-07-04

Current safe integration branch:

- `hotfix/live-auth-gallery-faceswap-20260703`
- integrated feed/new-ui commits from `feature/new-ui-v2-clean`
- latest integrated commit: use the current HEAD of this safe integration branch
  (do not deploy the old `feature/new-ui-v2-clean` worktree directly).

New visual shell for /new (2026-07-06):

- The /new studio shell is rebuilt from the HTML prototype
  `izo-aca-new-responsive-page (14).html`. Prototype `<style>` is scoped under
  `.iv3` in `frontend/src/newStudioV3.css` (auto-transformed: `:root/body/html`
  → `.iv3`, every selector prefixed `.iv3 `, @media/@keyframes preserved) to
  avoid collisions with index.css / newUi.css.
- Shared top bar `frontend/src/TopBarV3.tsx` (brand ИЗО АСА, Лента, mode tabs
  Текст→Изо/Изо→Изо/Редактор/Рисунок/Лицо/Видео[disabled], Галерея, Помощь,
  Профиль) is used on /new, /feed, /gallery, /profile. Cross-page links do a
  full navigation; on /new mode tabs switch in-page via onSelectMode.
- Only Текст→Изо is functionally wired in the new shell: prompt + 0/2000
  counter, Шаблоны (templates modal), Идея (random), styles row (I2I_STYLES +
  «Нет»), resolution select + 1:1/9:16/16:9, quality Быстро/Стандарт/Максимум,
  Сгенерировать → /api/generate + job polling, loading, result image, error
  (notice), download, Поделиться menu, history strip, «Промпт изображения» dock
  (Копировать / Изменить в → tabs / В ленту → openPublish / Вариации). Голос and
  Улучшить show honest «скоро» toasts.
- Изо→Изо, Редактор, Рисунок, Лицо, Видео are honest placeholders in the new
  shell (functionality remains in the current /  UI). Old studio render helpers
  (controls/resultPanel/paintView/futureView/progressCard/mobilePreview) and the
  primitive gallery/profile views were deleted from newUi.tsx; the feed and all
  generation wiring (apiFetch, useAuthV2, AuthV2Modal, /api/generate, polling,
  gallery, feed publish, stylePresets, RESOLUTION_PRESETS) are preserved.

Canonical routes (updated 2026-07-05, ported working screens):

- `/feed` (and `/lenta`) — public live feed, no login wall for reading.
- `/gallery` (compat `/new/gallery`) — renders the REAL working old gallery
  (`GalleryView` from App.tsx) inside a new-ui wrapper (`NewSubNav`). Full UX
  parity: quota banner (Галерея: занято X из Y · свободно Z · тариф PRO),
  Сетка/Список toggle, full-size cards (mode/date/prompt), card actions
  favorite/download/delete, detail modal with "Использовать изображение"
  action list (Изо→Изо, edit, paint, faceswap, try_on…), tech info,
  publish-to-feed modal, copy-link. Login required; guests get a sign-in card.
- `/profile` (compat `/new/profile`) — renders the REAL old account settings
  (`SettingsView` from App.tsx) inside the wrapper. Tabs Профиль / Тарифы /
  Заработать токены / Модели; avatar + "Загрузить файл", avatar presets, name,
  public code, plan badge, gallery limit, daily/balance tokens, promo/referral,
  email, language, template preview, age, Сохранить профиль, Выйти, tech info,
  linked sign-ins, plan cards, earn/referral, model picker. Not-authed handled
  by SettingsView's own guest branch.
- Rationale: do NOT reinvent these screens — the new routes mount the same
  components the old `/` Studio uses, so behaviour and backend wiring are
  identical. App.tsx routes `/gallery` and `/profile` (and `/new/*` compat)
  BEFORE the NewStudio branch. NewStudio's own primitive gallery/profile views
  are now unreachable dead code; its topbar/mobile Галерея/Профиль buttons do a
  full navigation to `/gallery` / `/profile`. Old `/` Studio still works.
- Navigation: NewSubNav links Лента(/feed) · ИЗО(/new) · Галерея · Профиль (+
  Админка if trusted admin). back-to-studio inside the screens → `/feed`.

What was integrated:

- `/new` UI polish from `8cce4e1`
- `/new/feed` and canonical `/feed` feed UI from `70895f6`
- live feed backend/API/publication flow from `bcb6bfe`
- feed stabilization from `864d04f`

Auth rules that must not be reverted:

- Do not reintroduce `AuthV2Panel`.
- Do not render old `Вход (v2)` / `Вход по email (v2)` UI.
- Do not send `X-OneNode-User` from frontend requests.
- Do not use `localStorage('onenode_user')` as identity.
- Admin UI visibility must come only from trusted auth state:
  `authV2Status === 'authed' && authMe?.account?.role === 'admin'`.
- Feed publishing/reactions must use trusted cookie session through backend.
- Feed reading must remain public. A guest may open `/feed`, `/new`, and
  `/new/feed` and see publications/empty-state without a blocking login panel.
  Login is required only for publishing, reactions, saves, recreate actions, and
  the personal gallery.
- `/new` gallery is personal and may ask guests to sign in, but its cards must
  keep the publication flow: gallery item -> `openPublish` -> `POST
  /api/feed/publications`.
- When merging work from another branch, keep the current `AuthV2Modal` and
  do not bring back old auth or guest-gated feed UI.

Before any future `/new` merge/deploy, run:

```powershell
rg -n "AuthV2Panel|Вход \(v2\)|Вход по email \(v2\)|X-OneNode-User|onenode_user|SESSION_USER_ID|auth-v2-code|auth-v2-providers" frontend/src
npm run lint
npx tsc -b
npx vite build
python -m pytest backend/test_feed_v2.py backend/test_password_auth.py backend/test_security_hotfix_20260629.py -q
```

Expected grep result:

- no real frontend matches;
- comments explaining that these legacy auth paths are forbidden are acceptable.

Deployment rule:

- Do not deploy `feature/new-ui-v2-clean` directly if it has not first absorbed the auth fixes.
- Deploy from the safe integrated branch after checks pass.
