---
status: owner-directed-master-spec
role: stabilization-optimization-program
daily_context: false
updated: 2026-09-14
repository: spikeal8-maker/IZO_ASA
source_baseline: 9128f99f825bdd4533dd68c44b5e2f4586719f7f
current_status_owner: docs/NOW.md
agent_program: docs/agent-control-plane.md
production_change_authorized: false
program_version: 2.0
---

# IZO_ASA — ТЗ на стабилизацию, оптимизацию и подготовку к AI-разработке

## 1. Назначение и границы

Это каноническое master-ТЗ программы стабилизации IZO_ASA. Оно определяет:

- что сохраняется без изменения продуктового смысла;
- что стабилизируется;
- что разрешено переписывать только через bounded extraction;
- какие механизмы нужно дописать;
- точный dependency order packages;
- канонические mutation surfaces каждого этапа;
- когда конкретный файл разрешено менять;
- какие проверки обязательны после package, после трёх merged implementation
  packages и после каждой фазы;
- при каких условиях работа останавливается для repair/extraction;
- как стандартизируется DEV/TEST через Docker;
- какие дополнительные gates нужны для supply-chain, данных, recovery,
  наблюдаемости и performance;
- почему production containerization не является частью основной bot-stability
  программы.

Документ не заменяет:

- `AGENTS.md` — repository-wide invariants;
- `AI_START_HERE.md` — порядок чтения coding-агента;
- `docs/NOW.md` — единственный current-status/router;
- `docs/agent-control-plane.md` — agent-specific subprogram;
- `docs/context/*` — bounded domain context;
- `architecture/contract.json` — reviewed machine-readable architecture;
- `docs/generated/*`, `backend/SYMBOL_MAP.md` — generated evidence;
- product-specific contracts;
- release/backup/restore runbooks.

Master-ТЗ имеет `daily_context: false`: обычный coding-agent не читает его целиком
для каждой задачи. Он читает `AGENTS → AI_START_HERE → NOW → scoped policy →
domain card → Task Contract → bounded evidence`.

Конкретный package становится исполняемым только после status transition в
`docs/NOW.md` и отдельного Task Contract.

---

# 2. Целевой результат

После основной программы типовая небольшая задача должна выглядеть так:

```text
запрос владельца
→ router определяет domain/risk/change class
→ Task Contract
→ отдельный package/worktree + один writer
→ machine-enforced scope
→ bounded context/symbol window
→ локальное изменение
→ affected tests
→ Package Health Gate
→ read-only review
→ clean PR
```

Целевой профиль `micro-ui`:

```text
source files read:             target ≤8, hard rollout target <15
production files changed:      ≤3 by default
changed production LOC:        ≤150 by default
undeclared cross-domain diff:  0
protected-hotspot growth:      0
broad monolith reads:          0 без recorded reason
repeated broad scans:          0
production/provider actions:   0
```

Главная метрика программы — **change locality**: сколько системы агент обязан
понять и имеет право изменить ради одного пользовательского результата.

Завершение программы не означает «проект идеален навсегда». Оно означает, что
проект достиг измеримого bot-stable/maintainable baseline, а дальнейшие изменения
не могут бесконтрольно ухудшать этот baseline.

---

# 3. Что сохраняем

Не переписывать продукт с нуля. Сохраняются:

- Web, Telegram Mini App, MAX Mini App;
- image/video/chat/audio/3D, gallery/feed, profile, billing, admin;
- пользовательские данные и media;
- действующие identity/billing/API contracts до отдельной миграции;
- modular monolith как базовый стиль;
- SQLite как текущий production datastore;
- Windows production до отдельного container-production gate;
- ComfyUI/Ollama/Qwen ASR contracts;
- внешние provider contracts;
- exact-SHA release/rollback model;
- раздельные статусы `CODE COMPLETE`, `VERIFIED`, `MERGED`, `DEPLOYED`,
  `OPERATIONALLY VERIFIED`.

Без отдельного owner-approved program запрещено совмещать со стабилизацией:

- big-bang rewrite;
- microservices ради стиля;
- SQLite → PostgreSQL;
- массовый redesign;
- смену auth model;
- production Docker cutover;
- перенос GPU runtime;
- deploy/restart/provider/network action.

---

# 4. Подтверждённый baseline и исходный риск

