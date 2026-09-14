---
status: canonical
status_role: current-status-aggregator
backlog_role: program-router
updated: 2026-09-14
source_main_at_status_update: 9128f99f825bdd4533dd68c44b5e2f4586719f7f
last_verified_main: d223c179d5944bc208cace867d5e93bc1341a3aa
production_release_sha: d223c179d5944bc208cace867d5e93bc1341a3aa
production_release_verified_at: 2026-09-02T00:08:04+03:00
completed_package: STAB-MASTER-SPEC-001
active_package: none
next_candidate: AI-EVAL-BASELINE-001
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

Source `main` на момент подготовки этого status package:
`9128f99f825bdd4533dd68c44b5e2f4586719f7f`.

Последний отдельно operationally verified production release:
`d223c179d5944bc208cace867d5e93bc1341a3aa` от 2026-09-02. Не выводить deploy
из GitHub: production подтверждается installed runtime evidence и `/api/version`.

## 2. Stabilization program

Завершённая основа:

- `AI-CANONICAL-001` — merged, `NOT DEPLOYED`;
- `AI-CANONICAL-REPAIR-001` — merged, `NOT DEPLOYED`;
- master stabilization specification — этот PR после merge.

Активного implementation package нет. Следующий кандидат после merge:

```text
AI-EVAL-BASELINE-001
```

Это существующий read-only issue #71. Не создавать дублирующий baseline package.

Далее идти только по dependency order master-spec. Ключевые gates:

```text
baseline
→ package ownership + remote main guard
→ fail-closed scope + architecture health
→ bounded context
→ product/supply-chain/test-health floor
→ isolated dev env + affected tests
→ Docker DEV/TEST
→ touch-driven decomposition
→ data/recovery/runtime/performance floor
→ contract/drift
→ final cold eval
→ optional container readiness/production
```

## 3. Context и generated evidence

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

## 4. Главные незакрытые capabilities

- package registry/one-writer ownership;
- remote `main` protection от ordinary coding agents;
- machine-enforced scope;
- file/coupling health gate;
- scoped/bounded context tooling;
- current critical product-flow contract;
- supply-chain vulnerability/license gate;
- test-health/flakiness/warning gate;
- isolated dev environment;
- affected-test router;
- Docker DEV/TEST;
- hotspot decomposition;
- restore rehearsal/data-integrity gate;
- worker/runtime health + deterministic performance budgets;
- contract graph/drift automation;
- final cold eval.

## 5. Self-audit cadence

1. После каждого implementation package — Package Health Gate.
2. После каждых трёх merged implementation packages — Architecture Checkpoint.
3. После каждой фазы — Phase Acceptance Gate + bounded cold-agent case.

Protected hotspots не растут. После extraction budget снижается в том же package.
Security/dependency/data/recovery regressions также могут остановить feature flow.

## 6. Program lanes

- stabilization master: `docs/stabilization-optimization-master-spec.md`;
- agent development: `docs/agent-control-plane.md`;
- chat: `docs/chat-system.md`;
- phone: `docs/phone-platform-master-plan-20260824.md`;
- production release: `docs/production-release-runbook.md`;
- backup/restore: `docs/backup-restore-runbook-20260713.md`,
  `docs/yandex-disk-backup-runbook-20260716.md`.

Historical phase/engineering documents are evidence, not active backlog.

## 7. Когда обновлять NOW

Обновлять только при смене completed/active/next package, blocker, canonical map,
verified source/release state или program routing. Не добавлять длинные логи,
implementation detail или package receipts.
