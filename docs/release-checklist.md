# Release Checklist

Use this before committing, pushing or deploying. The goal is to prevent mixed WIP,
wrong DB launches, stale frontend builds and accidental auth/security regressions.

## Before Any Commit

1. Confirm branch:

```powershell
git branch --show-current
git status --short
```

2. Do not use `git add .`.

3. Do not commit:

- `.env`
- SQLite DB files (`*.sqlite`, `*.sqlite3`)
- media/generated images unless explicitly intended assets
- screenshots
- backup patches
- `frontend/dist`
- `node_modules`
- `__pycache__`
- logs

4. Stage exact files only:

```powershell
git add path/to/file1 path/to/file2
git diff --cached --name-status
git diff --cached --stat
git diff --cached --check
```

5. Confirm the commit does not mix unrelated work.

Examples of separate workstreams:

- auth/login;
- admin/dashboard;
- generation/GPU workflow;
- gallery/tariffs;
- `/new` UI;
- documentation only.

## Standard Verification

Frontend:

```powershell
cd frontend
npx tsc -b
npx vite build
```

Backend syntax:

```powershell
cd backend
python -m py_compile main.py
```

Targeted backend tests depend on scope. Prefer narrow relevant tests plus smoke checks.

## Security Checks

Run static searches when touching auth or new UI:

```powershell
rg -n "X-OneNode-User|onenode_user|demo_user|userId" frontend/src backend/main.py
rg -n "password|token|cookie|initData|WebAppData" backend/main.py frontend/src
```

This search is not automatically a failure; it is a prompt to inspect whether usage is
safe. New trusted code must not use legacy identity as auth.

## Before Deploy

1. Confirm deploy source:

```powershell
git branch --show-current
git rev-parse HEAD
git status --short
```

2. Confirm `.env` and DB are not staged/tracked.

3. Confirm `start-public.bat` uses the real live DB:

- `APP_ENV=production`
- explicit `DATABASE_URL`
- `DB_GUARD_ALLOWED_PATHS`
- minimum DB size/user/admin thresholds

4. Run public launcher:

```powershell
.\start-public.bat
```

5. Verify backend:

```powershell
curl.exe -i http://127.0.0.1:8000/api/health
curl.exe -i http://127.0.0.1:8000/api/version
curl.exe -i http://127.0.0.1:8000/api/auth/capabilities-v2
```

6. Verify public domain:

```powershell
curl.exe -i https://izo.alikinas.ru/api/health
curl.exe -i https://izo.alikinas.ru/api/version
curl.exe -i https://izo.alikinas.ru/api/auth/capabilities-v2
```

7. No-session security checks:

```powershell
curl.exe -i https://izo.alikinas.ru/api/me-v2
curl.exe -i https://izo.alikinas.ru/api/gallery
curl.exe -i -X POST https://izo.alikinas.ru/api/generate
```

Expected: protected endpoints return 401/403 without session.

## Browser Smoke After Deploy

Do not use owner password unless owner is manually verifying.

Check:

- public site opens;
- auth modal opens;
- registration tab visible when password registration is not explicitly disabled;
- unavailable Telegram/MAX methods are hidden;
- generation without session is blocked;
- gallery without session is blocked;
- current `/` UI still works visually;
- admin without session is blocked;
- if deploying `/new`, `/new` works on desktop and mobile.

## Deploy Report Template

Use this exact structure:

```text
Branch:
Commit:
Files changed:
Tests run:
Deploy source:
/api/version:
/api/health:
DB guard:
No-session checks:
Browser screenshots:
Known issues:
Confirmations:
- no force push
- no reset/clean
- no DB mutation
- no owner/admin mutation
- no secrets exposed
```

## Rollback Rule

Do not run destructive rollback commands under pressure. Prefer a new revert commit or
deploying a known safe commit from a clean branch. Preserve the current state first with
a snapshot or backup patch.

