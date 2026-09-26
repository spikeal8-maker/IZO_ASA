from __future__ import annotations

import json
import os
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from tools.agent_system.env import (
    CONTRACT_ID,
    EnvironmentContractError,
    EnvironmentPaths,
    ProductionPathContract,
    build_environment_plan,
    derive_candidate_ports,
    derive_environment_paths,
    discover_production_path_contract,
    inspect_provider_credentials,
    load_environment_identity,
    provider_policy,
    validate_environment_paths,
    write_planned_environment,
)
from tools.agent_system.package import manifest_fingerprint, parse_manifest
from tools.agent_system.registry import load_registry, save_registry, token_hash


ROOT = Path(__file__).resolve().parents[1]
FIXED_TIME = "2026-09-27T00:00:00Z"


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(result.stderr or result.stdout)
    return result.stdout.strip()


def _manifest_text(package_id: str, base_sha: str) -> str:
    return f"""manifestVersion = 1
id = "{package_id}"
baseSha = "{base_sha}"
goal = "Synthetic environment contract."
userOutcome = "Synthetic package owns an isolated plan."
beforeScenario = "No environment plan."
afterScenario = "Environment plan exists."
nonGoals = ["product behavior"]
declaredFiles = ["tools/agent_system/env.py", "tools/test_agent_env.py"]
allowedPatterns = []
forbiddenPatterns = []
protectedFilesTouched = []
domain = "agent-control-plane"
riskClass = "standard"
changeClass = "architecture"
maxProductionFiles = 0
maxChangedLines = 1200
acceptance = ["environment plan passes"]
requiredEvidence = ["focused tests"]
targetedTests = ["tools/test_agent_env.py"]
fileGrowthExpectations = ["bounded"]
forbiddenOperations = ["deploy", "process-start", "port-bind"]
rollbackBoundary = "Remove synthetic package state."
"""


