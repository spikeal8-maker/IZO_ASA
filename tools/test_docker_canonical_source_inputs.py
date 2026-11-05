"""Static ordinary-runtime source closure; no Docker, Compose merge or ignore matcher.

These checks read declarations and literal COPY references. Only a separate
exact-SHA container gate can prove BuildKit contexts and runtime behavior.
"""
from __future__ import annotations

import ast
import json
import os
import re
import runpy
import shlex
import shutil
from pathlib import Path

import pytest
import yaml

from tools.docker_linux_bundle_build import pinned_dockerfiles
from tools.docker_test_bundle_format import RUNTIME, UVICORN

ROOT = Path(__file__).resolve().parents[1]
DEV = Path("ops/docker/dev")
DONOR_INPUTS = (
    "compose.shadow.yml", "Dockerfile.web", "nginx.shadow.conf",
    "Dockerfile.web.dockerignore", "Dockerfile.guard", "network_guard.py",
    "Dockerfile.guard.dockerignore", "comfyui_proxy.py",
)


def source_inputs(root: Path, *, profile: str) -> tuple[dict, list]:
    assert profile == RUNTIME, "This source contract requires explicit synthetic-runtime"
    inputs, documents = {}, []

    def require(relative: Path, consumer: str) -> Path:
        path = root / relative
        assert path.exists(), f"{consumer} requires missing {relative.as_posix()}"
        assert not path.is_symlink() and path.resolve().is_relative_to(root.resolve())
        inputs[relative.as_posix()] = path
        return path

    for name in ("compose.yml", "compose.shadow.yml"):
        compose = require(DEV / name, profile)
        document = yaml.safe_load(compose.read_text(encoding="utf-8-sig"))
        documents.append(document)
        for role, service in document["services"].items():
            if "build" not in service:
                continue
            build = service["build"]
            assert (compose.parent / build["context"]).resolve() == root.resolve()
            dockerfile = require(Path(build["dockerfile"]), f"{name}: services.{role}.build")
            relative = dockerfile.relative_to(root)
            ignore = Path(str(relative) + ".dockerignore") if role != "backend" else Path(".dockerignore")
            require(ignore, f"{relative.as_posix()} build context")
            text = dockerfile.read_text(encoding="utf-8-sig")
            stages = set(re.findall(r"(?m)^FROM \S+ AS (\w+)$", text))
            for line in text.splitlines():
                line = line.strip()
                if not re.match(r"COPY\s+", line, re.IGNORECASE):
                    continue
                parts = shlex.split(line)[1:]
                options = []
                while parts and parts[0].startswith("--"):
                    options.append(parts.pop(0))
                assert len(parts) >= 2 and not line.endswith("\\"), "Literal COPY contract only"
                assert all(option.startswith(("--chown=", "--from=", "--chmod=")) for option in options)
                stage = [option.split("=", 1)[1] for option in options if option.startswith("--from=")]
                if stage:
                    assert len(stage) == 1 and stage[0] in stages
                    continue  # Build-stage output is not a checkout file.
                for source in parts[:-1]:
                    assert not any(char in source for char in "*$?[]"), "Literal COPY contract only"
                    require(Path(source), f"{relative.as_posix()}: COPY")
    return inputs, documents


def test_actual_checkout_has_runtime_source_closure():
    inputs, _ = source_inputs(ROOT, profile=RUNTIME)
    assert set(pinned_dockerfiles(ROOT)) == {"backend", "web", "guard"}
    assert {(DEV / name).as_posix() for name in DONOR_INPUTS} <= set(inputs)


@pytest.fixture
def minimal_source(tmp_path):
    inputs, _ = source_inputs(ROOT, profile=RUNTIME)
    for relative, source in inputs.items():
        target = tmp_path / relative
        if source.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    return tmp_path


@pytest.mark.parametrize("missing", [
    *(f"ops/docker/dev/{name}" for name in DONOR_INPUTS),
    "ops/docker/dev/compose.yml", "ops/docker/dev/Dockerfile.backend", ".dockerignore",
    "backend/requirements.txt", "frontend/package.json", "frontend/package-lock.json",
])
def test_missing_input_is_rejected_in_temporary_tree(minimal_source, missing):
    assert minimal_source != ROOT
    (minimal_source / missing).unlink()
    with pytest.raises(AssertionError, match="requires missing " + re.escape(missing)):
        source_inputs(minimal_source, profile=RUNTIME)


@pytest.mark.parametrize("instruction", ["COPY ", "  copy\t"])
def test_new_copy_dependency_is_discovered_from_dockerfile(minimal_source, instruction):
    dockerfile = minimal_source / DEV / "Dockerfile.web"
    with dockerfile.open("a", encoding="utf-8") as handle:
        handle.write(f"\n{instruction}frontend/required-build-input.ts ./\n")
    with pytest.raises(AssertionError, match=r"Dockerfile.web: COPY requires missing frontend/required-build-input.ts"):
        source_inputs(minimal_source, profile=RUNTIME)


def test_profile_must_be_explicitly_ordinary():
    with pytest.raises(AssertionError, match="explicit synthetic-runtime"):
        source_inputs(ROOT, profile="acceptance-fixture")


