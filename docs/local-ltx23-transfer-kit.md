# LTX 2.3 transfer kit for a new Windows host

This package makes the local-video runtime reproducible without enabling it.
It does not include model weights, secrets or a fabricated ComfyUI API graph.

## What is pinned

The machine-readable source of truth is
`ops/ltx23/runtime-manifest.json`. It records:

- Python, Torch, CUDA and ComfyUI versions;
- exact custom-node commits;
- the five mandatory model paths, byte sizes and SHA-256 checksums;
- the minimum API-workflow contract;
- the tested 832x480, 121-frame, 24 fps, no-audio profile.

Q3 has a verified upstream revision in the manifest. The exact historical
revisions for Q4, Gemma and the video VAE were not recoverable from the local
Hugging Face cache, so their checksums are authoritative. Do not silently
replace them with a newer file carrying the same name.

## Expected layout

```text
ComfyUI_windows_portable\
  python_embeded\python.exe
  ComfyUI\
    main.py
    models\
      unet\
      text_encoders\
      vae\
    custom_nodes\
      ComfyUI-GGUF\
      ComfyUI-LTXVideo\
      ComfyUI-VideoHelperSuite\
      ComfyUI-KJNodes\
      rgthree-comfy\
```

Copy the five weights from the validated test host or download them from the
repositories named in the manifest. After every transfer, verify the complete
SHA-256; file names and sizes alone are insufficient.

Clone each custom node from its manifest repository and check out the exact
commit. Install node requirements with the portable Python when that repository
provides `requirements.txt`. Keep the ComfyUI repository at its pinned commit.

## Server-owned API workflow

The application expects:

```text
backend\workflows\ltx23_t2v_api.json
```

Create it only after a Q3 render succeeds interactively:

1. Open the tested basic Q3 UI workflow.
2. Remove or replace every missing audio/vocoder node; the MVP has no audio.
3. Render 832x480, 121 frames, 24 fps and 8 steps successfully.
4. Use ComfyUI **Save (API Format)**.
5. Store that JSON at the path above.
6. Run the preflight. Never copy the stale `extra.prompt` from the UI workflow.

The preflight rejects the known stale reference
`ltx-av-step-1751000_vocoder_24K.safetensors`, missing text/latent/output nodes,
wrong model hashes and unpinned custom-node commits.

## Preflight

From the repository root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File tools\check-ltx23-environment.ps1 `
  -ComfyRoot "C:\LLM\ComfyUI_windows_portable_nvidia_cu126\ComfyUI_windows_portable\ComfyUI"
```

After starting ComfyUI, repeat with live device validation:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File tools\check-ltx23-environment.ps1 `
  -ComfyRoot "C:\LLM\ComfyUI_windows_portable_nvidia_cu126\ComfyUI_windows_portable\ComfyUI" `
  -CheckEndpoint
```

Start the portable runtime with:

```powershell
.\python_embeded\python.exe -s .\ComfyUI\main.py `
  --windows-standalone-build --listen 127.0.0.1 --port 8188
```

The result must end with `LTX23_PREFLIGHT_OK`. A running process is not enough:
Torch and `/system_stats` must both report a CUDA device.

## Acceptance before enabling users

1. Keep `LOCAL_LTX_ENABLED=false`.
2. Run one Q3 2-second job through the application with concurrency one.
3. Verify MP4 playback, gallery/history persistence and daily-token charging.
4. Run Q3 4 seconds, then Q4 2 and 4 seconds.
5. Record elapsed time, peak VRAM, output dimensions, frame count and failures.
6. Repeat after a backend restart to verify provider-job recovery.
7. Enable the provider only after all four cases pass.

Use:

```text
LOCAL_LTX_ENABLED=true
LOCAL_LTX_WORKFLOW_API_PATH=<repo>\backend\workflows\ltx23_t2v_api.json
LOCAL_LTX_COMFYUI_BASE_URL=http://127.0.0.1:8190
```

Do not enable I2V, generated audio, upscaling or parallel LTX jobs in this
package. DPAPI secrets must be entered again on the new Windows account; they
are intentionally absent from this kit.
