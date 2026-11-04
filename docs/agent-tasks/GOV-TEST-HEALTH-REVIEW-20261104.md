# Устранение тестового долга #163/#164 — 4 ноября 2026

Пакет: `LINUX-TEST-HEALTH-001`. Проверка выполнена на Ubuntu 24.04,
Python 3.12.3, pytest 9.0.3, в отдельной среде
`/srv/izo-asa-deploy/tool-runtime/linux-test-health-001-venv`.
Рабочая ветка: `agent/linux-test-health-001`; исходный HEAD
`b308359e7466b78ecce06c9ae41b4a4b73cbe6ec`.

Это измерение незакоммиченного зарегистрированного кандидата. Оно не является
exact-head GitHub CI и не подтверждает установку приложения. До принятия нужны
независимое review, интеграция и обязательные проверки точного нового commit.
Issues этим документом не закрываются.

## Исправления и сохранённые ограничения

- #163: добавлен `httpx2==2.16.0`. `httpx==0.28.1`, FastAPI 0.136.3,
  Starlette 1.7.0 и остальные существующие pins сохранены. Provider-клиенты,
  использующие `httpx`, не мигрируют.
- #164: 87 статических request-level `cookies=` перенесены в 80 отдельных
  `TestClient(..., cookies=...)` контекстов семи тестовых модулей.
  Прежние 88 warnings включали два выполнения одной строки в цикле.
  Общего cookie jar или нового shared fixture нет.
- AST-проверка подтверждает прежние assertions, число клиентов и все HTTP
  arguments/headers, кроме удалённого request-level `cookies`. В каждом
  изменённом контексте остаётся одна прежняя cookie identity; анонимный запрос
  не получает авторизацию. Legacy spoof cookies остаются неподтверждёнными.
- Отрицательные CSRF/Origin и ownership проверки сохранены. Backend/product
  код, `backend/main.py`, lifecycle, provider-конфигурация и CI не изменялись.

### Основание выбора адаптера

FastAPI 0.136.3
[переэкспортирует Starlette TestClient](https://github.com/fastapi/fastapi/blob/0.136.3/fastapi/testclient.py).
[Starlette 1.7.0](https://github.com/Kludex/starlette/blob/1.7.0/starlette/testclient.py)
сначала импортирует `httpx2`; fallback на `httpx` порождает именно warning #163.
[Полный extra Starlette](https://github.com/Kludex/starlette/blob/1.7.0/pyproject.toml)
включает `httpx2>=2.0.0`.
[httpx2 2.16.0](https://github.com/pydantic/httpx2/blob/v2.16.0/src/httpx2/pyproject.toml)
требует Python >=3.11, anyio >=4.10 и truststore >=0.10; закреплённые зависимости
совместимы. Его
[клиент](https://github.com/pydantic/httpx2/blob/v2.16.0/src/httpx2/httpx2/_client.py)
поддерживает cookies конструктора и сохраняет deprecation request cookies.

Установка с `https://pypi.org/simple` и `pip check` завершились успешно.
Фактически загруженный `TestClient` наследует `httpx2.Client`, не
`httpx.Client`; импорт с `StarletteDeprecationWarning` как error проходит.
Версии: httpx2/httpcore2 2.16.0, httpx 0.28.1, httpcore 1.0.9,
anyio 4.15.1, truststore 0.10.4, idna 3.20.

## Измеренное доказательство

Focused pytest: **207 passed, 4 warnings, 54.44 s**, exit 0.
Проверены семь изменённых backend-модулей, `test_csrf_origin.py`,
`test_browser_client.py`, `tools/test_pytest_collection_contract.py` и
`tools/test_socks5_architecture_contract.py`.
Оба устраняемых warning вида повышены до ошибок:

```text
-W "error:Setting per-request cookies:DeprecationWarning"
-W "error::starlette.exceptions.StarletteDeprecationWarning"
```

Использован штатный `tools.test_health_pytest_plugin`; DB/media/secrets
изолированы backend fixture в собственном pytest basetemp. Полный argv и
SHA-256 проверенных файлов записаны в receipt. Сетевой allowlist не расширялся.

- Cookies warnings: **0**; deprecated TestClient fallback: **0**.
- Оставшиеся warnings: только `on_event`, `backend/main.py=2` и
  `site-packages/fastapi/applications.py=2`. Это focused subset; прежний
  full-suite allowance #162=8 не уменьшается по данному наблюдению.
- External attempts: **0**, blocked external: **0**.
  Прежние тесты сделали семь loopback probe attempts к 8188/9999/11434;
  нулевая сетевая активность не утверждается.
- Retry telemetry AVAILABLE, rerun reports **0**, retry plugins пусто.
  Повторная недетерминированность не измерена.
- Linux-наблюдение не подтверждает устранение Windows cleanup #165.

На сервере в `.runtime/test-health/` сохранены:
`dependency-install.log`, `dependency-proof.json`, `focused-pytest.log`,
`focused-junit.xml`, `focused-telemetry.json`, `focused-receipt.json`,
`source-invariants.json` и policy verification receipts.
Это локальные доказательства кандидата, не hosted CI artifact.

Операции 1Panel:
`045597706d8446b89b33e68cd11739ca` — scoped patch;
`1fb4086d2b40461595e54d3f5d39984c` — отдельная среда и adapter proof;
`e761a389d0e34e42b14aa7ab928282f5` — focused pytest.

SHA-256 cookie patch:
`bd2ddb1a56e0a1e960a6284d16131376ce535f76dc5ba5656f995c202b8d6d58`.
SHA-256 `backend/requirements.txt`:
`0baf5e18ea520514b41433e606bbfc07da492bc079c813a61931687bc8d0026c`.

## Решение по policy и незавершённым долгам

Из allowance удаляются только подтверждённо устранённые категории #163/#164
и соответствующие debtReviews. Warning ceiling уменьшается **97 → 8**;
возврат этих warning sources снова должен давать FAIL.
Исторический источник accepted baseline, cleanup allowance=1 и вся
`enforcement` сохраняются.

#162 и #165 остаются открытыми. Их категории, owner, reason и
`reviewBy=2026-10-30` не меняются. Проверка на 2026-11-04 обязана вернуть
`DEBT_REVIEW_EXPIRED_162` и `DEBT_REVIEW_EXPIRED_165`; общий policy gate
по-прежнему FAIL. Автоматического продления или нового исключения нет.

Для #162 по-прежнему требуется отдельный согласованный lifespan scope с
проверкой startup/failure/shutdown и единственного consumer owner.
Для #165 необходимо установленное владельцем решение по существующим
Windows teardown доказательствам или исправлению владельца ресурса.
Новых Windows проверок данный Linux-пакет не выполняет.

## Проверка изменения policy

Неизменённый tools/test_test_health_audit.py: **27 passed**, exit 0. Отрицательные проверки новых warning sources,
cleanup, network, retry, process leak и просроченных review остаются действующими.
policy-receipt.json фиксирует только два оставшихся EXPIRED и отсутствие
warning/cleanup non-regression нарушений в измеренном focused прогоне.
Штатный pwsh -NoProfile -File tools/agent.ps1 verify и git diff --check
выполняются после записи полного diff; их результат хранится в final-checks.json.
