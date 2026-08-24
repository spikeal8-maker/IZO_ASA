"""Provider-neutral contracts for future durable Phone 3D generation.

This module deliberately contains no provider key, HTTP client, billing write,
or production route. It is the boundary that Meshy, Tripo, and fake adapters
must satisfy before the disabled Phone 3D capability can be enabled.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, cast
from urllib.parse import urlparse


ThreeDMode = Literal["text_to_3d", "image_to_3d"]
ThreeDStatus = Literal["created", "queued", "running", "completed", "failed", "cancelled"]
ThreeDFormat = Literal["glb", "obj", "fbx", "stl", "usdz", "3mf"]

TERMINAL_3D_STATES = frozenset({"completed", "failed", "cancelled"})
SUPPORTED_3D_FORMATS = frozenset({"glb", "obj", "fbx", "stl", "usdz", "3mf"})
MOBILE_GLB_BUDGET_BYTES = 20 * 1024 * 1024
MOBILE_TRIANGLE_BUDGET = 150_000
MOBILE_TEXTURE_BUDGET = 2048


@dataclass(frozen=True)
class ThreeDRequest:
    mode: ThreeDMode
    prompt: str
    image_url: str | None = None
    texture: bool = True
    texture_resolution: Literal["2k", "4k"] = "2k"
    target_triangles: int = MOBILE_TRIANGLE_BUDGET
    output_format: ThreeDFormat = "glb"
    idempotency_key: str = ""

    def validate(self) -> None:
        if self.mode not in {"text_to_3d", "image_to_3d"}:
            raise ValueError("Unsupported 3D mode.")
        if not self.prompt.strip() or len(self.prompt) > 1_024:
            raise ValueError("3D prompt must contain 1 to 1024 characters.")
        if self.mode == "image_to_3d" and not self.image_url:
            raise ValueError("Image-to-3D requires an owned input image.")
        if self.output_format not in SUPPORTED_3D_FORMATS:
            raise ValueError("Unsupported 3D output format.")
        if not 1_000 <= self.target_triangles <= 500_000:
            raise ValueError("Unsafe triangle target.")
        if not self.idempotency_key.strip():
            raise ValueError("A durable idempotency key is required.")


@dataclass(frozen=True)
class ThreeDQuote:
    provider: str
    provider_credits: float
    charged_tokens: int
    currency_cost_usd: float | None = None


@dataclass(frozen=True)
class ThreeDAsset:
    format: ThreeDFormat
    source_url: str
    poster_url: str | None = None
    byte_size: int | None = None
    triangle_count: int | None = None
    texture_size: int | None = None

    def validate_provider_result(self) -> None:
        if self.format not in SUPPORTED_3D_FORMATS:
            raise ValueError("Provider returned an unsupported 3D format.")
        parsed = urlparse(self.source_url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("Provider asset URL must use HTTPS.")
        if self.poster_url:
            poster = urlparse(self.poster_url)
            if poster.scheme != "https" or not poster.netloc:
                raise ValueError("Provider poster URL must use HTTPS.")

    @property
    def mobile_ready(self) -> bool:
        return (
            self.format == "glb"
            and (self.byte_size is None or self.byte_size <= MOBILE_GLB_BUDGET_BYTES)
            and (self.triangle_count is None or self.triangle_count <= MOBILE_TRIANGLE_BUDGET)
            and (self.texture_size is None or self.texture_size <= MOBILE_TEXTURE_BUDGET)
        )


@dataclass(frozen=True)
class ThreeDJob:
    provider: str
    provider_task_id: str
    status: ThreeDStatus
    progress: int
    asset: ThreeDAsset | None = None
    error_code: str | None = None
    error_message: str | None = None
    provider_usage: dict[str, Any] = field(default_factory=dict)

    @property
    def terminal(self) -> bool:
        return self.status in TERMINAL_3D_STATES


class ThreeDProvider(Protocol):
    name: str

    async def quote(self, request: ThreeDRequest) -> ThreeDQuote: ...

    async def create(self, request: ThreeDRequest) -> ThreeDJob: ...

    async def get(self, provider_task_id: str) -> ThreeDJob: ...

    async def cancel(self, provider_task_id: str) -> bool: ...


def normalize_3d_status(value: Any) -> ThreeDStatus:
    normalized = str(value or "").strip().casefold()
    aliases: dict[str, ThreeDStatus] = {
        "pending": "queued", "in_progress": "running", "processing": "running",
        "succeeded": "completed", "success": "completed", "done": "completed",
        "failure": "failed", "error": "failed", "canceled": "cancelled",
    }
    result = aliases.get(normalized, normalized)
    if result not in {"created", "queued", "running", "completed", "failed", "cancelled"}:
        return "created"
    return cast(ThreeDStatus, result)


def public_3d_error(_provider_message: Any) -> str:
    """Never expose provider diagnostics, URLs, keys, or stack traces to users."""

    return "3D-модель не создана. Попробуйте ещё раз или обратитесь в поддержку."
