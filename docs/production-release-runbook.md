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
`tools/verify.ps1` may invoke `restart-backend.ps1 -PreflightOnly` as a
read-only release gate; that mode returns before every stop/restart operation.

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
6. Confirm the process that will invoke the promoter is elevated. This is a
   hard gate because WinSW service control cannot be delegated through a
   medium-integrity Codex/terminal process:

```powershell
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'STOP: promotion requires an elevated Windows Administrator process.'
}
```

7. From the exact clean canonical `main`, verify that the normalized tracked
   promoter, installed promoter and installation receipt agree:

```powershell
$expectedCommit = git rev-parse HEAD
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\ops\release\install-project-promoter.ps1 `
  -ExpectedCommit $expectedCommit `
  -VerifyOnly
```

   Continue only after `PROMOTER_VERIFY_OK`. `PROMOTER_VERIFY_FAILED` means the
   installed script is stale or lacks valid provenance. Install it only with
   `install-project-promoter.ps1`, preserve its rollback copy/receipt, and then
   repeat the complete preflight. Do not invoke the stale runtime script.
8. Run the read-only backend preflight from the same elevated process that will
   own the release. When process metadata is visible, continue only after it
   reports `ownership=installed-windows-service`. That classification proves
   the listener/launcher/service PID chain, WinSW XML executable and arguments,
   release virtual environment and immutable release SHA agree. It does not
   restart the service:

```powershell
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass `
  -File .\tools\restart-backend.ps1 `
  -RepoRoot (Get-Location).Path `
  -PythonPath .\backend\.venv\Scripts\python.exe `
  -PreflightOnly
```

9. Confirm the runtime health check recognizes
   `C:\IZO_ASA\runtime\project-release-maintenance.flag`. Back it up before any
   change. The promoter must fail closed if this contract is absent.
10. Do not modify, disable or bypass AdGuard VPN, FRP, DNS or the VPS during an
   application release.

## 4. Build and candidate preparation

1. Complete targeted tests and the appropriate Quick gate on the feature branch.
2. Commit only the bounded package, inspect the staged diff for secrets, open the
   PR and require CI plus automated review before merge.
3. In the canonical checkout, require clean `main`, `HEAD == origin/main`, and
   successful CI for the same SHA. This is `PUSHED`, not `DEPLOYED`.
4. From the elevated release-owner process, obtain one clean Full verification
   receipt bound to that exact SHA:

```powershell
$sha = git rev-parse HEAD
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$receipt = ".runtime\verification\full-$sha-$stamp.json"
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass `
  -File .\tools\verify.ps1 `
  -Mode Full `
  -RepoRoot (Get-Location).Path `
  -PythonPath .\backend\.venv\Scripts\python.exe `
  -RequireStableLiveSource `
  -ReceiptPath $receipt
```

   Continue only after `VERIFY_OK` and `VERIFY_RECEIPT_WRITTEN`. The receipt
   expires four hours after it is written. Validate/use it immediately; never
   reuse an expired receipt or rerun a combined deployment command around it.
   A generated administrator wrapper is a one-shot envelope around its embedded
   evidence. If any gate fails, preserve its complete output and determine
   whether the mutable promotion window began. A fresh attempt requires a new
   preflight and receipt; changing the clock, editing the receipt or invoking
   the same wrapper again cannot make it valid.
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

1. Reject a non-administrator process before acquiring the mutex, creating a
   backup or invoking a service executable.
2. Acquire the global single-owner mutex.
3. Validate marker SHA, candidate path, clean candidate checkout and immutable
   frontend identity before stopping anything.
4. Compare its normalized installed hash and installation receipt with the
   exact candidate's tracked promoter; fail before the mutable window on any
   mismatch.
5. Verify the installed health check honors the maintenance flag.
6. Create `project-release-maintenance.flag` before the mutable window. The
   watchdog may observe services but must not start `IZOBackend` or `IZOCaddy`
   while this flag exists.
7. Create a consistent SQLite hot backup while the old backend remains online,
   and copy service/Caddy configuration into a timestamped rollback directory.
8. Stop services, wait for stopped state and closed loopback ports, switch exact
   paths and identities, then start and verify the services.
9. On failure, restore the prior code/configuration and leave the additive live
   database in place. Database restoration is a separate rehearsed operator
   action, never an automatic file copy.
10. In outer cleanup, attempt to leave both services running, remove the
   maintenance flag and release the mutex.

