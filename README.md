# OneNode Image Studio

Prototype web / Telegram Mini App / MAX Mini App interface for `FluxKleinOneNode`.

## Documentation map

Start here when you or another agent joins the project:

- `docs/public-launch.md` — public/live launch flow with `start-public.bat` (запуск и deploy).
- `docs/production-hardening-roadmap-20260713.md` — authoritative current status and
  execution order for security, decomposition, tests and local production hardening.
- `docs/production-hardening-master-plan-20260712.md` — historical checkpoint journal
  and original requirements; it is no longer the current backlog.
- `docs/main-merge-handoff-20260707.md` — current merge/deploy handoff for `/new`, `/feed`,
  `/gallery`, and the rule that this project folder is the only deploy source.
- `docs/identity-core-plan.md` — auth architecture (identity core migration plan).
- `docs/identity-core-risks.md` — auth/security risks.
- `docs/auth-cookie-local-production-guide-20260708.md` — trusted-cookie rule for local
  HTTP vs production HTTPS, including restart persistence checks.
- `docs/admin-panel-product-spec.md` — admin product direction.
- `docs/new-ui-v2-plan.md` — new UI `/new` (working contract).
- `docs/new-ui-v2-review.md` — current `/new` review state.
- `docs/text-to-image-openrouter-contract-20260711.md` — current first-tab model,
  repeat, format and billing contract before OpenRouter expands to other modes.
- `docs/editor-face-reference-contract-20260711.md` — assembly face-reference slider,
  percentage reset and shared role-panel contract.
- `docs/feed-media-architecture.md` — public feed image storage, compression and DB contract.
- `docs/gallery-current-product-plan.md` — visible `/gallery` contract: slots,
  favorite protection, deletion, publish modal, viewer and grid order.

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

## Verify

The repository has one non-mutating verification entrypoint:

```powershell
# Fast static, tooling and production preflight checks.
.\tools\verify.ps1 -Mode Quick

# Complete local gate: Python compile, generated map, full backend/tools tests,
# frontend lint/build and read-only production process/source checks.
.\tools\verify.ps1 -Mode Full

# Deterministic checks suitable for CI; does not inspect the live backend/media.
.\tools\verify.ps1 -Mode CI

# Show the selected steps without executing them.
.\tools\verify.ps1 -Mode Full -PlanOnly
```

`Full` is the default mode. The verifier does not restart processes, delete files,
or modify production DB/media. Runtime packages still require the separate
controlled restart and live-smoke procedure documented in the production roadmap.

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

The bot update layer supports three modes:

- `BOT_MODE=disabled`: no background polling/webhook updates. `/api/bots/local-command` remains available for local adapter tests.
- `BOT_MODE=polling`: bot token required, public domain not required. Telegram can poll via `/api/telegram/poll-once`.
- `BOT_MODE=webhook`: bot token and public HTTPS URL required. Use `BACKEND_PUBLIC_URL` and `APP_PUBLIC_URL`.

Environment variables for real bots:

```powershell
TELEGRAM_BOT_TOKEN=...
# Required only when BOT_MODE/BOT_UPDATES_MODE is webhook.
TELEGRAM_WEBHOOK_SECRET=...
TELEGRAM_WEBHOOK_MAX_BODY_BYTES=262144
TELEGRAM_WEBHOOK_REPLAY_CACHE_SIZE=4096
MAX_BOT_TOKEN=...
MAX_API_BASE_URL=https://platform-api.max.ru
# Keep polling until webhook mode is switched explicitly with a configured secret.
MAX_UPDATES_MODE=polling
# Required only when MAX_UPDATES_MODE=webhook.
MAX_WEBHOOK_SECRET=...
MAX_WEBHOOK_MAX_BODY_BYTES=262144
APP_PUBLIC_URL=https://your-domain/app
BACKEND_PUBLIC_URL=https://your-domain
```

Do not commit real bot tokens to the repository. Set them in the process environment or a local `.env` that is excluded from version control.

Telegram polling does not need `TELEGRAM_WEBHOOK_SECRET`, and the public webhook
receiver is disabled in polling mode. Before switching Telegram to webhook mode,
generate a 32-byte URL-safe secret and place it only in the local `.env`/service
environment. Startup then requires that secret, passes it to Telegram as
`secret_token`, validates `X-Telegram-Bot-Api-Secret-Token` in constant time,
limits request bodies to 256 KiB by default, and suppresses repeated `update_id`
values in a bounded single-process cache.

```powershell
$bytes = New-Object byte[] 32
$rng = [Security.Cryptography.RandomNumberGenerator]::Create()
$rng.GetBytes($bytes)
$rng.Dispose()
([Convert]::ToBase64String($bytes)).TrimEnd('=').Replace('+', '-').Replace('/', '_')
```

MAX polling likewise does not need `MAX_WEBHOOK_SECRET`; polling disables its
public webhook receiver. Webhook mode requires a distinct secret matching
`^[A-Za-z0-9_-]{5,256}$`, sends it in the subscription body, and validates
`X-Max-Bot-Api-Secret` in constant time. The launcher never changes MAX from
polling to webhook implicitly. The format and header follow the official
[MAX subscription API](https://dev.max.ru/docs-api/methods/POST/subscriptions).

The same MAX documentation announces migration from `platform-api.max.ru` to
`platform-api2.max.ru` by 2026-07-19 together with trust-store changes. This
repository keeps the currently working hostname until the separate documented
certificate/migration rehearsal is completed; do not flip it during an unrelated
deployment.

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

Webhook setup requires `BACKEND_PUBLIC_URL` with HTTPS, the corresponding webhook
secret, and a trusted admin session. Do not run it while Telegram stays in polling:

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
