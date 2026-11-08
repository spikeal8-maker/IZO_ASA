"""Offline strict OpenRouter delta over the existing verified historical beta."""
from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

try:
    from tools import docker_history_beta_profile as history
    from tools import prepare_openrouter_egress as preparation
    from tools.docker_test_bundle_format import BundleError, SHA, file_hash, json_bytes, load_json, require
except ModuleNotFoundError:
    import docker_history_beta_profile as history
    import prepare_openrouter_egress as preparation
    from docker_test_bundle_format import BundleError, SHA, file_hash, json_bytes, load_json, require

bridge = history.bridge
PROJECT = history.PROJECT
SCOPE = "izo-asa-linux-test-a-openrouter-v1"
SECRET_VOLUME, SECRET_PATH = PROJECT + "-secrets-v1", "/home/izo/secrets"
PROFILE = preparation.PROFILE
TRANSPORT = "closed-proxy-v1"
ASSETS = {"docker_openrouter_profile.py", "prepare_openrouter_egress.py",
          "docker_history_beta_profile.py", "profiles/compose.openrouter-shadow.yml"}
DEPENDENCY = {"condition": "service_healthy", "required": True, "restart": True}
PROXY_HEALTH = ["CMD", "python", "-c", "import json,urllib.request; r=json.load(urllib.request.urlopen('http://127.0.0.1:18189/healthz',timeout=2)); assert r['ok'] and r['profile']=='closed-proxy-v1'"]
BACKEND_ENV = {"IZO_OPENROUTER_TRANSPORT": TRANSPORT,
               "OPENROUTER_BASE_URL": "http://127.0.0.1:18189/api/v1", "IZO_SECRET_DIR": SECRET_PATH}
SECRET_MOUNT = {"type": "volume", "source": "secrets-data", "target": SECRET_PATH,
                "volume": {"nocopy": True}}


def guard_history(document, source_sha):
    """Defend the delta boundary; callers obtain the base from history.render."""
    require(type(document) is dict and set(document) == {"name", "services", "volumes", "networks"}
            and document["name"] == PROJECT and type(source_sha) is str and SHA.fullmatch(source_sha),
            "OPENROUTER_HISTORY_BASE_INVALID")
    services = document["services"]
    require(type(services) is dict and set(services) == {"backend", "web", "guard", "comfy-proxy"},
            "OPENROUTER_HISTORY_SERVICES_INVALID")
    require(document["volumes"] == {
        "sqlite-data": {"external": True, "name": history.DATABASE_VOLUME},
        "media-data": {"external": True, "name": history.MEDIA_VOLUME}},
        "OPENROUTER_HISTORY_VOLUMES_INVALID")
    for role, service in services.items():
        require(type(service) is dict and not (set(service) - bridge.SERVICE_KEYS)
                and service.get("labels", {}).get("org.opencontainers.image.revision") == source_sha
                and service.get("cap_drop") == ["ALL"]
                and service.get("security_opt") == ["no-new-privileges:true"]
                and service.get("restart") in {"no", "unless-stopped"}, "OPENROUTER_HISTORY_POLICY_INVALID")
        tmpfs = service.get("tmpfs") or []
        if isinstance(tmpfs, str):
            tmpfs = [tmpfs]
        require(isinstance(tmpfs, list) and all(isinstance(target, str)
                and target.split(":", 1)[0] != SECRET_PATH for target in tmpfs),
                "OPENROUTER_EXISTING_SECRET_MOUNT_INVALID")
        if role != "guard":
            require(service.get("network_mode") == "service:guard"
                    and not any(service.get(k) for k in ("ports", "networks", "cap_add", "dns", "sysctls")),
                    "OPENROUTER_HISTORY_POLICY_INVALID")
    guard, backend, comfy = (services[k] for k in ("guard", "backend", "comfy-proxy"))
    require(guard.get("environment") == {"IZO_SHADOW_EGRESS_PROFILE": "comfyui-private-v1",
        "IZO_COMFY_UPSTREAM_IP": history.UPSTREAM_IP, "IZO_COMFY_UPSTREAM_PORT": str(history.UPSTREAM_PORT)}
        and guard.get("read_only") is True and not guard.get("volumes"), "OPENROUTER_HISTORY_GUARD_INVALID")
    require(comfy.get("environment") == {**guard["environment"], "IZO_COMFY_NAMESPACE": history.NAMESPACE,
        "IZO_COMFY_MODE": comfy.get("environment", {}).get("IZO_COMFY_MODE")}
        and comfy["environment"]["IZO_COMFY_MODE"] in {"capabilities", "generate-t2i-4b"}
        and comfy.get("user") == "10002:10002" and comfy.get("image") == guard["image"]
        and comfy.get("command") == ["python", "/comfyui_proxy.py"]
        and comfy.get("read_only") is True and not comfy.get("volumes"), "OPENROUTER_HISTORY_COMFY_INVALID")
    env = backend.get("environment", {})
    require(backend.get("user") == "10001:10001" and all(env.get(k) == v for k, v in history.HISTORY_ENV.items())
        and all(env.get(k) == v for k, v in {"COMFYUI_BASE_URL": "http://127.0.0.1:18188",
            "COMFYUI_REQUIRED": "true", "COMFYUI_MOCK_FALLBACK": "false", "COMFYUI_NATIVE4B_ONLY": "true"}.items())
        and env.get("OPENROUTER_BASE_URL") in {None, "http://127.0.0.1:1"}
        and "IZO_OPENROUTER_TRANSPORT" not in env
        and ("IZO_SECRET_DIR" not in env or env["IZO_SECRET_DIR"] == SECRET_PATH),
        "OPENROUTER_HISTORY_BACKEND_INVALID")
    require(all(m.get("target") != SECRET_PATH and m.get("source") != "secrets-data"
                for service in services.values() for m in service.get("volumes", [])),
            "OPENROUTER_EXISTING_SECRET_MOUNT_INVALID")


