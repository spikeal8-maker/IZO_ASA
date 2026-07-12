# IZO ASA — рабочий план оптимизации действующего проекта

Дата: 2026-07-12
Статус: готов к последовательной реализации
Контекст: весь проект работает на текущем личном Windows-компьютере и имеет реальных пользователей. Здесь находятся frontend, backend, SQLite, media, ComfyUI и Ollama. Внешний VPS используется только для прохождения домена через существующий tunnel, не является application server и полностью исключён из работ по оптимизации. Цель — исправить найденные проблемы и разделить монолитные файлы без остановки и без переписывания продукта.

## Статус реализации на 2026-07-12

Завершено и проверено:

- создана архитектурная карта и автоматически проверяемый symbol/route map;
- generation-тесты приведены к действующей матрице разрешений;
- удалена прямая раздача всего `/media`, добавлены trusted-session и ownership checks;
- Telegram/MAX operational endpoints закрыты trusted-admin авторизацией;
- TypeScript-ошибка теперь блокирует public launcher;
- выделен import-safe `app/config.py`;
- выделены `database/connection.py` и `database/guard.py` с совместимыми обёртками;
- выделены additive-column declarations и migration helpers;
- три статических SQL-блока вынесены в `database/schema.py` без изменения порядка выполнения;
- `init_db()` уменьшен с 973 до 208 строк;
- opaque token generation/HMAC validation вынесены в `security/tokens.py` с совместимыми `main.py` wrappers;
- Argon2id policy/hash/verify/dummy timing hash вынесены в `security/passwords.py`;
- trusted session create/resolve/refresh/revoke вынесены в `security/sessions.py` через явно внедряемый runtime;
- trusted user/admin permission checks вынесены в `security/permissions.py`, legacy identity inputs не получают право авторизации;
- OTP generation/hash/config validation/mock delivery/cleanup/rate limits вынесены в `security/otp.py`;
- session/security/login/product event persistence вынесено в `security/events.py`;
- старые `test_api.py` и `test_lifecycle.py` приведены к действующим auth/provider/resolution контрактам;
- после session/permissions extraction общий checkpoint: 326 backend tests, 2 известных устаревших feed-теста исключены отдельно;
- session/permissions package проверен пятью циклами по 84 теста, frontend build/lint и production smoke после рестарта;
- OTP/events package проверен пятью циклами по 152 теста; frontend production build и lint прошли без ошибок;
- 8 устаревших product/ComfyUI/OpenRouter assertions синхронизированы с подтверждёнными текущими контрактами и проверены пятью циклами;
- OpenRouter non-text generation теперь требует live capability выбранной модели до billing и создания job;
- расширенный backend checkpoint после синхронизации: 648 passed, 2 известных feed-теста deselected;
- canonical root containment, media URL parsing и compatibility URL creation вынесены в `storage/paths.py`;
- storage paths package проверен пятью циклами по 120 тестов; общий backend checkpoint: 652 passed, 2 известных feed-теста deselected;
- storage paths развёрнут в production; пять live smoke-циклов подтвердили private media 401 без сессии и traversal 404;
- private media ownership больше не использует небезопасное prefix-сопоставление `filename%`; разрешается только точный URL-путь и необязательный query string;
- trusted private-media resolution вынесен в `storage/private_media.py`, public avatar/feed resolution — в `storage/public_media.py`;
- private/public media package проверен пятью циклами по 81 тесту; общий backend checkpoint: 657 passed, 2 известных feed-теста deselected;
- production smoke 5/5 подтвердил private 401, traversal/orphan/unpublished 404 и опубликованный feed asset 200 локально и через домен;
- установлена причина нестабильного source availability: некоторые `TestClient`-тесты запускали startup maintenance с временной БД, но настоящим `backend/media`, а прямые media helpers создавали там тестовые source-файлы;
- `backend/conftest.py` теперь принудительно изолирует `DB_PATH`, `MEDIA` и `AVATAR_DIR` для каждого backend-теста;
- startup storage maintenance и background optimization блокируются под pytest через `storage/maintenance.py`;
- quarantine tool получил точный repeatable allowlist `--only-file`; 46 подтверждённых test artifacts перемещены в `D:\IZO_ASA_quarantine\pytest-media-20260712-1600` с SHA-256 manifest;
- test-isolation package проверен 5 циклами; полный backend checkpoint: 661 passed, 2 известных feed-теста deselected; live source snapshot остался 194/194 без added/removed/changed;
- при контрольном production restart старый startup cleanup удалил ещё 46 unreferenced source-файлов напрямую; availability остался стабильным 125/2 и changed=0, но необратимое удаление признано недопустимым;
- `storage/cleanup.py` теперь удаляет только orphan metadata rows и возвращает количество file candidates; физические файлы не удаляются;
- non-destructive cleanup package проверен 5 циклами; общий backend checkpoint: 662 passed, 2 известных feed-теста deselected; live source snapshot 148/148 без added/removed/changed;
- production restart подтвердил `fileCandidates=23`, `rowFiles=0`, `files=0`, availability 125/2 и changed=0; все 23 aged unreferenced candidates перемещены в `D:\IZO_ASA_quarantine\startup-source-candidates-20260712-1647`;
- итоговый read-only storage audit: blocking issues 0, missing active refs 0, source files 125, aged unreferenced source candidates 0; известные unavailable refs остаются diagnostic-only;
- source availability reconciliation вынесен в `storage/recovery.py`; первый проход корректирует статусы, повторный гарантированно даёт changed=0 при неизменном filesystem;
- availability package проверен 5 циклами; общий backend checkpoint: 663 passed, 2 известных feed-теста deselected; live source snapshot 125/125 без added/removed/changed;
- production restart после extraction подтвердил availability 125/2, changed=0, отсутствие cleanup/repair действий и live smoke 5/5;
- оба ранее deselected feed-теста возвращены в обязательный suite: gallery shell синхронизирован с текущими routes, а gallery-original migration исправлена так, чтобы `delete_source=False` действительно сохранял исходный PNG/JPG;
- текущий полный backend checkpoint: 665 passed, 0 deselected, 0 excluded; live source snapshot 125/125 без added/removed/changed;
- после рестарта удалён дублирующий Uvicorn-процесс, ошибочно слушавший `0.0.0.0:8000`; штатный backend подтверждён единственным listener на `127.0.0.1:8000`.
- восстановление unavailable source thumbnails из job settings вынесено из `main.py` в `storage/recovery.py` через явно внедряемые adapters; прежняя функция `repair_unavailable_image_sources_from_jobs()` сохранена как compatibility wrapper;
- extraction проверен новым модульным тестом на сохранение metadata/избранного и идемпотентность, существующим integration/startup-safety набором в 5 циклах по 6 тестов;
- текущий полный backend checkpoint после repair extraction: 666 passed, 0 deselected, 0 excluded; frontend lint — 0 errors (1 ранее известный hooks warning), production build — успешно;
- controlled production restart поднял единственный backend PID на `127.0.0.1:8000`; startup reconciliation: checked 127, available 125, missing 2, changed 0;
- live smoke после repair extraction прошёл 5/5: health/capabilities/frontend/public feed media — 200, private source без trusted session — 401;
- source snapshot до/после рестарта полностью совпал: 125 файлов, 1 871 474 bytes, общий SHA-256 `EDEAF248B43430834D42A6CB41E3E7CF069930DC43F3DD230AE4701A88B8D957`; активных pytest-процессов после проверки нет;
- source-tree traversal и owner-scoped восстановление rows для одной image вынесены в новый import-safe `storage/source_graph.py`; `main.py` сохраняет compatibility wrappers и инжектирует Pydantic parsing/persistence;
- source-graph package проверен 5 циклами по 6 тестов: live parent chain, snapshot fallback после удаления intermediate image, repair из job settings и multiple uploads;
- текущий полный backend checkpoint после source-graph extraction: 668 passed, 0 deselected, 0 excluded; frontend lint — 0 errors (1 ранее известный hooks warning), production build — успешно;
- controlled production restart source-graph package поднял единственный backend на `127.0.0.1:8000`; startup reconciliation снова checked 127, available 125, missing 2, changed 0;
- второй live smoke прошёл 5/5: health/capabilities/frontend/public feed media — 200, private source без trusted session — 401; source snapshot снова совпал (125 файлов, тот же SHA-256), pytest-процессов нет;
- transactional replacement source rows (`persist_image_sources`) вынесен в `storage/source_graph.py`; compatibility wrapper передаёт уже нормализованные inputs и явно инжектирует DB, thumbnail, URL и file cleanup adapters;
- добавлены прямые тесты successful commit и forced INSERT failure: slot-level favorite/library state сохраняется, старые файлы удаляются только после commit, а при ошибке DB rollback возвращает старую строку и удаляет новый thumbnail;
- source-persistence package проверен 5 циклами по 9 тестов; полный backend checkpoint: 670 passed, 0 deselected, 0 excluded; frontend lint — 0 errors (1 известный hooks warning), production build — успешно;
- controlled restart поднял единственный backend на `127.0.0.1:8000`; startup reconciliation: checked 127, available 125, missing 2, changed 0; live smoke прошёл 5/5;
- source snapshot после persistence extraction совпал до/после (125 файлов, 1 871 474 bytes, SHA-256 `EDEAF248B43430834D42A6CB41E3E7CF069930DC43F3DD230AE4701A88B8D957`); read-only storage audit: issues 0, missing active refs 0;
- source image decoding и WEBP thumbnail creation вынесены из `main.py` в новый `storage/source_thumbnails.py`; сохранены data URL/local media inputs, EXIF transpose, RGB, max-side, WEBP quality/method и безопасный `None` для повреждённых изображений;
- добавлены прямые тесты EXIF orientation/resize/WEBP и invalid/missing/local-media inputs; thumbnail package проверен 5 циклами по 9 тестов;
- полный backend checkpoint после thumbnail extraction: 672 passed, 0 deselected, 0 excluded; frontend lint — 0 errors (1 известный hooks warning), production build — успешно;
- controlled restart thumbnail package поднял единственный backend на `127.0.0.1:8000`; startup reconciliation остался changed 0, live smoke прошёл 5/5;
- source snapshot до/после thumbnail deployment совпал: 125 файлов, 1 871 474 bytes, SHA-256 `EDEAF248B43430834D42A6CB41E3E7CF069930DC43F3DD230AE4701A88B8D957`; pytest-процессов нет;
- source role labels и generation source normalization вынесены в новый `storage/source_inputs.py`; `main.py` сохраняет compatibility wrappers;
- прямые тесты фиксируют все labels, edit sorting/default roles, faceswap/try-on roles, canvas/mask slots, cap первых восьми inputs и dedup по первым 500 символам; focused package прошёл 5 циклов по 25 тестов;
- полный backend checkpoint после source-input extraction: 689 passed, 0 deselected, 0 excluded; frontend lint — 0 errors (1 известный hooks warning), production build — успешно;
- обнаружен оставшийся substring filename match через `LIKE '%filename%'` в `gallery_image_id_from_media_url` и `validate_generation_media_inputs`; исправление точного canonical URL ownership выделено в следующий security package;
- controlled restart source-input package поднял единственный backend на `127.0.0.1:8000`; startup reconciliation остался changed 0, live smoke прошёл 5/5;
- source snapshot до/после deployment совпал: 125 файлов, 1 871 474 bytes, SHA-256 `EDEAF248B43430834D42A6CB41E3E7CF069930DC43F3DD230AE4701A88B8D957`; pytest-процессов нет;
- добавлен единый `storage/media_references.py`: exact canonical/legacy URL с optional query, escaping `%/_`, active image/source state и точный поиск URL-строк через SQLite `json_tree` только в валидном job JSON;
- `gallery_image_id_from_media_url` и `validate_generation_media_inputs` больше не используют substring filename ownership; regression `foo.png` против принадлежащего пользователю `xfoo.png` подтверждает отказ `input_media_unavailable`;
- exact-media package проверен 5 циклами по 35 security/media тестов; полный backend checkpoint: 693 passed, 0 deselected, 0 excluded; frontend lint — 0 errors (1 известный hooks warning), production build — успешно;
- controlled restart exact-media package поднял единственный backend на `127.0.0.1:8000`; startup reconciliation остался changed 0, live smoke прошёл 5/5;
- source snapshot до/после security deployment совпал: 125 файлов, 1 871 474 bytes, SHA-256 `EDEAF248B43430834D42A6CB41E3E7CF069930DC43F3DD230AE4701A88B8D957`; pytest-процессов нет;
- owner-scoped generation media validation вынесен в `storage/input_validation.py`; новый typed `MediaInputValidationError` не зависит от FastAPI, а compatibility wrapper сохраняет прежние HTTP 400 payloads;
- прямые тесты подтверждают разрешённые active image/source/job references, приоритет `input_media_missing`, field mapping и отказ для existing-but-unowned media; package прошёл 5 циклов по 38 security/media тестов;
- полный backend checkpoint после input-validation extraction: 696 passed, 0 deselected, 0 excluded; frontend lint — 0 errors (1 известный hooks warning), production build — успешно;
- controlled restart input-validation package поднял единственный backend на `127.0.0.1:8000`; startup reconciliation остался changed 0, live smoke прошёл 5/5;
- source snapshot до/после deployment совпал: 125 файлов, 1 871 474 bytes, SHA-256 `EDEAF248B43430834D42A6CB41E3E7CF069930DC43F3DD230AE4701A88B8D957`; pytest-процессов нет;
- source file/row deletion вынесен в `storage/source_graph.py` через explicit filename/delete adapters; сохранён порядок: каждый конкретный thumbnail удаляется до `DELETE image_sources` в переданном transaction connection;
- прямой тест и реальные gallery/feed delete сценарии прошли 5 циклов по 8 тестов; полный backend checkpoint: 697 passed, 0 deselected, 0 excluded; frontend lint — 0 errors (1 известный hooks warning), production build — успешно;
- controlled restart source-deletion package поднял единственный backend на `127.0.0.1:8000`; startup reconciliation остался changed 0, live smoke прошёл 5/5;
- source snapshot до/после deployment совпал: 125 файлов, 1 871 474 bytes, SHA-256 `EDEAF248B43430834D42A6CB41E3E7CF069930DC43F3DD230AE4701A88B8D957`; pytest-процессов нет;
- Ollama inventory локализовал три независимые области: административный `/api/tags` status, prompt improvement `/api/chat` и voice transcription `/api/chat`; первым вынесен только низкорисковый status block;
- нормализация `OLLAMA_BASE_URL`, GET `/api/tags`, parsing списка models и безопасные error payloads вынесены в import-safe `app/integrations/ollama.py`; `main.ollama_models_status()` сохранён как compatibility wrapper;
- characterization tests фиксируют compatibility-wrapper delegation, trailing-slash normalization, точный `/api/tags` path, неизменные model rows, malformed models, HTTP 503, invalid JSON и отсутствие сетевых деталей в error payload; focused package прошёл 5 циклов по 17 тестов;
- полный backend checkpoint после первого Ollama extraction: 704 passed, 0 deselected, 0 excluded; frontend lint — 0 errors (1 известный hooks warning), TypeScript/Vite production build — успешно; активных pytest-процессов после проверки нет;
- controlled restart первого Ollama package поднял единственный backend PID 45108 на `127.0.0.1:8000`; startup reconciliation: checked 127, available 125, missing 2, changed 0;
- live smoke прошёл 5/5: health/capabilities/frontend/feed/public feed media — 200, private source без trusted session — 401; реальный локальный Ollama discovery вернул `ok=true` и 14 моделей без изменения его процесса или настроек;
- source snapshot до/после deployment совпал: 125 файлов, 1 871 474 bytes, SHA-256 `EDEAF248B43430834D42A6CB41E3E7CF069930DC43F3DD230AE4701A88B8D957`; pytest-процессов нет;
- все завершённые checkpoint-коммиты до `70195da` включительно синхронизированы с `origin/main`; каждый следующий завершённый пакет также документируется, коммитится и отправляется в GitHub.

