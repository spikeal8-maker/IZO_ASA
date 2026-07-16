"""YooKassa HTTP API adapter with explicit idempotency."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import httpx


YOOKASSA_API_URL = "https://api.yookassa.ru/v3"


class YooKassaError(RuntimeError):
    pass


@dataclass(frozen=True)
class YooKassaPayment:
    id: str
    status: str
    amount_value: str
    currency: str
    confirmation_url: str | None
    paid: bool


def rubles_value(amount: int) -> str:
    if amount <= 0:
        raise YooKassaError("Payment amount must be positive.")
    return f"{Decimal(amount):.2f}"


def parse_payment(payload: Any) -> YooKassaPayment:
    if not isinstance(payload, dict) or not payload.get("id"):
        raise YooKassaError("YooKassa returned an invalid payment.")
    amount = payload.get("amount") if isinstance(payload.get("amount"), dict) else {}
    confirmation = payload.get("confirmation") if isinstance(payload.get("confirmation"), dict) else {}
    return YooKassaPayment(
        id=str(payload["id"]),
        status=str(payload.get("status") or "unknown"),
        amount_value=str(amount.get("value") or ""),
        currency=str(amount.get("currency") or ""),
        confirmation_url=str(confirmation["confirmation_url"]) if confirmation.get("confirmation_url") else None,
        paid=bool(payload.get("paid")),
    )


async def create_yookassa_payment(
    *,
    shop_id: str,
    secret_key: str,
    amount: int,
    idempotency_key: str,
    return_url: str,
    description: str,
    metadata: dict[str, str],
    receipt: dict[str, Any] | None = None,
    client: httpx.AsyncClient | None = None,
) -> YooKassaPayment:
    owns_client = client is None
    current = client or httpx.AsyncClient(timeout=25.0)
    try:
        payload: dict[str, Any] = {
            "amount": {"value": rubles_value(amount), "currency": "RUB"},
            "capture": True,
            "confirmation": {"type": "redirect", "return_url": return_url},
            "description": description[:128],
            "metadata": metadata,
        }
        if receipt is not None:
            payload["receipt"] = receipt
        response = await current.post(
            f"{YOOKASSA_API_URL}/payments",
            auth=(shop_id, secret_key),
            headers={"Idempotence-Key": idempotency_key},
            json=payload,
        )
        response.raise_for_status()
        return parse_payment(response.json())
    except (httpx.HTTPError, ValueError) as exc:
        raise YooKassaError("YooKassa payment request failed.") from exc
    finally:
        if owns_client:
            await current.aclose()


async def fetch_yookassa_payment(
    payment_id: str,
    *,
    shop_id: str,
    secret_key: str,
    client: httpx.AsyncClient | None = None,
) -> YooKassaPayment:
    owns_client = client is None
    current = client or httpx.AsyncClient(timeout=20.0)
    try:
        response = await current.get(f"{YOOKASSA_API_URL}/payments/{payment_id}", auth=(shop_id, secret_key))
        response.raise_for_status()
        return parse_payment(response.json())
    except (httpx.HTTPError, ValueError) as exc:
        raise YooKassaError("YooKassa payment verification failed.") from exc
    finally:
        if owns_client:
            await current.aclose()
