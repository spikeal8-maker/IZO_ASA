# ComfyUI image VRAM watchdog

Date: **2026-07-23**

Status: **CODE COMPLETE in an isolated branch; not deployed**

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
- the installed 4B-specific outpaint LoRA.

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
- outpaint produces a target-sized canvas and mask, preserves source aspect
  ratio during editor zoom and supports desktop/mobile positioning;
- the outpaint workflow deliberately uses the installed 4B outpaint LoRA even
  when the global default is 9B, because no compatible 9B outpaint dependency
  is installed. Other local image modes follow the global 4B/9B selection.
