# IZO_ASA — актуальный master plan оптимизации production

Дата новой базовой проверки: **2026-07-19**
Статус: **спецификации и evidence; исполняемая очередь с 2026-07-20 —
[optimization-and-decomposition-plan-20260720.md](optimization-and-decomposition-plan-20260720.md)**
Фактический аудит: [agent-compliance-audit-20260719.md](agent-compliance-audit-20260719.md)
Предыдущий план: `engineering-transformation-master-plan-20260717.md` — исторический checkpoint, не текущая очередь.

## Пакет `PHONE-PLATFORM-MASTER-20260824`

Статус: **APPROVED SPECIFICATION; IMPLEMENTATION NOT STARTED**.

- единый обязательный контракт мобильных изображений, видео, чата, звука и
  3D-моделирования зафиксирован в
  [phone-platform-master-plan-20260824.md](phone-platform-master-plan-20260824.md);
- текущий iframe/standalone runtime и phone chat sidecar считаются переходными
  механизмами и не получают новую бизнес-логику;
- общие обязательные зависимости: service-safe release, React App Shell,
  capability catalog, durable jobs, media ownership и единый финансовый cycle;
- этапы документа являются epics и реализуются отдельными bounded packages по
  правилам этого master plan;
- первый пакет — `REL-SVC-001`: доказать запуск проверенного backend-кандидата
  в production service context и автономный rollback; до этого новые Phone
  функции не публикуются;
- AdGuard VPN, FRP, VPS, DNS и production data вне scope без отдельного решения
  владельца.

## Пакет `PHONE-CHAT-MINIMAL-UX-20260824`

Статус: **CODE COMPLETE; TARGETED AND QUICK TESTS GREEN; FULL RELEASE VERIFICATION PENDING**.

- телефонный чат не показывает внутренний JSON и аргументы инструментов;
- markdown ответа отображается как читаемый текст без сырых `**`, сообщения и
  композер используют более компактные мобильные размеры;
- плашка о контексте убрана из непустого диалога, поиск не повторяет запрос и
  сворачивает источники в компактный раскрываемый блок;
- результат генерации не повторяет длинный технический промпт, помещает картинку
  в карточку и предлагает открыть, скачать, поделиться или оживить;
- acceptance: backend tool-envelope regression, frontend lint/build, focused
  Playwright на `390×844` и `430×932`, Quick, один Full на clean SHA, затем
  мобильная browser-проверка точного production release.

## Пакет `AUTH-SOCIAL-PROOF-20260822`

Статус: **CODE COMPLETE; QUICK AND FOCUSED TESTS GREEN; NOT DEPLOYED**.

- когда production не может доставить email-код, новая парольная регистрация
  создаёт ограниченный аккаунт без стартовых токенов и требует реальную
  подтверждённую identity MAX или Telegram до генерации изображений и видео;
- подтверждение выполняется существующим подписанным bot-login challenge и
  привязывает provider identity к той же internal account; повторная доставка
  события идемпотентна;
- сразу после регистрации интерфейс предлагает MAX/Telegram, через 24 часа
  повторяет просьбу при следующем входе, а через 30 дней неподтверждённый аккаунт
  блокируется и анонимизируется bounded worker; финансовые и audit-записи
  сохраняются, администратор и demo account защищены;
- если оба бота недоступны, production-регистрация закрывается с `503`, чтобы не
  создавать аккаунт, который невозможно подтвердить;
- acceptance: migration v4 idempotency, image/video denial before proof, both
  providers, conflict/idempotency, 24-hour reminder, 30-day retention, focused
  auth/worker suite 5x, frontend lint/build, generated maps, Quick, Full on exact
  clean SHA, SQLite Backup API snapshot, deploy and one real provider flow.

## Пакет `PROD-RELIABILITY-20260728`

Статус: **IMPLEMENTATION IN PROGRESS; FOCUSED TESTS GREEN; NOT DEPLOYED**.

- GitHub Actions переносится на выделенный self-hosted Windows runner с меткой `izo-ci`;
  workflow допускает только доверенный репозиторий и владельца, не сохраняет Git credentials
  и всегда очищает временные runtime-данные;
- production updater работает fail-closed: любой CI-результат кроме `success` устанавливает
  `BLOCKED_CI`; локальная проверка больше не заменяет внешний CI и не создаёт promotion marker;
- production frontend build обязан получить детерминированный release identity
  `<12-hex-sha>-<UTC commit timestamp>`; `dev`, `unknown` и пустое значение запрещены до копирования
  кандидата и повторно проверяются после запуска;
- ночной Yandex outbound использует совместимое с Windows PowerShell журналирование и сохраняет
  тип ошибки, FullyQualifiedErrorId, позицию и stack trace без раскрытия секретов;
- backend передаёт Ollama `keep_alive=-1` по умолчанию (переопределяется
  `OLLAMA_KEEP_ALIVE`), поэтому вызванная локальная модель остаётся загруженной в VRAM;
- обязательная приёмка: focused tests, обновлённый architecture inventory, единый
  `verify.ps1 -Mode CI`, зелёный self-hosted GitHub check на точном SHA, затем Full/promotion
  с rollback и проверкой PRIMARY, локальных и публичных HTTP, release marker, голоса и `/api/ps`.

Операционный checkpoint 2026-07-28: опасный marker кандидата `289f2e5319...`, подготовленный
старым billing fallback, изолирован; установленный updater повторно выдал `BLOCKED_CI`;
focused suite — `42 passed`. До зелёного self-hosted check активный release не меняется.

## Пакет `VIDEO-UX-ERROR-20260728`

Статус: **CODE COMPLETE, LOCALLY VERIFIED; DEPLOYMENT AND OPERATIONAL VERIFICATION PENDING**.

- отказ OpenRouter при запуске видео сохраняет закрытую техническую диагностику, возвращает
  списанные токены и показывает пользователю безопасную причину без URL и трассировки провайдера;
- мобильная история поддерживает перетаскивание мышью и пальцем, сохраняет пропорции вертикальных
  и широких изображений и видео, а выбранный ролик воспроизводится в основном и встроенном плеере;
- форматные кнопки, нижние действия, CTA, русские пояснения моделей и глобальные уведомления
  проверяются на `1920×1080`, `1920×900`, `3840×2160` и `390×844`;
- release acceptance: backend video/OpenRouter suites, frontend lint/build и focused Playwright,
  Quick, один Full, затем авторизованная безопасная генерация `image_to_video` с теми же
  параметрами, что у инцидента (`4 секунды`, `720p`, `9:16`, без звука).

Локальная проверка 2026-07-28: focused backend `108 passed`; responsive Playwright green на
четырёх viewport с mouse/touch drag и mobile error overlay; единый CI gate — `1748 passed`,
frontend lint/build/release identity/origin isolation/studio resilience green.

## Пакет `GUEST-STUDIO-ENTRY-20260728`

Статус: **CODE COMPLETE, LOCALLY VERIFIED; DEPLOYMENT PENDING**.

- чистая сессия студии изображений открывается с квадратным форматом `1:1` и качеством
  `HD 1024×1024` на компьютере и телефоне;
- публичная конфигурация видеостудии показывает гостю только включённый каталог и безопасные
  цены без квоты, приватной истории и внутренних настроек;
- кнопка запуска видео для гостя остаётся неактивной и явно предлагает войти;
- при отсутствии собственной истории нижняя полоса видео смешивает последние публичные фото
  и ролики из вкладки ленты «Новое» с сохранением пропорций;
- пустой видеопредпросмотр использует общий фирменный фон студии изображений;
- acceptance: backend guest-config regression, frontend lint/build, Playwright `1440×900`
  и `390×844`, существующая video-layout suite, Quick, затем Full и production browser check.

## Пакет `VIDEO-LTX23-LOCAL-001`

Статус: **CODE COMPLETE, OPERATIONAL VERIFICATION BLOCKED**.

- существующий контракт `/api/video/*`, история и галерея расширены локальным
  провайдером без второй видеосистемы;
- стартовые профили ограничены T2V, 2/4 секундами, 16:9 480p, без звука и с
  concurrency 1;
