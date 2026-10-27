# Обычное синтетическое приложение на Linux

Пакет `DOCKER-LINUX-SYNTHETIC-RUNTIME-002` добавляет отдельную проверку
обычного приложения из формата 2. Границы:
[Task Contract](../tasks/DOCKER-LINUX-SYNTHETIC-RUNTIME-002.toml).

Исходная Linux-матрица формата 1 остается самостоятельной проверкой.
Ее backend с ограничением 300 секунд не подтверждает постоянный uvicorn.
Новая матрица требует обычный процесс, успешную генерацию после 420 секунд
и новые задания после каждого изменения жизненного цикла.

## Неизменяемые входы

| Компонент | Фиксация |
|---|---|
| Application A | `1030abdafc32a0f11fbc4a6593acd435eb1bbdfd` |
| Application B | `f51c316176bf2609ccb9271c00a358a7b1f02768` |
| Format-2 tooling | `b517feb365eb7dcb0047f92500d73d4e82a74bff` |
| Lifecycle controller SHA256 | `013b4e10448d091a7e4817dde33c8002dd23437e58450826493972504e52f1e1` |
| Common checks SHA256 | `d7a2f251194b2ef1e79776bd4325b126afa4d6e5cd0c725bf0111eb71b977663` |
| Linux004 common helper SHA256 | `2192a7aef412442850e25b73945c2c8e773859844ca77bcb5849d681ae2e6913` |

Python-код контроллера и проверок переносится без изменений. Его исходный
тестовый файл превышал 24 KiB: четыре целых класса распределены между
двумя файлами с сохранением AST всех методов и утверждений. Добавлены
проверки границ нового адаптера; существующие тесты формата 1 сохранены.

## Producer и независимый receiver

Оба задания используют GitHub-hosted Ubuntu 22.04 X64. В начале каждого
задания записывается полный список image/container IDs и volume names.
Любой непустой список завершает проверку отказом; `prune` отсутствует.
Проверка локального сокета, владельца UID0, hostname/kernel и boot hash
повторно использует неизмененный Linux004 helper. Persistent Engine ID
может совпадать у образов VM; boot и проверенный Engine instance обязаны
различаться. Это проверка конкретных hosted runners, не root-attestation.

Producer собирает guard/backend/web без кеша по двум каноническим Compose
файлам: `compose.yml` и `compose.shadow.yml`. Acceptance override не
подключается. Текущий builder вызывается с `--profile synthetic-runtime`.
Образы включаются в A/B ZIP; фиксируются их digests, source/tooling SHA,
Dockerfile FROM digests, build receipts, manifest hashes и версии Engine/Compose.

Хеш producer receipt передается независимым job output. Receiver проверяет
его до доверия содержимому скачанного artifact, затем сверяет тот же
head/run/attempt, разные роли/boots/instances, пустой producer inventory,
обе цепочки receipt→archive→manifest и явный формат 2.

## Обычная матрица

На receiver создается новый каталог с Unicode в пути и отдельный проект
`izo-asa-bundle-runtime-linux01`, порты loopback `48774/48775`.
Контроллер вызывается отдельным `python -B .../synthetic_runtime_accept.py`.
Это сохраняет изоляцию его импортов: `checks.support` запрещает заранее
загруженный пакет `tools`. Установщику доступен отдельный PATH только с
Python и Docker; Git/Node/npm через этот PATH недоступны.

Матрица сохраняет все 11 этапов контроллера: install B; два аккаунта и два
задания; удаление входной распаковки и повторная установка; наблюдение 420
секунд и новое задание; restart backend; совместные stop/start и recreate;
down/reinstall с прежними томами; переходы B→A→B. Итог — девять завершенных
заданий A и девять job-linked charges, ноль изображений B. Проверяются
private media, favorite, хеши, ledger, исходные сессии, volume generation и
CreatedAt, актуальная привязка к guard и равенство network namespace.

Короткая исходная матрица строго сравнивает счетчики дневного allowance.
Перед первым запуском требуется более 1800 секунд до следующих суток UTC:
1500 секунд на lifecycle, 240 на cleanup и 60 запаса. При меньшем окне
получается явный отказ до изменения runtime или входа в аккаунты, без
ожидания, повтора и skip. Это граница тестовой фикстуры, не ограничение
приложения. Workflow сохраняет прежние 30 минут бюджета receiver.

Выполняется локальный mock fallback обычного приложения. Попытка проверки
провайдера направлена на loopback `127.0.0.1:1`; реальное исполнение модели
не заявляется. Worker доказывается завершенными заданиями, поскольку
одного healthy-ответа combined-процесса недостаточно.

## Доказательства и очистка

`retainSyntheticCredentials=false`: два пароля живут только в памяти
контроллера; файл учетных записей не создается. Workflow загружает только
явно перечисленные ZIP/build receipts, producer receipt и выбранный
receiver summary. Полные аккаунты, session IDs, cookies, БД и медиа в
artifact не включаются. Состояние данных представлено счетчиками, хешами
и проверенными job-linked charges.

Только после успешной матрицы вызывается отдельный `cleanup` с точным
хешем acceptance receipt. Он повторно сверяет owner/active, container IDs,
namespace, volume generation/CreatedAt, installation claim и данные,
затем удаляет собственные контейнеры, сеть, два data volumes и claim.
Неиспользуемые образы остаются на временном runner и отдельно учитываются.

При отказе или timeout повторного запуска и автоматической очистки нет.
Ограничение времени может завершить только собственную process group
контроллера; Docker-ресурсы тогда сохраняются до удаления временного runner.
Такое удаление runner не засчитывается как успешная проверенная очистка.

`PASS_ORDINARY_SYNTHETIC_RUNTIME_LINUX_ONLY` требует одновременно успешные
11 этапов, девять заданий, 420 секунд, последующую генерацию и явную
очистку. Он не означает 24-часовую устойчивость, backup/restore, перезагрузку
хоста, production или работу реальных моделей. Windows и format-1 receipts
остаются отдельными доказательствами с их собственными исходными SHA.

## Граница регистрации

Этот первоначальный проект намеренно не содержит `baseSha`. Перед первой
регистрацией root проверяет интеграцию Linux004 в фактический текущий main,
успешный source CI exact `b517feb365eb7dcb0047f92500d73d4e82a74bff`
и независимое review установщика. Installer берется из отдельного checkout
с этим SHA; его интеграция в базу candidate технически не требуется.
Root заполняет исходную базу через обычную подготовку Task Contract.
Изменения зарегистрированных баз и ручное редактирование registry запрещены.
Exact-head source CI нового пакета, независимое review и новый реальный
Linux run остаются обязательными до принятия результата или merge.
