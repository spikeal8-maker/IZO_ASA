# OneNode Image Studio Test Plan

## Automated Backend/API Coverage

- Stage 1 shell: Web/Telegram/MAX bootstrap endpoints, platform readiness endpoint, SQLite database presence.
- Database persistence: jobs and images are written to SQLite and survive outside in-memory state.
- Bot commands: Telegram/MAX webhook handlers return Mini App buttons for `/start`, `/app`, `/help`, `/gallery`, `/settings`.
- Bot modes: local mode works without tokens/domain; Telegram send/polling endpoints require `TELEGRAM_BOT_TOKEN`; webhook mode reports HTTPS readiness.
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

## Current Automated Commands

```powershell
cd backend
python -m pytest -q
python -m py_compile main.py
```

```powershell
cd frontend
npm run lint
npm run build
npm run smoke
```
