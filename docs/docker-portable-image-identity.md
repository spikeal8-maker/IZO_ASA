# Переносимые образы существующего TEST-пакета

Пакет: `DOCKER-PORTABLE-IMAGE-IDENTITY-001`. Область — перенос встроенных
образов между classic Docker image store и containerd. Это исправление
существующих builder/installer; продуктовая приёмка и рабочий выпуск остаются
отдельными обязательными проверками.

## Исходный отказ

В [run 41800527232](https://github.com/spikeal8-maker/IZO_ASA/actions/runs/41800527232)
собрано приложение `7faf354ef1e9438adae1d9a4bbf2346b6e843bbe`.
Тот же ZIP прошёл проверку и распаковку на D2-R2, но установка остановилась:
Docker28.0.4 сохранил три безымянных образа в legacy manifest и только один
в OCI index. Containerd загрузил этот единственный образ. Кроме того, classic
store использует config digest как image ID, а containerd — manifest digest.

Исходный архив SHA256:
`dca84ba97e5fd7ec2f0c923e7ca1a6126a9b524dc8e67c9481aa8c2faa4d846e`.

Это два разрыва. Одного добавления тегов или замены ожидаемого ID недостаточно.

## Контракт идентичности

Format2 и профиль `synthetic-runtime` сохраняются. В новом embedded пакете
`image_identity` связывает каждую роль с archive reference, config digest
и OCI manifest digest. Поле `images` сохраняет config digests.
Прежние format1/format2 без этого расширения сохраняют прежний путь проверки.

Builder экспортирует существующие именованные Compose references.
Проверка архива сопоставляет его OCI и legacy представления, роли,
конфигурации и подтверждённые producer identities.
Неполный index, подмена роли или неоднозначный архив не должны публиковаться.

Installer разрешает конкретный локальный digest и проверяет source labels,
Linux/amd64 и предусмотренную команду backend. Тег не является доказательством
идентичности. До необходимой загрузки проверяется отсутствие конфликтующих
существующих тегов; чужой тег не перепривязывается молча.

Исходный `compose.json` остаётся частью неизменяемого inventory.
Для переносимого пакета installer создаёт постоянный sibling Compose
в собственном installation state. Отличаться могут только поля image,
заменённые подтверждёнными локальными digest. Перед использованием и health
проверяется полное ожидаемое содержимое; подменённый файл не перезаписывается.
Относительные frontend mounts разрешаются из прежнего release directory.

## Проверки и границы доказательства

Целевой workflow оформляется в отдельном зарегистрированном proof-пакете:
`docker-portable-image-delivery.yml`. Он явно разделяет workflow HEAD,
точный tooling SHA этого исправления и фиксированный application SHA.
Source guards, свежесть hosted Engine, provenance transfer и контрольные суммы
сохраняются. Producer собирает один комплект из канонического приложения;
отдельный Linux receiver и Windows D2 используют одинаковый ZIP.
На receiver сборка, переупаковка и ручное изменение image references не нужны.

Целевая проверка использует существующие extractor и installer, проверяет
свежую и повторную установку, source/frontend/backend identity и сохранение
installation owner и томов. Её PASS относится только к переносимости и
этим операциям. Уничтожение ephemeral runner не называется проверенной очисткой.

Полный nine-job controller не заменён этой проверкой. Его ранее обнаруженный
`IDEMPOTENT_ACCEPTANCE_CHANGED` остаётся отдельным отказом приложения.
Его старое прямое сравнение container.Image с config digest также требует
явной адаптации перед применением к новым portable bundles.

## Условия принятия

Перед merge нужны профильные тесты, scope/file hygiene, exact-head CI и
независимое review. Авторский просмотр не является независимым APPROVE.
Конкретные SHA, artifact URL, контрольные суммы и фактически выполненные
Windows/Linux команды фиксируются в PR и receipts соответствующего прогона.

Пакет сохраняет `model_execution=false` и `production_authorized=false`.
Он не разрешает настоящие модели, платежи или изменения рабочих интеграций.
Рабочий сервер, наблюдение, данные, Docker store и настройки хоста не меняются.
