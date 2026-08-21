# MAX channel reliability package — 2026-08-21

## Scope and current boundary

This package improves MAX as the primary client channel while preserving the
working Telegram path. It does not change AdGuard VPN, FRP, webhook ownership,
provider tokens, production data or login-signature validation.

Observed before implementation:

- AdGuard VPN 2.9.6 already has the built-in `Max` exclusion enabled;
- that preset excludes `max.ru`, `oneme.ru` and `okcdn.ru`, so it also covers
  `platform-api2.max.ru` and `st.max.ru`;
- MAX uses one HTTPS webhook at `/api/max/webhook`; Telegram uses one polling
  worker, keeping delivery ownership exclusive;
- the frontend did not load the official MAX Bridge and only recognized legacy
  globals, so official `window.WebApp.initData` and MAX viewport height were not
  reliable inputs;
- both bots ignored ordinary non-command messages.

No AdGuard setting is changed. Excluding the whole backend or Python process
would be too broad because it would also move unrelated project traffic outside
the VPN. A custom routing script is therefore neither required nor introduced.

## Implemented architecture

1. `frontend/index.html` loads the official Bridge from
   `https://st.max.ru/js/max-web-app.js`; Caddy CSP allows that exact script
   origin, not arbitrary HTTPS scripts.
2. `frontend/src/maxBridge.ts` prefers official `window.WebApp`, keeps the two
   legacy shapes as compatibility fallbacks, and never logs or persists signed
   initialization data.
3. Signed `initData` continues to go to `/api/auth/max-v2`, where the existing
   server-side HMAC, timestamp and session rules remain authoritative.
4. `getViewportSize()` supplies `--app-viewport-height`; VisualViewport and
   `innerHeight` are safe fallbacks. Resize, rotation and foreground events
   refresh the value.
5. MAX-only CSS applies the measured height and safe-area insets to the studio
   and authentication modal without changing normal browser or Telegram layout.
6. `backend/app/services/bot_copy.py` provides deterministic Russian answers for
   login, generation, gallery, settings and problem topics. It makes no LLM or
   paid external calls and does not ask users for secrets.
7. Telegram and human-authored MAX text messages receive help. Bot-authored MAX
   events are explicitly ignored to prevent webhook reply loops.
8. The bot admin page distinguishes token checks from live delivery: Telegram
   polling success/failure counters and MAX subscription/incoming-event times
   are shown separately.

## Acceptance

- focused bot-copy, Telegram, MAX-update and login tests;
- auth/security-focused tests repeated five times because the MAX login path is
  security-sensitive;
- frontend lint and production build;
- Playwright mobile MAX Bridge check with stubbed official SDK: signed data,
  620 px provider viewport, modal bounds, horizontal overflow and page errors;
- Caddy CSP contract and generated architecture/symbol maps;
- clean release verification before any production promotion.

## Rollback

The code rollback is one commit: remove the official Bridge script/CSP origin,
`maxBridge.ts` and MAX-only CSS, then restore command-only bot handling. No VPN,
FRP, bot token, webhook subscription or database rollback is required.

## Verification evidence

Completed in the isolated feature worktree on 2026-08-21:

- focused backend and Caddy set: `53 passed`;
- security-sensitive MAX/login set: `50 passed` in each of five consecutive runs;
- complete backend/tools suite: `1777 passed`;
- frontend ESLint, immutable-label production build, release identity, origin
  isolation and studio-resilience browser test: passed;
- dedicated MAX Bridge test on the final production build: official
  `window.WebApp.initData` reached the MAX auth request, provider viewport
  `390x620` was applied, the auth modal stayed inside it, and no page error or
  horizontal overflow was observed;
- Caddy 2.11.4 pinned hash and candidate configuration: passed;
- `npm audit`: zero known vulnerabilities after patch-level transitive updates
  to `brace-expansion`, `nanoid` and `postcss`;
- generated backend, frontend and architecture maps: current.

The production service was not restarted or promoted during these checks.
Operational verification still requires one real human MAX message and one real
MAX Mini App login after a controlled deployment.

## Truthful status vocabulary

- `CODE COMPLETE`: code and local checks are green in the feature worktree.
- `DEPLOYED`: an exact committed SHA is the active release.
- `VERIFIED`: local and public health pass on that exact SHA.
- `OPERATIONALLY VERIFIED`: after deployment, a real human MAX message and a
  real MAX Mini App login have produced fresh redacted timestamps and the
  expected account identity. Provider token checks alone do not satisfy this.
