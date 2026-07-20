# AUTH-LEGACY-001A — route matrix авторизации (2026-07-20)

Base SHA: `bd7b5ab8e9cbe11e72051560cd3aab833ea3bcb9`. Источник классификации —
generated `backend/SYMBOL_MAP.md` (223 маршрута, полный список с номерами
строк) и `architecture/contract.json`. Этот документ фиксирует ФАКТИЧЕСКОЕ
текущее поведение; runtime в пакете 001A не менялся. Runtime-доказательства —
`backend/test_auth_legacy_characterization.py`.

## Сводка по policy (все 223 маршрута классифицированы)

| Policy | Кол-во | Определение trusted identity |
|---|---:|---|
| `admin` | 97 | `require_trusted_admin` → server session + role=admin |
| `user` | 55 | `require_trusted_user` → server session |
| `session` | 1 | `resolve_auth_session_from_request` (список сессий) |
| `public/optional` | 60 | identity не требуется или optional session |
| `REVIEW` (admin wrappers) | 8 | делегируют в trusted-admin mutation (см. ниже) |
| `webhook: telegram` | 1 | provider secret header |
| `webhook: MAX` | 1 | provider secret header |

## Матрица групп

| Route (группа) | Method | Policy | Gate/dependency | Legacy input | Anonymous result | Spoof result |
|---|---|---|---|---|---|---|
| `/api/health`, `/api/version`, `/api/platforms`, `/api/bots/status`, `/api/feed*` (публичная лента), commerce/public docs, static shells | GET | public | нет (product-safe payload, SEC-DIAG-001) | игнорируется | 200 | 200, identity не создаётся |
| `/api/app/bootstrap`, `/api/bots/local-command` | POST | public/optional | без identity; Telegram initData валидируется, иначе деградация к web-профилю | `onenode_user` ставится как compat-output (не читается) | 200 (web identity) | 200, spoof id НЕ становится identity |
| `/api/auth/*-v2` (login/OTP/telegram/max/bot-login/refresh/logout) | POST | public/optional | создают/обновляют сессию только после server-side проверки (OTP hash, initData HMAC, WebAppData HMAC, refresh token hash) | не читается | 200/400/401 по флоу | подделка подписи → 401, identity нет |
| `/api/auth/sessions-v2` | GET | session | `resolve_auth_session_from_request` | не читается | 401 | 401 |
| `/api/generate`, `/api/jobs/*`, `/api/gallery*`, `/api/me*-v2`, `/api/account/*`, `/api/billing/*` (кроме webhook), video/feed мутации пользователя | GET/POST/PUT/DELETE | user | `require_trusted_user` | не читается | 401 | 401 (см. spoof-тесты) |
| `/api/admin/**-v2` (97 маршрутов: users, billing, bots, mail, analytics, diagnostics, models…) | все | admin | `require_trusted_admin`; мутации пишут audit | `X-OneNode-User` читается ТОЛЬКО в `resolve_trusted_identity` для audit spoof-попыток ПОСЛЕ session-резолюции | 401 | 401 + security audit |
| 8 v2 bot-token/verify/webhook-secret wrappers | PUT/DELETE/POST | admin (REVIEW-помечены) | тонкие обёртки, делегируют в provider-specific trusted-admin mutation (allowlist `reviewed_routes` в contract.json) | не читается | 401 | 401 |
| `/api/telegram/webhook` | POST | webhook | mode=webhook обязателен (иначе 404); `X-Telegram-Bot-Api-Secret-Token` сверяется constant-time; body limit | user id из legacy не читается | 404 (polling mode) / 403 без секрета | 403 — legacy id не заменяет секрет |
| `/api/max/webhook` | POST | webhook | mode=webhook (иначе 404); `X-Max-Bot-Api-Secret` | не читается | 404 / 403 | 403 |
| `/api/billing/yookassa/webhook-v2` | POST | webhook (payment) | валидация структуры события + идемпотентный event_key + сверка платежа через provider config; финансовое состояние меняется только по подтверждённому платежу | не читается | 400 invalid event / 503 not configured | legacy id не влияет |
| `/api/telegram|max/poll-once`, `set-webhook`, `delete-webhook` (не-admin operator paths) | POST | user/операторские | требуют токен провайдера; без него 400 | не читается | 400/401 | 400/401 |

## Legacy inputs — где они ещё существуют (allowlist contract.json)

| # | Symbol | Operation | Роль | Authorization? |
|---:|---|---|---|---|
| 1 | `main.request_user_id` | read `X-OneNode-User` | frozen compat helper | НЕТ: единственный вызов — `main.require_admin` |
| 2 | `main.request_user_id` | read `onenode_user` | frozen compat helper | НЕТ (та же цепочка) |
| 3 | `main.bootstrap` | set `onenode_user` | compat-OUTPUT для legacy Mini App | не credential |
| 4 | `main.web_login` | delete `onenode_user` | очистка устаревшей куки | нет |
| 5 | `permissions.resolve_trusted_identity` | read `X-OneNode-User` | security AUDIT spoof-попыток после session-резолюции | нет |

Ключевой статический факт (доказан AST-тестом): цепочка
`request_user_id` → `require_admin` не вызывается НИ ОДНИМ route handler.
Это мёртвая совместимость: protected/admin consumers legacy identity = 0.
Найденный drift contract.json относительно кода: отсутствует (5 записей
соответствуют 5 фактическим точкам использования).

## Ожидаемые ответы (сводно)

- Без trusted session: user/session route → 401; admin route → 401;
  webhook → 404/403 по своей boundary.
- С поддельным legacy id (header и/или cookie, включая admin id):
  те же 401/403 — значение не участвует в авторизации; на admin-поверхности
  spoof дополнительно попадает в security audit.
- Unsigned/повреждённый Telegram `initData` → identity не создаётся
  (validate → None; auth-v2 → 401; bootstrap деградирует к web-профилю).
- Непроверенный/повреждённый MAX `WebAppData` → `MaxAuthError` → 401.

## Известные ограничения текущего поведения (для 001B/001D, НЕ менялись здесь)

- Cookie-сессии в production используют `SameSite=None`; CSRF-граница для
  cookie-auth мутаций ещё не включена (готова в handoff, пакет 001B).
- Мёртвая пара `request_user_id`/`require_admin` остаётся в `main.py` до
  пакета 001D (характеризована тестами, вызовов нет).
