# Paint page editor, 2026-07-07

## Purpose

`Рисунок` is a separate editor page inside the new `/new` UI. It is not a small form block: the preview area becomes a workbench, and the left sidebar switches between paint-specific toolsets.

## Modes

The first integrated version exposes four sidebar modes:

- `Эскиз` -> backend mode `paint`;
- `Маска` -> backend mode `inpaint`;
- `Расширение` -> backend mode `outpaint`;
- `Удалить фон` -> backend mode `remove_background`.

## Current Contract

Shared shell:

- the same top navigation as the rest of `/new`;
- the same result/history dock;
- the same format and quality controls;
- a fixed bottom CTA on mobile;
- the preview panel turns into a canvas/workbench while `Рисунок` is active.

Current tools:

- sketch canvas: brush, eraser, color, rectangle, circle, fill/outline, white/gray background;
- mask canvas: source image behind the canvas, brush/eraser mask drawing;
- outpaint: source image upload plus left/right/top/bottom expansion controls;
- remove background: source image upload and dedicated submit route.

## Backend Payload

Sketch:

```ts
{
  mode: 'paint',
  canvas: paintCanvasDataUrl
}
```

Mask:

```ts
{
  mode: 'inpaint',
  inputImage1: paintImage,
  maskImage: generatedMaskPng
}
```

Outpaint:

```ts
{
  mode: 'outpaint',
  inputImage1: paintImage,
  outpaint: { left, right, top, bottom }
}
```

Remove background:

```ts
{
  mode: 'remove_background',
  inputImage1: paintImage
}
```

## Next Layers

This is the first working editor shell, not the final vector editor.

Planned follow-up layers:

- movable vector objects instead of only final-line geometry;
- polygon/star tool with adjustable point count;
- fill bucket;
- image layer import/edit inside sketch mode;
- zoom/pan on the canvas itself;
- layer list with visibility/opacity/reorder;
- dedicated outpaint drag frame, where the user positions the source image inside the target format visually.
