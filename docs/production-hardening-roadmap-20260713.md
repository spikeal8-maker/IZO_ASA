# IZO ASA — актуальный план оптимизации и подготовки production

Дата актуализации: 2026-07-13

Статус: главный рабочий roadmap

Общий результат: **НЕ ЗАВЕРШЁН**
Предыдущий документ: `production-hardening-master-plan-20260712.md` сохранён как исторический журнал выполненных checkpoint-коммитов.

## 1. Назначение документа

Этот roadmap отвечает на четыре вопроса:

1. Что в действующем проекте уже исправлено и проверено.
2. Что выполнено только частично.
3. Какие риски остаются открытыми.
4. В каком порядке продолжать оптимизацию без остановки проекта.

Проект уже работает с реальными пользователями на одном личном Windows-компьютере. На нём находятся frontend, backend, SQLite, media, ComfyUI и Ollama. Внешний VPS используется только существующим доменным tunnel и не является application server. VPS и tunnel не изменяются в рамках этого roadmap.

## 2. Как читать статусы

| Статус | Значение |
|---|---|
| `ГОТОВО` | Изменение реализовано, покрыто тестами, развёрнуто и проверено live smoke |
| `ЧАСТИЧНО` | Безопасная часть выполнена, но целевая архитектура ещё не достигнута |
| `НЕ НАЧАТО` | В production-коде решения ещё нет |
| `ОТЛОЖЕНО` | Осознанно вынесено в отдельный будущий проект |
| `НУЖНО РЕШЕНИЕ` | Реализация зависит от продукта, бюджета или юридического решения владельца |

«Безопасный checkpoint» означает только: Git чистый и синхронизирован, тесты зелёные, один ожидаемый backend listener работает, health/smoke проходят, live DB/media не изменены тестами. Это не означает завершение всего roadmap.

«Пакет» означает один небольшой атомарный commit: одна проблема или один перенос ограниченного блока, characterization tests, реализация, проверки, controlled restart, документация и push.

## 3. Фактическая контрольная точка

Проверено 2026-07-13:

| Параметр | Факт |
|---|---|
| Git | `main` синхронизирован с `origin/main` |
| Последний runtime checkpoint | `B1` — OpenRouter aliases/request metadata extraction; точный hash в Git history |
| Backend | один Uvicorn listener на `127.0.0.1:8000` |
| Backend health | HTTP 200 |
| Последний полный test checkpoint | 899 passed, 0 failed, 0 deselected |
| Frontend lint | 0 errors, 1 известный hooks warning |
| Frontend production build | успешно |
| Private source без trusted session | HTTP 401 |
| Source baseline | 122 файла; startup `changed=0` |
| Production DB/media в тестах | не используются, принудительно изолированы |
| CI | отсутствует |
| Frontend production server | Vite Preview |
| Process supervisor | отсутствует; используются launcher/PowerShell processes |
| Backup | регулярный согласованный backup не реализован |

## 4. Реальные размеры крупных файлов

Размеры измерены из текущего рабочего дерева, а не перенесены из старого плана.

| Файл | Строк | Цель |
|---|---:|---:|
| `backend/main.py` | 15 151 | entrypoint/application wiring; преимущественно 100–300 строк после удаления compatibility exports |
| `frontend/src/newStudioV3.css` | 5 408 | feature/component styles преимущественно до 300–500 строк |
| `frontend/src/newUi.tsx` | 4 242 | page composition до 300–500 строк |
| `frontend/src/LegacyApp.tsx` | 3 589 | feature components без удаления Legacy UI |
| `frontend/src/newUi.css` | 2 984 | tokens/base/layout/features |
| `frontend/src/index.css` | 1 999 | только глобальные правила |
| `frontend/src/adminModels.tsx` | 1 591 | API/types/hooks/components/page |
| `backend/test_feed_v2.py` | 1 501 | отдельные behavioral test modules |
| `backend/test_api.py` | 1 177 | отдельные API-area test modules |

