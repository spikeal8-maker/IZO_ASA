"""Schema identity controls use isolated files and fake Docker only."""
from __future__ import annotations

import json

import pytest

from tools import docker_test_bundle as builder
from tools import docker_test_bundle_runtime as runtime
from tools.docker_test_bundle_format import BundleError, verify
from tools.test_docker_synthetic_runtime import make_runtime, repin
from tools.test_docker_test_bundle_build import source_contract
from tools.test_docker_test_bundle_runtime import FakeDocker, fake_runtime


@pytest.mark.parametrize("schema", [7, 8])
def test_source_target_and_verified_bundle_agree(tmp_path, schema):
    source_contract(tmp_path, schema)
    assert builder.source_schema_version(tmp_path) == schema
    root, pin, manifest = make_runtime(tmp_path / "bundle", schema=schema)
    assert verify(root, pin)["schema"] == schema
    assert manifest["schema"] == schema


@pytest.mark.parametrize("low,high", [
    (1, True), (1, 8.0), (1, "8"), (1, 6), (1, 9), (0, 8),
    (True, 8), (1.0, 8), ("1", 8), (9, 8), (1, None),
])
def test_invalid_source_schema_contract_fails_closed(tmp_path, low, high):
    path = tmp_path / "architecture/contract.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"release_contract": {
        "schema_compatibility": {"min_version": low, "max_version": high}}}))
    with pytest.raises(BundleError, match="SOURCE_SCHEMA_CONTRACT_INVALID"):
        builder.source_schema_version(tmp_path)


@pytest.mark.parametrize("contract", [{}, {"release_contract": []},
    {"release_contract": {}}, {"release_contract": {"schema_compatibility": []}}])
def test_missing_source_contract_shape_is_not_assumed_to_be_schema7(tmp_path, contract):
    path = tmp_path / "architecture/contract.json"
    path.parent.mkdir()
    path.write_text(json.dumps(contract))
    with pytest.raises(BundleError, match="SOURCE_SCHEMA_CONTRACT_INVALID"):
        builder.source_schema_version(tmp_path)


@pytest.mark.parametrize("schema", [None, True, False, 7.0, 8.0, "8", 6, 9, 0, [], {}])
def test_unknown_or_mistyped_bundle_schema_is_rejected(tmp_path, schema):
    root, _, manifest = make_runtime(tmp_path / "bundle")
    manifest["schema"] = schema
    with pytest.raises(BundleError, match="BUNDLE_SCHEMA_UNSUPPORTED"):
        verify(root, repin(root, manifest))


@pytest.mark.parametrize("schema,reported", [(7, 7), (8, 8), (8, 7), (7, 8)])
def test_fresh_initializer_requires_its_pinned_schema_marker(tmp_path, schema, reported):
    root, _, manifest = make_runtime(tmp_path / "bundle", schema=schema)

    class BootstrapDocker:
        def __init__(self):
            self.calls = []

        def compose(self, directory, current, *args):
            assert current is manifest and directory == root
            self.calls.append(args)
            return f"FRESH_TEST_SCHEMA_{reported}_VERIFIED" if args[0] == "run" else ""

    docker = BootstrapDocker()
    if schema == reported:
        runtime.initialize_empty_test_database(docker, root, manifest)
    else:
        with pytest.raises(BundleError, match="FRESH_SCHEMA_INITIALIZATION_FAILED"):
            runtime.initialize_empty_test_database(docker, root, manifest)
    assert len(docker.calls) == 2
    code = docker.calls[1][-1]
    compile(code, "controlled-bootstrap", "exec")
    assert f"fetchone()[0]=={schema}" in code
    assert f"FRESH_TEST_SCHEMA_{schema}_VERIFIED" in code
    assert "main.db_guard_preflight()" in code and "main.init_db()" in code
    assert "sqlite_master" in code and "fetchone()[0]==0" in code
    assert "PRAGMA user_version=" not in code and "seal_restored_history" not in code


@pytest.mark.parametrize("method", [runtime.health, runtime.initialize_empty_test_database])
def test_runtime_rejects_unknown_schema_before_docker(method, tmp_path):
    class ForbiddenDocker:
        def __getattr__(self, name):
            pytest.fail("Docker accessed before schema refusal")
    with pytest.raises(BundleError, match="BUNDLE_SCHEMA_UNSUPPORTED"):
        method(ForbiddenDocker(), tmp_path, {"schema": 9})


@pytest.mark.parametrize("old_schema,new_schema", [(7, 8), (8, 7)])
def test_generic_cross_schema_update_stays_forbidden(tmp_path, monkeypatch, old_schema, new_schema):
    fake_runtime(monkeypatch)
    first, pin, _ = make_runtime(tmp_path / "first", schema=old_schema)
    second, candidate_pin, _ = make_runtime(tmp_path / "candidate", "b" * 40, schema=new_schema)
    state, docker = tmp_path / "state", FakeDocker()
    runtime.install(first, pin, state, docker)
    active = (state / "active.json").read_bytes()
    owner = (state / "owner.json").read_bytes()
    calls = [call for call in docker.calls if isinstance(call, tuple)]
    volumes = json.loads(active)["volumes"]
    with pytest.raises(BundleError, match="UPDATE_SCHEMA_UNSUPPORTED"):
        runtime.install(second, candidate_pin, state, docker, allow_update=True)
    assert (state / "active.json").read_bytes() == active
    assert (state / "owner.json").read_bytes() == owner
    assert [call for call in docker.calls if isinstance(call, tuple)] == calls
    assert json.loads((state / "active.json").read_bytes())["volumes"] == volumes
    assert not (state / "releases" / candidate_pin).exists()


def test_schema8_update_checks_schema8_quiescence_and_keeps_volumes(tmp_path, monkeypatch):
    fake_runtime(monkeypatch)
    first, pin, manifest = make_runtime(tmp_path / "first", schema=8)
    second, candidate_pin, _ = make_runtime(tmp_path / "candidate", "b" * 40, schema=8)
    state, docker = tmp_path / "state", FakeDocker()
    receipt = runtime.install(first, pin, state, docker)
    docker.containers = [{"Id": "backend", "Image": manifest["images"]["backend"],
        "State": {"Running": True}, "Config": {"Labels": {"com.docker.compose.service": "backend"}}}]
    active = (state / "active.json").read_bytes()
    with pytest.raises(BundleError, match="UPDATE_TEST_DATA_NOT_QUIESCENT"):
        runtime.install(second, candidate_pin, state, docker, allow_update=True)
    assert (state / "active.json").read_bytes() == active
    assert not (state / "releases" / candidate_pin).exists()
    docker.proof["schema"] = 8
    updated = runtime.install(second, candidate_pin, state, docker, allow_update=True)
    assert updated["manifest_sha256"] == candidate_pin
    assert updated["volumes"] == receipt["volumes"]


def test_schema_less_native_validation_keeps_legacy_contract(tmp_path):
    from tools.docker_test_bundle_format import validate_compose
    root, _, manifest = make_runtime(tmp_path / "bundle", schema=7)
    config = json.loads((root / "compose.json").read_text())
    legacy_manifest = dict(manifest)
    legacy_manifest.pop("schema")
    validate_compose(config, legacy_manifest)
    with pytest.raises(BundleError, match="BUNDLE_SCHEMA_UNSUPPORTED"):
        verify(root, repin(root, legacy_manifest))