def _make_control_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "control"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Env Test")
    _git(repo, "config", "user.email", "env-test@example.invalid")
    (repo / "README.md").write_text("seed\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "seed")
    return repo, _git(repo, "rev-parse", "HEAD")


def _add_package(control: Path, base_sha: str, package_id: str, worktree: Path) -> Path:
    branch = f"agent/{package_id.lower()}"
    _git(control, "worktree", "add", "-b", branch, str(worktree), base_sha)
    manifest_path = worktree / "tasks" / f"{package_id}.toml"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(_manifest_text(package_id, base_sha), encoding="utf-8")
    manifest = parse_manifest(manifest_path)

    token = f"synthetic-token-{package_id}"
    owner_id = f"owner-{package_id.lower()}"
    ownership_path = worktree / ".runtime" / "agent" / "ownership.json"
    ownership_path.parent.mkdir(parents=True)
    ownership_path.write_text(
        json.dumps(
            {
                "packageId": package_id,
                "token": token,
                "ownerInstanceId": owner_id,
            }
        ),
        encoding="utf-8",
    )

    payload = load_registry(control)
    payload["entries"].append(
        {
            "packageId": package_id,
            "manifestPath": f"tasks/{package_id}.toml",
            "manifestFingerprint": manifest_fingerprint(manifest),
            "branch": branch,
            "worktreePath": str(worktree.resolve()),
            "baseSha": base_sha,
            "currentHeadSha": base_sha,
            "writeOwnership": [f"tasks/{package_id}.toml"],
            "discoveredWriteOwnership": [],
            "state": "active",
            "ownerInstanceId": owner_id,
            "ownershipTokenHash": token_hash(token),
            "creatorHost": "test",
            "createdAt": FIXED_TIME,
            "updatedAt": FIXED_TIME,
            "scopeExpansionHistory": [],
        }
    )
    save_registry(control, payload)
    return worktree


def _known_contract(tmp_path: Path) -> ProductionPathContract:
    return ProductionPathContract(
        status="KNOWN",
        database_status="KNOWN",
        media_status="KNOWN",
        secret_status="KNOWN",
        database_roots=(str((tmp_path / "production-db").resolve()),),
        media_roots=(str((tmp_path / "production-media").resolve()),),
        secret_roots=(str((tmp_path / "production-secrets").resolve()),),
        source_files=("synthetic-production-contract",),
    )


def _single_package(tmp_path: Path, package_id: str = "PKG-ALPHA") -> tuple[Path, ProductionPathContract]:
    control, base = _make_control_repo(tmp_path)
    worktree = _add_package(control, base, package_id, tmp_path / package_id.lower())
    return worktree, _known_contract(tmp_path)


def _directory_link(link: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    link.parent.mkdir(parents=True, exist_ok=True)
    try:
        link.symlink_to(target, target_is_directory=True)
        return
    except OSError:
        if os.name != "nt":
            raise
    result = subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(result.stderr or result.stdout)


def _contains_key(value: object, forbidden: str) -> bool:
    if isinstance(value, dict):
        return any(
            str(key).casefold() == forbidden.casefold() or _contains_key(item, forbidden)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_key(item, forbidden) for item in value)
    return False


def test_repository_production_contract_fails_closed_on_unknown_media_root() -> None:
    contract = discover_production_path_contract(ROOT)
    assert contract.status == "UNKNOWN"
    assert contract.database_status == "KNOWN"
    assert contract.media_status == "UNKNOWN"
    assert contract.media_roots == ()
    assert contract.secret_status == "KNOWN"
    assert contract.source_files == ("ops/release/promote-project-release.ps1",)
    assert any(root.casefold() == r"c:\izo_asa".casefold() for root in contract.database_roots)
    assert any(root.casefold() == r"c:\izo_asa\secrets".casefold() for root in contract.secret_roots)
    with pytest.raises(EnvironmentContractError, match=r"PRODUCTION_PATH_STATUS_UNKNOWN.*media=UNKNOWN"):
        build_environment_plan(ROOT, environment={}, production_contract=contract)


def test_same_package_has_same_deterministic_roots_and_ports(tmp_path: Path) -> None:
    worktree, contract = _single_package(tmp_path)
    first = build_environment_plan(
        worktree, environment={}, production_contract=contract, timestamp=FIXED_TIME
    )
    second = build_environment_plan(
        worktree, environment={}, production_contract=contract, timestamp=FIXED_TIME
    )
    for key in ("environmentRoot", "databasePath", "mediaRoot", "secretRoot", "ports"):
        assert first[key] == second[key]
    assert first == second


def test_two_packages_have_disjoint_roots_and_ports(tmp_path: Path) -> None:
    control, base = _make_control_repo(tmp_path)
    first_root = _add_package(control, base, "PKG-ALPHA", tmp_path / "alpha")
    second_root = _add_package(control, base, "PKG-BETA", tmp_path / "beta")
    contract = _known_contract(tmp_path)

    first = build_environment_plan(
        first_root, environment={}, production_contract=contract, timestamp=FIXED_TIME
    )
    second = build_environment_plan(
        second_root, environment={}, production_contract=contract, timestamp=FIXED_TIME
    )

    assert first["environmentRoot"] != second["environmentRoot"]
    assert first["databasePath"] != second["databasePath"]
    assert first["mediaRoot"] != second["mediaRoot"]
    assert first["secretRoot"] != second["secretRoot"]
    assert {first["ports"]["backend"], first["ports"]["frontend"]}.isdisjoint(
        {second["ports"]["backend"], second["ports"]["frontend"]}
    )


def test_canonical_paths_are_inside_package_runtime_root(tmp_path: Path) -> None:
    worktree, contract = _single_package(tmp_path)
    identity = load_environment_identity(worktree)
    paths = derive_environment_paths(identity)
    validate_environment_paths(identity, paths, contract)

    expected = worktree / ".runtime" / "agent-env" / "PKG-ALPHA"
    assert paths.environment_root == expected
    assert paths.database_path == expected / "db" / "app.sqlite3"
    assert paths.media_root == expected / "media"
    assert paths.secret_root == expected / "secrets"
    assert paths.state_root == expected / "state"


@pytest.mark.parametrize(
    ("field", "error"),
    (
        ("database_path", "PRODUCTION_DATABASE_PATH_REJECTED"),
        ("media_root", "PRODUCTION_MEDIA_PATH_REJECTED"),
        ("secret_root", "PRODUCTION_SECRET_PATH_REJECTED"),
    ),
)
def test_known_production_paths_are_rejected(
    tmp_path: Path, field: str, error: str
) -> None:
    worktree, contract = _single_package(tmp_path)
    identity = load_environment_identity(worktree)
    paths = derive_environment_paths(identity)
    production_value = {
        "database_path": Path(contract.database_roots[0]),
        "media_root": Path(contract.media_roots[0]),
        "secret_root": Path(contract.secret_roots[0]),
    }[field]
    unsafe = replace(paths, **{field: production_value})
    with pytest.raises(EnvironmentContractError, match=error):
        validate_environment_paths(identity, unsafe, contract)


def test_unknown_production_path_status_fails_closed(tmp_path: Path) -> None:
    worktree, _contract = _single_package(tmp_path)
    unknown = ProductionPathContract("UNKNOWN", "UNKNOWN", "UNKNOWN", "UNKNOWN", (), (), (), ())
    with pytest.raises(EnvironmentContractError, match="PRODUCTION_PATH_STATUS_UNKNOWN"):
        build_environment_plan(worktree, environment={}, production_contract=unknown)


def test_outside_git_and_symlink_escape_fail_closed(tmp_path: Path) -> None:
    worktree, contract = _single_package(tmp_path)
    identity = load_environment_identity(worktree)
    paths = derive_environment_paths(identity)

    outside = replace(paths, media_root=tmp_path / "outside-media")
    with pytest.raises(EnvironmentContractError, match="MEDIA_PATH_OUTSIDE_WORKTREE"):
        validate_environment_paths(identity, outside, contract)

    inside_git = replace(paths, media_root=worktree / ".git" / "media")
    with pytest.raises(EnvironmentContractError, match="MEDIA_PATH_INSIDE_GIT"):
        validate_environment_paths(identity, inside_git, contract)

    agent_env = worktree / ".runtime" / "agent-env"
    _directory_link(agent_env, tmp_path / "symlink-escape")
    with pytest.raises(EnvironmentContractError, match="ENVIRONMENT_SYMLINK_ESCAPE"):
        validate_environment_paths(identity, paths, contract)


def test_real_provider_credential_fails_without_exposing_value(tmp_path: Path) -> None:
    worktree, contract = _single_package(tmp_path)
    secret_value = "do-not-leak-this-real-secret"
    with pytest.raises(EnvironmentContractError) as captured:
        build_environment_plan(
            worktree,
            environment={"OPENROUTER_API_KEY": secret_value},
            production_contract=contract,
            timestamp=FIXED_TIME,
        )
    assert "REAL_PROVIDER_CREDENTIAL_PRESENT" in str(captured.value)
    assert "OPENROUTER_API_KEY" in str(captured.value)
    assert secret_value not in str(captured.value)

    inventory = inspect_provider_credentials({"SMTP_PASSWORD": secret_value})
    rendered = json.dumps(inventory, sort_keys=True)
    assert "SMTP_PASSWORD" in rendered
    assert secret_value not in rendered
    assert all(set(item) == {"credentialName", "present", "classification"} for item in inventory)


def test_fake_only_provider_contract_passes(tmp_path: Path) -> None:
    worktree, contract = _single_package(tmp_path)
    plan = build_environment_plan(
        worktree, environment={}, production_contract=contract, timestamp=FIXED_TIME
    )
    assert plan["secretMode"] == "fake-only"
    assert plan["providerMode"] == "isolated"
    assert not any(item["present"] for item in plan["credentials"])

    providers = provider_policy()
    for name in ("telegram", "max", "openrouter", "smtp", "vk-social", "payments"):
        assert providers[name] == {
            "mode": "disabled/fake",
            "localEndpointAllowed": False,
            "externalInternetAllowed": False,
        }
    for name in ("comfyui", "ollama", "qwen"):
        assert providers[name] == {
            "mode": "local-configurable",
            "localEndpointAllowed": True,
            "externalInternetAllowed": False,
        }


def test_port_model_is_valid_distinct_deterministic_and_unreserved() -> None:
    first = derive_candidate_ports("PKG-ALPHA")
    second = derive_candidate_ports("PKG-ALPHA")
    assert first == second
    assert first["backend"] != first["frontend"]
    assert all(1024 <= port <= 65535 for port in first.values())

    other = derive_candidate_ports("PKG-BETA")
    assert set(first.values()).isdisjoint(set(other.values()))
    assert CONTRACT_ID == "izo.agent-env.plan.v1"


def test_stale_or_malformed_ownership_fails_closed(tmp_path: Path) -> None:
    worktree, contract = _single_package(tmp_path)
    ownership = worktree / ".runtime" / "agent" / "ownership.json"
    ownership.write_text("{not-json", encoding="utf-8")
    with pytest.raises(EnvironmentContractError, match="PACKAGE_OWNERSHIP_INVALID"):
        build_environment_plan(worktree, environment={}, production_contract=contract)


def test_receipt_structure_is_deterministic_planned_and_secret_free(tmp_path: Path) -> None:
    worktree, contract = _single_package(tmp_path)
    receipt = write_planned_environment(
        worktree,
        environment={},
        production_contract=contract,
        timestamp=FIXED_TIME,
    )
    identity = load_environment_identity(worktree)
    paths = derive_environment_paths(identity)

    stored_receipt = json.loads(paths.receipt_path.read_text(encoding="utf-8"))
    state = json.loads(paths.environment_state_path.read_text(encoding="utf-8"))
    assert receipt == stored_receipt
    assert stored_receipt["documentType"] == "environment-receipt"
    assert state["documentType"] == "environment-state"
    assert stored_receipt["state"] == "planned"
    assert stored_receipt["createdAt"] == FIXED_TIME
    assert stored_receipt["updatedAt"] == FIXED_TIME
    assert stored_receipt["ports"]["deterministic"] is True
    assert stored_receipt["ports"]["reserved"] is False
    assert stored_receipt["productionPathGuard"]["status"] == "PASS"
    assert not paths.database_path.exists()
    assert not _contains_key(stored_receipt, "pid")
    assert not _contains_key(stored_receipt, "token")
    assert not _contains_key(stored_receipt, "password")
    assert not _contains_key(stored_receipt, "apiKey")


def test_port_collision_fails_without_random_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    control, base = _make_control_repo(tmp_path)
    first_root = _add_package(control, base, "PKG-ALPHA", tmp_path / "alpha")
    _add_package(control, base, "PKG-BETA", tmp_path / "beta")
    contract = _known_contract(tmp_path)

    from tools.agent_system import env as env_module

    original = env_module.derive_candidate_ports

    def collide(package_id: str) -> dict[str, int]:
        if package_id in {"PKG-ALPHA", "PKG-BETA"}:
            return {"backend": 24000, "frontend": 24001}
        return original(package_id)

    monkeypatch.setattr(env_module, "derive_candidate_ports", collide)
    with pytest.raises(EnvironmentContractError, match="PORT_CANDIDATE_COLLISION"):
        env_module.build_environment_plan(
            first_root,
            environment={},
            production_contract=contract,
            timestamp=FIXED_TIME,
        )
