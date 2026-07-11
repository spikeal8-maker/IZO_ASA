from __future__ import annotations

import asyncio
import base64
from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image
import pytest

import main


@pytest.fixture(autouse=True)
def isolated_comfyui_test_state(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "comfyui_adapter_test.sqlite3")
    monkeypatch.setattr(main, "MEDIA", tmp_path / "media")
    main.MEDIA.mkdir(parents=True, exist_ok=True)
    main.init_db()
    main.jobs.clear()
    main.images.clear()
    main.queue = asyncio.Queue()
    main.worker_started = False


def test_choose_model_prefers_installed_flux_klein_9b_fp8() -> None:
    selected = main.choose_model(
        {
            "diffusion_models": [
                "flux-2-klein-4b-fp8.safetensors",
                "flux-2-klein-9b-fp8.safetensors",
            ],
            "text_encoders": ["clip_l.safetensors", "qwen_3_8b_fp8mixed.safetensors"],
            "vaes": ["wan_2.1_vae.safetensors", "flux2-vae.safetensors"],
        },
        "",
    )

    assert selected == (
        "flux-2-klein-9b-fp8.safetensors",
        "qwen_3_8b_fp8mixed.safetensors",
        "flux2-vae.safetensors",
    )


def test_effective_face_profile_follows_global_klein_profile() -> None:
    main._save_setting("models", {"editModelProfile": "flux_klein_4b", "poseModelProfile": "flux_klein_4b"})
    assert main.effective_face_profile("flux_klein_4b") == "flux_klein_4b"
    assert main.effective_face_profile("local_flux_klein") == "flux_klein_4b"


def test_choose_faceswap_lora_prefers_matching_9b_face_lora() -> None:
    selected = main.choose_faceswap_lora(
        [
            "bfs_head_v1_flux-klein_4b_step3500_rank128.safetensors",
            "bfs_head_v1_flux-klein_9b_step3500_rank128.safetensors",
        ],
        main.Lora(id="bfs_head_v1_flux-klein_4b_step3500_rank128.safetensors", strength=0.72),
        "flux-2-klein-9b-fp8.safetensors",
    )

    assert selected.id == "bfs_head_v1_flux-klein_9b_step3500_rank128.safetensors"
    assert selected.strength == 0.72


def test_choose_faceswap_lora_rejects_admin_disabled_lora() -> None:
    file_name = "bfs_head_v1_flux-klein_4b.safetensors"
    main._save_setting("server_model_loras", {"enabled": {file_name: False}})
    with pytest.raises(RuntimeError, match="выключена"):
        main.choose_faceswap_lora([file_name], None, "flux-2-klein-4b-fp8.safetensors")


def test_server_model_profile_is_persisted_and_sampler_is_applied(monkeypatch) -> None:
    main._save_setting("server_model_profiles", {"profiles": {"flux_klein_4b": {"width": 1536, "height": 1024, "steps": 6, "sampler": "euler", "seedMode": "fixed", "seed": 777}}})
    req = main.GenerateRequest(mode="text_to_image", width=1024, height=1024, steps=28, seed=42)
    settings = main.get_server_model_profiles()["flux_klein_4b"]
    assert settings["sampler"] == "euler"
    assert (req.width, req.height, req.steps, req.seed) == (1024, 1024, 28, 42)

    workflow = {"FK:171": {"inputs": {}}, "FK:170": {"inputs": {}}}
    main.patch_shared_flux_nodes(workflow, req, "flux-2-klein-4b-fp8.safetensors", "qwen", "vae")
    assert workflow["FK:171"]["inputs"]["sampler_name"] == "euler"


def test_missing_admin_setting_returns_empty_mapping() -> None:
    assert main._saved_setting("setting-that-does-not-exist") == {}


