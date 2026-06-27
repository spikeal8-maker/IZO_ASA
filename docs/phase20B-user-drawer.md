# Phase 20B — User Drawer / Client Card

Open a full user card from the Users CRM. Uses the existing trusted detail endpoint;
the only backend change is exposing `internal_user_id` in the analytics row (needed to
open the card). No DB/auth/generation changes; no risky admin actions migrated.

## Block 1 — Endpoint audit (`GET /api/admin/users/{internal_user_id}/analytics-v2`)
Returns (verified via TestClient as admin): `summary` (display_name, public_user_code,
providers, email, username, phone, role, status, first_seen_at, last_seen_at,
last_login_at, last_platform, last_ip, last_device, token_balance, tokens_spent,
generations_count, active_sessions_count, device_count, city, country,
internal_user_id, internal_user_id_short), `identities[]` (provider, provider_user_id,
provider_username, masked provider_email, first/last name, language_code, linked_at,
verified_at, last_login_at), `sessions[]` (id, provider, platform, ip_address, device,
created/last_seen/expires_at, revoked_at, revoke_reason), `devices[]` (installation_id,
platform, storage_type, first/last_seen, sanitized metadata), `recent_events[]`,
`recent_security_events[]`, `token_summary` (spent/entries/balance), `admin_actions[]`.
- `require_trusted_admin`; no-session → 401; non-admin → 403; **no** token/password/
  session/code hashes; **no** full raw_profile_json.

## Backend change (minimal, tested)
`admin_user_analytics_row` now also returns `internal_user_id` (used only for the drawer
fetch URL + the collapsed technical section, never a primary label). Test updated.

## Blocks 2-10 — Drawer UI (`adminAnalytics.tsx` → `UserDrawer`)
Right-side drawer (Esc / overlay / × to close). Header: display_name, public_user_code,
provider badges, status (+admin), balance, generations, last_seen. Section tabs:
- **Профиль:** display_name, code, email, username, phone, language, city/country, role,
  status, created_at, last_seen_at. (No raw internal/legacy id here.)
- **Источники:** per identity — Web/TG/MAX badge, provider_username, masked provider_email,
  **short** provider_user_id, linked/verified/last_login. No raw_profile_json.
- **Сессии:** platform/provider/ip, device (browser/os/type from metadata), created/expires,
  active vs revoked + reason. No token/refresh hashes.
- **Устройства:** short installation_id, platform, storage_type, language/timezone/app,
  first/last seen.
- **Генерации:** total + tokens spent + last activity; «детальная история будет в Phase 23».
- **Токены:** balance, total spent, ledger entries; «детальный журнал — Phase 20C/23».
- **Логи:** recent events + security_events + admin_actions (time/type/result/platform/ip).
  No raw prompt/password/token/cookie/initData/WebAppData.
- **Техническое:** collapsed by default, labeled «Технические идентификаторы. Не показывать
  пользователю.»; reveals internal_user_id / public_user_code / primary_provider.
- Actions: a single **disabled** placeholder «Действия будут перенесены в Phase 20C».

## Block 11 — States
Drawer handles loading / 404 («Пользователь не найден») / 401-403 («Сессия администратора
истекла») / network error / empty arrays — all human-readable.

## Deferred (20C / 23)
Risky admin actions (role/plan/tokens/ban/reset/disable); detailed generation history;
detailed token ledger.

## Security proof
Drawer fetches `users/{id}/analytics-v2` with `credentials:'include'`; never
`X-OneNode-User`, never legacy `require_admin`. Smoke enforces absence of
session_token_hash/refresh_token_hash/password_hash/code_hash/raw_profile_json/initData/
WebAppData in the UI code; `internal_user_id` is never a bold primary label.

## Tests / build / live
- `tsc -b` 0 · `vite build` 0 · smokes auth-v2 / auth-modal / generation-lock /
  admin-analytics (incl. drawer sections + states) OK. Backend `test_admin_analytics` +
  `test_admin_v2` → 28 passed.
- Live: backend restarted, build `20B-2026-06-26`; frontend dist `index-CB-Yn4X9.js`;
  no-session `/api/generate`, `/api/gallery`, `/api/admin/users-analytics-v2`,
  `/api/admin/users/{id}/analytics-v2` → 401; page renders (Playwright #root 11241, no errors).

## Files changed
- `backend/main.py` (+`internal_user_id` in analytics row; APP_BUILD 20B)
- `backend/test_admin_analytics.py` (assert internal_user_id present)
- `frontend/src/adminAnalytics.tsx` (UserDrawer replaces preview)
- `frontend/src/index.css` (drawer/tabs styles)
- `frontend/smoke-admin-analytics.mjs` (drawer smoke)
- `frontend/src/diag.tsx` (label 20B)
- `docs/phase20B-user-drawer.md`
