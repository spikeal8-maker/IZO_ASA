"""Explicit closed-mode transport policy; direct Windows behavior stays opt-in."""

from __future__ import annotations

import os
import re
from urllib.parse import urlsplit


CLOSED_MODE = "closed-proxy-v1"
CLOSED_BASE = "http://127.0.0.1:18189/api/v1"
_ENDPOINT_PATH = re.compile(r"/api/v1/images/models/[A-Za-z0-9][A-Za-z0-9._:-]{0,127}/[A-Za-z0-9][A-Za-z0-9._:-]{0,127}/endpoints")


def closed_mode() -> bool:
    mode = os.getenv("IZO_OPENROUTER_TRANSPORT", "direct").strip()
    if mode not in {"direct", CLOSED_MODE}:
        raise ValueError("OPENROUTER_TRANSPORT_MODE_INVALID")
    return mode == CLOSED_MODE


def client_options(base_url: str, *, timeout: float, transport=None,
                   follow_redirects: bool = False) -> dict:
    closed = closed_mode()
    if closed and base_url.rstrip("/") != CLOSED_BASE:
        raise ValueError("OPENROUTER_CLOSED_BASE_INVALID")
    options = {"timeout": timeout}
    if closed:
        options.update({"trust_env": False, "follow_redirects": False})
    elif follow_redirects:
        options["follow_redirects"] = True
    if transport is not None:
        options["transport"] = transport
    return options


def endpoint_document_url(value: str, *, base_url: str, endpoint_base_url: str) -> str:
    """Closed mode confines metadata credentials; direct mode retains compatibility."""
    if not closed_mode():
        return value if value.startswith("http") else endpoint_base_url.rstrip("/") + value
    parsed = urlsplit(value)
    if (parsed.query or parsed.fragment or parsed.username or parsed.password
            or (parsed.scheme and (parsed.scheme != "https" or parsed.netloc != "openrouter.ai"))
            or (parsed.netloc and not parsed.scheme) or not _ENDPOINT_PATH.fullmatch(parsed.path)):
        raise ValueError("OPENROUTER_ENDPOINT_DOCUMENT_REJECTED")
    if base_url.rstrip("/") != CLOSED_BASE:
        raise ValueError("OPENROUTER_CLOSED_BASE_INVALID")
    return CLOSED_BASE.removesuffix("/api/v1") + parsed.path
