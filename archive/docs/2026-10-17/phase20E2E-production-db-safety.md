# Phase 20E.2E — Production DB Safety Guard

## Root Cause

After the 20E.2C deploy, the live backend was started from a temporary clean worktree.
Because `DATABASE_URL` was not explicit in live mode, the backend silently fell back to:

`backend/onenode.sqlite3`

inside that temporary worktree. That temporary DB was about 0.5 MB and had only a few
users. The real live DB was about 287 MB and contained the real owner/admin data.
Normal password login was not broken; the backend was connected to the wrong DB.

## Guard Rules

In production/live mode (`APP_ENV`, `ENV`, or `MODE` is `production`, `prod`, or
`live`):

- `DATABASE_URL` is required.
- DB path must match `DB_GUARD_ALLOWED_PATHS` when an allowlist is configured.
- DB file must exist before migrations run.
- DB size must be at least `DB_GUARD_MIN_SIZE_MB`.
- Required tables must exist.
- Required columns must exist:
  - `users.plan`
  - `images.deleted_at`
  - `token_ledger.reason`
- Users count must be at least `DB_GUARD_MIN_USERS`.
- Active admin count must be at least `DB_GUARD_MIN_ACTIVE_ADMINS`.

If any production guard fails, backend startup is refused.

Development mode can still use the local fallback DB for tests and local work.

## Safe Live Start

Use `start-public.bat` for live/public launch. It now:

- sets `APP_ENV=production`;
- sets `DATABASE_URL` explicitly;
- sets `DB_GUARD_ALLOWED_PATHS`;
- refuses temporary/clean worktree launch paths;
- refuses suspiciously small DB files;
- prints only a safe DB confirmation before backend launch.

Expected safe confirmation shape:

`Live DB confirmed: .../backend/onenode.sqlite3 (287 MB)`

## Verification

After live start:

1. Open `/api/health`.
2. Confirm:
   - `environment` is `production`;
   - `database.path` is masked;
   - `database.size_mb` matches the real DB size class;
   - `database.users_count` is not tiny;
   - `database.active_admin_count` is not zero;
   - `db_guard.ok` is `true`.
3. Open `/api/version`.
4. Confirm:
   - `build` is current;
   - `backend_commit` is present when Git is available;
   - `db_guard.ok` is `true`.

## If Guard Fails

Do not delete or recreate the DB.

Check:

- Is `APP_ENV=production`?
- Is `DATABASE_URL` set to the real live SQLite file?
- Does `DB_GUARD_ALLOWED_PATHS` match the same file?
- Is the DB file unexpectedly small?
- Are migrations missing because the backend did not reach `init_db()`?

Fix the launch environment/path first. Only consider data repair if the real live DB
itself fails schema/count checks, and get explicit owner approval before changing
owner/admin data.

## Sensitive Data

The guard and diagnostics do not expose:

- raw `DATABASE_URL` with credentials;
- passwords;
- password/session/refresh hashes;
- cookies;
- raw tokens;
- Telegram initData;
- MAX WebAppData.

