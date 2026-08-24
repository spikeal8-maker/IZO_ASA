# PHONE-3D-SPIKE-001 — provider-neutral контракт и выбор направления

**Дата:** 2026-08-24

**Статус:** `CONTRACT COMPLETE; PAID QUALITY BENCHMARK NOT RUN; 3D REMAINS DISABLED`

## Что проверено без платных вызовов

Сравнивались официальные API Meshy и Tripo. Оба провайдера дают асинхронные
text-to-3D и image-to-3D задания, прогресс и GLB с постером. Это соответствует
существующей долговечной модели Phone jobs, но временный provider URL нельзя
отдавать как постоянное хранилище продукта.

| Критерий | Meshy | Tripo |
| --- | --- | --- |
| Создание | отдельные text/image-to-3D endpoints | v3 text/image-to-model |
| Состояния | task polling, `SUCCEEDED`/ошибка | task polling, queued/running/success/failed/cancelled |
| Основной web format | GLB; также OBJ/FBX/STL/USDZ/3MF | GLB и poster в результате |
| Текстуры | 2K/4K/8K, отдельный refine/retexture | texture/PBR и detailed quality |
| Цена в ответе | фиксированные credits по операции | `credits_consumed` в task result |
| Retention | API assets максимум 3 дня | срок не удалось подтвердить в публичной документации |
| Риск до benchmark | качество и topology не измерены | качество, цена и retention не измерены |

Официальные источники:

- [Meshy Quickstart](https://docs.meshy.ai/en/api/quick-start)
- [Meshy Image to 3D](https://docs.meshy.ai/en/api/image-to-3d)
- [Meshy API pricing](https://docs.meshy.ai/en/api/pricing)
- [Meshy asset retention](https://docs.meshy.ai/en/api/asset-retention)
- [Tripo v3 Quickstart](https://developers.tripo3d.com/en/docs/quick-start)
- [Tripo task query](https://developers.tripo3d.com/en/docs/task-query)
- [Tripo text to model](https://developers.tripo3d.com/en/docs/generation-text-to-model/standard)
- [Tripo image to model](https://developers.tripo3d.com/en/docs/generation-image-to-model/standard)

## Решение

Первым кандидатом адаптера для реализации выбран **Meshy**, потому что до
платного quality benchmark у него лучше документированы цены, выходные форматы и
жёсткий retention. Это выбор порядка интеграции, а не утверждение о лучшем
качестве. Tripo остаётся вторым benchmark adapter.

До включения `/phone/3d` обязательны:

1. отдельные DPAPI-секреты и read-only health в админке;
2. fake Meshy/Tripo adapters;
3. durable job с idempotency, cancel, quote/reserve/settle/refund;
4. немедленное скачивание GLB и poster в owner-checked storage;
5. проверка MIME/magic/размера, безопасный parser и mobile derivative;
6. `<model-viewer>` или Three.js viewer с rotate/zoom/pan/reset/fullscreen;
7. платный benchmark на пяти утверждённых запросах с точной квитанцией;
8. проверка коммерческих условий и retention Tripo.

## Зафиксированный контракт

`backend/app/services/phone_3d_contracts.py` задаёт request, quote, job, asset и
adapter protocol. GLB — основной preview format. Стартовые mobile budgets:
20 МБ, 150 000 triangles и texture 2K. Они являются лимитами производного файла,
а не обещанием качества исходника. Provider URL обязан быть HTTPS и после
скачивания не становится публичной постоянной ссылкой.

## Проверка

`backend/test_phone_3d_contracts.py` использует только fake provider и проверяет
quote → create → poll, нормализацию состояний, mobile budgets, HTTPS asset policy
и безопасную пользовательскую ошибку. Денежные средства не расходуются.
