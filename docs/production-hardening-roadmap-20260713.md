# IZO ASA — актуальный план оптимизации и подготовки production

Дата актуализации: 2026-07-14

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

Проверено 2026-07-14:

| Параметр | Факт |
|---|---|
| Git | `main` синхронизирован с `origin/main` |
| Последний completed checkpoint | `B8l` — separate feed source-history read/mapping service; B8 завершён, следующий пакет B9a |
| Backend | один Uvicorn listener на `127.0.0.1:8000` |
| Backend health | HTTP 200 |
| Последний полный test checkpoint | 1314 passed, 0 failed, 0 skipped, 0 deselected |
| Frontend lint | 0 errors, 1 известный hooks warning |
| Frontend production build | успешно |
| Private source без trusted session | HTTP 401 |
| Source baseline | 120 файлов / 1 595 746 байт / SHA-256 `078DB0E8BE1C646E914D8E7B247871F8DC7DD3B073204999E95837D8259787B4`; изменения объяснены реальными пользовательскими генерациями и были стабильны внутри gates |
| Production DB/media в тестах | не используются, принудительно изолированы |
| CI | GitHub Actions active; exact B8l/remediation run `29321670540` success (`1314 passed`), required branch protection недоступен на текущем private plan |
| Frontend production server | Vite Preview |
| Process supervisor | отсутствует; используются launcher/PowerShell processes |
| Backup | A6 tooling и пять live snapshot готовы; pre-B7a snapshot `20260713T221737.032822Z` verify/rehearsal успешен; schedule/retention ещё не включены |

## 4. Реальные размеры крупных файлов

Размеры измерены из текущего рабочего дерева, а не перенесены из старого плана.

| Файл | Строк | Цель |
|---|---:|---:|
| `backend/main.py` | 14 367 после B8l | B8 storage/gallery boundary завершена; B9a выносит read-only feed item/reaction/viewer query boundary, full payload и mutations остаются позже |
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
| BE-01 | `ГОТОВО` | `app/config.py` владеет env/DB-path helpers, typed HTTP/provider/runtime/bot/media/storage policies и secret-free blocking production validation; compatibility exports удаляются только в B14 |
| BE-02 | `ЧАСТИЧНО` | Schema/migration scope B3 готов: ledger/version, core/billing, identity и media groups; repository layer остаётся отдельной незавершённой границей |
| BE-03 | `ЧАСТИЧНО` | Tokens/passwords/sessions/permissions/OTP/events вынесены; legacy auth removal и routers не завершены |
| BE-04 | `ГОТОВО` | B8a–B8l завершили storage/gallery policy, repository, eviction, query, presentation, item, snapshot и source-history boundaries; feed publication/reaction/moderation orchestration относится к B9 |
| BE-05 | `ГОТОВО` | Текущий ограниченный scope Ollama: URL, discovery и общий chat transport вынесены |
| BE-06 | `ГОТОВО` | Ограниченный integration scope завершён: HTTP/parsing/planning/I/O/model aliases/request metadata вынесены; application caches, policy, persistence, billing и orchestration остаются в соответствующих будущих services |
| BE-07 | `ГОТОВО` | B4a client/errors/file URL/health и B4b parsing/update handlers service выделены; routes/polling lifecycle остаются общим B12/B13 scope |
| BE-08 | `ГОТОВО` | B5a client/errors/health и B5b parsing/update handlers service выделены; routes/polling/subscription lifecycle остаются B12/B13 scope |
| BE-09 | `ГОТОВО` | B6a HTTP client, B6b pure workflow builders и B6c result/media adapter выделены; generation/job/gallery orchestration остаётся B7/B8 |
| BE-10 | `ГОТОВО` | B7a recovery, B7b persistence/response, B7c result states, B7d single-job processor и B7e in-process queue consumer/one-shot startup lifecycle выделены; concrete adapters/compatibility wrappers удаляются только в B14 |
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
| OPS-04 | `НЕ НАЧАТО` | Backend/Caddy/ComfyUI/Ollama не оформлены как надёжные managed services: два backend PID исчезали без traceback; ComfyUI boot task имеет restart count 0/nonzero last result, а во время B7b процесс был недоступен и менял PID через параллельный launcher |
| OPS-05 | `ЧАСТИЧНО` | SQLite Backup API + incremental media работают на отдельный физический `I:`; пять live snapshot проверены, но регулярный schedule/retention ещё не настроены |
| OPS-06 | `ЧАСТИЧНО` | SHA-256, manifest checksum, SQLite `quick_check` и restore rehearsal готовы; encrypted offsite copy ещё не выбрана |
| OPS-07 | `ЧАСТИЧНО` | Есть health/logs и ручной storage audit, но нет единого monitoring/alerting контура |
| OPS-08 | `ГОТОВО` | Внешний VPS/tunnel исключён из оптимизационных изменений |
| OPS-09 | `ГОТОВО` | MAX переведён на `platform-api2.max.ru`; HTTPX использует native system trust store, polling и `/me` live smoke успешны |

### 5.6. Database, billing и масштабирование

| ID | Статус | Состояние |
|---|---|---|
| DATA-01 | `ЧАСТИЧНО` | SQLite остаётся единственной production DB; guard, ledger/version 1 и все текущие idempotent schema groups готовы, но lock/busy telemetry ещё не завершена |
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
| B2 | `ГОТОВО` — B2a HTTP security, B2b provider endpoints/timeouts, B2c runtime/bot modes, B2d media limits, B2e storage paths и B2f production validation готовы |
| B3 | `ГОТОВО` — ledger/version 1, core/billing, identity/auth, media/feed/search groups и migration tests; в `main.py` inline DDL отсутствует |
| B4 | `ГОТОВО` — B4a client/errors/health и B4b injected update handlers service выделены без смены polling/webhook semantics |
| B5 | `ГОТОВО` — B5a client/errors/health и B5b injected update handlers service выделены без смены polling/webhook semantics |
| B6 | `ГОТОВО` — B6a HTTP client, B6b workflow builders и B6c result/media adapter выделены |
| B7 | `ГОТОВО` — recovery, persistence/response, result states, single-job processor и in-process queue consumer/one-shot startup lifecycle выделены; persistent queue/multi-worker относятся к волне F |
| B8 | `ГОТОВО` — B8a–B8l quota/read/eviction/query/gallery/feed presentation/source-history boundaries выделены атомарно; source write/delete lifecycle уже принадлежит storage services |
| B9 | `НЕ НАЧАТО` — выделить feed item reads/presentation, publication, reaction и moderation services по отдельным пакетам |
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
9. `A7` — `ГОТОВО`: host allowlist и proxy-origin checks.
10. `B2` — `ГОТОВО`: typed config extraction и blocking production validation.
11. `B3a` — `ГОТОВО`: migration ledger, immutable checksum и baseline schema version 1.
12. `B3b` — `ГОТОВО`: media/feed/search idempotent schema execution group.
13. `B3c` — `ГОТОВО`: identity/auth prepare, legacy backfill и finalize phases.
14. `B3d` — `ГОТОВО`: core/base/billing schema preparation и default seeds; B3 закрыт.
15. `B4a` — `ГОТОВО`: Telegram client/typed errors/file URL/health boundary.
16. `B4b` — `ГОТОВО`: Telegram update parsing/handlers service без переноса routes; B4 закрыт.
17. `B5a` — `ГОТОВО`: MAX async/sync client, typed errors и health boundary.
18. `B5b` — `ГОТОВО`: MAX update parsing/handlers service без переноса routes; B5 закрыт.
19. `B6a` — `ГОТОВО`: ComfyUI HTTP client boundary без переноса workflow/result logic.
20. `B6b` — `ГОТОВО`: ComfyUI workflow endpoint policy и pure graph builders.
21. `B6c` — `ГОТОВО`: ComfyUI result/media adapter; B6 закрыт.
22. `B7a` — `ГОТОВО`: transactional startup reconciliation orphaned generation jobs и idempotent refund.
23. `B7b` — `ГОТОВО`: generation job persistence/response boundary без переноса worker orchestration.
24. `B7c` — `ГОТОВО`: pure generation result/job-state builders без переноса side effects.
25. `B7d` — `ГОТОВО`: single-job generation processor с явно инъецированными provider/storage/billing callbacks; внешний queue loop и startup lifecycle сохранены.
26. `B7e` — `ГОТОВО`: in-process queue consumer и one-shot startup-task lifecycle с characterization cancellation/error/duplicate-start; B7 закрыт.
27. `B8a` — `ГОТОВО`: pure normalizer тарифа, точный quota payload и решение вытеснить 0/1/2 старых unprotected image; SQL/files не переносились.
28. `B8b` — `ГОТОВО`: owner-scoped active count и favorite-protected oldest eviction-candidate read repository; mutations/files не переносились.
29. `B8c` — `ГОТОВО`: последовательность source-delete → soft-delete → file-delete → cache-drop вынесена через frozen injected runtime; concrete adapters остались в `main.py`.
30. `B8d` — `ГОТОВО`: pure cursor encode/decode и FTS normalization вынесены; valid-JSON non-object cursor теперь контролируемо даёт HTTP 400.
31. `B8e` — `ГОТОВО`: pure aspect-ratio, mode-label и source-ID helpers вынесены; неиспользуемая зависимость mode-label от admin cache удалена.
32. `B8f` — `ГОТОВО`: model-info builder вынесен с явно инъецированными price catalog/display-name/release-year dependencies; precedence и точный локальный ИЗО payload зафиксированы тестами.
33. `B8g` — `ГОТОВО`: pure/injected public gallery params builder вынесен; exact labels/order/filtering, `0 ток.` и callback sequence зафиксированы.
34. `B8h` — `ГОТОВО`: public bytes/duration/datetime/token-cost implementations вынесены в presentation service; thin wrappers, injected builder API и feed snapshot semantics сохранены.
35. `B8i` — `ГОТОВО`: legacy `row_to_image` mapping вынесен через structural row и JSON/model/file/public-params/row-get callbacks; wrapper сохранён.
36. `B8j` — `ГОТОВО`: новый 105-строчный `app/services/gallery_items.py` владеет feed readiness и gallery page-item mapping; presentation service не разросся.
37. `B8k` — `ГОТОВО`: новый 55-строчный `app/services/feed_presentation.py` владеет generation snapshot assembler через explicit callbacks; backfill SQL и `_feed_item_payload` не переносились.
38. `B8l` — `ГОТОВО`: новый 41-строчный `app/services/feed_sources.py` владеет source-history query/mapping; snapshot/item wrappers сохранены, B8 закрыт.
39. `B9a` — **СЛЕДУЮЩИЙ ПАКЕТ**: создать read-only `app/storage/feed_repository.py` и вынести из `_feed_item_payload` только image lookup, reaction counts и viewer reaction/follow/role reads в typed result; payload assembly, author/challenge/source callbacks, publication/reaction mutations и routes не переносить.

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

- OPS-05 имеет реализованный код schedule/age alert в A6b, но остаётся
  `ЧАСТИЧНО` до физической установки и недельного наблюдения; retention до этого
  намеренно выключен;
- OPS-06 остаётся `ЧАСТИЧНО`, пока не появится зашифрованная offsite-копия и
  отдельное хранение recovery key.

### Checkpoint A6b — Яндекс.Диск transport и STANDBY automation

Код реализован и локально проверен 2026-07-16:

- `tools/backup_transport.py` публикует только verified snapshot в раздельные
  `database/snapshots`, `recovery/manifests`, `data/media-objects`; база, manifest
  и media повторно сверяются, а `COMPLETED` публикуется последним;
- завершённый cloud snapshot неизменяем; повторный stage только проверяет его;
- STANDBY получает данные в отдельный ReplicaCache, после чего выполняет полный
  verify и опциональный rehearsal; backend/FRP автоматически не включаются;
- `ops/backup` содержит role config, fail-closed launcher guard, lock локального
  backup, 15-минутный local schedule, почасовой stage/receive, ежедневный STANDBY
  rehearsal и 10-минутный health monitor;
- установщик проверяет NTFS, отдельный backup volume, fixed internal Yandex root,
  наличие live DB/media/Python, `YandexDisk4.exe` и `cldflt`; secrets не записывает;
- contract suite: `17 passed`; все PowerShell-сценарии разобраны parser без ошибок;
- production-safe snapshot `20260716T005805.698960Z`: DB 565 104 640 байт,
  media 2 436 файлов / 260 170 702 байта, 96 новых objects / 2 340 reuse;
  `BACKUP_VERIFY_OK` и `BACKUP_REHEARSAL_OK` успешны без остановки backend.

Физическое внедрение пока `BLOCKED`, а не объявлено готовым:

- PRIMARY-кандидат: `D2-R2-X`; имя STANDBY и выделенный Яндекс-аккаунт не указаны;
- Диск 4.21.2.4570 и legacy 3.2.48.5157 работают одновременно с подтверждёнными
  разными невложенными roots `D:\Yandex.Disk` и `C:\Users\spike\YandexDisk`;
- `disk.yandex.ru:443` доступен через интерфейс `AdGuard VPN`, а требуемый direct
  route ещё не настроен; stage разрешён, но health остаётся `ATTENTION`;
- папка `D:\Yandex.Disk\IZO_ASA_ServerBackup` обнаружена, но Яндекс 360, режим
  «Хранить на компьютере», свободное облачное место и отсутствие sync errors не
  подтверждены;
- реальный cloud download на STANDBY, reboot/offline tests и пять полных циклов
  ещё должны быть выполнены по `yandex-disk-backup-runbook-20260716.md`;
- пользовательские media пока не имеют отдельного end-to-end encryption; решение
  владельца и recovery-key runbook обязательны до production offsite.

### Checkpoint A2 — deterministic GitHub Actions CI

Реализовано 2026-07-13:

- `.github/workflows/ci.yml` запускается на push/PR в `main` и вручную, имеет
  только `contents: read`, concurrency cancellation и 30-minute job timeout;
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

Exact-head CI после B2a:

- GitHub Actions run `29243790613` на SHA `ac81e3a` завершён успешно;
- `983 passed, 72 warnings` за 820,63 с; lint `0 errors / 1 existing warning`;
- production build 1,15 с, origin isolation `200/200/403/403`, итоговый
  `VERIFY_OK` CI за 868,60 с.

### Checkpoint B2b — typed provider endpoints and timeouts

Реализовано и развёрнуто 2026-07-13:

- `app/config.py` получил immutable `ProviderEndpointPolicy` и import-safe loader
  для ComfyUI URL/required/mock/timeouts, OpenRouter URL/timeout, prompt-improvement
  model/timeout и двух URL источников курса USD/RUB;
- `main.py` сохраняет прежние `COMFYUI_*`, `OPENROUTER_*`, `PROMPT_IMPROVE_*`,
  `CBR_DAILY_XML_URL` и `USD_RUB_FALLBACK_URL`, поэтому существующие clients,
  routes, tests и monkeypatch-поведение не переписаны массово;
- в точности сохранены legacy semantics: literal `true` для ComfyUI flags,
  отсутствие trim у ComfyUI/CBR/fallback URL, `rstrip("/")` у OpenRouter,
  `strip()` у prompt model, прежние clamp/floor rules и fail-fast `ValueError`
  для неверных integer values;
- строк в `main.py` временно стало 15 281: безопасные compatibility exports и
  развёрнутые imports пока больше удалённого env-блока. Реальное сокращение будет
  после перевода consumers и удаления exports в B14; ownership конфигурации уже
  вынесен из runtime entrypoint без изменения поведения.

Доказательства:

- characterization до реализации остановился ровно на отсутствующем
  `load_provider_endpoint_policy`;
- focused config/API/ComfyUI/OpenRouter/prompt/admin/secret suite:
  `306 passed, 54 warnings` пять последовательных циклов; generated map
  `609 symbols / 166 routes` совпал после каждого цикла;
- локальный Full: `987 passed, 72 warnings` за 288,85 с; frontend lint
  `0 errors / 1 existing warning`, production build успешен, origin
  `200/200/403/403`;
- verifier: 121 файл / 1 649 086 байт / SHA-256
  `FE5B537CBA2FCFD4F74A2CFD66261BB5DF3D5E885B8D3BC96AE2227E1B513CF8`,
  source stable, итоговый Full 315,27 с;
- deploy штатным production launcher: backend PID 33016, frontend PID 13156,
  по одному listener на `127.0.0.1:8000/5173`, Uvicorn с
  `--no-proxy-headers`, health/DB Guard ready;
- local main/health/version/models/feed и public main/health/version HTTP 200;
  auth smoke `401/401/401`; CORS allowed exact origin HTTP 200 с exact header,
  denied origin HTTP 400 без allow-origin; MAX `/me` и polling HTTP 200;
- paid generation не запускалась; secrets, production DB rows, media, VPS и
  tunnel не изменялись.

Exact-head CI после B2b:

- GitHub Actions run `29245840902` на SHA `433d979` завершён успешно;
- `987 passed, 72 warnings` за 657,46 с; lint `0 errors / 1 existing warning`;
- production build 1,35 с, origin isolation `200/200/403/403`, итоговый
  `VERIFY_OK` CI за 712,32 с.

### Checkpoint B2c — typed runtime and bot delivery modes

Реализовано и развёрнуто 2026-07-13:

- `app/config.py` получил immutable `RuntimeEnvironmentPolicy` и
  `BotDeliveryPolicy`, pure production-like predicate и import-safe loaders;