- локальная цена фиксируется до запуска и списывает дневные токены прежде
  основного баланса;
- workflow принадлежит серверу и не принимается от браузера;
- активные LTX/OpenRouter video jobs сохраняются при рестарте backend и
  продолжают опрос provider id;
- включение защищено `LOCAL_LTX_ENABLED=false` по умолчанию;
- инструкции и границы переноса:
  [local-ltx23-video-provider.md](local-ltx23-video-provider.md);
- live GPU smoke заблокирован на тестовой машине: ComfyUI сообщает
  `No CUDA GPUs are available`.
- 34 focused tests green; concurrency/restart checks green 5 повторов;
  repository Quick gate blocked только runtime-listener contract тестового Vite
  на 5173 против production Caddy.

## Пакет `VIDEO-LTX23-LOCAL-002`

Статус: **CODE COMPLETE, OPERATIONAL VERIFICATION BLOCKED**.

- добавлен переносимый manifest с точными версиями runtime, commit custom nodes,
  размерами и SHA-256 пяти обязательных моделей;
- добавлен PowerShell preflight для нового Windows-хоста: модели, workflow,
  версии Python/Torch/CUDA, CUDA-доступность и опциональный `/system_stats`;
- preflight отвергает сохранённый UI-граф с устаревшей ссылкой на отсутствующий
  vocoder и требует успешно экспортированный серверный API workflow;
- инструкция переноса и acceptance matrix:
  [local-ltx23-transfer-kit.md](local-ltx23-transfer-kit.md);
- operational gate остаётся заблокирован до появления CUDA в Torch на этой
  машине и реального Q3/Q4 smoke на новом сервере.

## Экстренный пакет `AUTH-BOT-P0-20260723`

Статус: **CODE COMPLETE**. Пакет имеет приоритет над плановой очередью, потому что
новые и вышедшие пользователи потеряли вход через Telegram/MAX, а устаревший
HTML мог оставлять уже открытый браузер на пустом экране после выпуска.

Область пакета:

- сохранённые в админке username/deep-link ботов применяются при старте backend
  вместе с DPAPI-токенами;
- выделенный MAX TLS-контекст получает проверенный корневой сертификат без
  установки системного CA и без отключения TLS-проверки;
- кнопки Telegram/MAX остаются видимыми и явно отключёнными, если provider ещё
  не готов, вместо бесследного исчезновения;
- отрицательный ответ проверки бота (`HTTP 200`, `ok=false`) больше не
  показывается админке как успех;
- production HTML получает `Cache-Control: no-store`, а hashed assets —
  `immutable`;
- acceptance: focused auth tests 5 раз, backend bot/TLS suites, frontend
  smoke/lint/build, Quick, один Full на точном release SHA, затем desktop/mobile
  и реальные Telegram/MAX provider checks с редактированным evidence.

Code evidence 2026-07-23: focused auth повторён 5 раз; bot/TLS suites — `44
passed`; полный изолированный release-контур — `1644 passed`, frontend
lint/build/release-identity/origin-isolation/studio-resilience — зелёные; живые
listener owners 5173/8000/8188/11434 подтверждены через WinSW ancestry и
service XML. Статусы `DEPLOYED`, `VERIFIED` и `OPERATIONALLY VERIFIED` ставятся
только после установки точного SHA и внешних desktop/mobile/provider проверок.

Follow-up reliability closure 2026-07-23: подтверждены независимые причины
`429` за FRP, накопление/перезапись challenge, потеря provider retry после
ошибки handler и блокировка popup после `await`. Реализация, redacted evidence,
rollback boundary и production acceptance вынесены в
[auth-bot-login-reliability-20260723.md](auth-bot-login-reliability-20260723.md).

Availability follow-up `AUTH-OUTAGE-P0-20260723`: a release rollback snapshot
held the backend offline for about 3.5 minutes and exposed `502` responses to
the login capability probe. The corrective package moves the database snapshot
to the SQLite online Backup API and makes the login modal recover automatically
from a transient capability-probe failure. Evidence and acceptance criteria are
recorded in
[auth-bot-login-reliability-20260723.md](auth-bot-login-reliability-20260723.md).

## Emergency package `AUTH-MAX-IDENTITY-P0-20260801`

Status: **CODE COMPLETE**. Production read-only evidence showed that 32 successful
MAX bot logins over 30 days used one provider id and one internal account. The
stored MAX profile had `is_bot=true`. Telegram did not exhibit the defect: its
eight provider ids resolved to eight distinct internal accounts.

Root cause: a MAX `message_callback` includes the original bot-authored message
and the human actor who pressed its button. Identity extraction consulted
`callback.message.sender` first, so the bot identity won before the callback
actor could be considered.

Package scope and acceptance:

- resolve callback/bot-start actor fields before any nested message sender;
- refuse `is_bot=true` profiles as login identities;
- preserve the existing mixed account and revoke its trusted sessions only
  after the corrected release is active and a fresh verified backup exists;
- do not guess ownership or redistribute existing mixed media automatically;
- focused MAX/auth tests five times, CI/Quick/Full gates, clean exact-SHA release,
  local/public health, then one redacted real-user MAX login proving a new human
  provider id creates a distinct internal account.

Code evidence 2026-08-01: focused MAX/auth contracts passed five consecutive
runs (`33 passed` each); repository CI passed with `1761 passed`, frontend
lint/build/release-identity/origin-isolation/studio-resilience green. The Quick
live gate remains blocked only by the pre-existing missing
`.runtime/active-frontend.json` deployment-integrity manifest and was not
bypassed or fabricated. `DEPLOYED` and provider-level verification remain
separate release/operational gates.

Availability follow-up `IMG-WATCHDOG-P0-20260723`: an image-edit prompt could
fill VRAM, outlive an application-side history request timeout and leave
ComfyUI running while the application queue advanced. The corrective package
keeps the selected model, prevents reference upscaling, enforces the existing
face megapixel budget, separates the five-minute image deadline from video,
and gates later submissions until a privileged ComfyUI-only restart is healthy.
The recovery helper does not mutate the persistent application queue. Design,
installation and acceptance evidence are recorded in
[comfyui-image-vram-watchdog-20260723.md](comfyui-image-vram-watchdog-20260723.md).
The 2026-07-24 follow-up also closes the model-switch gap in outpaint: 4B keeps
its compatible LoRA path, while 9B now has the official KV FP8 checkpoint and
retains `FluxKVCache`. A real local 9B outpaint completed in 52.3 seconds
without cancelling or reordering the next application job.

## 0. Ответ: готов ли этот план к реализации

Да. План разбит на ограниченные пакеты с порядком, областью изменения,
обязательными тестами, production boundary, rollback и критериями завершения.
Первый следующий кодовый пакет определён однозначно: **`REL-LOCK-001`**.

План не обещает одномоментно сделать проект «идеальным». Он задаёт безопасную
последовательность для уже работающего продукта с реальными пользователями:

1. остановить гонки агентов и закрыть публичные diagnostics;
2. доказать работоспособность Telegram, mail и backup, не меняя VPS;
3. усилить auth, workers, billing и process supervision;
4. по одному seam уменьшать большие backend/frontend файлы;
5. переходить на Linux/PostgreSQL/внешнюю очередь только по измеряемым scale
   triggers, а не ради моды.

## 1. Неизменяемые решения владельца

- Application stack сейчас работает на одном личном Windows-компьютере.
- VPS используется только как transport домена/tunnel. Пакеты этого плана не
  меняют VPS, FRP, DNS или домен без отдельного явного запроса.
- Проект уже production: есть пользователи, платежи, jobs, изображения, feed,
  gallery, Telegram/MAX и mail integration.
- Оптимизация должна сохранять пользовательское поведение и данные.
- Текущие providers: YooKassa для платежей и UniSender/mail adapters для почты.
  Их не меняем без доказанной продуктовой/операционной причины.
- Администратор может просматривать пользовательский оригинал для поддержки;
  доступ должен быть role-gated и аудироваться.