Частично выполнено:

- конфигурация: чистые helpers вынесены, остальные runtime-настройки ещё находятся в `main.py`;
- schema/migrations: SQL declarations вынесены, migration ledger/version и дальнейшее разделение seed/backfill ещё не выполнены;
- deploy gate: TypeScript блокирует запуск, но единая `tools/verify.ps1` и CI gate ещё не созданы.

Следующий пакет: вынести bounded Ollama prompt-improvement request/response block в `app/integrations/ollama.py` с characterization tests, сохранив текущие model/body/prompt/timeout/error contracts и compatibility wrapper в `main.py`. Voice transcription остаётся отдельным последующим пакетом. Production restart каждого пакета выполняется только после полного checkpoint.

Storage-аудит завершён: startup availability теперь стабилен (`changed=0` при неизменном filesystem), автоматическое физическое удаление файлов запрещено, тесты изолированы от production DB/media. Любая будущая очистка файлов выполняется только через manifest/quarantine.

## 1. Что именно исправляем

### Крупные файлы

| Файл | Текущий размер | Цель |
|---|---:|---:|
| `backend/main.py` | ~15 364 строки | entrypoint до 100–300 строк; остальное по модулям |
| `frontend/src/newStudioV3.css` | ~5 334 | файлы по feature/component, преимущественно до 300–500 строк |
| `frontend/src/newUi.tsx` | ~4 056 | page composition до 300–500 строк |
| `frontend/src/LegacyApp.tsx` | ~3 461 | разделённые feature-компоненты; поведение сохранено |
| `frontend/src/newUi.css` | ~2 613 | tokens/base/layout/features |
| `frontend/src/index.css` | ~1 992 | только действительно глобальные правила |
| `frontend/src/adminModels.tsx` | ~1 526 | API/types/hooks/components/page |
| `backend/test_feed_v2.py` | ~1 328 | отдельные test-модули по поведению |
| `backend/test_api.py` | ~906 | отдельные API test-модули |

