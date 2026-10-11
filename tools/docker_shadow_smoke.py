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
    check(len(containers) == 3, "SHADOW_CONTAINER_COUNT")
    guard = next(c for c in containers if c["Config"]["Labels"]["com.docker.compose.service"] == "guard")
    rows = {}
    for container in containers:
        service = container["Config"]["Labels"]["com.docker.compose.service"]
        check(container["State"]["Running"], "SHADOW_CONTAINER_STOPPED")
        check(container["State"].get("Health", {}).get("Status") == "healthy", "SHADOW_NOT_READY")
        image = json.loads(shadow.docker("image", "inspect", container["Image"]))[0]
        check(image["Config"]["Labels"]["org.opencontainers.image.revision"] == shadow.sha,
              "SHADOW_IMAGE_SOURCE_MISMATCH")
        networks = container["NetworkSettings"]["Networks"]
        bindings = container["HostConfig"]["PortBindings"]
        if service == "guard":
            check(list(networks) == [f"{shadow.project}_shadow"], "SHADOW_EXTRA_NETWORK")
            check(container["HostConfig"].get("Dns") == ["127.0.0.1"], "SHADOW_EXTERNAL_DNS")
            check(len(bindings) == 2 and all(p["HostIp"] == "127.0.0.1"
                  for ports in bindings.values() for p in ports), "SHADOW_PUBLIC_BINDING")
        else:
            check(container["HostConfig"]["NetworkMode"] == "container:" + guard["Id"]
                  and not networks and not bindings, "SHADOW_NAMESPACE_NOT_GUARDED")
            check(container["Config"]["User"] not in ("", "root", "0", "0:0"), "SHADOW_ROOT_USER")
            check(not container["HostConfig"].get("CapAdd"), "SHADOW_APP_CAPABILITIES")
        check(container["HostConfig"]["CapDrop"] == ["ALL"], "SHADOW_CAPABILITIES")
        check(not container["HostConfig"]["Privileged"], "SHADOW_PRIVILEGED")
        pid_status = shadow.docker("exec", "--user", "101:101" if service == "web" else "10001:10001",
                                   container["Id"], "cat", "/proc/1/status")
        ids = next(row for row in pid_status.splitlines() if row.startswith("Uid:")).split()[1:]
        check(all(value != "0" for value in ids) and "CapEff:\t0000000000000000" in pid_status
              and "NoNewPrivs:\t1" in pid_status, "SHADOW_PROCESS_PRIVILEGES")
        namespace = exec_json(shadow, container["Id"], """
import json
from pathlib import Path
status = Path('/proc/1/status').read_text()
print(json.dumps({'defaultRoutePresent':any(r.split()[1]=='00000000' for r in Path('/proc/net/route').read_text().splitlines()[1:]),
                  'nonroot':next(r for r in status.splitlines() if r.startswith('Uid:')).split()[1]!='0',
                  'capabilitiesZero':'CapEff:\\t0000000000000000' in status,
                  'ipv6Disabled':Path('/proc/sys/net/ipv6/conf/all/disable_ipv6').read_text().strip()=='1'}))
""") if service != "web" else exec_json(shadow, guard["Id"], """
import json
from pathlib import Path
print(json.dumps({'defaultRoutePresent':any(r.split()[1]=='00000000' for r in Path('/proc/net/route').read_text().splitlines()[1:])}))
""")
        check(all(namespace.values()), "SHADOW_NAMESPACE_BOUNDARY_FAILED")
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
                         "dnsForwarders": container["HostConfig"].get("Dns") or [],
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
marker = __MARKER__
path = Path('/home/izo/media/_shadow_topology_probe.txt')
probe = sqlite3.connect('/home/izo/data/shadow-topology-probe.sqlite3')
if __CREATE__:
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
""".replace("__MARKER__", repr(marker)).replace("__CREATE__", repr(create))
    state = exec_json(shadow, container, script)
    check(state["fixtureRow"] == marker and state["mediaHash"] == hashlib.sha256(marker.encode()).hexdigest(),
          "SHADOW_PERSISTENCE_FAILED")
    check(state["applicationIntegrity"] == "ok", "SHADOW_SQLITE_INTEGRITY_FAILED")
    return state


def kernel_policy(shadow, guard: str) -> dict:
    return json.loads(shadow.docker("exec", guard, "python", "/network_guard.py", "--check"))


def egress_proof(shadow, container: str) -> dict:
    containers = shadow.containers()
    guard = next(c for c in containers if c["Config"]["Labels"]["com.docker.compose.service"] == "guard")
    network = next(iter(guard["NetworkSettings"]["Networks"]))
    info = json.loads(shadow.docker("network", "inspect", network))[0]
    gateway = info["IPAM"]["Config"][0]["Gateway"]
    kernel_policy(shadow, guard["Id"])
    # No host namespace or host listener is created. This peer is exclusively
    # owned, has no mounts/ports/capabilities and listens only on the shadow bridge.
    name = shadow.project + "-egress-proof"
    check(not shadow.docker("ps", "-aq", "--filter", "name=^/" + name + "$"),
          "SHADOW_PROBE_NAME_COLLISION")
    peer = None
    listener = "import socket; s=socket.socket(); s.bind(('0.0.0.0',45678)); s.listen(); exec('while True:\n c,a=s.accept(); c.sendall(b\"shadow-fixture\"); c.close()')"
    result = {"gateway": gateway, "controlledGatewayProbe": "GATEWAY_LISTENER_PROOF_BLOCKED",
              "gatewayListenerLimitation": "Docker bridge gateway belongs to the host VM. A real listener there requires forbidden host networking; bridge-peer listener and exact kernel DROP counters are verified instead.",
              "probes": {}}
    try:
        peer = shadow.docker("run", "-d", "--rm", "--name", name, "--network", network,
                             "--label", "io.izo.owner=SHADOW-TOPOLOGY-01",
                             "--label", "io.izo.project=" + shadow.project,
                             "--user", "10001:10001", "--read-only", "--cap-drop", "ALL",
                             "--security-opt", "no-new-privileges:true", "--memory", "64m",
                             "--pids-limit", "16", guard["Image"], "python", "-c", listener)
        peer_info = json.loads(shadow.docker("inspect", peer))[0]
        address = peer_info["NetworkSettings"]["Networks"][network]["IPAddress"]
        # A separate, unfiltered test client on the SAME bridge must reach it.
        control = "import socket,time; time.sleep(.2); s=socket.create_connection((" + repr(address) + ",45678),2); assert s.recv(64)==b'shadow-fixture'; print('LISTENER_REACHABLE'); s.close()"
        positive = shadow.docker("run", "--rm", "--network", network,
                                 "--label", "io.izo.owner=SHADOW-TOPOLOGY-01",
                                 "--user", "10001:10001", "--read-only", "--cap-drop", "ALL",
                                 "--security-opt", "no-new-privileges:true", "--memory", "64m",
                                 "--pids-limit", "16", guard["Image"], "python", "-c", control)
        check(positive == "LISTENER_REACHABLE", "SHADOW_CONTROL_LISTENER_NOT_READY")
        result["controlledBridgeListener"] = {"ip": address, "positiveControl": "PASS"}
        for label, host, port in (("gateway", gateway, 65432), ("bridgePeer", address, 45678),
                                  ("external", "1.1.1.1", 443)):
            before = kernel_policy(shadow, guard["Id"])["blockedPackets"]
            script = """
