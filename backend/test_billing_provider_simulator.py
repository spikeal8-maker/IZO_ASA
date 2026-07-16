from __future__ import annotations

import asyncio

import pytest

from app.billing import (
    PaymentCreateCommand,
    PaymentProviderError,
    PaymentReceipt,
    PaymentReceiptItem,
    SimulatedPaymentProvider,
)


def command(key: str = "checkout-1") -> PaymentCreateCommand:
    return PaymentCreateCommand(
        amount=250,
        currency="RUB",
        idempotency_key=key,
        return_url="https://izo.example/payment",
        description="50 tokens",
        metadata={"payment_id": "local-1"},
        receipt=PaymentReceipt(
            contact="buyer@example.test",
            items=(PaymentReceiptItem(description="50 tokens", quantity=1, amount=250),),
        ),
    )


def test_simulator_is_idempotent_and_has_stable_confirmation_url() -> None:
    provider = SimulatedPaymentProvider(
        enabled=True,
        app_env="test",
        confirmation_base_url="https://izo.example/dev-payment",
    )
    first = asyncio.run(provider.create_payment(command()))
    second = asyncio.run(provider.create_payment(command()))

    assert first == second
    assert first.status == "pending"
    assert first.confirmation_url and first.id in first.confirmation_url


def test_simulator_supports_success_and_rejects_terminal_rewrite() -> None:
    provider = SimulatedPaymentProvider(enabled=True, app_env="test", confirmation_base_url="https://izo.example/dev-payment")
    created = asyncio.run(provider.create_payment(command()))
    succeeded = provider.transition(created.id, "succeeded")

    assert succeeded.paid is True
    assert asyncio.run(provider.fetch_payment(created.id)) == succeeded
    with pytest.raises(PaymentProviderError, match="terminal"):
        provider.transition(created.id, "canceled")


def test_simulator_cannot_be_enabled_in_production() -> None:
    with pytest.raises(PaymentProviderError, match="production"):
        SimulatedPaymentProvider(enabled=True, app_env="production", confirmation_base_url="https://izo.example/dev-payment")


def test_payment_contract_rejects_invalid_money_and_empty_receipt() -> None:
    with pytest.raises(ValueError, match="positive"):
        PaymentCreateCommand(amount=0, currency="RUB", idempotency_key="x", return_url="https://izo.example", description="bad")
    with pytest.raises(ValueError, match="at least one"):
        PaymentReceipt(contact="buyer@example.test", items=())