Вывод: backend-декомпозиция начата и имеет рабочую инфраструктуру, но монолит не устранён. Frontend-декомпозиция и разделение больших тестовых файлов практически не начинались.

## 5. Реестр текущего состояния

### 5.1. Runtime safety и тестирование

| ID | Статус | Состояние |
|---|---|---|
| SAFE-01 | `ГОТОВО` | Созданы `ARCHITECTURE.md` и автоматически проверяемый `SYMBOL_MAP.md` |
| SAFE-02 | `ГОТОВО` | Backend-тесты принудительно изолированы от production DB/media/avatar roots |
| SAFE-03 | `ГОТОВО` | Startup cleanup больше не удаляет файлы; cleanup использует audit/manifest/quarantine |
| SAFE-04 | `ГОТОВО` | Есть безопасный backend-only `tools/restart-backend.ps1` с preflight |
| SAFE-05 | `ГОТОВО` | После каждого runtime-пакета выполняются focused 5x tests, full suite, frontend gates, restart и live smoke |
| SAFE-06 | `ГОТОВО` | `tools/verify.ps1` объединяет Quick/Full/CI gates и выдаёт machine-readable `VERIFY_OK`; production checks read-only |
| SAFE-07 | `НЕ НАЧАТО` | Нет GitHub Actions CI и обязательных checks |

### 5.2. Security

| ID | Статус | Состояние |
|---|---|---|
| SEC-01 | `ГОТОВО` | Общий static mount private media удалён; private source требует trusted session + ownership |
| SEC-02 | `ГОТОВО` | Telegram/MAX operational management endpoints требуют trusted admin |
| SEC-03 | `НЕ НАЧАТО` | Telegram webhook receiver не проверяет обязательный platform secret header |
| SEC-04 | `НЕ НАЧАТО` | MAX webhook проверяет secret только если `MAX_WEBHOOK_SECRET` непустой; production-required validation отсутствует |
| SEC-05 | `НЕ НАЧАТО` | OpenRouter key из admin UI всё ещё хранится plaintext в SQLite `admin_secrets` |
| SEC-06 | `ЧАСТИЧНО` | Trusted Identity Core используется для protected routes, но legacy `X-OneNode-User` helpers и JS-readable `onenode_user` cookie остаются в коде |
| SEC-07 | `НЕ НАЧАТО` | `allowedHosts: true` остаётся в Vite server и preview config |
| SEC-08 | `ЧАСТИЧНО` | Backend/frontend привязаны к loopback, но `TRUST_CLOUDFLARE_HEADERS=true` задаётся launcher без отдельного документированного origin-isolation test |
| SEC-09 | `ЧАСТИЧНО` | Основные secret/token logs редактированы, но нужен отдельный automated log-redaction audit |

### 5.3. Backend-декомпозиция

| ID | Статус | Состояние |
|---|---|---|
| BE-01 | `ЧАСТИЧНО` | `app/config.py` создан; большая часть runtime constants/env policy остаётся в `main.py` |
| BE-02 | `ЧАСТИЧНО` | `database/connection.py`, `guard.py`, `schema.py`, `migrations.py` созданы; repository layer и migration ledger не завершены |
| BE-03 | `ЧАСТИЧНО` | Tokens/passwords/sessions/permissions/OTP/events вынесены; legacy auth removal и routers не завершены |
| BE-04 | `ЧАСТИЧНО` | Storage paths/private/public/recovery/source graph/thumbnails/validation/cleanup вынесены; оставшиеся gallery/media orchestration blocks ещё в `main.py` |
| BE-05 | `ГОТОВО` | Текущий ограниченный scope Ollama: URL, discovery и общий chat transport вынесены |
| BE-06 | `ГОТОВО` | Ограниченный integration scope завершён: HTTP/parsing/planning/I/O/model aliases/request metadata вынесены; application caches, policy, persistence, billing и orchestration остаются в соответствующих будущих services |
| BE-07 | `НЕ НАЧАТО` | Telegram integration client/typed errors/health не выделены |
| BE-08 | `НЕ НАЧАТО` | MAX integration client/typed errors/health не выделены |
| BE-09 | `НЕ НАЧАТО` | ComfyUI client/workflow/result adapter не выделены |
| BE-10 | `НЕ НАЧАТО` | Generation/gallery/feed/account/billing services не выделены системно |
| BE-11 | `НЕ НАЧАТО` | FastAPI routers не разделены по областям |
| BE-12 | `НЕ НАЧАТО` | Application factory/lifecycle не созданы; `main.py` остаётся ASGI-монолитом |