### Подтверждённые проблемы

1. Прямой `/media/{filename}` отдаёт приватные файлы без авторизации.
2. Управляющие Telegram/MAX endpoints не защищены admin/service authorization.
3. Telegram webhook не проверяет secret.
4. MAX webhook допускает пустой `MAX_WEBHOOK_SECRET`.
5. OpenRouter key из админки сохраняется в SQLite открытым текстом.
6. `start-public.bat` продолжает deploy после ошибки TypeScript.
7. 14 generation regression tests не совпадают с новой матрицей разрешений.
8. Нет CI gate.
9. Нет регулярного согласованного backup базы и media на другом физическом носителе.
10. `vite preview` используется как постоянный сервер frontend.
11. Процессы запускаются окнами PowerShell без полноценного supervisor.
12. Legacy auth helpers и JS-readable legacy cookie остаются в коде.
13. `allowedHosts: true` слишком широк для production.
14. `TRUST_CLOUDFLARE_HEADERS` требует подтверждённой изоляции origin.
15. Billing/token ledger требуют конкурентных и idempotency-тестов.
16. Исправлено: `gallery_image_id_from_media_url` и `validate_generation_media_inputs` используют exact canonical/legacy URL matching; похожие имена файлов больше не пересекают ownership boundary.

## 2. Жёсткие правила оптимизации

