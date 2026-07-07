# Face tab upstream reference, 2026-07-07

## Purpose

This note records the current functional reference for the new `Лицо` tab in the `/new` interface.
It is intended for later testing and backend review, especially while another agent is working on backend/feed/DB tasks.

## Upstream Reference

Primary reference:

- GitHub: `https://github.com/yanokusnir-ai/one-node-flux-2-klein`
- ComfyUI route: `/flux_klein/workflow_faceswap`
- Workflow file: `workflows/faceswap_workflow.json`
- UI file: `web/one_node_flux_2_klein.js`

The upstream node implements FaceSwap as a dedicated workflow. It is not just the generic edit workflow with two reference images.

Upstream FaceSwap inputs:

- target image: image to replace the face in;
- source image: image whose face is used;
- Faceswap LoRA: selected from ComfyUI LoRA models;
- prompt: default face-swap prompt can be used or edited;
- model/text encoder/VAE from the Flux Klein settings.

## Current Local Status

The new frontend tab exists and produces a result.

Current UI contract:

- tab: `Лицо`;
- slots: `Основа` and `Лицо`;
- CTA: `Заменить лицо`;
- prompt is optional extra guidance;
- recommended face strength default: `75%`;
- user-visible hint: `Рекомендуем 75%. Ниже мягче смешивает лицо, выше сильнее переносит черты.`

The `75%` value is the current practical recommendation because manual testing showed it gives the best visible result. Keep it as the default unless later backend tests prove a better value.

Frontend payload expectation:

```ts
{
  mode: 'faceswap',
  inputImage1: baseTargetImage,
  inputImage2: sourceFaceImage,
  strength: faceStrengthPct / 100,
  loras: [{ id: faceLora.id, strength: faceStrengthPct / 100, triggerWord: faceLora.triggerWord }]
}
```

## Backend Review Note

Do not silently assume that the frontend payload means the dedicated upstream FaceSwap workflow is used.

Current backend code should be checked before release:

- `fetch_workflow("faceswap")` must be compared against upstream `/flux_klein/workflow_faceswap`;
- if `faceswap` is routed through `workflow_edit`, the face strength slider may not affect `FKF:226.strength_model`;
- if the dedicated workflow is restored, verify it does not hang on the current Flux Klein 9B production setup.

This is the main place to investigate if the user sees generation progress but the face does not change, or if changing the strength value from `75` to `100` gives the same result.

## Test Checklist

Use this checklist when testing the tab:

- load one target/base image and one source face image;
- keep strength at the default `75%`;
- generate once and verify the result changes the face while preserving the target scene;
- repeat at `35%` and `100%` only for comparison;
- confirm the result is different enough between low and high strength before calling the slider functional;
- verify ComfyUI exposes `/flux_klein/workflow_faceswap`;
- verify the backend route actually uses the intended workflow and LoRA strength.

## Related Files

- `D:/Google Drive/My progact/wt-integrated/frontend/src/newUi.tsx`
- `D:/Google Drive/My progact/wt-integrated/frontend/src/newStudioV3.css`
- `D:/Google Drive/My progact/wt-integrated/backend/main.py`
- `D:/Google Drive/My progact/Генератор картинок/backend/main.py`
