---
status: canonical
role: chat-product-architecture-spec
scope: /chat and shared /phone/chat core
audience: product owners, designers, developers, QA and coding-agents
evidence_base_sha: 11b087d8441cb109b50b1d1e863fdcfa73201d07
status_effective_when: merged-to-main
updated: 2026-08-31
---

# Чат ИЗО АСА — продуктовый и архитектурный контракт

Этот документ описывает страницу `/chat` для владельца продукта, дизайнеров и
разработчиков. Текущее состояние программы и разрешённый следующий package
всегда определяет [docs/NOW.md](NOW.md); этот файл не является backlog или
release receipt.

Связанные документы:

- [контракт поведения AI-помощника](chat-assistant-contract.md);
- [краткая context-карта для coding-агентов](context/chat.md);
- [единая маршрутизация агента](../AI_START_HERE.md).

Быстрая навигация:

- [самостоятельность и назначение](#1-короткий-ответ-о-самостоятельности);
- [пользовательский контракт](#4-пользовательский-контракт);
- [текущая архитектура](#5-текущая-архитектура);
- [помощник, tools и безопасность](#10-помощник-модели-и-документация-ботов);
- [качество, проблемы и целевая граница](#14-observability-и-slo-кандидаты);
- [изменения и проверка](#18-как-оформлять-следующие-изменения).

## 1. Короткий ответ о самостоятельности

`/chat` уже является отдельной пользовательской страницей: у неё собственный
URL, lazy-loaded workspace, стили, история, composer, каталог моделей и
изолированный frontend E2E.

Однако сейчас это **не полностью отдельная техническая система**:

- маршрут входит в общий studio shell `frontend/src/newUi.tsx`;
- desktop workspace использует contracts и API из
  `frontend/src/phone/features/chat/api.ts`;
- desktop `/chat` и mobile `/phone/chat` используют одни backend routes
  `/api/phone/chat*`, одну историю и одну модель биллинга;
- генерация изображений, распознавание голоса, auth, jobs и token ledger
  остаются общими platform services.

Корректная формулировка текущего состояния: **отдельная продуктовая поверхность
внутри modular monolith с частично выделенной feature-реализацией**.

Целевое состояние: чат должен стать самостоятельным bounded module внутри
существующего modular monolith. Это не означает новый микросервис, отдельную БД,
новую авторизацию или дублирование providers.

## 2. Назначение продукта

Чат ИЗО АСА — единая точка общения с AI-помощником, который:

- отвечает на обычные и творческие вопросы;
- использует web search для актуальных сведений;
- принимает изображения как контекст;
- может запустить создание изображения;
- передаёт работу в видео, звук и будущий 3D-раздел;
- сохраняет диалоги между desktop и mobile;
- позволяет выбрать текстовую и media-модель в пределах тарифа.

Короткое пользовательское описание:

> Чат ИЗО АСА помогает находить актуальную информацию, развивать творческие
> идеи, работать с изображениями и запускать инструменты ИЗО АСА из одного
> диалога.

Чат не должен обещать созданный файл, источник или выполненное действие, пока
соответствующий tool/job не завершён и результат не подтверждён.

## 3. Термины

- **Чат** — продуктовая поверхность `/chat` и `/phone/chat` с общей историей.
- **Помощник** — пользовательская роль ИЗО АСА и правила ответа.
- **Модель** — конкретный local или API runtime, выбранный для ответа.
- **Профиль помощника** — будущая продуктовая конфигурация имени, назначения,
  поведения и ограничений; сейчас таких отдельных профилей нет.
- **Инструмент** — структурированное действие модели: `web_search` или
  `generate_image`.
- **Bot** в Telegram/MAX — transport/identity integration и не относится к
  моделям чата. Для него действует `docs/context/backend-auth-bots.md`.
- **Coding-agent / AI-агент** — разработчик-автоматизация; его краткая карта
  находится в `docs/context/chat.md`.

## 4. Пользовательский контракт

### 4.1. Вход и пустое состояние

- Неавторизованный пользователь видит объяснение входа и не может отправлять
  сообщения или получать историю.
- После входа пользователь видит последний диалог либо пустое состояние.
- Desktop empty state предлагает вопрос, web search, изображение и переходы в
  video/audio/3D. Mobile empty state сейчас содержит только три quick prompts и
  не имеет этих media actions. Ни одна поверхность не должна выдавать
  недоступный раздел за работающий.

### 4.2. История

- Диалоги принадлежат trusted server-side user identity.
- Desktop и mobile читают одни и те же threads/messages.
- Новый thread получает временное название «Новый чат»; после первого обмена
  backend использует начало первого запроса как title.
- Удаление thread удаляет связанную историю каскадно.
- Поиск истории на desktop выполняется локально по загруженным названиям.

### 4.3. Сообщение

- Один пользовательский turn ограничен 4 000 символами.
- Разрешены до четырёх JPEG/PNG/WebP изображений.
- CURRENT GAP: выбранная model не проверяется на visual capability до charge и
  provider call; unsupported attachment может завершиться ошибкой или быть проигнорирован.
- CURRENT GAP: server проверяет только data-URL prefix и base64 alphabet, но не
  декодирует attachment и не сверяет image magic bytes до provider call.
- Enter отправляет сообщение; Shift+Enter добавляет строку.
- Pending, error и completed должны быть различимы визуально и для assistive
  technology.
- REQUIRED: отображаемый пользователю текст должен совпадать с сохранённым в
  истории. CURRENT GAP: forced-tool flow показывает optimistic `rawContent`, но
  сохраняет user `content` со скрытым instruction prefix до перехода на
  structured field.

### 4.4. Модели

- Базовый `local:izo-chat` бесплатен и не расходует дневные или основные
  product tokens.
- API-модели публикуются администратором и проверяются по тарифу. Usage-based
  режим требует verified catalog price/курс; compatibility fixed-cost режим
  использует настроенный `apiTokenCosts` в POST billing branch. Текущий
  `GET /api/phone/chat/models` при этом всё равно требует присутствия модели в
  live catalog для `available=true`, поэтому обычный UI может блокировать
  fixed-cost модель без catalog price.
- Backend всегда отклоняет unpublished, disabled и tariff-forbidden model;
  usage-based branch также отклоняет model без verified catalog price/курса.
  Fixed-cost direct POST может принять published/enabled/tier-allowed model,
  даже если catalog/UI пометили её unavailable из-за отсутствующей live price.
- Пользовательское имя и описание не должны раскрывать техническое имя local
  runtime.

### 4.5. Голос и media

- Микрофон работает как push-to-talk: запись начинается удержанием и
  завершается отпусканием; короткая или отменённая запись не отправляется.
- Голос преобразуется в текст через общий transcription endpoint.
- `generate_image` сначала возвращает намерение tool, затем frontend запускает
  общий generation job и пытается сохранить итоговый tool state отдельным
  PATCH; текущая PATCH failure может оставить stale state.
- Desktop позволяет открыть preview, скачать, поделиться и передать изображение
  в видео. Mobile показывает image inline и даёт только «Скачать» и «Оживить»;
  отдельного preview/share control сейчас нет.

## 5. Текущая архитектура

```mermaid
flowchart LR
    U[Пользователь /chat] --> A[App route]
    A --> S[NewStudio shell]
    S --> D[DesktopChatWorkspace]
    D --> C[Shared phone chat API]
    C --> R[phone_chat router]
    R --> H[phone_chat_history]
    R --> B[chat_billing]
    R --> L[Ollama local]
    R --> O[OpenRouter API/search]
    D --> G[Shared image jobs]
    D --> T[Shared transcription]
    P[/phone/chat] --> C
```

### 5.1. Что уже выделено

| Граница | Текущее состояние |
|---|---|
| URL | `/chat` распознаётся отдельно в `frontend/src/App.tsx` |
| Desktop UI | `frontend/src/desktopChat/DesktopChatWorkspace.tsx` |
| Desktop CSS | `frontend/src/desktopChat/desktopChat.css` |
| Backend router | `backend/app/api/routers/phone_chat.py` |
| История | `backend/app/services/phone_chat_history.py` |
| Chat billing | `backend/app/services/chat_billing.py` |
| Frontend regression | `frontend/e2e-desktop-chat.mjs` |
| Backend contracts | `backend/test_phone_chat_history.py`, `backend/test_phone_chat_tools.py`, `backend/test_chat_billing.py` |

### 5.2. Что остаётся общим

| Общая область | Почему она общая |
|---|---|
| Studio shell/topbar/auth modal | `/chat` рендерится внутри `frontend/src/newUi.tsx` |
| Frontend API/types | desktop импортирует phone chat contracts |
| Threads/messages | desktop и phone должны видеть одну историю |
| Trusted identity | одна cookie session v2, без второго auth |
| Text providers | общие Ollama/OpenRouter integrations |
| Image jobs | общий `/api/generate` и durable generation pipeline |
| Voice | общий `/api/tools/transcribe` |
| Billing | общий token ledger и тарифы |
| Admin catalog | общая настройка assistant models |

## 6. Frontend ownership

### 6.1. Маршрутизация и shell

- `frontend/src/App.tsx` выбирает `NewStudio` для `/chat`.
- `frontend/src/studio/studioNavigation.ts` переводит URL в tab `chat` и задаёт
  client SEO metadata.
- `frontend/src/newUi.tsx` lazy-loads workspace, передаёт auth state и переходы
  в image/video/audio/3D.

### 6.2. Desktop workspace

`frontend/src/desktopChat/DesktopChatWorkspace.tsx` сейчас владеет:

- историей и переключением thread;
- optimistic messages и composer;
- model picker;
- image attachments и clipboard paste;
- tool menu;
- voice recording;
- web sources и image artifacts;
- desktop/mobile layout state;
- light/dark chat theme.

Файл превышает 1 200 строк. Следующие feature-изменения не должны продолжать
наращивать его без отдельного decomposition contract и характеризационных
тестов.

### 6.3. Shared client contracts

`frontend/src/phone/features/chat/api.ts` определяет `PhoneChatThread`,
`PhoneChatMessage`, `PhoneChatModel`, `PhoneChatTool` и все chat requests.
`frontend/src/phone/features/chat/format.ts` скрывает технические tool envelopes.

Это рабочее переиспользование, но название `phone` ошибочно описывает фактическое
владение. Перенос в нейтральный chat module допустим только отдельным package с
паритетом desktop и mobile; API paths при таком переносе сначала сохраняются.

## 7. Backend ownership и request flow

Основной router: `backend/app/api/routers/phone_chat.py`.

Путь одного сообщения:

1. `require_trusted_user` определяет server-side identity и тариф.
2. По `threadId` загружается bounded history пользователя.
3. Выбранная public model проверяется по publication, availability и тарифу.
4. Billing config выбирает usage-based или compatibility fixed-cost branch.
5. Usage branch проверяет catalog price/курс и резервирует максимум; fixed-cost
   branch списывает настроенный `apiTokenCosts` без live-price quote.
6. Запрос проходит через concurrency semaphore в Ollama или OpenRouter.
7. Модель может вызвать `web_search` или `generate_image`.
8. Явно перехваченные `ValueError`, timeout, `httpx.HTTPError` и `RuntimeError`
   во время provider route возвращают исходное списание в обоих режимах. После
   успешного provider call settlement выполняется только для usage reservation,
   а fixed charge остаётся окончательным.
9. User/assistant exchange и начальный requested tool state сохраняются одной
   history transaction.
10. Для `generate_image` frontend позже PATCH'ит running/done/error отдельными
    best-effort writes; проигнорированная PATCH failure может оставить stored
    tool state устаревшим относительно реально завершённого job.
11. Event `phone_chat_answered` записывает redacted usage, latency и billing.

Локальный и API providers получают один текущий system prompt. Отличающихся
профилей помощников в runtime сейчас нет.

## 8. HTTP contracts

Все маршруты требуют trusted user session, несмотря на исторический префикс
`/api/phone`.

Таблица ниже — навигационный обзор, а не замена точным schemas. Перед изменением
контракта агент сверяет [backend router и модели запросов](../backend/app/api/routers/phone_chat.py),
[frontend request types](../frontend/src/phone/features/chat/api.ts) и связанные
tests. Форму ошибки, idempotency и fallback нельзя выводить только из названия
endpoint.

| Method | Path | Назначение |
|---|---|---|
| GET | `/api/phone/chat/threads` | список последних threads |
| POST | `/api/phone/chat/threads` | создать thread |
| PATCH | `/api/phone/chat/threads/{thread_id}` | title/model/context settings |
| DELETE | `/api/phone/chat/threads/{thread_id}` | удалить owned thread |
| GET | `/api/phone/chat/threads/{thread_id}/messages` | thread и messages |
| PATCH | `/api/phone/chat/threads/{thread_id}/messages/{message_id}/tools` | сохранить итог tool |
| GET | `/api/phone/chat/models` | тарифный каталог моделей |
| POST | `/api/phone/chat` | получить один ответ |

`requestId` является idempotency boundary только для charge ledger; связанные
refund/settlement дедуплицируются по повторно используемому ledger id. Повтор всё
ещё запускает provider route, добавляет history exchange и может вернуть новый
image intent/job. Нельзя заменять `requestId` клиентским user id или доверять
`X-OneNode-User`.

## 9. Persistence

Migration `phone_chat_history` в `backend/app/database/migrations.py` создаёт:

- `phone_chat_threads`: owner, title, chat/image/video model, context size,
  created/updated timestamps;
- `phone_chat_messages`: role, content, provider, public model, tool JSON,
  charged tokens, token kind и timestamp.

Owner-check выполняется в каждом history operation. Production SQLite/WAL/SHM
никогда не используются как тестовые fixtures. Любое изменение schema — новая
additive migration; существующую migration нельзя переписывать.

## 10. Помощник, модели и документация «ботов»

Externally observable поведение одного помощника задаёт
[отдельный контракт](chat-assistant-contract.md). Этот раздел описывает только
отношение помощника, runtime-моделей и будущих model/profile cards.

### 10.1. Current state

- Пользователь видит одного помощника «ИЗО Чат» и список технических моделей.
- Все модели используют единый `PHONE_CHAT_SYSTEM_PROMPT`.
- Общий prompt и отдельный web-search subrequest сейчас требуют ответ на русском
  даже для запроса пользователя на другом языке; multilingual behavior — GAP.
- Администратор может менять local label/model, publication, default и tariff
  access, но не отдельное public capability description или persona.
- API descriptions сейчас объясняют оплату/недоступность, а не лучший сценарий
  использования.
- У опубликованной API-модели provider model id сейчас одновременно является
  public `id` и возвращается как `model`/`modelId`; local runtime model name
  остаётся защищённой internal/admin-only деталью.

Поэтому текущий model picker нельзя называть каталогом разных ботов: это выбор
runtime для одной роли.

### 10.2. Обязательная карточка будущего помощника/модели

Перед продуктовой публикацией карточка должна иметь:

- стабильный public id и public name;
- одно предложение «лучше всего для»;
- 2–4 поддерживаемых сценария;
- явные ограничения и отсутствие возможностей;
- speed class и ожидаемую first-token latency;
- context limit понятным пользователю языком;
- поддержку изображений, web search и tools;
- понятный принцип цены;
- availability reason и доступные тарифы;
- internal local runtime/workflow name только в admin surface. Текущий
  опубликованный API provider model id является public compatibility surface;
  его отделение от стабильного public id требует отдельной migration.

System prompt/profile должен отдельно определять identity, язык, формат,
uncertainty, citations, tool policy, privacy и запрет ложных claims. Эти правила
не должны смешиваться с тарифами или технической маршрутизацией. Публично
проверяемая часть этих правил находится в
[assistant contract](chat-assistant-contract.md), а raw system prompt остаётся
internal.

## 11. Tool contracts

### `web_search`

- Используется для погоды, новостей, цен, расписаний, прямого «найди/проверь» и
  другой изменяемой информации.
- Ответ должен опираться на найденные источники. Desktop отображает provider
  citations отдельными ссылками; mobile `ChatTools` фильтрует `web_search` и не
  показывает structured source links — это surface parity GAP.
- Ошибка поиска не превращается в выдуманный актуальный ответ.

### `generate_image`

- Модель возвращает validated prompt и aspect ratio.
- Реальная генерация начинается отдельным job; текстовое намерение не равно
  готовому изображению.
- Frontend пытается сохранить итоговые status/result/error отдельным PATCH в
  assistant message. CURRENT GAP: PATCH failure игнорируется и может оставить
  stale requested/running state; durable finalization является target contract.

Выбор «обязательного инструмента» должен быть отдельным validated request field.
Добавление скрытой инструкции к пользовательскому тексту считается временным
дефектом, а не целевым контрактом.

## 12. Billing

- Local base assistant бесплатен.
- API text models поддерживают два текущих режима. При
  `usageBillingEnabled=true` catalog price и курс должны быть проверены, перед
  запросом резервируется рассчитанный максимум, а после provider receipt
  выполняется settlement с возвратом остатка.
- Compatibility-режим `usageBillingEnabled=false` списывает настроенный
  `apiTokenCosts` до provider call и не выполняет live-price verification или
  usage settlement. Однако текущий model-catalog route независимо от режима
  ставит `available=true` только при `price_confirmed`, поэтому обычный UI всё
  ещё зависит от live catalog. Это catalog/UI gate, а не проверка POST billing.
- Idempotent refund исходного списания сейчас вызывается только в явно
  перехваченных ветках `ValueError`, timeout, `httpx.HTTPError` и `RuntimeError`
  вокруг provider route. Неизвестное исключение provider и ошибки последующих
  settlement, telemetry или history writes эту refund-ветку не проходят.
- UI должен объяснять активный принцип цены; нельзя описывать fixed-cost charge
  как расчёт по фактическому usage.
- UI должен объяснять цену до выбора платной модели, не раскрывая внутреннюю
  provider economics.

Изменения billing требуют high-assurance package и пяти повторов focused
race/idempotency tests.

## 13. Security и privacy

- Ни один client user id не является identity.
- Thread/message/tool mutations проверяют owner через trusted session.
- История, attachments и generated private media не становятся публичными из-за
  отображения в чате.
- Provider payload, protected local runtime/workflow names, system prompt,
  absolute paths и raw errors не возвращаются пользователю. Опубликованные API
  model ids сейчас являются public identifiers и возвращаются в catalog/answer.
- Тесты используют temporary DB/media/secrets и fake providers.
- Реальная provider verification требует отдельного разрешения и redacted
  receipt.

Retention period, полный lifecycle attachments после удаления thread, экспорт
истории и provider-side retention пока не зафиксированы как завершённый
пользовательский контракт. До отдельного privacy/data-lifecycle package нельзя
обещать конкретные сроки удаления или хранения.

## 14. Observability и SLO-кандидаты

Событие `phone_chat_answered` уже содержит model/provider, input/output size,
image count, latency, provider usage, cost, settlement и tool names.

Перед объявлением качества нужны измеряемые цели:

- p50/p95 first-token latency;
- p50/p95 complete latency отдельно local/API/tool;
- success, timeout, refund и tool-error rates;
- доля корректно выбранных tools;
- доля ответов с проверяемыми citations для live-data запросов;
- instruction-following и language quality по фиксированному eval set.

Настроенный provider или HTTP 200 не доказывает качество ответа.

## 15. SEO и crawler contract

Сейчас `/chat` получает client description «Чат с инструментами ИЗО АСА»,
остаётся `index, follow`, но исходный HTML описывает главную image-студию. Также
общий effect в `frontend/src/newUi.tsx` может перезаписать chat title.

Нужно выбрать один контракт отдельным SEO package:

1. Private app: `/chat` — `noindex, nofollow`, публичное описание находится на
   отдельной landing page.
2. Acquisition page: сервер/edge отдаёт правильные title, description,
   canonical и public pre-auth content для `/chat`, а личная история остаётся
   закрытой.

До решения нельзя считать текущую страницу корректно описанной для поисковых и
social bots.

## 16. Зафиксированные review observations

| Наблюдение | Evidence boundary | Следующий обязательный шаг |
|---|---|---|
| На ширине 390 px tool menu сжимает пункты из-за CSS specificity | `frontend/src/desktopChat/desktopChat.css`, `frontend/e2e-desktop-chat.mjs` | reproduction + отдельная UI issue |
| Model picker перегружен недоступными technical models и слабыми описаниями | `DesktopChatWorkspace.tsx`, model catalog route/test | product acceptance + отдельная issue |
| Local ответ может занимать около минуты; streaming и cancel отсутствуют | router latency event и desktop request flow | измеренный baseline + streaming package |
| Formatter не поддерживает полноценный Markdown и nested lists | `frontend/src/phone/features/chat/format.ts`, `frontend/phoneChat.test.ts` | characterization + renderer issue |
| Forced tool кодируется скрытым text prefix | desktop composer и backend tool contract | regression + structured-field issue |
| Финальный image-tool state пишется отдельным best-effort PATCH | desktop image job completion и tool-state route | recovery/idempotency issue |
| Surface actions не имеют desktop/mobile parity | desktop media empty-state actions и preview/share; mobile quick prompts и download/animate | product decision + mobile parity issue |
| Refund не покрывает unknown provider exception и post-provider settlement/telemetry/history failure | `phone_chat.py` exception boundary после charge | отдельная billing recovery issue с race/idempotency tests |
| Runtime и web-search prompt принудительно русские | `PHONE_CHAT_SYSTEM_PROMPT`, `_web_search` | multilingual prompt/eval package |
| `requestId` дедуплицирует ledger, но не provider/history/image job | charge service и POST route после duplicate result | end-to-end idempotency package |
| Visual capability не описана и не проверяется до платного provider call | model catalog/resolver и attachment path | capability schema + pre-charge validation |
| Mobile не показывает structured web-search source links | desktop source renderer и mobile `ChatTools` filter | citation surface parity package |
| Image data не декодируется и не сверяется с magic bytes | `_phone_chat_image_payloads` | content validation до charge/provider |
| Chat metadata конфликтуют с общим studio effect и исходным HTML | `studioNavigation.ts`, `newUi.tsx`, source HTML | SEO decision + отдельная issue |
| Нет канонического eval набора качества ответа и tool choice | [assistant contract](chat-assistant-contract.md) | eval package и versioned fixtures |

Это evidence-backed observations для discovery, а не исполняемый backlog и не
объявленные исправления. Перед изменением кода для каждого наблюдения создаётся
отдельная GitHub issue или Task Contract с reproduction, приоритетом, acceptance
и владельцем.

## 17. Целевая граница модуля

Самостоятельность чата считается достигнутой, когда:

- `/chat` остаётся отдельным route и может развиваться без чтения всего
  `newUi.tsx`;
- desktop и mobile используют нейтральный shared chat contract, а не
  desktop-import-from-phone;
- backend chat router/orchestration/history/billing имеют явные владельцы и
  ограниченные dependencies;
- assistant profiles и tool forcing представлены структурированными данными;
- frontend поддерживает streaming/cancel и устойчивый Markdown;
- chat-specific desktop/mobile/eval/security gates перечислены в одном месте;
- общими остаются только platform services: identity, ledger, providers, jobs,
  media и telemetry;
- migration, compatibility и rollback позволяют сохранять существующую историю.

Создание отдельного сервиса, отдельной БД или второго auth не является критерием
самостоятельности и противоречит текущей архитектуре modular monolith.

## 18. Как оформлять следующие изменения

Каждый package решает одну проблему: mobile menu, structured tools, response
streaming, model descriptions, Markdown, SEO или модульное извлечение. Нельзя
объединять redesign, backend refactor, billing и provider rollout в один пакет.

Минимум для любого chat package:

- before/after пользовательский сценарий;
- declared files и проверка пересечений;
- focused frontend/backend test;
- desktop и mobile evidence для UI;
- fake provider и temporary DB;
- обновление этой спецификации и `docs/context/chat.md`, если меняется контракт;
- Quick gate для завершённого non-release package.

## 19. Verification inventory

Frontend:

- `frontend/e2e-desktop-chat.mjs` — desktop/mobile layout, history, tools,
  artifacts, models, voice и auth return;
- `frontend/phoneChat.test.ts` — public formatting и client tool requests;
- `frontend/e2e-phone-shell.mjs` — mobile platform shell.

Backend:

- `backend/test_phone_chat_history.py`;
- `backend/test_phone_chat_tools.py`;
- `backend/test_phone_chat_model_catalog.py`;
- `backend/test_chat_billing.py`;
- `backend/test_assistant_runtime.py`;
- `backend/test_integrations_ollama_module.py`;
- `backend/test_integrations_openrouter_module.py`.

Auth, billing, persistent history и concurrency changes требуют focused
race/idempotency повторов в соответствии с `AGENTS.md`.

## 20. Definition of done для документации

Документация актуальна, когда она:

- не называет частично выделенный feature полностью автономной системой;
- отличает помощника, модель, tool, Telegram/MAX bot и coding-agent;
- совпадает с route/API/schema/test evidence;
- разделяет current defects и target behavior;
- содержит рабочие относительные ссылки на связанные канонические документы;
- не содержит secrets, production paths или непроверенных provider claims;
- обновляется вместе с code-bearing package, который меняет описанный контракт.