1. Проект продолжает работать во время оптимизации.
2. Один PR — одна проблема или один перенос ограниченного блока.
3. Нельзя одновременно переносить код и менять его поведение.
4. Перед переносом блока добавляются characterization tests.
5. После переноса публичные API и форматы БД не меняются.
6. Старые импорты временно сохраняются через re-export, если они нужны тестам/scripts.
7. Production SQLite не используется в тестах.
8. Schema changes остаются additive-only.
9. Внешний VPS и существующий доменный tunnel не изменяются и не проверяются в рамках этого плана.
10. После каждого PR обязательны backend tests, frontend build и соответствующий smoke.
11. Большой «переписать всё» PR запрещён.
12. PostgreSQL/Docker/Linux не смешиваются с текущей декомпозицией.
13. Каждый завершённый checkpoint обновляет документацию, получает отдельный commit и push в `origin/main`; секреты, live SQLite и media в Git не добавляются.

## 3. Итоговая структура backend

```text
backend/
  main.py
  app/
    __init__.py
    application.py
    lifecycle.py
    config.py
    api/
      dependencies.py
      errors.py
      routers/
        health.py
        auth.py
        account.py
        generation.py
        gallery.py
        feed.py
        admin.py
        bots.py
    database/
      connection.py
      guard.py
      schema.py
      migrations.py
      repositories/
        users.py
        sessions.py
        jobs.py
        images.py
        billing.py
        feed.py
        settings.py
    security/
      tokens.py
      sessions.py
      passwords.py
      otp.py
      permissions.py
      events.py
    services/
      generation.py
      gallery.py
      feed.py
      billing.py
      accounts.py
    storage/
      paths.py
      private_media.py
      public_media.py
      cleanup.py
      backup.py
    integrations/
      comfyui.py
      openrouter.py
      ollama.py
      telegram.py
      max.py
      email.py
    models/
      requests.py
      responses.py
      domain.py
    observability/
      logging.py
      metrics.py
```

