"""Browser-faithful TestClient for cookie-auth CSRF flows (AUTH-LEGACY-001B).

Some flows log in, receive a Set-Cookie, and then the SAME browser issues an
unsafe request. A raw ``TestClient`` over http cannot hold a Secure cookie and
never sends the Origin a browser would, so those tests do not exercise the
production browser path. ``BrowserTestClient`` models it:

- ``base_url`` is https so a Secure session cookie is actually stored;
- for unsafe methods, when a sensitive cookie is already in the jar and the
  caller did not set an Origin, it attaches the allowlisted browser Origin;
- a caller-supplied Origin (e.g. a foreign one in a negative test) is never
  replaced.

The behavior is independent of the local ``TRUSTED_COOKIE_SECURE`` setting:
whether the login cookie is Secure or not, it is stored over the https base
URL and the Origin is added, so the test does not depend on a gitignored
``.env``.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

import main

ALLOWLISTED_BROWSER_ORIGIN = "https://izo.alikinas.ru"
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def sensitive_cookie_names() -> set[str]:
    return {
        main.TRUSTED_SESSION_COOKIE_NAME,
        main.TRUSTED_REFRESH_COOKIE_NAME,
        main.BOT_LOGIN_CHALLENGE_COOKIE_NAME,
    }


class BrowserTestClient(TestClient):
    def __init__(self, app, *, base_url: str = "https://testserver", **kwargs) -> None:
        super().__init__(app, base_url=base_url, **kwargs)

    def _carries_sensitive_cookie(self) -> bool:
        jar_names = {cookie.name for cookie in self.cookies.jar}
        return bool(jar_names & sensitive_cookie_names())

    def request(self, method, url, **kwargs):  # type: ignore[override]
        if str(method).upper() in UNSAFE_METHODS and self._carries_sensitive_cookie():
            headers = dict(kwargs.get("headers") or {})
            if not any(str(key).lower() == "origin" for key in headers):
                headers["Origin"] = ALLOWLISTED_BROWSER_ORIGIN
                kwargs["headers"] = headers
        return super().request(method, url, **kwargs)
