---
status: review-draft
canonical: false
program: IZO_ASA Agent Control Plane
created: 2026-08-30
repository: spikeal8-maker/IZO_ASA
base_sha: ecb02bf84ae21a46711c9b38b61784147fb9fc0a
activation: review -> tested commit -> merge to main
---

# IZO_ASA Agent Control Plane

## 1. Назначение

Проекту нужен не ещё один длинный файл с советами, а исполнимый контур, который делает работу разработчиков и AI-агентов ограниченной, проверяемой и воспроизводимой.

Целевой цикл:

```text
запрос владельца
→ Task Contract
→ domain и risk class
→ ограниченный context packet
→ отдельный worktree и package registry
→ изолированная тестовая среда
→ изменение в заявленном scope
→ targeted verification и пользовательское evidence
→ один clean commit интегратору
→ обновление context/eval по фактическому drift
```

Главный принцип:

> Документация объясняет правила. Инструменты проверяют и обеспечивают их.

## 2. Что переиспользуется

Не создавать параллельные реализации существующих механизмов:

- корневой `AGENTS.md`;
- `docs/context/backend-auth-bots.md`;
- `docs/context/frontend-studio.md`;
- `docs/context/video-gallery-feed.md`;
- generated frontend/backend/architecture maps;
- `tools/repository-operation-lock.ps1`;
- `tools/verify.ps1`;
- временные DB/media roots и fake providers в CI;
- действующие release, backup и production-safety contracts.

## 3. Что не делается одновременно с базовым контуром

До завершения основных пакетов не смешивать с программой:

- redesign продукта;
- массовую декомпозицию `backend/main.py`, `newUi.tsx` или CSS;
- миграцию на Linux/PostgreSQL/Docker;
- установку Maya;
- deploy/restart;
- реальные платежи, webhook, письма или provider calls;
- массовое перемещение исторической документации.

3D получает domain-карту и eval-кейс. Maya остаётся отдельным продуктовым пакетом.

## 4. Единственная иерархия источников

Для coding-задачи действует порядок:

1. системные и пользовательские инструкции текущей сессии;
2. корневой `AGENTS.md`;
3. ближайший вложенный `AGENTS.md` целевой области;
4. `AI_START_HERE.md` как короткая навигация;
5. `docs/NOW.md` как единственный агрегатор текущего состояния;
6. выбранные `docs/context/*.md`;
7. Task Contract текущего package;
8. source code и tests;
9. historical/reference documents только по явной причине.

`README.md` не является исполняемым backlog.

## 5. Целевая структура

```text
AGENTS.md
AI_START_HERE.md
CLAUDE.md
GEMINI.md
.github/copilot-instructions.md

backend/AGENTS.md
frontend/AGENTS.md
ops/AGENTS.md
docs/AGENTS.md

docs/agent-control-plane.md
docs/NOW.md
docs/context/*.md
docs/generated/context-index.json
docs/generated/contract-graph.json
docs/generated/contract-graph.md
docs/agent-tasks/*.md
docs/evals/agent-cases/*.yaml

tools/agent.ps1
tools/agent_system/*.py
```

Runtime coordination хранится относительно Git common dir, чтобы все worktree одного clone видели общее состояние:

```text
<git-common-dir>/izo-agent-state/packages/*.json
<git-common-dir>/izo-agent-state/locks/*
<git-common-dir>/izo-agent-state/receipts/*
```

## 6. Один CLI вместо множества несвязанных скриптов

```powershell
.\tools\agent.ps1 doctor
.\tools\agent.ps1 context -Domain chat
.\tools\agent.ps1 symbol -Path backend/main.py -Symbol phone_chat_ollama
.\tools\agent.ps1 start -Manifest .\tasks\CHAT-001.yaml
.\tools\agent.ps1 status
.\tools\agent.ps1 scope-add -Path frontend/src/example.tsx -Reason "..."
.\tools\agent.ps1 env-up
.\tools\agent.ps1 verify
.\tools\agent.ps1 finish
.\tools\agent.ps1 eval -Suite smoke
```

### `doctor`

Проверяет до чтения больших файлов:

- команда запущена внутри Git repository;
- remote соответствует `spikeal8-maker/IZO_ASA`;
- repo root определяется через `git rev-parse --show-toplevel`;
- найден Git common dir;
- известны HEAD, branch, origin/main и worktree;
- отсутствуют конфликтующие workspace instructions;
- mutating-команда имеет package ID;
- test roots не указывают на production DB/media/secrets;
- нет пересечения с другим package или integration owner.

Абсолютный host-path может быть локальной заметкой конкретной машины, но не переносимым способом обнаружения repository root.

### `context`

Возвращает ограниченный packet:

- domain и routes;
- entrypoints;
- source paths;
- соседние domains;
- API, DB, workers, providers и billing effects;
- обязательные tests;
- запрещённые операции;
- active owners пересекающихся файлов;
- предупреждения о больших файлах.

Ограничения по умолчанию:

- до 250 строк;
- до 32 KiB;
- source-файлы больше 1500 строк не включаются целиком;
- historical docs не включаются автоматически.

