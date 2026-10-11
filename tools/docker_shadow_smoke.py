"""Bounded topology proof, not full product parity or production acceptance."""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

from tools.agent_system.env_runtime import EMPTY_CREDENTIAL_KEYS


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def check(condition: bool, code: str) -> None:
    if not condition:
        raise RuntimeError(code)


def inspect_stack(shadow) -> dict:
    shadow.ownership_guard()
    containers = shadow.containers()
    check(len(containers) == 2, "SHADOW_CONTAINER_COUNT")
    rows = {}
    for container in containers:
        service = container["Config"]["Labels"]["com.docker.compose.service"]
        check(container["State"]["Running"], "SHADOW_CONTAINER_STOPPED")
        check(container["State"].get("Health", {}).get("Status") == "healthy", "SHADOW_NOT_READY")
        image = json.loads(shadow.docker("image", "inspect", container["Image"]))[0]
        check(image["Config"]["Labels"]["org.opencontainers.image.revision"] == shadow.sha,
              "SHADOW_IMAGE_SOURCE_MISMATCH")
        networks = container["NetworkSettings"]["Networks"]
        check(list(networks) == [f"{shadow.project}_shadow"], "SHADOW_EXTRA_NETWORK")
        network = json.loads(shadow.docker("network", "inspect", next(iter(networks))))[0]
        check(network["Internal"], "SHADOW_NETWORK_NOT_INTERNAL")
        bindings = container["HostConfig"]["PortBindings"]
        check(len(bindings) == 1 and all(p["HostIp"] == "127.0.0.1"
              for ports in bindings.values() for p in ports), "SHADOW_PUBLIC_BINDING")
        check(container["Config"]["User"] not in ("", "root", "0", "0:0"), "SHADOW_ROOT_USER")
        check(container["HostConfig"]["CapDrop"] == ["ALL"], "SHADOW_CAPABILITIES")
        check(not container["HostConfig"]["Privileged"], "SHADOW_PRIVILEGED")
        mounts = container["Mounts"]
        check(all(m["Type"] in {"volume", "tmpfs"} for m in mounts), "SHADOW_HOST_MOUNT")
        if service == "backend":
            env = dict(item.split("=", 1) for item in container["Config"]["Env"])
            check(all(env.get(k) == "" for k in EMPTY_CREDENTIAL_KEYS), "SHADOW_CREDENTIAL_PRESENT")
            check(env["DATABASE_URL"] == "/home/izo/data/app.sqlite3"
                  and env["MEDIA_DIR"] == "/home/izo/media", "SHADOW_STORAGE_PATH")
            check(env["BOT_MODE"] == env["MAX_UPDATES_MODE"] == "disabled", "SHADOW_BOT_ENABLED")
            check(all(env[k] == "http://127.0.0.1:1" for k in
                      ("COMFYUI_BASE_URL", "OLLAMA_BASE_URL", "QWEN_ASR_BASE_URL",
                       "LOCAL_LTX_COMFYUI_BASE_URL", "OPENROUTER_BASE_URL")), "SHADOW_PROVIDER_ENABLED")
            check({m["Destination"] for m in mounts} == {"/home/izo/data", "/home/izo/media"},
                  "SHADOW_VOLUME_BOUNDARY")
        rows[service] = {"container": container["Id"], "image": container["Image"],
                         "sourceSha": shadow.sha, "ports": bindings,
                         "volumes": [{"name": m["Name"], "target": m["Destination"]}
                                     for m in mounts if m["Type"] == "volume"]}
    return rows


def http_proof(shadow) -> dict:
    base = f"http://127.0.0.1:{shadow.web_port}"
    routes = {}
    for path in ("/", "/feed", "/gallery", "/api/health", "/api/version"):
        with urlopen(base + path, timeout=8) as response:
            body = response.read().decode("utf-8")
            check(response.status == 200, "SHADOW_HTTP_STATUS")
        routes[path] = 200
        if path == "/":
            check(f'content="{shadow.sha}"' in body, "SHADOW_FRONTEND_SOURCE_MISMATCH")
            assets = re.findall(r'(?:src|href)="(/assets/[^"\s]+)"', body)
            check(bool(assets), "SHADOW_FRONTEND_ASSETS_MISSING")
            for asset in assets:
                with urlopen(base + asset, timeout=8) as response:
                    check(response.status == 200 and bool(response.read(32)), "SHADOW_ASSET_FAILED")
        elif path == "/api/health":
            check(json.loads(body)["ok"] is True, "SHADOW_API_HEALTH_FAILED")
    with urlopen(f"http://127.0.0.1:{shadow.api_port}/api/health", timeout=8) as response:
        check(json.load(response)["ok"] is True, "SHADOW_DIRECT_API_FAILED")
    return routes


