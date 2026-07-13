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
| Последний completed checkpoint | `B2a` — typed cookie/proxy/CORS config extraction; точный hash в Git history |
| Backend | один Uvicorn listener на `127.0.0.1:8000` |
| Backend health | HTTP 200 |
| Последний полный test checkpoint | 983 passed, 0 failed, 0 skipped, 0 deselected |
| Frontend lint | 0 errors, 1 известный hooks warning |
| Frontend production build | успешно |
| Private source без trusted session | HTTP 401 |
| Source baseline | 121 файл; startup `checked=123`, `available=121`, `missing=2`, `changed=0` |
| Production DB/media в тестах | не используются, принудительно изолированы |
| CI | GitHub Actions active; combined-head run `29242043545` success (`979 passed`), required branch protection недоступен на текущем private plan |
| Frontend production server | Vite Preview |
| Process supervisor | отсутствует; используются launcher/PowerShell processes |
| Backup | A6 tooling и три live snapshot готовы; автоматический schedule/retention ещё не включены |

## 4. Реальные размеры крупных файлов

Размеры измерены из текущего рабочего дерева, а не перенесены из старого плана.

| Файл | Строк | Цель |
|---|---:|---:|
| `backend/main.py` | 15 268 после B2a | entrypoint/application wiring; преимущественно 100–300 строк после удаления compatibility exports |
| `frontend/src/newStudioV3.css` | 5 408 | feature/component styles преимущественно до 300–500 строк |
| `frontend/src/newUi.tsx` | 4 242 | page composition до 300–500 строк |
| `frontend/src/LegacyApp.tsx` | 3 589 | feature components без удаления Legacy UI |
| `frontend/src/newUi.css` | 2 984 | tokens/base/layout/features |
| `frontend/src/index.css` | 1 999 | только глобальные правила |
| `frontend/src/adminModels.tsx` | 1 591 | API/types/hooks/components/page |
| `backend/test_feed_v2.py` | 1 501 | отдельные behavioral test modules |
| `backend/test_api.py` | 1 224 | отдельные API-area test modules |

Вывод: backend-декомпозиция начата и имеет рабочую инфраструктуру, но монолит не устранён. Frontend-декомпозиция и разделение больших тестовых файлов практически не начинались.

## 5. Реестр текущего состояния

### 5.1. Runtime safety и тестирование

| ID | Статус | Состояние |
|---|---|---|
| SAFE-01 | `ГОТОВО` | Созданы `ARCHITECTURE.md` и автоматически проверяемый `SYMBOL_MAP.md` |
| SAFE-02 | `ГОТОВО` | Backend-тесты принудительно изолированы от production DB/media/avatar roots |
| SAFE-03 | `ГОТОВО` | Startup cleanup больше не удаляет файлы; cleanup использует audit/manifest/quarantine |
| SAFE-04 | `ГОТОВО` | Безопасный backend-only restart имеет preflight и параметризуемый health timeout 10 секунд для текущей большой SQLite |
| SAFE-05 | `ГОТОВО` | После каждого runtime-пакета выполняются focused 5x tests, full suite, frontend gates, restart и live smoke |
| SAFE-06 | `ГОТОВО` | `tools/verify.ps1` объединяет Quick/Full/CI gates и выдаёт machine-readable `VERIFY_OK`; online media change отчётно отделён от strict maintenance mode |
| SAFE-07 | `ЧАСТИЧНО` | GitHub Actions CI успешно блокирует свой run при ошибках; required branch protection для private repo отклонён GitHub API 403 до Pro/public |

### 5.2. Security

