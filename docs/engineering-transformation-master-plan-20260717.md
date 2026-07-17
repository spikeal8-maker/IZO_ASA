# IZO_ASA — инженерная трансформация действующего production

Дата аудита и актуализации: **2026-07-17**

Статус документа: **главный исполняемый план; S0-001 и S0-002 VERIFIED, следующий пакет ENV-001**

Предыдущий roadmap: `production-hardening-roadmap-20260713.md` остаётся историей выполненных пакетов и больше не является источником актуального порядка работ.

## 0. Короткий ответ

Проект уже работает с реальными пользователями. Его не требуется переписывать с нуля, переносить в микросервисы или немедленно отправлять на VPS/Linux/PostgreSQL.

Нужна контролируемая трансформация **модульного монолита**:

1. сначала вернуть доказуемо зелёную и воспроизводимую исходную точку;
2. закрыть риски денег, авторизации, фоновых заданий, релиза и восстановления;
3. только затем последовательно уменьшать `backend/main.py`, `newUi.tsx`, CSS и крупные тестовые файлы;
4. сохранить один локальный Windows-компьютер основным application server;
5. не менять существующий VPS/FRP-туннель: он остаётся только транспортом домена;
6. перейти на Caddy и Windows Services локально, а Docker/Linux/PostgreSQL вводить только по измеряемым признакам необходимости.

«Идеальным» проект считается не по размеру файлов, а когда изменения безопасны, финансовые операции атомарны, фоновые задания восстанавливаются, релиз откатывается, backup реально восстанавливается, а все эти свойства подтверждаются автоматическими проверками.

## 1. Область действия и неизменяемые условия

### 1.1. Входит в программу

- backend, frontend, локальная SQLite, media, ComfyUI/Ollama-интеграции;
- YooKassa, токены, тарифы, возвраты, уведомления и обязательства НПД;
- auth, session cookies, Telegram/MAX/Web identity;
- очереди генерации, видео, публикаций и уведомлений;
- тесты, CI, release pipeline, локальный edge proxy, supervision;
- backup, restore, observability, миграции и подготовка к будущему масштабированию;
- постепенная декомпозиция крупных файлов без изменения пользовательского поведения.

### 1.2. Не входит без отдельного решения владельца

- изменение VPS, доменного FRP/tunnel и его сетевой конфигурации;
- немедленный переезд application stack на VPS;
- микросервисы;
- Kubernetes;
- немедленный Docker/Linux-переезд;
- немедленная замена SQLite на PostgreSQL;
- смена YooKassa или SMTP только ради «архитектурной чистоты»;
- массовая переделка интерфейса одновременно с критическими backend-пакетами.

### 1.3. Инварианты каждого пакета

- production DB и media не используются тестами и не изменяются ими;
- незавершённые пользовательские изменения не смешиваются с архитектурным пакетом;
- один пакет решает одну ограниченную проблему;
- сначала characterization/contract tests, затем перенос или изменение;
- публичный контракт API сохраняется либо версионируется;
- controlled restart выполняется только когда он нужен и только после зелёных gates;
- при неудаче старый процесс/release остаётся доступен или есть проверенный откат;
- секреты, live DB, media и модели не попадают в Git;
- коммит, документация и push входят в Definition of Done пакета;
- маленькие UI-правки могут идти параллельно только по правилам раздела 18.

## 2. Источники и метод аудита

План построен не только по прежним выводам. На 2026-07-17 проверены:

- предоставленный `IZO_ASA_ENGINEERING_TRANSFORMATION_MASTER_PLAN_2026-07-17.md`;
- предоставленный углублённый инженерный вывод;
- актуальные `main`, `origin/main` и незакоммиченный worktree;
- структура backend/frontend, маршруты, зависимости и workflow;
- live health/version/process/listener snapshot без изменения production;
- read-only структура и агрегаты live SQLite;
- критические тесты очереди, платежей, биллинга, auth, admin и video;
- frontend production build и npm production audit;
- последние GitHub Actions и доступность branch protection;
- backup tasks и их последние коды возврата;
- официальные документы SQLite, FastAPI, Vite, YooKassa и ФНС.

Любая величина в этом разделе является snapshot, а не вечной константой. Перед реализацией пакета она перепроверяется.

## 3. Подтверждённая исходная точка

### 3.1. Git и текущий WIP

| Параметр | Подтверждённый факт |
|---|---|
| Ветка | `main` |
| Проверенный repository baseline | `8f27dc086aaca381f47d965c82f3a849e5fff493` |
| Production runtime baseline | backend PID 26004 не перезапускался для S0-002; пакет не меняет ASGI/runtime behavior; актуальная параллельная UI-правка сохранена в `a5474f8` |
| Проверенные commits Gate 0 | S0-001: `d3561fe`, `2498f56`, `13c8216`, `0acb299`; UI checkpoint: `a5474f8`; S0-002: `8f27dc0` |
| Синхронизация baseline | `8f27dc0` отправлен в `origin/main` |
| Worktree checkpoint | реализация S0-002 завершена; точный отчёт оформляется отдельным документирующим commit |
| Следующий пакет | `ENV-001` — immutable production identity и устранение `development/global Python/unknown frontend build` drift |

На момент первоначального аудита одновременно менялись backend, frontend и static shells. В S0-001 этот WIP был инвентаризирован, исправлен, протестирован, разделён на четыре понятных commits и опубликован. Архитектурные переносы в продуктовые commits не добавлялись.

### 3.2. Размер и форма кода

| Объект | Snapshot 2026-07-17 | Вывод |
|---|---:|---|
| `backend/main.py` | 20 027 физических строк, 721 top-level functions, 81 class, 221 route | главный coordination/ownership риск |
| `frontend/src/newStudioV3.css` | 5 875 строк | стили смешивают несколько features |
| `frontend/src/newUi.tsx` | 4 373 строки | API/state/composition/view связаны |
| `frontend/src/LegacyApp.tsx` | 3 600 строк | legacy требует заморозки и контролируемого удаления |
| `frontend/src/newUi.css` | 3 096 строк | нужен feature split |
| `frontend/src/index.css` | 2 333 строки | глобальный слой шире своей роли |
| `backend/static/feed/index.html` | 2 110 строк | отдельный shell может дрейфовать от React |
| `frontend/src/adminModels.tsx` | 2 016 строк | API/types/hooks/page смешаны |
| `backend/test_feed_v2.py` | 2 320 строк | тестовый ownership тоже нужно разделять |

`backend/SYMBOL_MAP.md` и новый architecture inventory синхронизированы с baseline `8f27dc0`: 721 function, 81 class, 221 route. Пороговые guards ограничивают дальнейший рост заранее заданным запасом 750/90/230. Большие файлы остаются предметом следующих пакетов; Gate 0 не маскируется как их декомпозиция.

### 3.3. Runtime

| Компонент | Факт |
|---|---|
| Backend | production Uvicorn на `127.0.0.1:8000`; обнаруженный в S0-001 orphan backend на зарезервированном `8001` остановлен |
| Frontend | `vite preview` |
| ComfyUI | локально на `8188` |
| Ollama | локально на `11434` |
| GPU | RTX 3090, driver snapshot `610.47` |
| Python/Node/Git | Python 3.11.9, Node 24.14.1, npm 11.12.1, Git 2.55 |
| Backend version | после controlled restart процесс импортировал baseline `13c8216fbfe9`; frontend build identity пока `unknown` |
| Backend environment | live `/api/health` сообщил `development` |
| Python isolation | live Uvicorn запущен глобальным Python, не project `.venv` |

