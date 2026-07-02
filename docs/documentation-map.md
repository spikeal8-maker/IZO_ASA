# Project Documentation Map

This file is the first stop for humans and agents. The project has many historical
phase reports; this map explains which documents are current working references and
which documents are evidence from previous phases.

## Current Working Documents

Read these first:

1. `README.md`
   - Short project overview.
   - Local run notes.
   - High-level documentation map.

2. `CLAUDE.md`
   - Hard safety rules for identity/auth, DB and testing.
   - Especially important: do not trust `X-OneNode-User`, `onenode_user`, frontend
     `user_id`, Telegram `initDataUnsafe`, or unsigned MAX data.

3. `docs/current-architecture.md`
   - Current backend/frontend/runtime structure.
   - Main data stores and launch model.

4. `docs/auth-current-state.md`
   - Current login/registration/session state.
   - Telegram/MAX Mini App and bot-login status.
   - Email provider and verification rules.

5. `docs/release-checklist.md`
   - Required checks before commit, push, deploy or live verification.
   - Safe Git and deploy procedure.

6. `docs/collaboration-rules.md`
   - How multiple agents must split branches and files.
   - What to do before editing shared files.

7. `docs/new-ui-v2-plan.md`
   - Contract for the experimental `/new` UI.
   - Boundaries, allowed files, API contracts and acceptance checklist.

8. `docs/public-launch.md`
   - Difference between dev launch and public/live launch.
   - `start-public.bat` behavior and verification.

9. `docs/phase20E2E-production-db-safety.md`
   - Production SQLite guard rules.
   - What prevents the live backend from starting on the wrong DB.

10. `docs/identity-core-plan.md` and `docs/identity-core-risks.md`
    - Security background for identity/auth.
    - Required direction for auth-related work.

11. `docs/admin-panel-product-spec.md`
    - Product direction for admin and CRM.
    - Useful before admin UI or admin endpoint changes.

## Historical Phase Reports

Files named `docs/phase*.md` are historical reports from previous work. They are
valuable for evidence, tests run, and why decisions were made. They are not always
the current source of truth. If a historical document conflicts with a current
working document, follow the current working document and create an explicit update.

## Required Documentation Updates

Every non-trivial change must update documentation in the same branch:

- New auth behavior: update `docs/auth-current-state.md`.
- New runtime/deploy behavior: update `docs/current-architecture.md` or `docs/public-launch.md`.
- New release or verification requirement: update `docs/release-checklist.md` or `TEST_PLAN.md`.
- New `/new` UI behavior: update `docs/new-ui-v2-plan.md` and append to `docs/new-ui-v2-review.md`.
- New branch/parallel workflow: update `docs/collaboration-rules.md`.

Do not leave behavior only in chat logs. If it matters to future work, write it here
or in the appropriate document.

