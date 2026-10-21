"""Acceptance-harness regressions; fake HTTP results are not Docker evidence."""
from __future__ import annotations

from copy import deepcopy
from contextlib import redirect_stdout
import hashlib
from http.cookiejar import Cookie
from io import StringIO
import json
import os
from pathlib import Path
import re
import tempfile
import traceback
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from tools.docker_clean_admin import AdminError, PROFILE, assert_grant, prove_admin
from tools.docker_shadow_product import HttpClient, ProductError
from tools.docker_shadow_executor import IsolatedExecutor
from tools.docker_shadow_smoke import check_backend_credentials, prove
from tools.agent_system.env_runtime import EMPTY_CREDENTIAL_KEYS

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = "private-cookie-and-bootstrap-material-must-not-enter-evidence"
CODE = "isolated-bootstrap-" + "a" * 32
ATTESTATION = {"origin": "http://127.0.0.1:48125", "sourceSha": "a" * 40,
    "project": "izo-asa-shadow-admin-test", "isolatedData": True, "fakeProviderOnly": True,
    "networkEgressDenied": True, "externalEffectsDisabled": True, "freshData": True, "adminFixture": PROFILE}


class Api:
    """Small protocol double with observable accounts and deliberate source bugs."""
    def __init__(self, **flags):
        self.flags, self.users, self.sessions, self.payments, self.keys, self.refunds = flags, {}, {}, {}, {}, {}
        self.events, self.calls, self.logout_attempts = [], [], []
        self.next_id = 1
        self.package = {"code": "tokens_fixture", "kind": "tokens", "is_active": True,
                        "price_amount": 3, "token_amount": 7, "currency": "RUB"}

    def identifier(self):
        value = f"{self.next_id:010x}" + "a" * 22
        self.next_id += 1
        return value

    def login(self, client, role):
        identity = self.identifier()
        self.users[identity] = {"legacy_user_id": "web_" + identity, "internal_user_id": identity,
            "session": {"session_id": self.identifier(), "provider": "web_admin" if role == "admin" else "password",
                        "platform": "web"}, "role": role,
            "account": {"token_balance": 20, "daily_tokens_used": 0}, "ledger": []}
        self.sessions[client] = identity
        client.cookies.set_cookie(Cookie(0, "session", PRIVATE, None, False, "127.0.0.1", False,
                                        False, "/", True, False, None, True, None, None, {}))
        return self.me(client)

    def me(self, client):
        value = deepcopy(self.users[self.sessions[client]])
        value["unused_private_field"] = PRIVATE
        return value

    def payment_dict(self, payment):
        return {"id": payment["id"], "status": payment["status"], "provider": "simulator",
                "internal_user_id": payment["owner"], "token_ledger_id": payment.get("ledger_id")}

    def grant(self, payment):
        user = self.users[payment["owner"]]
        entry = {"id": self.identifier()[:10] + "…", "jobId": None, "delta": 7, "spentTokens": 0,
                 "reason": "payment_grant", "provider": None, "mode": None, "model": None,
                 "createdAt": "2026-10-17T00:00:00Z"}
        user["ledger"].append(entry)
        user["account"]["token_balance"] += 7
        payment.update(status="paid", ledger_id=entry["id"])

    def request(self, client, method, path, payload=None, *, expected=(200,), binary=False):
        self.calls.append((client, method, path))
        if self.flags.get("dashboard_exception") and path == "/api/admin/dashboard-v2" and client in self.sessions:
            if self.users[self.sessions[client]]["role"] == "admin":
                raise RuntimeError(PRIVATE)
        status, result = self.dispatch(client, method, path, payload)
        if status not in expected:
            raise ProductError(f"PRODUCT_HTTP_STATUS_UNEXPECTED_{status}")
        return deepcopy(result) if status == 200 else {"httpStatus": status}

    def dispatch(self, client, method, target, payload):
        path, query = urlsplit(target).path, parse_qs(urlsplit(target).query)
        if path == "/api/health":
            return 200, {"ok": True, "ready": True}
        if path == "/api/auth/password/register-v2":
            me = self.login(client, "user")
            return 200, {"ok": True, "requires_email_verification": False, "legacy_user_id": me["legacy_user_id"]}
        if path == "/api/auth/web-login":
            if payload["code"] != CODE:
                return 403, {"secret": PRIVATE}
            return 200, {"ok": True, "user": self.login(client, "admin")}
        if path == "/api/auth/session/logout-v2":
            self.logout_attempts.append(client)
            if self.flags.get("logout_failure") and len(self.logout_attempts) == 1:
                return 503, {"secret": PRIVATE}
            self.sessions.pop(client, None)
            return 200, {"ok": True}
        if path in ("/api/telegram/webhook", "/api/max/webhook"):
            return 404, {}
        if path == "/api/public/commerce-v2":
            return 200, {"ok": True, "payment_provider": "simulator", "payments_available": True,
                         "legal_readiness": {"ready": True}}
        if client not in self.sessions:
            return 401, {"secret": PRIVATE}
        user = self.users[self.sessions[client]]
        if path.startswith("/api/admin/") and user["role"] != "admin":
            return 403, {"secret": PRIVATE}
        if path == "/api/me-v2":
            return 200, self.me(client)
        if path == "/api/account/token-history-v2":
            return 200, {"ok": True, "items": user["ledger"], "summary": {
                "spentTokens": 0, "balanceSpentTokens": 0, "includedSpentTokens": 0,
                "refundedTokens": 0, "balance": user["account"]["token_balance"]}}
        if path == "/api/admin/dashboard-v2":
            return 200, {"ok": True, "dashboard": {"fixture": True}, "private": PRIVATE}
        if path == "/api/admin/payments/status-v2":
            return 200, {"ok": True, "provider": "simulator", "simulator_enabled": True,
                "configured": False, "summary": {"total": 0}, "payments": [],
                "config": {"shop_id": "", "secret_key": bool(self.flags.get("live_secret")), "private": PRIVATE}}
        if path == "/api/admin/settings/legal":
            return 200, {"ok": True, "key": "legal", "settings": payload["settings"]}
        if path == "/api/billing/packages-v2":
            return 200, {"provider": "simulator", "provider_ready": True, "packages": [self.package]}
        if path == "/api/billing/checkout-v2":
            key = payload["idempotency_key"]
            if key in self.keys:
                payment = self.payments[self.keys[key]]
                if payment["owner"] != user["internal_user_id"] and not self.flags.get("foreign_leak"):
                    return 409, {}
                return 200, {"ok": True, "idempotent": True, "payment_id": payment["id"],
                    "provider_payment_id": payment["provider_id"], "status": payment["status"],
                    "payment": self.payment_dict(payment)}
            identifier = self.identifier()
            payment = {"id": identifier, "provider_id": "sim_" + identifier[:24], "owner": user["internal_user_id"],
                       "status": "pending", "simulator": "pending", "amount": 3, "currency": "RUB", "tokens": 7}
            self.payments[identifier], self.keys[key] = payment, identifier
            return 200, {"ok": True, "payment_id": identifier, "provider_payment_id": payment["provider_id"],
                "status": "pending", "confirmation_url": ATTESTATION["origin"] + "/payment?simulator=1"}
        match = re.fullmatch(r"/api/billing/payments/([a-f0-9]{32})/status-v2", path)
        if match:
            payment = self.payments[match[1]]
            if payment["owner"] != user["internal_user_id"]:
                return 404, {}
            return 200, {"ok": True, "payment": {**self.payment_dict(payment), "amount": 3,
                                                 "currency": "RUB", "tokens": 7}}
        match = re.fullmatch(r"/api/admin/payments/([a-f0-9]{32})/(simulate-v2|refund-v2)", path)
        if match:
            payment = self.payments[match[1]]
            return self.mutate(payment, match[2], payload)
        if path == "/api/admin/audit-logs-v2":
            return 200, {"items": [entry for entry in self.events if entry["action"] == query.get("action", [entry["action"]])[0]]}
        raise AssertionError("Unexpected fake API endpoint: " + path)

    def mutate(self, payment, action, payload):
        if action == "refund-v2":
            key = payload["idempotency_key"]
            if key in self.refunds:
                return 200, {"ok": True, **self.refunds[key], "idempotent": True}
            if payment["status"] != "paid" or payload["amount"] != 3:
                return 400, {}
            payment["status"] = "refunded"
            refund = {"id": self.identifier(), "status": "completed", "amount": 3,
                      "token_reversal_policy": "deferred", "token_reversal_ledger_id": None}
            result = {"refund": refund, "payment": self.payment_dict(payment), "invoice": {"status": "refunded"}}
            self.refunds[key] = result
            self.events.append({"action": "billing_payment_refunded", "entity_id": refund["id"], "private": PRIVATE})
            return 200, {"ok": True, **result}
        requested = payload["status"]
        if payment["simulator"] in {"succeeded", "canceled"} and payment["simulator"] != requested:
            return 409, {}
        if payment["status"] == "refunded" and self.flags.get("post_refund_reject"):
            return 409, {}
        completed = None
        if requested == "succeeded":
            already = payment["status"] in {"paid", "refunded"}
            duplicate = self.flags.get("duplicate_grant") and payment["status"] == "paid"
            regrant = self.flags.get("post_refund_bug") and payment["status"] == "refunded"
            if not already or duplicate or regrant:
                self.grant(payment)
                already = False
            completed = {"idempotent": already}
        else:
            payment["status"] = "canceled"
        payment["simulator"] = requested
        self.events.append({"action": "admin_simulate_payment", "entity_id": payment["id"], "private": PRIVATE})
        return 200, {"ok": True, "payment": self.payment_dict(payment), "completed": completed}


