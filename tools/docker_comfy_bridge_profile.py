"""Read-only, pinned Compose renderer for explicit 1Panel ComfyUI activation."""
from __future__ import annotations

import argparse
import copy
import hashlib
import ipaddress
import json
import re
from pathlib import Path

try:
    from tools.docker_test_bundle_format import (BundleError, HASH, IMAGE, RUNTIME, SHA,
        UVICORN, file_hash, inventory, json_bytes, load_json, plain_path, require, validate_compose, verify)
    from tools.docker_test_bundle_images import identity
    from tools.docker_bundle_release_identity import verify_frontend_directory
except ModuleNotFoundError:
    from docker_test_bundle_format import (BundleError, HASH, IMAGE, RUNTIME, SHA,
        UVICORN, file_hash, inventory, json_bytes, load_json, plain_path, require, validate_compose, verify)
    from docker_test_bundle_images import identity
    from docker_bundle_release_identity import verify_frontend_directory

ASSETS = {"profiles/compose.comfyui-shadow.yml", "docker_comfy_bridge_profile.py",
          "profiles/LINUX-COMFY-BRIDGE-001.md"}
SERVICE_KEYS = {"image", "pull_policy", "labels", "cap_drop", "cap_add", "security_opt", "user",
    "command", "environment", "network_mode", "networks", "ports", "dns", "dns_opt", "sysctls",
    "restart", "read_only", "tmpfs", "cpus", "mem_limit", "pids_limit", "depends_on", "healthcheck",
    "stop_grace_period", "volumes"}
RELEASE = re.compile(r"[0-9a-f]{12}-[0-9]{14}")
COMPOSE_VERSION = "2.40.3+ds1-0ubuntu1~24.04.1"
COMPARISON_PROFILE = "compose-2.40.3-ubuntu24.04-json-v1"
PROXY_HEALTH = ["CMD", "python", "-c", "import json,urllib.request; r=json.load(urllib.request.urlopen('http://127.0.0.1:18188/healthz',timeout=2)); assert r['ok'] and r['profile']=='comfyui-private-v1'"]


def pinned(path, expected):
    path = plain_path(path)
    require(HASH.fullmatch(expected or "") and file_hash(path)[1] == expected, "BRIDGE_FILE_PIN_MISMATCH")
    return load_json(path)


