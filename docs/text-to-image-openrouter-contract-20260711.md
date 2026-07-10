# Text-to-image model contract — 2026-07-11

This document is the working contract for the first studio tab (`text_to_image`) before
OpenRouter support is enabled in the other tabs.

## Request flow

`prompt -> style suffix -> model -> supported format -> server price -> token charge -> queue -> provider -> gallery/result`

The frontend may present model and price information, but the backend remains the source
of truth for tariff access, request normalization, billing and token refunds.

## Local model

- Public id: `server:local_flux_klein`.
- Provider: `comfyui`.
- Every `text_to_image` request is normalized by the backend to exactly four steps.
- A client value such as 6, 10 or 28 cannot override the four-step invariant.
- An identical completed/submitted request is blocked in the current browser session to
  protect against an accidental repeat.
- A changed prompt, model or format is a new request.

## OpenRouter models

- OpenRouter is enabled only for `text_to_image` at this stage.
- The backend checks that the selected model is enabled for both the mode and user plan.
- Intentional identical repeats are allowed; every click creates a new request id.
- The active-job lock still prevents double submission while a request is in flight.
- Provider-specific format normalization and the server billing estimate are authoritative.
- OpenRouter currently receives model, prompt, image count and provider-safe size. Seed,
  steps, CFG, guidance and negative prompt must not be advertised as supported controls.

## Public model contract

`GET /api/model-access` returns the models available to the authenticated plan. Each model
includes a `generation` contract:

- `fixedSteps`: fixed server-owned step count or `null`;
- `allowsExactRepeat`: whether a deliberate identical follow-up request is allowed;
- `supportsSeed`: whether seed is a meaningful provider control.

The frontend preserves the server label, provider, profile, token hint and generation
contract. Its static model data is a fallback for a temporarily unavailable endpoint, not
the primary product catalog.

## UI rules

- Standard quality presets display the actual model used by each preset.
- Unsupported formats are disabled for the selected model.
- Changing quality or a Pro model corrects an incompatible format in the same interaction.
- The result dock stays disabled until a real gallery/result image is selected.
- Draft prompt text is not labeled as an image prompt.
- Submission history for this guard is isolated to the text tab; other studio tabs cannot
  overwrite it.

## Verification

- Backend: local text requests are stored with `steps = 4`.
- Backend: public model access exposes Local and OpenRouter generation contracts.
- Frontend: `smoke:text-contract` protects repeat, steps, isolation and result-dock rules.
- Frontend: production TypeScript/Vite build passes.
- Desktop 1440x900 and mobile 390x844 have no quality-button overflow or browser errors.

## Deferred before other tabs

- Run a controlled real generation for every enabled OpenRouter model and compare billed
  tokens, returned dimensions and gallery metadata.
- Replace remaining static fallback descriptions with a fully server-managed catalog.
- Add authenticated browser E2E for model selection, paid generation, result and refund.
- OpenRouter image-input adapters remain disabled for `image_to_image`, `edit`, `paint`,
  `inpaint`, `outpaint`, `faceswap` and `remove_background` until each adapter has its own
  validated input and billing contract.
