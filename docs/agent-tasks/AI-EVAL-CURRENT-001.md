---
status: ready-for-review
canonical: false
record_role: task-contract
package: AI-EVAL-CURRENT-001
package_mode: tooling
base_sha: f1ee842f41f2192e71db7f754ad1500190e1547f
branch: codex/ai-eval-current-20260831
risk_class: low
deployment: none
---

# AI-EVAL-CURRENT-001 — текущий baseline расхода контекста

## Цель

Добавить маленький воспроизводимый harness для измерения поведения нового
coding-агента **до** появления `agent context`/`symbol` CLI.

Package не оптимизирует retrieval и не меняет продукт. Он фиксирует три
одинаковых cold cases, выдаёт готовые prompts, создаёт JSON receipt, проверяет
его структуру, привязывает receipt к fingerprint неизменного prompt и показывает
нарушения bounded-gate.

Старый issue `#71` относится к pre-change SHA и историческому состоянию до
исправления Codex project/cwd, Memory и canonical routing. Этот package измеряет
текущее состояние после этих исправлений.

## Три cases

1. `chat-model-selector` — route `/chat`, выбор модели и `chatModelId`.
2. `admin-last-admin-race` — route-level routing к `AM-009`.
3. `studio-text-to-image` — текущая image studio без legacy UI.

## Scope

Только:

```text
docs/agent-tasks/AI-EVAL-CURRENT-001.md
tools/agent_efficiency_eval.py
tools/test_agent_efficiency_eval.py
```

## Использование после merge

Каждый case выполняется в отдельном новом Codex chat с отключённой Memory.

```powershell
python tools/agent_efficiency_eval.py list
python tools/agent_efficiency_eval.py prompt chat-model-selector
python tools/agent_efficiency_eval.py template chat-model-selector `
  --output .runtime/agent-evals/current/chat-model-selector.json
```

После ответа оператор заполняет фактический receipt:

- `subjectFilesOpened` — только реально открытые предметные файлы;
- `resultAnchors` — корректно найденные owners/source paths, даже если они были
  получены из canonical context без отдельного чтения source;
- плохое поведение не скрывается: broad scans, full reads и corrections
  записываются и превращаются в `violations`, а не делают receipt нечитаемым.

Проверка:

```powershell
python tools/agent_efficiency_eval.py validate `
  .runtime/agent-evals/current/chat-model-selector.json
```

После трёх независимых runs:

```powershell
python tools/agent_efficiency_eval.py summarize `
  .runtime/agent-evals/current
```

`.runtime/` уже исключён из Git. Receipts не коммитятся.

## Что измеряется

- предметные файлы, открытые помимо routing docs;
- найденные owners/anchors;
- полные чтения защищённых монолитов;
- broad/repeated searches;
- tool calls;
- proposed/run tests;
- owner corrections;
- elapsed seconds;
- фактические token counters и их неполные/полные totals, только если их
  показывает Codex/API.

`bytes / 4`, оценка по символам и другие вычисленные «токены» запрещены.

## Bounded-gate

Passing run должен:

- быть cold session с отключённой Memory;
- использовать точный `caseFingerprint` и один общий `repoHead` для трёх runs;
- открыть обязательные routing docs и нужную context-карту;
- уложиться в 6–8 предметных файлов;
- найти case-specific owners/anchors и targeted tests;
- не читать защищённые монолиты целиком;
- не выполнять broad/repeated search;
- не требовать коррекции владельца.

Failing/partial run остаётся валидным receipt и сохраняет violations. Baseline
нельзя улучшать удалением неудачных runs.

## Non-goals

- не создавать `agent context`, symbol retrieval или affected-test router;
- не добавлять новые context-карты;
- не менять `AGENTS.md`, `AI_START_HERE.md`, `docs/NOW.md` или product docs;
- не изменять frontend/backend product code;
- не исправлять найденные chat/admin/studio defects;
- не запускать production, providers, deploy или restart;
- не коммитить receipts.

## Проверка package

```powershell
python -m pytest -q tools/test_agent_efficiency_eval.py
python tools/agent_efficiency_eval.py list
python tools/agent_efficiency_eval.py prompt admin-last-admin-race
git diff --check
```

## Следующий gate

После merge и трёх cold receipts на одном Git SHA сравнить фактические результаты. Только если
они подтверждают дорогой повторный discovery, начинать отдельный
`AI-CONTEXT-CLI-PILOT-001` для `chat` и `admin`. Этот package не разрешает
автоматически начинать следующий.
