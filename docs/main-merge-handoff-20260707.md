# Main Merge Handoff 2026-07-07

This project folder is the current integration candidate for the new UI plus backend static feed/gallery pages.

## Source Of Truth

- Project folder: `D:\Google Drive\My progact\Генератор картинок`
- Branch: `hotfix/live-auth-gallery-faceswap-20260703`
- Do not use sibling worktrees as deployment sources for this project.
- Do not leave `frontend/` deleted in this folder. Public launch depends on `frontend/` for `vite build` and `vite preview`.

## Integrated Pieces

- New UI frontend remains in `frontend/`.
- Legacy React app was split into `frontend/src/LegacyApp.tsx`.
- Paint workbench is split into `frontend/src/PaintWorkbench.tsx`.
- Backend static feed page is installed at `backend/static/feed/index.html`.
- Feed visual assets are installed under `backend/static/feed/assets/`.
- Backend static gallery page is installed at `backend/static/gallery/index.html`.
- Backend serves page shells for `/feed`, `/feed/`, `/gallery`, and `/gallery/`.
- Vite dev and preview proxy backend-owned routes:
  - `/api`
  - `/media`
  - `/feed`
  - `/gallery`
  - `/static`

## Main Merge Rules

1. Merge from this project folder/branch into `main`.
2. Keep the restored `frontend/` directory from this branch.
3. Keep the backend feed/gallery static files from this branch.
4. Keep the Vite proxy entries for `/feed`, `/gallery`, and `/static`.
5. If conflicts appear in `backend/main.py`, preserve both:
   - new UI/live auth behavior already present in this branch;
   - feed/gallery route and API blocks from the integrated backend.
6. Do not remove the audit/migration scripts added for media and gallery safety unless the same checks are replaced elsewhere.

## Required Checks Before Main

Run from `D:\Google Drive\My progact\Генератор картинок`:

```powershell
python -m py_compile backend\main.py
python -m pytest backend\test_feed_v2.py -q
cd frontend
npm run build
```

Then run public mode from the same worktree:

```powershell
cd "D:\Google Drive\My progact\Генератор картинок"
.\start-public.bat
```

Check:

- `https://izo.alikinas.ru/new`
- `https://izo.alikinas.ru/feed`
- `https://izo.alikinas.ru/gallery`
- `https://izo.alikinas.ru/static/feed/assets/mode_text.webp`
- `https://izo.alikinas.ru/api/version`

## Current Risk Notes

- `/feed` and `/gallery` are backend static pages proxied through Vite preview on port `5173`.
- If Vite proxy misses `/feed`, `/gallery`, or `/static`, the domain may show the SPA or a 404 instead of the backend page.
- If backend is not restarted from this project folder, the live site can temporarily run mixed code: new Vite frontend with an older backend process.
