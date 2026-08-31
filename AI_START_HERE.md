---
status: canonical
role: agent-entrypoint
reading_order_role: sole-owner
updated: 2026-08-31
---
# AI_START_HERE — короткий вход в IZO_ASA

Этот файл навигирует coding-агента. Глобальная политика находится только в
`AGENTS.md`. Порядок чтения определяется только здесь и не дублируется в
`docs/NOW.md`, program-документах или Task Contracts.

## 1. Подтверди репозиторий
```powershell
$root = git rev-parse --show-toplevel
git remote get-url origin
git status --short --branch
git rev-parse HEAD
git rev-parse origin/main
git worktree list
```
Остановись без изменений, если remote не относится к
`spikeal8-maker/IZO_ASA`, рабочая копия содержит чужой overlapping WIP или задача
запущена из runtime/production directory, а не из Git worktree.

## 2. Единственный порядок чтения
1. Корневой `AGENTS.md` — обязательная политика.
2. Этот `AI_START_HERE.md` — маршрутизация.
3. `docs/NOW.md` — текущее состояние программы и допустимый следующий package.
4. Ближайший scoped `AGENTS.md`, если он существует для целевой области.
5. Одна релевантная карта из `docs/context/`; несколько — только для явно
   cross-domain задачи.
6. Task Contract текущего package.
7. Нужные generated maps, symbol map или ограниченные диапазоны строк.
8. Только source и tests в заявленном scope.

Не читай исторические master plans и большие монолиты целиком, если текущая карта, Task Contract или generated evidence прямо этого не требует.

## 3. Быстрая маршрутизация
| Задача | Первый предметный контекст |
|---|---|
| Студия изображений, профиль, `/`, `/paint` | [docs/context/frontend-studio.md](docs/context/frontend-studio.md) |
| Видео, лента, галерея | [docs/context/video-gallery-feed.md](docs/context/video-gallery-feed.md) |
| Auth, Telegram/MAX, trusted identity | [docs/context/backend-auth-bots.md](docs/context/backend-auth-bots.md) |
| `/chat`, `/phone/chat`, chat models/tools/history | [docs/context/chat.md](docs/context/chat.md) |
| Админка, CRM, административные экраны моделей | [docs/context/admin-control-center.md](docs/context/admin-control-center.md) |
| Product billing, images, audio, 3D, release | см. `docs/NOW.md`; отсутствующая карта означает bounded discovery, а не широкий scan |

Generated evidence:
```text
docs/generated/frontend-map.md
docs/generated/frontend-map.json
docs/generated/architecture-inventory.md
docs/generated/architecture-inventory.json
backend/SYMBOL_MAP.md
```

## 4. Выбери класс риска
| `riskClass` | Когда применять | Минимальный gate |
|---|---|---|
| `low` | Документация и локальные изменения без product contract | targeted checks |
| `standard` | Ограниченная frontend/backend feature-задача | Task Contract, targeted tests, Quick |
| `high-assurance` | Auth, billing, migrations, durable workers, privacy, media ownership | characterization, race/idempotency, rollback, CI, independent review |
| `release-ops` | Deploy, restart, webhook, production data/provider/network | явное разрешение владельца, exact-SHA receipt, operational evidence |

После двух одинаковых неудачных попыток запрещён третий broad scan: выполни bounded diagnosis и escalation с evidence.
`BLOCKED` допустим только при подтверждённой внешней зависимости; иначе package остаётся active.

## 5. До кода сформируй Task Contract
```yaml
id:
goal:
userOutcome:
beforeScenario:
afterScenario:
nonGoals: []
domain:
riskClass:
declaredFiles: []
allowedPatterns: []
acceptance: []
requiredEvidence: []
targetedTests: []
forbiddenOperations: []
rollbackBoundary:
```
Если нельзя воспроизвести сценарий «до» и сформулировать проверяемый результат
«после», выполняй только bounded discovery.

## 6. Рабочие правила
- Один package — одна проблема, одна feature branch/worktree и один clean commit.
- Не работай напрямую в `main`.
- Не используй stash/reset/cleanup для передачи или удаления чужой работы.
- Не расширяй scope молча; запиши причину и повторно проверь overlap.
- Production DB/media/secrets/providers не являются тестовой средой.
- После малой правки запускай targeted test, а не весь Full.
- Full, integration в `main` и release принадлежат одному интегратору.
- Deploy/restart/provider action выполняются только по отдельному разрешению.
- Не выполняй merge, пока CI и автоматический review не завершены.

## 7. Завершение package
```powershell
git status --short
git diff --check
git diff --stat
git diff
```
Выполни targeted checks и package gate; проверь отсутствие секретов и файлов вне
scope. Отчёт разделяй на:
```text
IMPLEMENTED
TESTED
COMMITTED
PUSHED/PR
MERGED
DEPLOYED
OPERATIONALLY VERIFIED
BLOCKED
```
Не объединяй эти состояния и не называй код развернутым без exact release evidence.
