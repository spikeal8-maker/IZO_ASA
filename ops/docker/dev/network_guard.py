"""Prepare one private Docker network namespace, then permanently drop root.

Docker Desktop does not publish ports on an internal bridge. Removing the
default route in a dedicated shared namespace keeps its directly connected
Docker ingress while preventing connections outside the project subnet.
Only this initializer receives NET_ADMIN; application processes never do.
"""
from __future__ import annotations

import ctypes
import fcntl
import os
import socket
import struct
import time
from pathlib import Path


class Sockaddr(ctypes.Structure):
    _fields_ = [("family", ctypes.c_ushort), ("data", ctypes.c_char * 14)]


class Route(ctypes.Structure):
    # Linux UAPI struct rtentry (linux/route.h), including native alignment.
    _fields_ = [("pad1", ctypes.c_ulong), ("destination", Sockaddr),
                ("gateway", Sockaddr), ("netmask", Sockaddr),
                ("flags", ctypes.c_ushort), ("pad2", ctypes.c_short),
                ("pad3", ctypes.c_ulong), ("pad4", ctypes.c_void_p),
                ("metric", ctypes.c_short), ("device", ctypes.c_char_p),
                ("mtu", ctypes.c_ulong), ("window", ctypes.c_ulong),
                ("irtt", ctypes.c_ushort)]


def default_routes() -> list[list[str]]:
    return [line.split() for line in Path("/proc/net/route").read_text().splitlines()[1:]
            if line.split()[1] == "00000000"]


def main() -> None:
    ready = Path("/tmp/shadow-network-ready")
    ready.unlink(missing_ok=True)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as control:
        for row in default_routes():
            route = Route()
            route.destination.family = route.gateway.family = route.netmask.family = socket.AF_INET
            route.gateway.data = b"\0\0" + struct.pack("<I", int(row[2], 16)) + b"\0" * 8
            route.flags = int(row[3], 16)
            route.device = row[0].encode("ascii")
            fcntl.ioctl(control.fileno(), 0x890C, bytes(route))  # SIOCDELRT
    if default_routes():
        raise RuntimeError("SHADOW_DEFAULT_ROUTE_REMAINS")
    # Drop all real/effective/saved root IDs; Linux clears permitted/effective
    # capabilities on this transition. no-new-privileges forbids regaining them.
    os.setgroups([])
    os.setgid(10001)
    os.setuid(10001)
    status = Path("/proc/self/status").read_text()
    if "CapEff:\t0000000000000000" not in status or os.getuid() == 0:
        raise RuntimeError("SHADOW_PRIVILEGE_DROP_FAILED")
    ready.write_text("NO_DEFAULT_ROUTE_NONROOT")
    print("SHADOW_NETWORK_READY uid=10001 capabilities=0 defaultRoutes=0", flush=True)
    while True:
        time.sleep(60)


if __name__ == "__main__":
    main()