def test_editor_workflow_failure_is_not_replaced_with_mock(monkeypatch) -> None:
    async def available() -> bool:
        return True

    async def models() -> dict[str, list[str]]:
        return {"diffusion_models": ["flux-2-klein-4b-fp8.safetensors"], "text_encoders": ["qwen_3_4b.safetensors"], "vaes": ["flux2-vae.safetensors"], "loras": []}

    async def workflow(_mode: str) -> dict:
        return {}

    async def upload(path) -> str:
        return path.name

    async def fail_submit(_workflow: dict, _job: dict):
        raise RuntimeError("invalid editor graph")

    image = Image.new("RGB", (512, 512), "white")
    buffer = BytesIO(); image.save(buffer, "PNG")
    data_url = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
    monkeypatch.setattr(main, "comfyui_available", available)
    monkeypatch.setattr(main, "get_comfyui_models", models)
    monkeypatch.setattr(main, "fetch_workflow", workflow)
    monkeypatch.setattr(main, "upload_to_comfyui", upload)
    monkeypatch.setattr(main, "submit_workflow", fail_submit)
    monkeypatch.setattr(main, "COMFYUI_MOCK_FALLBACK", False)
    req = main.GenerateRequest(mode="remove_background", inputImage1=data_url, modelProfile="flux_klein_4b")
    with pytest.raises(RuntimeError, match="invalid editor graph"):
        asyncio.run(main.send_to_comfyui(req, {"id": "editor-fail", "mode": "remove_background"}))


def test_models_endpoint_reports_selected_models(monkeypatch) -> None:
    async def fake_models() -> dict[str, list[str]]:
        return {
            "diffusion_models": ["flux-2-klein-9b-fp8.safetensors"],
            "text_encoders": ["qwen_3_8b_fp8mixed.safetensors"],
            "vaes": ["flux2-vae.safetensors"],
            "loras": ["bfs_head_v1_flux-klein_9b_step3500_rank128.safetensors"],
        }

    monkeypatch.setattr(main, "get_comfyui_models", fake_models)
    with TestClient(main.app) as client:
        payload = client.get("/api/models").json()

    assert payload["ok"] is True
    assert payload["selected"]["model"] == "Flux2"
    assert payload["selected"]["textEncoder"] == "Flux2 CLIP"
    assert payload["selected"]["vae"] == "Flux2 VAE"
    assert payload["diffusion_models"] == ["Flux2"]
    assert payload["text_encoders"] == ["Flux2 CLIP"]
    assert payload["vaes"] == ["Flux2 VAE"]
    assert payload["loras"] == ["bfs_head_v1_flux-klein_9b_step3500_rank128.safetensors"]


def test_send_to_comfyui_fails_when_comfyui_is_unavailable_without_fallback(monkeypatch) -> None:
    async def unavailable() -> bool:
        return False

    monkeypatch.setattr(main, "comfyui_available", unavailable)
    monkeypatch.setattr(main, "COMFYUI_REQUIRED", False)
    monkeypatch.setattr(main, "COMFYUI_MOCK_FALLBACK", False)

    request = main.GenerateRequest(mode="text_to_image", prompt="no server")
    try:
        asyncio.run(main.send_to_comfyui(request, {"id": "job_unavailable"}))
    except RuntimeError as exc:
        assert "ComfyUI недоступен" in str(exc)
    else:
        raise AssertionError("send_to_comfyui should fail when fallback is disabled")


def test_extract_images_from_history_handles_standard_comfyui_outputs() -> None:
    history = {
        "outputs": {
            "FK:86": {
                "images": [
                    {"filename": "FK_00001_.png", "subfolder": "one-node-flux-2-klein", "type": "output"},
                    {"filename": "FK_00002_.png", "subfolder": "one-node-flux-2-klein", "type": "output"},
                ]
            }
        }
    }

    images = main.extract_images_from_history(history)

    assert images == [
        {"filename": "FK_00001_.png", "subfolder": "one-node-flux-2-klein", "type": "output"},
        {"filename": "FK_00002_.png", "subfolder": "one-node-flux-2-klein", "type": "output"},
    ]


