---
status: canonical
domain: image-generation
read_when: ["image-generation","text-to-image","image-to-image","generation-jobs"]
source_paths: ["backend/app/services/generation_admission.py","backend/app/services/generation_accounting.py","backend/app/services/generation_claims.py","backend/app/services/generation_leases.py","backend/app/services/generation_dispatch.py","backend/app/services/generation_bootstrap.py","backend/app/generation_worker.py","backend/app/integrations/generation_ipc.py","backend/app/services/generation_jobs.py","backend/app/services/generation_queue.py","backend/app/services/generation_recovery.py","backend/app/services/generation_results.py","backend/app/services/generation_worker.py","backend/app/services/generation_worker_persistence.py","frontend/src/phone/features/image/api.ts"]
test_paths: ["backend/test_generation_admission.py","backend/test_generation_claims.py","backend/test_generation_leases.py","backend/test_generation_dispatch.py","backend/test_generation_worker_process.py","backend/test_generation_worker_claims.py","backend/test_generation_jobs_characterization.py","backend/test_generation_protection.py","backend/test_generation_recovery_wiring.py","backend/test_services_generation_jobs_module.py","backend/test_services_generation_queue_module.py","backend/test_services_generation_results_module.py","backend/test_services_generation_worker_module.py","frontend/phoneImage.test.ts"]
related_domains: ["frontend-studio","video-gallery-feed","chat"]
forbidden_paths: ["unknown"]
owner: image-generation-platform
context_role: scoped-domain-map
updated: 2026-10-18
---
# Context: генерация изображений

## Назначение и владение

Карточка описывает backend admission, выполнение задания и сохранение результата.
UI state не подтверждает durable state; готовое изображение не доказывает корректность списания и завершения задания.
Layout, paint и общий shell принадлежат `frontend-studio`; публикация и видимость — `video-gallery-feed`.
Вызов генерации из chat требует также domain `chat`, который сохраняет владение tool/history/billing semantics.
Изменение generation service не расширяет владение соседними domains.

## Source map

Выбирать ближайший к симптому слой; весь generation stack не является обязательным контекстом.
Пути в таблице относятся к `backend/app/services/`.

| Файл | Ответственность |
| --- | --- |
| `generation_admission.py` | Нормализованный запрос, validation, replay, charge/trial reservation и создание задания. |
| `generation_jobs.py` | Persisted job, protected metadata и публичная API projection. |
| `generation_claims.py` | Durable queued → running claim и проверка права на запись. |
| `generation_queue.py` | Локальная очередь и единственный consumer только в совместимом combined role. |
| `generation_leases.py`, `generation_dispatch.py` | Durable selection, lease/expiry, heartbeat и IPC владение в server role. |
| `generation_bootstrap.py` | Роль процесса, ранний single-writer lock, startup/shutdown и composition. |
| `generation_admin_probe.py` | Trusted admin probe через ту же claim/finalization boundary без пользовательских списаний. |
| `generation_worker.py` | Порядок provider work, завершения, failure и post-completion callbacks. |
| `generation_worker_persistence.py` | Присоединение DB callbacks, cancellation, cache и optimization. |
| `generation_accounting.py` | Существующие charge adjustments и однократные refunds на caller connection. |
| `generation_recovery.py` | Согласование незавершённых durable jobs после startup. |
| `generation_results.py` | Построение image record и terminal job state. |

`backend/main.py` сохраняет маршруты `/api/generate`, `/api/jobs/{job_id}` и `/api/jobs/{job_id}/cancel`, composition adapters и provider callbacks.
Читать в нём конкретный связанный symbol, без расширения задачи на весь composition shell.
Клиентский phone contract: `frontend/src/phone/features/image/api.ts`.

## Admission и повтор запроса

После DTO normalization и trusted authentication admission проверяет optional HTTP `Idempotency-Key`.
Без ключа сохраняется обычный случайный job ID. Ключ допускает 1–128 видимых ASCII символов.
Для ключа owner-scoped digest задаёт `job_request_<sha256>`; raw key не сохраняется и не возвращается API.
Fingerprint связывает ключ с нормализованным request JSON.

Ранний lookup возвращает исходный accepted response до trial/rate checks и provider preflight.
Другой payload для того же owner/key получает 409; разные владельцы имеют разные job IDs.
После preflight lookup повторяется под `BEGIN IMMEDIATE`.
Charge/trial reservation, job и private acceptance metadata коммитятся на одной connection либо откатываются вместе.
Только новое принятие публикует job в cache/queue и предпринимает запись события; replay не создаёт новый wake или charge.
Replay возвращает исходную acceptance projection, включая прежнюю queue position; актуальный статус читается через jobs API.

`_generationAdmission` хранится в существующем `jobs.settings_json` и создаётся только trusted admission caller.
Persist сохраняет прежнюю metadata; request payload не может создать или заменить её.
Отсутствующая, повреждённая или несовместимая metadata у сохранённого keyed job даёт 409, без повторного списания.
Гарантия replay действует, пока сохранены job row и metadata: удаление всей row удаляет mapping.

## Queue, claim и выполнение

