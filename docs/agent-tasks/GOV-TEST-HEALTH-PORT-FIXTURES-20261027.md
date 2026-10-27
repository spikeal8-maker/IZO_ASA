# Подготовка тестовых портов и продолжение review test-health

Контракт: [GOV-TEST-HEALTH-PORT-FIXTURES-20261027](../../tasks/GOV-TEST-HEALTH-PORT-FIXTURES-20261027.toml).
Основа: `0d134aa20cd0a1d1ca6828622fe6a435c74c415b`.
Это отдельный continuation package с новым владением; прежний Task Manifest
GOV-TEST-HEALTH-REVIEW-20261027 в него не переносится.

## Наблюдение и граница диагноза

[PR #252](https://github.com/spikeal8-maker/IZO_ASA/pull/252), exact
`da6d1046f3df3871c58c8bd9fcb13a81ff50fa64`, завершился с одним failed test:
`test_env_up_status_idempotent_down_and_cleanup`. Ошибка `PORT_IN_USE` возникла
в первом `env_up`; итог — 2296 passed, 1 failed, 1 skipped, 97 warnings, cleanup 0.
Источник: [run 40537045815](https://github.com/spikeal8-maker/IZO_ASA/actions/runs/40537045815),
job `122304990089`. Этот GitHub run остаётся FAILURE.

Фикстура использовала постоянный ID `PKG-LIFE`; штатный allocator всегда
выдаёт для него `56414/56415`. Временный Git worktree изолирует файлы и registry,
но TCP-порты принадлежат общей ОС. В тесте не было проверки доступности пары.
Та же зависимость от постоянных ID присутствовала в ready/runtime happy paths,
включая проверку локальных providers.

Локальная синтетическая проверка точного исходного теста воспроизвела отказ
при занятом собственным listener порте `56414`, затем `56415`. Собственный
«чужой» listener сохранился, частично занятый порт освободился, active state
не появился. Это подтверждает дефект изоляции фикстуры, но не устанавливает
историческую нативную причину Windows-сбоя.

Holder сворачивает любой socket `OSError` в `PORT_IN_USE`; injected `EADDRINUSE`
и `EACCES` дали одинаковый результат. Исходные errno/WinError и роль сокета
в CI не сохранены. Occupant, TIME_WAIT или excluded port поэтому не утверждаются.

## Подготовка фикстуры

[Общий test helper](../../tools/agent_env_test_ports.py) выбирает ID до создания
synthetic package. Каждый вызов получает новый namespace из 20 hex-символов UUID;
исходный prefix проверяется, затем его diagnostic label сокращается до 16 символов.
Весь ID ограничен 41 символом, последовательность кандидатов — 256.
Порты каждого кандидата вычисляет настоящий
`derive_candidate_ports`, поэтому identity, receipt и holder используют одну пару.

Оба порта должны быть меньше `49152`; занятые исключения и заранее выбранные
пары отбрасываются. Граница избегает стандартного Windows dynamic range
`49152–65535`, описанного в
[документации Microsoft](https://learn.microsoft.com/en-us/troubleshoot/windows-client/networking/tcp-ip-port-exhaustion-troubleshooting).
Она не утверждает настройки конкретного runner или отсутствие custom exclusions.

Оба IPv4 TCP-сокета одновременно проходят exclusive `bind` и `listen` на
`127.0.0.1`. Успешные, частично созданные и отказавшие probe-сокеты закрываются.
Исчерпание кандидатов даёт явную ошибку подготовки, а не skip или успешный тест.

После возврата helper порты уже освобождены. Между probe и запуском holder
остаётся окно гонки; решение не является атомарным резервированием. Реальный
`env_up` выполняется один раз на предусмотренный тестом шаг. Его ошибка
по-прежнему проваливает тест. Повторный вызов в тесте идемпотентности остаётся
самостоятельным проверяемым действием и не служит retry после ошибки.

## Сохранённое покрытие

ID выбирается явно перед фикстурой: `_single`, `_package` и `_active` не меняют
переданное имя. Временный worktree использует короткий basename `w`, чтобы
UUID не повторялся дважды в длинных Windows state paths. Два одновременно
активных пакета получают непересекающиеся пары до старта первого holder.
Оба старта находятся внутри existing cleanup boundary: отказ второго запуска
освобождает уже созданный первый holder и сохраняет исходную ошибку теста.

Deliberate collision test сначала подготавливает свободную пару, затем занимает
один порт собственным listener. Сохраняются прежние assertions: `PORT_IN_USE`,
ответ `FOREIGN` и освобождение частичной backend reservation. Stale recovery,
чужой PID, credential guards и runtime/application-ready assertions сохраняются.

Listener helpers перенесены из большого lifecycle test-файла в общий модуль.
Файл сокращается; новые helper и
[регрессии](../../tools/test_agent_env_port_fixtures.py) ограничены обычными
лимитами. Production allocator, lifecycle/runtime и gates в scope не входят.

## Унаследованное решение по долгам

[Предметный review #162–165](GOV-TEST-HEALTH-REVIEW-20261027.md) перенесён
как неизменённое доказательство из PR #252. Описанный в нём первоначальный
governance package — историческое происхождение review; текущую совокупную
проверку требует новый Task Contract выше.

Policy и review card должны побайтно совпадать с `da6d1046`. Относительно main
меняются только четыре `reason` и четыре `reviewBy`; deadline остаётся
**2026-10-30 включительно**. Владельцы, accepted baseline 97/1, все thresholds,
network/retry/process enforcement и открытый статус долгов сохраняются.

Исправление синтетических портов не меняет FastAPI lifecycle, TestClient,
cookie assertions или apply-secrets teardown из этих долгов. Оно не объявляет
долги исправленными и не продлевает уже согласованное окно.

## Проверка принятия

1. Exact-source diagnostic reproduction и полный diff; все прежние test
   assertions сохранены, runtime и allocator не изменены.
2. Focused helper regressions: backend/frontend bind/listen отказ, очистка
   partial/failed probe, bounded exhaustion, новый namespace, границы диапазона,
   disjoint pairs и распространение фактического `env_up` failure без retry;
   actual atomic diagnostic write с самым длинным fixture prefix и проверкой
   длины итогового/временного файла на Windows.
3. Реальный deliberate collision negative и affected Windows lifecycle,
   ready/runtime suites на точном candidate.
4. Неизменённые auditor tests и date controls: старая policy просрочена
   2026-10-27; новая действует до 2026-10-30; 2026-10-31 снова EXPIRED.
5. Policy/card equality с reviewed GOV, восемь scalar changes относительно main,
   canonical ownership/scope, file hygiene, независимое review и exact-head CI.

Локальные targeted результаты не заменяют Windows/hosted CI. До обязательных
проверок это candidate; Docker, production и operational acceptance этим
пакетом не заявляются. Откат ограничен его scoped файлами и сохраняет прежние
GitHub evidence и записи владения закрытого пакета.
