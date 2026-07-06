# IZO -> IZO v3 integration baseline, 2026-07-06

## Scope

This document records the first functional v3 implementation of the `Изо -> Изо` tab in the new `/new` interface.

Source references:

- `C:/Users/spike/Downloads/Новый интерфейс/2. Изо-Изо/izo-aca-new-responsive-page.html`
- `C:/Users/spike/Downloads/Новый интерфейс/2. Изо-Изо/izo-aca-i2i-integration.md`

The legacy production interface is not changed by this work. The new tab lives in the canonical new UI worktree:

- `D:/Google Drive/My progact/wt-integrated/frontend/src/newUi.tsx`
- `D:/Google Drive/My progact/wt-integrated/frontend/src/newStudioV3.css`

## UI Contract

`Изо -> Изо` reuses the existing v3 studio shell from `Текст -> Изо`:

- top navigation;
- preview/result panel;
- recent history strip;
- `Промпт изображения` dock;
- style row;
- format controls;
- quality controls;
- mobile fixed CTA.

Mode-specific differences:

- active mode: `Изо -> Изо`;
- page title: `Изо в изображение`;
- CTA: `Преобразовать`;
- prompt title: `Как преобразовать?`;
- prompt placeholder: `Опишите, как преобразовать исходное изображение...`;
- prompt limit: `1000`;
- source block appears before the prompt.

## Source Image Block

The block is inserted as:

```html
<section class="form-section i2i-source-section">
```

It contains two cards:

- upload/source card;
- `Влияние промпта` card.

Source actions:

- `Загрузить` opens the existing hidden file input and stores a `FileReader` data URL in `sourceImage`;
- `Галерея` opens the existing gallery picker and stores the selected gallery URL as `sourceImage`;
- `Последнее` uses the current result URL first, then the newest gallery image, then the selected/history image;
- all three actions include icons and keep a fixed button footprint.
- `x` clears `sourceImage` and returns the card to the required empty state.

The upload card intentionally stays inside the v3 sidebar and does not duplicate the whole page.

Layout stability:

- upload card and prompt-influence card share the same `--i2i-card-h` height;
- empty and filled source states must not change the source section height;
- preview padding uses border-box sizing to avoid image-load layout jumps.

Preview behavior:

- selected source images use `object-fit: contain`;
- portrait, landscape, and square images must remain fully visible in the source cell;
- dark/black padding is acceptable and preferred over cropping important parts of the source.
- the main result preview also keeps the generated image on `object-fit: contain`; the blurred backdrop may use `cover`.

## Prompt Influence

State:

```ts
const [strengthPct, setStrengthPct] = useState(75)
```

Rules:

- default value: `75`;
- min/max: `0..100`;
- snap: values within `75 +/- 3` become exactly `75`;
- clicking the `75` label sets the value to `75`.
- the numeric value in the card header is editable; typing a number updates the same `strengthPct` state as the range.

Backend payload:

```ts
{
  mode: 'image_to_image',
  inputImage1: sourceImage,
  width: selectedResolution.width,
  height: selectedResolution.height,
  strength: strengthPct / 100
}
```

The text prompt for `Изо -> Изо` is combined with the selected style transform prompt before sending.

Output format contract:

- the selected format is part of the IZO -> IZO request identity; changing only the format allows a new generation;
- backend `image_to_image` input preparation uses the requested `width x height` as a ComfyUI canvas;
- the source image is scaled up/down to fit fully inside that canvas without cropping;
- empty canvas areas are black, so the workflow receives the requested aspect ratio instead of silently keeping the source-image aspect ratio;
- other upload modes keep the older aspect-preserving input resize unless their own mode has a dedicated canvas/mask contract.

Prompt composition:

- `Шаблоны` in `Изо -> Изо` show visual transform cards and append their transform text into the prompt textarea;
- users may add several templates and edit the combined text before generation;
- selecting a style in the style row appends/replaces one visible `Стиль преобразования:` block at the end of the same textarea;
- no extra style prompt panel is shown below the textarea;
- backend prompt is the visible textarea value, so the user sees the text that will be sent.

Duplicate-submit guard:

- after a successful Text -> Image submit, pressing generate again with the exact same prompt is blocked;
- after a successful IZO -> IZO submit, pressing `Преобразовать` again with the same prompt and the same source image is blocked;
- the user must edit the prompt or replace the source image before another IZO -> IZO submit.

User notices:

- studio notices render as a large centered card inside the preview panel;
- the old bottom toast is kept only for the feed view;
- editing the prompt or replacing the source clears the persistent notice.

History strip:

- history thumbnails start from backend `width/height` or feed `aspectRatio`, then each loaded `<img>` rewrites its parent inline `aspect-ratio` from `naturalWidth / naturalHeight`;
- this natural-size correction is required for old or incomplete gallery/feed records, so portrait images do not fall back to square tiles after reload;
- thumbnail images use `object-fit: cover` inside their matching-ratio cell, avoiding black bars and avoiding visible crop when the frame ratio matches the actual image ratio;
- the left/right arrows are transparent overlays on top of the strip, not reserved black columns;
- arrow chevrons remain visible while images can visually run edge-to-edge behind them;
- arrow hover must stay transparent (`background: transparent`, no shadow), because the global button hover rule otherwise creates a dark patch over the thumbnails.

Before/after compare:

- IZO -> IZO results with a stored source image render a draggable before/after comparison in the main preview;
- the divider and handle use the brand yellow (`var(--lime)`);
- the handle uses one compact bidirectional arrow (`↔`), not two separate chevrons; mobile handle size is smaller than desktop;
- `До` / `После` labels are plain text over the preview, without heavy rounded backplates;
- the divider starts near the `После` edge (`96%`) and, if untouched, animates toward the `До` edge (`4%`) over about 2 seconds to reveal the result;
- users can drag the invisible range over the preview to compare source and result manually.

## Current Checks To Keep

- `/new` Text -> Image must continue using the same title, prompt limit `2000`, and CTA `Сгенерировать`.
- `/new` IZO -> IZO must show source image, prompt influence, prompt, styles, format, quality, and CTA.
- Mobile width must keep the source block readable before the prompt and keep the fixed CTA available.
