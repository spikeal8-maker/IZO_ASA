"""Direct contracts for trusted proxy metadata resolution."""

from __future__ import annotations

from types import SimpleNamespace

from app.security.proxy_headers import resolve_client_ip, resolve_country_code


def _request(headers: dict[str, str], host: str | None):
    client = SimpleNamespace(host=host) if host is not None else None
    return SimpleNamespace(headers=headers, client=client)


def test_proxy_headers_are_ignored_from_non_loopback_peer() -> None:
    request = _request(
        {
            "cf-connecting-ip": "8.8.8.8",
            "x-forwarded-for": "9.9.9.9, 127.0.0.1",
            "cf-ipcountry": "US",
        },
        "203.0.113.10",
    )

    assert resolve_client_ip(request, trust_cloudflare=True, trust_forwarded=True) == "203.0.113.10"
    assert resolve_country_code(request, trust_cloudflare=True) is None


def test_cloudflare_metadata_is_accepted_from_ipv4_loopback_peer() -> None:
    request = _request(
        {"cf-connecting-ip": "8.8.8.8", "cf-ipcountry": "ru"},
        "127.0.0.1",
    )

    assert resolve_client_ip(request, trust_cloudflare=True, trust_forwarded=False) == "8.8.8.8"
    assert resolve_country_code(request, trust_cloudflare=True) == "RU"


def test_forwarded_ip_is_accepted_from_ipv6_loopback_peer() -> None:
    request = _request(
        {"x-forwarded-for": "2001:4860:4860::8888, 127.0.0.1"},
        "::1",
    )

    assert resolve_client_ip(request, trust_cloudflare=False, trust_forwarded=True) == "2001:4860:4860::8888"


def test_invalid_forwarded_metadata_falls_back_to_direct_peer() -> None:
    request = _request(
        {
            "cf-connecting-ip": "not-an-ip",
            "x-forwarded-for": "also-not-an-ip, 127.0.0.1",
            "cf-ipcountry": "RUS",
        },
        "127.0.0.1",
    )

    assert resolve_client_ip(request, trust_cloudflare=True, trust_forwarded=True) == "127.0.0.1"
    assert resolve_country_code(request, trust_cloudflare=True) is None


def test_proxy_metadata_requires_explicit_trust_flags() -> None:
    request = _request(
        {"cf-connecting-ip": "8.8.8.8", "x-forwarded-for": "9.9.9.9", "cf-ipcountry": "DE"},
        "127.0.0.1",
    )

    assert resolve_client_ip(request, trust_cloudflare=False, trust_forwarded=False) == "127.0.0.1"
    assert resolve_country_code(request, trust_cloudflare=False) is None
