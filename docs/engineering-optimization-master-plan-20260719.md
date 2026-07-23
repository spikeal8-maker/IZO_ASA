# IZO_ASA — актуальный master plan оптимизации production

Дата новой базовой проверки: **2026-07-19**
Статус: **спецификации и evidence; исполняемая очередь с 2026-07-20 —
[optimization-and-decomposition-plan-20260720.md](optimization-and-decomposition-plan-20260720.md)**
Фактический аудит: [agent-compliance-audit-20260719.md](agent-compliance-audit-20260719.md)
Предыдущий план: `engineering-transformation-master-plan-20260717.md` — исторический checkpoint, не текущая очередь.

## Экстренный пакет `AUTH-BOT-P0-20260723`

Статус: **CODE COMPLETE**. Пакет имеет приоритет над плановой очередью, потому что
новые и вышедшие пользователи потеряли вход через Telegram/MAX, а устаревший
HTML мог оставлять уже открытый браузер на пустом экране после выпуска.

Область пакета:

- сохранённые в админке username/deep-link ботов применяются при старте backend
  вместе с DPAPI-токенами;
- выделенный MAX TLS-контекст получает проверенный корневой сертификат без
  установки системного CA и без отключения TLS-проверки;
- кнопки Telegram/MAX остаются видимыми и явно отключёнными, если provider ещё
  не готов, вместо бесследного исчезновения;
- отрицательный ответ проверки бота (`HTTP 200`, `ok=false`) больше не
  показывается админке как успех;
- production HTML получает `Cache-Control: no-store`, а hashed assets —
  `immutable`;
- acceptance: focused auth tests 5 раз, backend bot/TLS suites, frontend
  smoke/lint/build, Quick, один Full на точном release SHA, затем desktop/mobile
  и реальные Telegram/MAX provider checks с редактированным evidence.

Code evidence 2026-07-23: focused auth повторён 5 раз; bot/TLS suites — `44
passed`; полный изолированный release-контур — `1644 passed`, frontend
lint/build/release-identity/origin-isolation/studio-resilience — зелёные; живые
listener owners 5173/8000/8188/11434 подтверждены через WinSW ancestry и
service XML. Статусы `DEPLOYED`, `VERIFIED` и `OPERATIONALLY VERIFIED` ставятся
только после установки точного SHA и внешних desktop/mobile/provider проверок.

Follow-up reliability closure 2026-07-23: подтверждены независимые причины
`429` за FRP, накопление/перезапись challenge, потеря provider retry после
ошибки handler и блокировка popup после `await`. Реализация, redacted evidence,
rollback boundary и production acceptance вынесены в
[auth-bot-login-reliability-20260723.md](auth-bot-login-reliability-20260723.md).

Availability follow-up `AUTH-OUTAGE-P0-20260723`: a release rollback snapshot
held the backend offline for about 3.5 minutes and exposed `502` responses to
the login capability probe. The corrective package moves the database snapshot
to the SQLite online Backup API and makes the login modal recover automatically
from a transient capability-probe failure. Evidence and acceptance criteria are
recorded in
[auth-bot-login-reliability-20260723.md](auth-bot-login-reliability-20260723.md).

Availability follow-up `IMG-WATCHDOG-P0-20260723`: an image-edit prompt could
fill VRAM, outlive an application-side history request timeout and leave
ComfyUI running while the application queue advanced. The corrective package
keeps the selected model, prevents reference upscaling, enforces the existing
face megapixel budget, separates the five-minute image deadline from video,
and gates later submissions until a privileged ComfyUI-only restart is healthy.
The recovery helper does not mutate the persistent application queue. Design,
installation and acceptance evidence are recorded in
[comfyui-image-vram-watchdog-20260723.md](comfyui-image-vram-watchdog-20260723.md).
The 2026-07-24 follow-up also closes the model-switch gap in outpaint: 4B keeps
its compatible LoRA path, while 9B now has the official KV FP8 checkpoint and
retains `FluxKVCache`. A real local 9B outpaint completed in 52.3 seconds
without cancelling or reordering the next application job.

## 0. Ответ: готов ли этот план к реализации

Да. План разбит на ограниченные пакеты с порядком, областью изменения,
обязательными тестами, production boundary, rollback и критериями завершения.
Первый следующий кодовый пакет определён однозначно: **`REL-LOCK-001`**.

План не обещает одномоментно сделать проект «идеальным». Он задаёт безопасную
последовательность для уже работающего продукта с реальными пользователями:

1. остановить гонки агентов и закрыть публичные diagnostics;
2. доказать работоспособность Telegram, mail и backup, не меняя VPS;
3. усилить auth, workers, billing и process supervision;
4. по одному seam уменьшать большие backend/frontend файлы;
5. переходить на Linux/PostgreSQL/внешнюю очередь только по измеряемым scale
   triggers, а не ради моды.

## 1. Неизменяемые решения владельца

- Application stack сейчас работает на одном личном Windows-компьютере.
- VPS используется только как transport домена/tunnel. Пакеты этого плана не
  меняют VPS, FRP, DNS или домен без отдельного явного запроса.
- Проект уже production: есть пользователи, платежи, jobs, изображения, feed,
  gallery, Telegram/MAX и mail integration.
- Оптимизация должна сохранять пользовательское поведение и данные.
- Текущие providers: YooKassa для платежей и UniSender/mail adapters для почты.
  Их не меняем без доказанной продуктовой/операционной причины.
- Администратор может просматривать пользовательский оригинал для поддержки;
  доступ должен быть role-gated и аудироваться.
- Начальная экономика рассчитана на локальный host. Budget/managed services
  пересматриваются при росте, а не являются blocker текущей оптимизации.
