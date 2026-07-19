# IZO_ASA — аудит изменений, агентов и production-контура

Дата проверки: **2026-07-19**
Проверенная ветка: **`main`**
Проверенный Git SHA: **`dbb1ca253dfea926096bc494a03449d9f9917cc6`**
Текущий исполняемый план: [engineering-optimization-master-plan-20260719.md](engineering-optimization-master-plan-20260719.md)

## 1. Итог без смягчений

Последние изменения нельзя назвать неправильными целиком. В проекте появились
реальные полезные границы: Caddy, release receipts, SQLite migration ledger,
модули database/security/storage/services, защищённое администрирование ботов,
резервное копирование, устойчивость ленты/галереи и тесты. Рабочая система не была
«разрушена рефакторингом».

Но агенты следовали правилам **не полностью**. Главная причина — не было единой
актуальной инструкции для всех инструментов. Существовал только `CLAUDE.md` из
старой identity-фазы; он одновременно:

- запрещал уже реализованные payments/feed/gallery;
- запрещал необходимую постепенную декомпозицию `backend/main.py`;
- утверждал, что migration layer отсутствует, хотя он уже создан;
- не распространялся на Codex, Copilot и Gemini.

Из-за этого фактическое качество получилось смешанным: код часто покрывался
тестами и выделялся в модули, но архитектурные лимиты повышались вслед за ростом,
карты обновлялись отдельными запоздалыми commits, а два release-процесса смогли
одновременно запустить полные тесты и публикацию.

Решение аудита:

1. ввести один корневой `AGENTS.md` и адаптеры для всех агентов;
2. считать старый master plan историческим;
3. первым кодовым пакетом реализовать single-flight lock для release/Full verify;
4. затем закрыть публичную утечку diagnostics, Telegram transport, backup route и
   только после этого продолжать крупную декомпозицию;
5. не переписывать работающий продукт, не трогать VPS/FRP и не переносить его на
   PostgreSQL/Linux без измеряемого основания.

## 2. Как проводилась проверка

Аудит был read-only относительно production data и включал:

- `main`, `origin/main`, worktree и последние commits;
- сгенерированные backend/architecture maps и их contracts;
- физические размеры и символы крупных файлов;
- маршруты, auth gates, legacy-auth consumers и worker registry;
- live listeners, release identity и локальные/public HTTP smoke;
- read-only агрегаты рабочей SQLite;
- секреты и tracked-file scan;
- UniSender, Telegram и MAX по коду, тестам и доступным runtime evidence;
- Caddy, release receipts, backup tasks и backup health;
- зависимости Python/Node и production npm audit;
- GitHub Actions state;
- repository instructions для разных агентов.

Во время аудита другой активный процесс самостоятельно запустил два почти
одновременных `start-public.bat`. Один publisher развернул текущий SHA. Этот аудит
не инициировал deploy/restart, но событие стало прямым доказательством отсутствия
release mutex.

## 3. Подтверждённый snapshot

| Область | Факт на момент аудита | Оценка |
|---|---|---|
| Git | `main == origin/main == dbb1ca253d...`; worktree до документации был clean | хорошо |
| Live release | `dbb1ca253dfe-20260719043420`, backend commit совпадает с Git | хорошо |
| Runtime | Python `3.11.9`, Node `24.14.1`; Caddy на `127.0.0.1:5173`, backend на `127.0.0.1:8000` | хорошо |
| Smoke | local/public `/`, `/feed`, `/gallery`, `/api/health`, `/api/version` возвращали HTTP 200 | хорошо, но это не UI/provider proof |
| Full receipt | `dbb1ca253dfe-20260719043420-03eada4b68fd4824853e7038587910d5.json`, 15 gates, source stable | хорошо |
| GitHub Actions | run `29668784385`, SHA `dbb1ca2`, failure до выполнения steps из-за внешнего billing/spending blocker | внешний blocker, не code failure |
| SQLite | 565,104,640 bytes + WAL 4,148,872 bytes, `user_version=1`, 57 tables | работает; повышенный operational risk |
| Пользователи | 37 | production data существует |
| Jobs | 742 completed, 47 failed | нужна наблюдаемость причин/retry |
| Images | 1,050 | backup/media lifecycle критичны |
| Feed | 75 published, 1 pending review, 1 hidden | активная product surface |
| Payments | 1 paid, 2 canceled; provider events согласованы по этим статусам | малый объём, но финансовый контур уже реальный |
| Token ledger | 1,508 rows | денежно-подобный журнал уже важен |
| Sessions | 1,388 records | legacy cleanup нужен аккуратно |
| Backup tasks | hourly local и daily cloud: last result 0 | реализовано |
| Backup health | `ATTENTION`: только `yandex_routed_through_adguard_vpn`; latest local/cloud fresh | backup есть, route policy не закрыта |