### 5.4. Frontend и тестовые монолиты

| ID | Статус | Состояние |
|---|---|---|
| FE-01 | `НЕ НАЧАТО` | `newUi.tsx` не разделён на API/hooks/features/page composition |
| FE-02 | `НЕ НАЧАТО` | `LegacyApp.tsx` не разделён; Legacy UI не удаляется в рамках оптимизации |
| FE-03 | `НЕ НАЧАТО` | `adminModels.tsx` не разделён |
| FE-04 | `НЕ НАЧАТО` | Крупные CSS-файлы не разделены по tokens/base/components/features |
| FE-05 | `ЧАСТИЧНО` | Есть многочисленные smoke/E2E scripts, но visual regression gate не унифицирован |
| TEST-01 | `НЕ НАЧАТО` | `test_feed_v2.py` не разделён по publications/ownership/reactions/media/admin |
| TEST-02 | `НЕ НАЧАТО` | `test_api.py` не разделён по health/generation/gallery/providers/bots/admin |

### 5.5. Deployment, процессы и данные

| ID | Статус | Состояние |
|---|---|---|
| OPS-01 | `ГОТОВО` | `start-public.bat` блокирует deploy при ошибке `tsc -b` или Vite build |
| OPS-02 | `ЧАСТИЧНО` | Launcher проверяет DB/health/smoke, но release build не атомарный и build label не равен Git commit автоматически |
| OPS-03 | `НЕ НАЧАТО` | Vite Preview не заменён на Caddy |
| OPS-04 | `НЕ НАЧАТО` | Backend/Caddy/ComfyUI/Ollama не оформлены как Windows Services с restart-on-failure |
| OPS-05 | `НЕ НАЧАТО` | Нет регулярного SQLite Backup API + incremental media backup на другом физическом диске |
| OPS-06 | `НЕ НАЧАТО` | Нет encrypted offsite copy, checksum/quick_check pipeline и регулярного restore test |
| OPS-07 | `ЧАСТИЧНО` | Есть health/logs и ручной storage audit, но нет единого monitoring/alerting контура |
| OPS-08 | `ГОТОВО` | Внешний VPS/tunnel исключён из оптимизационных изменений |

### 5.6. Database, billing и масштабирование

| ID | Статус | Состояние |
|---|---|---|
| DATA-01 | `ЧАСТИЧНО` | SQLite остаётся единственной production DB; guard и additive migrations есть, lock/busy telemetry недостаточна |
| DATA-02 | `ЧАСТИЧНО` | Token ledger и refund logic существуют, но конкурентные/idempotency tests и формальная append-only policy не завершены |
| DATA-03 | `НЕ НАЧАТО` | Repository boundary, необходимая для PostgreSQL migration, не завершена |
| DATA-04 | `ОТЛОЖЕНО` | PostgreSQL migration выполняется отдельным проектом после database/service extraction |
| DATA-05 | `ОТЛОЖЕНО` | Persistent queue нужна перед несколькими backend workers; до этого остаётся текущая single-process queue |
| DATA-06 | `НУЖНО РЕШЕНИЕ` | Payment/email providers, retention/privacy policy и реальные платежи требуют отдельного продуктово-юридического решения для России |

## 6. Принятые технические решения

