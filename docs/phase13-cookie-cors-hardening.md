# Phase 13.2 — Cookie / CORS Live Hardening Config

Configuration-only security pass to prepare `https://izo.alikinas.ru` for a real
HttpOnly cookie-session test. No generation/gallery/templates/preview/editor or
auth-flow logic changed. No secrets are printed.

## Config before/after (no secrets)

| key | before | after |
|-----|--------|-------|
| APP_ENV | development | development (secure cookie forced ON manually) |
| TRUSTED_COOKIE_SECURE | false | **true** |
| TRUSTED_COOKIE_SAMESITE | lax | lax |
| TRUSTED_COOKIE_PATH | / | / |
| SESSION_HMAC_SECRET configured | no | **yes** (generated, not shown) |
| EMAIL_OTP_DEBUG_RETURN_CODE | false | false |

## CORS before/after

| aspect | before | after |
|--------|--------|-------|
| allow_origins | `["*"]` | env `CORS_ALLOWED_ORIGINS`, explicit list |
| allow_credentials | True | True |
| effective origins | wildcard | `https://izo.alikinas.ru`, `http://localhost:5173`, `http://127.0.0.1:5173` |
| wildcard + credentials | yes (unsafe) | **no** |

The CORS allowlist is read from `CORS_ALLOWED_ORIGINS` (comma-separated) with a
dev/tunnel fallback. `allow_credentials=True` is preserved so cookie auth works;
the wildcard origin is removed (invalid with credentials).

## Files changed
- `backend/main.py` — added `CORS_ALLOWED_ORIGINS` config; `allow_origins=["*"]` → `allow_origins=CORS_ALLOWED_ORIGINS`.
- `backend/.env` — appended hardening keys (see below).
- `docs/phase13-cookie-cors-hardening.md` — this file.

## Env changed (names only)
`TRUSTED_COOKIE_SECURE`, `TRUSTED_COOKIE_SAMESITE`, `TRUSTED_COOKIE_PATH`,
`CORS_ALLOWED_ORIGINS`, `SESSION_HMAC_SECRET` (strong random, value never printed).
APP_ENV left as `development`; secure cookie is enabled explicitly via
`TRUSTED_COOKIE_SECURE=true`.

## Restart
**PENDING (operator action).** The live server must be restarted to load the new
`.env`. The running process was NOT restarted automatically (unknown launch method;
avoid disrupting live users / spawning duplicates). After restart, confirm the
effective config matches the table above (without printing secrets).

## Local regression
- `pytest test_cookie_session.py` → 13 passed
- full isolated backend suite (11 files) → 214 passed
- `node smoke-auth-v2.mjs` → OK
- `npx tsc -b` → exit 0; `npx vite build` → exit 0

## Safe live check (pre-restart)
- `GET /api/me-v2` (no cookies) → 401 ✓
- CORS preflight from `https://evil.example` → no `Access-Control-Allow-Origin` ✓
- Login-cookie / Set-Cookie attribute test → PENDING (needs restart + a valid login).

## Remaining blockers
1. Live server restart required to apply the new config.
2. No real Telegram/MAX Mini App environment and no email provider ⇒ a valid live
   login still cannot be produced. To run the end-to-end cookie test on a dev/
   staging instance, temporarily set `EMAIL_OTP_DEBUG_RETURN_CODE=true` there (never
   in production) to obtain the OTP, complete email login, and inspect Set-Cookie.
3. (Optional) For production, set `APP_ENV=production` once an email provider exists.
