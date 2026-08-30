---
status: canonical
status_role: current-status-aggregator
backlog_role: program-router
updated: 2026-08-30
source_baseline: ecb02bf84ae21a46711c9b38b61784147fb9fc0a
---

# IZO_ASA — NOW

Это единственный агрегатор текущего состояния и маршрутизатор программ.
Он не заменяет Git, runtime manifests, tests, receipts или feature contracts.

## 1. Всегда определяй факты динамически

```powershell
git rev-parse --show-toplevel
git remote get-url origin
git status --short --branch
git rev-parse HEAD
git rev-parse origin/main
git worktree list
```

- GitHub source baseline, на котором начат `AI-CANONICAL-001`:
  `ecb02bf84ae21a46711c9b38b61784147fb9fc0a`.
- Текущий HEAD после этого baseline определяется только командами выше.
- Production release из GitHub не выводится. Его подтверждают установленный
  runtime manifest и `/api/version` в рамках разрешённой live-проверки.
- Наличие кода, merge, deployment и operational verification — разные состояния.

## 2. Текущая программа Agent Control Plane

- Program: `docs/agent-control-plane.md`.
- Latest package introduced by this source version: `AI-CANONICAL-001`.
- Task Contract: `docs/agent-tasks/AI-CANONICAL-001.md`.
- Tracking epic: GitHub issue `#70`.
- Baseline evaluation: issue `#71`, закреплён за исходным SHA выше.
- Следующий допустимый package после merge и review:
  `AI-CONTEXT-001`.
- Ни один из этих документов не разрешает deploy, restart или real provider
  actions.

## 3. Текущая иерархия знаний

1. `AGENTS.md` — обязательная политика.
2. `AI_START_HERE.md` — короткий вход.
3. Этот файл — актуальный router.
4. Ближайший вложенный `AGENTS.md`, если существует.
5. `docs/context/*.md` — scoped domain maps.
6. `docs/generated/*`, `backend/SYMBOL_MAP.md`,
   `architecture/generated-inventory.json` — generated evidence.
7. Task Contract package.
8. Source и tests.
9. Historical/reference docs — только по явной причине.

## 4. Доступные context-карты

- `docs/context/frontend-studio.md` — современная студия, профиль и основные
  frontend routes.
- `docs/context/video-gallery-feed.md` — видео, gallery и feed.
- `docs/context/backend-auth-bots.md` — auth, trusted identity, Telegram/MAX.

Для chat, admin-models, billing, images, audio, 3D и release отдельные карты ещё
не считаются завершёнными. До `AI-CONTEXT-001` задача в такой области должна
использовать generated maps и bounded discovery, а не создавать второй каталог
контекста или читать весь проект без ограничения.

## 5. Программные и продуктовые lanes

- Agent-development lane: `docs/agent-control-plane.md`.
- Phone product contract:
  `docs/phone-platform-master-plan-20260824.md`; читать только для `/phone` и
  связанных phone capabilities.
- Production release:
  `docs/production-release-runbook.md`; читать только для release/rollback/live
  diagnosis.
- Backup/restore:
  `docs/backup-restore-runbook-20260713.md` и
  `docs/yandex-disk-backup-runbook-20260716.md`.
- Старые engineering, transformation, hardening и phase documents — reference
  evidence, не автоматически активный backlog.

Этот файл не авторизует произвольный следующий feature. Каждая новая работа
требует отдельный Task Contract владельца.

## 6. Известные ограничения

- В `main` нет обязательной branch protection на текущем GitHub-плане; поэтому
  правила должны постепенно обеспечиваться worktrees, registry, locks, hooks,
  CI и одним интегратором.
- Package registry, isolated dev environment, affected-test router, generated
  contract graph и cold eval automation ещё не внедрены; они идут отдельными
  пакетами из epic `#70`.
- Крупные `backend/main.py`, `newUi.tsx`, `adminModels.tsx` и CSS остаются
  дорогими для агентов. До декомпозиции использовать context/maps/symbol ranges.

## 7. Что обновляет этот файл

Обновляй `docs/NOW.md` в том же commit только когда меняются:

- актуальная программа или очередность package;
- доступные canonical context-карты;
- подтверждённый source/release state;
- известный blocker;
- маршрутизация к действующим contracts.

Не добавляй сюда длинные логи, PID, временные ветки или непроверенные claims.
