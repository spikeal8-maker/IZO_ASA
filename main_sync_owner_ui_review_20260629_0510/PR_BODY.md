## Purpose

Freeze the manually verified owner UI recovery as the new safe baseline and integrate it safely on top of the current `origin/main` without merging 20E.2G tariff/gallery work.

## Baselines

- Safe live owner baseline branch: `safe-baseline-owner-ui-20260629`
- Safe live owner baseline commit: `a39faa5cd3e994d13eec9c65025fe08ddfee4330`
- Safe baseline tag: `safe-owner-ui-baseline-20260629-a39faa5`
- Existing historical live tag: `safe-owner-ui-live-20260629` dereferences to `e9e5fa1d61b37b2a7176ea8084ee18cb9bf4f885`
- Integration base: `origin/main` at `f64cfa8e1fcdcb6a2b51f6b2bcd2a46a7ee8af9e`
- Integration commit: `2cb76ebda9dcddce929c64e80b1d7fd6963e466a`

## Preserved `origin/main` work

This branch was created from latest `origin/main`, so these team commits remain in history:

- `f64cfa8` Bump frontend label for DB safety guard
- `49d49a6` Add production DB safety guard
- `aeeed6e` Bump backend build label for 20E.2C
- `f456014` Bump live build label for 20E.2C
- `ef3f44b` Fix CRM plan gallery promo consistency

## Files changed by integration

- `backend/main.py`
- `backend/test_api.py`
- `frontend/editPrompt.test.ts`
- `frontend/public/avatars/preset-*.svg`
- `frontend/src/App.tsx`
- `frontend/src/adminAnalytics.tsx`
- `frontend/src/authV2.tsx`
- `frontend/src/editPrompt.ts`
- `frontend/src/index.css`

## Verification

- `npx tsc -b` passed
- `npx vite build` passed
- Backend relevant tests passed: `78 passed`
- `npm run smoke:generation-lock` passed
- `node smoke-admin-analytics.mjs` passed

## Visual review package

Local mocked UI screenshots, no live DB and no live credentials:

`D:\Google Drive\My progact\Генератор картинок\main_sync_owner_ui_review_20260629_0510`

Includes Studio, Draw, prompt/edit, Settings, Gallery, Admin, CRM table, CRM card, and mobile checks.

## Safety notes

- No deploy performed by this PR preparation.
- No direct push to `main`.
- No force push.
- No `origin/main` pull/merge into owner recovery branch.
- No DB mutation.
- No owner/admin account mutation.
- No 20E.2G tariff/gallery branch merge.
- `phase-20e2c-clean` / `ef9ae411d2afa3fac8a7bcc1c7fd342080c4d0f4` remains separate.

## Follow-up

`smoke-auth-v2` and `smoke-auth-modal` still need selector maintenance for the restored owner Settings/auth layout. UI should not be changed just to satisfy old selectors.
