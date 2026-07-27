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
- current verified commit: `e700bb81eb768911f403bdf86bd35fe7ef0e9df4`
- original captured commit: `0e3b9baccdf39af3fa1691069494fe91938943ff`
- local compatibility patch:
  `ops/comfyui/runtime-contract/patches/0001-export-web-directory.patch`

The patch exports `WEB_DIRECTORY` from the custom node. Apply it after checking
out the pinned current commit. The verifier checks both the Git revision and
the local export. Do not copy the old custom node `.git` directory between
computers.

## Runtime endpoints used by IZO_ASA

| Product mode | Config UI endpoint |
|---|---|
| text-to-image | `/flux_klein/workflow_t2i` |
| image-to-image | `/flux_klein/workflow_edit` |
| edit, paint, try-on, texture transfer | `/flux_klein/workflow_edit` |
| face swap | `/flux_klein/workflow_edit` |
| inpaint | `/flux_klein/workflow_inpaint` |
| outpaint | `/flux_klein/workflow_outpaint` |
| remove background | `/flux_klein/workflow_remove_bg` |

The application intentionally does not use `workflow_faceswap`: that dedicated
graph hung with Klein 9B. Face swap patches `workflow_edit` with a model-only
LoRA and face-first reference ordering.

The application also intentionally routes image-to-image through
`workflow_edit`. The legacy denoise graph returned a plausible image but did
not reliably follow object-level edit instructions. The reference-latent edit
graph was visually accepted by changing a red ceramic mug to cobalt blue while
preserving its shape, table and composition.

The quality 9B rank-128 adapter uses ComfyUI's
`LoraLoaderBypassModelOnly`. Unlike the regular loader, bypass mode does not
materialize a second patched copy of the base weights. It injects the low-rank
adapter path into the forward pass, so the 9B FP8 base remains resident and the
adapter can be enabled without the 24 GB weight-backup spike.

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
`bfs_head_v1_flux-klein_9b_step3500_rank128.safetensors` is the production
quality face adapter selected by IZO_ASA. It is not a replacement for the 9B
model and is required by this contract. The older
`face_swap_flux_klein_9b_r32_800.safetensors` remains recorded only as an
optional compatibility asset; the application must not silently downgrade to
it.

The historical machine report measured 31.9 seconds with rank-32, not
rank-128. That number must not be used as acceptance evidence for the current
quality profile. Rank-128 requires a fresh GPU/browser acceptance run on the
target RTX 3090.

The manifest is authoritative for filenames, sizes and SHA-256 values. A green
asset-only check proves the Git package. A green runtime check proves file
parity, not GPU operability or image quality.

## BiRefNet background removal

Background removal is not a generative Klein/LoRA operation. It uses the
official ComfyUI `LoadBackgroundRemovalModel` and `RemoveBackground` nodes with
the official `Comfy-Org/BiRefNet` model. The runtime contract requires:

- ComfyUI base `3086026401180c9216bcb6ace442a4e3587d2c66`;
- BiRefNet support commit
  `f5cf50dd53bca0aedab19c66a4204fd8f86f16f4`;
- mask-device correctness fix
  `9f1f0a2fff34fae7050bbced5b0cd3293f38dd66`;
- `models/background_removal/birefnet.safetensors`, exactly
  444,473,596 bytes with SHA-256
  `9ab37426bf4de0567af6b5d21b16151357149139362e6e8992021b8ce356a154`.

The verifier checks that both required commits are ancestors of the installed
ComfyUI `HEAD`, and validates the model byte size and hash. After any runtime
change, restart ComfyUI and additionally confirm that
`/object_info/LoadBackgroundRemovalModel` and
`/object_info/RemoveBackground` are non-empty before browser acceptance.
