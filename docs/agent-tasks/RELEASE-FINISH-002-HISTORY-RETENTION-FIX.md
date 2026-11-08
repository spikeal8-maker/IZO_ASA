---
status: code-complete
updated: 2026-11-08
package: RELEASE-FINISH-002-HISTORY-RETENTION-FIX
base: 831694f2b32f400df568c7b6dd45b324f05c2778
contract: tasks/RELEASE-FINISH-002-HISTORY-RETENTION-FIX.toml
---

# Historical gallery retention after a new generation

## Problem and boundary

A newly authorized owner generation completed successfully in the existing
closed Linux beta. Its ordinary gallery eviction and deferred compaction paths
were not covered by startup-only no-replay protection. Two sealed historical
images were soft-deleted with their originals and thumbnails removed. Another
historical original was recompressed. The original snapshot volumes are intact.
The operational repair is limited to three pinned rows and five absent files;
it must retain the newly generated result, admission, ledger and login session.

This code package changes four production files. It does not change passwords,
ledger, tariffs in storage, provider settings, egress, GPU controls, schemas or
source snapshots. The existing test project is paused for the reviewed update.

## Behavior

- Gallery candidates exclude sealed images in SQL before ordering and limiting.
- In preserve mode, active sealed images belonging to this owner are counted
  separately from the normal positive allowance for new work. The copied runtime
  tariff includes that protected occupancy; stored plan settings do not change.
  Foreign and deleted history add no allowance. Zero slots still allow no saves.
- Eviction rechecks the history boundary before changing a row and before
  unlinking media. Missing required guards and invalid seals fail closed.
- Compaction is extracted into `backend/app/storage/gallery_maintenance.py`.
  It excludes sealed rows before `keep_recent`, claims only mutable originals,
  rechecks updates and destructive filesystem steps, and closes its connections.
- Preservation-disabled quota, oldest-candidate order and compaction behavior
  remain covered by the existing characterization tests.

`backend/main.py` remains a compatibility shell: its measured line budget falls
from 19,684 to 19,602. The pure gallery policy and its storage limits are unchanged.

## Verified source evidence

The new regression uses a temporary SQLite database, actual temporary PNG/WebP
files, the real HTTP admission endpoint and generation worker, and a fake provider.
It seeds an over-limit sealed gallery with originals, archives, thumbnails,
favorites, foreign rows and deleted rows. It verifies all historical row values
and all old file hashes after each completion and after reloading state.

The first new image is saved with one charge. Repeating its idempotency key returns
the existing completed job and image without another provider call or charge.
The second new image evicts only the first new image, preserving the full history.
Direct-helper cases cover stale candidates, invalid boundaries, zero allowance,
and concurrent compaction repeated three times.

Focused command (from repository root with `PYTHONPATH=backend`):

```text
python -m pytest -q --tb=short backend/test_history_gallery_retention.py backend/test_gallery_storage_optimization.py backend/test_storage_gallery_repository_module.py backend/test_services_gallery_eviction_module.py backend/test_services_gallery_policy_module.py backend/test_release_finish_history_http.py backend/test_history_replay.py
```

Result: **73 passed in 12.18 seconds**. Durable operation:
`fff7d8ff7b074fdd87efceefccbe7fe9`.

A separate negative control substituted only the exact four original callbacks
read from base commit `831694f2b32f400df568c7b6dd45b324f05c2778` into that isolated
test process. The same completion regression failed on changed sealed image rows
at `assert_history_unchanged`, as expected. No source checkout or live data was
changed by this control. The fixed run then passed all 73 tests.

## Release and recovery acceptance still required

Independent source review approved the four unchanged production files and the
verified regression with no blocking findings. Required CI on the published
candidate, native 1Panel update, precise recovery and historical UI/restart
acceptance remain separate release gates.
The focused test result is not deployment or operational acceptance evidence.
Recovery must use the stopped clone, full-row compare-and-swap, immutable original
file hashes and no whole-database replacement. The new owner result and all other
live data must survive. Reopening requires the fixed application and unchanged
network isolation. The main public domain is outside this release scope.