- environment policy владеет `APP_ENV`/`ENV`/`MODE`; bot policy — legacy
  `BOT_UPDATES_MODE` с fallback на `BOT_MODE`, Telegram/MAX polling flags и
  `MAX_UPDATES_MODE` с прежним fallback на нормализованный Telegram mode;
- `main.py` сохраняет прежние `APP_ENV`, `ENV_NAME`, `MODE_NAME`,
  `BOT_UPDATES_MODE`, `BOT_MODE`, `TELEGRAM_POLLING_ENABLED`,
  `MAX_POLLING_ENABLED`, `MAX_UPDATES_MODE` и динамический
  `is_production_like_env()`, поэтому monkeypatch и runtime consumers не менялись;
- policy не читает токены/secrets, не запускает workers и не делает provider
  requests; webhook validation и polling lifecycle остаются в прежнем порядке;
- нормализация в точности сохранена: trim/lower для modes, допустимы только
  `webhook/polling/disabled`, invalid Telegram → disabled, invalid MAX → Telegram,
  polling booleans используют прежние `1/true/yes/on` semantics;
- `main.py` временно 15 285 строк из-за compatibility imports/exports; это
  осознанный промежуточный этап до удаления exports в B14, а не заявление о
  завершённом физическом сокращении монолита.

Доказательства:

- characterization до реализации остановился ровно на отсутствующих pure loaders;
- focused config/API/DB-guard/Telegram/MAX/maintenance suite:
  `95 passed, 2 warnings` пять последовательных циклов; generated map
  `609 symbols / 166 routes` совпал после каждого цикла;
- локальный Full: `991 passed, 72 warnings` за 289,94 с; lint
  `0 errors / 1 existing warning`, build успешен, origin `200/200/403/403`;
- verifier: 121 файл / 1 649 086 байт / SHA-256
  `FE5B537CBA2FCFD4F74A2CFD66261BB5DF3D5E885B8D3BC96AE2227E1B513CF8`,
  source stable, итоговый Full 315,63 с;
- deploy штатным production launcher: backend PID 52900, frontend PID 44084,
  один loopback listener на каждом порту, Uvicorn `--no-proxy-headers`,
  health/DB Guard production ready;
- live bot status: Telegram mode `polling`, MAX mode `polling`, оба polling-ready;
  MAX API `/me` 200, polling 200, `lastUpdatesError=null`, webhook mode не включён;
- local main/health/version/models/feed и public main/health/version HTTP 200;
  auth `401/401/401`, allowed CORS exact 200, denied CORS 400, host
  `200/200/403/403`;
- provider modes не переключались вручную; secrets, production DB rows, media,
  VPS и tunnel не изменялись.

Exact-head CI после B2c:

- GitHub Actions run `29247461484` на SHA `3144a71` завершён успешно;
- `991 passed, 72 warnings` за 776,86 с; lint `0 errors / 1 existing warning`;
- production build 1,23 с, origin isolation `200/200/403/403`, итоговый
  `VERIFY_OK` CI за 833,69 с.

### Checkpoint B2d — typed media-processing limits

Реализовано и развёрнуто 2026-07-13:

- `app/config.py` получил immutable `MediaProcessingPolicy` и import-safe loader
  для ComfyUI input/face limits, face-source megapixels, gallery max side/WebP
  quality/recent full-quality count, archive side/quality и source thumbnails;
- `main.py` сохраняет все прежние `COMFYUI_*`, `GALLERY_*` и `SOURCE_THUMB_*`
  compatibility globals; resize, thumbnail, archive, recovery и save functions
  не переносились и не переписывались;
- точно сохранены прежние `int`/`float`, min/max bounds, зависимость face side от
  общего ComfyUI max, зависимость archive side от gallery max и fail-fast
  `ValueError` для неверных чисел;
- сохранён прежний порядок инициализации: эти limits, как и раньше, читаются до
  `load_local_env(ROOT)` и поэтому не начинают неожиданно принимать значения из
  `.env`; process-level environment contract не изменён;
- `COMFYUI_INPUT_MIN_SIDE=256` оставлен обычной константой в `main.py`;
- `main.py` временно 15 288 строк из-за compatibility imports/exports; физическое
  сокращение остаётся после перевода consumers и B14.

Доказательства:

- characterization до реализации остановился ровно на отсутствующем loader;
- focused config/ComfyUI/gallery/source/recovery/audit/generation/API/feed suite:
  `202 passed, 18 warnings` пять последовательных циклов; generated map
  `609 symbols / 166 routes` совпал после каждого цикла;
- локальный Full: `995 passed, 72 warnings` за 295,20 с; lint
  `0 errors / 1 existing warning`, build успешен, origin `200/200/403/403`;
- verifier завершился успешно за 321,40 с, но корректно отметил concurrent live
  source change во время online-прогона: `118 / 1 617 046 /
  2DB62587F1E1CD4EE03C058630A4EC32B7632B7729F09ED13D5F8D271A2C949D` →
  `115 / 1 568 444 /
  A16510695E8C187E330DB6D198F2CAC9157EE468111325CF8BF35568D05CD02A`,
  поэтому `sourceStable=false`; strict gate без maintenance window намеренно не
  применялся;
- после deploy startup независимо подтвердил согласованное текущее состояние:
  `checked=116`, `available=115`, `missing=1`, `changed=0`; тесты использовали
  temp roots, production media не изменяли;
- deploy штатным launcher: backend PID 32728, frontend PID 40472, по одному
  loopback listener, Uvicorn `--no-proxy-headers`, health/DB Guard ready;
- local main/health/version/models/feed и public main/health/version HTTP 200;
  auth `401/401/401`, CORS `200/400`, host `200/200/403/403`, Telegram/MAX
  polling ready, MAX `/me` и poll 200 без ошибки;
- paid generation не запускалась; secrets, production DB rows, VPS и tunnel не
  изменялись.

Exact-head CI после B2d:

- GitHub Actions run `29249610234` на SHA `31c6fd9` завершён успешно;
- `995 passed, 72 warnings` за 876,50 с; lint `0 errors / 1 existing warning`;
- production build 1,17 с, origin isolation `200/200/403/403`, итоговый
  `VERIFY_OK` CI за 920,76 с.

### Checkpoint B2e — typed storage path values

Реализовано и развёрнуто 2026-07-13:

- `app/config.py` получил immutable `StoragePathPolicy` и import-safe loader для
  `MEDIA_DIR`, derived avatar directory и `DATABASE_URL`/SQLite path;
- loader только вычисляет `Path`: он не создаёт каталоги, не читает содержимое,
  не подключается к SQLite и не перемещает data; `MEDIA.mkdir` и
  `AVATAR_DIR.mkdir` намеренно остались явными в runtime wiring `main.py`;
- `main.py` сохраняет compatibility globals `MEDIA`, `AVATAR_DIR`, `DB_PATH`,
  поэтому storage/database consumers и test monkeypatch не переписаны массово;
- сохранены legacy semantics `expanduser().resolve()` для media, пустого
  `MEDIA_DIR`, default `<backend>/media`, relative/raw/`sqlite:`/`sqlite:///`
  database values и default `<backend>/onenode.sqlite3`;
- policy создаётся на прежнем месте сразу после `load_local_env(ROOT)`; чтение
  `DATABASE_URL` происходит чуть раньше внутри того же синхронного import, но
  между прежними точками нет env mutation, а characterization/full suite
  подтвердили эквивалентность;
- static page/favicon/avatar-preset existence discovery оставлено в `main.py`:
  это runtime asset discovery, а не изменяемая path-конфигурация;
- `main.py` временно 15 289 строк из-за compatibility export; удаление exports
  остаётся B14 после перевода consumers.

Доказательства:

- characterization до реализации остановился ровно на отсутствующем loader;
- focused config/database/DB-guard/storage/lifecycle/API/ownership suite:
  `144 passed, 24 warnings` пять последовательных циклов; generated map
  `609 symbols / 166 routes` совпал после каждого цикла;
- отдельный test подтверждает отсутствие directory creation на несуществующем
  root и точную обработку empty media/relative SQLite paths;
- локальный Full: `998 passed, 72 warnings` за 390,16 с; lint
  `0 errors / 1 existing warning`, build успешен, origin `200/200/403/403`;
- verifier source стабилен весь прогон: 115 файлов / 1 568 444 байта /
  `A16510695E8C187E330DB6D198F2CAC9157EE468111325CF8BF35568D05CD02A`,
  итоговый Full 422,95 с;
- deploy штатным launcher: backend PID 44440, frontend PID 34680, по одному
  loopback listener, Uvicorn `--no-proxy-headers`;
- health подтвердил прежнюю live SQLite: 538,93 MB, 33 users, 5 active admins,
  migration/DB Guard `ok`; startup source `checked=116 / available=115 /
  missing=1 / changed=0`;
- local main/health/version/models/feed и public main/health/version HTTP 200;
  auth `401/401/401`, CORS `200/400`, host `200/200/403/403`, Telegram/MAX
  polling ready, MAX `/me` и polling 200 без ошибки;
- каталоги/data не переносились; paid generation, secrets, production DB rows,
  VPS и tunnel не изменялись.

Exact-head CI после B2e:

- GitHub Actions run `29252173619` на SHA `7983419` завершён успешно;
- `998 passed, 72 warnings` за 852,82 с; lint `0 errors / 1 existing warning`;
- production build 1,21 с, origin isolation `200/200/403/403`, итоговый
  `VERIFY_OK` CI за 899,04 с.

### Checkpoint B2f — blocking production configuration validation

Реализовано и развёрнуто 2026-07-13:

- `app/config.py` получил pure `production_configuration_errors()` и blocking
  `validate_production_configuration()`; development/test полностью пропускаются;
- production-like environment требует exact `APP_ENV=production`, чтобы DB Guard
  и session-secret validation не расходились из-за `ENV=prod`/`MODE=live` при
  фактическом development APP_ENV;
- startup до webhook и DB действий блокирует insecure/invalid cookie policy,
  empty/wildcard/malformed CORS, ComfyUI mock fallback, insecure external provider
  URL, пустую prompt model и relative media/database paths;
- внешние provider URL требуют HTTPS; HTTP разрешён только для localhost/IPv4/IPv6
  loopback, поэтому локальный ComfyUI `127.0.0.1:8188` остаётся корректным;
- URL validation проверяет scheme/host/credentials и numeric port; malformed port
  найден на diff-review, добавлен отдельный regression test и все focused-циклы
  после этого перезапущены с нуля;
- ошибки содержат только стабильные codes, без URL/path/secret values;
- существующие Telegram/MAX webhook secret checks, DB Guard и session secret guard
  не дублируются и выполняются сразу после нового общего gate;
- отдельный startup-order test доказывает, что unsafe config останавливает startup
  до webhook и DB; второй test проверяет передачу именно текущих typed policies;
- B2 завершён полностью. Временные compatibility globals остаются сознательно до
  перевода consumers и удаления exports в B14; поэтому `main.py` сейчас 15 297
  строк и ещё не считается физически сокращённым до целевого entrypoint.

Доказательства:

- characterization до реализации остановился ровно на отсутствующих validator
  functions;
- launcher-equivalent import-safe preflight выполнен дважды до deploy:
  `ok=True`, `errors=()`; FastAPI app/SQLite не импортировались, values/secrets не
  выводились;
- финальный focused config/startup/security/session/cookie/DB/webhook/proxy/
  launcher suite после malformed-port fix: `153 passed, 2 warnings` пять
  последовательных циклов; generated map `609 symbols / 166 routes` совпал;
- локальный Full: `1005 passed, 72 warnings` за 286,68 с; frontend lint
  `0 errors / 1 existing warning`, build успешен, origin `200/200/403/403`;
- verifier: 122 Python-файла, source стабилен — 115 файлов / 1 568 444 байта /
  `A16510695E8C187E330DB6D198F2CAC9157EE468111325CF8BF35568D05CD02A`,
  итоговый Full 313,84 с;
- deploy штатным launcher: backend PID 41484, frontend PID 28960, по одному
  loopback listener, Uvicorn `--no-proxy-headers`; свежий backend log
  `UNSAFE_CONFIG_ERRORS=0`;
- health: production, live SQLite 538,93 MB, 33 users, 5 active admins,
  migration/DB Guard `ok`; source `checked=116 / available=115 / missing=1 /
  changed=0`;
- local main/health/version/models/feed и public main/health/version HTTP 200;
  auth `401/401/401`, CORS `200/400`, host `200/200/403/403`, Telegram/MAX
  polling ready, MAX `/me` и poll 200 без ошибки;
- paid generation не запускалась; secrets, production DB rows, media, VPS и
  tunnel не изменялись.

Exact-head CI после B2f:

- GitHub Actions run `29254828576` на SHA `9aeb9eb` завершён успешно;
- `1005 passed, 72 warnings` за 994,30 с; lint `0 errors / 1 existing warning`;
- production build 1,78 с, origin isolation `200/200/403/403`, итоговый
  `VERIFY_OK` CI за 1040,73 с.

### Checkpoint B3a — SQLite migration ledger и baseline version 1

Реализовано и развёрнуто 2026-07-13:

- `app/database/migrations.py` получил immutable `MigrationDefinition`, таблицу
  `schema_migrations`, чтение `PRAGMA user_version` и идемпотентную запись
  применённой миграции с проверкой version/name/SHA-256 checksum;
- baseline `1 / legacy_schema_baseline` фиксирует уже существующую legacy-схему,
  не пытаясь повторно создавать или преобразовывать пользовательские данные;
- база с `user_version` или ledger version новее поддерживаемой блокируется до
  выполнения schema DDL; изменение checksum/name применённой версии и повторное
  использование имени другой версией также блокируются стабильными error codes;
- `init_db()` создаёт пустой ledger до идемпотентного legacy DDL, но записывает
  baseline и повышает `user_version` только в самом конце успешного schema/
  seed/backfill прохода; повторный `init_db()` не меняет `applied_at` и не создаёт
  вторую строку;
- B3 этим не завершён: группировка auth/feed/billing schema остаётся в B3b+;
  `main.py` временно 15 308 строк, поскольку legacy execution order и
  compatibility wiring пока сохранены.

Доказательства:

- до deploy live-БД открыта read-only: `user_version=0`, ledger отсутствует;
  baseline counts `users=33`, `active_admins=5`, `images=961`,
  `feed_publications=69`, `token_ledger=1373`;
- перед первой live-миграцией создан snapshot `20260713T142811.243312Z` на
  отдельном физическом `I:`: 565 104 640 байт SQLite, 2390 media-файлов /
  244 189 640 байт; отдельный `--verify-only` дал `BACKUP_VERIFY_OK`;
- focused database/DB-guard/identity/password/API/lifecycle/billing/feed suite:
  `164 passed, 2 warnings` пять последовательных циклов; отдельные tests
  подтверждают idempotency, mismatch/name-reuse/newer-version fail-fast и
  отсутствие schema mutation для неподдерживаемой версии;
- локальный Full: `1012 passed, 72 warnings` за 299,60 с; frontend lint
  `0 errors / 1 existing warning`, build успешен за 0,92 с, origin
  `200/200/403/403`;
- verifier: 122 Python-файла, source стабилен — 115 файлов / 1 568 444 байта /
  `A16510695E8C187E330DB6D198F2CAC9157EE468111325CF8BF35568D05CD02A`,
  итоговый Full 333,79 с;
- deploy штатным launcher: backend PID 55100, frontend PID 16372, по одному
  loopback listener, Uvicorn `--no-proxy-headers`; startup source
  `checked=116 / available=115 / missing=1 / changed=0`;
- после deploy read-only verification: SQLite `quick_check=ok`, `user_version=1`,
  ровно одна строка `legacy_schema_baseline` с ожидаемым checksum; все пять
  baseline counts полностью совпали, то есть пользовательские и финансовые строки
  миграцией не потеряны и не добавлены;
- health/DB Guard `ok`, local health/models/feed и frontend root/version HTTP 200,
  private gallery HTTP 401; MAX остался в polling, `/me` и polling 200 без ошибки;
- secrets, provider modes, paid generation, VPS и tunnel не изменялись.

Exact-head CI после B3a:

- GitHub Actions run `29258633264` на SHA `a2f337f` завершён успешно за 16 мин 06 с;
- `1012 passed, 72 warnings` за 842,50 с; lint `0 errors / 1 existing warning`;
- production build 1,38 с, origin isolation `200/200/403/403`, итоговый
  `VERIFY_OK` CI за 889,84 с.

### Checkpoint B3b — media/feed/search schema execution group

Реализовано и развёрнуто 2026-07-13:

- новый import-safe `app/database/schema_groups.py` владеет одним идемпотентным
  execution group: additive feed media columns, feed/gallery indexes,
  `deleted_at` normalization, image FTS schema/backfill, image-source и job indexes;
- 67-строчный inline SQL-блок в `main.init_db()` заменён одним вызовом
  `initialize_media_schema_group(conn)` строго в прежнем месте — после identity
  schema/session column и до challenge seed/identity backfill;
- SQL declarations, порядок statements и `executescript()` boundary не изменены;
  три больше не используемых imports удалены из `main.py`, а публичные database
  exports сохранены;
- `main.py` физически уменьшен с 15 308 до 15 238 строк; новый модуль не
  импортирует FastAPI, application globals, filesystem, network или secrets;
- schema version не повышалась: B3b — механическая декомпозиция уже применённой
  baseline schema version 1, а не новая data migration.

Доказательства:

- characterization до переноса на старом inline-коде подтвердил все 12 indexes,
  FTS backfill уже существующей image row, `deleted_at='' → NULL` и повторный
  `init_db()` без дублей; тот же тест зелёный после переноса;
