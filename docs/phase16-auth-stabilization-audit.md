# Phase 16.4 — Auth / Lifecycle Stabilization Audit

Audit of password login, lifecycle, admin password reset, generation protection and
ownership protection. No new features. No secrets printed.

## Verdict: STABLE WITH MINOR FIXES
Code is correct and fully green in tests + live. One operational issue found and
fixed: the **live backend was stale** (running an older build without generation/
ownership protection or admin password-reset) — restarted to load current code.

## Block 1 — Touched areas
- Password endpoints present: `POST /api/auth/password/register-v2`, `.../login-v2`.
- Admin reset present: `POST /api/admin/users/{internal_user_id}/password-reset-v2`.
- Protected: `generate`, `gallery`, `gallery/{id}`, `jobs/{id}` (+cancel) call
  `require_trusted_user`; per-resource ownership enforced (non-owner → 404, no leak).
- `request_user_id()` unchanged (legacy header/cookie, returns demo_user); protected
  endpoints do NOT use it.
- Frontend: `AuthV2Panel` (OTP, authed Settings) and `AuthV2Modal` (password Вход/
  Регистрация tabs) are both self-consistent; tsc clean, no dangling vars.

## Block 2 — Local regression
- `test_password_auth.py + test_lifecycle.py + test_admin_password_reset.py +
  test_generation_protection.py + test_ownership_protection.py + test_cookie_session.py +
  test_trusted_user_v2.py + test_password_schema.py` → **121 passed**.
- `npx tsc -b` → 0 · `npx vite build` → 0.
- `smoke-auth-v2` / `smoke-auth-modal` / `smoke-generation-lock` → OK.
- `test_api.py` not run. Working DB hash drift is the live server's own traffic (tests
  use temp DB via monkeypatch).

## Block 3 — Live freshness (PRE-restart finding)
- Live had password endpoints (login-v2 → 401, register-v2 → 400) BUT
  `/api/generate` and `/api/gallery` returned **200 without a session**, and admin
  password-reset returned **404**. → live process was stale (started before the
  protection/reset changes). One backend on :8000.
- **Fix:** restarted the single backend (stop old PID, start one fresh detached
  process; mirrors start-project.bat). Post-restart re-probe: generate→401, gallery→401,
  admin password-reset→401, me-v2→401. Protection now live.

## Block 4 — Live auth smoke (disposable email; no password/cookie printed)
| check | result |
|-------|--------|
| register email+password | 200, Set-Cookie yes |
| /api/me-v2 after register | 200 |
| reload (me-v2 again) | 200 |
| logout | 200, cookies cleared |
| /api/me-v2 after logout | 401 |
| login same email+password | 200 |
| wrong password | 401 generic |
| unknown email | 401 generic (identical detail) |

## Block 5 — Admin password reset
- **Live: BLOCKED — no admin session available** (no admin web_email password to log in
  with; granting admin would be an out-of-scope mutation; auth not bypassed).
- **Verified by isolated tests** (`test_admin_password_reset.py`, included in the 121
  passing): reset rotates password, old password → 401, new → 200, old sessions revoked,
  audit/security/event logs written, no raw password/hash stored.

## Block 6 — Safe-disable / lifecycle
- **Live: BLOCKED — same admin-session blocker** (disable/unblock are admin mutations).
- **Verified by isolated tests** (`test_lifecycle.py`): disabled user login → 403 safe,
  re-register same email → 409 generic, no orphan inconsistency, unblock/reset restores
  login.

## Block 7 — Protected endpoints (live, valid session)
- No session: generate / gallery / jobs → 401. ✓
- Valid session: `/api/gallery` → 200, returns a list scoped to the user (new user). ✓
- `X-OneNode-User: admin` spoof with a valid cookie session → identity unchanged
  (me-v2 still the registered user). ✓

## Bugs found
- None in code. One deployment issue: stale live backend (generation/gallery
  unprotected live, admin reset missing) — fixed by restart.

## Fixes made
- Restarted the live backend to load current code (operational; no code change).
- No source files changed during this audit.

## Remaining risks
- Admin-session-dependent live flows (reset, disable/unblock) verified only by isolated
  tests; live confirmation needs an admin login (a real admin password or a controlled
  admin session).
- The live test account (`audit_p16_*@example.com`) remains as a normal disabled-session
  row (logged out) — non-destructive disposable account.
- No `--reload` on uvicorn → future code changes need a manual restart to go live.

## Confirmations
- no raw password / password_hash / cookie / session/refresh token printed
- no destructive DB operation; no users.id change
- no new feature phase started
