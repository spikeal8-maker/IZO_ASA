# PHONE-CORE-001 — общие задания, media и billing

Статус: **CODE COMPLETE; TARGETED TESTS, BUILD AND MOBILE E2E GREEN; NOT DEPLOYED**.

## Реализовано

- authenticated facade `GET /api/phone/v1/jobs` для восстановления активных
  заданий пользователя после refresh;
- authenticated `GET /api/phone/v1/jobs/{job_id}` с обязательной проверкой
  владельца до обращения к существующему image/video reader;
- единый provider-neutral контракт статуса, фазы, прогресса, результата и
  списания;
- безопасная пользовательская ошибка без названия поставщика, URL, ключа или
  причины вроде недостаточного внешнего баланса;
- нормализация повреждённого прогресса и жёсткий диапазон 0–100;
- восстановление image/video результата из существующих таблиц без повторного
  запуска генерации;
- клиентский polling с AbortSignal, таймаутом и прекращением на terminal state;
- общие privacy-aware media helpers и раздельное оформление дневных и основных
  токенов;
- индикатор количества активных заданий в общем Phone shell.

Audio, chat и 3D не выданы за поддерживаемые этим facade задания: для них
остаются отдельные feature packages и честный `409`, пока соответствующий
domain service не подключён.

## Инварианты

- browser не вычисляет стоимость и не создаёт новое задание при восстановлении;
- пользователь не может перечислить или прочитать чужое задание;
- private media не превращается в публичную ссылку на клиенте;
- существующие desktop/image/video endpoints не изменены и остаются источником
  выполнения до дальнейшего выделения общих domain services;
- schema migration не требуется.

## Evidence

- Python compilation: green;
- focused backend: `21 passed`;
- phone core frontend: `4 passed`;
- phone contracts frontend: `3 passed`;
- frontend lint: green;
- immutable-label production build: green;
- mobile shell E2E: routes=5, viewports 390×844 и 430×932, iframe=false;
- generated backend/frontend maps refreshed.

## Rollback boundary

Пакет откатывается удалением Phone v1 jobs router, клиентского `phone/core`
слоя и badge активных заданий. База и старые задания не меняются, поэтому
откат не требует преобразования данных и не теряет пользовательские результаты.

## Следующий пакет

`PHONE-CHAT-001`: сохранённые диалоги и сообщения, server-owned context window,
чистое отображение tool calls, web search и image generation через отдельный
оркестратор без вывода технического JSON пользователю.