def native_base(config):
    """Validate accepted native differences, then reuse unchanged format-2 gates."""
    c = copy.deepcopy(config)
    require(set(c) == {"name", "services", "volumes", "networks"}
            and re.fullmatch(r"izo-asa-[a-z0-9][a-z0-9-]{2,48}", c["name"] or ""), "BRIDGE_BASE_SHAPE")
    services = c["services"]
    require(set(services) in ({"backend", "web", "guard"}, {"backend", "web", "guard", "init-db"}),
            "BRIDGE_BASE_SERVICES")
    backend, guard, web = (services[k] for k in ("backend", "guard", "web"))
    sha = backend.get("labels", {}).get("org.opencontainers.image.revision", "")
    require(SHA.fullmatch(sha), "BRIDGE_BASE_SOURCE")
    release_path = backend.get("environment", {}).get("IZO_RELEASE_MANIFEST", "")
    release = release_path.removeprefix("/opt/izo/.runtime/releases/frontend/").removesuffix("/release-manifest.json")
    require(RELEASE.fullmatch(release) and release.startswith(sha[:12] + "-"), "BRIDGE_BASE_RELEASE")
    frontend, nginx = None, None
    for role, service in services.items():
        require(set(service) <= SERVICE_KEYS and service.get("restart") in {"no", "unless-stopped"}
                and service.get("security_opt") == ["no-new-privileges:true"]
                and service.get("cap_drop") == ["ALL"] and IMAGE.fullmatch(service.get("image", ""))
                and service.get("labels", {}).get("org.opencontainers.image.revision") == sha,
                "BRIDGE_BASE_SERVICE_POLICY")
        service["restart"] = "no"
        if role == "guard":
            require(service.get("user") == "0:0" and service.get("read_only") is True
                    and service.get("sysctls") == {"net.ipv6.conf.all.disable_ipv6": "1"}
                    and not service.get("environment") and service.get("tmpfs") == ["/tmp"]
                    and service.get("healthcheck", {}).get("test") == ["CMD", "python", "/network_guard.py", "--check"],
                    "BRIDGE_BASE_GUARD_POLICY")
        else:
            require(service.get("user") == ("101:101" if role == "web" else "10001:10001")
                    and service.get("network_mode") == "service:guard"
                    and not service.get("cap_add") and not service.get("ports") and not service.get("networks")
                    and not service.get("dns") and not service.get("sysctls"), "BRIDGE_BASE_APP_POLICY")
        if role == "web":
            require(service.get("read_only") is True and not service.get("environment"), "BRIDGE_BASE_WEB_POLICY")
        for mount in service.get("volumes", []):
            if mount.get("type") != "bind":
                continue
            require(mount.get("read_only") is True and mount.get("bind") == {"create_host_path": False},
                    "BRIDGE_BASE_BIND_POLICY")
            path = mount.get("source", "")
            if role == "web" and mount.get("target") == "/etc/nginx/nginx.conf":
                require(nginx is None and Path(path).is_absolute() and Path(path).name == "nginx.conf",
                        "BRIDGE_BASE_NGINX_BIND")
                nginx = path
            else:
                require(role in {"backend", "web", "init-db"}
                        and mount.get("target") == ("/usr/share/nginx/html" if role == "web" else
                            "/opt/izo/.runtime/releases/frontend/" + release)
                        and (path == "./frontend" or Path(path).is_absolute()), "BRIDGE_BASE_FRONTEND_BIND")
                require(frontend is None or frontend == path, "BRIDGE_BASE_FRONTEND_DIVERGED")
                frontend = path
                mount["source"] = "./frontend"
    if "init-db" in services:
        init = services.pop("init-db")
        require(init.get("image") == backend["image"] and init.get("environment") == backend["environment"]
                and init.get("volumes") == backend.get("volumes") and init.get("command", [])[:2] == ["python", "-c"]
                and len(init["command"]) == 3 and "empty-test-only" in init["command"][2]
                and init.get("labels", {}).get("io.izo.role") == "empty-test-schema-init",
                "BRIDGE_BASE_INIT_POLICY")
    if nginx:
        require(frontend and Path(nginx).parent == Path(frontend).parent, "BRIDGE_BASE_NGINX_BIND")
        web["volumes"] = [v for v in web["volumes"] if v.get("target") != "/etc/nginx/nginx.conf"]
    require(frontend is not None, "BRIDGE_BASE_FRONTEND_MISSING")
    for key, value in backend["environment"].items():
        if key.lower() in {"http_proxy", "https_proxy", "all_proxy"}:
            require(value == "", "BRIDGE_BASE_PROXY_FORBIDDEN")
    ports = {p["target"]: int(p["published"]) for p in guard.get("ports", [])}
    m = {"format": 2, "profile": RUNTIME, "project": c["name"], "source_sha": sha,
         "release_id": release, "ports": {"web": ports.get(8080), "api": ports.get(8000)},
         "images": {k: v["image"] for k, v in services.items()}}
    validate_compose(c, m)
    return {"release": release, "frontend": frontend, "nginx": nginx}


def selected_images(manifest, images=None):
    roles = identity(manifest)
    require(roles is not None, "BRIDGE_PORTABLE_IMAGES_REQUIRED")
    selected = images or manifest["images"]
    require(set(selected) == {"backend", "web", "guard"} and all(
        selected[k] in {v["config_digest"], v["manifest_digest"]} for k, v in roles.items()),
        "BRIDGE_IMAGE_IDENTITY_MISMATCH")
    return selected


def substitutions(template, values):
    if isinstance(template, dict):
        return {k: substitutions(v, values) for k, v in template.items()}
    if isinstance(template, list):
        return [substitutions(v, values) for v in template]
    if isinstance(template, str) and template.startswith("${"):
        match = re.fullmatch(r"\$\{([A-Z0-9_]+):\?[^}]+\}", template)
        require(match and match[1] in values, "BRIDGE_PROFILE_SUBSTITUTION_INVALID")
        return values[match[1]]
    return template


