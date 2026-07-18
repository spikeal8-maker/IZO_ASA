"""Create and validate exact-SHA release verification receipts.

The receipt is intentionally secret-free. It is an integrity and freshness
contract for the local release workflow, not a replacement for repository access
control or a cryptographic signature service.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


RECEIPT_VERSION = 1
RECEIPT_TYPE = "release-verification"
RECEIPT_TTL = timedelta(hours=4)
CLOCK_SKEW = timedelta(minutes=5)
FULL_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
REQUIRED_RELEASE_GATES = (
    "py_compile",
    "backend_map_check",
    "architecture_inventory_check",
    "caddy_runtime_integrity",
    "caddy_config_validation",
    "pytest_full",
    "frontend_lint",
    "frontend_build",
    "frontend_release_identity",
    "frontend_origin_isolation",
    "frontend_studio_resilience",
)
FULL_ONLY_GATES = (
    "backend_preflight",
    "runtime_listener_contract",
    "caddy_edge_live",
    "source_snapshot",
)


class ReceiptError(ValueError):
    """A stable, secret-free release receipt validation error."""


def _run(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        list(arguments),
        cwd=root,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        raise ReceiptError("release receipt command failed")
    return result.stdout.strip()


def _git_state(root: Path) -> tuple[str, str, bool]:
    sha = _run(root, "git", "rev-parse", "HEAD")
    branch = _run(root, "git", "branch", "--show-current") or "detached"
    dirty = bool(_run(root, "git", "status", "--porcelain"))
    if not FULL_GIT_SHA.fullmatch(sha):
        raise ReceiptError("release receipt requires a full lowercase git SHA")
    return sha, branch, dirty


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _canonical_receipt_path(root: Path, value: Path) -> Path:
    root = root.resolve()
    allowed = (root / ".runtime" / "verification").resolve()
    candidate = (value if value.is_absolute() else root / value).resolve()
    if not _is_within(candidate, allowed) or candidate.suffix.lower() != ".json":
        raise ReceiptError("receipt must be inside the canonical verification directory")
    return candidate


def _as_utc(value: datetime | str, *, field: str) -> datetime:
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ReceiptError(f"{field} must be an ISO timestamp") from exc
    elif isinstance(value, datetime):
        parsed = value
    else:
        raise ReceiptError(f"{field} must be an ISO timestamp")
    if parsed.tzinfo is None:
        raise ReceiptError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _payload_digest(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def write_receipt(
    *,
    root: Path,
    output_path: Path,
    mode: str,
    started_at: datetime | str,
    completed_at: datetime | str,
    duration_seconds: float,
    summary: dict[str, Any],
) -> dict[str, Any]:
    root = root.resolve()
    output = _canonical_receipt_path(root, output_path)
    if mode not in {"Full", "CI"}:
        raise ReceiptError("release receipt requires Full or CI verification mode")
    if duration_seconds < 0:
        raise ReceiptError("verification duration cannot be negative")
    if not isinstance(summary, dict) or summary.get("ok") is not True:
        raise ReceiptError("verification summary must be successful")
    if summary.get("mode") not in {None, mode}:
        raise ReceiptError("verification summary mode mismatch")

    started = _as_utc(started_at, field="started_at")
    completed = _as_utc(completed_at, field="completed_at")
    if started > completed:
        raise ReceiptError("verification timestamps are invalid")
    sha, branch, dirty = _git_state(root)
    if branch != "main":
        raise ReceiptError("release receipt requires branch main")
    if dirty:
        raise ReceiptError("release receipt requires a clean checkout")

    verifier = root / "tools" / "verify.ps1"
    if not verifier.is_file():
        raise ReceiptError("verification script is missing")
    gates = list(REQUIRED_RELEASE_GATES)
    if mode == "Full":
        gates.extend(FULL_ONLY_GATES)
    receipt_id = f"{sha[:12]}-{completed.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:12]}"
    payload: dict[str, Any] = {
        "receipt_version": RECEIPT_VERSION,
        "receipt_type": RECEIPT_TYPE,
        "receipt_id": receipt_id,
        "ok": True,
        "git_sha": sha,
        "branch": branch,
        "dirty": False,
        "mode": mode,
        "started_at": _iso(started),
        "completed_at": _iso(completed),
        "expires_at": _iso(completed + RECEIPT_TTL),
        "duration_seconds": round(float(duration_seconds), 2),
        "gates": gates,
        "verifier_sha256": _sha256(verifier),
        "python_version": platform.python_version(),
        "summary": summary,
    }
    payload["payload_sha256"] = _payload_digest(payload)

    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise ReceiptError("refusing to overwrite an existing release receipt")
    temporary = output.with_suffix(f".json.tmp-{uuid.uuid4().hex}")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    return payload


def validate_receipt(
    *,
    root: Path,
    receipt_path: Path,
    expected_sha: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    path = _canonical_receipt_path(root, receipt_path)
    if not path.is_file():
        raise ReceiptError("release verification receipt was not found")
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReceiptError("release verification receipt is unreadable") from exc
    if not isinstance(payload, dict):
        raise ReceiptError("release verification receipt must be an object")

    supplied_digest = payload.get("payload_sha256")
    unsigned = dict(payload)
    unsigned.pop("payload_sha256", None)
    if not isinstance(supplied_digest, str) or supplied_digest != _payload_digest(unsigned):
        raise ReceiptError("release verification receipt integrity mismatch")
    if payload.get("receipt_version") != RECEIPT_VERSION or payload.get("receipt_type") != RECEIPT_TYPE:
        raise ReceiptError("release verification receipt version/type mismatch")
    if payload.get("ok") is not True or payload.get("dirty") is not False:
        raise ReceiptError("release verification receipt is not successful and clean")
    if payload.get("mode") not in {"Full", "CI"}:
        raise ReceiptError("release verification receipt mode is invalid")

    sha = str(payload.get("git_sha", ""))
    if not FULL_GIT_SHA.fullmatch(sha):
        raise ReceiptError("release verification receipt SHA is invalid")
    if not str(payload.get("receipt_id", "")).startswith(sha[:12] + "-"):
        raise ReceiptError("release verification receipt ID does not match SHA")
    actual_sha, branch, dirty = _git_state(root)
    if dirty:
        raise ReceiptError("release verification requires a clean checkout")
    if branch != "main" or payload.get("branch") != "main":
        raise ReceiptError("release verification receipt requires branch main")
    if sha != actual_sha or (expected_sha is not None and sha != expected_sha):
        raise ReceiptError("release verification receipt does not match the exact checkout SHA")

    started = _as_utc(payload.get("started_at"), field="started_at")
    completed = _as_utc(payload.get("completed_at"), field="completed_at")
    expires = _as_utc(payload.get("expires_at"), field="expires_at")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if started > completed or expires <= completed or expires - completed > RECEIPT_TTL:
        raise ReceiptError("release verification receipt timestamps are invalid")
    if current < completed - CLOCK_SKEW:
        raise ReceiptError("release verification receipt is from the future")
    if current > expires:
        raise ReceiptError("release verification receipt expired")

    gates = payload.get("gates")
    if not isinstance(gates, list) or not all(isinstance(item, str) for item in gates):
        raise ReceiptError("release verification receipt gates are invalid")
    if not set(REQUIRED_RELEASE_GATES).issubset(gates):
        raise ReceiptError("release verification receipt is missing required gates")
    if payload.get("mode") == "Full" and not set(FULL_ONLY_GATES).issubset(gates):
        raise ReceiptError("full release verification receipt is missing live gates")

    verifier = root / "tools" / "verify.ps1"
    if not verifier.is_file() or payload.get("verifier_sha256") != _sha256(verifier):
        raise ReceiptError("release verification receipt verifier hash mismatch")
    if payload.get("python_version") != platform.python_version():
        raise ReceiptError("release verification receipt Python version mismatch")
    summary = payload.get("summary")
    if not isinstance(summary, dict) or summary.get("ok") is not True or summary.get("mode") != payload.get("mode"):
        raise ReceiptError("release verification receipt summary mismatch")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    write = subparsers.add_parser("write")
    write.add_argument("--root", type=Path, required=True)
    write.add_argument("--output", type=Path, required=True)
    write.add_argument("--mode", choices=("Full", "CI"), required=True)
    write.add_argument("--started-at", required=True)
    write.add_argument("--duration-seconds", type=float, required=True)
    write.add_argument("--summary-json", required=True)

    validate = subparsers.add_parser("validate")
    validate.add_argument("--root", type=Path, required=True)
    validate.add_argument("--receipt", type=Path, required=True)
    validate.add_argument("--expected-sha", required=True)

    args = parser.parse_args()
    try:
        if args.command == "write":
            summary = json.loads(args.summary_json)
            completed = datetime.now(timezone.utc)
            payload = write_receipt(
                root=args.root,
                output_path=args.output,
                mode=args.mode,
                started_at=args.started_at,
                completed_at=completed,
                duration_seconds=args.duration_seconds,
                summary=summary,
            )
            print(
                "VERIFY_RECEIPT_WRITTEN "
                f"path={Path(args.output).resolve()} id={payload['receipt_id']} "
                f"sha={payload['git_sha']} expires={payload['expires_at']}"
            )
        else:
            payload = validate_receipt(
                root=args.root,
                receipt_path=args.receipt,
                expected_sha=args.expected_sha,
            )
            print(
                "RELEASE_VERIFICATION_RECEIPT_OK "
                f"path={Path(args.receipt).resolve()} id={payload['receipt_id']} "
                f"sha={payload['git_sha']} mode={payload['mode']} expires={payload['expires_at']}"
            )
    except (ReceiptError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
