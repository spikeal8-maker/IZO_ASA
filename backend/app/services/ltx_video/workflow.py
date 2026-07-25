from __future__ import annotations

import copy
import json
import secrets
from pathlib import Path
from typing import Any

from .profiles import LTX_480P_SIZES, LtxProfile


class LtxWorkflowError(RuntimeError):
    pass


_UNET_BY_QUANTIZATION = {
    "Q3_K_M": "ltx-2.3-22b-distilled-1.1-Q3_K_M.gguf",
    "Q4_K_M": "ltx-2.3-22b-distilled-1.1-Q4_K_M.gguf",
}


def _api_prompt(document: dict[str, Any]) -> dict[str, Any]:
    if document and all(
        isinstance(value, dict) and "class_type" in value for value in document.values()
    ):
        return document
    prompt = (document.get("extra") or {}).get("prompt")
    if isinstance(prompt, dict) and prompt:
        return prompt
    raise LtxWorkflowError("LTX workflow does not contain an API prompt")


def _nodes(prompt: dict[str, Any], *class_types: str) -> list[dict[str, Any]]:
    return [
        node
        for node in prompt.values()
        if isinstance(node, dict) and node.get("class_type") in class_types
    ]


def build_ltx_prompt(
    workflow_path: Path,
    *,
    profile: LtxProfile,
    text: str,
    duration: int,
    aspect_ratio: str = "16:9",
    filename_prefix: str,
) -> dict[str, Any]:
    try:
        document = json.loads(workflow_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LtxWorkflowError(f"Cannot read LTX workflow: {exc}") from exc
    prompt = copy.deepcopy(_api_prompt(document))

    unet_nodes = _nodes(prompt, "UnetLoaderGGUF")
    if len(unet_nodes) != 1:
        raise LtxWorkflowError("LTX workflow must contain exactly one GGUF model loader")
    try:
        unet_name = _UNET_BY_QUANTIZATION[profile.quantization]
    except KeyError as exc:
        raise LtxWorkflowError(
            f"Unsupported LTX quantization: {profile.quantization}"
        ) from exc
    unet_nodes[0].setdefault("inputs", {})["unet_name"] = unet_name

    text_nodes = _nodes(prompt, "CLIPTextEncode")
    if len(text_nodes) < 2:
        raise LtxWorkflowError("LTX workflow must contain positive and negative text nodes")
    positive = max(text_nodes, key=lambda node: len(str((node.get("inputs") or {}).get("text") or "")))
    positive.setdefault("inputs", {})["text"] = text.strip()

    frame_count = duration * 24 + 1
    if (frame_count - 1) % 8:
        raise LtxWorkflowError("LTX frame count must satisfy (frames - 1) % 8 == 0")

    latent_nodes = _nodes(prompt, "EmptyLTXVLatentVideo")
    if len(latent_nodes) != 1:
        raise LtxWorkflowError("LTX workflow must contain exactly one video latent node")
    latent_inputs = latent_nodes[0].setdefault("inputs", {})
    try:
        width, height = LTX_480P_SIZES[aspect_ratio]
    except KeyError as exc:
        raise LtxWorkflowError(f"Unsupported LTX aspect ratio: {aspect_ratio}") from exc
    latent_inputs["width"] = width
    latent_inputs["height"] = height
    length = latent_inputs.get("length")
    if isinstance(length, list) and length:
        frame_node = prompt.get(str(length[0]))
        if not isinstance(frame_node, dict):
            raise LtxWorkflowError("LTX frame-count node is missing")
        frame_node.setdefault("inputs", {})["value"] = frame_count
    else:
        latent_inputs["length"] = frame_count

    scheduler_nodes = _nodes(prompt, "LTXVScheduler")
    if scheduler_nodes:
        scheduler_nodes[0].setdefault("inputs", {})["steps"] = profile.steps
    for node in _nodes(prompt, "RandomNoise"):
        node.setdefault("inputs", {})["noise_seed"] = secrets.randbits(63)

    output_nodes = _nodes(prompt, "VHS_VideoCombine", "SaveVideo")
    if not output_nodes:
        raise LtxWorkflowError("LTX workflow has no video output node")
    for node in output_nodes:
        inputs = node.setdefault("inputs", {})
        inputs["filename_prefix"] = filename_prefix
        if node.get("class_type") == "VHS_VideoCombine":
            inputs["save_output"] = True
            inputs["format"] = "video/h264-mp4"
            inputs["frame_rate"] = 24

    return prompt
