"""Authenticated Phone API v1 platform manifest."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Request

from ...services.phone_platform import phone_platform_manifest


@dataclass(frozen=True)
class PhonePlatformDependencies:
    require_trusted_user: Callable[[Request], dict[str, Any]]


def create_phone_platform_router(deps: PhonePlatformDependencies) -> APIRouter:
    router = APIRouter(prefix="/api/phone/v1", tags=["phone-v1"])

    @router.get("/platform")
    async def phone_platform(request: Request) -> dict[str, Any]:
        deps.require_trusted_user(request)
        return phone_platform_manifest()

    return router