def test_download_comfyui_image_saves_optimized_webp_and_thumbnail(monkeypatch) -> None:
    image = Image.new("RGB", (3000, 1800), "#2f6fed")
    buffer = BytesIO()
    image.save(buffer, "PNG")
    png_bytes = buffer.getvalue()

    class FakeResponse:
        headers = {"content-type": "image/png"}
        content = png_bytes

        def raise_for_status(self) -> None:
            return None

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *args) -> None:
            return None

        async def get(self, url: str, params: dict) -> FakeResponse:
            assert url.endswith("/view")
            assert params["filename"] == "FK_00001_.png"
            return FakeResponse()

    monkeypatch.setattr(main.httpx, "AsyncClient", FakeAsyncClient)
    image_path, thumb_path = asyncio.run(
        main.download_comfyui_image(
            {"filename": "FK_00001_.png", "subfolder": "one-node-flux-2-klein", "type": "output"},
            "job_download_test",
        )
    )

    assert image_path.exists()
    assert thumb_path.exists()
    assert image_path.name == "job_download_test_comfyui.webp"
    assert thumb_path.name == "job_download_test_comfyui_thumb.webp"
    with Image.open(image_path) as saved:
        assert saved.format == "WEBP"
        assert max(saved.size) <= main.GALLERY_IMAGE_MAX_SIDE


def test_save_canvas_json_creates_raster_input() -> None:
    path = main.save_canvas_json("[]", "job_canvas_test")

    assert path is not None
    assert path.exists()
    with Image.open(path) as image:
        assert image.size == (1024, 1024)


def test_prepare_comfyui_input_image_downscales_large_landscape(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "MEDIA", tmp_path)
    source = tmp_path / "large_landscape.png"
    Image.new("RGB", (4000, 2000), "#2f6fed").save(source, "PNG")

    req = main.GenerateRequest(mode="image_to_image", width=1536, height=1024)
    prepared = main.prepare_comfyui_input_image(source, "job_large_landscape", req)

    assert prepared is not None
    with Image.open(prepared) as image:
        assert image.size == (1536, 768)
        assert image.size[0] % 16 == 0
        assert image.size[1] % 16 == 0
        assert max(image.size) <= main.COMFYUI_INPUT_MAX_SIDE


def test_prepare_comfyui_input_image_downscales_large_portrait(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "MEDIA", tmp_path)
    source = tmp_path / "large_portrait.png"
    Image.new("RGB", (2000, 4000), "#117865").save(source, "PNG")

    req = main.GenerateRequest(mode="edit", width=1024, height=1536)
    prepared = main.prepare_comfyui_input_image(source, "job_large_portrait", req)

    assert prepared is not None
    with Image.open(prepared) as image:
        assert image.size == (768, 1536)
        assert image.size[0] % 16 == 0
        assert image.size[1] % 16 == 0
        assert max(image.size) <= main.COMFYUI_INPUT_MAX_SIDE


def test_prepare_comfyui_face_input_uses_smaller_safe_limit(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "MEDIA", tmp_path)
    source = tmp_path / "large_face_target.png"
    Image.new("RGB", (3200, 2400), "#663399").save(source, "PNG")

    req = main.GenerateRequest(mode="faceswap", width=1536, height=1152)
    prepared = main.prepare_comfyui_input_image(source, "job_face_target", req, max_side=1024)

    assert prepared is not None
    with Image.open(prepared) as image:
        assert image.size == (1024, 768)
        assert image.size[0] % 16 == 0
        assert image.size[1] % 16 == 0
        assert max(image.size) <= 1024


def test_prepare_comfyui_outpaint_inputs_builds_canvas_and_mask(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "MEDIA", tmp_path)
    source = tmp_path / "source.png"
    Image.new("RGB", (100, 100), "#2f6fed").save(source, "PNG")

    req = main.GenerateRequest(
        mode="outpaint",
        width=1024,
        height=512,
        outpaint={"left": 50, "right": 50, "top": 0, "bottom": 0, "scaleDown": True},
    )
    image_path, mask_path = main.prepare_comfyui_outpaint_inputs(source, "job_outpaint", req)

    assert image_path is not None and mask_path is not None
    with Image.open(image_path) as image, Image.open(mask_path) as mask:
        assert image.size == (1024, 512)
        assert mask.size == (1024, 512)
        assert image.getpixel((512, 256)) == (47, 111, 237)
        assert mask.getpixel((10, 256)) == (255, 255, 255)
        assert mask.getpixel((512, 256)) == (0, 0, 0)


