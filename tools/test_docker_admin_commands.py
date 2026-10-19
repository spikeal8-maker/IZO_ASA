"""Negative ownership/admission tests; the separate workflow supplies real Docker evidence."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import docker_admin_commands as proof
from tools import docker_admin_commands_runtime as runtime


SHA = "6" * 40
RUN = "123456-1"
TEST_BASE = Path(tempfile.gettempdir()).resolve() / "admin-proof-unit-scope"
ROOT = TEST_BASE / "owned-repository"
OUTPUT = TEST_BASE / "runner-temp" / "admin-command-proof"
ENV = {"GITHUB_ACTIONS": "true", "RUNNER_ENVIRONMENT": "github-hosted", "RUNNER_OS": "Linux",
       "GITHUB_RUN_ID": "123456", "GITHUB_RUN_ATTEMPT": "1", "RUNNER_TEMP": str(OUTPUT.parent)}


def owned(kind: str) -> dict:
    return {"Labels": proof.labels(SHA, RUN)} if kind == "volume" else {"Config": {"Labels": proof.labels(SHA, RUN)}}


def phases() -> dict:
    return {
        "seed": {"status": "PASS", "phase": "seed", "targets": 10, "browserTargets": 4},
        "exercise": {"status": "PASS", "phase": "exercise", "races": 10, "negativeCases": 12, "realHttp": True},
        "replay": {"status": "PASS", "phase": "replay", "realHttp": True, "replayedCommands": 10,
                   "sameSession": True, "sameLedgerAuditPlanDates": True, "browserReplays": 4,
                   "sqliteIntegrity": "ok", "mediaSha256": "a" * 64},
    }


def valid_plan_effect():
    target = {"kind": "plan", "internal": "owned", "legacy": "owned-legacy", "actor": "test-admin",
              "plan": "pro", "durationDays": 35, "expectedGrant": 100, "delta": 25}
    payload = {"plan": "pro", "duration_days": 35, "reason": "controlled", "idempotency_key": "controlled-command-001"}
    start, expiry = "2026-10-19T00:00:00+00:00", "2026-11-23T00:00:00+00:00"
    response = {"ok": True, "internal_user_id": "owned", "plan": "pro", "activation": {
        "plan": "pro", "plan_started_at": start, "plan_expires_at": expiry, "monthly_tokens_granted": 100}}
    grant_key = f"tariff:admin:command:{start}"
    user = {"id": "owned-legacy", "role": "user", "token_balance": 150, "plan": "pro", "plan_started_at": start,
            "plan_expires_at": expiry, "plan_next_token_grant_at": "2026-11-19T00:00:00+00:00", "plan_monthly_token_grant": 100}
    binding = {"actor": "test-admin", "target": "owned", "operation": "activate-plan-v2",
               "payload": {key: value for key, value in payload.items() if key != "idempotency_key"}}
    ledger = {"id": "ledger", "delta": 100, "reason": "tariff_monthly_grant", "meta_json": json.dumps({
        "source": "admin", "source_id": "command", "grant_key": grant_key, "period_start": start})}
    grant = {"id": "grant", "amount": 100, "plan": "pro", "grant_key": grant_key,
             "source_id": "command", "source": "admin", "period_start": start}
    audit = {"id": "audit", "actor_internal_user_id": "test-admin", "entity_id": "owned-legacy", "action": "admin_change_plan",
             "after_json": json.dumps({"admin_command_id": "command", "reason": "controlled", "plan": "pro", "duration_days": 35})}
    command = {"id": "command", "command_key": payload["idempotency_key"], "actor_internal_user_id": "test-admin",
               "target_internal_user_id": "owned", "operation": "activate-plan-v2", "response_json": json.dumps(response), "created_at": start,
               "request_sha256": hashlib.sha256(json.dumps(binding, sort_keys=True, separators=(",", ":")).encode()).hexdigest()}
    observed = {"user": user, "counts": {"ledger": 1, "grants": 1, "audit": 1, "commands": 1},
                "rows": {"ledger": [ledger], "grants": [grant], "audit": [audit], "commands": [command]},
                "rowSha256": {name: "f" * 64 for name in ("ledger", "grants", "audit", "commands")}}
    return target, payload, response, observed


class AdmissionTests(unittest.TestCase):
    def test_remote_context_tls_and_builder_overrides_fail_before_any_command(self):
        for key in proof.DOCKER_OVERRIDES:
            with self.subTest(key=key), patch.object(proof, "command") as command, self.assertRaises(proof.ProofError):
                proof.admission(ROOT, OUTPUT, SHA, {**ENV, key: "remote-or-tls-override"})
            command.assert_not_called()
            with patch.object(proof.subprocess, "run") as child, self.assertRaises(proof.ProofError):
                proof.command(["docker", "volume", "create", "must-not-be-created"], env={key: "override"})
            child.assert_not_called()

    def test_every_docker_command_uses_explicit_local_endpoint_and_sanitized_environment(self):
        args = [["info"], ["build", "."], ["run", "owned"], ["volume", "create", "owned"],
                ["exec", "owned", "true"], ["container", "stop", "owned"], ["image", "rm", "owned"]]
        env = {key: "" for key in proof.DOCKER_OVERRIDES}
        env["PATH"] = "test-binary-path"
        with patch.object(Path, "is_socket", return_value=True), patch.object(proof.subprocess, "run",
                return_value=SimpleNamespace(returncode=0, stdout="ok\n", stderr="")) as child:
            for tail in args:
                self.assertEqual(proof.command(["docker", *tail], env=env), "ok")
                self.assertEqual(child.call_args.args[0], ["docker", "--host", proof.DOCKER_ENDPOINT, *tail])
                self.assertEqual(child.call_args.kwargs["env"], {"PATH": "test-binary-path"})

    def test_absent_local_socket_never_falls_back_to_any_context(self):
        with patch.object(Path, "is_socket", return_value=False), patch.object(proof.subprocess, "run") as child:
            with self.assertRaisesRegex(proof.ProofError, "LOCAL_DOCKER_SOCKET_MISSING"):
                proof.command(["docker", "info"], env={})
            child.assert_not_called()

    def test_preflight_retains_local_endpoint_and_redacted_engine_identity(self):
        with patch.object(proof, "command", return_value="linux|owned-daemon"), patch.object(proof, "inspect", return_value=None):
            result = proof.preflight(proof.resource_names(SHA, RUN))
        self.assertEqual(result, {"endpoint": "unix:///var/run/docker.sock", "socketVerified": True, "osType": "linux",
                                 "daemonIdSha256": hashlib.sha256(b"owned-daemon").hexdigest()})

    def test_non_hosted_wrong_os_invalid_run_or_source_never_queries_docker(self):
        cases = [("GITHUB_ACTIONS", "false"), ("RUNNER_ENVIRONMENT", "self-hosted"),
                 ("RUNNER_OS", "Windows"), ("GITHUB_RUN_ID", "../foreign"), ("GITHUB_RUN_ATTEMPT", "")]
        with patch.object(proof, "command") as command, patch.object(proof.sys, "platform", "linux"):
            for key, value in cases:
                with self.subTest(key=key), self.assertRaises(proof.ProofError):
                    proof.admission(ROOT, OUTPUT, SHA, {**ENV, key: value})
            with self.assertRaises(proof.ProofError):
                proof.admission(ROOT, OUTPUT, "main", ENV)
            command.assert_not_called()

    def test_output_cannot_escape_runner_temp_or_write_checkout(self):
        cases = [(TEST_BASE / "foreign", ENV), (Path(ENV["RUNNER_TEMP"]), ENV),
                 (ROOT / "receipt", {**ENV, "RUNNER_TEMP": str(TEST_BASE)})]
        with patch.object(proof, "command") as command, patch.object(proof.sys, "platform", "linux"):
            for output, env in cases:
                with self.subTest(output=output), self.assertRaises(proof.ProofError):
                    proof.admission(ROOT, output, SHA, env)
            command.assert_not_called()

    def test_sha_dirty_checkout_and_wrong_repository_are_rejected_before_docker(self):
        cases = [["f" * 40], [SHA, " M backend/main.py"], [SHA, "", "https://example.invalid/foreign.git"]]
        for responses in cases:
            with self.subTest(responses=responses), patch.object(proof.sys, "platform", "linux"):
                with patch.object(proof, "command", side_effect=responses) as command, self.assertRaises(proof.ProofError):
                    proof.admission(ROOT, OUTPUT, SHA, ENV)
                self.assertTrue(all(call.args[0][0] == "git" for call in command.call_args_list))

    def test_exact_clean_owned_source_is_admitted(self):
        with patch.object(proof.sys, "platform", "linux"), patch.object(proof, "command", side_effect=[
            SHA, "", "https://github.com/spikeal8-maker/IZO_ASA.git",
        ]):
            self.assertEqual(proof.admission(ROOT, OUTPUT, SHA, ENV), RUN)

    def test_preexisting_reserved_name_is_rejected_even_if_label_claims_ownership(self):
        with patch.object(proof, "command", return_value="linux|owned-daemon") as command:
            with patch.object(proof, "inspect", return_value=owned("container")), self.assertRaises(proof.ProofError):
                proof.preflight(proof.resource_names(SHA, RUN))
            self.assertEqual(command.call_count, 1)


class OwnershipTests(unittest.TestCase):
    def test_every_owner_dimension_is_required_for_each_resource_kind(self):
        for kind in ("container", "volume", "image"):
            proof.require_owned(owned(kind), kind, SHA, RUN)
            for key in proof.labels(SHA, RUN):
                value = owned(kind)
                target = value["Labels"] if kind == "volume" else value["Config"]["Labels"]
                target[key] = "foreign"
                with self.subTest(kind=kind, key=key), self.assertRaises(proof.ProofError):
                    proof.require_owned(value, kind, SHA, RUN)

    def test_cleanup_refuses_every_foreign_resource_without_any_delete(self):
        names = proof.resource_names(SHA, RUN)
        with patch.object(proof, "inspect", return_value={"Labels": {}, "Config": {"Labels": {}}}):
            with patch.object(proof, "command") as command:
                errors = proof.clean(names, SHA, RUN)
        self.assertEqual(len(errors), 5)
        command.assert_not_called()

    def test_cleanup_targets_only_exact_owned_names_and_never_prunes(self):
        names = proof.resource_names(SHA, RUN)
        inspections = [item for kind in ("container", "container", "volume", "volume", "image") for item in (owned(kind), None)]
        with patch.object(proof, "inspect", side_effect=inspections), patch.object(proof, "command", return_value="") as command:
            self.assertEqual(proof.clean(names, SHA, RUN), [])
        self.assertEqual([call.args[0] for call in command.call_args_list], [
            ["docker", "container", "rm", "--force", names["api"]],
            ["docker", "container", "rm", "--force", names["seed"]],
            ["docker", "volume", "rm", names["data"]], ["docker", "volume", "rm", names["media"]],
            ["docker", "image", "rm", "--no-prune", names["image"]],
        ])

    def test_container_has_no_published_port_host_network_bind_or_inherited_secret_env(self):
        names = proof.resource_names(SHA, RUN)
        args = proof.container_args(names["api"], names, SHA, RUN)
        self.assertEqual(args[args.index("--network") + 1], "none")
        self.assertEqual(args[args.index("--user") + 1], "10001:10001")
        self.assertFalse(set(args).intersection({"--publish", "-p", "--publish-all", "-P", "--privileged", "--env-file", "--volume", "-v"}))
        mounts = [args[i + 1] for i, value in enumerate(args) if value == "--mount"]
        self.assertEqual(len(mounts), 2)
        self.assertTrue(all(value.startswith("type=volume,source=izo-admin-") for value in mounts))
        environment = [args[i + 1] for i, value in enumerate(args) if value == "--env"]
        self.assertTrue(all("=" in value for value in environment))
        self.assertIn("SESSION_TOKEN_HMAC_KEY=", environment)

    def test_preexisting_identity_loss_fails_but_new_build_cache_is_allowed(self):
        before = {"images": ["original"], "volumes": ["foreign"]}
        proof.assert_foreign_identities(before, {"images": ["original", "pulled-base"], "volumes": ["foreign"]})
        with self.assertRaises(proof.ProofError):
            proof.assert_foreign_identities(before, {"images": ["original"], "volumes": []})


class EvidenceTests(unittest.TestCase):
    def test_plan_proof_rejects_unchanged_tariff_missing_dates_or_wrong_duration(self):
        target, payload, response, original = valid_plan_effect()
        with patch.object(runtime, "state", return_value=deepcopy(original)):
            self.assertEqual(runtime.verified_effect(target, response, payload)["user"]["plan"], "pro")
        for column, value in (("plan", "mini"), ("plan_started_at", None), ("plan_expires_at", None),
                              ("plan_expires_at", "2026-11-22T00:00:00+00:00"), ("plan_next_token_grant_at", None)):
            broken = deepcopy(original)
            broken["user"][column] = value
            with self.subTest(column=column), patch.object(runtime, "state", return_value=broken), self.assertRaises(AssertionError):
                runtime.verified_effect(target, response, payload)

    def test_plan_proof_rejects_forged_amount_source_command_or_audit_binding(self):
        target, payload, response, original = valid_plan_effect()
        for table, column, value in (("ledger", "delta", 99), ("grants", "source_id", "foreign"),
                                     ("commands", "command_key", "other-key"), ("audit", "actor_internal_user_id", "foreign")):
            broken = deepcopy(original)
            broken["rows"][table][0][column] = value
            with self.subTest(table=table), patch.object(runtime, "state", return_value=broken), self.assertRaises(AssertionError):
                runtime.verified_effect(target, response, payload)

    def test_runtime_bridge_rejects_other_origins_providers_mutations_and_foreign_targets_before_http(self):
        fixture = {"sessions": {"admin": "synthetic-test-session"}, "browserTargets": [{"internal": "owned", "kind": "tokens"}]}
        cases = [("GET", "http://example.invalid/api/me-v2"), ("GET", "//example.invalid/api/me-v2"),
                 ("GET", "/api/admin/models-page"), ("POST", "/api/admin/payments/reconcile-v2"),
                 ("POST", "/api/admin/users/foreign/tokens-v2"), ("POST", "/api/admin/users/owned/plan-v2"),
                 ("DELETE", "/api/admin/users/owned/tokens-v2"), ("POST", "/api/admin/users/owned/tokens-v2?bypass=1")]
        with patch.object(runtime, "private", return_value=fixture), patch.object(runtime, "request") as request:
            for method, path in cases:
                with self.subTest(method=method, path=path), self.assertRaises(RuntimeError):
                    runtime.bridge(RUN, json.dumps({"method": method, "path": path, "payload": {}}))
            request.assert_not_called()

    def test_browser_proof_needs_all_four_real_ui_http_retry_effect_pairs(self):
        value = {"status": "PASS", "sourceSha": SHA, "realCrm": True, "realHttp": True, "blockedRequests": [],
                 "cases": [{"viewport": viewport, "kind": kind, "status": "PASS", "httpRequests": 2,
                            "lostResponseInjected": True, "reloadedInput": True, "sameKeyResponseAndState": True,
                            "effects": {"ledger": 1, "grants": int(kind == "plan"), "audit": 1, "commands": 1}}
                           for viewport in ("desktop", "mobile") for kind in ("tokens", "plan")]}
        proof.validate_browser(value, SHA)
        for key in value:
            broken = deepcopy(value)
            del broken[key]
            with self.subTest(key=key), self.assertRaises(proof.ProofError):
                proof.validate_browser(broken, SHA)
        for key in value["cases"][0]:
            broken = deepcopy(value)
            del broken["cases"][0][key]
            with self.subTest(case_key=key), self.assertRaises(proof.ProofError):
                proof.validate_browser(broken, SHA)

    def test_missing_duplicate_wrong_phase_or_failed_receipt_cannot_pass(self):
        valid = proof.PREFIX + json.dumps(phases()["seed"])
        self.assertEqual(proof.receipt("startup log\n" + valid, "seed"), phases()["seed"])
        for raw in ("", valid + "\n" + valid, valid.replace('"PASS"', '"FAIL"')):
            with self.subTest(raw=raw), self.assertRaises(proof.ProofError):
                proof.receipt(raw, "seed")
        with self.assertRaises(proof.ProofError):
            proof.receipt(valid, "replay")

    def test_required_real_http_race_recreate_and_persistence_evidence_cannot_be_omitted(self):
        proof.validate_proof(phases())
        for name, value in phases().items():
            for key in value:
                candidate = deepcopy(phases())
                del candidate[name][key]
                with self.subTest(phase=name, key=key), self.assertRaises(proof.ProofError):
                    proof.validate_proof(candidate)


if __name__ == "__main__":
    unittest.main()
