"""Bounded HTTP request and allowlisted avatar decoding primitives."""

from __future__ import annotations

import io
import warnings

from PIL import Image, ImageOps
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class AvatarImageError(RuntimeError):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


class RequestBodyTooLarge(Exception):
    pass


class RequestBodyLimitMiddleware:
    """Reject oversized bodies even when the client omits Content-Length."""

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        try:
            declared_length = int(headers.get(b"content-length", b"0"))
        except ValueError:
            declared_length = 0
        if declared_length > self.max_bytes:
            await self._send_rejection(send)
            return
        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise RequestBodyTooLarge
            return message

        try:
            await self.app(scope, limited_receive, send)
        except RequestBodyTooLarge:
            await self._send_rejection(send)

    @staticmethod
    async def _send_rejection(send: Send) -> None:
        body = b'{"detail":"Request body is too large."}'
        await send({
            "type": "http.response.start",
            "status": 413,
            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
        })
        await send({"type": "http.response.body", "body": body})


def compress_allowlisted_avatar(
    data: bytes,
    declared_content_type: str | None,
    *,
    allowed_format_types: dict[str, set[str]],
    max_side: int,
    max_pixels: int,
    output_size: int,
    webp_quality: int,
) -> bytes:
    try:
        declared_type = (declared_content_type or "").strip().lower()
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as probe:
                image_format = (probe.format or "").upper()
                if image_format not in allowed_format_types:
                    raise AvatarImageError(415, "Avatar image format is not allowed.")
                if declared_type and declared_type not in allowed_format_types[image_format]:
                    raise AvatarImageError(415, "Avatar content type does not match the image.")
                width, height = probe.size
                if width < 1 or height < 1 or width > max_side or height > max_side or width * height > max_pixels:
                    raise AvatarImageError(413, "Avatar image dimensions are too large.")
                probe.verify()
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                image.load()
                image = ImageOps.exif_transpose(image)
                if image.mode not in ("RGB", "RGBA"):
                    image = image.convert("RGBA")
                if image.mode == "RGBA":
                    background = Image.new("RGBA", image.size, (18, 22, 20, 255))
                    background.alpha_composite(image)
                    image = background.convert("RGB")
                else:
                    image = image.convert("RGB")
                image = ImageOps.fit(image, (output_size, output_size), method=Image.Resampling.LANCZOS)
                output = io.BytesIO()
                image.save(output, format="WEBP", quality=webp_quality, method=6)
                return output.getvalue()
    except AvatarImageError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise AvatarImageError(413, "Avatar image dimensions are too large.")
    except Exception as exc:
        raise AvatarImageError(400, "Avatar file is not a valid image.") from exc
