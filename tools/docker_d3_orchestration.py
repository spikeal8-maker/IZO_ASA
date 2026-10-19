"""Finite D3 caller proposal; controlled results never imply real model acceptance.

The caller supplies SHA-verified complete D1/D2 artifacts and their loaded images.
Run only after the reviewed browser supervisor/accounting and video fixes land.
No image build/download, production target, SQL seed or live provider is exposed.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import secrets
import signal
import threading
import time

from tools import docker_shadow_roles as roles
from tools.docker_clean_admin import PROFILE, prove_admin
from tools.docker_clean_admin_runtime import CapturedAdminShadow, profile_config
from tools.docker_clean_install import cleanup_owned, completed_extended, ports, require_fresh, telemetry
from tools.docker_shadow_executor import IsolatedExecutor, compare_isolated
from tools.docker_shadow_product import HttpClient, ProductError, ProductFlow, path_id, require
from tools.docker_shadow_smoke import prove
from tools.docker_d3_profiles import AUDIO, DELTA, MARKER, D3Shadow, RegisteredFlow, run_audio
from tools.docker_d3_images import save_private as save

READ_RECEIPT = """import os,stat,sys
fd=os.open('/tmp/izo-shadow-provider-receipt.json',os.O_RDONLY|os.O_NOFOLLOW)
with os.fdopen(fd,'rb') as source:
 st=os.fstat(source.fileno())
 assert stat.S_ISREG(st.st_mode) and st.st_uid==10001 and stat.S_IMODE(st.st_mode)==0o600
 data=source.read(65537)
 assert len(data)<=65536
