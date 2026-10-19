---
status: canonical
domain: admin-control-center
read_when: ["admin","crm"]
source_paths: ["frontend/src/AdminApp.tsx","frontend/src/adminApi.ts","frontend/src/adminModels.tsx","frontend/src/adminCommand.ts","backend/main.py","backend/app/services/admin_commands.py","backend/app/services/admin_entitlement_commands.py"]
test_paths: ["backend/test_admin_v2.py","backend/test_admin_actions.py","backend/test_admin_bots_v2.py","backend/test_admin_command_idempotency.py","backend/test_admin_command_transactions.py","backend/test_admin_command_migration.py","frontend/adminCommand.test.ts","frontend/e2e-admin-command-retry.mjs"]
related_domains: ["admin-models","backend-auth-bots"]
forbidden_paths: ["unknown"]
owner: admin-platform
context_role: scoped-domain-map
updated: 2026-10-19
verified_source_sha: 11b087d8441cb109b50b1d1e863fdcfa73201d07
---
# Context: админка и административные изменения

Назначение: bounded-контекст для задач по `/admin`, CRM, административным каталогам моделей, тарифам, платежам, почте, ботам, уведомлениям, соцсетям и логам. Общая пользовательская картина находится в
`docs/admin-panel-guide.md`.

Проверяемая матрица ownership, API examples, side effects, risk и tests вместе с точными командами находится в `docs/admin-change-contract.md`.

Route-level evidence для bounded-набора из 19 критичных compatibility mutations identity/CRM/finance находится в `docs/admin-mutation-audit.md`. Он различает
`verified`, `partial` и `gap`; routes вне его scope нельзя считать прошедшими audit.

Карта применяется после обязательной маршрутизации из `AI_START_HERE.md`;
второго порядка чтения и активации historical backlog она не создаёт.
## Проверенные инварианты

- Главный frontend entrypoint: `frontend/src/AdminApp.tsx`.
- `/admin` и `/admin/dashboard` ведут на дашборд.
- Текущие верхние разделы: dashboard, CRM, models, notifications, social,
  tariffs, payments, mail, bots и logs.
- Доступ определяется server-side cookie session и ролью `admin`.
- `frontend/src/adminApi.ts` — общий HTTP wrapper для части админки: он
  использует `credentials: include` и один раз повторяет запрос после успешного
  refresh при `401`. Это не сквозной инвариант всей админки:
  `adminAnalytics.tsx` держит собственные `adminGet`/`adminPost` без refresh и
  автоматического network retry; `adminCommand.ts` сохраняет ручной retry только для tokens/plan commands. `adminModels.tsx`, `adminEnergy.tsx` и `adminVoice.tsx` используют
  отдельные локальные wrappers со своим retry после `401`. Изменение auth или
  session-refresh нужно проверять во всех этих владельцах, а не только в
  `adminApi.ts`.
- Backend admin route обязан применять `require_trusted_admin`; frontend-поле,
  `X-OneNode-User` и неподписанные provider payload не являются identity.
- Каждая административная мутация должна быть auditable. Для критичного действия
  нужна причина, а для финансового/provider действия — также idempotency и явная
  operator authorization.
## Frontend ownership

| Область | Основной файл | Соседние файлы |
|---|---|---|
| Shell, navigation, dashboard, tariffs, logs | `frontend/src/AdminApp.tsx` | `frontend/src/adminApi.ts`, `frontend/src/adminModelsResponsive.css` |
| CRM и user dossier | `frontend/src/adminAnalytics.tsx` | `frontend/src/adminCommand.ts`, `frontend/src/crmDossier.css`, `frontend/src/crmViewport.css` |
| Models shell и OpenRouter | `frontend/src/adminModels.tsx` | `frontend/src/adminModelsNavigation.tsx`, `frontend/src/adminModelsRoutes.ts` |
| Text catalog | `frontend/src/adminTextModelCatalog.tsx` | `frontend/src/adminTextModelCatalog.css` |
| Image/video publication | `frontend/src/adminImageModelPublication.ts` | `frontend/src/adminVideoPublication.ts` |
| Audio и 3D | `frontend/src/adminOpenRouterAuxPages.tsx` | `frontend/src/adminVoice.tsx` |
| Energy | `frontend/src/adminEnergy.tsx` | models shell |
| Notifications | `frontend/src/adminNotifications.tsx` | shared admin API |
| Social | `frontend/src/adminSocial.tsx` | shared admin API |
| Payments | `frontend/src/adminPayments.tsx` | billing backend |
| Mail | `frontend/src/adminMail.tsx` | mail backend/runtime |
| Bots | `frontend/src/adminBots.tsx` | bot admin router |

Для локальной правки `frontend/src/adminModels.tsx` сначала использовать
`frontend/src/adminModelsRoutes.ts`, ownership выше и точечный symbol/line search.
Не читать целиком этот файл или большие CSS, если достаточно целевых селекторов.
## Backend ownership

- `backend/app/api/routers/admin_operations.py` — OpenRouter status/catalog,
  notifications и social operations.
- `backend/app/api/routers/bots_admin.py` — Telegram/MAX config, token,
  verify и webhook operations.
