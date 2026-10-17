# Phase 12.2 — Live Auth Smoke Test

Read-only / safe smoke verification of the v2 login layer against the live tunnel
`https://izo.alikinas.ru` after the live server performed the additive `init_db()`
migration. No code, no destructive DB ops, no generation/gallery/templates touched.

## Block 1 — DB migration verification (read-only, mode=ro)

- Tables present: users, auth_identities, auth_sessions, device_installations,
  event_logs, security_events, audit_logs, user_consents, auth_otp_challenges — all ✓
- users columns: internal_user_id ✓, display_name ✓
- Counts: users=5, jobs=59, images=55, token_ledger=180, users_null_internal_user_id=0,
  auth_sessions=0, auth_identities=2
- users.id: legacy format preserved (demo_user, telegram_*, web_*); NOT replaced by UUID
- No UPDATE/DELETE/INSERT performed (opened with `?mode=ro`).

## Block 2 — Local build/smoke

- `npx tsc -b` → exit 0
- `npx vite build` → exit 0
- `node smoke-auth-v2.mjs` → OK, 34/34

## Block 3 — Live route availability

| endpoint | expected | actual |
|----------|----------|--------|
| GET /openapi.json | (record) | 200 (publicly reachable) |
| GET /docs | (record) | 200 (Swagger UI publicly reachable) |
| POST /api/auth/bootstrap-v2 | 200 | 200, `is_authenticated:false`, `auth_methods:["email_otp"]` |
| GET /api/me-v2 (no session) | 401 | 401 |
| GET /api/me/profile-v2 (no session) | 401 | 401 |
| GET /api/admin/users-v2 (no session) | 401 | 401 |

## Block 4 — Email OTP live status (single request, masked)

- `POST /api/auth/email/request-code-v2` for `s***@example.com` → 200
- Response keys: `challenge_id`, `expires_in_seconds` (300) — nothing else
- `debug_code` present: **No**
- Reveals email existence: **No**
- Blocker: no real email provider configured AND `debug_code` disabled on live ⇒ the
  OTP is generated/hashed and "sent" via the dev mock only, so the code is
  unreachable by a real user. Email OTP login **cannot complete** on live until a
  production email provider is wired (or debug_code is enabled in a dev/staging env).

## Block 5 — Browser manual checklist

| # | item | status |
|---|------|--------|
| 1 | App opens | PENDING (manual) |
| 2 | Settings / Аккаунт reachable | PENDING (manual) |
| 3 | AuthV2Panel visible | PENDING (manual) |
| 4 | Network: POST /api/auth/bootstrap-v2 | VERIFIED (200 via probe) |
| 5 | localStorage has only installation_id/anonymous_id, no tokens | VERIFIED in code (memory-only) + PENDING visual |
| 6 | Email OTP UI shows | PENDING (manual) |
| 7 | Telegram flow does not break web | PENDING (real TG env) |
| 8 | MAX flow does not break web | PENDING (real MAX env) |
| 9 | Logout UI present | PENDING (manual) |
| 10 | Legacy generation/gallery visually intact | PENDING (manual); legacy code unchanged |

## Block 6 — Current login-quality assessment

Working now:
- Anonymous bootstrap-v2 (issues installation_id/anonymous_id; not auth).
- Route authorization: all v2 protected endpoints return 401 without a session.
- Email request-code-v2 creates a hashed challenge with no existence disclosure.
- Backend identity/session machinery + additive DB migration complete and data-safe.

Not working end-to-end on live:
- Email OTP completion — no email provider + debug_code disabled ⇒ code unreachable.
- Telegram-v2 / MAX-v2 — require real Mini App environments (raw initData/WebAppData);
  not exercisable from plain web.
- Reload: session token is memory-only ⇒ reload requires re-login.

Needed for quality UX:
- HttpOnly trusted-session cookie (persist login across reload) + safe refresh flow.
- Production email provider for email OTP.
- Real Telegram Mini App and MAX Mini App environments.

## Block 7 — Next-step recommendation

**Option A — HttpOnly trusted-session cookie first.**
It is the cross-cutting enabler: today even a successful login is lost on reload
(memory-only token), which makes any feature built on top of auth fragile. A secure
HttpOnly cookie (+ refresh) makes sessions persist for ALL three providers and is a
natural continuation of the auth migration. Generation lock (B) and backend
generation protection (C) both depend on a reliable, persistent trusted session, so
A should land before them. Email provider is also required, but it is independent
and can proceed in parallel.

## Side effects created by this smoke (allowed app-level only)

- bootstrap-v2 inserted 1 device_installations row + 1 `app_opened` event.
- request-code-v2 inserted 1 auth_otp_challenges row (hashed code) + 1 `login_started` event.
No tokens logged; no destructive ops; no mass accounts; single OTP request only.
