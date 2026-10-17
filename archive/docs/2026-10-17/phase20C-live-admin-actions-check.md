# Phase 20C.1 — Live Admin Actions Parity Check

Verification/stabilization. No new features. Goal: confirm the trusted drawer admin
actions work live with a real admin session before the legacy block is removed.

## Verdict: BLOCKED — NO ADMIN SESSION
Everything that does not require an admin session is verified (preflight, negative
security, full test/build). The live browser **mutation** checks (Blocks 4–10) cannot run
because no admin session is available, and the phase rules forbid creating/promoting an
admin silently or resetting an existing admin's password without owner confirmation.

## Block 1 — Preflight (live) ✅
- backend build `20C-2026-06-26` · `/api/version` → 200.
- no-session: `/api/generate` → 401, `/api/gallery` → 401, `/api/admin/users-analytics-v2` → 401.
- frontend dist `index-vTjS_bhe.js` (20C) served; `@vite/client` absent (preview of dist, not dev).
- exactly one backend listener on :8000 (pid 33316).

## Block 2 — Admin session: NOT AVAILABLE
No admin credentials and no connected browser with an admin session. Not bypassed; no
admin created. Awaiting owner-provided admin login or an explicitly confirmed safe
recovery path.

## Blocks 3–10 — Live mutations: NOT RUN (blocked)
No disposable user created; no token/profile/plan/role/ban/password mutations performed
live. All of these flows are covered by isolated tests (see Block 12), which assert:
- tokens +/− adjust balance + write `token_ledger` + `audit_logs:admin_adjust_tokens` +
  `event_logs:admin_tokens_adjusted`; negative/zero/over-cap blocked.
- profile updates `display_name`/`email` only (id/role immutable) + `audit_logs:admin_update_user_profile`.
- plan updates `users.plan` (+gallery_enabled) + `audit_logs:admin_change_plan` (real field — see note).
- role promote/demote + `audit_logs:admin_change_role` + `security_events:admin_role_changed`;
  self-demotion and last-admin removal blocked.
- block/unblock + password-reset (existing trusted endpoints, separately tested).

Plan note: `plan-v2` is backed by the real `users.plan` column (+`gallery_enabled`), so it
is NOT a fake field; live restore-after-change is part of the pending live run.

## Block 11 — Negative security checks (live) ✅
- `tokens-v2` no-session (valid body) → 401.
- `X-OneNode-User: telegram_admin` spoof (no cookie) → 401 on `role-v2`, `block-v2`,
  `password-reset-v2`. Header spoof does NOT grant admin.
- Non-admin session → 403 covered by `test_admin_actions.test_role_requires_session_and_admin`.
- No `password_hash`/`session_token_hash`/`refresh_token_hash`/`code_hash` in any action
  response (covered by `test_admin_actions.test_no_hashes_in_responses`).

## Block 12 — Tests / build ✅
- Backend: `test_admin_actions` + `test_admin_password_reset` + `test_admin_v2` +
  `test_password_auth` + `test_lifecycle` → **67 passed**.
- Frontend: `tsc -b` 0 · `vite build` 0 · smokes admin-analytics / auth-v2 / auth-modal /
  generation-lock → OK.

## Fixes made
None — no bug found in the trusted admin actions.

## Remaining blocker
A real admin session (or an owner-confirmed safe recovery path) is required to execute the
live mutation parity run (Blocks 4–10). Until then those steps remain test-verified only.

## Confirmations
- no owner account harmed; no disposable user created (none left admin/banned).
- no balance drift (no +1/−1 performed live).
- no raw secrets/passwords printed.
- legacy block NOT removed.
- no new feature started.
