from __future__ import annotations

import hashlib
from urllib.parse import urlencode

from .contracts import PaymentCreateCommand, PaymentProviderError, PaymentSnapshot


class SimulatedPaymentProvider:
    """Deterministic in-memory gateway for development and automated tests."""

    name = "simulator"

    def __init__(self, *, enabled: bool, app_env: str, confirmation_base_url: str) -> None:
        if enabled and app_env.strip().lower() == "production":
            raise PaymentProviderError("Payment simulator cannot run in production.")
        self._enabled = enabled
        self._confirmation_base_url = confirmation_base_url.rstrip("?")
        self._payments: dict[str, PaymentSnapshot] = {}
        self._idempotency: dict[str, str] = {}

    def _require_enabled(self) -> None:
        if not self._enabled:
            raise PaymentProviderError("Payment simulator is disabled.")

    async def create_payment(self, command: PaymentCreateCommand) -> PaymentSnapshot:
        self._require_enabled()
        existing_id = self._idempotency.get(command.idempotency_key)
        if existing_id:
            return self._payments[existing_id]

        digest = hashlib.sha256(command.idempotency_key.encode("utf-8")).hexdigest()[:24]
        provider_payment_id = f"sim_{digest}"
        separator = "&" if "?" in command.return_url else "?"
        confirmation_url = command.return_url + separator + urlencode(
            {"simulator": "1", "payment_id": provider_payment_id}
        )
        snapshot = PaymentSnapshot(
            id=provider_payment_id,
            status="pending",
            amount=command.amount,
            currency=command.currency,
            confirmation_url=confirmation_url,
            paid=False,
        )
        self._payments[provider_payment_id] = snapshot
        self._idempotency[command.idempotency_key] = provider_payment_id
        return snapshot

    async def fetch_payment(self, provider_payment_id: str) -> PaymentSnapshot:
        self._require_enabled()
        try:
            return self._payments[provider_payment_id]
        except KeyError as exc:
            raise PaymentProviderError("Simulated payment was not found.") from exc

    def transition(self, provider_payment_id: str, status: str) -> PaymentSnapshot:
        self._require_enabled()
        current = self._payments.get(provider_payment_id)
        if current is None:
            raise PaymentProviderError("Simulated payment was not found.")
        if status not in {"succeeded", "canceled"}:
            raise PaymentProviderError("Unsupported simulated payment status.")
        if current.status in {"succeeded", "canceled"} and current.status != status:
            raise PaymentProviderError("A terminal simulated payment cannot change status.")
        updated = PaymentSnapshot(
            id=current.id,
            status=status,
            amount=current.amount,
            currency=current.currency,
            confirmation_url=current.confirmation_url,
            paid=status == "succeeded",
        )
        self._payments[provider_payment_id] = updated
        return updated
