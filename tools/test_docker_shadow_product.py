"""HTTP contract fixtures only: these tests never claim a Docker runtime PASS."""
from __future__ import annotations

import base64
import copy
import json
import socket
import tempfile
import threading
import unittest
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

from tools import docker_shadow_product as product

SHA = "a" * 40
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aV6kAAAAASUVORK5CYII=")


def attestation(origin="http://127.0.0.1:48125"):
    return {"origin": origin, "sourceSha": SHA, "project": "izo-asa-shadow-contract",
            "isolatedData": True, "fakeProviderOnly": True,
            "networkEgressDenied": True, "externalEffectsDisabled": True}


@contextmanager
def http_fixture():
    state = {"users": {}, "jobs": {}, "images": {}, "publications": {}, "media": {}, "requests": [],
             "duplicateCharge": False, "exposePrivateMedia": False, "signupFault": None,
             "logoutFails": False, "leakPending": False}

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
            elif path == "/unexpected-status":
                self.respond(503, raw=b"password=private-response-body")
            elif path == "/":
                self.respond(raw=f'<meta name="izo-build" content="{SHA}">'.encode())
            elif path.endswith("register-v2"):
                identifier = f"user{len(state['users']) + 1}"
                state["users"][identifier] = {"legacy_user_id": identifier, "email": body["email"],
                    "internal_user_id": "internal_" + identifier, "session_id": "registration_" + identifier,
                    "password": body["password"], "spent": 0, "ledger": [], "daily": 0, "balance": 50}
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
                if found:
                    state["users"][found]["session_id"] = "login_" + found
                self.respond(200 if found else 401, {"ok": bool(found)}, cookie=found)
            elif path.endswith("logout-v2"):
                self.respond(503 if state["logoutFails"] else 200, {"ok": True},
                             cookie=None if state["logoutFails"] else "")
            elif path == "/api/me-v2":
                self.respond(200 if user else 401, {"legacy_user_id": user["legacy_user_id"],
                    "internal_user_id": user["internal_user_id"],
                    "session": {"session_id": user["session_id"], "provider": "password", "platform": "web_desktop"},
                    "account": {"token_balance": user["balance"], "daily_tokens_used": user["daily"]}} if user else {})
            elif path == "/api/account/token-history-v2":
                self.respond(200 if user else 401, {"summary": {"spentTokens": user["spent"],
                    "balanceSpentTokens": 0, "includedSpentTokens": user["spent"], "refundedTokens": 0,
                    "balance": user["balance"]}, "items": copy.deepcopy(user["ledger"])} if user else {})
            elif path == "/api/generate":
                identifier = f"job_fixture_{len(state['jobs']) + 1}"
                image_id = f"image{len(state['images']) + 1}"
                url, thumb = "/api/media/" + image_id, "/api/media/" + image_id + "_thumb"
                state["images"][image_id] = {"id": image_id, "url": url, "thumbnailUrl": thumb,
                    "isFavorite": False, "userId": cookie, "mode": body["mode"], "provider": body["provider"],
                    "width": body["width"], "height": body["height"], "seed": body["seed"], "tokenCost": 4,
                    "sourceIds": ["image1"] if body["mode"] == "image_to_image" else []}
                state["media"][url] = PNG + image_id.encode()
                state["media"][thumb] = PNG + (image_id + "_thumb").encode()
                state["jobs"][identifier] = {"id": identifier, "status": "completed", "owner": cookie,
                    "resultImageId": image_id, "resultUrl": url}
                user["daily"] += 4
                user["spent"] += 4
                user["ledger"].append({"id": identifier, "spentTokens": 4, "jobId": identifier[:10] + "…",
                    "delta": 0, "reason": "daily_generation", "provider": body["provider"],
                    "mode": body["mode"], "createdAt": "2026-10-17T19:00:00Z"})
                if state["duplicateCharge"]:
                    user["ledger"].append({**user["ledger"][-1], "id": identifier + "-duplicate"})
                self.respond(body={"id": identifier, "status": "queued", "queuePosition": 1,
                                   "tokenCost": 4, "tokenBalance": 50, "dailyTokensUsed": user["daily"]})
            elif path.startswith("/api/jobs/"):
                job = state["jobs"].get(path.rsplit("/", 1)[1])
                self.respond(200 if job and job["owner"] == cookie else 404, job)
            elif path.startswith("/api/gallery/"):
                parts = path.split("/")
                image = state["images"].get(parts[3])
                if not image or image["userId"] != cookie:
                    self.respond(404)
                elif parts[-1] == "favorite":
                    image["isFavorite"] = body["isFavorite"]
                    self.respond(body=image)
                elif parts[-1] == "use-as":
                    self.respond(body={"ok": True, "inputImage": image["url"]})
                else:
                    self.respond(body=image)
            elif path.startswith("/api/media/"):
                image = next((item for item in state["images"].values()
                              if path in {item["url"], item["thumbnailUrl"]}), None)
                allowed = image and (image["userId"] == cookie or state["exposePrivateMedia"])
                self.respond(200 if allowed and path in state["media"] else 404, raw=state["media"].get(path, b""))
            elif path == "/api/feed/publications":
                image = state["images"][body["imageId"]]
                if image["userId"] != cookie:
                    self.respond(404)
                    return
                identifier = f"publication{len(state['publications']) + 1}"
                moderation = "approved" if image["mode"] == "text_to_image" else "pending_review"
                publication = {"id": identifier, "moderation_status": moderation, "image_id": image["id"],
                    "status": "published" if moderation == "approved" else "pending_review", "owner": cookie,
                    "media_type": "image", "media_status": "ready", "title": body["title"]}
                state["publications"][identifier] = publication
                for variant in ("large", "thumb"):
                    state["media"][f"/api/feed/media/{identifier}?variant={variant}"] = PNG + (identifier + variant).encode()
                self.respond(body={"moderation": moderation, "publication": publication})
            elif path.startswith("/api/feed/publications/") and path.endswith("/status"):
                publication = state["publications"].get(path.split("/")[-2])
                self.respond(200 if publication and publication["owner"] == cookie else 404,
                             {"ok": True, "publication": publication})
            elif path == "/api/feed":
                self.respond(body={"items": [item for item in state["publications"].values()
                    if item["moderation_status"] == "approved" or state["leakPending"]]})
            elif path.startswith("/api/feed/media/"):
                publication = state["publications"].get(path.rsplit("/", 1)[1])
                allowed = publication and (publication["moderation_status"] == "approved" or state["leakPending"])
                media_path = self.path if "?" in self.path else path + "?variant=large"
                self.respond(200 if allowed and media_path in state["media"] else 404,
                             raw=state["media"].get(media_path, b""))
            else:
                self.respond(404)

        do_GET = handle_request
        do_POST = handle_request

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", state
    finally:
        port = server.server_port
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        assert not thread.is_alive()
        with socket.socket() as probe:
            assert probe.connect_ex(("127.0.0.1", port)) != 0


