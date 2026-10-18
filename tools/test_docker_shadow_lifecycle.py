"""Reject unsafe fast fixture recycles; no Docker runtime is simulated as PASS."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
from unittest import TestCase
from unittest.mock import Mock, patch

from tools import docker_clean_recovery as recovery
from tools.docker_shadow import OWNER, Shadow, ShadowError
from tools.docker_clean_recovery import RecoveryError, RecoveryRun
from tools.test_docker_clean_recovery import target as recovery_target
from tools.test_docker_clean_workers import rows
from tools.test_docker_shadow_roles import IMAGE, PROJECT

SHA = "a" * 40


def stack():
    result = rows()
    for row in result:
        row["RestartCount"] = 0
        row["State"]["Health"] = {"Status": "healthy", "FailingStreak": 0, "Log": []}
        service = row["Config"]["Labels"]["com.docker.compose.service"]
        if service in {"guard", "web"}:
            row["Mounts"] = []
            row["Config"]["User"] = "0:0" if service == "guard" else "101:101"
        if service == "guard":
            row["HostConfig"].update(NetworkMode=PROJECT + "_shadow", Dns=["127.0.0.1"],
                CapAdd=["NET_ADMIN", "SETUID", "SETGID"], PortBindings={
                "8080/tcp": [{"HostIp": "127.0.0.1", "HostPort": "48125"}],
                "8000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "48126"}]})
            row["NetworkSettings"]["Networks"] = {PROJECT + "_shadow": {"NetworkID": "9" * 64}}
    return result


def fixture_shadow(before=None, after=None):
    shadow = Shadow(PROJECT, SHA, fixture=True)
    before = stack() if before is None else before
    shadow.source_guard = Mock()
    shadow.config = Mock(return_value={"services": {row["Config"]["Labels"]["com.docker.compose.service"]:
        {"image": "fixture-shared"} for row in before}})
    shadow.image_guard = Mock(return_value={name: IMAGE for name in shadow.config()["services"]})
    shadow.ownership_guard = Mock(side_effect=[before, deepcopy(before) if after is None else after])
    shadow.compose = Mock()
    return shadow


class OwnedInventoryTests(TestCase):
    def inventory(self):
        shadow = Shadow(PROJECT, SHA, fixture=True)
        containers = stack()
        resources = {kind: [{"Name": PROJECT + "_" + name, "Labels": {
            "io.izo.owner": OWNER, "com.docker.compose.project": PROJECT}} for name in names]
            for kind, names in (("volume", ("sqlite-data", "media-data", "worker_ipc")), ("network", ("shadow",)))}
        def docker(*args, **kwargs):
            if args[0] == "ps":
                return " ".join(row["Id"] for row in containers)
            if args[0] == "inspect":
                return json.dumps(containers)
            kind, command = args[:2]
            if command == "ls":
                selected = resources[kind]
                if "--filter" in args:
                    selected = [row for row in selected if row["Labels"].get("com.docker.compose.project") == PROJECT]
                return "\n".join(row["Name"] for row in selected)
            self.assertEqual(command, "inspect")
            return json.dumps([row for row in resources[kind] if row["Name"] in args[2:]])
        shadow.docker = Mock(side_effect=docker)
        return shadow, containers, resources

    def test_each_read_checks_a_fresh_inventory_without_reinspecting_owned_names(self):
        shadow, containers, _ = self.inventory()
        self.assertEqual(shadow.ownership_guard(), containers)
        self.assertEqual(shadow.docker.call_count, 8)
        for kind in ("volume", "network"):
            self.assertEqual(sum(call.args[:2] == (kind, "inspect") for call in shadow.docker.call_args_list), 1)
        containers[0]["State"]["Pid"] = 999
        self.assertEqual(shadow.ownership_guard()[0]["State"]["Pid"], 999)
        self.assertEqual(shadow.docker.call_count, 16)

    def test_batching_still_rejects_foreign_extras_and_unlabeled_name_collisions(self):
        for kind in ("volume", "network"):
            for fault in ("foreign-extra", "unlabeled-expected", "other-project-expected"):
                with self.subTest(kind=kind, fault=fault):
                    shadow, _, resources = self.inventory()
                    if fault == "foreign-extra":
                        resources[kind].append({"Name": PROJECT + "_extra", "Labels": {
                            "io.izo.owner": "foreign", "com.docker.compose.project": PROJECT}})
                        expected = "SHADOW_FOREIGN_" + kind.upper()
                    else:
                        resources[kind][-1]["Labels"] = {} if fault == "unlabeled-expected" else {
                            "io.izo.owner": OWNER, "com.docker.compose.project": "other-project"}
                        expected = "SHADOW_RESOURCE_NAME_COLLISION"
                    with self.assertRaisesRegex(ShadowError, expected):
                        shadow.ownership_guard()

    def test_read_only_backend_probe_uses_the_same_checked_container_snapshot(self):
        shadow, containers, _ = self.inventory()
        run = RecoveryRun(shadow, None, Mock())
        run.images = {"backend": IMAGE}
        self.assertEqual(run.backend(), containers[0])
        self.assertEqual(shadow.docker.call_count, 8)
        containers[0]["Image"] = "sha256:" + "f" * 64
        with self.assertRaisesRegex(RecoveryError, "BACKEND_IMAGE_CHANGED"):
            run.backend()

    def test_missing_batched_collision_metadata_fails_closed(self):
        shadow, _, resources = self.inventory()
        resources["volume"][-1]["Labels"] = {}
        inspect = shadow.docker.side_effect
        shadow.docker.side_effect = lambda *args, **kwargs: (
            "[]" if args == ("volume", "inspect", PROJECT + "_worker_ipc") else inspect(*args, **kwargs))
        with self.assertRaisesRegex(ShadowError, "RESOURCE_NAME_COLLISION"):
            shadow.ownership_guard()

    def test_duplicate_image_references_share_one_checked_immutable_id(self):
        shadow = Shadow(PROJECT, SHA, fixture=True)
        config = {"services": {name: {"image": reference} for name, reference in (
            ("backend", "app"), ("worker", "app"), ("worker_peer", "app"), ("guard", "guard"), ("web", "web"))}}
        def inspect(*args):
            return json.dumps([{"Id": "sha256:" + {"app": "1", "guard": "2", "web": "3"}[args[-1]] * 64,
                "Config": {"Labels": {"org.opencontainers.image.revision": SHA,
                    "org.opencontainers.image.source": "spikeal8-maker/IZO_ASA"}}}])
        shadow.docker = Mock(side_effect=inspect)
        result = shadow.image_guard(config)
        self.assertEqual(shadow.docker.call_count, 3)
        self.assertEqual({result[name] for name in ("backend", "worker", "worker_peer")}, {"sha256:" + "1" * 64})
        config["services"]["worker_peer"]["image"] = "web"
        with self.assertRaisesRegex(ShadowError, "WORKER_IMAGE_CHANGED"):
            shadow.image_guard(config)


class ApplicationRecycleTests(TestCase):
    def test_docker28_canonical_and_legacy_capabilities_keep_the_exact_three_grants(self):
        for caps in (["CAP_NET_ADMIN", "CAP_SETGID", "CAP_SETUID"],
                     ["NET_ADMIN", "SETUID", "SETGID"], ["CAP_SETUID", "NET_ADMIN", "CAP_SETGID"]):
            with self.subTest(caps=caps):
                before = stack()
                before[3]["HostConfig"]["CapAdd"] = caps
                shadow = fixture_shadow(before)
                observed = shadow.up(build=False, recreate=True, application_only=True)
                self.assertEqual(observed["before"], observed["after"])
                shadow.compose.assert_called_once()

    def test_capability_aliases_never_admit_extra_missing_duplicate_or_malformed_grants(self):
        canonical = ["CAP_NET_ADMIN", "CAP_SETGID", "CAP_SETUID"]
        invalid = [None, {}, "CAP_NET_ADMIN", [], canonical[:2], canonical + ["CAP_SYS_ADMIN"],
            canonical + ["NET_ADMIN"], ["CAP_NET_ADMIN", "NET_ADMIN", "CAP_SETUID"],
            ["CAP_NET_ADMIN", "CAP_SETUID", "ALL"], ["CAP_NET_ADMIN", "CAP_SETUID", "CAP_ALL"],
            ["CAP_NET_ADMIN", "CAP_SETUID", "CAP_CAP_SETGID"],
            ["CAP_NET_ADMIN", "CAP_SETUID", "setgid"], ["CAP_NET_ADMIN", "CAP_SETUID", 1]]
        for caps in invalid:
            with self.subTest(caps=caps):
                before = stack()
                before[3]["HostConfig"]["CapAdd"] = caps
                shadow = fixture_shadow(before)
                with self.assertRaisesRegex(ShadowError, "^SHADOW_RETAINED_GUARD_CAPABILITIES_INVALID$"):
                    shadow.up(build=False, recreate=True, application_only=True)
                shadow.compose.assert_not_called()

    def test_guard_diagnostics_are_fixed_and_distinguish_network_dns_ports_and_health(self):
        for field, code in (("network", "NETWORK"), ("dns", "DNS"), ("ports", "PORTS"), ("health", "HEALTH")):
            with self.subTest(field=field):
                before = stack()
                guard = before[3]
                if field == "network":
                    guard["NetworkSettings"]["Networks"]["foreign-secret-network"] = {}
                elif field == "dns":
                    guard["HostConfig"]["Dns"] = ["192.0.2.1"]
                elif field == "ports":
                    guard["HostConfig"]["PortBindings"]["8080/tcp"][0]["HostIp"] = "0.0.0.0"
                else:
                    guard["State"]["Health"]["Status"] = "unhealthy"
                shadow = fixture_shadow(before)
                with self.assertRaisesRegex(ShadowError, "^SHADOW_RETAINED_GUARD_" + code + "_INVALID$"):
                    shadow.up(build=False, recreate=True, application_only=True)
                shadow.compose.assert_not_called()

    def test_recovery_preflight_rejects_the_retained_boundary_before_http_or_sigkill(self):
        for caps in (["CAP_NET_ADMIN", "CAP_SETUID", "CAP_SYS_ADMIN"], None):
            with self.subTest(caps=caps), tempfile.TemporaryDirectory(prefix="izo-guard-preflight-") as directory:
                before = stack()
                before[3]["HostConfig"]["CapAdd"] = caps
                shadow = fixture_shadow(before)
                shadow.executor, shadow.docker = Mock(), Mock()
                attestation = {**recovery_target(), "sourceSha": shadow.sha, "project": shadow.project}
                with patch.object(recovery, "ProductFlow") as flow:
                    result = recovery.prove_recovery(shadow, attestation, Path(directory) / "receipt.json")
                self.assertEqual(result["status"], "FAIL")
                self.assertEqual(result["errorCode"], "SHADOW_RETAINED_GUARD_CAPABILITIES_INVALID")
                self.assertEqual(result["checks"], {})
                flow.assert_not_called()
                shadow.compose.assert_not_called()
                shadow.docker.assert_not_called()
                self.assertEqual(shadow.ownership_guard.call_count, 1)

    def test_only_api_and_two_workers_are_selected_with_immutable_ids_and_all_guards(self):
        shadow = fixture_shadow()
        launches = []
        def launch(*args, **kwargs):
            launches.append(args)
            data = json.loads(kwargs["override"].read_text())
            self.assertEqual(data, {"services": {name: {"image": IMAGE, "pull_policy": "never"}
                for name in shadow.image_guard.return_value}})
            self.assertEqual(shadow.source_guard.call_count, 2)
            self.assertEqual(shadow.ownership_guard.call_count, 1)
        shadow.compose.side_effect = launch
        result = shadow.up(build=False, recreate=True, application_only=True)
        self.assertEqual(launches, [("up", "-d", "--wait", "--wait-timeout", "180", "--no-build", "--pull", "never",
                                    "--force-recreate", "--no-deps", "backend", "worker", "worker_peer")])
        self.assertEqual(result["before"], result["after"])
        self.assertEqual(set(result["before"]), {"guard", "web"})
        self.assertEqual(shadow.ownership_guard.call_count, 2)

    def test_d1_full_stack_recreates_keep_the_original_selection(self):
        shadow = fixture_shadow()
        shadow.up(build=False, recreate=True)
        args = shadow.compose.call_args.args
        self.assertIn("--force-recreate", args)
        self.assertNotIn("--no-deps", args)
        self.assertFalse({"backend", "worker", "worker_peer", "guard", "web"} & set(args))

    def test_invalid_scope_or_changed_source_fails_before_mutation(self):
        for options in ({"build": True, "recreate": True}, {"build": False, "recreate": False},
                        {"build": False, "recreate": True, "fixture": False}):
            shadow = fixture_shadow()
            shadow.fixture = options.pop("fixture", True)
            with self.assertRaisesRegex(ShadowError, "APPLICATION_RECREATE_INVALID"):
                shadow.up(application_only=True, **options)
            shadow.compose.assert_not_called()
        shadow = fixture_shadow()
        shadow.source_guard.side_effect = [None, ShadowError("SHADOW_SOURCE_DIRTY")]
        with self.assertRaisesRegex(ShadowError, "SOURCE_DIRTY"):
            shadow.up(build=False, recreate=True, application_only=True)
        shadow.compose.assert_not_called()

    def test_unowned_or_unguarded_existing_stack_is_not_mutated(self):
        for fault in ("owner", "namespace", "ipc-mount", "guard-health", "web-root", "host-bind",
                      "guard-volume", "guard-extra-capability", "web-writable"):
            with self.subTest(fault=fault):
                before = stack()
                if fault == "owner":
                    before[3]["Config"]["Labels"]["io.izo.owner"] = "foreign"
                elif fault == "namespace":
                    before[1]["HostConfig"]["NetworkMode"] = "host"
                elif fault == "ipc-mount":
                    before[1]["Mounts"][0]["Name"] = "foreign-volume"
                elif fault == "guard-health":
                    before[3]["State"]["Health"]["Status"] = "unhealthy"
                elif fault == "web-root":
                    before[4]["Config"]["User"] = "0:0"
                elif fault == "host-bind":
                    before[4]["Mounts"].append({"Type": "bind", "Destination": "/foreign"})
                elif fault == "guard-volume":
                    before[3]["Mounts"].append({"Type": "volume", "Name": "foreign-volume"})
                elif fault == "guard-extra-capability":
                    before[3]["HostConfig"]["CapAdd"].append("SYS_ADMIN")
                else:
                    before[4]["HostConfig"]["ReadonlyRootfs"] = False
                shadow = fixture_shadow(before)
                with self.assertRaises(ShadowError):
                    shadow.up(build=False, recreate=True, application_only=True)
                shadow.compose.assert_not_called()

    def test_changed_retained_process_ports_or_network_cannot_be_reported_as_success(self):
        for fault in ("cid", "pid", "start", "restart", "port", "network"):
            with self.subTest(fault=fault):
                after = stack()
                if fault == "cid":
                    after[4]["Id"] = "f" * 64
                elif fault == "pid":
                    after[4]["State"]["Pid"] += 1
                elif fault == "start":
                    after[4]["State"]["StartedAt"] = "changed"
                elif fault == "restart":
                    after[4]["RestartCount"] = 1
                elif fault == "port":
                    after[3]["HostConfig"]["PortBindings"]["8080/tcp"][0]["HostPort"] = "48127"
                else:
                    after[3]["NetworkSettings"]["Networks"][PROJECT + "_shadow"]["NetworkID"] = "8" * 64
                shadow = fixture_shadow(after=after)
                with self.assertRaisesRegex(ShadowError, "RETAINED_RUNTIME_CHANGED"):
                    shadow.up(build=False, recreate=True, application_only=True)

    def test_recovery_receipt_retains_three_volumes_and_real_api_replacement(self):
        shadow = fixture_shadow()
        run = RecoveryRun(shadow, Mock(), Mock())
        before, after = deepcopy(stack()[0]), deepcopy(stack()[0])
        after["Id"] = "f" * 64
        run.guard = Mock()
        run.backend = Mock(side_effect=[before, after])
        run.provider = Mock(return_value={"provider": {"counts": {"accepted": 0}}})
        result = run.recreate()
        self.assertNotEqual(result["beforeContainer"], result["afterContainer"])
        self.assertEqual(len(result["volumes"]), 3)
        self.assertEqual(result["retainedRuntime"]["before"], result["retainedRuntime"]["after"])
