from __future__ import annotations

import asyncio
import base64
import io

import httpx
import pytest
from PIL import Image

from app.integrations.openrouter import (
    OpenRouterVideoRequestError, fetch_openrouter_image_model_documents,
    fetch_openrouter_text_models, poll_openrouter_video, submit_openrouter_video,
)
from app.integrations.openrouter_image_io import load_openrouter_response_image
from app.integrations.openrouter_transport import CLOSED_BASE, client_options, endpoint_document_url


@pytest.fixture(autouse=True)
def closed(monkeypatch):
    monkeypatch.setenv("IZO_OPENROUTER_TRANSPORT", "closed-proxy-v1")


def test_closed_transport_ignores_proxy_environment_and_disables_redirects(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://untrusted.invalid:8080")
    options = client_options(CLOSED_BASE, timeout=15, follow_redirects=True)
    assert options["trust_env"] is False and options["follow_redirects"] is False
    with pytest.raises(ValueError, match="BASE_INVALID"):
        client_options("https://openrouter.ai/api/v1", timeout=15)


@pytest.mark.parametrize("value", [
    "https://evil.invalid/api/v1/images/models/a/b/endpoints",
    "https://openrouter.ai.evil.invalid/api/v1/images/models/a/b/endpoints",
    "https://user@openrouter.ai/api/v1/images/models/a/b/endpoints",
    "https://openrouter.ai:443/api/v1/images/models/a/b/endpoints",
    "http://openrouter.ai/api/v1/images/models/a/b/endpoints",
    "//evil.invalid/api/v1/images/models/a/b/endpoints",
    "/api/v1/images/models/a/b/endpoints?key=fixture",
    "/api/v1/images/models/a/b/endpoints#fragment",
    "/api/v1/images/models/a/../b/endpoints",
    "/api/v1/images/models/a/b%2fother/endpoints",
])
def test_closed_endpoint_documents_reject_foreign_or_ambiguous_targets(value):
    with pytest.raises(ValueError):
        endpoint_document_url(value, base_url=CLOSED_BASE, endpoint_base_url="https://openrouter.ai")


@pytest.mark.parametrize("prefix", ["", "https://openrouter.ai"])
def test_closed_endpoint_documents_are_rewritten_to_only_the_loopback_proxy(prefix):
    path = "/api/v1/images/models/author/model/endpoints"
    assert endpoint_document_url(prefix + path, base_url=CLOSED_BASE, endpoint_base_url="https://ignored.invalid") == "http://127.0.0.1:18189" + path


def test_actual_closed_catalog_never_sends_credentials_to_foreign_metadata():
    seen = []

    def handler(request):
        seen.append((str(request.url), request.headers.get("authorization")))
        if request.url.path.endswith("/images/models"):
            return httpx.Response(200, json={"data": [
                {"id": "a/good", "endpoints": "https://openrouter.ai/api/v1/images/models/a/good/endpoints"},
                {"id": "a/bad", "endpoints": "https://evil.invalid/collect"},
            ]})
        return httpx.Response(200, json={"endpoints": [{"provider_tag": "valid"}]})

    rows = asyncio.run(fetch_openrouter_image_model_documents(base_url=CLOSED_BASE,
        headers={"Authorization": "Bearer fixture"}, transport=httpx.MockTransport(handler)))
    assert len(seen) == 2 and all(url.startswith("http://127.0.0.1:18189/api/v1/") for url, _ in seen)
    assert rows[0]["endpoint_status"] == 200
    assert rows[1]["endpoint_status"] is None and rows[1]["endpoints"] == []


def test_closed_catalog_redirect_does_not_follow_to_any_origin():
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(302, headers={"Location": "https://evil.invalid/"})

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(fetch_openrouter_text_models(base_url=CLOSED_BASE, headers={}, transport=httpx.MockTransport(handler)))
    assert len(seen) == 1


def test_closed_images_accept_inline_data_but_never_download_remote_urls():
    buffer = io.BytesIO()
    Image.new("RGB", (2, 2), "red").save(buffer, format="PNG")
    inline = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()
    image = asyncio.run(load_openrouter_response_image({"url": inline}, timeout_seconds=1))
    assert image.size == (2, 2)
    image.close()

    def network_forbidden(_request):
        pytest.fail("remote image request escaped closed mode")

    with pytest.raises(RuntimeError, match="inline image"):
        asyncio.run(load_openrouter_response_image({"url": "https://cdn.invalid/result.png"},
            timeout_seconds=1, transport=httpx.MockTransport(network_forbidden)))


def test_closed_video_submit_and_poll_fail_before_any_request():
    def network_forbidden(_request):
        pytest.fail("video request escaped closed profile")

    transport = httpx.MockTransport(network_forbidden)
    for operation in (submit_openrouter_video(base_url=CLOSED_BASE, headers={}, payload={}, transport=transport),
                      poll_openrouter_video(base_url=CLOSED_BASE, headers={}, job_id="fixture", polling_url="https://foreign.invalid/", transport=transport)):
        with pytest.raises(OpenRouterVideoRequestError, match="disabled"):
            asyncio.run(operation)


def test_direct_windows_compatibility_is_explicit(monkeypatch):
    monkeypatch.setenv("IZO_OPENROUTER_TRANSPORT", "direct")
    assert client_options("https://openrouter.test/api/v1", timeout=5, follow_redirects=True) == {"timeout": 5, "follow_redirects": True}
    assert endpoint_document_url("https://metadata.test/model", base_url="https://openrouter.test", endpoint_base_url="https://openrouter.test") == "https://metadata.test/model"