- Linux/Docker/PostgreSQL — будущий scale step, не текущая цель.

## 2. Базовая точка

| Показатель | Baseline 2026-07-19 |
|---|---|
| Git | `main == origin/main == dbb1ca253dfea926096bc494a03449d9f9917cc6` до governance package |
| Live release | `dbb1ca253dfe-20260719043420` |
| Runtime | Python 3.11.9, Node 24.14.1, Caddy edge, FastAPI/Uvicorn |
| DB | SQLite `user_version=1`, 57 tables, ~565 MB, один live writer process |
| Backend monolith | 20,311 lines; 728 top-level functions; 83 classes; 223 routes |
| Frontend large files | `newStudioV3.css` 5,875; `newUi.tsx` 4,378; `LegacyApp.tsx` 3,600 |
| Workers | generation, Telegram polling, MAX polling, feed-video publication |
| Backup | local hourly/cloud daily fresh; health `ATTENTION` из-за AdGuard VPN route |
| External CI | GitHub Actions запускается, но billing/spending blocker завершает run до steps |

Baseline подтверждает текущее состояние, но не фиксирует его навсегда. Каждый
пакет заново проверяет Git/live/process/data boundary.

## 3. Значения статусов

| Статус | Что он означает |
|---|---|
| `TODO` | пакет ещё не начат |
| `ACTIVE` | есть один назначенный owner и текущий WIP |
| `IN REVIEW` | bounded package реализован в ветке и проходит review/acceptance gates |
| `CODE COMPLETE` | код/документация реализованы и targeted tests зелёные |
| `DEPLOYED` | exact SHA/release активен в production |
| `VERIFIED` | все acceptance gates пакета подтверждены evidence |
| `OPERATIONALLY VERIFIED` | реальный provider/user flow подтверждён redacted receipt |
| `BLOCKED` | named external dependency не позволяет пройти следующий gate |

Нельзя заменять один статус другим. В частности, зеленый unit test не делает
mail `OPERATIONALLY VERIFIED`, а HTTP 200 не доказывает корректность UI.

## 4. Инварианты любого пакета

1. Перед началом выполняются правила `AGENTS.md` и фиксируется preflight.
2. Один owner — один пакет; release/Full verify — строго single-flight.
3. Production DB/media/secrets/providers не используются тестами.
4. Сначала characterization/negative/race test, затем изменение поведения.
5. Публичный API сохраняется или меняется через явно документированную версию.
6. Новая backend-логика не добавляется в `backend/main.py`.
7. Protected-file budgets не повышаются для принятия роста.
8. Generated maps меняются в том же code-bearing commit.
9. Full suite не запускается несколько раз параллельно.
10. Deploy/restart выполняется только если входит в пакет и явно разрешён.
11. UI-пакет включает desktop/mobile evidence; static `/feed` и `/gallery`
    проверяются отдельно от React shell.
12. Commit, docs и push входят в Definition of Done; deploy имеет отдельный статус.

## 5. Точная очередь исполнения

| Порядок | ID | Приоритет | Результат | Статус |
|---:|---|---|---|---|
| 0 | `GOV-001` | P0 | единые правила и новый plan/audit | `VERIFIED` |
| 1 | `REL-LOCK-001` | P0 | один publisher/Full verifier, no race | `VERIFIED` 2026-07-20 (evidence в секции пакета) |
| 2 | `SEC-DIAG-001` | P0 | public API не раскрывает operator details | `VERIFIED` 2026-07-20 (evidence в секции пакета) |
| 3 | `BOT-TG-001` | P0 | Telegram polling operational health доказан | `VERIFIED` 2026-07-20 (evidence в секции пакета) |
| 4 | `BACKUP-NET-001` | P1 | backup health зелёный с approved route | `VERIFIED` 2026-07-20 (evidence в секции пакета) |
| 5 | `MAIL-OPS-001` | P1 | UniSender delivery подтверждён | `DEFERRED_BY_OWNER` 2026-07-20 |
| 6 | `AUTH-LEGACY-001` | P1 | legacy auth consumers безопасно сокращаются | WIP сохранён как handoff (см. current-status); active code package отсутствует; далее `AUTH-LEGACY-001A` по плану 20260720 |
| 7 | `OPS-001` | P1 | service supervision и reboot/crash recovery | `TODO` |
| 8 | `REL-002` | P1 | immutable backend A/B switch + drain | `TODO` |
| 9 | `OBS-001` | P1 | actionable health/metrics/receipt evidence | `TODO` |
| 10 | `DB-MIG-002` | P1 | все новые schema changes — versioned migrations | `TODO` |
| 11 | `WORK-001` | P1 | persistent leasing/recovery/watchdogs | `TODO` |
| 12 | `BILL-001` | P1 | единая финансовая transaction boundary | `TODO` |
| 13 | `ARCH-BE-A..G` | P2 | `main.py` становится composition shell | `TODO` |
| 14 | `ARCH-FE-A..E` | P2 | frontend/CSS делятся по features | `ARCH-FE-A / Wave 1 — IN REVIEW`; `ARCH-FE-B..E — TODO` |
| 15 | `PORT-001` | P2 | воспроизводимый новый Windows host/standby | `TODO` |
| 16 | `SCALE-001` | trigger-based | Linux/PostgreSQL/queue readiness | `NOT TRIGGERED` |

Новая feature/UI правка может войти между пакетами только если не пересекает их
файлы/инварианты, имеет собственного owner и проходит свой targeted gate. Она не
перепрыгивает P0 security/release blockers для production deploy.

## 6. P0: управление агентами, release и публичная безопасность

### GOV-001 — единые правила для всех агентов

Цель: устранить противоречивые инструкции.

Состав:

