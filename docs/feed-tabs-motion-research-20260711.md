# Feed Tabs And Motion Research

Date: 2026-07-11.

## Scope

This document evaluates only the canonical `/feed` surface, its five primary
sections, mobile swipe behavior, loading behavior, and transition quality.

## Executive Finding

The current mobile interaction is not a pager. It recognizes a completed touch
gesture, changes the active label, destroys the current masonry, fetches another
60-item list, and rebuilds the page. The content does not follow the finger and
there is no outgoing/incoming panel transition. This is the primary cause of the
visible jump.

The correct target is a tab-controlled mobile pager with cached adjacent panes,
stable geometry, direct-manipulation swipe feedback, one-page snapping, and a
reduced-motion fallback.

## External Guidance

- WAI-ARIA describes tabs as mutually exclusive panels and recommends automatic
  activation only when panel content can appear without noticeable latency.
  Remote panels therefore need preloading or manual activation semantics.
  https://www.w3.org/WAI/ARIA/apg/patterns/tabs/
- Android distinguishes primary tabs as the top-level destinations of one
  content pane. Its pager guidance uses a full-width horizontal pager, lazily
  keeps pages, animates page changes, and limits a normal fling to one page.
  https://developer.android.com/develop/ui/compose/components/tabs
  https://developer.android.com/develop/ui/compose/layouts/pager
- Apple recommends tabs only for closely related, mutually exclusive panes,
  keeping all choices visible where practical and avoiding more than six. Five
  feed sections are within that limit. On mobile, a segmented or page-style
  control is the analogous pattern.
  https://developer.apple.com/design/human-interface-guidelines/tab-views
- High-performance motion should primarily animate `transform` and `opacity`,
  not properties that trigger layout and repaint of the masonry.
  https://web.dev/articles/animations-guide
- Dynamic content needs reserved geometry to avoid layout shifts. Replacing a
  whole feed with an empty container violates that principle.
  https://web.dev/articles/optimize-cls
- Motion must honor `prefers-reduced-motion`.
  https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/At-rules/%40media/prefers-reduced-motion

## Current Implementation Audit

### P0: transition mechanics

1. `activateFeedTab()` immediately changes selection and calls `loadFeed()`.
2. `loadFeed()` immediately sets `masonry.innerHTML = ''`.
3. The document height collapses until the network request and render finish.
4. The tab strip simultaneously calls smooth `scrollIntoView()`.
5. The mobile feed bar also reacts to window scroll direction and may hide or
   show while the document height is changing.
6. Swipe is recognized only on `touchend`; content never follows the finger.

These independent movements produce the perceived jerk and loss of place.

### P0: request correctness

- There is no per-tab cache.
- Adjacent tabs are not prefetched.
- Previous requests are not aborted or guarded by a request sequence. Rapid
  switching can allow an older response to overwrite a newer selection.
- There is no loading pane with reserved height and no per-pane error state.

### P1: section semantics

- `Для вас`: currently a global score of remix x8, save x4, like x1, challenge
  boost, and recency. It does not use the viewer's own interests, follows,
  history, hides, or similarity profile for positive personalization. The label
  overpromises the current behavior.
- `Новое`: correctly represents published items in reverse chronology.
- `Ремиксы`: correctly prioritizes recreate count, then saves and recency. It is
  a useful intent-specific feed.
- `Челленджи`: currently defaults to one hard-coded challenge category. The
  plural label implies a general challenge destination that does not yet exist.
- `Подписки`: correctly uses followed authors and reverse chronology, but guests
  and users with no follows need a deliberate empty/onboarding state.

Official product documentation from TikTok and YouTube supports a clear
separation between personalized discovery and content from followed creators.
Signals commonly include watch/view behavior, likes, dislikes/not-interested,
search, subscriptions, content information, and diversification.

### P1: feed completeness

- Every section is limited to 60 items with no cursor pagination.
- Search and action filters operate only on those 60 client-side items.
- Per-tab scroll position is not modeled.
- The tab markup lacks explicit `tabpanel`, `aria-controls`, and panel IDs.

## Recommended Product Model

Keep five primary sections, but define them precisely:

1. `Для вас`: personalized discovery. Use viewer reactions, hides, viewed items,
   followed authors, preferred modes/styles, recency, quality, and diversity.
   Guests receive a clearly defined popular/fresh blend.
2. `Новое`: strict publication chronology with cursor pagination.
3. `Ремиксы`: works that are useful as generation starting points, ranked by
   successful recreations, saves, recency, and diversity.
