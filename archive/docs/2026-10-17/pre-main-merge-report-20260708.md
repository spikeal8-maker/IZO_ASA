# Pre-main merge report — 2026-07-08

Canonical workspace: `D:\Google Drive\My progact\Генератор картинок`.

Source branch: `hotfix/live-auth-gallery-faceswap-20260703`.

Expected commit from handoff plan: `ae7ab89`.

Actual pre-merge HEAD after static shell stabilization: `9fbc1b4`.

## Scope vs main

`main...HEAD` contains 52 changed paths:

- Frontend UI 2.0 shell and modes: `frontend/src/newUi.tsx`, `frontend/src/newUi.css`, `frontend/src/newStudioV3.css`, `frontend/src/TopBarV3.tsx`, `frontend/src/PaintWorkbench.tsx`, `frontend/src/LegacyApp.tsx`, helper/preset files, and `frontend/vite.config.ts`.
- Backend/API/feed/gallery work: `backend/main.py`, feed/gallery media helpers, migration/audit scripts, and tests.
- Static public pages: `backend/static/feed/index.html`, `backend/static/gallery/index.html`, and feed visual assets in `backend/static/feed/assets/*.webp`.
- Documentation: handoff/review/architecture docs under `docs/`.
- Tooling: `tools/acceptance_generation_test.py`, startup/public scripts.

## Deletions and artifacts

- Deleted files in the merge scope: none.
- Archives: none found in the merge scope.
- Clipboard/temp screenshots: none found in the merge scope.
- HTML files in scope are intentional static public pages: `backend/static/feed/index.html`, `backend/static/gallery/index.html`, `frontend/index.html`.
- Binary assets in scope are intentional: feed `.webp` assets and `frontend/src/assets/preview-placeholder.jpg`.

## Pre-merge checks

- `npm run build` in `frontend`: passed.
- Backend smoke before merge:
  - `/api/health`: 200.
  - `/api/version`: 200.
  - `/api/feed?type=for_you&limit=3`: 200.
  - `/api/auth/capabilities-v2`: 200.
  - `/api/gallery/page`: 401 without a live user session; endpoint reachable and expected to require auth.
- Browser smoke before merge:
  - `/`, `/new`, `/paint`, `/feed`, `/gallery`, `/profile`: 200.
  - `/feed`: new feed page renders cards.
  - `/feed` and `/gallery`: no old root `/#...` links, no Kaspersky markers, no Vite dev client.
  - Static topbar marker `n2-topbar`: removed.

## Merge rule

Preserve the new UI 2.0, feed, gallery, auth-v2, and static shell work. Resolve conflicts manually without reverting new feed/gallery/UI behavior.
