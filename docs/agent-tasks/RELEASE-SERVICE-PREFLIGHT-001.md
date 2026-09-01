---
status: ready-for-review
canonical: false
record_role: task-contract
package: RELEASE-SERVICE-PREFLIGHT-001
domain: production-release
riskClass: high-assurance
base_sha: c84171969d6d0265cb1691674a92ae55fb10a057
branch: codex/release-service-preflight-20260901
created: 2026-09-01
---

# RELEASE-SERVICE-PREFLIGHT-001 — verify installed backend service ownership

## Goal and before/after

Make the read-only backend preflight accept the healthy installed Windows-service
topology only when the listener process chain agrees with the running
`IZOBackend` service and its WinSW XML contract. Before: an elevated Full
verification can inspect the process chain and rejects the release virtual
environment because it differs from the canonical checkout virtual environment.
After: the same visible chain is classified as an installed service only after
service PID, XML executable, working directory, immutable release SHA and
Uvicorn arguments agree.

## Non-goals

- No service restart, release promotion, updater execution or production write.
- No database, media, secrets, providers, public network or VPS changes.
- No general relaxation of Python/process ownership checks.
- No production-runbook claim until the implementation and real preflight have
  passed.

## Declared files

- `docs/agent-tasks/RELEASE-SERVICE-PREFLIGHT-001.md`
- `docs/production-release-runbook.md`
- `tools/backend-service-ownership.ps1`
- `tools/restart-backend.ps1`
- `tools/test_backend_service_ownership.py`
- `tools/test_restart_backend_script.py`

The package follows the completed promotion-preflight work already merged in
`c841719`; the related historical worktrees are clean and do not contain active
overlapping changes. The production runbook was added after the focused tests,
Quick gate and real elevated preflight succeeded so that it records observed
behavior rather than an untested procedure.

## Acceptance and evidence

- A visible installed chain passes only when listener -> configured release
  Python -> running `IZOBackend` service ownership is exact.
- Wrong service PID, executable, release SHA, working directory or arguments
  fail closed.
- Existing project-venv ownership and opaque non-administrator service fallback
  remain unchanged.
- `PreflightOnly` returns before every stop/restart operation.
- Focused behavioral tests pass before a real read-only preflight is attempted.
- No production state changes during package verification.

## Rollback boundary

Revert the single source/test commit. The package does not alter installed
runtime files or the active production release.

## Verification evidence

- Focused behavioral tests: `18 passed`, including exact ownership acceptance
  and rejection of wrong service PID, launcher executable, launcher arguments,
  release SHA, installed release root, service base Python and registered WinSW
  executable location.
- `tools/verify.ps1 -Mode Quick`: `99 passed`, backend/Caddy live checks green,
  `VERIFY_OK`, source stable.
- Real elevated `restart-backend.ps1 -PreflightOnly`:
  `ownership=installed-windows-service`, launcher PID owned by `IZOBackend`,
  `proxyHeadersDisabled=True`, exit code `0`.
- Automated review required the installed release root and service base Python
  to be pinned explicitly. Both findings were fixed with fail-closed behavioral
  tests. A second UAC launch was cancelled before the elevated process started;
  it made no runtime change and is not recorded as a successful re-verification.
- Follow-up review required the registered WinSW executable to match the exact
  installed runtime path; this finding is also fixed with a fail-closed test.
- The elevated check returned before every stop/restart operation. Installed
  services, release identity, data and network state were not changed.
