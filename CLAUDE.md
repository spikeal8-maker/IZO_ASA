# Claude Code Project Rules

> Scope note: These rules govern the safe, surgical replacement of the identity/auth
> layer of this project (OneNode Image Studio). We are NOT rebuilding the project.
> Read `.claude/rules/*` and `docs/identity-core-plan.md` before any identity/auth change.

## Project Facts

* Backend is FastAPI in `backend/main.py` (single-file monolith).
* Database is SQLite using raw `sqlite3` (no ORM).
* There is no dedicated migration layer; schema lives inside `init_db()` and is applied via
  `CREATE TABLE IF NOT EXISTS` + additive `ALTER TABLE ADD COLUMN`.
* Frontend is React + Vite + TypeScript (single-file UI in `frontend/src/App.tsx`).
* Current `users.id` is a legacy provider-based id: `telegram_xxx` / `max_xxx` / `web_xxx`.
* Do not destructively change `users.id`.
* New canonical identity must be introduced additively as `users.internal_user_id`.
* Do not introduce ORM in this phase.
* Do not migrate to PostgreSQL in this phase.
* Do not split `backend/main.py` into many modules unless explicitly approved.
* Preserve existing `jobs`, `images`, `token_ledger`, `presets`, `loras`, `model_profiles`,
  `promo_codes` and `admin_settings` data.

## Critical Security Rules

* Do not trust `X-OneNode-User` as authentication.
* Do not trust `onenode_user` cookie as authentication.
* Do not trust frontend `user_id`.
* Do not trust Telegram `initDataUnsafe`.
* Do not trust MAX `userId` without server-side `WebAppData` validation.
* Store only hashes of session tokens, refresh tokens and OTP codes.
* Do not log tokens, cookies, `Authorization` headers, OTP, passwords, full raw `initData`
  or full raw `WebAppData`.
* Auth failures must create `security_events`.
* Admin mutations must create `audit_logs`.

## Database Rules

* Additive-only schema changes.
* Allowed: `CREATE TABLE IF NOT EXISTS`.
* Allowed: `CREATE INDEX IF NOT EXISTS`.
* Allowed: `ALTER TABLE ADD COLUMN` only when safe for SQLite (nullable or default-safe).
* Forbidden: `DROP TABLE`.
* Forbidden: `DROP COLUMN`.
* Forbidden: rename `users.id`.
* Forbidden: mass `UPDATE users.id`.
* Forbidden: destructive schema rewrite.
* Always preserve existing data.

## Implementation Rules

* Work by small phases.
* Do not implement future modules unless explicitly requested.
* Do not implement payments, public feed, full gallery refactor or full template refactor now.
* Keep compatibility with the current project.
* Every security-sensitive change requires tests.
* Do not create a parallel auth system. The new Identity Core must become the trusted layer
  gradually.

## Testing Rules

* Test `X-OneNode-User` spoofing.
* Test unsigned MAX auth fails.
* Test Telegram without valid `initData` fails.
* Test repeated provider login reuses the same `internal_user_id`.
* Test session token hashes are stored, not raw tokens.
* Test non-admin cannot access admin endpoints.
* Test `init_db` idempotency.
* Test `users.id` is not changed.
