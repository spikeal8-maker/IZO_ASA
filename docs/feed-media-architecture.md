# Feed Media Architecture

Рабочий контракт для публичной ленты: какие изображения хранить, когда
сжимать, что писать в SQLite и какие URL должен использовать frontend.

## Product Inputs

Контракт сверяется с продуктовыми и визуальными спецификациями ленты:

- `C:/Users/spike/Downloads/Новый интерфейс/Лента/izo_feed_visual_spec.md`
- `C:/Users/spike/Downloads/Новый интерфейс/Лента/лента_izo_feed_documentation.md`
- `C:/Users/spike/Downloads/Новый интерфейс/Лента/izo_feed_aspect_ratio_origin_rules.md`
- `C:/Users/spike/Downloads/Новый интерфейс/Лента/izo_aca_gallery_ux_spec.md`
- `C:/Users/spike/Downloads/izo-aca-feed-v6-clean (1).html`

Ключевой вывод: лента — не просто публичная галерея. Главный сценарий —
`Лента -> Remix -> Генерация -> Публикация`, поэтому backend должен отдавать
не только ссылки на изображения, но и формат, происхождение, бейджи и политику
remix, чтобы frontend не угадывал эти данные.

## Зачем это нужно

Лента публичная и потенциально самая часто открываемая часть продукта. В нее не
должны попадать тяжелые оригинальные PNG/JPG из генерации. Оригинал может быть
нужен владельцу в галерее, но публичная лента должна отдавать подготовленные
версии: быстрые, ограниченные по разрешению, стабильные по формату и безопасные
для мобильных WebView.

Текущая проблема:

- `images.url` хранит оригинальный результат генерации, часто PNG/JPG 1-4 MB.
- `images.thumbnail_url` обычно хранит маленький WebP, но не всегда.
- `feed_publications` ссылается на `images`, публикация не создает отдельные
  feed-файлы.
- frontend карточек ленты сейчас использует `image_url`, то есть может грузить
  оригинал вместо thumbnail.
- в текущей live-БД уже есть поля `feed_thumb_name` / `feed_large_name`, но
  backend-код их не использует, а часть ожидаемых файлов отсутствует.

## Принцип

В базе не храним бинарники изображений. SQLite хранит только метаданные, статусы
и имена файлов. Файлы лежат в `backend/media`.

Для каждого изображения есть разные роли:

| Роль | Доступ | Назначение | Где используется |
|------|--------|------------|------------------|
| Original | приватный | мастер-файл владельца, повторное использование, скачивание | галерея, use-as |
| Gallery thumb | приватный | быстрая личная галерея | `/api/gallery` |
| Feed thumb | публичный | карточки/плитка ленты | `/api/feed`, grid |
| Feed large | публичный | detail-экран ленты | `/api/feed`, detail |

Публичная лента никогда не должна отдавать `images.url` напрямую. Она должна
отдавать только `feed_thumb` и `feed_large`.

## Demo / Seed Publications

Демо-изображения в текущей базе — это стартовое редакционное наполнение, а не
мусор. Они должны оставаться в ленте, чтобы у нового пользователя и гостя не
был пустой первый экран.

Правила:

- не удалять `seed_izo_*.png` в первых 6 заходах;
- не удалять seed/demo-строки из `feed_publications`;
- создать для seed/demo такие же `feed_thumb` и `feed_large`, как для обычных
  пользовательских публикаций;
- если `feed_thumb_name` / `feed_large_name` уже заполнены, но файлов нет,
  миграция должна создать эти файлы или обновить поля на реально созданные;
- seed/demo должны иметь `native_aspect_ratio`, `orientation`, `source_type`,
  `category` и редакционный/seed author marker;
- seed/demo не должны занимать пользовательские лимиты галереи.

Итог: стартовая лента остается наполненной, но перестает грузить тяжелые PNG.

## Aspect Ratio And Origin Contract

Формат изображения нельзя менять между карточкой и подробным просмотром.
Backend должен отдавать родной формат явно.

Минимальные поля для каждой публикации:

| Поле | Пример | Назначение |
|------|--------|------------|
| `native_aspect_ratio` | `9:16` | родной формат работы |
| `orientation` | `portrait` | `portrait` / `landscape` / `square` / `custom` |
| `source_type` | `text_to_image` | происхождение работы |
| `source_label` | `Текст -> Изо` | короткая метка для UI |
| `display_policy` | `preserve_aspect_ratio` | правило отображения |

Поддерживаемые `source_type`:

- `text_to_image`
- `image_to_image`
- `multi_reference`
- `drawing_to_image`
- `edit`
- `inpaint`
- `outpaint`
- `faceswap`
- `remix`
- `seed`

Правила:

- карточка использует `native_aspect_ratio`;
- detail использует тот же `native_aspect_ratio`;
- `feed_large` хранится без кропа, только downscale;
- `feed_thumb` сохраняет исходную композицию; CSS-preview может использовать
  cover только внутри карточки того же общего формата;
- detail использует contain-поведение, не общий 16:9 контейнер для всех работ.

## Целевые размеры

Цифры выбраны под текущий продукт: 1024-1536 px генерации, мобильные WebView,
desktop feed grid и быстрый публичный доступ.

| Версия | Максимальная сторона | Формат | Quality | Ожидаемый вес |
|--------|----------------------|--------|---------|---------------|
| Gallery thumb | 512 px | WebP | 82-88 | 20-80 KB |
| Feed thumb | 640 px | WebP | 78-84 | 25-120 KB |
| Feed large | 1536 px | WebP | 82-88 | 120-450 KB |
| Gallery original | до 2048 px | WebP | 90 | обычно до 1 MB |

Правила:

- Не апскейлить: если исходник меньше целевого лимита, сохраняем в его размере.
- Сохранять aspect ratio.
- Strip metadata/EXIF для публичных feed-файлов.
- Конвертировать публичные feed-файлы в RGB/RGBA-safe WebP.
- Если WebP-сохранение не удалось, публикация должна завершиться ошибкой, а не
  silently публиковать оригинал.
- GIF/анимация сейчас не поддерживаются как feed-output; первый кадр можно
  рассматривать только отдельной задачей.

## Когда сжимать

### После генерации

Backend уже должен создавать:

- gallery original: оптимизированный WebP (`GALLERY_IMAGE_MAX_SIDE`, по умолчанию
  2048 px; `GALLERY_IMAGE_WEBP_QUALITY`, по умолчанию 90);
- gallery thumbnail: `*_thumb.webp`.

На этом этапе не нужно сразу создавать feed-файлы для всех генераций. Большинство
работ никогда не попадет в ленту, поэтому это лишняя работа и диск.

Старые PNG/JPG originals остаются валидными и не переписываются автоматически.
Их можно мигрировать отдельным maintenance-заходом только после read-only отчета,
backup и проверки, что файл не используется как job input/source.

### При публикации в ленту

`POST /api/feed/publications` должен:

1. Проверить trusted-сессию.
2. Проверить, что `imageId` принадлежит пользователю.
3. Найти исходный файл `images.url`.
4. Создать/обновить feed-assets:
   - `feed/{publication_id}_thumb.webp`
   - `feed/{publication_id}_large.webp`
5. Записать имена файлов и metadata в `feed_publications`.
6. Вернуть публикацию, где:
   - `thumbnail_url` ведет на feed thumb;
   - `image_url` ведет на feed large.

Если публикация уже существует и пользователь меняет только title/visibility,
пережимать файлы не нужно, если исходный `image_id` тот же и файлы существуют.

### При чтении ленты

`GET /api/feed` не должен считать изображения на лету. Он только читает готовые
пути из БД и отдает публикации, которые одновременно имеют:

- `status='published'`;
- `media_ready_at IS NOT NULL`;
- `feed_thumb_name IS NOT NULL`;
- `feed_large_name IS NOT NULL`.

Если feed-файла нет, публикацию нельзя подставлять через тяжелый original.
Текущая реализация скрывает такие записи из публичной ленты до восстановления
media variants.

