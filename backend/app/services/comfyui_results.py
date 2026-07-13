"""Import-safe ComfyUI response parsing and downloaded-image adapter."""

from __future__ import annotations

import io
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image


@dataclass
class ComfyUIResult:
    prompt_id: str
    image_path: Path
    thumbnail_path: Path
    history: dict[str, Any]


def prompt_id_from_submission(payload: dict[str, Any]) -> str:
    error = payload.get("error")
    if error:
        raise RuntimeError(f"ComfyUI workflow error: {error}")
    node_errors = payload.get("node_errors") or {}
    if node_errors:
        raise RuntimeError(f"ComfyUI node errors: {json.dumps(node_errors, ensure_ascii=False)}")
    prompt_id = payload.get("prompt_id")
    if not prompt_id:
        raise RuntimeError("ComfyUI не вернул prompt_id.")
    return prompt_id


def extract_images_from_history(history: dict[str, Any]) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    outputs = history.get("outputs", {})
    for output in outputs.values():
        for image in output.get("images", []):
            if image.get("filename"):
                found.append(
                    {
                        "filename": image["filename"],
                        "subfolder": image.get("subfolder", ""),
                        "type": image.get("type", "output"),
                    }
                )
    return found


def persist_downloaded_image(
    content: bytes,
    job_id: str,
    *,
    save_original: Callable[[Image.Image, str], Path],
    create_thumbnail: Callable[[Path], Path],
) -> tuple[Path, Path]:
    with Image.open(io.BytesIO(content)) as opened:
        image_path = save_original(opened, f"{job_id}_comfyui")
    return image_path, create_thumbnail(image_path)
