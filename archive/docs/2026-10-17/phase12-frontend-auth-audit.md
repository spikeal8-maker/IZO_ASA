# Phase 12.1 — Frontend Auth v2 Audit + Typecheck Cleanup

Read-only audit of the Phase 12 minimal frontend auth migration, plus removal of
pre-existing dead declarations so the frontend typecheck/build is clean. No
backend, DB, auth-flow, or generation/gallery/templates logic was changed.

## 1. Auth-v2 source audit (frontend/src/authV2.tsx)

| # | check | result |
|---|-------|--------|
| 1 | session_token stored in-memory only (`let sessionToken`) | PASS |
| 2 | refresh_token not retained at all | PASS |
| 3 | localStorage used only for installation_id / anonymous_id | PASS |
| 4 | no sessionStorage for tokens | PASS |
| 5 | v2 calls use `Authorization: Bearer` | PASS |
| 6 | v2 calls never set X-OneNode-User | PASS (only in comments) |
| 7 | v2 calls never read onenode_user | PASS (only in comments) |
| 8 | Telegram sends raw `Telegram.WebApp.initData` | PASS |
| 9 | Telegram never uses initDataUnsafe.user.id | PASS |
| 10 | MAX sends raw WebAppData/initData | PASS |
| 11 | MAX never sends userId as identity | PASS |
| 12 | Email OTP errors are generic (no existence disclosure) | PASS (user-facing strings generic) |
| 13 | debug_code shown only if backend returned it | PASS |
| 14 | logout calls /api/auth/session/logout-v2 and clears memory | PASS |

## 2. App.tsx integration audit

| # | check | result |
|---|-------|--------|
| 1 | startup calls `bootstrapV2()` | PASS |
| 2 | `<AuthV2Panel/>` mounted once, in Settings/Аккаунт card | PASS |
| 3 | generation/gallery/templates not changed | PASS (only dead-decl removal) |
| 4 | legacy apiFetch / X-OneNode-User kept for legacy endpoints | PASS (App.tsx:195) |
| 5 | v2 auth/account UI does not use legacy apiFetch | PASS |
| 6 | no mass rewrite of App.tsx | PASS (import + 1 startup line + 1 mount + dead-code removal) |

## 3. Typecheck / build

- `npx tsc -b` → exit 0 (clean)
- `npx vite build` → exit 0 (dist produced; only a chunk-size advisory)
- `node smoke-auth-v2.mjs` → OK, 34/34 checks passed

## 4. Storage / token static proof (grep over src/)

- Forbidden token storage `(local|session)Storage.setItem(...session_token|refresh_token...)`: **none**.
- `X-OneNode-User` / `onenode_user` in authV2.tsx: **comments only**, no code usage.
- Allowed: `onenode_installation_id`, `onenode_anonymous_id` in localStorage.
- Legacy `X-OneNode-User` real usage: only `src/App.tsx:195` (legacy `apiFetch`), retained for old endpoints.

## 5. Manual test checklist (https://izo.alikinas.ru)

1. Open the app.
2. Open Settings / Аккаунт.
3. Confirm AuthV2Panel is visible.
4. Network: `POST /api/auth/bootstrap-v2` fires on load.
5. localStorage: `onenode_installation_id` + `onenode_anonymous_id` present; **no** session_token / refresh_token.
6. Enter email → "Получить код" → `POST /api/auth/email/request-code-v2`.
7. Enter code → "Войти" → `POST /api/auth/email/verify-code-v2`.
8. After login → `GET /api/me-v2` returns the current user.
9. "Выйти" → `POST /api/auth/session/logout-v2`, panel returns to email state.
10. Reload → user is logged out again (memory-only token; expected).
11. Generation/gallery still render and work as before.
12. Inspect any v2 request → Authorization: Bearer present, **no** X-OneNode-User.

## 6. Fixes made

- Removed 3 authorized unused declarations: `DEFAULT_FACESWAP_PROMPT`,
  `previewAspectWidth`, `previewAspectHeight`.
- Cascade: removing the two aspect consts left `previewImageSize` (their only
  reader) and its image-onload `useEffect` orphaned and unused. That state+effect
  produced a value nothing rendered (the mobile preview JSX uses `previewSource`
  directly), so it was dead. Removed the orphaned state+effect to complete the
  cleanup. No rendered behavior changed.

## 7. Remaining risks

- Memory-only session: a page reload requires re-login (no HttpOnly trusted-session
  cookie yet). A later phase can add a secure cookie.
- Legacy `X-OneNode-User` / `onenode_user` remain for old generation/gallery/admin
  endpoints (not migrated this phase).
- Real DB migration still pending (run `init_db()` deliberately, ideally after
  moving the DB out of the Google Drive sync path).
- No generation lock / backend generation protection yet (out of scope this phase).
