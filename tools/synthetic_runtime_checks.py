"""Read-only resource proofs and bounded synthetic HTTP checks for one reviewed TEST run."""
from __future__ import annotations

import hashlib
import base64
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import sys
import time
import types
import uuid


class CheckFailure(RuntimeError):
    pass


def require(value, code):
    if not value:
        raise CheckFailure(code)


def digest(path, *, canonical=False):
    if canonical:
        return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def encoded(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=True, indent=2) + "\n").encode()


def fingerprint(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def plain(path):
    path = Path(path)
    require(path.is_absolute() and ".." not in path.parts and "$" not in str(path), "UNSAFE_PATH")
    require(not any(p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction())
                    for p in (path, *path.parents)), "LINKED_PATH")
    return path


def read_json(path):
    path = plain(path)
    require(path.is_file() and path.stat().st_size <= 4 * 1024**2, "JSON_INPUT_INVALID")
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    require(type(value) is dict, "JSON_OBJECT_REQUIRED")
    return value


def support(plan):
    require("tools" not in sys.modules and "docker_test_bundle_format" not in sys.modules,
            "UNEXPECTED_SUPPORT_MODULE")
    folder = plain(plan["support"]["toolingRoot"])
    modules = {}
    for name, pin in plan["support"]["moduleHashes"].items():
        path = plain(folder / "tools" / (name + ".py"))
        require(digest(path, canonical=True) == pin, "SUPPORT_HASH_MISMATCH")
    package = types.ModuleType("tools"); package.__path__ = []; sys.modules["tools"] = package
    for name in ("docker_test_bundle_format", "docker_test_bundle_runtime"):
        spec = importlib.util.spec_from_file_location(name, folder / "tools" / (name + ".py"))
        module = importlib.util.module_from_spec(spec); sys.modules[name] = module
        spec.loader.exec_module(module); modules[name] = module
    path = plain(plan["support"]["httpClientPath"])
    require(digest(path, canonical=True) == plan["support"]["httpClientSha256"], "HTTP_CLIENT_HASH_MISMATCH")
    spec = importlib.util.spec_from_file_location("pinned_synthetic_http", path)
    http = importlib.util.module_from_spec(spec); spec.loader.exec_module(http)
    runtime = modules["docker_test_bundle_runtime"]
    require(runtime.verify.__module__ == "docker_test_bundle_format", "SUPPORT_IMPORT_MISMATCH")
    return modules["docker_test_bundle_format"], runtime, http


PRIVATE_ACL = r'''$ErrorActionPreference='Stop'
$p=$env:IZO_QA_PRIVATE_DIRECTORY
$sid=[Security.Principal.WindowsIdentity]::GetCurrent().User
$allowed=@($sid.Value,'S-1-5-18','S-1-5-32-544') | Select-Object -Unique
if($env:IZO_QA_SET_PRIVATE_ACL -eq '1') {
 $acl=[Security.AccessControl.DirectorySecurity]::new()
 $acl.SetOwner($sid); $acl.SetAccessRuleProtection($true,$false)
 foreach($id in $allowed) {
  $rule=[Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new($id),'FullControl','ContainerInherit,ObjectInherit','None','Allow')
  $acl.AddAccessRule($rule)
 }
 Set-Acl -LiteralPath $p -AclObject $acl
}
foreach($item in @($p,(Join-Path $p 'credentials.json'))) {
 if(!(Test-Path -LiteralPath $item)){continue}
 $a=Get-Acl -LiteralPath $item
 $owner=$a.GetOwner([Security.Principal.SecurityIdentifier]).Value
 if(($item -eq $p -and $owner -ne $sid.Value) -or ($item -ne $p -and $owner -notin $allowed)){throw 'Owner'}
 if($item -eq $p -and !$a.AreAccessRulesProtected){throw 'Inheritance'}
 $rules=@($a.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier]))
 if($rules.Count -ne $allowed.Count){throw 'RuleCount'}
 foreach($rule in $rules) {
  if($rule.IdentityReference.Value -notin $allowed -or $rule.AccessControlType -ne 'Allow' -or $rule.FileSystemRights -ne 'FullControl'){throw 'Rule'}
 }
 if(@($rules.IdentityReference.Value | Select-Object -Unique).Count -ne $allowed.Count){throw 'Sids'}
}
Write-Output 'PRIVATE_DIRECTORY_ACL_VERIFIED'
'''


