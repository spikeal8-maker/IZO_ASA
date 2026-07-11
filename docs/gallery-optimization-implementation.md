# Gallery optimization implementation

Canonical page: `/gallery` (`/gallery/` is an alias of the same static shell).

## Baseline: 2026-07-11

- SQLite backup: `backend/backups/gallery-before-optimization.sqlite3` (ignored runtime artifact).
- Backup SHA-256: `30EC437981B7E0742ADE825B392FF4084D791285B0233BCF980B0B77A0482983`.
- Media storage: 1,590 files, 172.62 MB.
- Unreferenced media: 758 files, 16.08 MB. No deletion was performed.
- Deleted-image residue: 6 files, 1.32 MB. No deletion was performed.
- First gallery page before optimization: 60 gallery cards plus feed and source cards.
- First 60 gallery thumbnails: about 2.10 MB.
- Production source library check: 20 cards returned, 15 loaded, 5 referenced missing files.
- Local source audit: 115 active rows referenced unavailable local files.

## Phase 1: integrity and initial load

Implemented:

- `image_sources.availability_status`, `availability_checked_at`, and `unavailable_at`.
- Read-only availability reconciliation; it marks rows but does not delete records or files.
- Missing source previews are excluded from the usable source-library response.
- The response reports `uploadedUnavailableCount` separately.
- New source previews are recorded as `available` in the same transaction as their metadata.
- Initial gallery page size is 24 on desktop and 12 on mobile.
- Feed and uploaded-source cards are not created until their sections approach the viewport.
- Feed cards are no longer duplicated when the main gallery appends another cursor page.
- Active `images` rows use normalized `deleted_at IS NULL` semantics.
- Partial ordered index: `(user_id, created_at DESC, id DESC) WHERE deleted_at IS NULL`.
- Dead gallery helper `allItems` removed.

Verification:

- SQLite query plan uses `idx_images_active_user_created` without a temporary B-tree.
- Source reconciliation is idempotent and non-destructive in isolated tests.
- Gallery JavaScript syntax check passes.
- New gallery tests pass. Two pre-existing legacy expectations remain unrelated to this phase.

## Remaining phases

1. Split gallery items, feed publications, uploads, and counters into independent cursor APIs.
2. Replace full-grid `innerHTML` rebuilds with incremental keyed updates.
3. Replace measured masonry with aspect-ratio placement and add bounded DOM windowing.
4. Add indexed search fields/FTS and request cancellation.
5. Add explicit immutable private-media cache policy.
6. Reconcile production source storage and recover or quarantine unavailable records.
7. Produce a reviewed cleanup manifest, quarantine files, then remove confirmed residue.
8. Run 10/100/500-item load tests on desktop and mobile.

## Phase 2: primary API and persistent media path

Implemented:

- `MEDIA_DIR` selects the durable media root; local development falls back to `backend/media`.
- `/api/gallery/items` returns only the primary cursor page and counters.
- The primary endpoint limits pages to 60 and defaults to 24.
- Publication lookup for primary cards is restricted to IDs in the current page.
- `/api/gallery/secondary` is a compatibility endpoint loaded only near the lower sections.
- Search/filter resets primary and secondary state independently.
- Cursor pagination remains available without repeating feed/source collections.

Deployment requirement:

- Configure a persistent Coolify volume and set `MEDIA_DIR` to its mounted absolute path.
- The SQLite database and `MEDIA_DIR` must survive the same deployment lifecycle.
- Do not remove missing `image_sources` rows until the production volume is mounted and reconciled.

## Phase 3: incremental grid and deterministic masonry

Implemented:

- Masonry spans are calculated from persisted image `width`/`height` and one container measurement.
- Removed per-card `getBoundingClientRect().height` layout reads.
- Removed per-image masonry `load` and `error` listeners.
- Cursor pages append only new, deduplicated card nodes.
- Favorite changes replace only cards with the affected image ID.
- Delete removes only cards with the affected image ID.
- Loading secondary sections no longer rebuilds the primary grid.
- Full grid rebuild remains only for a fresh search/filter and grid/list mode changes.

## Phase 4: indexed search and request cancellation

Implemented:

- SQLite FTS5 index covers image ID, original/translated prompt, mode, provider, model/settings metadata.
- Insert/update/delete triggers keep the search index synchronized.
- Existing images are backfilled idempotently during schema initialization.
- Primary gallery search uses FTS prefix terms instead of six `%LIKE%` scans.
- A new search aborts stale primary and secondary requests.
- Version guards prevent late responses from replacing newer results.
- Client-side prompt/aspect/model rescanning was removed; local filtering remains only for mutable favorite/publication state.
