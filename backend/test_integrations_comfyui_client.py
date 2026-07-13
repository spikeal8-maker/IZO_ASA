from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app.integrations.comfyui_client import (
    ComfyUIHistoryClient,
    comfyui_flux_klein_available,
    fetch_comfyui_image_bytes,
    fetch_comfyui_models,
    fetch_comfyui_node_names,
    fetch_comfyui_workflow,
    fetch_flux_bgremoval_models,
    fetch_flux_klein_config,
    fetch_flux_lora_triggers,
    free_comfyui_memory,
    interrupt_comfyui,
    submit_comfyui_workflow,
    upload_comfyui_image,
)


def request_timeout(request: httpx.Request) -> float:
    return float(request.extensions["timeout"]["read"])


def test_availability_probe_checks_required_node_and_uses_four_second_timeout() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"FluxKleinOneNode": {}, "SaveImage": {}})

    available = asyncio.run(
        comfyui_flux_klein_available(
            base_url="http://127.0.0.1:8188/",
            transport=httpx.MockTransport(handler),
        )
    )

    assert available is True
    assert requests[0].url == "http://127.0.0.1:8188/object_info"
    assert request_timeout(requests[0]) == 4


def test_availability_and_node_discovery_keep_non_raising_degraded_contract() -> None:
    def missing_node(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"SaveImage": {}})

    def unavailable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    assert asyncio.run(
        comfyui_flux_klein_available(
            base_url="http://comfy",
            transport=httpx.MockTransport(missing_node),
        )
    ) is False
    assert asyncio.run(
        fetch_comfyui_node_names(
            base_url="http://comfy",
            transport=httpx.MockTransport(unavailable),
        )
    ) == set()


def test_node_discovery_returns_names_and_uses_eight_second_timeout() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"FluxKleinOneNode": {}, "DWPreprocessor": {}})

    names = asyncio.run(
        fetch_comfyui_node_names(
            base_url="http://comfy",
            transport=httpx.MockTransport(handler),
        )
    )

    assert names == {"FluxKleinOneNode", "DWPreprocessor"}
    assert request_timeout(seen[0]) == 8


def test_catalog_config_and_auxiliary_endpoints_preserve_payload_contracts() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/flux_klein/models":
            return httpx.Response(200, json={"diffusion_models": ["m"], "loras": ["l"], "ignored": True})
        if request.url.path == "/flux_klein/config":
            return httpx.Response(200, json={"autofill_prompts": {"p": "x"}, "unknown": 1})
        if request.url.path == "/flux_klein/bgremoval_models":
            return httpx.Response(200, json={"models": ["bria"]})
        return httpx.Response(200, json={"triggers": ["portrait"]})

    transport = httpx.MockTransport(handler)

    async def scenario() -> tuple[dict, dict, dict, dict]:
        models = await fetch_comfyui_models(base_url="http://comfy", transport=transport)
        config = await fetch_flux_klein_config(base_url="http://comfy", transport=transport)
        bg = await fetch_flux_bgremoval_models(base_url="http://comfy", transport=transport)
        triggers = await fetch_flux_lora_triggers(base_url="http://comfy", name="face.safetensors", transport=transport)
        return models, config, bg, triggers

    models, config, bg, triggers = asyncio.run(scenario())

    assert models == {"diffusion_models": ["m"], "text_encoders": [], "vaes": [], "loras": ["l"]}
    assert config == {"autofill_prompts": {"p": "x"}, "lora_triggers_custom": {}, "t2i_templates": [], "discover_prompts": {}}
    assert bg == {"models": ["bria"]}
    assert triggers == {"triggers": ["portrait"]}
    assert seen[3].url.params["name"] == "face.safetensors"
    assert {request_timeout(request) for request in seen} == {10}


def test_upload_uses_legacy_multipart_contract_and_sixty_second_timeout(tmp_path) -> None:
    image_path = tmp_path / "input.png"
    image_path.write_bytes(b"png-content")
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"name": "server-input.png"})

    name = asyncio.run(
        upload_comfyui_image(
            base_url="http://comfy",
            path=image_path,
            transport=httpx.MockTransport(handler),
        )
    )

    body = seen[0].content
    assert name == "server-input.png"
    assert seen[0].method == "POST" and seen[0].url.path == "/upload/image"
    assert b'filename="input.png"' in body and b"png-content" in body
    assert b'overwrite' in body and b'true' in body and b'type' in body and b'input' in body
    assert request_timeout(seen[0]) == 60


def test_workflow_submit_and_history_keep_endpoints_payloads_and_connection_pool() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/flux_klein/workflow_edit":
            return httpx.Response(200, json={"node": {"inputs": {}}})
        if request.url.path == "/prompt":
            return httpx.Response(200, json={"prompt_id": "prompt-1"})
        return httpx.Response(200, json={"prompt-1": {"outputs": {}}})

    transport = httpx.MockTransport(handler)

    async def scenario() -> tuple[dict, dict, dict, dict]:
        workflow = await fetch_comfyui_workflow(base_url="http://comfy", endpoint="workflow_edit", transport=transport)
        submitted = await submit_comfyui_workflow(base_url="http://comfy", workflow=workflow, job_id="job-1", transport=transport)
        history_client = ComfyUIHistoryClient(base_url="http://comfy", transport=transport)
        with pytest.raises(RuntimeError, match="not open"):
            await history_client.fetch("prompt-1")
        async with history_client:
            first = await history_client.fetch("prompt-1")
            second = await history_client.fetch("prompt-1")
        return workflow, submitted, first, second

    workflow, submitted, first, second = asyncio.run(scenario())

    prompt_body = json.loads(seen[1].content)
    assert workflow == {"node": {"inputs": {}}}
    assert submitted == {"prompt_id": "prompt-1"}
    assert first == second == {"prompt-1": {"outputs": {}}}
    assert prompt_body == {
        "prompt": workflow,
        "client_id": "onenode-backend-job-1",
        "extra_data": {"enable_previews": True},
    }
    assert [request_timeout(request) for request in seen] == [20, 30, 20, 20]


def test_interrupt_preserves_non_raising_http_status_contract() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(503, json={"error": "busy"})

    asyncio.run(interrupt_comfyui(base_url="http://comfy", transport=httpx.MockTransport(handler)))

    assert seen[0].url.path == "/interrupt"
    assert request_timeout(seen[0]) == 5


def test_image_download_and_free_memory_preserve_binary_and_json_contracts() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/view":
            return httpx.Response(200, content=b"image-bytes")
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)

    async def scenario() -> tuple[bytes, bool]:
        content = await fetch_comfyui_image_bytes(
            base_url="http://comfy",
            image={"filename": "FK.png", "subfolder": "out"},
            transport=transport,
        )
        freed = await free_comfyui_memory(base_url="http://comfy", transport=transport)
        return content, freed

    content, freed = asyncio.run(scenario())

    assert content == b"image-bytes" and freed is True
    assert dict(seen[0].url.params) == {"filename": "FK.png", "subfolder": "out", "type": "output"}
    assert json.loads(seen[1].content) == {"unload_models": True, "free_memory": True}
    assert [request_timeout(request) for request in seen] == [120, 10]


def test_non_probe_http_failures_still_propagate() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "broken"})

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(fetch_comfyui_models(base_url="http://comfy", transport=httpx.MockTransport(handler)))
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(free_comfyui_memory(base_url="http://comfy", transport=httpx.MockTransport(handler)))