На baseline:

```text
backend/main.py                 19 749 lines
frontend/src/newUi.tsx           3 695 lines
frontend/src/LegacyApp.tsx       3 600 lines
frontend/src/adminModels.tsx     2 300 lines
frontend/src/index.css           2 501 lines
frontend/src/newStudioV3.css     6 071 lines
frontend/src/newUi.css           3 143 lines
backend/test_feed_v2.py          2 346 lines
```

Generated inventory также фиксирует множество routes/workers/tables и текущие
runtime/integration boundaries. Эти значения — debt baseline, не target.

Главная проблема: repository instructions уже сильнее, чем физическая локальность
кода. Бот знает правила, но небольшая задача всё ещё может требовать понимания
слишком большой части системы.

Уже существуют и должны переиспользоваться:

- `architecture/contract.json`;
- `tools/generate_architecture_inventory.py`;
- `tools/generate_frontend_map.mjs`;
- `tools/generate_backend_map.py`;
- `backend/SYMBOL_MAP.md`;
- `tools/verify.ps1`;
- `tools/repository-operation-lock.ps1`;
- `docs/context/*`;
- isolated CI с temporary DB/media/secrets и disabled providers.

Нельзя создавать параллельный inventory, второй repository lock, второй context
hierarchy или второй user-facing agent CLI.

---

# 5. Один факт — один владелец

| Уровень | Канонический владелец | Содержимое |
|---|---|---|
| repository policy | `AGENTS.md` | долговечные invariants/safety |
| reading/router | `AI_START_HERE.md` | порядок чтения, domain/risk routing |
| current status | `docs/NOW.md` | completed/active/next, blockers |
| master program | этот документ | последовательность стабилизации |
| agent subprogram | `docs/agent-control-plane.md` | agent capabilities/tooling |
| domain context | `docs/context/*.md` | bounded source/tests/contracts |
| reviewed architecture | `architecture/contract.json` | owners/limits/listeners/workers/integrations |
| generated evidence | `docs/generated/*`, `backend/SYMBOL_MAP.md` | наблюдаемое состояние source |
| package contract | Task Manifest/issue/PR | outcome/scope/budgets/acceptance |
| product behavior | bounded source modules | runtime behavior |
| operational contract | `ops/*`, runbooks | release/backup/runtime operations |

Дублирование одного факта в нескольких слоях должно сводиться ссылкой или удаляться.

---

# 6. Политика изменения ключевых файлов

## 6.1. Управляющие документы и tooling

### `AGENTS.md`

Менять только при изменении repository-wide invariants. Не превращать в backlog.

### `AI_START_HERE.md`

Менять только при изменении reading order/routing/risk classification.

### `docs/NOW.md`

Остаётся коротким status/router. Hard limit не повышается ради нового roadmap.
Подробности выносятся в master/package docs.

### `docs/agent-control-plane.md`

Только agent capabilities/order/metrics. Не накапливать receipts.

### `architecture/contract.json`

Менять только при сознательном изменении reviewed architecture contract. Нельзя
повышать `file_limits`/`symbol_limits` ради зелёного gate. После extraction лимит
снижается в том же package.

### `docs/generated/*`, `backend/SYMBOL_MAP.md`

Только generator output. Ручное редактирование запрещено.

### `tools/verify.ps1`

Остаётся orchestrator verification. Запрещено помещать product business logic,
одноразовый bypass или workaround ради одного package.

### `tools/repository-operation-lock.ps1`

Расширять существующий lock contract; второй lock implementation запрещён.

## 6.2. Product hotspots

### `backend/main.py`

Frozen compatibility/composition hotspot.

Разрешено:

- минимальный wiring после extraction;
- behavior-preserving extraction;
- incident bugfix с минимальным diff и `net non-growth`.

Запрещено:

- новое business logic;
- новый persistent worker/service/domain implementation;
- увеличение line/symbol budget.

### `frontend/src/newUi.tsx`

Feature-package не увеличивает файл. Если boundary не выделена — сначала отдельный
extraction package, затем отдельный behavior package.

### `frontend/src/adminModels.tsx`

Characterize → extract bounded admin feature → lower budget → затем behavior.

### `frontend/src/LegacyApp.tsx`

Frozen compatibility. Новые функции запрещены без compatibility-specific package.

