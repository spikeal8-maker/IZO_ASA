# Ограниченный review оставшегося тестового долга — 4 ноября 2026

Пакет: `GOV-LINUX-TEST-REVIEW-20261104`. **Статус: proposal до независимого
review и обязательного exact-head CI.** Это отдельное риск-решение по
[#112, acceptance 5](https://github.com/spikeal8-maker/IZO_ASA/issues/112),
разрешающему известный долг с owner/remediation либо bounded exception.

## Решение и пределы

Предлагается сохранить только прежние allowances #162/#165 до
**2026-11-07 включительно**. Owner обоих долгов — `spikeal8-maker`.
После этой даты требуется новое предметное решение; автоматического продления
нет. Issues остаются OPEN. Lifespan и Windows cleanup не объявляются исправленными.

Новый порученный владельцем review не отменяет
[решение 27 октября](GOV-TEST-HEALTH-REVIEW-20261027.md) задним числом:
его carry истёк 30 октября. Старые FAILURE и комментарии сохраняются.
Текущее предложение обосновано сверкой исходников и новым focused evidence,
а не необходимостью получить зелёный CI любой ценой.

## Точная цепочка кандидата

- Основа main: `b308359e7466b78ecce06c9ae41b4a4b73cbe6ec`.
- Независимо одобренный donor:
  [be44c22025949f6cff09273bf12aa944a65f3a8f](https://github.com/spikeal8-maker/IZO_ASA/commit/be44c22025949f6cff09273bf12aa944a65f3a8f).
- Его parent — указанная основа; tree:
  `553702753d0ce7f5292597b90e60e2d94a79955a`.
- SHA-256 полного reviewed donor patch:
  `04b7c9b614b9ee9dd1ebe619f076e9a05bffc194741cacd1854a6e5a735d7f2e`.
- Первый commit сохраняется. Второй содержит только четыре scalar replacements
  в policy, новый task manifest и эту review-card.
- Регистрация нового scope разрешена после штатного clean finish
  `LINUX-TEST-HEALTH-001`; finish/start receipts обязательны.
  GitHub commit/tree подтверждены; операция `373e0dee5a894d3d81d7f1c9f11d2238`
  выполнила штатные finish/start и FF donor `be44c22025949f6cff09273bf12aa944a65f3a8f`.
  Операция `f3ba276183074966b88222f2d2ccdf0d`: auditor 27 PASS, date controls PASS,
  ENFORCE_OK (13 files / 790 lines до этой записи); receipts в `.runtime/governance-review/`.

[Donor evidence](GOV-TEST-HEALTH-REVIEW-20261104.md) остаётся неизменным:
его вывод об EXPIRED #162/#165 описывает именно donor policy.
Исправления #163/#164 и их удалённые allowances сохраняются.

## Проверенные основания

Исторический оригинальный receipt:
[CI41813574349](https://github.com/spikeal8-maker/IZO_ASA/actions/runs/41813574349),
exact SHA `1a6931df500d61b7c3b18036d6af9a8a1089360f`;
2548 passed, 2 skipped, 97 warnings, cleanup0, process-leak PASS.
SHA-256 receipt:
`b1190e5482421fd7f8e309ad3eea2f2fee579c3f8c62d231f6fa4af7405c856d`.
Это существующий исторический FAILURE, не новый прогон main или donor.

Сравнение исторического exact SHA с b308 подтвердило byte identity:
requirements, `tools/test_migrate_openrouter_secret.py`,
`tools/migrate_openrouter_secret.py`, `backend/app/security/secret_store.py`,
auditor, pytest plugin, verify.ps1 и ci.yml. Startup/shutdown AST также совпали.
SHA-256 source-comparison receipt:
`109cae93c0c1c1996b2907e00b6138e63bd9eae395408f99d355618adef42ef5`.

Новый donor проверен на Linux/Python3.12.3: 207 passed, 4 known lifecycle warnings;
две устраняемые warning-категории проверялись как errors и не возникли.
Auditor: 27 passed. Сохранены 438 assertions и HTTP request semantics.
FastAPI0.136.3/Starlette1.7.0/httpx0.28.1 сохранены; добавлен httpx2 2.16.0,
адаптер и pip check проверены. External attempts0, reruns0; семь прежних
loopback probes отражены в telemetry. Repeat nondeterminism не измерена.
Это focused evidence; оно не заменяет full-suite или exact-head CI.

## #162 — lifespan/on_event

Остаются только исходные `DeprecationWarning` ceilings:
`backend/main.py=4`, `site-packages/fastapi/applications.py=4`, total8.
Focused значение4 не используется для уменьшения full-suite allowance.

Риск — будущая несовместимость lifecycle. Исторические функции и framework pins
сохранены; текущие client startup/shutdown сценарии проходят. Временный carry
позволяет отдельно согласовать supported lifespan и его failure/shutdown/
single-consumer-owner проверки, не вторгаясь в чужой main.py scope.
Выход: штатная передача scope, ограниченная миграция и её exact-head evidence.
Carry не разрешает изменение main.py, replay очередей или неподтверждённый запуск.

## #165 — Windows apply-secrets cleanup

Сохраняется единственный allowance:
`PermissionError / apply-secrets / <PYTEST_TEMP>/apply-secrets = 1`.
Его владелец — Windows-only
`test_apply_encrypts_verifies_and_deletes_legacy_row`.
Тест, migration script и DPAPI/ACL implementation идентичны историческому коду.

Риск — редкий дефект teardown/ACL/handle ownership. Исторический cleanup0 и
process-leak PASS не доказывают устранение. Linux не выполняет этот Windows путь.
Короткий carry сохраняет наблюдаемость исходного события до предметного решения
по владельцу ресурса; новые Windows/D2 проверки этим пакетом не запускаются.
Выход: подтверждённое исправление lifecycle либо подходящие независимые
evidence на одном точном коде, отдельное review закрытия; без скрытого retry.

## Политика и условия принятия

Меняются ровно `reason` и `reviewBy` двух debtReviews. Owners, categories,
warning ceiling8, cleanup ceiling1, historical provenance и весь enforcement
совпадают с donor. Новые warning sources, рост, test/network/retry/process
нарушения по-прежнему дают FAIL. #163/#164 не возвращаются в allowances.

Контроль дат через существующий evaluator относится к `metadata.startedAt`:
donor на 04Nov даёт EXPIRED162/165; proposal на 04Nov и07Nov не просрочен;
на08Nov оба EXPIRED снова обязательны. Это синтетическая проверка policy,
не новый runtime или CI receipt.

До merge обязательны: точный donor import, scope/line/file hygiene, auditor
tests, четыре scalar changes, date controls, независимый actual-diff review
и required exact-head CI двухкоммитного кандидата.
Любое последующее изменение lifecycle, relevant dependency, Windows teardown
или no-replay/startup требует отдельной проверки применимости этого решения.
Историческое равенство функций не переносится на такой diff автоматически.

Rollback — revert только второго governance commit: исправления #163/#164
сохраняются, прежние даты #162/#165 и expiry FAIL возвращаются.
Документ не утверждает deployment, browser acceptance, real-model generation,
сохранность импортированных пользовательских данных или автоматический rollback.