def overlay(document, addresses, source_sha):
    guard = document["services"]["guard"]
    targets = ",".join(addresses)
    proxy = {"image": guard["image"], "pull_policy": "never", "command": ["python", "/openrouter_https_proxy.py"],
        "user": "10003:10003", "network_mode": "service:guard", "restart": guard["restart"],
        "read_only": True, "cpus": 0.5, "mem_limit": "268435456", "pids_limit": 32,
        "cap_drop": ["ALL"], "security_opt": ["no-new-privileges:true"],
        "depends_on": {"guard": copy.deepcopy(DEPENDENCY)},
        "environment": {"IZO_OPENROUTER_PROFILE": TRANSPORT, "IZO_OPENROUTER_IPV4S": targets},
        "labels": {"io.izo.owner": "LINUX-OPENROUTER-OPERABILITY-001", "io.izo.project": PROJECT,
                   "org.opencontainers.image.revision": source_sha},
        "healthcheck": {"test": list(PROXY_HEALTH), "interval": "10s", "timeout": "3s", "retries": 12},
        "stop_grace_period": "5s"}
    return {"services": {
        "guard": {"environment": {"IZO_SHADOW_EGRESS_PROFILE": PROFILE, "IZO_OPENROUTER_IPV4S": targets}},
        "backend": {"environment": dict(BACKEND_ENV), "depends_on": {"openrouter-proxy": copy.deepcopy(DEPENDENCY)},
                    "volumes": [copy.deepcopy(SECRET_MOUNT)]},
        "openrouter-proxy": proxy},
        "volumes": {"secrets-data": {"external": True, "name": SECRET_VOLUME}}}


def apply_to_history(history_document, preparation_receipt, *, source_sha,
                     expected_prepare_helper_sha256, now_utc, template=None):
    """Pure delta: no Docker/DNS/key I/O and no modification of the input objects."""
    guard_history(history_document, source_sha)
    addresses = preparation.validate_receipt(preparation_receipt, source_sha=source_sha,
        expected_helper_sha256=expected_prepare_helper_sha256, now_utc=now_utc)
    release = history_document["services"]["backend"]["environment"].get("IZO_RELEASE_MANIFEST", "")
    require(release == "/opt/izo/.runtime/releases/frontend/" + preparation_receipt["release_id"]
            + "/release-manifest.json", "OPENROUTER_RECEIPT_RELEASE_MISMATCH")
    delta = overlay(history_document, addresses, source_sha)
    if template is not None:
        values = {"IZO_OPENROUTER_IPV4S": ",".join(addresses),
                  "IZO_OPENROUTER_GUARD_IMAGE": history_document["services"]["guard"]["image"],
                  "IZO_OPENROUTER_RESTART": history_document["services"]["guard"]["restart"],
                  "IZO_SOURCE_SHA": source_sha, "IZO_COMPOSE_PROJECT": PROJECT,
                  "IZO_SECRET_VOLUME": SECRET_VOLUME}
        require(bridge.substitutions(template, values) == delta, "OPENROUTER_PROFILE_DELTA_INVALID")
    config = copy.deepcopy(history_document)
    for role in ("guard", "backend"):
        for field, value in delta["services"][role].items():
            if field == "volumes":
                config["services"][role][field].extend(value)
            else:
                config["services"][role].setdefault(field, {}).update(value)
    config["services"]["openrouter-proxy"] = delta["services"]["openrouter-proxy"]
    config["volumes"].update(delta["volumes"])
    return config


