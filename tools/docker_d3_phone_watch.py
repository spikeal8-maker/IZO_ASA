"""One owned Phone marker releases one already-required held chat-image job.

The watcher runs in the caller, never in the private single-thread subreaper.
No application import, SQL write, new provider endpoint or generation is added.
"""
from __future__ import annotations

from copy import copy, deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import threading
import time

from tools.docker_d3_chat_video import admitted_provider
from tools.docker_d3_images import save_private
from tools.docker_shadow import OWNER
from tools.docker_shadow_executor import IsolatedExecutor
from tools.docker_shadow_product import ProductError, require

MARKER = "phone-active-held.json"
ACTIVE = {"queued", "running", "uploading", "sent_to_comfyui"}
OBSERVATIONS = {"sameJobAfterReload": True, "spaSignalAborted": True,
                "pollsAfterUnmount": 0, "imageSubmits": 0, "videoSubmits": 0}
MAX_COMMAND_SECONDS, PREPARE_SECONDS, HOLD_SECONDS, ACK_SECONDS, JOIN_SECONDS = 2, 15, 55, 8, 3

READ_STATE = r'''
import hashlib,json,os,re,sqlite3,stat,sys,time
try:
 owner,job=json.loads(sys.argv[1])
 assert isinstance(owner,list) and len(owner)==2
 assert re.fullmatch(r'web_[0-9a-f]{32}',owner[0])
 assert isinstance(owner[1],str) and re.fullmatch(r'[A-Za-z0-9_-]{1,120}',owner[1])
 assert job is None or isinstance(job,str) and re.fullmatch(r'[A-Za-z0-9_-]{1,120}',job)
 with open('/proc/1/stat','rb') as source: process=source.read(4097)
 assert len(process)<=4096
 ticks=process.rsplit(b')',1)[1].split()[19].decode('ascii');assert ticks.isdecimal()
 fd=os.open('/tmp/izo-shadow-provider-receipt.json',os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
 with os.fdopen(fd,'rb') as source:
  info=os.fstat(source.fileno())
  assert stat.S_ISREG(info.st_mode) and info.st_uid==10001 and stat.S_IMODE(info.st_mode)==0o600
  raw=source.read(65537);assert len(raw)<=65536
 provider=json.loads(raw)
 info=os.lstat('/home/izo/data/app.sqlite3')
 assert stat.S_ISREG(info.st_mode) and info.st_uid==10001
 conn=sqlite3.connect('file:/home/izo/data/app.sqlite3?mode=ro',uri=True,timeout=1)
 try:
  started=time.monotonic();conn.set_progress_handler(lambda:int(time.monotonic()-started>1),500)
  conn.execute('PRAGMA query_only=ON');assert conn.execute('PRAGMA query_only').fetchone()[0]==1
  conn.execute('BEGIN')
  assert conn.execute('SELECT id FROM users WHERE id=? AND internal_user_id=?',owner).fetchone() is not None
  row=None
  if job is not None:
   item=conn.execute('SELECT id,mode,provider,status FROM jobs WHERE id=? AND user_id=?',(job,owner[0])).fetchone()
   assert item is not None
   row=dict(zip(('id','mode','provider','status'),item))
   row['ownerSha256']=[hashlib.sha256(value.encode()).hexdigest() for value in owner]
   row['activeOwnedJobs']=conn.execute("SELECT COUNT(*) FROM jobs WHERE user_id=? AND status NOT IN ('completed','failed','cancelled')",(owner[0],)).fetchone()[0]
 finally:
  conn.rollback();conn.close()
 result=json.dumps({'receipt':provider,'job':row,'processStartTicks':ticks,'queryOnly':True},allow_nan=False).encode()
 assert len(result)<=65536
 sys.stdout.buffer.write(result)
except Exception:
 print('D3_PHONE_PRIVATE_STATE_REJECTED');raise SystemExit(1) from None
'''

