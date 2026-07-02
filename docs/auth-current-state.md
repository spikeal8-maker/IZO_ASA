# Auth Current State

This document describes the current authentication and account state. Update it when
registration, login, sessions, Telegram, MAX, email verification or account linking
changes.

## Core Rule

The trusted auth layer is server-issued cookie session auth.

Do not use as authentication:

- `X-OneNode-User`
- `onenode_user`
- `demo_user`
- query/body `userId`
- username, phone or email as provider proof
- Telegram `initDataUnsafe`
- unsigned MAX payload

If old compatibility code still exists outside the trusted path, do not copy it into
new UI or new endpoints.

## Frontend Auth Entry

Main frontend auth UI lives in:

- `frontend/src/authV2.tsx`

Auth state should be read through the v2 auth flow and backend session cookies. New UI
surfaces must call API with:

```ts
credentials: 'include'
```

and must not add legacy identity headers.

## `/api/me-v2`

`/api/me-v2` is the frontend's primary way to know whether the browser has a trusted
session. Without a valid session it returns 401. With a valid session it returns the
current user/account information used by the UI.

When changing `/api/me-v2`, document:

- user id fields exposed;
- email and email verification state;
- identities;
- plan/tokens/capabilities;
- generation/settings permissions;
- any admin flags.

## Capabilities

`GET /api/auth/capabilities-v2` tells the frontend which auth methods may be shown.

Expected capability concepts:

- password login availability;
- password registration availability;
- email OTP availability;
- Telegram bot-login availability;
- MAX bot-login availability.

UI rule: unavailable auth methods should not be shown as disabled public clutter.
Technical auth server errors may be shown as a clear auth/server problem, not as
provider buttons that promise a broken flow.

## Password Registration and Login

Password registration/login is implemented in backend auth endpoints. Passwords must
never be logged. Password hashes must never be returned.

Current security rule for email verification:

- If email verification provider is available and the user has `email_verified_at IS NULL`,
  password login must not create a trusted session.
- Login should return a safe `email_verification_required` response.
- If email provider is unavailable in non-production/dev flows, password registration/login
  may continue according to configured dev behavior.
- Production registration without a working provider must not silently create an unsafe
  trusted path.

When changing password auth, test:

- verified user can login;
- wrong password fails;
- deactivated/banned users cannot login;
- unverified user cannot bypass verification when email verification is enabled;
- no cookies are set on failed or verification-required login.

## Email OTP

Email OTP availability is determined by backend config/provider state. Current code has
rate limits and challenge storage for OTP verification. Do not implement or claim email
delivery is production-ready unless provider configuration and live smoke are verified.

Do not log:

- raw OTP;
- OTP hash;
- email provider secrets;
- cookies/tokens.

## Telegram Mini App

Telegram Mini App auth must be based on server-side signed `initData` validation.

Required principles:

- check signature with bot token;
- check `auth_date` TTL;
- do not trust `initDataUnsafe`;
- do not use Telegram username/phone as proof;
- provider user id must come from verified Telegram payload.

## MAX Mini App

MAX Mini App auth must be based on server-side signed `WebAppData`/init data validation.

Required principles:

- check signature using MAX bot secret/token rules implemented in backend;
- check TTL/auth date where available;
- provider user id must come from verified MAX payload;
- do not trust frontend `userId`, username, phone or email.

If MAX official payload rules change, update backend tests and this document together.

## Telegram/MAX Bot Login

Bot-login is a browser-to-bot challenge flow:

1. Browser calls `POST /api/auth/bot-login/start` with provider.
2. Backend creates one-time challenge and stores only hashes.
3. Backend sets a challenge cookie and returns a provider deep link.
4. User opens bot with `login_<token>` payload.
5. Bot shows "confirm login".
6. Provider callback/update approves the challenge using real provider user id.
7. Browser polls `GET /api/auth/bot-login/status`.
8. Backend creates trusted `onenode_session` and `onenode_refresh` cookies.

Do not create a session at `/start login_<token>` time. Session is created only when
the browser with the matching challenge cookie polls approved status.

## Account Linking

Account linking must never silently merge users.

Target behavior:

- If the user is already in a trusted session and links a provider, attach an identity
  to the current `internal_user_id`.
- If the provider identity belongs to another user, return conflict.
- If email belongs to another user, return conflict.
- No automatic merge.
- Rewards for linking must be one-time and ledger-backed.

If linking is not fully implemented for a provider, the UI must say so or hide it.

## Sessions

Sessions and refresh tokens must be stored as hashes only. Logout should invalidate
server-side session/refresh state and clear cookies.

When changing session behavior, test:

- no-session protected endpoints return 401;
- refresh rotation behavior if touched;
- logout clears access;
- admin endpoints reject non-admin and no-session;
- spoofed legacy headers do not grant access.

## Rate Limits

Rate limits exist around OTP and auth attempts in backend. When adding a new auth entry
point, add rate limiting and tests. Bot-login start endpoints should not be spam-able.

## Required Tests for Auth Changes

At minimum:

```powershell
cd backend
python -m pytest backend/test_password_auth.py backend/test_email_verification_flow.py backend/test_auth_sessions.py backend/test_auth_telegram_v2.py backend/test_auth_max_v2.py backend/test_bot_login_flow.py -q
```

Frontend:

```powershell
cd frontend
npx tsc -b
npx vite build
```

Run narrower tests when the change is intentionally scoped, but document what was not
run and why.