Эта структура создаётся постепенно. Нельзя создавать все файлы сразу пустыми и нельзя переносить весь `main.py` одним изменением.

## 4. Этап 0 — зафиксировать работающее состояние

### Задачи

1. Создать `backend/ARCHITECTURE.md`.
2. Создать автоматически обновляемый `backend/SYMBOL_MAP.md`:
   - функции;
   - классы;
   - routes;
   - номер строки;
   - auth policy.
3. Создать route matrix: route → handler → anonymous/user/admin/service.
4. Разделить тесты на:
   - fast;
   - security;
   - integration mock;
   - real ComfyUI;
   - real OpenRouter;
   - browser E2E.
5. Исправить запуск pytest из корня проекта.
6. Исправить 14 тестов с устаревшим `512x512` либо восстановить подтверждённую совместимость.
7. Зафиксировать API schemas критических routes.
8. Добавить команду `tools/verify.ps1`.

### Готово, когда

- fast/security suite зелёный;
- real-provider tests не входят в быстрый suite;
- агент может найти нужный блок без чтения всего `main.py`;
- текущие API зафиксированы тестами.

## 5. Этап 1 — исправить подтверждённые критические ошибки

Каждый подпункт выполняется отдельным PR до массового переноса функций.

### 1.1. Private media

1. Удалить публичный mount всего `backend/media`.
2. Разделить private gallery/source media и public feed derivatives.
3. Приватные файлы выдавать только после trusted session + ownership check.
4. Public feed получает специально подготовленную копию, не original.
5. Проверить path traversal и MIME.
6. Добавить negative tests: anonymous, другой user, deleted file.
7. Провести dry-run аудита существующих `/media/...` URL перед миграцией.