### `symbol`

Показывает выбранный symbol, imports, прямые связи, routes, tests и ограниченное source window. Не заменяет статический анализ выдуманными связями: неизвестное маркируется `unknown`.

### `env-up`

Создаёт package-specific среду:

- temporary SQLite;
- temporary media и secret roots;
- fake providers;
- test user и fixtures;
- уникальные backend/frontend ports;
- preview URL;
- PID/port receipt;
- автоматический cleanup через `finish`.

Команда обязана fail-closed при попытке использовать production state или платный provider.

## 7. Task Contract

До изменения product code package содержит проверяемый пользовательский результат:

```yaml
schemaVersion: 1
id: CHAT-LAYOUT-001
owner: agent-session-id
baseSha: full-40-char-sha
domain: chat
riskClass: standard
status: draft

goal: Исправить конкретное поведение
userOutcome: Что увидит и сможет сделать пользователь
beforeScenario: Как воспроизводится дефект до изменения
afterScenario: Как должен работать сценарий после изменения
nonGoals: []
routes: [/chat]

declaredFiles: []
allowedPatterns: []
discoveredFiles: []
scopeChanges: []

dataStates: []
acceptance: []
requiredEvidence: []
targetedTests: []
forbiddenOperations:
  - production-deploy
  - real-provider-call
  - production-db-write

deployment: none
rollbackBoundary: revert-package-commit
```

Если невозможно однозначно сформулировать `beforeScenario`, `afterScenario` и `acceptance`, создаётся discovery package без product-code changes.

## 8. Domain routing

Начальный обязательный набор:

- `chat`;
- `images`;
- `video`;
- `audio`;
- `three-d`;
- `frontend-shell`;
- `admin-models`;
- `auth`;
- `billing`;
- `bots`;
- `gallery-feed-media`;
- `database-migrations`;
- `release-ops`;
- `documentation`.

Каждый `docs/context/*.md` содержит YAML metadata:

```yaml
status: canonical
domain: chat
read_when:
  - route:/chat
  - path:frontend/src/desktopChat/**
source_paths:
  - frontend/src/desktopChat/DesktopChatWorkspace.tsx
  - frontend/src/phone/features/chat/api.ts
  - backend/app/api/routers/phone_chat.py
owners:
  - chat
```

`context-index.json` генерируется и не редактируется вручную. Актуальность карты определяется fingerprint перечисленных `source_paths`, а не SHA всего репозитория.

## 9. Contract graph

Для cross-domain задач генерируется цепочка:

```text
frontend route/component
→ API route and schema
→ service
→ DB tables
→ worker/job states
→ integration/provider
→ billing/token effect
→ public/private media result
→ tests
→ operational acceptance
```

Граф может содержать `unknown`; он не должен создавать ложную уверенность.

## 10. Package registry и worktree

Правила:

- один package — одна ограниченная проблема;
- один package — один branch и один worktree;
- обычный лимит — до 12 production-файлов;
- generated artifacts обязательны, но не являются эксклюзивными owned files;
- новые discovered files добавляются через `scope-add` с причиной;
- выход в другой domain требует остановки и расширения Task Contract;
- `main` принадлежит только интегратору;
- Full, integration и release используют single-flight lock;
- registry расширяет существующий lock-контур, а не создаёт второй алгоритм stale/PID recovery.

Состояния:

```text
draft → discovered → ready → implementing → verifying
→ ready-for-integration → integrated
```

Дополнительные: `blocked`, `cancelled`, `superseded`.

## 11. Risk classes

### `low`

Документация и локальные изменения без product contract. Targeted checks; Full не нужен.

### `standard`

Ограниченная frontend/backend feature-задача. Task Contract, package env, targeted tests и Quick перед handoff.

### `high-assurance`

Auth, billing, migrations, durable workers, privacy, media ownership. Characterization before change, race/idempotency tests, explicit rollback, CI и независимый review.

### `release-ops`

Deploy, restart, webhook, production data/provider. Только отдельное разрешение владельца, exact-SHA receipt и operational evidence.

После двух одинаковых неудачных попыток запрещён третий broad scan. Package становится `blocked` с конкретной неизвестностью и evidence.

## 12. Verification routing

`agent verify` строит план по diff и domain metadata.

| Изменение | Минимальная проверка |
|---|---|
| chat TS/TSX | typecheck + chat unit + focused desktop/phone E2E |
| CSS/layout | typecheck/build + desktop/mobile evidence |
| API route | focused backend tests + route/schema map |
| migration | migration idempotency + backup-safe rehearsal |
| auth/billing | focused race/idempotency suite пять повторов |
| generated-map source | regenerate + `--check` |
| docs/context | metadata/schema/path/fingerprint tests |

Тесты не доказывают пользовательский результат сами по себе. UI package требует visual evidence. Provider package получает operator evidence только после разрешённого live check.

Full запускается интегратором один раз на clean candidate SHA.

## 13. Enforcement

Git hooks полезны против случайных ошибок, но обходятся через `--no-verify`; это не security boundary.

Нужна комбинация:

