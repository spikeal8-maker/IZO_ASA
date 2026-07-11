# Feed Product And UX Audit

Date: 2026-07-12.

Scope: only `/feed`, feed tables/API, feed content, ranking, cards, detail view,
desktop/mobile behavior, and feed documentation.

## Executive Assessment

The feed has a sound public-media foundation and a much more stable tab pager
than its earlier implementation. It is not yet a mature social discovery
surface. The largest current gaps are social proof, trustworthy analytics,
pagination, content curation, and stronger differentiation between sections.

## Live Data Snapshot

- 67 publications, all `published`.
- 67/67 publications have ready thumbnail and large feed variants.
- 10 publishing authors.
- 0 rows in `feed_author_follows` before this audit.
- 810 likes, 179 recreates, and 175 saves.
- 696,262 aggregate views; average 10,392 and maximum 51,581.
- 44/67 prompts hidden, 23 open.
- 65/67 publications allow recreation.
- Categories: 37 showcase, 23 other, 6 Moscow challenge, 1 art.

The zero follow rows explain why no author currently has visible nonzero social
proof. The feature and API are present, but adoption/data are absent.

## What Is Good

### Media and database contract

- Public cards use independent public thumbnail/large variants.
- All current publication media is ready; there are no hidden/missing rows in
  the live snapshot.
- Personal hide, likes, saves, recreates, follows, owner deletion, and admin
  moderation have dedicated feed contracts.
- Automatic gallery quota eviction no longer removes feed publications.

### Interaction

- Tabs have accessible roles and a linked tab panel.
- Mobile paging has direct drag feedback, boundary resistance, cache, adjacent
  prefetch, request cancellation, and reduced-motion behavior.
- Publication cards preserve their source aspect ratios.
- The detail view exposes author identity, follow action, publication actions,
  generation data, history, and related work.

## Problems And Priorities

### P0: subscriptions have no visible adoption

Before this audit, follower counts appeared only after opening publication or
author details. General feed cards showed no follower count, and the live table
contained no follows. This made the feature effectively invisible.

Implemented now:

- every general feed card displays the author's real `followersCount`;
- the author row remains visible on touch devices;
- following/unfollowing immediately redraws card counts;
- swipe direction now follows the conventional pager model: swipe left moves to
  the next section, swipe right returns to the previous section.

Do not fabricate follows from real accounts. If editorial demo social proof is
needed, create follows only among clearly identified demo authors through an
audited seed migration.

### P0: analytics are not yet trustworthy as product metrics

The very high demo view/like totals and zero follows create an implausible
conversion funnel. Demo counters are useful visually, but must be distinguishable
from organic production analytics in database reporting.

Recommended schema addition:

- `metric_origin`: `organic | editorial_seed | imported`;
- event-level unique-view aggregation by viewer/installation and time window;
- dashboards should exclude editorial seed activity by default.

### P1: only 60 of 67 publications are reachable per request

Every tab has a hard limit of 60 and no cursor. Search/filtering is performed on
the loaded subset, so some public work is unreachable through normal browsing.

Recommended:

- opaque cursor based on the tab's ordering tuple;
- infinite loading before the user reaches the end;
- server-side search and personal filters;
- deduplication by publication ID when appending pages.

### P1: section promises and data differ

- `Для вас` now includes follows and prior content preferences, but remains a
  simple additive score. It needs diversity, already-seen suppression, quality
  floors, and exploration.
- `Новое` is a correct chronological feed.
- `Ремиксы` is useful, but should measure successful remix starts/completions,
  not only raw recreate reactions.
- `Челленджи` is plural but backed by one default category. Use singular until
  a real active-challenge selector exists.
- `Подписки` needs onboarding when empty and unread/new-publication indicators.

### P1: content curation and brand safety

The feed is a public first impression. Editorial demo content and titles must
follow the same moderation and naming standards as user publications. Sexualized
or body-focused demo titles visible in earlier screenshots are not appropriate
as broad-audience starter content and should be reviewed or removed through the
normal feed moderation workflow.

Recommended editorial checks:

- title quality and length;
- broad-audience suitability;
- duplicate/near-duplicate suppression;
- author and style diversity in the first viewport;
- no two consecutive works from the same author in discovery;
- explicit editorial flag instead of relying on ID conventions.

### P1: prompt availability conflicts with remix positioning

65 works permit recreation, but 44 hide their prompt. Hidden prompts are valid
for author privacy, yet the Remix section must explain what can be transferred
and should rank fully reproducible works higher when quality is comparable.

### P2: database indexes and lifecycle

The personalized ranking now reads reactions by viewer. Add and audit an index
on `(internal_user_id, kind, publication_id)` before traffic grows. Add retention
and audit rules for follows, reports, hides, and view events. Follow/unfollow must
remain idempotent and must never alter publication ownership or gallery media.

## Recommended Feed Experience

### Phone

- Keep two balanced masonry columns for visual browsing.
- Keep author avatar, name, and follower count visible without opening a card.
- Keep only remix and like as direct card actions.
- Use left swipe for next tab and right swipe for previous tab.
- Preserve each tab's position and cached content.
- Add pull-to-refresh only to the active pane.
- Show an unread dot/count on `Подписки`, not a permanent decorative badge.

### Desktop

- Keep dense masonry, but cap extreme wide-screen column count so works remain
  inspectable.
- Make author identity and follower count visible on hover and keyboard focus.
- Use the right-side detail view for deep actions; do not duplicate all controls
  on the grid card.
- Add a quiet reason label in `Для вас` such as followed author, similar style,
  popular remix, or fresh publication.

## Ranking Roadmap

1. Separate organic and editorial metrics.
2. Add unique view and dwell/preview-open signals with privacy limits.
3. Add already-seen suppression and author diversity.
4. Add negative feedback decay from hide/not-interested.
5. Add exploration slots for new authors with low historical engagement.
6. Evaluate ranking by saves, successful remixes, follows after view, and return
   sessions rather than raw likes alone.

TikTok's official recommendation description separates personalized discovery
from followed-author feeds and uses interactions, content information, user
context, negative feedback, and diversification. We should use the same product
separation without copying its presentation.

## Acceptance Metrics

- Feed open to first stable cards: p75 under 1.5 seconds on mobile.
- Tab switch from cache: p95 under 300 ms with zero layout collapse.
- No stale response can replace the selected tab.
- Follow action updates every visible representation immediately.
- Follower count is visible on grid, detail author card, and public profile.
- At least 95% of active public publications are reachable through pagination.
- Track follow-after-profile-open, save rate, successful-remix rate, hide rate,
  and seven-day return rate separately for each feed section.

## Sources

- WAI-ARIA Tabs Pattern: https://www.w3.org/WAI/ARIA/apg/patterns/tabs/
- Android Pager guidance: https://developer.android.com/develop/ui/compose/layouts/pager
- TikTok recommendation-system explanation:
  https://support.tiktok.com/en/using-tiktok/exploring-videos/how-tiktok-recommends-content
- Web.dev layout stability guidance: https://web.dev/articles/optimize-cls