- Начальная экономика рассчитана на локальный host. Budget/managed services
  пересматриваются при росте, а не являются blocker текущей оптимизации.
- Linux/Docker/PostgreSQL — будущий scale step, не текущая цель.

## 2. Базовая точка

| Показатель | Baseline 2026-07-19 |
|---|---|
| Git | `main == origin/main == dbb1ca253dfea926096bc494a03449d9f9917cc6` до governance package |
| Live release | `dbb1ca253dfe-20260719043420` |
| Runtime | Python 3.11.9, Node 24.14.1, Caddy edge, FastAPI/Uvicorn |
| DB | SQLite `user_version=1`, 57 tables, ~565 MB, один live writer process |
| Backend monolith | 20,311 lines; 728 top-level functions; 83 classes; 223 routes |
| Frontend large files | `newStudioV3.css` 5,875; `newUi.tsx` 4,378; `LegacyApp.tsx` 3,600 |
| Workers | generation, Telegram polling, MAX polling, feed-video publication |
| Backup | local hourly/cloud daily fresh; health `ATTENTION` из-за AdGuard VPN route |
| External CI | GitHub Actions запускается, но billing/spending blocker завершает run до steps |

Baseline подтверждает текущее состояние, но не фиксирует его навсегда. Каждый
пакет заново проверяет Git/live/process/data boundary.

## 3. Значения статусов

| Статус | Что он означает |
|---|---|
| `TODO` | пакет ещё не начат |
| `ACTIVE` | есть один назначенный owner и текущий WIP |
| `IN REVIEW` | bounded package реализован в ветке и проходит review/acceptance gates |
| `CODE COMPLETE` | код/документация реализованы и targeted tests зелёные |
| `DEPLOYED` | exact SHA/release активен в production |
| `VERIFIED` | все acceptance gates пакета подтверждены evidence |
| `OPERATIONALLY VERIFIED` | реальный provider/user flow подтверждён redacted receipt |
| `BLOCKED` | named external dependency не позволяет пройти следующий gate |

Нельзя заменять один статус другим. В частности, зеленый unit test не делает
mail `OPERATIONALLY VERIFIED`, а HTTP 200 не доказывает корректность UI.

## 4. Инварианты любого пакета

1. Перед началом выполняются правила `AGENTS.md` и фиксируется preflight.
2. Один owner — один пакет; release/Full verify — строго single-flight.
3. Production DB/media/secrets/providers не используются тестами.
4. Сначала characterization/negative/race test, затем изменение поведения.
5. Публичный API сохраняется или меняется через явно документированную версию.
6. Новая backend-логика не добавляется в `backend/main.py`.
7. Protected-file budgets не повышаются для принятия роста.
8. Generated maps меняются в том же code-bearing commit.
9. Full suite не запускается несколько раз параллельно.
10. Deploy/restart выполняется только если входит в пакет и явно разрешён.
11. UI-пакет включает desktop/mobile evidence; static `/feed` и `/gallery`
    проверяются отдельно от React shell.
12. Commit, docs и push входят в Definition of Done; deploy имеет отдельный статус.

## 5. Точная очередь исполнения

| Порядок | ID | Приоритет | Результат | Статус |
|---:|---|---|---|---|
| 0 | `GOV-001` | P0 | единые правила и новый plan/audit | `VERIFIED` |
| 1 | `REL-LOCK-001` | P0 | один publisher/Full verifier, no race | `VERIFIED` 2026-07-20 (evidence в секции пакета) |
| 2 | `SEC-DIAG-001` | P0 | public API не раскрывает operator details | `VERIFIED` 2026-07-20 (evidence в секции пакета) |
| 3 | `BOT-TG-001` | P0 | Telegram polling operational health доказан | `VERIFIED` 2026-07-20 (evidence в секции пакета) |
| 4 | `BACKUP-NET-001` | P1 | backup health зелёный с approved route | `REGRESSION_REPAIR` 2026-07-27; nightly upload must pass the next 02:00-05:00 gate |
| 5 | `MAIL-OPS-001` | P1 | UniSender delivery подтверждён | `DEFERRED_BY_OWNER` 2026-07-20 |
| 6 | `AUTH-LEGACY-001` | P1 | legacy auth consumers безопасно сокращаются | WIP сохранён как handoff (см. current-status); active code package отсутствует; далее `AUTH-LEGACY-001A` по плану 20260720 |
| 7 | `OPS-001` | P1 | service supervision и reboot/crash recovery | `TODO` |
| 8 | `REL-002` | P1 | immutable backend A/B switch + drain | `TODO` |
| 9 | `OBS-001` | P1 | actionable health/metrics/receipt evidence | `TODO` |
| 10 | `DB-MIG-002` | P1 | все новые schema changes — versioned migrations | `TODO` |
| 11 | `WORK-001` | P1 | persistent leasing/recovery/watchdogs | `TODO` |
| 12 | `BILL-001` | P1 | единая финансовая transaction boundary | `TODO` |
| 13 | `ARCH-BE-A..G` | P2 | `main.py` становится composition shell | `TODO` |
| 14 | `ARCH-FE-A..E` | P2 | frontend/CSS делятся по features | `ARCH-FE-A / Wave 1 — IN REVIEW`; `ARCH-FE-B..E — TODO` |
| 15 | `PORT-001` | P2 | воспроизводимый новый Windows host/standby | `TODO` |
| 16 | `SCALE-001` | trigger-based | Linux/PostgreSQL/queue readiness | `NOT TRIGGERED` |

Новая feature/UI правка может войти между пакетами только если не пересекает их
файлы/инварианты, имеет собственного owner и проходит свой targeted gate. Она не
перепрыгивает P0 security/release blockers для production deploy.

## 6. P0: управление агентами, release и публичная безопасность

### GOV-001 — единые правила для всех агентов

Цель: устранить противоречивые инструкции.

Состав:

- корневой `AGENTS.md`;
- актуальный `CLAUDE.md`;
- `.github/copilot-instructions.md`;
- `GEMINI.md`;
- автоматический `tools/test_agent_instructions.py`;
- этот plan и evidence audit;
- README указывает новый источник истины;
- старый master plan помечен superseded.

Acceptance:

- каждый adapter требует прочитать `AGENTS.md`;
- stale запреты старой identity-фазы отсутствуют;
- тест правил проходит;
- Quick verification зелёный;
- package committed и pushed без deploy/restart.

Verification evidence для этого package:

- `tools/test_agent_instructions.py`: 3 tests passed, пять последовательных
  запусков;
- architecture inventory и backend symbol map: `--check` passed;
- `tools/verify.ps1 -Mode Quick`: 79 tests passed, 55.58 s, source stable;
- production restart/deploy этим governance package не выполнялся.

### REL-LOCK-001 — single-flight repository operations

Цель: два агента физически не могут одновременно публиковать release или
запускать duplicate Full verification.

Предлагаемая реализация:

1. общий helper `tools/repository-operation-lock.ps1`;
2. атомарный lock directory под `.runtime/locks/<kind>`;
3. owner metadata: operation id, PID, process start time, SHA, command, UTC start;
4. отдельные kinds `public-release` и `full-verify`;
5. re-entrancy token, чтобы publisher мог вызвать verifier без deadlock;
6. `try/finally` release;
7. stale recovery только если PID/process-start больше не совпадает; TTL сам по
   себе не имеет права убить живого owner;
8. второй owner завершает работу до tests/build/runtime mutation с ясной ошибкой;
9. `start-public.bat`, publisher и `verify.ps1 -Mode Full` используют helper;
10. lock metadata игнорируется Git и не содержит secrets.

Обязательные тесты:

- два concurrent publisher preflight: победитель один;
- второй не запускает pytest/build/restart;
- stale dead PID восстанавливается;
- PID reuse не считается тем же owner без совпадения process-start;
- exception освобождает lock;
- re-entrant publisher -> Full verify не deadlock;
- focused concurrency suite проходит **5 последовательных раз**;
- Quick и один Full receipt проходят один раз на clean SHA.

