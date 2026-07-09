# SEO and multilingual roadmap - 2026-07-09

## Current decision

Do not publish separate English routes yet.

The production UI is still actively changing: `/`, `/paint`, `/feed`, `/gallery`, `/profile`, editor modes, face swap, sketch, masks, outpaint and gallery/feed flows are still being tuned. Opening `/en` now would create a second public surface that must be kept visually and functionally identical during every UI iteration.

For this release stage, SEO is focused on the Russian production surface:

- `/` - main UI 2.0 entry point.
- `/paint` - drawing/sketch page.
- `/feed` - public feed page.
- `/gallery` - gallery page.
- `/robots.txt` - crawl rules.
- `/sitemap.xml` - canonical public URLs.
- `/static/og/izo-asa-og.jpg` - stable social preview image.

## What is already implemented

- Server-readable title, description, canonical, Open Graph, Twitter Card and JSON-LD for the main app shell.
- Server-readable title, description, canonical, Open Graph, Twitter Card and JSON-LD for `/feed`.
- Server-readable title, description, canonical, Open Graph, Twitter Card and JSON-LD for `/gallery`.
- Stable social image URL that is not tied to Vite hashed assets.
- `robots.txt` disallows private/technical routes such as `/api`, `/admin`, `/profile`, `/old`, `/legacy`, `/v1`, `/diag`.
- `sitemap.xml` lists only current canonical public pages.
- Client-side route metadata updates for active UI modes, including English browser-language titles/descriptions for the live client.

## Why not one URL with a language toggle only

A language toggle is good for users, but weak for SEO and social previews.

Search engines, ad crawlers and messengers usually read the first HTML response for a URL. They often do not execute the full React client. If `/` sometimes becomes Russian and sometimes English only after JavaScript runs, bots may index the wrong language or miss translated metadata.

When the UI is stable, the preferred architecture is:

- One component system.
- One layout.
- Two dictionaries: `ru` and `en`.
- `/` uses the Russian dictionary.
- `/en` uses the English dictionary.
- `/feed` and `/en/feed` share one page implementation.
- `/gallery` and `/en/gallery` share one page implementation.
- Each language URL has its own server-readable metadata.
- `hreflang` links connect Russian and English equivalents.

This avoids duplicated layouts while still giving crawlers clear language-specific URLs.

## Future production milestone

Open English routes only after:

1. UI 2.0 layout is frozen enough that we are no longer moving major page structures every day.
2. Feed and gallery headers/navigation are stable.
3. Paint/sketch/editor/face flows have passed regression checks.
4. A shared i18n dictionary layer exists, so English pages reuse the same components instead of copying markup.
5. Server/static HTML for English routes can be generated with correct title, description, canonical, Open Graph and JSON-LD before JavaScript runs.

Recommended future public routes:

- `/en`
- `/en/paint`
- `/en/feed`
- `/en/gallery`

Private pages such as profile/admin should remain `noindex` in every language.

## Rule for current work

Until the future milestone is reached:

- Do not add `/en` to `sitemap.xml`.
- Do not advertise `/en` in social previews or navigation.
- Keep Russian public SEO high-quality.
- Keep client-side English metadata only as preparation for future i18n, not as a public SEO promise.
