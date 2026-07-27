"""Explicit local ComfyUI acceptance runner.

This script never uses the production database or media directory. It refuses
to submit while ComfyUI already has a running or pending prompt, so an operator
can validate one real workflow at a time without jumping ahead of user work.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import io
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from urllib.request import urlopen

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
RUN_ID = f"{int(time.time())}-{os.getpid()}"
TEMP_ROOT = Path(tempfile.gettempdir()) / f"izo-comfy-acceptance-{RUN_ID}"

os.environ.setdefault("DATABASE_URL", f"sqlite:///{(TEMP_ROOT / 'database.sqlite3').as_posix()}")
os.environ.setdefault("MEDIA_DIR", str(TEMP_ROOT / "media"))
os.environ.setdefault("COMFYUI_IMAGE_TIMEOUT_SECONDS", "600")
os.environ.setdefault("COMFYUI_WATCHDOG_REQUEST_PATH", str(TEMP_ROOT / "watchdog-request.json"))
sys.path.insert(0, str(BACKEND))

import main  # noqa: E402


SOURCE_PATHS = (
    BACKEND / "static" / "og" / "izo-asa-og.jpg",
    ROOT / "frontend" / "src" / "assets" / "preview-placeholder.jpg",
    ROOT / "frontend" / "src" / "assets" / "hero.png",
)


def data_url(path: Path) -> str:
    media_type = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    return f"data:{media_type};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def mask_data_url(size: tuple[int, int] = (512, 512)) -> str:
    image = Image.new("RGB", size, "black")
    draw = ImageDraw.Draw(image)
    draw.rectangle((size[0] // 2, 0, size[0] - 1, size[1] - 1), fill="white")
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return f"data:image/png;base64,{base64.b64encode(buffer.getvalue()).decode('ascii')}"


def assert_queue_empty() -> None:
    with urlopen("http://127.0.0.1:8188/queue", timeout=5) as response:
        queue = json.load(response)
    running = len(queue.get("queue_running") or [])
    pending = len(queue.get("queue_pending") or [])
    if running or pending:
        raise RuntimeError(f"ComfyUI queue is busy: running={running}, pending={pending}")


def build_request(mode: str, profile: str) -> main.GenerateRequest:
    first, second, third = (data_url(path) for path in SOURCE_PATHS)
    common = {
        "mode": mode,
        "modelProfile": profile,
        "prompt": "Create a coherent realistic result while preserving the primary composition.",
        "width": 512,
        "height": 512,
        "steps": 2,
        "cfg": 1.0,
        "seed": 24072026,
    }
    if mode == "text_to_image":
        common["prompt"] = "A small modern art studio, daylight, realistic interior photograph."
    elif mode == "image_to_image":
        common.update(inputImage1=first, strength=0.35)
    elif mode in {"edit", "edit_face"}:
        common["inputImages"] = [
            main.EditImage(index=1, role="base", image=first),
            main.EditImage(index=2, role="face" if mode == "edit_face" else "style", image=second),
        ]
        if mode in {"edit", "edit_face"}:
            common["inputImages"].append(
                main.EditImage(index=3, role="background", image=third)
            )
        if mode == "edit_face":
            common["mode"] = "edit"
            common.update(width=1024, height=1024)
            common["loras"] = [
                main.Lora(id="bfs_head_v1_flux-klein_4b.safetensors", strength=0.75)
            ]
    elif mode == "faceswap":
        common.update(
            inputImage1=data_url(ROOT / "frontend" / "public" / "avatars" / "avatar-050.webp"),
            inputImage2=data_url(ROOT / "frontend" / "public" / "avatars" / "avatar-001.webp"),
        )
    elif mode == "inpaint":
        common.update(inputImage1=first, maskImage=mask_data_url(), strength=0.65)
    elif mode == "outpaint":
        common.update(
            inputImage1=first,
            outpaint={"left": 96, "right": 96, "top": 0, "bottom": 0},
        )
    else:
        raise ValueError(f"Unsupported acceptance mode: {mode}")
    return main.GenerateRequest(**common)


async def run(mode: str, profile: str) -> dict[str, object]:
    assert_queue_empty()
    request = build_request(mode, profile)
    job_id = f"accept-{profile}-{mode}-{RUN_ID}"
    job = {"id": job_id, "status": "processing", "progress": 24}
    started = time.monotonic()
    result = await main.send_to_comfyui(request, job)
    elapsed = round(time.monotonic() - started, 1)
    with Image.open(result.image_path) as image:
        dimensions = list(image.size)
    digest = hashlib.sha256(result.image_path.read_bytes()).hexdigest()
    return {
        "mode": mode,
        "profile": profile,
        "promptId": result.prompt_id,
        "elapsedSeconds": elapsed,
        "dimensions": dimensions,
        "sha256": digest,
        "output": str(result.image_path),
        "progress": job.get("progress"),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        required=True,
        choices=("text_to_image", "image_to_image", "edit", "edit_face", "faceswap", "inpaint", "outpaint"),
    )
    parser.add_argument("--profile", required=True, choices=("flux_klein_4b", "flux_klein_9b"))
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    print(json.dumps(asyncio.run(run(arguments.mode, arguments.profile)), ensure_ascii=False))