SEND_SIGNAL = r'''
import os,signal,sys
try:
 assert os.geteuid()==10001 and sys.argv[2] in ('hold','release')
 with open('/proc/1/stat','rb') as source: raw=source.read(4097)
 assert len(raw)<=4096 and raw.rsplit(b')',1)[1].split()[19].decode('ascii')==sys.argv[1]
 os.kill(1,{'hold':signal.SIGUSR1,'release':signal.SIGUSR2}[sys.argv[2]])
 print('D3_PHONE_SIGNAL_SENT')
except Exception:
 print('D3_PHONE_SIGNAL_REJECTED');raise SystemExit(1) from None
'''


def marker_contract(value, source_sha, project, run_id):
    fields = {"schema", "status", "sourceSha", "project", "runId", "jobId", "clientSha256",
              "initialStatus", "reloadedStatus", "returnedStatus", "observations", "modelExecution", "acceleratorExecution"}
    require(isinstance(value, dict) and set(value) == fields
            and value["schema"] == "izo-d3-phone-active/v1" and value["status"] == "AWAITING_RELEASE"
            and value["sourceSha"] == source_sha and value["project"] == project and value["runId"] == run_id
            and isinstance(value["jobId"], str) and re.fullmatch(r"[A-Za-z0-9_-]{1,120}", value["jobId"])
            and value["clientSha256"] == hashlib.sha256(("onenode-backend-" + value["jobId"]).encode()).hexdigest()
            and all(value[key] in {"queued", "running", "processing"} for key in
                    ("initialStatus", "reloadedStatus", "returnedStatus"))
            and value["modelExecution"] is False and value["acceleratorExecution"] is False,
            "D3_PHONE_MARKER_IDENTITY_INVALID")
    observations = value["observations"]
    require(isinstance(observations, dict) and set(observations) == set(OBSERVATIONS)
            and all(type(observations[key]) is type(expected) and observations[key] == expected
                    for key, expected in OBSERVATIONS.items()), "D3_PHONE_MARKER_OBSERVATION_INVALID")
    return value


def held_job(value, marker, owner_hashes, instance, *, completed=False):
    receipt = value["receipt"]
    provider = admitted_provider(receipt)
    jobs, row = provider["jobs"], value.get("job")
    require(value.get("queryOnly") is True and receipt["instanceId"] == instance
            and isinstance(row, dict) and row.get("id") == marker["jobId"]
            and row.get("ownerSha256") == owner_hashes and row.get("mode") == "text_to_image"
            and row.get("provider") == "comfyui", "D3_PHONE_JOB_OWNER_MISMATCH")
    require(len(jobs) == 1 and type(provider.get("counts", {}).get("accepted")) is int
            and provider["counts"]["accepted"] == 1, "D3_PHONE_UNIQUE_PROVIDER_JOB_REQUIRED")
    job = jobs[0]
    require(isinstance(job, dict) and job.get("client_sha256") == marker["clientSha256"]
            and re.fullmatch(r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}", str(job.get("prompt_id")))
            and re.fullmatch(r"[a-f0-9]{64}", str(job.get("body_sha256"))) and job.get("mode") == "hold"
            and job.get("state") == ("completed" if completed else "held"), "D3_PHONE_HELD_PROVIDER_MISMATCH")
    if not completed:
        require(row.get("status") in ACTIVE and type(row.get("activeOwnedJobs")) is int
                and row["activeOwnedJobs"] == 1, "D3_PHONE_ACTIVE_OWNED_JOB_REQUIRED")
    return job


