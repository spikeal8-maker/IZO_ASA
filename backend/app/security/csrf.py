"""CSRF origin boundary for cookie-authenticated state changes.

AUTH-LEGACY-001B. The trusted cookies use ``SameSite=None`` in production, so
a browser attaches them to cross-site requests. This pure ASGI middleware
rejects unsafe-method requests that carry a sensitive cookie unless the
request presents an Origin that EXACTLY matches the configured allowlist.

Deliberate boundaries:

- Safe methods (GET/HEAD/OPTIONS/TRACE) are never blocked here.
- Requests without any sensitive cookie are not CSRF-able through ambient
  credentials; they pass through and keep their existing 401/400/403 route
  behavior (webhooks, CLI clients, anonymous traffic).
- Explicit ``Authorization: Bearer`` transport cannot be attached by a
  foreign page, so bearer-only requests are not CSRF-able — they carry no
  sensitive cookie and pass through above. Presence of an Authorization
  header does NOT disable the check when the browser also auto-attaches a
  sensitive cookie: the ambient credential is what CSRF abuses, so such
  requests still require an allowlisted Origin.
- For cookie-authenticated unsafe requests the Origin header is REQUIRED:
  a missing Origin, ``null``, a different scheme/port, userinfo tricks or a
  malicious suffix domain all fail the exact-match comparison and get 403.

The middleware never touches the database or providers, never echoes the
received Origin back, and never logs cookies, tokens or the full Origin.
"""
from __future__ import annotations

from collections.abc import Iterable

from starlette.types import ASGIApp, Receive, Scope, Send

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})
REJECTION_BODY = b'{"detail":"Cross-site request blocked."}'


def _cookie_names(cookie_header: str) -> set[str]:
    names: set[str] = set()
    for part in cookie_header.split(";"):
        name, separator, _value = part.strip().partition("=")
        if separator and name:
            names.add(name)
    return names


class CsrfOriginMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        allowed_origins: Iterable[str],
        sensitive_cookie_names: Iterable[str],
    ) -> None:
        self.app = app
        # Allowlist entries are clean origins from HttpSecurityPolicy; a
        # defensive rstrip keeps an accidental trailing slash in config from
        # silently disabling an origin. The REQUEST origin is never rewritten.
        self.allowed_origins = frozenset(
            origin.rstrip("/") for origin in allowed_origins if origin and origin != "null"
        )
        self.sensitive_cookie_names = frozenset(
            name for name in sensitive_cookie_names if name
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method", "").upper() in SAFE_METHODS:
            await self.app(scope, receive, send)
            return
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        cookie_header = headers.get(b"cookie", b"").decode("latin-1")
        if not (self.sensitive_cookie_names & _cookie_names(cookie_header)):
            await self.app(scope, receive, send)
            return
        origin = headers.get(b"origin", b"").decode("latin-1")
        if origin and origin != "null" and origin in self.allowed_origins:
            await self.app(scope, receive, send)
            return
        await self._send_rejection(send)

    @staticmethod
    async def _send_rejection(send: Send) -> None:
        await send({
            "type": "http.response.start",
            "status": 403,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(REJECTION_BODY)).encode()),
            ],
        })
        await send({"type": "http.response.body", "body": REJECTION_BODY})
