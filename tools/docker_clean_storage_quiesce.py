"""Paused owned-fixture source reader; Docker execution is a separate acceptance gate."""
from __future__ import annotations

import hashlib
import json
import re
import tempfile
import time
import uuid
from pathlib import Path

from tools.docker_clean_storage import MAX_ARCHIVE, StorageError, backend_id, mount_guard, require
from tools.docker_shadow import OWNER

READER_LABEL = "io.izo.storage.reader"
TARGETS = {"/home/izo/data": "sqlite-data", "/home/izo/media": "media-data"}
READ_ONLY_PROBE = """import json,sqlite3
from pathlib import Path
from contextlib import closing
db=Path('/home/izo/data/app.sqlite3')
wal,shm=Path(str(db)+'-wal'),Path(str(db)+'-shm')
with closing(sqlite3.connect(db.as_uri()+'?mode=ro',uri=True,timeout=5)) as connection:
 connection.execute('PRAGMA query_only=ON')
 mode=connection.execute('PRAGMA journal_mode').fetchone()[0]
 if mode=='wal' and not (wal.is_file() and shm.is_file()):
  raise RuntimeError('STORAGE_QUIESCE_WAL_SIDECARS_REQUIRED')
 connection.execute('SELECT count(*) FROM sqlite_master').fetchone()
 print(json.dumps({'journalMode':mode,'sqliteVersion':sqlite3.sqlite_version,
  'walPresent':wal.is_file(),'shmPresent':shm.is_file(),
  'walBytes':wal.stat().st_size if wal.is_file() else 0}))
"""


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class QuiescedSource:
    """A caller must close in finally, including when open fails after pausing.

    Only the original backend is paused. Its two named volumes remain attached;
    the one-off reader receives read-only mounts and cannot access a network.
    No source table is excluded from the caller's exact comparison window.
    """

    def __init__(self, source):
        self.source = source
        self.name = source.project + "-storage-source-reader"
        self.marker = uuid.uuid4().hex
        self.identifier = self.helper = self.image = self.identity = None
        self.volumes = self.source_name = self.environment = self.base_digest = None
        self.directory = self.override = self.overlay_bytes = None
        self.pause_attempted = self.run_attempted = False
        self.closed = self.failed = False
        self.started = None
        self.receipt = {"status": "NOT_RUN", "mode": "QUIESCED_APPLICATION",
                        "zeroDowntime": False, "sourceMounts": "NOT_VERIFIED",
                        "helperRemoved": "NOT_RUN", "sourceResumed": "NOT_RUN"}

    def _volume_identity(self):
        expected = {self.source.project + "_" + value for value in TARGETS.values()}
        rows = json.loads(self.source.docker("volume", "inspect", *sorted(expected)))
        require(isinstance(rows, list) and len(rows) == 2
                and {row["Name"] for row in rows} == expected, "STORAGE_QUIESCE_VOLUMES_INVALID")
        result = {}
        for row in rows:
            labels = row.get("Labels") or {}
            require(labels.get("io.izo.owner") == OWNER
                    and labels.get("com.docker.compose.project") == self.source.project
                    and row.get("Driver") == row.get("Scope") == "local" and not row.get("Options")
                    and isinstance(row.get("CreatedAt"), str) and bool(row["CreatedAt"]),
                    "STORAGE_QUIESCE_VOLUMES_NOT_OWNED")
            result[row["Name"]] = digest({key: row.get(key) for key in
                ("Name", "CreatedAt", "Driver", "Scope", "Options", "Labels")})
        return result

    def _guard(self, *, rollback=False):
        self.source.source_guard()
        require(self.source.executor.verify() == self.identity, "STORAGE_QUIESCE_ENGINE_CHANGED")
        require(self._volume_identity() == self.volumes, "STORAGE_QUIESCE_VOLUME_CHANGED")
        require(self.source.env == self.environment, "STORAGE_QUIESCE_ENVIRONMENT_CHANGED")
        if rollback:
            require(digest(self.source.config()) == self.base_digest, "STORAGE_QUIESCE_BASE_CONFIG_CHANGED")
        else:
            self.source.ownership_guard()
        if not rollback and self.override is not None:
            require(self.override.read_bytes() == self.overlay_bytes, "STORAGE_QUIESCE_OVERLAY_CHANGED")

    def _source_row(self, *, rollback=False):
        self._guard(rollback=rollback)
        if rollback:
            rows = json.loads(self.source.docker("inspect", self.identifier))
            require(isinstance(rows, list) and len(rows) == 1, "STORAGE_QUIESCE_SOURCE_AMBIGUOUS")
            row, labels = rows[0], rows[0]["Config"].get("Labels", {})
            require(row["Id"] == self.identifier and row["State"]["Running"]
                    and row["Config"]["User"] == "10001:10001"
                    and labels.get("io.izo.owner") == OWNER
                    and labels.get("com.docker.compose.project") == self.source.project
                    and labels.get("com.docker.compose.service") == "backend",
                    "STORAGE_QUIESCE_SOURCE_NOT_OWNED")
            require(len(row["Mounts"]) == 2 and {item["Destination"] for item in row["Mounts"]} == set(TARGETS)
                    and all(item["Type"] == "volume" and item.get("RW") is True
                            and item.get("Name") == self.source.project + "_" + TARGETS[item["Destination"]]
                            for item in row["Mounts"]), "STORAGE_QUIESCE_SOURCE_MOUNT_CHANGED")
        else:
            row = mount_guard(self.source, self.identifier)
        require(row["Image"] == self.image and row["Name"] == self.source_name,
                "STORAGE_QUIESCE_SOURCE_CHANGED")
        backends = [item for item in self.source.containers()
                    if item["Config"].get("Labels", {}).get("com.docker.compose.service") == "backend"]
        normal = {item["Id"] for item in backends
                  if item["Config"]["Labels"].get("com.docker.compose.oneoff", "").lower() != "true"}
        require(row["Config"]["Labels"].get("com.docker.compose.oneoff", "").lower() == "false"
                and normal == {self.identifier}
                and (rollback or {item["Id"] for item in backends} <= {self.identifier, self.helper}),
                "STORAGE_QUIESCE_BACKEND_CHANGED")
        return row

    def _helper_row(self, identifier, *, running=True, rollback=False):
        self._guard(rollback=rollback)
        rows = json.loads(self.source.docker("inspect", identifier))
        require(isinstance(rows, list) and len(rows) == 1, "STORAGE_QUIESCE_READER_AMBIGUOUS")
        row, labels = rows[0], rows[0]["Config"].get("Labels", {})
        host = row["HostConfig"]
        require(row["Id"] == identifier and row["Name"].lstrip("/") == self.name
                and row["Image"] == self.image and (row["State"]["Running"] or not running)
                and not row["State"].get("Paused") and row["Config"]["User"] == "10001:10001"
                and labels.get("io.izo.owner") == OWNER
                and labels.get("com.docker.compose.project") == self.source.project
                and labels.get("com.docker.compose.service") == "backend"
                and labels.get("com.docker.compose.oneoff", "").lower() == "true"
                and labels.get(READER_LABEL) == self.marker,
                "STORAGE_QUIESCE_READER_NOT_OWNED")
        require(len(row["Mounts"]) == 2 and {item["Destination"] for item in row["Mounts"]} == set(TARGETS)
                and all(item["Type"] == "volume" and item.get("RW") is False
                        and item.get("Name") == self.source.project + "_" + TARGETS[item["Destination"]]
                        for item in row["Mounts"]), "STORAGE_QUIESCE_READER_NOT_READ_ONLY")
        require(host["NetworkMode"] == "none" and not host.get("PortBindings")
                and not host.get("Privileged") and not host.get("CapAdd") and host.get("CapDrop") == ["ALL"]
                and "no-new-privileges:true" in host.get("SecurityOpt", [])
                and row["Config"].get("Healthcheck", {}).get("Test") == ["NONE"],
                "STORAGE_QUIESCE_READER_NOT_ISOLATED")
        return row

    def _named_helper(self):
        identifiers = self.source.docker("ps", "-aq", "--no-trunc", "--filter", "name=^/" + self.name + "$").split()
        require(len(identifiers) <= 1 and all(re.fullmatch(r"[0-9a-f]{64}", value) for value in identifiers),
                "STORAGE_QUIESCE_READER_AMBIGUOUS")
        return identifiers[0] if identifiers else None

    def open(self):
        try:
            return self._open()
        except Exception:
            self.failed = True
            raise StorageError("STORAGE_QUIESCE_OPEN_FAILED") from None

    def _open(self):
        require(not self.closed and self.identity is None and self.source.fixture and self.source.executor,
                "STORAGE_QUIESCE_ISOLATED_FIXTURE_REQUIRED")
        self.source.source_guard()
        self.identity = self.source.executor.verify()
        config = self.source.config()
        self.base_digest = digest(config)
        self.image = self.source.image_guard(config)["backend"]
        self.identifier = backend_id(self.source)
        row = mount_guard(self.source, self.identifier)
        require(row["Image"] == self.image and not row["State"].get("Paused")
                and not row["State"].get("Restarting"), "STORAGE_QUIESCE_SOURCE_NOT_READY")
        self.source_name, self.volumes = row["Name"], self._volume_identity()
        self.environment = dict(self.source.env)
        require(self._named_helper() is None, "STORAGE_QUIESCE_READER_NAME_COLLISION")
        backend = {"image": self.image, "pull_policy": "never", "network_mode": "none",
                   "healthcheck": {"disable": True}, "entrypoint": ["python"],
                   "command": ["-c", "import time; time.sleep(600)"], "labels": {READER_LABEL: self.marker},
                   "volumes": [{"type": "volume", "source": value, "target": key, "read_only": True}
                               for key, value in TARGETS.items()]}
        self.directory = tempfile.TemporaryDirectory(prefix="izo-storage-reader-")
        self.override = Path(self.directory.name) / "reader.json"
        self.overlay_bytes = (json.dumps({"services": {"backend": backend}}) + "\n").encode()
        self.override.write_bytes(self.overlay_bytes)
        resolved = json.loads(self.source.compose("config", "--format", "json", override=self.override))
        service = resolved["services"]["backend"]
        require(set(resolved.get("volumes", {})) == set(TARGETS.values())
                and all(service.get(key) == value for key, value in backend.items()
                        if key not in {"labels", "volumes", "healthcheck"})
                and service.get("healthcheck", {}).get("disable") is True
                and service.get("labels", {}).get(READER_LABEL) == self.marker
                and service.get("labels", {}).get("io.izo.owner") == OWNER
                and not service.get("networks") and not service.get("ports")
                and service.get("environment") == config["services"]["backend"].get("environment")
                and service.get("user") == "10001:10001" and service.get("cap_drop") == ["ALL"]
                and not service.get("cap_add") and "no-new-privileges:true" in service.get("security_opt", [])
                and len(service.get("volumes", [])) == 2
                and all(item.get("type") == "volume" and item.get("read_only") is True
                        and TARGETS.get(item.get("target")) == item.get("source")
                        for item in service["volumes"]), "STORAGE_QUIESCE_CONFIG_INVALID")
        self.receipt.update(sourceContainerId=self.identifier, sourceImageId=self.image,
                            volumeIdentities=self.volumes, baseConfigurationSha256=self.base_digest,
                            helperConfigurationSha256=digest(resolved))
        self._source_row()
        self.started, self.pause_attempted = time.monotonic(), True
        self.source.compose("pause", "backend")
        require(self._source_row()["State"].get("Paused") is True, "STORAGE_QUIESCE_PAUSE_NOT_ESTABLISHED")
        self.run_attempted = True
        self.helper = self.source.compose("run", "--no-deps", "-d", "--rm", "--name", self.name,
                                          "backend", override=self.override).strip()
        require(re.fullmatch(r"[0-9a-f]{64}", self.helper) is not None, "STORAGE_QUIESCE_READER_ID_INVALID")
        self.receipt["helperContainerId"] = self.helper
        probe = self.call(READ_ONLY_PROBE)
        require(set(probe) == {"journalMode", "sqliteVersion", "walPresent", "shmPresent", "walBytes"}
                and probe["journalMode"] in {"wal", "delete"}
                and re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", probe["sqliteVersion"])
                and type(probe["walPresent"]) is type(probe["shmPresent"]) is bool
                and type(probe["walBytes"]) is int and 0 <= probe["walBytes"] <= 64 * 1024**2
                and (probe["journalMode"] != "wal" or probe["walPresent"] and probe["shmPresent"]),
                "STORAGE_QUIESCE_SQLITE_METADATA_INVALID")
        self.receipt.update(sqliteReadOnly=probe, sourceMounts="READ_ONLY")
        self.receipt["status"] = "ACTIVE"
        return self

    def call(self, code):
        try:
            require(self.pause_attempted and self.helper and isinstance(code, str), "STORAGE_QUIESCE_NOT_OPEN")
            require(self._source_row()["State"].get("Paused") is True, "STORAGE_QUIESCE_SOURCE_NOT_PAUSED")
            self._helper_row(self.helper)
            raw = self.source.docker("exec", self.helper, "python", "-c", code, timeout=120)
            require(isinstance(raw, str) and len(raw) <= MAX_ARCHIVE * 2, "STORAGE_QUIESCE_RESPONSE_LIMIT")
            result = json.loads(raw)
            require(isinstance(result, dict), "STORAGE_QUIESCE_RESPONSE_INVALID")
            return result
        except Exception:
            self.failed = True
            raise StorageError("STORAGE_QUIESCE_READ_FAILED") from None

    def close(self):
        if self.closed:
            return self.receipt
        errors = []
        if self.run_attempted:
            try:
                self._guard(rollback=True)
                found = self._named_helper()
                if found:
                    require(self.helper in {None, found} or not re.fullmatch(r"[0-9a-f]{64}", self.helper),
                            "STORAGE_QUIESCE_READER_CHANGED")
                    self._helper_row(found, running=False, rollback=True)
                    self.helper = found
                    self.source.docker("rm", "-f", found)
                require(self._named_helper() is None, "STORAGE_QUIESCE_READER_REMAINING")
                self.helper = None
                self.receipt["helperRemoved"] = "PASS"
            except Exception:
                errors.append("STORAGE_QUIESCE_READER_CLEANUP_FAILED")
        if self.pause_attempted:
            try:
                row = self._source_row(rollback=True)
                if row["State"].get("Paused"):
                    # Compose v2.38.2 pause/unPause use oneOffExclude; the reader is never selected.
                    self.source.compose("unpause", "backend")
                require(self._source_row(rollback=True)["State"].get("Paused") is False,
                        "STORAGE_QUIESCE_SOURCE_STILL_PAUSED")
                self.receipt["sourceResumed"] = "PASS"
            except Exception:
                errors.append("STORAGE_QUIESCE_SOURCE_RESUME_FAILED")
            self.receipt["quiescedWindowSeconds"] = round(time.monotonic() - self.started, 3)
        if self.directory is not None:
            try:
                self.directory.cleanup()
            except Exception:
                errors.append("STORAGE_QUIESCE_LOCAL_CLEANUP_FAILED")
        self.receipt["status"] = "FAIL" if errors or self.failed or self.receipt["status"] != "ACTIVE" else "PASS"
        if errors:
            self.receipt["errorCodes"] = errors
        self.closed = True
        return self.receipt