class BoundedTransport:
    """Private executor copy caps its implicit identity queries as well as exec."""
    def __init__(self, shadow, stop):
        require(isinstance(shadow.executor, IsolatedExecutor) and shadow.fixture is True,
                "D3_PHONE_ISOLATED_EXECUTOR_REQUIRED")
        self.stop, self.deadline, self.commands = stop, time.monotonic() + PREPARE_SECONDS, 0
        self.shadow = copy(shadow)
        self.shadow.files, self.shadow.env = list(shadow.files), dict(shadow.env)
        def run(args, *, capture=True, timeout=MAX_COMMAND_SECONDS):
            self.check()
            self.commands += 1
            require(self.commands <= 180 and capture is True, "D3_PHONE_COMMAND_LIMIT")
            value = shadow.run(args, capture=True, timeout=min(timeout, MAX_COMMAND_SECONDS, self.deadline - time.monotonic()))
            self.check()
            require(isinstance(value, str) and len(value.encode()) <= 1024 * 1024, "D3_PHONE_COMMAND_OUTPUT_LIMIT")
            return value
        self.shadow.run = run
        original = shadow.executor
        self.shadow.executor = IsolatedExecutor(run, context=original.context,
            engine_id=original.engine_id, machine_sha256=original.machine_sha256)

    def check(self):
        require(not self.stop.is_set(), "D3_PHONE_WATCH_STOPPED")
        require(time.monotonic() < self.deadline, "D3_PHONE_WATCH_DEADLINE")


