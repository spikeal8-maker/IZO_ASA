"""D2 backup/restore on owned Docker fixtures; never a production recovery tool."""
from __future__ import annotations

import base64
import copy
import hashlib
import io
import json
import re
import shutil
import sqlite3
import sys
import tarfile
import tempfile
import time
import types
from pathlib import Path, PurePosixPath
from contextlib import closing
from datetime import datetime, timezone

MAX_ARCHIVE = 16 * 1024 * 1024
MAX_EXPANDED = 192 * 1024 * 1024
CHUNK_BYTES = 24000
DATABASE = "/home/izo/data/app.sqlite3"
MEDIA = "/home/izo/media"
TRANSFER = "/tmp/izo-storage-transfer.tar.gz"


class StorageError(RuntimeError):
    """Fixed codes only; archive/session contents never enter evidence."""


def require(condition, code):
    if not condition:
        raise StorageError(code)


def contract_module(source):
    # The immutable image contains backend/, while the reviewed tool imports backend.app.
    if "/opt/izo" not in sys.path:
        sys.path.insert(0, "/opt/izo")
    module = types.ModuleType("izo_storage_contract")
    module.__file__ = "/opt/izo/fixtures/docker_shadow_storage.py"
    exec(compile(source, module.__file__, "exec"), module.__dict__)
    return module


def state(contract, database, media):
    return {"database": contract.database_state(Path(database), Path(media)),
            "media": contract.media_state(Path(media))}


def storage_probe(contract_source, database=DATABASE, media=MEDIA):
    return state(contract_module(contract_source), database, media)


def backup_export(contract_source, database=DATABASE, media=MEDIA):
    contract = contract_module(contract_source)
    database, media = Path(database), Path(media)
    require(database.is_file() and not database.is_symlink() and database.stat().st_size <= 64 * 1024**2
            and media.is_dir() and not media.is_symlink(), "STORAGE_SOURCE_PATH_INVALID")
    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        active = connection.execute("SELECT COUNT(*) FROM jobs WHERE status IS NULL OR status NOT IN "
                                    "('completed','failed','error','cancelled')").fetchone()[0]
        require(active == 0, "STORAGE_SOURCE_JOBS_NOT_QUIESCENT")
    before = state(contract, database, media)
    with tempfile.TemporaryDirectory(prefix="izo-d2-export-") as directory:
        backup = Path(directory) / "backup"
        saved = contract.create_backup(Path(database), Path(media), backup, require_separate_volume=False)
        contract.verify_snapshot(backup, saved.snapshot_id)
        require(state(contract, backup / "snapshots" / saved.snapshot_id / "database.sqlite3", media) == before,
                "STORAGE_ONLINE_BACKUP_STATE_CHANGED")
        require(state(contract, database, media) == before, "STORAGE_SOURCE_CHANGED_DURING_BACKUP")
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode="w:gz") as archive:
            for path in sorted(backup.rglob("*")):
                require(not path.is_symlink(), "STORAGE_BACKUP_SYMLINK")
                if path.is_file():
                    archive.add(path, arcname="backup/" + path.relative_to(backup).as_posix(), recursive=False)
        payload = output.getvalue()
        require(0 < len(payload) <= MAX_ARCHIVE, "STORAGE_ARCHIVE_LIMIT")
        receipt = {"status": "PASS", "snapshot": saved.snapshot_id, "sourceState": before,
                   "databaseBackup": "SQLITE_BACKUP_API", "sourceUnchanged": "PASS", "activeJobs": active,
                   "separatePhysicalDisk": "NOT_VERIFIED_DISPOSABLE_FIXTURE", "archiveBytes": len(payload)}
    return {"archive": base64.b64encode(payload).decode("ascii"),
            "sha256": hashlib.sha256(payload).hexdigest(), "receipt": receipt}


