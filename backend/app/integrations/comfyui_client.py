"""Import-safe HTTP boundary for the local ComfyUI API."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx


class ComfyUIHistoryClient:
    """Reusable polling client so a generation keeps one HTTP connection pool."""

    def __init__(
        self,
        *,
        base_url: str,
        timeout_seconds: float = 20,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self.transport = transport
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> ComfyUIHistoryClient:
        self._client = httpx.AsyncClient(
            **_client_options(timeout_seconds=self.timeout_seconds, transport=self.transport)
        )
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def fetch(self, prompt_id: str) -> dict[str, Any]:
        if self._client is None:
            raise RuntimeError("ComfyUI history client is not open.")
        response = await self._client.get(_url(self.base_url, f"/history/{prompt_id}"))
        response.raise_for_status()
        return response.json()


def _url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def _client_options(
    *,
    timeout_seconds: float,
    transport: httpx.AsyncBaseTransport | None,
) -> dict[str, Any]:
    options: dict[str, Any] = {"timeout": timeout_seconds}
    if transport is not None:
        options["transport"] = transport
    return options


async def _get_json(
    *,
    base_url: str,
    path: str,
    timeout_seconds: float,
    params: dict[str, Any] | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> Any:
    async with httpx.AsyncClient(
        **_client_options(timeout_seconds=timeout_seconds, transport=transport)
    ) as client:
        response = await client.get(_url(base_url, path), params=params)
        response.raise_for_status()
        return response.json()


async def comfyui_flux_klein_available(
    *,
    base_url: str,
    timeout_seconds: float = 4,
    transport: httpx.AsyncBaseTransport | None = None,
) -> bool:
    """Return whether the required custom node is registered."""

    try:
        payload = await _get_json(
            base_url=base_url,
            path="/object_info",
            timeout_seconds=timeout_seconds,
            transport=transport,
        )
    except Exception:
        return False
    return isinstance(payload, dict) and "FluxKleinOneNode" in payload


async def fetch_comfyui_node_names(
    *,
    base_url: str,
    timeout_seconds: float = 8,
    transport: httpx.AsyncBaseTransport | None = None,
) -> set[str]:
    """Return registered node names, or an empty set when ComfyUI is unavailable."""

    try:
        payload = await _get_json(
            base_url=base_url,
            path="/object_info",
            timeout_seconds=timeout_seconds,
            transport=transport,
        )
    except Exception:
        return set()
    return set(payload.keys()) if isinstance(payload, dict) else set()


async def fetch_comfyui_models(
    *,
    base_url: str,
    timeout_seconds: float = 10,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, list[str]]:
    payload = await _get_json(
        base_url=base_url,
        path="/flux_klein/models",
        timeout_seconds=timeout_seconds,
        transport=transport,
    )
    return {
        "diffusion_models": payload.get("diffusion_models", []),
        "text_encoders": payload.get("text_encoders", []),
        "vaes": payload.get("vaes", []),
        "loras": payload.get("loras", []),
    }


async def fetch_flux_klein_config(
    *,
    base_url: str,
    timeout_seconds: float = 10,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    payload = await _get_json(
        base_url=base_url,
        path="/flux_klein/config",
        timeout_seconds=timeout_seconds,
        transport=transport,
    )
    return {
        "autofill_prompts": payload.get("autofill_prompts", {}),
        "lora_triggers_custom": payload.get("lora_triggers_custom", {}),
        "t2i_templates": payload.get("t2i_templates", []),
        "discover_prompts": payload.get("discover_prompts", {}),
    }


async def fetch_flux_bgremoval_models(
    *,
    base_url: str,
    timeout_seconds: float = 10,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    return await _get_json(
        base_url=base_url,
        path="/flux_klein/bgremoval_models",
        timeout_seconds=timeout_seconds,
        transport=transport,
    )


async def fetch_flux_lora_triggers(
    *,
    base_url: str,
    name: str,
    timeout_seconds: float = 10,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    return await _get_json(
        base_url=base_url,
        path="/flux_klein/lora_triggers",
        params={"name": name},
        timeout_seconds=timeout_seconds,
        transport=transport,
    )


async def upload_comfyui_image(
    *,
    base_url: str,
    path: Path,
    timeout_seconds: float = 60,
    transport: httpx.AsyncBaseTransport | None = None,
) -> str:
    async with httpx.AsyncClient(
        **_client_options(timeout_seconds=timeout_seconds, transport=transport)
    ) as client:
        with path.open("rb") as file:
            response = await client.post(
                _url(base_url, "/upload/image"),
                files={"image": (path.name, file, "image/png")},
                data={"overwrite": "true", "type": "input"},
            )
        response.raise_for_status()
        payload = response.json()
    return payload.get("name") or path.name


async def fetch_comfyui_workflow(
    *,
    base_url: str,
    endpoint: str,
    timeout_seconds: float = 20,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    return await _get_json(
        base_url=base_url,
        path=f"/flux_klein/{endpoint}",
        timeout_seconds=timeout_seconds,
        transport=transport,
    )


async def submit_comfyui_workflow(
    *,
    base_url: str,
    workflow: dict[str, Any],
    job_id: str,
    timeout_seconds: float = 30,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    async with httpx.AsyncClient(
        **_client_options(timeout_seconds=timeout_seconds, transport=transport)
    ) as client:
        response = await client.post(
            _url(base_url, "/prompt"),
            json={
                "prompt": workflow,
                "client_id": f"onenode-backend-{job_id}",
                "extra_data": {"enable_previews": True},
            },
        )
        response.raise_for_status()
        return response.json()


async def interrupt_comfyui(
    *,
    base_url: str,
    timeout_seconds: float = 5,
    transport: httpx.AsyncBaseTransport | None = None,
) -> None:
    """Request interruption without changing the legacy non-raising HTTP contract."""

    async with httpx.AsyncClient(
        **_client_options(timeout_seconds=timeout_seconds, transport=transport)
    ) as client:
        await client.post(_url(base_url, "/interrupt"))


async def fetch_comfyui_image_bytes(
    *,
    base_url: str,
    image: dict[str, str],
    timeout_seconds: float = 120,
    transport: httpx.AsyncBaseTransport | None = None,
) -> bytes:
    params = {
        "filename": image["filename"],
        "subfolder": image.get("subfolder", ""),
        "type": image.get("type", "output"),
    }
    async with httpx.AsyncClient(
        **_client_options(timeout_seconds=timeout_seconds, transport=transport)
    ) as client:
        response = await client.get(_url(base_url, "/view"), params=params)
        response.raise_for_status()
        return response.content


async def free_comfyui_memory(
    *,
    base_url: str,
    timeout_seconds: float = 10,
    transport: httpx.AsyncBaseTransport | None = None,
) -> bool:
    async with httpx.AsyncClient(
        **_client_options(timeout_seconds=timeout_seconds, transport=transport)
    ) as client:
        response = await client.post(
            _url(base_url, "/free"),
            json={"unload_models": True, "free_memory": True},
        )
        response.raise_for_status()
    return True
