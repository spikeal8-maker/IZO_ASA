# ComfyUI image VRAM watchdog

Date: **2026-07-23**

Status at incident time: **CODE COMPLETE in an isolated branch; not deployed**

**2026-10-17 documentation review:** do not treat that July statement as the
current deployed or verified state. Check the exact installed runtime and
`ops/windows/comfyui-image-watchdog.ps1` plus current tests before attempting
any watchdog or model-related operation. This is an incident/operational
reference, not authorization to restart host-native ComfyUI or change GPU
settings during the Docker migration.

## Incident

An image-edit job with a base image and a face reference exhausted almost all
VRAM on the RTX 3090. The application marked the job failed after an HTTP
history read timed out, but ComfyUI continued executing the prompt. That left
the GPU hot and full while the application queue could move on.

The workflow also scaled every edit reference to `1.0` megapixel. A face
reference therefore ignored the existing `COMFYUI_FACE_SOURCE_MEGAPIXELS=0.35`
policy, and small inputs could be enlarged unnecessarily.

## Corrective behavior

- The selected model and workflow are preserved. There is no fallback or model
  switch.
- Prepared references are never enlarged. They keep their bounded source size,
  aligned to the workflow requirements.
- A `face` reference is capped by both the face-side limit and the configured
  face megapixel budget.
- The workflow scale nodes receive the actual prepared megapixel values instead
  of forcing every reference to `1.0` megapixel.
- A transient `/history` request timeout is retried and no longer marks a
  still-running prompt failed.
- Image generation has a dedicated 300-second deadline. Video provider paths
  keep their existing independent timeout behavior.
- At the image deadline, the backend first sends interrupt/free commands and
  then creates a narrowly scoped restart request.
- A SYSTEM scheduled task consumes that request and restarts only
  `IZOComfyUI`. A successful service restart destroys the old GPU process and
  therefore releases its CUDA allocations.
- The application generation gate stays closed until the request is consumed
  and ComfyUI is healthy. Persistent SQLite jobs remain the source of truth;
  the recovery script never edits or clears the application queue.
- A failed restart leaves the request in place, so the next job cannot enter a
  known-bad ComfyUI process.

## Configuration

| Variable | Default | Meaning |
|---|---:|---|
| `COMFYUI_IMAGE_TIMEOUT_SECONDS` | `300` | Image prompt deadline |
| `COMFYUI_HISTORY_REQUEST_TIMEOUT_SECONDS` | `10` | Timeout of one history poll |
| `COMFYUI_RECOVERY_WAIT_SECONDS` | `180` | Current-job wait for hard recovery |
| `COMFYUI_WATCHDOG_REQUEST_PATH` | `C:\IZO_ASA\runtime\comfyui-watchdog\request.json` | Privileged handoff file |
| `COMFYUI_FACE_SOURCE_MEGAPIXELS` | `0.35` | Face-reference pixel budget |

`COMFYUI_IMAGE_TIMEOUT_SECONDS` is bounded by the existing general ComfyUI
timeout. The minimum is 60 seconds.

## Installation

Run the installer once from an elevated PowerShell session:

```powershell
powershell -ExecutionPolicy Bypass -File ops/windows/install-comfyui-image-watchdog.ps1
```

The installer creates a highest-privilege SYSTEM task named
`IZO_ASA ComfyUI Image Watchdog`. It runs every minute, permits only one instance,
and gives the backend service account write access only to the dedicated
handoff directory.

The task is intentionally not installed by a normal code checkout. Production
activation must follow the repository release process on the canonical
deployment checkout.

Real local workflow checks use the explicit operator runner. It uses a unique
temporary SQLite database and media directory and refuses to submit if the
ComfyUI queue is already occupied:

```powershell
backend\.venv\Scripts\python.exe tools\run_local_comfyui_acceptance.py `
  --mode outpaint --profile flux_klein_9b
