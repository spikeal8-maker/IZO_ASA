# Tariff and token contract

Status: contract retained for the two-balance tariff flow; original baseline 2026-07-17.

Documentation review 2026-10-17: actual accounting state, refunds and legacy
compatibility paths must be cross-checked with current `backend/app/billing/**`,
`backend/app/services/generation_accounting.py` when merged, the token ledger
and high-assurance race/idempotency tests. Draft PR #186 is **not** production
proof. This document does not permit balance migration or historical ledger
repair without separate owner-authorized scope.

## Two balances only

The product has exactly two spendable token balances:

1. Daily tariff allowance. It resets daily and is not carried forward.
2. Main balance (`users.token_balance`). Monthly tariff grants, purchased tokens,
   earned tokens, bonuses, compensations, and referrals all credit this balance.

The legacy `openrouter_monthly_tokens` and
`openrouter_monthly_tokens_used` fields are compatibility data only. They must
not be rendered or restored as a third wallet.

## Debit order

- Config UI/server generation spends the daily allowance first and then the
  main balance.
- OpenRouter/API generation spends the main balance only.
- A generation is rejected before submission if the applicable balances cannot
  cover its complete token price.
- A failed generation refunds the same split that was charged.

## Tariff lifecycle

- New accounts receive Mini for one month, then fall back to Free.
- Paid terms are available for 1, 3, 6, and 12 months.
- The monthly main-balance grant is credited at activation and at every monthly
  boundary inside a multi-month term.
- Extending the current tariff continues its monthly grant schedule and clears
  any previously scheduled downgrade.
- Upgrades activate immediately.
- Downgrades, including Free, activate when the current paid term expires.
- Downgrade and expiry never erase the main balance. The new tariff's model
  matrix only limits which models can spend it.
- Admin changes use an explicit duration. Durations below 30 days receive a
  prorated first monthly grant.

## Pricing and administration

- The tariff editor is the source of monthly prices and included daily/monthly
  tokens.
- Term discounts for 3, 6, and 12 months are stored separately in
  `admin_settings.tariff_terms`.
- The public tariff page, account checkout, billing package, invoice, and
  payment must use the same calculated term offer.
- Admin economics are planning estimates: total price, discount, included
  tokens, estimated cost, profit, and margin. Actual provider costs remain in
  generation analytics.
- `video_slots`, `image_model_count`, and `video_model_count` remain part of the
  tariff presentation. Model counts are calculated from the real access
  matrices and are not manually persisted totals.

## Release gate

Before release, run `tools/verify.ps1 -Mode Full`. Do not deploy if backend
tests, frontend type checks/build, lint, origin checks, or resilience checks
fail.
