# Linux-приёмка Docker TEST ZIP

Пакет `DOCKER-LINUX-BUNDLE-ACCEPTANCE-001` проверяет перенос поставки между
двумя отдельными GitHub-hosted Ubuntu 24.04 jobs. Он использует существующий
TEST-установщик без изменения его кода. Windows evidence не считается Linux
приёмкой; наличие workflow также не означает успешный реальный прогон.

Контракт: [Task Contract](../tasks/DOCKER-LINUX-BUNDLE-ACCEPTANCE-001.toml).
Workflow: [Docker Linux Bundle Acceptance](../.github/workflows/docker-linux-bundle-acceptance.yml).

## Закреплённые входы

| Роль | Exact SHA |
|---|---|
| Bundle tooling, PR #251 | `2fc621342721b1716e2ed898e24502115b71cb53` |
| Приложение A | `1030abdafc32a0f11fbc4a6593acd435eb1bbdfd` |
| Приложение B | `f51c316176bf2609ccb9271c00a358a7b1f02768` |

B — опубликованный integration candidate; эта проверка не объявляет его
предшественников merged или production-approved. Candidate workflow/helper SHA
записывается отдельно от application и installer SHA.

Исходники A/B и tooling находятся в отдельных чистых checkout с origin IZO_ASA.
Producer проверяет SHA, чистоту, origin и digest pins всех `FROM` в трёх
канонических Dockerfile. Затем запускает существующий Compose build с
`--no-cache` для guard/backend/web и исходными `compose.yml`,
`compose.shadow.yml`, `compose.acceptance.yml` из `ops/docker/dev`.
Настройки приложения, Dockerfile, зависимости и установщик не переписываются.

Сборка включает обычные разрешённые обращения к публичным registry за
закреплёнными образами и зависимостями. Runtime использует изолированный CPU
fixture и существующий guard; настоящие провайдеры, ключи и исторические данные
не нужны. Это не offline-сборка исходников.

## Независимость receiver и доверие к передаче

Producer/receiver исполняются на разных GitHub-hosted Linux X64 runners.
Оба проверяют Ubuntu 24.04 и записывают настоящие версии Docker Engine/Compose,
runner name, job, run, attempt и SHA. Эти версии наблюдаются, не выдумываются
из документации о runner image. Python совпадает с `.python-version`.

Перед работой receiver требует ноль Docker images, containers и volumes.
Обнаруженные ресурсы приводят к отказу; команда prune отсутствует.
Fingerprint Engine и SHA-256 Linux boot ID должны отличаться от producer.
Runner names записываются как наблюдение: их глобальная уникальность не предполагается.

Оба ZIP содержат `images.tar`. Передача выполняется artifact upload/download
внутри одного workflow run. SHA-256 `producer.json` передаётся отдельным job
output; receiver сверяет его, SHA обоих build receipts, архивов и манифестов.
Изменённый вместе со своим локальным checksum artifact не получает доверия.

Действия checkout/setup-python/upload используют ранее рассмотренные full-SHA
pins репозитория. Новый download pin взят из официального
[actions/download-artifact v4.3.0](https://github.com/actions/download-artifact/tree/d3f86a106a0bac45b974a628896c90dbdf5c8093).
Дополнительный token для скачивания artifact того же run не передаётся.
Workflow имеет только `contents: read`, допускает same-repository PR владельца
или ручной запуск владельцем, не использует `pull_request_target`.

## Одиннадцать положительных сценариев

1. Проверка и распаковка A: payload без `.git`.
2. Проверка и распаковка B в путь с пробелами и Unicode.
3. Установка A: дочерний installer видит в PATH только Python и Docker.
4. Два синтетических пользователя, две завершённые генерации, две проводки,
   приватное media, favorite и запрет доступа другого пользователя/гостя.
5. Удаление исходной распаковки A; восстановление Compose из постоянного state.
6. Повтор A сохраняет container IDs, данные и идентичность томов.
7. Разрешённое обновление A → B с сохранением данных.
8. Повтор B сохраняет container IDs и данные.
9. Явный возврат кода B → A при той же схеме 7.
10. Повторное обновление A → B.
11. Удаление контейнеров и сети; повторная установка B с прежними томами.

PATH изолируется отдельным allowlist bin с symlink на доверенные Python/Docker.
Каталог `/usr/bin` целиком не используется: иначе вместе с Docker был бы доступен
Git. Существующий механизм обнаружения Compose plugin сохраняется и проверяется
реальным вызовом в таком же окружении. У receiver host есть checkout для
evidence/harness; дочернему процессу installer Git/Node/npm недоступны через PATH.
Поставка работает без Git и исходников на стороне приложения; отсутствие этих
бинарников внутри application containers эта проверка не утверждает.

Сохранность проверяется через существующий bounded HTTP client из точного B.
Backend-модули не импортируются. Снимок в памяти охватывает обе учётные записи,
сессии, balance/used tokens, ledger, jobs, favorite и хеши приватных media.
Отчёт содержит контрольные суммы и результаты; пароли, cookies и содержимое
БД/файлов не публикуются. Receipt томов сравнивает generation и CreatedAt.

## Отрицательные сценарии и очистка

Проверяются неправильный manifest pin, реально повреждённый ZIP, копия state,
отсутствующий и пересозданный IPC-том. Перед/после отказа сравниваются ресурсы
и исходный active receipt; периодические healthcheck timestamps исключены
из сравнения, а container image/start identity и volume labels сохранены.

Missing/drift проверка выполняется после положительной матрицы. Она удаляет
только подтверждённый синтетический `worker_ipc`, затем создаёт новый generation
и требует отказа установщика. БД/media эта проверка не удаляет и не подменяет.

Финальная очистка проверяет owner UUID, Engine/state binding, generation labels
и отсутствие активного или stale operation lock. Все metadata томов сравниваются
с принятым снимком; намеренно созданный отрицательным сценарием IPC generation
учитывается отдельно. Неожиданный drift остальных томов запрещает удаление.
Удаляются только перечисленные
собственные контейнеры, сеть, data/IPC volumes и installation claim. При чужом
владельце или изменении тома очистка блокируется. Imported images остаются на
временном runner до его штатного уничтожения; global prune не выполняется.

## Evidence и ограничения

Artifacts: `linux-bundle-producer-evidence-<head>`,
`linux-bundle-receiver-evidence-<head>` и временный transfer artifact с двумя ZIP.
Успех receiver требует 11/11 положительных проверок, всех отрицательных сценариев
и успешной очистки. Нет receipt или есть неполная матрица — нет Linux PASS.

Локальные focused tests:
`python -B -m unittest tools.test_docker_linux_bundle_build tools.test_docker_linux_bundle_probe -v`.
Unit tests проверяют границы helper; реальный Engine они не имитируют как
доказательство operational acceptance. Scope, hygiene, independent review,
обычный exact-head CI и отдельный Linux workflow остаются разными gates.

CPU fixture завершает backend примерно через 300 секунд. Эта матрица проверяет
короткие тестовые переходы, а не постоянную работу сервера, production rollback,
исторический импорт, GPU, реальные модели или полную платформенную паритетность.
Репозиторное авторство/focused checks на D2 допустимы; Linux workload и его
синтетический runtime выполняются только в выделенных GitHub jobs.
