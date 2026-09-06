---
status: active
id: RELEASE-RECOVERY-PYTHON-PROBE-001
risk_class: release-ops
domain: release-incident-recovery
---

# RELEASE-RECOVERY-PYTHON-PROBE-001

```yaml
id: RELEASE-RECOVERY-PYTHON-PROBE-001
goal: Execute the complete read-only database probe through Windows PowerShell 5.1 without native argument quote loss.
userOutcome: The next recovery attempt can prove database evidence instead of failing while starting its Python probe.
beforeScenario: dd7e6507 passed both CI runs, PlanOnly and the real service hold; native Python -c then rejected the embedded code at line 8 before opening SQLite.
afterScenario: Python receives the same probe source over stdin; executable regression tests cover the entire production probe block against temporary SQLite fixtures, including negative cases and read-only evidence.
nonGoals: [change production DB or schema, change service recovery, bypass live gates, rerun consumed wrappers, change network or providers]
domain: release-incident-recovery
riskClass: release-ops
declaredFiles:
  - tools/check-stopped-backend-recovery.ps1
  - tools/test_stopped_backend_recovery_script.py
  - docs/production-release-runbook.md
  - docs/agent-tasks/RELEASE-RECOVERY-PYTHON-PROBE-001.md
  - .runtime/* (ignored fresh release evidence)
acceptance:
  - reproduce the exact native Python failure before source editing
  - execute the complete probe block through powershell.exe using temporary DB and actual migration definitions
  - cover valid ledger, mismatched ledger and corrupt database without touching production
  - preserve environment/error preferences and prove fixture bytes unchanged
  - require reviewed CI, clean exact-main Full and a new one-shot envelope before promotion
rollbackBoundary: No production data change. Preserve failed evidence; existing guard restores delayed Automatic startup and owned maintenance on failure.
```

Canonical main/origin are clean dd7e65073fb7180f0ecb4b82e32743265609a580.
The consumed dd7e6507 envelope records startup_restored=true, no Full receipt,
no candidate preparation and no promotion handoff. Repository operation locks
are free. This package follows the newly observed native-process boundary,
not another change to the repaired path conversion or service lifecycle.

Live DB/media/secrets/providers remain excluded from tests. Only temporary
SQLite files with synthetic ledger rows are used as fixtures.

## Executable evidence

- Before editing the checker, the valid temporary database case reproduced the
  real error exactly: `File "<string>", line 8`.
- After switching only code transport to stdin, all 11 recovery tests passed.
  Four new cases execute the unchanged Python probe, environment restoration
  and ledger gate from the actual production PowerShell block, not a test copy.
- Valid, mismatched, corrupt and missing fixtures retain their original bytes
  or absence. Error action preference and diagnostic environment are restored
  in all four cases; negative cases now expose the complete native diagnostic.
- This is code evidence only. Another deployment still requires reviewed CI,
  exact canonical main and a fresh one-shot Full receipt.
- Related recovery/lock/verifier/context suite: 36 passed; deterministic
  architecture inventory passed. Quick stops at the existing absent port-8000
  listener, so it is not reported green; stopped-backend Full remains required.
