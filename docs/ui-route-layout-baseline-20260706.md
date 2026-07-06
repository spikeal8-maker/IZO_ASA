# UI Route and Layout Baseline - 2026-07-06

This document freezes the current visual/topology state after the `/new`
Text-to-Image MVP release. Use it when comparing future UI changes, discussing
"old/new scale", or adding a future scale/view switcher.

## Production Topology

- Public frontend: `https://izo.alikinas.ru`
- Live preview process: `127.0.0.1:5173`
- Served build at capture time:
  - JS: `assets/index-DQEnT2L7.js`
  - CSS: `assets/index-BV9oev_x.css`
- Branch/worktree used for the frozen build:
  - `D:\Google Drive\My progact\wt-integrated`
  - branch: `feature/new-ui-v2-integrated-safe`
  - code commit: `465c9a9`
  - release-doc commit: `b27b3cc`

`https://izo.alikinas.ru/*` and `http://127.0.0.1:5173/*` were byte-identical
for the frontend assets above at capture time.

## Route Roles

Current route meanings:

- `/news` - legacy studio route. This is the old/current production studio
  layout and scale. It uses the old `.app-shell`, `.mode`, `.icon-button`,
  `.preview-panel` styling.
- `/new` - new v3 studio route. This is the frozen Text-to-Image MVP shell.
  It uses `.iv3`, `.n2`, `TopBarV3`, `.sidebar`, `.preview-panel`,
  `.result-dock`.
- `/feed` - live public feed route using the v3 top bar and feed layout.
- `/gallery` - separate gallery page. It mounts the real working gallery flow
  inside the new wrapper instead of duplicating gallery logic in `/new`.
- `/profile` - separate profile/settings page. It mounts the real working
  settings flow inside the new wrapper.

Planned route direction:

- Keep complex workflows as separate pages when they need large dedicated code:
  gallery, profile/settings, feed, drawing/canvas, editor.
- The drawing/canvas workflow should become its own dedicated route/page before
  it grows into a large editor surface.
- A future "old/new scale" switcher should be treated as a visual mode or route
  preference, not as browser zoom.

## Scale Terminology

There is no browser/CSS zoom difference between `/news` and `/new`:

- body font size: `16px` on both routes;
- effective zoom: `1`;
- the perceived scale difference comes from different component CSS and layout
  structure.

Recommended terms:

- `legacy studio scale` - `/news`
- `v3 studio scale` - `/new`

Avoid calling this a browser zoom mismatch.

## Desktop Baseline

Captured at viewport `1440x900`.

| Metric | `/news` legacy studio | `/new` v3 studio | Difference |
| --- | ---: | ---: | ---: |
| Topbar height | `50px` | `62px` | v3 is `+24.0%` taller |
| Preview width | `863px` | `904px` | v3 is `+4.8%` wider |
| Preview height | `560.5px` | `653.5px` | v3 is `+16.6%` taller |
| Main mode/tab font | `16px` | `14.5px` | v3 is `-9.4%` smaller |
| Top navigation font | `20px` | `14px-14.5px` | v3 is about `-27%` to `-30%` smaller |

Interpretation:

- `/new` gives more space to the image/preview work area.
- `/new` makes navigation and tab labels denser.
- `/news` keeps larger legacy navigation buttons.

## Mobile Baseline

Captured at viewport `375x812`.

| Metric | `/news` legacy studio | `/new` v3 studio | Difference |
| --- | ---: | ---: | ---: |
| Preview width | `355px` | `359px` | v3 is `+1.1%` wider |
| Preview height | `199.7px` | `278.7px` | v3 is `+39.6%` taller |
| Tab/button height | `34px` | `27px` | v3 is `-20.6%` shorter |
| Tab font | `11px` | `9.9px` | v3 is `-10.0%` smaller |
| First tab width | `114.3px` | `75.8px` | v3 is `-33.7%` narrower |

Interpretation:

- `/new` makes the mobile preview substantially taller.
- `/new` compresses mobile navigation so more modes fit in the top bar.
- `/news` uses wider, chunkier legacy mode buttons.

## Future Switcher Notes

If a future switcher is added, recommended product options:

- `Legacy scale` / `Old studio` - opens or emulates `/news`.
- `New scale` / `V3 studio` - opens or emulates `/new`.

Implementation guardrails:

- Prefer route-level switching first (`/news` vs `/new`) while both routes exist.
- If implemented inside settings/profile, store it as a user preference such as
  `preferred_studio_route` or `studio_layout_mode`, not as raw CSS zoom.
- Do not use browser zoom or global `zoom:` CSS to force parity; that will break
  mobile, modals, and sticky controls.
- Before changing either scale, recapture the same two viewports:
  `1440x900` desktop and `375x812` mobile.

## Capture Method

Measured with Playwright against:

- `http://127.0.0.1:5173/news`
- `http://127.0.0.1:5173/new`
- `https://izo.alikinas.ru/news`
- `https://izo.alikinas.ru/new`

The live and local measurements matched for the routes above.
