---
status: canonical
role: agent-entrypoint
reading_order_role: sole-owner
updated: 2026-10-17
---
# AI_START_HERE — короткий вход в IZO_ASA

Этот файл определяет порядок чтения. Общая политика находится только в
`AGENTS.md`; другие документы ссылаются сюда, а не переписывают порядок.

## 1. Подтверди репозиторий
```powershell
$root = git rev-parse --show-toplevel
git remote get-url origin
git status --short --branch
git rev-parse HEAD
git rev-parse origin/main
git worktree list
```
Остановись без изменений, если remote не относится к `spikeal8-maker/IZO_ASA`,
есть чужой overlapping WIP или работа запущена из production/runtime вместо Git worktree.

## 2. Единственный порядок чтения
1. Корневой `AGENTS.md` — обязательная политика.
2. Этот `AI_START_HERE.md` — маршрутизация.
3. `docs/NOW.md` — состояние программы и следующий package.
4. Ближайший scoped `AGENTS.md` для целевой области.
5. Одна релевантная карта из `docs/context/`; несколько — только для cross-domain scope.
6. Task Contract текущего package.
7. Нужные generated maps, symbol map или ограниченные диапазоны строк.
8. Только source и tests в заявленном scope.

## 3. Быстрая маршрутизация
| Задача | Первый предметный контекст |
|---|---|
| Студия, профиль, `/`, `/paint` | [frontend-studio](docs/context/frontend-studio.md) |
| Видео, лента, галерея | [video-gallery-feed](docs/context/video-gallery-feed.md) |
| Auth, Telegram/MAX | [backend-auth-bots](docs/context/backend-auth-bots.md) |
| `/chat`, `/phone/chat`, chat models/tools/history | [chat](docs/context/chat.md) |
| Админка, CRM, модели | [admin-control-center](docs/context/admin-control-center.md) |
| Docker | [приёмка](docs/docker-delivery-acceptance.md), [профили](docs/docker-environments.md) |
| Проверяющий код/документы/тесты | [стандарт документации](docs/documentation-standards.md), [тесты](docs/testing-file-standards.md) |

Прочие предметные карты и generated evidence перечислены в `docs/NOW.md`.
Большие JSON и `backend/SYMBOL_MAP.md` читать точечно; вручную их не редактировать.

## 4. Выбери класс риска
| `riskClass` | Когда применять | Минимальный gate |
|---|---|---|
| `low` | Документация, без product contract | targeted checks |
| `standard` | frontend/backend и ограниченные tools | Task Contract, targeted tests, применимый Quick/CI |
| `high-assurance` | Auth, billing, migrations, durable workers, privacy | characterization, race/idempotency, rollback, CI, independent review |
| `release-ops` | production data/provider/network, deploy/restart | разрешение владельца, exact-SHA receipt, operational evidence |

После двух одинаковых неудач запрещён третий broad scan: выполнить bounded diagnosis.
`BLOCKED` допустим только при подтверждённой внешней зависимости;
иначе package остаётся active и требуется устранение конкретной ошибки.

## 5. До кода сформируй Task Contract

Используется **TOML**, который проверяет существующий
`tools/agent_system/package.py` (`TaskManifest`, `parse_manifest`, `render_manifest`).
Полный проверяемый пример и запуск: [task-contract-guide.md](docs/task-contract-guide.md).
Неполный YAML не является manifest. Указать реальный base SHA, цель, результат,
scope, риск, проверки и откат; создать package штатным механизмом, не обходя ownership.
Без сценария «до/после» — только bounded discovery.

## 6. Рабочие правила

Один package — один результат, writer и PR. Не писать напрямую в main;
не стирать чужой WIP; scope расширять только с обоснованием и проверкой пересечений.
После малой правки — targeted tests; Full/integration принадлежат интегратору.
Portable CI не заменяет тесты приложения или Docker; отсутствие запуска — NOT_RUN.
Production, реальные секреты/провайдеры не являются fixtures. Deploy требует разрешения.
Приёмка определяется `AGENTS.md`: обязательные CI/review должны завершиться.
Комментарий самого исполнителя не является независимым review и не разрешает обход gates.

## 7. Завершение package
```powershell
git status --short
git diff --check
git diff --stat
git diff
```
Проверить scope, секреты, реальные результаты тестов и свежие base/head.
Отдельно сообщить IMPLEMENTED, TESTED, COMMITTED, PUSHED/PR, MERGED,
DEPLOYED, OPERATIONALLY VERIFIED или BLOCKED. Merge не означает deployment.
