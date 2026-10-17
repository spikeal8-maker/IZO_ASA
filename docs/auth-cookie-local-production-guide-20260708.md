# Auth Cookie Guide: Local vs Production

Первоначальная дата: 2026-07-08. Проверка документации: 2026-10-17.

Эта запись описывает инцидент локального входа и безопасные требования к
cookie. Текущее доверие устанавливается серверной сессией; прежние тексты
Identity Core с утверждениями об отсутствии auth защищены только Git-историей.
Политику cookie проверять в `backend/app/config.py` и её применении в
`backend/main.py`, а не переносить июльские значения env в контейнер.

## Что сломалось

Локальный вход по email/password мог выглядеть успешным, но сразу возвращал пользователя
в состояние `Войдите`.

Причина: `backend/.env` содержит production-cookie настройки:

- `TRUSTED_COOKIE_SECURE=true`
- `TRUSTED_COOKIE_SAMESITE=none`

Это правильно для `https://izo.alikinas.ru`, но на `http://localhost` и
`http://127.0.0.1` браузер не должен сохранять/отправлять `Secure` cookie. Поэтому backend
создавал сессию, но следующий `/api/me-v2` приходил без `onenode_session`.

## Текущее правило

Единая функция cookie-настроек находится в `backend/main.py`:

- `trusted_cookie_common(request)`

Она используется для:

- `onenode_session`
- `onenode_refresh`
- `onenode_bot_login`

Поведение:

- Для production/HTTPS остаются значения из env: `Secure=true`, `SameSite=None`.
- Для локального HTTP на `localhost`, `127.0.0.1`, `::1` backend временно ставит
  `Secure=false`, `SameSite=lax`, чтобы браузер реально сохранил cookie.

## Что нельзя делать

- Нельзя менять `backend/.env` на dev-cookie значения ради локального теста: это риск для
  публичного запуска.
- Нельзя возвращать JS-readable auth (`onenode_user`, `X-OneNode-User`, localStorage token).
- Нельзя чинить только email/password: bot-login challenge cookie должен использовать тот же
  helper, иначе Telegram/MAX локально снова сломаются.

## Проверка после изменений auth

Минимальная проверка локального HTTP:

1. Запустить backend на `127.0.0.1:8000`.
2. Зарегистрировать или залогинить тестового email-пользователя.
3. Проверить `Set-Cookie`: для local HTTP не должно быть `Secure`, должен быть `SameSite=lax`.
4. Проверить `/api/me-v2` с тем же cookie: должен вернуть пользователя.
5. Перезапустить backend.
6. Повторить `/api/me-v2` с тем же cookie: пользователь должен остаться авторизован.

Команды проверки, которые запускались после фикса:

```powershell
python -m py_compile main.py
npm run e2e:profile-auth
```

Также вручную проверено через `Invoke-WebRequest`:

- login/register -> `200`
- `/api/me-v2` до restart -> `200`
- restart backend
- `/api/me-v2` после restart -> `200`

## Связанные файлы

- `backend/main.py`
- `frontend/src/authV2.tsx`
- `backend/app/config.py`
- `backend/app/security/permissions.py`
- `docs/context/backend-auth-bots.md`
- `backend/test_auth_sessions.py`, `backend/test_cookie_session.py`
- `TEST_PLAN.md`