class TargetTests(unittest.TestCase):
    def test_rejects_production_external_credentials_and_non_origin_urls(self):
        for origin in ("https://izo.alikinas.ru", "http://127.0.0.1:8000", "http://127.0.0.1:48125@evil.example",
            "http://localhost:48125/path", "http://localhost:48125/?token=secret", "http://[::1]:48125",
            "file:///tmp/test", "http://localhost:invalid", "http://localhost:48125#fragment",
            "http://user:secret@localhost:48125"):
            with self.subTest(origin=origin), self.assertRaisesRegex(product.ProductError, "PRODUCT_TARGET_INVALID"):
                product.ProductFlow(attestation(origin))

    def test_unattested_target_fails_before_client_creation(self):
        for key, value in (("isolatedData", False), ("fakeProviderOnly", "true"), ("networkEgressDenied", None),
                          ("externalEffectsDisabled", False), ("sourceSha", "main"), ("project", "asa-lab-dev")):
            with self.subTest(key=key), patch.object(product, "HttpClient", side_effect=AssertionError("HTTP created")):
                with self.assertRaises(product.ProductError):
                    product.ProductFlow({**attestation(), key: value})


class HttpContractTests(unittest.TestCase):
    def setUp(self):
        self.fixture = http_fixture()
        self.origin, self.state = self.fixture.__enter__()
        self.addCleanup(self.fixture.__exit__, None, None, None)

    def flow(self):
        flow = product.ProductFlow(attestation(self.origin))
        self.addCleanup(flow.close)
        return flow

    def test_full_http_contract_and_repeat_persistence_observation(self):
        flow = self.flow()
        checks = flow.run()
        self.assertEqual(checks["auth"], "PASS")
        self.assertEqual(checks["publicationModeration"], "PASS")
        self.assertEqual(len(checks["generation"]), 2)
        for _ in range(2):
            start = len(self.state["requests"])
            result = flow.verify_persistence()
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["imagesVerified"], 2)
            self.assertEqual(result["jobsVerified"], 2)
            self.assertEqual(len(result["privateMedia"]), 4)
            self.assertEqual(len(result["publicMedia"]), 2)
            self.assertEqual(set(result["users"]), {"owner", "other"})
            self.assertTrue(all(method == "GET" for method, _ in self.state["requests"][start:]))
        # No Docker recreate occurs in this contract fixture.
        self.assertEqual(len(self.state["users"]), 2)
        self.assertEqual(flow.credentials, [])
        self.assertIn(("POST", "/api/auth/password/login-v2"), self.state["requests"])
        self.assertFalse(any("admin" in path for _, path in self.state["requests"]))
        self.assertEqual(flow.close()["sessionCleanup"], "PASS")

    def test_financial_duplication_and_private_media_exposure_are_not_pass(self):
        for failure, code in (("duplicateCharge", "PRODUCT_LEDGER_CHARGE_MISMATCH"),
                              ("exposePrivateMedia", "PRODUCT_HTTP_STATUS_UNEXPECTED_200")):
            with self.subTest(failure=failure), http_fixture() as (origin, state):
                state[failure] = True
                flow = product.ProductFlow(attestation(origin))
                try:
                    with self.assertRaisesRegex(product.ProductError, code):
                        flow.run()
                finally:
                    self.assertEqual(flow.close()["sessionCleanup"], "PASS")

    def test_network_redirect_and_sensitive_response_errors_are_redacted(self):
        client = product.HttpClient(self.origin)
        for path, code in (("/redirect", "PRODUCT_REDIRECT_FORBIDDEN"),
            ("/invalid-json", "PRODUCT_RESPONSE_INVALID"), ("/unexpected-status", "PRODUCT_HTTP_STATUS_UNEXPECTED_503")):
            with self.subTest(path=path), self.assertRaisesRegex(product.ProductError, "^" + code + "$"):
                client.request("GET", path)
        for path in ("http://example.com/secret", "//example.com/secret", "/api/me-v2#fragment"):
            with self.subTest(path=path), self.assertRaisesRegex(product.ProductError, "PRODUCT_CROSS_ORIGIN_PATH"):
                client.request("GET", path)

    def call_cli(self, data):
        with tempfile.TemporaryDirectory() as directory:
            input_path, receipt = Path(directory) / "input.json", Path(directory) / "receipt.json"
            input_path.write_text(json.dumps(data))
            with patch("sys.argv", ["tool", "--attestation", str(input_path), "--receipt", str(receipt)]):
                status = product.main()
            raw = receipt.read_text()
            self.assertNotIn(str(input_path), raw)
            return status, raw

    def test_cli_receipt_contains_only_selected_observations(self):
        status, raw = self.call_cli(attestation(self.origin))
        self.assertEqual(status, 0)
        data = json.loads(raw)
        self.assertEqual(data["status"], "HTTP_SCENARIOS_PASS")
        self.assertEqual(data["dockerAcceptance"], "NOT_VERIFIED_BY_THIS_TOOL")
        self.assertEqual(data["cleanup"]["sessionCleanup"], "PASS")
        for user in self.state["users"].values():
            for key in ("email", "password", "session_id"):
                self.assertNotIn(user[key], raw)
        self.assertNotIn("fixture_session", raw)

    def test_invalid_attestation_cli_emits_no_input_content(self):
        status, raw = self.call_cli(attestation("http://secret-user:secret-pass@localhost:48125"))
        self.assertEqual(status, 1)
        self.assertNotIn("secret-user", raw)
        self.assertNotIn("secret-pass", raw)
        self.assertEqual(json.loads(raw)["errorCode"], "PRODUCT_TARGET_INVALID")

    def test_provider_override_is_rejected_before_any_http(self):
        with self.assertRaisesRegex(product.ProductError, "PRODUCT_PROVIDER_OR_MODE_FORBIDDEN"):
            self.flow().generate({"provider": "openrouter", "mode": "text_to_image"})
        self.assertEqual(self.state["requests"], [])

    def test_session_cleanup_failure_prevents_cli_success(self):
        original = product.ProductFlow.close
        def cleanup_failure(flow):
            return {**original(flow), "sessionCleanup": "FAIL", "failedSessions": 1}
        with patch.object(product.ProductFlow, "close", cleanup_failure):
            status, raw = self.call_cli(attestation(self.origin))
        self.assertEqual(status, 1)
        self.assertEqual(json.loads(raw)["status"], "FAIL")
        self.assertEqual(json.loads(raw)["cleanup"]["sessionCleanup"], "FAIL")

    def test_failed_signup_with_issued_cookie_is_revoked_and_all_jars_checked(self):
        for fault, code in (("invalid-json", "PRODUCT_RESPONSE_INVALID"),
                            ("unexpected-status", "PRODUCT_HTTP_STATUS_UNEXPECTED_503")):
            with self.subTest(fault=fault), http_fixture() as (origin, state):
                state["signupFault"] = fault
                flow = product.ProductFlow(attestation(origin))
                with self.assertRaisesRegex(product.ProductError, code):
                    flow.register(flow.owner, 1)
                self.assertEqual(len(list(flow.owner.cookies)), 1)
                self.assertEqual(flow.credentials, [])
                cleanup = flow.close()
                self.assertEqual(cleanup["sessionCleanup"], "PASS")
                self.assertEqual(cleanup["checkedClients"], 3)
                self.assertEqual(cleanup["remainingCookieJars"], 0)
                self.assertEqual(state["requests"].count(("POST", "/api/auth/session/logout-v2")), 3)
                self.assertEqual(state["requests"].count(("GET", "/api/me-v2")), 3)

    def test_failed_revocation_clears_local_cookies_but_never_reports_cleanup_pass(self):
        flow = self.flow()
        flow.register(flow.owner, 1)
        self.state["logoutFails"] = True
        cleanup = flow.close()
        self.assertEqual(cleanup["sessionCleanup"], "FAIL")
        self.assertEqual(cleanup["failedSessions"], 3)
        self.assertEqual(cleanup["remainingCookieJars"], 0)
        self.assertEqual(flow.credentials, [])
        self.assertEqual(self.state["requests"].count(("GET", "/api/me-v2")), 4)

    def test_persistence_rejects_lost_identity_balance_daily_or_ledger_for_either_user(self):
        flow = self.flow()
        flow.run()
        baseline = copy.deepcopy(self.state["users"])
        cases = (("legacy_user_id", "wrong-legacy", "PRODUCT_SESSION_LOST_AFTER_RECREATE"),
            ("internal_user_id", "wrong-internal", "PRODUCT_SESSION_LOST_AFTER_RECREATE"),
            ("session_id", "wrong-session", "PRODUCT_SESSION_LOST_AFTER_RECREATE"),
            ("balance", 49, "PRODUCT_ACCOUNT_CHANGED_AFTER_RECREATE"),
            ("daily", 99, "PRODUCT_ACCOUNT_CHANGED_AFTER_RECREATE"),
            ("ledger", [{"id": "unexpected", "spentTokens": 0, "delta": 50, "reason": "bonus_grant"}],
             "PRODUCT_LEDGER_CHANGED_AFTER_RECREATE"))
        for user in ("user1", "user2"):
            for key, value, code in cases:
                with self.subTest(user=user, key=key):
                    self.state["users"] = copy.deepcopy(baseline)
                    self.state["users"][user][key] = value
                    with self.assertRaisesRegex(product.ProductError, code):
                        flow.verify_persistence()
        self.state["users"] = baseline

    def test_persistence_detects_ledger_detail_change_even_with_same_count_and_total(self):
        flow = self.flow()
        flow.run()
        baseline = copy.deepcopy(self.state["users"]["user1"]["ledger"])
        for key, value in (("delta", -4), ("jobId", "different-job"), ("reason", "generation_refund"),
                           ("provider", "different-provider"), ("createdAt", "different-time")):
            with self.subTest(key=key):
                self.state["users"]["user1"]["ledger"] = copy.deepcopy(baseline)
                self.state["users"]["user1"]["ledger"][0][key] = value
                with self.assertRaisesRegex(product.ProductError, "PRODUCT_LEDGER_CHANGED_AFTER_RECREATE"):
                    flow.verify_persistence()
        self.state["users"]["user1"]["ledger"] = baseline[::-1]
        self.assertEqual(flow.verify_persistence()["status"], "PASS")

    def test_persistence_checks_second_image_both_thumbnails_and_public_derivatives(self):
        flow = self.flow()
        flow.run()
        for path in tuple(self.state["media"]):
            if "publication2" in path:
                continue  # Pending derivatives are deliberately inaccessible through HTTP.
            with self.subTest(path=path):
                original = self.state["media"][path]
                self.state["media"][path] = original + b"changed"
                with self.assertRaises(product.ProductError):
                    flow.verify_persistence()
                self.state["media"][path] = original
        for image_id in ("image1", "image2"):
            for key, value in (("isFavorite", image_id != "image1"), ("width", 999), ("sourceIds", ["wrong-source"])):
                with self.subTest(image=image_id, key=key):
                    original = self.state["images"][image_id][key]
                    self.state["images"][image_id][key] = value
                    with self.assertRaisesRegex(product.ProductError, "PRODUCT_DATA_LOST_AFTER_RECREATE"):
                        flow.verify_persistence()
                    self.state["images"][image_id][key] = original
        removed = self.state["images"].pop("image2")
        with self.assertRaisesRegex(product.ProductError, "PRODUCT_HTTP_STATUS_UNEXPECTED_404"):
            flow.verify_persistence()
        self.state["images"]["image2"] = removed

    def test_persistence_keeps_pending_record_and_private_ownership(self):
        flow = self.flow()
        flow.run()
        for publication_id in ("publication1", "publication2"):
            removed = self.state["publications"].pop(publication_id)
            with self.subTest(publication=publication_id), self.assertRaises(product.ProductError):
                flow.verify_persistence()
            self.state["publications"][publication_id] = removed
        for fault, code in (("leakPending", "PRODUCT_PENDING_FEED_LEAK"),
                            ("exposePrivateMedia", "PRODUCT_HTTP_STATUS_UNEXPECTED_200")):
            self.state[fault] = True
            with self.subTest(fault=fault), self.assertRaisesRegex(product.ProductError, code):
                flow.verify_persistence()
            self.state[fault] = False
        self.state["publications"]["publication2"]["status"] = "published"
        with self.assertRaisesRegex(product.ProductError, "PRODUCT_PUBLICATION_LOST_AFTER_RECREATE"):
            flow.verify_persistence()

    def test_persistence_receipt_omits_sessions_credentials_and_user_profile(self):
        flow = self.flow()
        with self.assertRaisesRegex(product.ProductError, "PRODUCT_PERSISTENCE_BASELINE_MISSING"):
            flow.verify_persistence()
        flow.run()
        raw = json.dumps(flow.verify_persistence())
        for user in self.state["users"].values():
            for key in ("email", "password", "session_id", "internal_user_id"):
                self.assertNotIn(user[key], raw)
        self.assertNotIn("fixture_session", raw)


if __name__ == "__main__":
    unittest.main()
