"""Bounded stdlib HTTP transport for isolated synthetic acceptance.

Extracted from tools/docker_shadow_product.py at
f51c316176bf2609ccb9271c00a358a7b1f02768. Callers validate and attest the origin.
"""
from __future__ import annotations

import http.cookiejar
import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPCookieProcessor, ProxyHandler, Request, build_opener


class ProductError(RuntimeError):
    """Only fixed, secret-free diagnostic codes may cross the receipt boundary."""


def require(condition: bool, code: str) -> None:
    if not condition:
        raise ProductError(code)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ProductError("PRODUCT_REDIRECT_FORBIDDEN")


class HttpClient:
    def __init__(self, origin: str):
        self.origin = origin
        self.cookies = http.cookiejar.CookieJar()
        self.opener = build_opener(ProxyHandler({}), NoRedirect(), HTTPCookieProcessor(self.cookies))

    def request(self, method: str, path: str, payload: dict | None = None,
                *, expected: tuple[int, ...] = (200,), binary: bool = False):
        parsed = urlsplit(path)
        require(path.startswith("/") and not path.startswith("//") and not parsed.scheme
                and not parsed.netloc and not parsed.fragment, "PRODUCT_CROSS_ORIGIN_PATH")
        headers = {"Origin": self.origin, "Accept": "application/json"}
        data = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(payload).encode("utf-8")
        request = Request(self.origin + path, data=data, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=8) as response:
                status, content = response.status, response.read(20_000_001)
        except HTTPError as error:
            status = error.code
            content = b""  # Error bodies can contain paths or personal information.
            error.close()
        except (OSError, URLError, TimeoutError):
            raise ProductError("PRODUCT_HTTP_UNAVAILABLE") from None
        require(status in expected, f"PRODUCT_HTTP_STATUS_UNEXPECTED_{status}")
        require(len(content) <= 20_000_000, "PRODUCT_RESPONSE_TOO_LARGE")
        if status != 200:
            return {"httpStatus": status}
        if binary:
            return content
        try:
            value = json.loads(content)
        except (ValueError, UnicodeError):
            raise ProductError("PRODUCT_RESPONSE_INVALID") from None
        require(isinstance(value, dict), "PRODUCT_RESPONSE_INVALID")
        return value


def path_id(value) -> str:
    require(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,120}", value) is not None,
            "PRODUCT_OBJECT_ID_INVALID")
    return value
