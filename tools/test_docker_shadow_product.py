"""HTTP contract fixtures only: these tests never claim a Docker runtime PASS."""
from __future__ import annotations

import copy
import base64
import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import pytest

from tools import docker_shadow_product as product

SHA = "a" * 40
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aV6kAAAAASUVORK5CYII=")


def attestation(origin="http://127.0.0.1:48125"):
    return {"origin": origin, "sourceSha": SHA, "project": "izo-asa-shadow-contract",
            "isolatedData": True, "fakeProviderOnly": True,
            "networkEgressDenied": True, "externalEffectsDisabled": True}


@pytest.mark.parametrize("origin", ["https://izo.alikinas.ru", "http://127.0.0.1:8000",
    "http://127.0.0.1:48125@evil.example", "http://localhost:48125/path",
    "http://localhost:48125/?token=secret", "http://[::1]:48125", "file:///tmp/test",
    "http://localhost:invalid", "http://localhost:48125#fragment", "http://user:secret@localhost:48125"])
def test_target_rejects_production_external_credentials_and_non_origin_urls(origin):
    with pytest.raises(product.ProductError, match="PRODUCT_TARGET_INVALID"):
        product.ProductFlow(attestation(origin))


@pytest.mark.parametrize("key,value", [("isolatedData", False), ("fakeProviderOnly", "true"),
    ("networkEgressDenied", None), ("externalEffectsDisabled", False),
    ("sourceSha", "main"), ("project", "asa-lab-dev")])
def test_unattested_target_fails_before_client_creation(monkeypatch, key, value):
    data = attestation()
    data[key] = value
    monkeypatch.setattr(product, "HttpClient", lambda *_: pytest.fail("HTTP client created before target guard"))
    with pytest.raises(product.ProductError):
        product.ProductFlow(data)


