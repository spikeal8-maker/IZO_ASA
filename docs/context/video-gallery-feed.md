---
status: canonical
domain: video-gallery-feed
read_when: ["video","feed","gallery"]
source_paths: ["frontend/src/VideoStudio.tsx","backend/app/services/gallery_policy.py","backend/app/services/gallery_query.py","backend/app/services/feed_policy.py","backend/app/services/feed_presentation.py","backend/app/services/video_storage.py","backend/app/services/video_submission.py","backend/static/feed/index.html","backend/static/gallery/index.html"]
test_paths: ["backend/test_feed_v2.py","backend/test_ownership_protection.py","frontend/e2e-video-studio-layout.mjs","backend/test_feed_presentation_characterization.py","backend/test_gallery_query_characterization.py","backend/test_video_generation_api.py","backend/test_video_storage_policy.py"]
related_domains: ["frontend-studio","image-generation"]
forbidden_paths: ["unknown"]
owner: video-gallery-feed
context_role: scoped-domain-map
updated: 2026-09-19
---

# Context: видео, галерея и публичная лента

Назначение: минимальный контекст для задач по Video Studio, пользовательской
галерее, media-хранилищу и публичной ленте `/feed` + публичной галерее
`/gallery`.

## Назначение подсистемы

- Генерация и хранение изображений/видео пользователя (приватная галерея).
- Публикация в публичную ленту: отдельная производная копия, независимая от
  приватного оригинала.
- Публичные статические страницы `/feed` и `/gallery` для анонимных
  посетителей и SEO.

## Канонические entrypoints

- React Video Studio: маршрут `/video` внутри группы студии →
  `frontend/src/VideoStudio.tsx` (lazy из `newUi.tsx`).
- Публичные страницы: `/feed` и `/gallery` — СТАТИЧЕСКИЕ shells
  `backend/static/feed/index.html` и `backend/static/gallery/index.html`,
  отдаются через Caddy/BFF с заголовком `X-IZO-Release`; это НЕ React-app.
- Backend API: `/api/gallery*`, `/api/feed*`, `/api/media/*`,
  `/api/generate` (video-режимы), job-статусы `/api/jobs/*`.
- Startup: `main.startup` → `start_feed_video_publication_worker` —
  ре-queue строк `feed_publications` в статусе `preparing`.

## Что читать первым

1. `docs/generated/frontend-map.md` — API/CSS/тесты группы студии.
2. `architecture/contract.json:task_registrations` — worker
   `feed-video-publication` (owner, persistence, recovery).
3. `backend/SYMBOL_MAP.md` — точные строки нужных route/функций в `main.py`.

## Основные production-файлы

- Frontend: `frontend/src/VideoStudio.tsx` (~892), `videoStudio.css`
  (~2 596; делится только в `ARCH-FE-VIDEO-001`).
- Галерея (backend services): `backend/app/services/gallery_policy.py`,
  `gallery_query.py`, `gallery_items.py`, `gallery_presentation.py`,
  `gallery_eviction.py` — политика хранения, выборки, представление,
  вытеснение.
- Лента: `backend/app/services/feed_policy.py`, `feed_sources.py`,
  `feed_presentation.py`, `feed_downloads.py`.
- Видео: `backend/app/services/video_storage.py` и
  `backend/app/services/video_submission.py` — video-specific storage/submission;
  `video_pricing.py` — цены моделей/режимов.
- Generic generation job/queue/worker/recovery принадлежит canonical domain
  `image-generation`; эта карта не владеет общим generation lifecycle.
- В `main.py`: маршруты gallery/feed/media, публикация в ленту,
  `save_gallery_original`, thumbnail-восстановление, storage-оптимизация
  (`storage_tier: original/optimizing`), удаление media-файлов.

## Основные тесты

- `backend/test_feed_v2.py` (~2 400 строк, у файла есть budget в
  contract.json) — ключевые контракты ленты, включая регрессию: удаление
  приватного оригинала НЕ удаляет опубликованную feed-копию.
- `backend/test_ownership_protection.py` — доступ к чужим media запрещён.
- `backend/test_feed_presentation_characterization.py` — presentation contract ленты.
- `backend/test_gallery_query_characterization.py` — gallery query contract.
- `backend/test_video_generation_api.py` — video-specific generation API boundary.
- `backend/test_video_storage_policy.py` — video storage policy.
- Generic generation protection относится к `image-generation`.
- Frontend: `frontend/e2e-video-studio-layout.mjs`,
  `e2e-result-layout.mjs`, `e2e-generate.mjs`, `e2e-real-generations-25.mjs`
  (реальные генерации — только по явному разрешению).

## API и persistent state

- SQLite: `jobs`, `images`, `videos`, `feed_publications` (+ `feed_reactions`,
  `feed_author_follows`, `feed_view_events`, `feed_engagement_events`,
  `feed_subscription_reads`), `token_ledger` — всё на legacy `users.id`.
- Media-файлы: `backend/media/` (приватные оригиналы `*_source*_*.webp`,
  thumbnails, feed-производные). Verify-скрипт снимает snapshot этой папки —
  тесты не должны её трогать.
- Жизненный цикл публикации: private original → публикация создаёт
  независимую публичную копию → удаление original не трогает копию;
  `preparing` строки добираются worker'ом после рестарта.
- Storage-тиры изображений: `original` ⇄ `optimizing` (фоновая
  оптимизация); прерванная оптимизация возвращается в `original`.
- Публичная лента анонимна и product-safe; приватные media — только через
  owner-checked `/api/media/*` с сессией.

## Запрещённые изменения

- Не смешивать приватные и публичные media-пути; feed-копия и публичный
  аватар — отдельные осознанные поверхности.
- Не удалять/переписывать `backend/media` и live DB в тестах — только
  temp roots (autouse fixture в `backend/conftest.py` изолирует, но
  фикстуры пакетов обязаны сами задавать temp DB).
- Не менять схему иначе как additive (см. `.claude/rules/sqlite-migrations.md`).
- Не отправлять реальный provider-трафик (ComfyUI/OpenRouter) в тестах —
  только fake adapters.
- Пользовательское имя модели — `Flux2`; технические имена файлов моделей
  не показываются пользователю.

## Какие крупные файлы НЕ читать целиком

- `backend/main.py` — только по SYMBOL_MAP (gallery/feed секции большие).
- `backend/test_feed_v2.py` — читать только тесты нужного контракта.
- `videoStudio.css`, `newStudioV3.css` — только нужные селекторы.
- `backend/static/feed/index.html` (~2 200) — только нужный блок.

## Известные риски

- Feed-video publication worker не имеет независимого watchdog:
  current architecture contract фиксирует `watchdog = missing`.
  Следующий current runtime-health owner — `STAB-RUNTIME-HEALTH-001` (#119);
  не считать watchdog реализованным до отдельного package/evidence.
- Media snapshot в verify: параллельная пользовательская генерация во время
  gate меняет hash — это предупреждение, а не падение (строгий режим только
  в maintenance window).
- Копирование live SQLite обычным file-copy запрещено — только Backup API
  (`ops/backup/*`, `backend/app/storage/backup.py`).
- Storage-оптимизация и eviction меняют файлы на диске — характеризационные
  тесты обязательны до любых правок политики.
