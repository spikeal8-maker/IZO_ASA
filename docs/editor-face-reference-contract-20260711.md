# Assembly face-reference control — 2026-07-11

This contract covers the `Сборка` reference card when its role is `Лицо`.

The former standalone `Лицо` studio tab was removed on 2026-07-11. Face transfer is
owned only by the `Лицо` reference role in `Сборка`; old `#face` links open `Сборка`.
OpenRouter models may be offered for this role only through `Сборка` and only when
their live capability metadata reports at least two `input_references`.

## Visual contract

- The shared reference control panel, border and background remain visible.
- The label `Что взять из картинки` and role select remain visible, including after the
  user chooses `Лицо`, so the role can always be changed back.
- Face strength is a normal horizontal range below the role select.
- The range has one small native thumb. No percentage badge follows the thumb.
- The range resets global form-field chrome: no outer border, padding, minimum height or shadow.
- A separate percentage button is placed in a stable 34 px column at the right edge.
- The button displays the current value with `%` and resets the value to `75%` on click.

## Behaviour contract

- Default face-reference strength: `75%`.
- Range: `0..100`, step `1`.
- Existing near-75 snapping remains active.
- The value continues to affect only references whose role is `face`.
- Clothing, pose, body, background and other reference roles keep their existing logic.

## Regression protection

Run `npm run smoke:editor-contract`. The check protects the default value, role label,
separate percentage button, reset action and removal of the obsolete moving badge CSS.