Если пользователь удаляет изображение из галереи или оно удаляется автоматически
из-за лимита галереи, связанная feed-публикация должна быть переведена в
`hidden`, `feed_thumb_name` / `feed_large_name` очищены, а физические
`backend/media/feed/{publication_id}_*.webp` удалены. Публичный feed не должен
продолжать отдавать работу, которую владелец уже удалил из галереи.

### Миграция старых публикаций

Отдельная maintenance-команда/скрипт должна пройти по опубликованным строкам:

1. Для каждой публикации найти `images.url`.
2. Создать отсутствующие `feed_thumb` и `feed_large`.
3. Заполнить `feed_thumb_name`, `feed_large_name`, размеры и вес.
4. Не удалять original.
5. Сформировать отчет: сколько создано, сколько пропущено, сколько битых ссылок.

До такой миграции чистить файлы нельзя.

## Предлагаемая схема БД

Текущие таблицы можно расширять additive-only, без ломки существующих данных.

`feed_publications`:

| Колонка | Тип | Назначение |
|---------|-----|------------|
| `id` | TEXT PK | id публикации |
| `image_id` | TEXT UNIQUE | ссылка на `images.id` |
| `internal_user_id` | TEXT | автор в новой identity-системе |
| `legacy_user_id` | TEXT | владелец legacy image |
| `title` | TEXT | заголовок |
| `description` | TEXT nullable | описание |
| `prompt_visibility` | TEXT | `open` / `partial` / `hidden` |
| `allow_recreate` | INTEGER | разрешить повторение |
| `status` | TEXT | `published` / `hidden` / `media_missing` |
| `feed_thumb_name` | TEXT nullable | файл для карточки |
| `feed_large_name` | TEXT nullable | файл для detail |
| `feed_thumb_width` | INTEGER nullable | фактическая ширина |
| `feed_thumb_height` | INTEGER nullable | фактическая высота |
| `feed_thumb_bytes` | INTEGER nullable | размер файла |
| `feed_large_width` | INTEGER nullable | фактическая ширина |
| `feed_large_height` | INTEGER nullable | фактическая высота |
| `feed_large_bytes` | INTEGER nullable | размер файла |
| `media_ready_at` | TEXT nullable | когда assets подготовлены |
| `media_error` | TEXT nullable | краткая ошибка подготовки |
| `native_aspect_ratio` | TEXT nullable | родной формат: `1:1`, `4:5`, `9:16`, `16:9`, ... |
| `orientation` | TEXT nullable | `square`, `portrait`, `landscape`, `custom` |
| `source_type` | TEXT nullable | `text_to_image`, `image_to_image`, `edit`, `seed`, ... |
| `source_label` | TEXT nullable | человекочитаемая метка для UI |
| `display_policy` | TEXT nullable | обычно `preserve_aspect_ratio` |
| `category` | TEXT nullable | базовая категория для будущих фильтров |
| `remix_policy` | TEXT nullable | `allowed`, `prompt_locked`, `disabled` |
| `tags_json` | TEXT nullable | JSON-массив тегов/бейджей |
| `created_at` | TEXT | дата публикации |
| `updated_at` | TEXT nullable | последнее обновление |

Индексы:

- `idx_feed_publications_status_created(status, created_at)`
- `idx_feed_publications_user(internal_user_id)`
- `idx_feed_publications_media_ready(status, media_ready_at)`

`images` оставляем как master/gallery таблицу. Не надо превращать ее в публичный
feed-storage. Это снижает риск случайно открыть приватный original.

## API-контракт

`GET /api/feed` должен возвращать:

```json
{
  "id": "pub_id",
  "image_url": "/api/feed/media/pub_id?variant=large",
  "thumbnail_url": "/api/feed/media/pub_id?variant=thumb",
  "media_status": "ready",
  "aspect_ratio": "16:9",
  "native_aspect_ratio": "16:9",
  "orientation": "landscape",
  "source_type": "text_to_image",
  "source_label": "Текст -> Изо",
  "display_policy": "preserve_aspect_ratio",
  "remix_policy": "allowed",
  "resolution": "1536x864"
}
```

