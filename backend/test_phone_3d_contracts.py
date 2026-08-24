from __future__ import annotations

import asyncio
import pytest

from app.services.phone_3d_contracts import (
    MOBILE_GLB_BUDGET_BYTES,
    ThreeDAsset,
    ThreeDJob,
    ThreeDQuote,
    ThreeDRequest,
    normalize_3d_status,
    public_3d_error,
)


class FakeThreeDProvider:
    name = "fake-3d"

    async def quote(self, request: ThreeDRequest) -> ThreeDQuote:
        request.validate()
        return ThreeDQuote(self.name, provider_credits=20, charged_tokens=12)

    async def create(self, request: ThreeDRequest) -> ThreeDJob:
        request.validate()
        return ThreeDJob(self.name, "fake-task-1", "queued", 0)

    async def get(self, provider_task_id: str) -> ThreeDJob:
        asset = ThreeDAsset("glb", "https://fake.invalid/model.glb", "https://fake.invalid/poster.png", 8_000_000, 90_000, 2048)
        asset.validate_provider_result()
        return ThreeDJob(self.name, provider_task_id, "completed", 100, asset=asset)

    async def cancel(self, provider_task_id: str) -> bool:
        return provider_task_id == "fake-task-1"


def test_fake_provider_proves_quote_create_poll_contract() -> None:
    asyncio.run(_prove_fake_provider_contract())


async def _prove_fake_provider_contract() -> None:
    provider = FakeThreeDProvider()
    request = ThreeDRequest("image_to_3d", "Керамическая кружка", "https://private.invalid/source.png", idempotency_key="request-1")
    assert (await provider.quote(request)).charged_tokens == 12
    created = await provider.create(request)
    assert created.status == "queued"
    completed = await provider.get(created.provider_task_id)
    assert completed.terminal is True
    assert completed.asset and completed.asset.mobile_ready is True


def test_contract_rejects_unsafe_input_and_provider_assets() -> None:
    with pytest.raises(ValueError, match="owned input"):
        ThreeDRequest("image_to_3d", "Чашка", idempotency_key="request-2").validate()
    with pytest.raises(ValueError, match="HTTPS"):
        ThreeDAsset("glb", "file:///server/model.glb").validate_provider_result()
    assert ThreeDAsset("glb", "https://fake.invalid/large.glb", byte_size=MOBILE_GLB_BUDGET_BYTES + 1).mobile_ready is False


def test_provider_states_and_errors_are_product_safe() -> None:
    assert normalize_3d_status("SUCCEEDED") == "completed"
    assert normalize_3d_status("processing") == "running"
    assert normalize_3d_status("unexpected-provider-state") == "created"
    assert "token" not in public_3d_error("Bearer token=secret").casefold()
