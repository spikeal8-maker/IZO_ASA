---
status: code-complete
id: RELEASE-RECOVERY-PENDING-STATE-001
risk_class: high-assurance
domain: release-incident-recovery
---

# RELEASE-RECOVERY-PENDING-STATE-001

## Task Contract

```yaml
id: RELEASE-RECOVERY-PENDING-STATE-001
goal: Keep stopped-backend recovery valid when the installed updater safely advances from the historical failure record to an exact corrective PROMOTION_PENDING candidate.
userOutcome: A delayed administrator launch can verify and promote the already CI-green corrective SHA instead of failing because updater state changed normally in the background.
beforeScenario: promotion-current remains rolled_back, but the updater has prepared the clean current 3eee841 candidate and replaced update-current PROMOTION_FAILED with PROMOTION_PENDING, which the recovery checker rejects unconditionally.
afterScenario: Recovery accepts either the historical PROMOTION_FAILED state or a strictly bound PROMOTION_PENDING state for the current source or its canonical ancestor whose update state, pending marker, candidate path, candidate Git identity, active SHA and CI status all agree.
nonGoals:
  - accept arbitrary updater states or stale candidates
  - edit updater/promotion evidence, production SQLite, service XML or immutable releases
  - start or promote production from this code package
  - reuse either failed one-shot wrapper
domain: release-incident-recovery
riskClass: high-assurance
declaredFiles:
  - tools/check-stopped-backend-recovery.ps1
  - tools/test_stopped_backend_recovery_script.py
  - docs/production-release-runbook.md
  - docs/agent-tasks/RELEASE-RECOVERY-PENDING-STATE-001.md
acceptance:
  - PROMOTION_FAILED retains the existing fail-closed identity checks
  - PROMOTION_PENDING is accepted only for the current exact source SHA or its Git ancestor, previous active SHA, success CI, exact release-root candidate, exact pending marker and clean candidate Git checkout at the same SHA and origin
  - any other updater status or mismatch fails before Full verification or promotion
  - recovery remains read-only
  - focused tests, CI and automated review pass for the exact corrective commit
requiredEvidence:
  - preserved deploy-3eee841e-20260905-031406 result showing failure before receipt/candidate-preparation/promotion
  - observed PROMOTION_PENDING state and pending marker created at 2026-09-05T05:41:52+03:00 for exact 3eee841
  - candidate Git HEAD/origin/clean evidence
  - focused tests, clean diff, exact-SHA CI and automated review
  - a fresh one-shot recovery wrapper after merge and post-merge CI
forbiddenOperations:
  - rerun deploy-3eee841e-20260905-031406-admin.ps1
  - rewrite update-current.json, promotion-current.json or pending-release-promotion.json
  - production database restore or mutation
  - manual service XML or immutable-release edit
rollbackBoundary: Revert this checker change before generating a fresh receipt; this code package performs no live mutation.
```

## Incident evidence

- The second one-shot attempt stopped at `stopped-backend-recovery-preflight`;
  it wrote no Full receipt and no manual promotion-attempt record.
- `update-current.json` was written before the operator attempt and reports
  `PROMOTION_PENDING`, current SHA `3eee841edb473fba39d41a041dffd9b677a3a9d4`,
  active SHA `d223c179d5944bc208cace867d5e93bc1341a3aa`, successful CI and the exact
  candidate path.
- `pending-release-promotion.json` names the same SHA and candidate. The
  candidate checkout has that exact HEAD, the canonical origin and zero tracked
  changes.
- `promotion-current.json` remains the completed rollback evidence. Backend is
  stopped with port 8000 closed; Caddy remains running on loopback 5173.

## Local evidence

- Windows PowerShell `5.1.26100.9168` parsed the checker and completed
  `Backend`, `Listeners` and `Edge` `PlanOnly` with the explicit
  `PROMOTION_FAILED` or clean canonical `PROMOTION_PENDING` route.
- Focused recovery, listener, verifier, receipt, resilience and documentation
  suites passed: `40 passed`.
- Backend, architecture and frontend generated maps passed their checks without
  a generated diff.
- The package performed no production write, service start, promotion or state
  file rewrite.
