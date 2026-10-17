# Main release — UI 2.0, feed, gallery

Date: 2026-07-08.

Canonical workspace: `D:\Google Drive\My progact\Генератор картинок`.

Main merge commit: `26d2951`.

## Released state

- `/` and `/new` serve the UI 2.0 generator shell.
- `/paint` serves the separated drawing page.
- `/feed` serves the new public feed from `backend/static/feed/index.html`; this
  visible static page is the canonical feed UI for current optimization work.
- `/gallery` serves the new gallery shell and requires a valid user session for private gallery data.
- `/profile` remains part of the UI 2.0 shell.

## Legacy state

The old interface is no longer the canonical root experience. Keep any old working copies as archive/reference only; do not launch production from `wt-integrated`.

## Static shell checks

- `/feed` and `/gallery` use the UI 2.0 topbar visual rules.
- Old root hash links `/#...` were removed from static feed/gallery navigation.
- `n2-topbar` markers were removed from static feed/gallery HTML.
- No Vite dev client, Kaspersky marker, or temporary screenshot/archive artifact is expected in the release pages.

## Verification

- `npm run build` passed on `main`.
- API smoke passed for `/api/health`, `/api/version`, `/api/feed`, `/api/auth/capabilities-v2`.
- `/api/gallery/page` correctly requires auth and returns 401 without a live user session.
- Browser smoke passed locally and on `https://izo.alikinas.ru` for `/`, `/new`, `/paint`, `/feed`, `/gallery`, `/profile`.
