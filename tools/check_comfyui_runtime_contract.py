"""Verify the vendored Config UI workflow contract and an optional ComfyUI install."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_ROOT = REPO_ROOT / "ops" / "comfyui" / "runtime-contract"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_file(path: Path, expected: dict[str, object]) -> list[str]:
    errors: list[str] = []
    if not path.is_file():
        return [f"MISSING {path}"]
    expected_bytes = int(expected["bytes"])
    if path.stat().st_size != expected_bytes:
        errors.append(f"SIZE {path}: {path.stat().st_size} != {expected_bytes}")
    actual_hash = sha256(path)
    if actual_hash != expected["sha256"]:
        errors.append(f"SHA256 {path}: {actual_hash} != {expected['sha256']}")
    return errors


def load_manifest() -> dict[str, object]:
    return json.loads((CONTRACT_ROOT / "manifest.json").read_text(encoding="utf-8"))


def verify_assets(manifest: dict[str, object]) -> list[str]:
    errors: list[str] = []
    for item in manifest["assets"]:
        errors.extend(verify_file(CONTRACT_ROOT / item["path"], item))
    return errors


def verify_runtime(manifest: dict[str, object], comfyui_root: Path) -> list[str]:
    errors: list[str] = []
    node_root = comfyui_root / "custom_nodes" / manifest["customNode"]["name"]
    for item in manifest["assets"]:
        errors.extend(verify_file(node_root / item["path"].split("/", 1)[1], item))
    for item in manifest["models"]:
        path = comfyui_root / item["path"]
        if item.get("required") or path.exists():
            errors.extend(verify_file(path, item))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--comfyui-root",
        type=Path,
        help="Path containing ComfyUI/main.py, custom_nodes and models.",
    )
    args = parser.parse_args()
    manifest = load_manifest()
    errors = verify_assets(manifest)
    if args.comfyui_root:
        errors.extend(verify_runtime(manifest, args.comfyui_root.resolve()))
    if errors:
        print("\n".join(errors))
        return 1
    scope = "assets+runtime" if args.comfyui_root else "assets"
    print(f"COMFYUI_RUNTIME_CONTRACT_OK scope={scope}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
