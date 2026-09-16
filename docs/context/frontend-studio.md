---
status: canonical
domain: frontend-studio
read_when: ["image-studio","profile","paint"]
source_paths: ["frontend/src/newUi.tsx","frontend/src/PaintWorkbench.tsx","frontend/src/ProfilePage.tsx","frontend/src/TopBarV3.tsx"]
test_paths: ["frontend/e2e-studio-resilience.mjs"]
related_domains: ["video-gallery-feed"]
forbidden_paths: ["unknown"]
owner: frontend-studio
---

# Context: frontend studio (новый UI)

Назначение: минимальный контекст для задач по студии генерации (routes `/`,
`/paint`, `/video`, `/profile`). Прочитав этот файл и
`docs/generated/frontend-map.md`, агент не должен читать `newUi.tsx` целиком.

## Назначение подсистемы

- Основной пользовательский интерфейс генерации изображений/видео: prompt,
  режимы, загрузка исходников, результаты, галерея пользователя, профиль,
  оплата тарифов.
- Работает только через trusted cookie session v2 (`credentials: include`);
  никаких legacy-заголовков или клиентских идентификаторов.

## Канонические entrypoints

- `frontend/src/main.tsx` → `frontend/src/App.tsx` — маршрутизация по
  `window.location.pathname` (без react-router; см. предикаты `is*Route`).
- Route-группа студии: `/`, `/paint`, `/video`, `/profile` →
  lazy `frontend/src/newUi.tsx` (shell всей студии).
- `/admin` → `AdminApp.tsx`; `/old|/legacy|/v1` → `LegacyApp.tsx` (frozen);
  `/feed`, `/gallery` — СТАТИЧЕСКИЕ shells backend'а, не React.

## Что читать первым

1. `docs/generated/frontend-map.md` — route → components → hooks → API →
   CSS → tests (генерируется `tools/generate_frontend_map.mjs`).
2. `frontend/src/App.tsx` (93 строки) — вся маршрутизация.
3. Головы файлов `newUi.tsx` (строки 1–100: API-хелперы `apiFetch`/`apiUrl`,
   санитизация ошибок) и нужного feature-компонента.

## Основные production-файлы

- `frontend/src/newUi.tsx` (~4 378 строк) — shell студии: state, generate
  flow, история/галерея, tariffs/checkout; цель декомпозиции
  `ARCH-FE-STUDIO-001A..D` — превратить в тонкий shell.
- `frontend/src/PaintWorkbench.tsx` — paint/inpaint/outpaint workbench.
- `frontend/src/VideoStudio.tsx` — видеостудия (см. context
  `video-gallery-feed.md`).
- `frontend/src/ProfilePage.tsx` + `profileSupport.ts` + `profileAccount.css`.
- `frontend/src/authV2.tsx` + `authV2.css` — вход (email OTP, Telegram/MAX
  deep-link, пароль), `useAuthV2` store.
- `frontend/src/TopBarV3.tsx`, `topbarUtils.ts` — верхняя панель.
- `frontend/src/stylePresets.ts`, `editPrompt.ts`, `resolutionPolicy.ts` —
  пресеты, промпт-редактирование, политика разрешений.
- `frontend/src/runtimeContracts.ts`, `runtimeTelemetry.ts`,
  `RuntimeBoundary.tsx` — контракты ответов и телеметрия ошибок.
- `frontend/src/releaseIdentity.ts` — release identity meta (не менять
  формат: проверяется publisher'ом и `check:release`).
- CSS: `newStudioV3.css` (~5 875), `newUi.css` (~3 096),
  `videoStudio.css` (~2 596), `index.css`, `paymentCheckout.css` —
  разделение только через `ARCH-FE-CSS-001`, без redesign.

## Основные тесты

- Резильентность/шелл: `frontend/e2e-studio-resilience.mjs` (входит в Full),
  `e2e-ui.mjs`, `e2e-stage1.mjs`.
- Функциональные: `e2e-critical-prompts.mjs`, `e2e-critical-tools.mjs`,
  `e2e-generate.mjs`, `e2e-paint-workbench.mjs`, `e2e-result-layout.mjs`.
- Layout/responsive: `e2e-responsive-layout.mjs`, `e2e-video-studio-layout.mjs`.
- Auth/profile: `e2e-profile-auth.mjs`, `smoke-auth-v2.mjs`.
- Изоляция origin: `tools/check_frontend_origin_isolation.mjs`
  (`npm run check:origin`).

## API и state contracts

- Все запросы: `apiFetch(path)` → `fetch('/api'+path, {credentials:'include'})`
  c авто-refresh сессии при 401 (`ensureSessionRefreshedV2`).
- Полный список endpoint'ов группы — колонка `api` в frontend-map
  (25 литералов: generate, jobs, gallery, account/tariff, billing/checkout…).
- Публичная модель для пользователя всегда называется `Flux2`; технические
  имена моделей — только admin.
- Ошибки провайдеров санитизируются (`PRIVATE_ERROR_DETAILS` в `newUi.tsx`);
  не выводить сырые detail'ы провайдеров в UI.
- Release identity: meta `izo-release` в `index.html` и `/api/version`
  должны совпадать — publisher проверяет.

## Запрещённые изменения

- Не менять `LegacyApp.tsx` (frozen compatibility; удаление — только через
  telemetry/parity/rollback gates).
- Не делать redesign одновременно с декомпозицией; CSS-класс контракты и
  desktop/mobile поведение сохраняются.
- Не добавлять legacy идентичность (заголовки/куки) в запросы.
- Не трогать `releaseIdentity.ts` формат и origin-isolation инварианты.
- UI-пакет без desktop+mobile evidence не считается verified.

## Какие крупные файлы НЕ читать целиком

- `newUi.tsx`, `LegacyApp.tsx`, `newStudioV3.css`, `newUi.css`,
  `videoStudio.css`, `index.css` — только нужные секции; навигация — через
  frontend-map и grep по классам/идентификаторам.
- `adminModels.tsx` (~2 016) — только для admin-задач.

## Известные риски

- `newUi.tsx` — самый связанный файл frontend'а; любое извлечение делать
  по одному feature с характеризационным e2e до и после.
- Дублирование: `LegacyApp.tsx` импортирует те же feature-компоненты —
  изменение общего компонента влияет на оба маршрута.
- Static `/feed`/`/gallery` shells живут в backend/static и деплоятся
  вместе с backend, а не с Vite build — проверять оба пути.
- CSS-файлы пересекаются селекторами (`newStudioV3.css` и `newUi.css`);
  до `ARCH-FE-CSS-001` не переименовывать классы.
