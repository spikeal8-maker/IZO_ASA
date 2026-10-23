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

## Реальные результаты отдельного кандидата на D2-R2 — 24.10.2026

- **Exact running image/source SHA:** `0391644ff2274a67a791d1c5ab1eaf92769854f8`, based on PR #211 SHA `3f041ca8c2989e53cbd469dfbe29131a63279ae2`. Source updates after this exact image commit are tests/docs only; an updated image must be rebuilt before claiming newer runtime SHA.
- **Isolated Docker:** `izo-asa-shadow-comfy-214` — four candidates `guard/backend/bridge/web`, all healthy; own volumes `izo-asa-shadow-comfy-214_sqlite-data` and `..._media-data`, dedicated network `10.249.219.0/28`. No Yandex Disk restored data/secret volume mounted.
- **Web** `http://127.0.0.1:48214` HTTP 200, **API** `http://127.0.0.1:48215` HTTP 200; **host control** `127.0.0.1:48216` unauthenticated poll HTTP 403. Both standard-comfy `/system_stats`, `/queue`, `/object_info/UNETLoader` passed through Docker reverse tunnel: native host ComfyUI `0.42.1`, RTX 4070, FLUX4B model file actually listed. Guard check: `{"policy":"VERIFIED","blockedPackets":0}`.
- **REAL cross-Docker GPU inference PASS, NOT an IZO_ASA Studio test:** actual `POST /prompt` sent from isolated bridge container, host Comfy prompt_id `06e0e337-8839-4c8f-b415-3c33ccc026ac`, `GET /history` successful, `GET /view` fetched a true 512×512 PNG. Elapsed **12.28 seconds**. Windows host file `C:\ИИ\ComfyUI-Data\output\Comfy214\local4b_00001_.png` and Docker-fetched PNG have identical SHA256 `5a47da3f3b3bb6bc37322389e61332e5cf5d4fafb5f3146da94ebb8e3d8b0734`. Receipt `%LOCALAPPDATA%\IZO_ASA_Comfy214Runtime\bridge-proof.json`. Ollama HTTP 200 after GPU test, model safely unloaded to ~2GiB idle VRAM.
- **Security negatives PASS** (real runtime): unauthenticated trusted session `POST /api/generate` HTTP 401; `GET /api/admin/config-ui/status-v2` HTTP 401; bridge rejects forged graph, filesystem route and traversal with 403; control port without token 403. Native pure Python unit checks **10/10 PASS**, including model missing/offline/admin-disabled before submission, no blind retry on unknown outcome (these latter checks use in-process fake callbacks, not a real paid billing account).
- **Real Chromium (not mocked)**: desktop 1366×900 and mobile 390×844 both HTTP200 on actual candidate Studio, local model appears in `/api/models`, text composer editable, 0 page errors. Screenshots `%LOCALAPPDATA%\IZO_ASA_Comfy214Runtime\evidence\candidate-desktop.png` and `candidate-mobile.png`. Both explicitly tagged `actualGpuGeneration=NOT_RUN_GUEST`.
- **Prior Shadows unaffected:** 48125, 48135, 48145 responded HTTP 200; Docker Desktop daemon settings, installed ComfyUI runtime/models, GPU driver, Ollama and #213 restored data not touched.

### Unfinished Definition of Done / explicit blockers

- **NOT VERIFIED:** trusted login on *fresh* candidate test account, click **«Генерировать»** and complete native Comfy job through IZO_ASA admission/accounting/SQLite/gallery; authenticated desktop/mobile; exact one charge, cancellation, recovery. **Do not represent the successful bridge-only prompt as this proof.** A synthetic test-account registration attempt could not be completed through the current authorized tool path. Never bypass authentication or copy personal accounts/secrets from original Shadows or #213.
- **Admin Config UI:** backend integration successfully receives installed native 4B/Qwen/VAE and live queue/GPU data; actual browser admin role/enable-disable end-to-end remains **NOT VERIFIED** because no authorized candidate admin account has been established.
- **Independent security-review:** not yet obtained. Current implementation was self-reviewed and has automated negative checks; this is **not an independent approval**. Candidate must remain local-only and PR in Draft until an authorized reviewer independently evaluates network/bridge and source code.
- **Required GitHub-hosted CI:** verify exact PR head state. Historical GitHub Actions jobs in this repository were blocked by billing/spending limits, and cannot be reported as PASS without a real run.

**Stop boundary:** no merge, no production, no enabling local generation in existing OpenRouter Shadow. The candidate can remain available for owner-run **test-account** verification after reviewer approval; it is not ready to be called completed until authenticated Studio → gallery and ledger proof is obtained.