### `frontend/src/newStudioV3.css`, `frontend/src/newUi.css`, `frontend/src/index.css`

Новый feature не добавляет global selectors без доказанной необходимости.
Предпочтение — feature/component scoped CSS. Decomposition не смешивается с
redesign.

### Крупные legacy test files

Также `net non-growth`. При активном touch cohesive test group выносится в новый
bounded test module.

---

# 7. Quality budgets и anti-gaming

## 7.1. Protected hotspots

Для protected paths:

- feature package: delta ≤0;
- extraction package: delta <0;
- после extraction `max_lines` уменьшается в том же commit;
- уменьшение одного hotspot не компенсирует рост другого;
- временный uncommitted growth допустим только если итоговый diff уменьшает debt.

## 7.2. Новые handwritten modules

```text
≤500 lines       нормальный диапазон
501–750          decomposition review + записанная причина
>750             hard fail для обычного нового source module
```

Ориентиры:

```text
React component         желательно ≤300
hook/service module     желательно ≤350–500
feature-scoped CSS      желательно ≤400
new test module         желательно ≤500–700
```

## 7.3. Нельзя играть метрикой размера

Architecture audit одновременно контролирует:

- cross-domain imports;
- fan-in/fan-out;
- circular dependencies;
- duplicate services/API facades/contracts;
- CSS overlap/global specificity;
- routes/workers/integrations without owner;
- orphan/dead compatibility code;
- test locality;
- context packet size;
- filesOpened и repeated scans cold-agent.

Разбиение одного монолита на десять тесно связанных файлов без уменьшения blast
radius не считается успешной оптимизацией.

## 7.4. Trend rule

Если boundary вырос >15% за три implementation packages и рост не является новым
самостоятельным bounded module, следующий feature package блокируется до
Architecture Checkpoint.

---

# 8. Change classes

Каждый package имеет `riskClass` и `changeClass`.

| changeClass | Назначение | Default budget |
|---|---|---:|
| `micro-ui` | кнопка/текст/local layout | ≤3 prod files, ≤150 LOC |
| `feature-ui` | один bounded UI flow | ≤8 prod files, ≤500 LOC |
| `backend-feature` | один backend domain | ≤6 source modules |
| `bugfix` | локальный regression | минимальный reproducible diff |
| `extraction` | behavior-preserving decomposition | hotspot net decrease |
| `architecture` | tooling/contracts/maps | no product behavior change |
| `dev-env` | dev/test environment | no production runtime change |
| `security-maintenance` | dependency/security remediation | no unrelated behavior |
| `release-ops` | production/release/network | separate authorization |

Budget overflow приводит к `SCOPE_EXPANSION_REQUIRED`, а не к молчаливому росту.

---

# 9. Обязательная структура Task Manifest

```yaml
id:
goal:
userOutcome:
beforeScenario:
afterScenario:
nonGoals: []
domain:
riskClass:
changeClass:
declaredFiles: []
allowedPatterns: []
forbiddenPatterns: []
maxProductionFiles:
maxChangedLines:
acceptance: []
requiredEvidence: []
targetedTests: []
fileGrowthExpectations: []
forbiddenOperations: []
rollbackBoundary:
```

Handoff всегда отдельно показывает:

```text
IMPLEMENTED
TESTED
PACKAGE-HEALTH
FILE-GROWTH
SCOPE-VIOLATIONS
SECURITY/DEPENDENCY
DATA/RECOVERY (если применимо)
COMMITTED
PUSHED/PR
MERGED
DEPLOYED
OPERATIONALLY VERIFIED
BLOCKED
```

---

# 10. Три уровня самоконтроля

## 10.1. После каждого implementation package — Package Health Gate

Проверить:

1. полный diff и production file count;
2. declared/allowed/forbidden scope;
3. changed LOC/bytes;
4. protected file/symbol limits;
5. новые modules >500/>750;
6. dependency/cycle/cross-domain changes;
7. duplicate/parallel implementation risk;
8. generated-map drift;
9. context/docs drift;
10. targeted tests и locality;
11. secret/provider/production safety;
12. dependency/security delta;
13. rollback boundary;
14. user-visible before/after acceptance.

## 10.2. После каждых 3 merged implementation packages — Architecture Checkpoint

