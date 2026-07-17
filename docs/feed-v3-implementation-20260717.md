# Feed V3 Implementation Contract

Date: 2026-07-17.

Scope: only the canonical public `/feed` surface, its feed API and tables,
public feed media, ranking signals, publication detail, public author context,
and feed-specific desktop/mobile behavior.

## Canonical Surface

- `/feed` is served by `backend/static/feed/index.html`.
- The React SPA must not implement a second feed page.
- Feed navigation to `/`, `/gallery`, `/profile`, and `/#video` must remain
  aligned with the shared product shell.
- Visual work must not delete editorial seed publications or use private
  gallery originals as a public fallback.

## Product Target

The feed is a media-first discovery surface that helps a visitor inspect work,
understand its author, and continue into creation. Interface chrome must not
compete with the media. The feed uses one functional lime accent, restrained
purple for the social section identity, and no permanent glow.

## Color Contract

- The feed follows Design System 2.0 semantic roles instead of page-specific
  colors: `canvas`, `surface-1`, `surface-2`, `surface-hover`, `field`,
  `media-bg`, `divider`, `stroke-subtle`, and `stroke-control`.
- The media canvas remains `#070A08`. Header, mobile navigation, detail panels,
  and dialogs use `surface-1`; controls and selectable tiles use `surface-2`;
  inputs use `field`; photo and video letterboxing uses `media-bg`.
- Primary, secondary, muted, and disabled copy use their matching text tokens.
  A control border that communicates affordance uses `stroke-control` and must
  keep at least 3:1 non-text contrast against its surface.
- Lime is reserved for creation, active selection, focus, progress, and an
  accepted social action. A selected navigation item also keeps a shape or
  indicator, so color is never the only signal.
- Purple is limited to the calm `Лента` section marker and author/social brand
  context. It must not be used as a general action color or permanent glow.
- Danger and warning states use their semantic tokens. Image overlays may use
  black scrims and white copy when required for contrast over arbitrary media.
- Legacy `rgba(234,255,0,...)` acid values are forbidden in the canonical feed;
  alpha variants must derive from the `#C7F500` accent family.

## Desktop Contract

- The entire `rail + canvas` shell is centered as one layout.
- The media canvas is capped at `1320px` and renders at most four columns.
- Column count is derived from the actual canvas width, not the viewport width.
- The unframed left rail contains search, a personal signal filter, the five
  feed sections, and the only primary `Создать работу` action.
- `Лента` in the shared header is a calm current-section marker, not an
  animated call to action.
- Generator destinations stay available as neutral global navigation.

## Mobile Contract

- The header is one compact row. The five generator destinations are not
  rendered as a second row on `/feed`.
- Search and creation open from compact header controls. Creation uses a bottom
  sheet with the existing image and video destinations.
- There is no floating creation button over public media.
- The five feed sections are fixed bottom tabs with icons, labels, safe-area
  padding, and a single persistent active indicator.
- Swipe left opens the next section; swipe right opens the previous section.
- The active and adjacent panes use cached content and identical geometry so a
  swipe never exposes a grey or empty strip.
- Each feed section preserves its own scroll position.

## Card Contract

- Phone uses two balanced columns with a `4px` gap. Desktop uses two, three, or
  four columns according to the canvas container.
- Public media keeps its native aspect ratio. Canonical image ratios are `1:1`,
  `9:16`, `16:9`, and `3:2`; legacy and provider-specific ratios remain valid.
- No media is cropped merely to normalize the masonry. Extreme ratios may use
  a bounded frame with `object-fit: contain`.
- Grid cards expose author identity, remix, and like. Deep actions belong to
  the detail view.
- Touch actions keep a minimum interactive target while their visible glyphs
  remain compact.

## Detail And Author Contract

- Primary publication actions are remix, like, favorite, and more.
- Download, not interested, report, edit, delete, and owner/admin controls live
  in the secondary action surface.
- Prompt, parameters, and history are mutually exclusive panels.
- Follow remains visible in author context because it acts on the author.
- Other viewers see follower count, not the author's following count.
- The public profile renders saved public profile fields and the original
  avatar without fabricated fallback biography.

## Video Contract

- A feed publication is media-neutral and resolves to exactly one image or one
  video source.