def credential_shape(accounts):
    require(len(accounts) == 2 and [a.get("role") for a in accounts] == ["owner", "other"]
            and all(set(a) == {"role", "legacyUserId", "internalUserId", "email", "password"}
                    and all(type(v) is str and v for v in a.values()) and a["email"].endswith("@example.invalid")
                    for a in accounts), "SYNTHETIC_CREDENTIAL_SHAPE_INVALID")
    require(all(len({a[key] for a in accounts}) == 2 for key in ("legacyUserId", "internalUserId", "email")),
            "DISTINCT_SYNTHETIC_USERS_REQUIRED")


def credential_permissions(folder, environment, *, create=False):
    folder = plain(folder)
    require(folder.is_dir(), "PRIVATE_DIRECTORY_MISSING")
    if os.name == "nt":
        executable = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        env = {**environment, "IZO_QA_PRIVATE_DIRECTORY": str(folder), "IZO_QA_SET_PRIVATE_ACL": "1" if create else "0"}
        command = base64.b64encode(PRIVATE_ACL.encode("utf-16le")).decode("ascii")
        result = subprocess.run([str(executable), "-NoProfile", "-NonInteractive", "-EncodedCommand", command],
                                env=env, capture_output=True, timeout=30, check=False)
        require(result.returncode == 0 and result.stdout.strip() == b"PRIVATE_DIRECTORY_ACL_VERIFIED", "PRIVATE_ACL_NOT_VERIFIED")
    else:
        if create: folder.chmod(0o700)
        for path, mode in ((folder, 0o700), (folder / "credentials.json", 0o600)):
            if path.exists():
                value = plain(path).lstat()
                require(value.st_uid == os.getuid() and stat.S_IMODE(value.st_mode) == mode, "PRIVATE_MODE_NOT_VERIFIED")


def load_private_credentials(root, project, pin, environment):
    folder = plain(root / "private"); path = plain(folder / "credentials.json")
    credential_permissions(folder, environment)
    require(digest(path) == pin, "PRIVATE_ARTIFACT_CHANGED")
    value = read_json(path)
    require(set(value) == {"version", "purpose", "project", "accounts"} and type(value["version"]) is int
            and value["version"] == 1 and value["purpose"] == "synthetic-qa-only" and value["project"] == project,
            "PRIVATE_ARTIFACT_SCOPE_INVALID")
    credential_shape(value["accounts"])
    return value["accounts"]


def private_credentials(root, project, accounts, environment):
    credential_shape(accounts)
    folder = plain(root / "private")
    require(not folder.exists(), "PRIVATE_DIRECTORY_EXISTS")
    folder.mkdir(mode=0o700)
    credential_permissions(folder, environment, create=True)  # Restrict NEW directory before any credential byte.
    path = folder / "credentials.json"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        if os.name != "nt": os.fchmod(stream.fileno(), 0o600)
        stream.write(encoded({"version": 1, "purpose": "synthetic-qa-only", "project": project, "accounts": accounts}))
        stream.flush(); os.fsync(stream.fileno())
    credential_permissions(folder, environment)
    return {"path": "private/credentials.json", "sha256": digest(path), "accounts": 2, "cookiesStored": False,
            "permissionsVerified": True, "publicUploadAllowed": False}


