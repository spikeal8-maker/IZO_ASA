"""Import-safe MAX API TLS trust-store policy."""

from __future__ import annotations

import ssl
from pathlib import Path
from typing import Any, Callable


MAX_BUNDLED_CA_PATH = Path(__file__).with_name("certs") / "russian_trusted_root_ca.pem"


def normalize_max_tls_trust_store(value: str | None) -> str:
    mode = str(value or "system").strip().lower() or "system"
    if mode not in {"system", "certifi"}:
        raise RuntimeError("MAX_TLS_TRUST_STORE must be 'system' or 'certifi'.")
    return mode


def build_max_http_verify(
    mode: str,
    *,
    system_context_factory: Callable[[Any], Any] | None = None,
    bundled_ca_path: str | Path | None = None,
) -> Any:
    normalized = normalize_max_tls_trust_store(mode)
    if normalized == "certifi":
        return True
    if system_context_factory is None:
        import truststore

        system_context_factory = truststore.SSLContext
    context = system_context_factory(ssl.PROTOCOL_TLS_CLIENT)
    ca_path = Path(bundled_ca_path) if bundled_ca_path is not None else MAX_BUNDLED_CA_PATH
    if not ca_path.is_file():
        raise RuntimeError(f"Bundled MAX CA certificate is missing: {ca_path}")
    context.load_verify_locations(cafile=str(ca_path))
    return context