Это означает: сайт работает, но идентичность запущенного release и production-policy сейчас не доказаны. Официальный `start-public.bat` задаёт production environment, следовательно live процесс был запущен другим путём или потерял конфигурацию.

### 3.4. Тесты и сборка

| Проверка | Результат аудита |
|---|---|
| Исходный критический backend-набор аудита | **116 passed**, 28 warnings, 46.80 s |
| S0-001 полный backend/tools suite | **1448 passed**, 92 warnings, 383.34 s; code/test blob не менялся во время прогона |
| Focused product gate | 24 backend tests + isolated browser E2E, **5 последовательных проходов** |
| Worker lifecycle gate | 8 recovery/shutdown tests, **5 последовательных проходов** |
| Frontend lint | **PASS**, 0 errors, 0 warnings |
| Frontend production build | **PASS**, `tsc -b && vite build` |
| Frontend integration gates | origin isolation PASS; studio resilience PASS; video publication PASS на 1920×1080, 1920×900, 3840×2160 и 390×844 |
| Warnings | остаются deprecated FastAPI `on_event` и cookie deprecation в TestClient; вынесены в последующие пакеты |
| npm production audit | 0 production vulnerabilities |
| `pip check` | global environment конфликтует с посторонними пакетами; это не результат чистой project `.venv` |
| Остаточные pytest-процессы | после gate отсутствовали |

S0-001 закрыл первоначальный build blocker и дал новый проверенный baseline. Это не устраняет `development` environment, global Python и `frontend_build=unknown`: эти риски остаются предметом ENV-001.

### 3.5. GitHub Actions

Последние workflow runs на `main`, включая exact HEAD run `29585296500`, завершились за несколько секунд без runner и без шагов. Причина из GitHub annotation: неудавшиеся платежи аккаунта либо spending limit. Это **инфраструктурная блокировка CI**, а не падение тестов.

Branch protection для private repository возвращает HTTP 403 на текущем GitHub plan. Поэтому до изменения тарифа/visibility:

- локальный полный gate обязателен;
- GitHub status не считается подтверждением, пока job не получил runner и не выполнил шаги;
- exact-SHA verification receipt хранится как artifact/документ;
- публикация не должна автоматически считать skipped job зелёным.

### 3.6. Production data

| Показатель | Snapshot |
|---|---:|
| SQLite | около 539 MiB, WAL около 4 MiB |
| Tables | 57 |
| `user_version` | 1 |
| Recorded migration | только baseline v1 |
| Foreign keys | 0 |
| Users | 36 |
| Jobs | 701 completed, 45 failed, активных не было |
| Payments | 1 paid, 2 canceled |
| Invoices | 1 paid, 2 cancelled |
| Payment provider events | 1 succeeded, 2 canceled |
| Token ledger | 1 452 rows |
| Notification outbox | 2 pending |
| Feed | 71 published, 1 pending review |

Базовый orphan audit не обнаружил простых ссылочных сирот в проверенных связях. Это хороший сигнал, но отсутствие foreign keys и версионированных миграций остаётся риском.

### 3.7. Backup

- локальные snapshot/verify/rehearsal механизмы существуют;
- `IZO_ASA Local Backup 15m` и cloud stage task сообщили last result 0;
- `IZO_ASA Backup Health 10m` сообщил last result 2;
- offsite/standby нельзя называть готовыми, пока health, account, client, sync root и route preflights не подтверждены;
- live SQLite нельзя копировать обычной файловой командой: используется SQLite Backup API/согласованный snapshot.

## 4. Что в предоставленном исследовании верно, устарело и отсутствовало

### 4.1. Подтверждено

- `backend/main.py` остаётся чрезмерным и требует постепенной декомпозиции;
- SQLite надо защищать от конкурентных финансовых записей и готовить repository boundary;
- `vite preview` не является production server;
- отсутствует постоянный process supervisor;
- release не должен продолжаться после TypeScript/test failure;
- локальные DB/media требуют физически отдельного и offsite backup;
- legacy auth необходимо окончательно закрыть автоматическими архитектурными тестами;
- большие frontend/CSS/test files нуждаются в таком же ownership split, как backend.

### 4.2. Уточнено или уже исправлено

- Vite `allowedHosts: true` уже не актуально: сейчас используется конкретный host;
- значительная часть auth уже проходит через trusted identity core;
- YooKassa webhook не доверяет только входящему JSON: перед начислением backend повторно получает payment у provider и сверяет сумму/валюту;
- payment completion уже использует `BEGIN IMMEDIATE` и status idempotency;
- npm production dependency audit на snapshot чистый;
- decomposition infrastructure и service modules уже существуют, поэтому нужен не новый каркас, а продолжение границ.

### 4.3. Новые критические находки

1. **Неопределённый исход checkout.** Provider может создать платёж, а локальный процесс упасть до сохранения `provider_payment_id`. Повторный запрос возвращает существующую локальную запись и не восстанавливает связь с удалённым платежом.
2. **Ledger concurrency.** Списание токенов выполняет read/compute/write без единой атомарной операции и без уникального operation key.
3. **Refund concurrency.** Защита от повторного refund опирается на JSON `LIKE`, а не DB constraint.
4. **Manual paid race.** Ручное подтверждение invoice не сведено к единому финансовому transaction service.
5. **Нет durable fiscal obligation tracker.** Для НПД нужен явный статус чека, срок, ссылка и подтверждение отправки покупателю.
6. **Generation consumer может умереть.** Часть исключений возникает до `try/finally`; task handle не контролируется; watchdog отсутствует.
7. **Video finalization зависит от GET.** Если пользователь закрыл страницу, server-side reconciliation может не произойти вовремя.
8. **Outbox не обслуживается автоматически.** Durable lease есть, но два pending события подтверждают отсутствие постоянного worker.
9. **Live environment drift.** Реальный backend сообщил `development`, frontend build unknown и использует глобальный Python.
10. **Публичный health раскрывает лишнее.** Environment, DB size, admin/user counts и internal URLs должны быть доступны только trusted admin/ops.
11. **CSRF policy не выявлена.** При `SameSite=None` нужны unsafe-method Origin/CSRF gates; provider webhooks выделяются в отдельное исключение.
12. **CI снова выполняется, но близок к timeout и не сохраняет artifact.** Exact-SHA run S0-002 впервые прошёл все steps, однако job занял 25m45s из лимита 30 минут; нужен запас по длительности и сохраняемый verification manifest/log summary.
13. **Process role/port collision.** В S0-001 найден осиротевший второй full backend на `127.0.0.1:8001`, подключённый к live DB и Telegram polling, хотя порт зарезервирован для Qwen ASR. Он создавал duplicate polling и доказывает, что candidate/dev процесс нельзя запускать с production roots/workers без role guard.
14. **Ollama bind drift.** Ollama Desktop сейчас сообщает listener `:::11434`, хотя целевой контракт требует loopback `127.0.0.1:11434`. S0-002 делает это явным warning; изменение работающего Ollama переносится в OPS hardening с health/rollback, а не выполняется скрыто внутри inventory-пакета.

## 5. Архитектурные решения программы

### 5.1. Целевая форма: модульный монолит

Не вводить микросервисы. Цель — один versioned release с несколькими процессными ролями и ясными модулями:

```text
Internet/domain
      |
 existing VPS/FRP tunnel (не изменяется)
      |
 local Caddy edge
      |-- immutable frontend release
      |-- /api, protected media -> API slot A/B
      `-- legacy/static routes during migration

 local API process (no background workers)
 local worker processes from the same exact release SHA
      |-- generation
      |-- video reconciliation
      |-- feed publication
      `-- notifications/payments reconciliation

 SQLite + WAL + media on local host
 ComfyUI / Ollama on local host
 backup snapshot -> second physical disk -> encrypted offsite
```

### 5.2. Edge: Caddy

Caddy выбран вместо nginx для текущего Windows single-node:

- короткая и проверяемая конфигурация;
- удобный Windows binary/service;
- атомарная проверка и reload конфигурации;
- правильная раздача immutable assets, compression, headers, limits и reverse proxy;
- nginx не даёт преимущества, которое оправдывает дополнительную Windows-эксплуатационную сложность сейчас.

Caddy устанавливается **на этом компьютере** и принимает локальный порт, на который уже приходит FRP. VPS/tunnel не изменяются. Automatic public certificate не предполагается, если TLS уже завершается существующей схемой; сначала фиксируется фактический network contract.

### 5.3. Process supervisor: WinSW

Начальный supervisor — WinSW 2.x stable либо эквивалентно зафиксированная Windows service wrapper версия. Процессы запускаются под текущим выделенным Windows account, потому что DPAPI secrets, Ollama и часть models/runtime привязаны к пользователю.

Службы:

- `IZO-Edge-Caddy`;
- `IZO-API-A` и позднее `IZO-API-B`;
- `IZO-Worker-Generation`;
- `IZO-Worker-Video`;
- `IZO-Worker-Feed`;
- `IZO-Worker-Notification-Reconcile`;
- backup/health могут остаться Task Scheduler до отдельной миграции.

Docker on Windows и Linux — следующий deployment stage, не условие текущей стабилизации.

### 5.4. Persistent queue: SQLite lease/claim

Redis/RabbitMQ сейчас не нужны. Сначала вводятся durable job tables/status/attempt/lease owner/lease expiry/next attempt/error и атомарный claim через SQLite transaction.

Переход на Redis/другой broker рассматривается, если:

- нужна работа нескольких машин;
- SQLite queue contention измеримо нарушает SLO;
- backlog/retry throughput превышает single-node capability;
- нужен fan-out/event streaming, который нельзя безопасно выразить текущими таблицами.

### 5.5. PostgreSQL

PostgreSQL — будущая цель при масштабировании, но не немедленная правка. Сначала вводятся repositories, migration discipline и metrics.

Переход запускается при одном или нескольких подтверждённых условиях:

- более одного backend/worker host должен писать в одну БД;
- `SQLITE_BUSY`/lock errors > 0.1% write operations за окно наблюдения;
- p95 финансовой/интерактивной записи > 100 ms из-за contention;
- backup/restore RTO/RPO или HA не обеспечиваются SQLite single-node;
- длительные аналитические запросы мешают транзакциям;
- рост команды требует стандартных constraints/online migrations/roles.

Размещать PostgreSQL тогда лучше как managed service рядом с Linux application server либо как отдельный server с backup/PITR. Не размещать его на VPS-туннеле только потому, что VPS существует.

### 5.6. Secrets

Сейчас:

- provider secrets — Windows CurrentUser DPAPI в `%LOCALAPPDATA%\IZO_ASA\secrets` или `IZO_SECRET_DIR` вне repository;
- `.env` — только local configuration и временные совместимые значения, файл ignored и с ограниченными ACL;
- backup secret inventory хранит зашифрованные recovery instructions, но не незашифрованные ключи;
- на новом компьютере DPAPI-файлы не копируются как рабочие: секреты вводятся заново и ротируются.

Позже в Docker/Linux:

- mounted secret files/Docker secrets или managed secret store;
- секреты не baked into image, не в compose Git и не в command line;
- release artifact одинаков для environments.

### 5.7. Backup

Минимальная схема:

1. SQLite Backup API + manifest/hash;
2. media incremental snapshot;
3. копия на другой **физический** диск;
4. зашифрованная offsite-копия (Yandex.Disk допустим после всех preflight/health gates);
5. регулярный restore rehearsal на изолированном пути;
6. отдельный standby inventory: code SHA, runtimes, ComfyUI/Ollama models, secrets re-entry, Caddy/services config.

Копия на другом разделе того же SSD не является защитой от отказа SSD.

### 5.8. Providers

- платежи: оставить YooKassa;
- email: оставить текущий SMTP, пока delivery metrics не требуют transactional provider;
- выбор другого email provider нужен только при недоставке, volume limits, webhook/analytics или SLA;
- российский юридический и НПД-процесс фиксируется отдельным legal/operations contract, а не «прячется» в коде.

### 5.9. Legacy UI

Legacy UI замораживается: только security/critical compatibility fixes. Удаление разрешено после одновременного выполнения:

- функциональный parity list закрыт;
- 30 дней отсутствует реальный трафик на legacy entrypoints;
- browser/e2e покрывают replacement routes;
- static shells и public links ведут на новый UI;
- существует release rollback;
- владелец продукта подтверждает удаление.

### 5.10. Downtime

Downtime — время, когда пользователи не могут использовать продукт во время обновления.

Принятые цели:

- обычный additive code release: 0 запланированных минут после введения Caddy A/B;
- до A/B: controlled restart с измеренным временем и откатом;
- additive DB migration: API совместим со старой и новой схемой;
- редкая blocking data migration: не более 5 минут по отдельному maintenance plan;
- destructive migration: только отдельным пакетом после минимум одного совместимого release и проверенного backup restore.

## 6. Приоритеты

| Приоритет | Значение | Примеры |
|---|---|---|
| P0 | риск денег, доступа, потери данных или недоступности | checkout ambiguity, ledger atomicity, dead worker, broken release gate, backup health |
| P1 | высокий риск регрессий/эксплуатации | modular boundaries, migrations, Caddy, services, observability |
| P2 | поддерживаемость/performance/developer experience | frontend split, test split, query tuning, legacy removal |

Дробление файлов важно, но не должно обгонять P0. Иначе проект станет визуально «чище», сохранив риск двойного списания или умершего worker.

## 7. Универсальный протокол одного пакета

Каждая карточка ниже реализуется так:

1. **Preflight:** `git status`, owner файлов, live process/health, схема и baseline tests.
2. **Characterization:** тесты текущего правильного поведения и известных failure modes.
3. **Minimal change:** перенос без смешанного redesign либо один осмысленный behavior fix.
4. **Focused gate:** релевантные тесты; для рискованного алгоритма повторить минимум 5 раз.
5. **Static gate:** compile/map/lint/type/build/architecture guards.
6. **Full local gate:** изолированная DB/media, без production mutation.
7. **Review diff:** secrets, schema, route/auth/task inventory, generated artifacts.
8. **Commit:** один пакет, понятный message, обновлённый status в этом документе.
9. **Push/CI:** exact SHA; CI считается зелёным только если runner выполнил все steps.
10. **Controlled deploy:** backup при schema/finance, release manifest, smoke, logs.
11. **Post-deploy observation:** не менее заданного окна, затем checkpoint.

Нельзя «гонять полный suite пять раз» после каждой механической строки без причины: это создаёт нагрузку и замедляет feedback. Пять повторов применяются к focused regression/concurrency gate; полный suite — минимум один раз на пакет и повтор после устранения flaky/failure.

## 8. Gate 0 — нормализация текущего WIP

