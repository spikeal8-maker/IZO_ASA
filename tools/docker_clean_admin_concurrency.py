"""AM-009: five reciprocal role requests in the admitted, single-API fixture.

Uses existing independent sessions and ordinary HTTP only. Error bodies remain
discarded by HttpClient; the losing request is identified by security evidence.
The caller owns process identity, the 300-second fixture and session cleanup.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import threading
import time
import uuid

from tools.docker_shadow_product import HttpClient, ProductError, path_id

LOGS = {
    "audit": "/api/admin/audit-logs-v2?action=admin_change_role",
    "changed": "/api/admin/security-events-v2?event_type=admin_role_changed",
    "denied": "/api/admin/security-events-v2?event_type=trusted_admin_denied",
}


def _require(value, code):
    if not value:
        raise ProductError("ADMIN_AM009_" + code)


def _digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def _items(client, path):
    value = client.request("GET", path + ("&" if "?" in path else "?") + "limit=200&offset=0")
    items = value.get("items")
    _require(isinstance(items, list) and type(value.get("total")) is int
             and value["total"] == len(items) <= 200 and value.get("offset") == 0
             and value.get("limit") == 200, "INCOMPLETE_LIST")
    return items


def _users(client):
    items = _items(client, "/api/admin/users-v2")
    result = {path_id(item.get("internal_user_id")): {
        "legacy": path_id(item.get("legacy_user_id")), "role": item.get("role"),
        "status": item.get("status")} for item in items}
    _require(len(result) == len(items) and all(item["role"] in {"admin", "user"}
             and item["status"] == "active" for item in result.values()), "USER_STATE_INVALID")
    return result


def _me(client):
    value = client.request("GET", "/api/me-v2")
    _require(value.get("status") == "active" and value.get("account", {}).get("role")
             in {"user", "admin"}, "SESSION_INVALID")
    return {"user": path_id(value.get("internal_user_id")), "legacy": path_id(value.get("legacy_user_id")),
            "session": path_id(value.get("session", {}).get("session_id")),
            "provider": value.get("session", {}).get("provider"), "role": value["account"]["role"]}


def _role(client, target, role, reason):
    value = client.request("POST", f"/api/admin/users/{path_id(target)}/role-v2", {"role": role, "reason": reason})
    _require(value == {"ok": True, "internal_user_id": target, "role": role}, "ROLE_RESPONSE_INVALID")


def _logs(client):
    result = {}
    for name, path in LOGS.items():
        items = _items(client, path)
        result[name] = {path_id(item.get("id")): item for item in items}
        _require(len(result[name]) == len(items), "LOG_ID_COLLISION")
    return result


def _requests(clients, identities, reasons):
    barrier = threading.Barrier(2, timeout=8)

    def send(index):
        result = {"httpStatus": 0, "started": 0, "finished": 0}
        try:
            barrier.wait()
            result["started"] = time.monotonic_ns()
            value = clients[index].request("POST", f"/api/admin/users/{identities[1-index]['user']}/role-v2",
                {"role": "user", "reason": reasons[index]}, expected=(200, 403))
            status = value.get("httpStatus", 200)
            result["httpStatus"] = status if type(status) is int and status in {200, 403} else 0
            if result["httpStatus"] == 200:
                result["body"] = value
        except Exception:
            result["requestFailed"] = True
        finally:
            result["finished"] = time.monotonic_ns()
        return result

    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="am009") as pool:
        futures = [pool.submit(send, index) for index in range(2)]
        return [future.result() for future in futures]


def _evidence(before, after, winner, loser, reason, row):
    expected = {
        "audit": {"action": "admin_change_role", "actor_internal_user_id": winner["user"],
            "target_internal_user_id": loser["user"], "entity_type": "user", "entity_id": loser["legacy"],
            "before": {"role": "admin"}, "after": {"role": "user", "reason": reason}},
        "changed": {"event_type": "admin_role_changed", "severity": "warning",
            "internal_user_id": loser["user"], "session_id": None,
            "details": {"actor_internal_user_id": winner["user"], "role": "user", "reason": reason}},
        "denied": {"event_type": "trusted_admin_denied", "severity": "warning",
            "internal_user_id": loser["user"], "session_id": loser["session"], "details": None},
    }
    row["newEvidenceRows"] = {}
    for name in LOGS:
        _require(all(after[name].get(key) == value for key, value in before[name].items()), "PRIOR_LOG_CHANGED")
        added = [value for key, value in after[name].items() if key not in before[name]]
        row["newEvidenceRows"][name] = len(added)
        _require(len(added) == 1 and all(added[0].get(key) == value for key, value in expected[name].items()),
                 "ROLE_EVIDENCE_MISMATCH")
        row.setdefault("evidenceIdSha256", {})[name] = _digest(added[0]["id"])


class _RoleProbe:
    def __init__(self, probe, row):
        self.probe, self.row = probe, row
        self.clients = (probe.admin, probe.flow.other)
        self.prefix = "AM009 " + uuid.uuid4().hex
        self.identities, self.baseline, self.accounts = [], {}, []

    def expected_users(self, admins):
        return {key: {**value, "role": "admin" if key in admins else "user"}
                for key, value in self.baseline.items()}

    def trial(self, number):
        ids = self.identities
        _require(_users(self.clients[0]) == self.expected_users({item["user"] for item in ids}), "TWO_ADMINS_REQUIRED")
        for client, identity in zip(self.clients, ids):
            _require(_me(client) == {**identity, "role": "admin"}, "SESSION_CHANGED")
        before = _logs(self.clients[0])
        reasons = [f"{self.prefix} trial{number} {label}" for label in ("A_to_B", "B_to_A")]
        row = {"trial": number, "status": "FAIL"}
        self.row["trials"].append(row)
        results = _requests(self.clients, ids, reasons)
        row["httpStatuses"] = [item["httpStatus"] for item in results]
        origin = min(item["started"] for item in results)
        row["requestIntervalsMs"] = [[round((item[key] - origin) / 1e6, 3)
                                     for key in ("started", "finished")] for item in results]
        overlap = min(item["finished"] for item in results) - max(item["started"] for item in results)
        row["clientOverlapMs"] = round(overlap / 1e6, 3)
        current = [_me(client) for client in self.clients]
        row["participantRolesAfter"] = [item["role"] for item in current]
        _require(sorted(row["httpStatuses"]) == [200, 403], "RECIPROCAL_STATUS_MISMATCH")
        _require(all(item["started"] > 0 for item in results) and overlap > 0, "CLIENT_OVERLAP_NOT_OBSERVED")
        winner_index = row["httpStatuses"].index(200)
        winner, loser = ids[winner_index], ids[1-winner_index]
        _require(results[winner_index]["body"] == {"ok": True, "internal_user_id": loser["user"], "role": "user"},
                 "ROLE_RESPONSE_INVALID")
        _require(current[winner_index] == {**winner, "role": "admin"}
                 and current[1-winner_index] == {**loser, "role": "user"}, "SESSION_OR_ROLE_CHANGED")
        surviving = self.clients[winner_index]
        _require(_users(surviving) == self.expected_users({winner["user"]}), "SURVIVING_ADMIN_STATE_INVALID")
        row.update(winner="AB"[winner_index], activeAdminsAfter=1, losingSessionRetained=True)
        _evidence(before, _logs(surviving), winner, loser, reasons[winner_index], row)
        _role(surviving, loser["user"], "admin", f"{self.prefix} restore trial{number}")
        _require(_users(surviving) == self.expected_users({item["user"] for item in ids}), "TRIAL_RESTORE_FAILED")
        row.update(status="PASS", pairRestored=True)

    def restore(self, code):
        row = self.row
        row.update(restoration="FAIL", accountsUnchanged=False)
        try:
            # Read ordinary /me before any repair; never use bootstrap to retry a failed pair.
            current = [_me(client) for client in self.clients]
            actor = next((client for client, identity in zip(self.clients, current) if identity["role"] == "admin"), None)
            if actor is None:
                row["emergencyBootstrapUsed"] = True
                actor = HttpClient(self.probe.flow.origin)
                self.probe.flow.clients = (*self.probe.flow.clients, actor)
                actor.request("POST", "/api/auth/web-login", {"code": code})
                restored = _me(actor)
                _require(restored["user"] == self.identities[0]["user"] and restored["role"] == "admin"
                         and restored["provider"] == "web_admin", "BOOTSTRAP_RESTORE_INVALID")
            users = _users(actor)
            first = self.identities[0]["user"]
            if users[first]["role"] != "admin":
                _role(actor, first, "admin", self.prefix + " final restore A")
                actor = self.clients[0]
            for target in (self.demo, self.identities[1]["user"]):
                role = self.baseline[target]["role"]
                if users[target]["role"] != role:
                    _role(actor, target, role, self.prefix + " final restore owned role")
            _require(_users(actor) == self.baseline, "FINAL_ROLES_CHANGED")
            row["rolesRestored"] = True
            for client, before in zip((*self.clients, self.probe.flow.owner), self.accounts):
                _require(self.probe.flow.account_snapshot(client) == before, "ACCOUNT_STATE_CHANGED")
            row.update(restoration="PASS", accountsUnchanged=True, finalActiveAdmins=2)
        except Exception:
            row["restorationErrorCode"] = "ADMIN_AM009_RESTORATION_FAILED"

    def run(self, code):
        _require(self.probe.fresh_fixture, "FRESH_FIXTURE_REQUIRED")
        _require(self.clients[0] is not self.clients[1] and self.clients[0].cookies is not self.clients[1].cookies,
                 "INDEPENDENT_CLIENTS_REQUIRED")
        self.identities = [_me(client) for client in self.clients]
        a, b = self.identities
        control = _me(self.probe.flow.owner)
        _require(len({item["user"] for item in (a, b, control)}) == 3
                 and len({item["session"] for item in (a, b, control)}) == 3
                 and (a["role"], b["role"], control["role"]) == ("admin", "user", "user")
                 and (a["provider"], b["provider"], control["provider"]) == ("web_admin", "web_email", "web_email"),
                 "INDEPENDENT_IDENTITIES_REQUIRED")
        self.baseline = _users(self.clients[0])
        _require(all(self.baseline.get(item["user"]) == {"legacy": item["legacy"], "role": item["role"],
                     "status": "active"} for item in (a, b, control)), "USER_IDENTITY_MISMATCH")
        seeds = {item["legacy"]: key for key, item in self.baseline.items()}
        _require(len(seeds) == len(self.baseline) and set(seeds) == {
            a["legacy"], b["legacy"], control["legacy"], "demo_user", "seed_editorial"}, "OWNED_IDENTITIES_REQUIRED")
        self.demo = seeds["demo_user"]
        _require(self.baseline == self.expected_users({a["user"], self.demo}), "INITIAL_ADMINS_INVALID")
        clients = (*self.clients, self.probe.flow.owner)
        for client in clients:
            self.probe.flow.account_snapshot(client)  # Warm lazy account reconciliation before the baseline.
        self.accounts = [self.probe.flow.account_snapshot(client) for client in clients]
        self.row.update(case="AM-009", requiredTrials=5, trials=[], emergencyBootstrapUsed=False,
            participants=[{"label": label, "userIdSha256": _digest(item["user"]),
                "sessionIdSha256": _digest(item["session"]), "provider": item["provider"]}
                for label, item in zip("AB", self.identities)])
        try:
            _role(self.clients[0], self.demo, "user", self.prefix + " setup owned demo")
            _role(self.clients[0], b["user"], "admin", self.prefix + " setup B")
            for number in range(1, 6):
                self.trial(number)
        finally:
            self.restore(code)
        _require(self.row["restoration"] == "PASS", "RESTORATION_FAILED")


def prove_admin_concurrency(probe, row, bootstrap_code):
    """Called only after the inherited 17 admin checks pass; never starts an API."""
    _RoleProbe(probe, row).run(bootstrap_code)
