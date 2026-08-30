---
status: active
canonical: false
record_role: active-task-contract
package: AI-CANONICAL-REPAIR-001
program: IZO_ASA Agent Control Plane
issue: 74
base_sha: 49a19e271e4e0e71d1fa6f871f828f0a233cfbdf
candidate_ref: agent/ai-canonical-repair-20260830
risk_class: low
deployment: none
---

# AI-CANONICAL-REPAIR-001 — Task Contract

## Goal

Исправить дефекты уже слитого canonical agent layer до начала context rollout,
не затрагивая product-код или production.

## User outcome

Новый coding-агент получает один непротиворечивый порядок чтения, существующие
generated paths и правдивое состояние активного package. Следующий package не
может начаться до подтверждённого закрытия repair-package.

## Before / after

```yaml
beforeScenario:
  - canonical документы задают разные reading orders
  - docs/NOW.md ссылается на отсутствующий architecture inventory
  - завершённый AI-CANONICAL-001 остаётся ready-for-review
  - program остаётся review-draft
  - post-merge findings не защищены semantic tests
afterScenario:
  - AI_START_HERE.md единолично владеет reading order
  - generated evidence paths существуют
  - AI-CANONICAL-001 является completion receipt
  - repair-package остаётся active до merge evidence
  - network production changes требуют явного owner scope
  - semantic tests предотвращают возврат дефектов
```

## Non-goals

- Не менять `frontend/**` или `backend/**` product code.
- Не менять `ops/**`, production, runtime, DB, media, secrets или providers.
- Не выполнять deploy/restart.
- Не создавать новые domain context-карты.
- Не внедрять registry, hooks, dev sandbox или affected-test routing.
- Не начинать `AI-INSTRUCTION-SCOPE-001`.

## Scope

Разрешено:

```text
AGENTS.md
AI_START_HERE.md
docs/NOW.md
docs/agent-control-plane.md
docs/agent-tasks/AI-CANONICAL-001.md
docs/agent-tasks/AI-CANONICAL-REPAIR-001.md
tools/test_agent_instructions.py
GitHub issues #69, #70, #74
```

Запрещено всё вне этого списка без письменного scope expansion.

## Acceptance

1. Frontmatter ownership marker чтения встречается только в `AI_START_HERE.md`.
2. Reading order: policy → entrypoint → NOW → scoped instructions → context card
   → active Task Contract → generated/bounded evidence → source/tests.
3. Canonical routing не содержит `architecture/generated-inventory*`.
4. Все перечисленные generated paths существуют.
5. Program имеет `status: active-program`, `canonical: true`,
   `daily_context: false`.
6. `AI-CANONICAL-001` имеет completion receipt с PR #73 и merge SHA.
7. `docs/NOW.md` показывает этот repair-package активным и блокирует next.
8. Этот Task Contract существует и остаётся active до merge evidence.
9. `AGENTS.md` запрещает VPS/FRP/DNS/tunnel/AdGuard changes без owner scope.
10. Product-code diff отсутствует.
11. CI и automated review завершены; каждый finding разобран.
12. Deployment не выполнялся.

## Required checks

```powershell
python -m pytest -q tools/test_agent_instructions.py tools/test_context_docs.py
.\tools\verify.ps1 -Mode Quick -PlanOnly
.\tools\verify.ps1 -Mode Quick
```

## Evidence and handoff

```text
base SHA
final candidate SHA
changed files
focused/Quick result
GitHub CI run
automated review result
review findings and resolution
PR number
merge SHA, only after merge
explicit NOT DEPLOYED
```

## Completion transition

Этот файл и `docs/NOW.md` нельзя помечать completed до фактического merge и
review evidence. После merge выполняется отдельный bounded status-transition
commit/PR, который:

- записывает merge SHA;
- переводит package в `completed`;
- устанавливает `active_package: none`;
- разблокирует следующий candidate;
- закрывает issues #69 и #74;
- обновляет checklist epic #70.

До status-transition package считается активным, даже если implementation PR
уже merged.