Проверить:

- hotspot trend;
- modules >500/>750;
- cross-domain dependency count;
- duplicate API/services/styles;
- route/table/worker growth;
- ownerless runtime components;
- orphan compatibility code;
- test suite growth/flakiness/warnings;
- source/context/generated drift;
- cold-agent context cost;
- какие следующие features требуют extraction.

Checkpoint read-mostly. Он может открыть bounded repair/extraction package, но не
смешивает аудит и массовый refactor.

## 10.3. После каждой фазы — Phase Acceptance Gate

Обязательны:

- package-specific acceptance;
- required Quick/CI;
- bounded cold-agent scenario;
- metric comparison с началом фазы;
- file/coupling trend;
- security/dependency delta;
- remaining debt;
- rollback evidence.

Ухудшение ключевой метрики блокирует автоматический переход к следующей фазе.

## 10.4. Stop-the-line conditions

Следующий ordinary feature package не стартует, если обнаружено хотя бы одно:

- незаявленный cross-domain diff;
- direct ordinary-agent mutation `main`;
- новый high/critical dependency vulnerability без exception;
- protected hotspot growth;
- новый ownerless persistent worker/route/integration;
- stale generated/contract evidence;
- failed recovery/data-integrity rehearsal в затронутой data boundary;
- critical product flow без regression coverage после изменения его contract;
- повторяющийся flaky/failing test, скрывающий acceptance.

---

# 11. Dependency order реализации

## PHASE 0 — измеримая точка A

### `AI-EVAL-BASELINE-001` / issue #71

**Purpose:** измерить сегодняшнюю стоимость/точность cold-agent.

**Writes:** product writes запрещены. Разрешены только bounded evaluation receipts.

**Зафиксировать:**

- filesOpened/largeFilesOpened;
- repeatedScans/toolCalls;
- proposedDomains/files;
- routing mistakes;
- ownerCorrections;
- factual tokens, если доступны;
- baseline file sizes/routes/tables/workers;
- baseline test duration/warnings;
- baseline dependency audit summary.

**Exit:** точка A зафиксирована; top failure modes известны.

---

## PHASE 1 — package ownership и физическая защита `main`

### `AI-PACKAGE-001`

**Canonical mutation surface:**

```text
tools/agent.ps1                         NEW canonical CLI
tools/agent_system/package.py           NEW
tools/agent_system/registry.py          NEW
tools/repository-operation-lock.ps1     EXTEND, do not duplicate
tools/test_agent_package.py             NEW
```

**Реализовать:** Task Manifest, worktree lifecycle, one-writer ownership,
overlap detection, controlled scope expansion.

### `STAB-MAIN-GUARD-001`

**Purpose:** убрать класс ошибок «бот случайно записал в main».

**Mutation/config surface:**

```text
.github/workflows/ci.yml                validation only
tools/agent_system/main_guard.py        NEW or same package guard module
repository settings / GitHub ruleset    external reviewed configuration
agent credentials                       external permission boundary
```

**Required outcome:**

1. preferred: branch protection/ruleset запрещает direct push;
2. если текущий GitHub plan не позволяет достаточную protection — coding-agent
   credentials не имеют права обновлять `refs/heads/main`;
3. merge выполняет только integration owner/integration credential;
4. repo hooks остаются дополнительной, а не единственной защитой.

**Acceptance:** попытка ordinary coding-agent записать `main` получает отказ до
изменения remote ref.

**Exit:** one-writer/package ownership + remote main guard доказаны тестом.

---

## PHASE 2 — fail-closed scope и architecture health

### `AI-ENFORCE-001`

**Canonical surface:**

```text
tools/agent.ps1
tools/agent_system/enforce.py            NEW
tools/verify.ps1
.github/workflows/ci.yml
versioned hooks location                  one canonical implementation
tools/test_agent_enforce.py              NEW
```

**Fail closed на:** undeclared path, forbidden path, owner mismatch, unauthorized
migration/dependency/global-config change, budget overflow, invalid manifest.

### `STAB-SIZE-001`

Не создавать второй inventory. Расширить:

```text
architecture/contract.json
tools/generate_architecture_inventory.py
docs/generated/architecture-inventory.*
tools/test_architecture_inventory.py     existing/new focused tests
```

