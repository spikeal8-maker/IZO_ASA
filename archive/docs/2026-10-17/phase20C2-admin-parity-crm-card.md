# Phase 20C.2 — Admin Environment Parity + CRM User Card Redesign

Environment parity QA + redesign of the user card into a real CRM dossier. No new risky
features; no DB schema / users.id / auth / generation / gallery changes; legacy block kept.

## Block 1 — Why local and prod differed (ROOT CAUSE)
They do **not** use different environments. Verified:
- API base = `/api` (relative) in all code; **no `.env` files**, so `VITE_API_BASE_URL` is
  unset → always same-origin via the Vite proxy.
- `vite.config.ts`: both `server.proxy` (dev) and `preview.proxy` (preview) send `/api` →
  `http://127.0.0.1:8000`.
- Production = Cloudflare tunnel → the **same** `vite preview` (5173, serving dist) → the
  **same** backend (127.0.0.1:8000) → the **same** DB (`onenode.sqlite3`).
- Proof: `LOCAL /api/version` == `LIVE /api/version` == `20C.2-2026-06-27`; the visual
  parity run shows **both targets serve the identical bundle** `index-Dv7Ym4mj.js`.

So the difference was **auth state, not data source**:
- `127.0.0.1:5173?userId=admin` = legacy fake identity (`X-OneNode-User`), **no trusted
  admin cookie** → the new CRM's cookie-auth `/admin/users-analytics-v2` returns 401 →
  empty CRM.
- `https://izo.alikinas.ru` with the owner logged in = real `onenode_session` admin
  cookie → CRM returns real users.

This is correct, secure behaviour. The fix is to make it **visible** (diagnostics) — not
to weaken auth.

## Block 2 — Admin diagnostics
- Backend `GET /api/admin/diagnostics-v2` (`require_trusted_admin`): `backend_build`,
  `db_file` (**basename only**, never the path), `user_count`, `auth_mode`, `admin_role`,
  `admin_provider`, `server_time`. No secrets.
- Frontend `AdminDiagnostics` strip atop the Users CRM, always visible: frontend build
  label, backend build, API base, origin, Vite mode (DEV vs PRODUCTION/PREVIEW), **auth
  mode** (trusted admin session vs «НЕТ trusted-сессии — CRM будет пустым»), DB file, user
  count. Auto-expands when there is no admin session, so an empty CRM explains itself.

## Block 3 — Parity modes (scripts)
`npm run admin:dev` (LOCAL DEV), `npm run admin:preview` (LOCAL PROD PREVIEW: build + serve
dist on same backend), `npm run admin:visual-check` (`visual-admin-parity.mjs`). Mode is
labeled live by the diagnostics strip.

## Block 4 — Visual QA (`visual-admin-parity.mjs`, Playwright/Chromium, no extension)
Result: local-preview and production both → version `20C.2-2026-06-27`, asset
`index-Dv7Ym4mj.js`, diag 401 (fresh headless browser, no cookie), **no page errors** →
identical layout + bundle confirmed. Screenshots in `frontend/visual-out/`. The admin CRM
card itself needs an admin login to render data (same blocker as 20C.1) — owner-side.

## Block 5 — CRM card redesign
`UserDrawer` (narrow side drawer) → **`UserCard`**: centered large modal 90vw×90vh
(full-screen on mobile), **sticky header** (parsed name, public_user_code, provider badges,
role/status, balance, generations, created_at, last_seen, security-event count), **sticky
section nav** that jumps to anchors (`scrollIntoView`), and **all sections stacked
vertically** (not hidden behind tabs): Обзор · Профиль · Источники входа · Сессии ·
Устройства · Генерации · Токены · Логи · Админ-действия · Техническое.

## Block 6 — Parsed data
- Name fallback chain (`parsedName`): display_name → first+last → username → provider
  username → public_user_code.
- Contacts: email/username/phone (masked) + language/city/country from safe summary/identity.
- Identities: Web/TG/MAX, provider_username, masked provider_email, **short** provider_user_id,
  linked/verified/last_login, and **raw-профиль: да/нет** (`has_raw_profile` — boolean only;
  `raw_profile_json` is never sent).
- Sessions: provider/platform/ip, browser/os/device_type, created/expires, active/revoked +
  reason. Devices: short installation_id + **short anonymous_id**, platform, storage,
  language/timezone/app build, first/last seen.
- Generations/Tokens: summaries + clear deferred notes (detail → Phase 23). Logs:
  event_logs + security_events + audit_logs, no raw prompts/secrets. Technical: collapsed.

Safe backend enrichment (existing columns only): identities `has_raw_profile` + masked
`phone`; devices `anonymous_id`. New helper `mask_phone`.

## Block 7 — Admin actions
In the «Админ-действия» section: ban/unban, role, tokens (+50/−50/+1/−1 + free input),
plan (real `users.plan`), profile rename, password reset. Each: reason required, confirm,
loading/success/error, refreshes card + CRM row, button labeled «Подтвердить · в audit
log». The stale disabled row-level «Действия» button was removed (no confusing primary).

## Block 8 — Legacy preserved
Legacy block unchanged: collapsed behind the toggle with the emergency warning. Not deleted.

## Block 9 — Tests/build
`tsc -b` 0 · `vite build` 0 · smokes admin-analytics (card sections, sticky nav + anchors,
parsed name, has_raw_profile w/o JSON, diagnostics) / auth-v2 / auth-modal / generation-lock
OK. Backend `test_admin_analytics` + `test_admin_actions` + `test_admin_v2` → 37 passed.

## Block 10 — Security proof
Card + diagnostics use cookie auth (`credentials:include`) only; no `X-OneNode-User`. No
`password_hash`/`session_token_hash`/`refresh_token_hash`/`code_hash`/`raw_profile_json`/
`initData`/`WebAppData` in UI or responses (smoke + backend tests). `db_file` is basename
only. Diagnostics endpoint is `require_trusted_admin` (no-session → 401, verified live).

## Data still missing from backend
Detailed generation history + image previews and detailed token ledger rows (Phase 23);
server-side sort + admin-status filter (P1).

## Files changed
- `backend/main.py` (diagnostics-v2 endpoint; detail enrichment has_raw_profile/phone/
  anonymous_id; `mask_phone`; APP_BUILD 20C.2)
- `frontend/src/adminAnalytics.tsx` (UserCard + AdminDiagnostics + parsing)
- `frontend/src/index.css` (CRM card + diagnostics styles)
- `frontend/package.json` (admin:dev/preview/visual-check)
- `frontend/visual-admin-parity.mjs` (new)
- `frontend/smoke-admin-analytics.mjs` (card/diagnostics checks)
- `frontend/src/diag.tsx` (label 20C.2)
- `docs/phase20C2-admin-parity-crm-card.md`