def render(base, manifest, template, frontend, *, upstream_ip, upstream_port, namespace, mode, images=None):
    old = native_base(base)
    require(manifest.get("profile") == RUNTIME and manifest.get("source_sha") == manifest.get("tooling_sha"),
            "BRIDGE_EXACT_SOURCE_AND_TOOLING_REQUIRED")
    images = selected_images(manifest, images)
    try:
        address = ipaddress.IPv4Address(upstream_ip)
    except ValueError:
        raise BundleError("BRIDGE_UPSTREAM_INVALID") from None
    require(any(address in ipaddress.IPv4Network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))
            and type(upstream_port) is int and 1 <= upstream_port <= 65535, "BRIDGE_UPSTREAM_INVALID")
    require(re.fullmatch(r"izo-[a-z0-9][a-z0-9-]{15,59}", namespace or "")
            and mode in {"capabilities", "generate-t2i-4b"}, "BRIDGE_ACTIVATION_INVALID")
    frontend = str(frontend)
    require(Path(frontend).is_absolute() and Path(frontend).name == "frontend-" + manifest["release_id"],
            "BRIDGE_FRONTEND_PATH_INVALID")
    if old["frontend"] != "./frontend":
        require(Path(frontend).parent == Path(old["frontend"]).parent, "BRIDGE_FRONTEND_PATH_INVALID")
    config = copy.deepcopy(base)
    for role, service in config["services"].items():
        service["image"] = images["backend" if role == "init-db" else role]
        service["labels"]["org.opencontainers.image.revision"] = manifest["source_sha"]
        if role in {"backend", "init-db"}:
            service["environment"]["IZO_RELEASE_MANIFEST"] = (
                "/opt/izo/.runtime/releases/frontend/" + manifest["release_id"] + "/release-manifest.json")
        for mount in service.get("volumes", []):
            if mount.get("type") == "bind" and mount["source"] == old["frontend"]:
                mount["source"] = frontend
                if role != "web":
                    mount["target"] = "/opt/izo/.runtime/releases/frontend/" + manifest["release_id"]
    values = {"IZO_COMFY_UPSTREAM_IP": str(address), "IZO_COMFY_UPSTREAM_PORT": str(upstream_port),
        "IZO_COMFY_NAMESPACE": namespace, "IZO_COMFY_MODE": mode, "IZO_COMFY_GUARD_IMAGE": images["guard"],
        "IZO_COMFY_RESTART": base["services"]["guard"]["restart"], "IZO_SOURCE_SHA": manifest["source_sha"],
        "IZO_COMPOSE_PROJECT": base["name"]}
    overlay = substitutions(template, values)
    require(set(overlay) == {"services"} and set(overlay["services"]) == {"guard", "backend", "comfy-proxy"},
            "BRIDGE_PROFILE_SHAPE_INVALID")
    guard_env = {"IZO_SHADOW_EGRESS_PROFILE": "comfyui-private-v1",
                 "IZO_COMFY_UPSTREAM_IP": str(address), "IZO_COMFY_UPSTREAM_PORT": str(upstream_port)}
    dependency = {"condition": "service_healthy", "required": True, "restart": True}
    require(overlay["services"]["guard"] == {"environment": guard_env}
            and overlay["services"]["backend"] == {"environment": {
                "COMFYUI_BASE_URL": "http://127.0.0.1:18188", "COMFYUI_REQUIRED": "true",
                "COMFYUI_MOCK_FALLBACK": "false", "COMFYUI_NATIVE4B_ONLY": "true"},
                "depends_on": {"comfy-proxy": dependency}}, "BRIDGE_PROFILE_DELTA_INVALID")
    for role in ("guard", "backend"):
        delta = overlay["services"][role]
        require(set(delta) == ({"environment"} if role == "guard" else {"environment", "depends_on"}),
                "BRIDGE_PROFILE_DELTA_INVALID")
        for key, mapping in delta.items():
            config["services"][role].setdefault(key, {}).update(mapping)
    config["services"]["comfy-proxy"] = overlay["services"]["comfy-proxy"]
    proxy = config["services"]["comfy-proxy"]
    require(proxy.get("image") == images["guard"] and proxy.get("user") == "10002:10002"
            and proxy.get("command") == ["python", "/comfyui_proxy.py"]
            and proxy.get("network_mode") == "service:guard" and proxy.get("read_only") is True
            and proxy.get("cap_drop") == ["ALL"] and proxy.get("security_opt") == ["no-new-privileges:true"]
            and not (set(proxy) - SERVICE_KEYS) and not any(proxy.get(k) for k in
                ("volumes", "ports", "cap_add", "networks", "dns", "sysctls", "tmpfs")), "BRIDGE_PROXY_POLICY_INVALID")
    require(set(proxy) == {"image", "pull_policy", "command", "user", "network_mode", "restart",
                "read_only", "cpus", "mem_limit", "pids_limit", "cap_drop", "security_opt", "depends_on",
                "environment", "labels", "healthcheck", "stop_grace_period"}
            and proxy["environment"] == {**guard_env, "IZO_COMFY_NAMESPACE": namespace, "IZO_COMFY_MODE": mode}
            and proxy["pull_policy"] == "never" and proxy["restart"] == values["IZO_COMFY_RESTART"]
            and proxy["labels"] == {"io.izo.owner": "LINUX-COMFY-BRIDGE-001", "io.izo.project": base["name"],
                                    "org.opencontainers.image.revision": manifest["source_sha"]}
            and proxy["depends_on"] == {"guard": dependency}
            and proxy["healthcheck"] == {"test": PROXY_HEALTH, "interval": "10s", "timeout": "3s", "retries": 12}
            and proxy["cpus"] == 0.5 and proxy["mem_limit"] == "134217728"
            and proxy["pids_limit"] == 32 and proxy["stop_grace_period"] == "5s", "BRIDGE_PROXY_POLICY_INVALID")
    return config