| ID | Статус | Состояние |
|---|---|---|
| SEC-01 | `ГОТОВО` | Общий static mount private media удалён; private source требует trusted session + ownership |
| SEC-02 | `ГОТОВО` | Telegram/MAX operational management endpoints требуют trusted admin |
| SEC-03 | `ГОТОВО` | Webhook mode требует `TELEGRAM_WEBHOOK_SECRET`; официальный header проверяется constant-time, body ограничен, integer `update_id` защищён bounded replay guard |
| SEC-04 | `ГОТОВО` | MAX webhook mode требует official-format secret; header проверяется constant-time, body ограничен, polling receiver закрыт |
| SEC-05 | `ГОТОВО` | OpenRouter env override или external CurrentUser DPAPI; live SQLite plaintext row удалён, admin API возвращает только configured/source |
| SEC-06 | `ЧАСТИЧНО` | Trusted Identity Core используется для protected routes, но legacy `X-OneNode-User` helpers и JS-readable `onenode_user` cookie остаются в коде |
| SEC-07 | `ГОТОВО` | Vite server/preview используют exact `izo.alikinas.ru`; automated probe требует 403 для произвольного host и поддомена |
| SEC-08 | `ГОТОВО` | Backend/frontend loopback-only; Uvicorn proxy rewrite отключён, CF/XFF принимаются только от direct loopback peer и валидируются |
| SEC-09 | `ЧАСТИЧНО` | Основные secret/token logs редактированы, но нужен отдельный automated log-redaction audit |

### 5.3. Backend-декомпозиция

| ID | Статус | Состояние |
|---|---|---|
| BE-01 | `ЧАСТИЧНО` | `app/config.py` владеет env/DB-path helpers и typed cookie/proxy/CORS policy; paths, provider URLs/modes/limits и production validation ещё остаются |
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
| OPS-05 | `ЧАСТИЧНО` | SQLite Backup API + incremental media работают на отдельный физический `I:`; три live snapshot проверены, но регулярный schedule/retention ещё не настроены |
| OPS-06 | `ЧАСТИЧНО` | SHA-256, manifest checksum, SQLite `quick_check` и restore rehearsal готовы; encrypted offsite copy ещё не выбрана |
| OPS-07 | `ЧАСТИЧНО` | Есть health/logs и ручной storage audit, но нет единого monitoring/alerting контура |
| OPS-08 | `ГОТОВО` | Внешний VPS/tunnel исключён из оптимизационных изменений |
| OPS-09 | `ГОТОВО` | MAX переведён на `platform-api2.max.ru`; HTTPX использует native system trust store, polling и `/me` live smoke успешны |

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
| A2 | P0 | `ГОТОВО` — GitHub Actions CI вызывает тот же deterministic verifier на pinned Windows/Python/Node без production/real-provider tests |
| A3 | P0 | `ГОТОВО` — Telegram webhook secret required-in-webhook-mode validation, constant-time header check, negative/replay/body-limit tests |
| A4 | P0 | `ГОТОВО` — MAX secret: запрещён пустой secret в webhook mode, constant-time comparison, body/mode/negative tests |
| A4b | P0 | `ГОТОВО` — MAX API2/system trust-store migration, sanitized probe, polling + `/me` live smoke и rollback contract |
| A5 | P0 | `ГОТОВО` — OpenRouter external CurrentUser DPAPI store, verified SQLite migration/delete, admin configured/source contract и rotation/runbook |
| A6 | P0 | `ГОТОВО` — SQLite Backup API, SHA-256 media object store/manifest, внешний second-disk config, `quick_check`, verify и restore rehearsal; schedule/retention остаются отдельным operations-пакетом |
| A7 | P1 | `ГОТОВО` — exact Vite host allowlist, loopback-only validated proxy metadata, Uvicorn `--no-proxy-headers`, automated origin/live smoke |

### Волна B — завершить backend-декомпозицию

Порядок внутри каждого подпункта: pure helpers → client/persistence boundary → service → router → удаление compatibility wrapper.

