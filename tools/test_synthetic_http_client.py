"""Bounded transport regressions using synthetic responses and owned loopback HTTP."""
from __future__ import annotations

import io
import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

from tools import synthetic_http_client as transport


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def _reply(self, status, value, **headers):
        body = json.dumps(value).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for key, value in headers.items():
            self.send_header(key.replace("_", "-"), value)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass  # A refused redirect closes its response without reading it.

    def do_GET(self):
        self.server.requests.append(self.path)
        if self.path == "/session":
            self._reply(200, {"ok": True}, Set_Cookie="session=synthetic; Path=/; HttpOnly")
        elif self.path == "/cookie":
            self._reply(200, {"cookie": self.headers.get("Cookie", "")})
        elif self.path == "/redirect":
            self._reply(302, {}, Location="/redirect-target")
        elif self.path == "/json":
            self._reply(200, {"ok": True})
        else:
            self._reply(404, {"unexpectedPath": True})

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        self._reply(200, {"payload": json.loads(body), "origin": self.headers.get("Origin"),
                          "contentType": self.headers.get("Content-Type")})


class LoopbackTransportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), _Handler)
        cls.server.requests = []
        cls.addClassCleanup(cls.server.server_close)
        cls.thread = threading.Thread(target=cls.server.serve_forever,
                                      kwargs={"poll_interval": 0.01}, daemon=True)
        cls.thread.start()
        cls.addClassCleanup(cls._stop_server)
        cls.origin = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def _stop_server(cls):
        cls.server.shutdown()
        cls.thread.join(timeout=2)
        if cls.thread.is_alive():
            raise AssertionError("Synthetic loopback server thread did not stop")

    def test_cookie_session_is_kept_between_requests(self):
        client = transport.HttpClient(self.origin)
        self.assertEqual(client.request("GET", "/session"), {"ok": True})
        self.assertEqual(client.request("GET", "/cookie"), {"cookie": "session=synthetic"})

    def test_post_serializes_payload_and_sends_origin(self):
        client = transport.HttpClient(self.origin)
        payload = {"message": "synthetic", "count": 2}
        self.assertEqual(client.request("POST", "/echo", payload),
                         {"payload": payload, "origin": self.origin,
                          "contentType": "application/json"})

    def test_ambient_proxy_is_not_used(self):
        # A proxy request would send an absolute URI and receive our handler's 404.
        # Even that failure path stays on this owned loopback listener.
        environment = {key: self.origin for key in
                       ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")}
        environment.update(no_proxy="", NO_PROXY="")
        with patch.dict(os.environ, environment):
            client = transport.HttpClient(self.origin)
            self.assertEqual(client.request("GET", "/json"), {"ok": True})

    def test_redirect_is_refused_without_visiting_target(self):
        client = transport.HttpClient(self.origin)
        before = len(self.server.requests)
        with self.assertRaisesRegex(transport.ProductError, "^PRODUCT_REDIRECT_FORBIDDEN$"):
            client.request("GET", "/redirect")
        self.assertEqual(self.server.requests[before:], ["/redirect"])


class _Response:
    def __init__(self, content, status=200):
        self.content, self.status = content, status
        self.limits = []
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def read(self, limit):
        self.limits.append(limit)
        return self.content[:limit]


def _fake_response(content, status=200):
    client = transport.HttpClient("http://127.0.0.1:1")
    response = _Response(content, status)
    client.opener = Mock()
    client.opener.open.return_value = response
    return client, response


class TransportRefusalTests(unittest.TestCase):
    def test_cross_origin_or_fragment_paths_fail_before_io(self):
        client = transport.HttpClient("http://127.0.0.1:1")
        client.opener = Mock()
        for path in ("", "relative", "http://127.0.0.1:2/", "https://127.0.0.1:2/",
                     "//127.0.0.1:2/", "/api#fragment"):
            with self.subTest(path=path):
                with self.assertRaisesRegex(transport.ProductError, "^PRODUCT_CROSS_ORIGIN_PATH$"):
                    client.request("GET", path)
        client.opener.open.assert_not_called()

    def test_timeout_read_bound_and_response_close_are_preserved(self):
        client, response = _fake_response(b'{"ok": true}')
        self.assertEqual(client.request("GET", "/api"), {"ok": True})
        self.assertEqual(client.opener.open.call_args.kwargs, {"timeout": 8})
        self.assertEqual(response.limits, [20_000_001])
        self.assertTrue(response.closed)

    def test_response_at_limit_is_accepted_in_binary_mode(self):
        body = b"x" * 20_000_000
        client, response = _fake_response(body)
        self.assertEqual(client.request("GET", "/media", binary=True), body)
        self.assertEqual(response.limits, [20_000_001])

    def test_oversized_response_is_rejected_in_binary_mode(self):
        client, response = _fake_response(b"x" * 20_000_001)
        with self.assertRaisesRegex(transport.ProductError, "^PRODUCT_RESPONSE_TOO_LARGE$"):
            client.request("GET", "/media", binary=True)
        self.assertTrue(response.closed)

    def test_non_object_or_invalid_json_is_refused(self):
        for body in (b"[]", b"null", b"true", b"1", b'"text"', b"invalid json", b"\xff"):
            with self.subTest(body=body):
                client, response = _fake_response(body)
                with self.assertRaisesRegex(transport.ProductError, "^PRODUCT_RESPONSE_INVALID$"):
                    client.request("GET", "/api")
                self.assertTrue(response.closed)

    def test_http_errors_close_without_reading_or_disclosing_body(self):
        class PrivateBody(io.BytesIO):
            def read(self, *args):
                raise AssertionError("HTTP error body must not be read")

        for expected in ((403,), (200,)):
            with self.subTest(expected=expected):
                body = PrivateBody(b"synthetic-private-error-body")
                error = HTTPError("http://127.0.0.1:1/private", 403,
                                  "synthetic-private-error-reason", {}, body)
                client, _ = _fake_response(b"")
                client.opener.open.side_effect = error
                if expected == (403,):
                    self.assertEqual(client.request("GET", "/api", expected=expected), {"httpStatus": 403})
                else:
                    with self.assertRaisesRegex(transport.ProductError, "^PRODUCT_HTTP_STATUS_UNEXPECTED_403$"):
                        client.request("GET", "/api", expected=expected)
                self.assertTrue(body.closed)

    def test_network_errors_return_only_a_fixed_diagnostic(self):
        for error in (OSError("synthetic-private-os"), URLError("synthetic-private-url"),
                      TimeoutError("synthetic-private-timeout")):
            with self.subTest(error=type(error).__name__):
                client, _ = _fake_response(b"")
                client.opener.open.side_effect = error
                with self.assertRaisesRegex(transport.ProductError, "^PRODUCT_HTTP_UNAVAILABLE$") as caught:
                    client.request("GET", "/api")
                self.assertTrue(caught.exception.__suppress_context__)

    def test_object_ids_accept_only_bounded_ascii_path_components(self):
        for value in ("job-123_ABC", "a" * 120):
            self.assertEqual(transport.path_id(value), value)
        for value in (None, 12, "", "a" * 121, "../item", "a/b", "a?b", "a#b", "a b", "\u044f"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(transport.ProductError, "^PRODUCT_OBJECT_ID_INVALID$"):
                    transport.path_id(value)

    def test_require_preserves_fixed_code_contract(self):
        transport.require(True, "SYNTHETIC_REQUIRED")
        with self.assertRaisesRegex(transport.ProductError, "^SYNTHETIC_REQUIRED$"):
            transport.require(False, "SYNTHETIC_REQUIRED")


if __name__ == "__main__":
    unittest.main()
