# Phase 13.3 — Restart + Controlled Live Cookie Login Verification

Verification phase. No generation/gallery/templates/preview/editor changes. No raw
cookies/tokens/secrets logged.

## Block 1 — Restart readiness & restart
- Live backend launch method (from `start-project.bat`): a single detached window
  running `python -m uvicorn main:app --host 127.0.0.1 --port 8000`.
- Before: one uvicorn (PID 24828). Frontend = `vite` dev on :5173. Tunnel = cloudflared.
- Restart performed the launcher's way: freed port 8000 (stopped the single old
  uvicorn), then started one fresh detached uvicorn window. **No second overlapping
  backend created.**
- After: port 8000 owned by exactly one python.exe (the new backend). The extra
  PowerShell host windows that still contain the uvicorn command string are stale/
  harmless, not backends.
- Restart: **DONE.**

## Block 2 — Effective config after restart (no secrets)
Values the restarted process loads from `.env` (verified to load correctly; not
introspected from the live process beyond behavior):

| key | value |
|-----|-------|
| APP_ENV | development |
| TRUSTED_COOKIE_SECURE | true |
| TRUSTED_COOKIE_SAMESITE | lax |
| TRUSTED_COOKIE_PATH | / |
| TRUSTED_COOKIE_DOMAIN | null |
| SESSION_HMAC_SECRET configured | yes |
| EMAIL_OTP_DEBUG_RETURN_CODE | false |
| CORS_ALLOWED_ORIGINS | https://izo.alikinas.ru, http://localhost:5173, http://127.0.0.1:5173 |
| allow_credentials | True |

## Block 3 — Safe live baseline
- Live tunnel: `GET /api/me-v2` (no cookies) → **401**; `POST /api/auth/bootstrap-v2` → **200**.
- Direct `127.0.0.1:8000`: same (401 / 200); bootstrap returns the expected shape,
  `auth_methods: ["email_otp"]`.
- localStorage check (installation_id/anonymous_id only, no tokens) → pending manual
  DevTools; frontend code stores no tokens (static smoke proven).

## Block 4 — Controlled login path decision
- Option A (Telegram real Mini App): unavailable here.
- Option B (MAX real Mini App): unavailable here.
- Option C (Email OTP with real provider): unavailable (`EMAIL_PROVIDER` not set).
- Option D (temporary `EMAIL_OTP_DEBUG_RETURN_CODE=true`): the only feasible path.
  **STOPPED — awaiting explicit operator confirmation before enabling debug OTP.**
  Debug OTP was NOT enabled.

## Block 4 (resolved) — login method used
Operator confirmed Option D. `EMAIL_OTP_DEBUG_RETURN_CODE=true` was enabled
temporarily on this dev instance, one controlled email-OTP login was performed with
a single test address over the live HTTPS tunnel, then debug was reverted. No
debug_code / cookie values / tokens were printed.

## Blocks 5–8 — Cookie attributes / reload / refresh / logout — PASS
All observed over `https://izo.alikinas.ru` (names + attribute booleans only):

| check | result |
|-------|--------|
| Set-Cookie `onenode_session` present | yes |
| Set-Cookie `onenode_refresh` present | yes |
| both HttpOnly | yes |
| both Secure | yes |
| both SameSite=Lax | yes |
| both Path=/ | yes |
| both Max-Age present | yes |
| `GET /api/me-v2` after login | 200 |
| reload (`/api/me-v2` again) | 200 |
| `refresh-v2` (cookie, empty body) | 200, new Set-Cookie |
| `/api/me-v2` after refresh | 200 |
| old refresh token reuse after rotation | 401 |
| `logout-v2` (cookie) | 200, clears both cookies |
| `/api/me-v2` after logout | 401 |
| client used X-OneNode-User | no |

## Block 9 — Cleanup (done)
- `EMAIL_OTP_DEBUG_RETURN_CODE` reverted to **false**; server restarted.
- Effective config: debug **false** (request-code returns no debug_code).
- `GET /api/me-v2` (no cookies) → 401 on both tunnel and direct backend.
- Single backend process on :8000.

## Storage proof
Trusted cookies are HttpOnly (not in `document.cookie`); the frontend stores no
session/refresh token in localStorage/sessionStorage (static smoke-proven). Live
browser DevTools spot-check remains a manual confirmation but is not required for
the HTTP-level verification above.

## Blockers
None for cookie verification. (For ongoing real logins: a production email provider
or real Telegram/MAX Mini App environment is still needed; debug OTP is dev-only.)
