---
status: canonical
document_role: admin-mutation-audit
scope: critical-compatibility-identity-crm-finance-v1
updated: 2026-10-18
verified_source_sha: 03a9d850601ef85b9be940283037c9e19d291255
production_status_role: none
---

# Admin mutation audit — critical compatibility routes

Назначение: дать coding-agent route-level evidence до изменения критичных
identity/CRM/finance mutations, которые пока остаются в `backend/main.py`.
Документ не утверждает, что вся админка прошла audit, и не разрешает live
payment, refund, mail или provider action.

## Итог

В bounded scope вошли 19 routes:

- 6 `verified`: текущие auth/reason/audit и test evidence достаточны для
  зафиксированного route contract;
- 7 `partial`: базовые controls присутствуют, но replay, concurrency или
  split-external boundary доказаны не полностью;
- 6 `gap`: повтор запроса может создать дополнительный финансовый либо
  entitlement effect.

Общий положительный инвариант: все 19 handlers вызывают
`require_trusted_admin` и пишут `record_audit_log` внутри текущего evidence
scope. Для 16 routes непустая причина подтверждена; три payment-maintenance
routes принимают строку из одних пробелов и отмечены `AM-008`.
Route-level `source_fingerprint` охватывает decorator и полное тело handler;
изменение audited source без обновления evidence останавливает contract test.
Полные fingerprints `backend/main.py`, route map и всех заявленных test-файлов
дополнительно связывают выводы с общими helper/model dependencies и test
evidence, а не только с телами handlers.

Критические gaps:

1. `tokens-v2` повторно применяет относительный `delta`.
2. `plan-v2` на каждый вызов создаёт новый `source_id`, grant key и может снова
   начислить тарифные токены.
3. `invoices-v2` не имеет command/idempotency key и создаёт новый счёт при
   повторе.
4. Несколько финансовых routes принимают optional idempotency key, но при его
   отсутствии `_billing_idempotency` генерирует новый случайный ключ. Это не
   защищает retry после потерянного ответа.
5. Maintenance/payment-notification routes имеют split DB/provider boundary;
   существующие tests не закрывают весь replay/concurrency/live-provider риск,
   а live-capable reconcile/email execution не имеет отдельного operator
   authorization + redacted receipt control поверх trusted-admin.
6. Три maintenance routes принимают whitespace-only `reason`, который после
   `.strip()` превращается в пустую строку audit record.
7. `role-v2` проверяет last-admin invariant только последовательно; гонка двух
   администраторов не охарактеризована.
8. `bonus/{bonus_id}/cancel-v2` допускает concurrent double-debit до появления
   conditional status/transaction guard.
9. Все три maintenance routes пишут итоговый audit после части уже выполненных
   effects: simulate — после payment/invoice/token commit, reconcile — после
   payment/token commit, notification processing — после send и sent/retry
   state. У них нет общего durable pre-action audit/command boundary.

`verified` означает только перечисленные controls и tests на закреплённом source
SHA. Это не `DEPLOYED` и не `OPERATIONALLY VERIFIED`.

## Как использовать перед изменением

1. Найти exact method/path в JSON-контракте ниже.
2. Открыть только указанный `symbol` и `test_nodes`; проверить, что
   `source_fingerprint` остаётся актуальным.
3. Если `status` не `verified`, включить все `gap_ids` в Task Contract.
4. До изменения behavior добавить characterization failing-before/fixed-after.
5. Для money/token/entitlement/concurrency test повторить exact race/idempotency
   node пять раз на temporary DB.
6. Live provider, mail, payment или refund проверять только отдельным
   owner-authorized release-ops package.

## Machine-readable contract

