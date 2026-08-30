---
status: ready-for-review
canonical: false
record_role: task-contract
package: ADMIN-DOCS-002
base_sha: 2f03b4e54719a7afb9e5d0bea8c95b26e9e3c1f1
product_source_sha: 11b087d8441cb109b50b1d1e863fdcfa73201d07
branch: codex/admin-doc-contract-20260831
risk_class: low
authorized: owner request in Codex, 2026-08-31
depends_on_pr: none
deployment: none
verified: 2026-08-31
---

# ADMIN-DOCS-002 — Task Contract

## Goal

Сделать admin-документацию исполняемым change-contract: точные routes должны
сравниваться с source, а каждая область должна иметь ownership, side effects,
risk, required controls, tests и безопасный recipe.

## Before / after

- Before: guide содержит текущие маршруты, но тест проверяет только наличие
  известных строк и не обнаружит новый забытый route.
- After: source arrays, guide tables и machine-readable contract обязаны
  совпадать как точные множества; files/API examples/tests также валидируются.

## Non-goals

- Product/frontend/backend behavior и generated maps.
- Исправление audit gaps или `e2e-admin-crm-live.mjs`.
- Общий context index, affected-test router для всего репозитория или изменения
  общих routing-tests вне пяти declared files.
- Provider, production, deploy, restart или live QA actions.

## Declared files

- `docs/admin-change-contract.md`;
- `docs/admin-panel-guide.md`;
- `docs/context/admin-control-center.md`;
- `docs/agent-tasks/ADMIN-DOCS-002.md`;
- `tools/test_admin_docs_contract.py`.

## Acceptance

- Top-level admin routes/labels точно совпадают в source, guide и contract.
- Model/OpenRouter routes/labels точно совпадают в source, guide и contract.
- Все 10 admin areas имеют ownership, API examples, controls, risk и tests.
- Все пути существуют; API examples обнаруживаются в текущем backend evidence.
- Recipes содержат точные commands и отделяют mocked от live evidence.
- Targeted tests, `git diff --check`, complete diff и secret scan проходят.

## Forbidden operations and rollback

Не менять общие `AI_START_HERE.md`, `docs/NOW.md`, `tools/test_context_docs.py`
в этом bounded package. Не менять product/generated/runtime/provider state.
Rollback ограничен одним commit поверх текущего `main`.

## Verification receipt

- Admin/context/agent/collection contracts: 14 passed.
- Focused payment ledger/outbox idempotency: 2 tests × 5 повторов, все passed.
- Наблюдались существующие FastAPI deprecation и Windows temporary-directory
  cleanup warnings; test failures отсутствуют.
- Product source, generated maps, runtime, secrets и providers не изменялись.
