---
name: onenode-rules
description: Use for EVERY change to OneNode Image Studio, especially identity/auth work. Covers project facts (FastAPI monolith, SQLite, React+TS), critical security rules (no trust of headers/cookies/frontend IDs), additive-only DB schema, and phased implementation constraints. Activates on: onenode, identity, auth, session, sqlite migration, backend/main.py, frontend/src/App.tsx, X-OneNode-User, internal_user_id, auth_identities, Telegram initData, MAX WebAppData, bootstrap, security_events, audit_logs.
---

# OneNode Image Studio — Project Rules

> Scope: Safe, surgical replacement of the identity/auth layer. We are NOT rebuilding the project.
> Read `docs/identity-core-plan.md` and `docs/identity-core-risks.md` before any identity/auth change.

## Project Facts

* Backend is FastAPI in `backend/main.py` (single-file monolith).
* Database is SQLite using raw `sqlite3` (no ORM).
* No dedicated migration layer; schema lives inside `init_db()` and is applied via
  `CREATE TABLE IF NOT EXISTS` + additive `ALTER TABLE ADD COLUMN`.
* Frontend is React + Vite + TypeScript (single-file UI in `frontend/src/App.tsx`).
* Current `users.id` is a legacy provider-based id: `telegram_xxx` / `max_xxx` / `web_xxx`.
* Do **not** destructively change `users.id`.
* New canonical identity must be introduced additively as `users.internal_user_id`.
* Do **not** introduce ORM.
* Do **not** migrate to PostgreSQL.
* Do **not** split `backend/main.py` into many modules unless explicitly approved.
* Preserve existing `jobs`, `images`, `token_ledger`, `presets`, `loras`, `model_profiles`,
  `promo_codes` and `admin_settings` data.

## Critical Security Rules

* Do **not** trust `X-OneNode-User` as authentication.
* Do **not** trust `onenode_user` cookie as authentication.
* Do **not** trust frontend `user_id`.
* Do **not** trust Telegram `initDataUnsafe`.
* Do **not** trust MAX `userId` without server-side `WebAppData` validation.
* Store only **hashes** of session tokens, refresh tokens and OTP codes.
* Do **not** log tokens, cookies, `Authorization` headers, OTP, passwords, full raw `initData`
  or full raw `WebAppData`.
* Auth failures **must** create `security_events`.
* Admin mutations **must** create `audit_logs`.

## Database Rules (ABSOLUTE)

* Additive-only schema changes.
* Allowed: `CREATE TABLE IF NOT EXISTS`.
* Allowed: `CREATE INDEX IF NOT EXISTS`.
* Allowed: `ALTER TABLE ADD COLUMN` only when safe for SQLite (nullable or default-safe).
* **Forbidden**: `DROP TABLE`.
* **Forbidden**: `DROP COLUMN`.
* **Forbidden**: rename `users.id`.
* **Forbidden**: mass `UPDATE users.id`.
* **Forbidden**: destructive schema rewrite.
* Always preserve existing data.

## Identity Transitional Model

Keep the legacy id and layer the canonical identity beside it:

* `users.id` — legacy provider-based id. Stays stable.
* `users.internal_user_id` — new canonical, provider-independent identity id (opaque/UUID).
  Added via `ALTER TABLE ADD COLUMN`; backfilled idempotently.
* `auth_identities` — maps `(provider, provider_user_id)` → `internal_user_id`
  (UNIQUE on `provider` + `provider_user_id`).
* `auth_sessions` — trusted, server-issued sessions. Token **hash** → `internal_user_id` + legacy `users.id`.
* `security_events` — security-relevant events (never contains raw tokens/OTP/initData).
* `audit_logs` — admin mutations (who changed what, when).

## Implementation Rules

* Work by small phases.
* Do **not** implement future modules unless explicitly requested.
* Do **not** implement payments, public feed, full gallery refactor or full template refactor now.
* Keep compatibility with the current project.
* Every security-sensitive change requires tests.
* Do **not** create a parallel auth system. The new Identity Core must become the trusted layer gradually.

## Testing Rules

* Test `X-OneNode-User` spoofing.
* Test unsigned MAX auth fails.
* Test Telegram without valid `initData` fails.
* Test repeated provider login reuses the same `internal_user_id`.
* Test session token hashes are stored, not raw tokens.
* Test non-admin cannot access admin endpoints.
* Test `init_db` idempotency.
* Test `users.id` is not changed.

## Key Files

* Backend: `backend/main.py`
* Database: `backend/database.db` (SQLite)
* Frontend: `frontend/src/App.tsx`
* Env secrets: `backend/.env` — never modify, never log any value from it
* Docs: `docs/identity-core-plan.md`, `docs/identity-core-risks.md`

## Pre-Code Checklist (every identity/auth change)

1. Did I read `docs/identity-core-plan.md`?
2. Is this change additive-only (no DROP, no destructive ALTER)?
3. Does it preserve existing data?
4. Are secrets stored only as hashes?
5. Does it avoid trusting client headers/cookies/user_id?
6. Does it write `security_events` on auth failures?
7. Does it write `audit_logs` on admin mutations?
8. Does it include tests for security-sensitive paths?
