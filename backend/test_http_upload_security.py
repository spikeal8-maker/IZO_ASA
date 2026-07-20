from __future__ import annotations

import io

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from test_support.browser_client import BrowserTestClient
from app.security.http_requests import RequestBodyLimitMiddleware
from PIL import Image

import main


def _image_bytes(image_format: str = "PNG", size: tuple[int, int] = (32, 32)) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", size, "#336655").save(output, format=image_format)
    return output.getvalue()


def test_avatar_compressor_accepts_matching_declared_type() -> None:
    output = main.compress_avatar_image(_image_bytes("PNG"), "image/png")

    with Image.open(io.BytesIO(output)) as image:
        assert image.format == "WEBP"
        assert image.size == (main.AVATAR_OUTPUT_SIZE, main.AVATAR_OUTPUT_SIZE)


def test_avatar_compressor_rejects_declared_type_mismatch() -> None:
    with pytest.raises(HTTPException) as exc_info:
        main.compress_avatar_image(_image_bytes("PNG"), "image/jpeg")

    assert exc_info.value.status_code == 415


def test_avatar_compressor_rejects_non_allowlisted_image_format(monkeypatch) -> None:
    class UnsupportedImage:
        format = "PSD"
        size = (32, 32)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def verify(self) -> None:
            raise AssertionError("unsupported files must be rejected before decoder verification")

    monkeypatch.setattr(main.Image, "open", lambda _source: UnsupportedImage())

    with pytest.raises(HTTPException) as exc_info:
        main.compress_avatar_image(b"unsupported")

    assert exc_info.value.status_code == 415


def test_avatar_compressor_rejects_excessive_pixel_dimensions(monkeypatch) -> None:
    class OversizedImage:
        format = "PNG"
        size = (main.AVATAR_MAX_SIDE + 1, 1)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def verify(self) -> None:
            raise AssertionError("oversized files must be rejected before decoder verification")

    monkeypatch.setattr(main.Image, "open", lambda _source: OversizedImage())

    with pytest.raises(HTTPException) as exc_info:
        main.compress_avatar_image(b"oversized")

    assert exc_info.value.status_code == 413


def test_backend_rejects_untrusted_host_header() -> None:
    response = BrowserTestClient(main.app).get("/api/health", headers={"host": "attacker.example"})

    assert response.status_code == 400


def test_request_body_limit_rejects_declared_oversized_payload() -> None:
    limited_app = FastAPI()
    limited_app.add_middleware(RequestBodyLimitMiddleware, max_bytes=4)

    @limited_app.post("/echo")
    async def echo(request: Request) -> dict[str, int]:
        return {"size": len(await request.body())}

    response = TestClient(limited_app).post("/echo", content=b"12345")

    assert response.status_code == 413
    assert response.json()["detail"] == "Request body is too large."


def test_request_body_limit_counts_streamed_payload_without_content_length() -> None:
    limited_app = FastAPI()
    limited_app.add_middleware(RequestBodyLimitMiddleware, max_bytes=4)

    @limited_app.post("/echo")
    async def echo(request: Request) -> dict[str, int]:
        return {"size": len(await request.body())}

    response = TestClient(limited_app).post("/echo", content=iter((b"123", b"45")))

    assert response.status_code == 413