До первого архитектурного изменения выполнить строго отдельно.

### S0-001 — Завершить текущий продуктовый WIP

Статус: `VERIFIED`

Проверенный repository baseline: `0acb2992fe37a7ee08e3b9c7c324c868c9784a09`, push в `origin/main` подтверждён 2026-07-17. Production code baseline: `13c8216fbfe9abaf9312f4485b8bf3f608bda4e2`.

Цель: получить понятный, проверенный продуктовый commit без архитектурных переносов.

Работы:

- инвентаризировать текущие изменения по владельцу и назначению;
- исправить TypeScript contract `GalleryContractItem.mediaType` без скрытого `any`;
- обновить static feed/gallery regression expectations только по фактическому контракту;
- проверить background feed-video publication изменения на restart/recovery/idempotency;
- обновить `SYMBOL_MAP.md` генератором;
- focused frontend/backend tests ×5;
- полный local gate;
- отдельный commit и push.

DoD:

- production build зелёный;
- WIP не потерян и не смешан с планом;
- test DB/media изолированы;
- exact commit зафиксирован как новый baseline.

Checkpoint 2026-07-17:

- commits: `d3561fe` — token wallet/static gallery alignment; `2498f56` — безопасная асинхронная публикация видео; `13c8216` — синхронизация symbol map и чистый resolution fallback; `0acb299` — гарантия независимости опубликованной video-копии от удаления приватного оригинала;
- API impact: публикация видео возвращает асинхронный статус, gallery/history показывают `preparing|published|failed`, capability публикуется явно;
- schema impact: DDL и destructive migration отсутствуют, используются существующие поля `feed_publications`;
- auth impact: новые legacy-auth обходы не добавлены, действующие user ownership gates сохранены;
- task impact: feed-video worker восстанавливает `preparing` после startup, сериализует повторную публикацию и корректно дожидается активной производной при shutdown;
- focused verification: product gate ×5, worker lifecycle gate ×5 и private-delete/feed-copy regression ×5;
- full local verification: `python -m pytest -q backend tools` — 1448 passed; frontend lint/build/origin/resilience/video-layout gates — PASS;
- GitHub CI: run `29598478767`, job `87944577412`; runner не выполнил ни одного step из-за account billing/spending limit, поэтому это инфраструктурная блокировка, а не зелёный или упавший code gate;
- deploy: controlled backend restart `48536 -> 26004`, новый startup `2026-07-17 19:50:18 +03:00`; `/api/health`, `/api/version`, `/feed`, `/gallery` — HTTP 200;
- observation: после restart накопилось 93 `TelegramTransportError`; token probe `getMe` вернул 200, причиной оказался orphan full backend PID 39824 на зарезервированном Qwen ASR порту 8001 с той же live DB и polling;
- operational correction: при нулевых active jobs/preparing publications и отсутствии TCP-клиентов orphan PID 39824 остановлен graceful; 8001 освобождён, production PID 26004 остался healthy, за последующие 45 секунд новых Telegram polling errors — 0;
- rollback: не потребовался; предыдущая code point `2498f56` сохранена в Git;
- residual risk: runtime всё ещё сообщает `development`, global Python и `frontend_build=unknown`; исправляется в ENV-001, а не скрывается статусом S0-001.

### S0-002 — Снимок архитектурных контрактов

Статус: `VERIFIED`

Implementation commit: `8f27dc086aaca381f47d965c82f3a849e5fff493`, опубликован в `origin/main`.

Создать генерируемые/проверяемые inventories:

- routes: method/path/handler/auth policy/process role;
- tasks/workers: persistence, owner, startup, watchdog, recovery;
- schema/index/foreign-key snapshot;
- external integrations and secrets source;
- frontend entrypoints/API callers/static shells;
- listener/port ownership: `8000` API, `8001` Qwen ASR, `8188` ComfyUI, `11434` Ollama; незарегистрированный full-app listener считается ошибкой;
- file-size and symbol thresholds;
- release manifest baseline.

CI/verify должны падать при неописанном admin route, новом legacy auth consumer, незарегистрированном worker или рассинхронизации generated map.

Результат:

- `architecture/contract.json` стал reviewed semantic source для route exceptions, пяти legacy identity consumers, восьми `create_task` registrations, десяти integrations, frontend/static entrypoints, process/listener ownership и line/symbol budgets;
- `tools/generate_architecture_inventory.py` выполняет только AST/source scan, не импортирует `backend.main`, не открывает DB/media/network и детерминированно создаёт JSON/Markdown artifacts;
- inventory фиксирует 221 route с ролью `all-dev-current-monolith`, 4 постоянных worker, 4 ephemeral task, 52 объявленные SQLite table, 84 index, 0 foreign-key declaration, 102 имени environment inputs, 10 integrations и 25 нормализованных frontend/static API literals;
- read-only live schema comparison подтвердил все 52 объявления; дополнительные 5 live tables — штатные FTS5 shadows `images_search_*`, missing live table нет;
- secret inventory содержит только имена переменных и описание DPAPI/env source, значения secrets не сохраняются;
- `check-runtime-listeners.ps1` read-only проверяет 5173/8000/8001/8188/11434 и запрещает Python `uvicorn main:app` на любом порту, кроме зарегистрированного API 8000;
- runtime snapshot: один full-app process, API PID 26004 на 8000, Qwen ASR 8001 свободен, ComfyUI 8188 и Ollama 11434 принадлежат ожидаемым процессам; Ollama wildcard bind оставлен явным warning;
- `verify.ps1` запускает inventory drift check во всех режимах, runtime ownership только локально и никогда в CI; оба новых test modules входят в Quick и Full;
- focused architecture/verify tests: 19 passed, повторено 5/5; generator drift + live listener ownership: 5/5; Quick verifier: 56 passed;
- Full verifier: 1461 passed, 92 известных deprecation warnings за 373.16 s; ESLint, TypeScript/Vite production build, origin isolation и studio resilience E2E — PASS; общий verifier 424.89 s;
- GitHub CI на exact SHA `8f27dc0`: run `29602448159`, job `87957576637`, conclusion `success`; runner выполнил checkout/setup/install и полный `verify -Mode CI`, включая оба generated-map checks, 1461 tests/92 warnings, lint, TypeScript/Vite build, origin isolation и resilience E2E; verifier 1439.47 s, job 25m45s;
- live media snapshot до/после совпал: 129 files, 1 684 488 bytes, SHA-256 `E2232B6F56094FA00D6D6FAA495D1FCFB240CE133207B903636F5A299428AC04`;
- API/schema/auth behavior не менялся, миграции и restart/deploy не требовались; `/api/health` и `/api/version` после gate вернули HTTP 200;
- rollback code point: `a5474f8`; для отката S0-002 достаточно revert `8f27dc0`, production process не переключался;
- residual risks переданы по владельцам: immutable release identity — ENV-001, process roles/lifespan — ROLE-001, foreign keys/repository boundary — DB wave, Ollama loopback — OPS hardening.

## 9. Волна A — release truth и безопасный локальный production

### ENV-001 — Production identity gate

Приоритет: P0. Статус: `READY`.

- единый `release-manifest.json`: git SHA, dirty=false, build time, frontend asset manifest hash, Python/Node versions, schema compatibility range;
- backend `/api/version` берёт только этот manifest;
- frontend показывает/отправляет свой exact build ID;
- production startup запрещён при `APP_ENV != production`, unknown frontend build, dirty release или global Python вне разрешённого runtime;
- public health не раскрывает детали; подробный status только trusted admin;
- smoke сравнивает backend и frontend release IDs.

