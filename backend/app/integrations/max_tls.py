"""Import-safe MAX API TLS trust-store policy."""

from __future__ import annotations

import ssl
from typing import Any, Callable


def normalize_max_tls_trust_store(value: str | None) -> str:
    mode = str(value or "system").strip().lower() or "system"
    if mode not in {"system", "certifi"}:
        raise RuntimeError("MAX_TLS_TRUST_STORE must be 'system' or 'certifi'.")
    return mode


def build_max_http_verify(
    mode: str,
    *,
    system_context_factory: Callable[[Any], Any] | None = None,
) -> Any:
    normalized = normalize_max_tls_trust_store(mode)
    if normalized == "certifi":
        return True
    if system_context_factory is None:
        import truststore

        system_context_factory = truststore.SSLContext
    return system_context_factory(ssl.PROTOCOL_TLS_CLIENT)
