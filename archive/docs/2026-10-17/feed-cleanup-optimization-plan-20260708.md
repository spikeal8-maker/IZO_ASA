# Feed Cleanup Optimization Plan

Date: 2026-07-08.

## Principle

Optimization means deleting retired duplicates, not only hiding them behind
guards. A replacement is complete only when:

- the canonical route is documented;
- the old UI/code path cannot render;
- unused JSX/CSS/tests/docs are removed or explicitly moved to an archive
  decision;
- tests prove the old markers do not return;
- seed/demo feed content is preserved.

## Current Canonical Routes

- `/` and `/new`: main generator shell in `frontend/src/newUi.tsx`.
- `/paint`: main drawing shell in `frontend/src/newUi.tsx`.
- `/feed`: backend static feed, `backend/static/feed/index.html`.
- `/gallery`: backend static gallery, `backend/static/gallery/index.html`.
- `/profile`: profile/settings shell currently rendered through the SPA.
- `/admin`: admin shell currently rendered through `frontend/src/LegacyApp.tsx`.
- `/old`, `/legacy`, `/v1`: the allowed old page entrypoints.

Everything else should stop falling into old UI by accident.

## Already Completed

- `/feed` backend route serves only `backend/static/feed/index.html` with
  `Cache-Control: no-store`.
- The old React feed JSX was removed from `frontend/src/newUi.tsx`.
- `/feed` shell tests assert that `.nf-page` and `.iv3-feed` do not appear.
- Static feed topbar no longer carries old global/`n2` topbar styles.
- Static feed generator links use root routes (`/#text-to-image`, `/#editor`,
  `/#face`) instead of the old `/new#...` entrypoint.
- Admin feed deletion endpoint exists:
  `POST /api/admin/feed/publications/{publication_id}/delete-v2`.
- Seed/demo publications and files are protected by docs/tests and were not
  deleted.

## Remaining Cleanup Findings

### P0 - Route Hygiene - Done

- `frontend/src/App.tsx` now whitelists only current routes, explicit old-page
  routes, admin, and backend static guards. Unknown routes no longer render
  `LegacyApp`.
- `/lenta` handling was removed from frontend code. It is not a current product
  route.
- `/gallery` is treated as a backend static route; `/new/gallery` is no longer
  a duplicate SPA entrypoint.

### P1 - Retired Feed CSS - Done

- The large `nf-*` stylesheet block from the removed React feed was deleted from
  `frontend/src/newUi.css`.
- Remaining publish-modal controls were renamed from `nf-*` to `n2-*`.
- `.iv3 .iv3-feed` was removed from `frontend/src/newStudioV3.css`.

### P1 - Static Gallery Route Parity - Done

- `backend/static/gallery/index.html` and `gallery.js` now link to root/hash
  routes (`/#text-to-image`, `/#image-to-image`, `/#editor`, `/#face`).
- Gallery shell tests assert no old `/new#...` links after the cleanup.

### P1 - Documentation Drift

- `docs/new-ui-v2-review.md` still describes `/lenta` and the old React feed as
  working history. Mark it as historical or update its current-state notes.
- Older phase docs may mention removed routes. Do not rewrite history, but add a
  current-state note when a doc is still used as a live reference.

### P2 - Legacy UI Boundary - Reviewed

- `frontend/src/LegacyApp.tsx` is still allowed as the old page and admin host,
  but it is no longer the default fallback for unknown routes.
- Publishing code still exists in `LegacyApp.tsx`, `newUi.tsx`, and static
  gallery. Current reachable product flows are static gallery and new UI; the
  Legacy flow is contained behind explicit old/admin routes and should be
  removed only with a separate old-page retirement decision.

### Protected

Do not delete in this cleanup pass:

- `backend/static/feed/assets/*.webp` used by the visible feed rail/challenge.
- `backend/media/feed/seed-pub-*` feed variants.
- `backend/media/seed_izo_*` seed originals.
- `feed_publications` seed/demo rows.
- Live DB backups and migration/audit scripts unless a separate archival pass is
  approved.

## Execution Plan

1. Route whitelist pass - done:
   make `App.tsx` route only known current routes, explicit old routes, admin,
   and static guards. Unknown routes should not render `LegacyApp`.

2. Remove `/lenta` - done:
   delete `/lenta` handling from frontend code and tests/docs, or replace with a
   backend redirect only if the product explicitly wants that alias.

3. Static gallery parity - done:
   update `backend/static/gallery/*` from `/new#...` to root/hash routes and add
   shell assertions.

4. Retired feed CSS removal - done:
   rename publish-modal `nf-*` classes or isolate them, then delete the old
   `nf-page`/card/detail/mobile-nav CSS blocks from `frontend/src/newUi.css` and
   `.iv3-feed` from `frontend/src/newStudioV3.css`.

5. Duplicate publish flow review - reviewed:
   compare publish behavior in static gallery, `newUi.tsx`, and old
   `LegacyApp.tsx`; keep only current reachable flows outside the old page.

6. Verification:
   run backend feed/gallery tests, frontend build, and route smoke checks for
   `/`, `/feed`, `/gallery`, `/profile`, `/paint`, `/admin`, `/old`, unknown
   route, and `/lenta`.

## Done Criteria

- `rg "nf-page|iv3-feed|/new#|/lenta"` returns only intentional historical docs
  or tests asserting absence.
- `/feed` and `/gallery` cannot render SPA duplicate pages when proxied
  correctly; SPA fallback does not show old UI.
- `npm run build` passes.
- Feed and gallery shell tests pass.
- Seed/demo files and publications remain present.
