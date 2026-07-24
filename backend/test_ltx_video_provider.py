from __future__ import annotations

import json
import asyncio

import httpx
import pytest

from app.services.ltx_video import (
    ComfyLtxClient,
    build_ltx_prompt,
    estimate_local_ltx_billing,
    local_ltx_catalog,
    resolve_local_ltx_profile,
)


def test_local_catalog_is_explicitly_enabled_and_has_bounded_profiles():
    assert local_ltx_catalog(enabled=False) == []
    catalog = local_ltx_catalog(enabled=True)
    assert [model["id"] for model in catalog] == [
        "local/ltx-2.3-fast-q3",
        "local/ltx-2.3-standard-q4",
    ]
    assert all(model["modes"] == ["text_to_video"] for model in catalog)
    assert all(model["supportedDurations"] == [2, 4] for model in catalog)
    assert all(model["generateAudio"] is False for model in catalog)


def test_local_billing_uses_fixed_daily_token_quote():
    profile = resolve_local_ltx_profile("local/ltx-2.3-fast-q3")
    assert profile is not None
    assert estimate_local_ltx_billing(profile, duration=2)["chargedTokens"] == 1
    assert estimate_local_ltx_billing(profile, duration=4)["chargedTokens"] == 2
    with pytest.raises(ValueError):
        estimate_local_ltx_billing(profile, duration=6)


def test_workflow_is_server_owned_and_only_patches_allowed_inputs(tmp_path):
    workflow = {
        "0": {
            "class_type": "UnetLoaderGGUF",
            "inputs": {"unet_name": "unsafe.gguf"},
        },
        "1": {"class_type": "CLIPTextEncode", "inputs": {"text": "positive text is longer"}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": "bad"}},
        "3": {"class_type": "INTConstant", "inputs": {"value": 49}},
        "4": {
            "class_type": "EmptyLTXVLatentVideo",
            "inputs": {"width": 1, "height": 1, "length": ["3", 0], "batch_size": 1},
        },
        "5": {"class_type": "LTXVScheduler", "inputs": {"steps": 99}},
        "6": {"class_type": "RandomNoise", "inputs": {"noise_seed": 1}},
        "7": {
            "class_type": "VHS_VideoCombine",
            "inputs": {"filename_prefix": "unsafe", "format": "gif", "frame_rate": 1},
        },
    }
    path = tmp_path / "ltx-api.json"
    path.write_text(json.dumps(workflow), encoding="utf-8")
    profile = resolve_local_ltx_profile("local/ltx-2.3-fast-q3")
    assert profile is not None

    prompt = build_ltx_prompt(
        path,
        profile=profile,
        text="новая сцена",
        duration=2,
        filename_prefix="izo/ltx/job",
    )

    assert prompt["0"]["inputs"]["unet_name"] == "ltx-2.3-22b-distilled-1.1-Q3_K_M.gguf"
    assert prompt["1"]["inputs"]["text"] == "новая сцена"
    assert prompt["2"]["inputs"]["text"] == "bad"
    assert prompt["3"]["inputs"]["value"] == 49
    assert prompt["4"]["inputs"]["width"] == 832
    assert prompt["4"]["inputs"]["height"] == 480
    assert prompt["5"]["inputs"]["steps"] == 8
    assert prompt["7"]["inputs"]["filename_prefix"] == "izo/ltx/job"
    assert prompt["7"]["inputs"]["format"] == "video/h264-mp4"
    assert prompt["7"]["inputs"]["frame_rate"] == 24

    standard = resolve_local_ltx_profile("local/ltx-2.3-standard-q4")
    assert standard is not None
    q4_prompt = build_ltx_prompt(
        path,
        profile=standard,
        text="новая сцена",
        duration=4,
        filename_prefix="izo/ltx/job-q4",
    )
    assert q4_prompt["0"]["inputs"]["unet_name"] == "ltx-2.3-22b-distilled-1.1-Q4_K_M.gguf"
    assert q4_prompt["3"]["inputs"]["value"] == 97
    assert q4_prompt["5"]["inputs"]["steps"] == 12


def test_comfy_client_requires_a_gpu_for_readiness(monkeypatch):
    original_client = httpx.AsyncClient

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/system_stats"
        return httpx.Response(200, json={"devices": [{"name": "cpu", "type": "cpu"}]})

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **_kwargs: original_client(transport=httpx.MockTransport(handler)),
    )
    status = asyncio.run(ComfyLtxClient("http://comfy.test").readiness())
    assert status["ready"] is False


def test_comfy_client_releases_models_and_vram(monkeypatch):
    original_client = httpx.AsyncClient

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/free"
        assert json.loads(request.content) == {
            "unload_models": True,
            "free_memory": True,
        }
        return httpx.Response(200, json={})

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **_kwargs: original_client(transport=httpx.MockTransport(handler)),
    )
    asyncio.run(ComfyLtxClient("http://comfy.test").free_memory())
