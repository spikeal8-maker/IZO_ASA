# ComfyUI / Config UI runtime contract

Date: **2026-07-27**

Status: **transfer package; not a deployment receipt**

## Why this package exists

The backend fetches production API-format workflows from the installed
`one-node-flux-2-klein` ComfyUI custom node. A Git clone of IZO_ASA therefore
did not reproduce image generation: the workflows, custom-node revision,
Config UI configuration and model files lived outside this repository.

This package vendors the exact small JSON assets that were served by the
inspected runtime and records the required external model files. Multi-gigabyte
model binaries remain outside Git.

## Pinned custom node

- repository: `https://github.com/yanokusnir-ai/one-node-flux-2-klein.git`
- commit: `0e3b9baccdf39af3fa1691069494fe91938943ff`
- local compatibility patch:
  `ops/comfyui/runtime-contract/patches/0001-export-web-directory.patch`

The patch exports `WEB_DIRECTORY` from the custom node. Apply it after checking
out the pinned commit. Do not copy the old custom node `.git` directory between
computers.

## Runtime endpoints used by IZO_ASA

| Product mode | Config UI endpoint |
|---|---|
| text-to-image | `/flux_klein/workflow_t2i` |
| image-to-image | `/flux_klein/workflow_i2i` |
| edit, paint, try-on, texture transfer | `/flux_klein/workflow_edit` |
| face swap | `/flux_klein/workflow_edit` |
| inpaint | `/flux_klein/workflow_inpaint` |
| outpaint | `/flux_klein/workflow_outpaint` |
| remove background | `/flux_klein/workflow_remove_bg` |

The application intentionally does not use `workflow_faceswap`: that dedicated
graph hung with Klein 9B. Face swap patches `workflow_edit` with a model-only
LoRA and face-first reference ordering.

## Installation handoff

1. Install ComfyUI and check out the pinned custom-node commit.
2. Apply `0001-export-web-directory.patch` in the custom-node repository.
3. Copy the vendored `config.json` and `workflows/*.json` into the custom node.
4. Install the model files listed in `manifest.json` at their exact relative
   paths. Acquire them from their licensed upstream sources; never commit the
   binaries to IZO_ASA.
5. Verify the package itself:

   ```powershell
   backend\.venv\Scripts\python.exe tools\check_comfyui_runtime_contract.py
   ```

6. Verify the installed runtime:

   ```powershell
   backend\.venv\Scripts\python.exe tools\check_comfyui_runtime_contract.py `
     --comfyui-root C:\path\to\ComfyUI
   ```

7. Start ComfyUI and verify `/object_info`, `/system_stats`,
   `/flux_klein/models` and every endpoint in the table.
8. Run a real, queue-safe GPU smoke only after the target NVIDIA GPU is visible.

## Face model boundary

`flux-2-klein-9b-fp8.safetensors` is the full 9B diffusion model in FP8.
`face_swap_flux_klein_9b_r32_800.safetensors` is the small face adapter, not a
replacement for the 9B model. The inspected machine no longer contained this
rank-32 file, but prior acceptance identified its exact size and SHA-256. It is
required by this contract because the legacy rank-128 face LoRA previously
filled the RTX 3090 and stalled the workflow.

The manifest is authoritative for filenames, sizes and SHA-256 values. A green
asset-only check proves the Git package. A green runtime check proves file
parity, not GPU operability or image quality.
