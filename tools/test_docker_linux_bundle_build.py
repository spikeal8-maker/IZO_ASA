"""Deterministic producer/runner boundary tests; no Docker or network execution."""
import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import docker_linux_bundle_build as build


class ProducerBoundaryTests(unittest.TestCase):
    def runner_env(self):
        return {"GITHUB_ACTIONS": "true", "IZO_RUNNER_ENVIRONMENT": "github-hosted",
                "IZO_RUNNER_OS": "Linux", "IZO_RUNNER_ARCH": "X64",
                "GITHUB_REPOSITORY": build.REPOSITORY, "GITHUB_JOB": "producer",
                "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1", "IZO_RUNNER_NAME": "producer-vm",
                "IZO_EXPECTED_HEAD": "a" * 40}

    def metadata(self, env, release=None):
        with patch.dict(os.environ, env, clear=True), patch.object(build.platform, "system", return_value="Linux"), \
                patch.object(build.platform, "machine", return_value="x86_64"), \
                patch.object(build, "boot_fingerprint", return_value="d" * 64), \
                patch.object(build.platform, "freedesktop_os_release", return_value=release or {"ID": "ubuntu", "VERSION_ID": "22.04"}, create=True):
            return build.runner_metadata("producer")

    def test_github_hosted_metadata_bound_to_job_and_exact_head(self):
        value = self.metadata(self.runner_env())
        self.assertEqual((value["job"], value["head"], value["os"]), ("producer", "a" * 40, "ubuntu-22.04"))

    def test_distribution_label_does_not_substitute_for_actual_os_release(self):
        for release in ({"ID": "ubuntu", "VERSION_ID": "24.04"}, {"ID": "debian", "VERSION_ID": "22.04"}):
            with self.subTest(release=release), self.assertRaisesRegex(build.ProofError, "UBUNTU_2204_REQUIRED"):
                self.metadata(self.runner_env(), release)

    def test_self_hosted_other_arch_other_repository_and_missing_sha_fail(self):
        for key, value in (("IZO_RUNNER_ENVIRONMENT", "self-hosted"), ("IZO_RUNNER_ARCH", "ARM64"),
                           ("GITHUB_REPOSITORY", "other/project"), ("IZO_EXPECTED_HEAD", ""),
                           ("GITHUB_JOB", "receiver"), ("GITHUB_ACTIONS", "false")):
            with self.subTest(key=key), self.assertRaises(build.ProofError):
                self.metadata({**self.runner_env(), key: value})

    def test_secret_and_docker_override_environment_is_not_forwarded(self):
        env = {"PATH": "bin", "HOME": "home", "DOCKER_HOST": "remote-engine", "HTTPS_PROXY": "credential",
               "GITHUB_TOKEN": "secret", "OPENROUTER_API_KEY": "secret", "COMPOSE_FILE": "other.yml"}
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(build.environment(), {"PATH": "bin", "HOME": "home", "PYTHONDONTWRITEBYTECODE": "1"})

    def test_any_existing_engine_resource_refuses_without_prune(self):
        for role in ("producer", "receiver"):
            for kind in ("images", "containers", "volumes"):
                value = {"images": [], "containers": [], "volumes": []}; value[kind] = ["foreign"]
                with self.subTest(role=role, kind=kind), patch.object(build, "run") as command, \
                        self.assertRaisesRegex(build.ProofError, role.upper() + "_ENGINE_NOT_EMPTY_NO_PRUNE"):
                    build.fresh_engine(value, role)
                command.assert_not_called()

    def test_zero_resources_are_required_and_accepted_in_both_roles(self):
        before = {"images": [], "containers": [], "volumes": []}
        for role in ("producer", "receiver"):
            self.assertIsNone(build.fresh_engine(before, role))

    def test_inventory_retains_all_resource_categories_without_mutation(self):
        with patch.object(build, "run", side_effect=["sha256:b\nsha256:a\nsha256:b", "container-id", "volume-name"]) as command:
            self.assertEqual(build.inventory(), {"images": ["sha256:a", "sha256:b"],
                                                "containers": ["container-id"], "volumes": ["volume-name"]})
        self.assertEqual([call.args[0] for call in command.call_args_list], [
            ["docker", "--context", "default", "image", "ls", "-aq", "--no-trunc"],
            ["docker", "--context", "default", "ps", "-aq", "--no-trunc"],
            ["docker", "--context", "default", "volume", "ls", "-q"]])

    def test_nonempty_producer_retains_initial_inventory_before_build(self):
        for kind in ("images", "containers", "volumes"):
            before = {"images": [], "containers": [], "volumes": []}
            before[kind] = ["foreign-" + kind]
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); candidate = root / "candidate"; candidate.mkdir()
                (candidate / ".python-version").write_text(build.platform.python_version())
                output = root / "output"
                args = ["--candidate", str(candidate), "--tooling", str(root / "tooling"),
                        "--source-a", str(root / "source-a"), "--source-b", str(root / "source-b"),
                        "--output", str(output)]
                with patch.object(build, "runner_metadata", return_value={"head": "a" * 40}), \
                        patch.object(build, "source_guard"), patch.object(build, "engine_metadata", return_value={}), \
                        patch.object(build, "inventory", return_value=before), \
                        patch.object(build, "build_release") as build_release, patch.object(build, "run") as command:
                    self.assertEqual(build.main(args), 1)
                build_release.assert_not_called()
                command.assert_not_called()
                report = json.loads((output / "producer.json").read_text())
                self.assertEqual(report.get("before"), before)
                self.assertEqual(report["reason"], "PRODUCER_ENGINE_NOT_EMPTY_NO_PRUNE")
                self.assertEqual(report["stage"], "fresh_engine")
                self.assertEqual(list(output.iterdir()), [output / "producer.json"])

    def test_exact_clean_origin_rejects_similar_foreign_host(self):
        def response(args, **kwargs):
            if args[-1] == "origin": return "https://evil.invalid/spikeal8-maker/IZO_ASA.git"
            if args[-1] == "HEAD": return "a" * 40
            return ""
        with patch.object(build, "run", side_effect=response), self.assertRaisesRegex(build.ProofError, "CLEAN_EXACT"):
            build.source_guard(Path("source"), "a" * 40)

    def test_wrong_head_or_dirty_tree_refused(self):
        for head, dirty in (("b" * 40, ""), ("a" * 40, " M ops/docker/dev/compose.yml")):
            def response(args, **kwargs):
                if args[-1] == "origin": return "https://github.com/" + build.REPOSITORY + ".git"
                if args[-1] == "HEAD": return head
                return dirty
            with self.subTest(head=head, dirty=dirty), patch.object(build, "run", side_effect=response), \
                    self.assertRaisesRegex(build.ProofError, "CLEAN_EXACT"):
                build.source_guard(Path("source"), "a" * 40)

    def test_error_receipt_cannot_echo_subprocess_secrets(self):
        value = subprocess.CompletedProcess(["tool"], 9, "private-value", "private-value")
        with patch.object(build.subprocess, "run", return_value=value), self.assertRaises(build.ProofError) as caught:
            build.run(["tool"])
        self.assertEqual(str(caught.exception), "COMMAND_FAILED")

    def test_engine_receipt_records_actual_versions_and_fingerprint(self):
        info = {"ID": "private-engine-id", "OSType": "linux", "Architecture": "x86_64", "ServerVersion": "28.0.4"}
        with patch.object(build, "run", side_effect=[json.dumps(info), "2.38.2"]):
            value = build.engine_metadata()
        self.assertEqual((value["engine"], value["compose"]), ("28.0.4", "2.38.2"))
        self.assertRegex(value["fingerprint"], r"^[0-9a-f]{64}$")
        self.assertNotIn("private-engine-id", json.dumps(value))

    def test_linux_boot_identity_is_hashed_and_format_checked(self):
        with patch.object(Path, "read_text", return_value="12345678-1234-1234-1234-123456789abc\n"):
            self.assertRegex(build.boot_fingerprint(), r"^[0-9a-f]{64}$")
        with patch.object(Path, "read_text", return_value="not-a-boot-id"), self.assertRaises(build.ProofError):
            build.boot_fingerprint()

    def test_every_docker_stage_requires_an_immutable_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp); directory = source / "ops/docker/dev"; directory.mkdir(parents=True)
            for role in ("guard", "backend", "web"):
                (directory / ("Dockerfile." + role)).write_text("FROM python@sha256:" + "a" * 64 + "\n")
            self.assertEqual(set(build.pinned_dockerfiles(source)), {"guard", "backend", "web"})
            (directory / "Dockerfile.web").write_text("FROM node@sha256:" + "a" * 64 + " AS builder\nFROM nginx:latest\n")
            with self.assertRaisesRegex(build.ProofError, "DOCKER_BASE_NOT_DIGEST_PINNED"):
                build.pinned_dockerfiles(source)

    def test_existing_output_is_never_overwritten_on_failed_preflight(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); receipt = root / "producer.json"; receipt.write_text("keep-original")
            args = ["--candidate", tmp, "--tooling", tmp, "--source-a", tmp, "--source-b", tmp, "--output", tmp]
            self.assertEqual(build.main(args), 1)
            self.assertEqual(receipt.read_text(), "keep-original")


class WorkflowContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        cls.text = (cls.root / ".github/workflows/docker-linux-bundle-acceptance.yml").read_text(encoding="utf-8")

    def test_pinned_actions_and_distinct_jobs_with_dependency(self):
        actions = re.findall(r"uses:\s*(\S+)", self.text)
        self.assertTrue(actions)
        self.assertTrue(all(re.fullmatch(r"actions/[a-z-]+@[0-9a-f]{40}", value) for value in actions))
        self.assertEqual(self.text.count("runs-on: ubuntu-22.04"), 2)
        self.assertNotIn("runs-on: ubuntu-24.04", self.text)
        self.assertIn("tasks/" + build.CONTRACT + ".toml", self.text)
        self.assertIn("needs: producer", self.text)
        self.assertIn("github.actor == 'spikeal8-maker'", self.text)
        self.assertIn("github.event.pull_request.head.repo.full_name == github.repository", self.text)
        self.assertNotIn("pull_request_target", self.text)
        self.assertNotIn("write-all", self.text)
        self.assertNotIn("secrets.", self.text)

    def test_immutable_sources_trusted_receipt_and_no_privileged_or_prune(self):
        for sha in (*build.SOURCES.values(), build.TOOLING):
            self.assertIn("ref: " + sha, self.text)
        self.assertIn("needs.producer.outputs.receipt_sha256", self.text)
        self.assertIn("IZO_PRODUCER_RECEIPT_SHA256", self.text)
        self.assertIn("persist-credentials: false", self.text)
        self.assertNotIn("privileged", self.text)
        self.assertNotIn("prune", self.text)
        self.assertNotIn("setup-node", self.text)
        self.assertNotIn("sudo ", self.text)


if __name__ == "__main__":
    unittest.main()
