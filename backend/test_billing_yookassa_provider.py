from __future__ import annotations

import asyncio

import pytest

from app.billing import (
    PaymentCreateCommand,
    PaymentProviderError,
    PaymentReceipt,
    PaymentReceiptItem,
    YooKassaPaymentProvider,
)
from app.integrations.yookassa import YooKassaPayment


def command() -> PaymentCreateCommand:
    return PaymentCreateCommand(
        amount=250,
        currency="RUB",
        idempotency_key="checkout-receipt-1",
        return_url="https://izo.example/payment",
        description="50 tokens",
        receipt=PaymentReceipt(
            contact="buyer@example.test",
            items=(PaymentReceiptItem(description="50 tokens", quantity=1, amount=250),),
        ),
    )


def test_yookassa_provider_maps_receipt(monkeypatch) -> None:
    captured = {}

    async def create(**kwargs):
        captured.update(kwargs)
        return YooKassaPayment("pay-1", "pending", "250.00", "RUB", "https://pay.test", False)

    monkeypatch.setattr("app.billing.yookassa_provider.create_yookassa_payment", create)
    provider = YooKassaPaymentProvider(
        shop_id="shop",
        secret_key="secret",
        receipt_vat_code=1,
        payment_subject="service",
    )
    result = asyncio.run(provider.create_payment(command()))

    assert result.amount == 250
    assert captured["receipt"]["customer"] == {"email": "buyer@example.test"}
    assert captured["receipt"]["items"][0] == {
        "description": "50 tokens",
        "quantity": "1.000",
        "amount": {"value": "250.00", "currency": "RUB"},
        "vat_code": 1,
        "payment_mode": "full_payment",
        "payment_subject": "service",
    }


def test_yookassa_provider_requires_explicit_receipt_tax_code() -> None:
    provider = YooKassaPaymentProvider(shop_id="shop", secret_key="secret", receipt_vat_code=None)
    with pytest.raises(PaymentProviderError, match="VAT code"):
        asyncio.run(provider.create_payment(command()))
