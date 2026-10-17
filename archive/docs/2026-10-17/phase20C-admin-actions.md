# Phase 20C — Trusted Admin Actions in User Drawer

Risky per-user admin actions migrated from the legacy header-auth table into the user
drawer, on trusted cookie auth (`require_trusted_admin`), reason-gated + audited.
No DB/users.id/auth-login/generation/gallery changes.

## Block 1 — Audit
- Already trusted-v2: `block-v2`, `unblock-v2`, `password-reset-v2`.
- Missing → **added**: `role-v2`, `tokens-v2`, `plan-v2`, `profile-v2`.
- Columns used (existing): users.role/plan/token_balance/display_name/email/gallery_enabled,
  token_ledger (user_id=legacy id, delta, reason, meta_json).
- Legacy actions (Ред./Снять/Тариф/+50/−50/delete) still call legacy `apiFetch` →
  `X-OneNode-User`/`require_admin` (kept collapsed, stronger warning).

## Block 2 — Backend endpoints (require_trusted_admin, reason required, audit+security/event)
- `POST .../role-v2` `{role, reason}` — blocks self-demotion (403) and removing the last
  admin (403); updates users.role; `audit_logs:admin_change_role` + `security_events:admin_role_changed`.
- `POST .../tokens-v2` `{delta, reason}` — delta≠0, |delta|≤100000, balance can't go <0;
  updates users.token_balance + inserts `token_ledger` (reason='admin_adjust', meta=actor+reason);
  `audit_logs:admin_adjust_tokens` + `event_logs:admin_tokens_adjusted`; returns old/new/delta.
- `POST .../plan-v2` `{plan, reason}` — updates users.plan (+gallery_enabled); `audit_logs:admin_change_plan`.
- `POST .../profile-v2` `{display_name?, email?, reason}` — updates only display_name/email
  (protected fields like id/role untouched); `audit_logs:admin_update_user_profile`.
- Reused: `block-v2`/`unblock-v2`/`password-reset-v2`.

## Block 3 — Drawer UI («Админ-действия» tab)
Per-user buttons: Забанить/Разбанить, Сделать/Снять админа, Изменить токены (+50/−50
quick + free input), Изменить тариф (select), Изменить имя, Сбросить пароль. Each opens a
confirm form requiring a **reason** (+ extra input where relevant), shows loading +
success «Готово. Записано в журнал аудита.» / error, and on success re-fetches the drawer
and refreshes the CRM row (`onChanged`). All via cookie-auth `adminPost` (credentials:include).

## Block 4 — Safety
No raw ids as primary; no password/session hashes shown; admin-typed reset password is in
an `autoComplete="off"` field, **not stored** in localStorage/sessionStorage and not shown
back after submit; panel states «пишут запись в журнал аудита». No extra console logging.

## Block 5 — Legacy block
Kept collapsed behind the toggle; warning strengthened to «Эти действия устаревают.
Используйте карточку пользователя (Карточка → Админ-действия). Показывать только для
экстренных случаев.» Not deleted (live parity not yet proven without an admin session).

## Block 6-7 — Tests
- Backend `test_admin_actions.py`: role (401/403/change/self-demotion/last-admin/reason/
  logs), tokens (+/− balance+ledger, negative/zero/over-cap blocked, reason, logs), plan
  (change+audit), profile (display_name update, protected fields immutable, reason, audit),
  no hashes in responses, users.id unchanged. Full admin/auth regression: **146 passed**.
- Frontend smoke (`smoke-admin-analytics`): Админ-действия tab; calls role/tokens/plan/
  profile/block/unblock/password-reset-v2; cookie credentials; reason required; ban/role/
  token/reset controls; «журнал аудита»; password not persisted; no X-OneNode-User / hashes.

## Block 8 — Live
- backend restarted, build `20C-2026-06-26`; frontend dist `index-vTjS_bhe.js`.
- no-session `/api/generate`, `/api/gallery` → 401; all four new endpoints admin-gated
  (valid body, no session → 401; missing required field → 422, never executes).
- **Admin-action mutation (token +1/−1)**: not run live — no admin session available
  (no admin password; granting admin is out of scope and was not done). Fully covered by
  `test_admin_actions.py`. Endpoint existence + admin gating verified live.

## Deferred
Detailed token ledger view (23); plan enum if it grows; removing legacy block after live
parity with an admin session.

## Files changed
- `backend/main.py` (4 models + 4 endpoints; APP_BUILD 20C)
- `backend/test_admin_actions.py` (new)
- `frontend/src/adminAnalytics.tsx` (actions tab + adminPost)
- `frontend/src/App.tsx` (stronger legacy warning)
- `frontend/src/index.css` (actions styles)
- `frontend/smoke-admin-analytics.mjs` (actions smoke)
- `frontend/src/diag.tsx` (label 20C)
- `docs/phase20C-admin-actions.md`
