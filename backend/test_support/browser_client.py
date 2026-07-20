"""Test-only helper: a TestClient that models a browser sending Origin headers.

AUTH-LEGACY-001B. In production every modern browser attaches an ``Origin``
header to cross-site unsafe requests.  FastAPI's ``TestClient`` does *not*
model this – it omits ``Origin`` entirely.  ``BrowserTestClient`` fills that
gap **without touching production code**: it wraps ``TestClient`` and
automatically adds the allowlisted production Origin to cookie-authenticated
POST/PUT/PATCH/DELETE calls.

Explicit design decisions:

- Origin is added ONLY for POST / PUT / PATCH / DELETE.
- Origin is added ONLY when the request carries at least one of the three
  sensitive cookies: ``onenode_session``, ``onenode_refresh``,
  ``onenode_bot_login``.
- An Origin that is **already** present in the passed ``headers`` dict is
  **never** overwritten – negative-CSRF tests that want a foreign / null /
  missing Origin simply pass their own value (or use raw ``TestClient``).
- GET / HEAD / OPTIONS never get an Origin.
- Anonymous / bearer-only / webhook requests (no sensitive cookie) never get
  an Origin.
- No global monkeypatch, no environment variable, no production-code change.
"""
from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from httpx import URL, Cookies, Headers

BROWSER_ORIGIN = "https://izo.alikinas.ru"

_SENSITIVE_COOKIE_NAMES: frozenset[str] = frozenset(
    {"onenode_session", "onenode_refresh", "onenode_bot_login"}
)

_UNSAFE_METHODS: frozenset[str] = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def _has_sensitive_cookie(
    cookies: dict[str, str] | Cookies | None,
    client_cookies: Cookies | None,
) -> bool:
    """Return True when *any* sensitive cookie name appears in the request."""
    # httpx stores cookies in a Cookies jar; the TestClient also keeps a
    # persistent jar on the instance.  We inspect both the per-request dict
    # AND the client-level jar so that .cookies.set(...) on the instance
    # is seen as having a sensitive cookie.
    checked: set[str] = set()

    if isinstance(cookies, Cookies):
        checked.update(name for name in _SENSITIVE_COOKIE_NAMES if name in cookies)
    elif isinstance(cookies, dict):
        checked.update(name for name in _SENSITIVE_COOKIE_NAMES if name in cookies)

    if not checked and client_cookies is not None:
        checked.update(
            name for name in _SENSITIVE_COOKIE_NAMES if name in client_cookies
        )

    return bool(checked)


def _origin_from_headers(headers: dict[str, str] | Headers | None) -> str | None:
    """Extract an already-present Origin from headers if any."""
    if headers is None:
        return None
    if isinstance(headers, Headers):
        return headers.get("origin") or headers.get("Origin")
    # Case-insensitive lookup for plain dicts.
    for key, value in headers.items():
        if isinstance(key, str) and key.lower() == "origin":
            return str(value)
    return None


class BrowserTestClient(TestClient):
    """A ``TestClient`` that automatically adds the production Origin header
    to cookie-authenticated unsafe requests, modelling real browser behaviour.

    Usage (identical to ``TestClient``)::

        with BrowserTestClient(app) as client:
            client.cookies.set("onenode_session", token)
            resp = client.post("/api/protected", json={})
            # Origin is added automatically.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)

    def _inject_origin(
        self,
        method: str,
        headers: dict[str, str] | Headers | None,
        cookies: dict[str, str] | Cookies | None,
    ) -> dict[str, str] | Headers | None:
        if method.upper() not in _UNSAFE_METHODS:
            return headers
        if _origin_from_headers(headers) is not None:
            return headers
        if not _has_sensitive_cookie(cookies, self.cookies):
            return headers
        if headers is None:
            return {"Origin": BROWSER_ORIGIN}
        if isinstance(headers, Headers):
            headers["Origin"] = BROWSER_ORIGIN
            return headers
        return {**headers, "Origin": BROWSER_ORIGIN}

    # ------------------------------------------------------------------
    # Override the per-method shortcuts AND the underlying request() so
    # that both calling styles get Origin injection.
    # ------------------------------------------------------------------

    def request(  # type: ignore[override]
        self,
        method: str,
        url: str | URL,
        *,
        headers: dict[str, str] | Headers | None = None,
        cookies: dict[str, str] | Cookies | None = None,
        **kwargs: Any,
    ) -> Any:
        headers = self._inject_origin(method, headers, cookies)
        return super().request(
            method, url, headers=headers, cookies=cookies, **kwargs
        )

    # Convenience overrides – they all delegate to self.request() internally,
    # but we override them explicitly so that subclasses / IDE autocompletion
    # see the exact signatures.

    def post(  # type: ignore[override]
        self,
        url: str | URL,
        *,
        headers: dict[str, str] | Headers | None = None,
        cookies: dict[str, str] | Cookies | None = None,
        **kwargs: Any,
    ) -> Any:
        return self.request("POST", url, headers=headers, cookies=cookies, **kwargs)

    def put(  # type: ignore[override]
        self,
        url: str | URL,
        *,
        headers: dict[str, str] | Headers | None = None,
        cookies: dict[str, str] | Cookies | None = None,
        **kwargs: Any,
    ) -> Any:
        return self.request("PUT", url, headers=headers, cookies=cookies, **kwargs)

    def patch(  # type: ignore[override]
        self,
        url: str | URL,
        *,
        headers: dict[str, str] | Headers | None = None,
        cookies: dict[str, str] | Cookies | None = None,
        **kwargs: Any,
    ) -> Any:
        return self.request("PATCH", url, headers=headers, cookies=cookies, **kwargs)

    def delete(  # type: ignore[override]
        self,
        url: str | URL,
        *,
        headers: dict[str, str] | Headers | None = None,
        cookies: dict[str, str] | Cookies | None = None,
        **kwargs: Any,
    ) -> Any:
        return self.request("DELETE", url, headers=headers, cookies=cookies, **kwargs)