- `backend/app/services/admin_analytics.py` — dashboard/CRM analytics.
- `backend/app/services/admin_entitlement_commands.py` — tokens/plan transaction owners; main routes только связывают trusted admin и существующие callbacks.
- `backend/app/services/admin_commands.py` — глобальная key binding, текущие permissions под write lock, durable stored response и replay.
- `backend/app/database/admin_command_schema.py` — additive command schema и её fail-closed validation; version/ledger registry остаётся в `backend/app/database/migrations.py`.
- `backend/app/services/admin_notifications.py` и
  `backend/app/services/admin_notification_delivery.py` — durable notification model и delivery.
- `backend/app/services/bot_admin.py` — bot config normalization и безопасные diagnostics.
- `backend/app/security/permissions.py` — trusted identity/permission rules.
- `backend/app/security/secret_store.py` — внешний DPAPI-backed secret boundary.
- `backend/app/billing/contracts.py` и `backend/app/billing/outbox.py` — финансовые contracts и durable obligations.
- Часть compatibility/composition routes пока остаётся в `backend/main.py`.
  Использовать `backend/SYMBOL_MAP.md` и читать только диапазон конкретного
  symbol; новая business-логика в `backend/main.py` запрещена.

`docs/generated/architecture-inventory.md` и `backend/SYMBOL_MAP.md` не доказывают безопасность.
При отметке инъецированного route как `REVIEW` проверить scoped source его dependency/helper.

## Routing внутри «Моделей»

`frontend/src/adminModelsRoutes.ts` владеет маршрутами:

- OpenRouter: text, images, video, audio, 3D, settings;
- Config UI;
- energy;
- voice input;
- prompt improvement.

3D — placeholder: рабочий provider flow требует реализации и отдельного evidence.
Image branding — `Flux2`; технические model/workflow identifiers — internal/admin-only.

Публикация модели требует согласованных UI, серверного catalog, тарифного доступа,
quote/reservation/settlement и пользовательского списка. Отсутствующая или непроверенная
цена не может молча открыть платный продукт.

## Данные и side effects

- Production SQLite/WAL/SHM, media, secrets и runtime manifests не являются fixtures.
- CRM меняет user/profile/role/plan/tokens/discount/loyalty/billing state.
- Payments и refunds меняют финансовые обязательства; повторный запрос обязан быть безопасен.
- Mail/social/bot tests могут реально отправить сообщение или изменить provider
  state; unit/integration tests используют fake adapters.
- Bot polling и webhook не могут одновременно владеть delivery. Не удалять
  webhook, не сбрасывать cursor и не ротировать token автоматически.
- In-process queue не является durable source of truth для платежей,
  публикаций, почты или уведомлений.
- Секреты не возвращаются в API и не попадают в log, screenshot, fixture или commit.

## Bounded discovery по типу задачи

### Navigation, layout или dashboard

- Найти route/section в `frontend/src/AdminApp.tsx`.
- Проверить generated ownership в `docs/generated/frontend-map.md`.
- Для CSS читать только селекторы целевого shell/component.
- Сохранить desktop/mobile contracts и доступность sidebar.

### CRM

- Начать с exports/API calls в `frontend/src/adminAnalytics.tsx`.
- Найти backend symbols через `backend/SYMBOL_MAP.md`.
- Для critical mutations открыть exact route в `docs/admin-mutation-audit.md` и перенести `gap_ids` в Task Contract.
- Для mutation проверить trusted admin, reason, audit и rollback boundary.
- Для role/tokens/billing/security применять high-assurance gate.
- Для tokens/plan читать два service owners и `adminCommand.ts`; key обязателен и связан с actor/target/operation/normalized payload. Missing key, conflict и неизвестный исход — отдельные проверяемые случаи. Receipt, effect и audit атомарны; переоткрытие dialog/reload не создаёт новую pending command.
- AM-001/002 имеют реализацию с exact-head gates; AM-006 закрывается только для двух routes. Остальные AM-003–009 требуют отдельного scope.

### Models

- Начать с `frontend/src/adminModelsRoutes.ts` и нужного leaf component.
- Не загружать весь `frontend/src/adminModels.tsx` без необходимости.
- Совместно проверить publication, tariff visibility, pricing confidence и settlement; admin checkbox не единственный источник истины.

### Bots, mail, social или providers

- Использовать соответствующий leaf component и router/service ownership выше.
- Проверить secret boundary, fake-provider tests и persistent worker ownership.
- Реальная отправка, verify, webhook или token action требуют release-ops/operator scope.

### Auth или permissions

- Дополнительно использовать `docs/context/backend-auth-bots.md`.
- Не создавать вторую auth-систему и не оживлять legacy header identity.
- Для auth, payments, concurrent storage и persistent workers повторить focused race/idempotency test пять раз.

## Targeted tests

Backend core:

- `backend/test_admin_v2.py` — trusted access и основные admin v2 contracts;
- `backend/test_admin_actions.py` — CRM mutations;
- `backend/test_admin_command_idempotency.py` — реальные HTTP handlers на temporary DB, first/replay/conflict/auth и пять повторов каждой race;
- `backend/test_admin_command_transactions.py` — concurrent SQLite connections, global key binding, debits и rollback после audit/receipt failure;
- `backend/test_admin_command_migration.py` — additive upgrade, immutable migration metadata, integrity и отдельное восстановление pre-upgrade snapshot;
- `backend/test_admin_analytics.py` — dashboard/analytics;
- `backend/test_admin_bots_v2.py` — bot config/secrets/webhook boundary;
- `backend/test_admin_mail_v2.py` — mail admin behavior;
- `backend/test_admin_notifications.py` — notifications;
- `backend/test_admin_social_router.py` — social router;
- `backend/test_admin_password_reset.py` — password reset boundary.

Frontend:

- `frontend/adminCommand.test.ts` — pending key, storage failures и late-response races;
- `frontend/e2e-admin-command-retry.mjs` — owned desktop/mobile CRM → real isolated Docker API, lost-response/reload/retry;
- `frontend/e2e-admin-dashboard-layout.mjs`;
- `frontend/e2e-admin-model-pages.mjs`;
- `frontend/e2e-admin-crm-live.mjs` — требует явные QA session token/user code;
- `frontend/e2e-security-admin.mjs`;
- `frontend/smoke-admin-analytics.mjs`;
- `frontend/visual-admin-parity.mjs`.

Route-mocked browser E2E доказывает layout/contract, но не live provider,
production data или deployment. Для UI package также нужны frontend lint/build;
для завершённого non-release package — `tools/verify.ps1` в Quick mode.

Для tokens/plan реальный proof gate — `.github/workflows/admin-command-docker.yml`, host driver `tools/docker_admin_commands.py` и runtime `tools/docker_admin_commands_runtime.py`. Только hosted Linux и explicit local socket; каждый ресурс принадлежит точному run/SHA. API работает network-none, browser bridge разрешает конечный список собственных synthetic targets. До и после recreate сохраняются redacted user state и ledger/grant/audit/command digests; cleanup никогда не затрагивает ресурс с чужими labels. Unit guard `tools/test_docker_admin_commands.py` проверяет отрицательные границы, но не заменяет запуск workflow.

## Risk routing

| Изменение | Минимальный класс |
|---|---|
| Документация без product contract | low |
| Локальный layout/read-only UI | standard |
| Role, sessions, tokens, billing, refunds, secrets, bot ownership | high-assurance |
| Deploy/restart, live provider, webhook, real mail/payment | release-ops |

Повышение риска не разрешает production action. Смена домена требует обновить Task Contract, declared files и overlap check.

## Известные границы

- Верхние dashboard KPI «Потрачено» и «Заработано» пока placeholders.
- OpenRouter 3D пока placeholder.
- `frontend/e2e-admin-crm-live.mjs` ожидает семь header KPI, а текущий shell и
  dashboard-layout contract — шесть; не заявлять этот live test зелёным до
  исправления precondition.
- Для 19 critical compatibility mutations route-level auth/reason/audit evidence
  закреплено в `docs/admin-mutation-audit.md` текущими source fingerprints и exact-head gates; исходный discovery SHA сохранён как история. Ещё 39
  admin mutations находятся вне этого bounded audit; проверять конкретный route
  и не делать blanket claim.
- Generated frontend map может пропускать admin E2E; сверять bounded listing `frontend/e2e-admin-*.mjs`.
- Provider catalog/pricing и production release меняются независимо от source; нужно разрешённое датированное evidence.
- Historical Phase 18/20 и model master plans объясняют прошлые решения, но не
  являются текущей навигацией или автоматически активным backlog.

## Запрещённые shortcuts

- Не работать напрямую в `main` и не забирать чужой WIP из sibling worktree.
- Не читать `backend/main.py` или `frontend/src/adminModels.tsx` целиком ради
  поиска одного route/component.
- Не обходить `require_trusted_admin`, reason, audit или idempotency ради UI.
- Не использовать production DB/media/secrets/providers в тестах.
- Не показывать абсолютные paths, secret presence/details или operator diagnostics в public API.
- Не считать HTTP 200, running process или configured token operational proof.
- Не deploy/restart и не выполнять live action без отдельного owner scope.

## Документационное завершение

Изменение admin navigation, ownership, permission, safety contract или test
routing обновляет в том же commit эту карту, `docs/admin-panel-guide.md` и
`docs/admin-change-contract.md`. Generated artifacts обновляются только
repository scripts. В отчёте раздельно указывать `IMPLEMENTED`, `TESTED`,
`COMMITTED`, `PUSHED/PR`, `MERGED`, `DEPLOYED` и `OPERATIONALLY VERIFIED`.

Если меняется одна из 19 audited mutations, в том же commit обновить также
`docs/admin-mutation-audit.md` и его executable contract test. Расширение audit
на route вне bounded scope является отдельным package.

После repository generators hashes audit обновляются командой `python tools/test_admin_mutation_audit.py --refresh-fingerprints`; затем обязателен audit test. Не смешивать исторический discovery SHA с текущим CI/source receipt и не объявлять scoped admin proof полной приёмкой Д3.