Production boundary: не менять DB/media/VPS; deploy нужен только в отдельном
release step после code verification, не для проверки самого lock helper.

Rollback: удалить wiring на helper, сохранив прежние launch commands; lock
directories безопасно остаются runtime evidence.

Реализация 2026-07-20:

- `tools/repository-operation-lock.ps1`: dot-sourceable библиотека
  (`Lock-IzoRepositoryOperation` / `Unlock-IzoRepositoryOperation`) + CLI
  (`acquire`/`release`/`status`) для batch launchers; атомарность через staging
  directory и `Directory.Move`; владелец фиксируется как PID + точное UTC время
  старта процесса; stale recovery только при мёртвом PID или PID reuse; TTL не
  применяется к живому владельцу; re-entrancy через env token
  `IZO_REPO_LOCK_TOKEN_<KIND>`.
- `tools/verify.ps1 -Mode Full` берёт `full-verify` до любых
  pytest/build/runtime шагов и освобождает в `finally`; Quick/CI не блокируются.
- `tools/publish-frontend-release.ps1` берёт `public-release` (re-entrant из
  `start-public.bat`) и `full-verify`, экспортирует token дочернему verifier.
- `start-public.bat` владеет `public-release` на всё время запуска; владелец —
  cmd-процесс launcher, поэтому crash восстанавливается автоматически; release
  на всех exit paths через `:release_lock`.

Verification evidence:

- `tools/test_repository_operation_lock.py`: 9 tests
  (concurrent single winner; second Full verify fails fast без единого
  VERIFY_STEP; stale dead PID recovery; PID reuse отклонён по start time;
  живой owner не отбирается; exception освобождает lock; re-entrant без
  deadlock и без освобождения внешнего lock; чужой token не может release;
  wiring всех трёх entrypoints) — `9 passed` в пяти последовательных запусках;
- `tools/verify.ps1 -Mode Quick`: 79 passed, 48.75 s, source stable;
- contract-тесты verify/launchers/collection после включения нового файла в
  Quick-набор: 26 passed;
- первый Full запуск честно упал: новый тест был негерметичен (пытался взять
  `full-verify`, который законно держал внешний verifier); исправлено commit
  `3fc06fe` — тест переиспользует живой busy state и убирает re-entrancy token
  у дочернего verifier; lock при падении корректно освобождён `finally`,
  остаточных pytest не было;
- Full receipt на clean SHA `3fc06fef0b58…`: 1564 passed, frontend
  lint/build/identity/origin/resilience PASS, receipt
  `3fc06fef0b58-20260720105555-rellock.json`;
- live proof: работающий Full держал `full-verify` (owner PID 15704,
  stale=False), статус после — FREE.

Deployment evidence 2026-07-20 (рестарт явно разрешён владельцем):

- окно спокойное: active jobs 0, `preparing` feed publications 0 (read-only);
- `start-public.bat` владел `public-release` (owner cmd PID 29472); publisher
  re-entered по token, принял exact-SHA receipt без второго Full;
- candidate smoke на 5197 OK, активация `caddy-reload`, release
  `3fc06fef0b58-20260720110528`, previous `dbb1ca253dfe-20260719043420`
  сохранён для rollback;
- controlled backend restart: oldPid=28452 → newPid=64648, start 11:05:52;
- локальные пробы: health/capabilities 200; dev-client=False; hashed
  asset=True; release meta/shell `/feed` `/gallery`/api-version совпадают;
  generate/gallery/me-v2 no-session = 401;
- публичный домен: `/`, `/feed`, `/gallery`, `/api/health` 200,
  `/api/version` = `3fc06fef0b58-20260720110528`;
- оба lock освобождены (FREE); порт 8000 — один владелец 64648; 8001 свободен;
- свежий backend лог: 0 error-строк, 0 `TelegramTransportError`, MAX polling
  200.

Статус пакета: `VERIFIED` (код + acceptance в production окружении).

### SEC-DIAG-001 — минимальные публичные status endpoints

Цель: убрать operator intelligence из unauthenticated API.

Изменения:

- `/api/platforms` возвращает только public capability/ready/button/command data;
- абсолютный `DB_PATH` и database existence удаляются;
- `/api/bots/status` либо становится минимальным public product status, либо
  существующие consumers переводятся на новый public DTO;
- полные token/mode/URL/TLS/probe diagnostics остаются только в
  `/api/admin/bots/status-v2` с `require_trusted_admin`;
- payload builder и routes выносятся из `main.py` как первый low-risk seam;
- frontend/static consumers и кеширование проверяются до изменения.

Tests:

- anonymous payload не содержит drive letter, `DB_PATH`, token presence,
  webhook URL, TLS/proxy/internal API base;
- non-admin не получает admin diagnostics;
- trusted admin получает необходимые redacted diagnostics;
- `/new`, `/feed`, `/gallery` smoke не регрессируют;
- contract tests выполняются до/после extraction.

Acceptance: public redaction verified local/public; exact SHA deployed только
после authorized release.

Реализация 2026-07-20:

- новый seam `backend/app/services/platform_status.py`:
  `public_platforms_payload()` и `public_bots_status_payload()` — только
  product capability (ready/url/commands/buttonText); маршруты в `main.py`
  стали thin adapters;
- `bot_status_payload()` удалён из `main.py`; operator diagnostics существуют
  только в `/api/admin/bots/status-v2` (`require_trusted_admin`, 401 anonymous);
- из `/api/platforms` удалён блок `database` (абсолютный `DB_PATH` и
  existence); из `/api/bots/status` удалены tokens/mode/publicUrls/webhook/
  TLS/polling диагностика;
- consumers проверены до изменения: единственный frontend consumer —
  `frontend/e2e-stage1.mjs` (обновлён; UI не использует эти поля), README
  обновлён; admin UI использует `status-v2`;
- новый `backend/test_public_status_redaction.py` (4 теста: product-safe
  platforms; минимальный bots status без operator-ключей; сконфигурированный
  internal `BACKEND_PUBLIC_URL` не протекает; admin diagnostics 401);
- обновлены `test_api.py`, `test_bot_login_flow.py` под новый контракт;
- budgets ratcheted down в том же commit: `main.py` max_lines 20314→20258,
  functions 750→727, classes 90→83, routes 230→223.

Verification evidence:

- focused: 88 passed (redaction+api+bot_login+admin_bots); redaction file —
  5 последовательных запусков 4 passed;
- `tools/verify.ps1 -Mode Quick`: 88 passed, 52.76 s, source stable;
- generated maps/inventory регенерированы в том же commit;
- Full receipt на clean SHA `432f9b38199d…`: 1568 passed + все frontend gates,
  receipt `432f9b38199d-20260720112049-secdiag.json`.

Deployment evidence 2026-07-20 (рестарт разрешён владельцем, окно спокойное —
0 active jobs, 0 preparing publications):

- release `432f9b38199d-20260720112903` через locked pipeline: receipt принят
  без второго Full, candidate smoke OK, `caddy-reload`, backend
  oldPid=64648 → newPid=47856, previous release сохранён;
- локальные пробы: health/api 200, release identity совпадает,
  generate/gallery/me-v2 no-session = 401;
- публичный домен: `/`, `/feed`, `/gallery`, `/api/health` 200,
  `/api/version` = `432f9b38199d-20260720112903`;
- live redaction на `https://izo.alikinas.ru`: `/api/platforms` keys =
  web/telegram/max (без `database`), `/api/bots/status` keys = ok/platforms;
  в сериализованных payload нет drive letter, sqlite, token, webhook,
  `127.0.0.1:8000`, `platform-api`; anonymous `/api/admin/bots/status-v2` = 401;
- свежий backend лог: 0 error-строк; оба lock FREE; порт 8000 — один
  владелец 47856; 8001 свободен.

Статус пакета: `VERIFIED` (код + public redaction в production).

### BOT-TG-001 — Telegram operational recovery

Цель: заменить «token configured» на доказанную доставку/polling health.

Диагностика до изменения:

