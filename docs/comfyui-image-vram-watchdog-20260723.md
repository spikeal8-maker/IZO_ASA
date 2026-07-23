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