```

## Acceptance

1. A small base or face reference is not enlarged.
2. A large face reference is bounded to at most 0.35 MP by default.
3. The active Flux Klein 9B selection is unchanged.
4. A short `/history` timeout is retried.
5. A prompt still incomplete after 300 seconds produces one restart request.
6. The watchdog restarts only `IZOComfyUI`, verifies `/object_info`, and removes
   the request only after success.
7. While recovery is pending, no later application image job is submitted.
8. Persistent queued jobs remain present and resume in order after ComfyUI is
   healthy.
9. Video generation behavior and timeouts remain unchanged.

## Compatibility validation 2026-07-24

The local ComfyUI inventory contains both Klein checkpoints and their matching
text encoders:

- `flux-2-klein-4b-fp8.safetensors` with `qwen_3_4b.safetensors`;
- `flux-2-klein-9b-fp8.safetensors` with
  `qwen_3_8b_fp8mixed.safetensors`;
- the shared `flux2-vae.safetensors`;
- matching 4B and 9B face LoRAs;
- the lightweight rank-32 9B face-swap LoRA selected ahead of the legacy
  rank-128 checkpoint;
- the installed 4B-specific outpaint LoRA;
- the official `flux-2-klein-9b-kv-fp8.safetensors` checkpoint for 9B
  outpaint and accelerated multi-reference editing.

The 9B KV FP8 checkpoint was downloaded from
`black-forest-labs/FLUX.2-klein-9b-kv-fp8`. Its installed size is
`9,818,935,984` bytes and the Hugging Face/Xet metadata records SHA-256
`33f7da5625a00798349a719742999d3c7dd20c1a7eda14663922c363640728f1`.
The 9B model remains subject to the FLUX Non-Commercial License.

Local contract coverage verifies:

- the Config UI switch persists and routes both `4B -> 9B` transitions;
- explicit 4B and 9B profiles select the matching checkpoint and encoder;
- built-in 4B/9B profile IDs still resolve correctly when the optional
  `model_profiles` database catalog is unavailable, preventing an accidental
  4B-to-9B fallback;
- image-to-image keeps its source node and denoise control;
- Assembly serializes and wires one, two, three and four images in order;
- prepared source and mask images keep identical bounded dimensions for
  inpaint;
- externally supplied inpaint/outpaint masks are aligned exactly to the
  prepared source dimensions with nearest-neighbour resampling;
- outpaint produces a target-sized canvas and mask, preserves source aspect
  ratio during editor zoom and supports desktop/mobile positioning;
- 4B outpaint uses the installed compatible 4B LoRA and removes the 9B-only
  KV-cache node;
- 9B outpaint selects the dedicated KV FP8 checkpoint and preserves the stock
  `FluxKVCache` node, so the Config UI model switch is honored by outpaint too.

Real local acceptance on the production ComfyUI host:

- mode: 9B outpaint, 512×512, two sampling steps;
- prompt ID: `92a75da6-b5c1-4e6e-b162-45751d112eaa`;
- result: one valid 512×512 PNG;
- elapsed time: 52.3 seconds;
- observed RTX 3090 state while running: 11,754 MiB used, 47 °C;
- the following pre-existing application job remained queued and was not
  cancelled or reordered.

The lightweight 9B face LoRA was downloaded from `ilkerzgi/face-swap`. Its
installed size is `126,670,920` bytes and the Hugging Face LFS metadata records
SHA-256
`40ad042e09c938cc587864b896690daf4f30abda86c24812d6a074aa041c25ec`.
It remains subject to the FLUX Non-Commercial License.

Additional real local acceptance:

| Profile | Mode | Prompt ID | Result | Time |
|---|---|---|---:|---:|
| 4B | text-to-image | `128206c9-878b-4858-951c-d89a45379dfa` | 512x512 PNG | 4.1 s |
| 4B | image-to-image | `69bc3e6a-d444-4b3c-ade7-754397dcfecd` | 512x256 PNG | 4.4 s |
| 4B | Assembly, 3 refs | `1a6ba1f7-f01f-43b9-be96-1520de4c3036` | 512x512 PNG | 5.0 s |
| 4B | face-swap | `c9e3238e-ff4c-4649-bdef-c5ce5bebffb3` | 512x512 PNG | 8.8 s |
| 4B | inpaint | `186caa5a-3b42-4cca-8ac2-4744bf7439fa` | 512x256 PNG | 6.5 s |
| 4B | outpaint | `2c438095-689b-4a1c-9296-99c200a40adb` | 512x512 PNG | 6.8 s |
| 9B | text-to-image | `39625da7-bd7d-497b-95ce-6f50afe974e9` | 512x512 PNG | 50.6 s |
| 9B | image-to-image | `450e2e99-36f2-428d-a10d-35fb2bbf88ed` | 512x256 PNG | 51.3 s |
| 9B | Assembly, 3 refs | `c9e171db-6586-46f6-8a37-33c46ab2384c` | 512x512 PNG | 53.9 s |
| 9B | face-swap, rank 32 | `859db035-85d4-450d-a4e8-d894313957c2` | 512x512 PNG | 31.9 s |
| 9B | inpaint | `f9c1110b-5ee5-4a96-8462-e4fb1929a6e9` | 512x256 PNG | 6.5 s |
| 9B | outpaint, KV FP8 | `92a75da6-b5c1-4e6e-b162-45751d112eaa` | 512x512 PNG | 52.3 s |

The 9B outpaint run used 11,754 MiB at 47 C. The lightweight 9B face-swap
loaded at about 9.5 GiB and completed without OOM; the legacy rank-128 attempt
had previously filled the 24 GiB card and was interrupted. Every acceptance
submission first verified an empty ComfyUI queue and therefore did not cancel
or reorder application jobs.