`IZO_PROCESS_ROLE=combined` сохраняет прежнюю `asyncio.Queue` и локальный consumer.
`server` получает process lock до SQLite startup и не запускает этот consumer; durable truth находится в SQLite.
Отдельный `python -m app.generation_worker` не импортирует main/SQLite и выполняет provider HTTP через private Unix IPC.
API сохраняет admission, accounting, provider orchestration и media finalization; worker монтирует только IPC volume.
Server выбирает queued row из SQLite под single-writer lease, независимо от cache/wake, с одним активным image job.
Heartbeat продлевает только текущий lease; stream loss/expiry дают fenced failure и однократный refund без uncertain retry.
После каждого успешного `queue.get()` выполняется `task_done()` в `finally`, включая lookup/parse/runtime errors.
Ошибки продолжают распространяться; acknowledgement не означает успешную обработку или автоматический restart consumer.

Перед provider work claim атомарно меняет owned `queued` job на `running` под writer lock.
Private `_workerClaim` содержит token; token привязан к execution context и не находится в публичном job dict.
Повторный consumer не получает claim и не запускает provider.
Его public refresh не заменяет active cache владельца, чтобы не потерять runtime metadata.

Jobs persist проверяет claim до overlay, UPSERT и trial settlement.
Claimed row запрещает generic запись без действующего token; trusted cancellation получает отдельное разрешение на locked owner/job.
`GenerationClaimLost` завершает stale execution без нового refund, failure write или fallback.
Submission, late media save и mock output используют соответствующие claim guards.

## Завершение, cancellation и recovery

Provider awaits выполняются до локальной finalization transaction.
В ней объединяются claim fence, OpenRouter adjustment, image/source SQL и terminal job persist.
Вложенные `db()` callbacks заимствуют connection; их context exit не коммитит внешнюю transaction.
Не добавлять в этот boundary отдельный commit, provider await или работу в другом thread.
Cache publication и gallery eviction cleanup выполняются после commit; rollback не публикует незавершённый результат.
Optimization запускается после durable completion; её ошибка не превращает completed job в failed/refunded.

Cancellation проверяет persisted owner/status и выполняет refund + cancelled persist в одной transaction.
Повторная отмена terminal job не возвращает средства снова.
Отмена queued ComfyUI job не вызывает global interrupt активной чужой задачи.
Для активного ComfyUI job сохраняется global provider interrupt, сериализованный с admission следующего job; per-prompt isolation не предоставляется.

Startup recovery использует существующие jobs: найденный durable image позволяет согласовать completion; иначе active job завершается failure/refund по действующим правилам.
Recovery не создаёт новый claim, provider retry или независимый lifecycle.
Disk index repair не восстанавливает изображения для известных active/failed/cancelled jobs.
Реальные crash ordering и restart timing требуют отдельного runtime evidence.

## Границы и текущие ограничения

- Split role поддерживает один API/SQLite writer; несколько API writers и распределённый broker не предоставляются.
- Durable polling закрывает commit-to-wake gap в server role; combined сохраняет прежнюю локальную очередь.
- Worker liveness хранится в private status, lease/watchdog — в API snapshot; public health раскрывает только safe readiness reason.
- Provider и filesystem не имеют общего atomic rollback с SQLite; после сбоя могут остаться неиндексированные файлы.
- Materialized result не означает публикацию в feed; gallery/publication policy остаётся в соседнем domain.
- Provider/model availability, capacity и production queue не выводятся из source или configured credentials.

## Focused tests

- `backend/test_generation_leases.py`, `backend/test_generation_dispatch.py`, `backend/test_generation_worker_process.py` — durable selection, real process roles, loss/expiry и late-result fencing.
- `backend/test_phone_job_progress.py`, `backend/test_generation_admin_probe.py` — сохранённые Phone progress и admin probe contracts.
- `backend/test_generation_admission.py` — replay, mismatch, owner isolation, rollback, restart, two-connection races и last-trial reservation.
- `backend/test_generation_claims.py` — claim authority, nested transactions, cancellation permission и metadata boundaries.
- `backend/test_generation_worker_claims.py` — duplicate/shared-dict consumers, late results, SQL/cache rollback, actual recovery, cancellation и optimizer ordering.
- `backend/test_generation_jobs_characterization.py`, `backend/test_generation_protection.py`, `backend/test_generation_recovery_wiring.py` — сохранённые application contracts.
- `backend/test_services_generation_jobs_module.py`, `backend/test_services_generation_queue_module.py`, `backend/test_services_generation_results_module.py`, `backend/test_services_generation_worker_module.py` — отдельные service boundaries.
- `frontend/phoneImage.test.ts` — phone request/client contract.

Выбирать тесты изменяемого слоя; cross-layer изменение требует проверки каждого затронутого boundary.
Source/unit tests не заменяют exact-SHA runtime evidence или полный application CI.

## Runtime scope

Не запускать production queue, worker или provider ради чтения этой карточки.
Production media, credentials и secrets не являются fixtures.
Изменения durable state и runtime проверки требуют отдельно авторизованного scope.
Карточка хранит маршрутизацию и границы; текущие статусы и evidence route принадлежат `docs/NOW.md`.