- один ли backend владеет polling;
- webhook действительно выключен оператором для polling mode;
- DNS/TLS/proxy/firewall/IPv4/IPv6 path до Telegram API;
- timeout class и safe error code без token/URL leakage;
- last successful `getMe` и `getUpdates` timestamps;
- cursor before/after restart;
- retry/backoff/jitter и rate-limit behavior.

Реализация:

- provider health model с last success, last safe error, consecutive failures;
- bounded exponential backoff + jitter;
- alert после порога, recovery event после успеха;
- один owner; startup не создаёт duplicate polling task;
- admin UI показывает operational state, public API — только minimal readiness.

Tests: fake transport timeout/TLS/429/5xx/success, cursor idempotency, restart
recovery, duplicate-owner prevention. Real verification не удаляет webhook и не
сбрасывает cursor автоматически.

Acceptance: redacted `getMe`/poll cycle success и controlled restart evidence.

Реализация 2026-07-20:

- новый seam `backend/app/services/polling_health.py`: `PollingHealthRegistry`
  (last success/failure timestamps, safe error class, consecutive failures,
  alert exactly-once на пороге, recovery event), `compute_poll_backoff`
  (bounded exponential + jitter; более длинный provider Retry-After всегда
  уважается), сюда же перенесены `polling_retry_after` /
  `is_auth_polling_error`;
- worker'ы Telegram/MAX используют общий `_provider_polling_cycle`: health на
  каждом цикле, лог-маркеры `BOT_POLLING_ALERT`/`BOT_POLLING_RECOVERED` только
  с классом исключения; auth-ошибка по-прежнему останавливает worker и пишет
  `security_events`;
- `start_bot_polling_tasks`: живой owner никогда не дублируется; завершённый
  task заменяется только явным вызовом start (restart recovery);
- admin `/api/admin/bots/status-v2` получил `pollingHealth` для обоих
  провайдеров; public API не изменился (минимальный после SEC-DIAG-001);
- webhook не удаляется, cursor не сбрасывается — нигде автоматически;
- `mini_app_url` дедуплицирован в `platform_status.mini_app_public_url`;
  budgets ratcheted: max_lines 20258→20257, functions 727→725.

Verification evidence:

- `backend/test_polling_health.py`: 10 tests (bounded backoff+jitter;
  provider Retry-After; классификаторы на fake transport/429/5xx/auth;
  alert exactly-once + recovery; snapshot без секретов; worker cycle с
  ростом backoff и recovery; auth-stop с security_event; duplicate-owner
  prevention; restart recovery; cursor advance + идемпотентность пустого
  poll) — `10 passed` в пяти последовательных запусках;
- focused (polling_health+api+bot_login+admin_bots+integrations):
  131 passed; исправлен `FakeTask` в `test_api.py` (нужен `done()`);
- `tools/verify.ps1 -Mode Quick`: 88 passed, 65.01 s, source stable;
- generated maps/inventory в том же commit;
- Full receipt на clean SHA `263377ff0d5d…`: 1578 passed + все frontend gates,
  receipt `263377ff0d5d-20260720114925-bottg.json`.

Deployment/operational evidence 2026-07-20 (рестарт разрешён владельцем, окно
спокойное — 0 active jobs, 0 preparing publications):

- release `263377ff0d5d-20260720115826` через locked pipeline
  (`caddy-reload`); backend oldPid=47856 → newPid=64648, start 11:58:50;
- публичный smoke: `/`, `/api/health` 200; `/api/version` =
  `263377ff0d5d-20260720115826`; no-session generate/gallery/me-v2 = 401;
- стартовый лог: `telegramMode=polling maxMode=polling`;
- окно наблюдения 8+ минут: 0 `TelegramTransportError`, 0
  `telegram polling error`, 0 `BOT_POLLING_ALERT`, err-лог пуст — при
  long-poll timeout 25 s это ≥19 успешных Telegram-циклов, так как каждый
  сбой обязан оставить лог-строку с backoff;
- MAX: 19 × `MAX_POLL_RESPONSE status=200` за то же окно (прямое evidence);
- порт 8000 — один владелец 64648; оба operation lock FREE;
- webhook не удалялся, cursor не сбрасывался.

Статус пакета: `VERIFIED`; polling health `OPERATIONALLY VERIFIED` в окне
наблюдения (redacted log evidence без token/URL).

## 7. P1: backup, mail и операционная устойчивость

### BACKUP-NET-001R — nightly Yandex regression repair (2026-07-27)

#### SOCKS5-EGRESS-001 — explicit provider egress (2026-08-14)

The previous AdGuard application-exclusion design is being replaced because a
WFP/Wintun exclusion is not strong proof that FRP or Yandex.Disk bypasses the
VPN. The approved target architecture is:

1. AdGuard VPN runs in SOCKS5 mode and exposes a loopback-only listener.
2. `IZOBackend` receives `ALL_PROXY=socks5://127.0.0.1:<port>` and
   `NO_PROXY=127.0.0.1,localhost,::1`; pinned `httpx` plus `socksio` are release
   dependencies.
3. `IZOFrpc` and `YandexDisk4` receive no proxy environment and use the normal
   physical-interface route. Their old AdGuard app exclusions are no longer a
   security boundary.
4. The production switch validates the listener owner, performs credential-free
   OpenRouter and Telegram HTTPS probes, backs up the WinSW XML, restarts only
   `IZOBackend`, verifies local/public health, and restores the XML on failure.
5. Acceptance requires one FRP process, one established FRP connection sourced
   from a physical-interface address, a direct Yandex HTTPS probe, a live
   AdGuard-owned SOCKS5 listener, and public `ready=true`.

The legacy application-exclusion route remains a compatibility fallback for an
older deployed release until this package is promoted. It is not the target
state.

Current evidence:

- the scheduled 02:00 PRIMARY outbound cycle collided with the half-hour local
  backup and exited with code 3;
- one controlled retry at 02:57 created and verified local snapshot
  `20260726T235727.138048Z`, but the cloud-stage child exited with code 1;
- the deployed `C:\IZO_ASA\runtime\stage_cloud_backup.ps1` was older than the
  repository policy and treated a generic PowerShell route through `AdGuard VPN`
  as a fatal result;
- AdGuard logs prove both the Yandex.Disk application-exclusion configuration
  and process-specific `VPN_CA_FORCE_BYPASS` events for the exact executable on
  2026-07-23. No new event was captured as part of the failed 2026-07-27 stage,
  so the event timestamp remains explicit and a successful new nightly cycle is
  still required. Configuration and observed-event evidence remain separate in
  health output;
- local/public production remained available; no VPN, route, token, FRP, or
  security setting was changed.

Repair contract:

1. `IZO_ASA Local Backup 30m` runs as SYSTEM and a verified local snapshot stays
   younger than 45 minutes.
2. `IZO_ASA Yandex Outbound Nightly` runs only from 02:00 to 05:00
   Europe/Moscow in the interactive user context.
3. Local-backup exit code 3 is contention: the outbound runner waits once for
   the active backup and never launches a parallel copy.
4. `IZO_ASA Yandex Daytime Guard` runs at 05:00 and at logon, removes persistent
   autostart, and stops Yandex.Disk outside the approved window.
5. Network health records HTTPS reachability, probe interface, configured
   application exclusion, and process-specific observed bypass independently.
   A configured application exclusion prevents the generic PowerShell probe
   interface alone from becoming a false fatal error.
6. Legacy PRIMARY-incompatible receive/rehearsal/cloud-stage tasks remain
   disabled.
7. The update is promoted only after PowerShell parsing, focused backup tests,
   the full local CI verifier, and rollback-safe release promotion succeed.

Acceptance gate: `PRIMARY/databaseWriter=true`; local verified backup age
`<45m`; latest nightly cloud stage age `<30h`; outbound task last result 0;
manifest/hash/SQLite verification green; daytime guard effective after 05:00;
local and public HTTP green. Until a real cycle passes in the approved window,
the offsite portion is `AWAITING_OPERATIONAL_PROOF`, not `VERIFIED`.

### BACKUP-NET-001 — зелёный offsite backup route

Цель: убрать единственную текущую backup health ошибку без отключения защиты
вслепую.

