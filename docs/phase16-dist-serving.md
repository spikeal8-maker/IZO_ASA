# Phase 16.4B — Public Frontend Switched to Stable Dist Serving

Switched `https://izo.alikinas.ru` from the Vite **dev** server to the built
`frontend/dist`. No auth / backend / DB / generation changes.

## Old mode (before)
Live `/` HTML contained `<script src="/@vite/client">` + raw `<script src="/src/main.tsx">`
(Vite dev server on :5173, behind cloudflared). Caused blinking/state-reset and stale
mobile WebView caching.

## New mode (after)
- `frontend/dist` built (`npx tsc -b` + `npx vite build`), asset `index-dzsBkfKd.js`.
- Port 5173 now runs **`vite preview`** (serves dist; SPA fallback to index.html).
- `vite.config.ts` gained a `preview` block mirroring the `/api` + `/media` proxy to
  `http://127.0.0.1:8000` (preview uses `preview.*`, not `server.*`).
- cloudflared still points at :5173; backend untouched on :8000.

Note: `vite preview` is acceptable staging, not a hardened production server. For a
final setup, serve `dist/` via nginx/Caddy (or a backend static mount) with caching.

## Live verification
- `/` has **no** `/@vite/client`, **no** `/src/main.tsx`; serves hashed
  `assets/index-dzsBkfKd.js`. ✓
- `/api` proxied through preview (local + live `me-v2` → 401). ✓
- `?diag=1` panel shows `isViteDevClientPresent:false`, `hasHmrClient:false`,
  `frontend.build = 16.4A-2026-06-26`, backend build from `/api/version`.

## Backend security probes (live, no session)
`POST /api/generate` → 401 · `GET /api/gallery` → 401 · `GET /api/me-v2` → 401 ·
`GET /api/version` → 200.

## Auth smoke (live, disposable account; no secrets printed)
register → 200 · me-v2 → 200 · reload → 200 · logout → 200 · me-v2 after logout → 401 ·
login again → 200.

## Tests / build
`npx tsc -b` → 0 · `npx vite build` → 0 · smoke-auth-v2 / smoke-auth-modal /
smoke-generation-lock → OK.

## Telegram/MAX — manual checks (not fixed here)
Open `https://izo.alikinas.ru/?diag=1` and compare `frontend.build` across:
browser, Telegram Desktop, Telegram Mobile, MAX Desktop, MAX Mobile.
- If Telegram Mobile still shows an old label → Telegram in-app cache or an old Mini
  App URL; force-close/clear the Telegram Mini App, re-open from the bot button.
- If MAX Mobile still does not open → MAX app config: Mini App URL, domain allowlist,
  HTTPS, mobile launch/deep link; capture only the WebView error category via diag.

## Files changed
- `frontend/vite.config.ts` — added `preview` block (proxy + allowedHosts + port).
- (operational) port 5173 process switched from `vite dev` to `vite preview`.

## Remaining risk / operator note
The local launcher `start-project.bat` still starts `npm run dev`. After a reboot or
re-running the .bat, the public URL would revert to the dev server. For the public
tunnel, start the frontend with:
`cd frontend && npx vite build && npx vite preview --host 127.0.0.1 --port 5173`
(rebuild + restart preview on every frontend deploy; bump `APP_BUILD_LABEL`).
