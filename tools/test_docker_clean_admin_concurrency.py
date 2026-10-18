"""Reject false AM-009 evidence. These protocol observations are not Docker proof."""
from contextlib import ExitStack
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tools import docker_clean_admin_concurrency as subject
from tools.docker_shadow_product import ProductError

PRIVATE = "private-bootstrap-cookie-body-never-in-receipt"


class Observations:
    """Bounded observed responses, with deliberately invalid outcomes for the probe."""
    def __init__(self, fault=None):
        self.fault, self.pairs = fault, 0
        self.clients = [SimpleNamespace(label=label, cookies=object()) for label in "ABC"]
        self.roles = {"A": "admin", "B": "user", "C": "user", "demo": "admin", "editorial": "user"}
        self.original = dict(self.roles)
        self.events = {name: {} for name in subject.LOGS}
        if fault == "third_admin":
            self.roles["editorial"] = "admin"
        self.probe = SimpleNamespace(admin=self.clients[0], fresh_fixture=True,
            flow=SimpleNamespace(other=self.clients[1], owner=self.clients[2], clients=tuple(self.clients),
                origin="http://127.0.0.1:48125", account_snapshot=lambda client: {"balance": 20, "session": client.label}))
        self.bootstrap = Mock(side_effect=self.recover)

    def recover(self, method, path, body):
        assert (method, path, body) == ("POST", "/api/auth/web-login", {"code": PRIVATE})
        self.roles["A"] = "admin"
        return {"ok": True}

    def me(self, client):
        label = client.label
        session = "A" if self.fault == "same_session" and label == "B" else label
        return {"user": label, "legacy": "web_" + label, "session": "session_" + session,
            "provider": "web_admin" if label == "A" else "web_email", "role": self.roles[label]}

    def users(self, actor):
        assert self.roles[actor.label] == "admin"
        return {key: {"legacy": {"demo": "demo_user", "editorial": "seed_editorial"}.get(key, "web_" + key),
                      "status": "active", "role": role} for key, role in self.roles.items()}

    def role(self, actor, target, role, reason):
        if self.fault == "restore_failure" and "final restore" in reason:
            raise RuntimeError(PRIVATE)
        before = self.roles[target]
        self.roles[target] = role
        key = str(sum(map(len, self.events.values())) + 1)
        self.events["audit"][key] = {"id": key, "action": "admin_change_role", "entity_type": "user",
            "entity_id": self.me(SimpleNamespace(label=target))["legacy"], "actor_internal_user_id": actor.label,
            "target_internal_user_id": target, "before": {"role": before}, "after": {"role": role, "reason": reason},
            "ip_address": PRIVATE}
        self.events["changed"][key] = {"id": key, "event_type": "admin_role_changed", "severity": "warning",
            "internal_user_id": target, "session_id": None,
            "details": {"actor_internal_user_id": actor.label, "role": role, "reason": reason}, "private": PRIVATE}

    def requests(self, clients, identities, reasons):
        self.pairs += 1
        self.role(clients[0], "B", "user", reasons[0])
        audit_id = next(reversed(self.events["audit"]))
        if self.fault == "missing_audit":
            del self.events["audit"][audit_id]
        self.events["denied"][str(self.pairs)] = {"id": str(self.pairs), "event_type": "trusted_admin_denied",
            "severity": "warning", "internal_user_id": "B", "session_id": "session_B", "details": None}
        if self.fault == "wrong_denied_session":
            self.events["denied"][str(self.pairs)]["session_id"] = "session_C"
        statuses = (200, 403)
        if self.fault == "two_successes":
            self.role(clients[1], "A", "user", reasons[1])
            statuses = (200, 200)
        starts = (1_000_000, 4_000_000 if self.fault == "no_overlap" else 2_000_000)
        return [{"httpStatus": status, "started": start, "finished": start + 2_000_000,
            "body": {"ok": True, "internal_user_id": identities[1-index]["user"], "role": "user"}
                if status == 200 else {"httpStatus": status}}
            for index, (status, start) in enumerate(zip(statuses, starts))]

    def run(self, row):
        with ExitStack() as stack:
            for name, action in (("_me", self.me), ("_users", self.users), ("_role", self.role),
                    ("_logs", lambda client: deepcopy(self.events)), ("_requests", self.requests)):
                stack.enter_context(patch.object(subject, name, side_effect=action))
            stack.enter_context(patch.object(subject, "HttpClient", return_value=SimpleNamespace(
                label="A", cookies=object(), request=self.bootstrap)))
            subject.prove_admin_concurrency(self.probe, row, PRIVATE)


