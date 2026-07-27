from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import comfyui_workflows


MODEL_PROFILES = {
    "flux_klein_4b": {"sampler": "euler"},
    "flux_klein_9b": {"sampler": "er_sde"},
}


def workflow_request(mode: str, **overrides):
    values = {
        "mode": mode,
        "prompt": "portrait",
        "negativePrompt": None,
        "width": 1024,
        "height": 768,
        "seed": 42,
        "steps": 4,
        "cfg": 1.0,
        "strength": 0.45,
        "loras": [],
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def shared_graph() -> dict:
    return {
        node_id: {"inputs": {}}
        for node_id in (
            "FK:165", "FK:155", "FK:153", "FK:166", "FK:156",
            "FK:170", "FK:171", "FK:86",
        )
    }


def test_workflow_endpoint_mapping_preserves_all_modes_and_default() -> None:
    assert comfyui_workflows.WORKFLOW_ENDPOINTS == {
        "text_to_image": "workflow_t2i",
        "image_to_image": "workflow_i2i",
        "edit": "workflow_edit",
        "paint": "workflow_edit",
        "inpaint": "workflow_inpaint",
        "outpaint": "workflow_outpaint",
        "faceswap": "workflow_edit",
        "remove_background": "workflow_remove_bg",
        "try_on": "workflow_edit",
        "texture_transfer": "workflow_edit",
    }
    assert comfyui_workflows.workflow_endpoint_for_mode("unknown") == "workflow_t2i"


def test_builtin_model_profiles_have_database_independent_fallbacks() -> None:
    assert comfyui_workflows.fallback_model_for_profile("flux_klein_4b") == (
        "flux-2-klein-4b-fp8.safetensors"
    )
    assert comfyui_workflows.fallback_model_for_profile("flux_klein_9b") == (
        "flux-2-klein-9b-fp8.safetensors"
    )
    assert comfyui_workflows.fallback_model_for_profile("custom.safetensors") == (
        "custom.safetensors"
    )


def test_set_input_only_mutates_existing_node() -> None:
    graph = {"node": {}}

    comfyui_workflows.set_input(graph, "node", "value", 7)
    comfyui_workflows.set_input(graph, "missing", "value", 9)

    assert graph == {"node": {"inputs": {"value": 7}}}


@pytest.mark.parametrize(
    ("mode", "model", "negative", "expected_negative", "expected_sampler", "expected_denoise"),
    [
        ("text_to_image", "flux-klein-9b.safetensors", None, "default-neg", "er_sde", 1),
        ("image_to_image", "flux-klein-4b.safetensors", "custom-neg", "custom-neg", "euler", 0.45),
        ("edit", "flux-klein-9b.safetensors", "must-drop", "", "er_sde", 0.45),
        ("faceswap", "flux-klein-9b.safetensors", "must-drop", "", "er_sde", 0.45),
    ],
)
def test_patch_shared_flux_nodes_preserves_prompt_sampler_and_denoise_policy(
    mode: str,
    model: str,
    negative: str | None,
    expected_negative: str,
    expected_sampler: str,
    expected_denoise: float,
) -> None:
    graph = shared_graph()
    request = workflow_request(mode, negativePrompt=negative)

    comfyui_workflows.patch_shared_flux_nodes(
        graph,
        request,
        model,
        "qwen.safetensors",
        "flux2-vae.safetensors",
        default_negative_prompt="default-neg",
        model_profiles=MODEL_PROFILES,
    )

    assert graph["FK:165"]["inputs"]["unet_name"] == model
    assert graph["FK:166"]["inputs"]["text"] == "portrait"
    assert graph["FK:156"]["inputs"]["text"] == expected_negative
    assert graph["FK:170"]["inputs"] == {"width": 1024, "height": 768}
    assert graph["FK:171"]["inputs"] == {
        "seed": 42,
        "steps": 4,
        "cfg": 1.0,
        "denoise": expected_denoise,
        "sampler_name": expected_sampler,
        "scheduler": "simple",
    }


def test_optional_lora_patches_existing_loader_or_inserts_model_only_loader() -> None:
    lora = SimpleNamespace(id="face-9b.safetensors", strength=0.75)
    existing = {"loader": {"inputs": {"lora_name": "none", "strength_model": 0, "strength_clip": 0}}}

    comfyui_workflows.patch_optional_lora(existing, lora)

    assert existing["loader"]["inputs"] == {
        "lora_name": "face-9b.safetensors",
        "strength_model": 0.75,
        "strength_clip": 0.75,
    }

    inserted = {"FK:165": {"inputs": {}}, "FK:169": {"inputs": {"model": ["FK:165", 0]}}}
    comfyui_workflows.patch_optional_lora(inserted, lora)
    assert inserted["FK:admin_lora"]["inputs"] == {
        "model": ["FK:165", 0],
        "lora_name": "face-9b.safetensors",
        "strength_model": 0.75,
    }
    assert inserted["FK:169"]["inputs"]["model"] == ["FK:admin_lora", 0]


def test_9b_face_selection_prefers_quality_bfs_lora() -> None:
    selected, strength = comfyui_workflows.select_faceswap_lora(
        [
            "bfs_head_v1_flux-klein_9b_step3500_rank128.safetensors",
            "face_swap_flux_klein_9b_r32_800.safetensors",
        ],
        "",
        0.75,
        "flux-2-klein-9b-fp8.safetensors",
        enabled=lambda _name: True,
    )

    assert selected == "bfs_head_v1_flux-klein_9b_step3500_rank128.safetensors"
    assert strength == 0.75


def test_9b_face_assembly_bounds_three_reference_latents_only() -> None:
    roles = ["base", "face", "background"]
    assert comfyui_workflows.edit_reference_megapixel_limit(
        profile_id="flux_klein_9b", roles=roles, role="base", face_limit=0.35
    ) == 0.25
    assert comfyui_workflows.edit_reference_megapixel_limit(
        profile_id="flux_klein_9b", roles=roles, role="face", face_limit=0.35
    ) == 0.25
    assert comfyui_workflows.edit_reference_megapixel_limit(
        profile_id="flux_klein_4b", roles=roles, role="base", face_limit=0.35
    ) is None
    assert comfyui_workflows.edit_reference_megapixel_limit(
        profile_id="flux_klein_9b", roles=["base", "face"], role="face", face_limit=0.35
    ) == 0.35


def test_edit_reference_chain_builds_four_slots_and_rewires_sampler() -> None:
    graph = {"FK:171": {"inputs": {}}}

    comfyui_workflows.patch_edit_reference_chain(
        graph,
        ["base.png", "face.png", "style.png", "object.png"],
        [0.116736, 0.335872, 0.5, 0.25],
    )

    assert graph["FK:91"]["inputs"]["image"] == "base.png"
    assert graph["FK:88"]["inputs"]["image"] == "face.png"
    assert graph["FKE:301"]["inputs"]["image"] == "style.png"
    assert graph["FKE:401"]["inputs"]["image"] == "object.png"
    assert graph["FK:133"]["inputs"]["conditioning"] == ["FK:166", 0]
    assert graph["FK:233"]["inputs"]["conditioning"] == ["FK:133", 0]
    assert graph["FKE:407"]["inputs"]["conditioning"] == ["FKE:307", 0]
    assert graph["FK:171"]["inputs"]["positive"] == ["FKE:407", 0]
    assert graph["FK:171"]["inputs"]["negative"] == ["FKE:409", 0]
    assert graph["FK:171"]["inputs"]["denoise"] == 1
    assert graph["FK:163"]["inputs"]["megapixels"] == 0.116736
    assert graph["FK:163b"]["inputs"]["megapixels"] == 0.335872


def test_edit_reference_sizes_follow_present_files_when_an_upload_slot_is_empty() -> None:
    graph = {"FK:171": {"inputs": {}}}

    comfyui_workflows.patch_edit_reference_chain(
        graph,
        [None, "face.png", "style.png"],
        [0.335872, 0.25],
    )

    assert graph["FK:91"]["inputs"]["image"] == "face.png"
    assert graph["FK:163"]["inputs"]["megapixels"] == 0.335872
    assert graph["FK:88"]["inputs"]["image"] == "style.png"
    assert graph["FK:163b"]["inputs"]["megapixels"] == 0.25


def test_edit_reference_chain_removes_unused_slots_and_requires_base() -> None:
    graph = {"FK:171": {"inputs": {}}, "FK:88": {}, "FK:233": {}, "FK:231": {}}
    comfyui_workflows.patch_edit_reference_chain(graph, ["base.png", None, None])
    assert "FK:88" not in graph and "FK:233" not in graph and "FK:231" not in graph
    with pytest.raises(RuntimeError, match="хотя бы одно изображение"):
        comfyui_workflows.patch_edit_reference_chain({}, [])


def test_mode_builder_patches_image_to_image_and_remove_background() -> None:
    image_graph = {**shared_graph(), "FKI2I:img": {"inputs": {}}}
    comfyui_workflows.patch_mode_nodes(
        image_graph,
        workflow_request("image_to_image", strength=0.33),
        {"input1": "source.png"},
        "flux-klein-9b.safetensors",
        "qwen",
        "vae",
        default_negative_prompt="neg",
        model_profiles=MODEL_PROFILES,
    )
    assert image_graph["FKI2I:img"]["inputs"]["image"] == "source.png"
    assert image_graph["FK:171"]["inputs"]["denoise"] == 0.33

    remove_graph = {
        "rmbg:load": {"inputs": {}}, "rmbg:img": {"inputs": {}}, "rmbg:save": {"inputs": {}},
    }
    comfyui_workflows.patch_mode_nodes(
        remove_graph,
        workflow_request("remove_background"),
        {"input1": "source.png"},
        "flux-klein-9b.safetensors",
        "qwen",
        "vae",
        default_negative_prompt="neg",
        model_profiles=MODEL_PROFILES,
    )
    assert remove_graph["rmbg:load"]["inputs"]["bg_removal_name"] == "birefnet.safetensors"
    assert remove_graph["rmbg:img"]["inputs"]["image"] == "source.png"


def test_lightweight_9b_faceswap_reorders_face_before_body_and_sets_prompt() -> None:
    graph = {
        **shared_graph(),
        **{
            node_id: {"inputs": {}}
            for node_id in (
                "FK:169", "FK:91", "FK:88", "FK:163", "FK:163b",
                "FK:132", "FK:133", "FK:131", "FK:232", "FK:233", "FK:231",
            )
        },
    }
    request = workflow_request(
        "faceswap",
        loras=[
            SimpleNamespace(
                id="face_swap_flux_klein_9b_r32_800.safetensors",
                strength=1.0,
            )
        ],
    )

    comfyui_workflows.patch_mode_nodes(
        graph,
        request,
        {"input1": "body.png", "input2": "face.png"},
        "flux-klein-9b.safetensors",
        "qwen",
        "vae",
        default_negative_prompt="neg",
        model_profiles=MODEL_PROFILES,
    )

    assert graph["FK:91"]["inputs"]["image"] == "face.png"
    assert graph["FK:88"]["inputs"]["image"] == "body.png"
    assert graph["FK:166"]["inputs"]["text"].startswith("face_swap:")
    assert graph["FK:admin_lora"]["inputs"]["lora_name"] == (
        "face_swap_flux_klein_9b_r32_800.safetensors"
    )


@pytest.mark.parametrize(("mode", "prefix"), [("inpaint", "FKI"), ("outpaint", "FKO")])
def test_mode_builder_patches_inpaint_and_outpaint_contracts(mode: str, prefix: str) -> None:
    graph = {
        f"{prefix}:194": {"inputs": {}}, f"{prefix}:195": {"inputs": {}},
        f"{prefix}:196": {"inputs": {}}, f"{prefix}:6": {"inputs": {}},
        f"{prefix}:198": {"inputs": {}}, f"{prefix}:209": {"inputs": {}},
        f"{prefix}:163": {"inputs": {}}, f"{prefix}:203": {"inputs": {}},
        ("FKI:199" if mode == "inpaint" else "FKO:maskload"): {"inputs": {}},
    }
    comfyui_workflows.patch_mode_nodes(
        graph,
        workflow_request(mode, strength=0.25),
        {"input1": "canvas.png", "mask": "mask.png"},
        "model", "clip", "vae",
        default_negative_prompt="neg",
        model_profiles=MODEL_PROFILES,
    )
    assert graph[f"{prefix}:198"]["inputs"]["image"] == "canvas.png"
    assert graph[f"{prefix}:209"]["inputs"]["output_target_width"] == 1024
    assert graph[f"{prefix}:163"]["inputs"]["denoise"] == (0.25 if mode == "inpaint" else 1)


def pose_graph() -> dict:
    return {
        node_id: {"inputs": {}}
        for node_id in ("FKP:unet", "FKP:clip", "FKP:vae", "FKP:lora", "FKP:refimg", "FKP:poseimg", "FKP:noise")
    }


def test_pose_builder_uses_installed_refcontrol_lora_and_exact_inputs() -> None:
    graph = pose_graph()
    result = comfyui_workflows.build_pose_workflow(
        graph,
        {"loras": ["other.safetensors", "refcontrol_v2_poses.safetensors"]},
        {"settings": {"pose": {"lora": "fallback.safetensors"}}},
        "reference.png",
        "pose.png",
        model="model.safetensors",
        text_encoder="clip.safetensors",
        vae="vae.safetensors",
        seed=73,
    )
    assert result is graph
    assert graph["FKP:lora"]["inputs"]["lora_name"] == "refcontrol_v2_poses.safetensors"
    assert graph["FKP:refimg"]["inputs"]["image"] == "reference.png"
    assert graph["FKP:poseimg"]["inputs"]["image"] == "pose.png"
    assert graph["FKP:noise"]["inputs"]["noise_seed"] == 73


def outpaint_graph() -> dict:
    return {
        "FKO:216": {"inputs": {}}, "FKO:194": {"inputs": {}}, "FKO:195": {"inputs": {}},
        "FKO:196": {"inputs": {}}, "FKO:6": {"inputs": {}}, "FKO:198": {"inputs": {}},
        "FKO:maskload": {"inputs": {}}, "FKO:209": {"inputs": {}},
        "FKO:163": {"inputs": {}}, "FKO:203": {"inputs": {}},
    }


def outpaint_models() -> dict[str, list[str]]:
    return {
        "diffusion_models": ["flux-2-klein-base-4b.safetensors", "flux-2-klein-4b-fp8.safetensors"],
        "text_encoders": ["qwen_3_4b.safetensors"],
        "vaes": ["flux2-vae.safetensors"],
        "loras": ["flux2_klein_4b_outpaint_comfy.safetensors"],
    }


def build_outpaint(
    graph: dict,
    models: dict[str, list[str]],
    *,
    model: str = "flux-2-klein-4b-fp8.safetensors",
):
    is_4b = "4b" in model
    return comfyui_workflows.build_outpaint_workflow(
        graph,
        models,
        workflow_request("outpaint"),
        {"input1": "canvas.png", "mask": "mask.png"},
        model=model,
        text_encoder="qwen_3_4b.safetensors" if is_4b else "qwen_3_8b_fp8mixed.safetensors",
        vae="flux2-vae.safetensors",
        lora_enabled=lambda _name: True,
        default_negative_prompt="neg",
        model_profiles=MODEL_PROFILES,
    )


def test_outpaint_builder_rejects_missing_or_disabled_dependencies() -> None:
    missing = outpaint_models()
    missing["loras"] = []
    with pytest.raises(RuntimeError, match="Outpaint LoRA is missing"):
        build_outpaint(outpaint_graph(), missing)
    with pytest.raises(RuntimeError, match="disabled by the administrator"):
        comfyui_workflows.build_outpaint_workflow(
            outpaint_graph(), outpaint_models(), workflow_request("outpaint"), {"input1": "canvas.png"},
            model="flux-2-klein-4b-fp8.safetensors",
            text_encoder="qwen_3_4b.safetensors",
            vae="flux2-vae.safetensors",
            lora_enabled=lambda _name: False, default_negative_prompt="neg", model_profiles=MODEL_PROFILES,
        )


def test_outpaint_builder_removes_kv_cache_and_wires_lora_and_mask() -> None:
    graph = outpaint_graph()
    result = build_outpaint(graph, outpaint_models())
    assert result is graph and "FKO:216" not in graph
    assert graph["FKO:194"]["inputs"]["unet_name"] == "flux-2-klein-4b-fp8.safetensors"
    assert graph["FKO:outpaint_lora"]["inputs"]["lora_name"] == "flux2_klein_4b_outpaint_comfy.safetensors"
    assert graph["FKO:163"]["inputs"]["model"] == ["FKO:outpaint_lora", 0]
    assert graph["FKO:maskload"]["inputs"]["image"] == "mask.png"


def test_outpaint_builder_keeps_kv_cache_for_selected_9b_profile() -> None:
    graph = outpaint_graph()
    graph["FKO:216"]["inputs"]["model"] = ["old", 0]
    models = outpaint_models()
    models["diffusion_models"].extend(
        [
            "flux-2-klein-9b-fp8.safetensors",
            "flux-2-klein-9b-kv-fp8.safetensors",
        ]
    )
    models["text_encoders"].append("qwen_3_8b_fp8mixed.safetensors")

    result = build_outpaint(graph, models, model="flux-2-klein-9b-fp8.safetensors")

    assert result is graph and "FKO:216" in graph
    assert graph["FKO:194"]["inputs"]["unet_name"] == "flux-2-klein-9b-kv-fp8.safetensors"
    assert graph["FKO:216"]["inputs"]["model"] == ["FKO:194", 0]
    assert graph["FKO:163"]["inputs"]["model"] == ["FKO:216", 0]
    assert "FKO:outpaint_lora" not in graph


def test_outpaint_builder_rejects_selected_9b_without_kv_checkpoint() -> None:
    with pytest.raises(RuntimeError, match="Klein 9B KV FP8 checkpoint is missing"):
        build_outpaint(
            outpaint_graph(),
            outpaint_models(),
            model="flux-2-klein-9b-fp8.safetensors",
        )