### CI-001 — Восстановить выполняющийся CI

Приоритет: P0. Статус: `IN PROGRESS`; внешний GitHub billing/spending blocker снят, exact-SHA run `29602448159` успешно выполнил все steps.

- подтверждено: job `87957576637` получил Windows runner и выполнил все steps на `8f27dc0`;
- сохранить exact-SHA artifact с test counts и manifests;
- вернуть безопасный запас относительно 30-minute timeout без ослабления full gates;
- добавить dependency audit, secret scan и lightweight SAST;
- security/payment/video/profile browser suites распределить на обязательные jobs;
- пока branch protection недоступен, `tools/verify.ps1 -Mode CI` + receipt обязательны перед release;
- не делать repository public автоматически.

### REL-001 — Fail-closed publisher

Приоритет: P0.

- убрать обычный `-SkipVerify` из `start-public.bat`;
- любое TypeScript/build/test failure блокирует публикацию;
- break-glass допускается только отдельной явно названной командой, с причиной, operator, timestamp и audit log;
- candidate создаётся в новом immutable release directory;
- manifest активного release меняется только после candidate smoke;
- failed candidate удаляется/карантинируется без изменения active release;
- rollback — отдельная протестированная команда.

### EDGE-001 — Caddy вместо Vite Preview

Приоритет: P1, после REL-001.

- зафиксировать текущий local FRP ingress contract без изменения VPS;
- Caddyfile: frontend root, `/api` proxy, protected media routing, legacy routes;
- compression, cache policy для hashed assets, no-cache для HTML;
- security headers, request body limits, controlled upstream timeouts;
- trusted proxy/header boundary: origin недоступен извне в обход edge;
- structured access/error logs с rotation;
- config validate + local Host/TLS/header smoke;
- Vite Preview удалить из production launcher, оставить dev/preview only.

### REL-002 — API A/B switch и rollback

Приоритет: P1.

- два локальных API slots на разных loopback ports;
- candidate API запускается с `IZO_PROCESS_ROLE=api` и без workers;
- smoke candidate напрямую;
- `caddy validate`, atomic reload upstream/root;
- старый API остаётся на drain/rollback window;
- workers переключаются на тот же exact release SHA после API switch;
- incompatible migration не совмещается с switch.

## 10. Волна B — security и identity closure

### SEC-001 — Удалить legacy trust из protected surface

Приоритет: P0.

- заменить прямой legacy `require_admin` в runtime health route trusted admin dependency;
- AST/route inventory запрещает `request_user_id`, `X-OneNode-User`, mutable JS identity cookie и legacy admin dependency в protected handlers;
- Telegram и MAX принимаются только после криптографической/серверной верификации init data;
- legacy helpers сначала перестают иметь consumers, затем удаляются отдельным пакетом;
- negative tests: spoofed headers/cookies/initData, inactive/banned/deleted session, admin downgrade.

### SEC-002 — CSRF, Origin и public diagnostics

Приоритет: P0/P1.

- для unsafe cookie-auth methods проверять Origin по точному allowlist и/или synchronizer CSRF token;
- не полагаться только на CORS;
- webhook routes не используют browser session и имеют отдельную защиту;
- разделить `/livez`, `/readyz` и trusted `/api/admin/runtime-health`;
- public health возвращает только минимальный status/version;
- убрать из public response DB size/counts, internal service URLs и environment details;
- rate/body limits для auth/payment/public mutation endpoints;
- security headers тестируются через Caddy smoke.

### SEC-003 — Secret lifecycle

Приоритет: P1.

- inventory всех required/optional secrets без значений;
- ACL and source tests для DPAPI/env;
- rotation/revocation runbook по YooKassa, SMTP, bots, OpenRouter;
- redaction tests для exceptions/logs/admin APIs;
- migration-to-new-PC checklist: секреты вводятся заново, validation выполняется без реального списания;
- backup не содержит расшифрованных secrets.

## 11. Волна C — деньги, платежи и юридические обязательства

Эта волна выполняется до широкого backend split. Все tests используют fake provider; реальный платёж не создаётся автоматически.

### PAY-001 — Надёжный checkout при неопределённом исходе

Приоритет: P0.

Новая state machine минимум:

```text
new -> creating -> pending -> paid
                  |          |
                  |          `-> refund_pending -> refunded/partially_refunded
                  `-> ambiguous -> reconciled_pending/paid/canceled/manual_review
```

- локальный idempotency key уникален и хранится до вызова provider;
- повтор provider create выполняется с тем же YooKassa idempotency key и теми же параметрами;
- network timeout после отправки не переводит payment окончательно в failed/canceled;
- retry восстанавливает `provider_payment_id` из повторного idempotent create/result;
- mismatch параметров по тому же key блокируется;
- reconciler ищет и закрывает ambiguous/creating records;
- webhook без локальной связи сохраняется как orphan provider event для reconciliation, не теряется;
- тесты: crash before call, after remote create, before local attach, repeated request, webhook-first, amount/currency mismatch.

YooKassa документирует повтор результата при одинаковом idempotency key и параметрах в пределах срока хранения ключа; реализация должна опираться на этот контракт, не изобретая локальное «успех/ошибка» из сетевого timeout.

### PAY-002 — Webhook ingress hardening

Приоритет: P0.

- жёсткий body-size limit и schema validation;
- current YooKassa IP ranges применяются только за корректной trusted-proxy boundary;
- главным подтверждением денег остаётся server-to-server fetch текущего payment;
- быстрый HTTP 200 только после durable inbox write;
- повторная обработка event идемпотентна;
- retry/dead-letter/alert для failed handler;
- flood/rate tests не должны вызывать неограниченный provider API/DB load;
- raw payload redacted и хранится по retention policy.

### PAY-003 — Provider refund state machine

Приоритет: P0/P1.

- YooKassa refund создаётся через provider API с отдельным idempotency key;
- local token/money effects происходят только по подтверждённому status;
- `refund_pending`, `succeeded`, `canceled`, partial refund и ambiguous outcome;
- reconciliation и manual review;
- запрет «локально пометить refunded» без provider confirmation;
- audit link payment-invoice-refund-ledger-fiscal obligation.

### FISCAL-001 — НПД/чек как durable obligation

Приоритет: P0 operational/legal.

Добавить таблицу/модель обязательств:

- payment/refund link;
- obligation type `sale|refund`;
- status `required|created|sent|confirmed|overdue|manual_review`;
- legal due timestamp;
- receipt reference/URL/amount/customer contact;
- created/sent/confirmed timestamps and operator;
- retry/reminder/escalation evidence.

Admin queue показывает просрочку. Нельзя считать payment workflow полностью завершённым без закрытого fiscal status. Код не заменяет консультацию бухгалтера/юриста; перед ростом проводится отдельная проверка соответствия режиму НПД и 54-ФЗ.

### BILL-001 — Token ledger v2

Приоритет: P0.

- immutable ledger rows;
- unique `operation_key`;
- explicit `entry_type`, `source_type`, `source_id`, `reversal_of`, `currency/amount` where applicable;
- DB unique constraint на первичную операцию и reversal;
- balance изменяется в той же transaction, что ledger entry;
- никаких JSON `LIKE` для financial idempotency;
- отрицательный баланс/лимит защищён atomic conditional update или locked transaction;
- migration backfill с audit report и без удаления старых данных.

