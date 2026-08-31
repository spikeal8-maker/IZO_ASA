---
status: ready-for-review
canonical: false
record_role: task-contract
package: ADMIN-MUTATION-AUDIT-001
package_mode: bounded-discovery
base_sha: 7ea3c3b66a6b673707b67df91b74151c3474a9c6
branch: codex/admin-mutation-audit-20260831
risk_class: high-assurance
authorized: owner request in Codex, 2026-08-31
deployment: none
verified: 2026-08-31
---

# ADMIN-MUTATION-AUDIT-001 — Task Contract

## Goal and user outcome

Провести route-level audit 19 наиболее критичных compatibility mutations
identity/CRM/finance в `/api/admin`: для каждого route зафиксировать текущие
evidence и gaps по trusted-admin, reason, audit, transaction/idempotency и
focused tests. Будущий coding-agent должен получить проверяемый вход в
remediation package, а не повторять широкий поиск по `backend/main.py`.

## Before / after scenario

- Before: admin context требует проверять каждый mutation route, но единой
  route-level карты текущего покрытия нет; наличие общего test-файла может быть
  ошибочно принято за доказательство конкретного control.
- After: machine-readable audit покрывает точный bounded-набор из 19 routes,
  связывает каждый route с backend symbol и test evidence, различает
  `verified`, `partial` и `gap`, а contract test обнаруживает исчезнувший route,
  неверный HTTP method, несуществующий owner/test или неполную запись.

## Scope

Включены compatibility routes для block/unblock/password reset, role, tokens,
discount, plan, profile, payment simulate/reconcile/notification processing,
invoice create/mark-paid/cancel, refund, bonus grant/cancel, promo application и
referral reward.

## Non-goals

- Исправление найденных product/security gaps в этом package.
- Mail, provider secrets, OpenRouter, Config UI, assistants, moderation, media,
  bot token/webhook и другие admin mutations вне указанного набора.
- Изменение `backend/main.py`, frontend, generated maps, schema/migrations,
  production DB/media/secrets/runtime или provider state.
- Deploy, restart, live payment/refund/mail/webhook/provider verification.
- Blanket claim, что вся админка прошла audit.

## Declared files and allowed patterns

- `docs/admin-mutation-audit.md`;
- `docs/admin-change-contract.md`;
- `docs/admin-panel-guide.md`;
- `docs/context/admin-control-center.md`;
- `docs/agent-tasks/ADMIN-MUTATION-AUDIT-001.md`;
- `tools/test_admin_mutation_audit.py`.

Разрешены только эти шесть exact paths. Source и существующие tests читаются
точечно как evidence, но не изменяются.

Discovered scope: automated review указал обязательное правило
`docs/context/admin-control-center.md` — изменение safety/test routing должно в
том же commit обновлять `docs/admin-panel-guide.md`. Проверка open PR не нашла
пересечения по guide/audit/contract files; домен и risk class не изменились.

## Acceptance

- Audit содержит ровно 19 заявленных method/path/symbol triples, source SHA и
  проверяемый fingerprint decorator + полного тела каждого handler.
- Полные fingerprints `backend/main.py`, route map и заявленных test-файлов
  связывают выводы с общими helper/model dependencies и test evidence.
- Для каждого route заполнены risk, auth, reason, audit, idempotency/transaction,
  tests, evidence и remediation boundary; неизвестное обозначено как gap.
- HTTP methods/routes/symbols сверяются с `backend/SYMBOL_MAP.md`.
- Все owner/test paths существуют; test evidence привязано к конкретному route
  или явно отмечено как отсутствующее.
- Admin context и change contract направляют mutation package в audit до правки.
- Focused tests работают только с temporary DB/fake providers; финансовый
  idempotency/race invariant повторяется пять раз.
- Contract tests, `git diff --check`, complete diff и secret scan проходят.
- Test evidence сопоставляется с полным route template, а не с неоднозначным
  последним сегментом URL.

## Required evidence

- Bounded symbol ranges из `backend/main.py`, без чтения файла целиком.
- Exact route inventory из `backend/SYMBOL_MAP.md`.
- Focused node IDs и assertions из существующих admin/billing tests.
- Fresh CI и автоматический review exact head перед merge.

## Forbidden operations and rollback

Не использовать production fixtures, live providers, real payments/refunds,
deploy/restart, stash/reset/cleanup или sibling worktree. Не расширять scope на
provider/bot/mail/config routes без нового Task Contract. Rollback ограничен
одним documentation/tooling commit поверх `main`.

## Verification receipt

- Mutation/admin/context/agent executable contracts: 22 passed.
- Focused temporary-DB/fake-provider route suites: 47 passed.
- Existing keyed idempotency and durable outbox nodes: 5 tests × 5 повторов,
  все passed.
- Local Quick прошёл compile, generated-map и runtime-listener steps, затем
  остановился на `caddy_edge_live`: isolated feature worktree не содержит
  active production frontend manifest. Manifest не копировался; exact branch
  gate остаётся обязательным в isolated GitHub CI.
- Audit result: 19 routes = 6 verified, 7 partial, 6 gap; 9 remediation gap
  records связаны с exact routes.
- Первый automated review exact head нашёл две P2-слабости contract test:
  fingerprint не был проверяемым, а URL evidence допускал substring collision.
  Добавлены per-handler source fingerprints, full route-template matching и
  отдельная `block-v2`/`unblock-v2` regression.
- Второй automated review exact head нашёл whitespace-only reason gap у трёх
  maintenance routes и неполную привязку transitive controls. Добавлены
  `AM-008` и full normalized fingerprints source/map/test evidence.
- Третий automated review exact head выявил, что `AM-005` не требовал отдельное
  operator authorization и redacted receipt перед live-capable provider/email
  execution. Control, evidence и required fake-boundary tests добавлены.
- Четвёртый automated review exact head понизил `role-v2` до `partial` до
  пяти-кратной two-session last-admin race characterization (`AM-009`) и выявил
  обязательное обновление panel guide для нового safety/test routing. Оба
  замечания отражены.
- Пятый automated review exact head выявил concurrent double-debit в bonus
  cancellation и post-effect audit window в reconciliation. Bonus cancel
  включён в `AM-006`; reconcile audit помечен partial, а `AM-005` требует
  durable pre-action intent и crash recovery.
- Шестой automated review exact head показал такой же post-effect audit window
  у simulate и notification processing. Все три maintenance routes помечены
  `partial-post-effect`; `AM-005` теперь требует durable intent/finalization и
  отдельный crash-recovery test для каждого route. Fresh review нового exact
  head обязателен перед merge.
- Наблюдались существующие FastAPI/Starlette deprecation и Windows temporary
  directory cleanup warnings; test failures отсутствуют.
- Product source, generated maps, frontend, production data, secrets, runtime и
  providers не изменялись.
- `DEPLOYED` и `OPERATIONALLY VERIFIED` не входят в package.
