---
status: canonical
status_role: current-status-aggregator
backlog_role: program-router
updated: 2026-09-21
source_main_at_status_update: b6a8a74c19a1d72dfac2d913d17e0f7c60020c24
last_verified_main: b6a8a74c19a1d72dfac2d913d17e0f7c60020c24
production_release_sha: d223c179d5944bc208cace867d5e93bc1341a3aa
production_release_verified_at: 2026-09-02T00:08:04+03:00
completed_package: STAB-PRODUCT-CONTRACT-001
active_package: STAB-SUPPLY-CHAIN-001
active_task_contract: github-issue-111
baseline_source_sha: ecb02bf84ae21a46711c9b38b61784147fb9fc0a
baseline_status: completed-point-A-accepted
next_candidate: STAB-TEST-HEALTH-001
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
`b6a8a74c19a1d72dfac2d913d17e0f7c60020c24`.

Последний отдельно operationally verified production release:
`d223c179d5944bc208cace867d5e93bc1341a3aa` от 2026-09-02. Не выводить deploy
из GitHub: production подтверждается installed runtime evidence и `/api/version`.

## 2. Активный stabilization package

Completed: `STAB-PRODUCT-CONTRACT-001` (#110).
Active: `STAB-SUPPLY-CHAIN-001` (#111).
Architecture checkpoint after #108-#110: PASS; protected hotspot growth 0, routes/workers/tables 251/8/65, context ownerless/duplicate findings 0, product-flow count 14, generated drift 0.
`AI-CONTEXT-PILOT-001` (#107) completed: chat/admin-models packets stayed bounded and post-pilot A/B improved from false/false to partial/true with 0 broad scans.
Next: `STAB-TEST-HEALTH-001` (#112).

## 3. Frozen baseline — completed point A

Frozen source remains immutable:
```text
ecb02bf84ae21a46711c9b38b61784147fb9fc0a
```
Accepted point-A summary: 3 cases, 0 correct, 28 tool calls, 1 file opened,
84,968 input tokens and 1,996 output tokens. The failures are intentional baseline
evidence: broad scans and incorrect routing must not be repaired retroactively.

Post-pilot #107 comparison: A improved false -> partial and B false -> true;
combined input tokens fell from 63,241 to 3,643 and broad tool calls from 21 to 0.
No repository/product/provider/deploy action was part of the evaluation evidence.

Credential-isolation stop-the-line repair #139 and `AI-SYMBOL-CONTEXT-001` (#108)
are completed.

## 4. Context и generated evidence

Доступные context cards (11 canonical domains):
- `docs/context/3d.md`;
- `docs/context/admin-control-center.md`;
- `docs/context/admin-models.md`;
- `docs/context/audio.md`;
- `docs/context/backend-auth-bots.md`;
- `docs/context/billing-payments.md`;
- `docs/context/chat.md`;
- `docs/context/frontend-studio.md`;
- `docs/context/image-generation.md`;
- `docs/context/release-ops.md`;
- `docs/context/video-gallery-feed.md`.

Для отсутствующей domain card использовать bounded discovery, не broad scan.
Generated evidence:
```text
docs/generated/frontend-map.md
docs/generated/architecture-inventory.md
docs/generated/context-index.md
docs/generated/context-index.json
docs/generated/product-flow-map.md
backend/SYMBOL_MAP.md
```
Большие JSON/maps/monoliths читать точечно.

## 5. Главные незакрытые capabilities

- coupling/ownership health;
- supply-chain + test-health floor;
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
- historical dependency amendment: `docs/agent-tasks/AI-EVAL-BASELINE-DEFER-001.md`;
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
