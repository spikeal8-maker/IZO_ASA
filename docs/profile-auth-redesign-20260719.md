# Profile and authentication redesign

Date: 2026-07-19

## Scope

- Rebuilt the user profile for desktop and mobile around account status, token balances, tariff dates, personal data, security and public profile settings.
- Removed likes, followers and promotional bonus counters from the account overview.
- Added real authenticated password change with current-password verification and revocation of other active sessions.
- Added registration date, tariff start and tariff expiry to the profile contract and UI.
- Kept identity linking, avatar selection, tariff capabilities and public profile editing available without placing every control on the first screen.
- Reworked login and registration into a compact desktop dialog and a mobile bottom sheet.
- Successful password login, registration, email verification and bot authentication now return the user to `/#text-to-image`.

## Password contract

`POST /api/auth/password/change-v2`

Request:

```json
{
  "current_password": "current password",
  "new_password": "new password",
  "repeat_password": "new password"
}
```

The endpoint requires a trusted authenticated session, validates the current Argon2 hash and password policy, updates the hash and revokes every other active session. Passwords are not written to application or security logs.

## Profile contract

`GET /api/me-v2` now includes:

- `created_at` for the account registration date;
- `account.password_configured` for the security UI;
- the existing `account.plan_started_at` and `account.plan_expires_at` values used by the tariff status block.

## Email boundary

The authentication UI does not promise password recovery by email. Email recovery remains unavailable until a transactional mail channel is verified and enabled.

## Verification

- Backend password/auth tests cover success, wrong current password, password reuse, preservation of the current session and revocation of other sessions.
- Profile E2E covers authorized desktop and mobile layouts, registration and expiry dates, balances, removed irrelevant metrics and horizontal overflow.
- Auth E2E covers desktop and mobile dialog rendering and redirect to the text generator after successful login.
- Frontend TypeScript and Vite production build are required before release.

## Release boundary

This package is prepared in an isolated branch. It must be merged and deployed only after the active canonical production release has handed the shared workspace back.
