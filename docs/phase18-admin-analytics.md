# Phase 18 — Admin / Auth Analytics Foundation

Clean, human-readable user identity + admin analytics over the existing trusted auth.
No users.id change, no destructive migration, no generation/gallery changes. No
token/password/code hashes, no raw tokens/cookies/initData/WebAppData exposed.

## Data model (additive)
- `users.public_user_code TEXT` + partial UNIQUE index `ux_users_public_user_code`.
  Backfilled idempotently in `init_db()`. Format `WEB-000001 / TG-000002 / MAX-000003
  / USR-000004`; global monotonic number (unique), provider prefix from the primary
  provider at creation; **stable** once assigned; never an auth key.
- (also live from 14.4) `email_verified_at`, `phone_verified_at`.

## Helpers
- `ensure_public_user_code(conn, iuid)` — assign-once, idempotent.
- `resolve_primary_provider(conn, iuid)` — latest successful-login identity, else first linked.
- `resolve_display_name(urow, identity)` — priority: `display_name` → first+last →
  provider_username → email local-part → public_user_code → "Пользователь".
- `get_client_ip(request)` — analytics-only; trusts `CF-Connecting-IP` only when
  `TRUST_CLOUDFLARE_HEADERS=true`, `X-Forwarded-For` only when `TRUST_PROXY_HEADERS=true`;
  else the socket peer. `_client_ip` delegates to it (same default behavior).
- `parse_user_agent(ua)` → `{device_type, browser, os}` (coarse, dependency-free; no raw UA stored).

## Source / platform tracking
`create_auth_session` (called by every login: web_email/telegram/max) now also:
updates `users.last_seen_at`, ensures `public_user_code`, records `get_client_ip` +
parsed device in the session `metadata_json`. Providers: web_email / telegram / max.
Platforms: web / web_desktop / web_mobile / telegram_mini_app / max_mini_app / unknown.
Telegram/MAX identity upserts already store username/first/last/lang/photo (verified).

## IP trust (current Cloudflare tunnel)
`.env` sets `TRUST_CLOUDFLARE_HEADERS=true`. Trust assumption: the origin is reachable
ONLY via the cloudflared tunnel, which overwrites `CF-Connecting-IP`, so direct-internet
clients cannot spoof it. Defaults are `false`; IP is used for analytics only, never auth.

## Admin endpoints (require_trusted_admin)
- `GET /api/admin/dashboard-v2` → total_users, active_today/7d/30d, new_today/7d,
  logins_today, generations_today/total, tokens_spent_total, users_by_provider,
  users_by_platform, sessions_active, failed_logins_24h, banned_users.
- `GET /api/admin/users-analytics-v2?q&provider&status&limit&offset` → per user:
  public_user_code, display_name, primary_provider, providers[], masked email, username,
  phone, first/last seen, last_login, last_platform, last_ip, last_device, country/city,
  device_count, active_sessions_count, generations_count, tokens_spent, token_balance,
  status, role, and `internal_user_id_short` (collapsed, not a full id).
- `GET /api/admin/users/{internal_user_id}/analytics-v2` → summary + identities +
  sessions + devices + recent events + recent security events + token summary + admin
  actions. No hashes / raw tokens / full raw_profile_json.
- `/api/me-v2` profile now includes `display_name` (priority helper), `public_user_code`,
  `username`, `email`, `providers[]`.

## Frontend
- `src/adminAnalytics.tsx` (`AdminAnalyticsV2`): cookie-auth panel mounted in AdminView —
  dashboard cards + a clean user table (display_name + public_user_code, Web/TG/MAX
  badges, contacts, activity, balance, status). Technical id only as a short collapsed
  value. No `X-OneNode-User`, no token storage.
- Settings/account (`AuthV2Panel` authed view) shows display_name, **Код аккаунта**
  (public_user_code), email and provider badges — not a raw internal_user_id.

## Tests
- `test_admin_analytics.py` (10): code assigned/stable/unique/prefixed, display_name
  priority, login updates session/platform/last_seen, get_client_ip trust, dashboard
  admin-gated + counts, list hides hashes + clean ids, detail safe, provider profile
  fields captured, users.id unchanged.
- Full regression: **256 passed** (incl. password/cookie/generation/ownership/lifecycle/
  admin-reset/trusted-user/account/identity/telegram/max/email). `test_api.py` not run.
- Frontend: tsc 0, vite 0, smokes auth-v2 / auth-modal / generation-lock / admin-analytics OK.

## Live verification
Backend build `18-2026-06-26`; dashboard-v2/users-analytics-v2 no-session → 401;
register → 200, `/api/me-v2` profile carries `WEB-…` public_user_code + display_name;
frontend dist `index-CM7kVulk.js`; generate no-session → 401.

## Remaining gaps
- Country/city: only shown if already stored on the user; no IP→geo lookup implemented.
- Phone: shown if present; no phone capture/verification (deferred).
- MAX mobile launch is a separate infra/platform issue (Phase 17 / 17.1), not addressed here.
