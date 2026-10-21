"""Owned Docker lifecycle for the explicit, local-only admin acceptance profile."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import re
import secrets
import time

from tools.docker_clean_admin import PROFILE, prove_admin
from tools.docker_shadow import Shadow, ShadowError
from tools.docker_shadow_executor import IsolatedExecutor, compare_isolated
from tools.docker_shadow_smoke import check_backend_credentials, prove


class CapturedAdminShadow(Shadow):
    """Keep every child output private, including inherited lifecycle failures."""

    def run(self, args, *, capture=True, timeout=60):
        return super().run(args, capture=True, timeout=timeout)


def require(value, code):
    if not value:
        raise ShadowError(code)


def profile_config(shadow, code):
    require(isinstance(shadow.executor, IsolatedExecutor) and shadow.fixture is True,
            "ADMIN_RUNTIME_EXECUTOR_REQUIRED")
    require(isinstance(code, str) and re.fullmatch(r"[A-Za-z0-9_-]{48}", code),
            "ADMIN_RUNTIME_CODE_INVALID")
    config = shadow.config()
    backend = config["services"]["backend"]
    # Apply the exact inspected-container contract before the first Docker up.
    check_backend_credentials(shadow, {"Config": {"Cmd": backend.get("command"),
        "Entrypoint": backend.get("entrypoint")}}, backend.get("environment", {}),
        expected_ephemeral_admin_code=code)
    return config


def rehearse_admin(source_shadow, directory: Path):
    # Reuse the already reviewed ownership/cleanup helpers; no alternate Docker
    # command surface or host admission is introduced by this profile.
    from tools.docker_clean_install import cleanup_owned, ports, redact_logs, require_fresh, save, telemetry

    require(isinstance(source_shadow.executor, IsolatedExecutor) and source_shadow.fixture is True,
            "ADMIN_RUNTIME_EXECUTOR_REQUIRED")
    directory.mkdir(parents=True, exist_ok=False)
    web, api = ports()
    shadow = CapturedAdminShadow(source_shadow.project + "-admin", source_shadow.sha, web, api,
        root=source_shadow.root, fixture=True, executor_context=source_shadow.executor.context,
        engine_id=source_shadow.executor.engine_id,
        machine_sha256=source_shadow.executor.machine_sha256)
    overlay = shadow.root / "ops/docker/dev/compose.admin-acceptance.yml"
    require(overlay.is_file() and not overlay.is_symlink(), "ADMIN_RUNTIME_OVERLAY_MISSING")
    code = secrets.token_urlsafe(36)
    report = {"status": "FAIL", "sourceSha": shadow.sha, "project": shadow.project,
              "profile": PROFILE, "origin": f"http://127.0.0.1:{web}",
              "apiOrigin": f"http://127.0.0.1:{api}", "livePayments": False,
              "production": "NOT_VERIFIED"}
    admitted, foreign, stage = False, None, "admission"
    started = time.monotonic()
    try:
        shadow.source_guard()
        baseline = shadow.config()
        shadow.files.append(overlay)
        shadow.env["IZO_ACCEPTANCE_ADMIN_CODE"] = code
        config = profile_config(shadow, code)
        expected = copy.deepcopy(baseline)
        expected["services"]["backend"]["environment"].update(
            ADMIN_ONE_TIME_CODE=code, BILLING_SIMULATOR_ENABLED="true",
            PUBLIC_SITE_URL=report["origin"])
        require(config == expected, "ADMIN_RUNTIME_UNEXPECTED_CONFIG_CHANGE")
        report["configSha256"] = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
        report["overlaySha256"] = hashlib.sha256(overlay.read_bytes()).hexdigest()
        require_fresh(shadow)
        admitted = True
        foreign = shadow.executor.foreign_snapshot(shadow.project)
        save(directory / "foreign-before.json", foreign)
        stage = "topology"
        # This proof starts and recreates only this fresh project's pinned images,
        # and exercises the existing egress positive/negative controls.
        prove(shadow, directory / "topology.json", build=False,
              expected_ephemeral_admin_code=code)
        topology = json.loads((directory / "topology.json").read_text(encoding="utf-8"))
        require(topology.get("status") == "PASS", "ADMIN_RUNTIME_TOPOLOGY_NOT_PROVEN")
        report["resources"] = telemetry(shadow)
        attestation = {"origin": report["origin"], "sourceSha": shadow.sha,
            "project": shadow.project, "isolatedData": True, "fakeProviderOnly": True,
            "networkEgressDenied": True, "externalEffectsDisabled": True,
            "proof": "topology.json", "adminFixture": PROFILE, "freshData": True}
        save(directory / "attestation.json", attestation)
        stage = "admin-api"
        report["acceptance"] = prove_admin(attestation, directory / "admin.json", bootstrap_code=code)
        if report["acceptance"].get("status") == "PASS":
            report["status"] = "PASS"
        else:
            report["failedStage"] = stage
    except Exception:
        # Exceptions may contain a resolved Compose environment. Only a fixed
        # code and our own bounded stage name can reach the artifact.
        report.update(status="FAIL", failedStage=stage, errorCode="ADMIN_RUNTIME_OPERATION_FAILED")
    finally:
        if admitted:
            try:
                raw = shadow.compose("logs", "--no-color", "--tail", "150", capture=True, timeout=20)
                (directory / "containers.redacted.log").write_text(
                    redact_logs(raw).replace(code, "[REDACTED_ADMIN_CODE]"), encoding="utf-8")
            except Exception:
                report.update(status="FAIL", logCapture="ADMIN_RUNTIME_LOG_CAPTURE_FAILED")
            try:
                report["cleanup"] = cleanup_owned(shadow, admitted)
                after = shadow.executor.foreign_snapshot(shadow.project)
                save(directory / "foreign-after.json", after)
                report["foreignResources"] = compare_isolated(foreign, after)
                require(report["cleanup"].get("status") == "PASS"
                        and report["foreignResources"].get("status") == "PASS",
                        "ADMIN_RUNTIME_CLEANUP_NOT_PROVEN")
            except Exception:
                report.update(status="FAIL", cleanupError="ADMIN_RUNTIME_CLEANUP_FAILED")
        shadow.env.pop("IZO_ACCEPTANCE_ADMIN_CODE", None)
        report["durationSeconds"] = round(time.monotonic() - started, 3)
        save(directory / "receipt.json", report)
    return report
