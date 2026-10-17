# Phase 17 — Telegram/MAX Mobile Diagnostics (after stable dist serving)

Diagnosis only. No auth/business/DB changes. No raw initData/WebAppData/user ids/
tokens printed. The live site now serves built dist (Phase 16.4B/C).

## Block 1 — Public build verified
- `/` has **no** `/@vite/client`, **no** `/src/main.tsx`; serves hashed
  `assets/index-dzsBkfKd.js`.
- `/api/version` → `build = 16.4A-2026-06-26`; the same `APP_BUILD_LABEL` string is
  baked into the live JS bundle (so `?diag=1` shows it).
- No-session `/api/generate` → 401, `/api/gallery` → 401.

## Block 2 — Diagnostics capability (adequate; no change)
`?diag=1` (or `#diag`) panel shows booleans/labels only:
frontend.build, backend.build, backend.auth_v2, backend.generation_protected,
auth.state; delivery: origin, **path only**, hasSearch, hasHash,
isViteDevClientPresent, hasHmrClient; `tg.*`: hasTelegram, hasTelegramWebApp,
hasTelegramInitData, initDataLengthCategory(zero/nonzero), readyCallable,
expandCallable; `max.*`: hasMaxGlobal, hasWebAppGlobal, hasMaxWebAppData,
hasMaxInitData, hasHashWebAppDataParam, userAgentMaxLike, mobile.
No raw search/hash/initData/WebAppData/userId is ever shown.

## Block 3 — Telegram mobile (operator records via ?diag=1)

| field | Browser | TG Desktop | TG Mobile |
|-------|---------|-----------|-----------|
| frontend.build | | | |
| hasTelegram | | | |
| hasTelegramWebApp | | | |
| hasTelegramInitData | | | |
| initDataLengthCategory | | | |
| readyCallable | | | |
| expandCallable | | | |
| path | | | |

Interpretation:
- Mobile build label **differs** from desktop → Telegram mobile **cache** or old Mini
  App URL (most likely, since we just switched to dist).
- Build label **same** but UI looks old → route/state/render, not delivery.
- `hasTelegramInitData=false` inside Telegram → Mini App opened the wrong way / initData
  not passed (e.g. opened as a plain link, not via the WebApp button).
- `path` differs → an old URL/deep link/menu button is configured.

## Block 4 — Telegram config checklist (owner)
- BotFather → Bot Settings → Menu Button / Web App URL: must be `https://izo.alikinas.ru/`.
- Any inline-button / `startapp` deep-link URL pointing at the app.
- Confirm the configured URL has no stale path/query.
- Force-close Telegram (swipe-kill), reopen the Mini App from the bot button.
- Cache-bust: set the Mini App URL to `https://izo.alikinas.ru/?v=16.4A-2026-06-26`
  (bump on each deploy). Do NOT change config without owner confirming the exact URL.

## Block 5 — MAX mobile (operator records via ?diag=1)

| field | Browser | MAX Desktop | MAX Mobile (if it opens) |
|-------|---------|-------------|--------------------------|
| frontend.build | | | |
| hasMaxGlobal | | | |
| hasWebAppGlobal | | | |
| hasMaxWebAppData | | | |
| hasMaxInitData | | | |
| hasHashWebAppDataParam | | | |
| userAgentMaxLike | | | |
| mobile | | | |
| path | | | |

If MAX Mobile does **not** open at all, collect (no raw data):
- exact Mini App URL configured in MAX bot/admin settings;
- allowed domains list;
- HTTPS status on mobile (cert trusted in the mobile WebView?);
- whether the mobile launch URL / deep link differs from desktop;
- mobile WebView error **category** only (network / cert / blank / JS error);
- which global MAX injects on mobile (`window.MAX` vs `window.maxWebApp` vs none) —
  read from the diag `max.*` booleans.

## Block 6 — Possible low-risk fixes (PROPOSED, not applied)
1. Set Mini App URL to root with cache-bust: `https://izo.alikinas.ru/?v=<APP_BUILD_LABEL>`.
2. Ensure the URL is exactly `https://izo.alikinas.ru/` (root path).
3. Ensure `izo.alikinas.ru` is on the MAX domain allowlist for **mobile** launch.
4. Code (only if diag shows `max.hasHashWebAppDataParam=true` while
   `max.hasMaxWebAppData=false` on mobile): extend MAX detection to also read
   WebAppData from the URL hash. This is an auth-behavior change → do it as its own
   small, tested phase, not here.

## Root-cause hypotheses (ranked)
1. **Telegram Mobile = stale cache / old Mini App URL** (high). The dist switch is new;
   Telegram mobile caches the previous page. Fix = force-close + `?v=` cache-bust.
2. **MAX Mobile = config/launch** (high): wrong/缺 mobile Mini App URL, domain not
   allowlisted for mobile, or a mobile-only launch/deep-link difference. Desktop works
   with the same bundle, so it is not a bundle/JS-crash issue.
3. **MAX mobile passes WebAppData via URL hash, not a JS global** (medium): only an
   issue once the page loads; revealed by `max.hasHashWebAppDataParam`.
4. Frontend render/route issue (low): same bundle works on desktop.

## Confirmations
- no raw platform data exposed (booleans/labels only)
- no auth/business logic changed; no DB changed; no new feature started