def test_ordinary_topology_and_guard_boundaries():
    _, (base, overlay) = source_inputs(ROOT, profile=RUNTIME)
    assert set(base["services"]) == {"backend"}
    assert set(overlay["services"]) == {"backend", "web", "guard"}
    for document in (base, overlay):
        assert set(document["volumes"]) == {"sqlite-data", "media-data"}
        assert all("command" not in service and "entrypoint" not in service
                   for service in document["services"].values())
    guard = overlay["services"]["guard"]
    assert all(port.startswith("127.0.0.1:") for port in guard["ports"])
    assert set(guard["cap_add"]) == {"NET_ADMIN", "SETUID", "SETGID"}
    assert guard["cap_drop"] == ["ALL"] and guard["read_only"] is True
    assert guard["dns"] == ["127.0.0.1"]
    assert guard["sysctls"]["net.ipv6.conf.all.disable_ipv6"] == "1"
    assert guard["healthcheck"]["test"] == ["CMD", "python", "/network_guard.py", "--check"]
    for role in ("backend", "web"):
        app = overlay["services"][role]
        assert app["network_mode"] == "service:guard"
        assert app["depends_on"]["guard"]["condition"] == "service_healthy"
        assert "ports" not in app and "volumes" not in app
    web = overlay["services"]["web"]
    assert web["user"] == "101:101" and web["read_only"] is True
    assert web["cap_drop"] == ["ALL"] and "cap_add" not in web


@pytest.mark.parametrize("role", ["web", "guard"])
def test_declared_ignore_allowlists_and_exclusion_order(role):
    rules = [line.strip() for line in (ROOT / DEV / f"Dockerfile.{role}.dockerignore").read_text().splitlines()
             if line.strip() and not line.lstrip().startswith("#")]
    assert len(rules) == len(set(rules)), "Repeated rules can reverse the declared ignore boundary"
    parents = {"!ops/", "!ops/docker/", "!ops/docker/dev/"}
    allowed = ({"!frontend/", "!frontend/**", "!ops/docker/dev/nginx.shadow.conf"} if role == "web"
               else {"!ops/docker/dev/network_guard.py", "!ops/docker/dev/comfyui_proxy.py"})
    assert rules[0] == "**" and {rule for rule in rules if rule.startswith("!")} == parents | allowed
    boundaries = {"ops/**", "ops/docker/**", "ops/docker/dev/**"}
    for parent, boundary, child in (("!ops/", "ops/**", "!ops/docker/"),
                                    ("!ops/docker/", "ops/docker/**", "!ops/docker/dev/")):
        assert rules.index(parent) < rules.index(boundary) < rules.index(child)
    for leaf in (rule for rule in allowed if rule.startswith("!ops/docker/dev/")):
        assert rules.index("!ops/docker/dev/") < rules.index("ops/docker/dev/**") < rules.index(leaf)
    if role == "web":
        # The separate real BuildKit export proves matching and context boundaries.
        excluded = {"**/.env", "**/.env.*", "**/.npmrc", "**/secrets", "**/media",
                    "**/*.sqlite*", "**/*.db", "**/*.db-wal", "**/*.db-shm", "**/*.db-journal",
                    "**/node_modules", "**/dist"}
        assert excluded <= set(rules)
        assert min(rules.index(rule) for rule in excluded) > max(rules.index(rule) for rule in allowed | parents)
    else:
        assert set(rules) == {"**"} | parents | allowed | boundaries


def test_source_identity_and_existing_backend_command():
    for role in ("backend", "web", "guard"):
        text = (ROOT / DEV / f"Dockerfile.{role}").read_text(encoding="utf-8-sig")
        assert "ARG IZO_SOURCE_SHA" in text
        assert 'org.opencontainers.image.revision="${IZO_SOURCE_SHA}"' in text
        assert 'org.opencontainers.image.source="spikeal8-maker/IZO_ASA"' in text
        if role == "backend":
            assert json.loads(next(line[4:] for line in text.splitlines() if line.startswith("CMD "))) == UVICORN
            assert all("backend/" in line for line in text.splitlines() if line.startswith("COPY "))


def test_guard_policy_and_readiness_order_without_kernel_calls():
    path = ROOT / DEV / "network_guard.py"
    source = path.read_text()
    namespace = runpy.run_path(str(path))  # __main__ is not executed; no nft or privilege changes.
    expected = ('table inet izo_shadow { chain output { '
                'type filter hook output priority filter; policy drop; '
                'oifname "lo" accept ct state established,related accept counter drop } }')
    assert " ".join(namespace["RULES"].split()) == expected
    namespace["validate_policy"](namespace["RULES"])
    with pytest.raises(RuntimeError, match="SHADOW_KERNEL_POLICY_MISMATCH"):
        namespace["validate_policy"](namespace["RULES"].replace("counter drop", "accept\n        counter drop"))
    main = next(node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef) and node.name == "main")
    statements = [ast.unparse(node) for node in main.body]
    ordered = ["policy_state()", "os.setgroups([])", "os.setgid(10001)", "os.setuid(10001)",
               "signal.signal(signal.SIGCHLD, signal.SIG_IGN)", "READY.write_text(MARKER)"]
    indices = [statements.index(statement) for statement in ordered]
    assert indices == sorted(indices)


@pytest.mark.parametrize("context_mode", [0o600, 0o644])
def test_nginx_copy_declares_readable_image_mode_even_for_private_context(minimal_source, context_mode):
    config = minimal_source / DEV / "nginx.shadow.conf"
    config.chmod(context_mode)
    inputs, _ = source_inputs(minimal_source, profile=RUNTIME)
    if os.name == "nt":
        # Windows chmod controls the read-only flag, not POSIX permission bits.
        assert config.stat().st_mode & 0o200
    else:
        assert config.stat().st_mode & 0o777 == context_mode
    assert (DEV / "nginx.shadow.conf").as_posix() in inputs
    dockerfile = (minimal_source / DEV / "Dockerfile.web").read_text()
    copy = next(shlex.split(line) for line in dockerfile.splitlines()
                if line.startswith("COPY ") and "/etc/nginx/nginx.conf" in line)
    assert copy == ["COPY", "--chmod=0644", "ops/docker/dev/nginx.shadow.conf", "/etc/nginx/nginx.conf"]
    assert "USER 101:101" in dockerfile
