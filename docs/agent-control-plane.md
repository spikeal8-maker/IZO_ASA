---
status: active-program
canonical: true
daily_context: false
program: IZO_ASA Agent Control Plane
master_spec: docs/stabilization-optimization-master-spec.md
updated: 2026-09-14
repository: spikeal8-maker/IZO_ASA
---

# IZO_ASA Agent Control Plane

## 1. Назначение

Это agent-specific subprogram master-ТЗ. Он отвечает только за то, чтобы coding
agents работали ограниченно, воспроизводимо и проверяемо. Общий порядок, включая
product contract, supply-chain, recovery, runtime health и Docker, задаёт
`docs/stabilization-optimization-master-spec.md`. Текущий исполняемый package
определяет только `docs/NOW.md`.

```text
owner request
→ Task Contract
→ domain/risk/change class
→ package/worktree ownership
→ remote main guard
→ machine-enforced scope
→ bounded context
→ isolated environment
→ affected verification
→ Package Health Gate
→ clean PR
```

Главный принцип: документация объясняет правила; tooling/permissions/hooks/CI/locks
обеспечивают их технически.

### 1.1. GitHub-first execution

GitHub является канонической source/integration surface: repository, `main`,
branches, PR, Issues, exact SHA, CI и сохранённые receipts. Для repository-only
работы GitHub/CI имеет приоритет над удалённым рабочим компьютером.

- Source, docs, contracts, generators, tests и supply-chain checks, которые можно
  воспроизводимо выполнить в CI, должны реализовываться и проверяться через
  GitHub Actions на exact candidate HEAD.
- D2 или другой удалённый компьютер используется только как дополнительный
  operational executor, когда evidence зависит от установленного local runtime,
  listeners/processes, Docker host, GPU/Windows-only services, файлов вне GitHub
  или production-like topology.
- Local/remote checkout не является источником истины поверх GitHub.
- Поломка remote executor/tool не блокирует repository-only работу. Подходящая
  проверка переносится в GitHub CI; недоступная внешняя сеть/scanner фиксируется
  как `EXTERNAL_VERIFICATION_UNAVAILABLE`, а не как fabricated green и не как
  повод бесконечно повторять тот же local probe.
- Уже выданный владельцем доступ к компьютеру используется только когда задаче
  действительно нужно local/runtime evidence; доступность конкретного remote
  инструмента не является prerequisite для GitHub-native работы.
- Network-dependent supply-chain scanning по возможности принадлежит CI и
  привязывает результат к exact SHA. Auto-fix и вывод secret values запрещены.
- GitHub CI не подменяет live/deploy/runtime evidence: такие утверждения требуют
  отдельной operational verification.


## 2. Переиспользовать, не дублировать

- `AGENTS.md`, `AI_START_HERE.md`, `docs/NOW.md`;
- `docs/context/*`;
- generated frontend/backend/architecture maps;
- `architecture/contract.json`;
- `tools/repository-operation-lock.ps1`;
- `tools/verify.ps1`;
- temporary DB/media roots и fake providers;
- release/backup/production safety contracts.

Запрещены второй Task registry, второй agent CLI, второй context hierarchy, второй
repository lock и второй architecture inventory.

## 3. Завершённая основа

- `AI-CANONICAL-001`: PR #73, merge `49a19e271e4e0e71d1fa6f871f828f0a233cfbdf`, `NOT DEPLOYED`.
- `AI-CANONICAL-REPAIR-001`: PR #75, merge `8e15a89aae71f71eed31a0ef490228cdbc854c7d`, `NOT DEPLOYED`.
- baseline issue #71 существует и закрывается первым.

## 4. Agent capability order

### 0. `AI-EVAL-BASELINE-001`

Read-only cold-agent baseline issue #71. Product writes запрещены.

### 1. `AI-PACKAGE-001`

- machine-readable Task Manifest;
- `changeClass` + budgets;
- shared registry through Git common dir;
- worktree lifecycle;
- one-writer ownership;
- overlap detection;
- controlled scope expansion;
- reuse existing repository lock.

### 2. `STAB-MAIN-GUARD-001`

Agent Control Plane не считается fail-closed, пока ordinary coding credential
может обновить remote `main`. Preferred: GitHub ruleset/branch protection.
Fallback при ограничениях плана: coding-agent credentials не имеют права писать
`refs/heads/main`; merge credential принадлежит только integration owner.