- прямой unit-contract применяет group дважды без runtime wiring и проверяет feed,
  image-source, image и FTS contracts; весь database module: `19 passed`;
- focused database/DB Guard/API/lifecycle/feed/gallery/source-graph suite:
  `147 passed, 2 warnings` пять последовательных циклов по 130–133 с;
- локальный Full: `1014 passed, 72 warnings` за 280,73 с; frontend lint
  `0 errors / 1 existing warning`, build успешен за 0,505 с, origin
  `200/200/403/403`;
- verifier: 123 Python-файла, source стабилен — 116 файлов / 1 576 580 байт /
  `2D5E93221F75C4A01960EB43E9CCBEDBE94D8985D9B31A2B32CC77D397D1328B`,
  итоговый Full 304,75 с;
- pre/post restart affected schema fingerprint полностью совпал: 16 objects,
  SHA-256 `9d96dd2071ebaa776fe94defbc7174547dffa9d72a88fc39a409dab41c3e6ed6`;
  SQLite `quick_check=ok`, `user_version=1`, ledger rows `1`, images/search rows
  `962/962`, empty `deleted_at=0`;
- непосредственно до/после restart без изменений: feed publications `69`, image
  sources `124`, jobs `681`, token ledger `1376`; отдельный новый backup не нужен,
  потому что SQL/data behavior не менялись, а проверенный pre-B3a snapshot сохранён;
- deploy штатным launcher: backend PID 53684, frontend PID 35400, по одному
  loopback listener; startup source `checked=117 / available=116 / missing=1 /
  changed=0`;
- health/DB Guard, models, feed, frontend root/version HTTP 200, private gallery
  HTTP 401; MAX остался в polling, `/me` и poll 200 без ошибки;
- secrets, provider modes, paid generation, production data, VPS и tunnel не
  изменялись.

CI timeout correction для B3b:

- первый exact-head run `29261577261` на SHA `7d97cab` дошёл до `92%` pytest без
  test failure, но GitHub принудительно отменил job по прежнему пределу `20m0s`;
- это инфраструктурная отмена, не регрессия B3b: local Full/live gates остались
  зелёными, runtime не перезапускался повторно;
- workflow timeout увеличен до ограниченных 30 минут, что оставляет запас для
  вариативности Windows runner, но продолжает останавливать зависший job;
- новый contract сначала ожидаемо упал на старом YAML, затем весь
  `tools/test_ci_workflow.py` дал `4 passed` пять последовательных циклов;
- исправление фиксируется отдельным CI-only commit, после которого exact-head run
  запускается с нуля.

Exact-head CI после B3b и timeout correction:

- повторный GitHub Actions run `29263163242` на SHA `c6ff1ae` завершён успешно;
- `1014 passed, 72 warnings` за 828,99 с; lint `0 errors / 1 existing warning`;
- production build 1,35 с, origin isolation `200/200/403/403`, итоговый
  `VERIFY_OK` CI за 876,47 с; job завершился за 15 мин 53 с при новом bounded
  timeout 30 минут.

### Checkpoint B3c — identity/auth schema prepare и finalize

Реализовано и развёрнуто 2026-07-13:

- `schema_groups.py` получил `prepare_identity_schema_group()` до media group и
  `finalize_identity_schema_group()` после challenge seed; оба вызова стоят в
  прежних точках `init_db()`, поэтому execution order не переставлен;
- prepare владеет additive `internal_user_id`, идемпотентным `seed_editorial`,
  `IDENTITY_SCHEMA_SQL` и `auth_sessions.refresh_expires_at`;
- legacy `backfill_identity_core()` физически перенесён из `main.py` в database
  boundary без изменения UUID/provider semantics, duplicate Telegram/MAX fail-fast
  и запрета угадывать web/email identities;
- finalize выполняет backfill, затем прежние unique partial indexes canonical/public
  IDs и public-code assignment через injected callback; database module не импортирует
  provider/application logic;
- compatibility import `main.backfill_identity_core` сохранён на период
  декомпозиции, хотя runtime wiring использует finalize group;
- `main.py` уменьшен с 15 238 до 15 156 строк; `schema_groups.py` остаётся
  ограниченным модулем на 172 строки.

Доказательства:

- до переноса существующий identity/password characterization suite:
  `26 passed, 2 warnings`; после переноса тот же suite дал тот же результат;
- новый standalone unit-contract без `main.init_db()` дважды выполняет prepare и
  finalize, проверяя одну legacy Telegram identity, canonical/public IDs,
  refresh column, editorial seed и unique indexes; расширенный database/identity/
  password suite: `46 passed`;
- focused database/identity/password/session/auth/lifecycle/trusted-user/security/
  bootstrap suite: `154 passed, 3 warnings` пять последовательных циклов по
  77–80 с;
- локальный Full: `1015 passed, 72 warnings` за 300,66 с; frontend lint
  `0 errors / 1 existing warning`, build успешен за 0,605 с, origin
  `200/200/403/403`;
- verifier: 123 Python-файла, source стабилен — 116 файлов / 1 576 580 байт /
  `2D5E93221F75C4A01960EB43E9CCBEDBE94D8985D9B31A2B32CC77D397D1328B`,
  итоговый Full 327,38 с; generated map `608 symbols / 166 routes`;
- pre/post restart identity schema fingerprint полностью совпал: 85 objects,
  SHA-256 `356720a52f6c04e4a392d6f0d73140713697d9b7e82b9c8e72a13fb98eb10174`;
  SQLite `quick_check=ok`, `user_version=1`, ledger rows `1`;
- непосредственно до/после restart без изменений: users `33`, identities `27`,
  sessions `1201`, passwords `19`, feed publications `69`, token ledger `1376`;
  missing internal/public IDs `0/0`, duplicate canonical IDs `0`;
- отдельный новый backup не нужен: SQL/data behavior не менялись, migration version
  не повышалась, проверенный pre-B3a snapshot сохранён;
- deploy штатным launcher: backend PID 36836, frontend PID 46904, по одному
  loopback listener; startup source `checked=117 / available=116 / missing=1 /
  changed=0`;
- health/DB Guard, auth capabilities, models, feed, frontend root/version HTTP 200,
  anonymous me-v2 HTTP 401; MAX остался в polling, `/me` и poll 200 без ошибки;
- secrets, provider modes, paid generation, production data, VPS и tunnel не
  изменялись.

Exact-head CI после B3c:

- GitHub Actions run `29265857059` на SHA `0f8f68b` завершён успешно за 16 мин 08 с;
- `1015 passed, 72 warnings` за 847,08 с; lint `0 errors / 1 existing warning`;
- production build 1,43 с, origin isolation `200/200/403/403`, итоговый
  `VERIFY_OK` CI за 899,86 с.

### Checkpoint B3d — core/billing schema и default seeds

Реализовано и развёрнуто 2026-07-13:

- `prepare_core_schema_group()` владеет прежним `BASE_SCHEMA_SQL`, включая
  billing tables, и ранними additive user/image columns; он выполняется до
  вычисления общего startup timestamp, как и прежний inline-код;
- `seed_core_defaults()` после timestamp идемпотентно создаёт demo admin, legacy
  local profile, canonical FLUX 4B/9B profiles с прежним settings JSON и три
  system presets;
- `seed_default_challenge()` остаётся после identity/media schema, поэтому таблица
  `challenges` уже существует, а порядок относительно identity finalize сохранён;
- один больше не используемый `add_missing_columns` import удалён из `main.py`;
  helper остаётся публичным в `app.database` и используется schema groups/tests;
- `main.py` уменьшен с 15 156 до 15 063 строк; `schema_groups.py` ровно 293 строки,
  внутри установленной цели 100–300;
- финальный source audit не нашёл в `main.py` ни `CREATE/ALTER/DROP`, ни
  `executescript`; `init_db()` теперь только 21-строчная orchestration ledger →
  core → identity/media → baseline. Поэтому B3 закрыт полностью;
- repository layer и SQLite lock/busy telemetry не объявлены готовыми: это
  отдельные BE/DATA задачи после schema extraction.

Доказательства:

- characterization на старом inline-коде и после переноса проверяет точные demo,
  model settings/pose flags, presets и challenge dates/reward; оба прогона зелёные;
- standalone core contract дважды применяет BASE/additive/seeds и подтверждает
  billing tables, seed counts и неизменный first-created timestamp;
- database/billing/feed suite: `76 passed`; focused database/billing/promo/referral/
  account/product/feed/API suite: `170 passed, 2 warnings` пять последовательных
  циклов по 116–123 с;
- локальный Full: `1017 passed, 72 warnings` за 307,35 с; frontend lint
  `0 errors / 1 existing warning`, build успешен за 0,538 с, origin
  `200/200/403/403`;
- verifier: 123 Python-файла, source стабилен — 116 файлов / 1 576 580 байт /
  `2D5E93221F75C4A01960EB43E9CCBEDBE94D8985D9B31A2B32CC77D397D1328B`,
  итоговый Full 334,70 с; generated map `608 symbols / 166 routes`;
- pre/post restart application schema полностью совпала: 116 objects, SHA-256
  `d9839afcbff72749e85133fc7cce29dd1bf4a865668a8863d2e6a6f7b9bb2925`;
  seed-row SHA-256 также совпал:
  `4e36c556582613e5e058e58673201a9e35fe64dc092db1902bded8a7f32234aa`;
- SQLite `quick_check=ok`, `user_version=1`, ledger rows `1`; непосредственно
  до/после restart без изменений: users `33`, jobs `681`, images `962`, token
  ledger `1376`, billing packages/invoices/payments/refunds `0/0/0/0`, referral
  rewards `1`, model profiles/presets/challenges `3/3/1`;
- отдельный новый backup не нужен: SQL/data behavior не менялись, migration version
  не повышалась, проверенный pre-B3a snapshot сохранён;
- deploy штатным launcher: backend PID 49476, frontend PID 55520; health/DB Guard,
  auth capabilities, models, tariffs, feed, frontend root/version HTTP 200, private
  gallery HTTP 401; source `checked=117 / available=116 / missing=1 / changed=0`;
- MAX остался в polling, `/me` и poll 200 без ошибки; secrets, provider modes,
  paid generation, production data, VPS и tunnel не изменялись.

Exact CI после B3d:

- GitHub Actions run `29268631383` на SHA `59ba837` завершён успешно за 16 мин 39 с;
- `1017 passed, 72 warnings` за 860,80 с; lint `0 errors / 1 existing warning`;
- production build 1,59 с, origin isolation `200/200/403/403`, итоговый
  `VERIFY_OK` CI за 920,72 с.

### Checkpoint B4a — Telegram HTTP client, typed errors и health

Реализовано и развёрнуто 2026-07-13:

- новый import-safe `app/integrations/telegram.py` владеет одним POST transport к
  Telegram Bot API, 30-секундным legacy timeout default, проверкой HTTP 2xx и
  строгого верхнеуровневого `{ok: bool}` envelope;
- configuration, transport, invalid response и `ok=false` представлены отдельными
  типами ошибок. Их сообщения не содержат bot token, request URL или сырые network
  details; HTTP/API status и `retry_after` доступны polling-коду как typed fields;
- `probe_telegram_bot()` выполняет read-only `getMe` и возвращает только configured,
  `ok`, нормализованный status, bot id/username, status code и имя типа ошибки;
  provider description и token в health payload не попадают;
- официальный file URL вынесен в `telegram_file_url()` и используется avatar cache;
- `main.telegram_api()` сохранён как compatibility boundary: прежние HTTP 400 для
  отсутствующего token и HTTP 502 с прежним API-error detail не изменены; существующие
  monkeypatch callers, polling/update handlers и routes не переносились;
- generic polling helpers теперь понимают typed `status_code` и `retry_after`, сохраняя
  прежний fallback через `httpx.Response` для MAX;
- `main.py` временно вырос с 15 063 до 15 080 строк из-за явных compatibility imports
  и typed polling wiring. Это не объявляется уменьшением монолита: удаление Telegram
  handler/orchestration blocks является отдельным B4b;
- новый модуль — 230 строк, новый contract test module — 279 строк; generated map
  остаётся `608 symbols / 166 routes`.

Доказательства:

- characterization до переноса: `3 passed`; после переноса module contract:
  `18 passed`, включая body/path, missing token, HTTP 401, API 429/retry-after,
  connection redaction, malformed JSON/envelope, health и file URL;
- Telegram API/polling/webhook/login/avatar focused suite: `130 passed, 2 warnings`
  пять последовательных циклов по 59–61 с;
- первый Full был внешне завершён на 13% с process exit `-1`, без failed assertion и
  Python traceback; сразу после этого также исчез production backend PID 49476.
  Verifier корректно заблокировал следующий запуск на preflight (`0` listeners);
- live backend восстановлен с теми же production launcher env/bind/proxy settings как
  единственный listener PID 21084, DB Guard и migration status `ok`. Повторный Full
  полностью успешен и backend пережил его; отсутствие supervisor остаётся известным
  OPS-риском и не маскируется как исправленное;
- повторный локальный Full: `1035 passed, 72 warnings` за 297,19 с; frontend lint
  `0 errors / 1 existing warning`, build 1,23 с, origin `200/200/403/403`, итоговый
  `VERIFY_OK` за 330,31 с;
- production SQLite/media schema и migration version этим пакетом не изменяются;
  новый backup не требуется;
- после gate выполнен штатный controlled backend-only restart: PID `21084 → 53064`,
  один listener на `127.0.0.1:8000`, proxy headers disabled, health/DB Guard/migration
  status `200/ok/ok`; frontend остался PID 55520;
- live HTTP smoke: health/version/models/tariffs/feed/bot status/frontend
  `200`, private gallery `401`, polling-mode Telegram webhook POST `404`, frontend
  host isolation `200/200/403/403`;
- новый read-only Telegram `getMe` health probe вернул configured/ok/status
  `true/true/ok` без token; SQLite read-only `quick_check=ok`, `user_version=1`,
  migration rows `1`, users/jobs/images/token ledger `33/681/962/1376`;
- secrets, Telegram/MAX update modes, paid generation, VPS и tunnel не изменялись.

Exact CI после B4a:

- GitHub Actions run `29271478789`, job `86889984725`, на SHA `c6f4aa8`
  завершён успешно за 13 мин 09 с;
- `1035 passed, 72 warnings` за 665,74 с; lint `0 errors / 1 existing warning`;
- production build 1,40 с, origin isolation `200/200/403/403`, итоговый
  `VERIFY_OK` CI за 719,80 с.

### Checkpoint B4b — Telegram update handlers service

Реализовано и развёрнуто 2026-07-13:

- новый import-safe `app/services/telegram_updates.py` владеет parsing Telegram
  message/callback user/text/chat/callback id, mapping inline buttons и approve,
  command, callback-answer, batch handling;
- `TelegramUpdateRuntime` явно инъецирует Bot API call, login-token parser, challenge
  approval, avatar scheduling, command response и sanitized callback-error reporter;
  service не импортирует FastAPI, SQLite, env, provider token или `main.py`;
- последовательность старого поведения сохранена: approve → avatar schedule →
  callback answer → chat message; command сначала отправляет сообщение, затем пытается
  закрыть callback; ошибка callback answer подавляется и логируется по имени типа,
  а ошибка основного sendMessage по-прежнему распространяется;
- `main.telegram_answer_payload`, `telegram_message_from_update` и
  `telegram_user_from_update` сохранены как импортированные compatibility symbols;
  `main.handle_telegram_update(s)` — тонкие runtime-wiring wrappers;
- polling cursor/worker, webhook replay/security, FastAPI routes, bot-login persistence,
  command policy и delivery modes не переносились и не менялись;
- `main.py` уменьшен с 15 080 до 15 035 строк (−45); новый service — 114 строк,
  его direct test module — 261 строк; generated map `606 symbols / 166 routes`.

Доказательства:

- существующая API/login/avatar/webhook characterization после extraction:
  `89 passed, 2 warnings`; новый direct service contract: `8 passed`;
- direct contracts проверяют message/callback precedence, user parsing, callback/
  web-app/URL buttons, approve/reject call order, avatar condition, callback error
  boundary, send error propagation и ordered batch filtering;
- полный Telegram client/service/API/polling/webhook/login/avatar focused suite:
  `138 passed, 2 warnings` пять последовательных циклов по 56–59 с;
- локальный Full: `1043 passed, 72 warnings`; lint `0 errors / 1 existing warning`,
  build 0,483 с, origin `200/200/403/403`, итоговый `VERIFY_OK` за 320,13 с;
  128 Python-файлов, source стабилен: 116 файлов / 1 576 580 байт /
  `2D5E93221F75C4A01960EB43E9CCBEDBE94D8985D9B31A2B32CC77D397D1328B`;
- controlled backend-only restart: PID `53064 → 30560`, один listener
  `127.0.0.1:8000`, proxy headers disabled, health/DB Guard/migration `200/ok/ok`;
  frontend остался PID 55520;
- live HTTP: health/models/feed/bot status/local Telegram `/help`/`/settings` и
  frontend `200`, private gallery `401`, polling-mode webhook POST `404`, host
  isolation `200/200/403/403`; mode/ready/token configured `polling/true/true`;
- read-only service smoke обработал `/help`, проигнорировал plain text и не отправлял
  provider reply; read-only real Telegram `getMe` health `configured/ok/status =
  true/true/ok`;
- startup source availability `checked=117 / available=116 / missing=1 / changed=0`;
  MAX `/me` и polling status `200`, Telegram/MAX остаются в polling;
