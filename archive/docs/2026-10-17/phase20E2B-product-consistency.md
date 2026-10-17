# Phase 20E.2B Product Consistency + Live Bugfix Gate

Verdict: PARTIAL.

Code fixes and local verification are complete. Live browser verification is blocked by Browser Use enterprise policy for `https://izo.alikinas.ru`, so this phase is not live-accepted yet.

## Plan / Tariff Source Of Truth

Canonical field: `users.plan`.

Endpoints and reads:
- `POST /api/admin/users/{internal_user_id}/plan-v2` writes `users.plan` and derives `users.gallery_enabled`.
- password, Telegram, MAX, and legacy admin-created users default to `mini`.
- Users CRM table/card now read `plan` from `admin_user_analytics_row()`.

Root cause fixed:
- CRM analytics did not return `plan`, so frontend fell back to `free`.
- This made changed tariffs, including admin self-tariff changes, appear as `free` in Users CRM.

No mass backfill was performed. Existing inconsistent users are not silently changed.

## Gallery Access

Product rule implemented:
- admin: gallery access yes;
- `mini`, `plus`, `pro`: gallery access yes when `gallery_enabled = 1`;
- `free`: gallery access no.

Backend now enforces this rule on gallery read/detail/favorite/delete/use-as/send endpoints. CRM exposes `gallery_access` for table/card display.

## Gallery Disappearing Root Cause

Actual deletion risk found:
- `DELETE /api/gallery/{image_id}` physically deleted the `images` DB row.
- This made images disappear permanently from DB-backed gallery/history.

Fix:
- additive `images.deleted_at` column;
- delete endpoint now soft-deletes by setting `deleted_at`;
- gallery loads only non-deleted rows;
- DB row remains for audit/history.

No gallery rewrite was done.

## Bonus UX

Clarified workflow:
- token adjustment: direct admin correction;
- bonus: loyalty/compensation grant with `bonus_grants` + `token_ledger`;
- promo: code redemption;
- referral: referral reward/correction.

CRM changes:
- button renamed to `Бонус / компенсация`;
- modal includes bonus type: `manual`, `compensation`, `campaign`, `referral`;
- token amount and reason are required;
- loyalty tab shows bonus/promo/referral rows;
- cancel bonus remains available when safe.

## User Lifecycle

Hard delete remains deferred.

Safe action exposed:
- `Деактивировать` uses trusted `block-v2`;
- user cannot continue with existing session because sessions are revoked;
- data remains for audit/billing/history;
- reason required and audit/security logs are written.

Anonymization remains deferred.

## Verification

Passed:
- `python -m pytest -q backend/test_product_consistency_20e2b.py backend/test_promo_bonus_referral_v2.py backend/test_billing_v2.py backend/test_admin_analytics.py backend/test_admin_actions.py backend/test_auth_sessions.py backend/test_password_auth.py`
- `npx tsc -b`
- `npx vite build`
- `node smoke-admin-analytics.mjs`
- `node smoke-auth-v2.mjs`
- `node smoke-auth-modal.mjs`
- `node smoke-generation-lock.mjs`
- `node visual-crm-shots.mjs`

Live browser:
- blocked by Browser Use enterprise policy for `https://izo.alikinas.ru`;
- diagnostics/admin session/real user mutation were not live verified.

## Confirmations

- No destructive DB migration.
- No `users.id` changes.
- No fake data.
- No owner/admin account touched.
- No raw secrets/hashes/tokens/cookies/initData/WebAppData exposed.
- Visual blueprint remains binding.
