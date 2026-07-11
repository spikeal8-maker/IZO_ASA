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
