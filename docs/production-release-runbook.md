# IZO_ASA production release runbook

This is the mandatory release contract for the installed production site on
this Windows computer. It applies to every human or automated agent. Its purpose
is to prevent a verified change from being integrated through the wrong runtime,
against live data, or concurrently with another agent or watchdog.

## 1. Fixed topology

- Canonical Git integration source: `E:\IZO_ASA_WORKSPACE`.
- Installed runtime, configuration, services, health state and releases:
  `C:\IZO_ASA`.
- Public route: the existing FRP path to `izo.alikinas.ru` terminates at the
  local Caddy listener. AdGuard VPN and FRP are dependencies, not release tools.
- Production services are `IZOBackend` and `IZOCaddy`; their installed XML and
  executables are authoritative for live paths.

If all of these files exist, use only the installed updater/promoter workflow:

```text
C:\IZO_ASA\runtime\services\backend\IZOBackend.xml
C:\IZO_ASA\ops\scripts\check-project-update.ps1
C:\IZO_ASA\runtime\promote-project-release.ps1
```

`start-public.bat`, `tools/publish-frontend-release.ps1` and
`tools/restart-backend.ps1` belong to the repository-local bootstrap/manual
topology. They are not production promotion commands on this server.

## 2. Release states

Report these states separately:

- `CODE COMPLETE`: the bounded change and its tests are complete.
- `PUSHED`: the exact clean commit exists on `origin/main`.
- `CANDIDATE PREPARED`: the updater created an immutable candidate for that SHA.
- `DEPLOYED`: installed service and frontend configuration point to it.
- `VERIFIED`: local and public acceptance checks prove that exact release.
- `OPERATIONALLY VERIFIED`: a real provider or user flow produced redacted
  evidence.

Never describe a commit as deployed because tests passed or a public URL returned
HTTP 200.

## 3. Required preflight

Before changing or promoting anything:

1. Read repository `AGENTS.md` and this runbook.
2. Record the canonical worktree status, `HEAD`, `origin/main` and worktree list.
3. Preserve unrelated dirty files. Stage only package-owned paths; never reset a
   worktree to make a release clean.
4. Check for another verifier, updater, promoter, publisher or service switch.
   There is one release owner.
5. Resolve the active backend SHA, release ID, database path and Caddy root from
   installed configuration and `/api/version`; do not infer them from the Git
   checkout.
6. Confirm the runtime health check recognizes
   `C:\IZO_ASA\runtime\project-release-maintenance.flag`. Back it up before any
   change. The promoter must fail closed if this contract is absent.
7. Do not modify, disable or bypass AdGuard VPN, FRP, DNS or the VPS during an
   application release.

## 4. Build and candidate preparation

1. Complete targeted tests and the appropriate Quick gate.
2. For a release candidate, obtain one clean Full verification receipt bound to
   the exact commit.
3. Commit only the bounded package, inspect the staged diff for secrets, and
   push it to `origin/main`.
4. Require clean canonical `main`, `HEAD == origin/main`, and successful CI for
   the same SHA.
5. Ask the installed updater to prepare the candidate:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File C:\IZO_ASA\ops\scripts\check-project-update.ps1 -ForcePrepare
```

6. Read `C:\IZO_ASA\health\update-current.json`. Continue only when it reports
   `PROMOTION_PENDING`, the exact 40-character SHA, and a candidate path below
   `C:\IZO_ASA\releases\<sha>`.

Do not recreate or edit a pending marker by intuition. A missing or inconsistent
marker is a failed gate that must be explained from updater evidence.

## 5. Promotion safety contract

The tracked source is `ops/release/promote-project-release.ps1`; the installed
copy is `C:\IZO_ASA\runtime\promote-project-release.ps1`. Install a changed
promoter only with `ops/release/install-project-promoter.ps1`, an exact clean
commit, a rollback copy and its installation receipt.

During promotion the promoter must:

1. Acquire the global single-owner mutex.
2. Validate marker SHA, candidate path, clean candidate checkout and immutable
   frontend identity before stopping anything.
3. Verify the installed health check honors the maintenance flag.
4. Create `project-release-maintenance.flag` before the mutable window. The
   watchdog may observe services but must not start `IZOBackend` or `IZOCaddy`
   while this flag exists.
5. Create a consistent SQLite hot backup while the old backend remains online,
   and copy service/Caddy configuration into a timestamped rollback directory.
6. Stop services, wait for stopped state and closed loopback ports, switch exact
   paths and identities, then start and verify the services.
7. On failure, restore the prior code/configuration and leave the additive live
   database in place. Database restoration is a separate rehearsed operator
   action, never an automatic file copy.
8. In outer cleanup, attempt to leave both services running, remove the
   maintenance flag and release the mutex.

Run the installed promoter only after every preceding gate passes:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File C:\IZO_ASA\runtime\promote-project-release.ps1
```

## 6. Acceptance after promotion

Require `promotion-current.json` stage `complete` and
`update-current.json` status `INSTALLED`, both bound to the expected SHA/release.
Then verify:

- `IZOBackend` and `IZOCaddy` are running and own only the expected loopback
  listeners;
- local `/`, `/feed`, `/gallery`, `/api/health` and `/api/version`;
- public `https://izo.alikinas.ru/`, `/feed`, `/gallery`, `/api/health` and
  `/api/version`;
- frontend release marker, backend commit and frontend build all match;
- bounded backend, Caddy, updater and promotion logs contain no new fatal error;
- FRP remains connected and AdGuard VPN remains unchanged;
- UI changes have desktop and mobile browser evidence for the actual public
  route.

Synchronize repository-local release metadata with the verified installed
release only when the repository tooling requires it; never let stale local
metadata become false evidence about production.

## 7. Failure and rollback rule

Stop after one controlled failed promotion. Read the promotion status, updater
status, rollback directory, service configuration and bounded logs. Do not loop,
restart arbitrary processes or switch to the bootstrap publisher.

If automatic rollback reports success, verify the previous exact release locally
and publicly. If rollback fails, preserve all evidence and escalate as an
incident; do not restore SQLite or alter networking without a separate approved
recovery procedure.

## 8. Required release record

Every release report must include:

- package commit and `origin/main` SHA;
- verification receipt and CI result;
- candidate path and release ID;
- pre-release SHA/release and rollback directory;
- promotion/update final status;
- local/public route results and release identities;
- service/listener and bounded-log result;
- explicit statements that unrelated WIP was preserved and AdGuard VPN/FRP were
  not changed;
- exact remaining blockers, if any.