class AdminAcceptanceTests(unittest.TestCase):
    def run_protocol(self, **flags):
        api = Api(**flags)
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / "admin.json"
            with patch.object(HttpClient, "request", autospec=True, side_effect=api.request), patch("tools.docker_clean_admin.prove_models"):
                report = prove_admin(ATTESTATION, receipt, bootstrap_code=CODE)
            self.assertEqual(json.loads(receipt.read_text()), report)
            self.assertNotIn(PRIVATE, receipt.read_text())
            self.assertNotIn(CODE, receipt.read_text())
            if os.name != "nt":
                self.assertEqual(receipt.stat().st_mode & 0o777, 0o600)
        self.assertEqual(len(api.logout_attempts), 4)
        self.assertEqual(report["cleanup"]["remainingCookieJars"], 0)
        return api, report

    def test_normal_protocol_has_one_grant_and_preserves_refunded_state(self):
        api, report = self.run_protocol()
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(len(report["checks"]), 17)
        self.assertTrue(all(row["status"] == "PASS" for row in report["checks"].values()))
        self.assertEqual(report["checks"]["paymentSuccess"]["grantsAdded"], 1)
        self.assertRegex(report["checks"]["paymentSuccess"]["ledgerId"], r"^[0-9a-f]{10}…$")
        self.assertEqual({payment["status"] for payment in api.payments.values()}, {"refunded", "canceled"})
        self.assertEqual(sum(len(user["ledger"]) for user in api.users.values()), 1)
        self.assertFalse(api.sessions)
        self.assertFalse(any("notifications/process" in path or "check-v2" in path for _, _, path in api.calls))

    def test_source_foreign_key_bug_is_failure_without_suppressing_other_cases(self):
        _, report = self.run_protocol(foreign_leak=True)
        row = report["checks"]["foreignCheckoutReplay"]
        self.assertEqual((report["status"], row["status"]), ("FAIL", "FAIL"))
        self.assertEqual(row["errorCode"], "ADMIN_FOREIGN_CHECKOUT_PAYMENT_LEAK")
        self.assertTrue(row["foreignPaymentReturned"])
        self.assertEqual(row["httpStatus"], 200)
        self.assertEqual(report["checks"]["paymentSuccess"]["status"], "PASS")
        self.assertEqual(report["checks"]["otherUserBalance"]["status"], "PASS")

    def test_source_post_refund_regrant_is_failure_with_measured_financial_delta(self):
        _, report = self.run_protocol(post_refund_bug=True)
        row = report["checks"]["postRefundReplay"]
        self.assertEqual(row["errorCode"], "ADMIN_POST_REFUND_REPLAY_REGRANTED")
        self.assertEqual((report["status"], row["status"]), ("FAIL", "FAIL"))
        self.assertEqual(row["after"]["ledgerEntries"] - row["before"]["ledgerEntries"], 1)
        self.assertEqual(row["after"]["balance"] - row["before"]["balance"], 7)
        self.assertFalse(row["refundedStatePreserved"])
        self.assertEqual(report["checks"]["cancellation"]["status"], "PASS")

    def test_success_duplicate_grant_fails(self):
        _, report = self.run_protocol(duplicate_grant=True)
        self.assertEqual(report["checks"]["successReplay"]["status"], "FAIL")
        self.assertEqual(report["status"], "FAIL")

    def test_post_refund_conflict_preserving_state_is_also_valid(self):
        _, report = self.run_protocol(post_refund_reject=True)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["checks"]["postRefundReplay"]["httpStatus"], 409)

    def test_live_credential_presence_refuses_before_settings_and_payments(self):
        api, report = self.run_protocol(live_secret=True)
        self.assertEqual(report["checks"]["simulatorSafety"]["errorCode"], "ADMIN_LOCAL_SIMULATOR_REQUIRED")
        self.assertEqual(report["checks"]["legalSetup"]["status"], "NOT_RUN")
        self.assertFalse(api.payments)
        self.assertFalse(any(path == "/api/admin/settings/legal" for _, _, path in api.calls))

    def test_untrusted_target_or_profile_or_short_code_prevents_http(self):
        cases = [({**ATTESTATION, "origin": "http://example.com:48125"}, CODE),
                 ({**ATTESTATION, "freshData": False}, CODE), (ATTESTATION, "admin-demo")]
        with tempfile.TemporaryDirectory() as directory:
            for attestation, code in cases:
                with self.subTest(attestation=attestation, validCode=code == CODE):
                    with patch.object(HttpClient, "request") as request:
                        with self.assertRaises((AdminError, ProductError)):
                            prove_admin(attestation, Path(directory) / "receipt.json", bootstrap_code=code)
                        request.assert_not_called()

    def test_existing_receipt_is_not_overwritten_and_prevents_http(self):
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / "admin.json"
            receipt.write_text("prior evidence")
            with patch.object(HttpClient, "request") as request:
                with self.assertRaises(FileExistsError):
                    prove_admin(ATTESTATION, receipt, bootstrap_code=CODE)
                request.assert_not_called()
            self.assertEqual(receipt.read_text(), "prior evidence")

    def test_unexpected_exception_is_redacted_and_all_sessions_are_closed(self):
        api, report = self.run_protocol(dashboard_exception=True)
        self.assertEqual(report["checks"]["adminRights"]["errorCode"], "ADMIN_OPERATION_FAILED")
        self.assertFalse(api.sessions)
        self.assertEqual(report["cleanup"]["sessionCleanup"], "PASS")

    def test_logout_failure_prevents_pass_but_all_cookie_jars_are_cleared(self):
        _, report = self.run_protocol(logout_failure=True)
        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(report["cleanup"]["failedSessions"], 1)

    def test_grant_cannot_replace_a_prior_ledger_entry(self):
        before = {"identity": {"id": "one"}, "account": {"token_balance": 20, "daily_tokens_used": 0},
                  "ledger": {"items": [{"id": "0000000001…", "reason": "prior", "delta": 20, "spentTokens": 0}]}}
        after = deepcopy(before)
        after["account"]["token_balance"] += 7
        after["ledger"]["items"][0]["delta"] = 99
        after["ledger"]["items"].append({"id": "0000000002…", "reason": "payment_grant", "delta": 7, "spentTokens": 0})
        with self.assertRaisesRegex(AdminError, "ADMIN_EXISTING_ACCOUNT_STATE_CHANGED"):
            assert_grant(before, after, 7)

    def test_compose_override_cannot_add_mount_network_command_or_service(self):
        value = json.loads((ROOT / "ops/docker/dev/compose.admin-acceptance.yml").read_text())
        self.assertEqual(set(value), {"services"})
        self.assertEqual(set(value["services"]), {"backend"})
        self.assertEqual(set(value["services"]["backend"]), {"environment"})
        env = value["services"]["backend"]["environment"]
        self.assertEqual(set(env), {"ADMIN_ONE_TIME_CODE", "BILLING_SIMULATOR_ENABLED", "PUBLIC_SITE_URL"})
        self.assertEqual(env["BILLING_SIMULATOR_ENABLED"], "true")
        self.assertTrue(env["ADMIN_ONE_TIME_CODE"].startswith("${IZO_ACCEPTANCE_ADMIN_CODE:?"))
        self.assertTrue(env["PUBLIC_SITE_URL"].startswith("http://127.0.0.1:${IZO_SHADOW_WEB_PORT:?"))


