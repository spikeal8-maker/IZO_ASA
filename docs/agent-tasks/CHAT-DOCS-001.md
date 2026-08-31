---
status: code-complete
canonical: false
record_role: task-contract
package: CHAT-DOCS-001
domain: chat-documentation
riskClass: low
base_sha: 11b087d8441cb109b50b1d1e863fdcfa73201d07
branch: codex/chat-docs-20260831
created: 2026-08-31
scope_reviewed: 2026-08-31
completed: 2026-08-31
---

# CHAT-DOCS-001 — каноническая документация `/chat`

## Goal и пользовательский результат

Зафиксировать фактическую архитектуру, продуктовый контракт и целевую границу
самостоятельности страницы `/chat` до любых следующих изменений поведения.

До пакета сведения о чате разбросаны по frontend, phone API, backend router,
истории, биллингу и тестам. После пакета владелец и новый coding-agent должны
одинаково отвечать на вопросы: что такое чат, где его границы, что уже отделено,
что пока общее, какие контракты нельзя нарушать и с чего начинать следующую
задачу.

## Before / after scenario

- Before: `/chat` существует как отдельный URL и UI-компонент, но отдельной
  canonical context-карты и общей спецификации нет; его самостоятельность легко
  переоценить.
- After: `docs/chat-system.md` описывает продукт и архитектуру для людей, а
  `docs/context/chat.md` является короткой обязательной картой для AI-агентов.
  `AI_START_HERE.md` и `docs/NOW.md` направляют chat-задачи в эту карту.

## Non-goals

- Не менять UI, CSS, system prompt, модели, API, БД, billing или telemetry.
- Не извлекать чат из modular monolith и не переименовывать `/api/phone/chat*`.
- Не запускать реальные OpenRouter/Ollama/ComfyUI операции.
- Не выполнять deploy, restart, release или production diagnosis.
- Не объявлять существующий чат полностью автономной подсистемой без evidence.
- Не копировать chat-specific reading order или архитектуру в `AGENTS.md`.
- Не менять фактическое runtime-поведение помощника в documentation package.

## Scope extension после критического review

До первого push review выявил, что исходный пакет недостаточно готов для GitHub:
не было кликабельной навигации, отдельного проверяемого контракта поведения
AI-помощника и автоматической проверки chat-specific routing. Поэтому scope
расширен до publication/agent-discoverability hardening без изменения product
runtime. Старый отстающий worktree `ai-agent-system-20260828` содержит
неопубликованный overlapping WIP в README и agent tests; он не изменяется и не
используется как канонический источник. Пересечение разрешается через diff/PR
текущей чистой ветки.

## Declared files

- `docs/agent-tasks/CHAT-DOCS-001.md`
- `docs/chat-system.md`
- `docs/chat-assistant-contract.md`
- `docs/context/chat.md`
- `AI_START_HERE.md`
- `docs/NOW.md`
- `README.md`
- `tools/test_context_docs.py`

## Acceptance

- Общий документ разделяет current state и target boundary.
- Описаны route, UI, API, auth, persistence, providers, tools, billing,
  observability, failure modes и verification.
- Context-карта укладывается в 100–250 строк и ссылается только на существующие
  файлы.
- Есть отдельный externally testable contract помощника без публикации raw
  system prompt или provider internals.
- README и документы дают кликабельную GitHub-навигацию, но единственный порядок
  чтения остаётся в `AI_START_HERE.md`.
- Зафиксировано, что desktop `/chat` использует собственный workspace, но общий
  studio shell и phone chat contracts/backend.
- Известные проблемы предыдущего аудита записаны как evidence и не выдаются за
  уже исправленные.
- Canonical reading order остаётся только в `AI_START_HERE.md`.

## Required evidence и targeted checks

- `python -m pytest tools/test_context_docs.py tools/test_agent_instructions.py`
- проверка Markdown-ссылок и упомянутых repository paths;
- `git diff --check`, полный просмотр diff и `git status --short`;
- отсутствие изменений вне declared files.
- `tools/verify.ps1 -Mode Quick` перед первым push/PR; если live gate недоступен
  в feature-worktree, зафиксировать точную причину и выполнить безопасные
  isolated/static gates без подмены runtime manifest.

## Forbidden operations и rollback

Production DB, media, secrets, providers, runtime manifests, VPS/network и
release operations находятся вне scope. Rollback boundary — один
documentation-only commit; его отмена не требует миграции данных или restart.

## Local verification

```text
python -m pytest tools/test_context_docs.py tools/test_agent_instructions.py
10 passed

tools/verify.ps1 -Mode Quick
backend preflight, py_compile, generated maps and listener contract: passed
caddy_edge_live: unavailable because feature-worktree has no
.runtime/active-frontend.json; production manifest was not copied or changed

tools/verify.ps1 -Mode CI
generated/static/config gates: passed
pytest_full: 1870 passed, 97 pre-existing deprecation warnings
wrapper then stopped because frontend/node_modules was absent

npm ci
npm run lint
FRONTEND_BUILD_LABEL=<verification-id> npm run build
FRONTEND_BUILD_LABEL=<verification-id> npm run check:release
npm run check:origin
npm run e2e:studio-resilience
all passed after deterministic dependency installation
```

Product source, production/runtime state и внешние providers не изменялись.
`npm ci` сообщил о трёх существующих high-severity dependency audit findings;
package/lock files не менялись, dependency remediation находится вне scope.

GitHub automated review для PR #79 выявил семнадцать P2 documentation findings:
неописанный fixed-cost billing branch, слишком широкий запрет technical model ID
в internal telemetry, безусловное price requirement, зависимость catalog/UI
availability от `price_confirmed` даже в fixed mode и публичность published API
model ids, forced-tool display/storage divergence и отдельная best-effort запись
финального image-tool state, отсутствие mobile preview/share parity и
desktop-only media actions в empty state. Все исправлены по bounded source
evidence до merge. Последними устранены второй reading order в context-карте и
смешение catalog/UI availability с fixed-cost direct POST acceptance, а также
слишком широкое обещание refund за пределами реально перехваченных failure paths.
Дополнительно зафиксированы Russian-only runtime, ledger-only request idempotency
и отсутствие visual-capability validation до платного provider call, mobile
citation rendering и проверки реального image content/magic bytes.
