from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from PIL import Image

import main


PROMPT = (
    "На деревянном столе стоит треснувшая фарфоровая чашка, внутри чашки вырос "
    "крошечный ночной город с мостами, окнами, улицами и маленьким поездом по "
    "краю блюдца. Из трещины чашки вытекает тонкая светящаяся река. "
    "Макрофотография, реалистичный фарфор, уютный тёплый свет, без текста."
)
FORMATS = (
    ("square", 1024, 1024),
    ("portrait", 720, 1280),
    ("wide", 1280, 720),
    ("soft_wide", 1536, 1024),
)


def orientation(width: int, height: int) -> str:
    return "square" if width == height else "wide" if width > height else "portrait"


async def dry_run() -> int:
    catalog = await main.fetch_openrouter_image_capabilities(force=True)
    failures: list[str] = []
    checked = 0
    for capability in catalog:
        if "text_to_image" not in (capability.get("modes") or []):
            continue
        model = capability["id"]
        for name, width, height in FORMATS:
            request = main.GenerateRequest(
                mode="text_to_image",
                provider="openrouter",
                prompt=PROMPT,
                width=width,
                height=height,
                modelProfile=model,
            )
            try:
                plan = main.openrouter_image_request_plan(model, width, height)
                main.build_openrouter_image_body(request, model, plan, capability)
                checked += 1
            except Exception as exc:
                failures.append(f"{model} {name}: {exc}")
    print(f"dry_run_payloads={checked} failures={len(failures)}")
    for failure in failures:
        print(f"FAIL {failure}")
    return 1 if failures else 0


async def paid_run(model: str) -> int:
    main.persist_job = lambda *args, **kwargs: None
    failures: list[str] = []
    total_cost = 0.0
    for name, width, height in FORMATS:
        request = main.GenerateRequest(
            mode="text_to_image",
            provider="openrouter",
            prompt=PROMPT,
            width=width,
            height=height,
            modelProfile=model,
        )
        job = {"id": f"paid_matrix_{name}", "status": "queued", "progress": 0, "message": ""}
        try:
            result = await main.send_to_openrouter(request, job)
            path = Path(result.image_path)
            with Image.open(path) as image:
                image.verify()
            with Image.open(path) as image:
                actual = (image.width, image.height)
            if orientation(*actual) != orientation(width, height):
                raise RuntimeError(f"orientation mismatch: requested={width}x{height}, actual={actual[0]}x{actual[1]}")
            total_cost += float(result.cost_usd or 0)
            print(f"OK {name}: requested={width}x{height} actual={actual[0]}x{actual[1]} cost_usd={result.cost_usd}")
        except Exception as exc:
            failures.append(f"{name}: {exc}")
            print(f"FAIL {name}: {exc}")
    print(f"paid_failures={len(failures)} total_cost_usd={total_cost:.6f}")
    return 1 if failures else 0


async def main_async() -> int:
    parser = argparse.ArgumentParser(description="IZO image generation format matrix")
    parser.add_argument("--paid", action="store_true", help="perform four real paid OpenRouter generations")
    parser.add_argument("--model", default="black-forest-labs/flux.2-klein-4b")
    args = parser.parse_args()
    return await paid_run(args.model) if args.paid else await dry_run()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main_async()))