Шаги:

1. зафиксировать текущий AdGuard/VPN mode и route evidence;
2. настроить approved split route для Yandex Disk endpoints либо явно изменить
   policy после owner decision;
3. не ослаблять firewall/listeners;
4. дождаться hourly local и daily cloud stage;
5. выполнить verify-only и rehearsal restore последнего snapshot;
6. сохранить health evidence вне Git без секретов.

Acceptance: task last result 0, `OverallStatus=OK`, fresh local/cloud snapshot,
verified manifest и successful restore rehearsal.

Реализация и evidence 2026-07-20:

- owner decision: Яндекс Диск внесён в exclusions AdGuard VPN; функциональная
  проверка подтвердила in-tunnel split — egress, который видит Яндекс,
  отличается от общего VPN egress (адреса сравнивались только в памяти и не
  сохранялись);
- policy `ops/backup/check_backup_health.ps1` обновлена по owner decision:
  ошибка `yandex_routed_through_adguard_vpn` ставится только когда маршрут
  идёт через AdGuard И split НЕ доказан (fail-closed при недоступности любой
  из двух egress-проб); в health добавлен boolean `YandexEgressSplitActive`;
  firewall/listeners не менялись;
- runtime-копия `C:\IZO_ASA\runtime\check_backup_health.ps1` синхронизирована;
  scheduled task `IZO_ASA Backup Health 10m` запущена штатно: Last Result 0;
- `C:\IZO_ASA\health\backup-current.json`: `OverallStatus=OK`,
  `YandexSyncErrors=[]`, `YandexEgressSplitActive=true`, свежие
  `LastLocalBackup` (hourly) и `LastCloudStage` (daily 01:00);
- verify-only: `BACKUP_VERIFY_OK` + `LOCAL_BACKUP_STATUS_OK`
  (snapshot 565 MB DB, 1175 media files, manifest sha в health);
- rehearsal restore: `REHEARSAL_RESTORE_OK` новейшего snapshot в
  `D:\IZO_ASA_RestoreTest` (snapshot читался, production не затрагивался);
- новый contract-тест `test_yandex_route_check_requires_proven_egress_split`
  в `tools/test_backup_automation.py`; backup-тесты 17 passed; Quick 88
  passed;
- health evidence хранится вне Git и не содержит секретов/адресов.

Статус пакета: `VERIFIED`; маршрут `OPERATIONALLY VERIFIED` (split доказан
на живом соединении).

### MAIL-OPS-001 — UniSender от настройки до доставки

Цель: доказать реальную отправку, сохранив тесты безопасными.

Кодовые требования:

- API key только env/DPAPI;
- provider adapter не смешан с route;
- retry policy не дублирует письмо;
- durable outbox/idempotency key для обязательных уведомлений;
- safe provider error taxonomy и metrics;
- admin verify endpoint не возвращает key/request secrets.

Operator gate:

- владелец явно указывает безопасный тестовый адрес;
- отправляется одно маркированное письмо;
- фиксируются provider message id/time и факт получения без адреса/ключа в Git;
- 502/timeout проверяются как retryable, auth/template errors — fail-fast.

Acceptance: unit/integration tests + один полученный test email =
`OPERATIONALLY VERIFIED`. Без inbox evidence статус не выше `DEPLOYED`.

2026-07-20: `DEFERRED_BY_OWNER` («работу с почтой пропускаем»). UniSender-код
остаётся `DEPLOYED`; доставка не доказывалась; operator gate не выполнялся.
Возобновление возможно с той же спецификацией.

### AUTH-LEGACY-001 — закрытие compatibility authorization

Цель: legacy идентификаторы никогда не дают доступ к protected state.

Шаги:

- построить route matrix: public/optional/session/user/admin/webhook;
- negative tests для `X-OneNode-User`, изменяемой cookie, unsigned Telegram/MAX;
- доказать, что reviewed legacy consumers только создают compatibility output или
  security audit;
- перевести оставшиеся protected routes на trusted dependencies;
- удалять allowlist entry сразу после consumer removal;
- не менять `users.id` destructively; internal identity остаётся additive;
- закрыть CSRF для cookie-auth mutations и проверить SameSite/Secure policy.

Acceptance: legacy protected-route consumers = 0; compatibility output имеет
явную дату удаления; auth focused suite 5x; live login/logout/session/admin smoke.

### OPS-001 — Windows service supervision

Цель: stack восстанавливается после crash/reboot без ручных PowerShell окон.

Решение для текущего host: pinned WinSW либо эквивалентный проверенный wrapper под
выделенной Windows account, потому что DPAPI и model stores account-bound.

Services/ownership:

- Caddy;
- backend;
- ComfyUI dependency;
- Ollama dependency;
- optional Qwen ASR;
- tunnel launcher только в пределах локальной стороны текущей конфигурации.

Backup tasks могут остаться Task Scheduler.

Acceptance: least-privilege account, delayed dependency ordering, restart
backoff, log rotation, crash rehearsal, full reboot rehearsal, exact release
identity, DPAPI read, local/public smoke. VPS/FRP configuration не меняется.

2026-07-22 cold-start hardening: интерактивный production orchestrator создаёт
exact-SHA CI verification receipt, когда backend ещё не имеет listener после
перезагрузки, и передаёт её штатному immutable publisher. Это устраняет
циклическую зависимость «backend должен работать до собственного запуска».
Полный запуск до входа пользователя остаётся в OPS-001: он требует отдельной
Windows service identity и подтверждённого доступа этой identity к DPAPI,
моделям и GPU runtime; Startup-folder сценарий выполняется только после входа.

### REL-002 — immutable backend A/B

Цель: release не зависит от mutable checkout после activation.

Требования:

- immutable backend artifact/manifest с requirements/runtime identity;
- candidate backend на отдельном loopback port;
- schema compatibility preflight до switch;
- readiness и focused smoke;
- Caddy/API switch только после readiness;
- drain старого backend и workers;
- rollback artifact остаётся runnable;
- DB migration compatibility window forward/backward документирована.

Acceptance: fault-injected candidate не затрагивает old backend; successful
switch не теряет jobs; rollback rehearsal; exact frontend/backend identity.

### OBS-001 — evidence и alerts

- Full receipt фиксирует pytest passed/failed/skipped counts, runner versions,
  frontend lint/build summary и durations;
- worker health: queue depth/age, oldest job, last success/error;
- payment/mail webhook/outbox metrics без PII;
- Telegram/MAX last delivery success;
- storage/DB/WAL/free-space/backup freshness;
- Caddy/backend restart count and release id;
- alerts дедуплицируются и имеют recovery event.

GitHub CI billing blocker решается отдельно владельцем аккаунта. До этого local
CI receipt обязателен, но не выдаётся за GitHub success.

## 8. P1: БД, workers и деньги

### DB-MIG-002 — настоящая последовательность migrations

Текущее состояние: ledger v1 существует, но только фиксирует legacy baseline.

Правило для будущего:

- каждое schema изменение получает monotonic version, unique name/checksum;
- migration применима повторно или ledger делает повтор no-op;
- unknown future version fail-closed;
- heavy rebuild выполняется maintenance command, не скрыто на startup;
- до rebuild: SQLite Backup API snapshot, space check, copy audit, rollback plan;
- startup только применяет bounded additive migration либо отказывается безопасно;
- migration tests используют копию representative schema/data, не live DB.

Acceptance: первая реальная v2 migration проходит fresh, legacy-upgrade,
idempotency, interrupted/retry и unsupported-version cases.

### WORK-001 — durable leasing и watchdogs

Цель: процесс может упасть в любой точке, а обязательство не теряется и не
выполняется дважды.

Сначала без Redis:

- SQLite — source of truth;
- in-process queue только будит consumer;
- lease owner/lease expiry/attempts/next_attempt/error_class;
- atomic claim; idempotency key; terminal/dead-letter state;
- startup recovery и watchdog для generation/feed-video/mail;
- polling cursor transactionally advances after handled update;
- graceful shutdown прекращает claims и завершает/освобождает lease.

