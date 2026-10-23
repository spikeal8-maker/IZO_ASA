"""COMFYUI-BRIDGE-D2R2-001: opt-in, exact graph for installed commercial-safe 4B.

No custom nodes, model downloads, file inputs, LoRA or code-bearing graph nodes.
The same pure graph validator runs inside Docker relay AND Windows host agent.
"""
from __future__ import annotations

import json
import re
from typing import Any

MODEL = "flux-2-klein-4b-fp8.safetensors"
ENCODER = "qwen_3_4b_fp4_flux2.safetensors"
VAE = "flux2-vae.safetensors"
PREFIX = "Comfy214/local4b"
PROFILES = {"", "default", "local_flux_klein", "flux_klein_4b"}
CORE_NODES = frozenset({
    "UNETLoader", "CLIPLoader", "VAELoader", "CLIPTextEncode",
    "ConditioningZeroOut", "CFGGuider", "KSamplerSelect",
    "Flux2Scheduler", "EmptyFlux2LatentImage", "RandomNoise",
    "SamplerCustomAdvanced", "VAEDecode", "SaveImage",
})


class Native4BError(ValueError):
    pass


def check_request(
    *, mode: str, profile: str, width: int, height: int,
    prompt: str, steps: int, loras: int = 0,
) -> None:
    if mode != "text_to_image" or profile not in PROFILES:
        raise Native4BError("NATIVE4B_TEXT_TO_IMAGE_ONLY")
    if loras:
        raise Native4BError("NATIVE4B_LORA_DISABLED")
    if type(width) is not int or type(height) is not int:
        raise Native4BError("NATIVE4B_DIMENSIONS_INVALID")
    if not (512 <= width <= 768 and 512 <= height <= 768):
        raise Native4BError("NATIVE4B_RESOLUTION_LIMIT_512_TO_768")
    if width % 16 or height % 16:
        raise Native4BError("NATIVE4B_RESOLUTION_ALIGNMENT")
    if type(steps) is not int or steps != 4:
        raise Native4BError("NATIVE4B_DISTILLED_STEPS_MUST_BE_FOUR")
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 2000:
        raise Native4BError("NATIVE4B_PROMPT_INVALID")
    if any(ord(c) < 32 and c not in "\t\n" for c in prompt):
        raise Native4BError("NATIVE4B_PROMPT_CONTROL_CHAR")


def graph(*, prompt: str, width: int, height: int, seed: int) -> dict[str, dict[str, Any]]:
    check_request(mode="text_to_image", profile="flux_klein_4b",
                  width=width, height=height, prompt=prompt, steps=4)
    if type(seed) is not int or not 0 <= seed <= 0xFFFFFFFFFFFFFFFF:
        raise Native4BError("NATIVE4B_SEED_INVALID")
    return {
        "70": {"class_type": "UNETLoader",
               "inputs": {"unet_name": MODEL, "weight_dtype": "default"}},
        "71": {"class_type": "CLIPLoader",
               "inputs": {"clip_name": ENCODER, "type": "flux2"}},
        "72": {"class_type": "VAELoader", "inputs": {"vae_name": VAE}},
        "74": {"class_type": "CLIPTextEncode",
               "inputs": {"clip": ["71", 0], "text": prompt}},
        "76": {"class_type": "ConditioningZeroOut",
               "inputs": {"conditioning": ["74", 0]}},
        "63": {"class_type": "CFGGuider",
               "inputs": {"model": ["70", 0], "positive": ["74", 0],
                          "negative": ["76", 0], "cfg": 1.0}},
        "61": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "62": {"class_type": "Flux2Scheduler",
               "inputs": {"steps": 4, "width": width, "height": height}},
        "66": {"class_type": "EmptyFlux2LatentImage",
               "inputs": {"width": width, "height": height, "batch_size": 1}},
        "73": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "64": {"class_type": "SamplerCustomAdvanced",
               "inputs": {"noise": ["73", 0], "guider": ["63", 0],
                          "sampler": ["61", 0], "sigmas": ["62", 0],
                          "latent_image": ["66", 0]}},
        "65": {"class_type": "VAEDecode",
               "inputs": {"samples": ["64", 0], "vae": ["72", 0]}},
        "9": {"class_type": "SaveImage",
              "inputs": {"images": ["65", 0], "filename_prefix": PREFIX}},
    }