<!-- admin-mutation-audit-json:start -->
```json
{
  "version": 1,
  "source_sha": "03a9d850601ef85b9be940283037c9e19d291255",
  "source_fingerprint_algorithm": "sha256-decorated-source-v1",
  "evidence_artifact_algorithm": "sha256-normalized-text-v1",
  "evidence_artifacts": [
    {"path": "backend/main.py", "fingerprint": "sha256:8a7b745accd3a10d070bdfeb7eb05da633fcccb415bc9af169c1e591054edd44"},
    {"path": "backend/SYMBOL_MAP.md", "fingerprint": "sha256:25f3e7ea80696a8efead3797f7f67c91d36ceb9ac458f4d3cb951510e2bc2de3"},
    {"path": "backend/test_admin_v2.py", "fingerprint": "sha256:95662d4a3f7ffc28b93bf215b0b53bde276fee4d635decb5b18fd366e88481b2"},
    {"path": "backend/test_admin_password_reset.py", "fingerprint": "sha256:42625c68b02dc766e87f50b5d063ce51c5d41afac781268e8e566c225e9f8145"},
    {"path": "backend/test_admin_actions.py", "fingerprint": "sha256:6379e9bd7ed0c5788e830b56c1d2ba1d2707361e934ba74a62cedd48dd2f5912"},
    {"path": "backend/test_product_consistency_20e2b.py", "fingerprint": "sha256:1d237962b0a3c458361fb7206db2f09c4a2e946563cd33602c20762d498f524a"},
    {"path": "backend/test_billing_simulator_checkout_v2.py", "fingerprint": "sha256:da7881cbf71550d1de001e2aaba3816e239a05f768b9a1a8649756989fdd9946"},
    {"path": "backend/test_billing_notification_outbox.py", "fingerprint": "sha256:67b59933da8c78268b237434a870e98960b5919a34a00c0fe27b3bde5175ac4d"},
    {"path": "backend/test_billing_v2.py", "fingerprint": "sha256:92c0403dd590b87895802e540cf26b98a09d8fdb04a8298b78c9a561a62f9fc3"},
    {"path": "backend/test_promo_bonus_referral_v2.py", "fingerprint": "sha256:0d03133b66880f19b0a197ce6b88afedb6df8d3a8398132917f8cf924d575796"}
  ],
  "scope": "critical-compatibility-identity-crm-finance-v1",
  "summary": {"verified": 6, "partial": 7, "gap": 6},
  "routes": [
    {
      "method": "POST",
      "path": "/api/admin/users/{internal_user_id}/block-v2",
      "symbol": "admin_block_user_v2",
      "source_fingerprint": "sha256:2a5a7899e06336a3a633dd92626e39213ce1ee8310325a4c40e92b1070757a0f",
      "risk": "security",
      "auth": "verified",
      "reason": "verified",
      "audit": "verified",
      "transaction": "atomic-local",
      "replay": "effect-stable",
      "test_evidence": "verified",
      "status": "verified",
      "test_nodes": ["backend/test_admin_v2.py::test_block_requires_reason", "backend/test_admin_v2.py::test_block_sets_banned_revokes_sessions_and_logs"],
      "gap_ids": []
    },
    {
      "method": "POST",
      "path": "/api/admin/users/{internal_user_id}/unblock-v2",
      "symbol": "admin_unblock_user_v2",
      "source_fingerprint": "sha256:27029fe0ae6d7f153e29ef9f10fe0ef2279f07dc80cb44213481ee521b7cac7f",
      "risk": "security",
      "auth": "verified",
      "reason": "verified",
      "audit": "verified",
      "transaction": "atomic-local",
      "replay": "effect-stable",
      "test_evidence": "verified",
      "status": "verified",
      "test_nodes": ["backend/test_admin_v2.py::test_unblock_flow"],
      "gap_ids": []
    },
    {
      "method": "POST",
      "path": "/api/admin/users/{internal_user_id}/password-reset-v2",
      "symbol": "admin_password_reset_v2",
      "source_fingerprint": "sha256:d374a466ec59a9f7ab14245723a661918e6c95cb965307853d799b16ad6d40a6",
      "risk": "security",
      "auth": "verified",
      "reason": "verified",
      "audit": "verified",
      "transaction": "atomic-local",
      "replay": "security-effect-repeatable",
      "test_evidence": "verified",
      "status": "verified",
      "test_nodes": ["backend/test_admin_password_reset.py::test_no_session_401", "backend/test_admin_password_reset.py::test_non_admin_403", "backend/test_admin_password_reset.py::test_reason_required", "backend/test_admin_password_reset.py::test_audit_logs_written", "backend/test_admin_password_reset.py::test_no_raw_password_in_logs"],
      "gap_ids": []
    },
    {
      "method": "POST",
      "path": "/api/admin/users/{internal_user_id}/role-v2",
      "symbol": "admin_role_v2",
      "source_fingerprint": "sha256:0e40c5d7e5d524e05e941126f77b61529a52c5a79d6a1b93d03dc8915a4ee9d5",
      "risk": "security",
      "auth": "verified",
      "reason": "verified",
      "audit": "verified",
      "transaction": "atomic-local",
      "replay": "last-admin-race-uncharacterized",
      "test_evidence": "partial-sequential",
      "status": "partial",
      "test_nodes": ["backend/test_admin_actions.py::test_role_requires_session_and_admin", "backend/test_admin_actions.py::test_role_change_and_logs", "backend/test_admin_actions.py::test_self_demotion_and_last_admin_blocked"],
      "gap_ids": ["AM-009"]
    },
    {
      "method": "POST",
      "path": "/api/admin/users/{internal_user_id}/tokens-v2",
      "symbol": "admin_tokens_v2",
      "source_fingerprint": "sha256:7486787280ee31163cf378da70292bbc59e1703beca900ef0d8dce88bcec1668",
      "risk": "financial-entitlement",
      "auth": "verified",
      "reason": "verified",
      "audit": "verified",
      "transaction": "atomic-local",
      "replay": "gap",
      "test_evidence": "partial",
      "status": "gap",
      "test_nodes": ["backend/test_admin_actions.py::test_token_adjust_and_logs", "backend/test_admin_actions.py::test_token_negative_and_zero_blocked"],
      "gap_ids": ["AM-001", "AM-006"]
    },
    {
      "method": "POST",
      "path": "/api/admin/users/{internal_user_id}/discount-v2",
      "symbol": "admin_discount_v2",
      "source_fingerprint": "sha256:ce27a772d2f7b97e0e488bb8f4bc9fe6af9ec96c0c9ab67d6dd46b190c517cd5",
      "risk": "pricing",
      "auth": "verified",
      "reason": "verified",
      "audit": "verified",
      "transaction": "atomic-local",
      "replay": "effect-stable",
      "test_evidence": "verified",
      "status": "verified",
      "test_nodes": ["backend/test_admin_actions.py::test_personal_discount_change_is_persisted_and_audited"],
      "gap_ids": []
    },
    {
      "method": "POST",
      "path": "/api/admin/users/{internal_user_id}/plan-v2",
      "symbol": "admin_plan_v2",
      "source_fingerprint": "sha256:92f072d146e6284c76c7281436de6c3e99a8051c22098caf614631f3f9aae919",
      "risk": "financial-entitlement",
      "auth": "verified",
      "reason": "verified",
      "audit": "verified",
      "transaction": "atomic-local",
      "replay": "gap",
      "test_evidence": "partial",
      "status": "gap",
      "test_nodes": ["backend/test_admin_actions.py::test_plan_change_audit", "backend/test_product_consistency_20e2b.py::test_plan_v2_updates_canonical_field_and_analytics_reads_it"],
      "gap_ids": ["AM-002", "AM-006"]
    },
    {
      "method": "POST",
      "path": "/api/admin/users/{internal_user_id}/profile-v2",
      "symbol": "admin_profile_v2",
      "source_fingerprint": "sha256:f8deef3473fbc7ebec5241ad23b177a3a94872425f6020c0a3fbb3e07176a7a8",
      "risk": "identity-profile",
      "auth": "verified",
      "reason": "verified",
      "audit": "verified",
      "transaction": "atomic-local",
      "replay": "effect-stable",
      "test_evidence": "verified",
      "status": "verified",
      "test_nodes": ["backend/test_admin_actions.py::test_profile_update", "backend/test_admin_actions.py::test_no_hashes_in_responses"],
      "gap_ids": []
    },
    {
      "method": "POST",
      "path": "/api/admin/payments/{payment_id}/simulate-v2",
      "symbol": "admin_simulate_payment_v2",
      "source_fingerprint": "sha256:e2a26cae9f6026bb2e73a063f40bbfbe2348877b7306f4f3ead1ff2b7fa88877",
      "risk": "payment-state",
      "auth": "verified",
      "reason": "gap-whitespace-only-accepted",
      "audit": "partial-post-effect",
      "transaction": "split-provider-db",
      "replay": "effect-guarded-uncharacterized",
      "test_evidence": "partial",
      "status": "partial",
      "test_nodes": ["backend/test_billing_simulator_checkout_v2.py::test_simulator_checkout_success_is_end_to_end_and_idempotent", "backend/test_billing_simulator_checkout_v2.py::test_simulator_checkout_cancellation_updates_invoice"],
      "gap_ids": ["AM-005", "AM-006", "AM-008"]
    },
    {
      "method": "POST",
      "path": "/api/admin/payments/reconcile-v2",
      "symbol": "admin_reconcile_payments_v2",
      "source_fingerprint": "sha256:29aaa2a01569f9d622a8ac5de2aee16e67e91878f999e5228b1d13d8b732b552",
      "risk": "payment-provider",
      "auth": "verified",
      "reason": "gap-whitespace-only-accepted",
      "audit": "partial-post-effect",
      "transaction": "split-provider-db",
      "replay": "effect-guarded-uncharacterized",
      "test_evidence": "partial",
      "status": "partial",
      "test_nodes": ["backend/test_billing_simulator_checkout_v2.py::test_admin_reconciliation_finishes_pending_simulated_payment"],
      "gap_ids": ["AM-005", "AM-006", "AM-008"]
    },
    {
      "method": "POST",
      "path": "/api/admin/payments/notifications/process-v2",
      "symbol": "admin_process_payment_notifications_v2",
      "source_fingerprint": "sha256:b10f1e0aee5f13778fa6d81fd6acdac8543e059cf5bd18260dc6e108b012a2a2",
      "risk": "durable-external-delivery",
      "auth": "verified",
      "reason": "gap-whitespace-only-accepted",
      "audit": "partial-post-effect",
      "transaction": "split-provider-db",
      "replay": "at-least-once-window",
      "test_evidence": "partial",
      "status": "partial",
      "test_nodes": ["backend/test_billing_simulator_checkout_v2.py::test_simulator_checkout_success_is_end_to_end_and_idempotent", "backend/test_billing_notification_outbox.py::test_outbox_claim_prevents_duplicate_processing_and_recovers_expired_lease"],
      "gap_ids": ["AM-005", "AM-006", "AM-007", "AM-008"]
    },
    {
      "method": "POST",
      "path": "/api/admin/users/{internal_user_id}/invoices-v2",
      "symbol": "admin_create_invoice_v2",
      "source_fingerprint": "sha256:c68b0c79745c56545de0dd22a125e332bca08de38880c57d2df0bbf6ceb1c8b2",
      "risk": "financial",
      "auth": "verified",
      "reason": "verified",
      "audit": "verified",
      "transaction": "atomic-local",
      "replay": "gap",
      "test_evidence": "partial",
      "status": "gap",
      "test_nodes": ["backend/test_billing_v2.py::test_billing_requires_trusted_admin", "backend/test_billing_v2.py::test_create_invoice_writes_rows_audit_event_and_keeps_users_id"],
      "gap_ids": ["AM-003", "AM-006"]
    },
    {
      "method": "POST",
      "path": "/api/admin/invoices/{invoice_id}/mark-paid-v2",
      "symbol": "admin_mark_invoice_paid_v2",
      "source_fingerprint": "sha256:b20ae9635bb1132cde01e295307844cf8cfab8be35627d69896135356c64138b",
      "risk": "financial-entitlement",
      "auth": "verified",
      "reason": "verified",
      "audit": "verified",
      "transaction": "atomic-local",
      "replay": "partial-optional-key",
      "test_evidence": "verified-keyed",
      "status": "partial",
      "test_nodes": ["backend/test_billing_v2.py::test_mark_paid_grants_tokens_once_through_ledger"],
      "gap_ids": ["AM-004", "AM-006"]
    },
    {
      "method": "POST",
      "path": "/api/admin/invoices/{invoice_id}/cancel-v2",
      "symbol": "admin_cancel_invoice_v2",
      "source_fingerprint": "sha256:d5c178b85e300d16699df59afd8411eeae926c909de15ea961fbad3fa38202a2",
      "risk": "financial",
      "auth": "verified",
      "reason": "verified",
      "audit": "verified",
      "transaction": "atomic-local",
      "replay": "effect-stable",
      "test_evidence": "verified",
      "status": "verified",
      "test_nodes": ["backend/test_billing_v2.py::test_cancel_unpaid_and_cannot_cancel_paid"],
      "gap_ids": []
    },
    {
      "method": "POST",
      "path": "/api/admin/payments/{payment_id}/refund-v2",
      "symbol": "admin_refund_payment_v2",
      "source_fingerprint": "sha256:8923e6313840883da85a738776f59864099fa502c7cddc623cdaeb5e677a4845",
      "risk": "financial",
      "auth": "verified",
      "reason": "verified",
      "audit": "verified",
      "transaction": "atomic-local",
      "replay": "gap-optional-key",
      "test_evidence": "partial",
      "status": "gap",
      "test_nodes": ["backend/test_billing_v2.py::test_refund_limits_and_analytics_safe", "backend/test_billing_v2.py::test_yookassa_refund_cannot_be_falsely_completed_only_in_local_db"],
      "gap_ids": ["AM-004", "AM-006"]
    },
    {
      "method": "POST",
      "path": "/api/admin/users/{internal_user_id}/bonus-v2",
      "symbol": "admin_bonus_grant_v2",
      "source_fingerprint": "sha256:63da5f7c4c7d2fda2be35f556838c14406f6d5476f3b1b89c93d61d26414eba2",
      "risk": "financial-entitlement",
      "auth": "verified",
      "reason": "verified",
      "audit": "verified",
      "transaction": "atomic-local",
      "replay": "gap-optional-key",
      "test_evidence": "verified-keyed",
      "status": "gap",
      "test_nodes": ["backend/test_promo_bonus_referral_v2.py::test_loyalty_requires_trusted_admin", "backend/test_promo_bonus_referral_v2.py::test_bonus_grant_idempotent_cancel_and_users_id_safe"],
      "gap_ids": ["AM-004", "AM-006"]
    },
    {
      "method": "POST",
      "path": "/api/admin/users/{internal_user_id}/bonus/{bonus_id}/cancel-v2",
      "symbol": "admin_bonus_cancel_v2",
      "source_fingerprint": "sha256:3303a341821d44d03f150be62feae2349299ef3457ed27d169f74d02f7be9569",
      "risk": "financial-entitlement",
      "auth": "verified",
      "reason": "verified",
      "audit": "verified",
      "transaction": "atomic-local",
      "replay": "concurrent-double-debit-gap",
      "test_evidence": "partial-sequential",
      "status": "partial",
      "test_nodes": ["backend/test_promo_bonus_referral_v2.py::test_bonus_grant_idempotent_cancel_and_users_id_safe", "backend/test_promo_bonus_referral_v2.py::test_bonus_cancel_blocked_when_balance_insufficient"],
      "gap_ids": ["AM-006"]
    },
    {
      "method": "POST",
      "path": "/api/admin/users/{internal_user_id}/apply-promo-v2",
      "symbol": "admin_apply_promo_v2",
      "source_fingerprint": "sha256:65187a49133a2396f7e25a37f5abdbe60dcc223b12d23b7cf81babf102f964ad",
      "risk": "financial-entitlement",
      "auth": "verified",
      "reason": "verified",
      "audit": "verified",
      "transaction": "atomic-local",
      "replay": "partial-optional-key-with-domain-guard",
      "test_evidence": "verified-keyed",
      "status": "partial",
      "test_nodes": ["backend/test_promo_bonus_referral_v2.py::test_apply_promo_duplicate_blocked_and_safe"],
      "gap_ids": ["AM-004", "AM-006"]
    },
    {
      "method": "POST",
      "path": "/api/admin/users/{internal_user_id}/referral-reward-v2",
      "symbol": "admin_referral_reward_v2",
      "source_fingerprint": "sha256:f3a1f333a97fb72e02d2362c3eadc30caa31366c52e9f7f1221b7d16f2959a84",
      "risk": "financial-entitlement",
      "auth": "verified",
      "reason": "verified",
      "audit": "verified",
      "transaction": "atomic-local",
      "replay": "gap-optional-key",
      "test_evidence": "verified-keyed",
      "status": "gap",
      "test_nodes": ["backend/test_promo_bonus_referral_v2.py::test_referral_reward_writes_reward_and_ledger"],
      "gap_ids": ["AM-004", "AM-006"]
    }
  ],
  "gaps": [
    {
      "id": "AM-001",
      "priority": "P1",
      "title": "Relative token adjustment has no durable command identity",
      "routes": ["POST /api/admin/users/{internal_user_id}/tokens-v2"],
      "evidence": "AdminTokensV2Request has delta and reason only; admin_tokens_v2 writes a new token_ledger row on every accepted call.",
      "remediation": "Require a bounded idempotency key, persist a unique admin-command record in the same transaction, and return the stored result on replay.",
      "required_tests": ["same key returns the same result", "missing/invalid key is rejected", "concurrent same-key calls change balance once"]
    },
    {
      "id": "AM-002",
      "priority": "P1",
      "title": "Plan mutation can grant tariff tokens again on retry",
      "routes": ["POST /api/admin/users/{internal_user_id}/plan-v2"],
      "evidence": "admin_plan_v2 creates uuid source_id per call; _activate_tariff_now derives a new grant_key and resets the plan period.",
      "remediation": "Bind plan activation and grant_key to a durable admin command id and replay the first response without a second grant or period reset.",
      "required_tests": ["same key grants once", "concurrent same-key calls grant once", "retry preserves original plan dates"]
    },
    {
      "id": "AM-003",
      "priority": "P1",
      "title": "Invoice creation duplicates financial obligations on retry",
      "routes": ["POST /api/admin/users/{internal_user_id}/invoices-v2"],
      "evidence": "BillingCreateInvoiceV2Request has no idempotency key and admin_create_invoice_v2 generates a new invoice id/code on every call.",
      "remediation": "Require a durable command key scoped to actor, target and normalized invoice payload; return the original invoice for a replay.",
      "required_tests": ["same key creates one invoice and item set", "same key with conflicting payload is rejected", "concurrent same-key calls create one invoice"]
    },
    {
      "id": "AM-004",
      "priority": "P1",
      "title": "Optional financial idempotency keys fall back to random values",
      "routes": ["POST /api/admin/invoices/{invoice_id}/mark-paid-v2", "POST /api/admin/payments/{payment_id}/refund-v2", "POST /api/admin/users/{internal_user_id}/bonus-v2", "POST /api/admin/users/{internal_user_id}/apply-promo-v2", "POST /api/admin/users/{internal_user_id}/referral-reward-v2"],
      "evidence": "Request fields are optional and _billing_idempotency creates a UUID when the key is absent; current same-key tests always provide a key.",
      "remediation": "Make command identity mandatory for admin money/token mutations or derive a stable server key from an explicit command id; reject conflicting reuse.",
      "required_tests": ["omitted key cannot silently create a new command", "same key returns stored response", "conflicting payload is rejected"]
    },
    {
      "id": "AM-005",
      "priority": "P2",
      "title": "Maintenance routes lack complete per-route replay and provider characterization",
      "routes": ["POST /api/admin/payments/{payment_id}/simulate-v2", "POST /api/admin/payments/reconcile-v2", "POST /api/admin/payments/notifications/process-v2"],
      "evidence": "Existing simulator tests cover success/cancel/reconcile and one in-app notification pass, but not repeated admin calls, non-admin denial per route, fake email delivery or provider error recovery for every boundary. Reconcile can verify pending YooKassa payments and notification processing can send queued email after only the trusted-admin route check; there is no separate explicit operator authorization and redacted live-action receipt boundary. Every listed maintenance handler records its final admin audit after at least one stateful effect boundary: simulation after payment/invoice/token commit, reconciliation after payment/entitlement commit, and notification processing after email send plus sent/retry state changes. A crash or audit failure can therefore leave the administrative effect without its final route audit event.",
      "remediation": "Add focused fake-provider tests for auth, reason, audit, replay and error recovery. Persist durable pre-action command/audit intent before effects for every listed maintenance route and finalize it after completion or recovery. Before any live-capable provider or email execution, require explicit operator authorization and produce a redacted receipt; YooKassa/SMTP live actions remain outside ordinary tests.",
      "required_tests": ["repeat route without duplicate ledger/delivery", "fake provider failure remains recoverable", "crash after committed simulate effect leaves recoverable durable audit/command intent", "crash after committed reconcile effect leaves recoverable durable audit/command intent", "crash after notification send or sent/retry state leaves recoverable durable audit/command intent", "live-capable path is blocked without explicit operator authorization before fake provider/email call", "authorized fake boundary produces a redacted receipt", "audit contains redacted reason and result"]
    },
    {
      "id": "AM-006",
      "priority": "P1",
      "title": "Critical mutations lack focused concurrent command tests",
      "routes": ["POST /api/admin/users/{internal_user_id}/tokens-v2", "POST /api/admin/users/{internal_user_id}/plan-v2", "POST /api/admin/users/{internal_user_id}/invoices-v2", "POST /api/admin/invoices/{invoice_id}/mark-paid-v2", "POST /api/admin/payments/{payment_id}/refund-v2", "POST /api/admin/users/{internal_user_id}/bonus-v2", "POST /api/admin/users/{internal_user_id}/bonus/{bonus_id}/cancel-v2", "POST /api/admin/users/{internal_user_id}/apply-promo-v2", "POST /api/admin/users/{internal_user_id}/referral-reward-v2", "POST /api/admin/payments/{payment_id}/simulate-v2", "POST /api/admin/payments/reconcile-v2", "POST /api/admin/payments/notifications/process-v2"],
      "evidence": "Current focused suites assert sequential behavior; no listed node races two same-command requests against one temporary SQLite database. Bonus cancellation reads granted status and balance before unconditional ledger/status writes, so concurrent requests can both debit.",
      "remediation": "Add exact concurrent characterization per changed invariant and repeat that node five times; do not repeat the whole Full suite.",
      "required_tests": ["two concurrent same-key calls", "single ledger/obligation/delivery outcome", "deterministic stored response or documented conflict"]
    },
    {
      "id": "AM-007",
      "priority": "P2",
      "title": "Email outbox has a send-before-ack duplicate window",
      "routes": ["POST /api/admin/payments/notifications/process-v2"],
      "evidence": "The handler sends email after claim and marks sent in a later transaction; process loss after SMTP acceptance and before mark-sent can cause retry delivery.",
      "remediation": "Define the accepted at-least-once contract and provider/message deduplication boundary, then characterize crash recovery with a fake adapter.",
      "required_tests": ["crash after fake-provider acceptance", "recovery does not silently lose obligation", "deduplication behavior is explicit"]
    },
    {
      "id": "AM-008",
      "priority": "P2",
      "title": "Payment-maintenance reasons accept whitespace-only input",
      "routes": ["POST /api/admin/payments/{payment_id}/simulate-v2", "POST /api/admin/payments/reconcile-v2", "POST /api/admin/payments/notifications/process-v2"],
      "evidence": "BillingSimulationV2Request and AdminPaymentMaintenanceV2Request enforce min_length=3 before trimming; handlers write req.reason.strip() without rejecting an empty result.",
      "remediation": "Validate the stripped reason with the shared bounded helper before any side effect and keep the normalized non-empty reason in the audit record.",
      "required_tests": ["whitespace-only reason is rejected before side effects", "normalized non-empty reason is audited", "auth and reason failures do not call fake providers"]
    },
    {
      "id": "AM-009",
      "priority": "P1",
      "title": "Last-admin role invariant lacks concurrent characterization",
      "routes": ["POST /api/admin/users/{internal_user_id}/role-v2"],
      "evidence": "admin_role_v2 counts admins and then updates the target inside a deferred SQLite transaction; declared tests exercise only sequential self-demotion and last-admin cases.",
      "remediation": "Characterize two independent admin sessions racing reciprocal demotions, then enforce a transactional last-admin invariant with a deterministic loser outcome and audit record.",
      "required_tests": ["two admin sessions race reciprocal demotions", "at least one admin remains after every outcome", "loser result and audit record are deterministic", "repeat the exact race test five times"]
    }
  ]
}
```
<!-- admin-mutation-audit-json:end -->

## Remediation order

Не исправлять все gaps одним PR. Рекомендуемый порядок отдельных packages:

1. `ADMIN-ROLE-LAST-ADMIN-RACE-001`: двухсессионная last-admin race
   characterization и transactional invariant.
2. `ADMIN-COMMAND-IDEMPOTENCY-001`: общий durable command contract и
   `tokens-v2` + `plan-v2` characterization.
3. `ADMIN-INVOICE-IDEMPOTENCY-001`: invoice creation и mandatory/conflict-safe
   command key.
4. `ADMIN-LOYALTY-IDEMPOTENCY-001`: bonus/promo/referral command identity.
5. `ADMIN-PAYMENT-MAINTENANCE-001`: fake-provider replay/error/race coverage для
   simulate/reconcile/notification processing плюс отдельный explicit operator
   authorization и redacted receipt contract до любой live-capable ветки.

Каждый package должен заново проверить overlap и читать только нужные symbols.

## Verification boundary

Этот audit использует source, generated route evidence и temporary/fake tests.
Он не проверяет production DB, реальную YooKassa, SMTP или развернутую версию.