| Пакет | Результат |
|---|---|
| B1 | `ГОТОВО` — model aliases и request metadata вынесены; дальнейшее мелкое дробление этой integration boundary остановлено |
| B2 | `ЧАСТИЧНО` — B2a cookie/proxy/CORS policy готов; продолжить paths, URLs, modes, limits и production validation малыми пакетами |
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
3. `A3` — `ГОТОВО`: Telegram webhook secret/body/replay enforcement.
4. `A4` — `ГОТОВО`: MAX webhook secret/body/mode enforcement.
5. `A4b` — `ГОТОВО`: MAX API2/system trust-store migration.
6. `A5` — `ГОТОВО`: OpenRouter DPAPI secret store и удаление plaintext SQLite secret.
7. `A6` — `ГОТОВО`: backup/restore tooling и live rehearsal без автоматического schedule.
8. `A2` — `ГОТОВО`: GitHub Actions CI поверх стабильной verify command.
9. `A7` — **СЛЕДУЮЩИЙ ПАКЕТ**: host allowlist и proxy-origin checks.
10. `B2` — завершение config extraction.
11. `B3` — migration ledger/schema groups.
12. `B4`/`B5` — Telegram и MAX integrations.
13. `B6` — ComfyUI decomposition.

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

### Checkpoint A3 — защита Telegram webhook

Реализовано 2026-07-13:

- в Telegram webhook mode `TELEGRAM_WEBHOOK_SECRET` обязателен и проверяется fail-fast до DB preflight;
- допустимый secret соответствует Telegram `secret_token`: 1–256 символов `A-Z`, `a-z`, `0-9`, `_`, `-`;
- startup и admin set-webhook передают `secret_token`, но secret не логируется и не возвращается API;
- receiver сверяет `X-Telegram-Bot-Api-Secret-Token` через `hmac.compare_digest`;
- polling mode закрывает public webhook receiver HTTP 404 и не требует нового secret;
- `Content-Length` и фактический body ограничены 256 KiB по умолчанию, malformed/non-object JSON отклоняется;
- повторный integer `update_id` подтверждается без повторного handler call; cache ограничен 4096 entries по умолчанию и остаётся single-process до будущего queue/multi-worker проекта.

Доказательства:

- characterization test до реализации ожидаемо упал на отсутствии `app.security.webhooks`;
- новый security module + полный `test_api.py`: `61 passed`;
- focused security/webhook suite: `20 passed` пять последовательных прогонов;
- финальный `Full`: `913 passed, 72 warnings`, frontend lint `0 errors / 1 existing warning`, frontend build успешно;
- `py_compile` и generated map check успешны: 113 Python-файлов, 608 symbols, 165 routes;
- source snapshot до/после: 122 файла, 1 706 364 байта, SHA-256 `AC1A00934150E28C74BC1C4F319AFF24C84324FF8842AE8EEACD44D34A977850`, без изменений;
- controlled backend restart: PID 54256 → PID 55072, один listener `127.0.0.1:8000`, startup `changed=0`;
- live smoke 5/5: health/database/models/feed HTTP 200, Telegram mode `polling`, Telegram token configured, webhook HTTP 404, private source HTTP 401;
- production `.env` не менялся: текущему polling secret не нужен; Telegram API registration, VPS и tunnel не изменялись.

### Checkpoint A4 — защита MAX webhook и mode safety

Реализовано 2026-07-13:

- MAX webhook mode fail-fast требует secret формата `^[A-Za-z0-9_-]{5,256}$` до DB preflight;
- subscription body всегда содержит secret, receiver проверяет `X-Max-Bot-Api-Secret` через общий `hmac.compare_digest`;
- polling mode закрывает public MAX webhook receiver HTTP 404 и не требует secret;
- `Content-Length` и фактический body ограничены 256 KiB по умолчанию, malformed/non-object JSON отклоняется;
- secret не логируется и не возвращается status API; status показывает только configured boolean;
- `start-public.bat` больше не переключает MAX из работающего polling в webhook неявно;
- официальный MAX API требует отдельного перехода на `platform-api2.max.ru` до 2026-07-19; риск добавлен как новый срочный пакет A4b, без опасного переключения в A4.

Доказательства:

- characterization test до реализации ожидаемо упал на отсутствии MAX webhook helpers;
- оба webhook security modules + полный `test_api.py` + launcher tests: `74 passed`;
- focused security/launcher suite: `33 passed` пять последовательных прогонов;
- финальный `Full`: `924 passed, 72 warnings`, frontend lint `0 errors / 1 existing warning`, frontend build успешно;
- `py_compile` и generated map check успешны: 114 Python-файлов, 608 symbols, 165 routes;
- source snapshot до/после: 122 файла, 1 706 364 байта, SHA-256 `AC1A00934150E28C74BC1C4F319AFF24C84324FF8842AE8EEACD44D34A977850`, без изменений;
- controlled backend restart: PID 55072 → PID 12508, один listener `127.0.0.1:8000`, startup `changed=0`;
- реальный MAX long polling после restart: marker 9301, status 200, no error;
- live smoke 5/5: health/database/models/feed HTTP 200, MAX mode `polling`, MAX polling status 200, MAX webhook HTTP 404, private source HTTP 401;
- production `.env`, MAX subscription, VPS и tunnel не изменялись.

### Checkpoint A4b — MAX API2 и системный trust store

Реализовано 2026-07-13:

- исходный probe локализовал проблему: API1 Python/certifi HTTP 200, API2 Python/certifi `ConnectError`, API2 Windows trust store достигал HTTP 401 без токена;
- добавлен pinned `truststore==0.10.4`; `MAX_TLS_TRUST_STORE=system` создаёт native OS SSL context, rollback mode `certifi` сохраняется;
- async MAX API client и synchronous `/me` deep-link discovery используют один `MAX_HTTP_VERIFY` context;
- `tools/probe_max_api.py` выполняет read-only `/me` и выводит только host/trustStore/status/HTTP;
- launcher default и локальный production `.env` переведены на `https://platform-api2.max.ru`; delivery mode остался polling;
- никакие сертификаты вручную не копировались в repository, Python bundle или VPS.

Доказательства:

- characterization test ожидаемо упал на отсутствии `app.integrations.max_tls`;
- до реализации API2 system-trust probe вернул 200 с реальным токеном без вывода token/body;
- первый focused test обнаружил ошибочную SSL injection в Telegram вместо MAX до deployment; исправлено;
- первый API2 live cutover обнаружил второй sync `/me` certifi path: polling был 200, deep-link `ConnectError`; path исправлен и все gates повторены;
- финальный focused TLS/probe/launcher/deep-link suite: `15 passed` пять последовательных прогонов;
- финальный повторный `Full`: `934 passed, 72 warnings`, frontend lint `0 errors / 1 existing warning`, frontend build успешно;
- `py_compile` и generated map check успешны: 116 Python-файлов, 608 symbols, 165 routes;
- source snapshot до/после: 122 файла, 1 706 364 байта, SHA-256 `AC1A00934150E28C74BC1C4F319AFF24C84324FF8842AE8EEACD44D34A977850`, без изменений;
- controlled final restart: PID 41040 → PID 28572, один listener `127.0.0.1:8000`, startup `changed=0`;
- final runtime: API2, trust store `system`, MAX polling 200/no error, `/me` 200, nickname/deep-link resolved через API;
- live smoke 5/5: health/database/models/feed HTTP 200, MAX API2 polling + `/me` 200, MAX webhook HTTP 404, private source HTTP 401;
- локальный `.env` изменён только в публичных `MAX_API_BASE_URL`/`MAX_TLS_TRUST_STORE`; secrets, MAX subscription, VPS и tunnel не изменялись.

### Checkpoint A5 — OpenRouter CurrentUser DPAPI

Реализовано 2026-07-13:

- `app/security/secret_store.py` хранит versioned DPAPI document вне repository в `%LOCALAPPDATA%\IZO_ASA\secrets` или внешнем `IZO_SECRET_DIR`;
- используется Windows DPAPI CurrentUser scope с application entropy, atomic temp→replace и защищённым ACL без наследования;
- `OPENROUTER_API_KEY` остаётся env override; иначе source имеет только значения `dpapi`/`none`;
- admin save/delete работают с DPAPI и очищают legacy SQLite row; API/status никогда не возвращают key;
- `tools/migrate_openrouter_secret.py` имеет read-only `--plan`, encrypt/readback constant-time verification и удаляет SQLite row только после успешной проверки;
- обязательная backend conftest isolation подменяет production DPAPI root временным fake-crypto store;
- README содержит rotation/new-PC/service-account runbook; DPAPI file не считается переносимым backup.