def exec_json(shadow, container: str, script: str) -> dict:
    return json.loads(shadow.docker("exec", container, "python", "-c", script))


def fixture(shadow, container: str, marker: str, *, create: bool) -> dict:
    # Dedicated fixture DB proves volume semantics without becoming a second
    # application DB writer. The application DB is opened read-only for integrity.
    script = """
import hashlib,json,sqlite3
from pathlib import Path
marker = MARKER
path = Path('/home/izo/media/_shadow_topology_probe.txt')
probe = sqlite3.connect('/home/izo/data/shadow-topology-probe.sqlite3')
if CREATE:
    probe.execute('CREATE TABLE IF NOT EXISTS probe (id TEXT PRIMARY KEY)')
    probe.execute('INSERT INTO probe VALUES (?)', (marker,))
    probe.commit()
    path.write_text(marker)
found = probe.execute('SELECT id FROM probe WHERE id=?', (marker,)).fetchone()
probe.close()
with sqlite3.connect('file:/home/izo/data/app.sqlite3?mode=ro', uri=True) as app:
    integrity = app.execute('PRAGMA integrity_check').fetchone()[0]
    tables = {row[0] for row in app.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    counts = {t:app.execute('SELECT count(*) FROM '+t).fetchone()[0]
              for t in ('users','jobs','images') if t in tables}
print(json.dumps({'fixtureRow':found[0] if found else None,
                  'mediaHash':hashlib.sha256(path.read_bytes()).hexdigest(),
                  'applicationIntegrity':integrity,'applicationCounts':counts}))
""".replace("MARKER", repr(marker)).replace("CREATE", repr(create))
    state = exec_json(shadow, container, script)
    check(state["fixtureRow"] == marker and state["mediaHash"] == hashlib.sha256(marker.encode()).hexdigest(),
          "SHADOW_PERSISTENCE_FAILED")
    check(state["applicationIntegrity"] == "ok", "SHADOW_SQLITE_INTEGRITY_FAILED")
    return state


def egress_proof(shadow, container: str) -> dict:
    script = """
import json,socket
result = {}
for host,port in [('host.docker.internal',8000),('host.docker.internal',5173),('1.1.1.1',443)]:
    try:
        with socket.create_connection((host,port),timeout=1):
            result[host+':'+str(port)] = 'REACHABLE'
    except OSError:
        result[host+':'+str(port)] = 'UNREACHABLE'
print(json.dumps(result))
"""
    results = exec_json(shadow, container, script)
    check(all(value == "UNREACHABLE" for value in results.values()), "SHADOW_EGRESS_NOT_ISOLATED")
    return results


def prove(shadow, receipt: Path) -> None:
    result = {"contract": "SHADOW-TOPOLOGY-01", "repository": "spikeal8-maker/IZO_ASA",
              "sourceSha": shadow.sha, "project": shadow.project, "startedAt": now(),
              "status": "FAIL", "cycles": [],
              "limitations": ["Topology smoke only; Issue 125 product parity/recovery remains unaccepted.",
                              "Provider calls disabled; model output and real-provider behavior not verified.",
                              "Fixture DB/media persistence and read-only app integrity, not user-flow persistence.",
                              "Backend remains the accepted unmanaged DEV runtime; image labels bind its source."]}
    try:
        shadow.source_guard()
        config = shadow.config()
        result["configSha256"] = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
        result["containersBefore"] = inspect_stack(shadow)
        result["http"] = http_proof(shadow)
        backend = result["containersBefore"]["backend"]["container"]
        result["egress"] = egress_proof(shadow, backend)
        marker = "shadow-" + uuid.uuid4().hex
        before = fixture(shadow, backend, marker, create=True)
        result["persistenceBefore"] = before
        for cycle in range(2):
            # A real down/up proves named volumes survive removal, not only restart.
            shadow.ownership_guard()
            shadow.compose("down", capture=False)
            shadow.up(build=True)
            current = inspect_stack(shadow)
            state = fixture(shadow, current["backend"]["container"], marker, create=False)
            check(state == before, "SHADOW_APPLICATION_COUNTS_CHANGED")
            result["cycles"].append({"cycle": cycle + 1, "status": "PASS", "state": state,
                                      "containers": current, "http": http_proof(shadow)})
        result["resources"] = shadow.docker("stats", "--no-stream", "--format", "{{json .}}",
                                               *[row["container"] for row in current.values()])
        result["cleanup"] = "Shadow left running for owner inspection; named fixture volumes retained."
        result["status"] = "PASS"
    except Exception as exc:
        result["error"] = type(exc).__name__ + ": " + str(exc)
        raise
    finally:
        result["finishedAt"] = now()
        receipt.parent.mkdir(parents=True, exist_ok=True)
        receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"SHADOW_RECEIPT status={result['status']} path={receipt}")