@pytest.fixture
def http_fixture():
    state = {"users": {}, "jobs": {}, "images": {}, "publications": {}, "requests": [],
             "duplicateCharge": False, "exposePrivateMedia": False, "signupFault": None,
             "logoutFails": False}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def respond(self, status=200, body=None, *, raw=None, cookie=None):
            self.send_response(status)
            if cookie is not None:
                self.send_header("Set-Cookie", f"fixture_session={cookie}; Path=/; HttpOnly")
            self.end_headers()
            self.wfile.write(raw if raw is not None else json.dumps(body or {}).encode())

        def handle_request(self):
            path = urlsplit(self.path).path
            state["requests"].append((self.command, path))
            cookie = self.headers.get("Cookie", "").removeprefix("fixture_session=")
            user = state["users"].get(cookie)
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
            if path == "/redirect":
                self.send_response(302)
                self.send_header("Location", "http://127.0.0.1:1/forbidden")
                self.end_headers()
            elif path == "/invalid-json":
                self.respond(raw=b"sensitive invalid body /private/secret")
            elif path == "/":
                self.respond(raw=f'<meta name="izo-build" content="{SHA}">'.encode())
            elif path.endswith("register-v2"):
                identifier = f"user{len(state['users']) + 1}"
                state["users"][identifier] = {"legacy_user_id": identifier, "email": body["email"],
                    "password": body["password"], "spent": 0, "ledger": [], "daily": 0}
                if state["signupFault"] == "invalid-json":
                    self.respond(raw=b"private invalid json", cookie=identifier)
                    return
                if state["signupFault"] == "unexpected-status":
                    self.respond(503, cookie=identifier)
                    return
                self.respond(body={"ok": True, "requires_email_verification": False,
                                  "legacy_user_id": identifier}, cookie=identifier)
            elif path.endswith("login-v2"):
                found = next((key for key, value in state["users"].items()
                    if value["email"] == body["email"] and value["password"] == body["password"]), None)
                self.respond(200 if found else 401, {"ok": bool(found)}, cookie=found)
            elif path.endswith("logout-v2"):
                if state["logoutFails"]:
                    self.respond(503)
                else:
                    self.respond(body={"ok": True}, cookie="")
            elif path == "/api/me-v2":
                self.respond(200 if user else 401, {"legacy_user_id": cookie,
                    "account": {"token_balance": 50, "daily_tokens_used": user["daily"]}} if user else {})
            elif path == "/api/account/token-history-v2":
                self.respond(body={"summary": {"spentTokens": user["spent"], "refundedTokens": 0},
                                   "items": copy.deepcopy(user["ledger"])})
            elif path == "/api/generate":
                identifier = f"job_fixture_{len(state['jobs']) + 1}"
                image_id = f"image{len(state['images']) + 1}"
                url = "/api/media/" + image_id
                state["images"][image_id] = {"id": image_id, "url": url,
                    "isFavorite": False, "owner": cookie, "mode": body["mode"]}
                state["jobs"][identifier] = {"id": identifier, "status": "completed", "owner": cookie,
                    "resultImageId": image_id, "resultUrl": url}
                user["daily"] += 4
                user["spent"] += 4
                user["ledger"].append({"id": identifier, "spentTokens": 4, "jobId": identifier[:10] + "…"})
                if state["duplicateCharge"]:
                    user["ledger"].append({"id": identifier + "-duplicate", "spentTokens": 4,
                                           "jobId": identifier[:10] + "…"})
                self.respond(body={"id": identifier, "status": "queued", "queuePosition": 1,
                                   "tokenCost": 4, "tokenBalance": 50, "dailyTokensUsed": user["daily"]})
            elif path.startswith("/api/jobs/"):
                job = state["jobs"][path.rsplit("/", 1)[1]]
                self.respond(200 if job["owner"] == cookie else 404, job)
            elif path.startswith("/api/gallery/"):
                parts = path.split("/")
                image = state["images"][parts[3]]
                if image["owner"] != cookie:
                    self.respond(404)
                elif parts[-1] == "favorite":
                    image["isFavorite"] = body["isFavorite"]
                    self.respond(body=image)
                elif parts[-1] == "use-as":
                    self.respond(body={"ok": True, "inputImage": image["url"]})
                else:
                    self.respond(body=image)
            elif path.startswith("/api/media/"):
                image = state["images"][path.rsplit("/", 1)[1]]
                self.respond(200 if image["owner"] == cookie or state["exposePrivateMedia"] else 404,
                             raw=PNG)
            elif path == "/api/feed/publications":
                image = state["images"][body["imageId"]]
                if image["owner"] != cookie:
                    self.respond(404)
                    return
                identifier = f"publication{len(state['publications']) + 1}"
                moderation = "approved" if image["mode"] == "text_to_image" else "pending_review"
                publication = {"id": identifier, "moderation": moderation}
                state["publications"][identifier] = publication
                self.respond(body={"moderation": moderation, "publication": publication})
            elif path == "/api/feed":
                self.respond(body={"items": [item for item in state["publications"].values()
                                           if item["moderation"] == "approved"]})
            elif path.startswith("/api/feed/media/"):
                publication = state["publications"][path.rsplit("/", 1)[1]]
                self.respond(200 if publication["moderation"] == "approved" else 404,
                             raw=PNG)
            else:
                self.respond(404)

        do_GET = handle_request
        do_POST = handle_request

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    try:
        yield origin, state
    finally:
        port = server.server_port
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        assert not thread.is_alive()
        with socket.socket() as probe:
            assert probe.connect_ex(("127.0.0.1", port)) != 0


def test_full_http_contract_and_repeat_persistence_observation(http_fixture):
    origin, state = http_fixture
    flow = product.ProductFlow(attestation(origin))
    try:
        checks = flow.run()
        assert checks["auth"] == checks["publicationModeration"] == "PASS"
        assert len(checks["generation"]) == 2
        assert flow.verify_persistence()["status"] == "PASS"
        assert flow.verify_persistence()["status"] == "PASS"
        # No Docker recreate occurs in this contract fixture.
        assert len(state["users"]) == 2
        assert flow.credentials == []
        assert ("POST", "/api/auth/password/login-v2") in state["requests"]
        assert not any("admin" in path for _, path in state["requests"])
    finally:
        assert flow.close()["sessionCleanup"] == "PASS"


@pytest.mark.parametrize("failure,code", [("duplicateCharge", "PRODUCT_LEDGER_CHARGE_MISMATCH"),
    ("exposePrivateMedia", "PRODUCT_HTTP_STATUS_UNEXPECTED")])
def test_financial_duplication_and_private_media_exposure_are_not_pass(http_fixture, failure, code):
    origin, state = http_fixture
    state[failure] = True
    flow = product.ProductFlow(attestation(origin))
    try:
        with pytest.raises(product.ProductError, match=code):
            flow.run()
    finally:
        assert flow.close()["sessionCleanup"] == "PASS"


def test_network_redirect_and_sensitive_response_errors_are_redacted(http_fixture):
    origin, _ = http_fixture
    client = product.HttpClient(origin)
    with pytest.raises(product.ProductError, match="^PRODUCT_REDIRECT_FORBIDDEN$"):
        client.request("GET", "/redirect")
    with pytest.raises(product.ProductError, match="^PRODUCT_RESPONSE_INVALID$"):
        client.request("GET", "/invalid-json")
    for path in ("http://example.com/secret", "//example.com/secret", "/api/me-v2#fragment"):
        with pytest.raises(product.ProductError, match="PRODUCT_CROSS_ORIGIN_PATH"):
            client.request("GET", path)


