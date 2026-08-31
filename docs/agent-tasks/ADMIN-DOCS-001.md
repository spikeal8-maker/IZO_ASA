---
status: ready-for-review
canonical: false
record_role: task-contract
package: ADMIN-DOCS-001
base_sha: 11b087d8441cb109b50b1d1e863fdcfa73201d07
branch: codex/admin-documentation-20260831
risk_class: low
authorized: owner request in Codex, 2026-08-31
deployment: none
verified: 2026-08-31
---

# ADMIN-DOCS-001 — Task Contract

## Goal and user outcome

Создать одну актуальную общую документацию админки и одну scoped context-карту
для coding-агентов, чтобы владелец видел реальное состояние продукта, а агент
мог безопасно найти ownership, ограничения и проверки без broad scan.

## Before / after

- Before: сведения распределены между устаревшей Phase 19 spec, историческими
  фазами, model plans, runbooks, generated maps и source.
- After: `docs/admin-panel-guide.md` описывает текущую поверхность для человека,
  а `docs/context/admin-control-center.md` маршрутизирует bounded agent work.

## Non-goals

- Product/backend/frontend implementation.
- Исправление audit/reason gaps, layout или provider behavior.
- Production DB/media/secrets/runtime, deploy, restart и live provider actions.
- Редактирование незакоммиченного WIP в других worktree.
- Превращение historical plans в активный backlog.

## Domain and declared files

Domain: admin documentation across frontend/backend ownership.

Declared files:

- `docs/admin-panel-guide.md`;
- `docs/context/admin-control-center.md`;
- `docs/admin-panel-product-spec.md`;
- `docs/agent-tasks/ADMIN-DOCS-001.md`;
- `AI_START_HERE.md`;
- `docs/NOW.md`;
- `tools/test_context_docs.py`.

Allowed patterns: только Markdown routing/status и contract test новой карты.

## Acceptance and required evidence

- Руководство перечисляет фактические 10 top-level routes.
- Models routing совпадает с `frontend/src/adminModelsRoutes.ts`.
- Access описан через trusted cookie session/admin role без legacy identity.
- Context содержит ownership, safety, bounded discovery, risk и targeted tests.
- Старый Phase 19 документ явно historical и superseded.
- `AI_START_HERE.md` и `docs/NOW.md` маршрутизируют новую карту без второго
  reading order.
- Context reference/size tests, agent instruction contracts и Markdown link
  checks проходят.
- `git diff --check`, complete diff review и secret scan проходят.

## Forbidden operations

- Изменение source приложения или generated maps вручную.
- Работа в canonical `main`.
- Stash/reset/cleanup чужих worktree.
- Full verification, release, deploy, restart или provider mutation.

## Rollback boundary

Один documentation commit в отдельной ветке. Rollback удаляет только объявленные
документы/routing/test изменения и не затрагивает application state.

## Verification receipt

- `python -m pytest -q tools/test_context_docs.py tools/test_agent_instructions.py`
  — 7 passed.
- `AI_START_HERE.md` — 120 строк, enforced budget сохранён.
- `docs/context/admin-control-center.md` — 231 строка, context budget сохранён.
- Product source, generated maps, production runtime и providers не изменялись.
