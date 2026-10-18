"""Measured crash, duplicate request and duplicate queue delivery on an owned fixture.

Only the provider is simulated. Auth, jobs, queue, worker and accounting remain
the application implementation. Failed contracts remain failed in the receipt.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import time
import uuid

from tools.docker_shadow import Shadow
from tools.docker_shadow_executor import compare_isolated
from tools.docker_shadow_product import ProductFlow, path_id, validate_target
from tools import docker_shadow_roles as roles

ACTIVE = {"queued", "running", "uploading", "sent_to_comfyui", "sent_to_openrouter"}
TERMINAL = {"completed", "failed", "cancelled"}
CHARGES = {"generation", "daily_generation", "openrouter_monthly_generation"}
REFUNDS = {"generation_refund", "daily_generation_refund", "openrouter_monthly_generation_refund"}
PAYLOAD = {"mode": "text_to_image", "provider": "comfyui", "prompt": "A blue ceramic cup",
           "width": 704, "height": 704, "steps": 4, "seed": 18731}
PROVIDER_READ = "from pathlib import Path; print(Path('/tmp/izo-shadow-provider-receipt.json').read_text())"
DATABASE_READ = r'''
import json,sqlite3,sys
users,job_ids=json.loads(sys.argv[1])
conn=sqlite3.connect('file:/home/izo/data/app.sqlite3?mode=ro',uri=True,timeout=5)
conn.row_factory=sqlite3.Row
conn.execute('PRAGMA query_only=ON')
conn.execute('BEGIN')
u=','.join('?' for _ in users)
j=','.join('?' for _ in job_ids) or 'NULL'
accounts={r['id']:dict(r) for r in conn.execute(
    'SELECT id,token_balance,daily_tokens_used,tokens_used,generation_count,last_daily_reset '
    'FROM users WHERE id IN ('+u+')',users)}
jobs=[dict(r) for r in conn.execute(
    'SELECT id,user_id,status,progress,result_image_id,completed_at FROM jobs '
    'WHERE id IN ('+j+') AND user_id IN ('+u+') ORDER BY id',[*job_ids,*users])]
images=[dict(r) for r in conn.execute(
    'SELECT id,job_id FROM images WHERE job_id IN ('+j+') AND user_id IN ('+u+') '
    'AND deleted_at IS NULL ORDER BY id',[*job_ids,*users])]
rows=conn.execute('SELECT id,user_id,delta,reason,meta_json FROM token_ledger '
    'WHERE user_id IN ('+u+') ORDER BY id LIMIT 501',users).fetchall()
if len(rows)>500:
    raise RuntimeError('RECOVERY_LEDGER_LIMIT')
ledger=[]
for row in rows:
    meta=json.loads(row['meta_json'] or '{}')
    if not isinstance(meta,dict) or meta.get('jobId') not in job_ids:
        continue
    item={key:row[key] for key in ('id','user_id','delta','reason')}
    item.update({key:meta.get(key) for key in ('jobId','token_cost','refund_tokens','daily_part','balance_part','monthly_part')})
    item['cause']=meta.get('reason') if meta.get('reason') in {
        'startup_reconciliation','user_cancelled','generation_failed',
        'cancelled_before_start','cancelled_during_generation','worker_lease_expired'} else None
    ledger.append(item)
active=conn.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running','uploading','sent_to_comfyui','sent_to_openrouter')").fetchone()[0]
conn.rollback()
conn.close()
print(json.dumps({'users':accounts,'jobs':jobs,'images':images,'ledger':ledger,'activeJobs':active}))
'''


class RecoveryError(RuntimeError):
    """Fixed diagnostic codes only; raw application errors never enter evidence."""


def require(condition, code):
    if not condition:
        raise RecoveryError(code)


def error_code(error):
    code = str(error)
    return code if re.fullmatch(r"[A-Z][A-Z0-9_]{2,100}", code) else "RECOVERY_OPERATION_FAILED"


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(path)


def wait_for(probe, *, seconds=20, code="RECOVERY_OBSERVATION_TIMEOUT"):
    deadline = time.monotonic() + seconds
    while True:
        value = probe()
        if value:
            return value
        require(time.monotonic() < deadline, code)
        time.sleep(.2)


def keyed_post(client, path, payload, key):
    previous = list(client.opener.addheaders)
    client.opener.addheaders = [*previous, ("Idempotency-Key", key)]
    try:
        return client.request("POST", path, payload)
    finally:
        client.opener.addheaders = previous


def accounting(snapshot, ids, *, refunded):
    """Verify per-job rows, including a daily refund whose cash delta is zero."""
    owners = {row["id"]: row["user_id"] for row in snapshot["jobs"]}
    for job_id in ids:
        rows = [row for row in snapshot["ledger"] if row["jobId"] == job_id]
        require(job_id in owners and all(row["user_id"] == owners[job_id] for row in rows),
                "RECOVERY_LEDGER_OWNER_MISMATCH")
        charges = [row for row in rows if row["reason"] in CHARGES]
        returns = [row for row in rows if row["reason"] in REFUNDS]
        require(len(charges) == 1 and int(charges[0]["token_cost"] or 0) > 0,
                "RECOVERY_CHARGE_COUNT_INVALID")
        require(len(returns) == int(refunded), "RECOVERY_REFUND_COUNT_INVALID")
        if refunded:
            charge, returned = charges[0], returns[0]
            require(returned["delta"] == -charge["delta"]
                    and returned["refund_tokens"] == charge["token_cost"]
                    and int(returned["daily_part"] or 0) == int(charge["daily_part"] or 0),
                    "RECOVERY_REFUND_AMOUNT_INVALID")


def same_accounts(before, after):
    fields = ("token_balance", "daily_tokens_used", "tokens_used", "generation_count")
    values = lambda snapshot: {key: tuple(int(row[field] or 0) for field in fields)
                               for key, row in snapshot["users"].items()}
    return values(before) == values(after)


class RecoveryRun:
    def __init__(self, shadow, flow, checkpoint):
        self.shadow, self.flow, self.checkpoint = shadow, flow, checkpoint
        self.user_ids, self.job_ids, self.images = [], [], None

    def guard(self):
        shadow = self.shadow
        require(shadow.fixture is True and shadow.executor is not None, "RECOVERY_ISOLATED_FIXTURE_REQUIRED")
        shadow.source_guard()
        images = shadow.image_guard(shadow.config())
        require(self.images is None or images == self.images, "RECOVERY_IMAGE_CHANGED")
        self.images = images
        return shadow.ownership_guard()

    def preflight(self):
        # Admit the same retained boundary before creating jobs or killing the API.
        containers = self.guard()
        return roles.retained_runtime(self.shadow, containers, self.images)

    def backend(self, *, running=True):
        rows = [row for row in self.shadow.ownership_guard()
                if row["Config"]["Labels"].get("com.docker.compose.service") == "backend"]
        require(len(rows) == 1 and (not running or rows[0]["State"]["Running"]), "RECOVERY_BACKEND_UNAVAILABLE")
        require(rows[0]["Image"] == self.images["backend"], "RECOVERY_BACKEND_IMAGE_CHANGED")
        return rows[0]

    def inside(self, code, *args):
        raw = self.shadow.docker("exec", self.backend()["Id"], "python", "-c", code, *args, timeout=15)
        require(len(raw) <= 100000, "RECOVERY_EVIDENCE_TOO_LARGE")
        value = json.loads(raw)
        require(isinstance(value, dict), "RECOVERY_EVIDENCE_INVALID")
        return value

    def provider(self):
        value = self.inside(PROVIDER_READ)
        require(value.get("fixture") == "controlled-comfyui-v1"
                and re.fullmatch(r"[0-9a-f]{32}", str(value.get("instanceId", "")))
                and value["provider"].get("model_execution") is False, "RECOVERY_FIXTURE_RECEIPT_INVALID")
        return value

    def snapshot(self):
        value = self.inside(DATABASE_READ, json.dumps([self.user_ids, self.job_ids]))
        require(set(value["users"]) == set(self.user_ids), "RECOVERY_USERS_MISSING")
        require({job["id"] for job in value["jobs"]} == set(self.job_ids), "RECOVERY_JOBS_MISSING")
        return value

    def signal(self, action):
        before = self.provider()
        self.guard()
        number = {"hold": "SIGUSR1", "release": "SIGUSR2", "duplicate": "SIGWINCH"}[action]
        self.shadow.compose("kill", "--signal", number, "backend", timeout=20)

        def acknowledged():
            value = self.provider()
            require(value["instanceId"] == before["instanceId"], "RECOVERY_SIGNAL_RESTARTED_FIXTURE")
            control = value["control"]
            if control["sequence"] <= before["control"]["sequence"]:
                return None
            require(control["sequence"] == before["control"]["sequence"] + 1
                    and control["action"] == action and control["status"] == "ACK", "RECOVERY_CONTROL_FAILED")
            return value

        return wait_for(acknowledged, seconds=10)

    def submit(self, key):
        result = keyed_post(self.flow.owner, "/api/generate", PAYLOAD, key)
        job_id = path_id(result.get("id"))
        require(result.get("status") in ACTIVE and type(result.get("tokenCost")) is int
                and result["tokenCost"] > 0, "RECOVERY_GENERATION_CONTRACT_INVALID")
        if job_id not in self.job_ids:
            self.job_ids.append(job_id)
        self.flow.other.request("GET", f"/api/jobs/{job_id}", expected=(404,))
        return {"id": job_id, "status": result["status"], "tokenCost": result["tokenCost"]}

    def held_job(self, case, key=None):
        before = self.signal("hold")
        started = self.submit(key or uuid.uuid4().hex)
        case["submitted"] = started

        def held():
            provider = self.provider()
            previous = {job["prompt_id"] for job in before["provider"]["jobs"]}
            new = [job for job in provider["provider"]["jobs"] if job["prompt_id"] not in previous]
            require(provider["instanceId"] == before["instanceId"], "RECOVERY_PROVIDER_RESTARTED")
            if len(new) != 1 or new[0]["state"] != "held":
                return None
            durable = self.snapshot()
            if next(job for job in durable["jobs"] if job["id"] == started["id"])["status"] not in ACTIVE:
                return None
            accounting(durable, [started["id"]], refunded=False)
            return {"provider": provider, "database": durable}

        case["acceptedBeforeAction"] = wait_for(held)
        self.checkpoint()
        return started["id"]

    def recreate(self):
        self.guard()
        before = self.backend(running=False)
        volumes = sorted(mount["Name"] for mount in before["Mounts"] if mount["Type"] == "volume")
        require(volumes == sorted(self.shadow.project + "_" + name for name in roles.backend_targets(self.shadow).values()),
                "RECOVERY_VOLUMES_INVALID")
        retained = self.shadow.up(build=False, recreate=True, application_only=True)
        after = self.backend()
        require(after["Id"] != before["Id"] and volumes == sorted(
            mount["Name"] for mount in after["Mounts"] if mount["Type"] == "volume"), "RECOVERY_VOLUMES_CHANGED")
        self.flow.guest.request("GET", "/api/health")
        provider = self.provider()
        require(provider["provider"]["counts"].get("accepted", 0) == 0, "RECOVERY_JOB_REPLAYED")
        return {"beforeContainer": before["Id"], "afterContainer": after["Id"],
                "image": after["Image"], "volumes": volumes, "provider": provider, "retainedRuntime": retained}

    def cancel(self, ids, key):
        observations = []
        for job_id in ids:
            pair = []
            for _ in range(2):
                result = keyed_post(self.flow.owner, f"/api/jobs/{job_id}/cancel", {}, key)
                require(result.get("id") == job_id and result.get("status") in TERMINAL,
                        "RECOVERY_CANCEL_RESPONSE_INVALID")
                pair.append({"id": result.get("id"), "status": result.get("status")})
            observations.append(pair)

        def settled():
            snapshot = self.snapshot()
            selected = [job for job in snapshot["jobs"] if job["id"] in ids]
            if any(job["status"] not in {"failed", "cancelled"} for job in selected):
                return None
            accounting(snapshot, ids, refunded=True)
            return snapshot

        return {"responses": observations, "database": wait_for(settled)}

    def crash(self, case):
        baseline = self.snapshot()
        job_id = self.held_job(case)
        killed = self.backend()
        self.guard()
        self.shadow.compose("kill", "--signal", "SIGKILL", "backend", timeout=20)
        stopped = self.backend(running=False)
        require(stopped["Id"] == killed["Id"] and not stopped["State"]["Running"]
                and stopped["State"]["ExitCode"] == 137, "RECOVERY_CRASH_NOT_OBSERVED")
        case["crash"] = {"container": stopped["Id"], "exitCode": 137}
        self.checkpoint()
        case["restart"] = self.recreate()
        after = self.snapshot()
        api = self.flow.owner.request("GET", f"/api/jobs/{job_id}")
        row = next(job for job in after["jobs"] if job["id"] == job_id)
        require(api.get("status") == row["status"] == "failed" and row["completed_at"]
                and row["result_image_id"] is None and not after["images"], "RECOVERY_JOB_OUTCOME_INVALID")
        accounting(after, [job_id], refunded=True)
        require(any(row["jobId"] == job_id and row["reason"] in REFUNDS
                    and row["cause"] == "startup_reconciliation" for row in after["ledger"]),
                "RECOVERY_STARTUP_REFUND_NOT_OBSERVED")
        require(same_accounts(after, baseline), "RECOVERY_ACCOUNT_NOT_RESTORED")
        case["afterRecovery"] = after
        case["secondRestart"] = self.recreate()
        case["afterSecondRestart"] = self.snapshot()
        require(case["afterSecondRestart"] == after, "RECOVERY_SECOND_RESTART_CHANGED_STATE")
        case["status"] = "PASS"

    def repeated(self, case):
        baseline = self.snapshot()
        key = uuid.uuid4().hex
        self.held_job(case, key)
        first, second = case["submitted"], self.submit(key)
        ids = list(dict.fromkeys((first["id"], second["id"])))
        case.update(requestKeySha256=hashlib.sha256(key.encode()).hexdigest(), responses=[first, second],
                    beforeCancel=self.snapshot())
        accounting(case["beforeCancel"], ids, refunded=False)
        self.checkpoint()
        case["cancel"] = self.cancel(ids, key)
        require(same_accounts(case["cancel"]["database"], baseline), "RECOVERY_CANCEL_ACCOUNT_NOT_RESTORED")
        case["cancelReplay"] = "PASS"
        case["status"] = "PASS" if len(ids) == 1 else "FAIL"
        if len(ids) != 1:
            case["errorCode"] = "RECOVERY_DUPLICATE_GENERATION_CHARGED"

    def concurrent(self, case):
        from tools.docker_clean_workers import prove_workers
        prove_workers(self, case)

    def two_users(self, case):
        case["freshFixture"] = self.recreate()
        baseline, ids, clients = self.snapshot(), [], (self.flow.owner, self.flow.other)
        require(baseline["activeJobs"] == 0, "RECOVERY_QUEUE_NOT_EMPTY")
        case["baseline"] = baseline
        try:
            ids.append(self.held_job(case))
            result = keyed_post(clients[1], "/api/generate", {**PAYLOAD, "seed": PAYLOAD["seed"] + 1}, uuid.uuid4().hex)
            ids.append(path_id(result.get("id")))
            self.job_ids.append(ids[1])
            case["submittedOther"] = {key: result.get(key) for key in ("id", "status", "queuePosition")}
            require(ids[0] != ids[1] and result.get("status") == "queued" and type(result.get("queuePosition")) is int
                    and result["queuePosition"] == 1, "RECOVERY_SECOND_USER_QUEUE_INVALID")
            states = [client.request("GET", f"/api/jobs/{job}")["status"] for job, client in zip(ids, clients)]
            for job, client in zip(ids, reversed(clients)):
                client.request("GET", f"/api/jobs/{job}", expected=(404,))
            self.guard()
            rows = self.shadow.containers()
            require(len(rows) == len(self.images) and all(row["State"]["Running"] for row in rows) and {
                row["Config"]["Labels"]["com.docker.compose.service"]: row["Image"] for row in rows
            } == self.images, "RECOVERY_STATS_CONTAINER_MISMATCH")
            samples = [json.loads(line) for line in self.shadow.docker("stats", "--no-stream", "--no-trunc",
                "--format", "{{json .}}", *[row["Id"] for row in rows], timeout=15).splitlines() if line]
            require(len(samples) == len(self.images) and {row["ID"] for row in samples} == {row["Id"] for row in rows}
                    and all(row.get("CPUPerc") and row.get("MemUsage") for row in samples), "RECOVERY_STATS_SAMPLE_MISMATCH")
            database, wire = self.snapshot(), self.provider()
            held = sum(job["state"] == "held" for job in wire["provider"]["jobs"])
            case["measurement"] = {"scope": "OWN_TWO_JOBS", "queuePosition": result["queuePosition"],
                "activeCount": sum(state in ACTIVE - {"queued"} for state in states), "queuedCount": states.count("queued"),
                "providerHeldCount": held, "database": database, "provider": wire, "resources": samples}
            self.checkpoint()
            require(states[0] in ACTIVE - {"queued"} and states[1] == "queued" and {
                row["id"]: (row["user_id"], row["status"]) for row in database["jobs"] if row["id"] in ids
            } == dict(zip(ids, zip(self.user_ids, states))), "RECOVERY_TWO_USER_STATE_INVALID")
            require(held == wire["provider"]["counts"]["accepted"] == 1 and wire["instanceId"]
                    == case["acceptedBeforeAction"]["provider"]["instanceId"], "RECOVERY_SECOND_USER_NOT_QUEUED")
            accounting(database, ids, refunded=False)
            case["status"] = "PASS"
        except Exception as error:
            case.update(status="FAIL", errorCode=error_code(error))
        finally:
            if not ids and "submitted" in case:
                ids.append(case["submitted"]["id"])
            case["cancelResponses"] = []
            for job, client in reversed(list(zip(ids, clients))):
                try:
                    response = client.request("POST", f"/api/jobs/{job}/cancel", {})
                    case["cancelResponses"].append({"id": response.get("id"), "status": response.get("status")})
                    require(response.get("id") == job and response.get("status") in TERMINAL, "RECOVERY_CANCEL_RESPONSE_INVALID")
                except Exception as error:
                    case["status"] = "FAIL"
                    case.setdefault("cleanupErrors", []).append({"id": job, "errorCode": error_code(error)})
            try:
                case["afterCancel"] = after = wait_for(lambda: (value if value["activeJobs"] == 0 else None) if (value := self.snapshot()) else None)
                accounting(after, ids, refunded=True)
                require(same_accounts(baseline, after) and all(row["status"] in {"failed", "cancelled"}
                    for row in after["jobs"] if row["id"] in ids), "RECOVERY_TWO_USER_ACCOUNTS_NOT_RESTORED")
            except Exception as error:
                case.update(status="FAIL", cleanupError=error_code(error))


def prove_recovery(shadow: Shadow, attestation: dict, receipt: Path) -> dict:
    require(not receipt.exists(), "RECOVERY_RECEIPT_ALREADY_EXISTS")
    report = {"status": "FAIL", "sourceSha": shadow.sha, "project": shadow.project, "checks": {},
              "measurements": {"D3-queue": {"status": "NOT_RUN"}}}
    flow = run = foreign = None
    admitted = False
    previous_recorder = vars(shadow).get("_guard_health_recorder")
    def record_health(value):
        history = report.setdefault("guardHealth", [])
        if not history or history[-1] != value:
            history.append(value)
            del history[:-16]
        save(receipt, report)  # Saved before the unchanged healthy predicate may reject.
    shadow._guard_health_recorder = record_health
    try:
        origin = validate_target(attestation)
        require(origin == f"http://127.0.0.1:{shadow.web_port}" and attestation["sourceSha"] == shadow.sha
                and attestation["project"] == shadow.project, "RECOVERY_TARGET_MISMATCH")
        run = RecoveryRun(shadow, None, lambda: save(receipt, report))
        report["retainedRuntimeAdmission"] = run.preflight()
        run.provider()
        foreign = shadow.executor.foreign_snapshot(shadow.project)
        admitted = True
        flow = run.flow = ProductFlow(attestation)
        run.user_ids = [flow.register(client, number)["legacy_user_id"]
                        for number, client in enumerate((flow.owner, flow.other), 41)]
        require(len(set(run.user_ids)) == 2, "RECOVERY_TWO_USERS_REQUIRED")
        flow.credentials.clear()
        for name, action in (("D2-01", run.crash), ("D2-02", run.repeated), ("D2-03", run.concurrent),
                             ("D3-queue", run.two_users)):
            cases = report["checks"] if name.startswith("D2-") else report["measurements"]
            case = cases[name] = {"status": "FAIL"}
            try:
                action(case)
            except Exception as error:
                case["errorCode"] = error_code(error)
            finally:
                save(receipt, report)
            try:
                case["cleanupRestart"] = run.recreate()
            except Exception as error:
                case.update(status="FAIL", cleanupError=error_code(error))
                break
        if (len(report["checks"]) == 3 and all(case["status"] == "PASS" for case in report["checks"].values())
                and report["measurements"]["D3-queue"]["status"] == "PASS"):
            report["status"] = "PASS"
    except Exception as error:
        report["errorCode"] = error_code(error)
    finally:
        if flow is not None:
            try:
                report["sessionCleanup"] = flow.close()
                require(report["sessionCleanup"].get("sessionCleanup") == "PASS", "RECOVERY_SESSION_CLEANUP_FAILED")
            except Exception as error:
                report.update(status="FAIL", sessionCleanupError=error_code(error))
        if admitted:
            try:
                report["foreignResources"] = compare_isolated(foreign, shadow.executor.foreign_snapshot(shadow.project))
                require(report["foreignResources"]["status"] == "PASS", "RECOVERY_FOREIGN_RESOURCE_CHANGED")
            except Exception as error:
                report.update(status="FAIL", cleanupError=error_code(error))
        try:
            save(receipt, report)
        finally:
            if previous_recorder is None:
                vars(shadow).pop("_guard_health_recorder", None)
            else:
                shadow._guard_health_recorder = previous_recorder
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("project", "source-sha", "executor-context", "engine-id", "machine-sha256"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--web-port", type=int, required=True)
    parser.add_argument("--api-port", type=int, required=True)
    parser.add_argument("--attestation", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    shadow = Shadow(args.project, args.source_sha, args.web_port, args.api_port, fixture=True,
                    executor_context=args.executor_context, engine_id=args.engine_id, machine_sha256=args.machine_sha256)
    result = prove_recovery(shadow, json.loads(args.attestation.read_text()), args.receipt)
    print("DOCKER_RECOVERY_" + result["status"])
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