### BILL-002 — Единый BillingService

Приоритет: P0.

Через один transaction boundary проходят:

- reserve/charge/refund generation tokens;
- payment credit/tariff extension;
- manual invoice paid;
- admin adjustment;
- refund/reversal;
- daily usage update.

Запрещаются прямые финансовые SQL writes из route handlers и unrelated services. Architecture test проверяет allowlist modules.

### BILL-003 — Reconciliation и финансовый audit

Приоритет: P0/P1.

- периодический provider payment/refund reconciliation;
- ledger sum vs materialized balance;
- paid payment vs granted entitlement;
- invoice/payment/provider event consistency;
- fiscal obligation completeness;
- immutable audit event для admin operation;
- read-only daily report и alert на mismatch;
- repair только отдельной idempotent command с dry-run/approval/evidence.

Concurrency gate: минимум 50 параллельных повторов сценариев charge/refund/payment completion на временной БД; каждое logical operation даёт ровно один effect.

## 12. Волна D — фоновые задания и process roles

### QUEUE-001 — Worker survival contract

Приоритет: P0.

- весь queue item lifecycle заключён в `try/except/finally`;
- `task_done` вызывается ровно один раз;
- parse/runtime-build failure помечает job retry/failed и не убивает consumer;
- сохраняется task handle;
- done callback пишет structured fatal event;
- watchdog перезапускает consumer с bounded backoff;
- health отражает age последнего heartbeat, backlog, oldest item, active item;
- startup recovery не создаёт duplicate execution.

### QUEUE-002 — Durable SQLite claims

Приоритет: P0/P1.

Унифицированные поля/семантика для generation, feed publication, notifications и reconciliation:

- status, priority, attempt/max_attempts;
- `available_at`;
- `lease_owner`, `lease_expires_at`, heartbeat;
- idempotency/operation key;
- last error class/message (redacted);
- created/started/completed timestamps;
- dead-letter/manual retry.

Claim выполняется атомарно. Просроченный lease безопасно возвращается в очередь. In-memory `asyncio.Queue` может остаться ускорителем, но не единственным источником правды.

### VIDEO-001 — Server-side VideoReconciler

Приоритет: P0/P1.

- pending/running video jobs опрашиваются worker, а не только GET route;
- bounded provider polling/backoff;
- finalization/media persistence/refund идемпотентны;
- browser history read больше не отвечает за correctness;
- orphan provider video audit;
- health/metrics/alerts по oldest pending и repeated failure.

### NOTIFY-001 — Outbox worker

Приоритет: P1.

- автоматический worker обрабатывает email/in-app events;
- existing lease semantics проверяются и унифицируются;
- retry schedule, permanent failure, dead-letter, manual replay;
- delivery result/provider message ID;
- pending outbox участвует в readiness/admin health;
- существующие pending rows обрабатываются только после dry-run/inventory.

### ROLE-001 — App factory, lifespan и роли

Приоритет: P1.

- `create_app(settings, dependencies)` вместо import-time global orchestration;
- FastAPI lifespan вместо deprecated `on_event`;
- `IZO_PROCESS_ROLE=api|generation-worker|video-worker|feed-worker|notification-worker|all-dev`;
- production API не запускает workers;
- candidate smoke process не потребляет production queue;
- dev/test могут использовать `all-dev` только на временных roots;
- startup сверяет process role и listener ownership; full app с live DB не может занять зарезервированный для Qwen ASR порт 8001;
- preflight/candidate API запускается с отключёнными bot polling и background workers;
- graceful shutdown перестаёт принимать jobs, завершает/освобождает leases.

### OPS-001 — Windows Services

Приоритет: P1.

- pinned wrapper binary/checksum/config in operations artifact, не секрет;
- dependency/order: data mounts -> API/workers -> Caddy where appropriate;
- automatic restart with backoff, max restart alarm;
- stdout/stderr log rotation;
- service account rights documented;
- reboot rehearsal: services, DPAPI, ComfyUI/Ollama dependencies, health;
- uninstall/rollback procedure.

## 13. Волна E — данные и миграции

### DB-001 — Нумерованные migrations

Приоритет: P1, до новых сложных schema changes.

- один migration ledger с version/name/checksum/applied_at/duration;
- migration files immutable после применения;
- plan/apply/verify commands;
- startup только проверяет compatibility; тяжёлые rebuild не выполняются незаметно;
- expand/contract: сначала additive schema, затем backfill, затем code switch, потом отдельное cleanup release;
- production apply требует snapshot/verify и disk-space preflight;
- каждая migration проверяется на копии production schema/data profile.

### DB-002 — Constraints и ссылочная целостность

Приоритет: P1.

- полный orphan audit;
- unique/NOT NULL/check constraints сначала на новые writes;
- selective foreign keys вводятся после cleanup/backfill;
- delete/cascade semantics прописываются, не выбираются по умолчанию;
- финансовые записи не каскадно удаляются;
- user deletion становится state/anonymization workflow.

### DB-003 — Repository boundaries

Приоритет: P1.

- route/service не открывает произвольные connections;
- repositories по domains, transaction передаётся явно;
- SQLite-specific SQL локализован;
- row-to-domain mapping тестируется;
- будущий PostgreSQL adapter возможен без переписывания HTTP handlers.

### DATA-001 — Media ownership, privacy и retention

Приоритет: P1.

- классификация: private original/input, generated private, published derivative, admin/support accessible, temporary/provider artifact;
- private media не раздаётся через бесконтрольный static route;
- authorization проверяет owner/admin/support purpose;
- admin viewing логируется;
- published feed использует отдельные derivatives, а не private originals;
- retention по типу данных: срок, основание, delete/anonymize, legal hold;
- пользователь получает понятный delete/export contract;
- orphan cleanup только dry-run -> protected allowlist -> backup -> apply -> report.

Продуктовое решение уже принято: администратор может видеть оригинал для поддержки. Это требует audit log и purpose limitation, а не запрета доступа.

## 14. Волна F — декомпозиция backend

### 14.1. Правило декомпозиции

Не делить файл по количеству строк механически. Выделять вертикальный domain slice с tests и dependency direction.

Целевая структура:

```text
backend/app/
  bootstrap/          # settings, app factory, lifespan, wiring
  http/               # routers, dependencies, errors, schemas
  identity/           # sessions, Telegram/MAX/Web identity, admin policy
  billing/            # ledger, entitlements, invoices
  payments/           # YooKassa checkout/webhook/refund/reconcile
  generation/         # jobs, orchestration, adapters, queue
  video/              # jobs, provider adapters, reconciler
  media/              # paths, authorization, variants, retention
  feed/               # publication, reactions, views, presentation
  gallery/            # private gallery queries/commands
  notifications/      # outbox and transports
  bots/               # Telegram/MAX transport adapters
  admin/              # admin use cases/queries
  db/                 # connection, unit of work, migrations
  observability/      # logging, metrics, health
```

Dependency direction:

```text
router -> application service -> domain/repository port -> adapter
```

Запрещено:

- domain import из `main.py`;
- циклические импорты;
- route-to-route calls;
- финансовый SQL вне billing/payment repositories;
- import-time запуск task/thread/network/DB migration;
- скрытые globals, которые нельзя заменить в test.

### 14.2. Порядок пакетов backend

Каждый пункт — отдельная серия небольших коммитов, не один mega-commit.

