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
LOCAL_LTX_COMFYUI_BASE_URL=http://127.0.0.1:8190
```

`LOCAL_LTX_ENABLED` is false by default. The workflow must be exported from
ComfyUI in API format and stored on the server. The browser never sends a
workflow or model filename.

Start the dedicated video runtime with
`ops/ltx23/start-local-ltx-comfyui.ps1`. It uses low-VRAM weight offloading,
reserves 1 GB for VAE decoding, and loads only the four custom-node packages
required by LTX. Do not submit this workflow to an image runtime started with
`--gpu-only`: diffusion fits in 24 GB, but final VAE decoding can exhaust the
remaining VRAM.

After a terminal local-video state, the backend calls ComfyUI `/free`. The
current Windows GGUF runtime may terminate while unloading native model state;
the launcher therefore supervises the dedicated process and restarts it after
two seconds. This hard reset releases VRAM without interrupting the separate
image queue on port 8188.

The API workflow must contain at least two `CLIPTextEncode` nodes, exactly one
`EmptyLTXVLatentVideo`, an `LTXVScheduler` when steps are configurable, and
`VHS_VideoCombine` or `SaveVideo`. It must use the installed Q3/Q4 GGUF loader
and local Gemma/text-projection nodes.

The backend replaces only the positive prompt, frame dimensions/count, step
count, random seed and output prefix. Frame count is `duration * 24 + 1`, which
satisfies `(frames - 1) % 8 == 0`.

## Test-machine evidence

The operational ComfyUI root is:

```text
F:\AI\ComfyUI\ComfyUI_windows_portable\ComfyUI
```

It contains ComfyUI-GGUF, ComfyUI-LTXVideo, ComfyUI-VideoHelperSuite, Q3/Q4
LTX 2.3 weights, Gemma 3 12B, projection, video VAE and upscalers. Existing UI
workflows are not automatically trusted as API workflows.

On 2026-07-24 the Q3 2-second profile completed locally in the dedicated
low-VRAM runtime and produced an 832x480, 24 fps H.264 MP4. The same workflow
submitted to the image runtime with `--gpu-only` completed diffusion but failed
during VAE decoding because the model retained 23.17 GiB of VRAM.

The video runtime must not load `ComfyUI-AutoFreeMemory20s`. The launcher uses
`--disable-all-custom-nodes` plus a four-package whitelist, then supervises the
process because native GGUF unloading can terminate Python after `/free`.

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
