# UI 2.0 `/new` Plan

This document is the working contract for the experimental `/new` UI. It must be
updated whenever `/new` behavior, files, API contracts or acceptance criteria change.

## Status

Current status: WIP / not accepted for deploy.

The `/new` route is experimental and must not replace `/` until it passes the acceptance
checklist below and the owner explicitly approves.

## Goal

Create a modern UI 2.0 at `/new` while keeping the current production UI at `/`
stable. `/new` should gradually take over the real product flows:

- feed/social placeholder;
- text-to-image;
- image-to-image;
- editor/draw/face sections;
- gallery;
- settings/help;
- auth through existing auth v2;
- generation through existing backend APIs.

## Boundaries

Allowed files for `/new` work:

- `frontend/src/newUi.tsx`
- `frontend/src/newUi.css`
- `frontend/src/stylePresets.ts`
- minimal route hook in `frontend/src/App.tsx`
- `docs/new-ui-v2-plan.md`
- `docs/new-ui-v2-review.md`
- targeted tests or visual scripts for `/new`

Forbidden without separate approval:

- `backend/main.py`
- `frontend/src/authV2.tsx`
- Telegram/MAX/email auth
- tariffs/gallery backend
- dashboard/admin unrelated UI
- billing
- production deploy scripts
- DB schema/data

## Security Rules

`/new` must use trusted cookie auth only.

Forbidden in `frontend/src/newUi.tsx`:

- `X-OneNode-User`
- `onenode_user`
- `demo_user`
- query/body `userId` as auth

Required API pattern:

```ts
fetch(url, { credentials: 'include' })
```

If the user has no session, generating must open the real auth modal. It must not create
or impersonate a demo user.

## Route Design

- `/` remains the current production UI.
- `/new` renders UI 2.0.
- The route switch in `App.tsx` must be minimal.
- `/new` styles must be scoped under a root class such as `.n2`.

## Tabs

### Feed

Purpose: future social/public feed.

Current allowed state:

- placeholder;
- clear text that public feed is future work;
- no fake claim that likes/comments/publication are live unless backend exists.

### Text to Image

Must use:

- prompt input;
- templates;
- style presets;
- format/aspect ratio;
- resolution preset;
- generate button;
- job progress;
- result preview;
- recent/gallery reuse where applicable.

Generation API:

- `POST /api/generate`
- `GET /api/jobs/{id}`

### Image to Image

Must use:

- upload from file;
- choose from gallery;
- use last/generated image where safe;
- prompt/transform instructions;
- strength control;
- same generation job flow.

Large uploaded images must not be sent to ComfyUI at raw huge resolution. Backend should
downscale according to project limits; frontend may preview full image but must not imply
raw source resolution is the generation resolution.

### Editor / Draw / Face

If not fully implemented, mark as future/placeholder in UI and documentation. Do not
pretend unavailable workflows are production-ready.

## Shared Presets

`frontend/src/stylePresets.ts` may be shared between `/` and `/new`.

Rules:

- changes must preserve current `/` behavior unless explicitly approved;
- if prompt/style data changes, verify both `/` and `/new`;
- images used for style previews must be optimized and stable assets;
- user gender/age-specific previews are future/product work unless fully implemented
  and stored in profile/CRM correctly.

## API Contracts

`POST /api/generate`

- requires trusted session;
- returns 401/403 without session;
- creates a job when accepted;
- may return 402 for insufficient tokens;
- may return 429 for rate limit.

`GET /api/jobs/{id}`

- returns job status/progress/result/error;
- completed jobs should expose safe result URL.

`GET /api/gallery`

- requires trusted session;
- returns current user's gallery items only.

`GET /api/me-v2`

- source of auth/account state.

## Desktop Layout Rules

Target desktop: 1440x900 and wider.

- Main controls must fit without hiding the generate button.
- Generate button should remain reachable.
- Preview/result area must be visually dominant.
- Style/template galleries must not overlap other controls.
- Hover states should help discovery without shifting layout.

## Mobile Layout Rules

Target mobile: 375x812.

- Page must scroll.
- Sticky bottom controls must not cover required inputs permanently.
- Preview appears between prompt and lower controls where needed.
- Empty preview may be compact; after generation it should follow image aspect ratio.
- Template/style modal must have a visible close button.
- Buttons must remain tappable.

## Acceptance Checklist

Required before claiming `/new` ready:

- `npx tsc -b`
- `npx vite build`
- `/` opens and current UI still works
- `/new` opens
- desktop screenshot 1440x900
- mobile screenshot 375x812
- no `X-OneNode-User`, `onenode_user`, `demo_user` in `newUi.tsx`
- auth modal opens without session
- generate without session does not create a job
- generate with session creates a job
- job polling completes
- result image displays
- gallery opens
- image from gallery can be used in image-to-image
- mobile scroll works in every implemented tab
- known gaps documented in `docs/new-ui-v2-review.md`

## Definition of Done

`/new` can be considered ready for owner visual review only when:

- all acceptance checklist items are complete;
- no legacy auth path exists;
- old `/` is not regressed;
- screenshots are saved and referenced;
- docs are updated;
- no unrelated backend/auth/admin/tariff changes are mixed in.