Добавить protected flag, soft/hard thresholds, current/baseline delta, 3-package
trend и coupling-health summary.

**Acceptance:** искусственный рост protected hotspot fail; extraction с decrease +
lowered budget pass.

**Exit:** scope и structural regression технически не проходят green package.

---

## PHASE 3 — scoped instructions и bounded context

Последовательность:

1. `AI-INSTRUCTION-SCOPE-001`;
2. `AI-CONTEXT-SCHEMA-001`;
3. `AI-CONTEXT-PILOT-001`;
4. `AI-SYMBOL-CONTEXT-001`;
5. `AI-CONTEXT-EXPAND-001`.

**Canonical surface:**

```text
backend/AGENTS.md                         NEW scoped policy
frontend/AGENTS.md                        NEW
ops/AGENTS.md                             NEW
docs/AGENTS.md                            NEW
docs/context/**
docs/generated/context-index.*
tools/agent.ps1
tools/agent_system/context.py             NEW
tools/generate_context_index.py           NEW
existing frontend/backend maps            REUSE
```

**Exit:** ordinary UI cold task читает <15 source files, target ≤8; no unexplained
full reads hotspots; repeated broad scans = 0.

---

## PHASE 4 — продуктовый regression contract и supply-chain quality floor

### `STAB-PRODUCT-CONTRACT-001`

**Проблема:** существующий `TEST_PLAN.md` полезен, но не является достаточным
machine-readable current contract всех критичных пользовательских journeys.

**Canonical surface:**

```text
architecture/product-flows.json           NEW reviewed critical-flow contract
tools/generate_product_flow_map.py         NEW deterministic generator
docs/generated/product-flow-map.*          GENERATED
TEST_PLAN.md                                concise human entry/update
tests/e2e or existing focused tests         link, not duplicate
```

Каждый critical flow содержит: id, user surface, auth state, entry route, API
chain, durable result, billing/data side effects, expected failures, owner,
minimum automated evidence.

Минимальные flows: login/session, image generation, result/gallery, publish/feed,
billing/payment state, chat, video, audio, Telegram/MAX trusted entry, admin
critical operations.

**Acceptance:** изменение critical flow contract без связанного regression test
или explicit migration package fail.

### `STAB-SUPPLY-CHAIN-001`

**Current evidence:** CI должен учитывать фактические npm/Python dependency risks,
а не только lockfile наличие.

**Canonical surface:**

```text
frontend/package.json
frontend/package-lock.json
backend/requirements.txt
architecture/security-policy.json          NEW reviewed thresholds/exceptions
tools/supply_chain_audit.py                 NEW
.github/workflows/ci.yml
tools/verify.ps1
```

**Policy:**

- baseline existing vulnerabilities отдельно инвентаризируются;
- новые critical/high vulnerabilities fail closed;
- existing high/critical не становятся вечным baseline: каждый имеет issue,
  owner, rationale, remediation path и expiry;
- lockfile updates выполняются отдельными dependency packages;
- secret scanning обязателен для changed files/repo history boundary;
- license policy проверяется для новых production dependencies;
- auto-fix без review запрещён.

### `STAB-TEST-HEALTH-001`

**Purpose:** CI не должен быть зелёным ценой flaky tests, растущих warnings или
неубираемых temp resources.

Контролировать:

- failed/flaky/retried tests;
- warning count by category;
- cleanup errors;
- suite runtime trend;
- tests with hidden network/provider access.

**Exit phase:** critical product flow contract существует; security delta
контролируется; test-health baseline определён и не ухудшается.

---

## PHASE 5 — isolated dev environment и affected verification

### `AI-DEV-ENV-001`

**Surface:**

```text
tools/agent.ps1
tools/agent_system/env.py                  NEW
backend/test_support/**                    REUSE/EXTEND
.runtime/**                                local only, never Git data
tests for cleanup/isolation
```

Temporary DB/media/secrets, fake providers, unique ports, cleanup receipt.

### `AI-VERIFY-001`

**Surface:**

```text
tools/agent.ps1
tools/agent_system/verify.py               NEW
architecture/contract.json                 reviewed impact semantics
tools/verify.ps1
tools/generate_frontend_map.mjs            REUSE
tools/generate_architecture_inventory.py   REUSE
.github/workflows/ci.yml
```

