# OneNode Image Studio

Prototype web / Telegram Mini App / MAX Mini App interface for `FluxKleinOneNode`.

## Documentation map

Start here when you or another agent joins the project:

- `docs/public-launch.md` — public/live launch flow with `start-public.bat` (запуск и deploy).
- `docs/main-merge-handoff-20260707.md` — current merge/deploy handoff for `/new`, `/feed`,
  `/gallery`, and the rule that this project folder is the only deploy source.
- `docs/identity-core-plan.md` — auth architecture (identity core migration plan).
- `docs/identity-core-risks.md` — auth/security risks.
- `docs/admin-panel-product-spec.md` — admin product direction.
- `docs/new-ui-v2-plan.md` — new UI `/new` (working contract).
- `docs/new-ui-v2-review.md` — current `/new` review state.
- `docs/feed-media-architecture.md` — public feed image storage, compression and DB contract.

The `docs/phase*.md` files are historical phase reports. They are useful evidence, but
the current working rules should be read from the files listed above first.

## Run

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

```powershell
cd frontend
npm install
npm run dev
```

Open `http://127.0.0.1:5173`.

## ComfyUI

The backend checks `http://127.0.0.1:8188/object_info`, verifies `FluxKleinOneNode`, loads the One Node workflow JSON from `/flux_klein/workflow_*`, sends patched prompts to `/prompt`, waits for `/history/{prompt_id}`, downloads the image through `/view`, and stores a local copy plus thumbnail.

Set `COMFYUI_REQUIRED=true` to make missing ComfyUI a hard error.

Set `COMFYUI_MOCK_FALLBACK=true` only for demo mode without a working ComfyUI install.

Useful checks:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
Invoke-RestMethod http://127.0.0.1:8000/api/models
```

## Bots: domain and token modes

The bot layer supports three modes:

- `BOT_MODE=local`: no bot tokens and no public domain required. Use `/api/bots/local-command` to test Telegram/MAX commands locally.
- `BOT_MODE=polling`: bot token required, public domain not required. Telegram can poll via `/api/telegram/poll-once`.
- `BOT_MODE=webhook`: bot token and public HTTPS URL required. Use `BACKEND_PUBLIC_URL` and `APP_PUBLIC_URL`.

Environment variables for real bots:

```powershell
TELEGRAM_BOT_TOKEN=...
MAX_BOT_TOKEN=...
MAX_API_BASE_URL=https://platform-api.max.ru
MAX_WEBHOOK_SECRET=...
APP_PUBLIC_URL=https://your-domain/app
BACKEND_PUBLIC_URL=https://your-domain
```

Do not commit real bot tokens to the repository. Set them in the process environment or a local `.env` that is excluded from version control.

Useful local checks:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/bots/status
Invoke-RestMethod http://127.0.0.1:8000/api/bots/local-command -Method Post -ContentType 'application/json' -Body '{"platform":"telegram","text":"/app"}'
```

Real bot checks after tokens are set:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/telegram/poll-once -Method Post
Invoke-RestMethod http://127.0.0.1:8000/api/max/poll-once -Method Post
```

Webhook setup requires `BACKEND_PUBLIC_URL` with HTTPS:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/telegram/set-webhook -Method Post
Invoke-RestMethod http://127.0.0.1:8000/api/max/set-webhook -Method Post
```

## Implemented prototype scope

- RU/EN responsive interface.
- Web / Telegram / MAX-ready single frontend.
- SQLite database with prototype users, jobs, images, presets, LoRA and model profile tables.
- Web/Telegram/MAX bootstrap endpoints and bot command webhook handlers.
- Bot adapter modes for local, polling-ready and webhook-ready operation.
- Modes: text-to-image, image-to-image, edit, paint, inpaint, outpaint, face swap.
- Canvas sketch/mask prototype with Konva.
- Gallery, detail view, favorite/delete, Use as, presets, settings, admin summary.
- Stage 3 end-to-end: Text to Image, Image to Image and Edit Image run through ComfyUI workflows and gallery media can be reused as inputs.
- FastAPI backend with generation jobs, progress, cancellation, local media storage, real ComfyUI workflow adapter, Telegram/MAX webhook stubs.
