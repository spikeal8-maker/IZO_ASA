# Phase 20E.2 Promo / Bonus / Referral Foundation

Verdict: PROMO BONUS REFERRAL READY.

## Scope

Implemented trusted-admin loyalty mechanics for Users CRM without redesigning the accepted table/card layout.

Added additive SQLite schema:
- `promo_redemptions`
- `bonus_grants`
- `referral_links`
- `referral_relations`
- `referral_rewards`

Added trusted admin endpoints:
- `GET /api/admin/users/{internal_user_id}/promos-v2`
- `POST /api/admin/users/{internal_user_id}/bonus-v2`
- `POST /api/admin/users/{internal_user_id}/bonus/{bonus_id}/cancel-v2`
- `POST /api/admin/users/{internal_user_id}/apply-promo-v2`
- `GET /api/admin/users/{internal_user_id}/referrals-v2`
- `POST /api/admin/users/{internal_user_id}/referral-reward-v2`

Extended `GET /api/admin/users/{internal_user_id}/analytics-v2` with:
- `loyalty_summary`
- `promo_redemptions_recent`
- `bonus_grants_recent`
- `referral_link`
- `referral_relations`
- `referral_rewards_recent`

## Token Ledger Safety

- Manual bonuses grant tokens through `token_ledger` with reason `bonus_grant`.
- Bonus cancellation creates a compensating negative `token_ledger` row with reason `bonus_cancel` only when the current balance can safely cover it.
- Promo token bonuses grant through `token_ledger` with reason `promo_redemption`.
- Referral rewards grant through `token_ledger` with reason `referral_reward`.
- Each token effect updates `users.token_balance` in the same transaction as the ledger row.
- Idempotency keys prevent duplicate bonus/promo/referral token grants.

## Frontend Wiring

Existing CRM card now renders:
- loyalty summary;
- promo redemption rows;
- bonus grant rows;
- referral relations;
- referral reward rows.

Right action panel now supports:
- `Применить промокод`;
- `Начислить бонус`;
- `Реферальная корректировка`;
- `Отменить бонус` when a granted bonus is cancellable.

All loyalty confirmations require a reason and show the existing audit notice. Bonus cancellation uses danger styling.

## Deferred

- Public/user-facing referral signup flow.
- Promo discount application to invoices.
- Money/discount referral rewards.
- Promo/bonus/referral management screens beyond per-user CRM actions.
- Automatic campaign attribution.

## Verification

Passed:
- `python -m pytest -q backend/test_promo_bonus_referral_v2.py backend/test_billing_v2.py backend/test_admin_analytics.py backend/test_admin_actions.py`
- `npx tsc -b`
- `npx vite build`
- `node smoke-admin-analytics.mjs`
- `node smoke-auth-v2.mjs`
- `node smoke-auth-modal.mjs`
- `node smoke-generation-lock.mjs`
- `node visual-crm-shots.mjs`
