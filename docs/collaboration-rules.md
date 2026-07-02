# Collaboration Rules for Parallel Agents

This project often has more than one agent working at once. These rules prevent branch
pollution, overwritten manual work and old unsafe code returning.

## Golden Rules

- One workstream per branch.
- Do not work directly in `main` unless the task is tiny and explicitly approved.
- Do not deploy WIP branches.
- Do not use `git add .`.
- Do not run `git reset`, `git clean`, or checkout over dirty work unless explicitly
  approved for a recovery task.
- Always create a backup patch before moving or staging dirty work.
- Do not touch another agent's files unless coordinating in writing.

## Recommended Branch Ownership

`main`

- Stable integrated baseline.
- Only merged, reviewed, accepted work.

`feature/new-ui-v2`

- Experimental `/new` UI.
- Owner files:
  - `frontend/src/newUi.tsx`
  - `frontend/src/newUi.css`
  - `frontend/src/stylePresets.ts`
  - minimal `/new` route in `frontend/src/App.tsx`
  - `docs/new-ui-v2-plan.md`
  - `docs/new-ui-v2-review.md`

`feature/admin-*`

- Admin/dashboard/CRM work.
- Avoid touching `/new` files.

`feature/auth-*`

- Auth/login/session work.
- Must update `docs/auth-current-state.md`.
- Must run targeted auth tests.

`hotfix/*`

- Minimal release-safe fix.
- One problem only.

## Shared Files Require Extra Care

These files are high-conflict:

- `frontend/src/App.tsx`
- `frontend/src/index.css`
- `frontend/src/authV2.tsx`
- `backend/main.py`
- `frontend/src/stylePresets.ts`
- launch scripts

Before editing a shared file:

1. Check `git status --short`.
2. Check recent diff.
3. State why the shared edit is necessary.
4. Keep the edit minimal.
5. Update docs if behavior changes.

## Handoff Report Required

Every agent must end with:

```text
Branch:
Commit or WIP:
Files changed:
Files intentionally not touched:
Tests run:
Screenshots/artifacts:
Known blockers:
Next safe step:
```

## New UI `/new` Parallel Work

The `/new` work must not reintroduce legacy auth.

Forbidden in `frontend/src/newUi.tsx`:

- `X-OneNode-User`
- `onenode_user`
- `demo_user`
- query/body `userId` as auth

Required:

- API calls use `credentials: 'include'`.
- Generate without session opens auth, not a fake user.
- `/` remains unchanged.
- `/new` is documented in `docs/new-ui-v2-plan.md`.
- Each working session appends to `docs/new-ui-v2-review.md`.

## If Work Is Accidentally Done on `main`

Do not panic and do not reset.

1. Create a backup patch and copy untracked files.
2. Create a feature branch from the current dirty state.
3. Commit or preserve WIP on that branch.
4. Return `main` to clean only through safe, explicit, reviewed steps.

## What Must Never Be Committed

- `.env`
- secrets
- SQLite databases
- raw logs with tokens/cookies/passwords
- generated media unless explicitly intended assets
- screenshots unless they are intentional documentation artifacts
- `frontend/dist`
- `node_modules`
- `__pycache__`

