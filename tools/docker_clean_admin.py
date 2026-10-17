"""Normal HTTP admin and local-simulator acceptance on separately owned fresh state.

The caller proves Docker/source/egress ownership, enables the explicit Compose
profile and later deletes its volumes. This module never launches Docker, opens a
database, processes mail or follows a payment confirmation URL.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import time
from urllib.parse import urlsplit
import uuid

from tools.docker_shadow_product import HttpClient, ProductError, ProductFlow, path_id, validate_target

PROFILE = "local-billing-simulator-v1"
CHECKOUT = "/api/billing/checkout-v2"
ADMIN_STATUS = "/api/admin/payments/status-v2"
LEGAL = "/api/admin/settings/legal"


class AdminError(RuntimeError):
    pass


def require(value, code):
    if not value:
        raise AdminError(code)


def error_code(error):
    value = str(error)
    trusted = isinstance(error, (AdminError, ProductError))
    return value if trusted and re.fullmatch(r"(?:ADMIN|PRODUCT)_[A-Z0-9_]{2,100}", value) else "ADMIN_OPERATION_FAILED"


def financial_summary(snapshot):
    ledger = snapshot["ledger"]["items"]
    return {"balance": snapshot["account"]["token_balance"],
            "dailyUsed": snapshot["account"]["daily_tokens_used"], "ledgerEntries": len(ledger),
            "ledgerSha256": hashlib.sha256(json.dumps(ledger, sort_keys=True).encode()).hexdigest()}


def assert_grant(before, after, tokens):
    old = {item["id"]: item for item in before["ledger"]["items"]}
    new = {item["id"]: item for item in after["ledger"]["items"]}
    require(len(new) == len(after["ledger"]["items"]) and len(old) == len(before["ledger"]["items"]),
            "ADMIN_LEDGER_ID_COLLISION")
    added = [item for key, item in new.items() if key not in old]
    require(before["identity"] == after["identity"] and all(new.get(key) == item for key, item in old.items()),
            "ADMIN_EXISTING_ACCOUNT_STATE_CHANGED")
    require(len(added) == 1 and added[0]["reason"] == "payment_grant"
            and added[0]["delta"] == tokens and added[0]["spentTokens"] == 0,
            "ADMIN_PAYMENT_GRANT_NOT_EXACTLY_ONCE")
    require(after["account"]["token_balance"] == before["account"]["token_balance"] + tokens
            and after["account"]["daily_tokens_used"] == before["account"]["daily_tokens_used"],
            "ADMIN_PAYMENT_BALANCE_MISMATCH")
    ledger_id = added[0]["id"]
    require(isinstance(ledger_id, str) and re.fullmatch(r"[0-9a-f]{10}…", ledger_id) is not None,
            "ADMIN_PUBLIC_LEDGER_ID_INVALID")
    return ledger_id


class AdminProbe:
    def __init__(self, attestation):
        self.flow = ProductFlow(attestation)
        self.admin = HttpClient(self.flow.origin)
        self.flow.clients = (*self.flow.clients, self.admin)
        self.checks, self.data = {}, {}

    def step(self, name, action, dependencies=()):
        row = self.checks[name] = {"status": "NOT_RUN"}
        if any(self.checks[key]["status"] != "PASS" for key in dependencies):
            row["reasonCode"] = "ADMIN_PREREQUISITE_FAILED"
            return
        started = time.monotonic()
        try:
            action(row)
            row["status"] = "PASS"
        except Exception as error:
            row.update(status="FAIL", errorCode=error_code(error))
        row["durationMs"] = round((time.monotonic() - started) * 1000, 3)

    def snapshot(self, client=None):
        return self.flow.account_snapshot(client or self.flow.owner)

    def payment(self, payment_id, client=None):
        value = (client or self.flow.owner).request("GET", f"/api/billing/payments/{path_id(payment_id)}/status-v2")
        payment = value.get("payment", {})
        require(value.get("ok") is True and payment.get("id") == payment_id, "ADMIN_PAYMENT_READ_INVALID")
        return payment

    def simulate(self, payment_id, status, *, expected=(200,)):
        return self.admin.request("POST", f"/api/admin/payments/{path_id(payment_id)}/simulate-v2",
            {"status": status, "reason": "Docker D3 isolated simulator acceptance"}, expected=expected)

    def bootstrap(self, row, code):
        health = self.flow.guest.request("GET", "/api/health")
        require(health.get("ok") is True and health.get("ready") is True, "ADMIN_DATABASE_NOT_READY")
        self.flow.guest.request("GET", "/api/me-v2", expected=(401,))
        identities = [self.flow.register(client, index) for index, client in
                      enumerate((self.flow.owner, self.flow.other), start=1)]
        require(identities[0]["internal_user_id"] != identities[1]["internal_user_id"], "ADMIN_TWO_USERS_REQUIRED")
        self.data["ownerId"], self.data["otherId"] = (path_id(item["internal_user_id"]) for item in identities)
        self.admin.request("POST", "/api/auth/web-login", {"code": "invalid-" + uuid.uuid4().hex}, expected=(403,))
        self.admin.request("GET", "/api/me-v2", expected=(401,))
        login = self.admin.request("POST", "/api/auth/web-login", {"code": code})
        me = self.admin.request("GET", "/api/me-v2")
        require(login.get("ok") is True and login.get("user", {}).get("role") == "admin"
                and me.get("internal_user_id") == login["user"].get("internal_user_id")
                and me.get("session", {}).get("provider") == "web_admin", "ADMIN_BOOTSTRAP_IDENTITY_INVALID")
        row.update(healthReady=True, fixtureUsers=2, wrongCodeHttpStatus=403, sessionProvider="web_admin")

    def safety(self, row):
        value = self.admin.request("GET", ADMIN_STATUS)
        config = value.get("config", {})
        require(value.get("ok") is True and value.get("provider") == "simulator"
                and value.get("simulator_enabled") is True and value.get("configured") is False
                and config.get("secret_key") is False and config.get("shop_id") == "",
                "ADMIN_LOCAL_SIMULATOR_REQUIRED")
        require(value.get("summary", {}).get("total") == 0 and value.get("payments") == [],
                "ADMIN_FRESH_PAYMENT_STATE_REQUIRED")
        for provider in ("telegram", "max"):
            self.flow.guest.request("POST", f"/api/{provider}/webhook", {}, expected=(404,))
        row.update(provider="simulator", liveProviderConfigured=False, initialPayments=0,
                   disabledWebhookHttpStatus=404)

    def rights(self, row):
        dashboard = self.admin.request("GET", "/api/admin/dashboard-v2")
        require(dashboard.get("ok") is True and isinstance(dashboard.get("dashboard"), dict),
                "ADMIN_DASHBOARD_INVALID")
        for client, status in ((self.flow.owner, 403), (self.flow.other, 403), (self.flow.guest, 401)):
            for path in ("/api/admin/dashboard-v2", ADMIN_STATUS, "/api/admin/audit-logs-v2?limit=1"):
                client.request("GET", path, expected=(status,))
            client.request("POST", LEGAL, {"settings": {}}, expected=(status,))
        row.update(dashboardHttpStatus=200, ordinaryUsers=403, guest=401, settingsMutationBoundary="PASS")

    def setup(self, row):
        settings = {"brand_name": "IZO Docker isolated fixture", "seller_name": "Automated test fixture",
            "seller_status": "Test fixture", "inn": "0000000000", "legal_address": "Isolated fixture",
            "support_email": "support@example.invalid", "site_url": self.flow.origin, "offer_version": "d3-fixture"}
        value = self.admin.request("POST", LEGAL, {"settings": settings})
        require(value.get("ok") is True and value.get("key") == "legal"
                and all(value.get("settings", {}).get(key) == item for key, item in settings.items()),
                "ADMIN_LEGAL_SETUP_INVALID")
        commerce = self.flow.guest.request("GET", "/api/public/commerce-v2")
        require(commerce.get("ok") is True and commerce.get("payment_provider") == "simulator"
                and commerce.get("payments_available") is True
                and commerce.get("legal_readiness", {}).get("ready") is True, "ADMIN_COMMERCE_NOT_READY")
        offers = self.flow.owner.request("GET", "/api/billing/packages-v2")
        require(offers.get("provider") == "simulator" and offers.get("provider_ready") is True,
                "ADMIN_PACKAGE_PROVIDER_INVALID")
        packages = [p for p in offers["packages"] if p.get("kind") == "tokens" and p.get("is_active") is True
                    and type(p.get("price_amount")) is int and p["price_amount"] > 0
                    and type(p.get("token_amount")) is int and p["token_amount"] > 0 and p.get("currency") == "RUB"]
        require(bool(packages), "ADMIN_TOKEN_PACKAGE_UNAVAILABLE")
        self.data["package"] = min(packages, key=lambda item: (item["price_amount"], item["token_amount"]))
        self.data["before"], self.data["otherBefore"] = self.snapshot(), self.snapshot(self.flow.other)
        row.update(legalReady=True, paymentsAvailable=True, provider="simulator", packageKind="tokens")

    def new_checkout(self, client):
        package = self.data["package"]
        body = {"package_code": package["code"], "idempotency_key": uuid.uuid4().hex,
                "offer_accepted": True, "receipt_contact": "payer@example.invalid"}
        result = client.request("POST", CHECKOUT, body)
        payment_id = path_id(result.get("payment_id"))
        require(result.get("ok") is True and result.get("status") == "pending"
                and re.fullmatch(r"sim_[0-9a-f]{24}", str(result.get("provider_payment_id"))) is not None,
                "ADMIN_CHECKOUT_NOT_SIMULATED_PENDING")
        confirmation = urlsplit(result.get("confirmation_url", ""))
        require((confirmation.scheme, confirmation.netloc) == ("http", urlsplit(self.flow.origin).netloc)
                and not confirmation.username and not confirmation.password, "ADMIN_CONFIRMATION_TARGET_INVALID")
        payment = self.payment(payment_id, client)
        require(payment.get("status") == "pending" and payment.get("amount") == package["price_amount"]
                and payment.get("tokens") == package["token_amount"] and payment.get("currency") == "RUB",
                "ADMIN_CHECKOUT_FINANCIAL_CONTRACT_INVALID")
        return body, result, payment

    def checkout(self, row):
        body, result, payment = self.new_checkout(self.flow.owner)
        self.data.update(body=body, created=result, paymentId=payment["id"])
        require(self.snapshot() == self.data["before"], "ADMIN_PENDING_PAYMENT_CHANGED_BALANCE")
        row.update(paymentId=payment["id"], statusObserved="pending", amount=payment["amount"],
                   currency="RUB", tokens=payment["tokens"], balanceChanged=False)

    def checkout_replay(self, row):
        replay = self.flow.owner.request("POST", CHECKOUT, self.data["body"])
        require(replay.get("ok") is True and replay.get("payment_id") == self.data["paymentId"]
                and replay.get("idempotent") is True, "ADMIN_CHECKOUT_REPLAY_CREATED_PAYMENT")
        require(self.snapshot() == self.data["before"], "ADMIN_CHECKOUT_REPLAY_CHANGED_BALANCE")
        row.update(samePayment=True, idempotent=True, balanceChanged=False)

    def payment_access(self, row):
        payment_id = self.data["paymentId"]
        for client, status in ((self.flow.other, 404), (self.flow.guest, 401)):
            client.request("GET", f"/api/billing/payments/{payment_id}/status-v2", expected=(status,))
        self.flow.guest.request("POST", CHECKOUT, self.data["body"], expected=(401,))
        for client, status in ((self.flow.owner, 403), (self.flow.other, 403), (self.flow.guest, 401)):
            client.request("POST", f"/api/admin/payments/{payment_id}/simulate-v2",
                {"status": "succeeded", "reason": "Denied fixture mutation"}, expected=(status,))
            client.request("POST", f"/api/admin/payments/{payment_id}/refund-v2",
                {"amount": 1, "reason": "Denied fixture mutation", "idempotency_key": uuid.uuid4().hex}, expected=(status,))
        require(self.snapshot() == self.data["before"], "ADMIN_DENIED_PAYMENT_MUTATION_CHANGED_BALANCE")
        row.update(otherPaymentHttpStatus=404, guest=401, ordinaryMutationHttpStatus=403)

    def foreign_replay(self, row):
        result = self.flow.other.request("POST", CHECKOUT, self.data["body"], expected=(200, 403, 404, 409))
        status = result.get("httpStatus", 200)
        row["httpStatus"] = status
        if status == 200:
            same = result.get("payment_id") == self.data["paymentId"]
            same = same or result.get("payment", {}).get("internal_user_id") == self.data["ownerId"]
            row["foreignPaymentReturned"] = same
            require(not same, "ADMIN_FOREIGN_CHECKOUT_PAYMENT_LEAK")
            require(result.get("provider_payment_id") != self.data["created"]["provider_payment_id"],
                    "ADMIN_FOREIGN_PROVIDER_ID_REUSED")
            separate = self.payment(path_id(result.get("payment_id")), self.flow.other)
            require(separate.get("status") == "pending", "ADMIN_FOREIGN_CHECKOUT_STATE_INVALID")
            self.simulate(separate["id"], "canceled")
            require(self.payment(separate["id"], self.flow.other)["status"] == "canceled",
                    "ADMIN_SEPARATE_PAYMENT_CANCEL_FAILED")
        require(self.snapshot() == self.data["before"] and self.snapshot(self.flow.other) == self.data["otherBefore"],
                "ADMIN_FOREIGN_REPLAY_CHANGED_BALANCE")
        row.update(foreignPaymentReturned=False, balanceChanged=False)

    def success(self, row):
        result = self.simulate(self.data["paymentId"], "succeeded")
        self.data["paid"] = after = self.snapshot()
        row.update(before=financial_summary(self.data["before"]), after=financial_summary(after))
        ledger_id = assert_grant(self.data["before"], after, self.data["package"]["token_amount"])
        require(result.get("completed", {}).get("idempotent") is False
                and result.get("payment", {}).get("status") == "paid"
                and result["payment"].get("token_ledger_id") == ledger_id
                and self.payment(self.data["paymentId"])["status"] == "paid", "ADMIN_SUCCESS_STATE_INVALID")
        row.update(ledgerId=ledger_id, grantsAdded=1, statusObserved="paid")

    def success_replay(self, row):
        result = self.simulate(self.data["paymentId"], "succeeded")
        after = self.snapshot()
        row.update(before=financial_summary(self.data["paid"]), after=financial_summary(after))
        require(result.get("completed", {}).get("idempotent") is True
                and result.get("payment", {}).get("status") == "paid" and after == self.data["paid"],
                "ADMIN_SUCCESS_REPLAY_CHANGED_FINANCIAL_STATE")
        self.simulate(self.data["paymentId"], "canceled", expected=(409,))
        row.update(idempotent=True, terminalChangeHttpStatus=409, balanceChanged=False)

    def refund(self, row):
        body = {"amount": self.data["package"]["price_amount"], "reason": "Docker D3 isolated full refund",
                "idempotency_key": uuid.uuid4().hex}
        result = self.admin.request("POST", f"/api/admin/payments/{self.data['paymentId']}/refund-v2", body)
        refund = result.get("refund", {})
        require(result.get("ok") is True and refund.get("status") == "completed"
                and refund.get("amount") == body["amount"] and refund.get("token_reversal_policy") == "deferred"
                and not refund.get("token_reversal_ledger_id") and result.get("payment", {}).get("status") == "refunded"
                and result.get("invoice", {}).get("status") == "refunded", "ADMIN_REFUND_CONTRACT_INVALID")
        self.data.update(refundBody=body, refundId=path_id(refund.get("id")), refunded=self.snapshot())
        require(self.data["refunded"] == self.data["paid"], "ADMIN_DEFERRED_REFUND_CHANGED_TOKENS")
        row.update(refundId=self.data["refundId"], statusObserved="refunded", tokenReversalPolicy="deferred",
                   balanceChanged=False)

    def refund_replay(self, row):
        path = f"/api/admin/payments/{self.data['paymentId']}/refund-v2"
        result = self.admin.request("POST", path, self.data["refundBody"])
        require(result.get("idempotent") is True and result.get("refund", {}).get("id") == self.data["refundId"]
                and result.get("payment", {}).get("status") == "refunded", "ADMIN_REFUND_REPLAY_INVALID")
        self.admin.request("POST", path, {**self.data["refundBody"], "idempotency_key": uuid.uuid4().hex,
                           "amount": self.data["refundBody"]["amount"] + 1}, expected=(400,))
        require(self.snapshot() == self.data["refunded"], "ADMIN_REFUND_REPLAY_CHANGED_BALANCE")
        row.update(sameRefund=True, idempotent=True, excessRefundHttpStatus=400, balanceChanged=False)

    def post_refund_replay(self, row):
        result = self.simulate(self.data["paymentId"], "succeeded", expected=(200, 409))
        after = self.snapshot()
        status = self.payment(self.data["paymentId"])["status"]
        row.update(httpStatus=result.get("httpStatus", 200), before=financial_summary(self.data["refunded"]),
                   after=financial_summary(after), refundedStatePreserved=status == "refunded")
        require(after == self.data["refunded"] and status == "refunded", "ADMIN_POST_REFUND_REPLAY_REGRANTED")
        if row["httpStatus"] == 200:
            require(result.get("payment", {}).get("status") == "refunded", "ADMIN_REFUND_RESPONSE_STATE_MISMATCH")
        row["balanceChanged"] = False

    def cancellation(self, row):
        before = self.snapshot()
        _, _, payment = self.new_checkout(self.flow.owner)
        payment_id = self.data["cancelId"] = payment["id"]
        for _ in range(2):
            result = self.simulate(payment_id, "canceled")
            require(result.get("payment", {}).get("status") == "canceled"
                    and self.payment(payment_id)["status"] == "canceled", "ADMIN_CANCELLATION_INVALID")
        self.simulate(payment_id, "succeeded", expected=(409,))
        after = self.snapshot()
        row.update(paymentId=payment_id, before=financial_summary(before), after=financial_summary(after))
        require(after == before, "ADMIN_CANCELED_PAYMENT_CHANGED_BALANCE")
        row.update(repeatedCancellation="PASS", terminalChangeHttpStatus=409, balanceChanged=False)

    def audit(self, row):
        for action, entity, minimum in (("admin_simulate_payment", self.data["paymentId"], 2),
                ("billing_payment_refunded", self.data["refundId"], 1),
                ("admin_simulate_payment", self.data["cancelId"], 2)):
            value = self.admin.request("GET", f"/api/admin/audit-logs-v2?action={action}&limit=100")
            entries = [item for item in value["items"] if item.get("action") == action and item.get("entity_id") == entity]
            require(len(entries) >= minimum, "ADMIN_PAYMENT_AUDIT_MISSING")
        row.update(paymentTransitions="PRESENT", refund="PRESENT", cancellation="PRESENT", scope="EXERCISED_ACTIONS_ONLY")

    def other_balance(self, row):
        after = self.snapshot(self.flow.other)
        row.update(before=financial_summary(self.data["otherBefore"]), after=financial_summary(after))
        require(after == self.data["otherBefore"], "ADMIN_OTHER_USER_FINANCIAL_STATE_CHANGED")

    def run(self, code):
        self.step("bootstrap", lambda row: self.bootstrap(row, code))
        self.step("simulatorSafety", self.safety, ("bootstrap",))
        self.step("adminRights", self.rights, ("simulatorSafety",))
        self.step("legalSetup", self.setup, ("adminRights",))
        self.step("checkout", self.checkout, ("legalSetup",))
        for name, action in (("checkoutReplay", self.checkout_replay), ("paymentAccess", self.payment_access),
                             ("foreignCheckoutReplay", self.foreign_replay), ("paymentSuccess", self.success)):
            self.step(name, action, ("checkout",))
        self.step("successReplay", self.success_replay, ("paymentSuccess",))
        self.step("refund", self.refund, ("paymentSuccess",))
        self.step("refundReplay", self.refund_replay, ("refund",))
        self.step("postRefundReplay", self.post_refund_replay, ("refund",))
        self.step("cancellation", self.cancellation, ("legalSetup",))
        self.step("audit", self.audit, ("successReplay", "refund", "cancellation"))
        self.step("otherUserBalance", self.other_balance, ("legalSetup",))

    def close(self):
        failed = 0
        for client in self.flow.clients:
            try:
                client.request("POST", "/api/auth/session/logout-v2", {})
                client.request("GET", "/api/me-v2", expected=(401,))
            except Exception:
                failed += 1
            finally:
                client.cookies.clear()
        self.flow.credentials.clear()
        self.data.clear()
        return {"sessionCleanup": "FAIL" if failed else "PASS", "checkedClients": len(self.flow.clients),
                "failedSessions": failed, "remainingCookieJars": sum(bool(list(c.cookies)) for c in self.flow.clients),
                "fixtureData": "CALLER_OWNS_VOLUME_CLEANUP"}


def prove_admin(attestation: dict, receipt: Path, *, bootstrap_code: str) -> dict:
    """Caller must attest fresh, isolated volumes and remove them after this call."""
    origin = validate_target(attestation)
    require(attestation.get("adminFixture") == PROFILE and attestation.get("freshData") is True,
            "ADMIN_FRESH_ISOLATED_PROFILE_REQUIRED")
    require(isinstance(bootstrap_code, str) and re.fullmatch(r"[A-Za-z0-9_-]{32,128}", bootstrap_code) is not None,
            "ADMIN_EPHEMERAL_BOOTSTRAP_CODE_REQUIRED")
    receipt = Path(receipt)
    receipt.parent.mkdir(parents=True, exist_ok=True)
    with receipt.open("x", encoding="utf-8") as output:
        receipt.chmod(0o600)
        report = {"status": "FAIL", "sourceSha": attestation["sourceSha"], "project": attestation["project"],
                  "origin": origin, "profile": PROFILE, "startedAt": datetime.now(timezone.utc).isoformat(),
                  "livePayments": "NOT_RUN", "outboundDelivery": "NOT_RUN", "dockerLifecycle": "CALLER_OWNED"}
        probe = AdminProbe(attestation)
        try:
            probe.run(bootstrap_code)
        except Exception as error:
            report["errorCode"] = error_code(error)
        finally:
            report["checks"], report["cleanup"] = probe.checks, probe.close()
        if (report["checks"] and all(row["status"] == "PASS" for row in report["checks"].values())
                and report["cleanup"]["sessionCleanup"] == "PASS" and "errorCode" not in report):
            report["status"] = "PASS"
        report["finishedAt"] = datetime.now(timezone.utc).isoformat()
        json.dump(report, output, indent=2)
        output.write("\n")
    return report