### 1.2. Bot management

Закрыть admin/service authorization:

- Telegram/MAX send message;
- poll once;
- set/delete webhook;
- configure bot;
- служебные status/diagnostics.

Public webhook receiver остаётся публичным, но проверяет platform secret.

### 1.3. Webhook secrets

- `TELEGRAM_WEBHOOK_SECRET` обязателен в Telegram webhook mode;
- проверять Telegram secret header constant-time;
- `MAX_WEBHOOK_SECRET` обязателен в MAX webhook mode;
- не логировать полный payload;
- body size/rate limit;
- idempotency/replay check по update id, если доступен.

### 1.4. OpenRouter secret

- прекратить запись ключа в SQLite;
- runtime secret вынести из repository;
- admin UI показывает только configured/source;
- перенести существующий ключ;
- удалить plaintext запись;
- ротировать ключ после переноса;
- backup БД больше не считается secret storage.

### 1.5. Deploy gate

- ошибка `tsc -b` немедленно останавливает deploy;
- ошибка lint/build/backend compile/security smoke останавливает deploy;
- build label автоматически равен Git commit;
- неуспешная сборка не трогает текущий работающий release.

### Готово, когда

- `/media/private` без сессии не возвращает файл;
- anonymous не управляет ботами;
- forged webhooks получают 403;
- действующих provider keys нет в SQLite;
- сломанный TypeScript невозможно опубликовать.

## 6. Этап 2 — разрезать `backend/main.py`

### 2.1. `app/config.py`

Перенести без изменения поведения:

- `.env`/environment reading;
- paths и URLs;
- timeout/limit defaults;
- cookie flags;
- provider modes;
- production validation.

Тесты:

- development defaults;
- production required values;
- invalid mode;
- environment override;
- secret value не попадает в repr/log.

### 2.2. `database/connection.py` и `guard.py`

Перенести:

- `DB_PATH` resolution;
- `db()`;
- pragmas;
- busy timeout;
- DB Guard;
- masked diagnostics.

Не переносить одновременно все SQL-запросы.

### 2.3. `database/schema.py` и `migrations.py`

