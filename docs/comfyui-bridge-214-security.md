# COMFYUI-BRIDGE-D2R2-001 — security design / candidate-only test evidence

Context: Issue #214, stacked on PR #211 exact 3f041ca8c2989e53cbd469dfbe29131a63279ae2.
Scope: one real host RTX 4070 FLUX.2 Klein 4B text-to-image candidate; no IZO_ASA production or Docker Desktop global networking changes.

## Decision: DO NOT INSTALL unreviewed third-party node

Reviewed read-only pinned `yanokusnir-ai/one-node-flux-2-klein` @ `7827d1e4f1a51837c3e77b045ef56a2c34564c3f`. Its `nodes.py` registers POST routes `/flux_klein/delete`, `/flux_klein/open_folder` (subprocess to OS explorer), `/flux_klein/stage_input` and `/flux_klein/set_output`, beyond model/config/workflow GET. That is an unacceptable default attack surface for a route bridged from Docker. No custom nodes added or loaded. ComfyUI continues with `--disable-all-custom-nodes --offline`, original Python/models/versions unchanged. Existing IZO_ASA `/flux_klein/*` callers are replaced only behind `COMFYUI_NATIVE4B_ONLY=true`, not globally.

## Least-privilege traffic

    Browser 127.0.0.1:48214
      -> candidate guard nginx / API 8000 (trusted cookie + CSRF + admission)
      -> candidate backend / same guard network namespace
      -> 127.0.0.1:18888 [bridge server]
      -> internal queue (one-use random ID, 12 inflight cap, bounded wait)
      <- Windows-initiated poll (127.0.0.1:48216 -> guard 18889)
      -> Windows agent (separate owned PID, token from LOCALAPPDATA)
      -> 127.0.0.1:8188 native ComfyUI standard paths only
      -> /prompt /history /view PNG
      -> existing backend job persistence + owned gallery and tokens

- Candidate alone uses Docker subnet `10.249.219.0/28`, verified unused across the current 53 Docker networks when initial Docker default pools were exhausted. No existing subnet, host route or daemon address-pool setting is modified.
- Guard uses preexisting nftables `OUTPUT policy drop`, no accepted external egress; established inbound reply permitted, guard interfaces remain only candidate project.
- Host control endpoint published **127.0.0.1 only** on 48216; ComfyUI remains **127.0.0.1:8188** only, not container-addressable, no wildcard LAN binding or port changes.
- Backend listener 18888 binds container network loopback, not host-published. Bridge control requires random 96-hex token, stored only at Windows `%LOCALAPPDATA%\IZO_ASA_Comfy214Runtime\bridge.token`, read-only mounted into bridge under `/run/bridge/token`, never Git, never stdout/receipts.
- Both backend bridge and Windows host independently run **identical pure validator**. GET allowlist: `/system_stats`, `/queue`, `/object_info`, three fixed loader classes `/object_info/<loader>`, own UUID `/history/<id>`, and own output only `/view?filename=local4b_#####_.png&subfolder=Comfy214&type=output`. POST allowlist: `/prompt` only, full JSON exact-match to known official FLUX.2 4B graph with pinned 4B/Qwen FP4/VAE, Euler scheduler, 4 steps, 512–768x512–768. No base64 input, no LoRA, no 9B, no arbitrary nodes/paths, URLs, CONNECT, shell, upload, delete or unauthenticated proxies. The Windows agent tracks its submitted UUIDs and generated filenames so old host media cannot be exfiltrated by guessing.
- `/free` never forwarded from Docker; the owned agent may unload its 4B model only when queue becomes idle after PNG returned. `/interrupt` forbidden to prevent cancelling unrelated work on shared host GPU. Backend cancelling an active job fences accounting; it does not touch other ComfyUI requests.
- GPU preflight forbids sending a candidate POST if utilization high or used VRAM >=3500 MiB, and blocks if ComfyUI queue non-idle. Protects resident Ollama. One Windows agent serially executes tasks.
- Candidate `COMFYUI_MOCK_FALLBACK=false`, `COMFYUI_REQUIRED=true`. Server rejects disabled imageEnabled, non-4B, non-t2i, bad dimensions/steps/LoRA before token admission and *before* provider POST. No automatic uncertain-outcome provider resubmission. Uses current API durable job/SQLite/media; never copy old Shadows/OpenRouter secrets/Yandex restored owner data.
- No external paid provider traffic from candidate. Original OpenRouter Shadow (48145) not changed; independent unchanged cloud behavior validated by existing owner QA, not claimed retested in candidate unless actual test performed.

## Security boundaries and limitations

This is a **developer candidate**, not production-ready. Binding the tokenized control endpoint to 127.0.0.1 prevents LAN/Internet reachability. However other untrusted host-local processes could target candidate port; token and strict validation are required defense in depth. The token is a capability and must never be exposed in logs/browser or screenshots.

Review before accepting includes: constant-time token comparison, unauthenticated 403, route/path strict deny, duplicate completion 409, no host path leakage, candidate ports and volume labels, seccomp/capabilities/no-new-privileges, no query injection, bounded response sizes, unsigned local rollout/rollback identity, and no cross-user image. A failure/timeout after Comfy POST may be ambiguous; never blind retry with paid charge.

Independent security approval must come from a separate authorized reviewer with own evidence; implementer commentary is not independent approval.

## Owner operations / recovery

- Owned source: `agent/comfyui-bridge-d2r2-001` stacked on PR #211.
- Candidate Compose project: `izo-asa-shadow-comfy-214`, own SQLite/media volumes only.
- Candidate web: `http://127.0.0.1:48214`; API: `http://127.0.0.1:48215`; host control: `127.0.0.1:48216` with token required.
- Bridge agent script: `ops/windows/start-comfyui-bridge-agent.ps1 -Action start|status|stop`, executable only via `powershell.exe -NoProfile -ExecutionPolicy Bypass -File ...`.
- Never use `docker system prune`, `docker compose down -v` on unowned project, or kill the ComfyUI/Ollama/PID of other apps. If candidate fails, stop only owned bridge agent and remove only candidate service/container(s). Nothing in `C:\ИИ`, 48145/48135/48125, or #213 restore is part of rollback.

## Status truthfulness

The exact SHA of image labels, GPU prompt-id, PNG checksum, real accounts/job/gallery, desktop/mobile tests, billing ledger before/after, negative tests and independent review must be appended **after execution**; do not call a downloaded checkpoint or fixture a real Studio image.