Run the installed promoter only after every preceding gate passes:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File C:\IZO_ASA\runtime\promote-project-release.ps1
```

## 6. Acceptance after promotion

Before promotion, the updater's successful candidate state is
`PROMOTION_PENDING`. After promotion, require `promotion-current.json` stage
`complete` and `update-current.json` status `INSTALLED`, both bound to the
expected SHA/release. Do not wait for `PROMOTION_PENDING` after a successful
promoter has already advanced the updater state.
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

### Stopped-backend recovery after an additive schema advance

If a single failed promotion reports `rolled_back`, but the restored backend
cannot start because the live additive SQLite schema is newer than the previous
immutable release manifest, do not edit that manifest, the candidate or the
database. Do not rerun the failed candidate.

A subsequent corrective commit may use the bounded stopped-backend recovery
gate only when all of the following are true:

- the corrective exact SHA is clean canonical `main`, is on `origin/main`, and
  has successful exact-SHA CI plus automated review, and differs from the
  recorded failed candidate SHA;
- `promotion-current.json` is `rolled_back`, `update-current.json` is
  `PROMOTION_FAILED`, the installed `IZOBackend` service is stopped and port
  8000 is closed;
- installed XML still identifies the previous immutable release, while its
  manifest does not support the live schema;
- read-only SQLite `quick_check` passes, every applied migration ledger row
  matches the corrective source by version, name and checksum, and the full
  corrective release compatibility range contains that exact live schema;
- the ordinary contract-wide process/listener scan passes with only the
  explicitly stopped installed API listener treated as absent, so no stale
  full-application process owns another port;
- the `IZOCaddy` WinSW service owns the single pinned Caddy loopback listener
  on 5173, serves the previous immutable frontend on static SPA routes, and
  returns the expected 502 for the stopped API;
- the maintenance flag is absent and the installed health check retains its
  maintenance guard.

From the same elevated process that will own recovery, obtain one new Full
receipt with those fail-closed checks replacing only the three unavailable live
backend gates:

The installed recovery host uses Windows PowerShell 5.1. Before opening the
elevated one-shot window, run all three recovery `PlanOnly` checks through
`powershell.exe` and require
`pathComparison=windows-powershell-5.1-compatible`. Do not approve a checker
that calls `.Equals(...)` or `.StartsWith(...)` directly on an unparenthesized
static `GetFullPath(...)` expression: PowerShell 5.1 can bind the instance-call
arguments to `GetFullPath` and fail before the read-only evidence is collected.

```powershell
$sha = git rev-parse HEAD
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$receipt = ".runtime\verification\recovery-full-$sha-$stamp.json"
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass `
  -File .\tools\verify.ps1 `
  -Mode Full `
  -RepoRoot (Get-Location).Path `
  -PythonPath .\backend\.venv\Scripts\python.exe `
  -RequireStableLiveSource `
  -StoppedBackendRecovery `
  -ReceiptPath $receipt
```

The receipt remains a normal exact-SHA Full receipt and all code, build, source
stability and non-backend live gates still run. After it succeeds, prepare a new
candidate and run the installed promoter once for the corrective SHA. This path
does not authorize database restoration, manual service-XML switching or edits
inside an immutable release.

Use these exact classifications; do not collapse them into "deployment failed":

| Evidence | Meaning | Required next action |
|---|---|---|
| Administrator check is `False` or `PROMOTION_PREFLIGHT_FAILED` mentions elevation | The invoking process cannot safely control WinSW services | Do not run the promoter. Open an elevated Administrator process and repeat every preflight gate. |
| Recovery preflight reports that `GetFullPath` has no two-argument overload | The recovery checker is incompatible with Windows PowerShell 5.1; verification did not complete | Preserve the one-shot result, prove whether any mutation began and create a reviewed corrective commit with a fresh wrapper. Never rerun the failed wrapper. |
| Backend preflight reports `unexpected Python process chain` or fails installed-service ownership | Listener ownership, service XML or immutable release identity is inconsistent, or the checkout lacks the ownership repair | Do not run updater/promoter. Diagnose PID chain, `IZOBackend.xml` and exact source; never bypass the ownership gate. |
| Release verification receipt is expired | The four-hour exact-SHA verification window closed before candidate preparation/promotion | Do not reuse the combined command. Confirm clean exact `main`, then run one new Full verification to create a fresh receipt. |
| `PROMOTER_VERIFY_FAILED` or tracked/installed hashes differ | The installed promoter is stale, modified or has no matching receipt | Do not run it. Install the exact clean tracked promoter with the installer, retain its backup/receipt, then repeat preflight. |
| `Backend stop failed with exit code -2147467259` together with WinSW "operation was cancelled" and a non-administrator token | The service command crossed the elevation boundary from an invalid process | Treat it as the one controlled failed promotion. Verify rollback; never retry from the same process. |
| Installed promoter lacks the candidate's maintenance-flag guard | The watchdog can race the service switch even if the health script understands the flag | Stop before promotion and install the exact candidate promoter. Do not disable the watchdog manually. |
| `promotion-current.json` is `rolled_back` | Candidate is not deployed, regardless of HTTP 200 from the restored site | Verify the previous exact release and report `BLOCKED`, not `DEPLOYED`. |

For the 2026-08-31 incident, the non-administrator token and WinSW cancellation
are the confirmed cause of the service-control failure. The stale installed
promoter is a separate confirmed preflight defect and safety risk; available
evidence does not prove it produced that exit code.

The 2026-09-01/02 expired-receipt and installed Python-chain failures, the
fail-closed ownership repair, and the first verified successful deployment are
recorded in
[`production-release-incident-20260902.md`](production-release-incident-20260902.md).
Future agents must use its symptom table as incident evidence while continuing
to follow this runbook as the active procedure.

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
