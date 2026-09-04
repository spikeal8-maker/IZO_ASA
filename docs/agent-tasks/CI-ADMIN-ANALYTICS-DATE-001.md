---
status: ready-for-review
package: CI-ADMIN-ANALYTICS-DATE-001
owner: codex
updated: 2026-09-04
---

# Task Contract: CI-ADMIN-ANALYTICS-DATE-001

```yaml
id: CI-ADMIN-ANALYTICS-DATE-001
goal: Make the rolling 14-day admin analytics test independent of the wall-clock date.
userOutcome: Pull requests can receive trustworthy CI results instead of failing when a hard-coded fixture date ages out of the rolling activity window.
beforeScenario: Run `test_user_dossier_access_models_and_paginated_history` on 2026-09-04; its image event is fixed at 2026-08-20, falls outside the current 14-day window, and incorrectly reports zero API images.
afterScenario: Run the test on any date; its fixture events are anchored inside the current UTC 14-day window, while history ordering and economics assertions remain deterministic.
nonGoals:
  - Change admin analytics product behavior, API schemas, rolling-window semantics, UI, database migrations, or production data.
  - Modify the chat feature package or hide unrelated test failures.
  - Merge, deploy, restart services, or run live providers.
domain: admin analytics test reliability
riskClass: standard
declaredFiles:
  - backend/test_admin_analytics.py
  - docs/agent-tasks/CI-ADMIN-ANALYTICS-DATE-001.md
allowedPatterns:
  - test-only UTC-relative fixture timestamps
  - assertions proving the generated event remains in the rolling 14-day series
acceptance:
  - The previously failing dossier analytics test passes on the current date.
  - The complete admin analytics test module passes.
  - Product source and schemas remain byte-for-byte unchanged.
  - The fixture still proves login, generation, media, token, cost, invoice and payment behavior.
requiredEvidence:
  - reproduction on clean canonical main
  - focused failing node before/after
  - complete backend/test_admin_analytics.py
  - repository CI on the exact pushed commit
targetedTests:
  - backend/test_admin_analytics.py::test_user_dossier_access_models_and_paginated_history
  - backend/test_admin_analytics.py
forbiddenOperations:
  - production database, media, secrets, providers, payments, runtime, or network mutation
  - product behavior changes, deployment, service restart, release promotion, or direct edits in main
rollbackBoundary: Revert the single test-only commit; production code and data are unaffected.
```

## Evidence at start

- Canonical `main` was clean at `4ed17f0849b291ccb493513dcf3f599312739004` and matched `origin/main`.
- CI run `33896814979` failed the node with `api_images == 0`; 1,908 other tests passed.
- The exact node failed identically on clean canonical `main` on 2026-09-04.
- No open PR or issue and no dirty overlapping worktree was found for `backend/test_admin_analytics.py`.

## Completion evidence

- The fixture day is now calculated as the previous UTC day, so every related
  login, generation, media, token, invoice and payment event remains inside the
  rolling 14-day window without changing their relative ordering.
- `backend/test_admin_analytics.py::test_user_dossier_access_models_and_paginated_history`:
  1 passed.
- Complete `backend/test_admin_analytics.py`: 18 passed.
- `tools/verify.ps1 -Mode Quick` passed compilation, generated-map checks,
  backend ownership preflight and runtime-listener checks, then stopped at the
  expected feature-worktree boundary because no active release manifest exists
  there; no release or runtime mutation was attempted.
- `git diff --check`: passed; only the repository's existing Windows line-ending
  notice was reported.
- The diff contains only this contract and the test fixture. Product source,
  schemas, migrations, runtime and production data are unchanged.