Разделить огромный `init_db()`:

- identity/auth schema;
- core users/jobs/images;
- gallery/feed;
- billing/promos;
- admin/analytics;
- indexes;
- additive column migrations.

Добавить migration ledger/version. Все миграции остаются idempotent и additive.

### 2.4. `security/*`

Порядок:

1. `tokens.py` — generate/hash/compare.
2. `passwords.py` — Argon2 и policy.
3. `sessions.py` — create/resolve/refresh/revoke.
4. `permissions.py` — trusted user/admin/service.
5. `otp.py` — challenges/rate limits.
6. `events.py` — security/session/audit events.

Удаление legacy auth выполняется отдельным PR после подтверждения отсутствия consumers.

### 2.5. `storage/*`

Вынести всю работу с filesystem:

- canonical path;
- private/public classification;
- save/open/delete;
- thumbnails;
- ownership lookup;
- cleanup;
- storage audit.

После этого routers и integrations не собирают filesystem paths самостоятельно.

### 2.6. `integrations/*`

По одному PR:

1. Ollama.
2. OpenRouter.
3. Telegram.
4. MAX.
5. ComfyUI.

Каждая интеграция получает:

- client;
- typed errors;
- timeouts;
- redacted logs;
- health check;
- mock tests.

ComfyUI переносится последним: сначала HTTP client, затем workflow builder, затем result/media adapter.

### 2.7. `services/*`

Вынести business logic:

- generation orchestration;
- gallery lifecycle;
- feed publication/reactions;
- account/profile;
- billing/token ledger.

Services не зависят от FastAPI Request/Response, кроме явно переданных безопасных context values.

### 2.8. `api/routers/*`

Переносить routes в порядке:

1. health/version;
2. catalog/config;
3. account;
4. auth;
5. bots;
6. gallery;
7. feed;
8. generation;
9. admin;
10. billing mutations.

Router выполняет только transport validation, auth dependency, service call и response mapping.

### 2.9. Завершение

`backend/main.py` должен стать совместимым entrypoint:

```python
from app.application import create_app

app = create_app()
```

Временные re-export удаляются после обновления tests/scripts.

## 7. Этап 3 — разрезать frontend

### 3.1. `newUi.tsx`

Порядок переноса:

1. API types.
2. API client.
3. constants/config.
4. auth components/hooks.
5. generation polling hook.
6. upload/source selection hook.
7. model/resolution policy hook.
8. panels по generation mode.
9. gallery/feed/page sections.
10. page composition.

Целевая структура:

```text
frontend/src/
  api/
  auth/
  components/
  hooks/
  features/
    studio/
    gallery/
    feed/
    profile/
    admin/
```

### 3.2. `LegacyApp.tsx`

Legacy UI не удаляется и не отключается в рамках оптимизации.

- разделить API/hook/components;
- сохранить routes и поведение;
- общие helpers с новым UI перенести в shared modules;
- не выполнять редизайн одновременно с extraction.

### 3.3. `adminModels.tsx`

Разделить:

- `types.ts`;
- `api.ts`;
- hooks/state;
- provider status;
- resolution/model matrix;
- dialogs/actions;
- page.

### 3.4. CSS

Порядок:

1. tokens;
2. reset/base;
3. shared layout;
4. components;
5. feature styles;
6. responsive overrides рядом с feature.

Не менять внешний вид во время механического переноса. После каждого CSS PR — screenshots desktop/mobile и Telegram/MAX WebView smoke.

## 8. Этап 4 — разделить большие тесты

`test_feed_v2.py` разделить на:

- publications;
- ownership;
- reactions;
- moderation;
- media;
- challenges;
- admin actions.

`test_api.py` разделить на:

- health/config;
- generation lifecycle;
- gallery;
- providers;
- bots;
- admin summary.

Общие fixtures вынести в `conftest.py` и специализированные fixture modules. Test isolation обязательна; global state сбрасывается явно.

## 9. Этап 5 — оставшиеся найденные архитектурные проблемы

### SQLite

Сейчас не мигрировать. Сначала:

- измерять lock/busy errors;
- добавить конкурентные billing tests;
- явно определить transaction boundaries;
- добавить idempotency constraints;
- подготовить repository/database layer.

