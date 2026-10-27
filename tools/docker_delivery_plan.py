"""Read-only ISOAS install/update planner; never authorizes an apply operation."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

try:
    from tools.docker_delivery_probe import ProbeError, TargetInfo, probe_target
except ModuleNotFoundError:
    from docker_delivery_probe import ProbeError, TargetInfo, probe_target

SHA = re.compile(r"^[0-9a-f]{40}$")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
IMAGE_REPOSITORY = re.compile(
    r"^[a-z0-9]+(?:[._-][a-z0-9]+)*(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)+$"
)
ROLES = frozenset({"backend", "web", "guard", "worker"})
MAX_MANIFEST_BYTES = 16 * 1024
EXIT_CODES = {
    "READY": 0,
    "INVALID_INPUT": 2,
    "TARGET_UNAVAILABLE": 3,
    "OWNERSHIP_CONFLICT": 4,
    "INCOMPATIBLE_RELEASE": 5,
}


class PlanError(RuntimeError):
    def __init__(self, code: str, category: str = "INVALID_INPUT"):
        self.code = code
        self.category = category
        super().__init__(code)


@dataclass(frozen=True)
class Candidate:
    source_sha: str
    min_schema: int
    max_schema: int
    images: tuple[tuple[str, str], ...]
    manifest_sha256: str


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PlanError("MANIFEST_DUPLICATE_KEY")
        result[key] = value
    return result


def parse_manifest(raw: bytes) -> Candidate:
    if not raw or len(raw) > MAX_MANIFEST_BYTES:
        raise PlanError("MANIFEST_SIZE_INVALID")
    try:
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_pairs)
    except PlanError:
        raise
    except (UnicodeError, ValueError):
        raise PlanError("MANIFEST_JSON_INVALID") from None
    if not isinstance(data, dict) or set(data) != {
        "manifest_version", "source_sha", "schema_compatibility", "images"
    } or type(data["manifest_version"]) is not int or data["manifest_version"] != 1:
        raise PlanError("MANIFEST_STRUCTURE_INVALID")
    sha = data["source_sha"]
    if not isinstance(sha, str) or SHA.fullmatch(sha) is None:
        raise PlanError("MANIFEST_SOURCE_SHA_INVALID")
    schema = data["schema_compatibility"]
    if not isinstance(schema, dict) or set(schema) != {"min_version", "max_version"}:
        raise PlanError("MANIFEST_SCHEMA_INVALID")
    lower, upper = schema["min_version"], schema["max_version"]
    if (type(lower) is not int or type(upper) is not int
            or lower < 1 or upper < lower or upper > 100000):
        raise PlanError("MANIFEST_SCHEMA_INVALID")
    images = data["images"]
    if (not isinstance(images, dict) or not {"backend", "web"} <= set(images)
            or not set(images) <= ROLES):
        raise PlanError("MANIFEST_IMAGES_INVALID")
    for role, locator in images.items():
        if not isinstance(locator, str) or locator.count("@") != 1:
            raise PlanError("MANIFEST_IMAGE_NOT_PINNED")
        repository, digest = locator.split("@", 1)
        if (len(repository) > 200 or IMAGE_REPOSITORY.fullmatch(repository) is None
                or DIGEST.fullmatch(digest) is None):
            raise PlanError("MANIFEST_IMAGE_NOT_PINNED")
    return Candidate(
        source_sha=sha, min_schema=lower, max_schema=upper,
        images=tuple(sorted(images.items())),
        manifest_sha256=hashlib.sha256(raw).hexdigest(),
    )


def read_manifest(path: str) -> Candidate:
    candidate = Path(path).expanduser()
    try:
        if candidate.is_symlink() or not candidate.is_file():
            raise PlanError("MANIFEST_NOT_A_REGULAR_FILE")
        if candidate.stat().st_size > MAX_MANIFEST_BYTES:
            raise PlanError("MANIFEST_SIZE_INVALID")
        raw = candidate.read_bytes()
    except (OSError, ValueError):
        raise PlanError("MANIFEST_UNREADABLE") from None
    return parse_manifest(raw)


def _target_report(target: TargetInfo) -> dict[str, Any]:
    return {
        "context": target.context,
        "installation": target.installation,
        "engine_fingerprint_sha256": target.engine_fingerprint,
        "docker_server_version": target.server_version,
        "compose_version": target.compose_version,
        "existing_installation_detected": target.has_installation,
        "resource_counts": {
            "containers": target.owned_containers,
            "volumes": target.owned_volumes,
            "networks": target.owned_networks,
        },
    }


def make_plan(
    candidate: Candidate,
    target: TargetInfo,
    *,
    intent: str,
) -> dict[str, Any]:
    if intent not in {"install", "update"}:
        raise PlanError("UNSUPPORTED_INTENT")
    if intent == "install" and target.has_installation:
        raise PlanError("INSTALLATION_ALREADY_EXISTS", "OWNERSHIP_CONFLICT")
    if intent == "update":
        # A healthy Docker stack alone cannot prove its installed manifest,
        # its SQLite version, or the quiescence/backup required for an update.
        raise PlanError("UPDATE_RECEIPT_AND_SCHEMA_PROOF_REQUIRED", "INCOMPATIBLE_RELEASE")
    return {
        "status": "READY",
        "intent": "install",
        "apply_authorized": False,
        "mutation_performed": False,
        "read_only_plan": True,
        "target": _target_report(target),
        "candidate": {
            "source_sha": candidate.source_sha,
            "manifest_sha256": candidate.manifest_sha256,
            "schema_compatibility": {
                "min_version": candidate.min_schema,
                "max_version": candidate.max_schema,
            },
            "immutable_images": [
                {"role": role, "locator": locator} for role, locator in candidate.images
            ],
        },
        "proposed_changes": [
            "Create a single explicitly owned Compose installation",
            "Create isolated persistent SQLite and media volumes",
            "Publish only an explicitly approved loopback web listener",
        ],
        "remaining_gates": [
            "Verify trusted release manifest and image provenance",
            "Verify target resource names, mount paths, ports and free disk space",
            "Perform isolated backup/restore and fault-injection acceptance",
            "Require explicit separately authorized install/apply",
        ],
    }


def _safe_error(kind: str, code: str, action: str) -> dict[str, Any]:
    return {
        "status": "BLOCKED",
        "action": action,
        "category": kind,
        "reason": code,
        "apply_authorized": False,
        "mutation_performed": False,
    }


def evaluate(
    action: str,
    context: str,
    installation: str,
    manifest_path: str | None = None,
    *,
    probe: Callable[..., TargetInfo] = probe_target,
) -> tuple[int, dict[str, Any]]:
    try:
        if action == "plan" and not manifest_path:
            raise PlanError("MANIFEST_REQUIRED")
        if action == "doctor" and manifest_path is not None:
            raise PlanError("DOCTOR_DOES_NOT_READ_MANIFEST")
        candidate = read_manifest(manifest_path) if manifest_path else None
        target = probe(context, installation)
        if action == "doctor":
            return EXIT_CODES["READY"], {
                "status": "OBSERVED",
                "action": "doctor",
                "apply_authorized": False,
                "mutation_performed": False,
                "target": _target_report(target),
            }
        assert candidate is not None
        return EXIT_CODES["READY"], make_plan(candidate, target, intent="install")
    except PlanError as error:
        return EXIT_CODES[error.category], _safe_error(error.category, error.code, action)
    except ProbeError as error:
        if error.code.startswith("INVALID_") or error.code == "FORBIDDEN_DOCKER_COMMAND":
            kind = "INVALID_INPUT"
        elif error.code == "OWNERSHIP_CONFLICT":
            kind = "OWNERSHIP_CONFLICT"
        elif error.code == "TARGET_OSTYPE_UNSUPPORTED":
            kind = "INCOMPATIBLE_RELEASE"
        else:
            kind = "TARGET_UNAVAILABLE"
        return EXIT_CODES[kind], _safe_error(kind, error.code, action)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="docker-delivery", description=__doc__)
    parser.add_argument("action", choices=("plan", "doctor"))
    parser.add_argument("--context", required=True)
    parser.add_argument("--installation", required=True)
    parser.add_argument("--manifest")
    arguments = parser.parse_args(argv)
    status, result = evaluate(
        arguments.action, arguments.context, arguments.installation, arguments.manifest
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return status


if __name__ == "__main__":
    sys.exit(main())
