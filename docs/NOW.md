---
status: canonical
status_role: current-status-aggregator
backlog_role: program-router
updated: 2026-08-31
status_effective_when: merged-to-main
last_verified_main: 8e15a89aae71f71eed31a0ef490228cdbc854c7d
completed_package: AI-CANONICAL-001
completed_repair: AI-CANONICAL-REPAIR-001
active_package: none
next_candidate: AI-INSTRUCTION-SCOPE-001
---

# IZO_ASA — NOW

Это единственный агрегатор текущего состояния и маршрутизатор программ. Порядок
чтения определён только в `AI_START_HERE.md`.

Статусные переходы этого файла действуют только после merge соответствующего
source в canonical `main`. Feature branch не может сама разблокировать следующий
package.

## 1. Определи факты динамически

```powershell
git rev-parse --show-toplevel
git remote get-url origin
git status --short --branch
git rev-parse HEAD
git rev-parse origin/main
git worktree list
```

- Проверенный `main`: `8e15a89aae71f71eed31a0ef490228cdbc854c7d`.
- Production release нельзя выводить из GitHub. Его подтверждают установленный
  runtime manifest и `/api/version` в рамках разрешённой live-проверки.
- Код, merge, deployment и operational verification — разные состояния.

## 2. Agent Control Plane

Завершено:

- `AI-CANONICAL-001`: PR `#73`, merge
  `49a19e271e4e0e71d1fa6f871f828f0a233cfbdf`, `NOT DEPLOYED`.
- `AI-CANONICAL-REPAIR-001`: final reviewed head
  `8f1de5a167ca94a334e5df274da479cf0beab0ee`, CI run `33312197937`, PR `#75`,
  merge `8e15a89aae71f71eed31a0ef490228cdbc854c7d`, `NOT DEPLOYED`.
- Closeout tracking: issue `#76`.

Сейчас активного implementation package нет. Следующий кандидат —
`AI-INSTRUCTION-SCOPE-001`; он не активен и требует отдельный owner-approved
Task Contract, branch и gates.

Baseline issue `#71` остаётся закреплён за SHA
`ecb02bf84ae21a46711c9b38b61784147fb9fc0a`. Issue `#72` — широкая родительская
спецификация; её нельзя передавать одному агенту как единый package.

## 3. Доступные context-карты

- [docs/context/frontend-studio.md](context/frontend-studio.md) — студия,
  профиль и основные frontend routes.
- [docs/context/video-gallery-feed.md](context/video-gallery-feed.md) — видео,
  gallery и feed.
- [docs/context/backend-auth-bots.md](context/backend-auth-bots.md) — auth,
  trusted identity, Telegram/MAX.
- [docs/context/chat.md](context/chat.md) — desktop/mobile chat, общая история,
  модели, инструменты и chat billing. Полные контракты:
  [архитектура продукта](chat-system.md) и
  [поведение AI-помощника](chat-assistant-contract.md).

Для admin-models, billing, images, audio, 3D и release отдельные canonical
карты ещё не завершены. До context-pilot использовать bounded discovery.

## 4. Generated evidence

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
- Chat product/architecture: [docs/chat-system.md](chat-system.md).
- Phone product: `docs/phone-platform-master-plan-20260824.md`; только для
  `/phone` и связанных capabilities.
- Production release: `docs/production-release-runbook.md`; только для
  release/rollback/live diagnosis.
- Backup/restore: `docs/backup-restore-runbook-20260713.md` и
  `docs/yandex-disk-backup-runbook-20260716.md`.
- Старые engineering, transformation, hardening и phase documents — reference
  evidence, не автоматически активный backlog.

## 6. Известные ограничения

- `main` пока не защищён обязательной branch protection; нужны registry, locks,
  hooks, CI и один интегратор.
- Scoped `backend/frontend/ops/docs AGENTS.md`, isolated dev environment,
  affected-test router, contract graph и cold eval automation ещё не внедрены.
- Крупные `backend/main.py`, `newUi.tsx`, `adminModels.tsx` и CSS остаются
  дорогими. Использовать context/maps/symbol ranges до декомпозиции.
- Фактические tokens учитываются только по данным агента/API.

## 7. Когда обновлять NOW

Обновляй этот файл в том же commit, когда меняются завершённый/активный/следующий
package, canonical context-карты, подтверждённый source/release state, blocker
или маршрутизация к contracts. Не добавляй длинные логи, PID и непроверенные
claims.