- SQLite `quick_check=ok`, `user_version=1`, migrations `1`, users/jobs/images/token
  ledger `33/681/962/1376`; schema/data migration не выполнялась, новый backup не
  требуется; secrets, paid generation, VPS и tunnel не изменялись.

Exact CI после B5a:

- GitHub Actions run `29276052820`, job `86905247874`, на SHA `1841cf5`
  завершён успешно за 16 мин 41 с;
- `1062 passed, 72 warnings` за 864,91 с; lint `0 errors / 1 existing warning`;
- production build 1,37 с, origin isolation `200/200/403/403`, итоговый
  `VERIFY_OK` CI за 918,30 с.

### Checkpoint B5b — MAX update handlers service

Реализовано и развёрнуто 2026-07-13:

- новый import-safe `app/services/max_updates.py` владеет update type/payload-prefix,
  message/callback extraction, real MAX user/profile normalization, login payload,
  recipient priority, inline keyboard и approve/login/command/batch handling;
- `MaxUpdateRuntime` инъецирует API, token parser, challenge approval, avatar,
  command policy, UTC clock, diagnostic writer и log sink; service не импортирует
  FastAPI, SQLite, env, provider token или `main.py`;
- старые diagnostic timestamps и безопасные логи сохранены; login/approve payload
  выводится только нормализованным prefix, исходный token не логируется;
- все pure helpers доступны как compatibility symbols через `main`; wrappers
  `handle_max_update(s)` только создают runtime и делегируют;
- polling cursor/worker, webhook security/replay, subscription lifecycle, routes и
  delivery modes не переносились и не менялись;
- `main.py` уменьшен с 15 045 до 14 884 строк (−161); service 223 строки, direct
  tests 154 строки; generated map уменьшен `606 → 598 symbols`, routes `166`.

Доказательства:

- существующая API/login/webhook/avatar characterization: `85 passed`; direct service
  contracts: `6 passed`; полный MAX client/service suite `119 passed, 2 warnings`
  пять последовательных циклов примерно по 53 с;
- contracts покрывают real bot_started/callback/message shapes, avatar/language
  normalization, chat-over-user recipient priority, sanitized prefix, approve API/
  avatar/diag order, confirmation button и ordered batch filtering;
- локальный Full: `1068 passed, 72 warnings`; lint `0 errors / 1 existing warning`,
  build 0,479 с, origin `200/200/403/403`, итоговый `VERIFY_OK` за 337,05 с;
  132 Python-файла, source стабилен: 116 файлов / 1 576 580 байт /
  `2D5E93221F75C4A01960EB43E9CCBEDBE94D8985D9B31A2B32CC77D397D1328B`;
- controlled backend-only restart: PID `28304 → 35644`, один listener
  `127.0.0.1:8000`, proxy headers disabled; frontend PID 55520;
- live MAX client/service: `/me=200`, polling updates `200`, error `null`, mode/ready
  `polling/true`; read-only handler обработал `/help`, выбрал user recipient и
  проигнорировал plain text без отправки provider reply;
- schema/data migration не выполнялась, новый backup не требуется; secrets, paid
  generation, VPS и tunnel не изменялись.

Exact CI после B4b:

- GitHub Actions run `29273695204`, job `86897382294`, на SHA `1a678e1`
  завершён успешно за 15 мин 25 с;
- `1043 passed, 72 warnings` за 796,36 с; lint `0 errors / 1 existing warning`;
- production build 2,24 с, origin isolation `200/200/403/403`, итоговый
  `VERIFY_OK` CI за 852,32 с.

Exact CI после B5b:

- GitHub Actions run `29278442114`, job `86913334959`, на SHA `18266eb`
  завершён успешно за 17 мин 35 с;
- `1068 passed, 72 warnings` за 928,89 с; lint `0 errors / 1 existing warning`;
- production build 1,39 с, origin isolation `200/200/403/403`, итоговый
  `VERIFY_OK` CI за 975,33 с.

### Checkpoint B5a — MAX HTTP client, typed errors и health

Реализовано и развёрнуто 2026-07-13:

- новый import-safe `app/integrations/max_client.py` владеет async MAX API transport
  и синхронным startup `/me`, используемым для deep-link discovery;
- legacy contract сохранён: Authorization/JSON headers, base URL + path, body/query,
  30-секундный async timeout, 10-секундный sync timeout и один и тот же
  `MAX_HTTP_VERIFY` native-system trust context;
- configuration, transport/HTTP и invalid JSON/non-object response представлены
  typed errors. Их messages не содержат token, URL, provider response body или сырые
  network details; status/retry-after доступны polling и diagnostics;
- `probe_max_bot()` делает read-only `/me` с 5-секундным default timeout и возвращает
  только configured/ok/status/status_code/error_type, без полей provider payload;
- `main.max_api()` сохранён как compatibility wrapper с прежним HTTP 400/detail при
  пустом token; polling helpers уже понимают typed status/retry-after;
- `resolve_max_bot_deep_link_base()` использует общий sync client и сохраняет прежний
  HTTP status в cache/log даже при typed error; token по-прежнему не логируется;
- polling cursor/worker, MAX handlers, webhook/subscription lifecycle, routes,
  operator `tools/probe_max_api.py` и delivery modes не переносились и не менялись;
- `main.py` временно вырос с 15 035 до 15 045 строк (+10) из-за imports/wiring/status
  compatibility. Это не объявляется уменьшением: MAX handlers будут отдельным B5b;
  client — 254 строки, direct contract tests — 300 строк; map `606/166`.

Доказательства:

- первые characterization tests выявили два старых FakeResponse без `status_code`;
  parser сохранил прежний `raise_for_status()` fallback только для таких doubles,
  реальные `httpx.Response` проходят строгий 2xx check;
- direct MAX client contract: `19 passed`; расширенная MAX API/TLS/deep-link/polling/
  webhook/login/avatar/operator-probe suite: `113 passed, 2 warnings` пять
  последовательных циклов примерно по 52–53 с;
- contracts проверяют exact headers/body/query/path, sync/async transport, missing
  configuration, HTTP 401/403/429/retry-after, connection redaction, invalid JSON/
  object, sanitized health, system verify passthrough и deep-link cached status;
- локальный Full: `1062 passed, 72 warnings`; lint `0 errors / 1 existing warning`,
  build 0,517 с, origin `200/200/403/403`, итоговый `VERIFY_OK` за 314,75 с;
  130 Python-файлов, source стабилен: 116 файлов / 1 576 580 байт /
  `2D5E93221F75C4A01960EB43E9CCBEDBE94D8985D9B31A2B32CC77D397D1328B`;
- controlled backend-only restart: PID `30560 → 28304`, один listener
  `127.0.0.1:8000`, proxy headers disabled; frontend остался PID 55520;
- live MAX: response-body-free `/me` health `configured/ok/status=true/true/ok`,
  status `200`, trust store `system`; startup `/me=200`, polling updates `200`,
  `lastUpdatesError=null`, mode/ready `polling/true`;
- live HTTP: health/models/feed/bot status/local MAX `/help` и frontend `200`,
  admin MAX `/me` без session `401`, polling-mode webhook POST `404`, private
  gallery `401`, host isolation `200/200/403/403`;
- SQLite `quick_check=ok`, `user_version=1`, migrations `1`, users/jobs/images/token
  ledger `33/681/962/1376`; schema/data migration не выполнялась, новый backup не
  требуется; secrets, paid generation, VPS и tunnel не изменялись.

### Checkpoint B6a — ComfyUI HTTP client boundary

Реализовано и развёрнуто 2026-07-13:

- новый import-safe `app/integrations/comfyui_client.py` владеет HTTP-вызовами
  `/object_info`, Flux Klein models/config/bgremoval/LoRA/workflow endpoints,
  `/upload/image`, `/prompt`, `/history`, `/view`, `/interrupt` и `/free`;
- сохранены прежние endpoint payloads и таймауты: availability/node discovery
  `4/8`, catalog/config `10`, workflow/history `20`, submit `30`, upload `60`, image
  download `120`, interrupt `5` и free `10` секунд;
- availability и node discovery сохраняют non-raising degraded contract, interrupt
  сохраняет прежнее отсутствие `raise_for_status`; остальные HTTP failures по-прежнему
  доходят до application error policy;
- `ComfyUIHistoryClient` держит один reusable `httpx.AsyncClient`/connection pool на
  весь polling одной генерации; application deadline, cancel-before-network,
  progress и двухсекундный interval остаются в `main.wait_for_history()`;
- `main.py` сохраняет прежние compatibility function names, mode-to-workflow mapping,
  workflow patch/build logic, submit response validation, image persistence,
  generation fallback и job orchestration;
- прямых ComfyUI URL/`AsyncClient` вызовов в `main.py` больше нет; файл уменьшен с
  14 884 до 14 848 строк (−36), client имеет 293 строки, direct tests — 231 строку,
  wiring tests — 67 строк; generated map остаётся `598 symbols / 166 routes`.

Доказательства:

- исходный ComfyUI/Admin baseline до переноса: `59 passed`; direct client + wiring
  contracts: `11 passed`; расширенный ComfyUI/API/Admin suite: `117 passed,
  10 warnings` пять последовательных циклов за `64,64 / 65,04 / 65,23 / 65,90 /
  63,36` с;
- contracts проверяют exact URL/query/JSON/multipart, все прежние timeout values,
  missing/unavailable node behavior, HTTP failure propagation, legacy non-raising
  interrupt, binary download, memory-free payload, reusable history client и
  cancel-before-network;
- локальный Full: `1079 passed, 72 warnings` за 285,85 с; lint `0 errors / 1 existing
  warning`, build 0,466 с, origin `200/200/403/403`, итоговый `VERIFY_OK` за 311,39 с;
  135 Python-файлов, source стабилен: 116 файлов / 1 576 580 байт /
  `2D5E93221F75C4A01960EB43E9CCBEDBE94D8985D9B31A2B32CC77D397D1328B`;
- controlled backend-only restart: PID `35644 → 13016`, один listener
  `127.0.0.1:8000`, proxy headers disabled; frontend остался PID 55520;
- live HTTP: health/models/Flux config/bgremoval/feed/bot status/frontend и real
  LoRA triggers `200`, private media `401`, polling-mode Telegram webhook `404`;
  read-only real client получил workflow `dict/10 nodes` и пустую history для
  отсутствующего prompt; ComfyUI object/models доступны;
- SQLite `quick_check=ok`, `user_version=1`, migrations `1`, users/jobs/images/token
  ledger `33/681/962/1376`; schema/data migration, backup, secrets, paid generation,
  VPS и tunnel не изменялись;
- pre-restart audit нашёл одну stale production row `sent_to_comfyui/progress=24`
  возрастом около восьми часов при пустых ComfyUI running/pending queues. Строка не
  изменялась; обязательное startup reconciliation добавлено в scope B7.

Exact CI после B6a:

- GitHub Actions run `29281320422`, job `86922955651`, на SHA `2ac0a04`
  завершён успешно за 20 мин 42 с;
- `1079 passed, 72 warnings` за 1120,35 с; lint `0 errors / 1 existing warning`;
- production build 1,38 с, origin isolation `200/200/403/403`, итоговый
  `VERIFY_OK` CI за 1168,68 с.

### Checkpoint B6b — ComfyUI workflow builders

Реализовано и развёрнуто 2026-07-13:

- новый pure `app/services/comfyui_workflows.py` владеет mode-to-workflow endpoint
  policy, safe existing-node input patch, shared Flux nodes, negative/sampler/denoise
  policy, optional/existing/dynamic LoRA loader, multi-reference conditioning chain,
  mode-specific image-to-image/remove-background/inpaint/outpaint nodes, pose graph и
  installed 4B outpaint graph;
- service принимает structural request protocol, sampler profiles и `lora_enabled`
  callback; он не импортирует `main`, FastAPI, Pydantic, SQLite, HTTPX, environment или
  filesystem paths и не выполняет network/filesystem/database side effects;
- bundled pose template loading, DB-backed model/profile/LoRA selection, admin settings,
  request HTTP validation и all generation/result orchestration остаются в `main.py`;
- старые публичные имена `build_pose_workflow`, `build_outpaint_workflow`,
  `fetch_workflow`, `set_input`, `patch_shared_flux_nodes`, `patch_optional_lora`,
  `patch_edit_reference_chain` и `patch_mode_nodes` сохранены как compatibility wrappers;
- `main.py` уменьшен с 14 848 до 14 716 строк (−132); service имеет 260 строк,
  direct tests — 288 строк; generated map `598 → 597 symbols`, routes `166`.

Доказательства:

- исходный workflow/API baseline до переноса: `75 passed`; direct pure builder
  contracts: `15 passed`; расширенный B6 client/workflow/API/Admin suite:
  `132 passed, 10 warnings` пять последовательных циклов за `67,38 / 66,75 / 63,80 /
  64,16 / 63,89` с;
- contracts покрывают все mode mappings/default, missing-node no-op, exact model/clip/
  VAE/prompt/negative/size/seed/steps/cfg/denoise/sampler/scheduler/prefix values,
  existing/dynamic LoRA, one/four reference chains, inpaint/outpaint, pose и missing/
  disabled outpaint dependency failures;
- локальный Full: `1094 passed, 72 warnings` за 307,33 с; lint `0 errors / 1 existing
  warning`, build 0,538 с, origin `200/200/403/403`, итоговый `VERIFY_OK` за 336,92 с;
  137 Python-файлов, source стабилен: 116 файлов / 1 576 580 байт /
  `2D5E93221F75C4A01960EB43E9CCBEDBE94D8985D9B31A2B32CC77D397D1328B`;
- controlled backend-only restart: PID `13016 → 48632`, один listener
  `127.0.0.1:8000`, proxy headers disabled; frontend остался PID 55520;
- live HTTP: health/models/Flux config/bgremoval/feed/bot status/frontend `200`,
  private media `401`, polling-mode Telegram webhook `404`; read-only real graph smoke
  успешно patched `t2i 10 nodes`, `edit 16 nodes/denoise=1` и outpaint `13 nodes` с
  удалённым KV cache и добавленным LoRA loader, без upload/submit/interrupt/free;
- во время restart ComfyUI выполнял отдельный prompt с client id без
  `onenode-backend-*`; после backend-only restart тот же prompt продолжил выполняться,
  то есть ComfyUI не останавливался и `/interrupt` не вызывался;
- schema/data migration, production DB/media, backup, secrets, paid generation, VPS и
  tunnel не изменялись; ранее найденная stale job row остаётся отдельным scope B7.

Exact CI после B6b:

- GitHub Actions run `29284297234`, job `86932930187`, на SHA `66cbb3e`
  завершён успешно за 14 мин 09 с;
- `1094 passed, 72 warnings` за 712,83 с; lint `0 errors / 1 existing warning`;
- production build 1,71 с, origin isolation `200/200/403/403`, итоговый
  `VERIFY_OK` CI за 762,03 с.

### Checkpoint B6c — ComfyUI result/media adapter

Реализовано и развёрнуто 2026-07-14:

- новый import-safe `app/services/comfyui_results.py` владеет `ComfyUIResult`,
  точной проверкой ответа `/prompt`, нормализацией image descriptors из history и
  преобразованием скачанных bytes в PIL image с injected callbacks сохранения
  оригинала и thumbnail;
- точный прежний приоритет ошибок сохранён: provider `error`, затем Unicode-safe
  `node_errors`, затем обязательный непустой `prompt_id`; тексты RuntimeError не
  изменены;
- порядок outputs/images, default `subfolder=""`/`type="output"`, пропуск элементов
  без filename и prefix `{job_id}_comfyui` сохранены characterization tests;
- service не импортирует `main`, FastAPI, Pydantic, SQLite, HTTPX, environment или
  application storage roots; HTTP download остаётся в B6a client, а storage policy,
  callbacks, history polling, cancellation/progress, fallback, job lifecycle и gallery
  ownership остаются в `main.py` до B7/B8;
- прежние `submit_workflow`, `extract_images_from_history` и
  `download_comfyui_image` сохранены как compatibility wiring; оплачиваемая или
  пользовательская генерация для deploy-smoke не создавалась;
- `main.py` уменьшен с 14 716 до 14 696 строк (−20); service имеет 61 строку,
  direct tests — 128 строк, wiring tests — 64 строки; generated map
  `597 → 596 symbols`, routes остаются `166`.

Доказательства:

- characterization до переноса: `4 passed`; direct result + wiring contracts после
  переноса: `14 passed`; расширенный B6/API/Admin suite: `146 passed, 10 warnings`
  пять последовательных циклов за `66,45 / 65,16 / 66,97 / 62,87 / 67,03` с;
- локальный Full: `1108 passed, 72 warnings` за 291,53 с; lint
  `0 errors / 1 existing warning`, production build 0,505 с, origin
  `200/200/403/403`, итоговый `VERIFY_OK` за 318,53 с; 140 Python-файлов;
- live source-media snapshot до/после Full стабилен: 116 файлов / 1 576 580 байт /
  SHA-256 `2D5E93221F75C4A01960EB43E9CCBEDBE94D8985D9B31A2B32CC77D397D1328B`;
- pre-restart read-only audit: ComfyUI running/pending queues пусты; единственная
  строка `job_20260713_144446_cafd73` остаётся stale в
  `sent_to_comfyui/progress=24`, не изменялась и подтверждает обязательный B7 startup
  reconciliation;
- controlled backend-only restart: PID `41648 → 45088`, один listener
  `127.0.0.1:8000`, proxy headers disabled; frontend остался PID 55520, ComfyUI не
  останавливался;
