from __future__ import annotations

from typing import Any

from app.integrations.yookassa import create_yookassa_payment, fetch_yookassa_payment

from .contracts import PaymentCreateCommand, PaymentProviderError, PaymentSnapshot


def build_yookassa_receipt(
    command: PaymentCreateCommand,
    *,
    vat_code: int | None,
    payment_subject: str = "service",
) -> dict[str, Any] | None:
    receipt = command.receipt
    if receipt is None:
        return None
    if vat_code is None:
        raise PaymentProviderError("YooKassa receipt VAT code is not configured.")
    contact = receipt.contact.strip()
    customer = {"email": contact} if "@" in contact else {"phone": contact}
    return {
        "customer": customer,
        "items": [
            {
                "description": item.description.strip()[:128],
                "quantity": f"{item.quantity:.3f}",
                "amount": {"value": f"{item.amount:.2f}", "currency": item.currency},
                "vat_code": vat_code,
                "payment_mode": "full_payment",
                "payment_subject": payment_subject.strip() or "service",
            }
            for item in receipt.items
        ],
    }


class YooKassaPaymentProvider:
    name = "yookassa"

    def __init__(
        self,
        *,
        shop_id: str,
        secret_key: str,
        receipt_vat_code: int | None,
        payment_subject: str = "service",
    ) -> None:
        self._shop_id = shop_id.strip()
        self._secret_key = secret_key.strip()
        self._receipt_vat_code = receipt_vat_code
        self._payment_subject = payment_subject.strip() or "service"
        if not self._shop_id or not self._secret_key:
            raise PaymentProviderError("YooKassa credentials are not configured.")

    def _receipt_payload(self, command: PaymentCreateCommand) -> dict[str, Any] | None:
        return build_yookassa_receipt(
            command,
            vat_code=self._receipt_vat_code,
            payment_subject=self._payment_subject,
        )

    async def create_payment(self, command: PaymentCreateCommand) -> PaymentSnapshot:
        result = await create_yookassa_payment(
            shop_id=self._shop_id,
            secret_key=self._secret_key,
            amount=command.amount,
            idempotency_key=command.idempotency_key,
            return_url=command.return_url,
            description=command.description,
            metadata=dict(command.metadata),
            receipt=self._receipt_payload(command),
        )
        return PaymentSnapshot(
            id=result.id,
            status=result.status,
            amount=int(round(float(result.amount_value))),
            currency=result.currency,
            confirmation_url=result.confirmation_url,
            paid=result.paid,
        )

    async def fetch_payment(self, provider_payment_id: str) -> PaymentSnapshot:
        result = await fetch_yookassa_payment(
            provider_payment_id,
            shop_id=self._shop_id,
            secret_key=self._secret_key,
        )
        return PaymentSnapshot(
            id=result.id,
            status=result.status,
            amount=int(round(float(result.amount_value))),
            currency=result.currency,
            confirmation_url=result.confirmation_url,
            paid=result.paid,
        )
