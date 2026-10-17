# Yandex.Disk live Git synchronization incident — 2026-07-26

## Status

- Incident: live `.git` metadata was synchronized bidirectionally through
  Yandex.Disk between this computer and the older `D2-R2-X` computer.
- Recovery source: GitHub repository `spikeal8-maker/IZO_ASA`.
- Recovery branch: `codex/consolidate-remote-work-001`.
- Verified recovery head at audit time:
  `6b6c489127d1fb2c013f4f572468842725e78d5e`.
- New canonical Git workspace: `E:\IZO_ASA_WORKSPACE`.
- Historical cloud copy: `E:\Yandex.Disk\IZO_ASA`.
- Cleanup: blocked pending confirmation that Yandex.Disk is stopped on both
  computers and a separately authorized cleanup package.

## Observed and reported evidence

The older computer mounted the cloud copy at `D:\Yandex.Disk\IZO_ASA`.
Yandex.Disk repeatedly attempted to upload:

`D:\Yandex.Disk\IZO_ASA\.git\FETCH_HEAD (копия с компьютера D2-R2-X)`

The client reported:

`trying to upload without a file source`

`is empty placeholder, attempt 5`

The cloud/older-computer state was reported to contain:

- `.git\CHERRY_PICK_HEAD` pointing to
  `f5f16b519543ca17f57bb760f4e87b68ad59618f`;
- `.git\AUTO_MERGE`;
- `.git\MERGE_MSG`;
- conflicts in backend maps, OpenRouter catalog, `backend/main.py`, current
  status, generated architecture inventory and `frontend/src/AdminApp.tsx`.

At the read-only audit on this computer at
`2026-07-26T16:16:44+03:00`, the local historical copy was clean at
`6b6c489127d1fb2c013f4f572468842725e78d5e` and no longer contained those four
marker files. This local observation does not prove the cloud copy or the older
computer is clean; the old client state remains unverified.

## Recovery decision

GitHub history is the source of truth. The synchronized historical `.git`
directory must not be repaired with `cherry-pick --continue`,
`cherry-pick --abort`, manual marker deletion, reset or clean operations.

The clean clone at `E:\IZO_ASA_WORKSPACE` was created directly from GitHub.
It contains no production database, WAL/SHM, media, secrets, DPAPI material or
old runtime manifests. PR #26 contains four bounded commits on current main:

1. `50874bfc06fee28a517968fd4e9aeb286d661442`
2. `90df787d3eb0fd6a99ba9493d2bcc6a2b3503939`
3. `5e42effe3b2efd15c650cddcdf1bc8d26e151adb`
4. `6b6c489127d1fb2c013f4f572468842725e78d5e`

## Prevention rules

- Use GitHub branches and pull requests to move code between computers.
- Keep the canonical live `.git` directory outside every bidirectional
  synchronization root.
- Store backup data as immutable, versioned snapshots with manifests and
  verification receipts.
- Back up SQLite through the SQLite Backup API and repository backup tools.
  Never copy an open SQLite database through ordinary file synchronization.
- Do not synchronize runtime manifests, secrets, DPAPI blobs or active media
  working directories as source code.
- Do not use the historical Yandex copy for application startup, Git commands,
  testing, deployment or recovery.

## Deferred cleanup

No files were deleted, renamed or moved. The historical Yandex copy and all old
Git branches are preserved. Removing conflict copies or repairing its `.git`
metadata requires a new owner-authorized task after both Yandex clients are
confirmed stopped and a complete backup manifest has been accepted.
