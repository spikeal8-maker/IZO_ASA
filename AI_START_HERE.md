---
status: canonical
role: agent-entrypoint
---

# AI_START_HERE — короткий вход в IZO_ASA

Этот файл навигирует агента. Политика находится только в `AGENTS.md`.

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

## 2. Читай только в этом порядке

1. `AGENTS.md`.
2. Ближайший вложенный `AGENTS.md`, если он существует.
3. `docs/NOW.md`.
4. Одна или несколько релевантных карт из `docs/context/`.
5. Generated map или bounded symbol/line context.
6. Task Contract текущего package.
7. Source и tests в заявленном scope.

Не читай исторические master plans и большие монолиты целиком, если
`docs/NOW.md`, context-карта или generated map прямо этого не требуют.

## 3. Быстрая маршрутизация

| Задача | Первый контекст |
|---|---|
| Студия изображений, профиль, `/`, `/paint` | `docs/context/frontend-studio.md` |
| Видео, лента, галерея | `docs/context/video-gallery-feed.md` |
| Auth, Telegram/MAX, trusted identity | `docs/context/backend-auth-bots.md` |
| `/chat`, admin models, billing, audio, 3D, release | см. `docs/NOW.md`; отсутствующая карта означает discovery package, а не широкий scan |

`docs/generated/frontend-map.md` связывает routes, components, CSS и tests.
`backend/SYMBOL_MAP.md` и architecture inventory используются точечно.

## 4. До кода сформируй Task Contract

Минимум:

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

## 5. Рабочие правила

- Один package — одна проблема, одна feature branch/worktree и один clean commit.
- Не работай напрямую в `main`.
- Не используй stash/reset/cleanup для передачи или удаления чужой работы.
- Не расширяй scope молча; запиши причину и повторно проверь overlap.
- Production DB/media/secrets/providers не являются тестовой средой.
- После малой правки запускай targeted test, а не весь Full.
- Full, integration в `main` и release принадлежат одному интегратору.
- Deploy/restart/provider action выполняются только по отдельному разрешению.

## 6. Завершение package

Перед handoff:

```powershell
git status --short
git diff --check
git diff --stat
git diff
```

Затем выполни targeted checks, требуемый package gate и проверь отсутствие
секретов и файлов вне scope.

Отчёт разделяй на:

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

Не объединяй эти состояния и не называй код развернутым без exact release
evidence.
