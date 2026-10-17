# OneNode Image Studio / IZO_ASA

IZO_ASA — действующий production-продукт: Web, Telegram Mini App и MAX Mini App
для генерации и обработки изображений, видео, чата, аудио и развиваемого 3D,
с приватной галереей, публичной лентой, профилями, тарифами, платежами и
администрированием.

Проект работает как модульный монолит на Windows: React/Vite frontend, FastAPI,
SQLite, локальные media/jobs, ComfyUI, Ollama/Qwen ASR и внешние интеграции.
Наличие кода в Git не означает, что этот exact commit развернут или что внешний
провайдер operationally verified.

## Для разработчика или coding-агента

Сначала откройте [AGENTS.md](AGENTS.md), затем следуйте единственной
маршрутизации из [AI_START_HERE.md](AI_START_HERE.md). Текущее состояние
программы находится в [docs/NOW.md](docs/NOW.md), а подробный human-readable
обзор архитектуры — в [docs/system-overview.md](docs/system-overview.md).

`README.md` описывает продукт и базовые команды. Он не является backlog.
Исторические roadmaps и phase reports читаются только когда `docs/NOW.md`,
context-карта или Task Contract объясняют зачем.

Завершённые отчёты, которые не менялись с 17 августа 2026 года и не являются
рабочими контрактами, вынесены в [архив документации](archive/docs/2026-10-17/README.md).
Архив не является источником актуальных задач; его следует открывать только
для конкретного исторического расследования.

## Основные границы

- Современный frontend: `/`, `/paint`, `/video`, `/audio`, `/3d`, `/chat`,
  `/profile`; маршрутизация описана generated frontend map.
- `/feed` и `/gallery` имеют отдельные статические shells.
- `/old`, `/legacy`, `/v1` — frozen compatibility.
- Backend остаётся модульным монолитом; новое business logic размещается в
  `backend/app`, а не в `backend/main.py`.
- Production SQLite, media, secrets и providers не используются в тестах.
- Release, restart, реальные платежи, почта, webhooks и provider calls требуют
  отдельного operator authorization.

## Документация чата

- [Продуктовый и архитектурный контракт](docs/chat-system.md).
- [Контракт поведения AI-помощника](docs/chat-assistant-contract.md).
- Coding-агенты получают краткую карту через маршрутизацию в
  [AI_START_HERE.md](AI_START_HERE.md); chat-specific правила не дублируются в
  `AGENTS.md`.

## Локальный запуск для разработки

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

```powershell
cd frontend
npm install
npm run dev
```

По умолчанию frontend открывается на `http://127.0.0.1:5173`.

Эти команды предназначены для development checkout. Они не являются процедурой
production promotion.

## Проверка

```powershell
# Быстрые static/tooling checks и безопасные local preflights
.\tools\verify.ps1 -Mode Quick

# Полный локальный gate для одного clean integration/release candidate
.\tools\verify.ps1 -Mode Full

# Детерминированная CI-проверка без live runtime inspection
.\tools\verify.ps1 -Mode CI

# Показать план без исполнения
.\tools\verify.ps1 -Mode Full -PlanOnly
```

Используйте targeted tests после малых изменений. Не запускайте параллельные
Full suites. Passing tests означают проверку кода в указанной среде, а не
deployment или работоспособность реального провайдера.

## Continuous Integration

`.github/workflows/ci.yml` запускает `tools/verify.ps1 -Mode CI` в изолированных
временных DB/media/secret roots, с отключёнными реальными Telegram/MAX,
OpenRouter и ComfyUI actions.

Branch protection не является обязательной на текущем GitHub-плане. Поэтому
feature worktrees, Task Contracts, repository locks, CI и один интегратор
остаются обязательными процессными границами. Не меняйте visibility репозитория
только ради branch protection.

## Production release

Единственный обязательный runbook:

- `docs/production-release-runbook.md`

Он определяет installed Windows-service topology, exact-SHA verification,
promotion, maintenance flag, rollback и local/public smoke. Не используйте
первый найденный launcher как замену runbook.

## Backup и перенос

- `docs/backup-restore-runbook-20260713.md`
- `docs/yandex-disk-backup-runbook-20260716.md`
- `docs/current-machine-handoff-20260722.md`

Никогда не копируйте открытую SQLite обычным file copy и не синхронизируйте
живые `.git`, WAL/SHM, media working state или secrets через облачный диск.

## Секреты

OpenRouter и другие секреты хранятся вне Git: через process environment или
Windows CurrentUser DPAPI store. DPAPI привязан к аккаунту и компьютеру и не
является переносимой резервной копией. Telegram/MAX/YooKassa/mail secrets также
не должны попадать в source, logs, screenshots или test snapshots.

## Внешние сервисы

- ComfyUI — локальная генерация изображений и workflows.
- OpenRouter — разрешённые внешние text/image/video capabilities.
- Ollama — локальная text/assistant runtime.
- Qwen ASR — локальное распознавание речи.
- Telegram и MAX — Mini App, login/linking и bot delivery.
- YooKassa и mail providers — финансовые и коммуникационные интеграции.

Подробные endpoints, listeners, workers, persistence и recovery описаны в
`docs/system-overview.md`, architecture inventory и соответствующих runbooks.

## Реализованные пользовательские области

- text-to-image и image-to-image;
- сборка по нескольким референсам;
- paint/inpaint/outpaint и другие image tools;
- локальные и внешние модели;
- video flows;
- chat, web-search и image tools;
- audio/voice flows;
- private gallery и public feed;
- trusted auth/profile;
- tariffs, token ledger и payments;
- Telegram/MAX;
- admin models, users, finance, bots, mail and operational views.

Текущий продуктовый и агентный статус не фиксируется здесь. Используйте
`docs/NOW.md`.