Local hooks являются дополнительной, но не основной защитой.

### 3. `AI-ENFORCE-001`

- versioned package/scope guards;
- forbidden paths;
- file/LOC budgets;
- dependency/migration/global-config scope checks;
- integration lock;
- CI validation;
- fail closed при undeclared diff.

### 4. `STAB-SIZE-001`

Не отдельная система. Расширяет `architecture/contract.json` и существующий
architecture inventory: protected `net non-growth`, thresholds, trends и coupling
health.

### 5. Bounded context

Последовательно:

1. `AI-INSTRUCTION-SCOPE-001`;
2. `AI-CONTEXT-SCHEMA-001`;
3. `AI-CONTEXT-PILOT-001`;
4. `AI-SYMBOL-CONTEXT-001`;
5. `AI-CONTEXT-EXPAND-001`.

Target: relevant policies/domain/symbols/routes/tests/source windows вместо broad
monolith reads.

### 6. `AI-DEV-ENV-001`

- temporary DB/media/secrets;
- fake providers;
- fixtures;
- unique ports;
- preview/cleanup receipt.

### 7. `AI-VERIFY-001`

- affected-test routing;
- compact logs;
- visual/functional evidence;
- один Full на clean integration candidate.

### 8. `AI-DECOMPOSE-*`

Только после scope/context/env/verify foundations. Правило:

```text
characterize
→ extract without behavior change
→ verify parity
→ lower budget
→ separate behavior package
```

### 9. `AI-CONTRACT-GRAPH-001`

UI → API → service → DB → worker → provider → billing/media. `unknown` вместо
догадок. Master program добавляет общий drift gate поверх graph/evidence.

### 10. `AI-EVAL-001`

Финальный independent cold eval против baseline.

Product contract, supply-chain, test-health, recovery, runtime health, performance
и Docker packages определяет master-ТЗ; они не дублируются здесь.

## 5. Единая CLI

```powershell
.\tools\agent.ps1 doctor
.\tools\agent.ps1 start -Manifest .\tasks\TASK.yaml
.\tools\agent.ps1 context
.\tools\agent.ps1 symbol -Path <path> -Symbol <name>
.\tools\agent.ps1 status
.\tools\agent.ps1 scope-add -Path <path> -Reason "..."
.\tools\agent.ps1 env-up
.\tools\agent.ps1 verify
.\tools\agent.ps1 audit
.\tools\agent.ps1 finish
.\tools\agent.ps1 eval -Suite smoke
```

Отсутствующая команда не имитируется ручной процедурой, выдаваемой за enforcement.

## 6. Self-audit cadence

После каждого implementation package:

- scope/diff;
- file/coupling growth;
- protected budgets;
- targeted tests;
- generated/context drift;
- secret/provider/dependency safety;
- user acceptance evidence.

После каждых трёх merged implementation packages — Architecture Checkpoint.
После каждой фазы — Phase Acceptance Gate + bounded cold-agent case.

## 7. Целевые метрики

```text
core instructions:              ≤12–16 KiB
domain + Task Contract:         ≤12–16 KiB
ordinary UI source reads:       <15, target ≤8
micro-ui production files:      ≤3 by default
undeclared cross-domain diff:   0
protected hotspot growth:       0
repeated broad scan:            0
first-pass acceptance:          ≥80%
ordinary-agent direct main:     0
Full per integration candidate: 1
```

Tokens учитываются только по фактическим данным агента/API.

## 8. Merge/release rules

Каждый package имеет Task Contract + feature worktree, не расширяет scope молча,
проходит targeted checks/required Quick/CI, выполняет Package Health Gate, ждёт
review и передаёт self-contained PR.

`CODE COMPLETE`, `VERIFIED`, `MERGED`, `DEPLOYED`, `OPERATIONALLY VERIFIED` не
объединяются. Production/provider actions требуют отдельной authorization.

## 9. Definition of Done Agent Control Plane

1. Cold agent определяет правильный repo/domain/package без истории чата.
2. Task scope ограничен технически.
3. Ordinary coding-agent не может писать remote `main`.
4. Один writer не пересекает другой package.
5. Protected hotspots невозможно незаметно раздувать.
6. Bounded context заменяет broad monolith scans.
7. Test environment изолирована от production.
8. Affected verification объяснимо выбирается автоматически.
9. Self-audit evidence формируется до handoff.
10. Final cold eval ≥80% first-pass и лучше baseline.
