---
status: code-complete
id: RELEASE-RECOVERY-POWERSHELL51-001
risk_class: high-assurance
domain: release-incident-recovery
---

# RELEASE-RECOVERY-POWERSHELL51-001

## Task Contract

```yaml
id: RELEASE-RECOVERY-POWERSHELL51-001
goal: Make the stopped-backend recovery preflight executable by the installed Windows PowerShell 5.1 host after the f2648cec one-shot attempt stopped before verification.
userOutcome: A fresh corrective release attempt can complete its read-only recovery preflight instead of failing while comparing normalized Windows paths.
beforeScenario: The elevated one-shot attempt stopped IZOBackend and then PowerShell 5.1 parsed a chained GetFullPath(...).Equals(...) expression as a nonexistent two-argument GetFullPath overload.
afterScenario: Path equality and containment use explicit PowerShell-5.1-compatible helpers, and the normal PlanOnly test executes those helpers under powershell.exe before any new release attempt.
nonGoals:
  - start or switch production services in this code package
  - edit production SQLite, immutable releases, service XML, network or provider configuration
  - reuse the failed f2648cec wrapper or receipt
  - weaken any stopped-backend recovery evidence
domain: release-incident-recovery
riskClass: high-assurance
declaredFiles:
  - tools/check-stopped-backend-recovery.ps1
  - tools/test_stopped_backend_recovery_script.py
  - docs/production-release-runbook.md
  - docs/agent-tasks/RELEASE-RECOVERY-POWERSHELL51-001.md
allowedPatterns:
  - replace direct instance-method chaining on static GetFullPath results with explicit normalized-path helpers
  - add a PowerShell 5.1 execution regression and incident classification
acceptance:
  - all recovery path comparisons avoid direct GetFullPath(...).Equals/StartsWith chaining
  - each PlanOnly check executes the path-comparison compatibility probe using powershell.exe
  - recovery remains read-only and fail-closed
  - focused tests, recovery verification plan, CI and automated review pass for the exact corrective commit
requiredEvidence:
  - preserved failed result for deploy-f2648cec-20260905-012400-admin.ps1
  - focused recovery tests executed with Windows PowerShell 5.1
  - clean diff and secret scan
  - exact-SHA CI and automated review before merge
  - fresh one-shot Full recovery receipt before any new promotion
targetedTests:
  - backend/.venv/Scripts/python.exe -m pytest -q tools/test_stopped_backend_recovery_script.py
  - powershell.exe PlanOnly for Backend, Listeners and Edge
  - tools/verify.ps1 -Mode Full -StoppedBackendRecovery -PlanOnly with a receipt path
forbiddenOperations:
  - rerun the failed f2648cec wrapper
  - production database restore or mutation
  - manual immutable-release or service-XML edit
  - release promotion before the corrective commit is merged, CI-green and freshly verified
rollbackBoundary: Revert this compatibility commit before generating a fresh recovery receipt; the code package itself performs no live mutation.
```

## Incident evidence

- Failed one-shot result:
  `.runtime/deploy-f2648cec-20260905-012400-result.json`.
- The attempt reached `stopped-backend-recovery-preflight` after reporting
  `FAILED_SERVICE_QUIESCENT state=Stopped port8000=closed stableSeconds=30`.
- No update candidate, promotion attempt, release verification receipt or
  maintenance flag was created by that attempt.
- `IZOBackend` remained registered, automatic and stopped with PID 0; port 8000
  remained closed. `IZOCaddy` remained running.
- The exact failure was a Windows PowerShell 5.1 method-resolution error for
  `GetFullPath` with two arguments. The failed one-shot wrapper must not be
  rerun.

## Local evidence

- Windows PowerShell `5.1.26100.9168` parsed the corrected checker and executed
  `Backend`, `Listeners` and `Edge` `PlanOnly`; each emitted
  `pathComparison=windows-powershell-5.1-compatible` and completed.
- The focused recovery, listener, verifier, receipt and release-resilience
  suites passed: `31 passed`.
- Full stopped-backend recovery `PlanOnly` retained all normal Full gates,
  routed only the three unavailable live checks through recovery, completed,
  and wrote no receipt.
- No production service, database, immutable release, network or provider state
  was changed by this code package.
