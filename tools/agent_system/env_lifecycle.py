"""Isolated package-environment lifecycle: loopback lease only."""
from __future__ import annotations
import argparse
import hashlib
import hmac
import json
import os
import select
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Mapping
from .env import (
    CONTRACT_ID,
    EnvironmentContractError,
    EnvironmentIdentity,
    EnvironmentPaths,
    ProductionPathContract,
    _load_environment_identity_from_resolved_repo,
    build_environment_plan,
    derive_environment_paths,
    discover_production_path_contract,
    load_environment_identity,
    utc_now,
    validate_environment_paths,
)
from .registry import atomic_write_text, resolve_repo_root
LOOPBACK = "127.0.0.1"
STARTUP_TIMEOUT_SECONDS = 20.0
STOP_TIMEOUT_SECONDS = 8.0
SOCKET_TIMEOUT_SECONDS = 0.5
STATE_NAMES = {"planned", "active", "stale", "stopped"}
class EnvironmentLifecycleError(RuntimeError):
    pass
def _render(payload: Mapping[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise EnvironmentLifecycleError("ENVIRONMENT_STATE_INVALID") from None
    if not isinstance(payload, dict):
        raise EnvironmentLifecycleError("ENVIRONMENT_STATE_INVALID")
    return payload
def _identity_matches(document: Mapping[str, object], identity: EnvironmentIdentity) -> bool:
    return (
        document.get("packageId") == identity.package_id
        and document.get("contractId") == CONTRACT_ID
        and document.get("worktreePath") == str(identity.worktree_path)
    )
def _load_owned_state(identity: EnvironmentIdentity, paths: EnvironmentPaths) -> dict[str, Any] | None:
    if not paths.environment_root.exists():
        return None
    if not paths.environment_root.is_dir():
        raise EnvironmentLifecycleError("UNOWNED_ENVIRONMENT_ROOT")
    state, receipt = _read_json(paths.environment_state_path), _read_json(paths.receipt_path)
    if not _identity_matches(state, identity) or not _identity_matches(receipt, identity):
        raise EnvironmentLifecycleError("UNOWNED_ENVIRONMENT_ROOT")
    if state.get("state") not in STATE_NAMES:
        raise EnvironmentLifecycleError("ENVIRONMENT_STATE_INVALID")
    return state
def _pid_alive(pid: int) -> bool:
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        try:
            exit_code = wintypes.DWORD()
            if not ctypes.windll.kernel32.GetExitCodeProcess(
                handle, ctypes.byref(exit_code)
            ):
                return False
            return exit_code.value == 259
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False
def _exchange(port: int, message: str) -> str | None:
    try:
        with socket.create_connection((LOOPBACK, int(port)), timeout=SOCKET_TIMEOUT_SECONDS) as conn:
            conn.settimeout(SOCKET_TIMEOUT_SECONDS)
            conn.sendall((message + "\n").encode())
            return conn.recv(512).decode(errors="replace").strip()
    except OSError:
        return None
def _port_open(port: int) -> bool:
    try:
        with socket.create_connection((LOOPBACK, int(port)), timeout=SOCKET_TIMEOUT_SECONDS):
            return True
    except OSError:
        return False
def _lease_fields(state: Mapping[str, Any]) -> tuple[int, str, int, int]:
    lease, ports = state.get("portLease"), state.get("ports")
    if not isinstance(lease, dict) or not isinstance(ports, dict):
        raise EnvironmentLifecycleError("ENVIRONMENT_ACTIVE_STATE_INVALID")
    try:
        values = int(lease["pid"]), str(lease["leaseId"]), int(ports["backend"]), int(ports["frontend"])
    except (KeyError, TypeError, ValueError):
        raise EnvironmentLifecycleError("ENVIRONMENT_ACTIVE_STATE_INVALID") from None
    pid, lease_id, backend, frontend = values
    if not lease_id or ports.get("reserved") is not True or backend == frontend:
        raise EnvironmentLifecycleError("ENVIRONMENT_ACTIVE_STATE_INVALID")
    return pid, lease_id, backend, frontend
def _holder_healthy(state: Mapping[str, Any], identity: EnvironmentIdentity) -> bool:
    pid, lease_id, backend, frontend = _lease_fields(state)
    expected = f"LEASE {lease_id} {identity.package_id}"
    replies = (
        _exchange(backend, f"PING {lease_id} {identity.package_id}"),
        _exchange(frontend, f"PING {lease_id} {identity.package_id}"),
    )
    if _pid_alive(pid) and replies == (expected, expected):
        return True
    if _pid_alive(pid):
        raise EnvironmentLifecycleError("FOREIGN_OR_REUSED_PROCESS")
    return False
def environment_status(repo_root: Path | str) -> dict[str, object]:
    repo = resolve_repo_root(repo_root)
    try:
        identity = load_environment_identity(repo)
    except EnvironmentContractError as exc:
        raise EnvironmentLifecycleError(str(exc)) from None
    paths = derive_environment_paths(identity)
    state = _load_owned_state(identity, paths)
    if state is None:
        return {"status": "MISSING", "packageId": identity.package_id}
    recorded = str(state.get("state"))
    if recorded in {"planned", "stopped", "stale"}:
        return {"status": recorded.upper(), "packageId": identity.package_id}
    if not _holder_healthy(state, identity):
        return {"status": "STALE", "packageId": identity.package_id}
    pid, lease_id, backend, frontend = _lease_fields(state)
    return {
        "status": "ACTIVE",
        "packageId": identity.package_id,
        "pid": pid,
        "leaseId": lease_id,
        "ports": {"backend": backend, "frontend": frontend},
    }
def _runtime_dirs(paths: EnvironmentPaths) -> tuple[Path, ...]:
    return paths.environment_root / "db", paths.media_root, paths.secret_root, paths.state_root
STARTUP_DIAGNOSTIC_STAGES = {
    "HOLDER_ENTERED",
    "IDENTITY_ENTERED",
    "RESOLVE_REPO_ROOT_START",
    "RESOLVE_REPO_ROOT_OK",
    "LOAD_REGISTRY_START",
    "REGISTRY_COMMON_DIR_START",
    "REGISTRY_COMMON_DIR_OK",
    "REGISTRY_FILE_CHECK_START",
    "REGISTRY_FILE_CHECK_OK",
    "REGISTRY_FILE_READ_START",
    "REGISTRY_FILE_READ_OK",
    "REGISTRY_JSON_PARSE_OK",
    "LOAD_REGISTRY_OK",
    "ASSERT_OWNER_START",
    "OWNERSHIP_READ_START",
    "OWNERSHIP_READ_OK",
    "REGISTRY_ENTRY_LOOKUP_START",
    "REGISTRY_ENTRY_LOOKUP_OK",
    "OWNERSHIP_TOKEN_CHECK_START",
    "OWNERSHIP_TOKEN_CHECK_OK",
    "WORKTREE_PATH_CHECK_START",
    "WORKTREE_PATH_CHECK_OK",
    "BRANCH_QUERY_START",
    "BRANCH_QUERY_OK",
    "MANIFEST_PARSE_START",
    "MANIFEST_PARSE_OK",
    "MANIFEST_FINGERPRINT_START",
    "MANIFEST_FINGERPRINT_OK",
    "OWNER_ASSERT_OK",
    "ASSERT_OWNER_OK",
    "IDENTITY_OK",
    "OWNERSHIP_OK",
    "SOCKETS_BOUND",
    "READY_WRITTEN",
}

def _startup_diagnostic_path(startup: Path) -> Path:
    prefix = "lease-startup-"
    suffix = startup.name[len(prefix):] if startup.name.startswith(prefix) else startup.name
    return startup.with_name("lease-diagnostic-" + suffix)

def _write_startup_diagnostic(path: Path, stage: str, pid: int) -> None:
    if stage not in STARTUP_DIAGNOSTIC_STAGES:
        raise EnvironmentLifecycleError("PORT_LEASE_DIAGNOSTIC_STAGE_INVALID")
    atomic_write_text(path, _render({"stage": stage, "pid": int(pid)}))

def _read_startup_diagnostic(path: Path) -> tuple[str, int | None]:
    if not path.is_file():
        return "PRE_HOLDER_ENTRY", None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return "PRE_HOLDER_ENTRY", None
    stage, pid = str(payload.get("stage") or ""), payload.get("pid")
    if stage not in STARTUP_DIAGNOSTIC_STAGES:
        return "PRE_HOLDER_ENTRY", None
    return stage, pid if isinstance(pid, int) and not isinstance(pid, bool) and pid > 0 else None

def _startup_diagnostic_line(
    *, stage: str, process_alive: bool, pid: int,
    elapsed_ms: int | None = None, exit_code: int | None = None,
) -> str:
    alive_key = "processAliveBeforeTerminate" if elapsed_ms is not None else "processAlive"
    fields = ["PORT_LEASE_START_DIAGNOSTIC", f"stage={stage}",
              f"{alive_key}={str(process_alive).lower()}", f"pid={int(pid)}"]
    if elapsed_ms is not None:
        fields.append(f"elapsedMs={max(0, min(int(elapsed_ms), 120000))}")
    if exit_code is not None:
        fields.append(f"exitCode={int(exit_code)}")
    return " ".join(fields)

def _spawn_holder(
    repo: Path,
    identity: EnvironmentIdentity,
    paths: EnvironmentPaths,
    backend: int,
    frontend: int,
    lease_id: str,
) -> tuple[subprocess.Popen[Any], Path]:
    startup = paths.state_root / f"lease-startup-{lease_id}.json"
    command = [
        sys.executable, "-m", "tools.agent_system.env_lifecycle", "--repo-root", str(repo),
        "_holder", "--package-id", identity.package_id, "--lease-id", lease_id,
        "--backend-port", str(backend), "--frontend-port", str(frontend),
        "--startup-file", str(startup),
    ]
    child_env = {
        name: os.environ[name]
        for name in ("PATH", "SystemRoot", "WINDIR", "TEMP", "TMP", "HOME")
        if name in os.environ
    }
    source_root = str(Path(__file__).resolve().parents[2])
    child_env["PYTHONPATH"] = source_root
    kwargs: dict[str, Any] = {
        "cwd": str(repo), "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL, "close_fds": True, "env": child_env,
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    return subprocess.Popen(command, **kwargs), startup
def _wait_startup(process: subprocess.Popen[Any], startup: Path) -> dict[str, Any]:
    started = time.monotonic()
    deadline = started + STARTUP_TIMEOUT_SECONDS
    diagnostic = _startup_diagnostic_path(startup)
    while time.monotonic() < deadline:
        if startup.exists():
            payload = _read_json(startup)
            if payload.get("status") == "READY":
                diagnostic.unlink(missing_ok=True)
                return payload
            raise EnvironmentLifecycleError(str(payload.get("error") or "PORT_LEASE_START_FAILED"))
        exit_code = process.poll()
        if exit_code is not None:
            stage, _diagnostic_pid = _read_startup_diagnostic(diagnostic)
            print(
                _startup_diagnostic_line(
                    stage=stage,
                    process_alive=False,
                    pid=process.pid,
                    exit_code=int(exit_code),
                ),
                file=sys.stderr,
                flush=True,
            )
            raise EnvironmentLifecycleError("PORT_LEASE_START_FAILED")
        time.sleep(0.05)
    stage, _diagnostic_pid = _read_startup_diagnostic(diagnostic)
    process_alive = process.poll() is None
    elapsed_ms = int((time.monotonic() - started) * 1000)
    print(
        _startup_diagnostic_line(
            stage=stage,
            process_alive=process_alive,
            pid=process.pid,
            elapsed_ms=elapsed_ms,
        ),
        file=sys.stderr,
        flush=True,
    )
    process.terminate()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass
    print(
        "PORT_LEASE_CLEANUP_DIAGNOSTIC "
        f"processAliveAfterTerminate={str(process.poll() is None).lower()}",
        file=sys.stderr,
        flush=True,
    )
    raise EnvironmentLifecycleError("PORT_LEASE_START_TIMEOUT")
def _active_document(plan: Mapping[str, Any], pid: int, lease_id: str, stamp: str) -> dict[str, object]:
    ports = dict(plan["ports"])
    ports["reserved"] = True
    return {
        **plan,
        "state": "active",
        "ports": ports,
        "portLease": {"pid": pid, "leaseId": lease_id, "startedAt": stamp},
        "databaseInitialization": "NOT_STARTED",
        "updatedAt": stamp,
    }
def env_up(
    repo_root: Path | str,
    *,
    environment: Mapping[str, str] | None = None,
    production_contract: ProductionPathContract | None = None,
) -> dict[str, object]:
    repo = resolve_repo_root(repo_root)
    try:
        identity = load_environment_identity(repo)
        paths = derive_environment_paths(identity)
        state = _load_owned_state(identity, paths)
        if state is not None and state.get("state") == "active":
            current = environment_status(repo)
            if current["status"] == "ACTIVE":
                return {"result": "ALREADY_ACTIVE", **current}
            raise EnvironmentLifecycleError("ENVIRONMENT_STALE_RECOVERY_REQUIRED")
        plan = build_environment_plan(
            repo, environment=environment, production_contract=production_contract
        )
    except EnvironmentContractError as exc:
        raise EnvironmentLifecycleError(str(exc)) from None
    for directory in _runtime_dirs(paths):
        directory.mkdir(parents=True, exist_ok=True)
    try:
        validate_environment_paths(
            identity, paths, production_contract or discover_production_path_contract(repo)
        )
    except EnvironmentContractError as exc:
        raise EnvironmentLifecycleError(str(exc)) from None
    backend, frontend = int(plan["ports"]["backend"]), int(plan["ports"]["frontend"])
    lease_id = __import__("secrets").token_hex(16)
    process, startup = _spawn_holder(repo, identity, paths, backend, frontend, lease_id)
    try:
        ready = _wait_startup(process, startup)
        if int(ready.get("pid", -1)) != process.pid:
            raise EnvironmentLifecycleError("PORT_LEASE_IDENTITY_MISMATCH")
        stamp = utc_now()
        active = _active_document(plan, process.pid, lease_id, stamp)
        atomic_write_text(paths.environment_state_path, _render({"documentType": "environment-state", **active}))
        atomic_write_text(paths.receipt_path, _render({"documentType": "environment-receipt", **active}))
        startup.unlink(missing_ok=True)
        if environment_status(repo)["status"] != "ACTIVE":
            raise EnvironmentLifecycleError("PORT_LEASE_HEALTH_CHECK_FAILED")
        return {
            "status": "ACTIVE", "packageId": identity.package_id, "pid": process.pid,
            "leaseId": lease_id, "ports": {"backend": backend, "frontend": frontend},
        }
    except Exception:
        startup.unlink(missing_ok=True)
        _startup_diagnostic_path(startup).unlink(missing_ok=True)
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
        raise
def _wait_released(pid: int, backend: int, frontend: int) -> None:
    deadline = time.monotonic() + STOP_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if not _pid_alive(pid) and not _port_open(backend) and not _port_open(frontend):
            return
        time.sleep(0.05)
    raise EnvironmentLifecycleError("PORT_LEASE_STOP_TIMEOUT")
def _cleanup_payload(paths: EnvironmentPaths) -> None:
    root = paths.environment_root.resolve(strict=True)
    for target in (paths.environment_root / "db", paths.media_root, paths.secret_root):
        if not target.exists():
            continue
        if target.is_symlink():
            raise EnvironmentLifecycleError("CLEANUP_SYMLINK_FORBIDDEN")
        try:
            target.resolve(strict=False).relative_to(root)
        except ValueError:
            raise EnvironmentLifecycleError("CLEANUP_PATH_OUTSIDE_ENVIRONMENT") from None
        shutil.rmtree(target) if target.is_dir() else target.unlink()
    for pattern in ("lease-startup-*.json", "lease-diagnostic-*.json"):
        for startup in paths.state_root.glob(pattern):
            if startup.is_symlink():
                raise EnvironmentLifecycleError("CLEANUP_SYMLINK_FORBIDDEN")
            startup.unlink(missing_ok=True)
def _write_stopped(
    identity: EnvironmentIdentity,
    paths: EnvironmentPaths,
    previous: Mapping[str, Any],
    recovered: bool,
) -> dict[str, object]:
    stamp = utc_now()
    ports = dict(previous.get("ports") or {})
    ports["reserved"] = False
    document = {
        "schemaVersion": previous.get("schemaVersion", 1),
        "contractId": CONTRACT_ID,
        "packageId": identity.package_id,
        "baseSha": previous.get("baseSha", identity.base_sha),
        "worktreePath": str(identity.worktree_path),
        "environmentRoot": str(paths.environment_root),
        "databasePath": str(paths.database_path),
        "mediaRoot": str(paths.media_root),
        "secretRoot": str(paths.secret_root),
        "state": "stopped",
        "ports": ports,
        "databaseInitialization": "NOT_STARTED",
        "cleanup": "PASS",
        "recoveredStale": recovered,
        "createdAt": previous.get("createdAt", stamp),
        "updatedAt": stamp,
    }
    atomic_write_text(paths.environment_state_path, _render({"documentType": "environment-state", **document}))
    atomic_write_text(paths.receipt_path, _render({"documentType": "environment-receipt", **document}))
    return document
def env_down(
    repo_root: Path | str,
    *,
    recover_stale: bool = False,
    production_contract: ProductionPathContract | None = None,
) -> dict[str, object]:
    repo = resolve_repo_root(repo_root)
    try:
        identity = load_environment_identity(repo)
    except EnvironmentContractError as exc:
        raise EnvironmentLifecycleError(str(exc)) from None
    paths = derive_environment_paths(identity)
    state = _load_owned_state(identity, paths)
    if state is None or state.get("state") == "stopped":
        return {"status": "ALREADY_STOPPED", "packageId": identity.package_id}
    try:
        validate_environment_paths(
            identity, paths, production_contract or discover_production_path_contract(repo)
        )
    except EnvironmentContractError as exc:
        raise EnvironmentLifecycleError(str(exc)) from None
    current = environment_status(repo)
    if current["status"] == "ACTIVE":
        pid, lease_id, backend, frontend = _lease_fields(state)
        proof = _control_proof(repo, identity.package_id, lease_id)
        reply = _exchange(
            backend, f"STOP {lease_id} {identity.package_id} {proof}"
        )
        if reply != f"STOPPING {lease_id} {identity.package_id}":
            raise EnvironmentLifecycleError("LEASE_COOPERATIVE_STOP_REJECTED")
        _wait_released(pid, backend, frontend)
        _cleanup_payload(paths)
        stopped = _write_stopped(identity, paths, state, False)
        return {"status": "STOPPED", "cleanup": stopped["cleanup"]}
    if current["status"] == "PLANNED":
        raise EnvironmentLifecycleError("ENVIRONMENT_NOT_ACTIVE")
    if current["status"] != "STALE":
        raise EnvironmentLifecycleError("ENVIRONMENT_NOT_ACTIVE")
    if not recover_stale:
        raise EnvironmentLifecycleError("ENVIRONMENT_STALE_RECOVERY_REQUIRED")
    pid, _lease_id, backend, frontend = _lease_fields(state)
    if _pid_alive(pid):
        raise EnvironmentLifecycleError("FOREIGN_OR_REUSED_PROCESS")
    if _port_open(backend) or _port_open(frontend):
        raise EnvironmentLifecycleError("STALE_PORT_FOREIGN_OCCUPANT")
    _cleanup_payload(paths)
    stopped = _write_stopped(identity, paths, state, True)
    return {"status": "STOPPED", "cleanup": stopped["cleanup"], "recoveredStale": True}
def _exclusive_socket(port: int) -> socket.socket:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    try:
        listener.bind((LOOPBACK, int(port)))
        listener.listen(8)
        listener.setblocking(False)
        return listener
    except OSError:
        listener.close()
        raise
def _control_proof(repo: Path, package_id: str, lease_id: str) -> str:
    try:
        ownership = json.loads(
            (repo / ".runtime" / "agent" / "ownership.json").read_text(
                encoding="utf-8"
            )
        )
        if ownership.get("packageId") != package_id or not ownership.get("token"):
            raise ValueError
        token = str(ownership["token"]).encode()
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, AttributeError):
        raise EnvironmentLifecycleError("PACKAGE_OWNERSHIP_INVALID") from None
    message = f"{CONTRACT_ID}|{package_id}|{lease_id}".encode()
    return hmac.new(token, message, hashlib.sha256).hexdigest()
def _holder(
    repo: Path,
    package_id: str,
    lease_id: str,
    backend: int,
    frontend: int,
    startup_file: Path,
) -> int:
    listeners: list[socket.socket] = []
    diagnostic = _startup_diagnostic_path(startup_file)
    record_stage = lambda stage: _write_startup_diagnostic(
        diagnostic, stage, os.getpid()
    )
    record_stage("HOLDER_ENTERED")
    try:
        try:
            identity = _load_environment_identity_from_resolved_repo(
                repo, diagnostic=record_stage
            )
            if identity.package_id != package_id:
                raise EnvironmentContractError("PACKAGE_OWNERSHIP_INVALID")
            stop_proof = _control_proof(repo, package_id, lease_id)
            _write_startup_diagnostic(diagnostic, "OWNERSHIP_OK", os.getpid())
        except (EnvironmentContractError, EnvironmentLifecycleError):
            atomic_write_text(
                startup_file,
                _render({"status": "ERROR", "error": "PACKAGE_OWNERSHIP_INVALID"}),
            )
            return 2
        try:
            listeners.append(_exclusive_socket(backend))
            listeners.append(_exclusive_socket(frontend))
            _write_startup_diagnostic(diagnostic, "SOCKETS_BOUND", os.getpid())
        except OSError:
            atomic_write_text(
                startup_file, _render({"status": "ERROR", "error": "PORT_IN_USE"})
            )
            return 2
        atomic_write_text(startup_file, _render({"status": "READY", "pid": os.getpid()}))
        _write_startup_diagnostic(diagnostic, "READY_WRITTEN", os.getpid())
        diagnostic.unlink(missing_ok=True)
        running = True
        while running:
            readable, _, _ = select.select(listeners, [], [], 0.5)
            for listener in readable:
                connection, _ = listener.accept()
                with connection:
                    connection.settimeout(SOCKET_TIMEOUT_SECONDS)
                    try:
                        request = connection.recv(512).decode(errors="replace").strip()
                    except OSError:
                        continue
                    if request == f"PING {lease_id} {package_id}":
                        response = f"LEASE {lease_id} {package_id}"
                    elif request == f"STOP {lease_id} {package_id} {stop_proof}":
                        response, running = f"STOPPING {lease_id} {package_id}", False
                    else:
                        response = "DENIED"
                    try:
                        connection.sendall((response + "\n").encode())
                    except OSError:
                        pass
        return 0
    finally:
        for listener in listeners:
            listener.close()
def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-env-lifecycle")
    parser.add_argument("--repo-root", default=".")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("up")
    sub.add_parser("status")
    down = sub.add_parser("down")
    down.add_argument("--recover-stale", action="store_true")
    holder = sub.add_parser("_holder")
    holder.add_argument("--package-id", required=True)
    holder.add_argument("--lease-id", required=True)
    holder.add_argument("--backend-port", type=int, required=True)
    holder.add_argument("--frontend-port", type=int, required=True)
    holder.add_argument("--startup-file", required=True)
    return parser
def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "_holder":
        try:
            repo = Path(args.repo_root).resolve(strict=True)
        except (OSError, RuntimeError):
            print("PACKAGE_OWNERSHIP_INVALID", file=sys.stderr)
            return 2
    else:
        repo = resolve_repo_root(args.repo_root)
    try:
        if args.command == "up":
            print("AGENT_ENV_UP " + json.dumps(env_up(repo), sort_keys=True))
            return 0
        if args.command == "status":
            print("AGENT_ENV_STATUS " + json.dumps(environment_status(repo), sort_keys=True))
            return 0
        if args.command == "down":
            print("AGENT_ENV_DOWN " + json.dumps(env_down(repo, recover_stale=args.recover_stale), sort_keys=True))
            return 0
        if args.command == "_holder":
            return _holder(
                repo, args.package_id, args.lease_id, args.backend_port,
                args.frontend_port, Path(args.startup_file),
            )
    except (EnvironmentContractError, EnvironmentLifecycleError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 3
if __name__ == "__main__":
    raise SystemExit(main())