def verify_effective(expected, observed, *, compose_version):
    require(type(compose_version) is str and compose_version == COMPOSE_VERSION, "BRIDGE_COMPOSE_VERSION_UNSUPPORTED")
    drift = "BRIDGE_EFFECTIVE_COMPOSE_DRIFT"
    require(type(expected) is dict and type(observed) is dict, drift)
    normalized = copy.deepcopy(observed)
    wanted_services, services = expected.get("services"), normalized.get("services")
    require(type(wanted_services) is dict and type(services) is dict
            and set(services) == set(wanted_services)
            and set(services) in ({"backend", "web", "guard", "comfy-proxy"},
                                 {"backend", "web", "guard", "init-db", "comfy-proxy"}), drift)
    for role, wanted in wanted_services.items():
        service = services[role]
        require(type(wanted) is dict and type(service) is dict, drift)
        for field in (("entrypoint", "command") if role in {"guard", "web"} else ("entrypoint",)):
            if field not in wanted and field in service and service[field] is None:
                del service[field]
        if role in {"backend", "web", "init-db"} and wanted.get("network_mode") == "service:guard":
            wanted_dependencies, dependencies = wanted.get("depends_on", {}), service.get("depends_on", {})
            require(type(wanted_dependencies) is dict and type(dependencies) is dict, drift)
            edge = dependencies.get("guard")
            if ("guard" not in wanted_dependencies and type(edge) is dict
                    and set(edge) == {"condition", "required", "restart"} and edge["condition"] == "service_started"
                    and edge["required"] is True and edge["restart"] is True):
                del dependencies["guard"]
                if "depends_on" not in wanted and not dependencies:
                    del service["depends_on"]
        if role == "guard":
            wanted_ports, ports = wanted.get("ports"), service.get("ports")
            require(type(wanted_ports) is list and type(ports) is list and len(wanted_ports) == len(ports) == 2, drift)
            for wanted_port, port in zip(wanted_ports, ports):
                require(type(wanted_port) is dict and type(port) is dict, drift)
                for field, default in (("mode", "ingress"), ("protocol", "tcp")):
                    if field not in wanted_port and type(port.get(field)) is str and port[field] == default:
                        del port[field]
                published = wanted_port.get("published")
                if (type(published) is int and 1 <= published <= 65535
                        and type(port.get("published")) is str and port["published"] == str(published)):
                    port["published"] = published
        wanted_mounts, mounts = wanted.get("volumes", []), service.get("volumes", [])
        require(type(wanted_mounts) is list and type(mounts) is list and len(mounts) == len(wanted_mounts), drift)
        for wanted_mount, mount in zip(wanted_mounts, mounts):
            require(type(wanted_mount) is dict and type(mount) is dict, drift)
            options = wanted_mount.get("bind")
            if (wanted_mount.get("type") == "bind" and type(options) is dict and set(options) == {"create_host_path"}
                    and options["create_host_path"] is False and type(mount.get("bind")) is dict and not mount["bind"]):
                mount["bind"] = {"create_host_path": False}
    wanted_networks, networks = expected.get("networks"), normalized.get("networks")
    require(type(wanted_networks) is dict and type(networks) is dict, drift)
    wanted_shadow, shadow = wanted_networks.get("shadow"), networks.get("shadow")
    require(type(wanted_shadow) is dict and type(shadow) is dict, drift)
    if "ipam" not in wanted_shadow and type(shadow.get("ipam")) is dict and not shadow["ipam"]:
        del shadow["ipam"]
    try:
        require(json_bytes(normalized) == json_bytes(expected), drift)
    except (TypeError, ValueError):
        raise BundleError(drift) from None


