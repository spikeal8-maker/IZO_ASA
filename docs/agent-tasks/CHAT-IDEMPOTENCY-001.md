---
id: CHAT-IDEMPOTENCY-001
status: ready-for-review
owner: codex
riskClass: high-assurance
domain: chat-billing
created: 2026-08-31
verified: 2026-08-31
base_sha: 7ea3c3b66a6b673707b67df91b74151c3474a9c6
branch: codex/chat-idempotency-20260831
---

# CHAT-IDEMPOTENCY-001 — durable chat request lifecycle

## Goal

Сделать `POST /api/phone/chat` сквозно idempotent по паре trusted user и
`requestId`, а также гарантировать возврат незавершённого charge при любой
ошибке до атомарного сохранения успешного результата.

## User outcome

Повтор того же запроса после потери сети не вызывает модель, не добавляет
историю, не создаёт второй backend tool intent и не списывает средства повторно. Если
успешный результат не был атомарно сохранён, charge возвращается ровно один раз.

## Before scenario

1. Ledger ищет duplicate по JSON `LIKE` только по `request_id`, без trusted user
   и fingerprint операции.
2. Duplicate charge не останавливает повторный provider call и history write.
3. Повтор с другим payload/model может использовать прежний ledger.
4. Failure повторного provider call может refund'нуть ledger прежнего success.
5. Unknown provider, settlement, telemetry и history exceptions находятся вне
   полного compensation boundary.

## After scenario

1. `(user_id, request_id)` однозначно связан с canonical request fingerprint,
   resolved provider/model, ledger и публичным outcome.
2. Совпадающий completed replay возвращает сохранённый response без side effects.
3. Повтор с другим fingerprint получает conflict до charge/provider.
4. Одновременный replay видит durable `processing` и не запускает вторую работу.
5. Charge + request claim атомарны; settlement + history + successful outcome
   атомарны.
6. Любая ошибка после charge и до committed success выполняет один idempotent
   refund и сохраняет безопасный failed outcome.
7. Telemetry после committed success является best-effort и не меняет outcome.

## Non-goals

- Streaming/cancel.
- Durable finalization frontend image job и tool PATCH.
- Structured forced-tool request.
- Image content/capability validation.
- Redesign desktop/mobile UI.
- Изменение pricing policy, тарифов или provider configuration.
- Production deploy, restart, database migration или live provider verification.

## Declared files and patterns

- `docs/agent-tasks/CHAT-IDEMPOTENCY-001.md`
- `backend/app/api/routers/phone_chat.py`
- `backend/app/services/chat_billing.py`
- `backend/app/services/chat_request_lifecycle.py` (new, if confirmed by discovery)
- `backend/app/database/migrations.py`
- `backend/test_chat_billing.py`
- `backend/test_phone_chat_idempotency.py` (new)
- `backend/test_phone_chat_history.py` only if atomic-finalization coverage needs it
- `backend/test_social_account_verification.py` — discovered version assertion
  must advance from 6 to the new additive migration version 7; no social behavior changes
- `docs/context/chat.md`
- `docs/chat-system.md`
- `docs/chat-assistant-contract.md`
- generated maps required by repository structural checks

Discovered files may be added only with recorded reason and renewed overlap
check. `backend/main.py` may receive composition-only dependency wiring in a
bounded range; business logic there is forbidden.

## Acceptance

- Same user + same request id + same fingerprint returns the same completed
  response without a second charge/provider/history/tool intent.
- Same user + same request id + different fingerprint returns HTTP 409 before
  provider work.
- Different users may independently use the same request id.
- Concurrent duplicates produce one provider call and one history exchange.
- Provider, settlement and history failures refund exactly once and persist a
  deterministic safe failure.
- A stale interrupted request refunds its known charge exactly once and does not
  resume unknown provider work.
- Successful settlement/history/outcome are committed atomically.
- Telemetry failure does not fail or refund a committed success.
- No production DB/media/secrets/provider is used by tests.

## Required evidence

- Characterization tests fail against the before implementation.
- Additive versioned migration with a new checksum; no applied migration changes.
- Focused success, conflict, concurrent replay, failure and stale-recovery tests.
- Billing and concurrent-storage focused tests pass five consecutive times.
- Targeted backend suite and architecture/migration checks pass.
- `tools/verify.ps1 -Mode Quick` or the strongest isolated non-release fallback.
- Complete diff, secret scan, clean commit, GitHub CI and automated review.

## Targeted tests

- `backend/test_chat_billing.py`
- `backend/test_phone_chat_idempotency.py`
- `backend/test_phone_chat_history.py`
- relevant migration/static architecture tests selected by repository tooling

## Forbidden operations

- No production SQLite/WAL/SHM, media, secrets or runtime manifests.
- No real OpenRouter/Ollama/provider calls; tests use fakes.
- No backend restart, deploy, payment/refund operation or live verification.
- No schema rewrite, reused migration version/name/checksum or destructive SQL.
- No changes to auth identity, tariff policy, image jobs or frontend behavior.

## Discovery clarification

`POST /api/phone/chat` сохраняет только tool intent. Реальный image job запускает
frontend после ответа. Поэтому package доказывает idempotency chat
charge/provider/history/cached tool intent, но не объявляет frontend image job
или его best-effort final PATCH idempotent. Это остаётся отдельным non-goal и
известным GAP документации чата.

## Rollback boundary

Code rollback may stop using the additive request table, but does not drop it.
No destructive down migration is part of this package. Existing ledger, history
and user balances remain authoritative; rollback never rewrites production data.

## Verification receipt

- Before implementation, characterization reproduced two integrity failures:
  the same `requestId` crossed trusted-user boundaries in the legacy ledger
  lookup, and completed replay invoked the provider a second time.
- `backend/test_phone_chat_idempotency.py`: 9 passed in each of five consecutive
  runs, including concurrent ownership, deterministic replay, exact refund,
  stale recovery and settlement/history rollback.
- Relevant billing, migration, router, history, model and tool suites passed.
- `tools/verify.ps1 -Mode CI`: `VERIFY_OK`; 1 886 backend tests passed, frontend
  lint/build/release-identity/origin-isolation/studio-resilience gates passed.
- `tools/verify.ps1 -Mode Quick` reached the installed-edge check and correctly
  stopped because a feature worktree has no active production frontend manifest;
  the manifest was not copied or changed. The stronger isolated CI receipt above
  is the non-release evidence for this package.
- Generated architecture and symbol maps were regenerated with repository tools;
  `git diff --check` and a changed-file credential-pattern scan passed.
- Tests used temporary SQLite databases and fake providers only. Production DB,
  media, secrets, runtime, providers, processes and deployment were untouched.

`npm ci` reported three existing high-severity dependency audit findings. Lock
files were unchanged; dependency remediation is outside this package.