- live smoke 5/5: health/models/Flux config/bgremoval/feed/bot status/frontend `200`,
  private media без session `401`, polling-mode Telegram webhook `404`; затем PID
  `45088` и health `200` подтверждены 7/7 samples за 67 секунд;
- до этого PID 48632 завершился внешне без Uvicorn shutdown и без Python traceback;
  backend был восстановлен на PID 41648 и стабилен до controlled restart. Вместе с
  аналогичным B4a инцидентом это второй практический случай, поэтому OPS-04 supervisor
  остаётся открытым критическим operations-пакетом, а не считается application crash;
- schema/data migration, backup, secrets, paid generation, VPS и tunnel пакетом не
  изменялись; тесты не обращались к production DB/media, а live smoke был read-only.

Exact CI после B6c:

- GitHub Actions run `29286748620`, job `86941024277`, на SHA `03df252`
  завершён успешно за 19 мин 22 с;
- `1108 passed, 72 warnings` за 1021,60 с; lint `0 errors / 1 existing warning`;
- production build 1,59 с, origin isolation `200/200/403/403`, итоговый
  `VERIFY_OK` CI за 1079,82 с.

### Checkpoint B7a — startup reconciliation orphaned generation jobs

Реализовано и развёрнуто 2026-07-14:

- новый import-safe `app/services/generation_recovery.py` задаёт явный active-state
  contract: `queued`, `running`, `uploading`, `sent_to_comfyui` и
  `sent_to_openrouter` после нового startup не могут принадлежать живому worker
  предыдущего процесса;
- reconciliation выполняется одной транзакцией после DB Guard/migrations и до
  `load_db_state()`: active job с уже сохранённой active image восстанавливается как
  `completed`, остальные становятся `failed/progress=100` с понятным сообщением и
  `completed_at`;
- refund не реализован повторно: service получает существующий
  `refund_generation_tokens` как dependency, поэтому balance/daily/monthly paths и
  ledger idempotency сохраняются; повторный reconciliation terminal rows не меняет;
- refund exception намеренно откатывает всю транзакцию, чтобы startup не фиксировал
  job failure без согласованного финансового результата;
- service принимает structural connection/refund protocols и не импортирует `main`,
  FastAPI, HTTPX или environment. Он имеет 116 строк; direct tests — 175 строк,
  wiring tests — 59 строк;
- `main.py` временно вырос с 14 696 до 14 712 строк (+16) из-за явного startup
  adapter и импорта; это не объявляется сокращением монолита — job persistence и
  response mapping переносятся в B7b, worker orchestration в следующих B7 пакетах;
  generated map `596 → 597 symbols`, routes остаются `166`.

Доказательства:

- characterization до реализации остановился на отсутствующем recovery module;
  direct/wiring contracts после реализации: `8 passed`;
- расширенный recovery/generation/billing/database/startup/API suite:
  `122 passed, 20 warnings` пять последовательных циклов за
  `57,53 / 58,41 / 58,70 / 57,71 / 57,25` с;
- первый Full корректно нашёл несоответствие старого ownership test: он искусственно
  возвращал в `queued` уже завершённую job с сохранённой image, поэтому новая recovery
  обоснованно восстанавливала `completed`; результат `1115 passed / 1 failed` не
  засчитан как успешный gate;
- cancellation test уточнён без ослабления ownership: отдельная queued job создаётся
  уже после startup как работа текущего процесса. Recovery+ownership suite после
  исправления прошёл `39 passed` пять раз за
  `11,87 / 12,07 / 11,72 / 11,72 / 11,94` с;
- повторный локальный Full: `1116 passed, 72 warnings` за 289,32 с; lint
  `0 errors / 1 existing warning`, production build 0,474 с, origin
  `200/200/403/403`, итоговый `VERIFY_OK` за 314,53 с; 143 Python-файла;
- source-media snapshot внутри успешного Full стабилен: 115 файлов / 1 534 310 байт /
  SHA-256 `D5C642413D984AD5E4232FE8B650B9C9F6BE18D283D673010134B57E37F41D6F`;
  изменение 116→115 между двумя длинными Full зафиксировано как параллельная live
  активность, а не скрыто как test mutation;
- перед production mutation создан snapshot `20260713T221737.032822Z`: SQLite
  565 104 640 байт, 2394 media / 244 742 470 байт, 9 copied / 2385 reused objects;
  независимые `BACKUP_VERIFY_OK` и `BACKUP_REHEARSAL_OK` успешны;
- pre-restart audit подтвердил одну orphaned job
  `job_20260713_144446_cafd73` в `sent_to_comfyui/progress=24`, active images 0,
  исходный ledger `daily_generation`, refund 0; ComfyUI running/pending queues пусты;
- controlled backend-only restart: PID `45088 → 484`, один listener
  `127.0.0.1:8000`, proxy headers disabled; startup report ровно
  `checked=1/completed_from_images=0/failed=1/refunds_created=1`;
- post-deploy read-only audit: job стала `failed/progress=100`, создан ровно один
  `daily_generation_refund` с `startup_reconciliation`, active jobs 0; live smoke
  5/5 дал health/models/Flux/feed/bots/frontend `200`, private media `401`, Telegram
  webhook `404`, затем PID 484/health 200 подтверждены 7/7 samples за 67 секунд;
- pytest-процессов после gate 0; schema migration, secrets, paid generation, VPS и
  tunnel не изменялись. Единственная production DB mutation является заявленным и
  проверенным исправлением orphaned job/refund поверх pre-deploy backup.

Exact CI после B7a:

- GitHub Actions run `29289893003`, job `86950921063`, на SHA `4986667`
  завершён успешно за 12 мин 28 с;
- `1116 passed, 72 warnings` за 647,20 с; lint `0 errors / 1 existing warning`;
- production build 0,984 с, origin isolation `200/200/403/403`, итоговый
  `VERIFY_OK` CI за 683,92 с.

### Checkpoint B7b — generation job persistence/response boundary

Реализовано и развёрнуто 2026-07-14:

- новый import-safe `app/services/generation_jobs.py` владеет legacy-compatible
  UPSERT строки job, owner-scoped persisted job/image lookup и преобразованием
  SQLite row в API response;
- точные прежние правила сохранены: active image только при `deleted_at IS NULL`,
  сначала `result_image_id`, затем latest active image того же job/owner; чужой owner
  получает `None`, deleted result не используется;
- response сохраняет fallback result URL/size из settings, image overrides,
  `Готово`/error message, dict-only OpenRouter billing, display-name adapter и
  generation time из image settings;
- UPSERT сохраняет прежний whitelist settings и намеренно обновляет только
  status/progress/result/error/settings/completed_at. Owner/mode/provider/prompt/
  created_at/started_at при conflict остаются исходными; этот неочевидный contract
  зафиксирован до переноса;
- service получает structural connection и model-display callback, не импортирует
  `main`, FastAPI, Pydantic, HTTPX или environment. Pydantic `model_dump`, connection
  ownership и прежние function names остаются тонкими wrappers в `main.py`;
- worker, in-memory queue, provider calls, billing и gallery/result orchestration не
  переносились. `main.py` уменьшен с 14 712 до 14 654 строк (−58); service имеет
  165 строк, characterization tests — 163, direct tests — 199; generated map остаётся
  `597 symbols / 166 routes` из-за compatibility wrappers.

Доказательства:

- characterization старых функций до extraction: `3 passed`; после extraction
  direct + characterization contracts: `8 passed`;
- расширенный job/recovery/generation/ownership/billing/OpenRouter/API suite:
  `138 passed, 42 warnings` пять последовательных циклов за
  `70,85 / 67,77 / 69,89 / 66,88 / 66,29` с;
- локальный Full: `1124 passed, 72 warnings` за 290,06 с; lint
  `0 errors / 1 existing warning`, production build 2,12 с, origin
  `200/200/403/403`, итоговый `VERIFY_OK` за 325,63 с; 146 Python-файлов;
- source-media snapshot стабилен: 115 файлов / 1 534 310 байт / SHA-256
  `D5C642413D984AD5E4232FE8B650B9C9F6BE18D283D673010134B57E37F41D6F`;
- pre-restart SQLite active jobs — 0; controlled backend-only restart PID
  `484 → 46320`, один loopback listener, proxy headers disabled, DB Guard ready;
- live HTTP smoke 5/5: health/models/Flux config/bgremoval/feed/bots/frontend `200`,
  private media `401`, Telegram webhook `404`; real read-only latest completed job
  mapping дал `completed/progress=100`, result URL present, 18 response fields без
  вывода owner/prompt/URL;
- перед deploy отдельно обнаружено отсутствие ComfyUI listener. Параллельная локальная
  ComfyUI-работа запустила PID 16932, затем заменила его PID 54544. Мой запоздавший
  диагностический duplicate PID 17668 безопасно отказался на уже занятой DB/8188 и
  завершился; рабочий процесс не останавливался;
- фактический boot task называется `ComfyUI-AutoStart`, запускает текущий portable
  `run_nvidia_gpu.bat`, но имеет `RestartCount=0`, last result `3221225786` и не был
  источником наблюдавшегося restart. Это усиливает, а не закрывает OPS-04;
- финальный monitor после параллельного restart: backend PID 46320 и ComfyUI PID
  54544 стабильны 6/6 samples за 61 секунду, health/queue `200/200`, queue пуста;
- schema/data migration, backup, secrets, paid generation, VPS и tunnel пакетом B7b
  не изменялись; tests/live smoke не записывали production jobs/media.

Exact CI после B7b:

- GitHub Actions run `29291985656`, job `86957371006`, на SHA `48e9ba0`
  завершён успешно за 20 мин 9 с;
- `1124 passed, 72 warnings` за 1058,92 с; lint `0 errors / 1 existing warning`;
- production build 1,54 с, origin isolation `200/200/403/403`, итоговый
  `VERIFY_OK` CI за 1122,75 с.

### Checkpoint B7c — pure generation result/job-state builders

Реализовано и развёрнуто 2026-07-14:

- новый import-safe `app/services/generation_results.py` строит точную запись generated
  image и два terminal job state: `completed` и `failed`;
- image-record contract сохраняет прежние поля и правила: Unicode prompt не выдаётся
  за перевод, LoRA сохраняются как ID, ComfyUI prompt/history переносятся без
  преобразования, а фактические OpenRouter dimensions/metadata/billing/request
  используются только при наличии результата провайдера;
- terminal-state builders изменяют тот же job dict и сохраняют прежние message,
  progress, result/gallery quota и строковое представление ошибки. Не относящиеся к
  terminal transition поля намеренно не удаляются;
- builders используют только structural protocols/mappings и не импортируют `main`,
  FastAPI, Pydantic, SQLite, HTTPX, environment, filesystem или asyncio;
- worker по-прежнему владеет очередью, cancellation, provider calls, billing/refund,
  UUID/URL/time, DB/files, source graph, quota/eviction и persistence. Две
  дублированные completed-ветки сведены к одному вызову после прежнего gallery flow;
- `main.py` уменьшен с 14 654 до 14 631 строк (−23); новый service имеет 114 строк,
  direct contract tests — 4; generated map остаётся `597 symbols / 166 routes`.

Доказательства:

- до extraction прежний worker/gallery/refund baseline: `9 passed`; добавленные
  contracts сначала дали ожидаемый RED только на отсутствующем module import, затем
  direct suite `4 passed`, а direct + прежний integration baseline — `13 passed`;
- расширенный result/job/recovery/generation/ownership/ComfyUI/quota/API suite:
  `194 passed, 40 warnings` пять последовательных циклов за
  `81,66 / 79,85 / 81,83 / 82,24 / 79,67` с;
- первый Full gate штатно остановился на устаревших line numbers generated map; карта
  пересоздана официальным AST-generator и её `--check` успешен;
- успешный локальный Full: `1128 passed, 72 warnings`; frontend lint
  `0 errors / 1 existing warning`, production build 1,77 с, origin
  `200/200/403/403`, итоговый `VERIFY_OK` за 309,84 с; 148 Python-файлов;
- source-media snapshot до/после Full идентичен: 115 файлов / 1 534 310 байт /
  SHA-256 `D5C642413D984AD5E4232FE8B650B9C9F6BE18D283D673010134B57E37F41D6F`;
- pre-deploy audit: active jobs 0, ComfyUI running/pending 0/0, DB ready/Guard ok,
  единственные loopback listeners на 5173/8000/8188; controlled backend-only restart
  PID `46320 → 57684`, `--no-proxy-headers` сохранён;
- первый live-smoke harness ошибочно использовал GET для webhook из-за конфликта имени
  `$Args` и правильно получил 405; gate отклонил этот прогон. После исправления helper
  полный smoke повторён: 5/5 health/models/Flux/bgremoval/feed/bots/frontend `200`,
  private media `401`, Telegram POST webhook `404`;
- backend PID 57684 и ComfyUI PID 54544 стабильны 6/6 samples за 58 секунд,
  health/queue `200/200`; после restart active jobs 0 и pytest-процессов 0;
- schema/data migration, backup, secrets, paid generation, frontend runtime, ComfyUI,
  VPS и tunnel пакетом B7c не изменялись; tests/live smoke не записывали production
  jobs/media.

Exact CI после B7c:

- GitHub Actions run `29294261925`, job `86964255555`, на SHA `492601c`
  завершён успешно за 17 мин 29 с;
- `1128 passed, 72 warnings` за 928,28 с; lint `0 errors / 1 existing warning`;
- production build 1,37 с, origin isolation `200/200/403/403`, итоговый
  `VERIFY_OK` CI за 974,68 с.

### Checkpoint B7d — injected single-job generation processor

Реализовано и развёрнуто 2026-07-14:

- новый import-safe `app/services/generation_worker.py` владеет последовательностью
  обработки ровно одного уже найденного и разобранного job: cancellation, progress,
  provider dispatch, OpenRouter settlement application, fallback, quota branch,
  terminal state и failure/refund path;
- runtime является frozen dataclass из явных callbacks. Provider, billing, refund,
  quota/eviction, URL/ID/time, mock, image/source persistence, transient registration,
  optimization, sleep и job persistence инъецируются из `main.py` при каждом job;
- конкретные SQLite transactions, token ledger, files/PIL, in-memory mirrors,
  ComfyUI/OpenRouter functions и gallery storage остаются в тонких application
  adapters. Service не импортирует FastAPI, Pydantic, SQLite, HTTPX, environment или
  filesystem paths;
- динамическая сборка runtime сохраняет существующие monkeypatch/adapter contracts и
  не захватывает старые provider-функции при import;
- внешний `asyncio.Queue`, бесконечный consumer loop, request parsing, начальный timer,
  `task_done()` и startup task ownership не переносились и остаются точным B7e scope;
- прежний порядок side effects сохранён, включая idempotent cancel/failure refunds,
  OpenRouter adjustment до gallery save, protected-favorite transient result и
  повторное чтение quota после save/eviction;
- `main.py` уменьшен с 14 631 до 14 590 строк (−41); worker service имеет 170 строк,
  direct tests — 295 строк; generated map теперь `604 symbols / 166 routes`.

Доказательства:

- до extraction прежний worker/result/gallery/refund baseline: `13 passed`; direct
  contracts сначала дали ожидаемый RED только на отсутствующем module import;
- direct service suite после реализации: `8 passed`; direct + прежние worker
  integrations: `20 passed`;
- расширенный worker/result/job/recovery/generation/ownership/ComfyUI/quota/API suite:
  `202 passed, 40 warnings` пять последовательных циклов за
  `76,27 / 74,83 / 76,10 / 75,79 / 75,10` с;
- локальный Full: `1136 passed, 72 warnings`; frontend lint
  `0 errors / 1 existing warning`, production build 1,88 с, origin
  `200/200/403/403`, итоговый `VERIFY_OK` за 301,81 с; 150 Python-файлов;
- source-media snapshot стабилен внутри Full: 115 файлов / 1 532 066 байт / SHA-256
  `D69058C9F11BE9C1C504511604ED879AC9E0DE9B2AB993687F533B23985CE592`;
- отличие Full snapshot от B7c checkpoint (−2244 байта при том же count) исследовано
  read-only: production B7c успешно обрабатывал реальные пользовательские генерации
  и обычный gallery lifecycle между отдельными test/deploy windows; сам Full snapshot
  не менялся;
- два pre-deploy idle audit дали active jobs 0 и ComfyUI running/pending 0/0;
  controlled backend-only restart PID `57684 → 42376`, один loopback listener,
  `--no-proxy-headers`, DB ready/Guard ok;
- live smoke 5/5: health/models/Flux/bgremoval/feed/bots/frontend `200`, private media
  `401`, Telegram POST webhook `404`;
- backend PID 42376 и ComfyUI PID 54544 стабильны 6/6 samples за 58 секунд,
  health/queue `200/200`; после restart active jobs 0 и pytest-процессов 0;
- после Full, но ещё до restart, B7c завершил две дополнительные реальные генерации
  в 03:27–03:28 и добавил четыре source thumbnails. Последняя завершилась в 03:28:48,
  за 8 секунд до старта B7d PID 42376; final Quick затем был стабилен на 119 файлах /
  1 582 126 байтах / SHA-256
  `4565392F98C20F586C8F4E12CB35931C5D2A8842B93103FFFA1DA5020DD18B9A` и дал
  `43 passed`, `VERIFY_OK` за 8,70 с;
- schema/data migration, backup, secrets, paid test generation, frontend runtime,
  ComfyUI, VPS и tunnel пакетом B7d не изменялись. Изменение live jobs/media было
  реальной пользовательской активностью старого B7c process, а не тестами.