def test_prepare_comfyui_outpaint_inputs_uses_frame_placement(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "MEDIA", tmp_path)
    source = tmp_path / "wide.png"
    Image.new("RGB", (160, 90), "#c80028").save(source, "PNG")

    req = main.GenerateRequest(
        mode="outpaint",
        width=1024,
        height=1024,
        outpaint={
            "left": 0,
            "right": 0,
            "top": 35,
            "bottom": 35,
            "frameW": 1024,
            "frameH": 1024,
            "sourceX": 0,
            "sourceY": 224,
            "sourceW": 1024,
            "sourceH": 576,
        },
    )
    image_path, mask_path = main.prepare_comfyui_outpaint_inputs(source, "job_outpaint_square", req)

    assert image_path is not None and mask_path is not None
    with Image.open(image_path) as image, Image.open(mask_path) as mask:
        assert image.size == (1024, 1024)
        assert mask.size == (1024, 1024)
        assert image.getpixel((512, 512)) == (200, 0, 40)
        assert mask.getpixel((512, 40)) == (255, 255, 255)
        assert mask.getpixel((512, 512)) == (0, 0, 0)
        assert mask.getpixel((512, 980)) == (255, 255, 255)


def test_patch_outpaint_workflow_uses_full_denoise_and_target_size() -> None:
    wf = {
        "FKO:194": {"inputs": {}},
        "FKO:195": {"inputs": {}},
        "FKO:196": {"inputs": {}},
        "FKO:6": {"inputs": {}},
        "FKO:198": {"inputs": {}},
        "FKO:maskload": {"inputs": {}},
        "FKO:209": {"inputs": {}},
        "FKO:163": {"inputs": {"denoise": 0.25}},
        "FKO:203": {"inputs": {}},
    }
    req = main.GenerateRequest(mode="outpaint", prompt="expand", width=1024, height=1024, strength=0.25)

    main.patch_mode_nodes(wf, req, {"input1": "expanded.png", "mask": "mask.png"}, "m", "t", "v")

    assert wf["FKO:198"]["inputs"]["image"] == "expanded.png"
    assert wf["FKO:maskload"]["inputs"]["image"] == "mask.png"
    assert wf["FKO:209"]["inputs"]["output_target_width"] == 1024
    assert wf["FKO:209"]["inputs"]["output_target_height"] == 1024
    assert wf["FKO:163"]["inputs"]["denoise"] == 1


def test_patch_upload_modes_wire_expected_input_nodes() -> None:
    uploads = {"input1": "source.png", "input2": "face.png"}

    i2i = {"FKI2I:img": {"inputs": {}}, "FK:171": {"inputs": {}}}
    main.patch_mode_nodes(i2i, main.GenerateRequest(mode="image_to_image", prompt="i2i", strength=0.33), uploads, "m", "t", "v")
    assert i2i["FKI2I:img"]["inputs"]["image"] == "source.png"
    assert i2i["FK:171"]["inputs"]["denoise"] == 0.33

    faceswap = _edit_workflow_template()
    req = main.GenerateRequest(mode="faceswap", prompt="", seed=7, strength=0.75, loras=[main.Lora(id="face.safetensors", strength=0.75)])
    main.patch_mode_nodes(faceswap, req, uploads, "m", "t", "v")
    assert faceswap["FK:91"]["inputs"]["image"] == "source.png"
    assert faceswap["FK:88"]["inputs"]["image"] == "face.png"
    assert faceswap["FK:171"]["inputs"]["seed"] == 7
    assert faceswap["FK:171"]["inputs"]["denoise"] == 1
    assert faceswap["FK:171"]["inputs"]["scheduler"] == "simple"
    assert faceswap["FK:156"]["inputs"]["text"] == ""
    assert faceswap["FK:171"]["inputs"]["positive"] == ["FK:233", 0]
    assert faceswap["FK:171"]["inputs"]["negative"] == ["FK:231", 0]
    assert faceswap["FK:lora"]["inputs"]["lora_name"] == "face.safetensors"
    assert faceswap["FK:lora"]["inputs"]["strength_model"] == 0.75


