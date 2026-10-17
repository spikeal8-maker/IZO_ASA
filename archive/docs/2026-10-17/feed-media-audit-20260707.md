# Feed Media Audit — 2026-07-07

Заход 1: защитный аудит перед изменениями БД и файлов ленты.

## Backup

Создан бэкап live SQLite:

`backend/backups/onenode-before-feed-media-20260707-005942.sqlite3`

Исходная база:

`backend/onenode.sqlite3`

Размер исходной БД на момент аудита: `538.93 MB`.

## Table Counts

| Таблица | Строк |
|---------|------:|
| `users` | 20 |
| `jobs` | 210 |
| `images` | 531 |
| `feed_publications` | 53 |
| `feed_reactions` | 3 |

## Media Directory

`backend/media`:

| Группа | Файлов | Всего | Средний размер | Максимум |
|--------|------:|------:|---------------:|---------:|
| Gallery thumbs (`*_thumb.webp`) | 467 | 16.26 MB | 35.7 KB | 114.1 KB |
| Originals / inputs | 1081 | 790.88 MB | 749.2 KB | 3873.7 KB |
| Seed originals (`seed_izo_*.png`) | 43 | 107.00 MB | 2548.0 KB | 3014.0 KB |

Вывод: существующие gallery thumbnails легкие и нормальные. Главная нагрузка —
originals/inputs и особенно seed originals, которые сейчас используются как
публичные thumbnails в ленте.

## Feed Schema State

В `feed_publications` уже есть:

- `feed_thumb_name`
- `feed_large_name`
- `category`
- `is_seed`
- `author_type`
- `author_display`
- `base_like_count`
- `base_save_count`
- `base_recreate_count`
- `view_count`

Пока отсутствуют и должны быть добавлены additive migration:

- `feed_thumb_width`
- `feed_thumb_height`
- `feed_thumb_bytes`
- `feed_large_width`
- `feed_large_height`
- `feed_large_bytes`
- `media_ready_at`
- `media_error`
- `native_aspect_ratio`
- `orientation`
- `source_type`
- `source_label`
- `display_policy`
- `remix_policy`
- `tags_json`
- `updated_at`

## Feed Publications State

| Метрика | Значение |
|---------|---------:|
| Всего публикаций | 53 |
| `published` | 53 |
| Seed/demo detected | 43 |
| `feed_thumb_name/feed_large_name` заполнены | 43 |
| Публикаций с отсутствующим source/thumb | 5 |

По существующим файлам опубликованных работ:

- `image.url` average: `2428.0 KB`, median: `2516.6 KB`, max: `3014.0 KB`.
- `image.thumbnail_url` average: `2286.7 KB`, median: `2516.6 KB`, max: `3014.0 KB`.

Это подтверждает проблему: для seed/demo `thumbnail_url` фактически указывает на
тот же большой PNG, а не на легкий WebP.

## Seed / Demo Findings

Seed/demo публикации должны остаться. Они нужны как стартовое наполнение ленты.

Текущее состояние:

- 43 seed/demo публикации опубликованы.
- 43 seed originals физически существуют как `seed_izo_*.png`.
- Общий вес seed originals: `107.00 MB`.
- Средний seed original: `2548.0 KB`.
- У seed/demo публикаций в БД прописаны `seed-pub-XX_thumb.webp` и
  `seed-pub-XX_large.webp`.
- Эти WebP-файлы физически отсутствуют.
- `thumbnail_url` у seed/demo сейчас указывает на `seed_izo_XX.png`.

Пример:

```json
{
  "pub": "seed-pub-01",
  "title": "Ночной город будущего",
  "url": "seed_izo_01.png",
  "thumb_url": "seed_izo_01.png",
  "feed_thumb": "seed-pub-01_thumb.webp",
  "feed_large": "seed-pub-01_large.webp",
  "w": 1672,
  "h": 941
}
```

Решение: миграция должна создать отсутствующие `seed-pub-*_thumb.webp` и
`seed-pub-*_large.webp`, заполнить metadata и оставить seed/demo в ленте.

## Missing User Publication Files

Есть 5 обычных публикаций, у которых отсутствуют и original, и thumbnail:

- `a2b3298c1e684dbfab41e14ae3602441`
- `a18e89f1ee8d4266aa7fecb43e31a140`
- `62b6f58ff0b24b47b73d0f4f1f1bb283`
- `c0cfd88d71764be1a6ee5f727e25fbf3`
- `c2808f248db2401eb1fd67a7453201d1`

Текущие отсутствующие ссылки:

- `job_20260703_000131_31caef_comfyui.png`
- `job_20260703_035443_4acd74_comfyui.png`
- `job_20260702_031416_a0bd98_comfyui.png`
- `job_20260703_000656_eef0f9_comfyui.png`
- `job_20260702_222509_979ba3_comfyui.png`

Решение: при миграции эти публикации нельзя подменять original fallback. Их нужно
перевести в `media_missing` или заполнить `media_error`, пока source не восстановлен.

## Immediate Conclusions

1. Чистку делать рано.
2. Seed/demo надо сохранить и оптимизировать.
3. Новые feed media columns нужны.
4. Миграция должна быть осторожной: существующие `feed_thumb_name` /
   `feed_large_name` уже есть, но файлов нет.
5. `/api/feed` после внедрения не должен отдавать публикации без готовых feed
   variants как тяжелые originals.

## Follow-Up Applied

После аудита применена additive-only миграция схемы через `init_db`.

Теперь в live `feed_publications` присутствуют все поля feed-media контракта:

- `feed_thumb_width`
- `feed_thumb_height`
- `feed_thumb_bytes`
- `feed_large_width`
- `feed_large_height`
- `feed_large_bytes`
- `media_ready_at`
- `media_error`
- `native_aspect_ratio`
- `orientation`
- `source_type`
- `source_label`
- `display_policy`
- `remix_policy`
- `tags_json`
- `updated_at`

Проверка после миграции: `missing_after_migration_check []`.

Файлы не чистились и не переформатировались на этом шаге.

## Feed Media Migration Applied

После внедрения backend-контракта выполнена миграция feed media:

`python backend/feed_media_migrate.py --apply --report logs/feed-media-migration-20260707.json`

Итог:

| Метрика | Значение |
|---------|---------:|
| Всего публикаций | 53 |
| `published` после миграции | 48 |
| `media_missing` после миграции | 5 |
| Seed/demo опубликованы и сохранены | 43 |
| Published без имен feed-файлов | 0 |
| Published без физических feed-файлов | 0 |
| Средний `feed_thumb` | 61.2 KB |
| Максимальный `feed_thumb` | 105.6 KB |
| Средний `feed_large` | 265.5 KB |
| Максимальный `feed_large` | 448.8 KB |

Для всех доступных опубликованных публикаций созданы публичные WebP-варианты в
`backend/media/feed`:

- `*_thumb.webp`: карточки и быстрые previews.
- `*_large.webp`: детальный просмотр / открытие работы.

Оригиналы не удалялись и не перезаписывались. Seed/demo PNG остались как
исходники, но больше не должны отдаваться в ленту напрямую.

Пять публикаций с отсутствующими source-файлами переведены в `media_missing`.
Они не должны попадать в `/api/feed`, пока source не будет восстановлен и для них
не будут пересозданы feed variants.
