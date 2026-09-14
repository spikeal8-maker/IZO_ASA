---
status: canonical
status_role: current-status-aggregator
backlog_role: program-router
updated: 2026-09-14
source_main_at_status_update: 9eac361ae5c52be8d7f1f7596ea99c5bf31e1397
last_verified_main: d223c179d5944bc208cace867d5e93bc1341a3aa
production_release_sha: d223c179d5944bc208cace867d5e93bc1341a3aa
production_release_verified_at: 2026-09-02T00:08:04+03:00
completed_package: AI-EVAL-BASELINE-DEFER-001
active_package: AI-PACKAGE-001
active_task_contract: github-issue-101
baseline_source_sha: ecb02bf84ae21a46711c9b38b61784147fb9fc0a
baseline_status: deferred-required-before-AI-CONTEXT-PILOT-001
blocker: none
next_candidate: STAB-MAIN-GUARD-001
---
# IZO_ASA — NOW

Это единственный current-status aggregator/router. Порядок чтения определяет
только `AI_START_HERE.md`. Подробный stabilization backlog находится в
`docs/stabilization-optimization-master-spec.md`, agent-specific capabilities —
в `docs/agent-control-plane.md`.

## 1. Перед работой

```powershell
git rev-parse --show-toplevel
git remote get-url origin
git status --short --branch
git rev-parse HEAD
git rev-parse origin/main
git worktree list
```
Source `main` при последнем status transition:
`9eac361ae5c52be8d7f1f7596ea99c5bf31e1397`.

Последний отдельно operationally verified production release:
`d223c179d5944bc208cace867d5e93bc1341a3aa` от 2026-09-02. Не выводить deploy
из GitHub: production подтверждается installed runtime evidence и `/api/version`.

## 2. Активный stabilization package

Активен `AI-PACKAGE-001`, issue #101.
Цель package: versioned Task Manifest, один writer/worktree, shared registry между
sibling worktrees, overlap detection, controlled scope expansion и safe finish.
Product frontend/backend/runtime behavior в этом package не меняется.

Bootstrap для самого #101 выполняется по существующим repository rules через
отдельную feature branch/worktree: package создаёт CLI, которым будут обязаны
пользоваться последующие implementation packages.
Следующий package после успешного #101: `STAB-MAIN-GUARD-001` (#102).

## 3. Frozen baseline — deferred, not waived

`AI-EVAL-BASELINE-001`, issue #71, остаётся обязательным. Frozen source:
```text
ecb02bf84ae21a46711c9b38b61784147fb9fc0a
```
Независимый evaluator пока недоступен. Поскольку source SHA immutable, начало
foundational safety/tooling packages не разрушает точку A. Отдельный reviewed
amendment: `docs/agent-tasks/AI-EVAL-BASELINE-DEFER-001.md`.

Разрешено выполнить #101–#106 до baseline. **Запрещено активировать
`AI-CONTEXT-PILOT-001` (#107) или final `AI-EVAL-001` (#123), пока #71 не имеет
трёх принятых независимых cold receipts A/B/C.** Frozen SHA, prompts и критерии #71
не меняются.
Если независимый executor появляется раньше — #71 запускается сразу read-only на
frozen SHA, не вмешиваясь в чужой bounded implementation package.

## 4. Context и generated evidence

Доступные context cards:
- `docs/context/frontend-studio.md`;
- `docs/context/video-gallery-feed.md`;
- `docs/context/backend-auth-bots.md`;
- `docs/context/chat.md`;
- `docs/context/admin-control-center.md`.

Для отсутствующей domain card использовать bounded discovery, не broad scan.
Generated evidence:
```text
docs/generated/frontend-map.md
docs/generated/architecture-inventory.md
backend/SYMBOL_MAP.md
```
Большие JSON/maps/monoliths читать точечно.

## 5. Главные незакрытые capabilities

- package registry/one-writer ownership;
- remote `main` protection от ordinary coding agents;
- machine-enforced scope и file/coupling health;
- scoped/bounded context tooling;
- critical product-flow + supply-chain + test-health floor;
- isolated dev environment + affected-test router;
- Docker DEV/TEST;
- frontend/backend hotspot decomposition;
- restore/data-integrity + runtime/performance floor;
- contract graph/drift automation;
- final cold eval.

## 6. Self-audit cadence

1. После каждого implementation package — Package Health Gate.
2. После каждых трёх merged implementation packages — Architecture Checkpoint.
3. После каждой фазы — Phase Acceptance Gate + bounded cold-agent case.

Protected hotspots не растут. После extraction budget снижается в том же package.
Security/dependency/data/recovery regressions также могут остановить feature flow.

## 7. Program lanes

- stabilization master: `docs/stabilization-optimization-master-spec.md`;
- active dependency amendment: `docs/agent-tasks/AI-EVAL-BASELINE-DEFER-001.md`;
- agent development: `docs/agent-control-plane.md`;
- chat: `docs/chat-system.md`;
- phone: `docs/phone-platform-master-plan-20260824.md`;
- production release: `docs/production-release-runbook.md`;
- backup/restore: `docs/backup-restore-runbook-20260713.md`,
  `docs/yandex-disk-backup-runbook-20260716.md`.
Historical phase/engineering documents are evidence, not active backlog.

## 8. Когда обновлять NOW

Обновлять только при смене completed/active/next package, blocker, canonical map,
verified source/release state или program routing. Не добавлять длинные логи,
implementation detail или package receipts.
