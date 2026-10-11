"""Per-user provider secret names over an injected encrypted secret store."""

from __future__ import annotations

import hashlib
import re
from typing import Protocol


_PROVIDER_RE = re.compile(r"^[a-z0-9_]{2,24}$")


class SecretStore(Protocol):
    def exists(self, name: str) -> bool:
        ...

    def get(self, name: str) -> str:
        ...

    def set(self, name: str, value: str) -> None:
        ...

    def delete(self, name: str) -> bool:
        ...


def provider_secret_name(user_id: str, provider: str) -> str:
    provider_id = str(provider or "").strip().lower()
    if not _PROVIDER_RE.fullmatch(provider_id):
        raise ValueError("Invalid provider id.")
    subject = str(user_id or "").strip()
    if not subject:
        raise ValueError("Missing trusted user id.")
    digest = hashlib.sha256(
        f"portable-chat\0{provider_id}\0{subject}".encode("utf-8")
    ).hexdigest()[:40]
    return f"chat_{provider_id}_{digest}"


class UserProviderSecrets:
    def __init__(self, store: SecretStore) -> None:
        self._store = store

    def configured(self, user_id: str, provider: str) -> bool:
        return self._store.exists(provider_secret_name(user_id, provider))

    def get(self, user_id: str, provider: str) -> str:
        return self._store.get(provider_secret_name(user_id, provider))

    def set(self, user_id: str, provider: str, value: str) -> None:
        self._store.set(provider_secret_name(user_id, provider), value)

    def delete(self, user_id: str, provider: str) -> bool:
        return self._store.delete(provider_secret_name(user_id, provider))
