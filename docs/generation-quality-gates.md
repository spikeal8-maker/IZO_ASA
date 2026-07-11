# Generation quality gates

The generator uses layered checks. No single test is treated as proof that the
whole product works.

## Required on every generation change

1. Backend contracts:
   `python -m pytest test_generation_protection.py test_openrouter_capabilities.py -q`
2. Frontend type/build check: `npm run build`
3. Frontend lint: `npm run lint`
4. Studio recovery and active-control visibility:
   `npm run e2e:studio-resilience`
5. Free OpenRouter payload matrix across every advertised text-to-image model and
   all four formats: `python generation_matrix_smoke.py`

## Controlled paid verification

Run only when provider routing, dimensions, billing, or output decoding changes:

`python generation_matrix_smoke.py --paid --model black-forest-labs/flux.2-klein-4b`

The paid matrix uses the first product template, "Миниатюрный город в разбитой
чашке", and checks square, portrait, 16:9, and 3:2 outputs. It decodes every file,
checks orientation, reports actual dimensions, and sums provider cost.

## Failure containment contract

- API error payloads are normalized to strings before entering React state.
- A broken picker thumbnail fails only its card and displays "Файл недоступен".
- Studio form state is debounced into session storage. Prompt, format, quality,
  seed, influence, style, source, and assembly slots survive a component remount.
- If heavy inline image data exceeds browser storage quota, settings and URL-based
  sources are still retained.
- The root error boundary remounts the studio without reloading the page. It does
  not render arbitrary thrown objects.

## Manual control

After automated checks, inspect at least one desktop and one phone viewport. Verify
the selected model name remains readable before and during hover, a failed image
does not clear other slots, and restored drafts match the visible controls.