sys.stdout.buffer.write(data)
"""
ADMIN_CHECKS = set("bootstrap simulatorSafety adminRights modelEconomics legalSetup checkout checkoutReplay "
    "paymentAccess foreignCheckoutReplay paymentSuccess successReplay refund refundReplay postRefundReplay "
    "cancellation audit otherUserBalance adminConcurrency".split())


class BudgetExpired(BaseException):
    """Escape component catch-all handlers; the outer caller still owns cleanup."""


@contextmanager
def wallclock(seconds):
    require(threading.current_thread() is threading.main_thread() and hasattr(signal, "SIGALRM"),
            "D3_LINUX_MAIN_THREAD_REQUIRED")
    started = time.monotonic()
    previous, handler = signal.getitimer(signal.ITIMER_REAL), signal.getsignal(signal.SIGALRM)
    require(previous[1] == 0, "D3_UNEXPECTED_PERIODIC_TIMER")
    def expired(_number, _frame):
        raise BudgetExpired()
    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, min(seconds, previous[0]) if previous[0] else seconds)
    try:
        yield
        require(time.monotonic() - started < seconds, "D3_WALL_CLOCK_EXCEEDED")
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, handler)
        if previous[0]:
            signal.setitimer(signal.ITIMER_REAL, max(.000001, previous[0] - (time.monotonic() - started)))


@contextmanager
def ledger_budget(seconds):
    try:
        with wallclock(seconds):
            yield
    except BudgetExpired:
        raise ProductError("D3_PRIVATE_LEDGER_READ_TIMEOUT") from None


def admit_attempts(attempts, source_sha, selected_project):
    require(isinstance(attempts, list) and len(attempts) == 6, "D3_SIX_COMPLETE_INSTALLATIONS_REQUIRED")
    groups, projects, runs, selected = {}, set(), set(), None
    for report in attempts:
        require(completed_extended(report) and report["sourceSha"] == report["checkoutSha"] == source_sha
                and report["D1Status"] == "PASS" and all(report["checks"][f"D1-{n:02}"]["status"] == "PASS"
                    for n in range(1, 9)), "D3_D1_OR_CLEANUP_NOT_ACCEPTED")
        extended = report["extended"]["results"]
        require(all(extended[name]["status"] == "PASS" and all(
                    extended[name]["checks"][f"D2-{number:02}"]["status"] == "PASS" for number in numbers)
                    for name, numbers in (("recovery", (1, 2, 3)), ("storage", (4, 5, 6)))),
                "D3_D2_NOT_ACCEPTED")
        images = report["resourcesBeforeRecreate"]["images"]
        require(images == report["resourcesAfterRecreate"]["images"]
                and set(images) == {"guard", "web", "backend", *roles.WORKERS}
                and all(re.fullmatch(r"sha256:[a-f0-9]{64}", value) for value in images.values())
                and images["backend"] == images["worker"] == images["worker_peer"], "D3_IMAGE_EVIDENCE_INVALID")
        host = report["host"]
        runs.add((host["runId"], host["attempt"]))
        identity = tuple(host[key] for key in ("machineIdentitySha256", "bootIdentitySha256", "engineId", "runnerName"))
        require(host["runnerEnvironment"] == "github-hosted" and report["project"] not in projects,
                "D3_INSTALLATION_IDENTITY_INVALID")
        groups.setdefault(identity, []).append(images)
        projects.add(report["project"])
        if report["project"] == selected_project:
            selected = deepcopy(images)
    require(len(runs) == 1 and len(groups) == 2 and all(len(rows) == 3 and rows[0] == rows[1] == rows[2]
            for rows in groups.values()) and selected is not None, "D3_TWO_FRESH_VM_GROUPS_REQUIRED")
    # Observed GitHub golden images share machine/engine IDs; boot and runner differ.
    require(len({identity[1] for identity in groups}) == 2 and len({identity[3] for identity in groups}) == 2,
            "D3_VM_IDENTITIES_REUSED")
    return selected


def api_identity(shadow, images, expected=None):
    rows = shadow.ownership_guard()
    roles.retained_runtime(shadow, rows, images)
    backend = next(row for row in rows if row["Config"]["Labels"]["com.docker.compose.service"] == "backend")
    state = backend["State"]
    require(state["Running"] and type(state["Pid"]) is int and state["Pid"] > 0, "D3_API_NOT_RUNNING")
    expected = expected if expected is not None else shadow.config()["services"]["backend"]
    environment = dict(item.split("=", 1) for item in backend["Config"]["Env"])
    require(all(environment.get(key) == value for key, value in expected["environment"].items())
            and backend["Config"]["User"] == expected["user"]
            and backend["Config"]["Cmd"] == expected["command"], "D3_RUNTIME_PROFILE_MISMATCH")
    return {"containerId": backend["Id"], "imageId": backend["Image"], "hostPid": state["Pid"],
            "startedAt": state["StartedAt"], "restartCount": backend["RestartCount"]}


def fixed_provider_reader(shadow, images):
    from tools.docker_d3_chat_video import admitted_provider
    expected = shadow.config()["services"]["backend"]
    marker = expected["environment"]["IZO_SHADOW_FIXTURE"]
    require(marker in {"controlled-comfyui-v1", MARKER, AUDIO}, "D3_PROVIDER_MARKER_INVALID")
    identity = api_identity(shadow, images, expected)
    def read():
        try:
            with wallclock(8):
                current = api_identity(shadow, images, expected)
                require(current == identity, "D3_PROVIDER_API_CHANGED")
                raw = shadow.docker("exec", identity["containerId"], "python", "-c", READ_RECEIPT, timeout=8)
                require(isinstance(raw, str) and len(raw) <= 65536 and len(raw.encode("utf-8")) <= 65536, "D3_PROVIDER_RECEIPT_LIMIT")
                value = json.loads(raw)
                require(isinstance(value, dict) and value.get("fixture") == marker
                        and value.get("lifetimeSeconds") == 300, "D3_PROVIDER_PROFILE_CHANGED")
                if marker == MARKER:
                    admitted_provider(value)
                elif marker == AUDIO:
                    from tools.docker_d3_audio_runtime import admitted_audio
                    admitted_audio(value)
                else:
                    provider = value.get("provider", {})
                    require(provider.get("model_execution") is False and isinstance(provider.get("jobs"), list)
                            and len(provider["jobs"]) <= 64, "D3_PROVIDER_CONTRACT_INVALID")
                return value
        except BudgetExpired:
            raise ProductError("D3_PROVIDER_READ_TIMEOUT") from None
    return read


def provider_checkpoint(directory, name, reader):
    path = directory / (name + "-provider.json")
    save(path, reader())
    return {"status": "PASS", "receipt": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def browser_cleaned(value):
    if not isinstance(value, dict) or not isinstance(value.get("cleanup"), dict):
        return False
    cleanup = value["cleanup"]
    return (cleanup.get("status") == "PASS" and type(value.get("nodeReturncode")) is int
            and value.get("scope") == "PRIVATE_LINUX_SUBREAPER"
            and type(cleanup.get("remainingChildren")) is int and cleanup["remainingChildren"] == 0)


def browser_process(value):
    return (browser_cleaned(value) and value.get("status") == "PASS" and value.get("timedOut") is False
            and value["nodeReturncode"] == 0 and type(value["cleanup"].get("childrenAtShutdown")) is int
            and value["cleanup"]["childrenAtShutdown"] == 0)


def checkpoint_step(report, directory, name, seconds, action):
    report.setdefault("checks", {}).setdefault(name, {"status": "FAIL"})
    save(directory / "receipt.json", report)
    started = time.monotonic()
    try:
        with wallclock(seconds):
            result = action()
        require(isinstance(result, dict) and result.get("status") in {"PASS", "FAIL", "PARTIAL"},
                "D3_INVALID_STEP_RESULT")
        report["checks"][name] = result
    except (BudgetExpired, Exception):
        report["checks"][name].update(status="FAIL", errorCode="D3_CONTROLLED_STEP_FAILED")
    report["checks"][name]["durationSeconds"] = round(time.monotonic() - started, 3)
    save(directory / "receipt.json", report)
    return report["checks"][name]


@contextmanager
def owned_project(seed, directory, suffix, images):
    directory.mkdir(parents=True, mode=0o700, exist_ok=False)
    web, api = ports()
    shadow = D3Shadow(seed.project + suffix, seed.sha, web, api, root=seed.root, fixture=True,
        executor_context=seed.executor.context, engine_id=seed.executor.engine_id,
        machine_sha256=seed.executor.machine_sha256)
    code, admitted, foreign = secrets.token_urlsafe(36), False, None
    report = {"status": "FAIL", "sourceSha": seed.sha, "project": shadow.project,
              "modelExecution": False, "acceleratorExecution": False, "checks": {}}
    try:
        with wallclock(60):
            shadow.source_guard()
            baseline = shadow.config()
            overlay = shadow.root / "ops/docker/dev/compose.admin-acceptance.yml"
            require(overlay.is_file() and not overlay.is_symlink(), "D3_ADMIN_OVERLAY_MISSING")
            shadow.files.append(overlay)
            shadow.env["IZO_ACCEPTANCE_ADMIN_CODE"] = code
            actual = profile_config(shadow, code)
            expected = deepcopy(baseline)
            expected["services"]["backend"]["environment"].update(ADMIN_ONE_TIME_CODE=code,
                BILLING_SIMULATOR_ENABLED="true", PUBLIC_SITE_URL=f"http://127.0.0.1:{web}")
            require(actual == expected and shadow.image_guard(actual) == images, "D3_BASE_PROFILE_OR_IMAGES_CHANGED")
            require_fresh(shadow)
            admitted = True
            foreign = shadow.executor.foreign_snapshot(shadow.project)
            save(directory / "foreign-before.json", foreign)
        with wallclock(240):
            prove(shadow, directory / "topology.json", build=False, expected_ephemeral_admin_code=code)
            topology = json.loads((directory / "topology.json").read_text(encoding="utf-8"))
            require(topology.get("status") == "PASS", "D3_TOPOLOGY_FAILED")
            report["resources"] = telemetry(shadow)
        attestation = {"origin": f"http://127.0.0.1:{web}", "sourceSha": seed.sha, "project": shadow.project,
            "isolatedData": True, "fakeProviderOnly": True, "networkEgressDenied": True,
            "externalEffectsDisabled": True, "proof": "topology.json", "adminFixture": PROFILE, "freshData": True}
        save(directory / "attestation.json", attestation)
        yield shadow, attestation, code, report
    finally:
        if admitted:
            try:
                with wallclock(180):
                    report["cleanup"] = cleanup_owned(shadow, True)
                    after = shadow.executor.foreign_snapshot(shadow.project)
                    save(directory / "foreign-after.json", after)
                    report["foreignResources"] = compare_isolated(foreign, after)
                    require(report["cleanup"].get("status") == report["foreignResources"].get("status") == "PASS",
                            "D3_OWNED_CLEANUP_FAILED")
            except (BudgetExpired, Exception):
                report.update(status="FAIL", cleanupError="D3_OWNED_CLEANUP_FAILED")
        shadow.env.pop("IZO_ACCEPTANCE_ADMIN_CODE", None)
        save(directory / "receipt.json", report)


def grant_owned_mini(flow, admin, code):
    owner = flow.owner.request("GET", "/api/me-v2")
    identifier = path_id(owner["internal_user_id"])
    admin.request("POST", "/api/auth/web-login", {"code": code})
    actor = admin.request("GET", "/api/me-v2")
    require(actor.get("account", {}).get("role") == "admin" and actor["internal_user_id"] != identifier,
            "D3_ADMIN_SESSION_REQUIRED")
    audit_path = "/api/admin/audit-logs-v2?action=admin_change_plan&limit=100&target_internal_user_id=" + identifier
    before = admin.request("GET", audit_path)
    require(before.get("total") == 0 and before.get("items") == [], "D3_ENTITLEMENT_ALREADY_MUTATED")
    changed = admin.request("POST", f"/api/admin/users/{identifier}/plan-v2",
        {"plan": "mini", "duration_days": 1, "reason": "D3 isolated owned video entitlement"})
    config, audit = flow.owner.request("GET", "/api/video/config"), admin.request("GET", audit_path)
    entries = audit.get("items", [])
    require(changed.get("ok") is True and changed.get("internal_user_id") == identifier
            and changed.get("plan") == "mini" and type(config.get("videoSlots")) is int
            and config["videoSlots"] >= 1 and audit.get("total") == len(entries) == 1,
            "D3_VIDEO_ENTITLEMENT_NOT_ESTABLISHED")
    entry = entries[0]
    require(entry.get("actor_internal_user_id") == actor["internal_user_id"]
            and entry.get("target_internal_user_id") == identifier
            and entry.get("action") == "admin_change_plan" and entry.get("after", {}).get("plan") == "mini",
            "D3_ENTITLEMENT_AUDIT_MISMATCH")
    return {"status": "PASS", "internalUserId": identifier, "plan": "mini", "durationDays": 1,
            "videoSlots": config["videoSlots"], "auditId": path_id(entry["id"]),
            "ledgerBaseline": "TAKEN_AFTER_GRANT", "undo": "OWNED_VOLUME_DISPOSAL_NOT_LEDGER_REVERSAL"}


def run_admin(seed, directory, images):
    with owned_project(seed, directory, "-admin", images) as (shadow, attestation, code, report):
        def probe():
            before = api_identity(shadow, images)
            result = prove_admin(attestation, directory / "admin.json", bootstrap_code=code)
            after = api_identity(shadow, images)
            report["apiProcessContinuity"] = {"before": before, "after": after,
                "status": "PASS" if before == after else "FAIL"}
            require(before == after and set(result.get("checks", {})) == ADMIN_CHECKS,
                    "D3_ADMIN_PROCESS_OR_CHECK_SET_CHANGED")
            return result
        result = checkpoint_step(report, directory, "admin", 180, probe)
        report["status"] = "PASS" if result.get("status") == "PASS" else "FAIL"
    return report


def run_generation(seed, directory, images):
    from tools.docker_clean_audio_features import asr_validation, platform_capabilities
    from tools.docker_d3_chat_video import prove_chat_video, prove_publication_restart
    from tools.docker_d3_image_ledger import prove_image_modes_private
    from tools.docker_d3_phone_watch import PhoneWatch
    from tools.docker_d3_ledger import private_ledger_reader, prove_browser_ledger
    with owned_project(seed, directory, "-generation", images) as (shadow, attestation, code, report):
        flow, admin = RegisteredFlow(attestation), HttpClient(attestation["origin"])
        step = lambda name, seconds, action: checkpoint_step(report, directory, name, seconds, action)
        try:
            baseline = step("productBaseline", 60, lambda: {"status": "PASS", "checks": flow.run()})
            captured = step("baselineProvider", 30, lambda: provider_checkpoint(directory, "baseline-final",
                fixed_provider_reader(shadow, images)))
            if baseline["status"] != "PASS" or captured["status"] != "PASS":
                return report
            def feature(action):
                row = {}
                action(flow, row)
                return {**row, "status": "PASS"}
            step("asrValidation", 90, lambda: feature(asr_validation))
            step("platform", 30, lambda: feature(platform_capabilities))
            entitled = step("videoEntitlement", 45, lambda: grant_owned_mini(flow, admin, code))
            # Changing to free would keep granted ledger entries and reset daily counters.
            # Dispose this owned fixture instead of claiming financial rollback.
            def recycle(name, publication=None):
                reader = None
                def restart():
                    nonlocal reader
                    retained = shadow.activate()
                    reader = fixed_provider_reader(shadow, images)
                    return {**provider_checkpoint(directory, name, reader), "retainedRuntime": retained}
                action = restart if publication is None else lambda: prove_publication_restart(
                    flow, attestation, publication, restart, lambda: api_identity(shadow, images), images["backend"])
                value = step(name, 90, action)
                require(value["status"] == "PASS", "D3_PROFILE_RECREATE_FAILED")
                return reader
            if entitled["status"] == "PASS":
                reader = recycle("chatProfile")
                flow.browser_credentials()
                video = step("chatVideo", 180, lambda: prove_browser_ledger(shadow, images, flow,
                    directory / "ledger", browser_probe=lambda: prove_chat_video(flow, attestation,
                        directory / "browser", provider_receipt=reader, phone_watch=lambda output, run_id:
                            PhoneWatch(shadow, images, flow, output, run_id, api_identity=api_identity)), api_identity=api_identity,
                    wallclock=ledger_budget, save=save))
                flow.credentials.clear()
                if not browser_process(video.get("process")) or video.get("phoneWatch", {}).get("cleanup") != "PASS":
                    video.update(status="FAIL", processError="D3_BROWSER_CLEANUP_NOT_ACCEPTED")
                captured = step("chatFinalProvider", 8, lambda: provider_checkpoint(directory, "chat-final", reader))
                if (isinstance(video.get("image"), dict) and captured["status"] == "PASS" and browser_cleaned(video.get("process"))
                        and video.get("phoneWatch", {}).get("cleanup") == "PASS" and video["phoneWatch"].get("threadAlive") is False):
                    reader = recycle("imageProfile", video if video.get("status") == "PASS" else None)
                    def checkpoint(value):
                        report["checks"]["imageModes"] = value
                        save(directory / "receipt.json", report)
                    with ledger_budget(8):
                        private = private_ledger_reader(shadow, images, flow, api_identity=api_identity, wallclock=ledger_budget)
                    step("imageModes", 210, lambda: prove_image_modes_private(flow, video["image"],
                        directory / "image-ledger", attestation=attestation, provider_receipt=reader,
                        private_ledger=private, checkpoint=checkpoint))
                    step("imageFinalProvider", 8, lambda: provider_checkpoint(directory, "image-final", reader))
                else:
                    report["checks"]["imageModes"] = {"status": "NOT_RUN", "reasonCode": "D3_SOURCE_OR_RECEIPT_NOT_ACCEPTED"}
        finally:
            def close_sessions():
                result = flow.close()
                admin.request("POST", "/api/auth/session/logout-v2", {})
                admin.request("GET", "/api/me-v2", expected=(401,))
                return {**result, "status": result["sessionCleanup"], "separateAdminSession": "CLOSED"}
            step("sessionCleanup", 60, close_sessions)
            for client in (*flow.clients, admin):
                client.cookies.clear()
            flow.credentials.clear()
            flow.registration_credentials.clear()
        expected = {"productBaseline", "baselineProvider", "asrValidation", "platform", "videoEntitlement",
                    "chatProfile", "chatVideo", "chatFinalProvider", "imageProfile", "imageModes",
                    "imageFinalProvider", "sessionCleanup"}
        report["status"] = "PASS" if set(report["checks"]) == expected and all(
            row.get("status") == "PASS" for row in report["checks"].values()) else "FAIL"
    return report


def phone_acceptance(profiles):
    """Preserve an independently proved Phone phase after a later video failure."""
    from tools.docker_d3_chat_video import accepted_phone_watch
    result = {"activeResume": "NOT_VERIFIED", "uiCancellation": "NOT_SUPPORTED"}
    try:
        video = profiles["generation"]["checks"]["chatVideo"]
        require(browser_cleaned(video.get("process")), "D3_PHONE_PROCESS_NOT_CLEAN")
        accepted_phone_watch(video.get("phoneWatch"), video.get("browser", {}))
    except (AttributeError, KeyError, TypeError, ProductError):
        return result
    result["activeResume"] = "PASS"
    return result


def rehearse_d3(seed, directory, *, attempts, selected_project):
    """Invoked by the exact-source isolated CI caller, after all six exact-source D1/D2 gates."""
    require(isinstance(seed.executor, IsolatedExecutor) and seed.fixture is True, "D3_ISOLATED_EXECUTOR_REQUIRED")
    images = admit_attempts(attempts, seed.sha, selected_project)
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, mode=0o700, exist_ok=False)
    report = {"status": "FAIL", "sourceSha": seed.sha, "evidenceClass": "CONTROLLED_APPLICATION_RUNTIME",
        "selectedImageProject": selected_project, "images": images, "D1AssertionsRequired": 48, "profiles": {}}
    for name, action in (("admin", run_admin), ("generation", run_generation), ("audio", run_audio)):
        try:
            report["profiles"][name] = action(seed, directory / name, images)
        except (BudgetExpired, Exception):
            path = directory / name / "receipt.json"
            partial = json.loads(path.read_text()) if path.is_file() else {}
            report["profiles"][name] = {**partial, "status": "FAIL", "errorCode": "D3_PROFILE_FAILED"}
        save(directory / "receipt.json", report)
    report["controlledScenarios"] = "PASS" if all(row.get("status") == "PASS"
        for row in report["profiles"].values()) else "FAIL"
    report["status"] = "PARTIAL" if report["controlledScenarios"] == "PASS" else "FAIL"
    report["phoneAcceptance"] = phone_acceptance(report["profiles"])
    report["remainingAcceptance"] = ["real selected models/audio",
        "remaining bounded admin audit findings", "target capacity and Windows factory route"]
    image = report["profiles"]["generation"].get("checks", {}).get("imageProfile", {})
    publication = image.get("publicationPersistence")
    if image.get("status") != "PASS" or not isinstance(publication, dict) or publication.get("status") != "PASS":
        report["remainingAcceptance"].insert(1, "video publication restart")
    if report["phoneAcceptance"]["activeResume"] != "PASS":
        report["remainingAcceptance"].insert(1, "Phone active browser resume")
    save(directory / "receipt.json", report)
    return report
