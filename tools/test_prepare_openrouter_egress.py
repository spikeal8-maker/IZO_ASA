"""Preparation is source-pinned, TLS-only, immutable and expires for activation."""
import copy
import json
import ssl
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools import prepare_openrouter_egress as prepare
from tools.docker_test_bundle_format import BundleError, file_hash

NOW = datetime(2026, 11, 8, 13, 0, tzinfo=timezone.utc)
SOURCE, HELPER, MANIFEST = "a" * 40, "b" * 64, "c" * 64
RELEASE = SOURCE[:12] + "-20261108120000"


def receipt(now=NOW, addresses=None):
    return prepare.prepare({"source_sha": SOURCE, "tooling_sha": SOURCE, "release_id": RELEASE},
        manifest_sha256=MANIFEST, helper_sha256=HELPER, resolver=lambda: addresses or ["8.8.8.8", "104.18.2.47"],
        tls_verifier=lambda address: {"ipv4": address, "tls_version": "TLSv1.3", "certificate_verified": True},
        clock=lambda: now)


def validate(value, **changes):
    return prepare.validate_receipt(value, **({"source_sha": SOURCE, "expected_helper_sha256": HELPER,
        "now_utc": NOW, "manifest_sha256": MANIFEST, "release_id": RELEASE} | changes))


def test_receipt_binds_every_resolved_address_to_tls_and_exact_candidate():
    result = receipt()
    assert validate(result) == ["8.8.8.8", "104.18.2.47"]
    assert result["http_requests_sent"] == 0 and result["max_activation_age_seconds"] == 3600
    assert not any("ttl" in key.lower() or "key" in key.lower() for key in result)


@pytest.mark.parametrize("field,value", [
    ("source_sha", "d" * 40), ("tooling_sha", "d" * 40), ("prepare_helper_sha256", "d" * 64),
    ("manifest_sha256", "d" * 64), ("release_id", SOURCE[:12] + "-20261108110000"),
    ("host", "foreign.invalid"), ("port", 80), ("port", True), ("format", 1.0),
    ("http_requests_sent", 1), ("max_activation_age_seconds", 999999),
    ("ipv4s", ["127.0.0.1"]), ("ipv4s", ["8.8.8.8", "8.8.8.8"]),
    ("tls_checks", []), ("observed_at_utc", "2026-11-08T13:00:00+00:00"),
])
def test_receipt_policy_identity_and_proof_drift_are_rejected(field, value):
    data = receipt(); data[field] = value
    with pytest.raises(BundleError): validate(data)


@pytest.mark.parametrize("offset", [-1, 3601])
def test_future_and_expired_preparation_cannot_activate(offset):
    with pytest.raises(BundleError, match="OPENROUTER_PREPARATION_STALE"):
        validate(receipt(), now_utc=NOW + timedelta(seconds=offset))


def test_receipt_allows_boundary_freshness_but_not_unknown_proof_fields():
    assert validate(receipt(), now_utc=NOW + timedelta(seconds=3600))
    data = receipt(); data["network_override"] = "all"
    with pytest.raises(BundleError, match="SHAPE"):
        validate(data)
    data = receipt(); data["tls_checks"][0]["certificate_verified"] = False
    with pytest.raises(BundleError, match="TLS_PROOF"):
        validate(data)


@pytest.mark.parametrize("addresses", [["169.254.169.254"], ["192.168.1.112"], ["100.64.1.1"],
    ["224.0.0.1"], ["192.0.0.9"], ["203.0.113.1"], ["::1"], ["openrouter.ai"],
    ["104.18.2.47", "8.8.8.8"], ["8.8.8.8"] * 9])
def test_resolver_cannot_grant_private_noncanonical_or_unbounded_addresses(addresses):
    called = []
    with pytest.raises(BundleError):
        prepare.prepare({"source_sha": SOURCE}, manifest_sha256=MANIFEST, helper_sha256=HELPER,
            resolver=lambda: addresses, tls_verifier=lambda value: called.append(value))
    assert called == []


def test_dns_is_bounded_fixed_host_ipv4_only_and_no_environment_derived_host(monkeypatch):
    calls = []
    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout='["104.18.2.47", "8.8.8.8"]', stderr="")
    monkeypatch.setattr(prepare.subprocess, "run", run)
    monkeypatch.setenv("HTTPS_PROXY", "http://invalid-proxy.invalid")
    assert prepare.resolve_ipv4s() == ["8.8.8.8", "104.18.2.47"]
    command, options = calls[0]
    assert command[1:3] == ["-I", "-c"] and "'openrouter.ai',443,socket.AF_INET" in command[3]
    assert options["timeout"] == 15 and options["capture_output"] is True


def test_tls_probe_verifies_fixed_sni_without_sending_http(monkeypatch):
    events = []
    class Raw:
        def settimeout(self, value): assert value == 5
        def connect(self, target): events.append(target)
        def close(self): pass
        def send(self, *args): pytest.fail("unexpected application bytes")
        sendall = send
    class TLS:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def version(self): return "TLSv1.3"
        def selected_alpn_protocol(self): return "http/1.1"
    def wrap(context, sock, server_hostname):
        assert context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
        assert context.minimum_version >= ssl.TLSVersion.TLSv1_2 and server_hostname == "openrouter.ai"
        return TLS()
    monkeypatch.setattr(prepare.socket, "socket", lambda family, kind: Raw())
    monkeypatch.setattr(ssl.SSLContext, "wrap_socket", wrap)
    result = prepare.verify_tls("8.8.8.8")
    assert events == [("8.8.8.8", 443)]
    assert result == {"ipv4": "8.8.8.8", "tls_version": "TLSv1.3", "certificate_verified": True}


def test_receipt_publication_is_exclusive_and_never_overwrites_prior_evidence(tmp_path):
    path = tmp_path / "prepared.json"
    data = receipt(); original = copy.deepcopy(data)
    prepare.write_receipt(path, data)
    raw = path.read_bytes()
    assert json.loads(raw) == data == original
    with pytest.raises(FileExistsError): prepare.write_receipt(path, data | {"host": "changed"})
    assert path.read_bytes() == raw


def test_cli_requires_exact_own_helper_before_any_dns_or_tls(tmp_path, monkeypatch, capsys):
    called = []
    monkeypatch.setattr(prepare, "prepare", lambda *a, **k: called.append("called"))
    args = ["--bundle", str(tmp_path), "--output", str(tmp_path / "evidence.json"),
        "--manifest-sha256", MANIFEST, "--expect-source", SOURCE, "--helper-sha256", "0" * 64,
        "--accept-openrouter-egress"]
    assert prepare.main(args) == 2
    assert json.loads(capsys.readouterr().out)["reason"] == "OPENROUTER_PREPARE_HELPER_PIN_MISMATCH"
    assert called == [] and not (tmp_path / "evidence.json").exists()