- корневой `AGENTS.md`;
- актуальный `CLAUDE.md`;
- `.github/copilot-instructions.md`;
- `GEMINI.md`;
- автоматический `tools/test_agent_instructions.py`;
- этот plan и evidence audit;
- README указывает новый источник истины;
- старый master plan помечен superseded.

Acceptance:

- каждый adapter требует прочитать `AGENTS.md`;
- stale запреты старой identity-фазы отсутствуют;
- тест правил проходит;
- Quick verification зелёный;
- package committed и pushed без deploy/restart.

Verification evidence для этого package:

- `tools/test_agent_instructions.py`: 3 tests passed, пять последовательных
  запусков;
- architecture inventory и backend symbol map: `--check` passed;
- `tools/verify.ps1 -Mode Quick`: 79 tests passed, 55.58 s, source stable;
- production restart/deploy этим governance package не выполнялся.

### REL-LOCK-001 — single-flight repository operations

Цель: два агента физически не могут одновременно публиковать release или
запускать duplicate Full verification.

Предлагаемая реализация:

1. общий helper `tools/repository-operation-lock.ps1`;
2. атомарный lock directory под `.runtime/locks/<kind>`;
3. owner metadata: operation id, PID, process start time, SHA, command, UTC start;
4. отдельные kinds `public-release` и `full-verify`;
5. re-entrancy token, чтобы publisher мог вызвать verifier без deadlock;
6. `try/finally` release;
7. stale recovery только если PID/process-start больше не совпадает; TTL сам по
   себе не имеет права убить живого owner;
8. второй owner завершает работу до tests/build/runtime mutation с ясной ошибкой;
9. `start-public.bat`, publisher и `verify.ps1 -Mode Full` используют helper;
10. lock metadata игнорируется Git и не содержит secrets.

Обязательные тесты:

- два concurrent publisher preflight: победитель один;
- второй не запускает pytest/build/restart;
- stale dead PID восстанавливается;
- PID reuse не считается тем же owner без совпадения process-start;
- exception освобождает lock;
- re-entrant publisher -> Full verify не deadlock;
- focused concurrency suite проходит **5 последовательных раз**;
- Quick и один Full receipt проходят один раз на clean SHA.

Production boundary: не менять DB/media/VPS; deploy нужен только в отдельном
release step после code verification, не для проверки самого lock helper.

Rollback: удалить wiring на helper, сохранив прежние launch commands; lock
directories безопасно остаются runtime evidence.

Реализация 2026-07-20:

- `tools/repository-operation-lock.ps1`: dot-sourceable библиотека
  (`Lock-IzoRepositoryOperation` / `Unlock-IzoRepositoryOperation`) + CLI
  (`acquire`/`release`/`status`) для batch launchers; атомарность через staging
  directory и `Directory.Move`; владелец фиксируется как PID + точное UTC время
  старта процесса; stale recovery только при мёртвом PID или PID reuse; TTL не
  применяется к живому владельцу; re-entrancy через env token
  `IZO_REPO_LOCK_TOKEN_<KIND>`.
- `tools/verify.ps1 -Mode Full` берёт `full-verify` до любых
  pytest/build/runtime шагов и освобождает в `finally`; Quick/CI не блокируются.
- `tools/publish-frontend-release.ps1` берёт `public-release` (re-entrant из
  `start-public.bat`) и `full-verify`, экспортирует token дочернему verifier.
- `start-public.bat` владеет `public-release` на всё время запуска; владелец —
  cmd-процесс launcher, поэтому crash восстанавливается автоматически; release
  на всех exit paths через `:release_lock`.

Verification evidence:

- `tools/test_repository_operation_lock.py`: 9 tests
  (concurrent single winner; second Full verify fails fast без единого
  VERIFY_STEP; stale dead PID recovery; PID reuse отклонён по start time;
  живой owner не отбирается; exception освобождает lock; re-entrant без
  deadlock и без освобождения внешнего lock; чужой token не может release;
  wiring всех трёх entrypoints) — `9 passed` в пяти последовательных запусках;
- `tools/verify.ps1 -Mode Quick`: 79 passed, 48.75 s, source stable;
- contract-тесты verify/launchers/collection после включения нового файла в
  Quick-набор: 26 passed;
- первый Full запуск честно упал: новый тест был негерметичен (пытался взять
  `full-verify`, который законно держал внешний verifier); исправлено commit
  `3fc06fe` — тест переиспользует живой busy state и убирает re-entrancy token
  у дочернего verifier; lock при падении корректно освобождён `finally`,
  остаточных pytest не было;
- Full receipt на clean SHA `3fc06fef0b58…`: 1564 passed, frontend
  lint/build/identity/origin/resilience PASS, receipt
  `3fc06fef0b58-20260720105555-rellock.json`;
- live proof: работающий Full держал `full-verify` (owner PID 15704,
  stale=False), статус после — FREE.

Deployment evidence 2026-07-20 (рестарт явно разрешён владельцем):

- окно спокойное: active jobs 0, `preparing` feed publications 0 (read-only);
- `start-public.bat` владел `public-release` (owner cmd PID 29472); publisher
  re-entered по token, принял exact-SHA receipt без второго Full;
- candidate smoke на 5197 OK, активация `caddy-reload`, release
  `3fc06fef0b58-20260720110528`, previous `dbb1ca253dfe-20260719043420`
  сохранён для rollback;
- controlled backend restart: oldPid=28452 → newPid=64648, start 11:05:52;
- локальные пробы: health/capabilities 200; dev-client=False; hashed
  asset=True; release meta/shell `/feed` `/gallery`/api-version совпадают;
  generate/gallery/me-v2 no-session = 401;
- публичный домен: `/`, `/feed`, `/gallery`, `/api/health` 200,
  `/api/version` = `3fc06fef0b58-20260720110528`;
