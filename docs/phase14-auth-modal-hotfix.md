# Phase 14.2 — Auth Modal Hotfix + Telegram/MAX Diagnostics

Frontend-only hotfix. No backend / DB / generation / gallery / templates changes.

## Root cause
- The auth form rendered inside the normal layout flow (the modal was a child of
  `<div className="app-shell">`). Even with `position:fixed` CSS, rendering inside
  the app layout left it fragile to ancestor stacking/overflow contexts, so on
  desktop/mobile it pushed/overlapped the interface instead of floating above it.
- Fix: render the modal through a **React portal into `document.body`** with a true
  fixed overlay, so it can never affect the app layout.
- Settings "Войти": it called `openAuthModal()`; before the portal fix the modal it
  opened was the broken in-flow one, so it appeared not to work. With the portal it
  opens a proper centered/bottom-sheet dialog.
- Telegram button: correctly disabled in a plain browser (no `initData`); it only
  becomes active inside a Telegram Mini App. That is expected behavior, not a bug.

## Files changed
- `frontend/src/authV2.tsx` — `createPortal`; modal portaled to body; Esc + backdrop +
  X close; background-scroll lock; `telegramDiagnostics()` / `maxDiagnostics()`
  (booleans only); `notifyTelegramReady()` (ready/expand); `window.__authDiagV2`.
- `frontend/src/App.tsx` — (already) locked CTA opens modal; modal mounted at root.
- `frontend/src/index.css` — overlay `position:fixed; inset:0; z-index:9999;` backdrop;
  card `width: min(460px, calc(100vw - 32px))`; mobile bottom-sheet (`dvh`).
- `frontend/smoke-auth-modal.mjs` — portal/overlay/diagnostics checks; package.json script.
- `docs/phase14-auth-modal-hotfix.md` — this file.

## Modal fix
- **Portal:** `createPortal(<overlay/>, document.body)`.
- **Overlay:** `position:fixed; inset:0; z-index:9999;` dark backdrop; flex-centered.
- **Desktop:** card 460px (`max-width: calc(100vw - 32px)`), padded, rounded, inputs/
  buttons constrained inside the card.
- **Mobile (≤560px):** bottom-sheet — full width, `max-height: 92dvh`, internal
  `overflow-y:auto`, rounded top; background scroll locked while open.
- **Close:** X button, Esc key, backdrop click. `role="dialog"`, `aria-modal="true"`,
  `aria-labelledby`.

## Generation lock UX
- Single CTA with lock icon: desktop "🔒 Войдите, чтобы генерировать", mobile "🔒 Войти"
  (`lock-cta-full`/`lock-cta-short` swapped by media query — only one shows).
- Click opens the modal (`setAuthModalOpen(true)`); never opens Settings; never calls
  `generate()`.

## Settings UX (logged out)
- `if (!isAuthedV2)` → a single "Войдите, чтобы управлять аккаунтом" card + "Войти"
  button that opens the same modal. No tokens/promo/subscription/quality/megaspeed/size.
- Legacy `web_demo_user` "Вход выполнен" is gated behind the authed branch only.

## Telegram diagnostics
- Detection: `telegramDiagnostics()` → `{ hasTelegram, hasWebApp, hasInitData }` (booleans
  only). Available on `window.__authDiagV2.telegram()`.
- Behavior: button active only when `initData` is present; sends **raw** `initData` to
  `/api/auth/telegram-v2`; never uses `initDataUnsafe.user.id`; calls `ready()`/`expand()`
  when in a Telegram WebView. initData is never logged or shown.

## MAX diagnostics
- Detection: `maxDiagnostics()` → `{ hasMax, hasWebApp, hasWebAppData, hasInitData }`
  (booleans only). Available on `window.__authDiagV2.max()`.
- Behavior: if raw WebAppData/initData is present, send it to `/api/auth/max-v2`; never
  send a MAX userId as identity; otherwise the button is disabled with
  "Доступно в мини-приложении".
- **Mobile launch issue — not resolvable from frontend code alone.** The frontend now
  reads `MAX.WebApp.webAppData` / `MAX.WebApp.initData` / `maxWebApp.webAppData` and does
  not depend on any desktop-only object for *detection*. Why mobile MAX may not launch
  needs MAX-side info (collect in the MAX mobile WebView console — booleans/categories
  only, no raw data):
  1. Mini App **URL** registered in MAX (does it match `https://izo.alikinas.ru`?).
  2. **Domain allowlist** for the Mini App.
  3. Separate **mobile launch URL / deep link** configured?
  4. **HTTPS certificate** valid on mobile (some mobile WebViews are stricter).
  5. **Mobile WebView console**: any JS crash on load? capture error *category*, not text.
  6. Which **global object** mobile MAX injects (`window.MAX`? `window.maxWebApp`? other?)
     and whether `webAppData`/`initData` is populated there — read via `__authDiagV2.max()`.
  7. **viewport / safe-area** — confirm the page renders (not a blank crash).

## Tests / build
- `npx tsc -b` → exit 0; `npx vite build` → exit 0.
- `smoke-auth-v2` OK · `smoke-generation-lock` OK · `smoke-auth-modal` OK.

## Manual checklist
Desktop: locked CTA tidy → click → centered modal (page not shifted) → close X/Esc/backdrop
→ Settings "Войти" opens same modal → logged-out Settings is the single CTA card.
Mobile: locked CTA intact → modal is a bottom-sheet that fits → bottom nav unaffected →
email flow visible.
Telegram: open in Mini App → Telegram button active only if initData → login sends raw
initData. MAX: desktop → `__authDiagV2.max()` booleans; mobile → check the 7 items above.