PROJECTION = ('{"Id":{{json .Id}},"Name":{{json .Name}},"Image":{{json .Image}},'
    '"State":{"Running":{{json .State.Running}},"StartedAt":{{json .State.StartedAt}},'
    '"ExitCode":{{json .State.ExitCode}},"OOMKilled":{{json .State.OOMKilled}}},'
    '"RestartCount":{{json .RestartCount}},"VolumeNames":['
    '{{range $i,$m := .Mounts}}{{if $i}},{{end}}{{if eq $m.Type "volume"}}{{json $m.Name}}{{else}}null{{end}}{{end}}]}')


def inventory(docker):
    ids = docker.run("ps", "-aq", "--no-trunc").split()
    rows = [json.loads(line) for line in docker.run("inspect", "--format", PROJECTION, *ids).splitlines()] if ids else []
    result = {"containers": {c["Id"]: c for c in rows}, "volumes": {}, "networks": {}}
    for kind in ("volume", "network"):
        template = ('{"Name":{{json .Name}},"Driver":{{json .Driver}},"Scope":{{json .Scope}},'
                    + ('"CreatedAt":{{json .CreatedAt}}}' if kind == "volume" else '"Id":{{json .Id}}}'))
        names = docker.run(kind, "ls", "--format", "{{.Name}}").splitlines()
        values = [json.loads(line) for line in docker.run(kind, "inspect", "--format", template, *names).splitlines()] if names else []
        result[kind + "s"] = {v["Name"]: v for v in values}
    return result


def foreign_unchanged(current, baseline, own):
    for kind, prior in baseline.items():
        require(all(current[kind].get(key) == value for key, value in prior.items()), "FOREIGN_RESOURCE_CHANGED")
        require(set(current[kind]) - set(prior) <= set(own[kind]), "UNEXPECTED_NEW_RESOURCE")


def volume_metadata(resources):
    return {v["Name"]: {key: v.get(key) for key in ("Name", "CreatedAt", "Driver", "Scope", "Labels", "Options")}
            for v in resources["volumes"]}


def topology(runtime, docker, release, manifest, *, check_health=True):
    if check_health:
        runtime.health(docker, release, manifest)
    resources = runtime.owned_resources(docker, manifest)
    require(len(resources["containers"]) == 3, "SERVICE_COUNT_CHANGED")
    roles = {c["Config"]["Labels"].get("com.docker.compose.service"): c for c in resources["containers"]}
    require(set(roles) == {"backend", "web", "guard"}, "SERVICE_SET_CHANGED")
    require(roles["backend"]["Config"]["Cmd"] == runtime.UVICORN
            and not roles["backend"]["Config"].get("Entrypoint"), "ORDINARY_UVICORN_REQUIRED")
    config = json.loads((release / "compose.json").read_text(encoding="utf-8"))
    netns = {}
    for role, row in roles.items():
        require(row["Image"] == manifest["images"][role] and row["State"]["Running"]
                and not row["State"].get("OOMKilled") and row["RestartCount"] == 0
                and row["HostConfig"]["RestartPolicy"]["Name"] == "no", "RUNTIME_PROCESS_IDENTITY_CHANGED")
        image = json.loads(docker.run("image", "inspect", "--format", "{{json .Config}}", row["Image"]))
        expected = dict(item.split("=", 1) for item in image.get("Env", []))
        expected.update({k: str(v) for k, v in config["services"][role].get("environment", {}).items()})
        actual = dict(item.split("=", 1) for item in row["Config"]["Env"])
        require(actual == expected, "RUNTIME_ENVIRONMENT_CHANGED")
        require(actual.get("GALLERY_FULL_QUALITY_COUNT", "10") == "10", "MEDIA_QUALITY_WINDOW_CHANGED")
        value = docker.run("exec", row["Id"], "readlink", "/proc/self/ns/net")
        require(re.fullmatch(r"net:\[[0-9]+\]", value) is not None, "NETWORK_NAMESPACE_UNAVAILABLE")
        netns[role] = value
    require(len(set(netns.values())) == 1 and all(roles[role]["HostConfig"]["NetworkMode"]
            == "container:" + roles["guard"]["Id"] for role in ("backend", "web")), "NETWORK_NAMESPACE_MISMATCH")
    require(roles["guard"]["HostConfig"]["PortBindings"] == {
        "8000/tcp": [{"HostIp": "127.0.0.1", "HostPort": str(manifest["ports"]["api"])}],
        "8080/tcp": [{"HostIp": "127.0.0.1", "HostPort": str(manifest["ports"]["web"])}]}, "LOOPBACK_PORTS_CHANGED")
    for role in ("backend", "web"):
        require(not roles[role]["HostConfig"]["PortBindings"], "UNEXPECTED_SERVICE_PORT")
    require(len(resources["networks"]) == 1 and set(resources["networks"][0].get("Containers", {}))
            <= {c["Id"] for c in roles.values()}, "FOREIGN_NETWORK_CONSUMER")
    return {"containers": {role: {"id": c["Id"], "startedAt": c["State"]["StartedAt"],
            "image": c["Image"], "restartCount": c["RestartCount"]} for role, c in roles.items()},
            "netns": netns, "volumes": volume_metadata(resources)}


