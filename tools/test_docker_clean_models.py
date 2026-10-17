"""Failure bookkeeping for normal HTTP model probes; these are not Docker receipts."""
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest

from tools.docker_clean_admin import AdminProbe
from tools import docker_clean_models as models
from tools.docker_shadow_product import ProductError

PRIVATE = "private-settings-must-not-enter-receipts"


class ModelFixture:
    def __init__(self, *, missing=False, **faults):
        self.baseline = {**models.DEFAULTS, "fixturePrivate": PRIVATE}
        self.current = None if missing else deepcopy(self.baseline)
        if missing:
            self.baseline = deepcopy(models.DEFAULTS)
        self.calls, self.account_reads, self.was_changed = [], 0, False
        self.accounts, self.faults = [{"balance": 10, "ledger": []}, {"balance": 20, "ledger": []}], faults
        def client(role):
            return SimpleNamespace(role=role, request=lambda method, path, payload=None, **kw:
                                   self.request(role, method, path, payload, **kw))
        self.probe = SimpleNamespace(fresh_fixture=True, admin=client("admin"),
            flow=SimpleNamespace(owner=client("owner"), other=client("other"), guest=client("guest")),
            checks={name: {"status": "PASS"} for name in ("bootstrap", "simulatorSafety", "adminRights")})
        self.probe.snapshot = self.snapshot

    def snapshot(self, client):
        self.account_reads += 1
        return deepcopy(self.accounts[client.role == "other"])

    def request(self, role, method, path, payload=None, *, expected=(200,)):
        self.calls.append((role, method, path))
        status = 200 if role == "admin" else 401 if role == "guest" else 403
        if role != "admin" and self.faults.get("denial"):
            status = 200
            if method == "POST":
                self.current = deepcopy(payload["settings"])
        if status not in expected:
            raise ProductError("PRODUCT_HTTP_STATUS_UNEXPECTED_200")
        if status != 200:
            return {"httpStatus": status}
        if method == "POST":
            value = deepcopy(payload["settings"])
            changed = value != self.baseline
            if not changed and self.was_changed and self.faults.get("restore"):
                raise OSError(PRIVATE)
            self.current = value
            self.was_changed |= changed
            if changed and self.faults.get("financial"):
                self.accounts[1]["balance"] += int(self.faults["financial"] == "balance")
                self.accounts[1]["ledger"].append("unexpected")
            if changed and self.faults.get("lost"):
                raise OSError(PRIVATE)
            return {"ok": True, "key": models.KEY, "settings": deepcopy(value)}
        changed = self.current is not None and self.current != self.baseline
        if path == models.SETTINGS:
            value = self.baseline if changed and self.faults.get("stale_settings") else self.current
            return {"unrelated": PRIVATE, **({models.KEY: deepcopy(value)} if value is not None else {})}
        if path == models.CATALOG:
            return {"ok": True, "catalog": {"source": "fallback", "modelCount": 1}}
        if path == models.MODELS:
            value = self.baseline if changed and self.faults.get("stale_models") else self.current
            return {"catalog": [{"modelId": "fixture"}], "matrix": [], "economy": {}, "openrouter": {
                "keyConfigured": False, "catalogState": {"source": "fallback"}, "capabilityCatalog": [{}],
                "exchange": {"rate": None}, "backendPricing": [], "economy": {**models.DEFAULTS, **(value or {})}}}
        raise AssertionError(path)


class ModelProbeTests(unittest.TestCase):
    def execute(self, fixture):
        AdminProbe.step(fixture.probe, "modelEconomics", lambda row: models.prove_models(fixture.probe, row),
                        ("adminRights",))
        row = fixture.probe.checks["modelEconomics"]
        self.assertNotIn(PRIVATE, json.dumps(row))
        return row

    def test_roundtrip_restores_exact_baseline_and_reads_both_surfaces(self):
        fixture = ModelFixture()
        row = self.execute(fixture)
        self.assertEqual((row["status"], row["settingCleanup"], row["accountInvariance"]), ("PASS",) * 3)
        self.assertEqual(fixture.current, fixture.baseline)
        self.assertFalse(row["baselineCreatedInFreshFixture"])
        self.assertEqual(row["inferenceEconomics"], "NOT_VERIFIED")
        for path in (models.SETTINGS, models.MODELS):
            self.assertGreaterEqual(fixture.calls.count(("admin", "GET", path)), 3)

    def test_missing_setting_is_an_explicit_fixture_baseline(self):
        fixture = ModelFixture(missing=True)
        row = self.execute(fixture)
        self.assertEqual(row["status"], "PASS")
        self.assertTrue(row["baselineCreatedInFreshFixture"])
        self.assertEqual(fixture.current, models.DEFAULTS)

    def test_missing_fresh_or_bootstrap_admission_prevents_any_http(self):
        for kind in ("fresh", "bootstrap"):
            fixture = ModelFixture()
            if kind == "fresh":
                fixture.probe.fresh_fixture = False
            else:
                fixture.probe.checks["bootstrap"]["status"] = "FAIL"
            row = self.execute(fixture)
            self.assertEqual(row["errorCode"], "ADMIN_MODELS_FRESH_ADMISSION_REQUIRED")
            self.assertEqual((fixture.calls, fixture.account_reads), ([], 0))

    def test_stale_settings_or_derived_read_cannot_pass_and_still_restore(self):
        for fault in ("stale_settings", "stale_models", "lost", "denial"):
            with self.subTest(fault=fault):
                fixture = ModelFixture(**{fault: True})
                row = self.execute(fixture)
                self.assertEqual(row["status"], "FAIL")
                self.assertEqual((row["settingCleanup"], row["accountInvariance"]), ("PASS", "PASS"))
                self.assertEqual(fixture.current, fixture.baseline)

    def test_restore_failure_does_not_suppress_account_verification_or_fail_status(self):
        fixture = ModelFixture(restore=True)
        row = self.execute(fixture)
        self.assertEqual((row["status"], row["settingCleanup"], row["accountInvariance"]), ("FAIL", "FAIL", "PASS"))
        self.assertEqual(fixture.account_reads, 4)
        self.assertEqual(row["errorCode"], "ADMIN_MODELS_CLEANUP_FAILED")

    def test_other_user_balance_and_ledger_change_is_failure_after_successful_restore(self):
        for kind in ("balance", "ledger"):
            fixture = ModelFixture(financial=kind)
            row = self.execute(fixture)
            self.assertEqual((row["status"], row["settingCleanup"], row["accountInvariance"]), ("FAIL", "PASS", "FAIL"))
            self.assertEqual(fixture.current, fixture.baseline)


if __name__ == "__main__":
    unittest.main()
