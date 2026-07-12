# OneNode Image Studio Test Plan

## Automated Backend/API Coverage

- Stage 1 shell: Web/Telegram/MAX bootstrap endpoints, platform readiness endpoint, SQLite database presence.
- Database persistence: jobs and images are written to SQLite and survive outside in-memory state.
- Bot commands: Telegram/MAX webhook handlers return Mini App buttons for `/start`, `/app`, `/help`, `/gallery`, `/settings`.
- Bot modes: disabled mode keeps local adapter tests without background updates; Telegram send/polling endpoints require `TELEGRAM_BOT_TOKEN`; polling disables the public Telegram webhook receiver.
- Telegram webhook security: webhook mode requires a valid `TELEGRAM_WEBHOOK_SECRET`, registration sends `secret_token`, the official header is compared in constant time, oversized/malformed bodies are rejected, and repeated integer `update_id` values are acknowledged without reprocessing.
- MAX webhook security: polling keeps the receiver closed; webhook mode requires an official-format `MAX_WEBHOOK_SECRET`, subscription creation always sends it, the header is compared in constant time, and oversized/malformed bodies are rejected.
- Launcher mode safety: `start-public.bat` must not switch MAX from the proven polling mode to webhook implicitly.
- Health: API responds and reports ComfyUI/FluxKleinOneNode availability fields.
- Generation modes: `text_to_image`, `image_to_image`, `edit`, `paint`, `inpaint`, `outpaint`, `faceswap`.
- Providers: ComfyUI path calls the ComfyUI adapter, OpenRouter path does not.
- ComfyUI workflow adapter: selects installed model/text encoder/VAE, patches One Node workflow JSON, reads `/history`, downloads `/view`.
- ComfyUI failure mode: missing ComfyUI fails clearly when mock fallback is disabled.
- ComfyUI media adapter: extracts standard `history.outputs[*].images`, downloads `/view`, saves PNG and thumbnail.
- Workflow mode patching: text-to-image, image-to-image and face-swap node wiring is verified at node-id level.
- Canvas input fallback: Paint canvas JSON is converted into a raster input for the current ComfyUI edit workflow.
- Job lifecycle: `queued`, progress updates, `completed`, `cancelled`, validation errors, 404 for missing jobs.
- Media: result PNG and thumbnail WebP are saved into the gallery.
- Gallery: all generated images are listed with mode, provider, prompt, seed, dimensions, model profile, LoRA and timestamps.
- Stage 3: Text to Image, Image to Image and Edit Image are verified end-to-end; gallery detail, favorite, delete and Use as are covered.
- Utility endpoints: prompt translation, presets, Telegram webhook, MAX webhook, admin summary.

## Automated Frontend Coverage

- TypeScript compile and Vite production build.
- ESLint pass.
- UI smoke markers: all required modes, Telegram/MAX readiness, Gallery, Presets, Settings, Admin, Use as, Konva canvas, responsive CSS.

## Manual Acceptance Checklist

- Open `http://127.0.0.1:5173` on desktop and mobile width.
- Switch RU/EN.
- Generate text-to-image and verify progress/result/gallery.
- Upload one image for Image to Image/Edit/Inpaint/Outpaint.
- Upload two images for Face Swap.
- Draw in Paint and Inpaint canvas.
- Open Gallery detail and use `Use as...` into another mode.
- Switch provider to OpenRouter and confirm unsupported controls/modes are limited.
- Open Admin and verify jobs/errors/statistics update.
- Check `/api/health` reports `fluxKleinOneNode: true` when ComfyUI custom node is installed.
- Check `/api/models` returns the installed Flux Klein model, text encoder, VAE and LoRA lists.

## UI 2.0 `/new` Smoke Checks

The experimental `/new` page must be checked separately from the current `/` UI.

- `/` still opens and the existing user flow is unchanged.
- `/new` opens without crashing on desktop 1440x900 and mobile 375x812.
- No `X-OneNode-User`, `onenode_user` or `demo_user` auth path exists in `frontend/src/newUi.tsx`.
- Without a session, clicking generate opens the auth modal and does not create a job.
- With a valid session, text-to-image starts a job, polls `/api/jobs/{id}`, and renders the result image.
- Local HTTP auth-cookie check: login/register on `http://127.0.0.1:8000` must set
  `onenode_session`/`onenode_refresh` without `Secure` and with `SameSite=lax`; `/api/me-v2`
  must remain `200` with the same cookie after backend restart. Public HTTPS must keep
  production cookie flags from env. See `docs/auth-cookie-local-production-guide-20260708.md`.
- Image-to-image can use an uploaded image and an image selected from gallery.
- Gallery opens, shows real user images, and does not leak images without auth.
- Mobile scroll works in every `/new` tab; sticky generate controls do not cover required inputs.
- Build checks pass: `npx tsc -b` and `npx vite build`.

## Current Automated Commands

```powershell
.\tools\verify.ps1 -Mode Quick
.\tools\verify.ps1 -Mode Full
.\tools\verify.ps1 -Mode CI
```

```powershell
cd frontend
npm run lint
npm run build
npm run smoke
```