1. Текущий production остаётся на этом Windows-компьютере до появления измеримой необходимости переноса.
2. Внешний VPS и существующий tunnel не меняются.
3. Для локального Windows production reverse proxy выбран Caddy, но его установка выполняется отдельным rollbackable пакетом после подготовки конфигурации и smoke.
4. Секреты не должны храниться в Git или plaintext SQLite. Целевой Windows-вариант: DPAPI-encrypted secret file вне repository с ACL текущего service account; environment override поддерживается.
5. Первый backup target — другой физический диск. Offsite copy добавляется после появления локального проверенного restore flow.
6. SQLite пока сохраняется. PostgreSQL не смешивается с механической декомпозицией.
7. Persistent queue не выбирается до выделения generation service и появления нескольких backend workers.
8. Legacy UI не отключается и не удаляется в рамках текущей оптимизации.
9. Никакой крупный файл не делится одним массовым PR.

## 7. Новый порядок реализации

Работа идёт двумя чередующимися потоками: `защита production` и `декомпозиция монолитов`. Это не позволяет инфраструктурным рискам ждать окончания многомесячного разделения `main.py`, но сохраняет основной фокус на больших файлах.

### Волна A — обязательные production gates и критическая защита

| Пакет | Приоритет | Результат |
|---|---|---|
| A1 | P0 | `ГОТОВО` — единый read-only `tools/verify.ps1`: compile, focused/full backend, lint/build, map check, process/source checks; никаких restart/mutation |
| A2 | P0 | GitHub Actions CI вызывает те же deterministic checks без production/real-provider tests |
| A3 | P0 | Telegram webhook secret: required-in-webhook-mode validation, constant-time header check, negative/replay/body-limit tests |
| A4 | P0 | MAX secret: запрещён пустой secret в webhook production mode, constant-time comparison, negative tests |
| A5 | P0 | OpenRouter secret migration: DPAPI store вне repository, admin UI configured/source only, plaintext SQLite migration/delete, затем ручная rotation инструкция |
| A6 | P0 | Backup tooling: SQLite Backup API, media manifest/incremental copy, second-disk destination через внешнюю config, `quick_check`, checksum и restore rehearsal |
| A7 | P1 | Точный Vite host allowlist и automated loopback/proxy-header isolation check |

### Волна B — завершить backend-декомпозицию

Порядок внутри каждого подпункта: pure helpers → client/persistence boundary → service → router → удаление compatibility wrapper.

| Пакет | Результат |
|---|---|
| B1 | `ГОТОВО` — model aliases и request metadata вынесены; дальнейшее мелкое дробление этой integration boundary остановлено |
| B2 | Завершить `app/config.py`: paths, URLs, modes, limits, cookie/proxy policy и production validation |
| B3 | Завершить migrations: ledger/version, idempotent schema groups, billing/feed/auth migration tests |
| B4 | Выделить Telegram client и затем handlers/service |
| B5 | Выделить MAX client и затем handlers/service |
| B6 | Выделить ComfyUI HTTP client, workflow builders и result adapter отдельными пакетами |
| B7 | Выделить generation service и queue boundary |
| B8 | Выделить gallery/source lifecycle service |
| B9 | Выделить feed/publication/reaction/moderation service |
| B10 | Выделить account/auth service и удалить подтверждённо неиспользуемые legacy authorization consumers |
| B11 | Выделить billing/token ledger service с atomic/idempotency/concurrency tests |
| B12 | Перенести routers: health → config → account/auth → bots → gallery → feed → generation → admin/billing |
| B13 | Создать application factory/lifecycle; сократить `main.py` до entrypoint + временные exports |
| B14 | Удалить compatibility exports после обновления scripts/tests |

### Волна C — frontend-декомпозиция без редизайна

| Пакет | Результат |
|---|---|
| C1 | Общие API types/client и error mapping из `newUi.tsx` |
| C2 | Auth/session hooks/components |
| C3 | Generation polling/upload/source/model-resolution hooks |
| C4 | Studio panels по generation mode |
| C5 | Gallery/feed/profile sections |
| C6 | `adminModels.tsx`: types/API/hooks/provider panels/dialogs/page |
| C7 | `LegacyApp.tsx`: API/hooks/features без отключения Legacy UI |
| C8 | CSS tokens/base/shared layout |
| C9 | CSS components/features/responsive rules с visual smoke |