def validate_submitted_graph(request: Any) -> bool:
    """Full equality to canonical graph prevents arbitrary custom code / file ops."""
    if not isinstance(request, dict) or set(request) - {"prompt", "client_id", "extra_data"}:
        return False
    submitted = request.get("prompt")
    if not isinstance(submitted, dict) or set(submitted) != {
        "70", "71", "72", "74", "76", "63", "61", "62", "66",
        "73", "64", "65", "9",
    }:
        return False
    try:
        props = submitted["74"]["inputs"]["text"]
        w = submitted["66"]["inputs"]["width"]
        h = submitted["66"]["inputs"]["height"]
        seed = submitted["73"]["inputs"]["noise_seed"]
        if graph(prompt=props, width=w, height=h, seed=seed) != submitted:
            return False
        cid = request.get("client_id")
        if not isinstance(cid, str) or not re.fullmatch(r"onenode-backend-[A-Za-z0-9_-]{6,100}", cid):
            return False
        return request.get("extra_data") in (None, {"enable_previews": True})
    except (KeyError, TypeError, ValueError):
        return False


def validate_model_inventory(data: dict[str, Any]) -> bool:
    return (MODEL in data.get("diffusion_models", [])
            and ENCODER in data.get("text_encoders", [])
            and VAE in data.get("vaes", []))

def validate_bridge_route(method: str, target: str, body: bytes = b"") -> bool:
    """Identical strict path/graph policy on bridge and Windows host agent."""
    from urllib.parse import parse_qs, urlsplit

    if not isinstance(target, str) or not target.startswith("/") or len(target) > 350:
        return False
    if any(ord(c) < 32 for c in target) or "%" in target or "\\" in target:
        return False
    parsed = urlsplit(target)
    if parsed.fragment or parsed.username or parsed.hostname:
        return False
    path = parsed.path
    if method == "GET":
        if not parsed.query and path in (
            "/system_stats", "/queue", "/object_info",
            "/object_info/UNETLoader", "/object_info/CLIPLoader",
            "/object_info/VAELoader",
        ):
            return True
        if not parsed.query and re.fullmatch(
            r"/history/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", path
        ):
            return True
        if path == "/view":
            try:
                args = parse_qs(parsed.query, strict_parsing=True)
                return (set(args) == {"filename", "subfolder", "type"}
                        and len(args["filename"]) == len(args["subfolder"]) == len(args["type"]) == 1
                        and re.fullmatch(r"local4b_[0-9]{5}_.png", args["filename"][0]) is not None
                        and args["subfolder"] == ["Comfy214"]
                        and args["type"] == ["output"])
            except ValueError:
                return False
        return False
    if method != "POST" or parsed.query or path != "/prompt":
        return False
    try:
        return validate_submitted_graph(json.loads(body))
    except (ValueError, UnicodeDecodeError):
        return False

async def execute_request(payload: Any, job: dict[str, Any], *, available: Any,
                          inventory: Any, enabled: Any, submit: Any,
                          download: Any, result_factory: Any) -> Any:
    """Execute one acknowledged Comfy t2i under the existing job ledger."""
    check_request(mode=payload.mode, profile=payload.modelProfile or "",
                  width=payload.width, height=payload.height,
                  prompt=payload.prompt, steps=payload.steps, loras=len(payload.loras or []))
    if not await available():
        raise RuntimeError("NATIVE4B_COMFY_UNAVAILABLE_OR_CHECKPOINT_MISSING")
    if not validate_model_inventory(await inventory()):
        raise RuntimeError("NATIVE4B_REQUIRED_FILES_NOT_INSTALLED")
    if not enabled():
        raise RuntimeError("NATIVE4B_IMAGE_GENERATION_DISABLED")
    built = graph(prompt=payload.prompt, width=payload.width,
                  height=payload.height, seed=int(payload.seed or 0))
    ident, history, images = await submit(built, job)
    if not images:
        raise RuntimeError("NATIVE4B_NO_REAL_COMFY_IMAGE")
    output, thumbnail = await download(images[-1], job["id"])
    return result_factory(prompt_id=ident, image_path=output,
                          thumbnail_path=thumbnail, history=history)