class ConcurrencyEvidenceTests(unittest.TestCase):
    def test_inherited_seventeen_checks_gate_am009_and_its_failure_reaches_report(self):
        from tools.docker_clean_admin import prove_admin
        from tools.test_docker_clean_admin import ATTESTATION, CODE, Api, HttpClient
        for earlier_failure in (False, True):
            with self.subTest(earlier_failure=earlier_failure), tempfile.TemporaryDirectory() as directory:
                api = Api(dashboard_exception=earlier_failure)
                with patch.object(HttpClient, "request", autospec=True, side_effect=api.request), \
                        patch("tools.docker_clean_admin.prove_models"), \
                        patch("tools.docker_clean_admin.prove_admin_concurrency",
                              side_effect=ProductError("ADMIN_AM009_ROLE_EVIDENCE_MISMATCH")) as action:
                    report = prove_admin(ATTESTATION, Path(directory) / "receipt.json", bootstrap_code=CODE)
                inherited = dict(report["checks"])
                am009 = inherited.pop("adminConcurrency")
                self.assertEqual(len(inherited), 17)
                self.assertEqual(report["status"], "FAIL")
                self.assertEqual(am009["status"], "NOT_RUN" if earlier_failure else "FAIL")
                self.assertEqual(action.call_count, 0 if earlier_failure else 1)
                self.assertEqual(report["cleanup"]["sessionCleanup"], "PASS")
                if not earlier_failure:
                    self.assertTrue(all(item["status"] == "PASS" for item in inherited.values()))

    def test_five_pairs_keep_one_admin_and_restore_owned_roles_without_financial_effects(self):
        observed, row = Observations(), {}
        observed.run(row)
        self.assertEqual(observed.pairs, 5)
        self.assertEqual(observed.roles, observed.original)
        self.assertEqual(row["restoration"], "PASS")
        self.assertTrue(row["accountsUnchanged"])
        self.assertTrue(all(item["status"] == "PASS" and item["activeAdminsAfter"] == 1
            and item["newEvidenceRows"] == {"audit": 1, "changed": 1, "denied": 1} for item in row["trials"]))
        self.assertNotIn(PRIVATE, json.dumps(row))
        observed.bootstrap.assert_not_called()

    def test_third_admin_or_same_session_refuses_before_any_mutation(self):
        for fault in ("third_admin", "same_session"):
            with self.subTest(fault=fault):
                observed, row = Observations(fault), {}
                before = dict(observed.roles)
                with self.assertRaises(ProductError):
                    observed.run(row)
                self.assertEqual(observed.roles, before)
                self.assertEqual(observed.pairs, 0)
                self.assertFalse(any(observed.events.values()))
                observed.bootstrap.assert_not_called()

    def test_false_acceptance_cases_fail_first_pair_but_attempt_exact_restoration(self):
        for fault, code in (("no_overlap", "CLIENT_OVERLAP_NOT_OBSERVED"),
                ("two_successes", "RECIPROCAL_STATUS_MISMATCH"), ("missing_audit", "ROLE_EVIDENCE_MISMATCH"),
                ("wrong_denied_session", "ROLE_EVIDENCE_MISMATCH")):
            with self.subTest(fault=fault):
                observed, row = Observations(fault), {}
                with self.assertRaisesRegex(ProductError, "ADMIN_AM009_" + code):
                    observed.run(row)
                self.assertEqual(observed.pairs, 1)
                self.assertEqual(row["trials"][0]["status"], "FAIL")
                self.assertEqual(row["restoration"], "PASS")
                self.assertEqual(observed.roles, observed.original)
                self.assertEqual(observed.bootstrap.call_count, int(fault == "two_successes"))
                self.assertNotIn(PRIVATE, json.dumps(row))

    def test_successful_pairs_do_not_hide_restoration_failure(self):
        observed, row = Observations("restore_failure"), {}
        with self.assertRaisesRegex(ProductError, "ADMIN_AM009_RESTORATION_FAILED"):
            observed.run(row)
        self.assertEqual(observed.pairs, 5)
        self.assertEqual(row["restoration"], "FAIL")
        self.assertNotIn(PRIVATE, json.dumps(row))

    def test_truncated_user_list_cannot_hide_another_administrator(self):
        client = SimpleNamespace(request=Mock(return_value={"items": [], "total": 201, "limit": 200, "offset": 0}))
        with self.assertRaisesRegex(ProductError, "ADMIN_AM009_INCOMPLETE_LIST"):
            subject._items(client, "/api/admin/users-v2")

    def test_pair_uses_two_client_threads_and_redacts_untrusted_status_or_exception(self):
        clients, calls = [], []
        rendezvous = threading.Barrier(2, timeout=2)
        def request(index, method, path, body, *, expected):
            calls.append((index, threading.get_ident(), method, path, body, expected))
            rendezvous.wait()
            if index:
                raise RuntimeError(PRIVATE)
            return {"httpStatus": PRIVATE}
        for index in range(2):
            clients.append(SimpleNamespace(request=lambda *args, i=index, **kw: request(i, *args, **kw)))
        # The request barrier orders starts before finishes even within one OS clock tick.
        clock = SimpleNamespace(monotonic_ns=iter((1, 2, 3, 4)).__next__)
        with patch.object(subject, "time", clock):
            result = subject._requests(clients, [{"user": "A"}, {"user": "B"}], ["trial A", "trial B"])
        self.assertFalse(rendezvous.broken)
        self.assertEqual(len({item[1] for item in calls}), 2)
        self.assertEqual({item[3] for item in calls}, {"/api/admin/users/A/role-v2", "/api/admin/users/B/role-v2"})
        self.assertTrue(all(item["httpStatus"] == 0 for item in result))
        self.assertGreater(min(item["finished"] for item in result), max(item["started"] for item in result))
        self.assertNotIn(PRIVATE, json.dumps(result))


if __name__ == "__main__":
    unittest.main()
