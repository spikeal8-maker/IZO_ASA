"""Test-only loopback fixtures; probing does not reserve ports for a later holder."""
from __future__ import annotations

import socket
import threading
import uuid
from collections.abc import Iterable

from tools.agent_system.env import derive_candidate_ports
from tools.agent_system.package import ID_RE

LOOPBACK = "127.0.0.1"
MAX_CANDIDATES = 256
WINDOWS_DEFAULT_DYNAMIC_START = 49152


def _bound_listener(port: int) -> socket.socket:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        listener.bind((LOOPBACK, int(port)))
        listener.listen(8)
        return listener
    except BaseException:
        listener.close()
        raise


def available_package_id(
    prefix: str, *, excluded_ports: Iterable[int] = (), max_candidates: int = MAX_CANDIDATES,
) -> str:
    """Prepare one synthetic identity; never start or retry the system under test.

    A fresh namespace separates tests/workers. Both sockets stay bound during the
    pair probe, then close before return. A later holder still has a bind race.
    The low band avoids default Windows dynamic ports, not custom exclusions.
    """
    if not 1 <= max_candidates <= MAX_CANDIDATES:
        raise ValueError("invalid synthetic port candidate limit")
    if not ID_RE.fullmatch(prefix):
        raise ValueError("invalid synthetic package prefix")
    namespace = uuid.uuid4().hex[:20].upper()
    excluded = set(excluded_ports)
    for index in range(max_candidates):
        package_id = f"{prefix[:16]}-{namespace}-{index}"
        ports = derive_candidate_ports(package_id)
        pair = (ports["backend"], ports["frontend"])
        if max(pair) >= WINDOWS_DEFAULT_DYNAMIC_START or excluded.intersection(pair):
            continue
        listeners: list[socket.socket] = []
        try:
            for port in pair:
                listeners.append(_bound_listener(port))
            return package_id
        except OSError:
            continue
        finally:
            for listener in listeners:
                listener.close()
    raise RuntimeError("no available synthetic package port pair within candidate limit")


def can_bind(port: int) -> bool:
    try:
        listener = _bound_listener(port)
    except OSError:
        return False
    listener.close()
    return True


def foreign_listener(port: int):
    """Create only this test's deliberate foreign occupant, with the old protocol."""
    listener = _bound_listener(port)
    stop = threading.Event()

    def serve() -> None:
        while not stop.is_set():
            try:
                connection, _ = listener.accept()
            except (OSError, socket.timeout):
                continue
            with connection:
                try:
                    connection.recv(512)
                    connection.sendall(b"FOREIGN\n")
                except OSError:
                    pass

    thread = threading.Thread(target=serve, daemon=True)
    try:
        listener.settimeout(0.2)
        thread.start()
    except BaseException:
        listener.close()
        raise
    return listener, stop, thread


def close_listener(listener, stop, thread) -> None:
    stop.set()
    listener.close()
    thread.join(timeout=1)