Acceptance: kill/restart tests, duplicate wake-up, expired lease, poison job,
concurrent claim 5x, backlog age metrics.

Внешняя очередь рассматривается только при нескольких worker hosts или когда
SQLite leasing latency/backlog нарушает SLO. До этого новый Redis — лишний
операционный компонент.

### BILL-001 — единая финансовая transaction boundary

- route/webhook/admin не пишут balance/ledger/invoice напрямую;
- provider event authenticity проверяется до mutation;
- provider event id + business idempotency уникальны;
- invoice transition, token grant/refund и immutable ledger — одна transaction;
- повтор/параллельный webhook даёт тот же результат;
- manual admin action проходит тот же service и audit log;
- reconciliation job сравнивает provider/invoice/ledger;
- сумма, валюта, тариф и user binding проверяются server-side.

Tests: paid/canceled/refund/out-of-order/duplicate/concurrent/manual race; focused
financial suite 5x. Реальные charges/refunds не выполняются автоматически.

### DATA-RET-001 — privacy и retention

Техническая политика до юридического текста:

- originals private by default;
- support-admin read — только trusted role + audit reason/time;
- public feed хранит отдельную deliberate derivative;
- user deletion не удаляет финансовые/audit обязательства произвольно;
- retention periods конфигурируются и применяются отдельной dry-run cleanup job;
- delete report показывает DB/media/public derivative outcomes;
- product owner утверждает сроки и privacy notice с профильным юристом РФ.

До утверждения сроков запрещена автоматическая массовая очистка originals.

## 9. P2: последовательное уменьшение `backend/main.py`

### Общая стратегия

Первый code package после governance фиксирует budget на фактическом значении и
дальше только уменьшает его. `main.py` остаётся запущенным на каждом шаге; router
или service подключается через стабильную dependency boundary. Не переносить
несколько несвязанных доменов одним commit.

Целевое состояние: `main.py` содержит app/lifespan composition, router wiring и
временно явно помеченные compatibility adapters; ориентир — не более 2,000 строк.
Это долгосрочный end state, а не условие одного release.

### ARCH-BE-A — public diagnostics и platform composition

- вынести DTO/builders и маршруты `/api/platforms`, minimal bot status;
- использовать существующий `app/services/bot_admin.py` для admin details;
- characterization tests на точный безопасный contract;
- снизить main line/symbol budget до нового факта.

### ARCH-BE-B — bot admin и polling lifecycle

- router: admin bot status/token/verify/webhook operations;
- services: Telegram/MAX polling ownership/health;
- integrations остаются transport adapters;
- lifespan registry запускает workers через единый supervisor interface;
- no behavior change, tests Telegram и MAX раздельно.

### ARCH-BE-C — mail orchestration

- mail router, application service, durable outbox, provider adapter;
- template/rendering отдельно от delivery;
- fake-provider contract tests;
- main оставляет только router include.

### ARCH-BE-D — gallery/media routes

- routers используют уже существующие `storage/*` и `services/gallery_*`;
- ownership/private/public boundaries централизованы;
- media lifecycle tests: upload -> gallery -> publish -> delete private -> public
  read -> public unpublish/delete;
- никаких массовых file moves без plan/apply/recovery journal.

### ARCH-BE-E — feed image/video publication

- publication command/query services;
- worker и recovery ownership из main;
- moderation/reactions/views routes сгруппированы, но domain state остаётся одним;
- `test_feed_v2.py` делится по contract, publication lifecycle, video,
  moderation/reactions; tests не дублируются.

### ARCH-BE-F — generation, models и integrations

- routes становятся thin adapters к существующим generation services;
- ComfyUI/OpenRouter/Ollama/Qwen clients не импортируют main globals;
- runtime config инжектируется типизированным settings object;
- model branding проверяется на всех public payloads.

### ARCH-BE-G — identity и billing последними

- выполнять только после `AUTH-LEGACY-001` и `BILL-001` characterization;
- identity routers/dependencies/session service;
- billing routers/application service/repository ports/provider adapter;
- negative/race tests 5x;
- main остаётся composition shell.

Acceptance каждой волны:

- поведение API доказано before/after contract tests;
- targeted suite + architecture maps + Quick green;
- main line/functions/classes уменьшаются;
- budget снижен в том же commit;
- новый модуль не становится новым несвязным монолитом;
- no production deploy до отдельного clean release gate.

## 10. P2: frontend и CSS

### ARCH-FE-A — `newUi.tsx`

- оставить route/shell composition;
- вынести API client/hooks, session/bootstrap state, navigation/layout и feature
  views;
- запретить cross-feature hidden globals;
- единые loading/error/empty contracts.

Target: `newUi.tsx` постепенно <= 800 строк; feature module обычно <= 500.

#### ARCH-FE-A / Wave 1

| Поле | Значение |
|---|---|
| Package | `ARCH-FE-STUDIO-001A` |
| Branch | `arch/fe-studio-001a` |
| PR | `#9` |
| Status | `IN REVIEW` |
| Result | `newUi.tsx` 4,378 -> 3,628 строк |

Scope волны:

- types;
- API;
- bounded state hooks;
- draft storage;
- image/canvas processing;
- navigation/SEO;
- shared presentation helpers.

Дальнейшее уменьшение `newUi.tsx` является следующей отдельной волной, а не
незаконченной частью PR #9. CI-статус фиксируется в review evidence после
выполнения acceptance gate и не подразумевается статусом `IN REVIEW`.

### ARCH-FE-B — `newStudioV3.css` и `newUi.css`

- tokens/base/layout отдельно;
- component/feature styles рядом с feature;
- responsive rules остаются с соответствующим компонентом;
- не переименовывать массово classes одновременно со split;
- desktop 1440px и mobile 390px visual regression на каждой волне.

### ARCH-FE-C — Video Studio

- controls, progress/pricing, input assets, result viewer и responsive layout
  делятся на components/hooks/styles;
- price до history/usage сохраняется;
- generation state не дублируется между shared preview и local component.

### ARCH-FE-D — admin/profile

- `adminModels.tsx`: query/filter/table/editor/bulk actions;
- `ProfilePage.tsx`: identity/security/subscription/activity sections;
- admin visibility проверяется trusted role, не только наличием ссылки;
- provider/secrets fields не попадают в client logs.

### ARCH-FE-E — Legacy/static shells

- `LegacyApp.tsx` freeze: bug/security fixes only;
- Legacy отключается только когда current UI имеет parity, rollback и legacy
  traffic <1% активных сессий 30 последовательных дней;
- static `/feed` и `/gallery` либо используют shared generated assets/contracts,
  либо имеют отдельные DOM/behavior tests; React build не считается их тестом.

## 11. PORT-001 — переносимость нового Windows-компьютера

Этот пакет готовит новый host, не переключая production до rehearsal:

- Git и clean clone exact SHA;
- Python 3.11.9, `.venv`, exact `requirements.txt`, `pip check`;
- Node 24.14.1, `npm ci`, production build;
- pinned NVIDIA driver evidence, ComfyUI version/workflows/custom nodes и только
  реально используемые models;
- Ollama models/version и loopback bind;
- pinned Caddy, local tunnel launcher/config separately;
- DPAPI secrets **не копируются**: keys/tokens re-enter/rotate под service account;
- backup restore rehearsal в новые DB/media paths;
- service definitions, firewall, autostart and reboot rehearsal;
- old host остаётся rollback owner до acceptance.

Cutover требует maintenance window: это и есть допустимый downtime — заранее
согласованный период, когда новые записи временно остановлены для final backup,
restore и switch. До измерения объёма final delta точная длительность не обещается.

## 12. SCALE-001 — когда действительно менять платформу

### PostgreSQL trigger

Начать проект миграции, если выполняется хотя бы одно устойчивое условие:

- нужен второй backend writer/process или несколько application hosts;
- повторяющиеся `SQLITE_BUSY` остаются после правильных short transactions/retry;
- write latency/maintenance/backup нарушает утверждённый SLO;
- billing reconciliation и concurrent workflows невозможно надёжно обслуживать
  одним SQLite writer;