def verify_effective(expected, observed, *, compose_version):
    """Reuse the existing precise Compose normalizer without extending its policy."""
    require(type(expected) is dict and type(observed) is dict, "OPENROUTER_EFFECTIVE_COMPOSE_DRIFT")
    cores = [copy.deepcopy(expected), copy.deepcopy(observed)]
    expected_roles = {"backend", "web", "guard", "comfy-proxy", "openrouter-proxy"}
    for value in cores:
        require(type(value.get("services")) is dict and set(value["services"]) == expected_roles,
                "OPENROUTER_EFFECTIVE_COMPOSE_DRIFT")
    wanted, actual = (value["services"].pop("openrouter-proxy") for value in cores)
    require(type(wanted) is dict and type(actual) is dict, "OPENROUTER_EFFECTIVE_COMPOSE_DRIFT")
    if "entrypoint" not in wanted and "entrypoint" in actual and actual["entrypoint"] is None:
        del actual["entrypoint"]
    require(json_bytes(wanted) == json_bytes(actual), "OPENROUTER_EFFECTIVE_COMPOSE_DRIFT")
    bridge.verify_effective(*cores, compose_version=compose_version)


def load_candidate(args, *, now_utc=None):
    require(args.accept_openrouter_egress, "OPENROUTER_EXPLICIT_ACCEPTANCE_REQUIRED")
    config, manifest = history.load_candidate(args)
    require(ASSETS <= set(manifest["files"]), "OPENROUTER_PROFILE_ASSETS_MISSING")
    for module, name, pin in ((history, "docker_history_beta_profile.py", args.helper_sha256),
        (preparation, "prepare_openrouter_egress.py", args.prepare_helper_sha256)):
        size, digest = file_hash(Path(module.__file__))
        require(digest == pin and manifest["files"][name] == {"size": size, "sha256": digest},
                "OPENROUTER_DEPENDENCY_PIN_MISMATCH")
    size, digest = file_hash(Path(__file__))
    require(digest == args.openrouter_helper_sha256
            and manifest["files"]["docker_openrouter_profile.py"] == {"size": size, "sha256": digest},
            "OPENROUTER_HELPER_PIN_MISMATCH")
    receipt = bridge.pinned(args.preparation, args.preparation_sha256)
    now = now_utc if now_utc is not None else datetime.now(timezone.utc)
    preparation.validate_receipt(receipt, source_sha=manifest["source_sha"],
        expected_helper_sha256=args.prepare_helper_sha256, now_utc=now,
        manifest_sha256=args.manifest_sha256, release_id=manifest["release_id"])
    config = apply_to_history(config, receipt, source_sha=manifest["source_sha"],
        expected_prepare_helper_sha256=args.prepare_helper_sha256, now_utc=now,
        template=load_json(args.bundle / "profiles/compose.openrouter-shadow.yml"))
    return config, manifest, receipt


def parser():
    result = history.parser()
    result.description = __doc__
    result.add_argument("--accept-openrouter-egress", action="store_true")
    result.add_argument("--preparation", type=Path, required=True)
    for name in ("openrouter-helper-sha256", "prepare-helper-sha256", "preparation-sha256"):
        result.add_argument("--" + name, required=True)
    return result


def main(argv=None):
    try:
        args = parser().parse_args(argv)
        require(args.check_compose is not None or (args.check_sha256 is None and args.compose_version is None),
                "OPENROUTER_EFFECTIVE_CHECK_REQUIRED")
        config, manifest, receipt = load_candidate(args)
        if args.check_compose is not None:
            verify_effective(config, bridge.pinned(args.check_compose, args.check_sha256),
                             compose_version=args.compose_version)
            print(json.dumps({"status": "OPENROUTER_BETA_COMPOSE_VERIFIED", "scope": SCOPE,
                "source_sha": manifest["source_sha"], "release_id": manifest["release_id"],
                "compose_sha256": hashlib.sha256(json_bytes(config)).hexdigest(),
                "effective_compose_sha256": args.check_sha256, "preparation_sha256": args.preparation_sha256,
                "compose_version": args.compose_version, "ipv4_count": len(receipt["ipv4s"]),
                "secret_volume": SECRET_VOLUME, "runtime_verified": False,
                "secret_volume_initialization_required": True, "production_authorized": False}, sort_keys=True))
        else:
            print(json_bytes(config).decode(), end="")
        return 0
    except (BundleError, OSError, ValueError, TypeError, KeyError) as error:
        reason = str(error) if isinstance(error, BundleError) else "OPENROUTER_PROFILE_FAILED"
        print(json.dumps({"status": "BLOCKED", "reason": reason, "production_authorized": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
