# Идентичность Linux Docker-релиза

Пакет [LINUX-RELEASE-IDENTITY-001](../tasks/LINUX-RELEASE-IDENTITY-001.toml)
исправляет существующий Docker bundle и права nginx. Готовность приложения
и сохранность настоящей копии данных проверяются отдельно.

## Один идентификатор до сборки

Release ID сохраняет формат sha12-YYYYMMDDhhmmss.
Первая часть — application SHA, время — UTC committer timestamp того же точного
коммита. Часы упаковщика, tooling SHA, часовой пояс и дата повторной упаковки
не выбирают release ID. Поле built_at в frontend release manifest также содержит
время исходного коммита.

Существующий builder вычисляет ID до Compose render. Опциональный флаг
--build-images собирает образы этого же render с тем же окружением.
Без флага builder проверяет уже собранные образы. Source и tooling checkout
по-прежнему должны быть чистыми и совпадать с проверяемыми SHA.

Web build получает обязательный IZO_RELEASE_ID.
FRONTEND_BUILD_LABEL и OCI version используют release ID; OCI revision всех
образов продолжает содержать полный application SHA.
Backend release parser и frontend diagnostic comparison не изменены.

Сохраняются существующие acceptance fixture и synthetic runtime.
Сервисы, порты, постоянные тома, egress guard и обязательные safety gates
остаются под существующим builder/installer.

## Проверяемая цепочка

1. Application SHA и committer timestamp определяют release ID.
2. Реальный Compose render передаёт source SHA и release ID в web build.
3. Web image имеет ожидаемые OCI revision/source/version.
4. Из web image экспортируются реальные HTML и entry JavaScript. HTML содержит
   единственную release meta; compiled entry — тот же release ID.
5. Backend release manifest и ZIP manifest используют тот же ID.
6. ZIP inventory связывает HTML/JS с точными SHA-256 и размерами.
7. Установленный health сравнивает API, фактический HTML и entry JS по HTTP
   с release ID и pinned inventory. Receipt включает hashes полученных bytes.

Ожидаемый API frontend_build больше не считается доказательством содержания
frontend. Старый HTML, старый JS, подменённые bytes с правильным release marker,
неоднозначная meta, внешний/неожиданный entry path и redirect приводят к отказу.
HTTP reads ограничены размером и общим monotonic deadline каждого запроса (8 секунд).
Deadline применяется к connect/send и каждому socket read, включая HTTP headers и
chunk framing; медленный поток не продлевает бюджет. Runtime не создаёт read threads.
Redirect не выполняется. Duplicate attributes у всех meta/script отвергаются до
выбора name/type, чтобы разбор совпадал с browser first-attribute semantics.
Git и source checkout установленному helper не нужны.

## Nginx

Dockerfile копирует конфигурацию с явным --chmod=0644; runtime остаётся 101:101.
Режим конфигурации в образе не зависит от прав исходного файла после переноса.
Unit tests проверяют декларацию при режимах build context 0600 и 0644.
Фактические UID, доступность конфигурации и запуск nginx необходимо подтвердить
на exact built image; unit test не заменяет это доказательство.

## Канонические входы

Семь Docker inputs и три focused source/context файла перенесены из
7faf354ef1e9438adae1d9a4bbf2346b6e843bbe (PR #266).
Четыре portable installer модуля и три changed tests перенесены из
8667c47544b3048aeaee032f9f8f10066a656755 (PR #267).
Дальнейший delta ограничен release identity, nginx и их проверками.
Donor branches и их Task Contracts не изменяются.

## Проверки и эксплуатационная граница

Focused tests воспроизводят прежний ложный PASS при правильном API и старых
HTML/JS, затем требуют отказа. Дополнительно проверяются детерминированный ID,
image version, optional build order, tampered assets, URI boundaries, redirects,
ограничение размера и standalone import. Existing portable image, bundle,
ownership, volume persistence и source-context regressions сохраняются.

Назначенный постоянный target — asa-test/admins-MS-7D22. Source tests не означают
его установку. Exact-SHA build, nginx check, native 1Panel deployment, браузер,
доступ владельца и API evidence выполняются отдельными этапами.
На постоянном target lifecycle запускается только отдельной native 1Panel операцией.

Workflow docker-linux-release-identity.yml проверяет exact PR head как source и
tooling на одноразовом GitHub-hosted Linux: focused tests, реальный context export,
existing builder с --build-images, пустые synthetic volumes, actual HTML/JS/API,
UID101 nginx -t при исходном nginx mode0600, guard --check и owned cleanup.
Он сохраняет ZIP, checksums и public-safe evidence. YAML/AST checks до публикации
не означают, что этот runtime workflow уже выполнен. CI не доказывает постоянную
установку и не использует исторические БД/media.

Deterministic release ID не является обещанием побитовой повторяемости images
или ZIP при другой toolchain. Для переноса установленного релиза сохраняются
сам ZIP, его SHA-256, manifest pin и immutable image identities.
Release identity и synthetic profile сами по себе не включают safe copied
history policy и не исправляют accounting/idempotency приложения.