Exact CI после B7d:

- GitHub Actions run `29296269360`, job `86970359668`, на SHA `7b02ce3`
  завершён успешно за 19 мин 12 с;
- `1136 passed, 72 warnings` за 1026,96 с; lint `0 errors / 1 existing warning`;
- production build 1,63 с, origin isolation `200/200/403/403`, итоговый
  `VERIFY_OK` CI за 1085,67 с.

### Checkpoint B7e — generation queue consumer/one-shot startup lifecycle

Реализовано и развёрнуто 2026-07-14:

- новый import-safe `app/services/generation_queue.py` владеет бесконечным consumer
  loop и one-shot task starter для текущей in-process `asyncio.Queue`;
- frozen runtime явно получает queue protocol, jobs mapping, request parser, timer,
  worker-runtime factory и single-job processor callback. Модуль не импортирует
  `main`, FastAPI, Pydantic, SQLite, HTTPX, environment или filesystem;
- сохранён точный порядок legacy consumer: queue `get` → job lookup → request parse →
  timer → worker runtime → process внутри `try/finally` → один `task_done`;
- поэтому process exception или cancellation всё равно вызывает `task_done`, а lookup,
  parse или runtime-build failure до `try` его не вызывает. Это намеренно
  characterization, а не скрытое изменение поведения;
- one-shot starter не создаёт duplicate consumer при `worker_started=True`, выставляет
  started только после успешного `create_task` и пробрасывает task-creation error;
- `main.worker()` остаётся двухстрочным compatibility wrapper, а startup сохраняет
  глобальный `worker_started`. Тесты, меняющие `main.queue`/flag, продолжают работать;
- автоматического рестарта упавшего task по-прежнему нет — это открытый OPS-04 и будет
  решаться managed Windows service/supervisor, а не маскироваться рефакторингом;
- persistent queue, multi-worker, Docker и PostgreSQL не добавлялись и остаются волной F;
- `main.py` остался 14 590 строк: удалённые consumer/startup branches заменены явным
  runtime wiring/compatibility wrapper без искусственного сжатия форматирования;
  queue service имеет 54 строки, direct tests — 201; map `605 symbols / 166 routes`.

Доказательства:

- до extraction startup/worker/result/gallery/refund baseline: `23 passed`; direct
  contracts сначала дали ожидаемый RED только на отсутствующем module import;
- direct queue suite после реализации: `10 passed`; direct queue/worker/result +
  прежние startup/worker integrations: `32 passed`;
- расширенный queue/worker/result/job/recovery/generation/ownership/ComfyUI/quota/
  startup/API suite: `215 passed, 40 warnings` пять последовательных циклов за
  `76,50 / 76,13 / 77,58 / 76,56 / 76,05` с;
- локальный Full: `1146 passed, 72 warnings`; frontend lint
  `0 errors / 1 existing warning`, production build 0,413 с, origin
  `200/200/403/403`, итоговый `VERIFY_OK` за 299,19 с; 152 Python-файла;
- Full source snapshot стабилен: 120 файлов / 1 595 746 байт / SHA-256
  `078DB0E8BE1C646E914D8E7B247871F8DC7DD3B073204999E95837D8259787B4`;
- прирост от 119 до 120 файлов исследован read-only: уже B7d PID 42376 реально
  обработал пользовательскую ComfyUI job в 03:35:12–03:35:21 до `completed/100`,
  с result image, без error, и создал один source thumbnail 13 620 байт. Это первое
  реальное live-доказательство B7d, не платный test call;
- два pre-deploy idle audit дали active jobs 0 и ComfyUI running/pending 0/0;
  controlled backend-only restart PID `42376 → 49460`, один loopback listener,
  `--no-proxy-headers`, DB ready/Guard ok;
- live smoke 5/5: health/models/Flux/bgremoval/feed/bots/frontend `200`, private media
  `401`, Telegram POST webhook `404`;
- backend PID 49460 и ComfyUI PID 54544 стабильны 6/6 samples за 58 секунд,
  health/queue `200/200`; после restart active jobs 0 и pytest-процессов 0;
- final Quick после документации: `43 passed`, source snapshot неизменен,
  `VERIFY_OK` за 8,71 с;
- schema/data migration, backup, secrets, paid test generation, frontend runtime,
  ComfyUI, VPS и tunnel пакетом B7e не изменялись.

Exact CI после B7e:

- GitHub Actions run `29298111565`, job `86975939110`, на SHA `ec3a1d8`
  завершён успешно за 18 мин 57 с;
- `1146 passed, 72 warnings` за 989,26 с; lint `0 errors / 1 existing warning`;
- production build 0,991 с, origin isolation `200/200/403/403`, итоговый
  `VERIFY_OK` CI за 1035,79 с.

### Checkpoint B8a — pure gallery quota and eviction-target policy

Реализовано и развёрнуто 2026-07-14:

- новый import-safe `app/services/gallery_policy.py` владеет нормализацией плана,
  точным публичным quota payload и pure-решением, сколько старых unprotected rows
  требуется вытеснить перед новой записью;
- сохранена legacy-семантика без скрытой нормализации пробелов: known plan приводится
  к lower-case, неизвестное/пустое значение становится `mini`; payload сохраняет те
  же девять полей, integer/bool conversions, `gallery_free >= 0` и full при
  `used >= total`;
- eviction target остаётся `0` при положительном свободном месте или нулевом лимите,
  `1` на точном лимите и `2` выше лимита. Это сохраняет постепенное уменьшение старых
  over-limit galleries;
- owner-scoped count SQL, выбор oldest rows, favorite/source protection, soft-delete,
  физическое удаление original/thumbnail и in-memory mirror намеренно остались в
  `main.py`; их нельзя переносить одним большим change set;
- `main.py` уменьшен с 14 590 до 14 577 строк (−13); pure service имеет 48 строк,
  direct contract tests — 82 строки; generated map остаётся `605 symbols / 166 routes`.

Доказательства:

- новый contract suite до реализации ожидаемо остановился на отсутствии
  `app.services.gallery_policy`; после реализации direct suite дал `7 passed`;
- direct contracts и шесть прежних quota/eviction/favorite/feed scenarios дали
  `13 passed`;
- расширенный gallery/queue/worker/result/job/recovery/generation/ownership/ComfyUI/
  API suite: `223 passed, 40 warnings` пять последовательных циклов за
  `79,65 / 78,16 / 78,88 / 81,31 / 77,82` с;
- локальный Full: `1153 passed, 72 warnings` за 272,95 с; lint
  `0 errors / 1 existing warning`, production build 0,416 с, origin
  `200/200/403/403`, итоговый `VERIFY_OK` за 295,42 с; 154 Python-файла;
- source-media snapshot до/после Full строго идентичен: 120 файлов / 1 595 746 байт /
  SHA-256 `078DB0E8BE1C646E914D8E7B247871F8DC7DD3B073204999E95837D8259787B4`;
- первый ручной read-only pre-deploy query ошибочно использовал несуществующее имя
  таблицы `generation_jobs` и завершился без записи; исправленный audit использовал
  production `jobs`: active jobs 0, latest `completed/100`, ComfyUI running/pending
  0/0, pytest processes 0;
- controlled backend-only restart заменил PID `49460 → 43324`; независимый preflight
  подтвердил один listener `127.0.0.1:8000`, `--no-proxy-headers` и health `200`;
- live smoke 5/5: health/models/Flux config/bgremoval/feed/bots/frontend `200`, private
  media `401`, Telegram POST webhook `404`;
- backend PID 43324 и ComfyUI PID 54544 стабильны 6/6 samples за 58 секунд,
  health `200`, ComfyUI queue пуста;
- schema/data migration, production DB/media, backup, secrets, paid generation,
  frontend runtime, ComfyUI, VPS и tunnel пакетом B8a не изменялись.

Exact CI после B8a:

- GitHub Actions run `29299896127`, job `86981273737`, на SHA `376ecaa`
  завершён успешно за 17 мин 47 с;
- `1153 passed, 72 warnings` за 946,56 с; lint `0 errors / 1 existing warning`;
- production build 1,31 с, origin isolation `200/200/403/403`, итоговый
  `VERIFY_OK` CI за 994,32 с.

### Checkpoint B8b — gallery quota/candidate read repository

Реализовано и развёрнуто 2026-07-14:

- новый import-safe `app/storage/gallery_repository.py` владеет двумя read-only
  owner-scoped запросами: active gallery count и deterministic oldest eviction
  candidates;
- count сохраняет оба активных legacy-маркера: `deleted_at IS NULL` и пустую строку;
  user id всегда передаётся параметром, включая прежний explicit legacy override;
- candidate query сохраняет `is_favorite = 0`, исключает same-owner favorite source,
  не считает foreign source favorite защитой чужого owner row, сортирует по
  `created_at ASC, id ASC` и ограничивает exact target;
- repository использует structural connection protocol и не импортирует `main`,
  FastAPI, Pydantic, HTTPX, environment или filesystem. Неположительный limit безопасно
  возвращает пустой список без mutation;
- source-row deletion, `UPDATE images SET deleted_at`, original/thumbnail deletion и
  in-memory `images` mirror остались в прежнем цикле `main.py`; B8b не меняет порядок
  side effects или transaction ownership;
- `main.py` уменьшен с 14 577 до 14 566 строк (−11); repository имеет 46 строк,
  characterization tests — 139, direct tests — 129; map `605 symbols / 166 routes`.

Доказательства:

- три characterization-теста прошли на старом inline SQL до extraction и зафиксировали
  count markers/owner override, favorite/source protection, deterministic tie-break и
  exact over-limit target=2;
- direct contracts ожидаемо дали RED только на отсутствующем repository module, затем
  direct + characterization suite дал `9 passed`; вместе с прежними B8a/legacy
  quota/eviction/feed scenarios — `22 passed`;
- расширенный gallery/queue/worker/result/job/recovery/generation/ownership/ComfyUI/
  API suite: `232 passed, 40 warnings` пять последовательных циклов за
  `79,29 / 78,63 / 78,72 / 78,37 / 78,59` с;
- локальный Full: `1162 passed, 72 warnings` за 278,74 с; lint
  `0 errors / 1 existing warning`, production build 1,38 с, origin
  `200/200/403/403`, итоговый `VERIFY_OK` за 314,37 с; 157 Python-файлов;
- source-media snapshot до/после Full строго идентичен: 120 файлов / 1 595 746 байт /
  SHA-256 `078DB0E8BE1C646E914D8E7B247871F8DC7DD3B073204999E95837D8259787B4`;
- pre-deploy audit: production `jobs` active 0, latest `completed/100`, ComfyUI
  running/pending 0/0, pytest processes 0;
- controlled backend-only restart заменил PID `43324 → 49372`; независимый preflight
  подтвердил один listener `127.0.0.1:8000`, `--no-proxy-headers` и health `200`;
- live smoke 5/5: health/models/Flux config/bgremoval/feed/bots/frontend `200`, private
  media `401`, Telegram POST webhook `404`;
- backend PID 49372 и ComfyUI PID 54544 стабильны 6/6 samples за 58 секунд,
  health `200`, ComfyUI queue пуста;
- schema/data migration, production DB/media, backup, secrets, paid generation,
  frontend runtime, ComfyUI, VPS и tunnel пакетом B8b не изменялись.

Exact CI после B8b:

- GitHub Actions run `29301489818`, job `86985996536`, на SHA `ae48b7e`
  завершён успешно за 16 мин 46 с;
- `1162 passed, 72 warnings` за 886,86 с; lint `0 errors / 1 existing warning`;
- production build 1,37 с, origin isolation `200/200/403/403`, итоговый
  `VERIFY_OK` CI за 937,93 с.

### Checkpoint B8c — injected gallery eviction application

Реализовано и развёрнуто 2026-07-14:

- новый import-safe `app/services/gallery_eviction.py` владеет точным порядком
  side effects для уже выбранных rows: source deletion → soft-delete → original/thumb
  deletion → in-memory cache drop;
- frozen runtime получает четыре callbacks. Модуль не импортирует `main`, SQLite,
  FastAPI, Pydantic, HTTPX, environment или filesystem и не знает production paths;
- callbacks применяются к rows последовательно; исключение пробрасывается и останавливает
  текущую и оставшиеся строки в той же точке, что старый inline loop; nullable media
  values передаются без нормализации;
- `main.py` по-прежнему связывает active connection/`now_iso`, source/filesystem
  helpers и `images` mirror. Favorite selection остаётся read repository B8b;
- `main.py` вырос с 14 566 до 14 574 строк (+8), потому что неявный inline loop заменён
  явной сборкой четырёх concrete adapters с сохранённым public-feed комментарием.
  Это осознанный wiring overhead, а не сокращение файла; adapters удаляются только в
  B12–B14 после routers/application factory. Service имеет 31 строку, direct tests —
  106, расширенный characterization module — 218; map `605 symbols / 166 routes`.

Доказательства:

- два новых characterization contracts до extraction расширили прежний модуль до
  `5 passed` и зафиксировали точный межстрочный порядок и source-error short-circuit;
- direct contracts ожидаемо дали RED только на отсутствующем service module; после
  реализации direct + characterization suite дал `11 passed`, весь B8a–B8c и прежний
  product/feed baseline — `30 passed`;
- расширенный gallery/queue/worker/result/job/recovery/generation/ownership/ComfyUI/
  API suite: `240 passed, 40 warnings` пять последовательных циклов за
  `80,66 / 79,17 / 79,48 / 79,05 / 78,96` с;
- локальный Full: `1170 passed, 72 warnings` за 273,40 с; lint
  `0 errors / 1 existing warning`, production build 0,455 с, origin
  `200/200/403/403`, итоговый `VERIFY_OK` за 295,92 с; 159 Python-файлов;
- source-media snapshot до/после Full строго идентичен: 120 файлов / 1 595 746 байт /
  SHA-256 `078DB0E8BE1C646E914D8E7B247871F8DC7DD3B073204999E95837D8259787B4`;
- pre-deploy audit: production `jobs` active 0, latest `completed/100`, ComfyUI
  running/pending 0/0, pytest processes 0;
- controlled backend-only restart заменил PID `49372 → 9432`; независимый preflight
  подтвердил один listener `127.0.0.1:8000`, `--no-proxy-headers` и health `200`;
- live smoke 5/5: health/models/Flux config/bgremoval/feed/bots/frontend `200`, private
  media `401`, Telegram POST webhook `404`;
- backend PID 9432 и ComfyUI PID 54544 стабильны 6/6 samples за 58 секунд,
  health `200`, ComfyUI queue пуста;
- schema/data migration, production DB/media, backup, secrets, paid generation,
  frontend runtime, ComfyUI, VPS и tunnel пакетом B8c не изменялись.

Exact CI после B8c:

- GitHub Actions run `29302973816`, job `86990444646`, на SHA `9801626`
  завершён успешно за 14 мин 47 с;
- `1170 passed, 72 warnings` за 762,05 с; lint `0 errors / 1 existing warning`;
- production build 1,34 с, origin isolation `200/200/403/403`, итоговый
  `VERIFY_OK` CI за 810,71 с.

### Checkpoint B8d — pure gallery cursor and FTS helpers

Реализовано и развёрнуто 2026-07-14:

- новый import-safe `app/services/gallery_query.py` владеет URL-safe unpadded cursor
  encode, typed decode и legacy-compatible FTS term builder;
- cursor сохраняет exact compact JSON `created_at/id`, Unicode и padding removal;
  пустое значение остаётся `None`, malformed/missing fields дают typed
  `GalleryCursorError`;
- до extraction обнаружен реальный дефект: валидный base64 JSON со значением list,
  string, number или `null` проходил JSON decode, затем падал с `AttributeError` на
  `.get()` вместо client HTTP 400. Отдельный RED дал 4/4 failures с этим traceback;
- decoder теперь сначала требует mapping и переводит все четыре случая в typed error;
  тонкий wrapper `main.parse_gallery_cursor()` сохраняет прежний внешний
  `HTTPException(400, "invalid gallery cursor")`;
- FTS builder сохраняет lower-case Unicode `\w` terms, duplicates, `"term"*`, порядок,
  coercion и cap первых 12 terms;
- `main.py` уменьшен с 14 574 до 14 565 строк (−9); service имеет 43 строки,
  characterization tests — 63, direct tests — 75; map `605 symbols / 166 routes`.

Доказательства:

- девять существующих happy/malformed/missing/FTS characterization cases прошли до
  extraction; отдельные четыре non-object cases ожидаемо выявили pre-existing
  `AttributeError`; direct suite отдельно дал RED на отсутствующем module import;
- после реализации direct + characterization suite дал `27 passed`; полный B8,
  pagination, Unicode search и gallery optimization baseline — `63 passed`;
- расширенный gallery/queue/worker/result/job/recovery/generation/ownership/ComfyUI/
  API suite: `271 passed, 40 warnings` пять последовательных циклов за
  `80,82 / 79,95 / 80,60 / 80,28 / 80,05` с;
- локальный Full: `1197 passed, 72 warnings` за 273,98 с; lint
  `0 errors / 1 existing warning`, production build 0,424 с, origin
  `200/200/403/403`, итоговый `VERIFY_OK` за 296,68 с; 162 Python-файла;
- source-media snapshot до/после Full строго идентичен: 120 файлов / 1 595 746 байт /
  SHA-256 `078DB0E8BE1C646E914D8E7B247871F8DC7DD3B073204999E95837D8259787B4`;
