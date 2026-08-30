---
status: ready-for-owner-review
canonical: false
package: AI-CANONICAL-001
program: IZO_ASA Agent Control Plane
repository: spikeal8-maker/IZO_ASA
base_sha: ecb02bf84ae21a46711c9b38b61784147fb9fc0a
risk_class: low
deployment: none
---

# AI-CANONICAL-001 — канонический вход для coding-агентов

## 1. Роль package

Это первый исполнимый package программы. Он не redesign и не новый анализ. Он устраняет противоречия входа для агентов и создаёт один короткий маршрут к актуальному состоянию проекта.

После завершения новый агент должен без широкого сканирования определить:

- правильный Git repository и worktree;
- главный policy-файл;
- текущий status aggregator;
- нужную существующую context-карту;
- что разрешено и запрещено в текущей задаче.

## 2. Обязательный preflight

```powershell
git rev-parse --show-toplevel
git remote get-url origin
git status --short --branch
git rev-parse HEAD
git rev-parse origin/main
git worktree list
```

Остановиться без изменений, если:

- repository не `spikeal8-maker/IZO_ASA`;
- base SHA изменился и drift не проверен;
- текущий worktree содержит чужой WIP в scope;
- другой package владеет теми же файлами;
- задача запущена из production/runtime directory, а не Git worktree.

## 3. Task Contract

```yaml
schemaVersion: 1
id: AI-CANONICAL-001
domain: documentation
riskClass: low
status: ready

goal: Создать один непротиворечивый короткий вход для всех coding-агентов IZO_ASA.
userOutcome: Новый агент однозначно определяет правильный repo, policy, current status и следующий документ без чтения исторических планов.
beforeScenario: AGENTS.md и CLAUDE.md содержат несовместимые workspace instructions; README и AGENTS.md объявляют главным документ, который сам перенаправляет в другой план; current-status содержит июльское состояние.
afterScenario: Все adapters ссылаются на один AGENTS.md; AI_START_HERE.md даёт короткий маршрут; docs/NOW.md является единственным current-status aggregator; исторические документы не объявляются текущими.

nonGoals:
  - Не менять frontend/backend product code.
  - Не создавать package registry.
  - Не создавать dev sandbox.
  - Не внедрять hooks.
  - Не перестраивать все historical documents.
  - Не выполнять deploy/restart.
```

## 4. Scope

### Разрешённые файлы

```text
AGENTS.md
AI_START_HERE.md
CLAUDE.md
GEMINI.md
.github/copilot-instructions.md
README.md
docs/NOW.md
docs/current-status.md
docs/agent-control-plane.md
tools/test_agent_instructions.py
tools/test_context_docs.py
tools/verify.ps1
```

`tools/verify.ps1` разрешён только для подключения focused instruction test без изменения semantics Quick/Full/CI.

### Запрещённый scope

```text
backend/**
frontend/**
ops/**
architecture/contract.json
backend/SYMBOL_MAP.md
docs/generated/frontend-map.*
production DB/media/secrets/runtime
```

Дополнительный файл можно включить только после записи:

```text
path
reason
scope category
проверка overlap
почему существующего scope недостаточно
```

Выход за domain `documentation` требует остановки package.

## 5. Требования к реализации

### 5.1. `AGENTS.md`

- остаётся единственным repository-wide policy;
- устраняется конфликт абсолютных workspace paths;
- repo root для инструментов определяется через Git;
- host-specific path допускается только как machine note, но не как переносимый алгоритм обнаружения repository;
- раздел documentation/plan control указывает `docs/NOW.md` как единственный current-status aggregator;
- product plans остаются scoped references и не конкурируют за статус единственной очереди;
- production safety, security, data, release и verification правила не ослабляются.

Не выполнять в этом package массовое переписывание всего `AGENTS.md`.

### 5.2. Adapters

`CLAUDE.md`, `GEMINI.md` и `.github/copilot-instructions.md`:

- от 5 до 20 строк каждый;
- направляют к `AGENTS.md`;
- не содержат собственного absolute workspace path;
- не объявляют отдельный backlog;
- не дублируют длинные security/release rules;
- могут содержать не более трёх tool-specific reminders.

### 5.3. `AI_START_HERE.md`

Не более 120 строк. Содержит:

- проверку repo через `git rev-parse --show-toplevel` и `git remote get-url origin`;
- порядок чтения;
- ссылку на `docs/NOW.md`;
- таблицу «тип задачи → существующий context document»;
- минимальный preflight;
- состояния `CODE COMPLETE`, `VERIFIED`, `DEPLOYED`, `OPERATIONALLY VERIFIED`;
- запрет product changes без Task Contract;
- запрет deploy без явного разрешения;
- правило: historical docs читаются только по причине.

