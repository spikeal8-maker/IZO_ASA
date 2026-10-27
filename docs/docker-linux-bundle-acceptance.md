# Linux-приёмка Docker TEST ZIP

Пакет `DOCKER-LINUX-BUNDLE-ACCEPTANCE-004` проверяет неизменённый TEST-установщик
между двумя отдельными GitHub-hosted Ubuntu 22.04 jobs. Наличие workflow,
локальные unit tests и Windows evidence не заменяют реальный Linux PASS.

Контракт: [Task Contract](../tasks/DOCKER-LINUX-BUNDLE-ACCEPTANCE-004.toml).
Workflow: [Docker Linux Bundle Acceptance](../.github/workflows/docker-linux-bundle-acceptance.yml).

## Причина продолжения и наблюдения

В [прогоне 001](https://github.com/spikeal8-maker/IZO_ASA/actions/runs/40543794921)
producer отказал из-за непустого Engine до сборки; receiver был пропущен.
Исключение потеряло исходный inventory, поэтому точные прежние ресурсы неизвестны.
[Provisioner Ubuntu](https://github.com/actions/runner-images/blob/ubuntu22/20261012.322/images/ubuntu/scripts/build/install-docker.sh)
пропускает предварительные Docker pull на Ubuntu 22.04. Только фактически
измеренные пустые inventories подтверждают пригодность конкретных jobs.

В [прогоне 002](https://github.com/spikeal8-maker/IZO_ASA/actions/runs/40548696908)
на HEAD `1af745c949c33624973959fa30371df55bd9d9f7` producer `122346230432`
успешно собрал оба ZIP, receiver `122347299631` отказал до установки.
Оба `before` пусты. Единственная ложная предпосылка — обязательное различие
SHA-256 сохранённого Docker Engine ID: хеши совпали, Linux boot hashes различались.
Логи показывают разные Worker IDs и регионы eastus/westus3, общий runner image
`20261012.322.1`, Docker 28.0.4 и Compose 2.38.2. Этот run остаётся FAIL.

[Moby 28.0.4](https://github.com/moby/moby/blob/v28.0.4/daemon/id.go) читает
`engine-id` из Docker root и создаёт UUID только при отсутствии файла.
Provisioner запускает Docker при подготовке образа; его
[cleanup](https://github.com/actions/runner-images/blob/ubuntu22/20261012.322/images/ubuntu/scripts/build/cleanup.sh)
этот файл не удаляет. Клонирование persistent ID — обоснованный вывод из кода
и receipts; содержимое дисков завершившихся runners отдельно не исследовалось.

Документация [образа 20261023.322.3](https://github.com/actions/runner-images/blob/ubuntu22/20261023.322/images/ubuntu/Ubuntu2204-Readme.md)
относится к другому опубликованному tag и не подменяет наблюдения старого run.
[Retirement Ubuntu 22.04 назначен на 17.04.2027](https://github.com/actions/runner-images/issues/14254);
постоянная доступность этого временного варианта приёмки не обещается.

## Закреплённые входы и сборка

| Роль | Exact SHA |
|---|---|
| Bundle tooling, PR #251 | `2fc621342721b1716e2ed898e24502115b71cb53` |
| Приложение A | `1030abdafc32a0f11fbc4a6593acd435eb1bbdfd` |
| Приложение B | `f51c316176bf2609ccb9271c00a358a7b1f02768` |

B — integration candidate, без утверждения production readiness или merge.
Candidate SHA записывается отдельно от application/tooling.
Чистые отдельные checkout проверяются по exact SHA и origin IZO_ASA.
Три канонических Dockerfile обязаны иметь digest-pinned `FROM`; существующий
Compose build использует `--no-cache` для guard/backend/web и исходные
`compose.yml`, `compose.shadow.yml`, `compose.acceptance.yml`. Builder включает
точные образы Linux amd64 в `images.tar` обоих ZIP. Installer не изменяется.
Это сборка с разрешёнными публичными registry/dependency downloads, не offline build.

## Локальность и независимость Engine

Оба jobs проверяют GitHub-hosted Linux X64, Ubuntu 22.04, Python из `.python-version`,
head/run/attempt/job и версии Docker/Compose. Уникальность runner name не предполагается.

До build/load default context обязан указывать `unix:///var/run/docker.sock`
с `SkipTLSVerify=false`. Путь после штатного `/var/run` → `/run` должен быть
`/run/docker.sock`: Unix socket с владельцем uid 0. Docker `info.Name` и
`KernelVersion` должны совпасть с локальными hostname/kernel; требуется Linux amd64.
Окружение дочерних команд не пропускает Docker/context/proxy overrides.

`engine.fingerprint` сохраняет прежний SHA-256 `info.ID`, включая его использование
в ownership/cleanup установщика. Отдельный `engineInstanceFingerprint` вычисляется
из canonical JSON: version 1, boot hash, persistent Engine hash, endpoint,
canonical socket path/type/owner, hostname hash и kernel release. Receipt содержит
эти исходные поля; receiver проверяет точные типы и привязки, затем пересчитывает
оба instance hash. Старые/неполные/несогласованные identity evidence не принимаются.
Обязательны одновременно разные Linux boot hashes и разные instance hashes.
Одинаковый boot отказывается даже при разных persistent IDs. Совпадение persistent
ID допустимо лишь при независимых boot и корректном локальном evidence.

Это проверка доверенных штатных GitHub-hosted VM, без аттестации против злонамеренного
root или поддельного Unix proxy. Предположение о PID socket activation не используется.

Перед проверкой пустоты оба jobs сохраняют `before`: все image/container IDs
и имена volumes. Любой ресурс блокирует build/load/install с сохранением inventory
и причиной `PRODUCER_ENGINE_NOT_EMPTY_NO_PRUNE` либо `RECEIVER_ENGINE_NOT_EMPTY_NO_PRUNE`.
Prune, второй daemon, sudo provisioning и глобальные изменения отсутствуют.

## Доверие к передаче

ZIP/receipts передаются artifact upload/download внутри одного workflow run.
SHA-256 `producer.json` поступает отдельным trusted job output. Receiver сверяет
его, контракт 004, пустой producer `before`, head/run/attempt, роли и identities,
затем SHA build receipts, архивов и манифестов. Локальная замена artifact вместе
с собственным checksum не заменяет trusted pin. Full-SHA action pins сохраняются.
Workflow имеет только `contents: read`, допускает same-repository PR владельца
или ручной запуск владельцем; `pull_request_target` и дополнительные tokens не нужны.

## Одиннадцать положительных сценариев

1. Проверка и распаковка A: payload без `.git`.
2. Проверка и распаковка B в путь с пробелами и Unicode.
3. Установка A: installer видит в PATH только Python и Docker.
4. Два синтетических пользователя, две генерации и проводки, приватное media,
   favorite, запрет доступа другому пользователю и гостю.
5. Удаление распаковки A; восстановление Compose из постоянного state.
6. Повтор A сохраняет container IDs, данные и identity томов.
7. Явное обновление A → B с сохранением данных.
8. Повтор B сохраняет container IDs и данные.
9. Явный возврат кода B → A при той же схеме 7.
10. Повторное обновление A → B.
11. Удаление контейнеров/сети; повтор B с прежними томами.

Allowlist PATH содержит Python/Docker; Git/Node/npm недоступны дочернему installer.
Compose проверяется в том же окружении. На host есть harness checkout; отсутствие
бинарников внутри containers не утверждается. HTTP client из точного B проверяет accounts,
sessions, tokens/balance, ledger, jobs, favorite и media hashes без backend imports.
Пароли, cookies, содержимое БД/media не публикуются; generation/CreatedAt томов сверяются.

## Отказы, очистка и evidence

Существующие проверки bad manifest pin, реально испорченного ZIP, copied state,
missing/recreated IPC volume сохраняются. После отказа active receipt и ресурсы
должны совпасть; меняющиеся healthcheck timestamps исключены, image/start identity
сохранены. Missing/drift удаляет только подтверждённый синтетический `worker_ipc`
после положительной матрицы, без удаления БД/media.

Cleanup проверяет owner UUID, прежний persistent Engine/state binding, generation,
все принятые metadata и отсутствие operation lock. Намеренно заменённый IPC generation
учитывается отдельно. Неожиданные owner/drift блокируют удаление. Удаляются только
собственные перечисленные containers/network/volumes/installation claim.
Imported images остаются на временном runner до его штатного уничтожения.

Artifacts: `linux-bundle-producer-evidence-<head>`,
`linux-bundle-receiver-evidence-<head>` и transfer artifact с ZIP. Linux PASS требует
11/11 положительных случаев, всех runtime negatives и успешной owned cleanup.
Focused tests: `python -B -m unittest tools.test_docker_linux_bundle_build tools.test_docker_linux_bundle_probe -v`.
Cloned-ID regression должна отказывать на алгоритме 002 и проходить на 003;
remote locality, same boot, malformed/tampered/cross-bound identities отказывают.
Прежние receipt regressions сохраняют measured inventory при отказах обоих jobs.
Unit tests, scope/hygiene, independent review, exact-head CI и real workflow — разные gates.

CPU fixture завершает backend примерно через 300 секунд. Матрица доказывает короткие
тестовые переходы, не постоянную работу, production rollback, исторический импорт,
GPU/реальные модели или полный Windows/Linux parity. Runtime использует только
синтетические данные и guard. Canonical authoring/focused checks на D2 допустимы;
операционная Linux-приёмка выполняется только в отдельных ephemeral GitHub jobs.
