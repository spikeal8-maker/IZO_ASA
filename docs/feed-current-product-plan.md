# Публичная лента IZO_ASA — границы текущего продукта

**Актуализация по исходникам:** 17 октября 2026, `main` `fd53f17fe167e70ca7a66323c81447536889952a`. Этот текст заменяет накопленный июльский план и не устанавливает очередь задач. Состояние production требует отдельного installed/runtime evidence.

## Видимый интерфейс

Публичная страница `/feed` имеет отдельную статическую оболочку `backend/static/feed/index.html`. В React SPA нет основания добавлять вторую независимую версию ленты. Точную маршрутизацию подтверждают `frontend/src/App.tsx`, [generated/frontend-map.md](generated/frontend-map.md) и [контекст видео/ленты/галереи](context/video-gallery-feed.md).

Дизайн мобильного и десктопного экрана сверяется с текущей собранной оболочкой, тестами и принятой [дизайн-системой](izo-asa-design-system-20260716.md), а не с архивными макетами июля.

## Продуктовые границы

- Приватный оригинал в пользовательской галерее и разрешённая публичная производная — разные объекты и разные уровни доступа.
- Создание/модерация/публикация проходят backend-права владельца и устойчивое состояние SQLite. Запрещено открывать оригинал другого пользователя из публикации.
- Media-URL, thumbnails, авторство и реакции проверяются на стороне API и тестами. Не использовать fixture/demo для рабочей миграции.
- При сбоях очереди публикации требуется наблюдаемое и повторяемое восстановление без повторной выдачи прав.
- Нет разрешения самостоятельно чистить реальные медиа, отключать модерацию или создавать дублирующий frontend.

## Ориентиры для разработки

Код: `backend/app/services/feed_policy.py`, `feed_presentation.py`, `backend/static/feed/`, `backend/app/services/gallery_policy.py` и нужные маршруты API. Проверки: `backend/test_feed_v2.py`, `backend/test_feed_presentation_characterization.py`, `backend/test_feed_media_continuity.py`, `backend/test_ownership_protection.py`.

Для схемы данных, публикаций и файлов смотрите [feed-media-architecture.md](feed-media-architecture.md); для реальных связей используйте [архитектурный инвентарь](generated/architecture-inventory.md). Конкретная задача определяется только [docs/NOW.md](NOW.md)/Task Contract.

Предыдущие планы `feed-layout-redesign-20260716.md`, `feed-v3-implementation-20260717.md` и UX-аудиты перенесены в [исторический архив](../archive/docs/2026-10-17/README.md); они не являются действующим описанием.