PostgreSQL — отдельный будущий проект после завершения database extraction, не часть текущего механического разделения.

### Frontend server

- заменить Vite Preview на Caddy;
- Caddy устанавливается только на текущем компьютере и раздаёт `dist`/proxy `/api`;
- существующий доменный tunnel продолжает работать без изменений;
- cache, body limits, timeouts, logs, security headers.

### Process management

- backend и Caddy как Windows Services;
- ComfyUI/Ollama как service/managed task;
- restart on failure;
- работа без открытых PowerShell-окон;
- никаких изменений внешнего VPS/tunnel.

### Backup

- SQLite Backup API;
- media incremental backup;
- копия на другом физическом диске;
- encrypted offsite copy;
- checksum и `quick_check`;
- регулярный restore test.

### Proxy/security configuration

- заменить `allowedHosts: true` точным allowlist до удаления Vite Preview;
- сохранить локальную привязку backend/frontend к `127.0.0.1`;
- доверять proxy headers только в текущем известном production-маршруте;
- secrets вне repository/SQLite;
- security headers через локальный Caddy/backend без изменения VPS.

### Billing

- append-only ledger policy;
- atomic charge/refund;
- idempotency key;
- concurrent request tests;
- audit каждого admin изменения;
- реальные платежи не включать до отдельного provider security design.

## 10. Порядок реализации PR

1. Architecture/Symbol/Route map.
2. Test classification и единая verify command.
3. Исправление 14 resolution tests.
4. Security tests для private media.
5. Исправление private media.
6. Bot management authorization.
7. Telegram/MAX webhook secrets.
8. OpenRouter secret storage.
9. TypeScript/deploy gate.
10. CI checks.
11. `app/config.py`.
12. `database/connection.py` + `guard.py`.
13. Разделение schema/migrations.
14. `security/tokens.py` + `passwords.py`.
15. `security/sessions.py` + permissions.
16. `security/otp.py` + events.
17. `storage/paths.py` + private/public media.
18. Ollama integration.
19. OpenRouter integration.
20. Telegram integration.
21. MAX integration.
22. ComfyUI client.
23. ComfyUI workflow/result modules.
24. Gallery service/router.
25. Feed service/router.
26. Account/auth routers.
27. Generation service/router.
28. Admin/billing service/router.
29. FastAPI application factory и lifecycle.
30. Уменьшение `main.py` до entrypoint.
31. `newUi.tsx` API/hooks extraction.
32. Studio components extraction.
33. Gallery/feed frontend extraction.
34. `adminModels.tsx` extraction.
35. `LegacyApp.tsx` extraction без удаления.
36. CSS tokens/base.
37. CSS components/features.
38. Разделение больших test files.
39. Caddy + Windows Services.
40. Backup/monitoring hardening.

## 11. Проверки после каждого PR

Минимум:

```text
python -m py_compile
backend fast tests
backend security tests
npm run lint
npm run build
```

Дополнительно по области:

- auth PR → auth/session/password/OTP tests;
- media PR → ownership/path/delete tests;
- generation PR → charge/refund/job lifecycle;
- feed PR → publication/reaction/media;
- bot PR → forged webhook/admin authorization;
- CSS/component PR → desktop/mobile visual smoke;
- deploy PR → health/version/no-session smoke.

## 12. Критерии завершения оптимизации

- `backend/main.py` — только application entrypoint/compatibility exports;
- нет route без явной auth policy;
- private media не раздаётся static mount;
- provider secrets отсутствуют в SQLite/repository;
- frontend monoliths разделены по feature;
- основные source files преимущественно до 300–500 строк;
- все fast/security tests зелёные;
- deploy блокируется при любой compile/build ошибке;
- API contracts и рабочие пользовательские сценарии сохранены;
- существующий доменный tunnel продолжает работать без изменений;
- каждый этап можно откатить независимо.

## 13. Что делаем первым

Первый рабочий пакет:

1. `backend/ARCHITECTURE.md` и `SYMBOL_MAP.md`.
2. Route/auth matrix.
3. Исправление test baseline.
4. Исправление `/media`.
5. Bot/webhook authorization.
6. После этого — реальное начало разделения с `app/config.py`.

Это одновременно уменьшает текущий security-риск и начинает сокращать расход контекста при дальнейшей разработке.
