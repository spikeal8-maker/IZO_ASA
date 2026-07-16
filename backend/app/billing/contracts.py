from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Protocol


class PaymentProviderError(RuntimeError):
    """A safe provider-facing error that can be mapped to an API response."""


@dataclass(frozen=True, slots=True)
class PaymentReceiptItem:
    description: str
    quantity: int
    amount: int
    currency: str = "RUB"

    def __post_init__(self) -> None:
        if not self.description.strip():
            raise ValueError("Receipt item description is required.")
        if self.quantity <= 0:
            raise ValueError("Receipt item quantity must be positive.")
        if self.amount < 0:
            raise ValueError("Receipt item amount cannot be negative.")


@dataclass(frozen=True, slots=True)
class PaymentReceipt:
    contact: str
    items: tuple[PaymentReceiptItem, ...]

    def __post_init__(self) -> None:
        if not self.contact.strip():
            raise ValueError("Receipt contact is required.")
        if not self.items:
            raise ValueError("Receipt must contain at least one item.")


@dataclass(frozen=True, slots=True)
class PaymentCreateCommand:
    amount: int
    currency: str
    idempotency_key: str
    return_url: str
    description: str
    metadata: Mapping[str, str] = field(default_factory=dict)
    receipt: PaymentReceipt | None = None

    def __post_init__(self) -> None:
        if self.amount <= 0:
            raise ValueError("Payment amount must be positive.")
        if self.currency != "RUB":
            raise ValueError("Only RUB payments are supported.")
        if not self.idempotency_key.strip():
            raise ValueError("Idempotency key is required.")
        if not self.return_url.strip():
            raise ValueError("Return URL is required.")


@dataclass(frozen=True, slots=True)
class PaymentSnapshot:
    id: str
    status: str
    amount: int
    currency: str
    confirmation_url: str | None = None
    paid: bool = False


class PaymentProvider(Protocol):
    name: str

    async def create_payment(self, command: PaymentCreateCommand) -> PaymentSnapshot: ...

    async def fetch_payment(self, provider_payment_id: str) -> PaymentSnapshot: ...