- versioned `.githooks/pre-commit` и `.githooks/pre-push`;
- `agent install-hooks`;
- проверка package ID и diff scope;
- запрет обычному package пушить `main`;
- integration lock;
- CI-проверка Task Contract, context metadata и generated maps;
- review интегратора;
- по возможности отдельные credentials/роль интегратора.

## 14. Agent evals и метрики

До крупного внедрения фиксируется baseline. После каждого этапа выполняется smoke-набор; в конце — полный cold eval.

Обязательные кейсы:

1. chat layout defect;
2. admin model economics;
3. image generation contract;
4. auth regression;
5. billing idempotency;
6. video provider error;
7. 3D output contract;
8. frontend+backend change;
9. documentation-only task;
10. no-code diagnosis;
11. dangerous production request;
12. недостаточно определённая задача, которая должна стать discovery package.

Автоматически измеряются:

- files opened;
- characters/bytes/lines read;
- large-file opens;
- repeated scans;
- tool calls;
- test runs и reruns;
- scope expansions;
- changed files;
- reverted/reworked lines;
- first-pass acceptance;
- elapsed active time.

Фактические input/output/cached tokens записываются только когда их предоставляет Codex/API. Не использовать `bytes / 4` как фактическую стоимость.

Цели пилота:

- не менее 70% задач принимаются без полного переделывания;
- обычная UI-задача читает менее 15 source-файлов;
- context packet ≤ 32 KiB;
- незаявленные cross-domain changes = 0;
- direct agent push в `main` = 0;
- один Full на integration candidate;
- каждый package имеет Task Contract, tests и evidence.

## 15. Самообновление

После `finish` формируется drift report:

- planned files vs discovered files;
- planned tests vs useful tests;
- omissions context card;
- ручные пояснения владельца;
- repeated scans;
- false-positive routing;
- missing graph edges.

Drift report создаёт предложение. Canonical docs не переписываются автоматически.

## 16. Очередь внедрения

### Этап 0 — `AI-EVAL-BASELINE-001`

Три холодных задания без product changes; фиксируются context, retries, tests и outcome.

### Этап 1 — `AI-CANONICAL-001`

Устранить конфликт инструкций, создать короткий вход, назначить один `docs/NOW.md`, исправить adapters и добавить instruction tests. Commit/CI/merge; без deploy.

### Этап 2 — `AI-CONTEXT-001`

Расширить существующий `docs/context`, добавить metadata schema, generated index, `agent context` и `agent symbol`.

### Этап 3 — `AI-PACKAGE-001`

Task Contract, shared registry через Git common dir, worktree lifecycle, ownership, controlled scope expansion и integration lock.

### Этап 4 — `AI-DEV-ENV-001`

Temporary DB/media/secrets, fake providers, package ports, fixtures, preview и cleanup receipts.

### Этап 5 — `AI-VERIFY-001`

Affected-test routing, compact logs, visual evidence, CI package guards и one-Full integration procedure.

### Этап 6 — `AI-CONTRACT-GRAPH-001`

UI/API/service/DB/worker/provider/billing graph и cross-domain packets.

### Этап 7 — `AI-EVAL-001`

Полный cold eval и решение владельца о rollout.

### Этап 8 — постепенная декомпозиция

После доказанного эффекта: `backend/main.py`, `newUi.tsx`, `adminModels.tsx`, крупные CSS и legacy boundaries.

## 17. Definition of Done программы

Новый агент без истории чата:

1. запускает `agent doctor` и определяет правильный repo/worktree;
2. формирует Task Contract до product changes;
3. получает ограниченный domain context;
4. не читает большие монолиты целиком без причины;
5. не пересекается с другим package;
6. использует isolated DB/providers/ports;
7. запускает релевантные проверки;
8. предъявляет evidence пользовательского результата;
9. передаёт один clean commit интегратору;
10. не смешивает `CODE COMPLETE`, `DEPLOYED` и `OPERATIONALLY VERIFIED`;
11. оставляет drift report;
12. проходит eval лучше baseline по корректности и стоимости.

## 18. Анти-паттерны

Запрещено:

- делать этот документ обязательным чтением каждого агента;
- создавать второй набор domain-карт рядом с `docs/context`;
- объявлять несколько документов единственным current backlog;
- считать незакоммиченный локальный план действующим;
- редактировать один центральный index вручную всеми агентами;
- хранить отдельный registry в каждом worktree;
- создавать новый lock-алгоритм без переиспользования существующего;
- hardcode workspace path в переносимых repo-tools;
- запускать Full после каждой маленькой правки;
- блокировать базовый контур отсутствием Maya;
- заявлять проценты улучшения без eval baseline;
- оценивать фактические токены размером файлов;
- продолжать цикл «план → критика → ещё больший план» без commit и pilot.

## 19. Активация

Этот документ остаётся review draft, пока не выполнены:

1. review границ программы;
2. реализация `AI-CANONICAL-001`;
3. focused instruction/docs tests;
4. CI на clean commit;
5. merge через интегратора;
6. указание программы в `docs/NOW.md`.