`/api/feed/media/{publication_id}`:

- `variant=thumb` отдает только `feed_thumb_name`;
- `variant=large` отдает только `feed_large_name`;
- старый `thumb=1` можно временно поддержать как alias для совместимости;
- если variant отсутствует, по умолчанию отдавать `large`, но не original;
- endpoint доступен только для `published` публикаций с `media_ready_at` и обоими
  именами feed variants;
- `Content-Type`: `image/webp`;
- `Cache-Control` для ready feed-файлов: public, max-age=31536000, immutable;
- `ETag` или Last-Modified желательно добавить отдельной задачей.

Запрещенный fallback: если feed-файл отсутствует, нельзя отдавать `images.url`.
Это снова создаст тяжелую публичную ленту.

## Frontend-контракт

Карточки ленты:

- всегда использовать `thumbnail_url`;
- `loading="lazy"`;
- `decoding="async"`;
- размеры контейнера задаются CSS через aspect-ratio, чтобы layout не прыгал.

Detail-панель:

- использовать `image_url`, который уже является `feed_large`, а не original;
- не грузить detail-картинку до выбора публикации, если возможно;
- для мобильного overlay достаточно large 1536 px max-side.

Публикация из галереи:

- preview в модалке публикации использует gallery thumbnail;
- после успешного publish reload ленты получает уже feed thumb/large.

## Ошибки и устойчивость

Публикация не должна становиться `published`, если публичные файлы не готовы.
Допустимые варианты:

1. Синхронная подготовка: publish отвечает после создания feed-assets.
2. Асинхронная подготовка: publish создает `status='processing_media'`, worker
   готовит файлы, потом переводит в `published`.

Для текущего проекта проще и надежнее начать с синхронной подготовки: файлы
маленькие, публикация происходит редко, код проще тестировать.

Если исходный original отсутствует:

- новая публикация: `404 Image file not found`;
- существующая публикация при миграции: `status='media_missing'`, не показывать в
  публичной ленте до восстановления файла.

## Что не чистить пока

До внедрения этого контракта и миграции нельзя удалять:

- `images.url` original-файлы;
- существующие `_thumb.webp`;
- seed-файлы `seed_izo_*.png`;
- публикации с заполненными `feed_thumb_name` / `feed_large_name`, даже если
  файлов пока нет.

Сначала нужно создать недостающие feed-assets и убедиться, что `/api/feed` больше
не зависит от original.

## Acceptance Checklist

Backend:

- `POST /api/feed/publications` создает `feed_thumb` и `feed_large`.
- `GET /api/feed` возвращает URL только на feed variants.
- `GET /api/feed` фильтрует только `published` rows с `media_ready_at` и обоими
  feed filenames.
- `/api/feed/media` не отдает `images.url` даже как fallback.
- Битый source-файл не публикуется как original.
- Тесты покрывают: publish создает WebP variants, карточный URL меньше original,
  seed/old migration, отсутствие fallback на original.

Frontend:

- feed grid использует `thumbnail_url`.
- detail использует `image_url`/large.
- mobile/desktop layout не скачивает original в Network для ленты.
- карточка и detail используют один и тот же `native_aspect_ratio`.
- seed/demo публикации видны в ленте после миграции и не грузят original.

Data:

- migration-report сохранен в docs или logs.
- все `published` feed rows имеют существующие `feed_thumb_name` и
  `feed_large_name`.
- все seed/demo rows имеют существующие optimized feed variants.
- средний `feed_thumb` ориентировочно до 120 KB.
- средний `feed_large` ориентировочно до 450 KB.

## Порядок внедрения

1. Добавить helper генерации feed-assets в backend.
2. Расширить `init_db` additive-колонками, учитывая уже существующие live-поля.
3. Изменить publish endpoint: готовить assets до `published`.
4. Изменить `_feed_item_payload` и `feed_media`: отдавать feed variants.
5. Изменить frontend grid на `thumbnail_url`.
6. Добавить тесты feed-media.
7. Написать миграционный скрипт/команду для существующих публикаций.
8. Прогнать миграцию на копии БД, проверить отчет.
9. Только после этого решать, какие старые/лишние файлы можно чистить.