Числа — snapshot, а не постоянные характеристики. Перед каждым data/release
пакетом они снимаются заново.

## 4. Что агенты сделали правильно

### 4.1. Release и edge

- `vite preview` больше не является обычным production edge: активен Caddy.
- Frontend хранится как immutable release с manifest и связан с backend release
  identity.
- Publisher fail-closed проверяет clean source, exact SHA и receipt.
- Full verifier изолирует тестовые DB/media/secret roots от production.
- Rollback frontend уже ограничен совместимостью с backend identity.

Остаток: backend пока стартует из mutable checkout; полноценный A/B API switch,
drain и immutable backend artifact остаются `REL-002`.

### 4.2. База данных и storage

- Появились `backend/app/database/*`, schema groups, connection guard и migration
  ledger.
- Baseline migration version 1 фиксируется checksum, а неизвестная новая версия
  fail-closed.
- Private media и public feed derivatives разделены.
- Gallery cleanup и recovery получили отдельные storage/service boundaries.
- Backup открытой SQLite выполняется корректным API, а не обычным копированием.

Остаток: ledger содержит только legacy baseline v1; значительная часть bootstrap
schema всё ещё задаётся большой программной процедурой. Все будущие изменения
должны стать отдельными immutable migrations v2+.

### 4.3. Auth и bots

- V2 admin bot wrappers делегируют в provider-specific helpers с
  `require_trusted_admin` и audit logging.
- Telegram/MAX tokens не обнаружены в tracked files.
- MAX polling имеет успешные API evidence (`apiMeStatus=200`,
  `updatesStatus=200`) и cursor persistence.
- Bot-login/security helpers уже вынесены из монолита.

Остаток: пять явно зарегистрированных legacy-auth consumers ещё существуют;
Telegram transport в runtime остаётся нестабильным; публичный status endpoint
раскрывает лишнюю операционную информацию.

### 4.4. Декомпозиция

Полезные выделенные seams уже есть:

- `app/services/video_pricing.py`;
- `app/security/account_password.py`;
- `app/services/generation_*`;
- `app/services/feed_*`, `gallery_*`, `telegram_updates.py`, `max_updates.py`;
- `app/storage/*`;
- `app/integrations/unisender.py`, Telegram/MAX/OpenRouter/ComfyUI adapters;
- `app/billing/*`.

Это правильное направление: модульный монолит, а не одномоментный rewrite.

## 5. Подтверждённые нарушения и риски

### P0 — закрыть до следующего обычного production deploy

#### AUD-P0-01. Нет single-flight release/verification lock

Во время проверки два publisher-процесса с target receipts
`...043420...` и `...043511...` одновременно запустили два полных pytest-suite.
Один deploy завершился, но сам факт гонки означает, что:

- процессор нагружается дублями;
- два агента могут одновременно менять active release/runtime manifests;
- evidence одного процесса может быть ошибочно приписано другому;
- controlled restart перестаёт быть controlled.

Нужен атомарный repository operation lock с owner metadata, re-entrancy token,
stale-owner recovery и concurrency tests.

#### AUD-P0-02. Публичные diagnostics раскрывают внутренности

Unauthenticated `GET /api/platforms` возвращает абсолютный путь production DB:

`D:\Google Drive\My progact\Генератор картинок\backend\onenode.sqlite3`.

Unauthenticated `GET /api/bots/status` возвращает наличие токенов, внутренние и
public URLs, webhook paths/modes, MAX API base, TLS trust details и diagnostics.
Сами токены не выдаются, но это лишняя attack-surface информация.

Публичный endpoint должен стать минимальным capability status. Полная диагностика
остаётся только в trusted-admin API.

