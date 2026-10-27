# Synthetic runtime в существующем Docker bundle

Расширение существующих `docker_test_bundle` build/verify/install продолжает
DOCKER-TEST-BUNDLE-001. Границы продолжения заданы в
[TaskContract DOCKER-SYNTHETIC-RUNTIME-002](../tasks/DOCKER-SYNTHETIC-RUNTIME-002.toml).
Изменений приложения, Docker daemon или настроек Windows в этом пакете нет.

## Два явных контракта

| Формат | Профиль | Сервисы / тома | Backend |
| --- | --- | --- | --- |
| 1 | Прежний acceptance, поле profile отсутствует | 5 / 3 | CPU fixture, ограниченный срок около 300 секунд |
| 2 | `profile: synthetic-runtime` | backend/web/guard, sqlite-data/media-data | Обычный uvicorn без fixture deadline |

Сборка без нового параметра сохраняет [формат 1](docker-test-bundle.md). Для формата 2 существующей
команде build передают `--profile synthetic-runtime`; остальные параметры
source/sha/project/ports/context/output остаются обязательными. Используются
обычные `compose.yml` и `compose.shadow.yml`. Acceptance дополнительно включает
`compose.acceptance.yml`. Неизвестные версии/профили и поле profile в формате 1
отклоняются. Архивы не переименовываются в другой профиль после сборки.

Получатель использует те же install.cmd/install.sh либо
`docker_test_bundle_runtime.py install --test-only`. Профиль уже входит в
проверяемый manifest SHA. Git, Node и npm получателю не нужны. Source SHA
приложения, tooling SHA, image IDs и canonical release identity сохраняются.
Все архивные, path, lock, owner и volume generation проверки остаются включены.

## Обычный процесс и синтетические границы

Backend имеет точную команду `python -m uvicorn main:app --host 0.0.0.0 --port 8000`.
Builder и receiver дополнительно проверяют такой CMD и отсутствие скрытого
entrypoint в pinned backend image. `IZO_PROCESS_ROLE=combined` запускает штатного
in-process consumer; отдельные workers и worker IPC этому профилю не нужны.

Профиль явно фиксирует `COMFYUI_REQUIRED=false`, `COMFYUI_NATIVE4B_ONLY=false`,
`COMFYUI_MOCK_FALLBACK=true`, loopback-заглушку `COMFYUI_BASE_URL` и отсутствие
`IZO_SHADOW_FIXTURE`. Test environment, отключённые боты/внешние ключи, guard
egress deny и публикация только на 127.0.0.1 сохраняются. Синтетическая генерация
использует mock fallback приложения; внешний provider/model не проверяется.

Для точной проверки сохранности устанавливаются
`IZO_PREPROD_PRESERVE_HISTORY=1` и `IZO_DISABLE_STARTUP_STORAGE_MAINTENANCE=1`.
Это явная политика данного синтетического профиля. Она не определяет будущую
production-политику quota/maintenance. Автоматическая restart policy пока
остаётся `no`; ручные restart/recreate проверяются отдельной приёмкой.

Fresh install сохраняет существующий bootstrap: допускает только отсутствующую
БД или пустую схему 0, вызывает штатные db_guard_preflight/init_db, проверяет
схему 7 и лишь затем запускает обычный managed backend. Повторная установка
bootstrap не выполняет. Startup schema guard приложения не отключается.

Профиль записывается в owner/active и installation marker. Прежние v1 receipts
без profile остаются acceptance. Смена профиля в существующем state запрещена,
включая allow-code-update; runtime получает отдельный свежий namespace.
При новом runtime manifest, включая пересборку того же кода, неизвестные/NULL
job statuses, очередь video_file_deletions и preparing video publications
блокируют изменение runtime до Compose up. Exact-pin repeat остаётся идемпотентным.

## Доказательства и операционная приёмка

Unit tests проверяют v1 compatibility, v2 contract, image command, profile binding,
missing/drifted volumes, copied state, guard ID binding и реальный SQLite SELECT
на terminal/NULL/unknown jobs и pending media mutations. Эти тесты не запускают
Docker или приложение и не являются доказательством runtime-функциональности.

Source B статически поддерживает combined/mock fallback и штатный test password
auth/charge/finalization. Фактические login, generation, billing и session
результаты нужно получить на свежем синтетическом стенде. Приёмка фиксирует:

1. Fresh install и repeat из постоянного state после удаления тестовой incoming
   распаковки; managed identity, точные images/volumes и отсутствие fixture CMD.
2. Два синтетических пользователя в отдельных HTTP cookie jars, обычный login,
   генерация через HTTP, owner isolation и одна job-linked charge: daily/main
   части вместе равны tokenCost; balance/ledger delta может быть нулевой.
3. Работа дольше 300 секунд с неизменными IDs/StartedAt и без скрытых рестартов;
   затем отдельное 24-часовое наблюдение health/version/OOM/resources. Deadline
   останавливает наблюдатель, приложение продолжает работать.
4. Backend restart/recreate, согласованный restart группы и full recreate.
   После guard recreation backend/web обязаны ссылаться на новый guard ID;
   дополнительно сравниваются фактические network namespace inode всех трёх
   процессов. Проверяются HTTP ingress и штатный guard healthcheck. После 300
   секунд и каждого lifecycle этапа нужна новая HTTP-генерация: combined health
   сам по себе не подтверждает работоспособность consumer.
5. Сохраняются синтетические DB/media и работающая сессия в пределах её TTL.
   Изменение volatile auth-session timestamps отдельно от исторических данных.
6. Cold backup при остановленных writers штатным SQLite Backup API, restore
   только в отдельную свежую synthetic installation, сравнение logical records
   и каждого media SHA256, повторный старт/recreate восстановленной копии.

Backup учитывает committed WAL: исходные frozen DB/WAL/SHM читаются как байты,
SQLite работает с частной writable копией. Receipt/COMPLETED завершают backup;
timeout Docker CLI сам по себе не доказывает завершение helper. Повреждённый
snapshot/media, неверные hashes, незавершённый backup и несовместимая схема
должны блокировать restore до записи destination. Исторические данные и
резервные копии владельца для этой матрицы не используются.

Успешный immediate health receipt остаётся `TEST_RUNTIME_VERIFIED` с profile.
Он не обещает 24-часовой uptime, действующий login, восстановление после host
reboot или production readiness. Эти результаты записываются только после
соответствующей фактической проверки. Изменение host/daemon не требуется.