def test_cli_receipt_contains_only_selected_observations(http_fixture, tmp_path, monkeypatch):
    origin, state = http_fixture
    input_path, receipt = tmp_path / "attestation.json", tmp_path / "receipt.json"
    input_path.write_text(json.dumps(attestation(origin)))
    monkeypatch.setattr("sys.argv", ["docker_shadow_product", "--attestation", str(input_path),
                                    "--receipt", str(receipt)])
    assert product.main() == 0
    raw = receipt.read_text()
    data = json.loads(raw)
    assert data["status"] == "HTTP_SCENARIOS_PASS"
    assert data["dockerAcceptance"] == "NOT_VERIFIED_BY_THIS_TOOL"
    assert data["cleanup"]["sessionCleanup"] == "PASS"
    for user in state["users"].values():
        assert user["email"] not in raw and user["password"] not in raw
    assert "fixture_session" not in raw and str(input_path) not in raw


def test_invalid_attestation_cli_emits_no_input_content(tmp_path, monkeypatch):
    input_path, receipt = tmp_path / "input.json", tmp_path / "receipt.json"
    input_path.write_text(json.dumps(attestation("http://secret-user:secret-pass@localhost:48125")))
    monkeypatch.setattr("sys.argv", ["tool", "--attestation", str(input_path), "--receipt", str(receipt)])
    assert product.main() == 1
    raw = receipt.read_text()
    assert "secret-user" not in raw and "secret-pass" not in raw
    assert json.loads(raw)["errorCode"] == "PRODUCT_TARGET_INVALID"


def test_provider_override_is_rejected_before_any_http(http_fixture, monkeypatch):
    origin, state = http_fixture
    flow = product.ProductFlow(attestation(origin))
    with pytest.raises(product.ProductError, match="PRODUCT_PROVIDER_OR_MODE_FORBIDDEN"):
        flow.generate({"provider": "openrouter", "mode": "text_to_image"})
    assert state["requests"] == []


def test_session_cleanup_failure_prevents_cli_success(http_fixture, tmp_path, monkeypatch):
    origin, _ = http_fixture
    input_path, receipt = tmp_path / "input.json", tmp_path / "receipt.json"
    input_path.write_text(json.dumps(attestation(origin)))
    monkeypatch.setattr("sys.argv", ["tool", "--attestation", str(input_path), "--receipt", str(receipt)])
    original = product.ProductFlow.close

    def cleanup_failure(flow):
        result = original(flow)
        return {**result, "sessionCleanup": "FAIL", "failedSessions": 1}

    monkeypatch.setattr(product.ProductFlow, "close", cleanup_failure)
    assert product.main() == 1
    data = json.loads(receipt.read_text())
    assert data["status"] == "FAIL"
    assert data["cleanup"]["sessionCleanup"] == "FAIL"


@pytest.mark.parametrize("fault,code", [("invalid-json", "PRODUCT_RESPONSE_INVALID"),
    ("unexpected-status", "PRODUCT_HTTP_STATUS_UNEXPECTED")])
def test_failed_signup_with_issued_cookie_is_revoked_and_all_jars_checked(http_fixture, fault, code):
    origin, state = http_fixture
    state["signupFault"] = fault
    flow = product.ProductFlow(attestation(origin))
    with pytest.raises(product.ProductError, match=code):
        flow.register(flow.owner, 1)
    assert len(list(flow.owner.cookies)) == 1
    assert flow.credentials == []
    cleanup = flow.close()
    assert cleanup["sessionCleanup"] == "PASS"
    assert cleanup["checkedClients"] == 3 and cleanup["remainingCookieJars"] == 0
    assert state["requests"].count(("POST", "/api/auth/session/logout-v2")) == 3
    assert state["requests"].count(("GET", "/api/me-v2")) == 3


def test_failed_revocation_clears_local_cookies_but_never_reports_cleanup_pass(http_fixture):
    origin, state = http_fixture
    flow = product.ProductFlow(attestation(origin))
    flow.register(flow.owner, 1)
    state["logoutFails"] = True
    cleanup = flow.close()
    assert cleanup["sessionCleanup"] == "FAIL" and cleanup["failedSessions"] == 3
    assert cleanup["remainingCookieJars"] == 0 and flow.credentials == []
    assert state["requests"].count(("GET", "/api/me-v2")) == 4
