# Feed Current Product Plan

Date: 2026-07-08.

## Canonical Feed Screen

The current production-facing feed is the page served at `/feed` from:

- `backend/static/feed/index.html`

This is the screen users currently see on the site, and it remains the canonical
feed UI for the next optimization passes.

The older React feed surface was removed from `frontend/src/newUi.tsx`.
`/feed` must not have a second working UI implementation in the SPA.

The SPA must not claim `/feed`. Vite dev/preview proxy `/feed` to the backend,
and the frontend has a fallback guard so stale builds or broken proxy fallback
show a loading guard instead of reviving a duplicate feed surface.

## Current Goal

Turn the visible `/feed` page into the documented public feed product while
preserving the existing feed-media backend contract:

- public read access for guests;
- trusted-session-only publish and reactions;
- no public fallback to private gallery originals;
- feed cards use optimized public thumbnails;
- detail views use optimized public large WebP files;
- automatic gallery quota eviction preserves linked feed publications and their
  independent public media;
- explicit gallery deletion retires linked feed publications;
- seed/demo publications stay as editorial starter content.

## Implementation Order

1. Keep `/feed` canonical and document that rule.
2. Fix backend behavior gaps with narrow, tested changes.
3. Reconcile API fields with the current static feed page.
4. Improve the visible `/feed` UI in `backend/static/feed/index.html`.
5. Delete retired duplicate feed code, routes, CSS, docs, and tests after each
   replacement is proven by tests.
6. Update tests and release checks after each backend/frontend contract change.

Cleanup tracking lives in `docs/feed-cleanup-optimization-plan-20260708.md`.

## Immediate Backend Gaps

- `following`, `challenge`, author publications, and modal actions should remain
  aligned with the same public media contract.
- Future schema changes must be additive-only and backed by audits/migrations.

## Visual Notes For Step 6/9

- Continue visual QA on desktop/mobile cards after each CSS pass.

## Completed In This Pass

- Feed author payloads now expose real `followersCount` and `followingCount`
  values from `feed_author_follows`. The publication author card and public
  profile display both counts and update the follower count immediately after
  a follow or unfollow action.
- `Избранное` is defined as the signed-in user's private saved-publication
  collection. The star action saves or removes a publication, and saved works
  are available through the `Избранное` feed filter.
- The publication detail view keeps four primary controls visible: remix, like,
  favorite, and `Другие действия`. Follow, personal hide, download, report,
  owner/admin management, prompt, parameters, and history are grouped in the
  expandable secondary area.
- Gallery quota eviction no longer retires a linked feed publication or deletes
  its independent public WebP variants. Explicit gallery deletion still retires
  the linked publication according to the current product contract.
- The 12 publications previously retired by quota eviction were recovered from
  uniquely matched ComfyUI outputs. `backend/feed_hidden_recover.py` provides a
  dry-run/apply workflow and creates a SQLite backup before recovery.
- Personal `hide` now removes a publication from authenticated feed lists after
  reload while keeping the publication visible to guests and other users.
- `backend/test_feed_v2.py` covers the personal hide behavior for following and
  fresh feed reads.
- The visible `/feed` modal now exposes the existing backend `save` action:
  users can save/unsave a publication without leaving the current static feed UI.
- The static feed shell test now checks that the save control and endpoint wiring
  remain present in `backend/static/feed/index.html`.
- Personal `hide` filtering now happens inside feed SQL before `LIMIT`, so
  hidden publications do not consume result slots in fresh, top, remix,
  challenge, following, or author-publication lists.
- `type=top` now ranks by positive signals only (`like`, `save`, `recreate`);
  negative moderation/personal signals (`dislike`, `hide`, `report`) no longer
  boost a publication.
- Gallery page feed status now matches public feed availability: a publication
  is shown as published in `/api/gallery/page` only when its public feed media is
  ready, and missing feed media no longer creates feed-copy cards or consumes the
  visible feed-used counter.
- Database readiness now includes feed query indexes for category/challenge
  reads and gallery-owned publication reads:
  `idx_feed_publications_category_ready_created` and
  `idx_feed_publications_legacy_ready_created`.
- The visible `/feed` page now treats feed media URLs as strict: cards require
  `thumbnail_url`, detail/download require `image_url`, and incomplete media
  items are not rendered instead of falling back to a heavier variant.
- Admins can remove a publication from the public feed via
  `POST /api/admin/feed/publications/{publication_id}/delete-v2`. The action
  hides the publication, removes public feed variants, writes audit/security
  records, and leaves the user's private gallery source intact.
- Desktop feed card overlays no longer use dark backplates behind the author
  name, remix, or heart controls. They remain readable via text/drop shadows,
  while the controls stay real buttons for click and keyboard focus.
- The old React feed route was removed from current SPA routing. `/feed` is a
  backend static page, `/lenta` is no longer a product route, and unknown SPA
  routes no longer fall through to `LegacyApp`.
- The visible `/feed` top bar is part of the feed plan: it must visually match
  the main `TopBarV3` shell on desktop and mobile. The static feed no longer
  carries the old global/`n2` topbar rules, and feed-to-generator links use the
  main root route (`/#text-to-image`, `/#image-to-image`, etc.) instead of the
  older `/new#...` entrypoint.
- The old React feed JSX was removed from `frontend/src/newUi.tsx`; remaining
  feed-related code there is only for publishing from gallery/history and for
  using public feed thumbnails as empty-history suggestions.
- The retired feed CSS namespace was cleaned from current frontend code:
  `frontend/src/newUi.css` no longer carries the old `nf-*` feed stylesheet,
  publish-modal classes now use `n2-*`, and `.iv3-feed` was removed.
- The visible `/feed` mobile layout no longer has a duplicated fixed bottom
  navigation. The top site bar is sticky at the viewport top, while feed filters
  stay directly below it.

## Do Not Do Without A Separate Decision

- Do not replace the visible `/feed` page with the React feed tab.
- Do not keep disabled duplicate feed pages as "fallbacks"; remove them after a
  tested canonical replacement exists.
- Do not return to serving `images.url` originals from public feed endpoints.
- Do not remove seed/demo originals or feed publications during visual work.
- Do not let `/feed` drift from the main top bar treatment; update this page
  when `TopBarV3` changes.
- Do not change `feed_publications`, `/api/feed`, `/api/feed/media`, or
  `/api/feed/publications` without updating tests and this plan.