def test_faceswap_inserts_lora_loader_when_live_edit_workflow_has_none() -> None:
    workflow = _edit_workflow_template()
    workflow.pop("FK:lora")
    workflow["FK:165"] = {"class_type": "UNETLoader", "inputs": {"unet_name": "model.safetensors"}}
    workflow["FK:169"] = {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["FK:165", 0]}}
    req = main.GenerateRequest(mode="faceswap", loras=[main.Lora(id="face-9b.safetensors", strength=0.8)])
    main.patch_mode_nodes(workflow, req, {"input1": "body.png", "input2": "face.png"}, "model", "clip", "vae")
    assert workflow["FK:admin_lora"]["class_type"] == "LoraLoaderModelOnly"
    assert workflow["FK:admin_lora"]["inputs"]["lora_name"] == "face-9b.safetensors"
    assert workflow["FK:169"]["inputs"]["model"] == ["FK:admin_lora", 0]


def test_depth_refcontrol_uses_base_4b_and_long_schedule(monkeypatch) -> None:
    monkeypatch.setattr(main, "server_lora_enabled", lambda _name: True)
    models = {
        "diffusion_models": ["flux-2-klein-4b-fp8.safetensors", "flux-2-klein-base-4b.safetensors"],
        "text_encoders": ["qwen_3_4b.safetensors"],
        "vaes": ["flux2-vae.safetensors"],
        "loras": ["flux2_klein_4b_refcontrol_depth.safetensors"],
    }
    req = main.GenerateRequest(mode="edit", prompt="a glass house", seed=17)

    graph = main.build_depth_workflow(models, "reference.png", "depth-source.png", req)

    assert graph["FKP:unet"]["inputs"]["unet_name"] == "flux-2-klein-base-4b.safetensors"
    assert graph["FKP:lora"]["inputs"]["lora_name"] == "flux2_klein_4b_refcontrol_depth.safetensors"
    assert graph["FKP:dwpose"]["class_type"] == "DepthAnythingV2Preprocessor"
    assert graph["FKP:poseimg"]["inputs"]["image"] == "depth-source.png"
    assert graph["FKP:refimg"]["inputs"]["image"] == "reference.png"
    assert graph["FKP:prompt"]["inputs"]["text"] == "refcontrol a glass house"
    assert graph["FKP:guider"]["inputs"]["cfg"] == 5
    assert graph["FKP:sched"]["inputs"]["steps"] == 20
    assert graph["FKP:noise"]["inputs"]["noise_seed"] == 17


def test_outpaint_uses_installed_4b_lora_without_missing_kv_model(monkeypatch) -> None:
    monkeypatch.setattr(main, "server_lora_enabled", lambda _name: True)
    models = {
        "diffusion_models": ["flux-2-klein-4b-fp8.safetensors", "flux-2-klein-base-4b.safetensors"],
        "text_encoders": ["qwen_3_4b.safetensors"],
        "vaes": ["flux2-vae.safetensors"],
        "loras": ["flux2_klein_4b_outpaint_comfy.safetensors"],
    }
    graph = {
        "FKO:194": {"class_type": "UNETLoader", "inputs": {}},
        "FKO:216": {"class_type": "FluxKVCache", "inputs": {"model": ["FKO:194", 0]}},
        "FKO:195": {"class_type": "CLIPLoader", "inputs": {}},
        "FKO:196": {"class_type": "VAELoader", "inputs": {}},
        "FKO:6": {"class_type": "CLIPTextEncode", "inputs": {}},
        "FKO:198": {"class_type": "LoadImage", "inputs": {}},
        "FKO:maskload": {"class_type": "LoadImage", "inputs": {}},
        "FKO:163": {"class_type": "KSampler", "inputs": {}},
        "FKO:203": {"class_type": "SaveImage", "inputs": {}},
    }
    req = main.GenerateRequest(mode="outpaint", prompt="extend the forest", seed=9, width=1024, height=1024)

    result = main.build_outpaint_workflow(graph, models, req, {"input1": "canvas.png", "mask": "mask.png"})

    assert "FKO:216" not in result
    assert result["FKO:194"]["inputs"]["unet_name"] == "flux-2-klein-4b-fp8.safetensors"
    assert result["FKO:outpaint_lora"]["inputs"]["lora_name"] == "flux2_klein_4b_outpaint_comfy.safetensors"
    assert result["FKO:163"]["inputs"]["model"] == ["FKO:outpaint_lora", 0]
    assert result["FKO:198"]["inputs"]["image"] == "canvas.png"
    assert result["FKO:maskload"]["inputs"]["image"] == "mask.png"