#### AUD-P0-03. Инструкции разных агентов отсутствовали или противоречили фактам

До аудита не существовало `AGENTS.md`, `GEMINI.md` и
`.github/copilot-instructions.md`. `CLAUDE.md` описывал старую auth-фазу. Поэтому
невозможно доказать, что все агенты работали «по одной карте».

Исправление выполнено в governance-пакете этого аудита; автоматический test теперь
проверяет наличие adapters и ключевых запретов.

### P1 — следующий operational/security слой

#### AUD-P1-01. Architecture ratchet использовался как растущий потолок

`backend/main.py` сейчас содержит **20,311 строк, 728 top-level functions,
83 classes и 223 routes**. Его лимит равен 20,314 — запас всего три строки.

История contract:

- исходный limit: 20,250;
- commit `5a0ee4a`: 20,250 -> 20,251;
- commit `5298050`: 20,251 -> 20,314.

Повышение лимита вслед за добавленным кодом не является оптимизацией. Budget
должен только замораживаться или уменьшаться после extraction. Исключение —
явно одобренный incident fix с обязательным ratchet-down package.

#### AUD-P1-02. Generated maps обновлялись отдельными commits

Несколько feature commits оставляли промежуточный `main` без актуального symbol
map/inventory, после чего появлялся отдельный `chore(...): refresh ...`:

- mail: `3e26300` -> `05b98d4`;
- feed: `fb90c0f` -> `25594b4`/`5a0ee4a`;
- gallery: `ef0f318` -> `e263a0b`;
- profile/video: `fd9d50d`/`d633cd8` -> `dbb1ca2`.

Каждый code-bearing commit должен самостоятельно проходить map/architecture
gates. Поздний refresh допустим только как исправление уже обнаруженного
нарушения, а не нормальный процесс.

#### AUD-P1-03. Telegram configured, но не operationally healthy

Есть token и polling-ready configuration, однако runtime evidence содержит
повторяющийся `TelegramTransportError`. Поэтому статус «Telegram работает» сейчас
недоказан. Нужны timestamp последнего успешного update cycle, классифицированная
transport причина, bounded retry и alert.

MAX по доступным evidence здоровее, но также должен перейти от token/config
status к last-success health.

#### AUD-P1-04. UniSender code complete не равен доставленной почте

Adapter модульный, ключ скрыт DPAPI/env и тесты не возвращают его API-клиенту.
При одной live verify попытке наблюдался HTTP 502; подтверждения реально
полученного тестового письма в audit evidence нет.

До такого подтверждения корректный статус: `DEPLOYED`, но не
`OPERATIONALLY VERIFIED`.

#### AUD-P1-05. Нет process supervisor

Startup script умеет поднять/проверить stack, но Windows service supervision,
crash restart/backoff и reboot rehearsal остаются невыполненным `OPS-001`.
Старые PowerShell launchers могут оставаться как не владеющие listener процессы.

#### AUD-P1-06. Backup health не зелёный

Local/cloud snapshots свежие, Yandex Disk доступен, но health task возвращает 2,
потому что `disk.yandex.ru` маршрутизируется через AdGuard VPN. Не нужно отключать
backup или VPN вслепую: требуется явный split-route/approved route policy и
повторная health/restore проверка.

#### AUD-P1-07. Legacy auth ещё не закрыт

Architecture contract содержит пять reviewed consumers `X-OneNode-User` /
`onenode_user`. Они задекларированы как compatibility-only, но наличие allowlist
не является доказательством невозможности legacy authorization на всех старых
routes. Нужен route-by-route negative test и поэтапное удаление.

#### AUD-P1-08. Локальные listeners и operator diagnostics

Ollama наблюдался на IPv6 wildcard `:::11434`; contract пока только предупреждает.
Если внешний firewall/profile допускает доступ, local model API может стать
доступен за пределами host. Нужны loopback enforcement или доказанный firewall
boundary.

#### AUD-P1-09. Verification receipt недостаточно подробный

Full receipt перечисляет gate names, duration и source stability, но не фиксирует
число тестов, skipped/failed summary и версии ключевых test runners. Для аудита
нельзя восстановить точный pytest объём только из receipt.

### P2 — плановая архитектурная трансформация