Доказательства:

- read-only inventory: один `admin_secrets` row, OpenRouter value length 73, другие rows отсутствовали; value не выводился;
- characterization test ожидаемо упал на отсутствии `app.security.secret_store`;
- real CurrentUser DPAPI roundtrip, atomic/encryption/ACL/corruption/failure/idempotency/tool tests успешны;
- расширенный A5 package: `126 passed`; focused secret/admin/migration suite: `17 passed` пять последовательных прогонов;
- финальный `Full`: `945 passed, 72 warnings`, frontend lint `0 errors / 1 existing warning`, frontend build успешно;
- `py_compile` и generated map check успешны: 118 Python-файлов, 609 symbols, 165 routes;
- source snapshot до/после: 122 файла, 1 706 364 байта, SHA-256 `AC1A00934150E28C74BC1C4F319AFF24C84324FF8842AE8EEACD44D34A977850`, без изменений;
- live plan: legacyRows 1 / dpapiConfigured false; apply: `migrated`, legacyRows 0 / configured true / source dpapi;
- encrypted document: 570 bytes, plaintext absent, ACL inheritance disabled, current Windows user FullControl;
- OpenRouter read-only provider verification до и после restart: `/key` 200, `/credits` 200;
- первый post-migration restart: PID 28572 → PID 50240, startup `already_migrated`, source dpapi, `changed=0`;
- `/api/health` измерен 3,4–4,8 секунды; два финальных restart preflight с прежним hardcoded 3-second timeout безопасно отказались до остановки PID;
- restart helper получил `HealthProbeTimeoutSeconds=10`, contract suite `11 passed` пять циклов; final restart PID 50240 → PID 49032 успешен;
- live smoke 5/5: health/database/models/tariffs/feed HTTP 200, MAX polling 200, private source HTTP 401; paid OpenRouter generation не запускалась;
- первый live migration command завершился до plan/apply из-за неверного working directory, ничего не изменив; повтор с абсолютным root прошёл успешно;
- VPS, tunnel, Telegram/MAX secrets и OpenRouter provider key value не изменялись и не выводились.

### Checkpoint A6 — согласованный backup и проверяемый restore

Реализовано 2026-07-13:

- `app/storage/backup.py` создаёт SQLite snapshot только через
  `sqlite3.Connection.backup()`, затем выполняет `PRAGMA quick_check` и SHA-256;
- media сохраняются в content-addressed `media-objects`; manifest содержит только
  безопасные относительные пути, размеры и SHA-256, одинаковые данные не дублируются;
- изменившийся во время чтения media-файл повторяется до трёх раз, symlink и path
  traversal/drive path в source или подменённом manifest запрещены;
- snapshot считается завершённым только после финального `COMPLETED`; новый marker
  содержит SHA-256 manifest, два ранних live snapshot остаются verify-compatible;
- `tools/backup_production.py` использует внешний config и по умолчанию запрещает
  backup на тот же drive letter, где находятся DB/media;
- `tools/restore_backup.py` имеет `--verify-only`, временный `--rehearse` и restore
  только в новый пустой каталог; live DB/media автоматически не заменяются;
- `.env`, DPAPI secret, Git repository, ComfyUI/Ollama и модели намеренно не
  включены; границы восстановления описаны в `backup-restore-runbook-20260713.md`;
- Quick verifier включает backup/restore contract suite. Автоматический schedule,
  retention и encrypted offsite не смешивались с первым rollbackable tooling PR.

Фактическая инфраструктура и live-доказательства:

- production source: физический `D:` / `ST8000NM017B-2TJ103` SATA;
- backup target: отдельный физический `I:` / `ST1000LM 035-1RK172` USB, свободно
  после проверки около 849 ГБ;
