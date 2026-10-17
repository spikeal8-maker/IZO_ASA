# Feed Layout Redesign

Date: 2026-07-16.

Scope: only the canonical public `/feed` page served by
`backend/static/feed/index.html`.

## Product Decision

The feed is an image-discovery surface first. Generator promotion, search,
section navigation, and filters must not consume the first desktop or mobile
viewport at the expense of public works.

The redesign keeps the existing feed API, ranking, tab cache, cursor pagination,
swipe pager, reactions, subscriptions, public profiles, and detail view. It
changes only the feed navigation shell, card density, and responsive placement.

## Desktop Contract

- The feed uses at most four masonry columns.
- The image canvas is capped at `1320px`; ultra-wide screens add breathing room
  instead of making every image excessively large.
- The left rail is an unframed navigation lane, not a promotional card.
- Search and the personal signal filter appear at the top of the rail.
- `Для вас`, `Новое`, `Ремиксы`, `Челлендж`, and `Подписки` are vertical
  icon-and-label navigation items using the existing tab semantics.
- `Создать своё` is the only generator call to action in the rail.
- Cards preserve their public thumbnail aspect ratio, have no permanent border,
  and use only a restrained image-scale hover response.
- Masonry columns have no decorative vertical offsets.

## Mobile Contract

- The first feed cards begin directly below the shared site top bar.
- The site top bar uses one compact row on `/feed`; the five generator
  destinations are available from the creation chooser instead of a second
  compressed navigation row.
- The feed keeps two balanced columns below `640px` with a `4px` gap.
- The five feed sections become a fixed bottom tab bar using the same DOM tab
  controls as desktop.
- Horizontal drag continues to switch the cached adjacent feed pane and updates
  the selected bottom tab.
- Search opens from a compact top-bar icon and does not reserve permanent
  vertical space or cover feed actions.
- Creation opens from a compact top-bar control and uses a mode chooser. There
  is no floating action over the media canvas.
- Bottom padding includes the device safe area so navigation never covers the
  final publications.
- Remix and like remain visually compact while retaining a `40px` minimum touch
  target.

## Masonry Rules

- `< 640px`: two columns.
- `640px - 1079px`: three columns.
- `>= 1080px`: four columns.
- Tall-card balancing uses the real aspect ratio up to `2.25`; a `9:16` work is
  no longer incorrectly estimated as `1.45`.
- The same column rules apply to the active pane, prepared adjacent pane, and
  loading skeleton.

## Acceptance Checks

- No five-column feed is rendered at any viewport.
- At `1440x900`, the canvas shows four inspectable columns and starts immediately
  below the top bar.
- At `390x844`, the canvas starts immediately below the top bar with two columns.
- Mobile bottom navigation fits at `360px`, `390px`, and `430px` without
  horizontal overflow.
- Search opens and closes without changing document height.
- A tab click, keyboard change, and horizontal swipe all update the same active
  tab state.
- Existing feed shell, cursor pagination, reaction, subscription, and detail
  tests remain green.

## Reference Patterns

- Midjourney Explore prioritizes the image canvas and exposes reuse, similarity,
  and like actions contextually:
  https://docs.midjourney.com/hc/en-us/articles/33329460426765-Website-Overview
- Ideogram uses left-side product navigation and combines community search with
  content categories:
  https://docs.ideogram.ai/using-ideogram/ui-overview/pages-ui/home-page
- Leonardo exposes its Community Feed from the left sidebar:
  https://intercom.help/leonardo-ai/en/articles/8942657-how-to-write-great-text-to-image-prompts
- Shedevrum separates recent, best, personal, and followed-author feeds:
  https://apps.apple.com/ru/app/id1671837122
