# Phase 20E.1 Billing Foundation (historical checkpoint)

> Current payment contracts, simulator and production gate are documented in
> `billing-readiness-20260716.md`. This file preserves the initial milestone and
> is not the source of current readiness status.

Verdict: CRM DATA/BILLING P0 READY.

## Scope

Implemented the first trusted-admin billing foundation for Users CRM without redesigning the accepted CRM layout.

Added additive SQLite schema:
- `billing_packages`
- `invoices`
- `invoice_items`
- `payments`
- `refunds`

Added trusted admin endpoints:
- `GET /api/admin/users/{internal_user_id}/billing-v2`
- `POST /api/admin/users/{internal_user_id}/invoices-v2`
- `POST /api/admin/invoices/{invoice_id}/mark-paid-v2`
- `POST /api/admin/invoices/{invoice_id}/cancel-v2`
- `POST /api/admin/payments/{payment_id}/refund-v2`

Extended `GET /api/admin/users/{internal_user_id}/analytics-v2` with:
- `billing_summary`
- `invoices_recent`
- `payments_recent`
- `refunds_recent`

## Safety Rules

- Trusted cookie admin session is required.
- No `X-OneNode-User`.
- No raw hashes, tokens, cookies, initData/WebAppData, provider payloads, or webhook payloads in responses.
- No `users.id` changes.
- No auth, generation, gallery, or identity rewrite.
- Manual payment is only a recorded admin action; there is no payment provider integration.
- Payment token grants write `token_ledger` first and update balance in the same transaction.
- Duplicate manual payment with the same idempotency key returns the existing payment and does not grant tokens again.
- Refunds record the manual refund only. Token reversal is explicitly deferred and surfaced as `token_reversal_policy: "deferred"`.

## Frontend Wiring

Existing CRM card finance surfaces now render real billing fields:
- billing summary;
- recent invoices;
- recent payments;
- recent refunds;
- token ledger remains visible.

Right action panel now supports:
- `Выставить счёт`;
- `Отметить оплату` for an unpaid invoice;
- `Возврат` for paid/partially refunded payment;
- `Отменить счёт` for an unpaid invoice.

All billing confirmations show target user, action, amount/value, mandatory reason, and audit notice. Dangerous actions use the existing danger confirm styling.

## Deferred

- Payment provider/webhook integration.
- External refund execution.
- Token reversal ledger for refunds.
- Billing package management UI.
- Promos, bonuses, referrals, marketing modules, advanced timeline.

## Verification

Passed:
- `python -m pytest -q backend/test_billing_v2.py backend/test_admin_analytics.py backend/test_admin_actions.py`
- `npx tsc -b`
- `npx vite build`
- `node smoke-admin-analytics.mjs`
- `node smoke-auth-v2.mjs`
- `node smoke-auth-modal.mjs`
- `node smoke-generation-lock.mjs`
- `node visual-crm-shots.mjs`
