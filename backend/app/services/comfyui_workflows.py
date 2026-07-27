"""Pure ComfyUI workflow selection and graph builders."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol


class WorkflowLora(Protocol):
    id: str
    strength: float


class WorkflowRequest(Protocol):
    mode: str
    prompt: str
    negativePrompt: str | None
    width: int
    height: int
    seed: int
    steps: int
    cfg: float
    strength: float
    loras: Sequence[WorkflowLora]


WORKFLOW_ENDPOINTS = {
    "text_to_image": "workflow_t2i",
    "image_to_image": "workflow_i2i",
    "edit": "workflow_edit",
    "paint": "workflow_edit",
    "inpaint": "workflow_inpaint",
    "outpaint": "workflow_outpaint",
    # Dedicated workflow_faceswap hangs on Flux 2 Klein 9B in production.
    "faceswap": "workflow_edit",
    "remove_background": "workflow_remove_bg",
    "try_on": "workflow_edit",
    "texture_transfer": "workflow_edit",
}

PROFILE_MODEL_FALLBACKS = {
    "flux_klein_4b": "flux-2-klein-4b-fp8.safetensors",
    "flux_klein_9b": "flux-2-klein-9b-fp8.safetensors",
}


def active_profile_admin_files(
    profiles: Sequence[Mapping[str, Any]],
    profile_id: str,
    profile_settings: Mapping[str, Any],
) -> dict[str, Any]:
    active_profile = next((profile for profile in profiles if profile.get("id") == profile_id), {})
    is_9b = profile_id.endswith("9b")
    return {
        "modelFile": active_profile.get("modelName") or PROFILE_MODEL_FALLBACKS[profile_id],
        "textEncoder": "qwen_3_8b" if is_9b else "qwen_3_4b",
        "vae": "flux2-vae.safetensors",
        "sampler": profile_settings.get("sampler", "er_sde"),
        "width": profile_settings.get("width", 1024),
        "height": profile_settings.get("height", 1024),
        "steps": profile_settings.get("steps", 4),
        "seed": profile_settings.get("seedMode", "random"),
    }


def fallback_model_for_profile(profile_id: str) -> str:
    """Resolve built-in profiles even when the optional DB catalog is unavailable."""

    return PROFILE_MODEL_FALLBACKS.get(profile_id, profile_id)


def select_faceswap_lora(
    available_loras: Sequence[str],
    requested_id: str,
    requested_strength: float,
    model: str,
    *,
    enabled: Callable[[str], bool],
) -> tuple[str, float]:
    target_tag = "4b" if "4b" in model.lower() else "9b"
    candidate = requested_id.strip()
    if candidate and candidate != "none" and target_tag in candidate.lower() and candidate in available_loras and enabled(candidate):
        return candidate, requested_strength
    matches = [
        item for item in available_loras
        if target_tag in item.lower()
        and enabled(item)
        and any(keyword in item.lower() for keyword in ("bfs", "face", "head"))
    ]
    matches.sort(key=str.lower)
    match = matches[0] if matches else ""
    if not match:
        raise RuntimeError(
            f"Face LoRA для Flux Klein {target_tag.upper()} не установлена "
            "или выключена в Config UI."
        )
    return match, requested_strength


def edit_reference_megapixel_limit(
    *,
    profile_id: str,
    roles: Sequence[str],
    role: str,
    face_limit: float,
) -> float | None:
    """Bound 9B multi-reference conditioning while preserving model quality."""

    if "9b" in profile_id.lower() and "face" in roles and len(roles) >= 2:
        limit = 0.25 if len(roles) >= 3 else face_limit
        return min(face_limit, limit) if role == "face" else limit
    return face_limit if role == "face" else None


EDIT_SLOT_NODES = (
    {"load": "FK:91", "scale": "FK:163", "vae": "FK:132", "pos": "FK:133", "neg": "FK:131"},
    {"load": "FK:88", "scale": "FK:163b", "vae": "FK:232", "pos": "FK:233", "neg": "FK:231"},
    {"load": "FKE:301", "scale": "FKE:303", "vae": "FKE:305", "pos": "FKE:307", "neg": "FKE:309"},
    {"load": "FKE:401", "scale": "FKE:403", "vae": "FKE:405", "pos": "FKE:407", "neg": "FKE:409"},
)


def workflow_endpoint_for_mode(mode: str) -> str:
    return WORKFLOW_ENDPOINTS.get(mode, "workflow_t2i")


def set_input(prompt: dict[str, Any], node_id: str, key: str, value: Any) -> None:
    if node_id in prompt:
        prompt[node_id].setdefault("inputs", {})[key] = value


def patch_shared_flux_nodes(
    prompt: dict[str, Any],
    request: WorkflowRequest,
    model: str,
    text_encoder: str,
    vae: str,
    *,
    default_negative_prompt: str,
    model_profiles: Mapping[str, Mapping[str, Any]],
) -> None:
    set_input(prompt, "FK:165", "unet_name", model)
    set_input(prompt, "FK:155", "clip_name", text_encoder)
    set_input(prompt, "FK:153", "vae_name", vae)
    set_input(prompt, "FK:166", "text", request.prompt)
    negative = "" if request.mode in {"edit", "faceswap"} else (request.negativePrompt or default_negative_prompt)
    set_input(prompt, "FK:156", "text", negative)
    set_input(prompt, "FK:170", "width", request.width)
    set_input(prompt, "FK:170", "height", request.height)
    set_input(prompt, "FK:171", "seed", request.seed)
    set_input(prompt, "FK:171", "steps", request.steps)
    set_input(prompt, "FK:171", "cfg", request.cfg)
    set_input(prompt, "FK:171", "denoise", 1 if request.mode == "text_to_image" else request.strength)
    profile_id = "flux_klein_4b" if "4b" in model.lower() else "flux_klein_9b"
    set_input(prompt, "FK:171", "sampler_name", model_profiles[profile_id]["sampler"])
    set_input(prompt, "FK:171", "scheduler", "simple")
    set_input(prompt, "FK:86", "filename_prefix", "one-node-flux-2-klein/FK")


def patch_optional_lora(prompt: dict[str, Any], lora: WorkflowLora | None) -> None:
    if not lora or not lora.id or lora.id == "none":
        return
    loader_class = (
        "LoraLoaderBypassModelOnly"
        if "bfs_head_v1_flux-klein_9b" in lora.id.lower()
        else "LoraLoaderModelOnly"
    )
    for node in prompt.values():
        inputs = node.get("inputs") if isinstance(node, dict) else None
        if not isinstance(inputs, dict) or "lora_name" not in inputs:
            continue
        if node.get("class_type") in {"LoraLoaderModelOnly", "LoraLoaderBypassModelOnly"}:
            node["class_type"] = loader_class
        inputs["lora_name"] = lora.id
        if "strength_model" in inputs:
            inputs["strength_model"] = lora.strength
        if "strength_clip" in inputs:
            inputs["strength_clip"] = lora.strength
        return
    if "FK:165" in prompt and "FK:169" in prompt:
        prompt["FK:admin_lora"] = {
            "class_type": loader_class,
            "inputs": {"model": ["FK:165", 0], "lora_name": lora.id, "strength_model": lora.strength},
            "_meta": {"title": "Config UI LoRA"},
        }
        set_input(prompt, "FK:169", "model", ["FK:admin_lora", 0])


def _ensure_edit_slot_nodes(prompt: dict[str, Any], slot: int) -> None:
    nodes = EDIT_SLOT_NODES[slot]
    number = slot + 1
    prompt.setdefault(nodes["load"], {"class_type": "LoadImage", "inputs": {"image": "placeholder.png"}, "_meta": {"title": f"Load Image {number}"}})
    prompt.setdefault(nodes["scale"], {"class_type": "ImageScaleToTotalPixels", "inputs": {"image": [nodes["load"], 0], "upscale_method": "nearest-exact", "megapixels": 1, "resolution_steps": 1}, "_meta": {"title": f"Scale Image {number} to bounded size"}})
    prompt.setdefault(nodes["vae"], {"class_type": "VAEEncode", "inputs": {"pixels": [nodes["scale"], 0], "vae": ["FK:153", 0]}, "_meta": {"title": f"VAE Encode Image {number}"}})
    prompt.setdefault(nodes["pos"], {"class_type": "ReferenceLatent", "inputs": {"conditioning": ["FK:166", 0], "latent": [nodes["vae"], 0]}, "_meta": {"title": f"Reference Latent Positive Img{number}"}})
    prompt.setdefault(nodes["neg"], {"class_type": "ReferenceLatent", "inputs": {"conditioning": ["FK:156", 0], "latent": [nodes["vae"], 0]}, "_meta": {"title": f"Reference Latent Negative Img{number}"}})


def patch_edit_reference_chain(
    prompt: dict[str, Any],
    image_files: Sequence[str | None],
    reference_megapixels: Sequence[float | None] | None = None,
) -> None:
    sizes = list(reference_megapixels or ())
    present_files = [file_name for file_name in image_files if file_name][:4]
    present = [
        (file_name, sizes[index] if index < len(sizes) else None)
        for index, file_name in enumerate(present_files)
    ]
    if not present:
        raise RuntimeError("Для редактирования нужно хотя бы одно изображение (основа).")
    previous_positive, previous_negative = "FK:166", "FK:156"
    for index, (file_name, megapixels) in enumerate(present):
        _ensure_edit_slot_nodes(prompt, index)
        nodes = EDIT_SLOT_NODES[index]
        set_input(prompt, nodes["load"], "image", file_name)
        if megapixels is not None:
            set_input(prompt, nodes["scale"], "megapixels", round(max(0.001, megapixels), 6))
            prompt[nodes["scale"]].setdefault("_meta", {})["title"] = (
                f"Keep Image {index + 1} at bounded source size"
            )
        set_input(prompt, nodes["pos"], "conditioning", [previous_positive, 0])
        set_input(prompt, nodes["neg"], "conditioning", [previous_negative, 0])
        previous_positive, previous_negative = nodes["pos"], nodes["neg"]
    for index in range(len(present), 4):
        for node_id in EDIT_SLOT_NODES[index].values():
            prompt.pop(node_id, None)
    set_input(prompt, "FK:171", "positive", [previous_positive, 0])
    set_input(prompt, "FK:171", "negative", [previous_negative, 0])
    set_input(prompt, "FK:171", "denoise", 1)


def patch_mode_nodes(
    prompt: dict[str, Any],
    request: WorkflowRequest,
    uploads: Mapping[str, str],
    model: str,
    text_encoder: str,
    vae: str,
    *,
    default_negative_prompt: str,
    model_profiles: Mapping[str, Mapping[str, Any]],
    edit_reference_megapixels: Sequence[float | None] | None = None,
) -> None:
    patch_shared_flux_nodes(
        prompt,
        request,
        model,
        text_encoder,
        vae,
        default_negative_prompt=default_negative_prompt,
        model_profiles=model_profiles,
    )
    if request.mode == "image_to_image":
        set_input(prompt, "FKI2I:img", "image", uploads["input1"])
        set_input(prompt, "FK:171", "denoise", request.strength)
    elif request.mode == "remove_background":
        set_input(prompt, "rmbg:load", "bg_removal_name", "birefnet.safetensors")
        set_input(prompt, "rmbg:img", "image", uploads["input1"])
        set_input(prompt, "rmbg:save", "filename_prefix", "one-node-flux-2-klein/assets/rmbg")
    elif request.mode in {"edit", "paint", "faceswap", "try_on", "texture_transfer"}:
        image_files = [uploads.get(f"input{index}") for index in range(1, 5)]
        if request.mode in {"edit", "faceswap"}:
            patch_optional_lora(prompt, request.loras[0] if request.loras else None)
        lora_id = request.loras[0].id.lower() if request.loras else ""
        if request.mode == "faceswap" and "face_swap_flux_klein_9b" in lora_id:
            image_files[:2] = [image_files[1], image_files[0]]
            set_input(
                prompt,
                "FK:166",
                "text",
                "face_swap: take the face from Picture 1 and swap it onto the person in Picture 2. "
                "Preserve the exact face and features from Picture 1 and the body, pose, lighting, "
                f"and scene from Picture 2. {request.prompt}".strip(),
            )
        patch_edit_reference_chain(prompt, image_files, edit_reference_megapixels)
    elif request.mode == "inpaint":
        for node_id, key, value in (
            ("FKI:194", "unet_name", model), ("FKI:195", "clip_name", text_encoder),
            ("FKI:196", "vae_name", vae), ("FKI:6", "text", request.prompt),
            ("FKI:198", "image", uploads["input1"]), ("FKI:199", "image", uploads.get("mask", uploads["input1"])),
            ("FKI:209", "preresize_min_width", request.width), ("FKI:209", "preresize_min_height", request.height),
            ("FKI:209", "output_target_width", request.width), ("FKI:209", "output_target_height", request.height),
            ("FKI:163", "seed", request.seed), ("FKI:163", "steps", request.steps),
            ("FKI:163", "cfg", request.cfg), ("FKI:163", "denoise", request.strength),
            ("FKI:203", "filename_prefix", "one-node-flux-2-klein/FK"),
        ):
            set_input(prompt, node_id, key, value)
    elif request.mode == "outpaint":
        for node_id, key, value in (
            ("FKO:194", "unet_name", model), ("FKO:195", "clip_name", text_encoder),
            ("FKO:196", "vae_name", vae), ("FKO:6", "text", request.prompt),
            ("FKO:198", "image", uploads["input1"]), ("FKO:maskload", "image", uploads.get("mask", uploads["input1"])),
            ("FKO:209", "preresize_min_width", request.width), ("FKO:209", "preresize_min_height", request.height),
            ("FKO:209", "output_target_width", request.width), ("FKO:209", "output_target_height", request.height),
            ("FKO:163", "seed", request.seed), ("FKO:163", "steps", request.steps),
            ("FKO:163", "cfg", request.cfg), ("FKO:163", "denoise", 1),
            ("FKO:203", "filename_prefix", "one-node-flux-2-klein/FK"),
        ):
            set_input(prompt, node_id, key, value)


def build_pose_workflow(
    graph: dict[str, Any],
    models: Mapping[str, list[str]],
    profile: Mapping[str, Any],
    ref_image_name: str,
    pose_image_name: str,
    *,
    model: str,
    text_encoder: str,
    vae: str,
    seed: int,
) -> dict[str, Any]:
    pose_meta = (profile.get("settings") or {}).get("pose", {}) or {}
    pose_lora = next((name for name in models.get("loras", []) if "refcontrol" in name.lower()), pose_meta.get("lora", ""))
    graph["FKP:unet"]["inputs"]["unet_name"] = model
    graph["FKP:clip"]["inputs"]["clip_name"] = text_encoder
    graph["FKP:vae"]["inputs"]["vae_name"] = vae
    graph["FKP:lora"]["inputs"]["lora_name"] = pose_lora
    graph["FKP:refimg"]["inputs"]["image"] = ref_image_name
    graph["FKP:poseimg"]["inputs"]["image"] = pose_image_name
    graph["FKP:noise"]["inputs"]["noise_seed"] = seed
    return graph


def build_outpaint_workflow(
    graph: dict[str, Any],
    models: Mapping[str, list[str]],
    request: WorkflowRequest,
    uploads: Mapping[str, str],
    *,
    model: str,
    text_encoder: str,
    vae: str,
    lora_enabled: Callable[[str], bool],
    default_negative_prompt: str,
    model_profiles: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    if "4b" in model.lower():
        outpaint_lora = next(
            (name for name in models.get("loras", []) if "4b" in name.lower() and "outpaint" in name.lower()),
            "",
        )
        if not outpaint_lora:
            raise RuntimeError("Outpaint 4B is not ready: the compatible Outpaint LoRA is missing.")
        if not lora_enabled(outpaint_lora):
            raise RuntimeError("Outpaint 4B LoRA is disabled by the administrator.")
        graph.pop("FKO:216", None)
        graph["FKO:194"]["inputs"].update({"unet_name": model, "weight_dtype": "default"})
        graph["FKO:outpaint_lora"] = {
            "class_type": "LoraLoaderModelOnly",
            "inputs": {"model": ["FKO:194", 0], "lora_name": outpaint_lora, "strength_model": 1},
            "_meta": {"title": "Klein 4B Outpaint LoRA"},
        }
        graph["FKO:163"]["inputs"]["model"] = ["FKO:outpaint_lora", 0]
    else:
        kv_model = next(
            (
                name
                for name in models.get("diffusion_models", [])
                if "klein-9b-kv" in name.lower() and "fp8" in name.lower()
            ),
            "",
        )
        if not kv_model:
            raise RuntimeError("Outpaint 9B is not ready: the Klein 9B KV FP8 checkpoint is missing.")
        model = kv_model
        graph.pop("FKO:outpaint_lora", None)
        graph["FKO:194"]["inputs"].update({"unet_name": model, "weight_dtype": "default"})
        graph["FKO:216"]["inputs"]["model"] = ["FKO:194", 0]
        graph["FKO:163"]["inputs"]["model"] = ["FKO:216", 0]
    patch_mode_nodes(
        graph,
        request,
        uploads,
        model,
        text_encoder,
        vae,
        default_negative_prompt=default_negative_prompt,
        model_profiles=model_profiles,
    )
    return graph
