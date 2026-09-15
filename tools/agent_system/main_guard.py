from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

MAIN_REF = "refs/heads/main"

class MainGuardError(RuntimeError):
    pass

def normalize_ref(value: str) -> str:
    ref = value.strip()
    return MAIN_REF if ref == "main" else ref

def assert_remote_target_allowed(remote_ref: str) -> str:
    ref = normalize_ref(remote_ref)
    if not ref:
        raise MainGuardError("MAIN_GUARD_TARGET_MISSING")
    if ref == MAIN_REF:
        raise MainGuardError(f"DIRECT_MAIN_FORBIDDEN target={MAIN_REF}")
    return ref

def _git(repo_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise MainGuardError(f"MAIN_GUARD_GIT_FAILED detail={detail}")
    return result.stdout.strip()

def assert_local_mutation_allowed(repo_root: Path) -> str:
    branch = _git(repo_root.resolve(), "branch", "--show-current")
    if not branch:
        raise MainGuardError("DIRECT_MAIN_FORBIDDEN reason=detached-or-ambiguous-branch")
    if branch == "main":
        raise MainGuardError("DIRECT_MAIN_FORBIDDEN target=refs/heads/main")
    return branch

def check_pre_push_stream(payload: str) -> int:
    checked = 0
    for line_number, raw_line in enumerate(payload.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 4:
            raise MainGuardError(f"PRE_PUSH_INPUT_INVALID line={line_number}")
        _local_ref, _local_sha, remote_ref, _remote_sha = parts
        assert_remote_target_allowed(remote_ref)
        checked += 1
    return checked

def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="main_guard")
    sub = parser.add_subparsers(dest="command", required=True)
    target = sub.add_parser("check-target")
    target.add_argument("--ref", required=True)
    local = sub.add_parser("check-local")
    local.add_argument("--repo-root", default=".")
    sub.add_parser("pre-push")
    return parser

def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "check-target":
            ref = assert_remote_target_allowed(args.ref)
            print(f"MAIN_GUARD_OK target={ref}")
            return 0
        if args.command == "check-local":
            branch = assert_local_mutation_allowed(Path(args.repo_root))
            print(f"MAIN_GUARD_OK branch={branch}")
            return 0
        checked = check_pre_push_stream(sys.stdin.read())
        print(f"MAIN_GUARD_OK refs={checked}")
        return 0
    except MainGuardError as exc:
        print(str(exc), file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