def extract_archive(payload, destination):
    require(0 < len(payload) <= MAX_ARCHIVE and not destination.exists(), "STORAGE_ARCHIVE_INPUT_INVALID")
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
        members, names, total = [], set(), 0
        for member in archive:
            require(len(members) < 3000, "STORAGE_ARCHIVE_MEMBER_LIMIT")
            path = PurePosixPath(member.name)
            require(member.isfile() and not path.is_absolute() and len(path.parts) > 1
                    and path.parts[0] == "backup" and ".." not in path.parts
                    and "\\" not in member.name and member.name not in names,
                    "STORAGE_ARCHIVE_PATH_INVALID")
            names.add(member.name)
            total += member.size
            require(0 <= member.size <= MAX_EXPANDED and total <= MAX_EXPANDED, "STORAGE_ARCHIVE_EXPANSION_LIMIT")
            members.append(member)
        require(members, "STORAGE_ARCHIVE_MEMBER_LIMIT")
        destination.mkdir()
        for member in members:
            target = destination / member.name
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.extractfile(member) as source, target.open("xb") as output:
                shutil.copyfileobj(source, output, 1024 * 1024)


def restore_import(contract_source, archive_file=TRANSFER, database=DATABASE, media=MEDIA, expected_sha=None):
    contract = contract_module(contract_source)
    database, media, archive_file = Path(database), Path(media), Path(archive_file)
    require(database.parent.is_dir() and media.is_dir() and not any(database.parent.iterdir())
            and not any(media.iterdir()), "STORAGE_DESTINATION_NOT_EMPTY")
    require(archive_file.is_file() and not archive_file.is_symlink()
            and archive_file.stat().st_size <= MAX_ARCHIVE, "STORAGE_ARCHIVE_INPUT_INVALID")
    payload = archive_file.read_bytes()
    require(hashlib.sha256(payload).hexdigest() == expected_sha, "STORAGE_TRANSFER_CHECKSUM")
    with tempfile.TemporaryDirectory(prefix="izo-d2-import-") as directory:
        root = Path(directory)
        extract_archive(payload, root / "extracted")
        backup = root / "extracted" / "backup"
        verified = contract.verify_snapshot(backup)
        negative = {}
        for kind in ("database", "media", "incomplete"):
            damaged = root / ("damaged-" + kind)
            shutil.copytree(backup, damaged)
            snapshot = damaged / "snapshots" / verified.snapshot_id
            if kind == "database":
                with (snapshot / "database.sqlite3").open("r+b") as stream:
                    stream.write(b"invalid SQLite!!")
            elif kind == "media":
                next(path for path in (damaged / "media-objects").rglob("*") if path.is_file()).write_bytes(b"corrupt")
            else:
                (snapshot / contract.COMPLETE_MARKER).unlink()
            negative[kind] = contract.expect_rejection(damaged, root / ("refused-" + kind), verified.snapshot_id)
            contract.verify_snapshot(backup, verified.snapshot_id)
            shutil.rmtree(damaged)
        staged = root / "restored"
        contract.restore_snapshot(backup, staged, verified.snapshot_id)
        expected = state(contract, staged / "database.sqlite3", staged / "media")
        # Only empty, independently owned volumes have reached this point.
        shutil.copy2(staged / "database.sqlite3", database)
        for path in (staged / "media").rglob("*"):
            target = media / path.relative_to(staged / "media")
            if path.is_dir():
                target.mkdir(exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
        observed = state(contract, database, media)
        require(observed == expected, "STORAGE_RESTORED_VOLUME_MISMATCH")
    archive_file.unlink()
    return {"status": "PASS", "restoredState": observed, "negativeCases": negative,
            "invalidDestinationsWritten": False, "snapshot": verified.snapshot_id}


def script(operation, arguments, module_source):
    require(operation in {"backup_export", "restore_import", "storage_probe"}, "STORAGE_OPERATION_INVALID")
    return ("import json,types; m=types.ModuleType('izo_storage_run'); "
            "m.__file__='/opt/izo/fixtures/docker_clean_storage.py'; "
            f"exec(compile({module_source!r},m.__file__,'exec'),m.__dict__); "
            f"a=json.loads({json.dumps(arguments)!r}); "
            f"print(json.dumps(getattr(m,{operation!r})(**a)))")


def mount_guard(shadow, identifier, *, helper=False, running=True):
    from tools.docker_shadow import OWNER
    shadow.ownership_guard()
    rows = json.loads(shadow.docker("inspect", identifier))
    require(len(rows) == 1, "STORAGE_CONTAINER_AMBIGUOUS")
    row, labels = rows[0], rows[0]["Config"].get("Labels", {})
    require(row["Id"] == identifier and (row["State"]["Running"] or not running)
            and labels.get("io.izo.owner") == OWNER and labels.get("com.docker.compose.project") == shadow.project
            and labels.get("com.docker.compose.service") == "backend" and row["Config"]["User"] == "10001:10001",
            "STORAGE_CONTAINER_NOT_OWNED")
    expected = {"/home/izo/data": shadow.project + "_sqlite-data", "/home/izo/media": shadow.project + "_media-data"}
    require(len(row["Mounts"]) == 2 and {m["Destination"] for m in row["Mounts"]} == set(expected)
            and all(m["Type"] == "volume" and m.get("RW") is True
            and expected.get(m["Destination"]) == m.get("Name") for m in row["Mounts"]), "STORAGE_VOLUME_NOT_OWNED")
    if helper:
        require(row["HostConfig"]["NetworkMode"] == "none" and not row["HostConfig"].get("PortBindings")
                and not row["HostConfig"].get("Privileged")
                and "no-new-privileges:true" in row["HostConfig"].get("SecurityOpt", [])
                and not row["HostConfig"].get("CapAdd") and row["HostConfig"]["CapDrop"] == ["ALL"],
                "STORAGE_HELPER_NOT_ISOLATED")
    return row


def backend_id(shadow):
    rows = [row for row in shadow.containers() if row["Config"]["Labels"].get("com.docker.compose.service") == "backend"]
    require(len(rows) == 1, "STORAGE_BACKEND_AMBIGUOUS")
    mount_guard(shadow, rows[0]["Id"])
    return rows[0]["Id"]


def container_call(shadow, identifier, code, *, helper=False):
    mount_guard(shadow, identifier, helper=helper)
    raw = shadow.docker("exec", identifier, "python", "-c", code, timeout=120)
    require(len(raw) <= MAX_ARCHIVE * 2, "STORAGE_CONTAINER_RESPONSE_LIMIT")
    result = json.loads(raw)
    require(isinstance(result, dict), "STORAGE_CONTAINER_RESPONSE_INVALID")
    return result


def copied_flow(flow, restored):
    from tools.docker_shadow_product import ProductFlow
    copy_flow = ProductFlow({"origin": f"http://127.0.0.1:{restored.web_port}", "project": restored.project,
        "sourceSha": restored.sha, "isolatedData": True, "fakeProviderOnly": True,
        "networkEgressDenied": True, "externalEffectsDisabled": True})
    copy_flow.saved, copy_flow.checks = copy.deepcopy(flow.saved), copy.deepcopy(flow.checks)
    for source, destination in zip(flow.clients, copy_flow.clients):
        for cookie in source.cookies:
            destination.cookies.set_cookie(copy.copy(cookie))
    return copy_flow


def media_fault(shadow, flow):
    identifier = backend_id(shadow)
    mode = container_call(shadow, identifier,
        "import json,stat; from pathlib import Path; p=Path('/home/izo/media'); "
        "f=p/'.write-probe'; f.open('xb').close(); f.unlink(); "
        "print(json.dumps({'mode':stat.S_IMODE(p.stat().st_mode)}))")["mode"]
    before = flow.account_snapshot(flow.owner)
    try:
        fault = container_call(shadow, identifier,
            "import json; from pathlib import Path; p=Path('/home/izo/media'); p.chmod(0o500); "
            "f=p/'.denied-probe'\ntry:\n f.open('xb').close(); f.unlink(); blocked=False\n"
            "except PermissionError:\n blocked=True\nprint(json.dumps({'blocked':blocked}))")
        require(fault.get("blocked") is True, "STORAGE_FAULT_NOT_ESTABLISHED")
        health = flow.guest.request("GET", "/api/health", expected=(200, 503))
        health_status = health.get("httpStatus", 200)
        started = flow.owner.request("POST", "/api/generate", {"provider": "comfyui", "mode": "text_to_image",
            "prompt": "Storage rejection fixture", "width": 704, "height": 704, "steps": 4, "seed": 193},
            expected=(200, 500, 503))
        if started.get("httpStatus") in {500, 503}:
            time.sleep(1)
            after = flow.account_snapshot(flow.owner)
            require(after["account"] == before["account"] and after["ledger"] == before["ledger"],
                    "STORAGE_REJECTED_REQUEST_CHARGED")
            return {"status": "PASS", "requestHttpStatus": started["httpStatus"],
                    "healthHttpStatus": health_status, "healthOk": health.get("ok"),
                    "charges": 0, "fault": "OWNED_MEDIA_DIRECTORY_NOT_WRITABLE", "duplicateChargeObservationSeconds": 1}
        from tools.docker_shadow_product import path_id
        job_id, deadline = path_id(started.get("id")), time.monotonic() + 60
        while True:
            job = flow.owner.request("GET", "/api/jobs/" + job_id)
            if job.get("status") in {"failed", "error", "cancelled", "completed"}:
                break
            require(time.monotonic() < deadline, "STORAGE_FAILURE_JOB_TIMEOUT")
            time.sleep(.2)
        require(job.get("status") in {"failed", "error", "cancelled"} and not job.get("resultImageId"),
                "STORAGE_FAILURE_FALSE_SUCCESS")
        after = flow.account_snapshot(flow.owner)
        require(after["account"] == before["account"], "STORAGE_FAILURE_BALANCE_NOT_RESTORED")
        previous = {item["id"] for item in before["ledger"]["items"]}
        changes = [item for item in after["ledger"]["items"] if item["id"] not in previous]
        charges = [item for item in changes if item["spentTokens"] > 0]
        refunds = [item for item in changes if item["reason"].endswith("_refund")]
        public_job = job_id[:10] + ("…" if len(job_id) > 10 else "")
        require(len(changes) == 2 and len(charges) == len(refunds) == 1
                and all(item["jobId"] == public_job for item in changes)
                and charges[0]["spentTokens"] == started["tokenCost"],
                "STORAGE_FAILURE_LEDGER_INVALID")
        time.sleep(1)
        require(flow.account_snapshot(flow.owner)["ledger"] == after["ledger"], "STORAGE_FAILURE_RECHARGED")
        return {"status": "PASS", "jobId": job_id, "jobStatus": job["status"],
                "healthHttpStatus": health_status, "healthOk": health.get("ok"),
                "balanceRestored": True, "charges": 1, "refunds": 1,
                "duplicateChargeObservationSeconds": 1, "fault": "OWNED_MEDIA_DIRECTORY_NOT_WRITABLE"}
    finally:
        container_call(shadow, identifier, "import json; from pathlib import Path; "
            f"Path('/home/izo/media').chmod({int(mode)}); print(json.dumps({{'permissionsRestored':True}}))")


def rehearse_storage(source, restored, flow, evidence_dir):
    from tools.docker_shadow_executor import compare_isolated
    from tools.docker_shadow_smoke import inspect_stack, http_proof, kernel_policy
    evidence_dir = Path(evidence_dir)
    require(not evidence_dir.exists() and bool(flow.saved), "STORAGE_EVIDENCE_OR_BASELINE_INVALID")
    require(source.fixture and restored.fixture and source.project != restored.project and source.sha == restored.sha
            and source.executor and restored.executor
            and source.executor.verify() == restored.executor.verify(), "STORAGE_ISOLATED_PAIR_REQUIRED")
    require(len({source.web_port, source.api_port, restored.web_port, restored.api_port}) == 4,
            "STORAGE_PORTS_NOT_DISTINCT")
    for shadow in (source, restored):
        shadow.source_guard()
        shadow.config()
        shadow.ownership_guard()
    require(not restored.containers() and all(not restored.docker(kind, "ls", "-q", "--filter",
        f"label=com.docker.compose.project={restored.project}").strip() for kind in ("volume", "network")),
        "STORAGE_RESTORED_PROJECT_NOT_NEW")
    evidence_dir.mkdir(parents=True)
    foreign = source.executor.foreign_snapshot(source.project)
    contract_source = (source.root / "tools/docker_shadow_storage.py").read_text(encoding="utf-8")
    module_source = Path(__file__).read_text(encoding="utf-8")
    helper = restored_flow = None
    report = {"status": "FAIL", "sourceSha": source.sha, "sourceProject": source.project,
              "restoredProject": restored.project, "checks": {}, "stage": "backup",
              "startedAt": datetime.now(timezone.utc).isoformat(), "origin": f"http://127.0.0.1:{restored.web_port}"}
    started_at = time.monotonic()
    try:
        exported = container_call(source, backend_id(source), script("backup_export",
                    {"contract_source": contract_source}, module_source))
        archive = base64.b64decode(exported.pop("archive"), validate=True)
        require(0 < len(archive) <= MAX_ARCHIVE and hashlib.sha256(archive).hexdigest() == exported["sha256"],
                "STORAGE_EXPORT_CHECKSUM")
        report["backup"] = exported
        images = restored.image_guard(restored.config())
        override = evidence_dir / "helper.json"
        override.write_text(json.dumps({"services": {"backend": {"image": images["backend"], "pull_policy": "never",
            "network_mode": "none", "healthcheck": {"disable": True}, "entrypoint": ["python"],
            "command": ["-c", "import time; time.sleep(600)"]}}}), encoding="utf-8")
        report["stage"] = "new-volumes"
        helper = restored.compose("run", "--no-deps", "-d", "--rm", "--name", restored.project + "-storage-helper",
            "backend", override=override).strip()
        require(re.fullmatch(r"[0-9a-f]{64}", helper) is not None, "STORAGE_HELPER_ID_INVALID")
        helper_row = mount_guard(restored, helper, helper=True)
        require(helper_row["Image"] == images["backend"]
                and helper_row["Config"].get("Healthcheck", {}).get("Test") == ["NONE"],
                "STORAGE_HELPER_IMAGE_OR_HEALTH_INVALID")
        report["volumes"] = [restored.project + "_sqlite-data", restored.project + "_media-data"]
        report["stage"] = "transfer-restore"
        for offset in range(0, len(archive), CHUNK_BYTES):
            chunk = base64.b64encode(archive[offset:offset + CHUNK_BYTES]).decode("ascii")
            code = ("import base64,json; from pathlib import Path; p=Path(" + repr(TRANSFER) + "); "
                    f"assert (p.stat().st_size if p.exists() else 0)=={offset}; "
                    f"f=p.open({'xb' if offset == 0 else 'ab'!r}); f.write(base64.b64decode({chunk!r},validate=True)); "
                    "f.close(); print(json.dumps({'written':True}))")
            container_call(restored, helper, code, helper=True)
        archive = b""
        imported = container_call(restored, helper, script("restore_import",
            {"contract_source": contract_source, "expected_sha": exported["sha256"]}, module_source), helper=True)
        require(imported["restoredState"] == exported["receipt"]["sourceState"], "STORAGE_RESTORE_STATE_MISMATCH")
        report["restore"] = imported
        report["checks"]["D2-05"] = {"status": "PASS", "negativeCases": imported["negativeCases"]}
        mount_guard(restored, helper, helper=True)
        restored.docker("rm", "-f", helper)
        helper = None
        report["stage"] = "restored-application"
        restored.up(build=False)
        stack = inspect_stack(restored)
        guard = next(row["Id"] for row in restored.containers()
                     if row["Config"]["Labels"].get("com.docker.compose.service") == "guard")
        report["topology"] = {"stack": stack, "http": http_proof(restored), "kernel": kernel_policy(restored, guard)}
        restored_flow = copied_flow(flow, restored)
        report["restoredApplication"] = restored_flow.verify_persistence()
        current = container_call(restored, backend_id(restored), script("storage_probe",
            {"contract_source": contract_source}, module_source))
        baseline = exported["receipt"]["sourceState"]
        require(current["media"] == baseline["media"]
                and current["database"]["migrationLedger"] == baseline["database"]["migrationLedger"]
                and current["database"]["imageReferences"] == baseline["database"]["imageReferences"],
                "STORAGE_RUNNING_APPLICATION_STATE_MISMATCH")
        report["runningStorage"] = current
        report["checks"]["D2-04"] = {"status": "PASS", "newNamedVolumes": 2, "application": "PASS"}
        report["stage"] = "storage-fault"
        report["checks"]["D2-06"] = media_fault(restored, restored_flow)
        report["status"] = "PASS"
    except Exception as error:
        code = str(error)
        report["errorCode"] = code if re.fullmatch(r"[A-Z][A-Z0-9_]{2,120}", code) else "STORAGE_OPERATION_FAILED"
        if code == "STORAGE_FAULT_NOT_ESTABLISHED" and report["stage"] == "storage-fault":
            report["checks"]["D2-06"] = {"status": "NOT_RUN", "reasonCode": code}
    finally:
        if restored_flow is not None:
            report["sessionCleanup"] = restored_flow.close()
            if report["sessionCleanup"]["sessionCleanup"] != "PASS":
                report["status"] = "FAIL"
        try:
            restored.ownership_guard()
            for row in restored.containers():
                if row["Name"].lstrip("/") == restored.project + "-storage-helper":
                    mount_guard(restored, row["Id"], helper=True, running=False)
                    restored.docker("rm", "-f", row["Id"])
            restored.compose("down", "--volumes", timeout=120)
            remaining = {kind: restored.docker(kind, "ls", "-q", "--filter",
                f"label=com.docker.compose.project={restored.project}").split() for kind in ("volume", "network")}
            require(not restored.containers() and not any(remaining.values()), "STORAGE_CLEANUP_INCOMPLETE")
            report["cleanup"] = {"status": "PASS", "remaining": remaining}
            report["foreignComparison"] = compare_isolated(foreign, source.executor.foreign_snapshot(source.project))
            require(report["foreignComparison"]["status"] == "PASS", "STORAGE_FOREIGN_RESOURCES_CHANGED")
            if "backup" in report:
                observed = container_call(source, backend_id(source), script("storage_probe",
                    {"contract_source": contract_source}, module_source))
                report["sourceAfterD2"] = observed
                require(observed == report["backup"]["receipt"]["sourceState"], "STORAGE_SOURCE_CHANGED_DURING_D2")
                report["sourceUnchanged"] = "PASS"
        except Exception as error:
            code = str(error)
            report["cleanup"], report["status"] = {"status": "FAIL", "errorCode": code
                if re.fullmatch(r"[A-Z][A-Z0-9_]{2,120}", code) else "STORAGE_CLEANUP_FAILED"}, "FAIL"
        attempted = {"D2-04": True, "D2-05": report["stage"] in {"transfer-restore", "restored-application", "storage-fault"},
                     "D2-06": report["stage"] == "storage-fault"}
        for name in ("D2-04", "D2-05", "D2-06"):
            report["checks"].setdefault(name, {"status": "FAIL" if attempted[name] else "NOT_RUN"})
        report.update(finishedAt=datetime.now(timezone.utc).isoformat(), durationSeconds=round(time.monotonic()-started_at, 3))
        (evidence_dir / "storage.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report