- Video capability is model-driven. The feed stores actual width, height,
  duration, aspect ratio, audio state, and source mode instead of a fixed global
  list of resolutions.
- Public video media consists of a lightweight poster, a muted preview, and a
  full MP4. Private gallery media is never exposed as a fallback.
- Initial feed loading fetches posters only. Desktop preview starts on hover or
  keyboard focus; phone preview starts by explicit user action in the first
  rollout. Only one preview may play at a time.
- Reduced-motion users receive a static poster unless they explicitly start the
  video. Public MP4 responses support byte ranges.
- Video publication is released behind a dedicated server setting after the
  schema migration, derivative pipeline, and image-only regression suite pass.

## Analytics Contract

- Keep card impression, detail open, accepted unique view, dwell, remix start,
  remix completion, creation entry, video play, qualified video view, and video
  completion as distinct events.
- Poster or preview loading alone never counts as a publication view.
- Organic and editorial seed metrics remain separable.
- Ranking changes require measured data and must preserve stable cursor order,
  author diversity, already-seen suppression, and exploration for new authors.

## Release Gates

1. Baseline tests, database manifest, screenshots, and a verified SQLite backup.
2. Desktop/mobile shell and image cards pass before any video schema change.
3. Shadow-table migration copies and audits every publication before switching.
4. Video remains disabled until poster/preview/full media pass privacy, range,
   performance, and browser checks.
5. Every implementation block is committed separately from unrelated work.
6. Moderation expansion is outside this contract; existing eligibility and
   provenance checks remain in force.

## Acceptance Matrix

- Viewports: `320x568`, `360x800`, `390x844`, `430x932`, `768x1024`,
  `1024x768`, `1440x900`, `1920x1080`, `2560x1440`, and `3840x2160`.
- Feed first stable cards: mobile p75 below 1.5 seconds.
- Cached tab switch: p95 below 300 milliseconds with no layout collapse.
- No five-column state, no mobile horizontal overflow, and no sticky control
  covering the final publication or keyboard focus.
- Initial feed requests contain no video payload; at most one preview is active.
- Existing seed count, publication count, reactions, follows, and image media
  readiness remain unchanged by visual work.

## Verified Implementation State

Verified on 2026-07-17:

- the canonical feed shell renders two columns on phone, three on tablet, and
  at most four on desktop; the canvas is capped at 1320px;
- all ten acceptance viewports pass without horizontal overflow;
- image cards keep their existing behavior and video cards fetch only a poster
  during initial rendering;
- desktop hover or focus and explicit phone play load one muted preview at a
  time; opening detail loads the full MP4 player;
- video detail exposes like, favorite, and more while image-only remix and edit
  actions stay unavailable;
- the media-neutral shadow migration preserves legacy publication rows and the
  live schema audit reports no missing tables, columns, or indexes;
- `backend/test_feed_v2.py` passes 62 tests,
  `backend/test_video_generation_api.py` passes 5 tests, and
  `backend/test_gallery_shell_regressions.py` passes 12 tests;
- the video-studio browser flow passes at 1920x1080, 1920x900, 3840x2160,
  and 390x844, including asynchronous publication through `preparing` to
  `published`;
- the verified local data manifest remains 72 publications, 71 published and
  approved, 0 hidden, 1184 reactions, and 4 follows;
- browser QA recorded impression, detail-open, dwell, video-play, and qualified
  video-view events on an isolated database copy;
- the temporary browser database, synthetic publication, and video derivatives
  were removed after verification.

Video publication is enabled by default after the bounded background pipeline
passed the feed, gallery, and real-FFmpeg tests. `FEED_VIDEO_PUBLICATION_ENABLED`
remains a production kill switch and may be set to `0` without disabling image
publication.

Publishing never transcodes inside the HTTP request. The request creates or
reuses one `preparing` publication and places it onto a single in-process queue.
One low-priority FFmpeg worker uses one encoding thread and atomically produces:

- a compact WebP poster for the initial feed render;
- a muted three-second MP4 preview loaded only on interaction;
- a public H.264/AAC MP4 copy capped at a 1920px long edge.

The private gallery original is not modified. The owner can continue working
while the status endpoint reports `preparing`; success changes the publication
to `published`, and a failed preparation can be retried. Pending jobs are
recovered on application startup.
