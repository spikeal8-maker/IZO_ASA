# Gallery storage cleanup - 2026-07-19

## Scope

This maintenance pass covered only the private gallery, uploaded source library,
gallery media indexes, video storage checks, and the gallery-to-generator handoff.
Public feed and unrelated application data were not cleanup targets.

## Recovery points

- Verified external snapshot: `I:\IZO_ASA_Backups\20260718T214204.979655Z`.
- Database copy before terminal-job compaction:
  `D:\Google Drive\My progact\IZO_ASA_Gallery_Quarantine\20260719T0042\database\onenode-before-terminal-compaction.sqlite3`.
- Both the live database and the compaction copy passed `PRAGMA integrity_check`.
- Quarantined files remain outside the repository and can be restored by their
  SHA-256 manifests. No quarantine batch was permanently deleted.

## Applied maintenance

### Legacy PNG originals

- 69 active PNG originals were decoded, verified, and converted to WebP.
- Source size: 128,557,887 bytes.
- Verified WebP size: 13,330,702 bytes.
- Reclaimable source size: 115,227,185 bytes (109.89 MB).
- Every target preserves the original dimensions, is smaller than its source,
  passes Pillow verify/load, and is now referenced by the active image row.
- Structured references in `images.settings_json` and `jobs.settings_json` were
  rewritten to the verified WebP targets before the PNG files moved.
- Original PNG manifest:
  `D:\Google Drive\My progact\IZO_ASA_Gallery_Quarantine\20260719T0042\legacy-png\manifest.json`.

### Deleted and unreferenced media

- The current deleted-image residue had grown from the earlier 42-file estimate
  to 45 files / 13,682,096 bytes. All 45 were moved to manifest quarantine.
- Deleted-image manifest:
  `D:\Google Drive\My progact\IZO_ASA_Gallery_Quarantine\20260719T0042\deleted-image-residue\manifest.json`.
- The unverified pool was reclassified instead of blindly deleted.
- 1,367 files / 17,442,417 bytes were confirmed to have no image, job, source,
  feed, or video owner and moved to quarantine.
- Reviewed-unreferenced manifest:
  `D:\Google Drive\My progact\IZO_ASA_Gallery_Quarantine\20260719T0042\reviewed-unreferenced\manifest.json`.
- 84 protected files / 12,692,814 bytes remain in media intentionally:
  42 seed originals and 42 public-feed variants.

### Terminal jobs

- 185 eligible terminal jobs were compacted after the separate database copy.
- Settings payload size changed from 94,932,906 to 186,827 bytes.
- Removed Base64 payload: 94,746,079 bytes (about 90.36 MB).
- A repeated compaction plan selects zero additional eligible rows.

### Source library

- One historical source thumbnail remains unrecoverable:
  `a06aefc433924aa3a445279e646b2839` /
  `img_b76afcea284b_source1_45409ced28.webp`.
- Its bytes are absent from current media, feed derivatives, and every retained
  backup manifest. The row is accurately marked `missing` and is excluded from
  the available source library; no active gallery card references it.
- The 42 seed publications are classified as feed-backed originals, eliminating
  their previous false private-media warnings.

## Gallery fixes found during browser QA

- The gallery-to-generator `Use as` handoff no longer prefixes an already
  private `/api/media/...` URL with a second `/api`. Authentication refresh is
  retained and the media URL is verified directly before use.
- Mobile sticky navigation no longer places horizontal clipping on `body`.
  A 390 px Playwright check at 3,000 px scroll keeps the header at `top: 0` and
  reports `clientWidth == scrollWidth == 390`.
- The browser QA fixture was published, favorited, viewed, and then removed with
  the normal gallery delete action. Its image, job, publication, and files were
  removed after verification; the account returned to 100/100 images,
  22/100 feed publications, and 14/80 favorites.

## Final verification

- `gallery_original_audit.py --fail-on-issues`: 361/361 active originals
  checked; 0 missing, 0 unreadable, 0 conversion candidates, 42 feed-backed.
- `media_storage_audit.py --fail-on-issues`: 0 missing active references,
  0 deleted-image residue, 84 intentionally protected unreferenced files.
- `user_gallery_link_audit.py --fail-on-issues`: 0 active missing file refs,
  0 user ownership mismatches, 0 job mismatches.
- `video_storage_audit.py --fail-on-issues`: 11 active videos, 0 missing files,
  0 size mismatches, 0 pending or failed deletions.
- `media_health_check.py --fail-on-issues`: passed.
- Gallery/media/source focused backend suite: 144 passed.
- Gallery handoff and shell regression suite: 18 passed.
- `eslint src/newUi.tsx`: passed.
- Production frontend build: passed.

## Restore procedure

1. Stop writes before restoring database or active media.
2. Select the relevant quarantine `manifest.json` and verify each stored SHA-256.
3. Restore files to their original relative paths from the manifest.
4. For a database rollback, restore the pre-compaction SQLite copy as one unit;
   do not mix its WAL/SHM state with the live database.
5. Run all five media audits above before reopening writes.