def _edit_workflow_template() -> dict:
    # Минимальная копия структуры workflow_edit (как отдаёт ComfyUI): база + 1 референс.
    return {
        "FK:166": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}},
        "FK:156": {"class_type": "CLIPTextEncode", "inputs": {"text": "neg"}},
        "FK:153": {"class_type": "VAELoader", "inputs": {}},
        "FK:91": {"class_type": "LoadImage", "inputs": {"image": "placeholder.png"}},
        "FK:88": {"class_type": "LoadImage", "inputs": {"image": "placeholder.png"}},
        "FK:163": {"class_type": "ImageScaleToTotalPixels", "inputs": {"image": ["FK:91", 0]}},
        "FK:163b": {"class_type": "ImageScaleToTotalPixels", "inputs": {"image": ["FK:88", 0]}},
        "FK:132": {"class_type": "VAEEncode", "inputs": {"pixels": ["FK:163", 0], "vae": ["FK:153", 0]}},
        "FK:133": {"class_type": "ReferenceLatent", "inputs": {"conditioning": ["FK:166", 0], "latent": ["FK:132", 0]}},
        "FK:131": {"class_type": "ReferenceLatent", "inputs": {"conditioning": ["FK:156", 0], "latent": ["FK:132", 0]}},
        "FK:232": {"class_type": "VAEEncode", "inputs": {"pixels": ["FK:163b", 0], "vae": ["FK:153", 0]}},
        "FK:233": {"class_type": "ReferenceLatent", "inputs": {"conditioning": ["FK:133", 0], "latent": ["FK:232", 0]}},
        "FK:231": {"class_type": "ReferenceLatent", "inputs": {"conditioning": ["FK:131", 0], "latent": ["FK:232", 0]}},
        "FK:170": {"class_type": "EmptyFlux2LatentImage", "inputs": {}},
        "FK:171": {"class_type": "KSampler", "inputs": {"positive": ["FK:133", 0], "negative": ["FK:131", 0], "latent_image": ["FK:170", 0], "denoise": 0.45}},
        "FK:lora": {"class_type": "LoraLoader", "inputs": {"lora_name": "none", "strength_model": 0, "strength_clip": 0}},
    }


def test_edit_single_image_uses_only_base_and_full_denoise() -> None:
    wf = _edit_workflow_template()
    req = main.GenerateRequest(mode="edit", prompt="cinematic", strength=0.45)
    main.patch_mode_nodes(wf, req, {"input1": "base.png"}, "m", "t", "v")
    assert wf["FK:91"]["inputs"]["image"] == "base.png"
    # denoise обязан стать 1.0 (пустой латент), иначе «мусорное полотно».
    assert wf["FK:171"]["inputs"]["denoise"] == 1
    # Сэмплер читает реф первого изображения; лишние слоты удалены.
    assert wf["FK:171"]["inputs"]["positive"] == ["FK:133", 0]
    assert "FK:88" not in wf and "FK:233" not in wf


