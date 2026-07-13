"""Resolve analytics proxy metadata without trusting arbitrary socket peers."""

from __future__ import annotations

import ipaddress
import re
from typing import Any


def _direct_client_host(request: Any | None) -> str | None:
    if request is None:
        return None
    client = getattr(request, "client", None)
    host = getattr(client, "host", None)
    return str(host).strip() if host else None


def _is_loopback_peer(host: str | None) -> bool:
    if not host:
        return False
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _valid_ip(value: str | None) -> str | None:
    candidate = (value or "").strip()
    if not candidate:
        return None
    try:
        return ipaddress.ip_address(candidate).compressed
    except ValueError:
        return None


def resolve_client_ip(
    request: Any | None,
    *,
    trust_cloudflare: bool,
    trust_forwarded: bool,
) -> str | None:
    """Return a validated client IP while trusting headers only from loopback.

    Uvicorn must run with ``--no-proxy-headers`` so ``request.client.host`` stays
    the actual socket peer. The public frontend proxy and the planned local Caddy
    instance both connect over loopback.
    """

    direct_host = _direct_client_host(request)
    if request is None or not _is_loopback_peer(direct_host):
        return direct_host

    if trust_cloudflare:
        cloudflare_ip = _valid_ip(request.headers.get("cf-connecting-ip"))
        if cloudflare_ip:
            return cloudflare_ip

    if trust_forwarded:
        forwarded = request.headers.get("x-forwarded-for")
        forwarded_ip = _valid_ip(forwarded.split(",", 1)[0] if forwarded else None)
        if forwarded_ip:
            return forwarded_ip

    return direct_host


def resolve_country_code(request: Any | None, *, trust_cloudflare: bool) -> str | None:
    """Return a coarse CF country code only from an explicitly trusted local proxy."""

    direct_host = _direct_client_host(request)
    if request is None or not trust_cloudflare or not _is_loopback_peer(direct_host):
        return None
    code = (request.headers.get("cf-ipcountry") or "").strip().upper()
    if code == "XX":
        return None
    return code if re.fullmatch(r"[A-Z]{2}", code) else None
