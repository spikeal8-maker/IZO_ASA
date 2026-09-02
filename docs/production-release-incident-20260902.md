---
status: verified-historical-evidence
record_role: production-release-incident
incident_started: 2026-09-01
resolved: 2026-09-02T00:08:04+03:00
release_sha: d223c179d5944bc208cace867d5e93bc1341a3aa
---

# Production release incident and recovery — 2026-09-01/02

This record explains the failed attempts and the first sequence that actually
deployed the requested release. It is evidence, not a replacement for
[`production-release-runbook.md`](production-release-runbook.md).

## Impact

The requested change was merged but was not active while the release gates were
failing. The expired-receipt and backend-preflight failures happened before the
mutable promotion window, so they did not switch the installed release or alter
the production database, media, providers or network. The existing site stayed
on its previous release until the successful promotion.

## What failed

### 1. An expired exact-SHA receipt was reused

The first generated administrator wrapper stopped with
`release verification receipt expired`. The same file was then invoked again,
but its embedded evidence could not become fresh by retrying it. The command's
own failure text said not to rerun it; the correct response was to stop, confirm
that no promotion had started, and create one fresh Full receipt for the current
clean `main` SHA.

This was an execution and documentation failure: the receipt validator behaved
correctly, but the operator-facing instructions did not make the one-shot
lifecycle and replacement procedure prominent enough. Repeating the wrapper
spent time without changing any prerequisite.

### 2. The backend preflight rejected a healthy installed service

After fresh evidence was prepared, Full verification stopped at
`backend_preflight` with `unexpected Python process chain`. The older check
expected the repository-local Python topology. Installed production uses WinSW:

```text
IZOBackend WinSW service
  -> immutable release virtual-environment launcher
    -> installed base-Python listener on 127.0.0.1:8000
```

That difference is legitimate only when the entire installed-service contract
agrees. It was unsafe either to ignore the error or to kill/restart processes by
guessing, so deployment correctly remained blocked until the preflight itself
was repaired and tested.

## What was changed

PR [#87](https://github.com/spikeal8-maker/IZO_ASA/pull/87) added
`tools/backend-service-ownership.ps1` and integrated it into the read-only
backend preflight. The new path returns
`ownership=installed-windows-service` only after all of these checks pass:

- exactly one loopback listener and the expected bind/port arguments;
- listener parent is the release launcher and launcher parent is the running
  `IZOBackend` service PID;
- listener is exactly the installed base Python;
- the registered service executable is exactly the installed WinSW executable;
- WinSW XML identity, release virtual-environment executable, working directory
  and launcher arguments match the live processes;
- the immutable release directory is `C:\IZO_ASA\releases\<40-char-sha>` and its
  SHA matches the XML `GIT_COMMIT` value.

The check fails closed on any mismatch and `-PreflightOnly` still returns before
all stop/restart operations. Focused coverage passed `18` tests; the repository
Quick gate passed `99` tests. Automated review found three missing pins — exact
release root, installed base Python and registered WinSW executable — and each
was added with a rejection test before merge.

The fix merged as
`d223c179d5944bc208cace867d5e93bc1341a3aa`. Exact-SHA CI run
[#33546310079](https://github.com/spikeal8-maker/IZO_ASA/actions/runs/33546310079)
completed successfully.

## Sequence that worked

1. Confirm clean canonical `main`, `HEAD == origin/main == d223c179...`, no
   competing release process and an Administrator token.
2. Install/verify the tracked promoter for that exact clean SHA.
3. Run one elevated Full verification. It passed the repaired backend preflight
   and wrote a fresh four-hour exact-SHA receipt.
4. Immediately run the installed updater with `-ForcePrepare`. It created the
   immutable candidate
   `C:\IZO_ASA\releases\d223c179d5944bc208cace867d5e93bc1341a3aa`.
5. After the updater produced the exact pending candidate, run the installed
   promoter once. Do not retry it automatically.
6. Wait for structured result files rather than treating the presence or
   disappearance of the UAC/PowerShell window as success or failure.
7. Require promotion stage `complete`, updater status `INSTALLED`, and exact
   local/public release identity before reporting `DEPLOYED`.

The visible administrator window closed automatically after it wrote the
successful result. That was normal completion, not evidence that the process
failed.

## Verified result

- Administrator deployment result: `ok=true`, `promotion_stage=complete`,
  completed `2026-09-02T00:08:04+03:00`.
- `C:\IZO_ASA\health\promotion-current.json`: `stage=complete`, `ok=true`,
  `NewSha=d223c179...`.
- `C:\IZO_ASA\health\update-current.json`: `Status=INSTALLED`, exact remote SHA
  and exact immutable candidate path.
- `IZOBackend` and `IZOCaddy`: running; the backend service remains registered
  to `C:\IZO_ASA\runtime\services\backend\IZOBackend.exe`.
- Project release maintenance flag: absent after promoter cleanup.
- Local and public `/api/health`: HTTP 200 and ready.
- Local and public `/api/version`: backend commit and release ID resolve to
  `d223c179...`.
- Public `/` and `/chat`: HTTP 200.
- FRP, AdGuard VPN, DNS and VPS configuration were not changed.

This proves `DEPLOYED` and release-level `VERIFIED`. It does not prove
`OPERATIONALLY VERIFIED` for an authenticated chat conversation or a real model
provider call; that requires a separate authorized user-flow check.

## Mandatory response to the same symptoms

| Symptom | Meaning | Next action |
|---|---|---|
| `release verification receipt expired` | No valid Full evidence; promotion has not been authorized by that wrapper | Stop. Do not rerun the file. Confirm clean exact `main`, create a fresh Full receipt and generate a fresh bounded administrator command. |
| `unexpected Python process chain` | Ownership is unproved, not permission to restart or kill Python | Stop before updater/promoter. Require the repaired preflight to return `installed-windows-service`; diagnose every mismatch. |
| Administrator window disappears | Ambiguous by itself | Read the structured result and update/promotion state files. Success requires exact SHA and `complete`; absence of a result is not success. |
| Updater is still consuming CPU | Candidate verification may still be running | Monitor one process and wait. Do not start a second updater, Full verification or promoter. |
| Promotion reports failure or rollback | The new release is not deployed | Do not retry. Verify the previous exact release and follow the runbook's rollback/incident path. |

Never commit raw transcripts, installed XML, environment values or secrets as
incident evidence. Store only redacted facts and stable GitHub references.