class PhoneWatch:
    def __init__(self, shadow, images, flow, directory, run_id, *, api_identity):
        require(re.fullmatch(r"[a-f0-9]{32}", str(run_id)) and flow.project == shadow.project
                and flow.source_sha == shadow.sha, "D3_PHONE_WATCH_IDENTITY_INVALID")
        directory = Path(directory).absolute()
        require(directory == directory.resolve(), "D3_PHONE_DIRECTORY_INVALID")
        info = directory.lstat()
        require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid()
                and stat.S_IMODE(info.st_mode) == 0o700, "D3_PHONE_DIRECTORY_INVALID")
        require(not (directory / MARKER).exists(), "D3_PHONE_MARKER_ALREADY_EXISTS")
        self.directory, self.images, self.api_identity = directory, deepcopy(images), api_identity
        self.stop_event, self.lock = threading.Event(), threading.Lock()
        self.transport = BoundedTransport(shadow, self.stop_event)
        me = flow.owner.request("GET", "/api/me-v2")
        self.owner = [me.get("legacy_user_id"), me.get("internal_user_id")]
        require(isinstance(self.owner[0], str) and re.fullmatch(r"web_[a-f0-9]{32}", self.owner[0])
                and isinstance(self.owner[1], str) and re.fullmatch(r"[A-Za-z0-9_-]{1,120}", self.owner[1]),
                "D3_PHONE_OWNER_INVALID")
        self.owner_hashes = [hashlib.sha256(value.encode()).hexdigest() for value in self.owner]
        self.result = {"status": "FAIL", "sourceSha": shadow.sha, "project": shadow.project, "runId": run_id,
            "ownerSha256": self.owner_hashes, "cleanup": "PENDING", "modelExecution": False,
            "acceleratorExecution": False}
        self.thread, self.marker_inode, self.closed = None, None, False
        self.directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        actual = os.fstat(self.directory_fd)
        self.directory_inode = info.st_dev, info.st_ino
        if (actual.st_dev, actual.st_ino) != self.directory_inode:
            os.close(self.directory_fd)
            raise ProductError("D3_PHONE_DIRECTORY_CHANGED")

    def _directory_unchanged(self):
        info = self.directory.lstat()
        require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == 0o700
                and (info.st_dev, info.st_ino) == self.directory_inode, "D3_PHONE_DIRECTORY_CHANGED")

    def _save(self):
        self._directory_unchanged()
        save_private(self.directory / "phone-active-watch.json", self.snapshot())

    def snapshot(self):
        with self.lock:
            return deepcopy(self.result)

    def _update(self, **fields):
        with self.lock:
            self.result.update(fields)

    def _error(self, error):
        code = str(error)
        self._update(status="FAIL", errorCode=code if isinstance(error, ProductError)
            and re.fullmatch(r"D3_PHONE_[A-Z0-9_]{2,100}", code) else "D3_PHONE_WATCH_FAILED")

    def _same_api(self):
        shadow = self.transport.shadow
        rows = json.loads(shadow.docker("inspect", self.identity["containerId"], timeout=MAX_COMMAND_SECONDS))
        require(isinstance(rows, list) and len(rows) == 1, "D3_PHONE_API_CHANGED")
        row, expected = rows[0], self.expected
        labels, state = row["Config"]["Labels"], row["State"]
        current = {"containerId": row["Id"], "imageId": row["Image"], "hostPid": state["Pid"],
                   "startedAt": state["StartedAt"], "restartCount": row["RestartCount"]}
        environment = dict(item.split("=", 1) for item in row["Config"]["Env"])
        require(current == self.identity and state["Running"] is True and labels.get("io.izo.owner") == OWNER
                and labels.get("com.docker.compose.project") == shadow.project
                and labels.get("com.docker.compose.service") == "backend"
                and row["Config"]["User"] == expected["user"] and row["Config"]["Cmd"] == expected["command"]
                and all(environment.get(key) == value for key, value in expected["environment"].items()),
                "D3_PHONE_API_CHANGED")

    def _state(self, job_id=None):
        self._same_api()
        raw = self.transport.shadow.docker("exec", self.identity["containerId"], "python", "-c", READ_STATE,
            json.dumps([self.owner, job_id]), timeout=MAX_COMMAND_SECONDS)
        require(len(raw.encode()) <= 65536, "D3_PHONE_PRIVATE_STATE_LIMIT")
        value = json.loads(raw)
        require(isinstance(value, dict) and value.get("queryOnly") is True
                and re.fullmatch(r"[0-9]{1,24}", str(value.get("processStartTicks"))), "D3_PHONE_PRIVATE_STATE_INVALID")
        if hasattr(self, "ticks"):
            require(value["processStartTicks"] == self.ticks
                    and value["receipt"].get("instanceId") == self.instance, "D3_PHONE_API_CHANGED")
        return value

    def _signal(self, action):
        self.transport.check()
        self._same_api()
        require(action in {"hold", "release"}, "D3_PHONE_SIGNAL_INVALID")
        output = self.transport.shadow.docker("exec", self.identity["containerId"], "python", "-c", SEND_SIGNAL,
            self.ticks, action, timeout=MAX_COMMAND_SECONDS)
        require(output == "D3_PHONE_SIGNAL_SENT", "D3_PHONE_SIGNAL_INVALID")

    def _ack(self, action, sequence, job_id=None):
        outer = self.transport.deadline
        self.transport.deadline = min(outer, time.monotonic() + ACK_SECONDS)
        try:
            while True:
                value = self._state(job_id)
                control = value["receipt"].get("control", {})
                require(type(control.get("sequence")) is int and control["sequence"] in {sequence - 1, sequence},
                        "D3_PHONE_CONTROL_CHANGED")
                if control["sequence"] == sequence:
                    require(control.get("action") == action and control.get("status") == "ACK",
                            "D3_PHONE_CONTROL_REJECTED")
                    return value
                self.stop_event.wait(.1)
                self.transport.check()
        finally:
            self.transport.deadline = outer

    def start(self):
        require(threading.current_thread() is threading.main_thread() and self.thread is None and not self.closed,
                "D3_PHONE_WATCH_START_INVALID")
        try:
            shadow = self.transport.shadow
            shadow.source_guard()
            self.expected = deepcopy(shadow.config()["services"]["backend"])
            require(self.expected["environment"].get("IZO_SHADOW_FIXTURE") == "controlled-chat-video-v1"
                    and self.expected["environment"].get("IZO_PROCESS_ROLE") == "server"
                    and self.expected["command"] == ["python", "/opt/izo/fixtures/docker_shadow_fixture.py"],
                    "D3_PHONE_PROFILE_INVALID")
            self.identity = self.api_identity(shadow, self.images, self.expected)
            baseline = self._state()
            provider = admitted_provider(baseline["receipt"])
            control = baseline["receipt"].get("control", {})
            require(not provider["jobs"] and not provider["d3"]["chat"] and provider["d3"]["video"] is None
                    and control == {"sequence": 0, "action": None, "status": "IDLE"}, "D3_PHONE_FRESH_PROVIDER_REQUIRED")
            self.instance, self.ticks = baseline["receipt"]["instanceId"], baseline["processStartTicks"]
            self.started = time.monotonic()
            self.transport.deadline = self.started + HOLD_SECONDS
            self._signal("hold")
            held = self._ack("hold", 1)
            require(not admitted_provider(held["receipt"])["jobs"], "D3_PHONE_EARLY_SUBMIT")
            self._update(holdAck={"sequence": 1, "action": "hold", "status": "ACK"},
                         apiIdentity=self.identity, providerInstanceId=self.instance, phase="AWAITING_MARKER")
            self._save()
            self.thread = threading.Thread(target=self._observe, name="izo-d3-phone-watch", daemon=True)
            self.thread.start()
        except BaseException as error:
            self._error(error)
            raise
        return self

    def _marker(self):
        self.transport.check()
        self._directory_unchanged()
        try:
            descriptor = os.open(MARKER, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=self.directory_fd)
        except FileNotFoundError:
            return None
        with os.fdopen(descriptor, "rb") as source:
            info = os.fstat(source.fileno())
            require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid() and info.st_nlink == 1
                    and stat.S_IMODE(info.st_mode) == 0o600 and 0 <= info.st_size < 4096,
                    "D3_PHONE_MARKER_FILE_INVALID")
            inode = info.st_dev, info.st_ino
            require(self.marker_inode in {None, inode}, "D3_PHONE_MARKER_REPLACED")
            self.marker_inode = inode
            raw = source.read(4096)
            require(len(raw) < 4096, "D3_PHONE_MARKER_FILE_INVALID")
        if not raw.endswith(b"\n"):
            return None
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return marker_contract(value, self.result["sourceSha"], self.result["project"], self.result["runId"]), hashlib.sha256(raw).hexdigest()

    def _observe(self):
        try:
            marker = None
            while marker is None:
                marker = self._marker()
                if marker is None:
                    self.stop_event.wait(.1)
            value, digest = marker
            self.transport.shadow.source_guard()
            before = self._state(value["jobId"])
            job = held_job(before, value, self.owner_hashes, self.instance)
            require(before["receipt"].get("control") == {"sequence": 1, "action": "hold", "status": "ACK"}
                    and self._marker() == marker, "D3_PHONE_MARKER_OR_CONTROL_CHANGED")
            self._update(phase="RELEASING", jobId=value["jobId"], clientSha256=value["clientSha256"], markerSha256=digest)
            self._signal("release")
            after = self._ack("release", 2, value["jobId"])
            released = held_job(after, value, self.owner_hashes, self.instance, completed=True)
            require(released["prompt_id"] == job["prompt_id"] and released["body_sha256"] == job["body_sha256"],
                    "D3_PHONE_RELEASED_JOB_CHANGED")
            self.transport.check()
            self._update(status="PASS", phase="RELEASED", releaseAck={"sequence": 2, "action": "release", "status": "ACK"},
                promptId=job["prompt_id"], releaseSeconds=round(time.monotonic() - self.started, 3),
                fullJobOwnerVerified=True, wasHeld=True, newGenerationRequests=0)
        except BaseException as error:
            self._error(error)
        finally:
            try:
                self._save()
            except Exception:
                self._update(status="FAIL", errorCode="D3_PHONE_CHECKPOINT_FAILED")

    def close(self):
        if self.closed:
            return self.snapshot()
        self.stop_event.set()
        if self.thread is not None and self.thread.ident is not None:
            self.thread.join(JOIN_SECONDS)
        alive = self.thread is not None and self.thread.is_alive()
        self._update(cleanup="FAIL" if alive else "PASS", threadAlive=bool(alive), commands=self.transport.commands)
        if alive:
            self._update(status="FAIL", errorCode="D3_PHONE_WATCH_JOIN_FAILED")
        else:
            os.close(self.directory_fd)
        self.closed = True
        try:
            self._save()
        except Exception:
            self._update(status="FAIL", errorCode="D3_PHONE_CHECKPOINT_FAILED")
        return self.snapshot()
