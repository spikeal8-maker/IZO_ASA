# Project Cleanup Baseline - 2026-07-06

This document records the cleanup performed after freezing the `/new`
Text-to-Image MVP.

## Canonical Working Point

- Active/canonical worktree: `D:\Google Drive\My progact\wt-integrated`
- Branch: `feature/new-ui-v2-integrated-safe`
- Current head after cleanup docs: `4fad9d6`
- Public frontend: `https://izo.alikinas.ru`
- Live local frontend preview: `127.0.0.1:5173`
- Live backend: `127.0.0.1:8000`
- ComfyUI: `127.0.0.1:8188`

The old main worktree at `D:\Google Drive\My progact\Генератор картинок` remains
as the production backend/data location and a git worktree, but it is not the
canonical frontend development location for the frozen `/new` MVP.

## Ports After Cleanup

Kept:

- `5173` - live Vite preview serving the frozen frontend build.
- `8000` - live FastAPI backend using the production SQLite DB.
- `8188` - local ComfyUI.

Stopped:

- `5188`
- `5189`
- `5191`
- `5193`

These were extra Vite dev servers from earlier QA sessions.

## Archive

Moved cleanup artifacts to:

`D:\Google Drive\My progact\IZO_cleanup_archive_20260706_2035`

The archive contains:

- old screenshot/review folders from previous live checks;
- old stash/export folders;
- old loose frontend/backend logs;
- old frontend visual artifacts and screenshots;
- old backend cache files and old DB backup artifacts;
- old `.opencode`, `.pytest_cache`, `tmp_logs`;
- the previous `_v3frontend` symlink;
- the removed old `wt-new-ui` worktree files;
- `main-worktree-uncommitted-diff-before-cleanup.patch`, preserving the old
  uncommitted main-worktree frontend WIP before it was restored.

The archive manifest is:

`D:\Google Drive\My progact\IZO_cleanup_archive_20260706_2035\archive-manifest.tsv`

## What Was Not Moved

The following were intentionally kept in the active project:

- `.tools/` - contains `cloudflared.exe`, useful for future tunnel/deploy work.
- `backend/.env` - local secrets/config.
- `backend/media/` - generated/user media.
- `backend/onenode.sqlite3`, `backend/onenode.sqlite3-shm`,
  `backend/onenode.sqlite3-wal` - live production SQLite DB files.
- `frontend/dist/` - currently served frozen build.
- `frontend/node_modules/` - installed frontend dependencies.
- `logs/live_backend_faceswap_test.log` - current live backend log target.

## Git Worktrees

After cleanup, active worktrees are:

- `D:\Google Drive\My progact\Генератор картинок`
  - branch: `hotfix/live-auth-gallery-faceswap-20260703`
  - status: clean
- `D:\Google Drive\My progact\wt-integrated`
  - branch: `feature/new-ui-v2-integrated-safe`
  - status: clean before this cleanup doc

Removed/deactivated:

- `D:\Google Drive\My progact\wt-new-ui`
  - removed from git worktree list;
  - physical files moved into the cleanup archive.

Stale `.git/worktrees/*` metadata for older removed worktrees was also removed,
leaving only `wt-integrated` metadata.

## Safety Notes

- No live backend restart was performed.
- No live database file was moved or edited.
- No generated media folder was moved.
- The frontend live preview on `5173` remained running.
- The old main-worktree uncommitted WIP was archived as a patch before tracked
  files were restored to clean state.