4. `Челленджи`: active challenge works, with an active challenge selector when
   more than one challenge exists. Until then, use singular `Челлендж`.
5. `Подписки`: recent work from followed authors. Do not silently fill an empty
   result with recommendations; provide a clear empty state and a route back to
   discovery.

`Избранное` and `Лайкнутые` remain filters or personal collections, not equal
primary feed destinations.

## Target Mobile Interaction

### Structure

- Stable sticky tab row and search/filter row.
- A clipped pager viewport below them.
- A horizontal track containing previous, current, and next panes only.
- Each pane owns cached items, loading/error/empty state, cursor, and scroll
  position.

### Swipe

- Lock direction only after about 8-12 px of movement.
- Horizontal intent must exceed vertical movement by a clear ratio.
- While dragging, translate the pager track with the finger using
  `requestAnimationFrame`; do not wait for `touchend` to show feedback.
- Commit on approximately 25% width or sufficient velocity; otherwise spring
  back.
- Move at most one section per gesture.
- Settle in roughly 200-260 ms with a decelerating curve.
- The tab indicator follows pager progress instead of jumping first.
- Do not animate masonry item positions individually during a page change.

### Loading and cache

- Cache each tab response for a short product-defined TTL.
- Prefetch the immediate previous and next sections when idle.
- Keep the outgoing pane visible until the incoming pane has stable geometry.
- Reserve at least the visible viewport height for first-load skeletons.
- Abort obsolete requests and ignore responses whose request token is stale.
- Preserve each tab's scroll position when returning to it.

### Accessibility and reduced motion

- Add `id`, `aria-controls`, `aria-labelledby`, and `role="tabpanel"` links.
- Use manual keyboard activation until remote panes are prefetched; after cache
  warm-up, automatic arrow activation is acceptable.
- With `prefers-reduced-motion: reduce`, replace horizontal travel with a short
  opacity transition or instant swap while preserving geometry.

## Visual Direction

The primary sections should read as one navigation system, not five unrelated
buttons. Recommended treatment:

- one quiet full-width tab rail;
- equal-height labels with stable dimensions;
- a single moving active indicator;
- no shadows, raised cards, or individual button backgrounds;
- clear selected/unselected contrast;
- partial next-label visibility only when horizontal overflow is unavoidable.

The last implementation's individual bordered rectangles make the row read as
a segmented command control. That is better than bare words but still not the
right visual language for a content pager.

## Implementation Order

1. Remove destructive empty-before-fetch behavior and add request cancellation.
2. Add per-tab state/cache and stable loading geometry.
3. Build the three-pane mobile pager with direct drag feedback.
4. Synchronize the tab indicator to pager progress.
5. Preserve per-tab scroll positions and add cursor pagination.
6. Complete ARIA panel relationships and reduced-motion behavior.
7. Replace the current global `Для вас` score with actual viewer-aware ranking.
8. Generalize challenges or temporarily rename the single destination.

## Acceptance Criteria

- No blank frame during a cached or uncached tab change.
- No document-height collapse or top-bar jump.
- Content visibly tracks the finger during swipe.
- One gesture changes at most one section.
- Rapid repeated switching never renders the wrong response.
- Returning to a section restores its prior content and position.
- Vertical scroll remains reliable on image cards.
- No horizontal page overflow at 360, 390, 430, 768, and desktop widths.
- Reduced-motion mode has no large horizontal page movement.
- Browser checks confirm stable geometry and no unexpected layout shifts.

## Implemented After Audit

- The feed no longer clears the masonry before a replacement response arrives.
- A stable tab panel, loading skeleton, short-lived per-tab cache, adjacent-tab
  prefetch, request cancellation, and stale-response guard are implemented.
- Mobile drag now moves the feed panel with the finger, applies boundary
  resistance, uses distance/velocity commit rules, and settles by transform and
  opacity. Reduced-motion users receive an opacity-only change.
- Swipe direction follows the conventional content pager: left reveals the next
  section and right returns to the previous one. A prepared adjacent pane now
  fills the revealed area during drag instead of exposing a blank background.
- Rapid tab requests retain the latest requested destination instead of
  allowing an obsolete response to win.
- Tab and panel ARIA relationships and contextual empty/error messages exist.
- `Для вас` now adds viewer-aware author-follow and content-preference signals
  to the existing quality/recency ranking while retaining a guest fallback.

Cursor pagination, a general multi-challenge selector, and a richer long-term
interest model remain separate backend/product increments; they are not required
for the corrected transition mechanics.
