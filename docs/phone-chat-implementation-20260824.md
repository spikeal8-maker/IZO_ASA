# PHONE-CHAT-001 — нативный мобильный чат

Статус: **CODE COMPLETE; AUTOMATED MOBILE E2E GREEN; NOT DEPLOYED; LIVE PROVIDER ACCEPTANCE PENDING ROLLOUT**.

## Реализовано

- нативный React-экран `/phone/chat` без iframe и технического JSON;
- сохраняемые диалоги, горизонтальные вкладки, создание, выбор и удаление;
- восстановление сообщений и выбранной модели после refresh;
- server-owned список локальных и API-моделей с кратким описанием, контекстом,
  стоимостью и правильным цветом дневных/основных токенов;
- контекст диалога хранится на сервере и ограничивается настройкой thread;
- компактные сообщения, копирование, изменение/повтор запроса и быстрые
  стартовые варианты;
- до четырёх JPEG/PNG/WebP вложений с ограничением размера;
- голос по удержанию: запись начинается на pointer down, завершается на release,
  затем проходит через существующий authenticated speech-to-text endpoint;
- поиск в интернете остаётся серверным tool call и не показывает служебный
  блок пользователю;
- image tool запускает реальный `/api/generate`, отслеживает общий Phone job,
  показывает результат, скачивание и переход в оживление;
- состояние image tool сохраняется в сообщении, а private provider URL не может
  быть записан или возвращён вместо внутреннего `/api/*` media route;
- нейтральные ошибки и возврат токенов при provider/timeout failure сохранены.

## Экономика и данные

- цена чата и тип токенов поступают только из backend model config;
- запрос имеет уникальный `requestId`, а существующий billing service выполняет
  idempotent charge/refund;
- изображение, запущенное инструментом, является отдельной реальной генерацией
  и оплачивается её обычным серверным путём;
- сообщения принадлежат thread пользователя; обновить результат инструмента в
  чужом сообщении невозможно;
- сырые provider name, endpoint, ключ и внешний баланс пользователю не выдаются.

## Evidence

- focused backend chat/history/tools/billing: `38 passed`;
- frontend chat contract/tool tests: `3 passed`;
- frontend lint: green;
- immutable-label production build: green;
- mobile E2E на 390×844 и 430×932: создание thread, отправка, ответ, refresh,
  пять маршрутов и отсутствие iframe — green;
- backend/frontend generated maps refreshed.

Browser E2E использует управляемый ответ provider, поэтому не доказывает живой
внешний поиск или качество модели. Live provider acceptance выполняется только
после staged deploy на тестовом аккаунте: один поиск, один обычный ответ, один
image tool, проверка двух списаний и результата в галерее.

## Rollback boundary

Frontend откатывается на compatibility panel, backend — удалением endpoint
обновления tools и дополнительных message ids. Таблицы thread/messages остаются
совместимыми; migration не добавлялась, история и созданные media не удаляются.

## Следующий пакет

`PHONE-IMAGE-001`: нативная рабочая область изображений с существующими стилями,
шаблонами, режимами изменения/совмещения/рисования, 16:9 preview, zoom/pinch,
реальными моделями, заданиями и галереей.
