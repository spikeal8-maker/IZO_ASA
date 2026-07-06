# /new Text→Image MVP — Release Notes

- **Branch:** `feature/new-ui-v2-integrated-safe`
- **Commit:** `465c9a9` (`fix(new-ui): stage 5.4 — prompt, format, share, loading polish`)
- **Release date:** 2026-07-06
- **Checks at freeze:** eslint 0, `tsc -b` OK, `vite build` OK

## What's in the MVP (`/new` Text → Image)

- New responsive shell from the HTML prototype, scoped under `.iv3` (`newStudioV3.css`).
- Unified top bar (`TopBarV3`) shared across `/new`, `/feed`, `/gallery`, `/profile`.
- **Text → Image** tab fully wired:
  - prompt textarea (0/2000 counter, desktop resize, mobile auto-grow + scroll);
  - styles row (36 styles, short localized labels, hover-preview, drag/wheel scroll);
  - format / resolution (custom dropdown: shape icon + size; 1:1 / 9:16 / 16:9 in sync);
  - quality (Быстро / Стандарт / Максимум);
  - Generate → `POST /api/generate` + job polling (unchanged contract);
  - states: empty, loading (blurred backdrop + shimmer + progress), result, error;
  - history strip (adaptive square/portrait/wide thumbnails, drag-scroll, active outline);
  - feed fallback (guest / no own images → placeholder + latest public feed, badged «Лента»);
  - download + share menu; publish to feed (`POST /api/feed/publications`) via the existing flow;
  - prompt dock sync (Копировать / Изменить в / В ленту / Вариации).
- Mobile: sticky two-row topbar, fixed bottom Generate CTA, readable tool buttons.

## What's NOT in the MVP (deferred)

- Изо → Изо (placeholder only)
- Редактор (placeholder only)
- Рисунок (placeholder only)
- Лицо (placeholder only)
- Видео (disabled tab)
- Full English localization (only short style labels + core strings are bilingual)
- Final polish of all modals (publish modal has mobile sizing but not fully audited)

## Freeze rule

`/new` is frozen after this release. Do **not** modify `/new` except for a
blocker / critical bug. New tabs (Изо→Изо, Редактор, Рисунок, Лицо, Видео),
full EN localization and further polish are separate, later stages.

## Layout baseline

The current visual-size baseline is documented in
`docs/ui-route-layout-baseline-20260706.md`.

Important route distinction:

- `/news` is the legacy studio scale.
- `/new` is the v3 studio scale from this MVP.

They are different UI implementations, not the same page with a different
browser zoom. Future settings/profile work may add a route/layout preference,
but should not implement this as global CSS zoom.