- оба lock освобождены (FREE); порт 8000 — один владелец 64648; 8001 свободен;
- свежий backend лог: 0 error-строк, 0 `TelegramTransportError`, MAX polling
  200.

Статус пакета: `VERIFIED` (код + acceptance в production окружении).

### SEC-DIAG-001 — минимальные публичные status endpoints

Цель: убрать operator intelligence из unauthenticated API.

Изменения:

- `/api/platforms` возвращает только public capability/ready/button/command data;
- абсолютный `DB_PATH` и database existence удаляются;
- `/api/bots/status` либо становится минимальным public product status, либо
  существующие consumers переводятся на новый public DTO;
- полные token/mode/URL/TLS/probe diagnostics остаются только в
  `/api/admin/bots/status-v2` с `require_trusted_admin`;
- payload builder и routes выносятся из `main.py` как первый low-risk seam;
- frontend/static consumers и кеширование проверяются до изменения.

Tests:

- anonymous payload не содержит drive letter, `DB_PATH`, token presence,
  webhook URL, TLS/proxy/internal API base;
- non-admin не получает admin diagnostics;
- trusted admin получает необходимые redacted diagnostics;
- `/new`, `/feed`, `/gallery` smoke не регрессируют;
- contract tests выполняются до/после extraction.

Acceptance: public redaction verified local/public; exact SHA deployed только
после authorized release.

Реализация 2026-07-20:

- новый seam `backend/app/services/platform_status.py`:
  `public_platforms_payload()` и `public_bots_status_payload()` — только
  product capability (ready/url/commands/buttonText); маршруты в `main.py`
  стали thin adapters;
- `bot_status_payload()` удалён из `main.py`; operator diagnostics существуют
  только в `/api/admin/bots/status-v2` (`require_trusted_admin`, 401 anonymous);
- из `/api/platforms` удалён блок `database` (абсолютный `DB_PATH` и
  existence); из `/api/bots/status` удалены tokens/mode/publicUrls/webhook/
  TLS/polling диагностика;
- consumers проверены до изменения: единственный frontend consumer —
  `frontend/e2e-stage1.mjs` (обновлён; UI не использует эти поля), README
  обновлён; admin UI использует `status-v2`;
- новый `backend/test_public_status_redaction.py` (4 теста: product-safe
  platforms; минимальный bots status без operator-ключей; сконфигурированный
  internal `BACKEND_PUBLIC_URL` не протекает; admin diagnostics 401);
- обновлены `test_api.py`, `test_bot_login_flow.py` под новый контракт;
- budgets ratcheted down в том же commit: `main.py` max_lines 20314→20258,
  functions 750→727, classes 90→83, routes 230→223.

Verification evidence:

- focused: 88 passed (redaction+api+bot_login+admin_bots); redaction file —
  5 последовательных запусков 4 passed;
- `tools/verify.ps1 -Mode Quick`: 88 passed, 52.76 s, source stable;
- generated maps/inventory регенерированы в том же commit;
- Full receipt на clean SHA `432f9b38199d…`: 1568 passed + все frontend gates,
  receipt `432f9b38199d-20260720112049-secdiag.json`.

Deployment evidence 2026-07-20 (рестарт разрешён владельцем, окно спокойное —
0 active jobs, 0 preparing publications):

- release `432f9b38199d-20260720112903` через locked pipeline: receipt принят
  без второго Full, candidate smoke OK, `caddy-reload`, backend
  oldPid=64648 → newPid=47856, previous release сохранён;
- локальные пробы: health/api 200, release identity совпадает,
  generate/gallery/me-v2 no-session = 401;
- публичный домен: `/`, `/feed`, `/gallery`, `/api/health` 200,
  `/api/version` = `432f9b38199d-20260720112903`;
- live redaction на `https://izo.alikinas.ru`: `/api/platforms` keys =
  web/telegram/max (без `database`), `/api/bots/status` keys = ok/platforms;
  в сериализованных payload нет drive letter, sqlite, token, webhook,
  `127.0.0.1:8000`, `platform-api`; anonymous `/api/admin/bots/status-v2` = 401;
- свежий backend лог: 0 error-строк; оба lock FREE; порт 8000 — один
  владелец 47856; 8001 свободен.

Статус пакета: `VERIFIED` (код + public redaction в production).

### BOT-TG-001 — Telegram operational recovery

Цель: заменить «token configured» на доказанную доставку/polling health.

Диагностика до изменения:

- один ли backend владеет polling;
- webhook действительно выключен оператором для polling mode;
- DNS/TLS/proxy/firewall/IPv4/IPv6 path до Telegram API;
- timeout class и safe error code без token/URL leakage;
- last successful `getMe` и `getUpdates` timestamps;
- cursor before/after restart;
- retry/backoff/jitter и rate-limit behavior.

Реализация:

- provider health model с last success, last safe error, consecutive failures;
- bounded exponential backoff + jitter;
- alert после порога, recovery event после успеха;
- один owner; startup не создаёт duplicate polling task;
- admin UI показывает operational state, public API — только minimal readiness.

Tests: fake transport timeout/TLS/429/5xx/success, cursor idempotency, restart
recovery, duplicate-owner prevention. Real verification не удаляет webhook и не
сбрасывает cursor автоматически.

Acceptance: redacted `getMe`/poll cycle success и controlled restart evidence.

Реализация 2026-07-20:

- новый seam `backend/app/services/polling_health.py`: `PollingHealthRegistry`
  (last success/failure timestamps, safe error class, consecutive failures,
  alert exactly-once на пороге, recovery event), `compute_poll_backoff`
  (bounded exponential + jitter; более длинный provider Retry-After всегда
  уважается), сюда же перенесены `polling_retry_after` /
  `is_auth_polling_error`;