## Maintenance Commands

Общая проверка здоровья ленты, пользователей и media-storage:

```bash
python backend/media_health_check.py --report logs/media-health-check-latest.json --fail-on-issues
```

Она агрегирует schema-audit, feed-audit, storage-audit, user/gallery-audit и cleanup-plan.
`--fail-on-issues` падает только на hard-проблемах связей и файлов: битые
активные ссылки, опубликованные публикации без source, опубликованные публикации
на удаленных images, missing feed variants и т.п. Размерные warning остаются в
детальном nested report и не считаются блокирующей ошибкой health-check.

Read-only аудит готовности SQLite-схемы:

```bash
python backend/db_schema_audit.py --fail-on-issues
```

Он проверяет, что в live DB есть feed-media contract columns и индексы под
частые запросы галереи, jobs и ленты. Это быстрый guard после откатов,
переносов базы и ручных восстановлений из backup.

Read-only аудит текущего состояния feed media:

```bash
python backend/feed_media_audit.py --report logs/feed-media-audit-latest.json --fail-on-issues
```

Он не меняет БД и файлы. Проверяет:

- статусы публикаций;
- `published` rows без `media_ready_at`;
- `published` rows, у которых отсутствует исходная `images` строка;
- `published` rows, у которых исходная `images` строка уже `deleted_at`;
- отсутствие физических `feed/*.webp`;
- средний/максимальный вес `thumb` и `large`;
- orphan-файлы в `backend/media/feed`.

Read-only аудит всего `backend/media` перед будущей чисткой:

```bash
python backend/media_storage_audit.py --report logs/media-storage-audit-latest.json --fail-on-issues
```

Он не удаляет файлы. Проверяет:

- общий размер `backend/media`;
- размер файлов, на которые есть активные ссылки из `images`, feed или
  `settings_json`;
- файлы, которые остались от deleted image rows;
- unreferenced файлы без активной ссылки из БД;
- отсутствующие активные ссылки (`missing_active_refs`).

Аудит специально читает `images.settings_json` и `jobs.settings_json`: входные,
reference и remix-файлы могут быть нужны для истории генераций или повторного
использования, даже если они не являются `images.url`. Такие файлы нельзя
автоматически считать мусором.

`/api/generate` обязан валидировать входные `/api/media/...` до создания job,
очереди и списания токенов. Разрешены только существующие файлы активной галереи
текущего пользователя или файлы, уже связанные с `jobs.settings_json` этого же
пользователя. Отсутствующие файлы возвращают `input_media_missing`, чужие или
непривязанные — `input_media_unavailable`.

Если старые `jobs.settings_json` уже содержат ссылки на отсутствующие файлы,
их надо чинить repair-командой. Она переносит битые input-ссылки в
`_media_ref_status.missing`, а рабочие поля `inputImage1`, `inputImages[].image`
и аналогичные очищает:

```bash
python backend/job_media_ref_repair.py --report logs/job-media-ref-repair-dryrun-latest.json
python backend/job_media_ref_repair.py --apply --report logs/job-media-ref-repair-latest.json
```

Read-only аудит связки пользователей, галереи и физических файлов:

```bash
python backend/user_gallery_link_audit.py --report logs/user-gallery-link-audit-latest.json
```

Он проверяет:

- `images.user_id` существует в `users.id`;
- у пользователей есть `internal_user_id`;
- нет дублей `internal_user_id`;
- `jobs.user_id` совпадает с `images.user_id`;
- active images имеют физические original/thumbnail-файлы;
- deleted images отделяются от active missing и не считаются поломкой галереи.

Seed/demo изображения принадлежат системному владельцу `seed_editorial`.
`init_db` создает эту строку в `users` idempotent-миграцией без auth identity:
это нужно только для целостной связки `images.user_id -> users.id`.

