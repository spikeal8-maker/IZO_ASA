---
status: ready-for-review
canonical: false
record_role: task-contract
package: RELEASE-PROMOTION-PREFLIGHT-001
domain: production-release
riskClass: high-assurance
base_sha: 486c06cc5e0cf1cac7f41a04e6680d30c5048fbe
branch: codex/release-promotion-preflight-20260831
created: 2026-09-01
---

# RELEASE-PROMOTION-PREFLIGHT-001 — fail closed before Windows service control

## Goal and before/after

Prevent a production promotion from reaching Windows service control when the
operator process is not elevated or the installed promoter is stale. Before:
the 2026-08-31 promotion ran from a medium-integrity, non-administrator process;
WinSW stopped the old backend but returned `-2147467259` with an operation
cancelled message, and the installed promoter was older than the tracked source.
The automatic rollback restored the previous release. After: both conditions
are explicit preflight gates, the promoter independently fails before backup or
service commands, and the runbook gives an exact diagnosis/action matrix.

## Non-goals

- No second promotion attempt, service restart or runtime promoter installation.
- No production DB, media, secrets, providers, FRP, AdGuard, DNS or VPS changes.
- No change to application/chat behavior or release candidate contents.
- No claim that the stale promoter caused the WinSW exit; it is a separate,
  confirmed safety-contract violation.

## Declared files

- `docs/agent-tasks/RELEASE-PROMOTION-PREFLIGHT-001.md`
- `docs/production-release-runbook.md`
- `ops/release/README.md`
- `ops/release/install-project-promoter.ps1`
- `ops/release/promote-project-release.ps1`
- `tools/test_install_project_promoter.py`
- `tools/test_release_resilience_scripts.py`

The discovered source changes are required because documentation alone cannot
prevent a non-elevated or stale installed script from executing service-control
commands. No overlapping active release package was found.

## Acceptance and evidence

- The promoter rejects a non-administrator token before mutex, backup,
  maintenance flag or service commands.
- `install-project-promoter.ps1 -VerifyOnly` proves normalized tracked,
  installed and receipt hashes agree without changing runtime state.
- The promoter compares its installed normalized hash and installation receipt
  with the exact candidate's tracked promoter before the mutable window.
- The runbook requires both gates and maps known failure signatures to one safe
  next action.
- Focused installer and release-resilience tests pass.
- Complete diff, `git diff --check` and secret scan pass.

## Rollback

One source/documentation commit only. Revert the commit to remove the new gates.
The package does not install the promoter or mutate the current production
release.

## Verification receipt

- Current Codex token: medium integrity, `IS_ADMINISTRATOR=False`.
- Failed promotion evidence: WinSW operation cancelled, backend stop exit
  `-2147467259`, followed by successful automatic rollback.
- Installed promoter receipt: commit `f230e6d4727c46c459129aaa91cec70aca93bd35`;
  installed source lacks the maintenance guard added by `05105d3` and differs
  from the exact candidate source.
- Focused tests: `14 passed`, including the documented installer command with
  automatic repository-root resolution.
- `tools/verify.ps1 -Mode Quick`: `98 passed`, live listener/Caddy checks green,
  `VERIFY_OK`, source stable.
- Production services, release identity, DB, media, secrets, providers and
  network were not changed by this package.