#### AUD-P2-01. Крупные файлы всё ещё крупные

| Файл | Строк | Решение |
|---|---:|---|
| `backend/main.py` | 20,311 | поэтапно оставить composition/compatibility shell |
| `frontend/src/newStudioV3.css` | 5,875 | feature/layout/component CSS boundaries |
| `frontend/src/newUi.tsx` | 4,378 | shell, view, state и API hooks раздельно |
| `frontend/src/LegacyApp.tsx` | 3,600 | freeze; удалять только по telemetry/parity |
| `frontend/src/newUi.css` | 3,096 | split без смены class contract |
| `frontend/src/videoStudio.css` | 2,596 | component sections + responsive contracts |
| `backend/test_feed_v2.py` | 2,346 | test modules по contract/lifecycle/moderation |
| `frontend/src/index.css` | 2,337 | global tokens/base vs feature styles |
| `backend/static/feed/index.html` | 2,124 | shell/assets/behavior раздельно и тестировать отдельно |
| `frontend/src/adminModels.tsx` | 2,016 | query/state/table/editor boundaries |
| `frontend/src/ProfilePage.tsx` | 1,023 | profile sections/hooks |

Размер сам по себе не баг. Баг — смешанная ответственность и необходимость
читать тысячи несвязанных строк ради маленькой правки.

#### AUD-P2-02. Persistent work всё ещё зависит от одного процесса

Architecture map содержит четыре workers:

- generation consumer — SQLite jobs + in-process wake-up queue;
- Telegram polling — SQLite cursor;
- MAX polling — SQLite marker;
- feed-video publication — SQLite status + in-process queue.

Generation имеет recovery module, video requeues `preparing`, но независимых
watchdogs нет. Gallery startup optimization также не имеет watchdog. Сначала
нужно укрепить SQL leasing/recovery/idempotency в одном процессе; Redis не нужен
до появления нескольких application hosts или измеренной queue contention.

#### AUD-P2-03. SQLite приближается к operational, а не немедленному size limit

565 MB и 57 tables сами по себе не требуют PostgreSQL. Текущий ограничитель —
один writer process, восстановление jobs и финансовая конкурентность. PostgreSQL
нужен при измеряемых событиях: второй backend writer, повторяющиеся `SQLITE_BUSY`
после retry, недопустимая write latency или переход на multi-host Linux.

## 6. Что меняется в правилах после аудита

Единый `AGENTS.md` теперь требует:

1. canonical preflight и проверку параллельных процессов;
2. одного release owner;
3. запрет тестам касаться production DB/media/providers;
4. запрет повышать architecture budgets для принятия роста;
5. module-first изменения и ratchet-down в том же commit;
6. maps/tests/docs в том же code-bearing commit;
7. пять повторов только focused concurrency/high-risk tests, а не пять Full suite;
8. точное разделение `CODE COMPLETE`, `DEPLOYED`, `VERIFIED` и
   `OPERATIONALLY VERIFIED`;
9. минимальные public diagnostics и trusted-admin для внутренних деталей;
10. одного polling/webhook owner для каждого бота;
11. отсутствие deploy/restart/VPS изменений без явного разрешения;
12. обязательное обновление текущего плана при найденной проблеме.

## 7. Что сейчас не нужно делать

- Не переписывать проект с нуля.
- Не переносить application stack на VPS: VPS остаётся только transport домена.
- Не вводить микросервисы/Kubernetes.
- Не переносить SQLite на PostgreSQL только из-за размера файла.
- Не устанавливать Redis «потому что очередь должна быть внешней».
- Не смешивать масштабную UI-переделку с security/release packages.
- Не отключать Legacy UI без telemetry/parity/rollback.
- Не называть настроенный provider работающим без реального redacted receipt.

## 8. Следующий обязательный шаг

Следующий кодовый пакет — **`REL-LOCK-001`**, описанный в текущем master plan.
Он не меняет пользовательские функции, БД, VPS или tunnel. Он устраняет
подтверждённую гонку между агентами до продолжения общей оптимизации.

После него порядок: `SEC-DIAG-001` -> `BOT-TG-001` -> `BACKUP-NET-001` ->
`MAIL-OPS-001` -> первый безопасный extraction wave.