- внешний config создан в `%LOCALAPPDATA%\IZO_ASA\backup.json`, target
  `I:\IZO_ASA_Backups`; config и backup не добавлены в Git;
- read-only plan: DB 565 104 640 байт, media 2 394 файла / 215 152 173 байта;
- первый snapshot `20260713T010621.501808Z`: 1 104 новых уникальных objects и
  1 290 deduplicated reuse;
- второй snapshot `20260713T010933.881891Z`: 0 новых / 2 394 reuse;
- финальный checksum-marker snapshot `20260713T011450.444384Z`: 0 новых /
  2 394 reuse; marker точно совпал с SHA-256 manifest;
- для финального snapshot отдельно успешны `BACKUP_VERIFY_OK` и
  `BACKUP_REHEARSAL_OK`, включая восстановленную БД/media и повторные checksums;
- focused suite после финального тестового контракта: `18 passed` пять
  последовательных прогонов;
- единый `Full`: `958 passed, 72 warnings`; frontend lint `0 errors / 1 existing
  warning`, frontend build успешен;
- `py_compile` успешен для 119 Python-файлов, generated map check успешен;
- source snapshot до/после: 122 файла, 1 706 364 байта, SHA-256
  `AC1A00934150E28C74BC1C4F319AFF24C84324FF8842AE8EEACD44D34A977850`;
- после backup/verify/rehearsal один listener PID 49032, health=true,
  database.ready=true; restart не выполнялся, потому что ASGI runtime не изменён;
- VPS, tunnel, live DB/media, `.env` и DPAPI document не изменялись.

Открытые подпункты после A6:

- OPS-05 остаётся `ЧАСТИЧНО`, пока отдельный пакет не включит schedule, age alert
  и безопасный retention;
- OPS-06 остаётся `ЧАСТИЧНО`, пока не появится зашифрованная offsite-копия и
  отдельное хранение recovery key.

### Checkpoint A2 — deterministic GitHub Actions CI

Реализовано 2026-07-13:

- `.github/workflows/ci.yml` запускается на push/PR в `main` и вручную, имеет
  только `contents: read`, concurrency cancellation и 20-minute job timeout;
- official `checkout`, `setup-python` и `setup-node` закреплены полными release
  commit SHA; checkout не сохраняет Git credentials;
- `.python-version=3.11.9`, `.node-version=24.14.1`, exact Python requirements и
  `npm ci` по lockfile воспроизводят текущий toolchain;
- hosted job вызывает только `tools/verify.ps1 -Mode CI`: Python compile,
  generated map, полный backend/tools pytest, frontend lint и production build;
- DB/media/DPAPI roots направлены в `RUNNER_TEMP`; Telegram/MAX/OpenRouter/session
  и email secrets явно пусты, bot updates/real ComfyUI отключены;
- CI contract tests запрещают unpinned Actions, write permissions, secrets,
  self-hosted runner, deploy/push, restart/live backend и production backup calls;
- `pytest.ini` собирает только явные `test_*.py`; операторский
  `acceptance_generation_test.py` переведён с незаявленного `requests` на уже
  закреплённый `httpx` и не коллекционируется как unit test;
- bot/profile fixtures теперь создают собственные fake tokens, production-mode
  auth fixtures — собственный test HMAC secret;
- generation cancel route contract больше не зависит от lifespan worker/CPU race:
  queued job отменяется без фонового worker, ComfyUI interrupt клиент подменён.

Доказательства и найденные clean-environment проблемы:

- локальный focused workflow suite: `9 passed` пять циклов; после clean-env
  исправлений расширенный набор `36 passed` пять циклов;
- cancel contract дополнительно прошёл `20/20` отдельных clean-env запусков;
- финальный локальный CI-mode: `964 passed, 72 warnings`, frontend lint
  `0 errors / 1 existing warning`, build successful, `liveChecks=false`;
