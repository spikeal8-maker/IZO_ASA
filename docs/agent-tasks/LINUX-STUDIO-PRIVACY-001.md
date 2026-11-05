# LINUX-STUDIO-PRIVACY-001

## Problem and authority

Base: `d5119571ec0aabecc114b1a5be65d98b313aa6c9`. The closed Linux stand reproduced A logout → B registration with A's result, download link and prompt still in Studio. Reload removed the result through backend authorization, but restored the unowned image prompt from session storage. A second reproduction retained B's result after logout to guest.

The package was registered with the normal agent lifecycle on 2026-11-05. Its four production paths are App, authV2, studioDraft and useStudioState. Resilience, media-helper and video-handoff paths were admitted with native `scope-add`; the registered manifest is retained byte-for-byte and its four-production-file limit is unchanged. The media helper remains unmodified. No backend, protected Studio hotspot, foreign package, generated map, provider or historical-data change is included.

## Change

- App waits for trusted cookie-auth resolution and keys the Studio subtree by account identity and identity generation. Different accounts, logout and expiry unmount the old React state and callbacks; an ordinary same-account profile or balance refresh preserves it.
- Password mutations and logout invalidate older auth reads. Logout immediately removes private UI and keeps the loading boundary until the logout HTTP response completes, preventing a new Studio login form from racing that response.
- Image drafts retain the existing storage key but require version 2 and the current trusted owner. Legacy or mismatched drafts are discarded. Autosave captures both owner and generation and rejects a late write, including A → B → A.
- App resolves an image handoff through the existing gallery, uploaded-source or feed `use-as` endpoint before mounting Studio. Only cached source, identifier and target select the request; prompt and media come exclusively from a fresh authorized response. Invalid, ambiguous, unavailable or unowned handoffs are discarded, including beside absent, corrupt or legacy image drafts.
- Preparation is shared across StrictMode subscribers, has an eight-second overall deadline and checks the captured owner, generation, operation and original storage value before publishing. A late response cannot overwrite a newer handoff or restore another account's data. A known owner transition removes both image and video handoffs before the next child mount.
- The pure draft serializer receives a read-only auth snapshot through App; it does not import React TSX or treat stored metadata as authentication. Storage failure remains nonfatal.

## Compatibility boundaries

First-mount video image handoff keeps its existing private-media check; its image prompt is not copied into the video textarea. This package does not strengthen that check's HTTP-cache freshness. All original `e2e-video-image-handoff.mjs` scenarios remain required compatibility checks. Same-owner in-page image-to-video actions keep their existing path.

Existing gallery/feed image, editor, draw, face and prompt transfers are preserved through authorized reconstruction; cached payload fields are never a fallback on failure. The existing unowned VideoStudio localStorage draft and general private-media HTTP-cache freshness are outside this package; this change does not claim complete video draft privacy. Backend foreign-job and foreign-media denial must remain enabled and be checked on the installed candidate.

## Verification

The new Node behavior controls cover owner recovery, guest/account isolation, legacy rejection, stale autosave, storage errors, attribution integrity, authorized reconstruction, StrictMode, delayed responses and the overall deadline. The first implementation passed 13 controls and failed four subsequently added handoff regressions. The original source fails the ownership regressions.

The browser fixture extends the existing desktop/mobile profile suite with same-owner refresh, held logout, A → guest → B registration without reload, legacy/no-draft/corrupt-draft rejection, direct account switching, delayed A gallery/auth responses and session expiry. It uses Vite's real frontend auth module with explicit API fixtures; run it against Vite dev, not built preview. The existing video suite retains its scenarios and adds fresh image-handoff allow/deny checks while media itself remains available. These are fixture regressions, not installed real-backend or real HTTP-cache evidence.

The first server snapshot passed the 13 Node controls on Node 22, auth smoke, TypeScript, ESLint, production build, origin verification and frontend-map `--check`. Every final candidate requires its own focused server receipts, video/resilience tests, native scope/file hygiene, independent review, exact-head hosted CI and installed desktop/mobile acceptance. The new Node suite and profile-auth suite are explicit focused gates: the existing mandatory CI does not automatically run them. Earlier snapshot results do not prove the final candidate.

## Execution and rollback

Only the exact reviewed package is eligible for publication. Installed acceptance must include both test accounts, logout/session expiry, foreign-resource denial and a restart with persistent data. A synthetic browser/API fixture does not replace that acceptance.

Rollback restores the preceding reviewed frontend package and rebuilds its exact source release. SQLite, media, worker behavior, historical volumes and ownership state are outside this change.