### Волна D — тестовые монолиты

1. Разделить `test_feed_v2.py` на publications, ownership, reactions, moderation, media, challenges и admin.
2. Разделить `test_api.py` на health/config, generation, gallery, providers, bots и admin.
3. Вынести общие fixtures без global-state leakage.
4. Классифицировать fast/security/integration/real-provider/browser suites.
5. Запретить real paid/provider tests в default CI.

### Волна E — локальная production-инфраструктура

1. Подготовить Caddyfile и параллельный localhost smoke без переключения tunnel.
2. Проверить static cache, compression, body limits, timeouts, access/error logs и security headers.
3. Переключить локальный frontend origin с Vite Preview на Caddy с rollback.
4. Оформить backend и Caddy как Windows Services.
5. Оформить ComfyUI/Ollama как managed service/task с restart-on-failure.
6. Добавить disk/DB/media/process/health monitoring и alerts.

### Волна F — масштабирование после измерений

Начинается только при подтверждённых метриках нагрузки или перед переносом на Linux:

1. Repository interfaces и PostgreSQL compatibility tests.
2. PostgreSQL migration rehearsal на копии DB.
3. Persistent queue и multiple-worker design.
4. Docker Compose для воспроизводимого окружения.
5. Linux/systemd deployment и controlled cutover.

## 8. Ближайшая очередь пакетов

Это точная очередь, а не список всего проекта:

1. `A1` — `ГОТОВО`: единая `tools/verify.ps1`.
2. `B1` — `ГОТОВО`: OpenRouter aliases/request metadata extraction.
3. `A3` — **СЛЕДУЮЩИЙ ПАКЕТ**: Telegram webhook secret enforcement.
4. `A4` — MAX webhook secret enforcement.
5. `A5` — OpenRouter DPAPI secret store и удаление plaintext SQLite secret.
6. `A6` — backup/restore tooling без автоматического schedule на первом PR.
7. `A2` — GitHub Actions CI поверх стабильной verify command.
8. `A7` — host allowlist и proxy-origin checks.
9. `B2` — завершение config extraction.
10. `B3` — migration ledger/schema groups.
11. `B4`/`B5` — Telegram и MAX integrations.
12. `B6` — ComfyUI decomposition.

После каждого пакета статус в разделе 5 обновляется. Завершённый пункт меняется на `ГОТОВО` только после commit, push, production restart и live smoke, если пакет затрагивает runtime.

### Checkpoint A1 — единый verification gate

Реализовано 2026-07-13:

- `tools/verify.ps1` поддерживает `Quick`, `Full`, `CI` и `-PlanOnly`;
- `Quick` выполняет `py_compile`, проверку generated map, focused tools tests и read-only production preflight/source snapshot;
- `Full` добавляет полный `backend + tools` pytest suite, frontend lint и production build;
- `CI` выполняет deterministic gates без обращения к live backend/media;
- скрипт не содержит restart, `Stop-Process`, удаления файлов или записи в production DB/media;
- завершение имеет machine-readable строку `VERIFY_OK`.

Доказательства:

- focused contract suite: `15 passed` пять последовательных прогонов;
- финальный `Full`: `887 passed, 72 warnings`, frontend lint `0 errors / 1 existing warning`, frontend build успешно;
- `py_compile`: 111 Python-файлов;
- source snapshot до/после: 122 файла, 1 706 364 байта, SHA-256 `AC1A00934150E28C74BC1C4F319AFF24C84324FF8842AE8EEACD44D34A977850`, без изменений;
- время полного gate: 312,78 секунды;
- backend preflight: один loopback listener, PID 51140; health HTTP 200;
- исправлены две найденные ошибки самого verifier: ложное обнаружение родительского PowerShell как pytest-процесса и конфигурация UTF-8 для вывода;
- controlled restart не выполнялся: A1 добавляет только verification tooling и документацию, runtime-код не менялся.

### Checkpoint B1 — OpenRouter aliases и request metadata

Реализовано 2026-07-13:

- legacy alias resolution перенесён из `main.py` в pure helper `resolve_openrouter_image_model()`;
- сборка сохраняемой не-секретной `openrouterRequest` metadata перенесена в `build_openrouter_image_request_metadata()`;
- `main.py` сохраняет тонкие compatibility wrappers и application orchestration;
- каталог capabilities, API key/header policy, HTTP transport, billing, job/gallery persistence и paid generation behavior не менялись;
- дальнейшее мелкое дробление OpenRouter integration остановлено; следующие крупные границы выделяются только вместе с services/routers.

Доказательства:

- characterization test до реализации ожидаемо упал на отсутствии новых imports;
- focused OpenRouter images/client suite: `67 passed` пять последовательных прогонов;
- финальный `Full`: `899 passed, 72 warnings`, frontend lint `0 errors / 1 existing warning`, frontend build успешно;
- `py_compile` и generated map check успешны: 111 Python-файлов, 608 symbols, 165 routes;
- source snapshot до/после: 122 файла, 1 706 364 байта, SHA-256 `AC1A00934150E28C74BC1C4F319AFF24C84324FF8842AE8EEACD44D34A977850`, без изменений;
- controlled backend restart: PID 51140 → PID 54256, один listener `127.0.0.1:8000`, startup `changed=0`;
- live smoke 5/5: health/database/models/tariffs/feed HTTP 200, private source без trusted session HTTP 401;
- реальная платная OpenRouter generation не запускалась; VPS и tunnel не изменялись.

## 9. Обязательный gate каждого пакета

Минимальный порядок:

1. Проверить clean/sync Git и единственный production listener.
2. Зафиксировать characterization tests до переноса поведения.
3. Внести один ограниченный change set.
4. Прогнать focused tests пять последовательных раз.
5. Прогнать полный backend+tools suite один раз.
6. Выполнить `npm run lint` и `npm run build`.
7. Проверить `git diff --check`, `py_compile`, generated symbol map.
8. Для runtime-пакета выполнить `restart-backend.ps1 -PreflightOnly`, source snapshot, controlled restart и live smoke.
9. Проверить отсутствие pytest-процессов и неизменность DB/media.
10. Обновить этот roadmap и архитектурную документацию.
11. Сделать отдельный commit и push в `origin/main`.

Нельзя считать пакет завершённым только потому, что код перенесён или unit tests прошли один раз.

## 10. Критерии завершения всего roadmap

Roadmap считается выполненным, когда одновременно соблюдены условия:

- `backend/main.py` является entrypoint/application wiring, а не хранилищем business logic;
- routes имеют явную anonymous/user/admin/service policy;
- Telegram/MAX webhook secrets обязательны и проверяются;
- provider secrets отсутствуют в plaintext SQLite и repository;
- единая verify command и CI блокируют merge/deploy при ошибке;
- private media остаётся owner-scoped;
- frontend и большие CSS-файлы разделены по features без визуальной регрессии;
- большие test files разделены, suites классифицированы;
- Caddy заменил постоянный Vite Preview;
- процессы работают под supervisor/Windows Services с restart-on-failure;
- SQLite и media регулярно копируются на другой физический диск согласованным способом;
- restore rehearsal задокументирован и успешно выполнен;
- billing ledger имеет atomic/idempotency/concurrency guarantees;
- existing domain tunnel продолжает работать без изменений;
- каждый этап можно откатить независимо.

PostgreSQL, Docker/Linux, persistent queue, payment/email providers и юридическая retention/privacy policy не являются критерием завершения механической оптимизации, но имеют отдельные входные условия в волне F или продуктовых решениях.

## 11. История и доказательства

- Подробный хронологический журнал уже выполненных extraction/deployment checkpoints: `production-hardening-master-plan-20260712.md`.
- Текущая backend architecture map: `../backend/ARCHITECTURE.md`.
- Generated symbol/route map: `../backend/SYMBOL_MAP.md`.
- Git history является источником истины для commit hashes.

Этот документ является единственным источником истины для текущих статусов и очереди работ. Исторический журнал не используется для определения того, что ещё осталось выполнить.
