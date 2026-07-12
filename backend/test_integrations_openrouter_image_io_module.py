from __future__ import annotations

import asyncio
import base64
import io

import httpx
import pytest
from PIL import Image

import main
from app.integrations.openrouter_image_io import (
    load_openrouter_response_image,
    resolve_openrouter_reference_value,
)


def png_bytes(size: tuple[int, int] = (3, 2)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, (10, 20, 30)).save(buffer, "PNG")
    return buffer.getvalue()


@pytest.mark.parametrize(
    "source",
    [
        "data:image/png;base64,AA==",
        "https://images.test/source.png",
        "http://images.test/source.png",
    ],
)
def test_reference_value_preserves_remote_and_data_urls(source):
    def unexpected_resolver(_value):
        raise AssertionError("passthrough references must not access local media")

    assert resolve_openrouter_reference_value(
        f"  {source}  ",
        local_path_resolver=unexpected_resolver,
    ) == source


@pytest.mark.parametrize("source", [None, "", "   "])
def test_reference_value_preserves_missing_source_error(source):
    with pytest.raises(RuntimeError, match="Для режима «По фото» требуется исходное изображение"):
        resolve_openrouter_reference_value(source, local_path_resolver=lambda _value: None)


def test_reference_value_encodes_application_resolved_local_file(tmp_path):
    source_path = tmp_path / "source.webp"
    source_path.write_bytes(b"source-bytes")
    seen: list[str] = []

    value = resolve_openrouter_reference_value(
        "  /api/media/source.webp  ",
        local_path_resolver=lambda source: seen.append(source) or source_path,
    )

    assert seen == ["/api/media/source.webp"]
    assert value == f"data:image/webp;base64,{base64.b64encode(b'source-bytes').decode('ascii')}"


def test_reference_value_uses_png_fallback_for_unknown_extension(tmp_path):
    source_path = tmp_path / "source.unknown-extension"
    source_path.write_bytes(b"unknown")

    value = resolve_openrouter_reference_value(
        "source-value",
        local_path_resolver=lambda _source: source_path,
    )

    assert value.startswith("data:image/png;base64,")


def test_reference_value_preserves_unavailable_local_source_error():
    with pytest.raises(RuntimeError, match="Исходное изображение недоступно для OpenRouter"):
        resolve_openrouter_reference_value(
            "/api/media/missing.webp",
            local_path_resolver=lambda _source: None,
        )


@pytest.mark.parametrize("field", ["b64_json", "base64", "image_base64"])
def test_response_image_loads_all_legacy_base64_fields(field):
    encoded = base64.b64encode(png_bytes((4, 3))).decode("ascii")

    with asyncio.run(load_openrouter_response_image(
        {field: encoded},
        timeout_seconds=9,
    )) as image:
        assert image.size == (4, 3)


def test_response_image_strips_data_url_prefix():
    encoded = base64.b64encode(png_bytes((5, 4))).decode("ascii")

    with asyncio.run(load_openrouter_response_image(
        {"b64_json": f"data:image/png;base64,{encoded}"},
        timeout_seconds=9,
    )) as image:
        assert image.size == (5, 4)


def test_response_image_follows_redirects_and_uses_timeout_for_remote_url():
    seen: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/redirect":
            return httpx.Response(302, headers={"Location": "/final"})
        return httpx.Response(200, content=png_bytes((6, 5)), headers={"Content-Type": "image/png"})

    with asyncio.run(load_openrouter_response_image(
        {"url": "https://images.test/redirect"},
        timeout_seconds=7,
        transport=httpx.MockTransport(handler),
    )) as image:
        assert image.size == (6, 5)

    assert [request.url.path for request in seen] == ["/redirect", "/final"]
    assert all(set(request.extensions["timeout"].values()) == {7} for request in seen)


def test_response_image_preserves_remote_http_error():
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "unavailable"})

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(load_openrouter_response_image(
            {"url": "https://images.test/unavailable"},
            timeout_seconds=7,
            transport=httpx.MockTransport(handler),
        ))


@pytest.mark.parametrize("payload", [{}, {"url": ""}, {"b64_json": ""}])
def test_response_image_preserves_missing_payload_error(payload):
    with pytest.raises(RuntimeError, match="OpenRouter response не содержит b64_json или url изображения"):
        asyncio.run(load_openrouter_response_image(payload, timeout_seconds=7))


def test_main_reference_value_wrapper_keeps_application_path_resolver(monkeypatch):
    expected = "data:image/png;base64,sentinel"
    captured: dict[str, object] = {}

    def path_resolver(_source):
        raise AssertionError("fake integration must receive but not call resolver")

    def fake_resolve(source, *, local_path_resolver):
        captured.update({"source": source, "resolver": local_path_resolver})
        return expected

    monkeypatch.setattr(main, "local_media_path_from_url", path_resolver)
    monkeypatch.setattr(main, "resolve_openrouter_reference_value", fake_resolve)

    assert main.openrouter_reference_value("source") == expected
    assert captured == {"source": "source", "resolver": path_resolver}


def test_main_response_image_wrapper_keeps_production_timeout(monkeypatch):
    sentinel = Image.new("RGB", (1, 1))
    captured: dict[str, object] = {}

    async def fake_load(payload, *, timeout_seconds):
        captured.update({"payload": payload, "timeout": timeout_seconds})
        return sentinel

    monkeypatch.setattr(main, "load_openrouter_response_image", fake_load)

    payload = {"url": "https://images.test/source.png"}
    assert asyncio.run(main._openrouter_image_to_pil(payload)) is sentinel
    assert captured == {"payload": payload, "timeout": main.OPENROUTER_TIMEOUT_SECONDS}
