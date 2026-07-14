from __future__ import annotations

import asyncio
import httpx
import pytest

from app.integrations.yookassa import YooKassaError, create_yookassa_payment, fetch_yookassa_payment, rubles_value


def payment_payload(status="pending"):
    return {"id": "pay-1", "status": status, "paid": status == "succeeded", "amount": {"value": "250.00", "currency": "RUB"}, "confirmation": {"confirmation_url": "https://pay.test/1"}}


def test_create_payment_uses_basic_auth_and_idempotency():
    async def handler(request: httpx.Request):
        assert request.headers["Idempotence-Key"] == "checkout-1"
        assert request.headers["Authorization"].startswith("Basic ")
        return httpx.Response(200, json=payment_payload(), request=request)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await create_yookassa_payment(shop_id="shop", secret_key="secret", amount=250, idempotency_key="checkout-1", return_url="https://izo.test/", description="50 tokens", metadata={"invoice_id": "inv"}, client=client)
    result = asyncio.run(run())
    assert result.id == "pay-1" and result.confirmation_url == "https://pay.test/1"


def test_fetch_payment_parses_verified_status():
    async def handler(request: httpx.Request):
        return httpx.Response(200, json=payment_payload("succeeded"), request=request)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await fetch_yookassa_payment("pay-1", shop_id="shop", secret_key="secret", client=client)
    result = asyncio.run(run())
    assert result.paid is True and result.amount_value == "250.00"


def test_rubles_value_rejects_non_positive_amount():
    assert rubles_value(250) == "250.00"
    with pytest.raises(YooKassaError):
        rubles_value(0)
