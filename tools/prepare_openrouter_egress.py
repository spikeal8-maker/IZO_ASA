"""Prepare immutable public IPv4/TLS evidence for the opt-in closed beta route."""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import socket
import ssl
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from tools.docker_test_bundle_format import (
        BundleError, HASH, RUNTIME, SHA, file_hash, json_bytes, plain_path, require, verify,
    )
except ModuleNotFoundError:
    from docker_test_bundle_format import (
        BundleError, HASH, RUNTIME, SHA, file_hash, json_bytes, plain_path, require, verify,
    )

HOST, PORT = "openrouter.ai", 443
PROFILE = "comfyui-openrouter-v1"
MAX_IPS, MAX_ACTIVATION_AGE_SECONDS = 8, 3600
RECEIPT_KEYS = {"format", "status", "profile", "host", "port", "source_sha", "tooling_sha",
                "release_id", "manifest_sha256", "prepare_helper_sha256", "observed_at_utc",
                "ipv4s", "tls_checks", "max_activation_age_seconds", "http_requests_sent"}
DNS_SCRIPT = ("import json,socket; print(json.dumps(sorted({r[4][0] for r in "
              "socket.getaddrinfo('openrouter.ai',443,socket.AF_INET,socket.SOCK_STREAM,socket.IPPROTO_TCP)})))")


def public_addresses(values):
    require(type(values) is list and 1 <= len(values) <= MAX_IPS
            and all(type(v) is str for v in values), "OPENROUTER_IPV4_SET_INVALID")
    try:
        addresses = [ipaddress.IPv4Address(v) for v in values]
    except (ValueError, TypeError):
        raise BundleError("OPENROUTER_IPV4_SET_INVALID") from None
    require(len(set(addresses)) == len(addresses)
            and all(a.is_global and not a.is_multicast and not a.is_reserved and not a.is_unspecified
                    and a not in ipaddress.IPv4Network("192.0.0.0/24") for a in addresses)
            and values == [str(a) for a in sorted(addresses)], "OPENROUTER_IPV4_SET_INVALID")
    return list(values)


def resolve_ipv4s():
    try:
        result = subprocess.run([sys.executable, "-I", "-c", DNS_SCRIPT], text=True,
                                capture_output=True, check=False, timeout=15)
        require(result.returncode == 0 and len(result.stdout) <= 2048, "OPENROUTER_DNS_FAILED")
        values = json.loads(result.stdout)
        require(type(values) is list and 1 <= len(values) <= MAX_IPS, "OPENROUTER_DNS_FAILED")
        return public_addresses(sorted(set(values), key=ipaddress.IPv4Address))
    except (OSError, ValueError, TypeError, subprocess.TimeoutExpired):
        raise BundleError("OPENROUTER_DNS_FAILED") from None


def verify_tls(address):
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.set_alpn_protocols(["http/1.1"])
    raw = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    raw.settimeout(5)
    try:
        raw.connect((address, PORT))
        with context.wrap_socket(raw, server_hostname=HOST) as secured:
            version = secured.version()
            require(version in {"TLSv1.2", "TLSv1.3"}
                    and secured.selected_alpn_protocol() in {None, "http/1.1"}, "OPENROUTER_TLS_FAILED")
        return {"ipv4": address, "tls_version": version, "certificate_verified": True}
    except OSError:
        raise BundleError("OPENROUTER_TLS_FAILED") from None
    finally:
        raw.close()