| ID | Slice | Сначала выносится | Exit criterion |
|---|---|---|---|
| ARCH-001 | Guardrails | dependency rules, size/symbol diff budget | новые нарушения блокируются |
| DOM-BILL | billing/payments | после Волны C уже сформированные services/repos | routes — тонкие adapters |
| DOM-IDENT | identity/auth | trusted dependencies, session service, adapters | legacy consumers 0 |
| DOM-QUEUE | job infrastructure | claim/lease/watchdog/health | workers используют общий contract |
| DOM-VIDEO | video | provider, reconciler, finalize/refund | GET routes read-only по lifecycle |
| DOM-GEN | generation | request validation, orchestration, adapters | ComfyUI/OpenRouter behind ports |
| DOM-MEDIA | media/gallery | path/auth/variants/retention | private/public boundary доказана |
| DOM-FEED | feed | queries, reactions, publication worker | static shell API contract tested |
| DOM-NOTIFY | notifications | outbox/transports | no delivery logic in routes |
| DOM-BOTS | Telegram/MAX | verified identity + transport | no auth fallback |
| DOM-ADMIN | admin | read models/use cases/routers | no business SQL in handlers |
| ROUTER-001 | router registration | all APIRouters | `main.py` has no endpoints |
| BOOT-001 | bootstrap | settings/app/lifespan/wiring | `main.py` compatibility shim only |

### 14.3. Size budgets

Budgets — guardrail, не цель любой ценой:

- route module: обычно <= 400 строк;
- application service: обычно <= 500 строк;
- repository/adapter: обычно <= 500 строк;
- schema module: обычно <= 400 строк;
- test module: обычно <= 800 строк;
- `main.py` конечная цель: <= 300 строк bootstrap/compatibility;
- временное превышение требует documented waiver с owner и removal package.

После каждого переноса сравниваются route inventory, response snapshots, auth matrix и focused behavior tests. Массовое переименование и изменение поведения в одном переносе запрещено.

## 15. Волна G — frontend и static shells

### FE-001 — Настоящий test/API foundation

Приоритет: P1.

- единый typed API client;
- единая обработка credentials/errors/retry/request ID;
- запрет прямого `fetch` вне adapters через lint/architecture rule;
- Vitest + React Testing Library для unit/component tests;
- существующий `editPrompt.test.ts` включить в реальный runner;
- MSW/fake server для contract cases;
- Playwright suites разделить на smoke/security/payment/profile/video/feed;
- CI публикует traces/screenshots только при failure.

### FE-002 — Разделить `newUi.tsx`

Порядок:

1. types/contracts and adapters;
2. pure mapping/formatting functions;
3. query/mutation hooks;
4. studio state machine/controller;
5. generation panels by mode;
6. history/gallery/feed dock;
7. overlays/modals/toasts;
8. page composition.

Нельзя одновременно с переносом менять визуальное поведение. Сначала parity tests/snapshots, потом отдельный UX commit.

### FE-003 — Разделить CSS

- tokens/base остаются глобальными;
- layout shell отдельно;
- feature styles рядом с feature;
- responsive rules рядом с owning component;
- удалить дубли только после computed-style/visual snapshot comparison;
- z-index, breakpoints, spacing и colors переводятся в documented tokens;
- style budget и duplicate selector report входят в CI advisory, затем gate.

### FE-004 — Устранить drift static shells

`/feed` и `/gallery` сейчас отдельны от React build. Выбрать и реализовать один путь:

- предпочтительно: единый shared shell/assets/contracts;
- затем: перенос routes в основной frontend, если SEO/performance/behavior сохраняются;
- до миграции: общий header/footer component build artifact и shell regression tests;
- изменения TopBar/navigation считаются незавершёнными, пока проверены React, feed и gallery shells.

### FE-005 — Legacy removal

- traffic telemetry;
- parity matrix;
- redirects/deep-link contract;
- 30-day zero-use window;
- deletion package с bundle-size/report и rollback release;
- удалить legacy CSS/API adapters только после entrypoint removal.

## 16. Волна H — observability, performance и recovery

### OBS-001 — Structured telemetry

- JSON logs: timestamp, level, release SHA, process role, request/job/payment correlation ID;
- secrets/tokens/personal data redaction;
- metrics: request rate/error/latency, DB write latency/busy, queue depth/age, worker heartbeat/restart, provider latency/errors, payment reconciliation mismatch, disk/backup age;
- admin health показывает dependencies без секретов;
- alerts имеют owner, threshold, runbook и suppression rule;
- logs rotate and have retention.

### PERF-001 — Измеряемая оптимизация

Сначала baseline, затем index/query/cache:

- `ensure_rate_limit` заменить Python scan всех jobs на indexed SQL aggregate;
- slow query log и `EXPLAIN QUERY PLAN` для top endpoints;
- indexes по реально измеренным filters/order;
- feed/gallery pagination cursor, без unbounded reads;
- media variants/cache headers;
- frontend bundle analysis and route/feature lazy loading;
- load profile: read-heavy, concurrent generation submission, admin+feed, webhook flood;
- не запускать destructive/load tests против production.

### DR-001 — Backup/restore/standby readiness

- исправить failing backup health task, не скрывать code 2;
- daily automated manifest verification;
- restore rehearsal по расписанию;
- измерять RPO/RTO;
- second physical disk capacity/health alert;
- encrypted offsite preflight and completed marker;
- standby runbook включает runtimes/models/secrets/Caddy/services;
- quarterly controlled failover rehearsal;
- readiness объявляется только после успешного restore + app smoke на восстановленной копии.

### SCALE-001 — Решение о Linux/Docker/PostgreSQL по метрикам

Ежемесячный capacity review:

- active users/concurrency;
- GPU utilization/queue wait;
- API p95/p99/error rate;
- SQLite busy/write latency/size;
- disk growth and backup duration;
- operator hours/restart incidents;
- cost forecast.

Результат review: `stay single-node`, `split GPU worker`, `move application to Linux`, `move DB to managed PostgreSQL` или комбинация с датой и evidence. Миграция не запускается по абстрактному числу пользователей.

## 17. Порядок реализации и зависимости

```text
S0-001 current WIP green
  -> S0-002 inventories
  -> ENV-001 + CI-001 + REL-001
  -> SEC-001/002
  -> PAY-001/002/003 + FISCAL-001 + BILL-001/002/003
  -> QUEUE-001/002 + VIDEO-001 + NOTIFY-001
  -> ROLE-001
  -> EDGE-001 + OPS-001
  -> REL-002 A/B
  -> DB-001/002/003 + DATA-001
  -> backend domain slices
  -> frontend foundation/slices/static convergence
  -> observability/performance/DR/scaling continuously
```

Допустимая параллельность:

- CI billing fix может идти параллельно S0;
- documentation/inventories read-only могут идти параллельно;
- маленькая UI lane допускается по разделу 18;
- payment/schema/queue/release changes друг с другом не смешиваются;
- два пакета не редактируют один ownership area одновременно.

## 18. Параллельные маленькие продуктовые и визуальные правки

Разрешены, если они:

- не меняют DB schema, auth, billing, payment, worker lifecycle и release pipeline;
- не меняют API contract без contract test;
- не редактируют файлы активного transformation package;
- проходят frontend build, relevant unit/e2e и static shell checks;
- имеют отдельный commit;
- после merge transformation branch/release baseline обновляется через rebase/merge и повторный gate.

Если визуальная правка затрагивает shared topbar, она проверяется минимум на main React UI, `/feed` и `/gallery`. «На одной странице выглядит правильно» недостаточно.