- worker'ы Telegram/MAX используют общий `_provider_polling_cycle`: health на
  каждом цикле, лог-маркеры `BOT_POLLING_ALERT`/`BOT_POLLING_RECOVERED` только
  с классом исключения; auth-ошибка по-прежнему останавливает worker и пишет
  `security_events`;
- `start_bot_polling_tasks`: живой owner никогда не дублируется; завершённый
  task заменяется только явным вызовом start (restart recovery);
- admin `/api/admin/bots/status-v2` получил `pollingHealth` для обоих
  провайдеров; public API не изменился (минимальный после SEC-DIAG-001);
- webhook не удаляется, cursor не сбрасывается — нигде автоматически;
- `mini_app_url` дедуплицирован в `platform_status.mini_app_public_url`;
  budgets ratcheted: max_lines 20258→20257, functions 727→725.

Verification evidence:

- `backend/test_polling_health.py`: 10 tests (bounded backoff+jitter;
  provider Retry-After; классификаторы на fake transport/429/5xx/auth;
  alert exactly-once + recovery; snapshot без секретов; worker cycle с
  ростом backoff и recovery; auth-stop с security_event; duplicate-owner
  prevention; restart recovery; cursor advance + идемпотентность пустого
  poll) — `10 passed` в пяти последовательных запусках;
- focused (polling_health+api+bot_login+admin_bots+integrations):
  131 passed; исправлен `FakeTask` в `test_api.py` (нужен `done()`);
- `tools/verify.ps1 -Mode Quick`: 88 passed, 65.01 s, source stable;
- generated maps/inventory в том же commit;
- Full receipt на clean SHA `263377ff0d5d…`: 1578 passed + все frontend gates,
  receipt `263377ff0d5d-20260720114925-bottg.json`.

Deployment/operational evidence 2026-07-20 (рестарт разрешён владельцем, окно
спокойное — 0 active jobs, 0 preparing publications):

- release `263377ff0d5d-20260720115826` через locked pipeline
  (`caddy-reload`); backend oldPid=47856 → newPid=64648, start 11:58:50;
- публичный smoke: `/`, `/api/health` 200; `/api/version` =
  `263377ff0d5d-20260720115826`; no-session generate/gallery/me-v2 = 401;
- стартовый лог: `telegramMode=polling maxMode=polling`;
- окно наблюдения 8+ минут: 0 `TelegramTransportError`, 0
  `telegram polling error`, 0 `BOT_POLLING_ALERT`, err-лог пуст — при
  long-poll timeout 25 s это ≥19 успешных Telegram-циклов, так как каждый
  сбой обязан оставить лог-строку с backoff;
- MAX: 19 × `MAX_POLL_RESPONSE status=200` за то же окно (прямое evidence);
- порт 8000 — один владелец 64648; оба operation lock FREE;
- webhook не удалялся, cursor не сбрасывался.

Статус пакета: `VERIFIED`; polling health `OPERATIONALLY VERIFIED` в окне
наблюдения (redacted log evidence без token/URL).

## 7. P1: backup, mail и операционная устойчивость

### BACKUP-NET-001 — зелёный offsite backup route

Цель: убрать единственную текущую backup health ошибку без отключения защиты
вслепую.

Шаги:

1. зафиксировать текущий AdGuard/VPN mode и route evidence;
2. настроить approved split route для Yandex Disk endpoints либо явно изменить
   policy после owner decision;
3. не ослаблять firewall/listeners;
4. дождаться hourly local и daily cloud stage;
5. выполнить verify-only и rehearsal restore последнего snapshot;
6. сохранить health evidence вне Git без секретов.

Acceptance: task last result 0, `OverallStatus=OK`, fresh local/cloud snapshot,
verified manifest и successful restore rehearsal.

Реализация и evidence 2026-07-20:

- owner decision: Яндекс Диск внесён в exclusions AdGuard VPN; функциональная
  проверка подтвердила in-tunnel split — egress, который видит Яндекс,
  отличается от общего VPN egress (адреса сравнивались только в памяти и не
  сохранялись);
- policy `ops/backup/check_backup_health.ps1` обновлена по owner decision:
  ошибка `yandex_routed_through_adguard_vpn` ставится только когда маршрут
  идёт через AdGuard И split НЕ доказан (fail-closed при недоступности любой
  из двух egress-проб); в health добавлен boolean `YandexEgressSplitActive`;
  firewall/listeners не менялись;
- runtime-копия `C:\IZO_ASA\runtime\check_backup_health.ps1` синхронизирована;
  scheduled task `IZO_ASA Backup Health 10m` запущена штатно: Last Result 0;
- `C:\IZO_ASA\health\backup-current.json`: `OverallStatus=OK`,
  `YandexSyncErrors=[]`, `YandexEgressSplitActive=true`, свежие
  `LastLocalBackup` (hourly) и `LastCloudStage` (daily 01:00);
- verify-only: `BACKUP_VERIFY_OK` + `LOCAL_BACKUP_STATUS_OK`
  (snapshot 565 MB DB, 1175 media files, manifest sha в health);
- rehearsal restore: `REHEARSAL_RESTORE_OK` новейшего snapshot в
  `D:\IZO_ASA_RestoreTest` (snapshot читался, production не затрагивался);
- новый contract-тест `test_yandex_route_check_requires_proven_egress_split`
  в `tools/test_backup_automation.py`; backup-тесты 17 passed; Quick 88
  passed;
- health evidence хранится вне Git и не содержит секретов/адресов.

Статус пакета: `VERIFIED`; маршрут `OPERATIONALLY VERIFIED` (split доказан
на живом соединении).

