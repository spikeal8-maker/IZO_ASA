# Phase 13.1 — Live HttpOnly Cookie Session Verification

Verification of Phase 13 cookie sessions after the black-screen hotfix. No raw
cookie/token values are logged. No generation/gallery/templates/preview changes.

## Verdict
**COOKIE CODE OK BUT LIVE LOGIN NOT TESTABLE** — and specifically **NOT READY FOR
COOKIE LIVE TEST** until `TRUSTED_COOKIE_SECURE=true` on the HTTPS tunnel.

## Block 1 — Hotfix regression
- `previewAspectWidth` declared at App.tsx:992, `previewAspectHeight` at 993, used at 1105 (declared-before-use). ✓
- `npx tsc -b` → exit 0; `npx vite build` → exit 0; `node smoke-auth-v2.mjs` → OK.
- Black error screen resolved in the rebuilt bundle (local dist `index-upxTWJhp.js`).
  Live serving of the fresh dist is pending manual confirmation.

## Block 2 — Environment / config (no secrets)

| key | effective value |
|-----|-----------------|
| APP_ENV | development |
| TRUSTED_COOKIE_SECURE | **false** ⚠️ (blocker on HTTPS) |
| TRUSTED_COOKIE_SAMESITE | lax |
| TRUSTED_COOKIE_DOMAIN | null |
| TRUSTED_COOKIE_PATH | / |
| TRUSTED_SESSION_COOKIE_NAME | onenode_session |
| TRUSTED_REFRESH_COOKIE_NAME | onenode_refresh |
| SESSION_HMAC_SECRET configured | no |
| EMAIL_PROVIDER configured | no |
| EMAIL_OTP_DEBUG_RETURN_CODE | false |

Because `TRUSTED_COOKIE_SECURE=false` on an HTTPS tunnel, the live login-cookie test
is **not** performed (per phase rule). To unblock: set `TRUSTED_COOKIE_SECURE=true`
(or `APP_ENV=production`, which also flips the default) on the live server, and set
`SESSION_HMAC_SECRET` if running production.

## Block 3 — Local regression
- backend `pytest test_cookie_session.py` → 13 passed
- `node smoke-auth-v2.mjs` → OK
- `npx tsc -b` → exit 0
- `npx vite build` → exit 0

## Block 4 — Live route / cookie smoke
- `GET /api/me-v2` (no cookies) → **401** (correct gating). ✓
- Full login-cookie flow (Set-Cookie attributes, me-v2 200, reload, logout-clears):
  **PENDING / BLOCKED** — (a) secure=false blocker; (b) no real Telegram/MAX Mini App
  environment and no email provider, so a valid live login cannot be produced.

## Block 5 — Refresh rotation smoke
- **PENDING** — requires a valid login (unavailable live). Covered by isolated tests
  (refresh-via-cookie, rotation, old-cookie-invalid) → all pass.

## Block 6 — Browser storage check (manual)
Pending manual DevTools check on https://izo.alikinas.ru. Expected (by code):
- localStorage: `onenode_installation_id`, `onenode_anonymous_id` present; no tokens.
- sessionStorage: no tokens.
- `document.cookie`: trusted cookies are HttpOnly → not visible to JS.
- Network: v2 requests carry cookies automatically; no `X-OneNode-User`.

## Block 7 — CORS risk
- Current: `allow_origins=["*"]` with `allow_credentials=True`.
- Risk: wildcard origin + credentials is invalid for credentialed cross-origin
  requests (browsers reject `Access-Control-Allow-Origin: *` with credentials).
  Same-origin (izo.alikinas.ru serving both) is unaffected, so cookie auth works
  same-origin. Not fixed in this phase.
- Recommendation (Phase 13.2): explicit allowed origins, no wildcard-with-credentials,
  preserve same-origin behavior.

## Blockers
1. `TRUSTED_COOKIE_SECURE=false` on HTTPS → enable before live cookie test.
2. No real Telegram/MAX environment and no email provider → cannot produce a live login.
3. `SESSION_HMAC_SECRET` unset (fine for dev; required if APP_ENV=production).
4. CORS wildcard + credentials (same-origin OK; cross-origin would fail).

## Recommended next phase
**Phase 13.2 — cookie/CORS hardening** before any generation lock: set
`TRUSTED_COOKIE_SECURE=true`, set `SESSION_HMAC_SECRET`, and replace wildcard CORS
with explicit origins. Only after a real login becomes testable should Phase 14
(generation lock) proceed.
