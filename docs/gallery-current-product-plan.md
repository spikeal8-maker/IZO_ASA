# Gallery Current Product Plan

Date: 2026-07-15.

## Canonical Gallery Screen

The current production-facing gallery is the page served at `/gallery` from:

- `backend/static/gallery/index.html`
- `backend/static/gallery/gallery.css`
- `backend/static/gallery/gallery.js`

`frontend/src/LegacyApp.tsx` still contains an older React gallery view. Treat it
as reference material unless we explicitly decide to migrate the visible
`/gallery` page into React later.

## Storage And Slot Rules

- Gallery slots are tariff-based and counted from active `images` rows where
  `deleted_at` is empty.
- A heart/favorite marks an original as protected from automatic eviction.
- When a new generation completes and the gallery is full, the backend deletes
  the oldest active non-favorite original.
- Automatic quota eviction affects only the private gallery original. If that
  image was explicitly published, its independent public feed variants and
  publication remain available.
- Favorite originals are never auto-deleted. If the newest or last visible
  important image is favorite-protected, an older non-favorite image should be
  evicted instead.
- If every occupied slot is favorite-protected, the generated result is returned
  to the job, but it is not persisted as a gallery item. The user must unheart
  or manually delete an image to free a slot.
- Manual delete is explicit and may delete a favorite after confirmation.
  Deleting an original retires linked feed publications and removes the generated
  gallery media, but does not delete independently retained uploaded-source rows.
- Uploaded-source library state is independent from the lifecycle and quota of a
  generated gallery card. Source favorites protect source-library entries only;
  image favorites protect generated gallery entries only.
- A source whose parent result was evicted or manually deleted remains available
  until the user explicitly removes that source from the uploaded-source library.

## Visible Gallery Behavior

- The grid must render in normal reading order: newest item at the top-left,
  then left-to-right across the row, then the next row.
- Do not use CSS multi-column layout for gallery cards. Browser columns fill
  top-to-bottom first, which makes users scan down one column before seeing the
  next newest item.
- The visual grid uses CSS Grid masonry via calculated `grid-row-end` spans.
  Tall cards may be tall and wide cards may be wide, but one tall card must not
  stretch the whole row and create a large empty black band beside it.
- Normal user navigation to the gallery must do a real navigation to `/gallery`.
  React routes must not render a second public gallery. If a React fallback ever
  sees `/gallery`, it should show only a loading/guard state while the backend
  static page is expected to own the route.
- The older React gallery picker in `frontend/src/LegacyApp.tsx` is only allowed
  for internal image picking flows, such as choosing an editor/source slot. It
  must not be exposed as the normal user gallery screen.
- Gallery topbar styles must stay scoped under `.iv3.topbar-scope`; do not add
  unscoped `.topbar`, `.brand`, `.mode-tabs`, or similar duplicates to
  `gallery.css`, because they drift from `TopBarV3` and can break mobile parity.
- Card actions are: heart, publish to feed, delete.
- Publish opens a confirmation modal. The user provides a title and chooses
  whether the prompt is visible (`open`) or hidden (`hidden`).
- Delete opens an in-page confirmation modal. Do not use browser-native
  `confirm()` for this flow.
- The image viewer is fullscreen and includes zoom controls, download, publish,
  delete, favorite, share, and edit/use-as actions.
- Mobile layout keeps counters compact, hides the tariff chip and secondary
  utility buttons, and places search next to filter/view controls.
- Keep the HTML shell light. Gallery CSS and JavaScript live in separate static
  files so the browser can cache them independently from the no-store HTML page.
- Empty search/filter states should offer a reset action.
- The fullscreen thumbnail rail should render a small window around the current
  image instead of every loaded thumbnail at once.

## Backend/API Contract

- `GET /api/gallery/items` is the cursor payload for the visible primary gallery.
  It is loaded in small batches, not as one large all-history payload. Search
  (`q`) and filters (`filter`) are server-side so they work beyond the currently
  loaded card batch.
- `GET /api/gallery/secondary` lazily returns feed copies and uploaded-source
  cards without rerunning the primary query.
- `GET /api/gallery/page` remains a compatibility aggregate for older clients
  and tests.
- `POST /api/gallery/{image_id}/favorite` toggles favorite protection only.
- `DELETE /api/gallery/{image_id}` performs explicit deletion and slot release.
- `POST /api/feed/publications` publishes an original to the feed using the
  submitted title and prompt visibility.
- `/api/media/{filename}` checks active image ownership through SQLite. A narrow
  in-memory fallback exists only for a just-generated result that could not be
  persisted because every gallery slot is favorite-protected.
- Private media responses use owner-scoped authorization and a private one-day
  browser cache. `use-as` validates the exact database row and physical file;
  a missing file returns `410` instead of a broken editor draft.

## Generator Image Picker

- The internal picker used by `По фото`, `Сборка`, and `Редактор` has two
  explicit tabs: `Сгенерированные` and `Загруженные`.
- Generated images come from bounded `GET /api/gallery/items` pages. Previously
  uploaded source images come from `uploadedItems` in bounded
  `GET /api/gallery/secondary` pages; the picker must not request the full
  compatibility aggregate or maintain a second source-image index.
- Picker thumbnails preserve their stored width/height ratio. Do not force a
  square crop: portrait and landscape sources must be recognizable before the
  user selects them.
- Selecting an item from either tab applies it to the exact upload target that
  opened the picker, including a specific `Сборка` reference slot.
- Loading, empty, and failure states are visible inside the uploaded tab and do
  not erase the generated tab.
- Private picker images retry once after a trusted-session refresh. A `use-as`
  draft is removed from session storage only after its image has been verified
  and applied, so a transient authorization failure does not lose the action.
- A source row marked `missing` is metadata for a lost physical preview, not a
  consumed source-library slot. Startup repair recreates that preview from the
  original job data, an existing media input, or a linked gallery image while
  preserving the same row, favorite state, and library-deletion state.
- New generations persist compressed source previews as `available` in the same
  workflow. A newly uploaded source should therefore appear after generation;
  recurring mass `missing` counts indicate a non-persistent `MEDIA_DIR` volume,
  not normal tariff eviction.

## Test Coverage To Keep

- `test_favorite_image_is_not_auto_evicted_when_gallery_quota_is_full`
- `test_auto_eviction_skips_newer_favorite_and_removes_previous_unprotected`
- `test_stage3_gallery_detail_favorite_use_as_and_delete`
- `test_gallery_page_uses_cursor_pagination`
- `test_gallery_page_search_and_filter_are_server_side`
- `test_gallery_media_access_is_db_backed_and_removed_after_delete`

Any change to gallery quota, favorite protection, deletion, or feed-publication
side effects should update these tests and this document together.
