# Phase 16.4A — Live Delivery Stability + Deployment Health

Goal: stabilize live delivery + add safe version/diagnostics markers. No auth/DB/
feature changes. No secrets or raw platform data exposed.

## Block 1 — Live frontend serving mode

| component | port | process | mode | risk |
|-----------|------|---------|------|------|
| cloudflared tunnel | — | PID 44280 | routes public host → 5173 | — |
| frontend | 5173 | vite (PID 43472) | **Vite DEV server** | HIGH |
| backend | 8000 | uvicorn | FastAPI | restarted to current |

Evidence: live `/` HTML contains `<script type="module" src="/@vite/client">` and
`<script type="module" src="/src/main.tsx">` (raw source modules, not hashed
`/assets/index-*.js`). `vite.config.ts` proxies `/api` + `/media` → 127.0.0.1:8000;
`hmr:false` is set.

**Risk:** serving the Vite dev server on the public URL is the likely cause of:
blinking/lost input (dev transforms invalidated when files change — e.g. Google Drive
sync writes — cause module refetch/flash), and mobile WebViews (Telegram/MAX) caching
dev modules → stale "old version". **Recommended: serve the production `dist` build.**

## Block 2 — Backend freshness health
- Added `GET /api/version` → `{ ok, app:"izo-asa", build, auth_v2:true,
  password_login, generation_protected }`. No secrets, no env, no DB paths.
- Live now returns `build = 16.4A-2026-06-26`, `password_login:true`,
  `generation_protected:true`.
- Behavioral freshness probes (no session): `/api/generate` → 401, `/api/gallery` →
  401 (protection live after restart).

## Block 3 — Frontend build marker + diagnostics
- `frontend/src/diag.tsx`: `APP_BUILD_LABEL = '16.4A-2026-06-26'` (bump per deploy),
  `isDiagMode()` (`?diag=1` or `#diag`), `<DiagPanel/>` mounted at app root.
- Panel shows ONLY: frontend build label; backend build/auth_v2/generation_protected
  (from /api/version); auth state (loading/anon/authed); origin + path (path only);
  `hasSearch`/`hasHash` booleans; `isViteDevClientPresent`; `hasHmrClient`.
- Never shows full query/hash (TG/MAX may put platform data there), tokens, or cookies.

## Block 4 — Telegram diagnostics (booleans only)
Panel `tg.*`: hasTelegram, hasTelegramWebApp, hasTelegramInitData,
initDataLengthCategory (zero/nonzero), readyCallable, expandCallable. No initData,
no initDataUnsafe, no user id.
Checklist: open `?diag=1` in browser, Telegram Desktop, Telegram Mobile; compare
`frontend.build`. If mobile label differs → stale cache / old URL / old dev bundle
(expected while live runs Vite dev) — fixed by switching to dist + cache-busting.

## Block 5 — MAX diagnostics (booleans only)
Panel `max.*`: hasMaxGlobal, hasWebAppGlobal, hasMaxWebAppData, hasMaxInitData,
hasHashWebAppDataParam, userAgentMaxLike, mobile. No WebAppData, no userId, no hash value.
Checklist: open diag in MAX Desktop vs MAX Mobile. If MAX Mobile does not open, check:
Mini App URL, domain allowlist, HTTPS cert on mobile, mobile launch URL/deep link,
mobile WebView console error category, and which global (`MAX`/`maxWebApp`) is injected.

## Block 6 — Stop-blinking plan (recommended; NOT applied — infra needs owner OK)
Preferred (stable):
1. `cd frontend && npx vite build` (produces `dist/`).
2. Serve `dist/` statically — either `npx vite preview --host 127.0.0.1 --port 5173`
   (serves the built bundle) OR mount `dist/` on the backend / a static server.
3. Point the tunnel at the static server, not the Vite dev server. No HMR / no
   `/@vite/client` on the public URL.
Temporary mitigations until then:
- Pause file-writing agents/Google-Drive-sync churn during live testing.
- Rebuild + restart frontend after changes; bump `APP_BUILD_LABEL` to bust caches.

## Block 7 — Modal visual fix (done, low-risk CSS only)
Styled `.auth-modal-tabs` / `.auth-modal-tab` / `.active` for the dark UI (no white
default buttons, active tab highlighted in acid). No auth logic changed.

## Block 8 — Tests/build
`npx tsc -b` → 0 · `npx vite build` → 0 · smoke-auth-v2 / smoke-auth-modal /
smoke-generation-lock → OK. Diag static-checked: no raw secret/token/cookie rendering.

## Operator checklist for EVERY deploy
1. `cd frontend && npx vite build` (and bump `APP_BUILD_LABEL`).
2. Restart backend (stop the single uvicorn on :8000, start one fresh).
3. Restart/serve frontend from `dist` (not dev).
4. Probe `POST /api/generate` (no session) → **401**.
5. Probe `GET /api/gallery` (no session) → **401**.
6. `GET /api/version` → check `build` matches what you deployed.
7. Open `?diag=1` → check `frontend.build` matches; `isViteDevClientPresent:false`
   once on dist.