Связать changed path/symbol → domain/contracts → unit/component/integration/e2e.
Full — один раз на clean integration/release candidate.

**Exit:** micro-task не запускает unrelated full-system verification; environment
не имеет доступа к production data/providers.

---

## PHASE 6 — Docker DEV/TEST

### `DOCKER-DEV-001`

Docker вводится только после scope/context/env/verify foundations.

**Surface:**

```text
ops/docker/dev/compose.yml                  NEW
ops/docker/dev/Dockerfile.backend           NEW
ops/docker/dev/Dockerfile.frontend          if justified
ops/docker/dev/.env.example                 secret-free
.dockerignore
backend/app/config.py                       only portable config changes
tools/agent.ps1                             env-up/env-down integration
```

**Portability audit:** Windows paths, DPAPI-only assumptions, localhost,
subprocess/service control, filesystem semantics, provider endpoints, GPU deps,
persistence roots.

ComfyUI/Ollama/Qwen остаются host-native/fake на этом этапе.

**Exit:** clean machine/agent поднимает безопасную DEV/TEST environment одной
командой; Windows production не меняется.

---

## PHASE 7 — frontend hotspot decomposition

### `AI-DECOMPOSE-FRONTEND-*`

Не массовый rewrite. Выбирать boundary по фактическим touch points.

Целевое направление:

```text
StudioShell
features/
  navigation/
  generation/
  result/
  history/
  gallery/
  profile/
  billing/
  video/
  audio/
  chat/
```

Feature по возможности владеет component + hook/state + API facade + scoped CSS
+ tests.

Порядок каждой extraction:

```text
characterization
→ extract without behavior change
→ targeted parity tests
→ update maps/context
→ lower hotspot budget
→ merge + checkpoint
→ separate feature package
```

**Exit:** новая небольшая UI-функция обычно живёт в одной feature boundary;
global CSS growth = 0; cold-task locality улучшается.

---

## PHASE 8 — backend hotspot decomposition

### `AI-DECOMPOSE-BACKEND-*`

Canonical owners уже существуют в:

```text
backend/app/api/**
backend/app/billing/**
backend/app/database/**
backend/app/integrations/**
backend/app/lifespan/**
backend/app/security/**
backend/app/services/**
backend/app/storage/**
```

Не создавать `backend_new`, `core2`, `services_new`.

Порядок: characterization → route/service/data boundary → extraction → parity →
maps/context → lower `main.py` budget → отдельный behavior package.

Priority определяется activity/blast radius: workers, generation/recovery, feed,
auth, billing/payments, media lifecycle, admin operations.

**Exit:** новое business logic не попадает в `backend/main.py`; composition shell
имеет устойчивый downward trend.

---

## PHASE 9 — data integrity, recovery, runtime health и performance floor

### `STAB-DATA-RECOVERY-001`

Существующие backup/restore runbooks переиспользуются. Не создавать второй
production backup mechanism.

**Проверить на безопасных копиях:**

- SQLite `quick_check`/integrity;
- migration ledger/checksum compatibility;
- backup creation via supported mechanism;
- restore rehearsal в isolated location;
- media/database referential consistency;
- startup после restore;
- rollback boundary;
- RPO/RTO фактически измерены для rehearsal, не придуманы.

**Acceptance:** restore rehearsal создаёт receipt и не затрагивает production.

### `STAB-RUNTIME-HEALTH-001`

Каждый persistent worker/listener/integration имеет owner, durable state,
recovery, retry/idempotency, health evidence и понятное degraded state.

`watchdog: missing` для production-critical persistent worker должен быть либо
закрыт, либо иметь явный approved waiver с rationale.

Добавить/уточнить readiness отдельно от process-is-running.

### `STAB-PERFORMANCE-001`

Сначала измерить deterministic baseline, затем задать budgets. Не использовать
внешнюю AI/provider latency как жёсткий CI gate.

Контролировать минимум:

- frontend bundle/build size trend;
- app startup/readiness time;
- latency локальных deterministic API endpoints;
- SQLite hot-path/query regressions там, где есть measurable scenario;
- worker backlog/loop health;
- test/CI duration;
- memory/resource regression для deterministic dev/test workloads.

Default rule: >10–15% unexplained regression требует review, а hard threshold
фиксируется только после baseline package.

