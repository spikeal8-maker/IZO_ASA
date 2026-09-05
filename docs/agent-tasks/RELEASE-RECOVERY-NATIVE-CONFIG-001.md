---
status: active
id: RELEASE-RECOVERY-NATIVE-CONFIG-001
risk_class: release-ops
domain: release-incident-recovery
---

# RELEASE-RECOVERY-NATIVE-CONFIG-001

```yaml
id: RELEASE-RECOVERY-NATIVE-CONFIG-001
goal: Read SCM failure delays without parsing localized or console-dependent native command output.
beforeScenario: The elevated 72a446e9 wrapper failed to parse sc.exe qfailure output before any service mutation; the same query appeared usable in the non-interactive development shell.
afterScenario: QueryServiceConfig2 reads structured delay values with read-only service access in both environments; the existing owned guard uses those values without changing its stop, restore or handoff guarantees.
nonGoals: [change service recovery settings, change networks or providers, bypass recovery gates, retry a consumed wrapper]
domain: release-incident-recovery
riskClass: release-ops
declaredFiles:
  - ops/release/service-recovery-config.ps1
  - ops/release/recovery-service-guard.ps1
  - tools/test_recovery_service_guard.py
  - tools/test_service_recovery_config.py
  - docs/production-release-runbook.md
  - docs/agent-tasks/RELEASE-RECOVERY-NATIVE-CONFIG-001.md
  - .runtime/* (ignored read-only probe and fresh one-shot envelope evidence)
acceptance:
  - read structured recovery delays without sc.exe text parsing or any configuration mutation
  - read succeeds in real elevated Windows PowerShell 5.1 before requesting another deployment
  - original guard lifecycle tests still pass five times using temporary state and fake services
  - exact-head CI and review precede merge; fresh exact-main Full precedes promotion
rollbackBoundary: No service change in config reader. Existing guard restores startup and maintenance on failure. Preserve all failed wrappers and results.
```

Canonical main is clean `72a446e976bdd074b01f01760acf01ec160e491d`.
PR 95 and main CI passed (runs 33952524312 and 33953092803). The one-shot result
`deploy-72a446e9-20260905-104002-result.json` records `mutation_started=false`,
`receipt_written=false`, and no candidate preparation. Its release lock is
released; installed startup is still Automatic with delayed auto-start, and no
maintenance flag remains. Live database, media, secrets and providers remain
excluded from tests. This is a bounded correction to the SCM-reading adapter;
there is no overlapping code or active release/Full owner.

## Evidence before another deployment

The read-only elevated probe `.runtime/probe-native-recovery-20260905-1054.json`
reports PowerShell `5.1.26100.9168`, UI culture `ru-RU`, native delays
`[10000, 30000, 120000]`, 10 captured legacy console lines, zero English-pattern
matches, and `service_changed=false`. This validates the replacement adapter in
the environment where the previous attempt failed, before any new deployment.

The reader follows the documented
[QueryServiceConfig2 contract](https://learn.microsoft.com/en-us/windows/win32/api/winsvc/nf-winsvc-queryserviceconfig2w):
`SERVICE_QUERY_CONFIG` access, info level 2, sized buffer, and structured
`SERVICE_FAILURE_ACTIONS`/`SC_ACTION` data. It requests no service mutation access.

Local gates: native ABI/handle-error tests and existing guard lifecycle tests
pass with temporary/fake application state; the native ABI test queries only the
standard OS EventLog service. The 30 recovery/lock/verifier/context contracts and
architecture inventory check pass. Quick remains blocked by the existing absent
API listener; no successful Quick or production deployment is claimed.