DB_PROBE = r'''import hashlib,json,sqlite3,sys
expected=json.loads(sys.argv[1]); c=sqlite3.connect('file:/home/izo/data/app.sqlite3?mode=ro',uri=True)
c.row_factory=sqlite3.Row; c.execute('PRAGMA query_only=ON'); c.execute('BEGIN')
assert c.execute('PRAGMA user_version').fetchone()[0]==7
assert c.execute('PRAGMA quick_check').fetchone()[0]=='ok'
assert c.execute('PRAGMA foreign_key_check').fetchone() is None
assert c.execute("SELECT count(*) FROM jobs WHERE status NOT IN ('completed','failed','cancelled') OR status IS NULL").fetchone()[0]==0
assert c.execute('SELECT count(*) FROM video_file_deletions').fetchone()[0]==0
assert c.execute("SELECT count(*) FROM feed_publications WHERE media_type='video' AND status='preparing'").fetchone()[0]==0
rows=[dict(r) for r in c.execute('SELECT * FROM token_ledger')]; charges={}
for job in expected:
 found=[r for r in rows if json.loads(r['meta_json'] or '{}').get('jobId')==job['id']]
 assert len(found)==1
 row=found[0]; meta=json.loads(row['meta_json']); cost=job['cost']
 assert row['user_id']==job['user'] and row['reason'] in ('generation','daily_generation')
 assert meta['token_cost']==cost and meta['daily_part']+meta['balance_part']==cost
 assert row['delta']==-meta['balance_part'] and meta['balance_delta']==row['delta']
 charges[job['id']]={'rows':1,'cost':cost,'daily':meta['daily_part'],'main':meta['balance_part'],'delta':row['delta']}
tables={}
for name in ('images','jobs','token_ledger'):
 values=[dict(r) for r in c.execute('SELECT * FROM "'+name+'" ORDER BY rowid')]
 data=json.dumps(values,sort_keys=True,ensure_ascii=True,default=lambda x:{'bytes':x.hex()},separators=(',',':')).encode()
 tables[name]={'count':len(values),'sha256':hashlib.sha256(data).hexdigest()}
c.close();print(json.dumps({'schema':7,'idle':True,'charges':charges,'protectedTables':tables},sort_keys=True))
'''


def database(docker, backend, jobs):
    return json.loads(docker.run("exec", backend, "python", "-c", DB_PROBE,
                                json.dumps(jobs, separators=(",", ":")), timeout=60))


