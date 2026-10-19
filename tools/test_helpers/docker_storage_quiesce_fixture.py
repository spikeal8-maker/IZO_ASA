"""Owned Docker-state fixture shared by quiesce lifecycle and cleanup tests."""
from __future__ import annotations

import copy
import json
import sqlite3
import types

from tools import docker_clean_storage_quiesce as quiesce
from tools.docker_shadow_roles import backend_targets

CID, HID, IMAGE = "a" * 64, "b" * 64, "sha256:" + "c" * 64
PROJECT = "izo-asa-shadow-quiesce-contract"
CANARY = "PRIVATE_CANARY_DO_NOT_PUBLISH"


class Source:
    def __init__(self):
        self.project, self.sha, self.fixture = PROJECT, "d" * 40, True
        self.env = {"IZO_COMPOSE_PROJECT": PROJECT, "in_memory_fixture_value": CANARY}
        self.identity = {"engineId": "owned-test-engine", "context": "fixture", "machineIdentitySha256": "e" * 64}
        self.executor = types.SimpleNamespace(verify=lambda: copy.deepcopy(self.identity))
        labels = {"io.izo.owner": quiesce.OWNER, "com.docker.compose.project": PROJECT,
                  "com.docker.compose.service": "backend", "com.docker.compose.oneoff": "False"}
        self.rows = {CID: {"Id": CID, "Name": "/" + PROJECT + "-backend-1", "Image": IMAGE,
            "Config": {"User": "10001:10001", "Labels": labels, "Healthcheck": {"Test": ["CMD", "health"]}},
            "State": {"Running": True, "Paused": False, "Restarting": False},
            "Mounts": [{"Type": "volume", "Destination": key, "Name": PROJECT + "_" + value, "RW": True}
                       for key, value in backend_targets(self).items()],
            "HostConfig": {"NetworkMode": "container:owned-guard", "CapDrop": ["ALL"],
                           "SecurityOpt": ["no-new-privileges:true"], "Privileged": False}}}
        self.volumes = {PROJECT + "_" + value: {"Name": PROJECT + "_" + value, "CreatedAt": "2026-10-17T00:00:00Z",
            "Driver": "local", "Scope": "local", "Options": None,
            "Labels": {"io.izo.owner": quiesce.OWNER, "com.docker.compose.project": PROJECT}}
            for value in backend_targets(self).values()}
        self.events, self.failure, self.bad_reader, self.bad_config = [], None, None, None
        self.payload = {"database": {"tables": {"power_samples": {"rows": 1, "digest": "f" * 64}}}}
        self.probe = {"journalMode": "wal", "sqliteVersion": sqlite3.sqlite_version,
                      "walPresent": True, "shmPresent": True, "walBytes": 4096}

    def source_guard(self):
        if self.failure == "source":
            raise RuntimeError(CANARY)

    def ownership_guard(self):
        for row in self.rows.values():
            if row["Config"]["Labels"].get("io.izo.owner") != quiesce.OWNER:
                raise RuntimeError(CANARY)

    def containers(self):
        return copy.deepcopy(list(self.rows.values()))

    def config(self):
        return {"volumes": {value: {"name": PROJECT + "_" + value} for value in backend_targets(self).values()},
            "services": {"backend": {"image": "local-fixture-tag", "network_mode": "service:guard",
                "user": "10001:10001", "cap_drop": ["ALL"], "security_opt": ["no-new-privileges:true"],
                "labels": {"io.izo.owner": quiesce.OWNER}, "environment": dict(self.env)}}}

    def image_guard(self, config):
        return {"backend": IMAGE}

    def compose(self, *args, override=None, **kwargs):
        if args[0] == "config":
            resolved = self.config()
            backend = resolved["services"]["backend"]
            text = override.read_text()
            assert text.count('"volumes": !override [') == 1
            overlay = json.loads(text.replace('"volumes": !override [', '"volumes": [', 1))["services"]["backend"]
            labels = backend["labels"] | overlay["labels"]
            backend.update(overlay)
            backend["labels"] = labels
            backend["healthcheck"]["test"] = ["CMD", "inherited-but-disabled"]
            if self.bad_config:
                self.bad_config(resolved)
            self.resolved = resolved
            return json.dumps(resolved)
        self.events.append(args[0])
        if args[0] == "pause":
            assert args == ("pause", "backend")
            self.rows[CID]["State"]["Paused"] = True
            if self.failure == "pause_after":
                raise RuntimeError(CANARY)
        elif args[0] == "unpause":
            assert args == ("unpause", "backend")
            if self.failure == "unpause":
                raise RuntimeError(CANARY)
            self.rows[CID]["State"]["Paused"] = False
        elif args[0] == "run":
            assert self.rows[CID]["State"]["Paused"] and "--no-deps" in args and "--rm" in args
            row = copy.deepcopy(self.rows[CID])
            row.update(Id=HID, Name="/" + args[args.index("--name") + 1])
            row["State"]["Paused"] = False
            row["Config"]["Labels"].update(self.resolved["services"]["backend"]["labels"])
            row["Config"]["Labels"]["com.docker.compose.oneoff"] = "True"
            row["Config"]["Healthcheck"] = {"Test": ["NONE"]}
            row["HostConfig"]["NetworkMode"] = "none"
            row["Mounts"] = [mount for mount in row["Mounts"] if mount["Destination"] in quiesce.TARGETS]
            for mount in row["Mounts"]:
                mount["RW"] = False
            if self.bad_reader:
                self.bad_reader(row)
            self.rows[HID] = row
            if self.failure == "run_after":
                raise RuntimeError(CANARY)
            return HID
        else:
            raise AssertionError(args)
        return ""

    def docker(self, *args, **kwargs):
        if args[0] == "volume":
            assert args[1] == "inspect"
            return json.dumps([self.volumes[value] for value in args[2:]])
        if args[0] == "inspect":
            return json.dumps([self.rows[value] for value in args[1:] if value in self.rows])
        if args[0] == "ps":
            target = "/" + PROJECT + "-storage-source-reader"
            return "\n".join(row["Id"] for row in self.rows.values() if row["Name"] == target)
        if args[0] == "rm":
            assert args == ("rm", "-f", HID)
            self.events.append("remove-reader")
            if self.failure == "rm":
                raise RuntimeError(CANARY)
            del self.rows[HID]
            return ""
        if args[0] == "exec":
            assert args[1:4] == (HID, "python", "-c") and kwargs.get("timeout") == 120
            self.events.append("reader-exec")
            if self.failure == "exec":
                raise RuntimeError(CANARY)
            return json.dumps(self.probe if args[4] == quiesce.READ_ONLY_PROBE else self.payload)
        raise AssertionError(args)