- первый hosted run `29232617232` остановил undeclared `requests` во время
  collection; исправлено без добавления зависимости;
- второй hosted run `29233126914` выявил 15 зависимостей tests от локального
  `.env` и одну cancel race; secret fixtures/isolation исправлены;
- третий hosted run `29234441726`: `963 passed`, осталась только cancel race;
- четвёртый hosted run `29235661215` завершён `success`: `964 passed,
  72 warnings` за 722,32 с, lint `0 errors / 1 warning`, Vite build 1,42 с,
  итоговый `VERIFY_OK mode=CI durationSeconds=774.29 liveChecks=false`;
- success URL: `https://github.com/spikeal8-maker/IZO_ASA/actions/runs/29235661215`;
- production backend не перезапускался и не использовался GitHub runner;
  локальный Quick после правок: `36 passed`, source snapshot неизменен.

Ограничение GitHub plan:

- repository private; попытка прочитать/настроить `main` branch protection
  возвращает GitHub API 403: для этой private repository требуется GitHub Pro
  либо public visibility;
- repository не делался public и платный план не оформлялся автоматически;
- поэтому workflow A2 готов и реально выполняется, но SAFE-07 остаётся
  `ЧАСТИЧНО`: check ещё нельзя сделать обязательным правилом merge на текущем plan.

### Checkpoint A7 — Host/origin и proxy-header isolation

Реализовано и развёрнуто 2026-07-13:

- Vite `server.allowedHosts` и `preview.allowedHosts` больше не равны `true`;
  разрешён только exact hostname `izo.alikinas.ru`, без wildcard/subdomain;
- `npm run check:origin` поднимает production config на временном loopback port и
  блокирует gate, если exact domain/loopback не дают 200 либо чужой host/subdomain
  не дают 403; этот шаг запускается после build в Full и CI;
- production и dev launchers, а также controlled restart запускают Uvicorn с
  `--no-proxy-headers`, чтобы `request.client.host` оставался реальным socket peer;
- `app/security/proxy_headers.py` вынесен из `main.py`: CF/XFF принимаются только
  при явном feature flag и direct peer `127.0.0.1`/`::1`; IP и country code
  валидируются, заголовки от non-loopback peer игнорируются;
- restart helper разрешает безопасный переход со старого процесса, но новый PID
  принимает только после проверки `--no-proxy-headers`; preflight сообщает
  `proxyHeadersDisabled=True|False`;
- `start-public.bat` формирует generate smoke через `ConvertTo-Json`; статусы
  generate/gallery/me-v2 должны быть ровно `401/401/401`, иначе deploy завершается
  с code 23;
- относительный запуск `powershell -File tools\verify.ps1` и restart helper теперь
  надёжно вычисляет repository root, regression tests это фиксируют;
- online verifier больше не приписывает реальную активность пользователей тестам:
  concurrent source change даёт явный marker и `sourceStable=false`; флаг
  `-RequireStableLiveSource` сохраняет strict fail для maintenance window.

Доказательства:

- characterization ожидаемо остановился на отсутствующем proxy module;
- финальный focused A7 suite: `38 passed` плюс origin-probe, пять последовательных
  циклов; отдельный verifier concurrency contract: `6 passed` пять циклов;
- окончательный Full: `976 passed, 72 warnings` за 300,73 с; frontend lint
  `0 errors / 1 existing warning`, build successful, origin checks
  `izo.alikinas.ru=200`, loopback=200, subdomain=403, foreign host=403;
- Full preflight после deploy: PID 50636, loopback, `proxyHeadersDisabled=True`;
  source snapshot стабилен: 121 файл / 1 649 086 байт / SHA-256
  `FE5B537CBA2FCFD4F74A2CFD66261BB5DF3D5E885B8D3BC96AE2227E1B513CF8`;
- предыдущий strict Full корректно заметил реальное изменение 122→121 во время
  работающего production; backend log одновременно зафиксировал настоящий
  `/api/generate` HTTP 200 и gallery/media reads, pytest после gate отсутствовал;
