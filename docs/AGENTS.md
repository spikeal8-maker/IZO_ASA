# Documentation scoped policy

Root `AGENTS.md` and `AI_START_HERE.md` remain mandatory. This file owns only
rules for `docs/**`; it does not own the reading order itself.

## Canonical ownership

- `docs/NOW.md` is the only current-status aggregator and program router.
- `AI_START_HERE.md` is the only reading-order owner; docs may point to it but
  must not restate another hierarchy.
- `docs/context/*.md` are scoped domain maps. Extend the existing context
  hierarchy instead of creating a parallel one.
- `docs/agent-control-plane.md` is program documentation, not daily context.
- Historical roadmaps and completed package documents are evidence, not active
  backlog. `README.md` describes product/basic operations and is not a backlog.
- Historical reports kept under `archive/docs/` are excluded from ordinary task
  discovery. Open a specific archived file only for a referenced evidence question.
- A two-month age cutoff is an archival review trigger, not permission to discard
  active contracts, runbooks, recovery/security guidance or linked evidence.

## Generated and historical evidence

- `docs/generated/*` and `backend/SYMBOL_MAP.md` are generator-owned evidence.
  Never hand-edit generated output; change source/contract/generator and
  regenerate deterministically in the same package.
- Keep generated machine evidence deterministic and human evidence readable.
- Do not claim runtime/deployment state from documentation alone; deployment
  requires installed exact-SHA evidence.

## Читаемость и разбиение больших документов

- Для новых рукописных тематических Markdown: не более **200 строк и 12 КиБ UTF-8**; для короткого указателя — не более **120 строк и 8 КиБ**. Действующие `docs/context/*.md` используют собственный контракт до 250 строк, `docs/generated/**` — только генератор.
- Старые большие документы — долг: сначала разделить по темам и сохранить исходный Git blob в архиве, затем проверить ссылки и только после этого менять смысл. Не удалять нормативные требования ради лимита.
- Подробное правило: [`docs/documentation-standards.md`](documentation-standards.md). Организация и лимиты тестов — [`docs/testing-file-standards.md`](testing-file-standards.md). Размеры исходного кода определяет существующий `architecture/contract.json`, без параллельного норматива.

## Status and package documentation

- Update `docs/NOW.md` only when completed/active/next package, blocker,
  canonical routing/evidence map or verified source/release state changes.
- Keep implementation logs and long receipts in the Task Contract/issue/PR, not
  in `NOW`.
- Scoped docs must never claim `status_role`, `backlog_role` or
  `reading_order_role`; those markers have exactly one canonical owner each.
- Links to repository paths must resolve or explicitly identify future work.
