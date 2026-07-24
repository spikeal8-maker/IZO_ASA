# Local LTX 2.3 video provider

## Scope

The local provider extends the existing `/api/video/*` contract. It does not
create a second video page, gallery or token ledger.

Initial boundary:

- text to video only;
- 2 or 4 seconds at 24 fps;
- 16:9 at 832x480, exposed as `480p`;
- no generated audio;
- one ComfyUI job at a time;
- persisted ComfyUI prompt ids survive backend restart and resume through
  `/history/{prompt_id}`;
- server-owned workflow;
- daily tariff tokens first, then the main balance;
- OpenRouter video behavior remains unchanged.

| Model id | Quantization | Steps | 2 seconds | 4 seconds |
| --- | --- | ---: | ---: | ---: |
| `local/ltx-2.3-fast-q3` | Q3_K_M | 8 | 1 token | 2 tokens |
| `local/ltx-2.3-standard-q4` | Q4_K_M | 12 | 2 tokens | 4 tokens |

These are product prices for local compute, not provider-cost estimates. Change
them only with a measured GPU benchmark and a corresponding test update.

## Required environment

```text
LOCAL_LTX_ENABLED=true
LOCAL_LTX_WORKFLOW_API_PATH=D:\path\to\ltx23_t2v_api.json
COMFYUI_BASE_URL=http://127.0.0.1:8188
```

`LOCAL_LTX_ENABLED` is false by default. The workflow must be exported from
ComfyUI in API format and stored on the server. The browser never sends a
workflow or model filename.

The API workflow must contain at least two `CLIPTextEncode` nodes, exactly one
`EmptyLTXVLatentVideo`, an `LTXVScheduler` when steps are configurable, and
`VHS_VideoCombine` or `SaveVideo`. It must use the installed Q3/Q4 GGUF loader
and local Gemma/text-projection nodes.

The backend replaces only the positive prompt, frame dimensions/count, step
count, random seed and output prefix. Frame count is `duration * 24 + 1`, which
satisfies `(frames - 1) % 8 == 0`.

## Test-machine evidence

The inspected ComfyUI root is:

```text
C:\LLM\ComfyUI_windows_portable_nvidia_cu126\ComfyUI_windows_portable
```

It contains ComfyUI-GGUF, ComfyUI-LTXVideo, ComfyUI-VideoHelperSuite, Q3/Q4
LTX 2.3 weights, Gemma 3 12B, projection, video VAE and upscalers. Existing UI
workflows are not automatically trusted as API workflows.

On 2026-07-24 this computer failed ComfyUI startup with:

```text
RuntimeError: No CUDA GPUs are available
```

Code and fake-provider tests can run here, but real LTX generation cannot be
called operationally verified until Windows and ComfyUI see the NVIDIA GPU.

Repository evidence on 2026-07-24:

- 34 focused provider, API, recovery and architecture tests passed;
- the concurrency/restart pair passed five consecutive runs;
- `tools/verify.ps1 -Mode Quick` reached generated-map and architecture checks,
  then stopped at the runtime-listener contract because the isolated test UI
  uses Vite on port 5173 while that contract requires production Caddy.

## Repeatable validation

The complete cross-machine manifest, checksum checker, pinned custom-node
commits and API-workflow export procedure are in
[local-ltx23-transfer-kit.md](local-ltx23-transfer-kit.md). Run that preflight
before enabling this provider on another computer.

1. Confirm `nvidia-smi` sees the intended GPU.
2. Start ComfyUI and verify `/system_stats` reports a non-CPU device.
3. Export the selected Q3 workflow in API format to the configured path.
4. Enable the local provider in the isolated test-stack environment.
5. Verify `/api/video/config` contains both local models.
6. Generate a 2-second Q3 text video.
7. Confirm media streaming, history/gallery storage and daily-token charging.
8. Repeat Q4 and 4 seconds while recording time, peak VRAM and failures.
9. Keep concurrency at one until repeated GPU tests pass.

Do not enable I2V, audio, upscaling or parallel jobs in this initial package.
