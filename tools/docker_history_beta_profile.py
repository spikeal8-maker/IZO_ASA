"""Offline, pinned history binding for one existing native 1Panel beta project."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

try:
    from tools import docker_comfy_bridge_profile as bridge
    from tools.docker_test_bundle_format import (
        BundleError, file_hash, inventory, json_bytes, load_json, plain_path, require, verify,
    )
except ModuleNotFoundError:
    import docker_comfy_bridge_profile as bridge
    from docker_test_bundle_format import (
        BundleError, file_hash, inventory, json_bytes, load_json, plain_path, require, verify,
    )

PROJECT = "izo-asa-linux-test-a"
SCOPE = "izo-asa-linux-test-a-history-20261108-v1"
SNAPSHOT = "20261104T190706.420010Z"
SCHEMA = 8
DATABASE_VOLUME = PROJECT + "_history-20261108-sqlite"
MEDIA_VOLUME = PROJECT + "_history-20261108-media"
UPSTREAM_IP, UPSTREAM_PORT = "192.168.1.112", 8188
NAMESPACE = "izo-linux-test-a-20261106-bridge01"
HISTORY_ENV = {
    "IZO_PREPROD_PRESERVE_HISTORY": "1",
    "IZO_HISTORY_SNAPSHOT_ID": SNAPSHOT,
    "IZO_CLOSED_BETA": "1",
}


def validate_binding(*, scope, snapshot_id, schema, database_volume, media_volume):
    require(scope == SCOPE, "HISTORY_SCOPE_INVALID")
    require(snapshot_id == SNAPSHOT, "HISTORY_SNAPSHOT_INVALID")
    require(type(schema) is int and schema == SCHEMA, "HISTORY_SCHEMA_INVALID")
    require(database_volume == DATABASE_VOLUME and media_volume == MEDIA_VOLUME,
            "HISTORY_VOLUMES_INVALID")


def render(base, manifest, template, frontend, *, scope, snapshot_id, schema,
           database_volume, media_volume, upstream_ip, upstream_port, namespace, mode, images=None):
    """Reuse all bridge guards, then apply only the declared historical delta."""
    validate_binding(scope=scope, snapshot_id=snapshot_id, schema=schema,
                     database_volume=database_volume, media_volume=media_volume)
    require(base.get("name") == PROJECT, "HISTORY_PROJECT_INVALID")
    require(type(manifest.get("schema")) is int and manifest["schema"] == SCHEMA,
            "HISTORY_RELEASE_SCHEMA_INVALID")
    require(upstream_ip == UPSTREAM_IP and type(upstream_port) is int and upstream_port == UPSTREAM_PORT
            and namespace == NAMESPACE, "HISTORY_GPU_ROUTE_INVALID")
    config = bridge.render(base, manifest, template, frontend, upstream_ip=upstream_ip,
                           upstream_port=upstream_port, namespace=namespace, mode=mode, images=images)
    require("init-db" in config["services"], "HISTORY_EMPTY_INITIALIZER_REQUIRED")
    # bridge.native_base already verified this exact empty-only initializer.
    del config["services"]["init-db"]
    for service in config["services"].values():
        dependencies = service.get("depends_on", {})
        require(type(dependencies) is dict, "HISTORY_DEPENDENCY_INVALID")
        if "init-db" in dependencies:
            require(dependencies["init-db"] == {
                "condition": "service_completed_successfully", "required": True, "restart": True,
            }, "HISTORY_INITIALIZER_DEPENDENCY_INVALID")
            del dependencies["init-db"]
            if not dependencies:
                del service["depends_on"]
    require(set(config["volumes"]) == {"sqlite-data", "media-data"}, "HISTORY_VOLUME_SHAPE_INVALID")
    for logical, volume in (("sqlite-data", database_volume), ("media-data", media_volume)):
        require(config["volumes"][logical]["name"] == PROJECT + "_" + logical,
                "HISTORY_BASE_VOLUME_INVALID")
        # External forbids Compose from silently creating an empty replacement.
        config["volumes"][logical] = {"external": True, "name": volume}
    config["services"]["backend"]["environment"].update(HISTORY_ENV)
    require(set(config["services"]) == {"backend", "web", "guard", "comfy-proxy"},
            "HISTORY_SERVICE_SHAPE_INVALID")
    return config


def load_candidate(args):
    require(args.accept_private_http and args.accept_history_bind, "HISTORY_EXPLICIT_ACCEPTANCE_REQUIRED")
    require(file_hash(Path(__file__))[1] == args.helper_sha256, "HISTORY_HELPER_PIN_MISMATCH")
    require((args.images is None) == (args.images_sha256 is None), "HISTORY_IMAGE_PIN_CONTEXT_REQUIRED")
    manifest = verify(args.bundle, args.manifest_sha256)
    require(manifest["source_sha"] == args.expect_source and manifest["release_id"] == args.expect_release
            and bridge.ASSETS <= set(manifest["files"]), "BRIDGE_RELEASE_IDENTITY_MISMATCH")
    size, digest = file_hash(Path(bridge.__file__))
    require(manifest["files"]["docker_comfy_bridge_profile.py"] == {"size": size, "sha256": digest},
            "BRIDGE_HELPER_IDENTITY_MISMATCH")
    base = bridge.pinned(args.base_compose, args.base_sha256)
    require(base.get("name") == PROJECT, "HISTORY_PROJECT_INVALID")
    base_info = bridge.native_base(base)
    if base_info["nginx"]:
        require(file_hash(plain_path(Path(base_info["nginx"])))[1] == args.nginx_sha256,
                "BRIDGE_NGINX_PIN_MISMATCH")
    assets = inventory(plain_path(args.frontend))
    expected = {k.removeprefix("frontend/"): v for k, v in manifest["files"].items()
                if k.startswith("frontend/")}
    require(assets == expected, "BRIDGE_FRONTEND_BYTES_MISMATCH")
    bridge.verify_frontend_directory(args.frontend, manifest["release_id"])
    metadata = load_json(args.frontend / "release-manifest.json")
    require(metadata.get("git_sha") == manifest["source_sha"] and metadata.get("release_id") == manifest["release_id"]
            and metadata.get("dirty") is False, "BRIDGE_FRONTEND_RELEASE_MISMATCH")
    require(metadata.get("schema_compatibility") == {"min_version": SCHEMA, "max_version": SCHEMA},
            "HISTORY_FRONTEND_SCHEMA_INVALID")
    template = load_json(args.bundle / "profiles/compose.comfyui-shadow.yml")
    config = render(base, manifest, template, args.frontend, scope=args.scope,
        snapshot_id=args.snapshot_id, schema=args.schema_version,
        database_volume=args.database_volume, media_volume=args.media_volume,
        upstream_ip=args.upstream_ip, upstream_port=args.upstream_port, namespace=args.namespace,
        mode=args.mode, images=bridge.pinned(args.images, args.images_sha256) if args.images else None)
    return config, manifest


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    for name in ("bundle", "base-compose", "frontend"):
        result.add_argument("--" + name, type=Path, required=True)
    for name in ("manifest-sha256", "base-sha256", "expect-source", "expect-release", "upstream-ip", "namespace",
                 "helper-sha256", "scope", "snapshot-id", "database-volume", "media-volume"):
        result.add_argument("--" + name, required=True)
    result.add_argument("--schema-version", type=int, required=True)
    result.add_argument("--upstream-port", type=int, required=True)
    result.add_argument("--mode", choices=("capabilities", "generate-t2i-4b"), required=True)
    result.add_argument("--accept-private-http", action="store_true")
    result.add_argument("--accept-history-bind", action="store_true")
    result.add_argument("--nginx-sha256")
    result.add_argument("--images", type=Path)
    result.add_argument("--images-sha256")
    result.add_argument("--check-compose", type=Path)
    result.add_argument("--check-sha256")
    result.add_argument("--compose-version")
    return result


def main(argv=None):
    try:
        args = parser().parse_args(argv)
        require(args.check_compose is not None or (args.check_sha256 is None and args.compose_version is None),
                "HISTORY_EFFECTIVE_CHECK_REQUIRED")
        if args.check_compose is not None:
            require(args.compose_version == bridge.COMPOSE_VERSION, "BRIDGE_COMPOSE_VERSION_UNSUPPORTED")
        config, manifest = load_candidate(args)
        if args.check_compose is not None:
            observed = bridge.pinned(args.check_compose, args.check_sha256)
            bridge.verify_effective(config, observed, compose_version=args.compose_version)
            print(json.dumps({"status": "HISTORY_BETA_COMPOSE_VERIFIED", "scope": SCOPE,
                "source_sha": manifest["source_sha"], "release_id": manifest["release_id"],
                "schema_version": SCHEMA, "snapshot_id": SNAPSHOT,
                "database_volume": DATABASE_VOLUME, "media_volume": MEDIA_VOLUME,
                "compose_sha256": hashlib.sha256(json_bytes(config)).hexdigest(),
                "effective_compose_sha256": args.check_sha256, "compose_version": args.compose_version,
                "comparison_profile": bridge.COMPARISON_PROFILE,
                "runtime_verified": False, "clone_and_seal_proof_required": True,
                "production_authorized": False}, sort_keys=True))
        else:
            print(json_bytes(config).decode(), end="")
        return 0
    except (BundleError, OSError, ValueError, TypeError, KeyError) as error:
        reason = str(error) if isinstance(error, BundleError) else "HISTORY_PROFILE_FAILED"
        print(json.dumps({"status": "BLOCKED", "reason": reason, "production_authorized": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
