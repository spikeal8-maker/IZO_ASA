---
status: canonical
domain: image-generation
read_when: ["image-generation","text-to-image","image-to-image","generation-jobs"]
source_paths: ["backend/app/services/generation_jobs.py","backend/app/services/generation_queue.py","backend/app/services/generation_recovery.py","backend/app/services/generation_results.py","backend/app/services/generation_worker.py","frontend/src/phone/features/image/api.ts"]
test_paths: ["backend/test_generation_jobs_characterization.py","backend/test_generation_protection.py","backend/test_generation_recovery_wiring.py","backend/test_services_generation_jobs_module.py","backend/test_services_generation_queue_module.py","backend/test_services_generation_results_module.py","backend/test_services_generation_worker_module.py","frontend/phoneImage.test.ts"]
related_domains: ["frontend-studio","video-gallery-feed","chat"]
forbidden_paths: ["unknown"]
owner: image-generation-platform
context_role: scoped-domain-map
updated: 2026-09-19
---
# Context: генерация изображений

## Назначение

Эта карточка задаёт bounded-контекст для генерации изображений: от создания задания до materialized result.
Она не описывает весь интерфейс студии и не дублирует `frontend-studio`.
Для layout, paint, profile и общего shell сначала используется соответствующий соседний domain.

## Владение

- `backend/app/services/generation_jobs.py` владеет жизненным циклом generation job.
- `backend/app/services/generation_queue.py` владеет постановкой и выборкой заданий из очереди.
- `backend/app/services/generation_worker.py` владеет worker execution boundary.
- `backend/app/services/generation_recovery.py` владеет восстановлением незавершённых заданий.
- `backend/app/services/generation_results.py` владеет materialized result.
- `frontend/src/phone/features/image/api.ts` является клиентской точкой входа phone image flow.
- UI не является источником истины для durable job state.

## Основные точки входа

Начинать с ближайшего к симптомам слоя, а не читать весь generation stack.

1. Job state — `backend/app/services/generation_jobs.py`.
2. Queue behavior — `backend/app/services/generation_queue.py`.
3. Worker behavior — `backend/app/services/generation_worker.py`.
4. Recovery — `backend/app/services/generation_recovery.py`.
5. Materialized result — `backend/app/services/generation_results.py`.
6. Phone request/client contract — `frontend/src/phone/features/image/api.ts`.

## Границы

- Генерация изображения и визуальный shell студии имеют разное владение.
- Изменение generation service не даёт права менять `frontend-studio`.
- Очередь и worker являются отдельными failure boundaries.
- Recovery не создаёт второй независимый lifecycle.
- Materialized result не означает автоматическую публикацию в feed/gallery.
- UI optimistic state не подтверждает durable state.
- Provider/model availability является runtime evidence, а не фактом из source.
- Production media не используется как test fixture.
- Provider calls не выполняются ради проверки этой карточки.

## Жизненный цикл задания

Нормальный маршрут рассматривается как последовательность контрактов.

1. Клиент формирует запрос на генерацию.
2. Backend создаёт или обновляет generation job по существующему contract.
3. Job становится доступен queue только в допустимом состоянии.
4. Worker забирает работу через существующий queue boundary.
5. Worker завершает работу или фиксирует ошибочное состояние.
6. Result layer материализует подтверждённый результат.
7. UI читает состояние через API и не подменяет backend truth.

Каждый переход проверяется отдельно.
Наличие финального изображения само по себе не доказывает корректность предыдущих переходов.

## Очередь и worker

Queue отвечает за порядок и доступность работы.
Worker отвечает за выполнение уже выбранной работы.
Исправление worker не должно незаметно менять queue ownership.
Исправление queue не должно обходить job-state protection.
Повторное получение задания должно сохранять существующие idempotency и ownership semantics.

## Recovery

Recovery работает только с состояниями, которые уже существуют в canonical lifecycle.
Он не должен создавать конкурирующий источник истины.
При сбое важно различать:
- job ещё не был взят worker;
- worker начал работу;
- result уже materialized;
- ответ клиенту был потерян;
- состояние требует безопасной повторной оценки.

Реальный crash/restart scenario требует отдельного runtime evidence.

## Materialized result

`generation_results.py` фиксирует слой результата.
Этот слой не равен feed/gallery publication.
Если задача касается показа результата в gallery или feed, дополнительно нужен domain `video-gallery-feed`.
Если задача касается только studio composition, дополнительно нужен `frontend-studio`.

## Связь с frontend-studio

`frontend-studio` владеет shell, layout и пользовательской композицией студии.
Эта карточка владеет backend generation lifecycle и связанным client contract.
Не переносить UI state management в generation services и наоборот.

## Связь с video-gallery-feed

Publication, gallery visibility и feed policy находятся за отдельной границей.
Materialized generation result может быть входом в publication flow, но не является самим publication contract.

## Связь с chat

Если изображение запускается из chat flow, дополнительно использовать domain `chat`.
Chat остаётся владельцем chat tool/history/billing semantics.
Эта карточка не расширяет chat ownership.

## Focused tests

- `backend/test_generation_jobs_characterization.py`
- `backend/test_generation_protection.py`
- `backend/test_generation_recovery_wiring.py`
- `backend/test_services_generation_jobs_module.py`
- `backend/test_services_generation_queue_module.py`
- `backend/test_services_generation_results_module.py`
- `backend/test_services_generation_worker_module.py`
- `frontend/phoneImage.test.ts`

Сначала выбирать тесты слоя, который меняется.
Cross-layer изменение требует тестов каждого реально затронутого boundary.

## Safety

- Не запускать production worker.
- Не запускать production queue.
- Не выполнять production provider calls.
- Не использовать production media, credentials или secrets.
- Не считать configured provider доказательством его доступности.
- Не менять durable state вне отдельного runtime scope.

## Unknowns

- Фактическая доступность provider/model определяется runtime configuration.
- Worker capacity и очередь на production не выводятся из repository source.
- Crash ordering и recovery timing требуют отдельного operational evidence.
- Publication policy после materialized result может принадлежать соседнему domain.
- Экономика конкретной модели может принадлежать billing/admin layer.

Карточка предназначена для маршрутизации и границ, а не для истории проекта.