class AdminProfileGuardTests(unittest.TestCase):
    def setUp(self):
        self.shadow = SimpleNamespace(fixture=True, web_port=48125,
            executor=IsolatedExecutor(lambda *args, **kwargs: None, context="owned", engine_id="a" * 16,
                                      machine_sha256="b" * 64))
        self.container = {"Config": {"Cmd": ["python", "/opt/izo/fixtures/docker_shadow_fixture.py"], "Entrypoint": None}}
        self.env = {**{key: "" for key in EMPTY_CREDENTIAL_KEYS}, "ADMIN_ONE_TIME_CODE": CODE,
            "APP_ENV": "test", "ENV": "test", "MODE": "test", "IZO_SHADOW_FIXTURE": "controlled-comfyui-v1",
            "COMFYUI_BASE_URL": "http://127.0.0.1:48991", "COMFYUI_MOCK_FALLBACK": "false",
            "BILLING_SIMULATOR_ENABLED": "true", "PUBLIC_SITE_URL": ATTESTATION["origin"]}

    def check(self, code=CODE):
        check_backend_credentials(self.shadow, self.container, self.env, expected_ephemeral_admin_code=code)

    def rejected(self, expected, code=CODE):
        with self.assertRaises(RuntimeError) as caught:
            self.check(code)
        self.assertEqual(str(caught.exception), expected)
        self.assertNotIn(PRIVATE, str(caught.exception))
        self.assertNotIn(CODE, str(caught.exception))

    def test_default_still_requires_empty_admin_and_explicit_profile_preserves_input(self):
        initial = deepcopy(self.env)
        with self.assertRaisesRegex(RuntimeError, "^SHADOW_CREDENTIAL_PRESENT$"):
            check_backend_credentials(self.shadow, self.container, self.env)
        self.check()
        self.assertEqual(self.env, initial)
        self.env["ADMIN_ONE_TIME_CODE"] = ""
        check_backend_credentials(self.shadow, self.container, self.env)
        self.assertIn("ADMIN_ONE_TIME_CODE", EMPTY_CREDENTIAL_KEYS)

    def test_wrong_expected_or_actual_code_is_fixed_failure(self):
        self.rejected("SHADOW_ADMIN_CODE_INVALID", "admin-demo")
        for value in (PRIVATE, "\u042f" * 32, None):
            self.env["ADMIN_ONE_TIME_CODE"] = value
            self.rejected("SHADOW_ADMIN_CODE_MISMATCH")

    def test_wrong_profile_environment_or_public_origin_always_fails(self):
        for key, value in (("APP_ENV", "production"), ("ENV", "production"), ("MODE", "production"),
                ("IZO_SHADOW_FIXTURE", "other"), ("COMFYUI_BASE_URL", "http://127.0.0.1:1"),
                ("COMFYUI_MOCK_FALLBACK", "true"), ("BILLING_SIMULATOR_ENABLED", "false"),
                ("PUBLIC_SITE_URL", "http://example.com:48125"), ("PUBLIC_SITE_URL", "http://127.0.0.1:48126")):
            with self.subTest(key=key, value=value):
                previous = self.env[key]
                self.env[key] = value
                self.rejected("SHADOW_ADMIN_PROFILE_REQUIRED")
                self.env[key] = previous
        for key, value in (("fixture", False), ("executor", None), ("executor", object())):
            previous = getattr(self.shadow, key)
            setattr(self.shadow, key, value)
            self.rejected("SHADOW_ADMIN_PROFILE_REQUIRED")
            setattr(self.shadow, key, previous)
        for key, value in (("Cmd", ["uvicorn", "main:app"]), ("Entrypoint", ["sh", "-c"])):
            previous = self.container["Config"][key]
            self.container["Config"][key] = value
            self.rejected("SHADOW_ADMIN_PROFILE_REQUIRED")
            self.container["Config"][key] = previous

    def test_every_other_sensitive_key_still_rejects(self):
        for key in EMPTY_CREDENTIAL_KEYS:
            if key != "ADMIN_ONE_TIME_CODE":
                with self.subTest(key=key):
                    self.env[key] = PRIVATE
                    self.rejected("SHADOW_CREDENTIAL_PRESENT")
                    self.env[key] = ""

    def test_proof_failure_never_serializes_exception_credentials(self):
        def fail():
            raise RuntimeError(PRIVATE + CODE)
        shadow = SimpleNamespace(sha=ATTESTATION["sourceSha"], project=ATTESTATION["project"],
                                 executor=None, source_guard=fail)
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(StringIO()) as output:
            receipt = Path(directory) / "proof.json"
            with self.assertRaises(RuntimeError) as caught:
                prove(shadow, receipt, build=False, expected_ephemeral_admin_code=CODE)
            self.assertEqual(json.loads(receipt.read_text())["error"], "SHADOW_ADMIN_PROOF_FAILED")
            content = receipt.read_text() + "".join(traceback.format_exception(caught.exception))
            self.assertNotIn(PRIVATE, content + output.getvalue())
            self.assertNotIn(CODE, content + output.getvalue())

    def test_config_digest_and_both_inspections_include_the_admin_profile(self):
        config = {"services": {"backend": {"environment": self.env}}}
        shadow = SimpleNamespace(sha=ATTESTATION["sourceSha"], project=ATTESTATION["project"],
            executor=SimpleNamespace(foreign_snapshot=lambda project: {}), source_guard=lambda: None,
            up=lambda **kwargs: None, config=lambda: config, docker=lambda *args, **kwargs: "[]")
        stack = {"backend": {"container": "owned-container"}}
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(StringIO()):
            with patch("tools.docker_shadow_smoke.inspect_stack", return_value=stack) as inspection, \
                    patch("tools.docker_shadow_smoke.http_proof", return_value={}), \
                    patch("tools.docker_shadow_smoke.fixture", return_value={"same": True}), \
                    patch("tools.docker_shadow_smoke.egress_proof", return_value={}), \
                    patch("tools.docker_shadow_executor.compare_isolated", return_value={"status": "PASS"}):
                receipt = Path(directory) / "proof.json"
                prove(shadow, receipt, build=False, expected_ephemeral_admin_code=CODE)
                report = json.loads(receipt.read_text())
                self.assertEqual(report["status"], "PASS")
                self.assertEqual(inspection.call_count, 2)
                for call in inspection.call_args_list:
                    self.assertEqual(call.kwargs, {"expected_ephemeral_admin_code": CODE})
            self.assertEqual(report["configSha256"], hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest())
            self.assertNotIn(CODE, receipt.read_text())


if __name__ == "__main__":
    unittest.main()
