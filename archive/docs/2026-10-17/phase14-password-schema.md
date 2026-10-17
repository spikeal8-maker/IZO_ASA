# Phase 14.4 — Password Auth Schema + Argon2id Hashing Helpers

Backend foundation only. No login/register/forgot/reset endpoints, no frontend,
no generation/gallery/templates changes. Additive schema + hashing helpers + tests.

## Dependency
- `argon2-cffi==23.1.0` installed and added to `backend/requirements.txt`.
- `argon2.PasswordHasher` produces Argon2id (`$argon2id$…`).

## Schema (additive-only, inside init_db())
- `users.email_verified_at TEXT` (nullable, added if missing)
- `users.phone_verified_at TEXT` (nullable, added if missing)
- `auth_passwords` — id PK, internal_user_id, password_hash, algorithm, created_at,
  updated_at, disabled_at, password_updated_at, metadata_json.
  - `idx_auth_passwords_internal_user_id`
  - `ux_auth_passwords_active` = UNIQUE(internal_user_id) WHERE disabled_at IS NULL
    (at most one ACTIVE password per user; unlimited disabled history).
- `password_reset_challenges` — id PK, internal_user_id, token_hash, expires_at,
  consumed_at, created_at, ip_address, user_agent_hash, metadata_json.
  - `idx_password_reset_internal_user_id`, `idx_password_reset_token_hash`,
    `idx_password_reset_expires_at`.
- No DROP / RENAME / rewrite; no `users.id` change; no destructive migration.

## Helpers (Argon2id)
- `validate_password_policy(password) -> list[str]` — codes `password_too_short`
  (<8) / `password_too_long` (>128); unicode allowed; no complexity rules; no breach check.
- `hash_password_argon2(password) -> str` — rejects empty + policy violations, returns
  `$argon2id$…`; never logs password/hash.
- `verify_password_argon2(password, hash) -> bool` — constant-time; returns False on
  mismatch/empty/invalid/malformed hash; never raises to caller; never logs.
- `password_hash_needs_rehash(hash) -> bool` — via `check_needs_rehash`; False on garbage.
- Params: `PasswordHasher(time_cost=3, memory_cost=64MiB, parallelism=2)`; constants
  `PASSWORD_MIN_LENGTH=8`, `PASSWORD_MAX_LENGTH=128`, `PASSWORD_ALGORITHM='argon2id'`.

## Security properties
- Raw password never stored (only Argon2id hash with per-record random salt) and never
  logged. Hash itself never logged. Same password hashes differently each call (salt).
  Verify returns False on mismatch/invalid hash without leaking exceptions.

## Tests
- `pytest test_password_schema.py` → 12 passed (covers all 24 required assertions:
  tables/columns created, idempotent init_db, data + users.id preserved, one-active-
  password constraint + disabled history, reset-token indexes, salted non-raw hashes,
  verify true/false/invalid, needs_rehash bool, policy <8/>128/ok, no raw password in
  log tables, legacy request_user_id/require_admin + v2 endpoints intact, no password
  endpoints yet).
- Full isolated suite (12 files) → 226 passed. `test_api.py` not run.
- backend/onenode.sqlite3 hash identical before/after (tests use temp DB).

## Not done (by design)
register/login/forgot/reset endpoints, frontend, generation protection — later phases.