Любое удаление должно делаться отдельной задачей после просмотра этого отчета и
после бэкапа. Нельзя удалять `seed_izo_*.png`, пока не принято отдельное решение
по хранению seed originals.

Read-only manifest кандидатов на будущую чистку:

```bash
python backend/media_cleanup_plan.py --report logs/media-cleanup-plan-latest.json
```

По умолчанию manifest включает только unreferenced / deleted-residue файлы типов:

- `original_or_input`;
- `gallery_thumb`.

Он намеренно защищает и не включает:

- `seed_original`;
- `feed_variant`.

Даже если передать защищенный тип через `--kind`, он попадет в
`ignored_requested_protected_kinds`, а не в `candidates`. Этот скрипт тоже ничего
не удаляет: в отчете должно быть `deletes_files: false`.

Фактическое удаление выполняется отдельным apply-скриптом после dry-run и
бэкапа:

```bash
python backend/media_cleanup_apply.py --report logs/media-cleanup-apply-dryrun-latest.json --limit 5000
python backend/media_cleanup_apply.py --apply --report logs/media-cleanup-apply-latest.json --limit 5000
```

Apply-скрипт удаляет только кандидатов из плана, повторно проверяет, что путь
строго внутри `backend/media`, и не удаляет защищенные типы `seed_original` и
`feed_variant`.

Read-only проверка миграции без создания файлов:

```bash
python backend/feed_media_migrate.py --report logs/feed-media-migrate-dryrun-latest.json
```

Применение миграции или пересоздание feed variants после восстановления source:

```bash
python backend/feed_media_migrate.py --apply --report logs/feed-media-migration-latest.json
```

Точечная проверка/пересоздание одной публикации:

```bash
python backend/feed_media_migrate.py --publication-id <publication_id> --report logs/feed-media-one-dryrun.json
python backend/feed_media_migrate.py --apply --publication-id <publication_id> --report logs/feed-media-one-apply.json
```

Проверка/пересоздание только тех публикаций, которые сейчас находятся в
`media_missing`:

```bash
python backend/feed_media_migrate.py --only-missing --report logs/feed-media-missing-dryrun.json
python backend/feed_media_migrate.py --apply --only-missing --report logs/feed-media-missing-apply.json
```

Если восстановили один или несколько пропавших original-файлов из списка
`media_missing`, запуск `--apply` пересоздаст для них `thumb/large` и вернет такие
публикации в `published`.

## Implementation Plan

Эта работа выполняется отдельным backend/data заходом. Визуальные изменения ленты,
редактор, генератор и общий UI могут идти параллельно в другой ветке/другим агентом,
но не должны менять контракт БД и feed-media без согласования.

### Заход 1 — аудит и бэкап

Цель: получить точную карту текущей БД и файлов перед любыми изменениями.

Действия:

1. Сделать бэкап `backend/onenode.sqlite3`.
2. Посчитать строки `images`, `feed_publications`, `feed_reactions`, `jobs`.
3. Собрать отчет по `backend/media`: originals, `_thumb.webp`, seed-файлы, битые
   ссылки, общий вес и средний вес.
4. Отдельно проверить публикации ленты:
   - есть ли source original;
   - есть ли gallery thumbnail;
   - заполнены ли `feed_thumb_name` / `feed_large_name`;
   - существуют ли эти файлы физически.
5. Ничего не удалять.

Результат: отчет по текущему состоянию и список рисков.

### Заход 2 — миграция схемы БД

Цель: подготовить `feed_publications` к хранению публичных optimized variants.

Добавляем additive-only колонки, проверяя наличие каждой колонки перед `ALTER`:

- `feed_thumb_name`
- `feed_large_name`
- `feed_thumb_width`
- `feed_thumb_height`
- `feed_thumb_bytes`
- `feed_large_width`
- `feed_large_height`
- `feed_large_bytes`
- `media_ready_at`
- `media_error`
- `updated_at`
- `native_aspect_ratio`
- `orientation`
- `source_type`
- `source_label`
- `display_policy`
- `category`
- `remix_policy`
- `tags_json`

