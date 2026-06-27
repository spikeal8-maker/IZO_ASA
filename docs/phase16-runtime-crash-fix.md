# Phase 16.4D — Production runtime crash fix (`Ce.slice is not a function`)

Emergency fix. No backend/auth/DB/generation changes. No secrets logged.

## Root cause
After generation/gallery protection landed, `GET /api/gallery` returns **401** for
unauthenticated users, with a JSON body `{"detail": "..."}` (an object, not an array).

Two frontend gallery loaders parsed that body and stored it directly in `gallery`
state:
- `src/App.tsx:678` (startup effect): `apiFetch('/gallery').then(r => r.json()).then(setGallery)`
- `src/App.tsx:634` (`fetchGallery`): `.then(r => r.json()).catch(() => [])` — `.catch`
  does NOT catch a resolved 401, so the `{detail}` object passed through.

`setGallery({detail})` made `gallery` a non-array, so the home/studio thumbnail strip
`gallery.slice(0, 6).map(...)` (`src/App.tsx:1190`) threw **`gallery.slice is not a
function`** during initial render. In the minified production bundle `gallery` is the
variable `Ce`, hence `Ce.slice is not a function`. Desktop showed the React error
screen; mobile WebViews rendered blank ("does not open").

Confirmed via sourcemap build: the only `Ce.slice(` in the bundle corresponds to the
gallery thumbnail map.

## Fix (type normalization at the source — no try/catch hiding)
`src/App.tsx`:
- line 678: `apiFetch('/gallery').then(r => r.ok ? r.json() : []).then(d => setGallery(Array.isArray(d) ? d : [])).catch(() => undefined)`
- `fetchGallery` (634): `.then(r => r.ok ? r.json() : []) ... setGallery(Array.isArray(images) ? images : [])`

`gallery` is now guaranteed to be an array, so `.slice/.map/.length/[0]` never crash,
regardless of auth state or response shape. (`Ce.slice(` still appears in the bundle —
that's the valid call on an always-array value.)

## Regression guard
`smoke-generation-lock.mjs`: asserts every `setGallery(...)` argument is
`Array.isArray`-guarded and that the raw `'/gallery' → json → setGallery` pattern is
gone.

## Tests / build
- `npx tsc -b` → 0 · `npx vite build` → 0 (clean dist, no sourcemap) → `index-DSBKHwTG.js`.
- smoke-auth-v2 / smoke-auth-modal / smoke-generation-lock → OK.

## Live verification
- `vite preview` serves `dist/` per request, so the rebuild went live automatically:
  live `/` now references `assets/index-DSBKHwTG.js`; no `/@vite/client`.
- **Playwright headless load (no secrets):**
  - `/` → `#root` renders 11241 chars, **no** slice/not-a-function error.
  - `/?diag=1` → `#root` renders 12543 chars, no crash.
  - Remaining console messages are expected 401/403 from protected endpoints (handled
    gracefully, not JS crashes).
- Backend probes: `/api/version` → 200, no-session `/api/generate` → 401,
  `/api/gallery` → 401.

## Mobile status
Not opened in this fix (no device access). The fatal JS crash that blanked mobile is
resolved (same bundle now renders in headless Chromium). Any remaining
Telegram/MAX-mobile "old version / won't open" is a separate platform cache/launch issue
— see docs/phase17-mobile-miniapp-diagnostics.md; do not mix it into this crash fix.

## Files changed
- `frontend/src/App.tsx` (2 lines: gallery loaders array-guarded).
- `frontend/smoke-generation-lock.mjs` (regression guard).
- `docs/phase16-runtime-crash-fix.md`.

Note: `APP_BUILD_LABEL` still reads `16.4A`; the definitive live marker is the asset
hash `index-DSBKHwTG.js`. Bump the label on the next intentional deploy.
