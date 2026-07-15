# Feed Product And UX Audit

Date: 2026-07-15. Live-data figures below remain the 2026-07-12 snapshot.

Scope: only `/feed`, feed tables/API, feed content, ranking, cards, detail view,
desktop/mobile behavior, and feed documentation.

## Executive Assessment

The feed has a sound public-media foundation, stable tab pager, complete cursor
reachability, server search/filtering, bounded unique-view accounting, and
working subscription unread state. It is now a credible public browsing
surface, but still needs production telemetry, recommendation explanations,
author diversity, and broader challenge semantics before it is a mature social
discovery product.

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

The live table contained no follows, so all honest follower counts were zero.
Follower data belongs to author context, not to the image-preview metrics.

Implemented now:

- image previews keep only author identity, likes, and remixes;
- the author row remains visible but compact on touch devices;
- the opened author card and public profile display real `followersCount`;
- `followingCount` is hidden from other viewers and shown only to the owner;
- following/unfollowing immediately redraws card counts;
- swipe direction now follows the conventional pager model: swipe left moves to
  the next section, swipe right returns to the previous section.

Do not fabricate follows from real accounts. If editorial demo social proof is
needed, create follows only among clearly identified demo authors through an
audited seed migration.

### P0: analytics origin and repeat views

The very high demo view/like totals and zero follows create an implausible
conversion funnel. Demo counters are useful visually, but must be distinguishable
from organic production analytics in database reporting.

Implemented 2026-07-15:

- `metric_origin` distinguishes `organic` and `editorial_seed` publications;
- seeded reaction totals are explicitly labelled in the opened card;
- a view is accepted once per user/installation in a six-hour window;
- anonymous keys are hashed and view events are retained for 90 days;
- reporting can exclude editorial seed activity without ID conventions.

Still required: a production analytics dashboard and migration policy for a
future explicit `imported` source.

### P1: publication reachability and discovery

Resolved 2026-07-15:

- opaque cursors use each section's complete ordering tuple;
- the initial 30-item page extends through automatic loading and a manual
  fallback button;
- search and personal filters run before pagination on the server;
- appended pages deduplicate publication IDs;
- automated coverage walks 67 records through three cursor pages with no loss
  or duplication.

### P1: section promises and data differ

- `Для вас` now includes follows and prior content preferences, but remains a
  simple additive score. It needs diversity, already-seen suppression, quality
  floors, and exploration.
- `Новое` is a correct chronological feed.
- `Ремиксы` is useful, but should measure successful remix starts/completions,
  not only raw recreate reactions.
- `Челленджи` is plural but backed by one default category. Use singular until
  a real active-challenge selector exists.
- `Подписки` has an honest empty message and unread/new-publication indicator;
  a richer author-discovery onboarding route remains desirable.

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

The personalized ranking index `(internal_user_id, kind, publication_id)` is
installed and audited. View lookup and retention have dedicated indexes;
anonymous view keys are hashed and old events are removed in bounded batches.
Follow/unfollow remains idempotent and does not alter publication ownership or
gallery media. Explicit lifecycle policy for other personal reaction events is
still required.

## Recommended Feed Experience

### Phone

- Keep two balanced masonry columns for visual browsing.
- Keep only the compact author avatar and name visible without opening a card.
- Show follower count after opening the author context, not as an image metric.
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
- Follower count is visible in the opened author context and public profile;
  image-preview metrics remain limited to the publication itself.
- At least 95% of active public publications are reachable through pagination.
- Track follow-after-profile-open, save rate, successful-remix rate, hide rate,
  and seven-day return rate separately for each feed section.

## Sources

- WAI-ARIA Tabs Pattern: https://www.w3.org/WAI/ARIA/apg/patterns/tabs/
- Android Pager guidance: https://developer.android.com/develop/ui/compose/layouts/pager
- TikTok recommendation-system explanation:
  https://support.tiktok.com/en/using-tiktok/exploring-videos/how-tiktok-recommends-content
- Web.dev layout stability guidance: https://web.dev/articles/optimize-cls
