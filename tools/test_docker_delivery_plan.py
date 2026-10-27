"""Synthetic Docker delivery plan tests: zero resource mutation or secrets."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tools.docker_delivery_plan import (
    PlanError, evaluate, main, make_plan, parse_manifest, read_manifest,
)
from tools.docker_delivery_probe import ProbeError, TargetInfo

SHA = "f" * 40
D1 = "a" * 64
D2 = "b" * 64


def payload() -> dict:
    return {
        "manifest_version": 1,
        "source_sha": SHA,
        "schema_compatibility": {"min_version": 7, "max_version": 7},
        "images": {
            "backend": "ghcr.io/example/isoas-backend@sha256:" + D1,
            "web": "ghcr.io/example/isoas-web@sha256:" + D2,
        },
    }


def raw(value: dict | None = None) -> bytes:
    return json.dumps(payload() if value is None else value, sort_keys=True).encode("utf-8")


def target(*, existing: bool = False) -> TargetInfo:
    return TargetInfo(
        context="desktop-linux", installation="isoas",
        server_version="29.8.2", compose_version="5.6.0",
        engine_fingerprint="c" * 64,
        owned_containers=2 if existing else 0,
        owned_volumes=2 if existing else 0,
        owned_networks=1 if existing else 0,
    )


def test_canonical_manifest_and_plan_are_deterministic() -> None:
    document = raw()
    candidate = parse_manifest(document)
    assert candidate.manifest_sha256 == hashlib.sha256(document).hexdigest()
    assert candidate.source_sha == SHA
    plan = make_plan(candidate, target(), intent="install")
    assert plan["status"] == "READY"
    assert plan["apply_authorized"] is False and plan["mutation_performed"] is False
    assert plan["candidate"]["schema_compatibility"] == {"min_version": 7, "max_version": 7}
    assert len(plan["candidate"]["immutable_images"]) == 2
    assert plan == make_plan(candidate, target(), intent="install")
    assert "private" not in json.dumps(plan)


@pytest.mark.parametrize("edit,error", [
    ({"manifest_version": 2}, "MANIFEST_STRUCTURE_INVALID"),
    ({"source_sha": "main"}, "MANIFEST_SOURCE_SHA_INVALID"),
    ({"source_sha": "A" * 40}, "MANIFEST_SOURCE_SHA_INVALID"),
    ({"schema_compatibility": {"min_version": 8, "max_version": 7}}, "MANIFEST_SCHEMA_INVALID"),
    ({"schema_compatibility": {"min_version": True, "max_version": 7}}, "MANIFEST_SCHEMA_INVALID"),
    ({"schema_compatibility": {"min_version": 0, "max_version": 7}}, "MANIFEST_SCHEMA_INVALID"),
    ({"images": {"backend": "backend:latest", "web": "web:latest"}}, "MANIFEST_IMAGE_NOT_PINNED"),
    ({"images": {"backend": "example@sha256:" + D1, "web": "example@sha256:" + D2}},
     "MANIFEST_IMAGE_NOT_PINNED"),
    ({"images": {"backend": "ghcr.io/x/api@sha256:" + D1, "web": "registry/x/web@sha256:" + D2,
                 "unknown": "registry/x/unknown@sha256:" + D1}}, "MANIFEST_IMAGES_INVALID"),
    ({"images": {"backend": "ghcr.io/x/api@sha256:" + D1}}, "MANIFEST_IMAGES_INVALID"),
])
def test_invalid_manifest_is_fail_closed(edit: dict, error: str) -> None:
    source = payload()
    source.update(edit)
    with pytest.raises(PlanError, match=error):
        parse_manifest(raw(source))


@pytest.mark.parametrize("bad", [
    b"{", b"\xff", b"", b"a" * 20000,
    b'{"manifest_version":1,"manifest_version":1}',
    b'{"manifest_version":true,"source_sha":"a"}',
])
def test_garbled_duplicate_or_large_manifest_rejected(bad: bytes) -> None:
    with pytest.raises(PlanError):
        parse_manifest(bad)


def test_schema_and_role_keys_are_strict_and_no_surprise_flags() -> None:
    candidate = payload()
    candidate["unexpected"] = "extra"
    with pytest.raises(PlanError, match="MANIFEST_STRUCTURE_INVALID"):
        parse_manifest(raw(candidate))
    candidate = payload()
    candidate["schema_compatibility"] = {"min_version": 7, "max_version": 7, "force": True}
    with pytest.raises(PlanError, match="MANIFEST_SCHEMA_INVALID"):
        parse_manifest(raw(candidate))


def test_install_collision_and_update_are_blocked() -> None:
    candidate = parse_manifest(raw())
    with pytest.raises(PlanError) as result:
        make_plan(candidate, target(existing=True), intent="install")
    assert result.value.category == "OWNERSHIP_CONFLICT"
    with pytest.raises(PlanError) as result:
        make_plan(candidate, target(existing=True), intent="update")
    assert result.value.category == "INCOMPATIBLE_RELEASE"
    assert result.value.code == "UPDATE_RECEIPT_AND_SCHEMA_PROOF_REQUIRED"


def test_plan_and_doctor_exits_without_any_apply(tmp_path: Path) -> None:
    path = tmp_path / "candidate.json"
    path.write_bytes(raw())
    calls: list[tuple[str, str]] = []

    def probe(context: str, installation: str) -> TargetInfo:
        calls.append((context, installation))
        return target()

    code, output = evaluate("doctor", "desktop-linux", "isoas", probe=probe)
    assert code == 0 and output["status"] == "OBSERVED"
    assert output["mutation_performed"] is False
    code, output = evaluate("plan", "desktop-linux", "isoas", str(path), probe=probe)
    assert code == 0 and output["status"] == "READY"
    assert output["apply_authorized"] is False
    assert calls == [("desktop-linux", "isoas"), ("desktop-linux", "isoas")]


def test_manifest_is_verified_before_any_docker_probe(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("not a manifest", encoding="utf-8")

    def forbidden_probe(*args: object) -> TargetInfo:
        raise AssertionError("invalid manifest must not call docker")

    code, output = evaluate("plan", "desktop-linux", "isoas", str(path), probe=forbidden_probe)
    assert code == 2 and output["reason"] == "MANIFEST_JSON_INVALID"


def test_docker_failure_returns_redacted_fixed_code(tmp_path: Path) -> None:
    path = tmp_path / "candidate.json"
    path.write_bytes(raw())

    def failing_probe(*args: object) -> TargetInfo:
        raise ProbeError("TARGET_UNAVAILABLE")

    code, output = evaluate("plan", "desktop-linux", "isoas", str(path), probe=failing_probe)
    assert code == 3
    assert output["status"] == "BLOCKED" and output["reason"] == "TARGET_UNAVAILABLE"
    assert not output["mutation_performed"]


@pytest.mark.parametrize("error,code", [
    ("INVALID_CONTEXT", 2),
    ("OWNERSHIP_CONFLICT", 4),
    ("TARGET_OSTYPE_UNSUPPORTED", 5),
    ("TARGET_METADATA_INVALID", 3),
])
def test_probe_error_exit_code_contract(error: str, code: int) -> None:
    def fails(*args: object) -> TargetInfo:
        raise ProbeError(error)

    code_actual, result = evaluate("doctor", "desktop-linux", "isoas", probe=fails)
    assert code_actual == code
    assert result["apply_authorized"] is False


def test_cli_prints_single_stable_secret_free_json_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "candidate.json"
    path.write_bytes(raw())
    import tools.docker_delivery_plan as plan_module
    monkeypatch.setattr(plan_module, "probe_target", lambda c, i: target())
    # main() resolves evaluate's injected default at definition time; override evaluate,
    # not subprocess, for this CLI formatting-only characterization.
    monkeypatch.setattr(plan_module, "evaluate", lambda *args: (0, make_plan(parse_manifest(raw()), target(), intent="install")))
    assert main(["plan", "--context", "desktop-linux", "--installation", "isoas", "--manifest", str(path)]) == 0
    first = capsys.readouterr()
    assert first.err == ""
    assert "token" not in first.out.lower()
    assert json.loads(first.out)["status"] == "READY"
    assert main(["plan", "--context", "desktop-linux", "--installation", "isoas", "--manifest", str(path)]) == 0
    second = capsys.readouterr()
    assert first.out == second.out


def test_read_manifest_rejects_symlink_and_missing_file(tmp_path: Path) -> None:
    with pytest.raises(PlanError, match="MANIFEST_NOT_A_REGULAR_FILE"):
        read_manifest(str(tmp_path / "missing"))
    target_file = tmp_path / "manifest.json"
    target_file.write_bytes(raw())
    sym = tmp_path / "shortcut.json"
    try:
        sym.symlink_to(target_file)
    except OSError:
        pytest.skip("Symlinks not permitted on this Windows runner")
    with pytest.raises(PlanError, match="MANIFEST_NOT_A_REGULAR_FILE"):
        read_manifest(str(sym))


@pytest.mark.parametrize("untrusted_args", [
    ["plan", "--context", "desktop-linux", "--installation", "isoas",
     "--unexpected-private-key", "sensitive-test-value"],
    ["update", "--context", "desktop-linux", "--installation", "isoas"],
    ["plan", "--installation", "isoas"],
])
def test_argparse_failure_is_one_redacted_json_line(
    untrusted_args: list[str], capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as raised:
        main(untrusted_args)
    captured = capsys.readouterr()
    assert raised.value.code == 2
    assert captured.err == ""
    assert len(captured.out.splitlines()) == 1
    answer = json.loads(captured.out)
    assert answer == {
        "status": "BLOCKED", "action": "unknown", "category": "INVALID_INPUT",
        "reason": "CLI_ARGUMENTS_INVALID", "apply_authorized": False,
        "mutation_performed": False,
    }
    assert "sensitive-test-value" not in captured.out
