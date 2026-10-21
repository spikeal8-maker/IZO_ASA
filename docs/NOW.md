---
status: canonical
status_role: current-status-aggregator
backlog_role: program-router
updated: 2026-10-17
source_main_at_status_update: d1ee3a0ac5114ec08f4a8daee9cf6e41e97d6a7a
last_verified_main: 7ab1861b53320b1234f3680f4fa5dd13175f3e27
production_release_sha: d223c179d5944bc208cace867d5e93bc1341a3aa
production_release_verified_at: 2026-09-02T00:08:04+03:00
completed_package: CONTAINER-READY-001
active_package: CONTAINER-SHADOW-001
active_task_contract: github-issue-125
baseline_source_sha: ecb02bf84ae21a46711c9b38b61784147fb9fc0a
baseline_status: completed-point-A-accepted
next_candidate: CONTAINER-PRODUCTION-001
candidate_pr: 193
candidate_source_sha: 9609adeecae78e6f538bcbab7eb8aa5d4b876cc4
candidate_state: acceptance-repair-in-progress
candidate_exact_head_ci: NOT_RUN
candidate_docker_acceptance: D1_PASS_EXTENDED_FAIL
---
# IZO_ASA — NOW

Порядок чтения определяет только `AI_START_HERE.md`. Перед работой сверить
origin, чистоту checkout, актуальные main/PR HEAD и пересечения других задач.
`source_main_at_status_update` — просмотренный Git-срез, НЕ отметка CI PASS.
`last_verified_main` и production-поля — прежние доказательства; свежий merge
их не обновляет. Установленный рабочий релиз в этой ревизии не проверялся.

## 1. Состояние программы

Completed: `CONTAINER-READY-001` (#124).
Active: `CONTAINER-SHADOW-001` (#125).
Next: `CONTAINER-PRODUCTION-001` (#126).

D0 и Docker DEV/TEST foundation (#115) приняты ранее; #124 завершён.
PR #186/#191 интегрированы с main; Draft #192 хранит checkpoint `d6ecb7f`.
На `9609ade`: Д1 6×8 PASS; исправления generation/payment/video подтверждены.
Д2/Д3 не приняты: source drift телеметрии, отдельная роль и live gaps.
Следующий кандидат: quiesced backup и доступные admin/factory API.
Full CI и независимая приёмка review HEAD обязательны.
#126 не начат; production не переключать.

Профили DEV, Shadow и будущей поставки: [docker-environments.md](docker-environments.md).
Критерии: [docker-delivery-acceptance.md](docker-delivery-acceptance.md).
Текущий Task: `DOCKER-ACCEPTANCE-REPAIR-001`; запуск и evidence —
[docker-clean-install.md](docker-clean-install.md). Кандидат ещё не принят.
История прежних Task Contracts сохранена в исходных коммитах.

## 2. Принятые инварианты

#112 test-health и #113 AI-DEV-ENV приняты; #114 AI-VERIFY подготовлен,
но не является prerequisite первого безопасного Docker smoke.
Active non-regression: warning baseline 97; cleanup baseline 1;
hidden outbound external = 0 required; pytest rerun observability active;
process leak gate active. Tracked debt: #162, #163, #164, #165.
Protected hotspots не растут; extraction снижает бюджет в том же пакете.

## 3. Frozen baseline — completed point A

Frozen source: `ecb02bf84ae21a46711c9b38b61784147fb9fc0a`.
Историческая точка A: 3 cases, 0 correct; 84,968 input tokens и 1,996 output tokens.
После #107: 63,241 to 3,643 input tokens; broad tool calls from 21 to 0.
Это неизменяемые результаты эксперимента, не сегодняшняя проверка Docker.
#139 и `AI-SYMBOL-CONTEXT-001` (#108) завершены; повторно их не активировать.

## 4. Контекст и точечный поиск

- `docs/context/3d.md`; `docs/context/admin-control-center.md`;
- `docs/context/admin-models.md`; `docs/context/audio.md`;
- `docs/context/backend-auth-bots.md`; `docs/context/billing-payments.md`;
- `docs/context/chat.md`; `docs/context/frontend-studio.md`;
- `docs/context/image-generation.md`; `docs/context/release-ops.md`;
- `docs/context/video-gallery-feed.md`.

Generated evidence: `docs/generated/frontend-map.md`, `docs/generated/frontend-map.json`,
`docs/generated/architecture-inventory.md`, `docs/generated/architecture-inventory.json`,
`docs/generated/context-index.md`, `docs/generated/context-index.json`,
`docs/generated/product-flow-map.md`, `backend/SYMBOL_MAP.md`. Читать точечно.

## 5. Владельцы контрактов и дальнейшая работа

Программа: `docs/stabilization-optimization-master-spec.md`;
агенты: `docs/agent-control-plane.md`; чат: `docs/chat-system.md`;
phone: `docs/phone-platform-master-plan-20260824.md`.
Release: `docs/production-release-runbook.md`; backup:
`docs/backup-restore-runbook-20260713.md`, `docs/yandex-disk-backup-runbook-20260716.md`.
История — evidence, не backlog. Не ждать всей декомпозиции перед испытаниями Docker.

После реализации — Package Health Gate, после трёх implementation packages —
Architecture Checkpoint, после фазы — Phase Acceptance и bounded cold-agent case.
Обновлять NOW при изменении активной работы/барьеров/проверенных фактов,
а не для накопления логов или автоматического присваивания нового production SHA.