def test_edit_two_images_rewires_sampler_to_second_reference() -> None:
    wf = _edit_workflow_template()
    req = main.GenerateRequest(mode="edit", prompt="put clothes")
    main.patch_mode_nodes(wf, req, {"input1": "base.png", "input2": "ref1.png"}, "m", "t", "v")
    assert wf["FK:91"]["inputs"]["image"] == "base.png"
    assert wf["FK:88"]["inputs"]["image"] == "ref1.png"
    # Раньше сэмплер оставался на FK:133 (img1) и игнорировал второе изображение — теперь FK:233.
    assert wf["FK:171"]["inputs"]["positive"] == ["FK:233", 0]
    assert wf["FK:171"]["inputs"]["negative"] == ["FK:231", 0]
    assert wf["FK:171"]["inputs"]["denoise"] == 1


def test_edit_four_images_builds_full_reference_chain() -> None:
    wf = _edit_workflow_template()
    req = main.GenerateRequest(mode="edit", prompt="multi ref")
    uploads = {"input1": "base.png", "input2": "ref1.png", "input3": "ref2.png", "input4": "ref3.png"}
    main.patch_mode_nodes(wf, req, uploads, "m", "t", "v")
    # Слоты 3 и 4 созданы.
    assert wf["FKE:301"]["inputs"]["image"] == "ref2.png"
    assert wf["FKE:401"]["inputs"]["image"] == "ref3.png"
    # Положительная цепочка: FK:166 -> 133 -> 233 -> 307 -> 407.
    assert wf["FK:133"]["inputs"]["conditioning"] == ["FK:166", 0]
    assert wf["FK:233"]["inputs"]["conditioning"] == ["FK:133", 0]
    assert wf["FKE:307"]["inputs"]["conditioning"] == ["FK:233", 0]
    assert wf["FKE:407"]["inputs"]["conditioning"] == ["FKE:307", 0]
    assert wf["FKE:307"]["inputs"]["latent"] == ["FKE:305", 0]
    # Сэмплер читает конец цепочки.
    assert wf["FK:171"]["inputs"]["positive"] == ["FKE:407", 0]
    assert wf["FK:171"]["inputs"]["negative"] == ["FKE:409", 0]
    assert wf["FK:171"]["inputs"]["denoise"] == 1


def test_edit_negative_prompt_is_empty() -> None:
    wf = _edit_workflow_template()
    req = main.GenerateRequest(mode="edit", prompt="x", negativePrompt="should be dropped")
    main.patch_mode_nodes(wf, req, {"input1": "base.png"}, "m", "t", "v")
    assert wf["FK:156"]["inputs"]["text"] == ""


def test_validate_edit_rejects_reference_without_role() -> None:
    from fastapi import HTTPException
    req = main.GenerateRequest(mode="edit", prompt="x", inputImages=[
        main.EditImage(index=1, role="base", image="data:img1"),
        main.EditImage(index=2, role="", image="data:img2"),
    ])
    try:
        main.validate_edit_request(req)
    except HTTPException as exc:
        assert exc.status_code == 422 and "роль" in exc.detail
    else:
        raise AssertionError("reference without role must be rejected")


def test_validate_edit_rejects_missing_base() -> None:
    from fastapi import HTTPException
    req = main.GenerateRequest(mode="edit", prompt="x", inputImages=[
        main.EditImage(index=2, role="face", image="data:img2"),
    ])
    try:
        main.validate_edit_request(req)
    except HTTPException as exc:
        assert exc.status_code == 422
    else:
        raise AssertionError("missing base must be rejected")


def test_validate_edit_accepts_valid_four_images() -> None:
    req = main.GenerateRequest(mode="edit", prompt="x", inputImages=[
        main.EditImage(index=1, role="base", image="data:1"),
        main.EditImage(index=2, role="clothing", image="data:2"),
        main.EditImage(index=3, role="face", image="data:3"),
        main.EditImage(index=4, role="style", image="data:4"),
    ])
    main.validate_edit_request(req)  # must not raise