## 19. Тестовая стратегия

### 19.1. Пирамида

- pure unit tests: mappings, state machines, financial math;
- repository tests на временной SQLite;
- service tests с fake providers;
- API contract/auth matrix;
- worker crash/recovery/concurrency tests;
- frontend component tests;
- Playwright end-to-end;
- release/rollback/restore rehearsals;
- controlled load tests в изолированном environment.

### 19.2. Обязательные suites по рискам

| Риск | Обязательная проверка |
|---|---|
| Деньги | idempotency, concurrency, crash points, reconciliation, immutable audit |
| Auth | negative spoof matrix, CSRF/Origin, session lifecycle, admin downgrade |
| Queue | exception at every stage, lease expiry, duplicate delivery, restart |
| Video | browser absent, provider delays/failure, finalization exactly once |
| Release | candidate failure, Caddy invalid config, API crash, rollback |
| Backup | verify + isolated restore + application smoke |
| Decomposition | route/symbol/schema snapshots and import rules |
| UI | build, component contract, browser smoke, shared-shell visual checks |

### 19.3. Повторные проверки

- focused regression после change: минимум 1;
- для критического изменённого алгоритма перед commit: **5 последовательных зелёных повторов**;
- financial/lease concurrency: минимум 50 controlled iterations;
- full local gate: минимум 1 на commit candidate;
- после restart/deploy: smoke + observation window;
- flaky test считается дефектом, а не «ещё раз перезапустили до зелёного».

### 19.4. Запреты

- никаких реальных YooKassa списаний в автоматических tests;
- никаких provider emails/messages без explicit sandbox recipient;
- никаких tests против production DB/media;
- никаких load tests на live ComfyUI/API;
- никакого утверждения «CI зелёный», если GitHub job не стартовал.

## 20. SLO и инженерные показатели

Начальные цели уточняются после двух недель baseline telemetry:

| Показатель | Начальная цель |
|---|---|
| Public API availability | >= 99.5% monthly на single-node stage |
| API error rate | < 1% excluding validated user errors |
| API p95 | < 500 ms для non-generation endpoints |
| Worker heartbeat age | < 60 s |
| Queue oldest runnable age | threshold по типу queue, alert before user-visible SLA breach |
| Financial mismatch | 0; любое расхождение alert/manual review |
| Duplicate financial effect | 0 |
| Backup RPO | <= 15 min для DB после подтверждения schedule |
| Restore RTO | сначала измерить; целевая граница фиксируется после rehearsal |
| Offsite freshness | <= 24 h после реального включения и health green |
| Release rollback | < 5 min, затем уменьшить после A/B |

GPU generation time не смешивается с API latency: отдельно измеряются queue wait и provider/runtime duration.

## 21. Definition of Done всей программы single-node hardening

Программа текущего Windows stage завершена, когда одновременно:

- release exact SHA воспроизводим, проверен и откатывается;
- Caddy заменил Vite Preview в production;
- процессы автоматически запускаются и восстанавливаются после reboot/crash;
- public health минимален, detailed health защищён;
- legacy protected auth consumers отсутствуют; CSRF/Origin policy проверяется;
- payment checkout/refund/webhook/reconcile устойчивы к crash/retry;
- ledger и все финансовые mutation атомарны и уникальны;
- fiscal obligations видимы, не просрочены молча и имеют evidence;
- generation/video/feed/notification workers durable и supervised;
- schema изменяется только numbered migrations;
- backup health зелёный, restore и offsite реально проверены;
- `main.py` — bootstrap shim, domains имеют ownership/repositories/tests;
- frontend имеет unit runner, typed API client и разделённые features;
- static shells не дрейфуют;
- полный local/CI gate зелёный на exact deployed commit;
- dashboards/alerts/runbooks позволяют владельцу понять и восстановить систему.

Это не означает, что Linux/PostgreSQL уже обязательны. Их readiness определяется `SCALE-001`.

## 22. Точный ближайший блок

Следующий исполняемый блок после завершённого Gate 0:

1. **ENV-001:** устранить `development/global Python/unknown frontend build` drift только с готовым rollback;
2. **CI-001:** закрепить реально выполняющийся exact-SHA CI и сохраняемый verification artifact;
3. **REL-001:** fail-closed immutable publisher;
4. затем начинать **SEC-001**, а не произвольный большой перенос строк из `main.py`.

Первый backend domain extraction после P0 foundation — billing/payments, потому что новые изменения оплаты уже сформировали естественную границу и требуют самых строгих инвариантов.

## 23. Отчётность по каждому пакету

В этом документе или отдельном linked checkpoint фиксируются:

- ID/status/date/commit;
- что было доказано до изменения;
- изменённые файлы;
- schema/API/auth/task impact;
- exact test commands/counts/repeats;
- CI run ID и действительно выполненные steps;
- backup/restart/deploy needed/actual;
- live smoke без персональных данных;
- rollback command/result;
- discovered follow-ups;
- остаточный риск.

Статусы: `BLOCKED`, `READY`, `IN PROGRESS`, `CODE COMPLETE`, `DEPLOYED`, `VERIFIED`, `SUPERSEDED`. `CODE COMPLETE` не равен `VERIFIED`.

## 24. Официальные технические основания

- SQLite допускает много readers, но одновременно только одного writer; `BEGIN IMMEDIATE` начинает write transaction заранее: <https://www.sqlite.org/lang_transaction.html>.
- FastAPI рекомендует lifespan; `startup`/`shutdown` events являются устаревающей альтернативой: <https://fastapi.tiangolo.com/advanced/events/>.
- Vite прямо определяет `vite preview` как локальный preview build, а не production server: <https://vite.dev/guide/static-deploy>.
- YooKassa idempotency/interaction contract: <https://yookassa.ru/developers/using-api/interaction-format>.
- YooKassa webhook delivery/authentication guidance: <https://yookassa.ru/developers/using-api/webhooks>.
- YooKassa refunds: <https://yookassa.ru/developers/payment-acceptance/after-the-payment/refunds>.
- ФНС, вопросы НПД и чеков: <https://npd.nalog.ru/faq/>.
- Caddy installation/service guidance: <https://caddyserver.com/docs/install> и <https://caddyserver.com/docs/command-line>.
- WinSW Windows service wrapper: <https://github.com/winsw/winsw>.

## 25. Журнал актуализации

| Дата | Изменение |
|---|---|
| 2026-07-17 | Новый source of truth построен после аудита текущего worktree, live runtime/DB, CI, payments, queues, auth, frontend и предоставленных исследований. Старый roadmap переведён в historical status. |
| 2026-07-17 | S0-001 завершён и проверен на repository baseline `0acb299` / production code baseline `13c8216`: WIP разделён на продуктовые commits, full/focused/frontend gates зелёные, controlled restart и live smoke выполнены; S0-002 переведён в READY. |
| 2026-07-17 | В live observation найден и graceful остановлен orphan backend на Qwen ASR порту 8001; duplicate Telegram polling прекратился. В S0-002/ROLE-001 добавлены listener ownership и process-role guards. |
| 2026-07-17 | S0-002 завершён в `8f27dc0`: semantic contract, детерминированные route/auth/task/schema/integration/frontend/release inventories, size/symbol budgets и read-only listener ownership встроены в Quick/Full/CI; focused ×5, полный local gate и exact-SHA GitHub run `29602448159` зелёные, прежний billing blocker снят, Gate 0 закрыт, следующий пакет ENV-001. |