Результат: live-БД и temp-БД тестов готовы хранить feed media metadata без
поломки существующих строк.

### Заход 3 — backend helper для feed-assets

Цель: единый способ делать публичные файлы ленты из original.

Нужные variants:

- `feed/{publication_id}_thumb.webp`: max side 640 px;
- `feed/{publication_id}_large.webp`: max side 1536 px.

Правила:

- WebP;
- без апскейла;
- сохранять aspect ratio;
- strip EXIF/metadata;
- сохранять width/height/bytes;
- при ошибке не подставлять original.

Результат: backend умеет качественно и предсказуемо готовить изображения для
публичной ленты.

### Заход 4 — backend-контракт публикации и отдачи

Цель: новые публикации сразу должны быть быстрыми и не зависеть от original.

Изменения:

1. `POST /api/feed/publications` проверяет владельца, создает feed-assets,
   записывает metadata и только потом делает публикацию `published`.
2. `GET /api/feed` возвращает:
   - `thumbnail_url` на feed thumb;
   - `image_url` на feed large;
   - `media_status`.
3. `/api/feed/media/{publication_id}` отдает только feed variants:
   - `variant=thumb`;
   - `variant=large`;
   - `thumb=1` временно остается alias.
4. Fallback на `images.url` запрещен.

Результат: новые публикации не грузят тяжелые PNG/JPG в публичную ленту.

### Заход 5 — миграция существующих публикаций

Цель: привести старую ленту и seed-публикации к новому контракту.

Действия:

1. Написать maintenance-скрипт/команду.
2. Для каждой опубликованной строки найти source через `images.url`.
3. Создать недостающие `feed_thumb` и `feed_large`.
4. Заполнить media metadata и поля `native_aspect_ratio` / `orientation`.
5. Для seed/demo сохранить публикации и привести их к тем же optimized variants.
6. Если source отсутствует, записать `media_error` или перевести строку в
   `media_missing`.
7. Сохранить отчет: создано, пропущено, отсутствует source, ошибки.

Результат: существующая лента перестает ссылаться на тяжелые originals.

### Заход 6 — frontend, тесты и трафик

Цель: frontend использует правильные URL, а тесты защищают контракт.

Frontend:

- feed grid использует `thumbnail_url`;
- detail использует `image_url`, который уже является feed large;
- добавить `decoding="async"` для изображений ленты;
- проверить, что карточки не скачивают original.

Проверки:

- `python -m pytest backend/test_feed_v2.py -q`;
- новые тесты на feed-assets;
- ручная проверка `/feed`;
- проверка Network: grid качает thumbs, detail качает large;
- сравнение средних размеров до/после.

Результат: лента работает быстро и стабильно, а регрессии ловятся тестами.

### Отдельный будущий заход — чистка

Чистка файлов не входит в первые 6 заходов. Удалять что-либо можно только после:

- успешной миграции;
- сохраненного отчета;
- подтверждения, что `/api/feed` не зависит от original;
- понимания, какие originals нужны галерее, истории генераций и `use-as`.

## Coordination Boundaries

Параллельно может работать второй агент над визуалом, редактором и функционалом
генерации. Чтобы не пересекаться:

Моя зона:

- `backend/main.py` в части feed/media/SQLite;
- `backend/test_feed_v2.py` и новые backend-тесты feed-media;
- maintenance-скрипты/отчеты миграции;
- документация `docs/feed-media-architecture.md`;
- минимальная frontend-правка только для URL изображений ленты, если она нужна
  для завершения backend-контракта.

Зона второго агента:

- визуал редактора;
- визуал и UX генерации;
- frontend-логика генератора;
- layout/стили, не меняющие backend feed-media contract.

Нельзя без согласования:

- менять схему `feed_publications`;
- менять `/api/feed`, `/api/feed/media`, `/api/feed/publications`;
- чистить `backend/media`;
- менять смысл `images.url` / `images.thumbnail_url`;
- переводить ленту обратно на original-файлы.