import json,socket
s=socket.socket(); s.settimeout(.7)
try:
    s.connect((__HOST__, __PORT__))
    result={'connected':True,'errno':0,'timeout':False}
except OSError as e:
    result={'connected':False,'errno':e.errno,'timeout':isinstance(e,TimeoutError)}
finally:s.close()
print(json.dumps(result))
""".replace("__HOST__", repr(host)).replace("__PORT__", str(port))
            probe = exec_json(shadow, container, script)
            after = kernel_policy(shadow, guard["Id"])["blockedPackets"]
            probe.update(ip=host, port=port, blockedPacketDelta=after-before)
            # ECONNREFUSED, DNS failure and lack of a route are never evidence
            # of filtering: require timeout AND packets counted by exact policy.
            check(not probe["connected"] and probe["timeout"] and after > before,
                  "SHADOW_EGRESS_NOT_BLOCKED_BY_POLICY")
            result["probes"][label] = probe
        result["kernelPolicy"] = kernel_policy(shadow, guard["Id"])
        result["status"] = "KERNEL_AND_BRIDGE_VERIFIED_GATEWAY_LISTENER_BLOCKED"
        return result
    finally:
        if peer:
            item = json.loads(shadow.docker("inspect", peer))[0]
            labels = item["Config"]["Labels"]
            check(labels.get("io.izo.owner") == "SHADOW-TOPOLOGY-01" and
                  labels.get("io.izo.project") == shadow.project, "SHADOW_FOREIGN_PROBE")
            shadow.docker("rm", "-f", peer)


def prove(shadow, receipt: Path) -> None:
    result = {"contract": "SHADOW-TOPOLOGY-01", "repository": "spikeal8-maker/IZO_ASA",
              "sourceSha": shadow.sha, "project": shadow.project, "startedAt": now(),
              "status": "FAIL", "cycles": [],
              "limitations": ["Topology smoke only; Issue 125 product parity/recovery remains unaccepted.",
                              "Provider calls disabled; model output and real-provider behavior not verified.",
                              "Fixture DB/media persistence and read-only app integrity, not user-flow persistence.",
                              "Backend remains the accepted unmanaged DEV runtime; image labels bind its source."]}
    production_before = None
    try:
        shadow.source_guard()
        from tools.docker_shadow_evidence import snapshot, compare
        production_before = snapshot(shadow)
        result["productionBefore"] = production_before
        shadow.up(build=True)
        config = shadow.config()
        result["configSha256"] = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
        result["containersBefore"] = inspect_stack(shadow)
        result["http"] = http_proof(shadow)
        backend = result["containersBefore"]["backend"]["container"]
        result["egress"] = egress_proof(shadow, backend)
        marker = "shadow-" + uuid.uuid4().hex
        before = fixture(shadow, backend, marker, create=True)
        result["persistenceBefore"] = before
        for cycle in range(1):
            # Review repair: one controlled up -> smoke -> recreate -> smoke.
            # The original two down/build/up receipts remain historical evidence.
            shadow.up(build=False, recreate=True)
            current = inspect_stack(shadow)
            state = fixture(shadow, current["backend"]["container"], marker, create=False)
            check(state == before, "SHADOW_APPLICATION_COUNTS_CHANGED")
            result["cycles"].append({"cycle": cycle + 1, "status": "PASS", "state": state,
                                      "containers": current, "http": http_proof(shadow),
                                      "egress": egress_proof(shadow, current["backend"]["container"])})
        result["resources"] = shadow.docker("stats", "--no-stream", "--format", "{{json .}}",
                                               *[row["container"] for row in current.values()])
        result["cleanup"] = "Shadow left running for owner inspection; named fixture volumes retained."
        result["status"] = "GATEWAY_LISTENER_PROOF_BLOCKED"
    except Exception as exc:
        result["error"] = type(exc).__name__ + ": " + str(exc)
        raise
    finally:
        if production_before is not None:
            try:
                result["productionAfter"] = snapshot(shadow)
                result["productionComparison"] = compare(production_before, result["productionAfter"])
                if result["productionComparison"]["status"] != "PROVEN":
                    result["status"] = "FAIL"
            except Exception as error:
                result["productionEvidenceError"] = type(error).__name__
                result["status"] = "FAIL"
        result["finishedAt"] = now()
        receipt.parent.mkdir(parents=True, exist_ok=True)
        receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"SHADOW_RECEIPT status={result['status']} path={receipt}")
        check(result["status"] == "PASS", result["status"])