- pre-deploy audit: production `jobs` active 0, latest `completed/100`, ComfyUI
  running/pending 0/0, pytest processes 0;
- controlled backend-only restart заменил PID `9432 → 26536`; независимый preflight
  подтвердил один listener `127.0.0.1:8000`, `--no-proxy-headers` и health `200`;
- live smoke 5/5: health/models/Flux config/bgremoval/feed/bots/frontend `200`, private
  media `401`, Telegram POST webhook `404`;
- backend PID 26536 и ComfyUI PID 54544 стабильны 6/6 samples за 58 секунд,
  health `200`, ComfyUI queue пуста;
- schema/data migration, production DB/media, backup, secrets, paid generation,
  frontend runtime, ComfyUI, VPS и tunnel пакетом B8d не изменялись.

Exact CI после B8d:

- GitHub Actions run `29304365769`, job `86994601228`, на SHA `fe18538`
  завершён успешно за 13 мин 27 с;
- `1197 passed, 72 warnings` за 685,54 с; lint `0 errors / 1 existing warning`;
- production build 1,39 с, origin isolation `200/200/403/403`, итоговый
  `VERIFY_OK` CI за 732,84 с.

### Checkpoint B8e — pure basic gallery presentation helpers

Реализовано и развёрнуто 2026-07-14:

- новый import-safe `app/services/gallery_presentation.py` владеет aspect-ratio,
  mode-label и source-ID helpers;
- aspect сохраняет legacy `math.gcd` reduction, zero/None handling и даже прежнюю
  negative-value форму; mode labels сохраняют 14 aliases, lookup trim и untrimmed
  unknown fallback;
- source IDs сохраняют приоритет `sourceImageIds → source_image_ids → sourceIds`,
  list-only contract, slicing первых четырёх значений до фильтрации и string coercion;
- до extraction обнаружена лишняя и опасная зависимость: `_gallery_mode_label()` читал
  `_admin_models_page_cache`, вычислял timestamp и никогда не использовал ни cache data,
  ни timestamp. Строка `corrupt-unused-timestamp` вызывала `ValueError` при обычном
  построении gallery item;
- pure helper больше не читает admin cache, поэтому presentation не может упасть из-за
  несвязанного cache timestamp; model catalog, file size, public params и full item
  mapping намеренно не переносились;
- `main.py` уменьшен с 14 565 до 14 533 строк (−32); service имеет 45 строк,
  characterization tests — 71, direct tests — 60; map `605 symbols / 166 routes`.

Доказательства:

- 14 legacy aspect/mode/source characterization cases прошли до extraction;
  отдельный corrupt-cache test ожидаемо дал `ValueError`, direct suite — RED на
  отсутствующем module import;
- после реализации direct + characterization suite дал `27 passed`; весь B8,
  pagination/search/item output baseline — `90 passed`;
- расширенный gallery/queue/worker/result/job/recovery/generation/ownership/ComfyUI/
  API suite: `298 passed, 40 warnings` пять последовательных циклов за
  `82,19 / 80,21 / 80,65 / 80,93 / 80,24` с;
- локальный Full: `1224 passed, 72 warnings` за 274,58 с; lint
  `0 errors / 1 existing warning`, production build 0,439 с, origin
  `200/200/403/403`, итоговый `VERIFY_OK` за 297,54 с; 165 Python-файлов;
- source-media snapshot до/после Full строго идентичен: 120 файлов / 1 595 746 байт /
  SHA-256 `078DB0E8BE1C646E914D8E7B247871F8DC7DD3B073204999E95837D8259787B4`;
- pre-deploy audit: production `jobs` active 0, latest `completed/100`, ComfyUI
  running/pending 0/0, pytest processes 0;
- controlled backend-only restart заменил PID `26536 → 33788`; независимый preflight
  подтвердил один listener `127.0.0.1:8000`, `--no-proxy-headers` и health `200`;
- live smoke 5/5: health/models/Flux config/bgremoval/feed/bots/frontend `200`, private
  media `401`, Telegram POST webhook `404`;
- backend PID 33788 и ComfyUI PID 54544 стабильны 6/6 samples за 58 секунд,
  health `200`, ComfyUI queue пуста;
- schema/data migration, production DB/media, backup, secrets, paid generation,
  frontend runtime, ComfyUI, VPS и tunnel пакетом B8e не изменялись.

Exact CI после B8e:

- GitHub Actions run `29305739880`, job `86998579375`, на SHA `7ccaa43`
  завершён успешно за 14 мин 07 с;
- `1224 passed, 72 warnings` за 720,35 с; lint `0 errors / 1 existing warning`;
- production build 2,47 с, origin isolation `200/200/403/403`, итоговый
  `VERIFY_OK` CI за 778,35 с.

### Checkpoint B8f — injected gallery model-info builder

Реализовано и развёрнуто 2026-07-14:

- `app/services/gallery_presentation.py` теперь владеет model-info builder,
  который получает price catalog, release-year map и display-name callback
  как явные зависимости;
- сохранён exact raw-model precedence `modelProfile → openrouterModel → provider`,
  billing override перед catalog, catalog перед display fallback и release-year
  fallback `2026`;
- локальные `empty/comfyui/local_flux/*klein*` сохраняют точный
  public payload `ИЗО Base / ИЗО / FLUX.2 Klein / 2026`;
- `_gallery_model_info()` в `main.py` остался тонким compatibility adapter;
  filesystem, public params и full row/page-item mapping намеренно не
  переносились;
- `main.py` уменьшен с 14 533 до 14 518 строк (−15); service имеет
  76 строк, characterization tests — 135, direct tests — 120; map
  `605 symbols / 166 routes`.

Доказательства:

- 21 legacy characterization case прошёл до extraction; direct test отдельно
  дал ожидаемый RED `ImportError` на ещё отсутствовавшем
  `gallery_model_info`;
- после реализации direct + characterization suite дал `36 passed`;
  полный B8 pagination/search/item-output baseline — `100 passed`;
- расширенный gallery/queue/worker/result/job/recovery/generation/ownership/ComfyUI/
  API suite: `308 passed, 40 warnings` пять последовательных циклов за
  `83,80 / 82,59 / 82,97 / 82,48 / 82,48` с;
- локальный Full: `1233 passed, 72 warnings` за 274,73 с; lint
  `0 errors / 1 existing warning`, production build 0,412 с, origin
  `200/200/403/403`, итоговый `VERIFY_OK` за 297,24 с; 165 Python-файлов;
- source-media snapshot до/после Full строго идентичен: 120 файлов /
  1 595 746 байт / SHA-256
  `078DB0E8BE1C646E914D8E7B247871F8DC7DD3B073204999E95837D8259787B4`;
- pre- и post-deploy audit: production `jobs` active 0, latest `completed/100`,
  ComfyUI running/pending 0/0, pytest processes 0;
- controlled backend-only restart заменил PID `33788 → 56088`;
  независимый preflight подтвердил один listener `127.0.0.1:8000` и
  `--no-proxy-headers`;
- первый ручной probe ошибочно использовал `/health` и получил
  закономерный HTTP 404; фактический `/api/health` затем дал 200;
- первый multi-endpoint smoke через Python `urllib` завершился
  единичным `ConnectionResetError` без смены PID/listener и без записи
  в error-log; каждый endpoint немедленно проверен по отдельности,
  после чего `curl` live smoke 5/5 дал health/models/Flux
  config/bgremoval/feed/bots/frontend `200`, private media `401`, Telegram POST
  webhook `404`;
- backend PID 56088 и ComfyUI PID 54544 стабильны 6/6 samples за 55 секунд,
  health `200`, ComfyUI queue пуста;
- schema/data migration, production DB/media, backup, secrets, paid generation,
  frontend runtime, ComfyUI, VPS и tunnel пакетом B8f не изменялись.

Exact CI после B8f:

- GitHub Actions run `29307623081`, job `87004172469`, на SHA `18442a5`
  завершён успешно за 21 мин 16 с;
- `1233 passed, 72 warnings` за 1133,85 с; lint `0 errors / 1 existing warning`;
- production build 1,32 с, origin isolation `200/200/403/403`, итоговый
  `VERIFY_OK` CI за 1191,35 с; run был медленнее предыдущих, но
  завершился в пределах workflow timeout 30 минут.

### Checkpoint B8g — injected public gallery params builder

Реализовано и развёрнуто 2026-07-14:

- `app/services/gallery_presentation.py` теперь владеет упорядоченным
  public-params builder с явно инъецированными model/token/aspect/file/
  formatting callbacks;
- сохранены точные восемь labels, их порядок, falsy filtering,
  resolution/aspect semantics, позиция full model name последней и
  отображение `0 ток.`;
- observable callback sequence сохранен дословно, включая два
  вызова token-cost callback при не-`None` значении;
- `image_id` остался в compatibility wrapper как прежде и не влияет
  на output; filesystem file-size resolution и full row/page-item mapping не
  переносились;
- explicit callback wiring временно увеличил `main.py` с 14 518 до
  14 523 строк (+5), хотя business list/filter logic переехала в service;
  service имеет 108 строк, characterization tests — 250, direct tests —
  191; map `605 symbols / 166 routes`. B8h должен убрать из `main.py`
  чистые formatter/token-cost implementations, не скрывая эту промежуточную
  цену wiring.

Доказательства:

- 23 legacy characterization case прошли до extraction; direct suite затем
  дал ожидаемый RED `ImportError` на отсутствовавшем
  `gallery_public_params`;
- после реализации direct + characterization suite дал `40 passed`;
  quota/repository/eviction/query/presentation/gallery-page baseline — `100 passed`;
- расширенный gallery/queue/worker/result/job/recovery/generation/ownership/ComfyUI/
  API suite: `312 passed, 40 warnings` пять последовательных циклов за
  `83,42 / 82,89 / 82,36 / 82,75 / 83,04` с;
- локальный Full: `1237 passed, 72 warnings` за 274,60 с; lint
  `0 errors / 1 existing warning`, production build 0,421 с, origin
  `200/200/403/403`, итоговый `VERIFY_OK` за 297,37 с; 165 Python-файлов;
- source-media snapshot до/после Full строго идентичен: 120 файлов /
  1 595 746 байт / SHA-256
  `078DB0E8BE1C646E914D8E7B247871F8DC7DD3B073204999E95837D8259787B4`;
- pre- и post-deploy audit: production `jobs` active 0, latest `completed/100`,
  ComfyUI running/pending 0/0, pytest processes 0;
- controlled backend-only restart заменил PID `56088 → 44880`; независимый
  preflight подтвердил один listener `127.0.0.1:8000` и `--no-proxy-headers`;
- `curl` live smoke 5/5: health/models/Flux config/bgremoval/feed/bots/frontend
  `200`, private media `401`, Telegram POST webhook `404`;
- backend PID 44880 и ComfyUI PID 54544 стабильны 6/6 samples за 55 секунд,
  health `200`, ComfyUI queue пуста;
- schema/data migration, production DB/media, backup, secrets, paid generation,
  frontend runtime, ComfyUI, VPS и tunnel пакетом B8g не изменялись.

Exact CI после B8g:

- GitHub Actions run `29309575938`, job `87010293918`, на SHA `d336fc6`
  завершён успешно за 13 мин 14 с;
- `1237 passed, 72 warnings` за 675,54 с; lint `0 errors / 1 existing warning`;
- production build 1,30 с, origin isolation `200/200/403/403`, итоговый
  `VERIFY_OK` CI за 729,71 с.

### Checkpoint B8h — pure public format and token-cost helpers

Реализовано и развёрнуто 2026-07-14:

- `app/services/gallery_presentation.py` теперь владеет pure bytes, duration,
  Moscow-datetime и token-cost implementations;
- bytes сохраняет `Б/КБ/МБ/ГБ`, 1024 thresholds, one-decimal formatting и
  русскую запятую; duration — integer coercion, invalid/non-positive filtering,
  `мс` до 1000 и one-decimal seconds;
- datetime сохраняет `Z`/aware/naive parsing, UTC assumption для naive,
  перевод в UTC+3 и string fallback для invalid input;
- token cost сохраняет приоритет `tokenCost → chargedTokens → actualTokens`,
  integer coercion, invalid-value fallback и значение `0`;
- четыре private symbols в `main.py` остались thin wrappers, поэтом
  builder monkeypatch seams и feed snapshot consumers не менялись;
- `main.py` уменьшен с 14 523 до 14 485 строк (−38); совместно
  B8g+B8h теперь дают −33 строки монолита. Service имеет 167 строк,
  characterization tests — 314, direct tests — 259; map
  `605 symbols / 166 routes`.

Доказательства:

- 51 legacy characterization case прошёл до extraction; direct suite затем
  дал ожидаемый RED `ImportError` на первом отсутствовавшем
  `format_gallery_public_bytes`;
- после реализации direct + characterization suite дал `96 passed`;
  quota/repository/eviction/query/presentation/gallery-page baseline — `156 passed`;
- расширенный gallery/queue/worker/result/job/recovery/generation/ownership/ComfyUI/
  API suite: `368 passed, 40 warnings` пять последовательных циклов за
  `83,23 / 82,32 / 82,67 / 82,78 / 82,38` с;
- локальный Full: `1293 passed, 72 warnings` за 274,70 с; lint
  `0 errors / 1 existing warning`, production build 0,431 с, origin
  `200/200/403/403`, итоговый `VERIFY_OK` за 297,19 с; 165 Python-файлов;
- source-media snapshot до/после Full строго идентичен: 120 файлов /
  1 595 746 байт / SHA-256
  `078DB0E8BE1C646E914D8E7B247871F8DC7DD3B073204999E95837D8259787B4`;
- pre- и post-deploy audit: production `jobs` active 0, latest `completed/100`,
  ComfyUI running/pending 0/0, pytest processes 0;
- controlled backend-only restart заменил PID `44880 → 41568`; независимый
  preflight подтвердил один listener `127.0.0.1:8000` и `--no-proxy-headers`;
- `curl` live smoke 5/5: health/models/Flux config/bgremoval/feed/bots/frontend
  `200`, private media `401`, Telegram POST webhook `404`;
- backend PID 41568 и ComfyUI PID 54544 стабильны 6/6 samples за 55 секунд,
  health `200`, ComfyUI queue пуста;
- schema/data migration, production DB/media, backup, secrets, paid generation,
  frontend runtime, ComfyUI, VPS и tunnel пакетом B8h не изменялись.

Exact CI после B8h:

- GitHub Actions run `29311262324`, job `87015311958`, на SHA `3ee9158`
  завершён успешно за 15 мин 38 с;
- `1293 passed, 72 warnings` за 828,76 с; lint `0 errors / 1 existing warning`;
- production build 1,27 с, origin isolation `200/200/403/403`, итоговый
  `VERIFY_OK` CI за 874,81 с.

### Checkpoint B8i — injected legacy row-to-image mapper

Реализовано и развёрнуто 2026-07-14:

- `app/services/gallery_presentation.py` теперь владеет legacy row-to-image
  mapping через structural row и injected settings loader, file-size, model label,
  model-info, public-params и row-get callbacks;
- сохранены все 28 output fields, их имена/defaults и точный
  callback order: JSON → file size → model label → model info → public params →
  deleted row-get → storage row-get;
- empty prompts остаются `""`, seed/generation time — `0`, loras — `[]`,
  favorite — `False`, а пустой storage tier — `original`;
- `main.row_to_image()` остался thin compatibility wrapper; SQL, filesystem
  adapter, `_gallery_page_item` и feed mapping не переносились;
- `main.py` уменьшен с 14 485 до 14 455 строк (−30); presentation
  service имеет 218 строк и больше не расширяется page-item
  mapping: B8j создаёт отдельный `gallery_items.py`. Characterization tests
  имеют 441 строку, direct tests — 356; их разделение остаётся
  отдельной волной D. Map — `605 symbols / 166 routes`.

Доказательства:

- 53 legacy characterization case прошли до extraction; direct suite затем
  дал ожидаемый RED `ImportError` на отсутствовавшем
  `gallery_row_to_image`;
- после реализации direct + characterization suite дал `100 passed`;
  quota/repository/eviction/query/presentation/gallery-page baseline — `160 passed`;
- расширенный gallery/queue/worker/result/job/recovery/generation/ownership/ComfyUI/
  API suite: `372 passed, 40 warnings` пять последовательных циклов за
  `82,78 / 82,08 / 83,72 / 83,59 / 82,39` с;
- локальный Full: `1297 passed, 72 warnings` за 274,43 с; lint
  `0 errors / 1 existing warning`, production build 0,570 с, origin
  `200/200/403/403`, итоговый `VERIFY_OK` за 298,97 с; 165 Python-файлов;
- source-media snapshot до/после Full строго идентичен: 120 файлов /
  1 595 746 байт / SHA-256
  `078DB0E8BE1C646E914D8E7B247871F8DC7DD3B073204999E95837D8259787B4`;
- pre- и post-deploy audit: production `jobs` active 0, latest `completed/100`,
  ComfyUI running/pending 0/0, pytest processes 0;
- controlled backend-only restart заменил PID `41568 → 14672`; независимый
  preflight подтвердил один listener `127.0.0.1:8000` и `--no-proxy-headers`;
- `curl` live smoke 5/5: health/models/Flux config/bgremoval/feed/bots/frontend
  `200`, private media `401`, Telegram POST webhook `404`;
- backend PID 14672 и ComfyUI PID 54544 стабильны 6/6 samples за 55 секунд,
  health `200`, ComfyUI queue пуста;
