# Yandex.Disk quarantine manifest - 2026-07-26

## Scope

- Historical path: `E:\Yandex.Disk\IZO_ASA`
- Canonical clean clone: `E:\IZO_ASA_WORKSPACE`
- Read-only audit time: `2026-07-26T16:16:44+03:00`
- Historical branch: `codex/consolidate-remote-work-001`
- Historical HEAD: `6b6c489127d1fb2c013f4f572468842725e78d5e`
- GitHub `origin/main` at clone time:
  `1ef0ecce3cf58f6c44a0152f2c8bf6fb4ddf82be`

## Locally verified state

- The historical worktree was clean during the read-only audit.
- The local Yandex.Disk client process count was zero.
- The historical copy contained `backend\media` and `.runtime`.
- No local `backend\onenode.sqlite3`, secret file or DPAPI material was found
  by the targeted audit.
- The following Git marker files were not present locally:
  `.git\CHERRY_PICK_HEAD`, `.git\AUTO_MERGE`, `.git\MERGE_MSG`, and the
  reported conflicting `FETCH_HEAD` copy.
- No file in the historical copy was deleted, renamed, moved or repaired.

## Reported remote state, not locally verified

- The older `D2-R2-X` computer or synchronized cloud state was reported to
  contain cherry-pick and merge marker files.
- The reported `CHERRY_PICK_HEAD` value was
  `f5f16b519543ca17f57bb760f4e87b68ad59618f`.
- Yandex.Disk reported an empty-placeholder upload error for a conflicting
  `FETCH_HEAD` copy.
- It is not confirmed that the Yandex.Disk client is stopped on the older
  computer.

## Quarantine decision

- Cleanup is blocked until both Yandex.Disk clients are confirmed stopped and
  the owner authorizes a separate cleanup package.
- The historical path must not be used for Git operations, tests, deployment
  or application runtime.
- GitHub is the source of truth for code recovery.
- Production was not deployed, restarted or modified by this consolidation.
