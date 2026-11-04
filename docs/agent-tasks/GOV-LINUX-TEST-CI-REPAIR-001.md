# Исправление выбора task manifest в CI

Пакет: `GOV-LINUX-TEST-CI-REPAIR-001`.
Статус: подготовленный repair; actual-diff review, native CI-mode и новый
обязательный exact-head CI должны быть подтверждены отдельными receipts.

## Подтверждённая причина

[PR #270](https://github.com/spikeal8-maker/IZO_ASA/pull/270), HEAD
`78682a205cb1a20d9b09a704a4a296273ced664e`, получил
[CI FAILURE 41903055025](https://github.com/spikeal8-maker/IZO_ASA/actions/runs/41903055025).
Job `126830294922` остановился на `Enforce package scope`:
`PACKAGE_MANIFEST_UNRESOLVED`. Зависимости и тесты ещё не запускались;
warnings и cleanup для этого run — NOT_MEASURED, artifacts отсутствуют.
[File hygiene 41903055010](https://github.com/spikeal8-maker/IZO_ASA/actions/runs/41903055010)
прошёл. Эти результаты сохраняются без изменения задним числом.

`tools/agent_system/enforce.py::_ci_manifest` требует ровно один существующий
изменённый `tasks/[ID].toml` относительно base. В прежнем tree их два.
Локальный verify выбирал manifest по runtime ownership и не проверял
такой CI selector. Изменять selector или workflow для этого не требуется.

SHA-256 сохранённого failure receipt:
`f7cef39339ccb0b21f25832a6aad858968b93eb9c08cde0a2bbe00e3e21803f6`.

## Сохранённая история и границы изменения

Реальная основа main: `b308359e7466b78ecce06c9ae41b4a4b73cbe6ec`.
Первый исходный commit: `be44c22025949f6cff09273bf12aa944a65f3a8f`.
Carry commit: `78682a205cb1a20d9b09a704a4a296273ced664e`, tree
`cd0b8921a99ff0958e5111e1b1df878bbb398be9`. Оба commit сохраняются.

Из нового конечного tree убираются только два завершённых manifest:

- [LINUX-TEST-HEALTH-001 в be44](https://github.com/spikeal8-maker/IZO_ASA/blob/be44c22025949f6cff09273bf12aa944a65f3a8f/tasks/LINUX-TEST-HEALTH-001.toml).
- [GOV-LINUX-TEST-REVIEW-20261104 в 78682](https://github.com/spikeal8-maker/IZO_ASA/blob/78682a205cb1a20d9b09a704a4a296273ced664e/tasks/GOV-LINUX-TEST-REVIEW-20261104.toml).

Их прежнее содержимое доступно по этим immutable ссылкам. Новый
[task manifest](../../tasks/GOV-LINUX-TEST-CI-REPAIR-001.toml) явно владеет
обоими retirements и всем переносимым diff. Старые local branch/worktree
не переписываются; registry entries закрываются обычной командой finish.
Это закрытие владения чистым пакетом с известным CI FAIL, не принятие релиза.

Остальные **11 файлов** из carry сохраняются побайтово. В их числе
[исходное evidence](GOV-TEST-HEALTH-REVIEW-20261104.md) и
[ограниченный review](GOV-LINUX-TEST-REVIEW-20261104.md).
Policy SHA-256 остаётся
`69a2a2a37fd816bb6a72309564b3842c06286c123b46085162c608e0098b600c`.
Прежние документы описывают свои commits; этот receipt объясняет отдельное
последующее исправление упаковки task authority.

## Порядок подтверждения

1. Проверить clean carry HEAD/tree и fresh main; записать старый CI FAIL.
   Выполнить native verify и finish прежнего GOV package.
2. Через обычный agent start зарегистрировать новый scope на fresh main;
   fast-forward нового branch к carry. Runtime receipts фиксируют результат.
3. Удалить ровно два завершённых manifest, добавить новый manifest и этот
   документ. Проверить 11 сохранённых файлов, полный diff и local scope.
   Временный GIT_INDEX_FILE связывает reviewed tree; реальный index не меняется.
4. Получить независимый review фактического diff. Опубликовать точный reviewed
   tree с parent carry на новом зарегистрированном repair branch без нового PR.
5. На полученном неизменяемом clean HEAD выполнить native CI-mode с реальным
   base b308 и changed-file hygiene. Только после PASS разрешён ожидаемый
   non-force fast-forward remote branch существующего PR270 из 78682 к этому
   descendant. При изменении исходного remote ref остановиться.
6. Дождаться обоих обязательных hosted checks на точном новом HEAD и review.
   Local verify и selector proof не заменяют эти проверки.

В runtime evidence сохраняются finish/start/FF, retired и carried hashes,
четырёхфайловый repair diff, candidate tree, native gates и hosted receipts.
До их получения этот документ не утверждает новый CI SUCCESS.

## Неизменные условия review

Даты не переносятся: `reviewBy=2026-11-07`, с 8 ноября expiry снова даёт FAIL.
Warning ceiling8 и cleanup ceiling1, owners, categories и enforcement сохранены.
#162/#165 остаются открыты; Linux evidence не доказывает Windows cleanup fix.
Будущие изменения lifecycle, relevant dependency, Windows teardown либо
startup/no-replay требуют новой проверки применимости ограниченного review.

Новых ручных Windows/D2, provider или Full запусков repair не добавляет.
Он не меняет runtime, пользовательские данные или deployment.
Отмена только repair commit возвращает прежние два manifest и известную CI
неоднозначность; исправления тестов и policy остаются. Это source recovery,
а не автоматический rollback установленного приложения.