- schema/data migration, production DB/media, backup, secrets, paid generation,
  frontend runtime, ComfyUI, VPS и tunnel пакетом B8i не изменялись.

Exact CI после B8i:

- GitHub Actions run `29313254489`, job `87021485270`, на SHA `b793769`
  завершён успешно за 18 мин 26 с;
- `1297 passed, 72 warnings` за 985,01 с; lint `0 errors / 1 existing warning`;
- production build 1,33 с, origin isolation `200/200/403/403`, итоговый
  `VERIFY_OK` CI за 1030,15 с.

### Checkpoint B8j — separate gallery page-item service

Реализовано и развёрнуто 2026-07-14:

- новый import-safe `app/services/gallery_items.py` владеет short-circuit
  feed-publication readiness и gallery page-item mapping;
- readiness сохраняет точный порядок `status → media_ready_at → thumb → large`
  и не читает лишние поля после первого falsy условия;
- page mapper сохраняет exact 42-field payload, prompt/model/preset/loras/defaults,
  двойные display-name и aspect callback calls, feed-media URL substitution,
  publication status/views и source IDs;
- новый module получает settings/row/readiness/file/model/aspect/params/source
  behavior только через callbacks и не импортирует FastAPI, SQLite, HTTPX или
  filesystem roots;
- `_feed_publication_ready` и `_gallery_page_item` в `main.py` остались thin
  compatibility wrappers; feed snapshot, DB queries и source lifecycle не переносились;
- `main.py` уменьшен с 14 455 до 14 401 строк (−54); новый service
  имеет 105 строк, presentation service остался 218 строк;
  characterization tests — 181, direct tests — 96; map
  `605 symbols / 166 routes`.

Доказательства:

- три legacy readiness/page/defaults characterization case прошли до extraction;
  direct suite затем дал ожидаемый RED `ModuleNotFoundError` на ещё
  отсутствовавшем `app.services.gallery_items`;
- после реализации direct + characterization suite дал `6 passed`;
  quota/repository/eviction/query/presentation/gallery-page baseline — `166 passed`;
- расширенный gallery/queue/worker/result/job/recovery/generation/ownership/ComfyUI/
  API suite: `378 passed, 40 warnings` пять последовательных циклов за
  `84,96 / 86,97 / 84,11 / 84,61 / 84,14` с;
- локальный Full: `1303 passed, 72 warnings` за 282,62 с; lint
  `0 errors / 1 existing warning`, production build 0,448 с, origin
  `200/200/403/403`, итоговый `VERIFY_OK` за 308,04 с; 168 Python-файлов;
- source-media snapshot до/после Full строго идентичен: 120 файлов /
  1 595 746 байт / SHA-256
  `078DB0E8BE1C646E914D8E7B247871F8DC7DD3B073204999E95837D8259787B4`;
- между test/deploy windows появилась новая реальная пользовательская
  генерация; pre-deploy audit подтвердил её `completed/100`, active jobs 0
  и ComfyUI running/pending 0/0. Это не test mutation;
- post-deploy audit: production active jobs 0, latest `completed/100`, ComfyUI 0/0,
  pytest processes 0;
- controlled backend-only restart заменил PID `14672 → 41536`; независимый
  preflight подтвердил один listener `127.0.0.1:8000` и `--no-proxy-headers`;
- `curl` live smoke 5/5: health/models/Flux config/bgremoval/feed/bots/frontend
  `200`, private media `401`, Telegram POST webhook `404`;
- backend PID 41536 и ComfyUI PID 54544 стабильны 6/6 samples за 55 секунд,
  health `200`, ComfyUI queue пуста;
- schema/data migration, production DB/media, backup, secrets, paid generation,
  frontend runtime, ComfyUI, VPS и tunnel пакетом B8j не изменялись.

Exact CI после B8j:

- GitHub Actions run `29315621560`, job `87028854760`, на SHA `58d5804`
  завершён успешно за 19 мин 25 с;
- `1303 passed, 72 warnings` за 1004,79 с; lint `0 errors / 1 existing warning`;
- production build 1,34 с, origin isolation `200/200/403/403`, итоговый
  `VERIFY_OK` CI за 1067,05 с.

### Checkpoint B8k — separate feed generation-snapshot presentation service

Реализовано и развёрнуто 2026-07-14:

- новый import-safe `app/services/feed_presentation.py` владеет только сборкой
  generation snapshot для публикации и backfill;
- сохранены exact 16-field payload, trimming/defaults, model/style/seed/time
  semantics и точный порядок всех row/JSON/model/aspect/params/source/token/file
  callback calls;
- settings, не являющиеся mapping, как и раньше заменяются на пустой словарь;
- connection передаётся только в injected source-history callback; module не
  импортирует FastAPI, SQLite, HTTPX, environment или filesystem roots;
- `_feed_generation_snapshot` в `main.py` остался thin compatibility wrapper;
  source-history SQL, snapshot backfill SQL, `_feed_item_payload`, reactions и
  publication routes не переносились;
- `main.py` уменьшен с 14 401 до 14 383 строк (−18); новый service имеет
  55 строк, characterization tests — 162, direct tests — 120; map
  `605 symbols / 166 routes`.

Доказательства:

- два legacy snapshot characterization case прошли до extraction; direct suite
  затем дал ожидаемый RED `ModuleNotFoundError` на ещё отсутствовавшем
  `app.services.feed_presentation`;
- после реализации direct + characterization suite дал `5 passed`;
  feed/gallery baseline, включая publication snapshot API, дал `172 passed`;
- расширенный gallery/queue/worker/result/job/recovery/generation/ownership/ComfyUI/
  API suite: `383 passed, 40 warnings` пять последовательных циклов за
  `87,00 / 87,22 / 88,24 / 87,00 / 87,65` с;
- локальный Full: `1308 passed, 72 warnings` за 293,57 с; lint
  `0 errors / 1 existing warning`, production build 0,497 с, origin
  `200/200/403/403`, итоговый `VERIFY_OK` за 319,91 с; 171 Python-файл;
- source-media snapshot до/после Full строго идентичен: 120 файлов /
  1 595 746 байт / SHA-256
  `078DB0E8BE1C646E914D8E7B247871F8DC7DD3B073204999E95837D8259787B4`;
- pre-deploy audit: production active jobs 0, latest
  `job_20260714_100842_be737a completed/100`, ComfyUI 0/0, pytest processes 0;
- controlled backend-only restart заменил PID `41536 → 41928`; независимый
  preflight подтвердил один listener `127.0.0.1:8000` и `--no-proxy-headers`;
- live smoke 5/5: health/models/Flux config/bgremoval/feed/bots/frontend `200`,
  private media `401`, Telegram POST webhook `404`;
- backend PID 41928 и ComfyUI PID 54544 стабильны 6/6 samples за 55 секунд,
  health `200`, ComfyUI queue пуста;
- финальный Quick после документации: `43 passed`, source snapshot стабилен,
  `VERIFY_OK` за 10,02 с;
- schema/data migration, production DB/media, backup, secrets, paid generation,
  frontend runtime, ComfyUI, VPS и tunnel пакетом B8k не изменялись.

Exact CI после B8k:

- GitHub Actions run `29318047634`, job `87036500287`, на SHA `9117626`
  завершён успешно за 13 мин 32 с;
- `1308 passed, 72 warnings` за 688,55 с; lint `0 errors / 1 existing warning`;
- production build 1,36 с, origin isolation `200/200/403/403`, итоговый
  `VERIFY_OK` CI за 732,58 с.

### Checkpoint B8l — separate feed source-history read/mapping service

Реализовано и развёрнуто 2026-07-14:

- новый import-safe `app/services/feed_sources.py` владеет read-only
  `image_sources` query и row-to-public source-history mapping;
- сохранены exact selected columns, parameter binding, deterministic
  `slot_index ASC, created_at ASC` order, output fields, integer/default coercion,
  invalid-children fallback и точный callback order;
- пустой `image_id` по-прежнему возвращает `[]` без SQL и без callbacks;
- module получает structural connection и JSON/row/role-label callbacks, не
  импортирует FastAPI, SQLite, HTTPX, environment или filesystem roots;
- `_feed_source_history_payload` в `main.py` остался thin compatibility wrapper;
  snapshot/item payload, source mutations, publication/reaction/moderation SQL и
  routes не переносились;
- `main.py` уменьшен с 14 383 до 14 367 строк (−16); новый service имеет
  41 строку, characterization tests — 133, direct tests — 101; map
  `605 symbols / 166 routes`.

Доказательства:

- два legacy SQL/mapping/short-circuit characterization case прошли до
  extraction; direct suite затем дал ожидаемый RED `ModuleNotFoundError` на
  ещё отсутствовавшем `app.services.feed_sources`;
- после реализации direct + characterization suite дал `5 passed`;
  feed/gallery baseline, включая publication snapshot API, дал `177 passed`;
- расширенный gallery/queue/worker/result/job/recovery/generation/ownership/ComfyUI/
  API suite: `388 passed, 40 warnings` в каждом из пяти последовательных
  циклов; общий wall clock пяти циклов — 433,0 с;
- локальный Full: `1313 passed, 72 warnings` за 291,16 с; lint
  `0 errors / 1 existing warning`, production build 0,437 с, origin
  `200/200/403/403`, итоговый `VERIFY_OK` за 317,19 с; 174 Python-файла;
- source-media snapshot до/после Full строго идентичен: 120 файлов /
  1 595 746 байт / SHA-256
  `078DB0E8BE1C646E914D8E7B247871F8DC7DD3B073204999E95837D8259787B4`;
- pre-deploy audit: production active jobs 0, latest
  `job_20260714_100842_be737a completed/100`, ComfyUI 0/0, pytest processes 0;
- controlled backend-only restart заменил PID `41928 → 42564`; независимый
  preflight подтвердил один listener `127.0.0.1:8000` и `--no-proxy-headers`;
- live smoke 5/5: health/models/Flux config/bgremoval/feed/bots/frontend `200`,
  private media `401`, Telegram POST webhook `404`;
- backend PID 42564 и ComfyUI PID 54544 стабильны 6/6 samples за 55 секунд,
  health `200`, ComfyUI queue пуста;
- финальный Quick после документации: `43 passed`, source snapshot стабилен,
  `VERIFY_OK` за 9,38 с;
- schema/data migration, production DB/media, backup, secrets, paid generation,
  frontend runtime, ComfyUI, VPS и tunnel пакетом B8l не изменялись.

CI remediation после первого B8l push:

- GitHub Actions run `29320213377`, job `87043492546`, на SHA `3a33d93`
  завершил функциональную часть с `1312 passed`; единственный failure — старый
  shared-runner wall-clock assert: полный cursor scan 500 строк занял 7,948 с
  при локальном абсолютном лимите 3,0 с;
- status/count/search/pagination/no-duplicate assertions в этом case прошли;
  B8l source-history код в failure не участвовал;
- local performance limits сохранены строгими: first/scan/search/secondary
  `1/3/1/1` с; только при official `GITHUB_ACTIONS=true` действует bounded
  multiplier 4 (`4/12/4/4` с), поэтому gate остаётся ограничивающим, но не
  зависит от кратковременной нагрузки shared runner;
- добавлен отдельный contract test local/GitHub timing limits; весь load-profile
  file прошёл 5 локальных циклов и отдельный `GITHUB_ACTIONS=true` цикл — по
  `4 passed` каждый;
- повторный локальный Full после remediation: `1314 passed, 72 warnings` за
  291,27 с; lint `0 errors / 1 existing warning`, build 0,464 с, origin
  `200/200/403/403`, `VERIFY_OK` за 318,53 с; source snapshot стабилен;
- remediation изменяет только test gate и roadmap; production runtime не
  перезапускался повторно после уже успешного B8l deploy-monitor.

Exact CI после B8l remediation:

- GitHub Actions run `29321670540`, job `87048191809`, на SHA `ac01375`
  завершён успешно за 22 мин 06 с;
- `1314 passed, 72 warnings` за 1182,39 с; lint
  `0 errors / 1 existing warning`;
- production build 1,34 с, origin isolation `200/200/403/403`, итоговый
  `VERIFY_OK` CI за 1243,83 с;
- это последний code-bearing checkpoint перед B9a; рабочая `main`
  синхронизирована, production runtime этим test-only remediation не изменялся.

### Maintenance checkpoint G8 — gallery resilience and source retention

Реализовано и отправлено в `main` 2026-07-15, commit `c1d1a26`:

- bounded gallery/Studio picker reads, lazy secondary sections и private-media
  session retry устраняют full-history загрузки и потерю `use-as` draft;
- source-library rows отделены от lifecycle и quota generated gallery cards;
  source/image favorites защищают только собственные библиотеки;
- source authorization, recovery и audit учитывают сохранённые исходники после
  удаления parent result; отсутствующий физический файл даёт явный `410`;
- terminal-job Base64 compaction вынесен в dry-run maintenance command с
  обязательным backup для apply; live DB автоматически не изменялась;
- verification: gallery/storage `228 passed`, final focused `13 passed`, frontend
  build, Python/JavaScript syntax checks и desktop/mobile smoke прошли.

Подробный текущий контракт и эксплуатационные доказательства находятся в
`gallery-current-product-plan.md` и `gallery-optimization-implementation.md`.

### Product checkpoint V1 — OpenRouter video catalog in admin

Реализовано и проверено 2026-07-15:

- специализированный OpenRouter video catalog подключен к backend и кешируется;
- админка показывает раскрывающиеся списки по тексту, стартовому изображению,
  первому/последнему кадру и референсам;
- возможности, длительности, разрешения, аудио и ценовые SKU видны до начала
  реализации пользовательской видеостраницы;
- добавлена отдельная конфигурация включения видеомоделей и доступа по тарифам
  `Mini`/`Plus`/`Pro`/`Business`, backend отбрасывает неизвестные модели и режимы;
- предварительная бухгалтерия рассчитывает каждую поддерживаемую длительность:
  USD/RUB себестоимость, проектные токены, выручку, прибыль и фактическую маржу;
- основной список приведен к финансовой таблице изображений: чекбокс модели слева,
  общий выбор режима, тарифные столбцы и сопоставимый сценарий `5 сек. / 1080p`
  с автоматическим выбором ближайшего поддерживаемого варианта;
- backend готовит честный фактический счетчик завершенных video jobs по моделям и
  режимам; расходы показываются только когда провайдер сохранил реальную стоимость;
- секундные, входные image fees и видеотокенные SKU считаются раздельно;
  видеотокенные варианты разделены по фактическим размерам и пропорциям;
- режим референсов честно отмечен как вывод из описания и требует контрактного
  теста; пользовательская генерация и списание токенов этим пакетом не включены;
- verification: 91 focused tests пять раз подряд, 1312 full backend tests,
  adminModels ESLint, frontend build,
  авторизованный desktop/mobile live smoke; детали в
  `openrouter-video-admin-catalog-20260715.md`.

### Product checkpoint V2 — user video generation studio

Реализовано и проверено 2026-07-15:

- заглушка верхней вкладки `Видео` заменена отдельной lazy-loaded страницей `/video`;
- реализованы режимы по тексту, стартовому изображению, первому/последнему кадру и референсам;
- frontend строит длительности, разрешения, пропорции и аудио из возможностей выбранной модели, а стоимость получает с backend;
- backend валидирует тариф и модель, резервирует токены, создает OpenRouter video job, выполняет polling и сохраняет готовый MP4 в приватное медиахранилище;
- история и активные задания восстанавливаются из базы после обновления страницы; ошибки задания не сбрасывают пользовательский черновик;
- терминальные ошибки возвращают резерв идемпотентно; фактический `usage.cost` сохраняется для аудита, переплата относительно оценки возвращается без скрытой доплаты;
- desktop/mobile browser smoke не выявил горизонтального переполнения, мобильная рабочая область показывается перед параметрами;
- verification: 96 video/integration tests, 117 integration/protection tests, полный backend gate 1319 passed четырьмя непересекающимися группами, frontend lint без ошибок и production build;
- эксплуатационный контракт и повторное развертывание описаны в `video-generation-studio-20260715.md`.

До массового включения остается платный контрактный smoke каждой production-модели.

### Product checkpoint V3 — video product shell and media gallery

Реализовано и локально проверено 2026-07-16:

- видеостудия приведена к проектной схеме `Composer -> Stage -> Actions -> History + Context` из `izo-asa-design-system-20260716.md`;
- все четыре режима сохраняются на desktop и mobile, а режимы с кадрами получают загрузку с устройства и выбор из общей галереи;
- Stage использует выбранный формат кадра вместо фиксированной мобильной высоты; mobile-кнопка генерации больше не перекрывает Composer;
- API каталога отдает минимальную публичную цену и проверенные примеры по длительности/разрешению, поэтому цена видна до выбора модели;
- профиль получил пользовательский каталог видеомоделей, видимость и назначения `Быстро`/`Стандарт`/`Максимум` по режимам;
- добавлена таблица `videos`, идемпотентный backfill завершенных заданий и единая галерейная выдача изображений и видео;
- общая галерея воспроизводит, скачивает, отмечает избранным, фильтрует и удаляет видео; действия ленты и image-editor для видео пока честно скрыты;
- удаление видео убирает физический MP4 и запись из активной галереи, но сохраняет job и бухгалтерский аудит;
- verification: frontend production build, Python/JS syntax, `206 passed` video/database/gallery regressions, полный backend gate `1332 passed`, Playwright desktop/mobile visual smoke;
- платный контрактный smoke production-моделей выполняется перед массовым включением production-моделей.

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
