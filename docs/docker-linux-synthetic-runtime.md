# Канонический Docker candidate на Linux

Пакет `DOCKER-CANONICAL-CANDIDATE-002` связывает существующую приёмку
format 2 с текущим точным application SHA. Границы:
[Task Contract](../tasks/DOCKER-CANONICAL-CANDIDATE-002.toml).

Исходная Linux-матрица формата 1 остаётся отдельной проверкой. Installer,
bundle format и Linux004 common helper не меняются. Старые A/B и Windows
receipts сохраняют свои исходные SHA и не подтверждают новый candidate.

## Закреплённые входы

| Компонент | Фиксация |
|---|---|
| Previous application A | `96314d9414df2954d3d8abbf3db20cf2e5e7dce0` |
| Current application B | `IZO_EXPECTED_HEAD`: точный PR head или dispatch SHA |
| Format-2 tooling | `b517feb365eb7dcb0047f92500d73d4e82a74bff` |
| Lifecycle controller SHA256 | `b794b18f435159cc23c5b607909c71a21c49867961f1dccb941bcf67c9f2ce58` |
| Common checks SHA256 | `d7a2f251194b2ef1e79776bd4325b126afa4d6e5cd0c725bf0111eb71b977663` |
| Linux004 common helper SHA256 | `2192a7aef412442850e25b73945c2c8e773859844ca77bcb5849d681ae2e6913` |
| HTTP helper SHA256 | `cef42d3f1eff18f853c76cb55d611065d38cbdb8c847176c40acae94712ff506` |

Producer получает явные `--source-a-sha` и `--source-b-sha`. A должен
совпадать с предыдущим canonical pin, B — с exact candidate head; SHA
должны различаться. Candidate, tooling и два application checkout находятся
в разных, не вложенных каталогах. Каждый checkout проходит существующий
origin/HEAD/clean guard до Docker, application — также до и после сборки.

Producer receipt и закреплённый plan версии 2 содержат одинаковый `sources`
с ключами A/B. Controller сверяет этот mapping с build receipts, archive
manifests, installer results и active receipt на всех этапах. Expected SHA
не выводится из непроверенного архива. Legacy plan версии 1 сохраняет старые
фиксированные A/B и не допускает подмены через дополнительное поле `sources`.

HTTP-клиент находится в `candidate/tools/synthetic_http_client.py`.
Он содержит только stdlib `HttpClient`, `path_id` и их защитные определения;
его hash проверяется перед использованием. Receiver не получает application
checkout B. ProductFlow, acceptance fixtures и worker IPC в поставку не входят.

## Producer и отдельный receiver

Оба job используют GitHub-hosted Ubuntu 22.04 X64. До работы сохраняются
полные image/container IDs и volume names. Непустой Engine приводит к отказу;
`prune` отсутствует. Проверки локального сокета, UID0, hostname/kernel и boot
hash повторно используют неизменённый Linux004 helper. Persistent Engine ID
может совпадать у образов VM; проверенные boot и Engine instance различаются.

После `fresh_engine` и до сборки обоих приложений producer запускает
`tools.docker_canonical_context_probe` только для CURRENT B: временный
синтетический context, `FROM scratch`, `--network=none`, без pull базового
образа. Проверяются точные положительные файлы web/guard и исключение
синтетических sidecars/посторонних ops-файлов. Вложенные ignore-правила
не получают allowances для неожиданного содержимого.

Gate требует `PASS_CONTEXT_EXPORT_ONLY`, правильный contract и CURRENT SHA,
`sourceDirty=false`. Source guard повторяется непосредственно до/после probe;
три ignore hash сверяются с файлами CURRENT до/после операции. Полный
`context.json` и его hash входят в producer
receipt; receiver сверяет переданный context receipt с этой закреплённой
копией. Context proof относится только к CURRENT, прежний A неизменяем.

Для каждого приложения сначала рендерится merged Compose из `compose.yml`
и `compose.shadow.yml`; сервисов ровно три. Затем без кеша собираются
`guard/backend/web`. Acceptance override не подключается. Existing builder
вызывается с `--profile synthetic-runtime`; A/B ZIP включают images.tar.
Receipt фиксирует source/tooling SHA, manifest/archive hashes, image IDs,
Dockerfile FROM digests, hash rendered Compose и Engine/Compose metadata.