**Exit phase:** recovery rehearsal проходит; persistent runtime имеет health
contracts; deterministic performance не деградирует бесконтрольно.

---

## PHASE 10 — contract graph и drift

### `AI-CONTRACT-GRAPH-001`

Описывать:

```text
UI → API → service → DB → worker → provider → billing/media result
```

Использовать `unknown`, а не догадки.

### `STAB-DRIFT-001`

Расширять существующие generators/`verify.ps1`, не создавать второй audit engine.

CI обнаруживает:

- source/context mismatch;
- stale generated maps;
- ownerless route/worker/integration;
- undeclared cross-domain dependency;
- file/symbol budget drift;
- duplicate ownership;
- stale contract edge;
- critical product-flow test drift;
- security-policy exception expiry.

**Exit:** существенный architectural/product/security drift невозможно незаметно
протащить в green package.

---

## PHASE 11 — финальный cold-agent acceptance

### `AI-EVAL-001`

Независимые cases:

1. micro UI;
2. bounded backend behavior;
3. chat;
4. admin economics;
5. diagnosis-only;
6. extraction;
7. dependency/security maintenance;
8. data-safe migration/verification case без production mutation.

Метрики:

```text
filesOpened
largeFilesOpened
filesChanged
crossDomainViolations
repeatedScans
toolCalls
ownerCorrections
firstPassAcceptance
factualTokenUsage
verificationTime
```

Bot-stability targets:

- first-pass acceptance ≥80%;
- ordinary UI source reads <15, target ≤8;
- undeclared cross-domain changes = 0;
- merged scope violations = 0;
- protected hotspot growth = 0;
- repeated broad scans = 0;
- unauthorized production/release action = 0;
- ordinary coding-agent direct main writes = 0.

**Exit:** результат лучше baseline и все program-wide DoD gates ниже выполнены.

---

## PHASE 12 — optional container readiness/shadow

Не входит в обязательный bot-stability DoD.

### `CONTAINER-READY-001`

Абстрагировать только доказанные portability blockers: Windows paths, localhost,
DPAPI coupling, service-control/domain coupling, storage/media roots,
readiness/shutdown, provider endpoints.

### `CONTAINER-SHADOW-001`

Containerized app запускается на отдельном порту и безопасных данных. Проверить
frontend/API/jobs/storage/shutdown/resource parity. Production users не
переключаются.

---

## PHASE 13 — optional hybrid production Docker

Только отдельный `high-assurance/release-ops` program:

```text
Windows host
├── approved edge/FRP
├── ComfyUI host-native GPU
├── Ollama host-native GPU
├── Qwen ASR host-native GPU
└── Docker: IZO application/backend/frontend/workers
```

Обязательны exact image identity, persistent volumes, consistent SQLite backup,
portable secrets, readiness/health, shadow/canary, rollback на Windows runtime.

Docker migration нельзя совмещать с SQLite → PostgreSQL.

GPU containers/Linux migration — отдельная будущая программа.

---

# 12. Минимальные проверки по типу изменений

| Изменение | До | После |
|---|---|---|
| extraction | characterization/regression | parity + map + lower budget |
| micro-ui | focused component/browser baseline | targeted + desktop/mobile evidence |
| backend feature | relevant contract/unit baseline | service/API + Quick |
| worker/job | lifecycle/idempotency baseline | focused race/idempotency x5 |
| auth/billing | security boundary baseline | focused security/race x5 + review |
| dependency update | audit + lockfile diff | audit no worse + targeted behavior |
| architecture/tooling | generator check | tool tests + deterministic `--check` + Quick |
| dev environment | isolated CI baseline | temp/fake cleanup + no prod access |
| Docker DEV | native dev smoke | clean build/recreate parity |
| data/recovery | backup/restore preflight on copy | integrity + restore receipt |
| release-ops | runbook preflight | exact-SHA operational evidence |

---

# 13. Program-wide quality floor

Программа не считается завершённой только потому, что боты читают меньше файлов.
Нужны одновременно пять уровней качества.

## 13.1. Agent safety

- scope enforced mechanically;
- one writer/package;
- direct main write denied;
- bounded context;
- affected verification;
- no unauthorized production actions.

## 13.2. Architecture health

