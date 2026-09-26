from __future__ import annotations

import ipaddress
import json
import os
import socket
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import pytest


TELEMETRY_ENV = "IZO_TEST_HEALTH_TELEMETRY"


class OutboundNetworkBlocked(OSError):
    pass


def _safe_host(value: Any) -> str:
    if value is None:
        return "<NONE>"
    if isinstance(value, bytes):
        return value.decode("ascii", "replace").lower()
    return str(value).strip().lower()


def classify_host(value: Any) -> str:
    host = _safe_host(value)
    if host in {"<none>", "", "localhost"}:
        return "loopback"
    candidate = host.strip("[]").split("%", 1)[0]
    try:
        address = ipaddress.ip_address(candidate)
    except ValueError:
        return "external"
    return "loopback" if address.is_loopback else "external"


def _address_parts(address: Any, family: int | None = None) -> tuple[str, int | None, str]:
    if getattr(socket, "AF_UNIX", None) is not None and family == socket.AF_UNIX:
        return "<LOCAL_IPC>", None, "local_ipc"
    if isinstance(address, tuple) and address:
        host = _safe_host(address[0])
        port = address[1] if len(address) > 1 and isinstance(address[1], int) else None
        return host, port, classify_host(host)
    host = _safe_host(address)
    return host, None, classify_host(host)


@dataclass
class TelemetryState:
    active_nodeid: str = "<SESSION>"
    attempts: list[dict[str, Any]] = field(default_factory=list)
    rerun_nodeids: list[str] = field(default_factory=list)
    loaded_retry_plugins: list[str] = field(default_factory=list)

    def record_network(
        self,
        operation: str,
        host: str,
        port: int | None,
        classification: str,
        blocked: bool,
    ) -> None:
        self.attempts.append(
            {
                "testNodeid": self.active_nodeid or "<SESSION>",
                "operation": operation,
                "host": host,
                "port": port,
                "classification": classification,
                "blocked": blocked,
            }
        )

    def check(
        self,
        operation: str,
        address: Any,
        *,
        family: int | None = None,
        port: int | None = None,
    ) -> None:
        if port is not None:
            host = _safe_host(address)
            classification = classify_host(host)
        else:
            host, port, classification = _address_parts(address, family)
        blocked = classification == "external"
        self.record_network(operation, host, port, classification, blocked)
        if blocked:
            raise OutboundNetworkBlocked(
                f"TEST_HEALTH_EXTERNAL_NETWORK_BLOCKED operation={operation} host={host} port={port}"
            )

    def payload(self) -> dict[str, Any]:
        blocked = [item for item in self.attempts if item["blocked"]]
        reruns = list(dict.fromkeys(self.rerun_nodeids))
        return {
            "schemaVersion": 1,
            "network": {
                "status": "AVAILABLE",
                "blockedExternalAttempts": len(blocked),
                "attempts": self.attempts,
            },
            "retry": {
                "observability": "AVAILABLE",
                "rerunReports": len(self.rerun_nodeids),
                "rerunNodeids": reruns,
                "loadedRetryPlugins": sorted(set(self.loaded_retry_plugins)),
                "flakyStatus": (
                    "NO_PYTEST_RERUN_EVENTS_OBSERVED"
                    if not self.rerun_nodeids
                    else "PYTEST_RERUN_EVENTS_OBSERVED"
                ),
                "repeatRunNondeterminism": "NOT_MEASURED",
            },
        }


class NetworkGuard:
    def __init__(self, state: TelemetryState) -> None:
        self.state = state
        self._original_getaddrinfo: Callable[..., Any] | None = None
        self._original_create_connection: Callable[..., Any] | None = None
        self._original_connect: Callable[..., Any] | None = None
        self._original_connect_ex: Callable[..., Any] | None = None

    def install(self) -> None:
        if self._original_getaddrinfo is not None:
            return
        self._original_getaddrinfo = socket.getaddrinfo
        self._original_create_connection = socket.create_connection
        self._original_connect = socket.socket.connect
        self._original_connect_ex = socket.socket.connect_ex

        def getaddrinfo(host: Any, port: Any, *args: Any, **kwargs: Any) -> Any:
            safe_port = port if isinstance(port, int) else None
            self.state.check("getaddrinfo", host, port=safe_port)
            return self._original_getaddrinfo(host, port, *args, **kwargs)

        def create_connection(address: Any, *args: Any, **kwargs: Any) -> Any:
            self.state.check("create_connection", address)
            return self._original_create_connection(address, *args, **kwargs)

        def connect(sock: socket.socket, address: Any) -> Any:
            self.state.check("socket.connect", address, family=sock.family)
            return self._original_connect(sock, address)

        def connect_ex(sock: socket.socket, address: Any) -> Any:
            self.state.check("socket.connect_ex", address, family=sock.family)
            return self._original_connect_ex(sock, address)

        socket.getaddrinfo = getaddrinfo
        socket.create_connection = create_connection
        socket.socket.connect = connect
        socket.socket.connect_ex = connect_ex

    def uninstall(self) -> None:
        if self._original_getaddrinfo is None:
            return
        socket.getaddrinfo = self._original_getaddrinfo
        socket.create_connection = self._original_create_connection
        socket.socket.connect = self._original_connect
        socket.socket.connect_ex = self._original_connect_ex
        self._original_getaddrinfo = None


_STATE: TelemetryState | None = None
_GUARD: NetworkGuard | None = None
_OUTPUT: Path | None = None


def _write() -> None:
    if _STATE is None or _OUTPUT is None:
        return
    _OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    _OUTPUT.write_text(json.dumps(_STATE.payload(), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _retry_plugins(config: pytest.Config) -> list[str]:
    names: set[str] = set()
    for name, _plugin in config.pluginmanager.list_name_plugin():
        lower = str(name).lower()
        if any(token in lower for token in ("rerun", "retry", "flaky")):
            names.add(str(name))
    try:
        for _plugin, dist in config.pluginmanager.list_plugin_distinfo():
            project = str(getattr(dist, "project_name", "") or getattr(dist, "name", ""))
            lower = project.lower()
            if any(token in lower for token in ("rerun", "retry", "flaky")):
                names.add(project)
    except Exception:
        pass
    return sorted(names)


def pytest_configure(config: pytest.Config) -> None:
    global _STATE, _GUARD, _OUTPUT
    output = os.environ.get(TELEMETRY_ENV, "").strip()
    if not output:
        raise pytest.UsageError(f"{TELEMETRY_ENV} is required when test-health plugin is loaded")
    _OUTPUT = Path(output)
    _STATE = TelemetryState(loaded_retry_plugins=_retry_plugins(config))
    _GUARD = NetworkGuard(_STATE)
    _GUARD.install()
    _write()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item: pytest.Item, nextitem: pytest.Item | None):
    if _STATE is not None:
        _STATE.active_nodeid = item.nodeid
    try:
        yield
    finally:
        if _STATE is not None:
            _STATE.active_nodeid = "<SESSION>"


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    if _STATE is not None and report.outcome == "rerun":
        _STATE.rerun_nodeids.append(report.nodeid)
        _write()


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    _write()


def pytest_unconfigure(config: pytest.Config) -> None:
    global _GUARD
    _write()
    if _GUARD is not None:
        _GUARD.uninstall()
        _GUARD = None