Хеш producer receipt передаётся отдельным job output. Receiver проверяет
его до доверия artifact, затем сверяет head/run/attempt, разные роли,
boots/instances, исходный пустой Engine, explicit source mapping, context
receipt и обе цепочки receipt → archive → manifest.

## Обычная матрица

Receiver использует новый каталог с Unicode в пути, проект
`izo-asa-bundle-runtime-linux01` и loopback-порты `48774/48775`.
Controller запускается отдельным `python -B .../synthetic_runtime_accept.py`.
Его support loader не допускает заранее импортированный пакет `tools`.
Installer получает PATH только с Python/Docker, без Git/Node/npm.

Сохраняются все 11 этапов: install B; два аккаунта и два задания;
удаление incoming B и exact repeat; 420 секунд непрерывной работы с новым
заданием; backend restart; group stop/start и recreate; down/reinstall с
прежними томами; B → A → B. Итог — девять завершённых заданий и связанных
списаний у owner, ноль изображений у other. Проверяются private media,
favorite, хеши, ledger, исходные сессии, volume generation/CreatedAt,
актуальная привязка к guard и равенство network namespace.

До запуска требуется более 1800 секунд до следующих суток UTC:
1500 на lifecycle, 240 на cleanup и 60 запаса. При меньшем окне — отказ
до runtime/auth mutation без ожидания, повтора или skip. Это ограничение
фикстуры дневных счетчиков, а не приложения. Budget receiver — 30 минут.

Используется локальный mock fallback обычного приложения; endpoints
реальных провайдеров направлены на loopback `127.0.0.1:1`. Реальная модель
не вызывается. Работу обработки заданий подтверждает их завершение,
а не один healthy-ответ combined-процесса. Browser proof — отдельный gate:
текущий controller проверяет API и данные, но не управляет браузером.

## Одна поставка для Windows и Linux

Тот же ZIP с Linux/amd64 image IDs передаётся Windows Docker Desktop
(Linux containers) и Linux receiver без пересборки. В archive уже есть
`install.cmd` и `install.sh`; receiver нужны Python 3.11+ и Docker/Compose.
На каждом host создаются свой state-dir, owner и Engine binding. Plan
содержит фактические OS/host/context/paths, Windows не использует Linux plan.
Копировать installed state между Engines запрещает существующий installer.

Для повторной установки используется тот же manifest pin; смена кода
выполняется `install --allow-code-update` при неизменной схеме 7 и idle
предыдущем backend. Down/reinstall сохраняет тома и использует штатный lock.
B → A проверяет возврат кода, не восстановление БД из резервной копии.

## Доказательства и границы

`retainSyntheticCredentials=false`: пароли остаются в памяти controller.
Workflow загружает только allowlist: ZIP/build receipts, producer/context
receipts, неизменённый format-модуль и redacted receiver summary. БД, медиа, cookies и полные аккаунты
не загружаются. Хеши и счётчики описывают проверенное сохранение данных.

`linux-runtime-transfer-${{ env.IZO_EXPECTED_HEAD }}` хранит оба ZIP, build receipts,
producer.json, context.json и штатный format-модуль для безопасной распаковки
7 дней. Producer/context evidence и выбранный
receiver summary хранятся 30 дней. Срок хранения не является гарантией
наличия artifacts после его истечения.

Только после успешной матрицы отдельный `cleanup` с точным acceptance hash
повторно сверяет owner/active, container IDs, namespace, volume identity,
installation claim и данные. Он удаляет только собственные контейнеры,
сеть, два data volumes и claim; образы остаются на временном runner.
При отказе/timeout нет повторного запуска или автоматической очистки.
Timeout может завершить только созданную process group controller;
исчезновение ephemeral runner не засчитывается как проверенная очистка.

Workflow paths включают scoped candidate tools/task и `ops/docker/dev/**`.
Stdlib controller/adapter/HTTP tests идут в producer; pytest context tests
идут в обычном source CI. Реальный context export является отдельным
обязательным producer gate и не заменяется моками либо нулём собранных тестов.

`PASS_ORDINARY_SYNTHETIC_RUNTIME_LINUX_ONLY` требует 11 этапов, девять
заданий, 420 секунд, последующую генерацию и явную очистку. Он не доказывает
Windows/browser acceptance, backup/restore, reboot, production или модели.
Обязательные exact-head source CI и review остаются самостоятельными gates;
этот пакет не продлевает policy debts и не меняет их даты либо пороги.
