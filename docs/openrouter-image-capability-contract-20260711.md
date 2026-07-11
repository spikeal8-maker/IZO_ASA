# OpenRouter image capability contract — 2026-07-11

The admin model lists prefer capability data from `GET /api/v1/images/models`
instead of inferring support from model names. Capability metadata is cached for six hours.
If a running backend predates this response field or discovery is temporarily
unavailable, the admin UI must show the verified local catalog with prices and
controls. An absent live catalog must never render every mode as an empty list.

## Mode rules

- `По тексту`: text input and image output.
- `По фото`: image output and `input_references.max >= 1`.
- `Сборка`: image output and `input_references.max >= 2`.
- `Редактор — эскиз и правки`: the same minimum as `По фото`.
- `Редактор — маска`: an explicit `mask`, `mask_image`, or `inpaint` parameter.
- `Редактор — расширение`: an explicit `outpaint`, `outpaint_mask`, or `canvas` parameter.
- `Редактор — удалить фон`: at least one input reference and `background=transparent`.

Do not infer mask or outpaint support from generic image input, aspect ratio,
resolution, quality, or background parameters. A model may appear in several modes
when its declared capabilities satisfy each mode independently.

## Current live audit

Audit date: 2026-07-11. OpenRouter returned 39 image models:

- text to image: 39;
- one-image editing: 34;
- multi-reference assembly: 22;
- sketch/reference editing: 34;
- native mask: 0;
- native outpaint: 0;
- transparent-background editing candidates: 6.

Counts are informational and may change after the six-hour cache refresh.

## Configuration safety

Admin configuration is filtered against the live capability catalog when it is
displayed and saved. Incompatible enabled models, defaults, tariff access entries,
and quality defaults are removed. Historical OpenRouter jobs remain readable.

Run `python -m pytest test_openrouter_capabilities.py -q` from `backend` to verify
the classification and stale-configuration cleanup contracts.

## По фото request contract

- OpenRouter is allowed for `image_to_image` only when live metadata reports that mode.
- The source is sent as one `input_references` image URL; private project media is
  converted to an inline data URL before leaving the backend.
- The UI percentage remains native `denoise` for ComfyUI. For OpenRouter it is a
  semantic edit-influence instruction and is described as such in the UI.
- Seed is sent only when the selected endpoint advertises `seed`.
- Job metadata records reference count, influence percent and whether seed was sent,
  but never records the inline image bytes.
- An obsolete admin assignment cannot bypass the live capability check.

The 2026-07-11 payload matrix built a valid one-reference request for all 34 models
that advertised `image_to_image`; no paid provider calls were made by that matrix.

## Aspect ratio and actual resolution

- The format control expresses the target aspect ratio. It is not a promise that
  every provider will return the UI preset's exact pixel dimensions.
- When a model advertises `aspect_ratio`, the backend sends the normalized ratio
  (`1:1`, `16:9`, `9:16`, or `3:2`). When it also advertises `resolution`, the
  backend sends the model-appropriate tier separately. It must not send a
  conflicting square `size`.
- The former `google_1k_safe_size` branch forced every Google request to
  `1024x1024`; it was removed because it silently broke non-square selections in
  both `text_to_image` and `image_to_image`.
- The gallery and job contract store the decoded output's real width and height.
  The result preview displays those actual dimensions after generation.
- Paid verification on 2026-07-11 used `google/gemini-3-pro-image` with a `16:9`
  request. Both text-to-image and image-to-image returned valid `1376x768` files,
  confirming provider-normalized wide output rather than the old square fallback.