- финальный deploy через штатный launcher: backend PID 42616, frontend PID 31244,
  по одному listener на `127.0.0.1`; health/database ready, public main/health/version
  HTTP 200, local foreign Host HTTP 403;
- новый blocking auth smoke подтверждён в свежем backend log:
  generate/gallery/me-v2 = `401/401/401`; MAX polling продолжил HTTP 200;
- GitHub Actions run `29239661386` для exact commit `87f4351` завершён
  `success`: `976 passed, 72 warnings` за 689,08 с, lint
  `0 errors / 1 warning`, build 1,22 с, origin `200/200/403/403`, итоговый
  `VERIFY_OK mode=CI durationSeconds=748.92 liveChecks=false`;
- VPS, доменный tunnel, secrets, live DB и пользовательские media не изменялись
  пакетом A7; обнаруженные параллельные favicon-правки не включались в A7 commit.

Интеграция параллельной favicon-правки после A7:

- отдельный commit `97ebc74` корректно сохранил favicon route/shell tests, но первый
  exact-head CI run `29241278620` остановился до pytest: `backend/SYMBOL_MAP.md`
  не был перегенерирован после нового route и сдвига строк `main.py`;
- application code не менялся при исправлении: карта обновлена до 609 symbols /
  166 routes; gallery/map suite прошёл `9 passed` пять циклов;
- локальный Full после исправления: `978 passed, 72 warnings`, lint
  `0 errors / 1 existing warning`, build/origin-probe successful, source snapshot
  стабилен; runtime restart не требовался, так как менялись только generated map
  и документация.

### Checkpoint B2a — typed HTTP security configuration

Реализовано и развёрнуто 2026-07-13:

- `app/config.py` получил immutable `HttpSecurityPolicy` и import-safe loader для
  session/refresh/challenge cookie names, secure/samesite/domain/path, challenge
  TTL, CF/XFF trust flags и CORS origins;
- `main.py` сохраняет прежние compatibility globals, поэтому существующие auth,
  bot-login, cookie и analytics consumers не переписаны массово;
- extraction намеренно сохраняет старую security semantics: только literal
  `true` (case-insensitive, без whitespace normalization) включает secure/proxy
  trust; `1`, `yes` и ` true ` не расширяют доверие;
- production secure default по-прежнему включается только при точном
  `APP_ENV=production`; `prod` не меняет прежнее поведение;
- CORS default/ordering и очистка пустых comma-separated entries сохранены;
  FastAPI middleware получает обычный list из typed tuple policy;
- production validation не смешана с extraction и остаётся следующим подпакетом
  B2 вместе с path/URL/mode/limit policies.

Доказательства:

- characterization ожидаемо остановился на отсутствующих
  `DEFAULT_CORS_ALLOWED_ORIGINS`/`load_http_security_policy`;
- расширенный config/cookie/bot/proxy suite: `55 passed` пять последовательных
  циклов; generated backend map `ok` в каждом цикле;
- финальный Full: `983 passed, 72 warnings` за 293,45 с; frontend lint
  `0 errors / 1 existing warning`, build successful, origin `200/200/403/403`;
- source snapshot стабилен: 121 файл / 1 649 086 байт / SHA-256
  `FE5B537CBA2FCFD4F74A2CFD66261BB5DF3D5E885B8D3BC96AE2227E1B513CF8`;
- deploy через штатный production launcher: backend PID 48656, frontend PID 10564,
  по одному loopback listener, health/database ready, public main/health/version
  HTTP 200, auth smoke `401/401/401`, MAX polling HTTP 200;
- live CORS: `https://izo.alikinas.ru` получил HTTP 200 и exact allow-origin;
  `https://evil.example` получил HTTP 400 без allow-origin;
- VPS, tunnel, secrets, DB и media не изменялись; runtime restart выполнялся
  launcher с production environment, а не unconfigured backend-only shell.

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
9. Проверить отсутствие pytest-процессов, temp-root isolation и source marker;
   strict неизменность live media требовать только в maintenance window.
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
