---
status: canonical
status_role: current-status-aggregator
backlog_role: program-router
updated: 2026-08-30
last_verified_main: 49a19e271e4e0e71d1fa6f871f828f0a233cfbdf
completed_package: AI-CANONICAL-001
completed_repair: AI-CANONICAL-REPAIR-001
active_package: none
next_candidate: AI-INSTRUCTION-SCOPE-001
---

# IZO_ASA — NOW

Это единственный агрегатор текущего состояния и маршрутизатор программ. Он не
заменяет Git, runtime manifests, tests, receipts или feature contracts. Порядок
чтения определён только в `AI_START_HERE.md`.

## 1. Определи факты динамически

```powershell
git rev-parse --show-toplevel
git remote get-url origin
git status --short --branch
git rev-parse HEAD
git rev-parse origin/main
git worktree list
```

- Последний проверенный `main` до этого repair-package:
  `49a19e271e4e0e71d1fa6f871f828f0a233cfbdf`.
- После merge текущий SHA определяется только Git-командами выше.
- Production release нельзя выводить из GitHub. Его подтверждают установленный
  runtime manifest и `/api/version` в рамках разрешённой live-проверки.
- Код, merge, deployment и operational verification — разные состояния.

## 2. Agent Control Plane

- Активная программа: `docs/agent-control-plane.md`.
- `AI-CANONICAL-001` завершён через PR `#73`, merge
  `49a19e271e4e0e71d1fa6f871f828f0a233cfbdf`, `NOT DEPLOYED`.
- `AI-CANONICAL-REPAIR-001` относится к issue `#74`; после merge этого source
  version он считается завершённым, а `active_package` остаётся `none`.
- Baseline evaluation: issue `#71`, закреплён за исходным SHA
  `ecb02bf84ae21a46711c9b38b61784147fb9fc0a`.
- Следующий кандидат требует отдельного owner-approved Task Contract:
  `AI-INSTRUCTION-SCOPE-001`.
- `AI-CONTEXT-001` issue `#72` не исполняется как один широкий package до
  разделения на schema, pilot и expansion.
- Ни один program-документ не разрешает deploy, restart или real provider
  actions.

## 3. Доступные context-карты

- `docs/context/frontend-studio.md` — современная студия, профиль и основные
  frontend routes.
- `docs/context/video-gallery-feed.md` — видео, gallery и feed.
- `docs/context/backend-auth-bots.md` — auth, trusted identity, Telegram/MAX.

Для chat, admin-models, billing, images, audio, 3D и release отдельные canonical
карты ещё не завершены. До context-pilot задача в такой области использует
bounded discovery, а не второй каталог контекста или чтение всего проекта.

## 4. Generated evidence

Существующие пути:

```text
docs/generated/frontend-map.md
docs/generated/frontend-map.json
docs/generated/architecture-inventory.md
docs/generated/architecture-inventory.json
backend/SYMBOL_MAP.md
```

Generated evidence читается точечно. Большие JSON, symbol maps и монолиты не
загружаются целиком без обоснованной необходимости.

## 5. Программные и продуктовые lanes

- Agent-development: `docs/agent-control-plane.md`.
- Phone product: `docs/phone-platform-master-plan-20260824.md`; только для
  `/phone` и связанных capabilities.
- Production release: `docs/production-release-runbook.md`; только для
  release/rollback/live diagnosis.
- Backup/restore: `docs/backup-restore-runbook-20260713.md` и
  `docs/yandex-disk-backup-runbook-20260716.md`.
- Старые engineering, transformation, hardening и phase documents — reference
  evidence, не автоматически активный backlog.

## 6. Известные ограничения

- `main` пока не защищён обязательной branch protection; enforcement должен
  появиться через worktrees, registry, locks, hooks, CI и одного интегратора.
- Scoped `backend/frontend/ops/docs AGENTS.md`, package registry, isolated dev
  environment, affected-test router, contract graph и cold eval automation ещё
  не внедрены.
- Крупные `backend/main.py`, `newUi.tsx`, `adminModels.tsx` и CSS остаются
  дорогими. Использовать context/maps/symbol ranges до декомпозиции.
- Фактические tokens учитываются только по данным агента/API.

## 7. Когда обновлять NOW

Обновляй этот файл в том же commit, когда меняются:

- завершённый, активный или следующий package;
- canonical context-карты;
- подтверждённый source/release state;
- известный blocker;
- маршрутизация к действующим contracts.

Не добавляй длинные логи, PID, временные ветки или непроверенные claims.