- выполняется переход на production Linux server и managed DB укладывается в
  утверждённый budget.

Предпочтение тогда: managed PostgreSQL рядом с Linux application server с PITR,
а не база на tunnel VPS только потому, что VPS уже существует.

### External queue trigger

Redis/RabbitMQ/другая очередь нужна, когда:

- workers живут на нескольких hosts/process roles;
- SQL leasing создаёт измеренную contention/backlog проблему;
- нужны routing/rate/scheduling semantics, которые нельзя безопасно реализовать
  текущим durable job table.

До trigger SQLite durable leasing + in-process wake-up проще и надёжнее.

### Linux/Docker trigger

- один Windows host перестаёт удовлетворять availability/capacity;
- есть утверждённый server budget и operator plan;
- secrets, models, GPU runtime, backup/restore и observability воспроизводимы;
- current Windows service/release path уже документирован, чтобы migration не
  скрывала старые operational defects.

## 12.1. CRM-USER-001 — компактная карточка пользователя

Пакет исправляет операторскую карточку без создания второй аналитической
системы. Источником остаются существующие trusted-admin API и рабочая SQLite:

- обзор показывает полученные деньги, фактический расход OpenRouter, маржу до
  ещё не настроенной стоимости локальных вычислений и 14-дневный график входов,
  локальных изображений, API-изображений и видео;
- генерации отображаются плотными строками с превью результата, моделью,
  режимом, началом промпта, статусом, токенами и временем;
- медиатека объединяет результаты, загруженные исходники и признак публикации
  в ленте, сохраняя trusted-admin доступ к файлам;
- финансы раздельно показывают основные и дневные токены, возвраты за ошибки,
  оплаты, денежные возвраты и реальную стоимость API;
- активность различает пользовательские сессии и админскую сессию, а управление
  сгруппировано в компактные безопасные действия с обязательной причиной.

Acceptance: generated symbol map, targeted backend tests, frontend lint/build,
один clean Full receipt, desktop/mobile browser evidence на точном production
SHA и public health после переключения.

## 12.2. ADMIN-DASH-001 — единый операционный дашборд

Пакет 2026-08-21 убирает дубли верхней панели и собирает операторский обзор в
две компактные строки: реальные показатели и навигацию. Шесть разрозненных
графиков заменяются одним графиком генераций с четырьмя сериями: всего,
локальные изображения, платные API-изображения и видео. Категории вычисляются
сервером одним ограниченным чтением журнала jobs; рабочая база не изменяется.

Acceptance: семь показателей без повторной KPI-сетки, одна строка вкладок, один
график с четырьмя сериями и периодами 1 час–90 дней, отсутствие горизонтального
overflow страницы на desktop/mobile, targeted API test, lint/build, Playwright,
Quick и один clean Full receipt перед выпуском, затем browser evidence на
точном production SHA. Сетевой маршрут, FRP и AdGuard VPN вне scope.

## 12.3. OPENROUTER-ECON-002 — сверка расходов и живой каталог

Пакет 2026-08-22 закрывает сценарий, при котором OpenRouter принимал дорогую
видеозаявку, а локальный HTTP-клиент через 30 секунд отмечал её как неотправленную.
На production-данных выявлены 31 одинаковая заявка Seedance 2.0 Fast за 20 августа:
313 пользовательских токенов были полностью возвращены, но вероятный расход
провайдера составил около `$9.05`. Это оценка по фактическому коэффициенту
завершённой заявки той же модели, а не выдуманная «фактическая» сумма.

- тайм-аут отправки видео использует общую production-политику провайдера вместо
  скрытых 30 секунд;
- одинаковая активная заявка и повтор после неопределённого тайм-аута блокируются
  локальным fingerprint, не создавая второй платный запрос;
- CRM раздельно показывает записанный фактический расход и калиброванную оценку
  несверенных списаний, включая число таких заявок и потенциальную маржу;
- расчёт видео учитывает новые SKU `cents_per_second_output`, минимальную цену
  генерации и использует фактическую историю как нижнюю границу котировки;
- девять новых image-моделей из живого каталога OpenRouter получают backend-price
  и могут быть включены администратором; структурированные endpoint-цены имеют
  приоритет над статическим fallback и учитывают разрешение и входные изображения.

Acceptance: regression тайм-аута/дедупликации, сверка ledger, тесты endpoint-price
и CRM reconciliation, frontend lint/build, актуальные generated maps, Quick,
один clean Full receipt, production browser evidence каталога и карточки клиента.
Реальную платную генерацию без отдельного подтверждения оператора не запускать.
AdGuard VPN, FRP и маршрутизация вне scope.

## 12.4. PHONE-CHAT-003 — минимальный сохраняемый чат

Пакет 2026-08-24 заменяет временный чат в памяти браузера на пользовательские
диалоги в SQLite. Сервер является источником истории и сам собирает ограниченный
контекст; браузер больше не пересылает произвольные двадцать старых сообщений.

- вкладки диалогов восстанавливаются, прокручиваются горизонтально, создаются и
  удаляются с каскадным удалением сообщений;
- технический JSON и карточка web-search не выводятся в ленте, а источники
  доступны через меню ответа;
- `contextChars` по умолчанию 60 000 отделён от `localNumCtx` Ollama 16 384;
- оба лимита администрируются, а пользователь может выбрать короткую, обычную
  или большую историю конкретного диалога;
- голос в мобильном чате записывается только во время удержания микрофона.

Acceptance: migration/service ownership tests, router/tool regressions,
frontend lint/build, generated maps, Quick, один clean Full receipt и проверка
на реальном мобильном viewport после выпуска. AdGuard VPN и FRP вне scope.

## 13. Матрица обязательных проверок

| Изменение | Targeted | Повтор 5x | Quick | Full | Live/provider |
|---|---:|---:|---:|---:|---:|
| docs/agent rules | да | нет | да | нет | нет |
| pure module extraction | да | нет | да | перед release | smoke после deploy |
| auth/security | да | да | да | да | login/logout/admin negative |
| payments/ledger | да | да | да | да | sandbox/reconciliation; no real charge by default |
| worker/queue | да | да | да | да | controlled restart/recovery |
| release lock/switch | да | да | да | один раз | rollback/switch rehearsal |
| DB migration | да | да для interruption/race | да | да | backup + rehearsal on copy |
| frontend/CSS | да | нет | да | перед release | desktop/mobile/static shells |
| mail/bot provider | fake tests | retry/idempotency 5x | да | да | explicit redacted real flow |

Full receipt выполняется один раз на clean release candidate. Пять повторов
относятся к узкому race/idempotency test, а не к полной suite.

## 14. Definition of Done пакета

Пакет не завершён, пока отсутствует хотя бы один применимый пункт:

- preflight и owner зафиксированы;
- scope/acceptance определены до кода;
- characterization/negative/race tests существуют;
- code и rollback boundary реализованы;
- targeted gates зелёные;
- generated maps актуальны в том же commit;
- docs/plan обновлены по факту, а не по намерению;
- secret scan/staged diff проверены;
- commit понятен и не содержит чужой WIP;
- push подтверждён;
- если deploy входил в scope: exact SHA receipt, controlled switch, live/public
  smoke и logs подтверждены;
- статусы `CODE COMPLETE`/`DEPLOYED`/`VERIFIED`/`OPERATIONALLY VERIFIED` названы
  честно и раздельно.

## 15. Точное следующее действие

2026-07-20 (PLAN-SYNC-001): исполняемая очередь перенесена в
[optimization-and-decomposition-plan-20260720.md](optimization-and-decomposition-plan-20260720.md),
краткий фактический статус — в [current-status.md](current-status.md).
Этот документ остаётся хранилищем спецификаций пакетов и verified evidence;
его прежние «следующие шаги» больше не являются очередью.

Историческая заметка REL-LOCK-001: гонка двух publisher была воспроизведена на
работающем компьютере; теперь второй owner обязан завершиться до
tests/build/runtime mutation с ясной ошибкой `REPOSITORY_OPERATION_LOCK_BUSY`.