### MAIL-OPS-001 — UniSender от настройки до доставки

Цель: доказать реальную отправку, сохранив тесты безопасными.

Кодовые требования:

- API key только env/DPAPI;
- provider adapter не смешан с route;
- retry policy не дублирует письмо;
- durable outbox/idempotency key для обязательных уведомлений;
- safe provider error taxonomy и metrics;
- admin verify endpoint не возвращает key/request secrets.

Operator gate:

- владелец явно указывает безопасный тестовый адрес;
- отправляется одно маркированное письмо;
- фиксируются provider message id/time и факт получения без адреса/ключа в Git;
- 502/timeout проверяются как retryable, auth/template errors — fail-fast.

Acceptance: unit/integration tests + один полученный test email =
`OPERATIONALLY VERIFIED`. Без inbox evidence статус не выше `DEPLOYED`.

2026-07-20: `DEFERRED_BY_OWNER` («работу с почтой пропускаем»). UniSender-код
остаётся `DEPLOYED`; доставка не доказывалась; operator gate не выполнялся.
Возобновление возможно с той же спецификацией.

### AUTH-LEGACY-001 — закрытие compatibility authorization

Цель: legacy идентификаторы никогда не дают доступ к protected state.

Шаги:

- построить route matrix: public/optional/session/user/admin/webhook;
- negative tests для `X-OneNode-User`, изменяемой cookie, unsigned Telegram/MAX;
- доказать, что reviewed legacy consumers только создают compatibility output или
  security audit;
- перевести оставшиеся protected routes на trusted dependencies;
- удалять allowlist entry сразу после consumer removal;
- не менять `users.id` destructively; internal identity остаётся additive;
- закрыть CSRF для cookie-auth mutations и проверить SameSite/Secure policy.

Acceptance: legacy protected-route consumers = 0; compatibility output имеет
явную дату удаления; auth focused suite 5x; live login/logout/session/admin smoke.

### OPS-001 — Windows service supervision

Цель: stack восстанавливается после crash/reboot без ручных PowerShell окон.

Решение для текущего host: pinned WinSW либо эквивалентный проверенный wrapper под
выделенной Windows account, потому что DPAPI и model stores account-bound.

Services/ownership:

- Caddy;
- backend;
- ComfyUI dependency;
- Ollama dependency;
- optional Qwen ASR;
- tunnel launcher только в пределах локальной стороны текущей конфигурации.

Backup tasks могут остаться Task Scheduler.

Acceptance: least-privilege account, delayed dependency ordering, restart
backoff, log rotation, crash rehearsal, full reboot rehearsal, exact release
identity, DPAPI read, local/public smoke. VPS/FRP configuration не меняется.

2026-07-22 cold-start hardening: интерактивный production orchestrator создаёт
exact-SHA CI verification receipt, когда backend ещё не имеет listener после
перезагрузки, и передаёт её штатному immutable publisher. Это устраняет
циклическую зависимость «backend должен работать до собственного запуска».
Полный запуск до входа пользователя остаётся в OPS-001: он требует отдельной
Windows service identity и подтверждённого доступа этой identity к DPAPI,
моделям и GPU runtime; Startup-folder сценарий выполняется только после входа.

### REL-002 — immutable backend A/B

Цель: release не зависит от mutable checkout после activation.

Требования:

- immutable backend artifact/manifest с requirements/runtime identity;
- candidate backend на отдельном loopback port;
- schema compatibility preflight до switch;
- readiness и focused smoke;
- Caddy/API switch только после readiness;
- drain старого backend и workers;
- rollback artifact остаётся runnable;
- DB migration compatibility window forward/backward документирована.

Acceptance: fault-injected candidate не затрагивает old backend; successful
switch не теряет jobs; rollback rehearsal; exact frontend/backend identity.

### OBS-001 — evidence и alerts

- Full receipt фиксирует pytest passed/failed/skipped counts, runner versions,
  frontend lint/build summary и durations;
- worker health: queue depth/age, oldest job, last success/error;
- payment/mail webhook/outbox metrics без PII;
- Telegram/MAX last delivery success;
- storage/DB/WAL/free-space/backup freshness;
- Caddy/backend restart count and release id;
- alerts дедуплицируются и имеют recovery event.

GitHub CI billing blocker решается отдельно владельцем аккаунта. До этого local
CI receipt обязателен, но не выдаётся за GitHub success.

## 8. P1: БД, workers и деньги

### DB-MIG-002 — настоящая последовательность migrations

Текущее состояние: ledger v1 существует, но только фиксирует legacy baseline.

Правило для будущего:

- каждое schema изменение получает monotonic version, unique name/checksum;
- migration применима повторно или ledger делает повтор no-op;
- unknown future version fail-closed;
- heavy rebuild выполняется maintenance command, не скрыто на startup;
- до rebuild: SQLite Backup API snapshot, space check, copy audit, rollback plan;
- startup только применяет bounded additive migration либо отказывается безопасно;
- migration tests используют копию representative schema/data, не live DB.

Acceptance: первая реальная v2 migration проходит fresh, legacy-upgrade,
idempotency, interrupted/retry и unsupported-version cases.

### WORK-001 — durable leasing и watchdogs

Цель: процесс может упасть в любой точке, а обязательство не теряется и не
выполняется дважды.

Сначала без Redis:

- SQLite — source of truth;
- in-process queue только будит consumer;
- lease owner/lease expiry/attempts/next_attempt/error_class;
- atomic claim; idempotency key; terminal/dead-letter state;
- startup recovery и watchdog для generation/feed-video/mail;
- polling cursor transactionally advances after handled update;
- graceful shutdown прекращает claims и завершает/освобождает lease.

