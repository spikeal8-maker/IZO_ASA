---
status: canonical
role: chat-agent-context
scope: /chat and shared /phone/chat core
audience: coding-agents
evidence_base_sha: 11b087d8441cb109b50b1d1e863fdcfa73201d07
status_effective_when: merged-to-main
updated: 2026-08-31
---

# Context: продуктовый чат `/chat`

Назначение: минимальный канонический контекст для задач по desktop `/chat`,
mobile `/phone/chat`, общей истории, assistant models, chat tools и chat billing.
После Task Contract подробности находятся в
[продуктовом и архитектурном контракте](../chat-system.md) и
[контракте поведения AI-помощника](../chat-assistant-contract.md).

## Граница подсистемы

- `/chat` — отдельная пользовательская страница и отдельный desktop workspace.
- `/phone/chat` — отдельная mobile поверхность того же продукта.
- Обе поверхности используют одну trusted identity, одну историю и backend
  routes `/api/phone/chat*`.
- Сейчас desktop импортирует contracts/API из phone feature; это рабочее переиспользование, но не окончательная граница владения.
- Чат является bounded feature внутри modular monolith, не микросервисом.
- Общими platform services остаются auth, token ledger, providers, jobs, media,
  transcription и telemetry.

Не называй существующий чат полностью автономной системой. Корректно:
«отдельная продуктовая поверхность с частично выделенной feature-реализацией».

## Chat-specific reference после Task Contract

Этот раздел не создаёт второй reading order. Сначала следуй
[AI_START_HERE.md](../../AI_START_HERE.md) до Task Contract текущего package.
После него используй [docs/chat-system.md](../chat-system.md), нужную route-строку
в [generated frontend map](../generated/frontend-map.md) и
`backend/SYMBOL_MAP.md`. Открывай только bounded source ranges. UI,
orchestration, history, tools, billing, auth и SEO остаются разными packages и
risk classes; проверь overlap до расширения domain.

## Frontend entrypoints

- `frontend/src/App.tsx` — route `/chat` выбирает lazy `NewStudio`; route
  `/phone/*` выбирает `PhoneApp`.
- `frontend/src/studio/studioNavigation.ts` — path → tab `chat`, canonical и
  client metadata.
- `frontend/src/newUi.tsx` — общий studio shell; импортируй только bounded
  диапазоны вокруг `DesktopChatWorkspace`, не читай файл целиком.
- `frontend/src/desktopChat/DesktopChatWorkspace.tsx` — desktop history,
  messages, composer, models, tools, voice, artifacts и responsive state.
- `frontend/src/desktopChat/desktopChat.css` — desktop/mobile chat layout.
- `frontend/src/phone/PhoneApp.tsx` — mobile platform shell.
- `frontend/src/phone/features/chat/PhoneChatWorkspace.tsx` — mobile chat UI.
- `frontend/src/phone/features/chat/api.ts` — shared-in-practice types и client
  requests для desktop/mobile.
- `frontend/src/phone/features/chat/format.ts` — public text cleanup.
- `frontend/src/phone/core/http.ts` — credentialed phone API transport.

`DesktopChatWorkspace.tsx` превышает 1 200 строк. Новое поведение не добавлять в
него без оценки extraction boundary и regression coverage.

## Backend entrypoints

- `backend/app/api/routers/phone_chat.py` — trusted routes, model routing,
  system prompt, tools, provider loop, billing settlement и persistence call.
- `backend/app/services/phone_chat_history.py` — owned threads/messages и
  bounded context.
- `backend/app/services/chat_billing.py` — config normalization, reservation,
  settlement, refund и usage report.
- `backend/app/database/migrations.py` — additive migration
  `phone_chat_history`.
- `backend/app/integrations/ollama.py` — local transport.
- `backend/app/integrations/openrouter.py` — API transport и public error policy.

Новая business logic не возвращается в `backend/main.py`. Router уже имеет
dependency seam через `PhoneChatDependencies`.

## Текущий request flow

1. Frontend отправляет последний user turn, `threadId`, public `modelId`,
   `requestId` и до четырёх images.