- protected hotspots не растут;
- новые ordinary modules не превышают hard thresholds;
- ownerless routes/workers/integrations = 0;
- no silent duplicate ownership;
- cross-domain dependency trend объясним и bounded.

## 13.3. Product regression safety

- critical product flows имеют owners и minimum automated evidence;
- behavior-preserving extraction доказывает parity;
- user-visible change имеет before/after acceptance;
- legacy compatibility меняется только отдельным contract.

## 13.4. Security/supply-chain

- secret scan clean для changed scope;
- новые critical/high dependency vulnerabilities = 0;
- существующие exceptions time-bounded и tracked;
- new production dependency проходит license/security review;
- lockfile changes принадлежат отдельному package или явному scope.

## 13.5. Data/runtime recoverability

- migration checksums/ledger consistent;
- isolated restore rehearsal проходит;
- persistent workers имеют recovery/health evidence;
- deterministic performance/resource budgets не имеют unexplained regression.

---

# 14. Definition of Done основной программы

Основная программа завершена только когда одновременно выполнено:

1. Cold agent правильно определяет repo/domain/package без истории чата.
2. Task scope проверяется технически, не только текстом.
3. Coding-agent не может записать `main` напрямую.
4. Один writer не пересекает чужой package незаметно.
5. Ordinary UI task не требует чтения больших монолитов.
6. Protected hotspots не растут и имеют downward trend при touch.
7. Новый business code находится в bounded modules.
8. File/coupling/architecture drift автоматически блокирует regression.
9. Critical product flows имеют current machine-readable contract и tests.
10. New high/critical dependency vulnerabilities не допускаются.
11. Existing high/critical dependency debt имеет bounded remediation/expiry.
12. Test-health baseline не деградирует: flaky/warning/cleanup debt tracked.
13. Isolated dev/test не использует production DB/media/providers.
14. Docker DEV/TEST воспроизводим и не является условием Windows production.
15. Affected tests выбираются автоматически и объяснимо.
16. Restore rehearsal на безопасной копии проходит с evidence.
17. Persistent runtime components имеют owner/recovery/health semantics.
18. Deterministic performance budgets не имеют unexplained regression.
19. Cold-agent first-pass acceptance ≥80%.
20. Undeclared cross-domain changes = 0.
21. Merged scope violations = 0.
22. Unauthorized production/release actions = 0.
23. Каждый третий implementation package оставляет Architecture Checkpoint.
24. Каждая фаза закрывается Phase Acceptance Gate.
25. Production Docker не требуется для достижения основной цели.

Если хотя бы один обязательный пункт не выполнен, программа не получает статус
`BOT-STABILITY ACCEPTED`.

---

# 15. Порядок следующей работы

После merge master-spec первым остаётся существующий read-only package:

```text
AI-EVAL-BASELINE-001
```

Далее dependency chain:

```text
AI-EVAL-BASELINE-001
→ AI-PACKAGE-001
→ STAB-MAIN-GUARD-001
→ AI-ENFORCE-001
→ STAB-SIZE-001
→ AI-INSTRUCTION-SCOPE-001
→ AI-CONTEXT-SCHEMA-001
→ AI-CONTEXT-PILOT-001
→ AI-SYMBOL-CONTEXT-001
→ AI-CONTEXT-EXPAND-001
→ STAB-PRODUCT-CONTRACT-001
→ STAB-SUPPLY-CHAIN-001
→ STAB-TEST-HEALTH-001
→ AI-DEV-ENV-001
→ AI-VERIFY-001
→ DOCKER-DEV-001
→ AI-DECOMPOSE-FRONTEND-*
→ AI-DECOMPOSE-BACKEND-*
→ STAB-DATA-RECOVERY-001
→ STAB-RUNTIME-HEALTH-001
→ STAB-PERFORMANCE-001
→ AI-CONTRACT-GRAPH-001
→ STAB-DRIFT-001
→ AI-EVAL-001
→ optional CONTAINER-READY/SHADOW
→ optional production containerization
```

После каждого package — Package Health Gate. После каждых трёх merged
implementation packages — Architecture Checkpoint. После каждой фазы — Phase
Acceptance Gate.

Ключевое правило на всём пути:

```text
если feature требует роста уже перегруженной boundary,
сначала минимальный behavior-preserving extraction/stabilization package,
затем отдельный feature package.
```
