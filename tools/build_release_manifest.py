"""Build an immutable, secret-free release manifest for a frontend artifact."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
FULL_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
RELEASE_ID = re.compile(r"^[0-9a-f]{12}-[0-9]{14}$")
EXCLUDED_ARTIFACTS = {"release.json", "release-manifest.json"}


def normalize_runtime_version(value: str) -> str:
    normalized = value.strip().removeprefix("v")
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", normalized):
        raise ValueError("runtime version must use major.minor.patch")
    return normalized


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def frontend_asset_inventory(release_path: Path) -> tuple[list[dict[str, Any]], str]:
    rows: list[dict[str, Any]] = []
    for path in sorted(release_path.rglob("*")):
        if not path.is_file() or path.name in EXCLUDED_ARTIFACTS:
            continue
        if path.is_symlink():
            raise ValueError("frontend release must not contain symlinks")
        relative = path.relative_to(release_path).as_posix()
        rows.append({"path": relative, "size": path.stat().st_size, "sha256": _sha256(path)})
    if not rows:
        raise ValueError("frontend release contains no assets")
    digest = hashlib.sha256()
    for row in rows:
        digest.update(row["path"].encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(row["size"]).encode("ascii"))
        digest.update(b"\0")
        digest.update(row["sha256"].encode("ascii"))
        digest.update(b"\n")
    return rows, "sha256:" + digest.hexdigest()


def build_manifest(
    *,
    release_path: Path,
    release_id: str,
    git_sha: str,
    built_at: str,
    python_version: str,
    node_version: str,
    schema_min_version: int,
    schema_max_version: int,
) -> dict[str, Any]:
    if not RELEASE_ID.fullmatch(release_id):
        raise ValueError("release id is invalid")
    if not FULL_GIT_SHA.fullmatch(git_sha):
        raise ValueError("git SHA must be a full lowercase commit")
    if not release_id.startswith(git_sha[:12] + "-"):
        raise ValueError("release id must start with the commit prefix")
    parsed_time = datetime.fromisoformat(built_at.replace("Z", "+00:00"))
    if parsed_time.tzinfo is None:
        raise ValueError("built_at must include a timezone")
    python_version = normalize_runtime_version(python_version)
    node_version = normalize_runtime_version(node_version)
    if schema_min_version <= 0 or schema_max_version < schema_min_version:
        raise ValueError("schema compatibility range is invalid")
    assets, asset_hash = frontend_asset_inventory(release_path)
    return {
        "manifest_version": 1,
        "release_id": release_id,
        "git_sha": git_sha,
        "dirty": False,
        "built_at": built_at,
        "frontend_asset_manifest_hash": asset_hash,
        "frontend_asset_count": len(assets),
        "python_version": python_version,
        "node_version": node_version,
        "schema_compatibility": {
            "min_version": schema_min_version,
            "max_version": schema_max_version,
        },
    }


def _run(root: Path, *arguments: str) -> str:
    command = list(arguments)
    if command and command[0] == "git":
        command[1:1] = ["-c", f"safe.directory={root}"]
    result = subprocess.run(
        command,
        cwd=root,
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("release command failed")
    return result.stdout.strip()


def _resolve(root: Path, value: Path) -> Path:
    return value if value.is_absolute() else root / value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    parser.add_argument("--release-path", type=Path, required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--git-sha", required=True)
    parser.add_argument("--built-at", default="")
    parser.add_argument("--output", type=Path, default=Path("release-manifest.json"))
    args = parser.parse_args()

    root = args.root.resolve()
    release_path = _resolve(root, args.release_path).resolve()
    allowed_root = (root / ".runtime" / "releases" / "frontend").resolve()
    try:
        release_path.relative_to(allowed_root)
    except ValueError:
        raise SystemExit("release path is outside the canonical runtime") from None
    if not release_path.is_dir():
        raise SystemExit("release path does not exist")

    current_sha = _run(root, "git", "rev-parse", "HEAD")
    if current_sha != args.git_sha or not FULL_GIT_SHA.fullmatch(current_sha):
        raise SystemExit("release SHA does not match the current checkout")
    if _run(root, "git", "status", "--porcelain"):
        raise SystemExit("release checkout is dirty")

    python_pin = (root / ".python-version").read_text(encoding="utf-8").strip()
    node_pin = (root / ".node-version").read_text(encoding="utf-8").strip()
    actual_python = platform.python_version()
    actual_node = normalize_runtime_version(_run(root, "node", "--version"))
    if normalize_runtime_version(python_pin) != actual_python:
        raise SystemExit("Python runtime does not match .python-version")
    if normalize_runtime_version(node_pin) != actual_node:
        raise SystemExit("Node.js runtime does not match .node-version")

    contract = json.loads((root / "architecture" / "contract.json").read_text(encoding="utf-8"))
    schema = contract["release_contract"]["schema_compatibility"]
    built_at = args.built_at or datetime.now(timezone.utc).isoformat()
    manifest = build_manifest(
        release_path=release_path,
        release_id=args.release_id,
        git_sha=args.git_sha,
        built_at=built_at,
        python_version=actual_python,
        node_version=actual_node,
        schema_min_version=int(schema["min_version"]),
        schema_max_version=int(schema["max_version"]),
    )
    output_path = args.output if args.output.is_absolute() else release_path / args.output
    temporary_path = output_path.with_suffix(output_path.suffix + ".tmp")
    temporary_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary_path.replace(output_path)
    print(f"RELEASE_MANIFEST_OK path={output_path} release={manifest['release_id']} assets={manifest['frontend_asset_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
