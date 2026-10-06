---
status: canonical
status_role: current-status-aggregator
backlog_role: program-router
updated: 2026-10-05
source_main_at_status_update: 77fd1ed7ede83b9bc8216008b685b8fd51242879
last_verified_main: 77fd1ed7ede83b9bc8216008b685b8fd51242879
production_release_sha: d223c179d5944bc208cace867d5e93bc1341a3aa
production_release_verified_at: 2026-09-02T00:08:04+03:00
completed_package: DOCKER-DEV-001
active_package: CONTAINER-READY-001
active_task_contract: github-issue-124
baseline_source_sha: ecb02bf84ae21a46711c9b38b61784147fb9fc0a
baseline_status: completed-point-A-accepted
next_candidate: CONTAINER-SHADOW-001
---
# IZO_ASA — NOW

Порядок чтения: `AI_START_HERE.md`; NOW — компактный current-status router.

## 1. Перед работой

Сверить repository root, origin, clean status, HEAD/origin-main и worktrees.
Source main: `77fd1ed7ede83b9bc8216008b685b8fd51242879`.
Production release: `d223c179d5944bc208cace867d5e93bc1341a3aa` (2026-09-02);
production подтверждается installed runtime evidence.

## 2. Активный stabilization package

Completed: `DOCKER-DEV-001` (#115).
Active: `CONTAINER-READY-001` (#124).
Next: `CONTAINER-SHADOW-001` (#125).
D0 = COMPLETE.
#112 test-health = COMPLETE.
Active non-regression: warning baseline 97; cleanup baseline 1; hidden outbound external = 0 required; pytest rerun observability active; process leak gate active.
Tracked debt: #162, #163, #164, #165.
#113 AI-DEV-ENV = COMPLETE; implementation + post-merge verification accepted.
#114 AI-VERIFY = OPEN / PREPARED; not active; not prerequisite for first D1 Docker smoke.
#115 DOCKER-DEV = COMPLETE; merge `77fd1ed7ede83b9bc8216008b685b8fd51242879`; post-merge CI #743 = SUCCESS.
#124 CONTAINER-READY = ACTIVE; ACTIVATION / PORTABILITY AUDIT; implementation NOT STARTED.
#125 CONTAINER-SHADOW = NEXT.
D1 Docker DEV/TEST foundation (#115) = COMPLETE.
Architecture checkpoint after #108-#110: PASS; routes/workers/tables 251/8/65; product-flow count 14.

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