def main(argv=None):
    try:
        p = argparse.ArgumentParser(description=__doc__)
        for name in ("bundle", "base-compose", "frontend"):
            p.add_argument("--" + name, type=Path, required=True)
        for name in ("manifest-sha256", "base-sha256", "expect-source", "expect-release", "upstream-ip", "namespace"):
            p.add_argument("--" + name, required=True)
        p.add_argument("--upstream-port", type=int, required=True)
        p.add_argument("--mode", choices=("capabilities", "generate-t2i-4b"), required=True)
        p.add_argument("--accept-private-http", action="store_true")
        p.add_argument("--nginx-sha256")
        p.add_argument("--images", type=Path)
        p.add_argument("--images-sha256")
        p.add_argument("--check-compose", type=Path)
        p.add_argument("--check-sha256")
        p.add_argument("--compose-version")
        a = p.parse_args(argv)
        require(a.check_compose is not None or (a.check_sha256 is None and a.compose_version is None),
                "BRIDGE_EFFECTIVE_CHECK_REQUIRED")
        if a.check_compose is not None:
            require(a.compose_version is not None, "BRIDGE_COMPOSE_VERSION_REQUIRED")
            require(a.compose_version == COMPOSE_VERSION, "BRIDGE_COMPOSE_VERSION_UNSUPPORTED")
        require(a.accept_private_http, "BRIDGE_PRIVATE_HTTP_ACCEPTANCE_REQUIRED")
        manifest = verify(a.bundle, a.manifest_sha256)
        require(manifest["source_sha"] == a.expect_source and manifest["release_id"] == a.expect_release
                and ASSETS <= set(manifest["files"]), "BRIDGE_RELEASE_IDENTITY_MISMATCH")
        own_size, own_hash = file_hash(Path(__file__))
        require(manifest["files"]["docker_comfy_bridge_profile.py"] == {"size": own_size, "sha256": own_hash},
                "BRIDGE_HELPER_IDENTITY_MISMATCH")
        base = pinned(a.base_compose, a.base_sha256)
        base_info = native_base(base)
        if base_info["nginx"]:
            require(file_hash(plain_path(Path(base_info["nginx"])))[1] == a.nginx_sha256, "BRIDGE_NGINX_PIN_MISMATCH")
        assets = inventory(plain_path(a.frontend))
        expected = {k.removeprefix("frontend/"): v for k, v in manifest["files"].items() if k.startswith("frontend/")}
        require(assets == expected, "BRIDGE_FRONTEND_BYTES_MISMATCH")
        verify_frontend_directory(a.frontend, manifest["release_id"])
        metadata = load_json(a.frontend / "release-manifest.json")
        require(metadata.get("git_sha") == manifest["source_sha"] and metadata.get("release_id") == manifest["release_id"]
                and metadata.get("dirty") is False, "BRIDGE_FRONTEND_RELEASE_MISMATCH")
        template = load_json(a.bundle / "profiles/compose.comfyui-shadow.yml")
        config = render(base, manifest, template, a.frontend, upstream_ip=a.upstream_ip,
                        upstream_port=a.upstream_port, namespace=a.namespace, mode=a.mode,
                        images=pinned(a.images, a.images_sha256) if a.images else None)
        if a.check_compose:
            verify_effective(config, pinned(a.check_compose, a.check_sha256), compose_version=a.compose_version)
            print(json.dumps({"status": "BRIDGE_COMPOSE_VERIFIED", "source_sha": manifest["source_sha"],
                "release_id": manifest["release_id"], "compose_sha256": hashlib.sha256(json_bytes(config)).hexdigest(),
                "effective_compose_sha256": a.check_sha256, "compose_version": a.compose_version,
                "comparison_profile": COMPARISON_PROFILE,
                "mode": a.mode, "production_authorized": False}, sort_keys=True))
        else:
            print(json_bytes(config).decode(), end="")
        return 0
    except (BundleError, OSError, ValueError, TypeError, KeyError) as error:
        reason = str(error) if isinstance(error, BundleError) else "BRIDGE_PROFILE_FAILED"
        print(json.dumps({"status": "BLOCKED", "reason": reason, "production_authorized": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
