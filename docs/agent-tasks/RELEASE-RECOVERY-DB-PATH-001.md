---
status: active
id: RELEASE-RECOVERY-DB-PATH-001
risk_class: release-ops
domain: release-incident-recovery
---

# RELEASE-RECOVERY-DB-PATH-001

```yaml
id: RELEASE-RECOVERY-DB-PATH-001
goal: Make installed SQLite URL conversion executable in Windows PowerShell 5.1 before another recovery attempt.
beforeScenario: The 599bc470 wrapper successfully held the service Disabled and stopped, but the recovery check failed at line 230; PowerShell parsed the inline -replace comma as a second GetFullPath argument.
afterScenario: A pure URL conversion helper normalizes the path before calling single-argument GetFullPath. PlanOnly exercises the helper; executable tests check URL conversion and every GetFullPath call's parsed arity.
nonGoals: [change database contents or schema, alter service recovery, bypass live gates, retry consumed wrappers, change network or providers]
domain: release-incident-recovery
riskClass: release-ops
declaredFiles:
  - tools/check-stopped-backend-recovery.ps1
  - tools/test_stopped_backend_recovery_script.py
  - docs/production-release-runbook.md
  - docs/agent-tasks/RELEASE-RECOVERY-DB-PATH-001.md
  - .runtime/* (ignored diagnostic and fresh one-shot release evidence)
acceptance:
  - reproduce the exact production expression failure with a synthetic URL before editing source
  - execute conversion and parsed-arity checks in Windows PowerShell 5.1 without touching any database or service
  - retain approved-root, database-integrity, schema, owner, exact-SHA and one-shot gates
  - require CI and review before merge, then a fresh exact-main Full and real release acceptance
rollbackBoundary: Path conversion is pure. Existing service guard restores original delayed Automatic startup and its own maintenance flag on failure; preserve failed evidence.
```

Canonical `main` is clean `599bc470133675617c02193814de2ec88022d658`.
The failed result records `startup_restored=true`, no receipt or candidate
preparation and no promotion handoff. Both repository operation locks are free.
The installed backend still identifies the old d223c179 release and live schema
7 remains unchanged. The nightly updater now holds a clean pending 599bc470
candidate. Live database, media, secrets and providers are not test fixtures.

The read-only `.runtime/probe-recovery-db-path-20260906.ps1` reproduces the exact
line-230 error using a synthetic URL. The PowerShell AST reports two arguments
for that call and one for the other eight GetFullPath calls. It opens no database
and changes no service. This is a missed executable path in the prior PlanOnly
coverage, not evidence of database corruption.

## Local evidence

- Before the source edit, the new executable AST regression failed with
  `GetFullPath at line 230 has 2 parsed arguments` (one failed test).
- After the edit, all seven focused recovery tests passed in Windows
  PowerShell 5.1. Synthetic paths cover forward/backward separators, spaces,
  Unicode and parent normalization; unsupported URL schemes are rejected.
- PlanOnly now calls the production conversion helper. The conversion test
  rejects service/file-read/database probes, and the AST test checks all nine
  GetFullPath calls, preventing the previously unexercised argument ambiguity.
- These results prove code compatibility, not deployment. The failed 599bc470
  envelope remains consumed and preserved; production still needs a fresh
  reviewed exact-main release and its local/public acceptance evidence.
- Related recovery, repository-lock, verifier and context checks: 32 passed;
  deterministic architecture inventory check passed. Quick stopped at the
  existing absent live API listener (`found 0` on port 8000), before code gates;
  it is not reported as green. The authorized stopped-backend Full remains the
  required release gate, alongside isolated CI on the reviewed exact source.
