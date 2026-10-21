"""Canonical scope enforcement and redacted secret checks on an exact CI checkout.

This wrapper installs only the existing reviewed Gitleaks version in disposable
Linux runner storage. It never changes package scope, Git state or application data.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import secrets
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

from tools.supply_chain_floor import classify_secret_scan, evaluate_secret_policy

ROOT = Path(__file__).resolve().parents[1]
SHA = re.compile(r"^[0-9a-f]{40}$")
SCANNER_VERSION = "8.30.1"
SCANNER_URL = "https://github.com/gitleaks/gitleaks/releases/download/v8.30.1/gitleaks_8.30.1_linux_x64.tar.gz"
SCANNER_SHA256 = "551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb"
MAX_DOWNLOAD = 16 * 1024 * 1024
MAX_BINARY = 32 * 1024 * 1024


class GateError(RuntimeError):
    """Only stable error codes leave this wrapper, never raw subprocess output."""


def command(argv: list[str], *, cwd: Path, timeout: int = 60) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(argv, cwd=cwd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GateError("COMMAND_UNAVAILABLE") from exc


def git(repo: Path, *args: str) -> str:
    result = command(["git", "-C", str(repo), *args], cwd=repo)
    if result.returncode:
        raise GateError("GIT_EVIDENCE_FAILED")
    return result.stdout.strip()


def verify_checkout(repo: Path, base: str, head: str) -> None:
    if not SHA.fullmatch(base) or not SHA.fullmatch(head):
        raise GateError("EXACT_SHA_REQUIRED")
    if Path(git(repo, "rev-parse", "--show-toplevel")).resolve() != repo.resolve():
        raise GateError("REPOSITORY_ROOT_MISMATCH")
    origin = git(repo, "remote", "get-url", "origin")
    if origin not in {"https://github.com/spikeal8-maker/IZO_ASA.git",
                      "https://github.com/spikeal8-maker/IZO_ASA",
                      "git@github.com:spikeal8-maker/IZO_ASA.git"}:
        raise GateError("REPOSITORY_IDENTITY_MISMATCH")
    git(repo, "cat-file", "-e", base + "^{commit}")
    git(repo, "cat-file", "-e", head + "^{commit}")
    if git(repo, "rev-parse", "HEAD") != head:
        raise GateError("CHECKOUT_SHA_MISMATCH")
    git(repo, "merge-base", "--is-ancestor", base, head)
    if git(repo, "status", "--porcelain", "--untracked-files=all"):
        raise GateError("CHECKOUT_NOT_CLEAN")


def run_scope(repo: Path, base: str, head: str | None = None) -> dict:
    expected_head = head if head is not None else git(repo, "rev-parse", "HEAD")
    result = command([sys.executable, "-m", "tools.agent_system.enforce",
                      "--repo-root", str(repo), "ci", "--target-base", base],
                     cwd=ROOT, timeout=120)
    lines = (result.stdout + "\n" + result.stderr).splitlines()
    records = [line.split(" ", 1) for line in lines
               if line.startswith(("ENFORCE_OK ", "ENFORCE_FAIL "))]
    if len(records) != 1:
        raise GateError("CANONICAL_SCOPE_RECEIPT_MISSING")
    try:
        prefix, raw = records[0]
        receipt = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise GateError("CANONICAL_SCOPE_RECEIPT_INVALID") from exc
    if not isinstance(receipt, dict):
        raise GateError("CANONICAL_SCOPE_RECEIPT_INVALID")
    if result.returncode == 0:
        if (prefix != "ENFORCE_OK" or receipt.get("mode") != "ci"
                or not isinstance(receipt.get("packageId"), str) or not receipt["packageId"].strip()
                or receipt.get("baseSha") != base or receipt.get("headSha") != expected_head
                or not isinstance(receipt.get("findings"), list) or receipt["findings"]):
            raise GateError("CANONICAL_SCOPE_RECEIPT_INVALID")
    elif prefix != "ENFORCE_FAIL":
        raise GateError("CANONICAL_SCOPE_RECEIPT_INVALID")
    return {"status": "PASS" if result.returncode == 0 else "FAIL",
            "exitCode": result.returncode, "receipt": receipt}


def install_scanner(folder: Path) -> Path:
    if platform.system() != "Linux" or platform.machine().lower() not in {"x86_64", "amd64"}:
        raise GateError("SCANNER_REQUIRES_LINUX_X64")
    archive = folder / "gitleaks.tar.gz"
    try:
        request = urllib.request.Request(SCANNER_URL, headers={"User-Agent": "IZO-ASA-portable-CI"})
        with urllib.request.urlopen(request, timeout=30) as response:
            data = response.read(MAX_DOWNLOAD + 1)
    except (OSError, ValueError) as exc:
        raise GateError("SCANNER_DOWNLOAD_UNAVAILABLE") from exc
    if len(data) > MAX_DOWNLOAD or hashlib.sha256(data).hexdigest() != SCANNER_SHA256:
        raise GateError("SCANNER_ARCHIVE_HASH_MISMATCH")
    archive.write_bytes(data)
    binary = folder / "gitleaks"
    try:
        with tarfile.open(archive, "r:gz") as bundle:
            member = bundle.getmember("gitleaks")
            if not member.isfile() or not 0 < member.size <= MAX_BINARY:
                raise GateError("SCANNER_ARCHIVE_INVALID")
            stream = bundle.extractfile(member)
            if stream is None:
                raise GateError("SCANNER_ARCHIVE_INVALID")
            with stream:
                binary.write_bytes(stream.read(MAX_BINARY + 1))
        binary.chmod(0o700)
    except (OSError, tarfile.TarError, KeyError) as exc:
        raise GateError("SCANNER_ARCHIVE_INVALID") from exc
    version = command([str(binary), "--version"], cwd=folder)
    if version.returncode or not re.search(r"\b8\.30\.1\b", version.stdout):
        raise GateError("SCANNER_VERSION_MISMATCH")
    return binary


def normalized_secret(raw: str, exit_code: int) -> dict:
    # The maintained normalizer strips Match/Secret and raw scanner diagnostics.
    report = classify_secret_scan(raw, scanner_exit_code=exit_code)
    if report.get("status") == "AVAILABLE":
        if (exit_code == 0 and report.get("findings")) or (exit_code == 23 and not report.get("findings")):
            raise GateError("SCANNER_RESULT_INCONSISTENT")
    return report


def run_secrets(repo: Path, base: str, head: str, folder: Path) -> dict:
    binary = install_scanner(folder)
    fixture = folder / "synthetic"
    fixture.mkdir()
    fake = "gh" + "p_" + secrets.token_hex(18)
    (fixture / "fixture.txt").write_text("token=" + fake + "\n", encoding="utf-8")
    synthetic_path = folder / "synthetic.json"
    flags = ["--redact=100", "--report-format", "json", "--exit-code", "23", "--no-banner", "--no-color"]
    synthetic = command([str(binary), "dir", str(fixture), *flags,
                         "--report-path", str(synthetic_path)], cwd=folder)
    synthetic_raw = synthetic_path.read_text(encoding="utf-8") if synthetic_path.exists() else ""
    synthetic_report = normalized_secret(synthetic_raw, synthetic.returncode)
    synthetic_ok = (synthetic.returncode == 23 and bool(synthetic_report.get("findings"))
                    and fake not in synthetic_raw + synthetic.stdout + synthetic.stderr)
    raw_path = folder / "changed-range.json"
    scan = command([str(binary), "git", str(repo), "--log-opts=" + base + ".." + head,
                    *flags, "--report-path", str(raw_path)], cwd=repo, timeout=180)
    raw = raw_path.read_text(encoding="utf-8") if raw_path.exists() else ""
    normalized = normalized_secret(raw, scan.returncode)
    policy = evaluate_secret_policy(normalized, synthetic_test="PASS" if synthetic_ok else "FAIL")
    return {"status": policy["status"], "scannerVersion": SCANNER_VERSION,
            "archiveSha256": SCANNER_SHA256, "source": SCANNER_URL,
            "range": base + ".." + head, "exitCode": scan.returncode,
            "synthetic": "PASS" if synthetic_ok else "FAIL", "scan": normalized, "policy": policy}


def execute(repo: Path, base: str, head: str) -> dict:
    result = {"repository": "spikeal8-maker/IZO_ASA", "baseSha": base, "headSha": head,
              "status": "FAIL", "scope": {"status": "NOT_RUN"}, "secrets": {"status": "NOT_RUN"},
              "workflowRun": os.environ.get("GITHUB_RUN_ID"),
              "workflowAttempt": os.environ.get("GITHUB_RUN_ATTEMPT")}
    try:
        verify_checkout(repo, base, head)
        result["scope"] = run_scope(repo, base, head)
        if result["scope"]["status"] != "PASS":
            return result
        with tempfile.TemporaryDirectory(prefix="izo-portable-gates-") as folder:
            result["secrets"] = run_secrets(repo, base, head, Path(folder))
        verify_checkout(repo, base, head)
        if result["secrets"]["status"] == "PASS":
            result["status"] = "PASS"
    except GateError as exc:
        result["error"] = str(exc)
    except (OSError, ValueError, TypeError, KeyError):
        result["error"] = "GATE_EVIDENCE_INVALID"
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    result = execute(args.repo_root.resolve(), args.base_sha, args.head_sha)
    try:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        with args.report.open("x", encoding="utf-8") as report:
            json.dump(result, report, ensure_ascii=False, indent=2, sort_keys=True)
            report.write("\n")
    except OSError:
        print("PORTABLE_GATES_REPORT_WRITE_FAILED", file=sys.stderr)
        return 2
    print("PORTABLE_GATES_" + result["status"])
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