Acceptance: kill/restart tests, duplicate wake-up, expired lease, poison job,
concurrent claim 5x, backlog age metrics.

Внешняя очередь рассматривается только при нескольких worker hosts или когда
SQLite leasing latency/backlog нарушает SLO. До этого новый Redis — лишний
операционный компонент.

### BILL-001 — единая финансовая transaction boundary

- route/webhook/admin не пишут balance/ledger/invoice напрямую;
- provider event authenticity проверяется до mutation;
- provider event id + business idempotency уникальны;
- invoice transition, token grant/refund и immutable ledger — одна transaction;
- повтор/параллельный webhook даёт тот же результат;
- manual admin action проходит тот же service и audit log;
- reconciliation job сравнивает provider/invoice/ledger;
- сумма, валюта, тариф и user binding проверяются server-side.

Tests: paid/canceled/refund/out-of-order/duplicate/concurrent/manual race; focused
financial suite 5x. Реальные charges/refunds не выполняются автоматически.

### DATA-RET-001 — privacy и retention

Техническая политика до юридического текста:

- originals private by default;
- support-admin read — только trusted role + audit reason/time;
- public feed хранит отдельную deliberate derivative;
- user deletion не удаляет финансовые/audit обязательства произвольно;
- retention periods конфигурируются и применяются отдельной dry-run cleanup job;
- delete report показывает DB/media/public derivative outcomes;
- product owner утверждает сроки и privacy notice с профильным юристом РФ.

До утверждения сроков запрещена автоматическая массовая очистка originals.

## 9. P2: последовательное уменьшение `backend/main.py`

### Общая стратегия

Первый code package после governance фиксирует budget на фактическом значении и
дальше только уменьшает его. `main.py` остаётся запущенным на каждом шаге; router
или service подключается через стабильную dependency boundary. Не переносить
несколько несвязанных доменов одним commit.

Целевое состояние: `main.py` содержит app/lifespan composition, router wiring и
временно явно помеченные compatibility adapters; ориентир — не более 2,000 строк.
Это долгосрочный end state, а не условие одного release.

### ARCH-BE-A — public diagnostics и platform composition

- вынести DTO/builders и маршруты `/api/platforms`, minimal bot status;
- использовать существующий `app/services/bot_admin.py` для admin details;
- characterization tests на точный безопасный contract;
- снизить main line/symbol budget до нового факта.

### ARCH-BE-B — bot admin и polling lifecycle

- router: admin bot status/token/verify/webhook operations;
- services: Telegram/MAX polling ownership/health;
- integrations остаются transport adapters;
- lifespan registry запускает workers через единый supervisor interface;
- no behavior change, tests Telegram и MAX раздельно.

### ARCH-BE-C — mail orchestration

- mail router, application service, durable outbox, provider adapter;
- template/rendering отдельно от delivery;
- fake-provider contract tests;
- main оставляет только router include.

### ARCH-BE-D — gallery/media routes

- routers используют уже существующие `storage/*` и `services/gallery_*`;
- ownership/private/public boundaries централизованы;
- media lifecycle tests: upload -> gallery -> publish -> delete private -> public
  read -> public unpublish/delete;
- никаких массовых file moves без plan/apply/recovery journal.

### ARCH-BE-E — feed image/video publication

- publication command/query services;
- worker и recovery ownership из main;
- moderation/reactions/views routes сгруппированы, но domain state остаётся одним;
- `test_feed_v2.py` делится по contract, publication lifecycle, video,
  moderation/reactions; tests не дублируются.

### ARCH-BE-F — generation, models и integrations

- routes становятся thin adapters к существующим generation services;
- ComfyUI/OpenRouter/Ollama/Qwen clients не импортируют main globals;
- runtime config инжектируется типизированным settings object;
- model branding проверяется на всех public payloads.

### ARCH-BE-G — identity и billing последними

- выполнять только после `AUTH-LEGACY-001` и `BILL-001` characterization;
- identity routers/dependencies/session service;
- billing routers/application service/repository ports/provider adapter;
- negative/race tests 5x;
- main остаётся composition shell.

Acceptance каждой волны:

- поведение API доказано before/after contract tests;
- targeted suite + architecture maps + Quick green;
- main line/functions/classes уменьшаются;
- budget снижен в том же commit;
- новый модуль не становится новым несвязным монолитом;
- no production deploy до отдельного clean release gate.

## 10. P2: frontend и CSS

### ARCH-FE-A — `newUi.tsx`

- оставить route/shell composition;
- вынести API client/hooks, session/bootstrap state, navigation/layout и feature
  views;
- запретить cross-feature hidden globals;
- единые loading/error/empty contracts.

Target: `newUi.tsx` постепенно <= 800 строк; feature module обычно <= 500.

#### ARCH-FE-A / Wave 1

| Поле | Значение |
|---|---|
| Package | `ARCH-FE-STUDIO-001A` |
| Branch | `arch/fe-studio-001a` |
| PR | `#9` |
| Status | `IN REVIEW` |
| Result | `newUi.tsx` 4,378 -> 3,628 строк |

Scope волны:

- types;
- API;
- bounded state hooks;
- draft storage;
- image/canvas processing;
- navigation/SEO;
- shared presentation helpers.

Дальнейшее уменьшение `newUi.tsx` является следующей отдельной волной, а не
незаконченной частью PR #9. CI-статус фиксируется в review evidence после
выполнения acceptance gate и не подразумевается статусом `IN REVIEW`.

### ARCH-FE-B — `newStudioV3.css` и `newUi.css`

- tokens/base/layout отдельно;
- component/feature styles рядом с feature;
- responsive rules остаются с соответствующим компонентом;
- не переименовывать массово classes одновременно со split;
- desktop 1440px и mobile 390px visual regression на каждой волне.

