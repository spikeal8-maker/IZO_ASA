---
status: active
id: RELEASE-RECOVERY-SERVICE-GUARD-001
risk_class: release-ops
domain: release-incident-recovery
---

# RELEASE-RECOVERY-SERVICE-GUARD-001

```yaml
id: RELEASE-RECOVERY-SERVICE-GUARD-001
goal: Hold the failed installed backend stopped across recovery verification and candidate preparation, then restore automatic startup for promotion.
userOutcome: The authorized chat deployment can progress without Windows restarting the failed backend between release gates.
beforeScenario: The dde6630b one-shot wrapper observed 30 seconds stopped, then its next check found a service PID. SCM event 7031 confirms queued automatic restarts with delays of 10, 30 and 120 seconds.
afterScenario: The release owner creates an owned maintenance record, temporarily disables startup of the identified IZOBackend service, stops it once, verifies stopped/PID-zero/port-closed state, holds that state through Full and candidate preparation, then restores Automatic under maintenance before invoking the installed promoter once. Cleanup restores startup and removes only its own maintenance record.
nonGoals: [change recovery actions or service XML, change the watchdog or network, restore or edit SQLite, rerun a failed wrapper]
domain: release-incident-recovery
riskClass: release-ops
declaredFiles:
  - ops/release/recovery-service-guard.ps1
  - tools/check-stopped-backend-recovery.ps1
  - tools/test_recovery_service_guard.py
  - tools/test_stopped_backend_recovery_script.py
  - docs/production-release-runbook.md
  - docs/agent-tasks/RELEASE-RECOVERY-SERVICE-GUARD-001.md
  - docs/generated/architecture-inventory.*
  - .runtime/deploy-*-admin.ps1 (fresh ignored operational envelope only)
acceptance:
  - no service change without matching live production-release lock owner and installed executable
  - recovery preflight requires owned maintenance plus Disabled startup, Stopped state, PID zero and closed API port
  - original Automatic startup including DelayedAutoStart is journaled before mutation and restored on failure and before promotion
  - queued SCM restarts cannot fire throughout Full; restoration waits at least the configured maximum delay
  - failure, stale owner, foreign flag, registration mismatch and delayed restart cases execute under PowerShell 5.1 with fake services and temporary state
requiredEvidence: [focused runtime tests repeated five times, generated checks, CI, automated review, fresh Full receipt, exact local/public release acceptance]
forbiddenOperations: [production test fixtures, copied live SQLite, manual XML switching, editing old wrappers, disabling watchdog tasks, changing recovery actions]
rollbackBoundary: The operational guard restores the original service startup and only its own maintenance flag in finally. Interruption evidence persists outside Git for explicit recovery; no automatic stale-lease takeover.
```

The existing full attempt result reports `receipt_written=false`, no candidate
preparation by the wrapper, and no promotion. Its only live mutation was stopping
the failed backend. The source checkout is clean canonical `dde6630b`; installed
XML still identifies `d223c179`. Live SQLite resides under
`F:\IZO_ASA_StandbyData\active`; it, service secrets and media are excluded from
tests. No overlapping release process or release lock was found.

## Local evidence, 2026-09-05

- Windows PowerShell 5.1 executed the real guard against fake service/SCM/lock
  adapters and temporary maintenance/journal paths: 13 lifecycle cases,
  including delayed Automatic restoration, failed stop/restore, late restart,
  stale/foreign ownership and promoter cleanup, repeated five times.
- Recovery checker, operation-lock, verifier and context-document contracts:
  30 tests passed. Architecture inventory check passed without generated drift.
- `verify.ps1 -Mode Quick` stopped at `backend_preflight`: no listener on 8000.
  This is the existing production incident, not a successful Quick gate.
- No service configuration, live data or runtime state was changed by these
  local tests. CI/review and fresh elevated Full/release acceptance remain
  separate gates; this record does not claim deployment success.
