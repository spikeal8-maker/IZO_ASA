# AUTH-BOT-P0 — надёжность входа Telegram/MAX

Дата: 2026-07-23

Статус: CODE COMPLETE; production deployment и real-provider acceptance фиксируются ниже отдельно.

## Инцидент

После переноса production на новый Windows-host пользователи могли открыть окно
входа, но кнопки Telegram/MAX не завершали авторизацию. Повторные клики иногда
возвращали общий текст «не удалось начать вход», а переход на `/profile`
показывал отдельную гостевую страницу перед настоящим диалогом входа.

## Подтверждённые причины

1. FRP/VPS передавал очищенные `X-Real-IP`/`X-Forwarded-For`, но active Caddy и
   backend не включили доверие к ним. Все публичные клиенты учитывались как
   loopback, поэтому общий rate limit отвечал `429` даже нормальному посетителю.
2. Повторный клик того же браузера создавал ещё одну pending-заявку и заменял
   cookie; подтверждение старой ссылки уже не совпадало с текущим браузером.
3. Telegram/MAX webhook возвращал `200` даже при исключении обработчика.
   Telegram update при этом уже попадал в replay-cache и больше не исполнялся.
4. Подтверждённая ботом заявка не восстанавливалась при возврате или перезагрузке
   страницы до завершения polling.
5. Ссылка на бота открывалась только после сетевого ожидания. Safari/mobile мог
   считать это не пользовательским кликом и заблокировать новое окно.
6. MAX subscription существовала без доказанного совпадения текущего webhook
   secret; её нужно перерегистрировать после переключения host.

Секреты, токены, пользовательские адреса и содержимое cookies в evidence не
записываются.

## Исправление

- backend принимает proxy metadata только от прямого loopback peer; production
  launcher включает `TRUST_PROXY_HEADERS=true`, Uvicorn остаётся с
  `--no-proxy-headers`, а Caddy доверяет только `127.0.0.1/32`;
- новый start атомарно завершает предыдущую pending-заявку того же браузера и
  provider, не ослабляя per-IP/global limits для разных браузеров;
- повторное подтверждение тем же provider user идемпотентно для `approved` и
  `consumed`, включая provider retry после успешной записи в БД;
- при ошибке Telegram handler update освобождается из replay-cache и webhook
  отвечает `503`; MAX также отвечает `503`, чтобы provider повторил доставку;
- startup браузера проверяет незавершённую bot-login cookie и завершает уже
  одобренный вход после возврата/перезагрузки;
- окно provider резервируется синхронно в обработчике клика; при popup-blocker
  используется same-tab fallback;
- гостевой `/profile` заменяется на `/` и сразу открывает `AuthV2Modal`;
- админские «Проверить» и «Зарегистрировать webhook» показывают явный busy-state.

## Проверки до deployment

- backend bot/proxy/webhook suite: 54 passed;
- high-risk retry/idempotency/rate-limit selection: 9 tests, 5/5 прогонов;
- frontend auth smoke: passed;
- ESLint: passed;
- TypeScript + Vite production build: passed;
- desktop/mobile `/profile`, Telegram popup и MAX popup E2E: passed;
- production dependency audit: 0 vulnerable production dependencies;
- backend symbol map и architecture inventory: generated and drift-check passed;
- Quick/Full exact-SHA gates: pending clean release candidate.

## Production acceptance

После merge точного SHA:

1. Выпустить immutable release штатным updater/promotion pipeline.
2. Проверить active service XML: `TRUST_PROXY_HEADERS=true` и
   `--no-proxy-headers` одновременно.
3. Проверить active Caddy trusted-proxy block и public/local health.
4. Перерегистрировать Telegram webhook и MAX subscription с текущими DPAPI
   secrets через trusted-admin endpoint.
5. Выполнить по одному реальному входу Telegram и MAX с публичного origin;
   после контролируемого start убедиться, что challenge хранит не loopback IP.
6. Проверить negative secret response (`403`), retryable handler response
   (`503` в fake test) и отсутствие секретов в логах.

Rollback boundary: previous immutable release, предыдущие service XML/Caddy
config и DB snapshot promotion pipeline. Схема БД не меняется.