### ARCH-FE-C — Video Studio

- controls, progress/pricing, input assets, result viewer и responsive layout
  делятся на components/hooks/styles;
- price до history/usage сохраняется;
- generation state не дублируется между shared preview и local component.

### ARCH-FE-D — admin/profile

- `adminModels.tsx`: query/filter/table/editor/bulk actions;
- `ProfilePage.tsx`: identity/security/subscription/activity sections;
- admin visibility проверяется trusted role, не только наличием ссылки;
- provider/secrets fields не попадают в client logs.

### ARCH-FE-E — Legacy/static shells

- `LegacyApp.tsx` freeze: bug/security fixes only;
- Legacy отключается только когда current UI имеет parity, rollback и legacy
  traffic <1% активных сессий 30 последовательных дней;
- static `/feed` и `/gallery` либо используют shared generated assets/contracts,
  либо имеют отдельные DOM/behavior tests; React build не считается их тестом.

## 11. PORT-001 — переносимость нового Windows-компьютера

Этот пакет готовит новый host, не переключая production до rehearsal:

- Git и clean clone exact SHA;
- Python 3.11.9, `.venv`, exact `requirements.txt`, `pip check`;
- Node 24.14.1, `npm ci`, production build;
- pinned NVIDIA driver evidence, ComfyUI version/workflows/custom nodes и только
  реально используемые models;
- Ollama models/version и loopback bind;
- pinned Caddy, local tunnel launcher/config separately;
- DPAPI secrets **не копируются**: keys/tokens re-enter/rotate под service account;
- backup restore rehearsal в новые DB/media paths;
- service definitions, firewall, autostart and reboot rehearsal;
- old host остаётся rollback owner до acceptance.

Cutover требует maintenance window: это и есть допустимый downtime — заранее
согласованный период, когда новые записи временно остановлены для final backup,
restore и switch. До измерения объёма final delta точная длительность не обещается.

## 12. SCALE-001 — когда действительно менять платформу

### PostgreSQL trigger

Начать проект миграции, если выполняется хотя бы одно устойчивое условие:

- нужен второй backend writer/process или несколько application hosts;
- повторяющиеся `SQLITE_BUSY` остаются после правильных short transactions/retry;
- write latency/maintenance/backup нарушает утверждённый SLO;
- billing reconciliation и concurrent workflows невозможно надёжно обслуживать
  одним SQLite writer;
- выполняется переход на production Linux server и managed DB укладывается в
  утверждённый budget.

Предпочтение тогда: managed PostgreSQL рядом с Linux application server с PITR,
а не база на tunnel VPS только потому, что VPS уже существует.

### External queue trigger

Redis/RabbitMQ/другая очередь нужна, когда:

- workers живут на нескольких hosts/process roles;
- SQL leasing создаёт измеренную contention/backlog проблему;
- нужны routing/rate/scheduling semantics, которые нельзя безопасно реализовать
  текущим durable job table.

До trigger SQLite durable leasing + in-process wake-up проще и надёжнее.

### Linux/Docker trigger

- один Windows host перестаёт удовлетворять availability/capacity;
- есть утверждённый server budget и operator plan;
- secrets, models, GPU runtime, backup/restore и observability воспроизводимы;
- current Windows service/release path уже документирован, чтобы migration не
  скрывала старые operational defects.

## 13. Матрица обязательных проверок

| Изменение | Targeted | Повтор 5x | Quick | Full | Live/provider |
|---|---:|---:|---:|---:|---:|
| docs/agent rules | да | нет | да | нет | нет |
| pure module extraction | да | нет | да | перед release | smoke после deploy |
| auth/security | да | да | да | да | login/logout/admin negative |
| payments/ledger | да | да | да | да | sandbox/reconciliation; no real charge by default |
| worker/queue | да | да | да | да | controlled restart/recovery |
| release lock/switch | да | да | да | один раз | rollback/switch rehearsal |
| DB migration | да | да для interruption/race | да | да | backup + rehearsal on copy |
| frontend/CSS | да | нет | да | перед release | desktop/mobile/static shells |
| mail/bot provider | fake tests | retry/idempotency 5x | да | да | explicit redacted real flow |

Full receipt выполняется один раз на clean release candidate. Пять повторов
относятся к узкому race/idempotency test, а не к полной suite.

## 14. Definition of Done пакета

Пакет не завершён, пока отсутствует хотя бы один применимый пункт:

- preflight и owner зафиксированы;
- scope/acceptance определены до кода;
- characterization/negative/race tests существуют;
- code и rollback boundary реализованы;
- targeted gates зелёные;
- generated maps актуальны в том же commit;
- docs/plan обновлены по факту, а не по намерению;
- secret scan/staged diff проверены;
- commit понятен и не содержит чужой WIP;
- push подтверждён;
- если deploy входил в scope: exact SHA receipt, controlled switch, live/public
  smoke и logs подтверждены;
- статусы `CODE COMPLETE`/`DEPLOYED`/`VERIFIED`/`OPERATIONALLY VERIFIED` названы
  честно и раздельно.

## 15. Точное следующее действие

2026-07-20 (PLAN-SYNC-001): исполняемая очередь перенесена в
[optimization-and-decomposition-plan-20260720.md](optimization-and-decomposition-plan-20260720.md),
краткий фактический статус — в [current-status.md](current-status.md).
Этот документ остаётся хранилищем спецификаций пакетов и verified evidence;
его прежние «следующие шаги» больше не являются очередью.

Историческая заметка REL-LOCK-001: гонка двух publisher была воспроизведена на
работающем компьютере; теперь второй owner обязан завершиться до
tests/build/runtime mutation с ясной ошибкой `REPOSITORY_OPERATION_LOCK_BUSY`.
