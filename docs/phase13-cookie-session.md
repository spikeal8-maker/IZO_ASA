# Phase 13 — HttpOnly Trusted-Session Cookies

Login now delivers the trusted session via HttpOnly cookies so it survives a page
reload without putting any token in localStorage/sessionStorage. The DB still
stores only token hashes; cookies are just secure transport for the raw tokens.

## Backend

### Config (env-overridable)
- `TRUSTED_SESSION_COOKIE_NAME` (default `onenode_session`)
- `TRUSTED_REFRESH_COOKIE_NAME` (default `onenode_refresh`)
- `TRUSTED_COOKIE_SECURE` (default `true` when `APP_ENV=production`, else `false`)
- `TRUSTED_COOKIE_SAMESITE` (default `lax`)
- `TRUSTED_COOKIE_DOMAIN` (optional)
- `TRUSTED_COOKIE_PATH` (default `/`)
- HttpOnly is always `True`.
- `SESSION_COOKIE_NAME = TRUSTED_SESSION_COOKIE_NAME` so the existing resolver
  keeps reading the same cookie.

### Helpers
- `set_trusted_auth_cookies(response, session_token, refresh_token, expires_at, refresh_expires_at)`
  — sets session cookie (max_age = access TTL) and refresh cookie (max_age = refresh
  TTL), both HttpOnly + secure/samesite/path/domain from config. Raw values never logged.
- `clear_trusted_auth_cookies(response)` — deletes both cookies (logout).
- `_extract_refresh_token(request)` — reads the refresh cookie.

### Endpoints updated
- `POST /api/auth/telegram-v2`, `POST /api/auth/max-v2`, `POST /api/auth/email/verify-code-v2`
  — on success call `set_trusted_auth_cookies(...)`. Tokens remain in the JSON body
  for backward compat (the Phase 13 frontend ignores them; a later phase may remove them).
- `POST /api/auth/session/refresh-v2` — uses body `refresh_token` if present, else the
  refresh cookie; rotates tokens; sets fresh cookies. The old refresh token is revoked
  by rotation, so the old refresh cookie can no longer be used.
- `POST /api/auth/session/logout-v2` — uses body `session_token` if present, else the
  session cookie; revokes the session if found; always clears both cookies and returns
  `{ok:true}` (idempotent, never reveals whether a session existed).
- `resolve_auth_session_from_request` — unchanged: Bearer first, else the trusted
  session cookie; never trusts `onenode_user`.

### Not changed
`request_user_id()`, `require_admin()`, legacy endpoints, generation/gallery/templates,
`users.id`, jobs/images/token_ledger. CORS left as-is (same-origin deployment needs
none); not broadened.

## Frontend (src/authV2.tsx)
- All v2 calls use `credentials: 'include'`; the browser attaches the HttpOnly cookies.
- No session/refresh token is read, stored, or kept in JS — cookie-only. Login success
  is based on `res.ok`; JSON tokens are ignored.
- Startup: `bootstrapV2()` then `GET /api/me-v2` to restore the session after reload;
  on 401 it tries a cookie refresh (`POST /api/auth/session/refresh-v2`, empty body)
  then retries `/me-v2` once (Option A); otherwise attempts a silent Telegram/MAX login.
- Logout: `POST /api/auth/session/logout-v2` (empty body, credentials include); backend
  clears the cookies. `installation_id`/`anonymous_id` are retained.
- No `X-OneNode-User`; legacy `onenode_user` never used as auth.

## Tests
- Backend isolated (`test_cookie_session.py`, 13): cookies set by all 3 logins; HttpOnly;
  Secure in production config; SameSite=lax; session max_age≈access TTL, refresh
  max_age≈refresh TTL; refresh via cookie when body missing; rotation; old refresh
  cookie unusable; logout clears cookies + works via cookie; resolver accepts cookie;
  resolver ignores `onenode_user`; raw tokens not stored; tokens/cookies not in logs.
- Frontend static smoke (`smoke-auth-v2.mjs`): credentials:include, no token storage,
  no in-JS token var, login ignores JSON tokens, me-v2 restore, logout-v2, no X-OneNode-User.
- Commands: `pytest test_cookie_session.py` (+ full suite 214 passed), `node smoke-auth-v2.mjs`,
  `npx tsc -b`, `npx vite build` — all green.

## Live/manual checklist
1. Open https://izo.alikinas.ru. 2. Login via available provider. 3. Application →
Cookies: `onenode_session` + `onenode_refresh` present with HttpOnly. 4. localStorage/
sessionStorage: no tokens. 5. Reload → still authenticated (me-v2 restores). 6. Logout →
cookies cleared. 7. Reload after logout → unauthenticated.

Note: on the dev tunnel `TRUSTED_COOKIE_SECURE` defaults to false (APP_ENV not
production). Over HTTPS you may set `TRUSTED_COOKIE_SECURE=true` for Secure cookies.