class Product:
    def __init__(self, http, origin):
        self.http, self.origin = http, origin
        self.clients = [http.HttpClient(origin) for _ in range(3)]
        self.owner, self.other, self.guest = self.clients
        self.images, self.jobs, self.requests, self.credentials = [], [], [], []
        self.saved = None

    def register_and_login(self):
        for index in (0, 1):
            signup = self.http.HttpClient(self.origin)
            email, password = "runtime-" + uuid.uuid4().hex + "@example.invalid", secrets.token_urlsafe(32)
            value = signup.request("POST", "/api/auth/password/register-v2", {"email": email, "password": password,
                "password_repeat": password, "accepted_terms": True, "accepted_privacy": True,
                "accepted_personal_data": True, "platform": "web_desktop"})
            require(value.get("ok") is True and value.get("requires_email_verification") is False, "SIGNUP_FAILED")
            signup.cookies.clear()
            client = self.clients[index]
            login = client.request("POST", "/api/auth/password/login-v2", {"email": email, "password": password})
            require(login.get("ok") is True, "PASSWORD_LOGIN_FAILED")
            me = client.request("GET", "/api/me-v2")
            require(me.get("legacy_user_id") == value.get("legacy_user_id"), "LOGIN_IDENTITY_MISMATCH")
            self.credentials.append({"role": "owner" if index == 0 else "other", "legacyUserId": me["legacy_user_id"],
                                     "internalUserId": me["internal_user_id"], "email": email, "password": password})
            email = password = ""
        require(all(len({a[key] for a in self.credentials}) == 2 for key in ("legacyUserId", "internalUserId", "email")),
                "DISTINCT_SYNTHETIC_USERS_REQUIRED")
        self.guest.request("GET", "/api/me-v2", expected=(401,))
        tariffs = self.owner.request("GET", "/api/tariffs")["tariffs"]
        me = self.owner.request("GET", "/api/me-v2"); account = me["account"]
        require(account.get("plan") == "mini", "FRESH_MINI_TARIFF_REQUIRED")
        mini = tariffs["mini"]
        require(int(mini["gallery_slots"]) == account["gallery_slots"] and account["gallery_free"] >= 9
                and account["token_balance"] + account["daily_tokens_remaining"] >= 9, "SYNTHETIC_BUDGET_INSUFFICIENT")
        return {"users": 2, "passwordLogin": "PASS", "guestSessionDenied": True, "plannedJobs": 9}

    def post_job(self, payload, key):
        previous = self.owner.opener.addheaders
        self.owner.opener.addheaders = [*previous, ("Idempotency-Key", key)]
        try:
            return self.owner.request("POST", "/api/generate", payload)
        finally:
            self.owner.opener.addheaders = previous

    def generate(self, *, mode="text_to_image"):
        before = self.owner.request("GET", "/api/account/token-history-v2")
        payload = {"mode": mode, "provider": "comfyui", "prompt": "A blue ceramic cup on a plain table",
                   "width": 704, "height": 704, "steps": 4, "seed": 18731 + len(self.jobs)}
        if mode == "image_to_image": payload["inputImage1"] = self.images[0]
        key = "runtime-" + uuid.uuid4().hex
        accepted = self.post_job(payload, key)
        identity = self.http.path_id(accepted.get("id"))
        require(accepted.get("status") == "queued" and type(accepted.get("tokenCost")) is int
                and accepted["tokenCost"] == 1, "GENERATION_ADMISSION_CHANGED")
        require(self.post_job(payload, key) == accepted, "IDEMPOTENT_ACCEPTANCE_CHANGED")
        self.other.request("GET", "/api/jobs/" + identity, expected=(404,))
        deadline = time.monotonic() + 75
        while True:
            job = self.owner.request("GET", "/api/jobs/" + identity)
            require(job.get("status") in {"queued", "running", "uploading", "sent_to_comfyui", "completed"}, "GENERATION_FAILED")
            if job["status"] == "completed": break
            require(time.monotonic() < deadline, "GENERATION_TIMEOUT")
            time.sleep(.2)
        image = self.owner.request("GET", "/api/gallery/" + self.http.path_id(job["resultImageId"]))
        require(image["url"] == job["resultUrl"], "RESULT_PROVENANCE_CHANGED")
        require(identity not in {x["id"] for x in self.jobs} and image["id"] == job["resultImageId"]
                and image["id"] not in {x["image"] for x in self.jobs}, "GENERATION_IDENTITY_REUSED")
        self.images.append(image["url"])
        self.jobs.append({"id": identity, "cost": accepted["tokenCost"], "user": accepted["userId"], "image": image["id"]})
        self.requests.append((payload, key, accepted))
        after = self.owner.request("GET", "/api/account/token-history-v2")
        added = [row for row in after["items"] if row["id"] not in {x["id"] for x in before["items"]}]
        require(after["summary"]["spentTokens"] - before["summary"]["spentTokens"] == 1
                and after["summary"]["refundedTokens"] == before["summary"]["refundedTokens"]
                and len(added) == 1 and added[0]["spentTokens"] == 1, "GENERATION_LEDGER_CHANGED")
        me = self.owner.request("GET", "/api/me-v2")
        require(me["account"]["token_balance"] == accepted["tokenBalance"]
                and me["account"]["daily_tokens_used"] == accepted["dailyTokensUsed"], "GENERATION_BALANCE_CHANGED")
        return {"jobId": identity, "cost": 1, "idempotentReplay": "PASS", "realModelExecution": False}

    def snapshot(self):
        accounts = []
        for client in (self.owner, self.other):
            me = client.request("GET", "/api/me-v2")
            identity = {k: me.get(k) for k in ("legacy_user_id", "internal_user_id")}
            identity.update({k: me.get("session", {}).get(k) for k in ("session_id", "provider", "platform")})
            require(all(type(v) is str and v for v in identity.values()), "SESSION_IDENTITY_INVALID")
            ledger = client.request("GET", "/api/account/token-history-v2?days=365&limit=200")
            summary = {k: ledger["summary"][k] for k in ("spentTokens", "balanceSpentTokens", "includedSpentTokens", "refundedTokens", "balance")}
            fields = ("id", "jobId", "delta", "spentTokens", "reason", "provider", "mode", "model", "createdAt")
            entries = sorted(({k: row.get(k) for k in fields} for row in ledger["items"]), key=lambda x: x["id"])
            require(len(entries) < 200, "LEDGER_TRUNCATED")
            accounts.append({"identity": identity, "account": {k: me["account"][k] for k in
                             ("token_balance", "daily_tokens_used", "gallery_used", "gallery_free", "gallery_slots")},
                             "ledger": {"summary": summary, "items": entries}})
        images = []
        for job in self.jobs:
            image = self.owner.request("GET", "/api/gallery/" + job["image"])
            self.other.request("GET", "/api/gallery/" + job["image"], expected=(404,))
            media = {}
            for path in {image["url"], image.get("thumbnailUrl") or image["url"]}:
                require(path.startswith("/api/media/"), "PRIVATE_MEDIA_PATH_CHANGED")
                blob = self.owner.request("GET", path, binary=True)
                require(blob.startswith((b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff"))
                        or (blob[:4] == b"RIFF" and blob[8:12] == b"WEBP"), "MEDIA_NOT_IMAGE")
                media[path] = hashlib.sha256(blob).hexdigest()
                self.other.request("GET", path, expected=(403, 404))
                self.guest.request("GET", path, expected=(401, 403, 404))
            status = self.owner.request("GET", "/api/jobs/" + job["id"])
            require(status["status"] == "completed" and status["resultImageId"] == job["image"], "PERSISTENT_JOB_CHANGED")
            images.append({"id": image["id"], "favorite": image["isFavorite"], "media": media})
        return {"accounts": accounts, "images": images, "jobs": self.jobs.copy()}

    def replay_and_compare(self):
        require(self.snapshot() == self.saved, "PRODUCT_PERSISTENCE_CHANGED")
        payload, key, accepted = self.requests[0]
        require(self.post_job(payload, key) == accepted, "PERSISTENT_IDEMPOTENCY_CHANGED")
        require(self.snapshot() == self.saved, "REPLAY_CHANGED_PRODUCT")
        return {"snapshotSha256": fingerprint(self.saved), "sessionPreserved": True, "replayNoCharge": True}

    def close(self):
        for client in self.clients: client.cookies.clear()
        self.requests.clear()
        self.credentials.clear()
