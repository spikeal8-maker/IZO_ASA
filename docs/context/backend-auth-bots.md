---
status: canonical
domain: backend-auth-bots
read_when: ["auth","sessions","bot-login","telegram","max","bots","telegram-max","trusted-identity"]
source_paths: ["backend/main.py","backend/app/api/routers/bots_public.py","backend/app/api/routers/bots_admin.py","backend/app/security/permissions.py","backend/app/security/bot_login.py","backend/app/security/csrf.py","backend/app/security/http_middleware.py","backend/app/services/polling_health.py","backend/app/services/telegram_updates.py","backend/app/services/max_updates.py","backend/app/integrations/telegram.py","backend/app/integrations/max_client.py"]
test_paths: ["backend/test_cookie_session.py","backend/test_auth_sessions.py","backend/test_auth_telegram_v2.py","backend/test_auth_max_v2.py","backend/test_csrf_origin.py","backend/test_bot_login_flow.py","backend/test_polling_health.py","backend/test_admin_bots_v2.py"]
related_domains: ["admin-control-center","chat"]
forbidden_paths: ["unknown"]
owner: backend-auth-bots
context_role: scoped-domain-map
updated: 2026-09-19
---

# Context: backend auth, identity и боты

Назначение: минимальный контекст для задач по аутентификации, сессиям,
admin-доступу и Telegram/MAX ботам. Прочитав этот файл, агент не должен
читать `backend/main.py` целиком.

## Назначение подсистемы

- Доверенная идентичность пользователя: server-side сессии, hash-only токены.
- Боты Telegram/MAX: доставка команд/логина, polling с health-моделью.
- Admin-поверхность: только через `require_trusted_admin`, всё мутации — audit.

## Канонические entrypoints

- HTTP-приложение: `backend/main.py` (`app = FastAPI(...)`) — composition
  shell; новая логика живёт в `backend/app/*`.
- Auth v2 routes: `/api/auth/*-v2`, `/api/me-v2`, `/api/admin/*-v2`.
- Боты: `/api/telegram/*`, `/api/max/*`, `/api/bots/*`,
  admin — `/api/admin/bots/*-v2`.
- Startup wiring: `main.startup` → `start_bot_polling_tasks()`.

## Что читать первым (вместо всего main.py)

1. `backend/SYMBOL_MAP.md` — все symbols/routes с номерами строк.
2. `architecture/contract.json` — legacy allowlist, workers, listeners,
   budgets (`main.py` строго ограничен по строкам/функциям/маршрутам).
3. Этот файл, затем точечные чтения `main.py` по номерам из SYMBOL_MAP.

## Основные production-файлы

- `backend/app/security/permissions.py` — trusted resolution
  (`resolve_trusted_user`, `require_admin` runtime-вариант, audit spoof
  чтения `X-OneNode-User`).
- `backend/app/security/http_requests.py` — body limit middleware и avatar
  decoding.
- `backend/app/security/csrf.py` — реализованная CSRF origin boundary.
- `backend/app/security/http_middleware.py` — реализованная HTTP middleware
  composition, включая подключение security middleware.
- `backend/app/security/bot_login.py` — bot-login challenge/rate limits.
- `backend/app/security/secret_store.py` — DPAPI secret store (bot tokens,
  webhook secrets; account/computer-bound).
- `backend/app/services/polling_health.py` — health registry polling
  (last success/failure, consecutive failures, alert/recovery), backoff
  `compute_poll_backoff`, классификаторы `is_auth_polling_error` /
  `polling_retry_after`.
- `backend/app/services/telegram_updates.py`, `max_updates.py` — обработка
  updates через runtime-объекты (api_call инъецируется из main).
- `backend/app/services/bot_admin.py` — нормализация bot-конфигурации,
  `safe_bot_error`, webhook URL builder.
- `backend/app/services/platform_status.py` — публичные product-safe DTO
  для `/api/platforms` и `/api/bots/status` (SEC-DIAG-001).
- `backend/app/integrations/telegram.py`, `max_client.py`, `max_tls.py` —
  транспорт к провайдерам; `TelegramTransportError` и probe-функции.
- В `main.py` остаются: session service (генерация/refresh/revoke сессий),
  `require_trusted_user` / `require_trusted_admin` wrappers,
  `telegram_poll_once_from_api` / `max_poll_once_from_api`,
  `_provider_polling_cycle`, `start_bot_polling_tasks`,
  `bot_polling_tasks` dict, `POLLING_HEALTH`.

## Основные тесты

- Сессии/куки: `backend/test_cookie_session.py`, `test_auth_sessions.py`.
- Provider auth: `test_auth_telegram_v2.py`, `test_auth_max_v2.py`,
  `test_auth_bootstrap_v2.py`, `test_auth_email_otp_v2.py`.
- Admin: `test_admin_v2.py`, `test_admin_bots_v2.py`,
  `test_admin_password_reset.py`.
- Боты/поллинг: `test_polling_health.py`, `test_bot_login_flow.py`,
  `test_integrations_telegram_module.py`, `test_integrations_max_client_module.py`.
- Публичная безопасность: `test_public_status_redaction.py`,
  `test_security_hotfix_20260629.py`, `test_ownership_protection.py`.

## API и persistent state

- `users.id` — legacy строковый id, стабилен навсегда;
  `users.internal_user_id` — канонический id; маппинг в `auth_identities`.
- `auth_sessions` — только хэши session/refresh токенов; revoked/expired
  сессии не работают; события в `security_events` / `session events`.
- `bot_polling_state` — cursor/marker поллинга по провайдеру; переживает
  restart; НЕ сбрасывается автоматически.
- `admin_settings.bot_diagnostics` — сохранённые диагностики ботов.
- Публичные `/api/platforms`, `/api/bots/status` — только capability
  (ready/commands/buttonText); вся operator-диагностика — только в
  `/api/admin/bots/status-v2` (анонимно = 401).

## Запрещённые изменения

- Не доверять `X-OneNode-User`, `onenode_user`, `initDataUnsafe`,
  неподписанным MAX данным — ни при каких условиях.
- Не создавать вторую auth-систему; legacy consumers перечислены в
  `architecture/contract.json:legacy_auth_consumers` и замораживаются.
- Не удалять webhook и не сбрасывать polling cursor автоматически —
  только явное операторское действие.
- Не запускать второй polling owner: живой task в `bot_polling_tasks`
  никогда не дублируется.
- Не логировать сырые токены, OTP, initData, WebAppData, cookies.
- Не добавлять новую business-логику в `backend/main.py`; бюджеты файла
  затянуты и не повышаются ради роста.

## Какие крупные файлы НЕ читать целиком

- `backend/main.py` (~20 257 строк) — только точечно по SYMBOL_MAP.
- `backend/test_feed_v2.py` — не относится к auth/ботам.
- `frontend/src/newUi.tsx`, `LegacyApp.tsx` — для auth-задач достаточно
  `frontend/src/authV2.tsx` и `docs/generated/frontend-map.md`.

## Известные риски

- Cookie/session auth требует сохранения реализованной CSRF origin boundary и
  HTTP middleware composition; их нельзя обходить локальным route shortcut.
- Bot login и provider updates должны продолжать использовать trusted identity,
  bounded rate limits и product-safe errors.
- Polling owner должен оставаться единственным: при transport-ошибках проверять
  ownership/listener evidence, а не запускать второй polling loop.
- Runtime/provider availability не выводится из source и требует отдельного
  operational evidence.