def validate_receipt(value, *, source_sha, expected_helper_sha256, now_utc,
                     manifest_sha256=None, release_id=None):
    require(type(value) is dict and set(value) == RECEIPT_KEYS, "OPENROUTER_RECEIPT_SHAPE_INVALID")
    require(SHA.fullmatch(source_sha or "") and HASH.fullmatch(expected_helper_sha256 or "")
            and value["source_sha"] == value["tooling_sha"] == source_sha
            and value["prepare_helper_sha256"] == expected_helper_sha256,
            "OPENROUTER_RECEIPT_SOURCE_MISMATCH")
    require(type(value["format"]) is int and value["format"] == 1
            and value["status"] == "OPENROUTER_EGRESS_PREPARED" and value["profile"] == PROFILE
            and value["host"] == HOST and type(value["port"]) is int and value["port"] == PORT
            and type(value["http_requests_sent"]) is int and value["http_requests_sent"] == 0
            and type(value["max_activation_age_seconds"]) is int
            and value["max_activation_age_seconds"] == MAX_ACTIVATION_AGE_SECONDS,
            "OPENROUTER_RECEIPT_POLICY_INVALID")
    require(type(value["manifest_sha256"]) is str and HASH.fullmatch(value["manifest_sha256"])
            and type(value["release_id"]) is str
            and re.fullmatch(source_sha[:12] + r"-[0-9]{14}", value["release_id"])
            and (manifest_sha256 is None or value["manifest_sha256"] == manifest_sha256)
            and (release_id is None or value["release_id"] == release_id),
            "OPENROUTER_RECEIPT_RELEASE_MISMATCH")
    addresses = public_addresses(value["ipv4s"])
    checks = value["tls_checks"]
    require(type(checks) is list and len(checks) == len(addresses)
            and all(type(item) is dict and set(item) == {"ipv4", "tls_version", "certificate_verified"}
                    and item["ipv4"] == address and item["certificate_verified"] is True
                    and item["tls_version"] in {"TLSv1.2", "TLSv1.3"}
                    for item, address in zip(checks, addresses)), "OPENROUTER_TLS_PROOF_INVALID")
    try:
        observed = datetime.strptime(value["observed_at_utc"], "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
        require(type(now_utc) is datetime and now_utc.utcoffset() is not None
                and now_utc.utcoffset().total_seconds() == 0, "OPENROUTER_RECEIPT_TIME_INVALID")
        age = (now_utc - observed).total_seconds()
        require(0 <= age <= MAX_ACTIVATION_AGE_SECONDS, "OPENROUTER_PREPARATION_STALE")
    except (ValueError, TypeError, AttributeError):
        raise BundleError("OPENROUTER_RECEIPT_TIME_INVALID") from None
    return addresses


def prepare(manifest, *, manifest_sha256, helper_sha256, resolver=resolve_ipv4s,
            tls_verifier=verify_tls, clock=lambda: datetime.now(timezone.utc)):
    addresses = public_addresses(resolver())
    checks = [tls_verifier(address) for address in addresses]
    observed = clock()
    result = {"format": 1, "status": "OPENROUTER_EGRESS_PREPARED", "profile": PROFILE,
              "host": HOST, "port": PORT, "source_sha": manifest["source_sha"],
              "tooling_sha": manifest["tooling_sha"], "release_id": manifest["release_id"],
              "manifest_sha256": manifest_sha256, "prepare_helper_sha256": helper_sha256,
              "observed_at_utc": observed.strftime("%Y-%m-%dT%H:%M:%S.%fZ"), "ipv4s": addresses,
              "tls_checks": checks, "max_activation_age_seconds": MAX_ACTIVATION_AGE_SECONDS,
              "http_requests_sent": 0}
    validate_receipt(result, source_sha=manifest["source_sha"], expected_helper_sha256=helper_sha256,
                     now_utc=observed, manifest_sha256=manifest_sha256, release_id=manifest["release_id"])
    return result


def write_receipt(path, value):
    path = plain_path(path)
    require(path.is_absolute() and path.parent.is_dir(), "OPENROUTER_RECEIPT_PATH_INVALID")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(json_bytes(value))
        stream.flush()
        os.fsync(stream.fileno())
    if os.name == "posix":
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)


def main(argv=None):
    try:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("--bundle", type=Path, required=True)
        parser.add_argument("--output", type=Path, required=True)
        for name in ("manifest-sha256", "expect-source", "helper-sha256"):
            parser.add_argument("--" + name, required=True)
        parser.add_argument("--accept-openrouter-egress", action="store_true")
        args = parser.parse_args(argv)
        require(args.accept_openrouter_egress, "OPENROUTER_EXPLICIT_ACCEPTANCE_REQUIRED")
        size, digest = file_hash(plain_path(Path(__file__)))
        require(digest == args.helper_sha256, "OPENROUTER_PREPARE_HELPER_PIN_MISMATCH")
        manifest = verify(args.bundle, args.manifest_sha256)
        require(manifest["source_sha"] == manifest["tooling_sha"] == args.expect_source
                and manifest["profile"] == RUNTIME
                and manifest["files"].get("prepare_openrouter_egress.py") == {"size": size, "sha256": digest},
                "OPENROUTER_PREPARE_SOURCE_MISMATCH")
        require(not args.output.exists(), "OPENROUTER_RECEIPT_ALREADY_EXISTS")
        result = prepare(manifest, manifest_sha256=args.manifest_sha256, helper_sha256=digest)
        write_receipt(args.output, result)
        print(json.dumps({"status": result["status"], "source_sha": args.expect_source,
                          "receipt_sha256": file_hash(args.output)[1], "ipv4_count": len(result["ipv4s"]),
                          "http_requests_sent": 0, "runtime_changed": False}, sort_keys=True))
        return 0
    except (BundleError, OSError, ValueError, TypeError, KeyError) as error:
        reason = str(error) if isinstance(error, BundleError) else "OPENROUTER_EGRESS_PREPARATION_FAILED"
        print(json.dumps({"status": "BLOCKED", "reason": reason,
                          "runtime_changed": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