2. Backend разрешает trusted user и тариф; client user id не используется.
3. History service загружает bounded messages только owned thread.
4. Model resolver проверяет publication, enabled state, tariff и billing config.
5. API billing выбирает usage reservation с verified price или compatibility
   fixed charge из `apiTokenCosts` при `usageBillingEnabled=false`.
6. Semaphore ограничивает параллельные local/API chat calls.
7. Общий system prompt и tools передаются Ollama или OpenRouter.
8. Tool loop разрешает `web_search` и `generate_image`, не больше bounded rounds.
9. Только явно caught provider failure/timeout возвращает charge; success
   выполняет usage settlement, а unknown/post-provider failure может пройти без refund.
10. Frontend завершает image job и best-effort PATCH'ит итоговый tool state;
    ignored PATCH failure может оставить stored state устаревшим.

## HTTP contracts

- `GET /api/phone/chat/threads` — последние owned threads.
- `POST /api/phone/chat/threads` — новый thread.
- `PATCH /api/phone/chat/threads/{thread_id}` — title/model/context settings.
- `DELETE /api/phone/chat/threads/{thread_id}` — owned delete.
- `GET /api/phone/chat/threads/{thread_id}/messages` — thread + messages.
- `PATCH /api/phone/chat/threads/{thread_id}/messages/{message_id}/tools` —
  validated assistant tool state.
- `GET /api/phone/chat/models` — тарифный catalog и availability.
- `POST /api/phone/chat` — один ответ и billing/tool receipt.

Исторический префикс `phone` не означает, что endpoints принадлежат только
телефону. Не переименовывай paths без compatibility/migration package.

## Persistence contract

- `phone_chat_threads` хранит owner, title, chat/image/video model,
  `context_chars` и timestamps.
- `phone_chat_messages` хранит role/content/provider/public model/tools,
  charged tokens, token kind и timestamp.
- Delete thread каскадно удаляет messages.
- Каждый read/update/delete проверяет owner через trusted identity.
- Desktop и mobile показывают одну историю одного пользователя.
- Production SQLite/WAL/SHM не являются fixtures.
- Applied migration нельзя изменять; schema change создаёт новую версию.

## Помощник, модели и «боты»

- В runtime один помощник и общий prompt; он и web-search subrequest
  принудительно требуют русский ответ, multilingual behavior — GAP.
- Local/API items в picker — разные runtimes, не отдельные personas.
- Telegram/MAX bots — transport/identity domain, см. `docs/context/backend-auth-bots.md`.
- Coding-agents используют этот context, но не являются product assistants.
- Admin меняет local label/model, publication, default и tariff access; отдельные
  public descriptions/personas пока не настраиваются.

Если задача меняет system prompt, публичное описание, язык, citations, tool
policy, error behavior или assistant eval, обязательным источником становится
[assistant behavior contract](../chat-assistant-contract.md). Raw system prompt в
GitHub-документацию не копируется.

Будущая карточка помощника/модели должна иметь public name, best-for,
capabilities, limitations, speed, context, tools, price и tariff availability.
Текущий published API provider id является public `id`/`modelId`; защищёнными
admin-only остаются local runtime/workflow names. Их нельзя смешивать.

## Tool invariants

### `web_search`

- Нужен для изменяемых сведений и прямых просьб найти/проверить.
- Provider citations доходят до tools; desktop показывает links, mobile их фильтрует.
- Search failure не разрешает выдумывать актуальный ответ.

### `generate_image`

- Tool request содержит prompt и validated aspect ratio.
- Tool request не равен готовому изображению.
- Реальный результат появляется только после durable generation job.
- Result/error пишется в assistant message отдельным PATCH без provider envelope;
  failure сейчас игнорируется и может оставить stale tool state.

Forced tool должен стать structured backend contract. Текущий hidden text prefix
в desktop UI — известный defect; не закрепляй его новыми consumers.

## Billing, auth и privacy

- `local:izo-chat` бесплатен.
- При `usageBillingEnabled=true` API model требует verified catalog price/курс и
  проходит reservation/settlement. При `false` действует настроенный fixed
  `apiTokenCosts` без live-price verification и settlement в POST branch.
