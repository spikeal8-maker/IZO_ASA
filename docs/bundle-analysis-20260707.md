# Bundle analysis, 2026-07-07

## Goal

Make the new UI route (`/new`) stop paying for the old interface, legacy paint editor, admin screens, and Konva canvas code.

## Before

After the first `/paint` split, the build still had a large startup chunk:

- `index-*.js`: ~825 KB raw, ~238 KB gzip.
- `newUi-*.js`: ~127 KB raw, ~32 KB gzip.
- `PaintWorkbench-*.js`: ~5.7 KB raw, ~2.1 KB gzip.

Sourcemap groups inside the old `index` chunk:

- `konva`: ~181 KB;
- `react-reconciler`: ~116 KB;
- `react-konva`: ~8 KB;
- `src/App.tsx` legacy UI: ~172 KB;
- admin screens: ~73 KB;
- `react-dom`: ~178 KB.

Problem: `/new` loaded the startup `index` chunk first, so the new UI still paid for the old root app and old drawing editor.

## Changes

- `src/App.tsx` is now a small route router.
- The previous monolithic root app moved to `src/LegacyApp.tsx`.
- `src/newUi.tsx` is lazy-loaded only for new UI routes.
- `src/PaintWorkbench.tsx` remains lazy-loaded only when the paint workbench is visible.
- Legacy admin screens (`adminAnalytics`, `adminModels`) are lazy-loaded inside `LegacyApp`.

## After

Production build without sourcemaps:

- `index-DpgDTAez.js`: 193.99 KB raw, 61.61 KB gzip.
- `newUi-D4F9FkrY.js`: 127.26 KB raw, 32.47 KB gzip.
- `PaintWorkbench-Dm6trQWP.js`: 5.77 KB raw, 2.18 KB gzip.
- `ReactKonva-Cne9-PzF.js`: 306.35 KB raw, 93.14 KB gzip.
- `LegacyApp-CWayUt3p.js`: 216.02 KB raw, 56.42 KB gzip.
- `adminModels-Bs1DTOav.js`: 28.04 KB raw, 6.97 KB gzip.
- `adminAnalytics-BOTFxdpC.js`: 50.60 KB raw, 12.32 KB gzip.

Route resource checks:

- `/new`: loads `index`, `newUi`, shared new UI chunks and CSS. Does not load `LegacyApp`, `ReactKonva`, or `PaintWorkbench`.
- `/paint`: loads `index`, `newUi`, `PaintWorkbench`, and `ReactKonva`.
- `/`: loads `index`, `LegacyApp`, and `ReactKonva` because the old interface still includes the legacy paint editor.

Approximate JS heap after route load in headless Chrome:

- `/new`: used JS heap ~3.15 MB.
- `/paint`: used JS heap ~4.49 MB.
- `/`: used JS heap ~4.03 MB.

These heap numbers are comparative smoke metrics, not a full runtime memory profile.

## Current conclusion

The new page is no longer blocked by the old monolith. The remaining weight on `/new` is mainly:

- React/ReactDOM startup in `index`;
- `newUi` itself;
- shared new UI CSS.

The old interface is still intentionally available, but now isolated behind `LegacyApp`.

## Next cleanup candidates

- Split or retire `LegacyApp` after the new UI fully replaces the old interface.
- Split large CSS files by route if first-paint CSS becomes the next bottleneck.
- Reduce `newUi.tsx` by extracting feed/gallery/profile/editor submodules after behavior stabilizes.
- Keep `/paint` canvas features inside `PaintWorkbench` or further lazy submodules, not in `newUi.tsx`.

