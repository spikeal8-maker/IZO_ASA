---
status: code-complete
id: RELEASE-STOPPED-BACKEND-RECOVERY-001
risk_class: high-assurance
domain: release-incident-recovery
---

# RELEASE-STOPPED-BACKEND-RECOVERY-001

## Task Contract

```yaml
id: RELEASE-STOPPED-BACKEND-RECOVERY-001
goal: Permit an exact-SHA Full recovery receipt when a verified additive-schema rollback leaves the previous installed backend unable to start.
userOutcome: A corrective release can restore the production API without editing the live database, immutable manifests or service configuration by hand.
beforeScenario: The previous backend is stopped after rolled_back because schema 7 exceeds its immutable manifest max_version 6, so ordinary live Full verification cannot start.
afterScenario: Full verification substitutes three unavailable live gates with fail-closed stopped-service, read-only database and static-edge evidence, then the normal updater/promoter workflow installs a new corrective SHA.
nonGoals:
  - restore, downgrade or mutate the live database
  - edit an immutable release or bypass release identity
  - retry the failed candidate
  - change FRP, AdGuard, DNS, VPS, providers or secrets
domain: release-incident-recovery
riskClass: high-assurance
declaredFiles:
  - tools/check-stopped-backend-recovery.ps1
  - tools/verify.ps1
  - tools/test_stopped_backend_recovery_script.py
  - docs/production-release-runbook.md
  - docs/agent-tasks/RELEASE-STOPPED-BACKEND-RECOVERY-001.md
  - docs/generated/architecture-inventory.json
  - docs/generated/architecture-inventory.md
acceptance:
  - recovery mode is Full-only, receipt-only and stable-source-only
  - no recovery check starts/stops services or writes production state
  - rolled_back, PROMOTION_FAILED, stopped WinSW, closed API port, read-only SQLite integrity, exact migration ledger, schema ranges and WinSW-owned Caddy fallback are all proved
  - ordinary Full behavior remains unchanged
requiredEvidence:
  - focused tool tests and generated-map check
  - CI and automated review for the exact corrective commit
  - fresh elevated Full recovery receipt
forbiddenOperations:
  - database restore or direct mutation
  - immutable manifest/candidate edits
  - manual service XML switching
  - rerunning the failed promotion
rollbackBoundary: Revert the recovery-gate commit; it performs no live mutation by itself.
```

## Local evidence

- PowerShell parser: recovery checker and verifier passed without errors.
- Recovery `PlanOnly`: `Backend`, `Listeners` and `Edge` each completed.
- Verifier `PlanOnly`: Full recovery routed only the three unavailable live
  gates through the bounded checker and retained every remaining Full gate.
- Focused tests: `26 passed` for the recovery checker, verifier, receipt and
  release-resilience contracts.
- Generated architecture, backend and frontend maps: checks passed; no
  generated diff was required.
- Ordinary Quick verification reached its unchanged live backend preflight and
  stopped because the incident state intentionally has zero listeners on port
  8000. It did not report a code-test failure and did not mutate production.
