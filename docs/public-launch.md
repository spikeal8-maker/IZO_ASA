# Public vs Dev launch

Two launchers, clearly separated:

| script | purpose | frontend on :5173 |
|--------|---------|-------------------|
| `start-project.bat` | **DEV ONLY** (local development) | Vite **dev** server (hot-reload, raw `/src`) |
| `start-public.bat` | **PUBLIC / LIVE** (tunnel izo.alikinas.ru) | Vite **preview** of built `frontend/dist` |
| `stop-public.bat` | stop public backend+frontend | — (leaves cloudflared running) |

## Why this split
The public tunnel `https://izo.alikinas.ru` routes to port **5173**. If that port runs
the Vite **dev** server, the live HTML contains `/@vite/client` + raw `/src/main.tsx`:
- the page blinks / resets state (dev re-transforms modules when files change — e.g.
  Google Drive sync writes);
- mobile WebViews (Telegram/MAX) cache stale dev modules → "old version".
`start-public.bat` serves the immutable, hashed `dist` build instead — stable, cacheable.

## start-project.bat (DEV ONLY)
Unchanged behavior; now prints a DEV-ONLY warning. Starts backend (:8000) + `npm run
dev` (:5173). Do **not** use while the tunnel is meant to serve the public site.

## start-public.bat (PUBLIC)
1. Builds frontend: `npx tsc -b` + `npx vite build` (aborts on failure — public site
   stays unchanged if the build is broken).
2. Frees ports 8000 + 5173 (stops old backend/dev/preview; no duplicates).
3. Starts backend: `uvicorn main:app --host 127.0.0.1 --port 8000`.
4. Starts frontend: `npx vite preview --host 127.0.0.1 --port 5173` (serves dist).
5. Probes and prints: backend/frontend PIDs, vite-dev-client present (False expected),
   hashed asset present (True), `/api/version` (200), and no-session
   generate/gallery/me (401 each).
Cloudflared is NOT managed here — it must already point to :5173.

## Safe backend-only restart

After a backend-only change that has already passed the full test/build gate, use the
checked PowerShell helper instead of assembling stop/start commands manually:

```powershell
.\tools\restart-backend.ps1 -PreflightOnly
.\tools\restart-backend.ps1
```

The helper is intentionally restricted to `127.0.0.1`. It validates the Python import,
requires exactly one existing `uvicorn main:app` listener with the expected command,
checks current health before stopping it, writes separate timestamped stdout/stderr logs,
waits for the new `/api/health` response, and verifies the new listener PID. It inherits
the caller's environment and does not manage frontend, ComfyUI, Ollama or the tunnel.

For a dependency/path check without inspecting or restarting a listener:

```powershell
.\tools\restart-backend.ps1 -ValidateOnly
```

`vite preview` is acceptable staging, not a hardened production server; for a final
setup serve `dist/` via nginx/Caddy with caching.

## Deploy checklist (every change)
1. Run `start-public.bat` (rebuilds dist + restarts backend + preview). Bump
   `APP_BUILD_LABEL` in `frontend/src/diag.tsx` so caches/labels are distinguishable.
2. Open `https://izo.alikinas.ru/` → view source has **no** `/@vite/client`.
3. `GET /api/version` → 200, `build` matches what you deployed.
4. `POST /api/generate` (no session) → **401**.
5. `GET /api/gallery` (no session) → **401**.
6. Open `https://izo.alikinas.ru/?diag=1` → `isViteDevClientPresent:false`,
   `frontend.build` correct, `backend.build` correct.

## Mobile (Telegram/MAX) note
If a mobile app still shows an old build after `start-public.bat`: it is platform
cache, not the server. Force-close the Mini App and re-open from the bot. If MAX Mobile
won't open at all, check the MAX Mini App URL / domain allowlist / HTTPS / mobile launch
config (see docs/phase16-live-delivery-stability.md).