- Независимо от billing mode текущий `GET /api/phone/chat/models` выставляет
  `available=true` только при `price_confirmed`; UI поэтому может блокировать
  fixed-cost model при недоступном catalog. Direct fixed-cost POST при этом
  принимает published/enabled/tier-allowed model без catalog price.
- CURRENT GAP: `requestId` не привязан к user/model/operation/outcome; replay может обойти charge или refund'нуть прежний success, а provider/history/job повторяются.
- Auth — только trusted cookie session v2; не добавляй второй auth или legacy
  identity headers.
- Private history/attachments/results не становятся public автоматически.
- Provider payload, system prompt, secrets и raw errors не попадают в user
  response, public logs или screenshots. Internal redacted telemetry может
  хранить resolved technical model/provider и usage для billing/operations.
- Billing/auth/history concurrency changes — `high-assurance`, пять повторов
  focused race/idempotency test.

## Известные проблемы, не считать исправленными

- Mobile tool menu ломается на ширине 390 px из-за CSS specificity.
- Picker перегружен недоступными моделями и не объясняет best-for.
- Local answer может занимать около минуты; streaming/cancel отсутствуют.
- Desktop formatter не поддерживает полный Markdown/nested lists.
- Forced tool добавляет скрытый текст к user content; optimistic и stored text
  могут разойтись.
- Финальный image-tool PATCH не durable и при failure оставляет stale state.
- Refund не покрывает unknown provider и post-provider failure после charge.
- Нет visual-capability validation; attachment может уйти в unsupported paid model.
- Image content/magic bytes не проверяются до charge/provider.
- Surface actions различаются: desktop имеет media/preview/share, mobile — quick prompts/download/animate.
- SEO description слишком общий, исходный HTML не chat-specific, а studio effect
  может перезаписать title.
- Нет канонического eval set качества, latency и tool choice.

## Target boundary

- Нейтральный shared chat client module вместо desktop-import-from-phone.
- Тонкий desktop workspace с отдельными history/composer/model/tool/artifact
  components.
- Явные backend orchestration/history/billing/tool seams.
- Structured assistant profiles и forced tools.
- Streaming/cancel и устойчивый Markdown renderer.
- Общая history совместима с текущими desktop/mobile consumers.
- Никакого микросервиса, второй БД или второго auth.

Каждый пункт — отдельный bounded package. Не смешивай decomposition, redesign,
billing, provider rollout и SEO.

## Targeted verification

Frontend baseline:

- `frontend/e2e-desktop-chat.mjs`;
- `frontend/phoneChat.test.ts`;
- `frontend/e2e-phone-shell.mjs`.

Backend baseline:

- `backend/test_phone_chat_history.py`;
- `backend/test_phone_chat_tools.py`;
- `backend/test_phone_chat_model_catalog.py`;
- `backend/test_chat_billing.py`;
- `backend/test_assistant_runtime.py`;
- `backend/test_integrations_ollama_module.py`;
- `backend/test_integrations_openrouter_module.py`.

UI acceptance всегда включает desktop и mobile evidence. Provider tests используют
fake adapters, temporary DB/media/secrets и не отправляют реальные запросы.

## Запрещённые расширения scope

- Не менять real provider, webhook, token, payment, production DB или runtime.
- Не деплоить и не перезапускать backend из documentation/UI package.
- Не читать целиком `backend/main.py`, `frontend/src/newUi.tsx`,
  `frontend/src/LegacyApp.tsx` или `frontend/src/adminModels.tsx`.
- Не раскрывать local runtime/workflow branding пользователю. Published API
  provider ids сейчас являются public compatibility identifiers, не secrets.
- Не объявлять HTTP 200 доказательством качества, provider health или UI parity.

Если задача меняет одну из этих границ, обнови Task Contract, эту карту и
[docs/chat-system.md](../chat-system.md) в том же code-bearing commit. При
изменении externally observable поведения также обнови
[assistant contract](../chat-assistant-contract.md).
