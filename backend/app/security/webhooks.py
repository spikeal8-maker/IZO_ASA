"""Import-safe webhook authentication, payload and replay helpers."""

from __future__ import annotations

import hmac
import json
import re
from collections import OrderedDict
from typing import Any


TELEGRAM_SECRET_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


class WebhookPayloadError(ValueError):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


class WebhookReplayGuard:
    """Bounded single-process replay guard for monotonic provider update IDs."""

    def __init__(self, max_entries: int = 4096) -> None:
        self.max_entries = max(1, int(max_entries))
        self._seen: OrderedDict[int, None] = OrderedDict()

    def claim(self, update_id: Any) -> bool:
        if isinstance(update_id, bool) or not isinstance(update_id, int):
            return True
        if update_id in self._seen:
            self._seen.move_to_end(update_id)
            return False
        self._seen[update_id] = None
        while len(self._seen) > self.max_entries:
            self._seen.popitem(last=False)
        return True

    def clear(self) -> None:
        self._seen.clear()

    def __len__(self) -> int:
        return len(self._seen)


def validate_telegram_webhook_secret(mode: str, secret: str | None) -> None:
    if str(mode or "").strip().lower() != "webhook":
        return
    value = str(secret or "").strip()
    if not value:
        raise RuntimeError("TELEGRAM_WEBHOOK_SECRET is required in Telegram webhook mode.")
    if len(value) > 256:
        raise RuntimeError("TELEGRAM_WEBHOOK_SECRET must contain at most 256 characters.")
    if not TELEGRAM_SECRET_PATTERN.fullmatch(value):
        raise RuntimeError("TELEGRAM_WEBHOOK_SECRET may contain only letters, digits, underscore and hyphen.")


def webhook_secret_matches(expected: str, provided: str | None) -> bool:
    if not expected or not provided:
        return False
    try:
        expected_bytes = expected.encode("ascii")
        provided_bytes = provided.encode("ascii")
    except UnicodeEncodeError:
        return False
    return hmac.compare_digest(expected_bytes, provided_bytes)


def build_telegram_set_webhook_payload(public_url: str, secret: str) -> dict[str, str]:
    return {
        "url": f"{public_url.rstrip('/')}/api/telegram/webhook",
        "secret_token": secret,
    }


def parse_webhook_json_object(body: bytes, max_body_bytes: int) -> dict[str, Any]:
    if len(body) > max_body_bytes:
        raise WebhookPayloadError(413, "Telegram webhook body is too large.")
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WebhookPayloadError(400, "Telegram webhook body must be valid JSON.") from exc
    if not isinstance(payload, dict):
        raise WebhookPayloadError(400, "Telegram webhook body must be a JSON object.")
    return payload