Не дублирует подробные production, backup и security rules из `AGENTS.md`.

### 5.4. `docs/NOW.md`

В первом package допускается tracked snapshot, если generator ещё не реализован. Он явно помечается:

```yaml
status: generated-snapshot
source_of_truth: git-and-runtime-evidence
```

Содержит только:

- verified repository/main SHA;
- known live release либо `unknown/not reverified`;
- active program/package lanes;
- next package;
- blockers;
- canonical context documents;
- дату и команды проверки.

Не содержит длинных test logs, PID, старых worktree и исторических handoff.

### 5.5. `docs/current-status.md`

Один из допустимых вариантов:

1. заменить коротким redirect/documentation stub на `docs/NOW.md`;
2. пометить как historical snapshot и убрать утверждение, что он current.

Он не должен продолжать сообщать агенту состояние июля 2026 года как актуальное.

### 5.6. `README.md`

- убрать `Prototype` как описание текущего production-продукта;
- в начале documentation map указать `AI_START_HERE.md` для coding-агентов;
- не называть `engineering-optimization-master-plan-20260719.md` единственной текущей очередью;
- сохранить runbooks как references;
- не превращать README в копию `AGENTS.md`.

### 5.7. Tests

Создать `tools/test_agent_instructions.py`.

Минимальные проверки:

- adapters существуют и ссылаются на `AGENTS.md`;
- adapters находятся в диапазоне 5–20 строк;
- adapters не содержат конфликтующих drive-root paths;
- `AI_START_HERE.md` существует и ≤ 120 строк;
- ровно один документ объявлен current-status aggregator;
- `docs/NOW.md` содержит обязательные metadata и sections;
- paths из короткого entry document существуют;
- historical snapshot не может называться active/current backlog;
- README не называет продукт prototype;
- `AGENTS.md` и README не объявляют разные единственные current backlogs;
- focused test подключён в существующий verify entrypoint.

Существующий `tools/test_context_docs.py` расширять только если это необходимо для проверки новых ссылок; не создавать второй конкурирующий context-index в этом package.

## 6. Acceptance

1. Product-code diff отсутствует.
2. Нет указаний работать одновременно в `E:\...` и `D:\...`.
3. Новый агент читает не более трёх файлов до выбора domain: `AGENTS.md`, `AI_START_HERE.md`, `docs/NOW.md`.
4. Ровно один current-status aggregator.
5. Нет двух документов, объявленных единственной исполняемой очередью.
6. `AI_START_HERE.md` ≤ 120 строк.
7. Adapters по 5–20 строк.
8. Focused tests зелёные.
9. `verify.ps1 -Mode Quick -PlanOnly` показывает instruction test.
10. Diff не содержит product code, secrets и runtime paths.
11. Один self-contained commit.
12. Commit не считается deployed.

## 7. Проверки

```powershell
python -m pytest -q tools/test_agent_instructions.py tools/test_context_docs.py
.\tools\verify.ps1 -Mode Quick -PlanOnly
.\tools\verify.ps1 -Mode Quick
```

Если Quick блокируется только live/runtime prerequisite:

- зафиксировать точный blocker;
- отдельно доказать focused tests;
- не менять runtime, Caddy, listeners или production ради docs package.

## 8. Запрещённые действия

- `git reset --hard`;
- автоматический stash чужой работы;
- direct push в `main`;
- deploy/restart;
- production DB/media/secrets changes;
- VPS/FRP/DNS changes;
- real provider calls;
- создание нового master plan вместо реализации;
- расширение scope без причины;
- изменение product code для прохождения docs tests;
- ослабление существующих safety contracts.

## 9. Формат команды агенту

```text
Реализуй package AI-CANONICAL-001 строго по
`docs/agent-tasks/AI-CANONICAL-001.md`.

Перед изменениями выполни preflight и сообщи exact HEAD/origin/main/worktree.
Работай только в отдельной feature-ветке/worktree, не в main.
Не меняй frontend, backend, ops, production или runtime.
Не создавай ещё один план: реализуй требования package.
После каждой логической правки запускай только focused tests.
Перед handoff запусти указанные проверки, проверь diff и создай один commit.
Не выполняй deploy/restart/push в main.

Отчёт раздели на:
IMPLEMENTED
TESTED
COMMITTED
PUSHED/PR
MERGED
DEPLOYED
BLOCKED
```

## 10. Handoff contract

Package считается `ready-for-integration`, только если отчёт содержит:

```text
base SHA
branch/worktree
changed files
scope changes
focused test results
Quick result или точный blocker
commit SHA
remaining risks
explicit statement: NOT DEPLOYED
```

Документы становятся действующими только после review, green checks и merge в `main`.
