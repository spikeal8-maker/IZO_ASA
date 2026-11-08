"""The mandatory image probe is isolated, exact, fail-closed and cleaned up."""
from __future__ import annotations

import ast
import copy
import json
from pathlib import Path

import pytest

from tools import docker_backend_posix_probe as subject
from tools.docker_test_bundle_format import BundleError


IMAGE = "sha256:" + "a" * 64
SOURCE = "b" * 40


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "candidate"
    for relative in subject.MODULES:
        path = root / "backend" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# controlled installed module fixture\n")
    for name in subject.TESTS:
        (root / "backend" / name).write_text("def test_controlled():\n    assert True\n")
    (root / "tools").mkdir()
    for name in subject.CLIS:
        (root / "tools" / name).write_text("# controlled CLI fixture\n")
    (root / "backend/requirements.txt").write_text("pytest==9.0.3\ncryptography==50.0.2\n")
    return root


class DockerFixture:
    def __init__(self):
        self.calls = []
        self.report_delta = {}
        self.labels = {}
        self.failure = None
        self.config = None
        self.removed = False
        self.exit_code = "0"

    def run(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if args[0] == "create":
            self.labels = dict(args[i + 1].split("=", 1) for i, item in enumerate(args) if item == "--label")
            mount = args[args.index("--mount") + 1]
            host = Path(mount.split("source=", 1)[1].split(",target=", 1)[0])
            self.config = json.loads((host / "config.json").read_text())
            self.runner = (host / "runner.py").read_text()
            self.host_root = host
            return "c" * 64
        if args[0] == "start":
            return args[1]
        if args[0] == "wait":
            if self.failure:
                raise BundleError(self.failure)
            return self.exit_code
        if args[0] == "logs":
            report = {"status": "PASS", "collected": 45, "passed": 45, "failed": 0, "skipped": 0,
                      "errors": 0, "warnings": 0, "exit_code": 0, "failed_nodes": [],
                      "cli_restore_verified": True, "cli_help_verified": True,
                      "python": "3.11.9", **copy.deepcopy(self.config), **self.report_delta}
            return json.dumps(report)
        if args[0] == "inspect":
            return json.dumps([{"Config": {"Labels": self.labels}}])
        if args[:2] == ("rm", "--force"):
            self.removed = True
            return args[2]
        raise AssertionError("Unexpected fixture operation")


def test_exact_installed_modules_and_candidate_tests_are_bound_to_safe_receipt(source):
    docker = DockerFixture()
    result = subject.probe_backend_posix(source, SOURCE, IMAGE, docker)
    assert result["status"] == "PASS" and result["source_sha"] == SOURCE and result["image"] == IMAGE
    assert result["owned_container_removed"] is True and docker.removed
    assert set(result["modules"]) == set(subject.MODULES)
    assert set(result["tests"]) == set(subject.TESTS)
    assert set(result["cli"]) == set(subject.CLIS)
    assert result["dependencies"] == {"cryptography": "50.0.2", "pytest": "9.0.3"}
    assert not docker.host_root.exists()
    create = docker.calls[0][0]
    assert create[create.index("--user") + 1] == "10001:10001"
    assert create[create.index("--network") + 1] == "none" and "--read-only" in create
    assert create[create.index("--cap-drop") + 1] == "ALL" and "no-new-privileges:true" in create
    assert create[create.index("--entrypoint") + 1] == "python" and IMAGE in create
    assert "-I" in create and "-B" in create
    assert create.count("--mount") == 1 and "target=/verification,readonly" in create[create.index("--mount") + 1]
    assert str(source) not in " ".join(create) and "/home/izo" not in " ".join(create)
    assert "PYTEST_DISABLE_PLUGIN_AUTOLOAD=1" in create
    assert docker.calls[2][1]["timeout"] == 180


@pytest.mark.parametrize("field,value", [("status", "FAILED"), ("collected", 0), ("passed", 0),
    ("failed", 1), ("skipped", 1), ("errors", 1), ("warnings", 1), ("exit_code", 1),
    ("modules", {}), ("tests", {}), ("cli", {}), ("cli_restore_verified", False), ("cli_help_verified", False),
    ("dependencies", {"cryptography": "49.0.0", "pytest": "9.0.3"})])
def test_zero_tests_skips_failures_or_source_drift_cannot_pass(source, field, value):
    docker = DockerFixture()
    docker.report_delta[field] = value
    with pytest.raises(BundleError, match="BACKEND_POSIX_PROBE_FAILED"):
        subject.probe_backend_posix(source, SOURCE, IMAGE, docker)
    assert docker.removed and not docker.host_root.exists()


def test_deadline_failure_removes_only_owned_probe_without_other_resources(source):
    docker = DockerFixture()
    docker.failure = "FIXTURE_DEADLINE"
    with pytest.raises(BundleError, match="FIXTURE_DEADLINE"):
        subject.probe_backend_posix(source, SOURCE, IMAGE, docker)
    assert docker.removed and not docker.host_root.exists()
    assert all(args[0] not in {"volume", "network", "compose"} for args, _ in docker.calls)


def test_nonzero_container_exit_cannot_be_hidden_by_a_pass_json(source):
    docker = DockerFixture()
    docker.exit_code = "1"
    with pytest.raises(BundleError, match="BACKEND_POSIX_PROBE_FAILED"):
        subject.probe_backend_posix(source, SOURCE, IMAGE, docker)
    assert docker.removed


@pytest.mark.parametrize("requirements", ["pytest==9.0.3\n", "pytest==9.0.3\ncryptography>=50\n",
    "pytest==9.0.3\ncryptography==50.0.2\ncryptography==49.0.0\n"])
def test_missing_unpinned_or_ambiguous_dependencies_rejected_before_docker(source, requirements):
    (source / "backend/requirements.txt").write_text(requirements)
    docker = DockerFixture()
    with pytest.raises(BundleError, match="PINNED_DEPENDENCIES"):
        subject.probe_backend_posix(source, SOURCE, IMAGE, docker)
    assert docker.calls == []


def test_runner_import_is_safe_for_multiprocessing_spawn():
    # The concurrency tests use spawn; importing __mp_main__ must not recursively run pytest.
    tree = ast.parse(subject.RUNNER)
    assert any(isinstance(node, ast.If) for node in tree.body)
    namespace = {"__name__": "__mp_main__"}
    exec(compile(tree, "isolated-posix-runner", "exec"), namespace)
    assert callable(namespace["main"])
